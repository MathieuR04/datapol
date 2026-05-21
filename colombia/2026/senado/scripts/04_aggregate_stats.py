"""
04_aggregate_stats.py — Aggregate national election stats from results CSVs.

Reads all municipio rows (including exterior) from the results CSVs and
the electoral roll, then writes data/aggregate_stats.json for the frontend.

Inputs:
  data/results/colombia_2026_municipio_senado_nacional.csv
  data/results/colombia_2026_municipio_senado_indigena.csv
  metadata/colombia_2026_municipio_electoral_roll.csv

Output:
  data/aggregate_stats.json

  {
    "nacional":  { votantes, votos_validos, votos_blanco, votos_nulos,
                   votos_no_marcados, mesas_escrutadas, mesas_total, censo },
    "indigena":  { votantes, votos_validos, votos_blanco, votos_nulos,
                   votos_no_marcados, mesas_escrutadas, mesas_total, censo }
  }

  censo and mesas_total come from the electoral roll (authoritative metadata).
  All vote / mesa fields come from the CSVs (actual results, all municipios).
"""

import csv
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"

NAT_CSV  = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
IND_CSV  = RESULTS / "colombia_2026_municipio_senado_indigena.csv"
ROLL_CSV = METADATA / "colombia_2026_municipio_electoral_roll.csv"


def sum_col(rows: list[dict], col: str) -> int:
    return sum(int(r.get(col) or 0) for r in rows)


def main():
    # ── Nacional CSV (all municipios incl. exterior) ──────────────────────────
    with open(NAT_CSV) as f:
        nat = list(csv.DictReader(f))

    # censo and mesas_total come from the CSV when the scraper has populated them
    # (they reflect the Registraduría's reported figures per municipio).
    # Fall back to the electoral roll when the CSV lacks these columns (e.g. mock).
    csv_censo    = sum_col(nat, "censo")
    csv_mesas_tot = sum_col(nat, "mesas_total")

    if not csv_censo or not csv_mesas_tot:
        print("  CSV missing censo/mesas_total — falling back to electoral roll")
        with open(ROLL_CSV) as f:
            roll = list(csv.DictReader(f))
        csv_censo     = csv_censo     or sum_col(roll, "censo")
        csv_mesas_tot = csv_mesas_tot or sum_col(roll, "num_mesas")

    nat_stats = {
        "votantes":          sum_col(nat, "votantes"),
        "votos_validos":     sum_col(nat, "votos_validos"),
        "votos_blanco":      sum_col(nat, "votos_blanco"),
        "votos_nulos":       sum_col(nat, "votos_nulos"),
        "votos_no_marcados": sum_col(nat, "votos_no_marcados"),
        "mesas_escrutadas":  sum_col(nat, "mesas_escrutadas"),
        "mesas_total":       csv_mesas_tot,
        "censo":             csv_censo,
    }

    print(f"Nacional: votantes={nat_stats['votantes']:,}  "
          f"mesas={nat_stats['mesas_escrutadas']:,}/{nat_stats['mesas_total']:,}  "
          f"censo={nat_stats['censo']:,}")

    # ── Indígena CSV (all municipios incl. exterior) ──────────────────────────
    with open(IND_CSV) as f:
        ind = list(csv.DictReader(f))

    ind_stats = {
        "votantes":          sum_col(ind, "votantes"),
        "votos_validos":     sum_col(ind, "votos_validos"),
        "votos_blanco":      sum_col(ind, "votos_blanco"),
        "votos_nulos":       sum_col(ind, "votos_nulos"),
        "votos_no_marcados": sum_col(ind, "votos_no_marcados"),
        "mesas_escrutadas":  sum_col(ind, "mesas_escrutadas"),
        "mesas_total":       csv_mesas_tot,  # same physical polling stations as nacional
        "censo":             csv_censo,
    }

    print(f"Indígena: votantes={ind_stats['votantes']:,}  "
          f"mesas={ind_stats['mesas_escrutadas']:,}/{ind_stats['mesas_total']:,}")

    # ── Totals across both circunscripciones ──────────────────────────────────
    total_votantes = nat_stats["votantes"] + ind_stats["votantes"]
    print(f"Total votantes (nacional + indígena): {total_votantes:,}")

    # ── Write output ──────────────────────────────────────────────────────────
    out = {
        "total_votantes": total_votantes,
        "nacional":       nat_stats,
        "indigena":       ind_stats,
    }
    path = OUT / "aggregate_stats.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved → {path.name}")


if __name__ == "__main__":
    main()
