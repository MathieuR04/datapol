"""
04_aggregate_stats.py — Peru 2026 EG Primera Vuelta
Compute aggregate statistics from district-level results.

Outputs:
  data/aggregate_stats.json    ← national totals, per-candidate summary
  data/forecast.json           ← placeholder (populated by 05_forecast.py)
"""

import datetime
import json
import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"


def load_candidates() -> list[dict]:
    with open(DATA_DIR / "candidates.json") as f:
        return json.load(f)


def main():
    candidates = load_candidates()
    cand_cols  = [f"cand_{c['codigo']}" for c in candidates]

    csv_path = RESULTS / "peru_2026eg_distrito_primera.csv"
    if not csv_path.exists():
        print(f"No results file: {csv_path}")
        return

    # Load and sum all districts
    totals: dict[str, int] = {
        "votos_validos":  0,
        "votos_blancos":  0,
        "votos_nulos":    0,
        "votos_emitidos": 0,
        "actas_contabilizadas": 0,
        "actas_total":    0,
    }
    for col in cand_cols:
        totals[col] = 0

    n_distritos = 0
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            n_distritos += 1
            for key in totals:
                totals[key] += int(row.get(key, 0) or 0)

    # votos_emitidos comes directly from the API (totalVotosEmitidos); don't re-derive.

    # Per-candidate stats
    cand_summary = []
    for cand in candidates:
        col   = f"cand_{cand['codigo']}"
        votes = totals.get(col, 0)
        vv    = totals["votos_validos"] or 1
        ve    = totals["votos_emitidos"] or 1
        cand_summary.append({
            "codigo":  cand["codigo"],
            "nombre":  cand.get("nombre", ""),
            "partido": cand.get("partido", ""),
            "color":   cand.get("color", "#888"),
            "votos":   votes,
            "pct_validos":  round(votes / vv * 100, 3),
            "pct_emitidos": round(votes / ve * 100, 3),
        })
    cand_summary.sort(key=lambda x: -x["votos"])

    # Electoral roll totals
    roll_electores = 0
    roll_path = METADATA / "peru_2026_distrito_electoral_roll.csv"
    if roll_path.exists():
        with open(roll_path) as f:
            for row in csv.DictReader(f):
                roll_electores += int(row.get("num_electores", 0) or 0)

    stats = {
        "n_distritos":         n_distritos,
        "num_electores":       roll_electores,
        "votos_emitidos":      totals["votos_emitidos"],
        "votos_validos":       totals["votos_validos"],
        "votos_blancos":       totals["votos_blancos"],
        "votos_nulos":         totals["votos_nulos"],
        "actas_contabilizadas": totals["actas_contabilizadas"],
        "actas_total":         totals["actas_total"],
        "participacion_pct":   round(
            totals["votos_emitidos"] / max(roll_electores, 1) * 100, 2),
        "actas_pct":           round(
            totals["actas_contabilizadas"] / max(totals["actas_total"], 1) * 100, 2),
        "candidatos":          cand_summary,
        "generated_at":        datetime.datetime.utcnow().isoformat() + "Z",
    }

    out_path = DATA_DIR / "aggregate_stats.json"
    with open(out_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"Saved → {out_path.name}")
    print(f"  {n_distritos:,} distritos")
    print(f"  Votos válidos : {stats['votos_validos']:>12,}")
    print(f"  Votos blancos : {stats['votos_blancos']:>12,}")
    print(f"  Votos nulos   : {stats['votos_nulos']:>12,}")
    print(f"  Participación : {stats['participacion_pct']:.1f}%")
    print(f"  Actas         : {stats['actas_pct']:.1f}%")
    print()
    for c in cand_summary[:7]:
        print(f"  {c['pct_validos']:5.2f}%  {c['votos']:>10,}  {c['nombre']}")


if __name__ == "__main__":
    main()
