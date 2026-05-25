"""
04_aggregate_stats.py — Aggregate national primarias stats for the frontend.

Reads all municipio rows (including exterior code 88*) from the interconsultas CSV
(which contains COMMON_FIELDS shared by all four views) and the three per-consulta CSVs
(for per-consulta candidate totals), then writes data/aggregate_stats.json.

Inputs:
  data/results/colombia_2026_municipio_primarias_interconsultas.csv
  data/results/colombia_2026_municipio_primarias_soluciones.csv
  data/results/colombia_2026_municipio_primarias_gran.csv
  data/results/colombia_2026_municipio_primarias_frente.csv
  metadata/colombia_2026_municipio_electoral_roll.csv

Output:
  data/aggregate_stats.json

  {
    "mesas_total":       <int>,    ← from CSV (or electoral roll fallback)
    "mesas_escrutadas":  <int>,
    "censo":             <int>,    ← from CSV (or electoral roll fallback)
    "votantes":          <int>,    ← total across all consultas (shared pool)
    "votos_validos":     <int>,
    "votos_blanco":      <int>,
    "votos_nulos":       <int>,
    "votos_no_marcados": <int>,
    "soluciones": { "total": <int>, <codcan>: <int>, ... },
    "gran":       { "total": <int>, <codcan>: <int>, ... },
    "frente":     { "total": <int>, <codcan>: <int>, ... },
    "interconsultas": {
      "consulta_30": <int>,
      "consulta_31": <int>,
      "consulta_32": <int>
    }
  }

Notes:
  - All vote totals (votantes, votos_validos, etc.) come from the interconsultas CSV
    because those fields are identical across all four CSVs (same physical voters).
  - Per-consulta candidate vote totals come from the individual per-consulta CSVs.
  - censo and mesas_total come from the CSV when populated; otherwise fall back to
    the electoral roll.
"""

import csv
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"

INTER_CSV = RESULTS / "colombia_2026_municipio_primarias_interconsultas.csv"
ROLL_CSV  = METADATA / "colombia_2026_municipio_electoral_roll.csv"

CONSULTAS = {
    30: ("soluciones", "cand_30_"),
    31: ("gran",       "cand_31_"),
    32: ("frente",     "cand_32_"),
}


def isum(rows: list[dict], col: str) -> int:
    return sum(int(r.get(col) or 0) for r in rows)


def sum_cand_cols(rows: list[dict], prefix: str) -> dict:
    """
    Aggregate all columns starting with prefix across all municipio rows.
    Returns {col_name: total_votes}.
    """
    totals: dict[str, int] = {}
    for row in rows:
        for k, v in row.items():
            if k.startswith(prefix):
                totals[k] = totals.get(k, 0) + int(v or 0)
    return totals


def main():
    # ── Interconsultas CSV (shared vote pool metadata) ────────────────────────
    if not INTER_CSV.exists():
        print(f"ERROR: {INTER_CSV.name} not found — run 02_scrape_municipios.py first.")
        return

    with open(INTER_CSV) as f:
        inter_rows = list(csv.DictReader(f))

    csv_censo     = isum(inter_rows, "censo")
    csv_mesas_tot = isum(inter_rows, "mesas_total")

    if not csv_censo or not csv_mesas_tot:
        print("  CSV missing censo/mesas_total — falling back to electoral roll")
        with open(ROLL_CSV) as f:
            roll = list(csv.DictReader(f))
        csv_censo     = csv_censo     or isum(roll, "censo")
        csv_mesas_tot = csv_mesas_tot or isum(roll, "num_mesas")

    stats: dict = {
        "mesas_total":       csv_mesas_tot,
        "mesas_escrutadas":  isum(inter_rows, "mesas_escrutadas"),
        "censo":             csv_censo,
        "votantes":          isum(inter_rows, "votantes"),
        "votos_validos":     isum(inter_rows, "votos_validos"),
        "votos_blanco":      isum(inter_rows, "votos_blanco"),
        "votos_nulos":       isum(inter_rows, "votos_nulos"),
        "votos_no_marcados": isum(inter_rows, "votos_no_marcados"),
        "interconsultas": {
            "consulta_30": isum(inter_rows, "consulta_30"),
            "consulta_31": isum(inter_rows, "consulta_31"),
            "consulta_32": isum(inter_rows, "consulta_32"),
        },
    }

    print(
        f"Totals: votantes={stats['votantes']:,}  validos={stats['votos_validos']:,}  "
        f"mesas={stats['mesas_escrutadas']:,}/{stats['mesas_total']:,}  "
        f"censo={stats['censo']:,}"
    )
    print(
        f"  Interconsultas: soluciones={stats['interconsultas']['consulta_30']:,}  "
        f"gran={stats['interconsultas']['consulta_31']:,}  "
        f"frente={stats['interconsultas']['consulta_32']:,}"
    )

    # ── Per-consulta candidate totals ─────────────────────────────────────────
    for codpar, (slug, prefix) in CONSULTAS.items():
        csv_path = RESULTS / f"colombia_2026_municipio_primarias_{slug}.csv"
        if not csv_path.exists():
            print(f"  SKIP {slug}: CSV not found")
            stats[slug] = {"total": 0}
            continue

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))

        cand_totals = sum_cand_cols(rows, prefix)
        grand_total = sum(cand_totals.values())

        # Simplify keys: strip prefix and pipe-suffix, keep "codcan: votes" form
        simple: dict[str, int] = {}
        for col, votes in sorted(cand_totals.items(), key=lambda x: -x[1]):
            raw  = col[len(prefix):]                   # e.g. "000027|ROY BARRERAS MOTOA"
            code = raw.split("|")[0]                   # e.g. "000027"
            name = raw.split("|")[1] if "|" in raw else raw
            simple[code] = {"votes": votes, "nombre": name}

        stats[slug] = {"total": grand_total, "candidates": simple}

        print(f"  {slug.capitalize()}: total={grand_total:,}  candidates={len(simple)}")

    # ── Write ─────────────────────────────────────────────────────────────────
    out_path = OUT / "aggregate_stats.json"
    with open(out_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\nSaved → {out_path.name}")


if __name__ == "__main__":
    main()
