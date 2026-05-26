"""
06_build_electoral_rolls.py — Peru 2026 EG Primera Vuelta
Derive num_mesas and num_electores for each district from the mesa CSV,
update peru_2026_distrito_electoral_roll.csv, and create
peru_2026_mesa_electoral_roll.csv.

Usage:
  python3 06_build_electoral_rolls.py

Inputs:
  metadata/peru_2026_distrito_electoral_roll.csv   (existing roll to update)
  primera/data/results/peru_2026eg_mesa_primera.csv

Outputs:
  metadata/peru_2026_distrito_electoral_roll.csv   (updated in-place)
  metadata/peru_2026_mesa_electoral_roll.csv       (new, one row per mesa)
"""

import csv
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent                          # metadata/
PRIMERA    = SCRIPT_DIR.parent / "primera" / "data"
RESULTS    = PRIMERA / "results"

DIST_ROLL  = SCRIPT_DIR / "peru_2026_distrito_electoral_roll.csv"
MESA_CSV   = RESULTS    / "peru_2026eg_mesa_primera.csv"
MESA_ROLL  = SCRIPT_DIR / "peru_2026_mesa_electoral_roll.csv"


# ── 1. Aggregate mesa CSV by district ──────────────────────────────────────────

print("Loading mesa results …")
mesa_rows = []
with open(MESA_CSV, newline="") as f:
    mesa_rows = list(csv.DictReader(f))

print(f"  {len(mesa_rows):,} mesas loaded")

# Aggregate per district
dist_mesas       = defaultdict(int)   # ubigeo → count of mesas
dist_electores   = defaultdict(int)   # ubigeo → sum of electores_habiles

for row in mesa_rows:
    u = row["ubigeo_distrito"]
    dist_mesas[u]     += 1
    dist_electores[u] += int(row.get("electores_habiles", 0) or 0)


# ── 2. Update distrito electoral roll ──────────────────────────────────────────

print("\nUpdating district electoral roll …")
with open(DIST_ROLL, newline="") as f:
    dist_rows = list(csv.DictReader(f))
    fieldnames = dist_rows[0].keys() if dist_rows else []

# Rebuild with updated num_mesas / num_electores
updated = 0
for row in dist_rows:
    u = row["ubigeo_distrito"]
    nm = dist_mesas.get(u, 0)
    ne = dist_electores.get(u, 0)
    if nm > 0 or ne > 0:
        row["num_mesas"]     = nm
        row["num_electores"] = ne
        updated += 1

with open(DIST_ROLL, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(dist_rows[0].keys()))
    w.writeheader()
    w.writerows(dist_rows)

print(f"  {updated:,} districts updated  →  {DIST_ROLL.name}")


# ── 3. Build mesa electoral roll ────────────────────────────────────────────────

print("\nBuilding mesa electoral roll …")

# Load district roll to get province / dept lookups
dist_lkp = {}
with open(DIST_ROLL, newline="") as f:
    for row in csv.DictReader(f):
        dist_lkp[row["ubigeo_distrito"]] = row

MESA_ROLL_FIELDS = [
    "codigo_mesa",
    "ubigeo_distrito", "nombre_distrito",
    "ubigeo_provincia", "nombre_provincia",
    "ubigeo_dept",     "nombre_dept",
    "is_exterior",
    "electores_habiles",
    "codigo_local_votacion", "nombre_local_votacion",
]

with open(MESA_ROLL, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=MESA_ROLL_FIELDS)
    w.writeheader()
    for row in sorted(mesa_rows, key=lambda r: r["codigo_mesa"]):
        u = row["ubigeo_distrito"]
        dl = dist_lkp.get(u, {})
        w.writerow({
            "codigo_mesa":           row["codigo_mesa"],
            "ubigeo_distrito":       u,
            "nombre_distrito":       dl.get("nombre_distrito", ""),
            "ubigeo_provincia":      dl.get("ubigeo_provincia", ""),
            "nombre_provincia":      dl.get("nombre_provincia", ""),
            "ubigeo_dept":           dl.get("ubigeo_dept", ""),
            "nombre_dept":           dl.get("nombre_dept", ""),
            "is_exterior":           dl.get("is_exterior", ""),
            "electores_habiles":     row.get("electores_habiles", 0),
            "codigo_local_votacion": row.get("codigo_local_votacion", ""),
            "nombre_local_votacion": row.get("nombre_local_votacion", ""),
        })

print(f"  {len(mesa_rows):,} mesas  →  {MESA_ROLL.name}")
print("\nDone.")
