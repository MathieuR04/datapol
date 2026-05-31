"""
05_forecast.py — Colombia 2026 Primera Vuelta (Municipio Projection Forecast)

For each municipio we know mesas_escrutadas / mesas_total.
We project the final vote total by assuming remaining mesas vote like
the already-counted mesas in the same municipio (fallback: dept → national).

Battle is hardcoded: Cepeda (1st) vs De la Espriella (2nd).

Output: data/forecast.json
"""

import csv
import json
import math
import random
import datetime
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"

MPIO_CSV   = RESULTS / "colombia_2026_municipio_primera.csv"
CAND_JSON  = DATA_DIR / "candidates.json"
OUT_JSON   = DATA_DIR / "forecast.json"

# Hardcoded battle pair (1st vs 2nd)
BATTLE_1ST = "cepeda"
BATTLE_2ND = "delaespriella"

N_SIM  = 5_000
N_BINS = 100
SEED   = 42


# ── Load ───────────────────────────────────────────────────────────────────────

def load_candidates():
    with open(CAND_JSON) as f:
        return json.load(f)

def load_mpios(cand_cols):
    rows = []
    if not MPIO_CSV.exists():
        return rows
    with open(MPIO_CSV, newline="") as f:
        for row in csv.DictReader(f):
            row["_dept"]      = str(row.get("mpio_reg_code_7", ""))[:2]
            row["_mt"]        = int(row.get("mesas_total")      or 0)
            row["_me"]        = int(row.get("mesas_escrutadas") or 0)
            row["_vv"]        = int(row.get("votos_validos")     or 0)
            row["_votes"]     = {col: int(row.get(col) or 0) for col in cand_cols}
            rows.append(row)
    return rows


# ── Projection ─────────────────────────────────────────────────────────────────

def dept_shares(mpios, cand_cols):
    """Weighted average share per candidate per dept, from municipios that have data."""
    dept_vv  = defaultdict(int)
    dept_vot = defaultdict(lambda: defaultdict(int))
    for m in mpios:
        if m["_me"] > 0 and m["_vv"] > 0:
            d = m["_dept"]
            dept_vv[d] += m["_vv"]
            for col in cand_cols:
                dept_vot[d][col] += m["_votes"][col]
    shares = {}
    for d, vv in dept_vv.items():
        shares[d] = {col: dept_vot[d][col] / vv for col in cand_cols} if vv else {}
    return shares

def national_shares(mpios, cand_cols):
    """Weighted national average share."""
    total_vv  = sum(m["_vv"] for m in mpios if m["_me"] > 0)
    total_vot = defaultdict(int)
    for m in mpios:
        if m["_me"] > 0:
            for col in cand_cols:
                total_vot[col] += m["_votes"][col]
    if not total_vv:
        return {col: 1/len(cand_cols) for col in cand_cols}
    return {col: total_vot[col] / total_vv for col in cand_cols}

def project_mpio(m, cand_cols, dept_sh, nat_sh):
    """
    Returns (observed_votes, projected_remaining_votes) per candidate.
    observed  = what's already counted
    remaining = projection for the mesas not yet counted
    """
    mt, me = m["_mt"], m["_me"]
    remaining = mt - me

    observed = {col: m["_votes"][col] for col in cand_cols}

    if remaining <= 0:
        return observed, {col: 0 for col in cand_cols}

    # Share to apply to remaining mesas
    if me > 0 and m["_vv"] > 0:
        # Use this municipio's own observed share
        share = {col: m["_votes"][col] / m["_vv"] for col in cand_cols}
        # Votes per mesa in this municipio
        vpm = m["_vv"] / me
    else:
        # Fall back to dept, then national
        d = m["_dept"]
        share = dept_sh.get(d) or nat_sh
        # National votes per mesa estimate
        total_me  = sum(x["_me"]  for x in [m] if False) or 1   # placeholder
        vpm = None

    if vpm is None:
        # Use national avg votes per mesa
        # We'll set vpm = 0 here and handle in simulation via nat_vpm
        return observed, {col: 0 for col in cand_cols}

    proj_remaining = {col: share[col] * vpm * remaining for col in cand_cols}
    return observed, proj_remaining


# ── Monte Carlo ────────────────────────────────────────────────────────────────

def run_simulations(mpios, cand_cols, dept_sh, nat_sh, n_sims, seed):
    """
    For each municipio:
      - observed votes are fixed
      - remaining votes are sampled: N(mu, sigma) where
          mu    = projected_remaining (observed share × vpm × remaining_mesas)
          sigma = mu * uncertainty_factor  (higher when fewer mesas counted)
    """
    rng = random.Random(seed)

    # Precompute per-municipio projection params
    # nat_vpm: national average valid votes per mesa (from counted municipios)
    total_vv = sum(m["_vv"] for m in mpios if m["_me"] > 0)
    total_me = sum(m["_me"] for m in mpios if m["_me"] > 0)
    nat_vpm  = (total_vv / total_me) if total_me > 0 else 200

    mpio_params = []
    for m in mpios:
        mt, me = m["_mt"], m["_me"]
        remaining = max(0, mt - me)
        obs = {col: m["_votes"][col] for col in cand_cols}

        if remaining == 0:
            mpio_params.append({"obs": obs, "mu": None})
            continue

        if me > 0 and m["_vv"] > 0:
            share = {col: m["_votes"][col] / m["_vv"] for col in cand_cols}
            vpm   = m["_vv"] / me
        else:
            d     = m["_dept"]
            share = dept_sh.get(d) or nat_sh
            vpm   = nat_vpm

        mu  = {col: share[col] * vpm * remaining for col in cand_cols}
        # Uncertainty: sqrt of remaining mesas → relative std ~15% / sqrt(remaining)
        rel_std = 0.15 / math.sqrt(remaining) if remaining > 0 else 0.15
        sigma = {col: max(0.0, mu[col] * rel_std) for col in cand_cols}

        mpio_params.append({"obs": obs, "mu": mu, "sigma": sigma})

    col_1st = f"cand_{BATTLE_1ST}"
    col_2nd = f"cand_{BATTLE_2ND}"

    margins = []
    for _ in range(n_sims):
        totals = defaultdict(float)
        for p in mpio_params:
            for col in cand_cols:
                totals[col] += p["obs"][col]
            if p.get("mu"):
                for col in cand_cols:
                    totals[col] += max(0.0, rng.gauss(p["mu"][col], p["sigma"][col]))
        margins.append(int(totals[col_1st] - totals[col_2nd]))

    return margins


# ── Output helpers ─────────────────────────────────────────────────────────────

def percentile(lst, p):
    s   = sorted(lst)
    idx = p / 100 * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

def make_histogram(values, n_bins):
    mn, mx = min(values), max(values)
    if mn == mx:
        return {"edges": [mn, mx + 1], "counts": [len(values)]}
    bw     = (mx - mn) / n_bins
    counts = [0] * n_bins
    for v in values:
        bi = min(int((v - mn) / bw), n_bins - 1)
        counts[bi] += 1
    edges = [int(mn + i * bw) for i in range(n_bins + 1)]
    return {"edges": edges, "counts": counts}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    candidates = load_candidates()
    cand_cols  = [f"cand_{c['code']}" for c in candidates]
    cand_meta  = {f"cand_{c['code']}": c for c in candidates}

    print("Loading municipios …")
    mpios = load_mpios(cand_cols)

    total_mt = sum(m["_mt"] for m in mpios)
    total_me = sum(m["_me"] for m in mpios)
    pct_mesas = round(total_me / total_mt * 100, 2) if total_mt else 0.0

    print(f"  {len(mpios):,} municipios  |  mesas: {total_me:,}/{total_mt:,} ({pct_mesas:.1f}%)")

    # Empty state
    if total_me == 0:
        result = {
            "generated_at":         datetime.datetime.utcnow().isoformat() + "Z",
            "pct_mesas":            0.0,
            "mesas_contabilizadas": 0,
            "mesas_remaining":      total_mt,
            "mesas_total":          total_mt,
            "n_sims":               0,
            "candidates":           [],
            "battle": {
                "cand_2nd":            BATTLE_1ST,
                "cand_3rd":            BATTLE_2ND,
                "nombre_2nd":          cand_meta[f"cand_{BATTLE_1ST}"]["nombre"],
                "nombre_3rd":          cand_meta[f"cand_{BATTLE_2ND}"]["nombre"],
                "color_2nd":           cand_meta[f"cand_{BATTLE_1ST}"]["color"],
                "color_3rd":           cand_meta[f"cand_{BATTLE_2ND}"]["color"],
                "prob_2nd_pct":        0.0,
                "prob_3rd_pct":        0.0,
                "mean_margin_votes":   0,
                "ci_lo_votes":         0,
                "ci_hi_votes":         0,
                "margin_distribution": {"edges": [0, 1], "counts": [0]},
            },
        }
        with open(OUT_JSON, "w") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        print("Empty state saved.")
        return

    dept_sh = dept_shares(mpios, cand_cols)
    nat_sh  = national_shares(mpios, cand_cols)

    # Observed totals
    obs_totals = defaultdict(int)
    for m in mpios:
        for col in cand_cols:
            obs_totals[col] += m["_votes"][col]

    obs_ranked   = sorted(cand_cols, key=lambda c: obs_totals[c], reverse=True)
    total_vv_obs = sum(obs_totals.values())

    print(f"Running {N_SIM:,} simulations …")
    margins = run_simulations(mpios, cand_cols, dept_sh, nat_sh, N_SIM, SEED)

    mean_margin = int(sum(margins) / len(margins))
    ci_lo       = int(percentile(margins, 2.5))
    ci_hi       = int(percentile(margins, 97.5))
    prob_1st    = round(sum(1 for m in margins if m > 0) / len(margins) * 100, 1)
    prob_2nd    = round(100 - prob_1st, 1)

    # Candidate summary
    cand_summary = []
    for col in obs_ranked:
        c     = cand_meta[col]
        votes = obs_totals[col]
        cand_summary.append({
            "code":         c["code"],
            "nombre":       c.get("nombre", ""),
            "color":        c.get("color", "#666"),
            "votes":        votes,
            "pct_emitidos": round(votes / total_vv_obs * 100, 3) if total_vv_obs else 0,
            "prob_runoff":  100.0 if c["code"] in (BATTLE_1ST, BATTLE_2ND) else 0.0,
        })

    result = {
        "generated_at":         datetime.datetime.utcnow().isoformat() + "Z",
        "pct_mesas":            pct_mesas,
        "mesas_contabilizadas": total_me,
        "mesas_remaining":      total_mt - total_me,
        "mesas_total":          total_mt,
        "n_sims":               N_SIM,
        "candidates":           cand_summary,
        "battle": {
            "cand_2nd":            BATTLE_1ST,
            "cand_3rd":            BATTLE_2ND,
            "nombre_2nd":          cand_meta[f"cand_{BATTLE_1ST}"]["nombre"],
            "nombre_3rd":          cand_meta[f"cand_{BATTLE_2ND}"]["nombre"],
            "color_2nd":           cand_meta[f"cand_{BATTLE_1ST}"]["color"],
            "color_3rd":           cand_meta[f"cand_{BATTLE_2ND}"]["color"],
            "prob_2nd_pct":        prob_1st,
            "prob_3rd_pct":        prob_2nd,
            "mean_margin_votes":   mean_margin,
            "ci_lo_votes":         ci_lo,
            "ci_hi_votes":         ci_hi,
            "margin_distribution": make_histogram(margins, N_BINS),
        },
    }

    with open(OUT_JSON, "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nSaved → {OUT_JSON.name}")
    print(f"  {cand_meta[f'cand_{BATTLE_1ST}']['nombre'].split()[0]} margin: "
          f"{mean_margin:+,} votes  CI [{ci_lo:+,}, {ci_hi:+,}]")
    print(f"  P(Cepeda > Abelardo): {prob_1st:.1f}%")
    print()
    for c in cand_summary[:5]:
        print(f"  {c['pct_emitidos']:5.2f}%  {c['votes']:>10,}  {c['nombre']}")


if __name__ == "__main__":
    main()
