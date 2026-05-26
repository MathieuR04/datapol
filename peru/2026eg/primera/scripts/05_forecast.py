"""
05_forecast.py — Peru 2026 EG Primera Vuelta
Monte Carlo bootstrap to project final results and estimate runoff probabilities.

For each simulation, districts are resampled with replacement (bootstrap) to
capture geographic uncertainty.  Even with 100% actas the bootstrap produces
non-trivial CIs when the race between 2nd and 3rd is close.

Output: data/forecast.json  (Colombia-compatible structure)
"""

import csv
import json
import math
import random
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR  = Path(__file__).parent
DATA_DIR    = SCRIPT_DIR.parent / "data"
RESULTS     = DATA_DIR / "results"

N_SIM = 10_000
SEED  = 42


def load_candidates() -> list[dict]:
    with open(DATA_DIR / "candidates.json") as f:
        return json.load(f)


def main():
    random.seed(SEED)
    candidates = load_candidates()
    cand_cols  = [f"cand_{c['codigo']}" for c in candidates]
    cand_by_col = {f"cand_{c['codigo']}": c for c in candidates}

    dist_csv = RESULTS / "peru_2026eg_distrito_primera.csv"
    if not dist_csv.exists():
        print(f"No district results: {dist_csv}")
        return

    rows = []
    with open(dist_csv) as f:
        for row in csv.DictReader(f):
            rows.append(row)

    # ── Actual (reported) totals ──────────────────────────────────────────────
    actas_ok  = sum(int(r.get("actas_contabilizadas", 0) or 0) for r in rows)
    actas_tot = sum(int(r.get("actas_total",          0) or 0) for r in rows)
    pct_actas = round(actas_ok / max(actas_tot, 1) * 100, 2)

    actual_votes: dict[str, int] = defaultdict(int)
    for row in rows:
        for col in cand_cols:
            actual_votes[col] += int(row.get(col, 0) or 0)

    total_valid = sum(actual_votes.values()) or 1

    # Rank by actual votes
    ranked = sorted(cand_cols, key=lambda c: -actual_votes[c])

    # ── Monte Carlo bootstrap ─────────────────────────────────────────────────
    # Sample districts with replacement; partial districts are scaled up first.
    # Precompute scale factors.
    scaled_rows = []
    for row in rows:
        ac = int(row.get("actas_contabilizadas", 0) or 0)
        at = int(row.get("actas_total",          0) or 0)
        scale = (at / ac) if ac > 0 and at > ac else 1.0
        entry = {}
        for col in cand_cols:
            entry[col] = round(int(row.get(col, 0) or 0) * scale)
        scaled_rows.append(entry)

    n = len(scaled_rows)
    in_top2_count: dict[str, int] = defaultdict(int)
    sim_pcts: dict[str, list] = {col: [] for col in cand_cols}
    # For battle: track margin (2nd pct - 3rd pct) per simulation
    battle_margins: list[float] = []

    for _ in range(N_SIM):
        sample = random.choices(scaled_rows, k=n)
        sim_v: dict[str, int] = defaultdict(int)
        for row in sample:
            for col in cand_cols:
                sim_v[col] += row[col]
        sim_total = sum(sim_v.values()) or 1

        sim_sorted = sorted(cand_cols, key=lambda c: -sim_v[c])
        top2 = set(sim_sorted[:2])
        for col in top2:
            in_top2_count[col] += 1

        for col in cand_cols:
            sim_pcts[col].append(sim_v[col] / sim_total * 100)

        # Battle margin: 2nd - 3rd in pct points
        pct2 = sim_v[sim_sorted[1]] / sim_total * 100
        pct3 = sim_v[sim_sorted[2]] / sim_total * 100
        # sign: positive = actual-2nd-place ahead
        sign = 1 if sim_sorted[1] == ranked[1] else -1
        battle_margins.append(sign * (pct2 - pct3))

    # ── Per-candidate summary ─────────────────────────────────────────────────
    def percentile(lst, p):
        s = sorted(lst)
        i = p / 100 * (len(s) - 1)
        lo, hi = int(i), min(int(i) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (i - lo)

    cand_out = []
    for col in ranked:
        c = cand_by_col[col]
        pcts = sim_pcts[col]
        cand_out.append({
            "code":               c["codigo"],
            "nombre":             c.get("nombre", ""),
            "partido":            c.get("partido", ""),
            "color":              c.get("color", "#888"),
            "prob_runoff":        round(in_top2_count[col] / N_SIM * 100, 1),
            "votes_current":      actual_votes[col],
            "vote_pct_projected": round(actual_votes[col] / total_valid * 100, 3),
            "ci_low_pct":         round(percentile(pcts, 2.5), 2),
            "ci_high_pct":        round(percentile(pcts, 97.5), 2),
        })

    # ── Battle (2nd vs 3rd) ───────────────────────────────────────────────────
    left_col  = ranked[1]   # actual 2nd place
    right_col = ranked[2]   # actual 3rd place
    left_c    = cand_by_col[left_col]
    right_c   = cand_by_col[right_col]

    margin_proj = actual_votes[left_col] / total_valid * 100 - actual_votes[right_col] / total_valid * 100

    # Margin distribution histogram (40 bins)
    mn = min(battle_margins)
    mx = max(battle_margins)
    pad = max(abs(mn), abs(mx)) * 0.05
    lo = mn - pad
    hi = mx + pad
    n_bins = 40
    bw = (hi - lo) / n_bins
    counts = [0] * n_bins
    for m in battle_margins:
        i = min(int((m - lo) / bw), n_bins - 1)
        counts[i] += 1
    edges = [round(lo + i * bw, 3) for i in range(n_bins + 1)]

    battle = {
        "left_code":        left_c["codigo"],
        "right_code":       right_c["codigo"],
        "left_nombre":      left_c.get("nombre", ""),
        "right_nombre":     right_c.get("nombre", ""),
        "left_color":       left_c.get("color", "#888"),
        "right_color":      right_c.get("color", "#888"),
        "margin_pct_projected": round(margin_proj, 3),
        "ci_low_pct":       round(percentile(battle_margins, 2.5), 2),
        "ci_high_pct":      round(percentile(battle_margins, 97.5), 2),
        "margin_distribution": {"edges": edges, "counts": counts},
    }

    forecast = {
        "pct_mesas":    pct_actas,
        "n_simulations": N_SIM,
        "candidates":   cand_out,
        "battle":       battle,
    }

    out_path = DATA_DIR / "forecast.json"
    with open(out_path, "w") as f:
        json.dump(forecast, f, ensure_ascii=False, indent=2)

    print(f"Saved → {out_path.name}  ({N_SIM:,} sims, {pct_actas:.1f}% actas)")
    print(f"  Battle: {left_c['nombre'].split()[0]} vs {right_c['nombre'].split()[0]}")
    print(f"  Margin: {margin_proj:+.3f}pp  CI [{battle['ci_low_pct']:+.2f}, {battle['ci_high_pct']:+.2f}]pp")
    print()
    for c in cand_out[:5]:
        print(f"  {c['prob_runoff']:5.1f}%  {c['vote_pct_projected']:5.2f}%  {c['nombre']}")


if __name__ == "__main__":
    main()
