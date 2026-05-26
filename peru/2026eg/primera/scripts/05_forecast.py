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
) -> tuple[list[int], list[str], dict[str, int]]:
    """
    Returns:
      margins      – list of (votes_2nd − votes_3rd) per simulation
      winners_2nd  – which cand_col was 2nd in each simulation
      in_top2      – {cand_col: count of sims in top-2}
    """
    margins     = []
    winners_2nd = []
    in_top2: dict[str, int] = defaultdict(int)

    for _ in range(n_sims):
        sim = dict(base_votes)

        for m, prior in zip(remaining, priors):
            elec = m["_electores"]
            if elec == 0:
                continue

            # Sample turnout
            turnout = max(0.01, min(1.0,
                rng.gauss(prior["mean_turnout"], prior["std_turnout"])))
            emitidos = int(elec * turnout)
            if emitidos == 0:
                continue

            # Sample each candidate's share (of votos_emitidos)
            mean_s = prior["mean_shares"]
            std_s  = prior["std_shares"]
            for col in cand_cols:
                ms = mean_s.get(col, 0.0)
                ss = std_s.get(col, ms * 0.1 + 1e-4)
                share = max(0.0, rng.gauss(ms, ss))
                sim[col] = sim.get(col, 0) + int(emitidos * share)

        ranked = sorted(cand_cols, key=lambda c: sim.get(c, 0), reverse=True)
        margins.append(sim.get(ranked[1], 0) - sim.get(ranked[2], 0))
        winners_2nd.append(ranked[1])
        for col in ranked[:2]:
            in_top2[col] += 1

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

    print(f"  Counted: {len(counted):,}  Remaining: {len(remaining):,}")

    # Simulations
    margins, winners_2nd, in_top2 = run_simulations(
        base_votes, remaining, priors, cand_cols, n_sims, rng)

    # --- Results ---
    base_ranked = sorted(cand_cols, key=lambda c: base_votes.get(c, 0), reverse=True)
    cand_2nd    = base_ranked[1]
    cand_3rd    = base_ranked[2]

    total_sim   = len(margins)
    # winners_2nd contains column names ("cand_10") — compare with column names here
    prob_2nd    = sum(1 for w in winners_2nd if w == cand_2nd) / total_sim * 100
    prob_3rd    = sum(1 for w in winners_2nd if w == cand_3rd) / total_sim * 100
    # Note: cand_2nd / cand_3rd are column names ("cand_10") throughout the internal logic;
    # they're converted to plain codigos only in the output dict below.

    mean_margin = sum(margins) / len(margins)
    ci_lo       = int(percentile(margins, 2.5))
    ci_hi       = int(percentile(margins, 97.5))

    # Candidate summary (from mesa CSV totals of ALL counted mesas in base)
    total_emitidos = sum(m["_emitidos"] for m in counted)
    cand_summary = []
    cand_by_col  = {f"cand_{c['codigo']}": c for c in candidates}
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


def run_validation(mesas, cand_cols, candidates, n_trials=50, n_sims=2000, seed=SEED):
    """
    50-% holdout calibration test.
    Runs n_trials randomised holdouts; reports coverage of 95% CI.
    """
    counted_all = [m for m in mesas if m["_is_C"]]
    # True final margin (2nd - 3rd) from all counted mesas
    true_base: dict[str, int] = defaultdict(int)
    for m in counted_all:
        for col, v in m["_votes"].items():
            true_base[col] += v
    cand_cols_sorted = sorted(cand_cols, key=lambda c: true_base.get(c, 0), reverse=True)
    true_2nd   = cand_cols_sorted[1]
    true_3rd   = cand_cols_sorted[2]
    true_margin = true_base[true_2nd] - true_base[true_3rd]

    print(f"\n{'='*60}")
    print(f"Validation: {n_trials} × 50% holdout  ({n_sims} sims each)")
    print(f"True margin (2nd−3rd): {true_margin:+,} votes")
    print(f"{'='*60}")

    covered = 0
    for trial in range(n_trials):
        res = run_forecast(mesas, cand_cols, candidates,
                           n_sims=n_sims, seed=seed + trial,
                           holdout_frac=0.5)
        lo = res["battle"]["ci_lo_votes"]
        hi = res["battle"]["ci_hi_votes"]
        hit = lo <= true_margin <= hi
        covered += int(hit)
        print(f"  Trial {trial+1:2d}: CI [{lo:+,}, {hi:+,}]  {'✓' if hit else '✗'}")

    cov_pct = covered / n_trials * 100
    print(f"\nCoverage: {covered}/{n_trials} = {cov_pct:.1f}%  (target: 95%)")
    if cov_pct < 90:
        print("  ⚠ Under-coverage — increase VOLATILITY or MIN_PEERS")
    elif cov_pct > 99:
        print("  ⚠ Over-coverage — consider reducing volatility")
    else:
        print("  ✓ Coverage acceptable")
    return cov_pct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="Run 50% holdout calibration check")
    parser.add_argument("--trials",   type=int, default=50)
    parser.add_argument("--sims",     type=int, default=N_SIM)
    args = parser.parse_args()

    candidates = load_candidates()
    cand_cols  = [f"cand_{c['codigo']}" for c in candidates]

    print("Loading data …")
    roll_lkp = load_roll_lkp()
    mesas    = load_mesas(cand_cols)
    attach_hierarchy(mesas, roll_lkp)

    n_c = sum(m["_is_C"] for m in mesas)
    print(f"  {len(mesas):,} mesas  ({n_c:,} Contabilizadas, {len(mesas)-n_c:,} remaining)")

    if args.validate:
        run_validation(mesas, cand_cols, candidates,
                       n_trials=args.trials, n_sims=args.sims)
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
