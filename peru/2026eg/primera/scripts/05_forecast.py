"""
05_forecast.py — Peru 2026 EG Primera Vuelta
Extrapolate final district-level results from partial mesa returns.

Uses mesa-level data (02b) to project totals for districts with incomplete
actas, then re-aggregates to produce early-call projections.

Method: for each district with actas_contabilizadas < actas_total,
scale reported candidate votes by (actas_total / actas_contabilizadas).

Inputs:
  data/results/peru_2026eg_distrito_primera.csv   ← from 02a (partial results)
  data/results/peru_2026eg_mesa_primera.csv        ← from 02b (mesa-level, optional)
  data/candidates.json

Output:
  data/forecast.json
"""

import csv
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"
METADATA   = SCRIPT_DIR.parent.parent.parent / "metadata"


def load_candidates() -> list[dict]:
    with open(DATA_DIR / "candidates.json") as f:
        return json.load(f)


def main():
    candidates = load_candidates()
    cand_cols  = [f"cand_{c['codigo']}" for c in candidates]

    dist_csv = RESULTS / "peru_2026eg_distrito_primera.csv"
    if not dist_csv.exists():
        print(f"No district results: {dist_csv}")
        return

    rows = []
    with open(dist_csv) as f:
        rows = list(csv.DictReader(f))

    # Total reported across all districts
    reported:  dict[str, int] = {col: 0 for col in cand_cols}
    projected: dict[str, int] = {col: 0 for col in cand_cols}
    actas_ok   = 0
    actas_tot  = 0

    for row in rows:
        contab = int(row.get("actas_contabilizadas", 0) or 0)
        total  = int(row.get("actas_total", 0) or 0)
        actas_ok  += contab
        actas_tot += total

        scale = (total / contab) if (contab > 0 and total > contab) else 1.0

        for col in cand_cols:
            v = int(row.get(col, 0) or 0)
            reported[col]  += v
            projected[col] += round(v * scale)

    pct_reported = round(actas_ok / max(actas_tot, 1) * 100, 2)
    total_valid_r = sum(reported.values())
    total_valid_p = sum(projected.values())

    # Per-candidate summary
    cand_out = []
    for cand in candidates:
        col = f"cand_{cand['codigo']}"
        cand_out.append({
            "codigo":         cand["codigo"],
            "nombre":         cand.get("nombre", ""),
            "partido":        cand.get("partido", ""),
            "color":          cand.get("color", "#888"),
            "votos_rep":      reported.get(col, 0),
            "votos_proj":     projected.get(col, 0),
            "pct_rep":        round(reported.get(col, 0) / max(total_valid_r, 1) * 100, 3),
            "pct_proj":       round(projected.get(col, 0) / max(total_valid_p, 1) * 100, 3),
        })
    cand_out.sort(key=lambda x: -x["votos_proj"])

    forecast = {
        "actas_contabilizadas": actas_ok,
        "actas_total":          actas_tot,
        "pct_contabilizadas":   pct_reported,
        "votos_validos_rep":    total_valid_r,
        "votos_validos_proj":   total_valid_p,
        "candidatos":           cand_out,
    }

    out_path = DATA_DIR / "forecast.json"
    with open(out_path, "w") as f:
        json.dump(forecast, f, ensure_ascii=False, indent=2)

    print(f"Saved → {out_path.name}")
    print(f"  Actas: {pct_reported:.1f}% ({actas_ok:,}/{actas_tot:,})")
    print()
    for c in cand_out[:5]:
        print(f"  Rep {c['pct_rep']:5.2f}%  Proj {c['pct_proj']:5.2f}%  {c['nombre']}")


if __name__ == "__main__":
    main()
