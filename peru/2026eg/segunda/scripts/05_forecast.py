"""
05_forecast.py — Peru 2026 EG Segunda Vuelta  (Bayesian Hierarchical Forecast)

For each non-Contabilizada (remaining) mesa we estimate a vote-share
distribution from the finest available geographic hierarchy level:

  polling place  →  district  →  province  →  department  →  national

Then we run N_SIM Monte Carlo simulations to project the final margin
(in absolute votes) by which one candidate will win the runoff.

Positive margin = Keiko winning; negative margin = Sánchez winning.
At 100% reporting there are no remaining mesas → CI collapses to observed margin.

Usage:
  python3 05_forecast.py               # normal run
  python3 05_forecast.py --validate    # 50-% holdout calibration check

Output: segunda/data/forecast.json
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
META        = SCRIPT_DIR.parent.parent / "metadata"

MESA_CSV    = RESULTS / "peru_2026eg_mesa_segunda.csv"
CAND_JSON   = DATA_DIR / "candidates.json"
MESA_ROLL   = META / "peru_2026_mesa_electoral_roll.csv"
OUT_JSON    = DATA_DIR / "forecast.json"

# ── Constants ──────────────────────────────────────────────────────────────────
N_SIM        = 10_000
SEED         = 42
MIN_PEERS    = 5      # min counted mesas at a level to use it as prior
N_BINS       = 100    # histogram bins for margin distribution

# ── Exterior prior (from 2021 segunda vuelta exterior mesas) ──────────────────
# Keiko (FP) 66.19%, Castillo (PL) 33.81% — P2=FP, P1=PL in 2021 dictionary
# Turnout 36.5%, ~106 votes/mesa
# Used as fallback when no exterior mesas are yet counted at any hierarchy level.
EXTERIOR_PRIOR_SHARES  = {"cand_01": 0.6619, "cand_02": 0.3381}  # keiko, roberto
EXTERIOR_PRIOR_TURNOUT = 0.365
EXTERIOR_PRIOR_TURNOUT_STD = 0.08


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
        m["_local"]      = f"{dist}_{local_raw}" if local_raw else ""
        m["_dist"]       = dist
        m["_prov"]       = (rl.get("ubigeo_provincia") or dist[:4] or "")
        m["_dept"]       = (rl.get("ubigeo_dept")      or dist[:2] or "")
        m["_is_exterior"] = rl.get("is_exterior") == "True"


def load_roll_lkp() -> dict:
    if not MESA_ROLL.exists():
        return {}
    with open(MESA_ROLL, newline="") as f:
        return {r["codigo_mesa"]: r for r in csv.DictReader(f)}


# ═══════════════════════════════════════════════════════════════════════════════
# Hierarchy statistics
# ═══════════════════════════════════════════════════════════════════════════════

def compute_level_stats(counted: list[dict], key_fn, cand_cols: list[str]) -> dict:
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
            "n":            n,
            "mean_shares":  mean_s,
            "std_shares":   std_s,
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
    """Collapse mesas sharing the same prior into a single entry (speedup)."""
    groups: dict[int, dict] = {}
    for m, p in zip(remaining, priors):
        pid = id(p)
        if pid not in groups:
            groups[pid] = {"prior": p, "_electores": 0}
        groups[pid]["_electores"] += m["_electores"]
    agg_mesas  = [{"_electores": g["_electores"]} for g in groups.values()]
    agg_priors = [g["prior"]                       for g in groups.values()]
    return agg_mesas, agg_priors


def get_prior(mesa: dict, stats: dict, cand_cols: list) -> dict:
    """Return the finest level stats with >= MIN_PEERS observations.
    Exterior mesas with no counted peers fall back to 2021 exterior prior
    instead of the national average (which reflects only domestic mesas).
    """
    for level_name, key in [
        ("local", mesa["_local"]),
        ("dist",  mesa["_dist"]),
        ("prov",  mesa["_prov"]),
        ("dept",  mesa["_dept"]),
    ]:
        if not key:
            continue
        st = stats[level_name].get(key)
        if st and st["n"] >= MIN_PEERS:
            return st

    # Exterior fallback: use 2021 exterior shares instead of domestic national avg
    # Must be checked BEFORE national prior, which would otherwise always match
    if mesa.get("_is_exterior"):
        shares = {col: EXTERIOR_PRIOR_SHARES.get(col, 1/len(cand_cols))
                  for col in cand_cols}
        std_s  = {col: 0.06 for col in cand_cols}  # modest uncertainty
        return {
            "mean_shares":   shares,
            "std_shares":    std_s,
            "mean_turnout":  EXTERIOR_PRIOR_TURNOUT,
            "std_turnout":   EXTERIOR_PRIOR_TURNOUT_STD,
            "n": 0,
        }

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
    col_a:       str,
    col_b:       str,
) -> tuple[list[int], dict[str, int]]:
    """
    Signed-margin simulation for a runoff between exactly two candidates.

    margin > 0  → col_a is winning
    margin < 0  → col_b is winning

    Returns:
      margins   – list of (col_a − col_b) votes per simulation
      wins      – {col: number of sims won}
    """
    if HAS_NUMPY and len(remaining) > 500:
        return _run_simulations_np(base_votes, remaining, priors, cand_cols,
                                   n_sims, rng, col_a, col_b)
    return _run_simulations_py(base_votes, remaining, priors, cand_cols,
                               n_sims, rng, col_a, col_b)


def _run_simulations_py(base_votes, remaining, priors, cand_cols,
                        n_sims, rng, col_a, col_b):
    margins: list[int] = []
    wins: dict[str, int] = {col_a: 0, col_b: 0}

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

        margin = sim.get(col_a, 0) - sim.get(col_b, 0)
        margins.append(margin)
        if margin > 0:
            wins[col_a] += 1
        else:
            wins[col_b] += 1

    return margins, wins


def _run_simulations_np(base_votes, remaining, priors, cand_cols,
                        n_sims, rng, col_a, col_b):
    """Vectorised numpy simulation."""
    CHUNK = 250
    N = len(remaining)
    C = len(cand_cols)

    elec_arr   = np.array([m["_electores"]          for m in remaining], dtype=np.float32)
    mean_to    = np.array([p["mean_turnout"]         for p in priors],   dtype=np.float32)
    std_to     = np.array([p["std_turnout"]          for p in priors],   dtype=np.float32)
    mean_s_mat = np.array([[p["mean_shares"].get(col, 0.0) for col in cand_cols]
                            for p in priors], dtype=np.float32)
    std_s_mat  = np.array([[p["std_shares"].get(
                                col,
                                p["mean_shares"].get(col, 0.0) * 0.1 + 1e-4)
                            for col in cand_cols]
                            for p in priors], dtype=np.float32)

    base_arr = np.array([base_votes.get(col, 0) for col in cand_cols], dtype=np.int64)
    np_rng   = np.random.default_rng(rng.randint(0, 2**31))

    sim_votes = np.zeros((n_sims, C), dtype=np.int64)

    for start in range(0, n_sims, CHUNK):
        end = min(start + CHUNK, n_sims)
        S   = end - start

        turnout  = np_rng.normal(mean_to, std_to, size=(S, N)).clip(0.01, 1.0)
        emitidos = (elec_arr * turnout).astype(np.int32)

        for ci in range(C):
            shares = np_rng.normal(mean_s_mat[:, ci], std_s_mat[:, ci],
                                   size=(S, N)).clip(0.0, None)
            sim_votes[start:end, ci] = (emitidos * shares).sum(axis=1)

    sim_votes += base_arr

    idx_a = cand_cols.index(col_a)
    idx_b = cand_cols.index(col_b)
    margins_arr = (sim_votes[:, idx_a] - sim_votes[:, idx_b])
    margins = margins_arr.tolist()
    wins = {
        col_a: int((margins_arr > 0).sum()),
        col_b: int((margins_arr <= 0).sum()),
    }

    return margins, wins


# ═══════════════════════════════════════════════════════════════════════════════
# Output helpers
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
# Main forecast
# ═══════════════════════════════════════════════════════════════════════════════

def run_forecast(mesas: list[dict], cand_cols: list[str], candidates: list[dict],
                 n_sims: int = N_SIM, seed: int = SEED,
                 holdout_frac: float = 0.0) -> dict:
    """
    Runoff forecast.  With only 2 candidates there is no need for a pass-1
    battle-pair identification step — we always forecast the margin between
    the two known finalists.

    Positive margin = cand_cols[0] winning; negative = cand_cols[1] winning.
    The 'winner' (cand who leads in most sims) is surfaced as cand_2nd in the
    JSON to reuse the same frontend structure as primera.
    """
    rng = random.Random(seed)

    counted_all = [m for m in mesas if m["_is_C"]]
    non_c       = [m for m in mesas if not m["_is_C"]]

    # Empty state: no actas counted yet — return zeroed output sorted alphabetically
    if not counted_all:
        cand_summary = sorted(
            [{"codigo": c["codigo"], "nombre": c.get("nombre", ""),
              "color": c.get("color", "#666"), "votes": 0,
              "pct_emitidos": 0, "prob_runoff": 0}
             for c in candidates],
            key=lambda c: c["nombre"]
        )
        col_0 = f"cand_{cand_summary[0]['codigo']}"
        col_1 = f"cand_{cand_summary[1]['codigo']}"
        cand_by_col = {f"cand_{c['codigo']}": c for c in candidates}
        return {
            "generated_at":         datetime.datetime.utcnow().isoformat() + "Z",
            "pct_actas":            0.0,
            "mesas_contabilizadas": 0,
            "mesas_remaining":      len(non_c),
            "mesas_total":          len(mesas),
            "mesas_in_analysis":    0,
            "n_sims":               0,
            "candidates":           cand_summary,
            "battle": {
                "cand_2nd":          cand_summary[0]["codigo"],
                "cand_3rd":          cand_summary[1]["codigo"],
                "nombre_2nd":        cand_summary[0]["nombre"],
                "nombre_3rd":        cand_summary[1]["nombre"],
                "color_2nd":         cand_summary[0]["color"],
                "color_3rd":         cand_summary[1]["color"],
                "prob_2nd_pct":      0.0,
                "prob_3rd_pct":      0.0,
                "mean_margin_votes": 0,
                "ci_lo_votes":       0,
                "ci_hi_votes":       0,
                "margin_distribution": {"edges": [0, 1], "counts": [0]},
            },
        }

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

    # Hierarchy priors
    stats  = build_all_stats(counted, cand_cols)
    priors = [get_prior(m, stats, cand_cols) for m in remaining]

    # Aggregate mesas sharing the same prior
    agg_remaining, agg_priors = aggregate_by_prior(remaining, priors)

    print(f"  Counted: {len(counted):,}  Remaining: {len(remaining):,}  "
          f"(aggregated to {len(agg_remaining):,} prior groups)")

    # The two candidates — determine who is currently leading to assign
    # cand_2nd (the "favorite" displayed on the left of the needle).
    col_0, col_1 = cand_cols[0], cand_cols[1]
    if base_votes.get(col_0, 0) >= base_votes.get(col_1, 0):
        col_leader, col_trailer = col_0, col_1
    else:
        col_leader, col_trailer = col_1, col_0

    # Simulation — signed margin: positive = col_leader winning
    margins, wins = run_simulations(
        base_votes, agg_remaining, agg_priors, cand_cols, n_sims, rng,
        col_a=col_leader, col_b=col_trailer)

    total_sim    = len(margins)
    prob_leader  = wins[col_leader]  / total_sim * 100
    prob_trailer = wins[col_trailer] / total_sim * 100

    mean_margin = sum(margins) / len(margins)
    ci_lo       = int(percentile(margins, 2.5))
    ci_hi       = int(percentile(margins, 97.5))
    ci_lo_99    = int(percentile(margins, 0.5))
    ci_hi_99    = int(percentile(margins, 99.5))

    # Candidate summary
    total_emitidos = sum(m["_emitidos"] for m in counted)
    cand_by_col    = {f"cand_{c['codigo']}": c for c in candidates}

    cand_summary = []
    for col in cand_cols:
        c     = cand_by_col[col]
        votes = base_votes.get(col, 0)
        cand_summary.append({
            "codigo":       c["codigo"],
            "nombre":       c.get("nombre", ""),
            "color":        c.get("color", "#666"),
            "votes":        votes,
            "pct_emitidos": round(votes / total_emitidos * 100, 3) if total_emitidos else 0,
            # prob_runoff reused as "probability of winning the runoff" for frontend compatibility
            "prob_runoff":  round(wins.get(col, 0) / total_sim * 100, 1),
        })

    return {
        "generated_at":         datetime.datetime.utcnow().isoformat() + "Z",
        "pct_actas":            round(len(counted_all) / max(len(mesas), 1) * 100, 2),
        "mesas_contabilizadas": len(counted_all),
        "mesas_remaining":      len(non_c),
        "mesas_total":          len(mesas),
        "mesas_in_analysis":    len(counted),
        "n_sims":               total_sim,
        "candidates":           cand_summary,
        # 'battle' key kept for frontend compatibility; semantics: 2nd = leader, 3rd = trailer
        "battle": {
            "cand_2nd":          cand_by_col[col_leader]["codigo"],
            "cand_3rd":          cand_by_col[col_trailer]["codigo"],
            "nombre_2nd":        cand_by_col[col_leader].get("nombre", ""),
            "nombre_3rd":        cand_by_col[col_trailer].get("nombre", ""),
            "color_2nd":         cand_by_col[col_leader].get("color", "#888"),
            "color_3rd":         cand_by_col[col_trailer].get("color", "#888"),
            "prob_2nd_pct":      round(prob_leader, 1),   # prob of winning outright
            "prob_3rd_pct":      round(prob_trailer, 1),
            "mean_margin_votes": int(mean_margin),
            "ci_lo_votes":       ci_lo,
            "ci_hi_votes":       ci_hi,
            "ci_lo_99_votes":    ci_lo_99,
            "ci_hi_99_votes":    ci_hi_99,
            "margin_distribution": make_histogram(margins, N_BINS),
        },
    }


def run_validation(mesas, cand_cols, candidates,
                   n_trials=100, n_sims=2_000, seed=SEED,
                   obs_frac=0.05):
    """Calibration via repeated random holdouts."""
    cand_by_col  = {f"cand_{c['codigo']}": c for c in candidates}

    counted_all = [m for m in mesas if m["_is_C"]]
    non_c       = [m for m in mesas if not m["_is_C"]]
    if not counted_all:
        print("No Contabilizada mesas — run the scraper first.")
        return

    true_base: dict[str, int] = defaultdict(int)
    for m in counted_all:
        for col, v in m["_votes"].items():
            true_base[col] += v

    col_0, col_1 = cand_cols[0], cand_cols[1]
    true_margin = true_base[col_0] - true_base[col_1]
    true_leader = col_0 if true_margin >= 0 else col_1
    true_trailer = col_1 if true_margin >= 0 else col_0
    true_margin_abs = abs(true_margin)

    n_obs = int(len(counted_all) * obs_frac)
    print(f"\n{'='*60}")
    print(f"Calibration: {n_trials} trials × {obs_frac*100:.0f}% observed  ·  {n_sims:,} sims/trial")
    print(f"True final margin: {true_margin:+,} votes")
    print(f"True winner: {cand_by_col[true_leader]['nombre']}")
    print(f"{'='*60}")

    covered = 0
    widths  = []

    for trial in range(n_trials):
        rng_t = random.Random(seed + trial)
        counted_copy = list(counted_all)
        rng_t.shuffle(counted_copy)
        n_obs_t   = int(len(counted_copy) * obs_frac)
        observed  = counted_copy[:n_obs_t]
        held_out  = counted_copy[n_obs_t:]
        remaining = held_out + non_c

        base_votes: dict[str, int] = defaultdict(int)
        for m in observed:
            for col, v in m["_votes"].items():
                base_votes[col] += v

        stats  = build_all_stats(observed, cand_cols)
        priors = [get_prior(m, stats, cand_cols) for m in remaining]
        agg_mesas, agg_priors = aggregate_by_prior(remaining, priors)

        margins, _ = run_simulations(
            base_votes, agg_mesas, agg_priors, cand_cols, n_sims, rng_t,
            col_a=true_leader, col_b=true_trailer)

        lo  = int(percentile(margins, 2.5))
        hi  = int(percentile(margins, 97.5))
        hit = lo <= true_margin <= hi
        covered += int(hit)
        widths.append(hi - lo)
        print(f"  {trial+1:3d}/{n_trials}  CI [{lo:+,}, {hi:+,}]  {'✓' if hit else '✗'}")

    mean_width = sum(widths) / len(widths)
    cov_pct    = covered / n_trials * 100
    print(f"\n{'─'*60}")
    print(f"Coverage : {covered}/{n_trials} = {cov_pct:.1f}%  (target: 95%)")
    print(f"CI width : mean={mean_width:,.0f}  min={min(widths):,}  max={max(widths):,} votes")


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
        print(f"\nPreview mode: {obs_frac*100:.0f}% observed")
        result = run_forecast(mesas, cand_cols, candidates,
                              n_sims=args.sims, holdout_frac=holdout_frac)
        with open(OUT_JSON, "w") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        b = result["battle"]
        print(f"Saved → {OUT_JSON.name}")
        print(f"  Leader: {b['nombre_2nd'].split()[0]}  Margin: {b['mean_margin_votes']:+,} votes  "
              f"CI [{b['ci_lo_votes']:+,}, {b['ci_hi_votes']:+,}]")
        print(f"  P(winner): {b['prob_2nd_pct']:.1f}%")
        return

    if args.validate:
        run_validation(mesas, cand_cols, candidates,
                       n_trials=args.trials, n_sims=args.sims,
                       obs_frac=args.obs)
        return

    print(f"\nRunning {N_SIM:,} simulations …")
    result = run_forecast(mesas, cand_cols, candidates, n_sims=N_SIM)

    with open(OUT_JSON, "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    b = result["battle"]
    print(f"\nSaved → {OUT_JSON.name}")
    print(f"  Leader: {b['nombre_2nd'].split()[0]}  Margin: {b['mean_margin_votes']:+,} votes  "
          f"CI [{b['ci_lo_votes']:+,}, {b['ci_hi_votes']:+,}]")
    print(f"  P(winner): {b['prob_2nd_pct']:.1f}%")
    print()
    for c in result["candidates"]:
        print(f"  {c['pct_emitidos']:5.2f}%  {c['votes']:>10,}  {c['nombre']}")


if __name__ == "__main__":
    main()
