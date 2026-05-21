"""
05_forecast.py — Monte Carlo forecast for Colombia 2026 primera vuelta.

Reads the mesa-level results CSV and produces a probabilistic forecast of
which two candidates will advance to the segunda vuelta (runoff).

Inputs:
  data/results/colombia_2026_mesa_primera.csv
  data/candidates.json

Output:
  data/forecast.json

Empty state (all mesas at 0):
  - pct_mesas = 0.0
  - First 2 candidates in JSON order get prob_runoff = 100.0
  - All others get prob_runoff = 0.0
  - battle.margin_distribution is a flat uniform histogram

Live state (some mesas counted):
  - Stratified resampling by municipio: uncounted mesas sampled from counted
    mesas in the same municipio (or nationally if no counted mesas in that mpio)
  - 10,000 simulations → prob_runoff = fraction of sims where candidate is top 2
  - battle: 2nd vs 3rd most likely candidates, with margin distribution
"""

import csv
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"

MESA_CSV   = RESULTS / "colombia_2026_mesa_primera.csv"
CANDS_JSON = OUT / "candidates.json"

N_SIMS     = 10_000
HIST_BINS  = 20
RANDOM_SEED = 42


# ── Helpers ────────────────────────────────────────────────────────────────────

def sum_col(rows: list[dict], col: str) -> int:
    return sum(int(r.get(col) or 0) for r in rows)


def linspace(start: float, stop: float, n: int) -> list[float]:
    if n <= 1:
        return [start]
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


def histogram(values: list[float], edges: list[float]) -> list[int]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
        else:
            if values and v >= edges[-1]:
                counts[-1] += 1
    return counts


# ── Empty-state output ─────────────────────────────────────────────────────────

def write_empty_forecast(candidates: list[dict]) -> None:
    """Write forecast.json for the pre-election zero state."""
    # Flat histogram edges: -50 to +50 pct, 21 edges = 20 bins
    edges  = [round(-50.0 + i * 5.0, 1) for i in range(HIST_BINS + 1)]
    counts = [N_SIMS // HIST_BINS] * HIST_BINS

    cand_out = []
    for i, c in enumerate(candidates):
        cand_out.append({
            "code":              c["code"],
            "nombre":            c.get("nombre", c["code"]),
            "partido":           c.get("partido", ""),
            "color":             c.get("color", "#888"),
            "votes_current":     0,
            "vote_pct_current":  0.0,
            "vote_pct_projected": 0.0,
            "ci_low_pct":        0.0,
            "ci_high_pct":       0.0,
            "prob_runoff":       100.0 if i < 2 else 0.0,
        })

    out = {
        "pct_mesas":     0.0,
        "n_simulations": N_SIMS,
        "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates":    cand_out,
        "battle": {
            "left_code":            candidates[0]["code"],
            "right_code":           candidates[1]["code"],
            "left_nombre":          candidates[0].get("nombre", candidates[0]["code"]),
            "right_nombre":         candidates[1].get("nombre", candidates[1]["code"]),
            "left_color":           candidates[0].get("color", "#888"),
            "right_color":          candidates[1].get("color", "#888"),
            "margin_pct_projected": 0.0,
            "ci_low_pct":           0.0,
            "ci_high_pct":          0.0,
            "margin_distribution": {
                "edges":  edges,
                "counts": counts,
            },
        },
    }

    path = OUT / "forecast.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved → {path.name}  (empty state)")


# ── Live forecast ──────────────────────────────────────────────────────────────

def run_forecast(candidates: list[dict], rows: list[dict],
                 counted: list[dict], uncounted: list[dict],
                 total_mesas: int, counted_mesas: int) -> None:
    """Run Monte Carlo simulations and write forecast.json."""
    rng = random.Random(RANDOM_SEED)

    cand_codes = [c["code"] for c in candidates]
    cand_cols  = [f"cand_{code}" for code in cand_codes]

    # Current vote totals from counted mesas
    current_votes = {code: sum_col(counted, f"cand_{code}") for code in cand_codes}
    total_current_valid = sum(current_votes.values())

    # Build per-municipio pools of counted mesas for resampling
    mpio_counted: dict[str, list[dict]] = defaultdict(list)
    for r in counted:
        mpio_counted[r["mpio_reg_code_7"]].append(r)
    national_pool = counted  # fallback

    # Simulations
    runoff_counts = defaultdict(int)   # code → times in top 2
    projected_pcts: dict[str, list[float]] = defaultdict(list)
    margins: list[float] = []

    for _ in range(N_SIMS):
        sim_votes = dict(current_votes)

        for mesa in uncounted:
            mpio = mesa["mpio_reg_code_7"]
            pool = mpio_counted.get(mpio) or national_pool
            if not pool:
                continue
            sample = rng.choice(pool)
            for code in cand_codes:
                col = f"cand_{code}"
                sim_votes[code] = sim_votes.get(code, 0) + int(sample.get(col) or 0)

        total_valid = max(sum(sim_votes.values()), 1)

        # Rank candidates
        ranked = sorted(cand_codes, key=lambda c: sim_votes.get(c, 0), reverse=True)
        top2   = set(ranked[:2])
        for code in top2:
            runoff_counts[code] += 1

        for code in cand_codes:
            projected_pcts[code].append(sim_votes.get(code, 0) / total_valid * 100)

        # Margin: 2nd place pct - 3rd place pct
        if len(ranked) >= 3:
            m = (sim_votes.get(ranked[1], 0) - sim_votes.get(ranked[2], 0)) / total_valid * 100
            margins.append(m)

    pct_mesas = round(counted_mesas / max(total_mesas, 1) * 100, 2)
    total_current_valid_safe = max(total_current_valid, 1)

    # Rank candidates by prob_runoff for battle selection
    by_prob = sorted(cand_codes, key=lambda c: runoff_counts.get(c, 0), reverse=True)
    battle_left  = by_prob[0] if len(by_prob) > 0 else cand_codes[0]
    battle_right = by_prob[1] if len(by_prob) > 1 else cand_codes[1]

    # Histogram for margin distribution
    if margins:
        lo = min(margins)
        hi = max(margins)
        span = max(hi - lo, 1.0)
        edges  = [round(lo + i * span / HIST_BINS, 2) for i in range(HIST_BINS + 1)]
        counts = histogram(margins, edges)
    else:
        edges  = [round(-50.0 + i * 5.0, 1) for i in range(HIST_BINS + 1)]
        counts = [N_SIMS // HIST_BINS] * HIST_BINS

    # Build candidate output (preserve JSON order)
    cand_out = []
    for c in candidates:
        code  = c["code"]
        pcts  = projected_pcts.get(code, [0.0])
        pcts_sorted = sorted(pcts)
        n     = len(pcts_sorted)
        ci_lo = pcts_sorted[max(0, int(n * 0.025))]
        ci_hi = pcts_sorted[min(n - 1, int(n * 0.975))]
        mean  = sum(pcts) / n if pcts else 0.0

        cand_out.append({
            "code":              code,
            "nombre":            c.get("nombre", code),
            "partido":           c.get("partido", ""),
            "color":             c.get("color", "#888"),
            "votes_current":     current_votes.get(code, 0),
            "vote_pct_current":  round(current_votes.get(code, 0) / total_current_valid_safe * 100, 2),
            "vote_pct_projected": round(mean, 2),
            "ci_low_pct":        round(ci_lo, 2),
            "ci_high_pct":       round(ci_hi, 2),
            "prob_runoff":       round(runoff_counts.get(code, 0) / N_SIMS * 100, 1),
        })

    # Battle stats
    def _margin_stats(left_code, right_code):
        left_pcts  = projected_pcts.get(left_code, [0.0])
        right_pcts = projected_pcts.get(right_code, [0.0])
        diffs = [l - r for l, r in zip(left_pcts, right_pcts)]
        diffs_sorted = sorted(diffs)
        n = len(diffs_sorted)
        return {
            "margin_pct_projected": round(sum(diffs) / n if diffs else 0.0, 2),
            "ci_low_pct":  round(diffs_sorted[max(0, int(n * 0.025))], 2),
            "ci_high_pct": round(diffs_sorted[min(n - 1, int(n * 0.975))], 2),
        }

    bl_info = next((c for c in candidates if c["code"] == battle_left),  candidates[0])
    br_info = next((c for c in candidates if c["code"] == battle_right), candidates[1])
    mstats  = _margin_stats(battle_left, battle_right)

    out = {
        "pct_mesas":     pct_mesas,
        "n_simulations": N_SIMS,
        "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates":    cand_out,
        "battle": {
            "left_code":            battle_left,
            "right_code":           battle_right,
            "left_nombre":          bl_info.get("nombre", battle_left),
            "right_nombre":         br_info.get("nombre", battle_right),
            "left_color":           bl_info.get("color", "#888"),
            "right_color":          br_info.get("color", "#888"),
            "margin_pct_projected": mstats["margin_pct_projected"],
            "ci_low_pct":           mstats["ci_low_pct"],
            "ci_high_pct":          mstats["ci_high_pct"],
            "margin_distribution": {
                "edges":  edges,
                "counts": counts,
            },
        },
    }

    path = OUT / "forecast.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved → {path.name}  (pct_mesas={pct_mesas:.1f}%)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    with open(CANDS_JSON) as f:
        candidates = json.load(f)

    with open(MESA_CSV) as f:
        rows = list(csv.DictReader(f))

    total_mesas   = len(rows)
    counted       = [r for r in rows if int(r.get("mesas_escrutadas") or 0) > 0]
    uncounted     = [r for r in rows if int(r.get("mesas_escrutadas") or 0) == 0]
    counted_mesas = len(counted)

    print(f"Mesas: {counted_mesas:,} counted / {total_mesas:,} total")

    if counted_mesas == 0:
        print("Empty state — writing default forecast.")
        write_empty_forecast(candidates)
        return

    print(f"Running {N_SIMS:,} simulations …")
    run_forecast(candidates, rows, counted, uncounted, total_mesas, counted_mesas)


if __name__ == "__main__":
    main()
