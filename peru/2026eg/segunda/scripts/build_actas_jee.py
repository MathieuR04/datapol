"""
build_actas_jee.py — Peru 2026 EG Segunda Vuelta
Builds actas_jee.csv: one row per acta with estado_acta == 'E',
with full geo info and binary columns for each error type.

Usage:
  python3 scripts/build_actas_jee.py           # full rebuild
  python3 scripts/build_actas_jee.py --update  # append only new mesas not yet in CSV
"""

import argparse
import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"
META       = SCRIPT_DIR.parent.parent / "metadata"

MESA_CSV = RESULTS / "peru_2026eg_mesa_segunda.csv"
ROLL_CSV = META    / "peru_2026_mesa_electoral_roll.csv"
OUT_CSV  = RESULTS / "actas_jee.csv"

ERROR_COLS = [
    "Acta con error aritmético",
    "Acta ilegible",
    "Acta impugnada",
    "Acta sin firmas",
]

FIELDS = [
    "codigo_mesa",
    "ubigeo_distrito", "nombre_distrito",
    "ubigeo_provincia", "nombre_provincia",
    "ubigeo_dept", "nombre_dept",
    "is_exterior",
    "electores_habiles",
    "votos_emitidos", "votos_validos",
    "cand_01", "cand_02",
    "descripcion_error",
] + ERROR_COLS


def parse_errors(raw: str) -> set:
    parts = set()
    for chunk in raw.replace(",", "|").split("|"):
        t = chunk.strip()
        if t:
            parts.add(t)
    return parts


def load_roll() -> dict:
    roll = {}
    with open(ROLL_CSV) as f:
        for row in csv.DictReader(f):
            roll[row["codigo_mesa"]] = row
    return roll


def build_row(row: dict, geo: dict) -> dict:
    active = parse_errors(row.get("descripcion_error", ""))
    out = {
        "codigo_mesa":       row["codigo_mesa"],
        "ubigeo_distrito":   geo.get("ubigeo_distrito",  row.get("ubigeo_distrito", "")),
        "nombre_distrito":   geo.get("nombre_distrito",  ""),
        "ubigeo_provincia":  geo.get("ubigeo_provincia", ""),
        "nombre_provincia":  geo.get("nombre_provincia", ""),
        "ubigeo_dept":       geo.get("ubigeo_dept",      ""),
        "nombre_dept":       geo.get("nombre_dept",      ""),
        "is_exterior":       geo.get("is_exterior",      ""),
        "electores_habiles": row.get("electores_habiles", ""),
        "votos_emitidos":    row.get("votos_emitidos",   ""),
        "votos_validos":     row.get("votos_validos",    ""),
        "cand_01":           row.get("cand_01",          ""),
        "cand_02":           row.get("cand_02",          ""),
        "descripcion_error": row.get("descripcion_error",""),
    }
    for ec in ERROR_COLS:
        out[ec] = 1 if ec in active else 0
    return out


def main(update_mode: bool = False):
    roll = load_roll()

    # Load existing rows if in update mode
    existing_codes: set = set()
    existing_rows: list = []
    if update_mode and OUT_CSV.exists():
        with open(OUT_CSV) as f:
            for row in csv.DictReader(f):
                existing_codes.add(row["codigo_mesa"])
                existing_rows.append(row)
        print(f"Existing actas_jee.csv: {len(existing_rows)} rows")

    # Scan mesa CSV for estado E
    new_rows = []
    with open(MESA_CSV) as f:
        for row in csv.DictReader(f):
            if row["estado_acta"] != "E":
                continue
            if update_mode and row["codigo_mesa"] in existing_codes:
                continue
            geo = roll.get(row["codigo_mesa"], {})
            new_rows.append(build_row(row, geo))

    if update_mode:
        if not new_rows:
            print("No new actas E — nothing to add.")
            return
        all_rows = existing_rows + new_rows
        print(f"New actas E found: {len(new_rows)}")
    else:
        all_rows = new_rows

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    print(f"Saved {len(all_rows)} actas E → {OUT_CSV.name}")
    counts = {ec: sum(1 for r in all_rows if str(r.get(ec)) == "1") for ec in ERROR_COLS}
    for ec, n in counts.items():
        print(f"  {n:4d}  {ec}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only append new actas E not already in the CSV")
    args = parser.parse_args()
    main(update_mode=args.update)
