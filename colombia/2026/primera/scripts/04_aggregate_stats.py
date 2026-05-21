"""
04_aggregate_stats.py — Aggregate national primera vuelta stats from results CSV.

Reads all municipio rows (including exterior) and writes data/aggregate_stats.json
for the frontend.

Inputs:
  data/results/colombia_2026_municipio_primera.csv
  metadata/colombia_2026_municipio_electoral_roll.csv
  data/candidates.json

Output:
  data/aggregate_stats.json

  {
    "votantes": 0,
    "votos_validos": 0,
    "votos_blanco": 0,
    "votos_nulos": 0,
    "votos_no_marcados": 0,
    "mesas_escrutadas": 0,
    "mesas_total": 126647,
    "censo": 41287084,
    "candidates": [
      {"code": "cepeda", "votes": 0},
      ...
    ]
  }

censo and mesas_total come from the CSV when present; else from the electoral roll.
"""

import csv
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"

MPIO_CSV  = RESULTS / "colombia_2026_municipio_primera.csv"
ROLL_CSV  = METADATA / "colombia_2026_municipio_electoral_roll.csv"
CANDS_JSON = OUT / "candidates.json"


def sum_col(rows: list[dict], col: str) -> int:
    return sum(int(r.get(col) or 0) for r in rows)


def main():
    with open(MPIO_CSV) as f:
        rows = list(csv.DictReader(f))

    with open(CANDS_JSON) as f:
        candidates = json.load(f)

    # censo and mesas_total: use CSV values when present and non-zero;
    # fall back to electoral roll when CSV lacks these columns (e.g. mock).
    csv_censo     = sum_col(rows, "censo")
    csv_mesas_tot = sum_col(rows, "mesas_total")

    if not csv_censo or not csv_mesas_tot:
        print("  CSV missing censo/mesas_total — falling back to electoral roll")
        with open(ROLL_CSV) as f:
            roll = list(csv.DictReader(f))
        csv_censo     = csv_censo     or sum_col(roll, "censo")
        csv_mesas_tot = csv_mesas_tot or sum_col(roll, "num_mesas")

    stats = {
        "votantes":          sum_col(rows, "votantes"),
        "votos_validos":     sum_col(rows, "votos_validos"),
        "votos_blanco":      sum_col(rows, "votos_blanco"),
        "votos_nulos":       sum_col(rows, "votos_nulos"),
        "votos_no_marcados": sum_col(rows, "votos_no_marcados"),
        "mesas_escrutadas":  sum_col(rows, "mesas_escrutadas"),
        "mesas_total":       csv_mesas_tot,
        "censo":             csv_censo,
        "candidates": [
            {"code": c["code"], "votes": sum_col(rows, f"cand_{c['code']}")}
            for c in candidates
        ],
    }

    print(f"Votantes:        {stats['votantes']:,}")
    print(f"Votos válidos:   {stats['votos_validos']:,}")
    print(f"Mesas:           {stats['mesas_escrutadas']:,}/{stats['mesas_total']:,}")
    print(f"Censo:           {stats['censo']:,}")

    path = OUT / "aggregate_stats.json"
    with open(path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"Saved → {path.name}")


if __name__ == "__main__":
    main()
