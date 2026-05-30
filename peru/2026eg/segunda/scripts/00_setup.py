"""
00_setup.py — Peru 2026 EG Segunda Vuelta
Create empty-state result CSVs from metadata and candidates.json.

Run this once before any live-data scraping to initialise the result files
with the correct schema and zero values.  Re-running at any point resets
results back to the pre-election empty state.

Inputs (never modified):
  ../../metadata/peru_2026_distrito_electoral_roll.csv
  ../../metadata/peru_2026_mesa_electoral_roll.csv
  data/candidates.json

Outputs (overwritten):
  data/results/peru_2026eg_distrito_segunda.csv
    — one row per district; ubigeo_distrito + actas_total populated;
      all vote/candidate columns blank.

  data/results/peru_2026eg_mesa_segunda.csv
    — one row per polling table; codigo_mesa + actas_total=1,
      estado_acta=P, ever_E=FALSE; all vote/candidate columns blank.
"""

import csv
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"

RESULTS.mkdir(parents=True, exist_ok=True)

# ── Candidates ─────────────────────────────────────────────────────────────────
with open(DATA_DIR / "candidates.json") as f:
    candidates = json.load(f)

# Column order matches candidates.json declaration order (same as scrapers)
cand_cols = [f"cand_{c['codigo']}" for c in candidates]

print(f"Candidates: {len(candidates)}")

# ── Distrito CSV ───────────────────────────────────────────────────────────────
print("\nBuilding empty distrito CSV …")
dist_roll = METADATA / "peru_2026_distrito_electoral_roll.csv"
dist_out  = RESULTS  / "peru_2026eg_distrito_segunda.csv"

dist_cols = (
    ["ubigeo_distrito",
     "votos_validos", "votos_blancos", "votos_nulos", "votos_emitidos",
     "actas_contabilizadas", "actas_total"]
    + cand_cols
)

n_dist = 0
with open(dist_roll, newline="") as f, open(dist_out, "w", newline="") as out:
    reader = csv.DictReader(f)
    writer = csv.DictWriter(out, fieldnames=dist_cols)
    writer.writeheader()
    for row in reader:
        record = {c: "" for c in dist_cols}
        record["ubigeo_distrito"] = row["ubigeo_distrito"]
        record["actas_total"]     = row["num_mesas"]
        writer.writerow(record)
        n_dist += 1

print(f"  {n_dist:,} districts → {dist_out.name}")

# ── Mesa CSV ───────────────────────────────────────────────────────────────────
print("\nBuilding empty mesa CSV …")
mesa_roll = METADATA / "peru_2026_mesa_electoral_roll.csv"
mesa_out  = RESULTS  / "peru_2026eg_mesa_segunda.csv"

mesa_cols = (
    ["codigo_mesa", "ubigeo_distrito",
     "codigo_local_votacion", "nombre_local_votacion",
     "electores_habiles",
     "votos_emitidos", "votos_validos", "votos_blancos", "votos_nulos",
     "actas_total", "actas_contabilizadas",
     "estado_acta", "ever_E", "descripcion_error"]
    + cand_cols
)

n_mesa = 0
with open(mesa_roll, newline="") as f, open(mesa_out, "w", newline="") as out:
    reader = csv.DictReader(f)
    writer = csv.DictWriter(out, fieldnames=mesa_cols)
    writer.writeheader()
    for row in reader:
        record = {c: "" for c in mesa_cols}
        record["codigo_mesa"]             = row["codigo_mesa"]
        record["ubigeo_distrito"]         = row["ubigeo_distrito"]
        record["codigo_local_votacion"]   = row["codigo_local_votacion"]
        record["nombre_local_votacion"]   = row["nombre_local_votacion"]
        record["electores_habiles"]       = row["electores_habiles"]
        record["actas_total"]             = "1"
        record["estado_acta"]             = "P"
        record["ever_E"]                  = "FALSE"
        writer.writerow(record)
        n_mesa += 1

print(f"  {n_mesa:,} mesas → {mesa_out.name}")

print("\nDone. Empty-state files created.")
print("Run scripts 03_build_geojson.py through 08_build_analisis.py to regenerate all outputs.")
