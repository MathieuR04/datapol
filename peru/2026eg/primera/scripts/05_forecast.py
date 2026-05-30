"""
05_forecast.py — Peru 2026 EG Primera Vuelta  (Bayesian Hierarchical Forecast)

For each non-Contabilizada (remaining) mesa we estimate a vote-share
distribution from the finest available geographic hierarchy level:

  polling place  →  district  →  province  →  department  →  national

Then we run N_SIM Monte Carlo simulations to project the final margin
(in absolute votes) between the 2nd- and 3rd-place candidates for the
runoff slot.

At 100% reporting there are no remaining mesas, so each simulation
returns the observed margin → P(winner) = 100%, CI = [margin, margin].

Usage:
  python3 05_forecast.py               # normal run
  python3 05_forecast.py --validate    # 50-% holdout calibration check

Output: primera/data/forecast.json
"""

import csv
import json
import math
import random
import argparse
import datetime
from pathlib import Path
from collections import defaultdict

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
DATA_DIR    = SCRIPT_DIR.parent / "data"
RESULTS     = DATA_DIR / "results"
META        = SCRIPT_DIR.parent.parent.parent / "metadata"

MESA_CSV    = RESULTS / "peru_2026eg_mesa_primera.csv"
CAND_JSON   = DATA_DIR / "candidates.json"
MESA_ROLL   = META / "peru_2026_mesa_electoral_roll.csv"
OUT_JSON    = DATA_DIR / "forecast.json"

# ── Constants ──────────────────────────────────────────────────────────────────
N_SIM        = 10_000
SEED         = 42
MIN_PEERS    = 5      # min counted mesas at a level to use it as prior
N_BINS       = 100    # histogram bins for margin distribution


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_candidates():
    with open(CAND_JSON) as f:
        return json.load(f)


def load_mesas(cand_cols: list[str]) -> list[dict]:
    """Load mesa CSV; attach parsed numeric helpers."""
    rows = []
    with open(MESA_CSV, newline="") as f:
        for row in csv.DictReader(f):
            row["_votes"]    = {col: int(row.get(col) or 0) for col in cand_cols}
            row["_emitidos"] = int(row.get("votos_emitidos")    or 0)
            row["_electores"]= int(row.get("electores_habiles") or 0)
            row["_is_C"]     = row.get("estado_acta") == "C"
            rows.append(row)
    return rows


def attach_hierarchy(mesas: list[dict], roll_lkp: dict):
    """Add _local, _prov, _dept keys derived from mesa CSV + electoral roll."""
    for m in mesas:
        rl = roll_lkp.get(m["codigo_mesa"], {})
        local_raw = (m.get("codigo_local_votacion") or "").strip()
        dist      = m.get("ubigeo_distrito", "")
        # local key: district + local code (local codes are per-district)
        m["_local"] = f"{dist}_{local_raw}" if local_raw else ""
        m["_dist"]  = dist
        m["_prov"]  = (rl.get("ubigeo_provincia") or dist[:4] or "")
        m["_dept"]  = (rl.get("ubigeo_dept")      or dist[:2] or "")


def load_roll_lkp() -> dict:
    if not MESA_ROLL.exists():
        return {}
    with open(MESA_ROLL, newline="") as f:
        return {r["codigo_mesa"]: r for r in csv.DictReader(f)}


# ═══════════════════════════════════════════════════════════════════════════════
# Hierarchy statistics
# ═══════════════════════════════════════════════════════════════════════════════

def compute_level_stats(counted: list[dict], key_fn, cand_cols: list[str]) -> dict:
    """
    For each group keyed by key_fn(mesa), compute:
      n, mean_shares{col→float}, std_shares{col→float},
      mean_turnout, std_turnout
    share_c = votes_c / votos_emitidos  (fraction of all cast ballots)
    """
    groups: dict[str, list] = defaultdict(list)
    for m in counted:
        k = key_fn(m)
        if not k or m["_emitidos"] == 0:
            continue
        shares  = {col: m["_votes"][col] / m["_emitidos"] for col in cand_cols}
        turnout = m["_emitidos"] / m["_electores"] if m["_electores"] > 0 else None
        groups[k].append((shares, turnout))

    stats = {}
    for k, items in groups.items():
        n = len(items)
        mean_s = {col: sum(it[0][col] for it in items) / n for col in cand_cols}
        if n > 1:
            std_s = {col: math.sqrt(
                sum((it[0][col] - mean_s[col]) ** 2 for it in items) / (n - 1)
            ) for col in cand_cols}
        else:
            std_s = {col: 0.0 for col in cand_cols}

        to_vals = [it[1] for it in items if it[1] is not None]
        mean_to = sum(to_vals) / len(to_vals) if to_vals else 0.7
        std_to  = (
            math.sqrt(sum((x - mean_to) ** 2 for x in to_vals) / max(len(to_vals)-1, 1))
            if len(to_vals) > 1 else 0.05
        )
        stats[k] = {
            "n":           n,
            "mean_shares": mean_s,
            "std_shares":  std_s,
            "mean_turnout": mean_to,
            "std_turnout":  std_to,
        }
    return stats


def build_all_stats(counted: list[dict], cand_cols: list[str]) -> dict:
    return {
        "local": compute_level_stats(counted, lambda m: m["_local"], cand_cols),
        "dist":  compute_level_stats(counted, lambda m: m["_dist"],  cand_cols),
        "prov":  compute_level_stats(counted, lambda m: m["_prov"],  cand_cols),
        "dept":  compute_level_stats(counted, lambda m: m["_dept"],  cand_cols),
        "nat":   compute_level_stats(counted, lambda m: "NAT",       cand_cols),
    }


def aggregate_by_prior(remaining: list[dict], priors: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Collapse mesas that share the same prior into a single entry by summing
    their electores. This reduces simulation cost dramatically when most mesas
    fall back to province / dept / national level (common at low reporting rates).

    Returns (agg_mesas, agg_priors) where agg_mesas only has _electores set.
    """
    groups: dict[int, dict] = {}
    for m, p in zip(remaining, priors):
        pid = id(p)
        if pid not in groups:
            groups[pid] = {"prior": p, "_electores": 0}
        groups[pid]["_electores"] += m["_electores"]
    agg_mesas  = [{"_electores": g["_electores"]} for g in groups.values()]
    agg_priors = [g["prior"]                       for g in groups.values()]
    return agg_mesas, agg_priors


def get_prior(mesa: dict, stats: dict) -> dict:
    """Return the finest level stats with >= MIN_PEERS observations."""
    for level_name, key in [
        ("local", mesa["_local"]),
        ("dist",  mesa["_dist"]),
        ("prov",  mesa["_prov"]),
        ("dept",  mesa["_dept"]),
        ("nat",   "NAT"),
    ]:
        if not key:
            continue
        st = stats[level_name].get(key)
        if st and st["n"] >= MIN_PEERS:
            return st
    # Absolute fallback: national (even if < MIN_PEERS)
    return stats["nat"].get("NAT", {
        "mean_shares": {}, "std_shares": {},
        "mean_turnout": 0.7, "std_turnout": 0.1
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Monte Carlo
# ═══════════════════════════════════════════════════════════════════════════════

def run_simulations(
    base_votes:  dict[str, int],
    remaining:   list[dict],
    priors:      list[dict],
    cand_cols:   list[str],
    n_sims:      int,
    rng:         random.Random,
    battle_cols: tuple[str, str] | None = None,
) -> tuple[list[int], list[str], dict[str, int]]:
    """
    Returns:
      margins      – list of (col_a − col_b) votes per simulation.
                     If battle_cols given, col_a/col_b are fixed regardless of rank.
                     Otherwise col_a = simulated 2nd, col_b = simulated 3rd.
      winners_2nd  – which cand_col was 2nd in each simulation
      in_top2      – {cand_col: count of sims in top-2}
    """
    if HAS_NUMPY and len(remaining) > 500:
        return _run_simulations_np(base_votes, remaining, priors, cand_cols,
                                   n_sims, rng, battle_cols)
    return _run_simulations_py(base_votes, remaining, priors, cand_cols,
                               n_sims, rng, battle_cols)


def _run_simulations_py(base_votes, remaining, priors, cand_cols,
                        n_sims, rng, battle_cols):
    """Pure-Python fallback (slow for large remaining sets)."""
    margins: list[int] = []
    winners_2nd: list[str] = []
    in_top2: dict[str, int] = defaultdict(int)

    for _ in range(n_sims):
        sim = dict(base_votes)
        for m, prior in zip(remaining, priors):
            elec = m["_electores"]
            if elec == 0:
                continue
            turnout  = max(0.01, min(1.0,
                rng.gauss(prior["mean_turnout"], prior["std_turnout"])))
            emitidos = int(elec * turnout)
            if emitidos == 0:
                continue
            mean_s = prior["mean_shares"]
            std_s  = prior["std_shares"]
            for col in cand_cols:
                ms    = mean_s.get(col, 0.0)
                ss    = std_s.get(col, ms * 0.1 + 1e-4)
                share = max(0.0, rng.gauss(ms, ss))
                sim[col] = sim.get(col, 0) + int(emitidos * share)

        ranked = sorted(cand_cols, key=lambda c: sim.get(c, 0), reverse=True)
        if battle_cols:
            col_a, col_b = battle_cols
            margins.append(sim.get(col_a, 0) - sim.get(col_b, 0))
        else:
            margins.append(sim.get(ranked[1], 0) - sim.get(ranked[2], 0))
        winners_2nd.append(ranked[1])
        for col in ranked[:2]:
            in_top2[col] += 1

    return margins, winners_2nd, in_top2


def _run_simulations_np(base_votes, remaining, priors, cand_cols,
                        n_sims, rng, battle_cols):
    """
    Vectorised numpy simulation.

    Processes simulations in chunks of CHUNK to keep peak memory under ~200 MB
    even when remaining has 80k+ mesas and there are 18+ candidates.
    """
    CHUNK = 250
    N = len(remaining)
    C = len(cand_cols)

    # Pre-build prior arrays: shape (N,) / (N, C)
    elec_arr   = np.array([m["_electores"]          for m in remaining], dtype=np.float32)
    mean_to    = np.array([p["mean_turnout"]         for p in priors],   dtype=np.float32)
    std_to     = np.array([p["std_turnout"]          for p in priors],   dtype=np.float32)
    mean_s_mat = np.array([[p["mean_shares"].get(col, 0.0) for col in cand_cols]
                            for p in priors], dtype=np.float32)          # (N, C)
    std_s_mat  = np.array([[p["std_shares"].get(
                                col,
                                p["mean_shares"].get(col, 0.0) * 0.1 + 1e-4)
                            for col in cand_cols]
                            for p in priors], dtype=np.float32)          # (N, C)

    base_arr = np.array([base_votes.get(col, 0) for col in cand_cols], dtype=np.int64)

    # Seed numpy RNG from Python RNG for reproducibility
    np_rng = np.random.default_rng(rng.randint(0, 2**31))

    # Accumulate total votes per simulation: (n_sims, C)
    sim_votes = np.zeros((n_sims, C), dtype=np.int64)

    for start in range(0, n_sims, CHUNK):
        end = min(start + CHUNK, n_sims)
        S   = end - start                                  # sims in this chunk

        # Turnout: (S, N) → emitidos: (S, N)
        turnout  = np_rng.normal(mean_to, std_to, size=(S, N)).clip(0.01, 1.0)
        emitidos = (elec_arr * turnout).astype(np.int32)  # (S, N)

        # Candidate shares — one candidate at a time to keep memory low
        for ci in range(C):
            shares = np_rng.normal(mean_s_mat[:, ci], std_s_mat[:, ci],
                                   size=(S, N)).clip(0.0, None)          # (S, N)
            sim_votes[start:end, ci] = (emitidos * shares).sum(axis=1)

    # Add observed base votes
    sim_votes += base_arr                                  # broadcast (1, C)

    # Derive margins, winners, in_top2
    ranked_idx  = np.argsort(-sim_votes, axis=1)          # (n_sims, C) desc
    winners_2nd = [cand_cols[ranked_idx[s, 1]] for s in range(n_sims)]
    in_top2: dict[str, int] = defaultdict(int)
    for s in range(n_sims):
        in_top2[cand_cols[ranked_idx[s, 0]]] += 1
        in_top2[cand_cols[ranked_idx[s, 1]]] += 1

    if battle_cols:
        idx_a = cand_cols.index(battle_cols[0])
        idx_b = cand_cols.index(battle_cols[1])
        margins = (sim_votes[:, idx_a] - sim_votes[:, idx_b]).tolist()
    else:
        idx2 = ranked_idx[:, 1]
        idx3 = ranked_idx[:, 2]
        margins = (sim_votes[np.arange(n_sims), idx2]
                   - sim_votes[np.arange(n_sims), idx3]).tolist()

    return margins, winners_2nd, in_top2


# ═══════════════════════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════════════════════

def percentile(lst: list, p: float) -> float:
    s = sorted(lst)
    idx = p / 100 * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def make_histogram(values: list[int], n_bins: int) -> dict:
    mn, mx = min(values), max(values)
    if mn == mx:
        return {"edges": [mn, mx + 1], "counts": [len(values)]}
    bw = (mx - mn) / n_bins
    counts = [0] * n_bins
    for v in values:
        bi = min(int((v - mn) / bw), n_bins - 1)
        counts[bi] += 1
    edges = [int(mn + i * bw) for i in range(n_bins + 1)]
    return {"edges": edges, "counts": counts}


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run_forecast(mesas: list[dict], cand_cols: list[str], candidates: list[dict],
                 n_sims: int = N_SIM, seed: int = SEED,
                 holdout_frac: float = 0.0) -> dict:
    """
    Core forecast.  holdout_frac > 0 → randomly treat that fraction of C mesas
    as remaining (for calibration validation).
    """
    rng = random.Random(seed)

    counted_all = [m for m in mesas if m["_is_C"]]
    non_c       = [m for m in mesas if not m["_is_C"]]

    if holdout_frac > 0:
        rng.shuffle(counted_all)
        n_hold = int(len(counted_all) * holdout_frac)
        held_out  = counted_all[:n_hold]
        counted   = counted_all[n_hold:]
        remaining = held_out + non_c
    else:
        counted   = counted_all
        remaining = non_c

    # Base totals from counted mesas
    base_votes: dict[str, int] = defaultdict(int)
    for m in counted:
        for col, v in m["_votes"].items():
            base_votes[col] += v

    # Build hierarchy statistics
    stats  = build_all_stats(counted, cand_cols)
    priors = [get_prior(m, stats) for m in remaining]

    # Aggregate mesas sharing the same prior → massive speedup at low reporting rates
    agg_remaining, agg_priors = aggregate_by_prior(remaining, priors)

    print(f"  Counted: {len(counted):,}  Remaining: {len(remaining):,}  "
          f"(aggregated to {len(agg_remaining):,} prior groups)")

    # Pass 1: small run (500 sims) just to identify who the real battle candidates are.
    # 500 sims is enough to reliably rank candidates by in_top2.
    N_ID = min(500, n_sims)
    _, _, in_top2_id = run_simulations(
        base_votes, agg_remaining, agg_priors, cand_cols, N_ID, rng,
        battle_cols=None)

    # Battle pair = 2nd and 3rd by simulation probability (not by raw vote count).
    sim_ranked = sorted(cand_cols, key=lambda c: in_top2_id.get(c, 0), reverse=True)
    cand_2nd   = sim_ranked[1]   # most likely to reach 2da vuelta (after leader)
    cand_3rd   = sim_ranked[2]   # second most likely

    # Pass 2: full n_sims with signed margin for the confirmed battle pair
    rng2 = random.Random(seed)   # re-seed so pass-2 output is reproducible
    margins, winners_2nd, in_top2 = run_simulations(
        base_votes, agg_remaining, agg_priors, cand_cols, n_sims, rng2,
        battle_cols=(cand_2nd, cand_3rd))

    total_sim = len(margins)
    prob_2nd  = sum(1 for w in winners_2nd if w == cand_2nd) / total_sim * 100
    prob_3rd  = sum(1 for w in winners_2nd if w == cand_3rd) / total_sim * 100

    mean_margin = sum(margins) / len(margins)
    ci_lo       = int(percentile(margins, 2.5))
    ci_hi       = int(percentile(margins, 97.5))

    # Candidate summary (from mesa CSV totals of ALL counted mesas in base)
    total_emitidos = sum(m["_emitidos"] for m in counted)
    cand_summary = []
    cand_by_col  = {f"cand_{c['codigo']}": c for c in candidates}
    base_ranked  = sorted(cand_cols, key=lambda c: base_votes.get(c, 0), reverse=True)
    for col in base_ranked:
        c     = cand_by_col[col]
        votes = base_votes.get(col, 0)
        cand_summary.append({
            "codigo":      c["codigo"],
            "nombre":      c.get("nombre", ""),
            "color":       c.get("color", "#666"),
            "votes":       votes,
            "pct_emitidos":  round(votes / total_emitidos * 100, 3) if total_emitidos else 0,
            "prob_runoff": round(in_top2.get(col, 0) / total_sim * 100, 1),
        })

    return {
        "generated_at":         datetime.datetime.utcnow().isoformat() + "Z",
        "pct_actas":            round(len(counted_all) / max(len(mesas), 1) * 100, 2),
        "mesas_contabilizadas": len(counted_all),
        "mesas_remaining":      len(non_c),
        "mesas_total":          len(mesas),
        "mesas_in_analysis":    len(counted),   # after holdout, if any
        "n_sims":               total_sim,
        "candidates":           cand_summary,
        "battle": {
            "cand_2nd":          cand_by_col[cand_2nd]["codigo"],   # just "10", not "cand_10"
            "cand_3rd":          cand_by_col[cand_3rd]["codigo"],
            "nombre_2nd":        cand_by_col[cand_2nd].get("nombre", ""),
            "nombre_3rd":        cand_by_col[cand_3rd].get("nombre", ""),
            "color_2nd":         cand_by_col[cand_2nd].get("color", "#888"),
            "color_3rd":         cand_by_col[cand_3rd].get("color", "#888"),
            "prob_2nd_pct":      round(prob_2nd, 1),
            "prob_3rd_pct":      round(prob_3rd, 1),
            "mean_margin_votes": int(mean_margin),
            "ci_lo_votes":       ci_lo,
            "ci_hi_votes":       ci_hi,
            "margin_distribution": make_histogram(margins, N_BINS),
        },
    }


def run_validation(mesas, cand_cols, candidates,
                   n_trials=100, n_sims=2_000, seed=SEED,
                   obs_frac=0.05):
    """
    Calibration test via repeated random holdouts.

    obs_frac  – fraction of C mesas treated as *observed* (default 0.05 = 5%).
                The rest are held out and forecast.
    n_trials  – number of independent random splits.
    n_sims    – Monte Carlo draws per trial.

    Reports:
      • per-trial CI and hit/miss
      • overall 95%-CI coverage rate
      • CI width statistics
    """
    holdout_frac = 1.0 - obs_frac
    cand_by_col  = {f"cand_{c['codigo']}": c for c in candidates}

    counted_all = [m for m in mesas if m["_is_C"]]
    non_c       = [m for m in mesas if not m["_is_C"]]
    if not counted_all:
        print("No Contabilizada mesas — run the scraper first.", flush=True)
        return

    # True final margin from ALL counted mesas
    true_base: dict[str, int] = defaultdict(int)
    for m in counted_all:
        for col, v in m["_votes"].items():
            true_base[col] += v
    cand_cols_sorted = sorted(cand_cols, key=lambda c: true_base.get(c, 0), reverse=True)
    true_2nd    = cand_cols_sorted[1]
    true_3rd    = cand_cols_sorted[2]
    true_margin = true_base[true_2nd] - true_base[true_3rd]

    n_obs = int(len(counted_all) * obs_frac)

    print(f"\n{'='*60}", flush=True)
    print(f"Calibration: {n_trials} trials × {obs_frac*100:.0f}% observed "
          f"({n_obs:,} of {len(counted_all):,} C mesas)  ·  {n_sims:,} sims/trial", flush=True)
    print(f"True final margin (2nd−3rd): {true_margin:+,} votes", flush=True)
    print(f"True 2nd: {cand_by_col[true_2nd]['nombre']}", flush=True)
    print(f"True 3rd: {cand_by_col[true_3rd]['nombre']}", flush=True)
    print(f"Engine   : {'numpy' if HAS_NUMPY else 'pure Python'}", flush=True)
    print(f"{'='*60}", flush=True)

    covered = 0
    widths  = []

    for trial in range(n_trials):
        print(f"  {trial+1:3d}/{n_trials}  building priors …", end="\r", flush=True)

        rng_t = random.Random(seed + trial)
        counted_all_copy = list(counted_all)
        rng_t.shuffle(counted_all_copy)
        n_obs_t   = int(len(counted_all_copy) * obs_frac)
        observed  = counted_all_copy[:n_obs_t]          # the ~5% we "see"
        held_out  = counted_all_copy[n_obs_t:]          # held-out C mesas
        remaining = held_out + non_c                    # everything to forecast

        base_votes: dict[str, int] = defaultdict(int)
        for m in observed:
            for col, v in m["_votes"].items():
                base_votes[col] += v

        stats  = build_all_stats(observed, cand_cols)
        priors = [get_prior(m, stats) for m in remaining]

        # Collapse mesas sharing the same prior → huge speedup at low reporting rates
        agg_mesas, agg_priors = aggregate_by_prior(remaining, priors)

        print(f"  {trial+1:3d}/{n_trials}  simulating ({n_sims:,} draws, "
              f"{len(agg_mesas):,} prior groups from {len(remaining):,} mesas) …",
              end="\r", flush=True)

        margins, _, _ = run_simulations(
            base_votes, agg_mesas, agg_priors, cand_cols, n_sims, rng_t,
            battle_cols=(true_2nd, true_3rd))

        lo  = int(percentile(margins, 2.5))
        hi  = int(percentile(margins, 97.5))
        hit = lo <= true_margin <= hi
        covered += int(hit)
        widths.append(hi - lo)

        print(f"  {trial+1:3d}/{n_trials}  CI [{lo:+,}, {hi:+,}]  "
              f"width={hi-lo:,}  {'✓' if hit else '✗'}          ", flush=True)

    mean_width = sum(widths) / len(widths)
    cov_pct    = covered / n_trials * 100
    print(f"\n{'─'*60}")
    print(f"Coverage : {covered}/{n_trials} = {cov_pct:.1f}%  (target: 95%)")
    print(f"CI width : mean={mean_width:,.0f}  min={min(widths):,}  max={max(widths):,} votes")
    if cov_pct < 90:
        print("  ⚠  Under-coverage — CIs too narrow for this reporting level")
    elif cov_pct > 99:
        print("  ⚠  Over-coverage — CIs too wide")
    else:
        print("  ✓  Coverage acceptable")
    return cov_pct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="Run holdout calibration check")
    parser.add_argument("--preview",  type=float, default=None, metavar="OBS_FRAC",
                        help="Simulate early-night: treat OBS_FRAC of C mesas as observed "
                             "(e.g. 0.05 = 5%%), save forecast.json, then exit")
    parser.add_argument("--obs",      type=float, default=0.05,
                        help="Fraction of C mesas treated as observed (default: 0.05 = 5%%)")
    parser.add_argument("--trials",   type=int, default=100,
                        help="Number of random holdout trials (default: 100)")
    parser.add_argument("--sims",     type=int, default=2_000,
                        help="Monte Carlo draws per trial (default: 2000)")
    args = parser.parse_args()

    candidates = load_candidates()
    cand_cols  = [f"cand_{c['codigo']}" for c in candidates]

    print("Loading data …")
    roll_lkp = load_roll_lkp()
    mesas    = load_mesas(cand_cols)
    attach_hierarchy(mesas, roll_lkp)

    n_c = sum(m["_is_C"] for m in mesas)
    print(f"  {len(mesas):,} mesas  ({n_c:,} Contabilizadas, {len(mesas)-n_c:,} remaining)")

    if args.preview is not None:
        obs_frac     = args.preview
        holdout_frac = 1.0 - obs_frac
        print(f"\nPreview mode: {obs_frac*100:.0f}% observed  "
              f"({int(sum(m['_is_C'] for m in mesas)*obs_frac):,} C mesas as input)")
        result = run_forecast(mesas, cand_cols, candidates,
                              n_sims=args.sims, holdout_frac=holdout_frac)
        with open(OUT_JSON, "w") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        b = result["battle"]
        print(f"Saved → {OUT_JSON.name}")
        print(f"  Battle: {b['nombre_2nd'].split()[0]} vs {b['nombre_3rd'].split()[0]}")
        print(f"  Margin: {b['mean_margin_votes']:+,} votes  "
              f"CI [{b['ci_lo_votes']:+,}, {b['ci_hi_votes']:+,}]")
        print(f"  P(2nd holds): {b['prob_2nd_pct']:.1f}%")
        return

    if args.validate:
        run_validation(mesas, cand_cols, candidates,
                       n_trials=args.trials, n_sims=args.sims,
                       obs_frac=args.obs)
        return

    print(f"\nRunning {args.sims:,} simulations …")
    result = run_forecast(mesas, cand_cols, candidates, n_sims=args.sims)

    with open(OUT_JSON, "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    b = result["battle"]
    print(f"\nSaved → {OUT_JSON.name}")
    print(f"  Battle: {b['nombre_2nd'].split()[0]} vs {b['nombre_3rd'].split()[0]}")
    print(f"  Margin: {b['mean_margin_votes']:+,} votes  "
          f"CI [{b['ci_lo_votes']:+,}, {b['ci_hi_votes']:+,}]")
    print(f"  P(2nd holds): {b['prob_2nd_pct']:.1f}%")
    print()
    for c in result["candidates"][:5]:
        print(f"  {c['pct_emitidos']:5.2f}%  {c['votes']:>10,}  {c['nombre']}")


if __name__ == "__main__":
    main()
