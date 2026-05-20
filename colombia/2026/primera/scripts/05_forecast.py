"""
forecast.py  —  Colombia Presidencial 2026, Primera Vuelta
Monte Carlo simulation: probability of each candidate entering the runoff.

Method:
  1. Load mesa-level results (partial escrutinio).
  2. For each un-scrutinised mesa, estimate vote shares using the geographic
     mean of already-counted mesas in the same group (mpio → dept → national),
     then sample from a Dirichlet distribution with low concentration (wide CI).
  3. Run N simulations; record who finishes top-2 in each.
  4. P(runoff) = fraction of simulations where candidate is top-2.

Design principle: prefer HIGH volatility — use low Dirichlet concentration
(alpha_scale) so confidence intervals are wide and the true result is unlikely
to fall outside them.

Outputs:
  presidencial2026/processed/forecast.json
"""

import json
import csv
import random
import math
import datetime
from pathlib import Path
from collections import defaultdict

SHARED = Path(__file__).parent.parent.parent / "data" / "processed"
OUT    = Path(__file__).parent.parent.parent / "data" / "presidencial2026" / "processed"

N_SIM        = 10_000    # Monte Carlo draws
ALPHA_SCALE  = 5.0       # Dirichlet concentration — lower = more uncertain
MIN_MESAS_FOR_ESTIMATE = 3  # need at least this many mesas in a group to use its mean


def load_data():
    """Load mesa results, candidate list, and puestos master."""
    with open(OUT / "candidates.json") as f:
        candidates = json.load(f)
    cand_codes = [c["code"] for c in candidates]

    master = {}
    with open(METADATA / "colombia_2026_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            master[row["puesto_code"]] = row

    mesas = []
    mesa_path = OUT / "resultados_mesas.csv"
    if mesa_path.exists():
        with open(mesa_path) as f:
            for row in csv.DictReader(f):
                mesas.append(row)

    return candidates, cand_codes, master, mesas


def get_shares(rows: list[dict], cand_codes: list[str]) -> list[float]:
    """Return mean vote-share vector across a group of rows."""
    totals = [0.0] * len(cand_codes)
    grand  = 0.0
    for row in rows:
        vv = float(row.get("votos_validos") or 0)
        if vv <= 0: continue
        for i, c in enumerate(cand_codes):
            totals[i] += float(row.get(c) or 0)
        grand += vv
    if grand <= 0:
        return [1.0 / len(cand_codes)] * len(cand_codes)
    return [t / grand for t in totals]


def dirichlet_sample(alpha: list[float]) -> list[float]:
    """Sample from Dirichlet using gamma variates."""
    gammas = [-math.log(random.random()) * (1.0 / a) if a > 0 else 0
              for a in alpha]
    # Correct: Dirichlet via gamma(alpha_i, 1)
    gammas = [random.gammavariate(a, 1.0) for a in alpha]
    s = sum(gammas)
    return [g / s for g in gammas]


def run_forecast():
    candidates, cand_codes, master, mesas = load_data()

    # Separate counted vs uncounted
    counted   = [m for m in mesas if int(m.get("mesas_escrutadas") or 0) > 0]
    uncounted = [m for m in mesas if int(m.get("mesas_escrutadas") or 0) == 0]

    n_counted   = sum(int(m.get("mesas_escrutadas") or 0) for m in mesas)
    n_total     = sum(int(m.get("mesas_total") or 0) for m in mesas)

    # Build geographic group means from counted mesas
    mpio_groups  = defaultdict(list)
    dept_groups  = defaultdict(list)
    national_all = []
    for m in counted:
        info = master.get(m.get("puesto_code",""), {})
        mpio = info.get("mpio_reg_code_7","")
        dept = info.get("dept_reg_code","")
        if mpio: mpio_groups[mpio].append(m)
        if dept: dept_groups[dept].append(m)
        national_all.append(m)

    def group_alpha(m: dict) -> list[float]:
        """Return Dirichlet alpha for un-scrutinised mesa m."""
        info = master.get(m.get("puesto_code",""), {})
        mpio = info.get("mpio_reg_code_7","")
        dept = info.get("dept_reg_code","")
        # Prefer finest geographic group with enough data
        for group in [mpio_groups.get(mpio,[]),
                      dept_groups.get(dept,[]),
                      national_all]:
            if len(group) >= MIN_MESAS_FOR_ESTIMATE:
                shares = get_shares(group, cand_codes)
                return [s * ALPHA_SCALE for s in shares]
        # No data at all: uniform prior
        k = len(cand_codes)
        return [ALPHA_SCALE / k] * k

    # Aggregate current vote totals from counted mesas
    current_totals = [0.0] * len(cand_codes)
    current_vv     = 0.0
    for m in counted:
        vv = float(m.get("votos_validos") or 0)
        for i, c in enumerate(cand_codes):
            current_totals[i] += float(m.get(c) or 0)
        current_vv += vv

    # Estimate uncounted mesa sizes (use censo as proxy for votantes)
    uncounted_census = [float(master.get(m.get("puesto_code",""),{}).get("num_mesas",1) or 1)
                        for m in uncounted]
    total_uncounted_census = sum(uncounted_census) or 1

    # Run simulations
    runoff_counts = [0] * len(cand_codes)
    first_counts  = [0] * len(cand_codes)

    # Pre-compute alpha for each uncounted mesa
    alphas = [group_alpha(m) for m in uncounted]

    # Estimate typical votes per "mesa unit"
    votes_per_mesa = current_vv / n_counted if n_counted > 0 else 200.0

    for _ in range(N_SIM):
        sim_totals = list(current_totals)
        for j, m in enumerate(uncounted):
            n_mesas = int(m.get("mesas_total") or 1)
            est_votes = votes_per_mesa * n_mesas
            shares = dirichlet_sample(alphas[j])
            for i, s in enumerate(shares):
                sim_totals[i] += s * est_votes

        # Find top-2
        ranked = sorted(range(len(cand_codes)), key=lambda i: -sim_totals[i])
        runoff_set = set(ranked[:2])
        for i in runoff_set:
            runoff_counts[i] += 1
        first_counts[ranked[0]] += 1

    # Build output
    vv_now = current_vv or 1
    cand_out = []
    for i, c in enumerate(candidates):
        code = c["code"]
        v = current_totals[i]
        ci_sims = []
        # Quick CI estimate: run 200 extra sims to get percentile
        if uncounted:
            for _ in range(200):
                t = current_totals[i]
                for j, m in enumerate(uncounted):
                    n_mesas = int(m.get("mesas_total") or 1)
                    shares = dirichlet_sample(alphas[j])
                    t += shares[i] * votes_per_mesa * n_mesas
                grand = sum(current_totals) + sum(
                    sum(dirichlet_sample(alphas[j])[k] * votes_per_mesa * int(uncounted[j].get("mesas_total") or 1)
                        for k in range(len(cand_codes)))
                    for j in range(len(uncounted)))
                ci_sims.append(t / (grand or 1) * 100)
            ci_sims.sort()
            ci_low  = round(ci_sims[10],  1)   # 5th percentile
            ci_high = round(ci_sims[190], 1)   # 95th percentile
        else:
            ci_low = ci_high = round(v / vv_now * 100, 1)

        cand_out.append({
            "code":             code,
            "nombre":           c["nombre"],
            "partido":          c.get("partido",""),
            "color":            c.get("color","#888"),
            "prob_runoff":      round(runoff_counts[i] / N_SIM * 100, 1),
            "prob_1st":         round(first_counts[i]  / N_SIM * 100, 1),
            "votes_current":    int(v),
            "vote_pct_current": round(v / vv_now * 100, 2) if vv_now > 0 else 0.0,
            "poll_pct":         c.get("poll_pct", None),
            "ci_low":           ci_low,
            "ci_high":          ci_high,
        })

    # Sort by prob_runoff desc
    cand_out.sort(key=lambda x: -x["prob_runoff"])

    forecast = {
        "note":              "Simulación Monte Carlo en tiempo real basada en mesas escrutadas.",
        "mesas_escrutadas":  n_counted,
        "mesas_total":       n_total,
        "pct_mesas":         round(n_counted / n_total * 100, 2) if n_total else 0.0,
        "n_simulations":     N_SIM,
        "last_updated":      datetime.datetime.utcnow().isoformat() + "Z",
        "candidates":        cand_out,
    }

    with open(OUT / "forecast.json", "w") as f:
        json.dump(forecast, f, ensure_ascii=False, indent=2)
    print(f"Saved → forecast.json  ({N_SIM:,} simulations, "
          f"{n_counted:,}/{n_total:,} mesas)")
    for c in cand_out[:5]:
        print(f"  {c['nombre'][:35]:35s}  {c['vote_pct_current']:5.1f}%  "
              f"P(runoff)={c['prob_runoff']:.1f}%  [{c['ci_low']:.1f}–{c['ci_high']:.1f}%]")


if __name__ == "__main__":
    run_forecast()
