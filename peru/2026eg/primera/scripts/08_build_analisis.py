"""
08_build_analisis.py
Build analisis_data.json for the Análisis scatter-plot tab.

For each district we output:
  ubigeo, nombre (district + dept), electores,
  pobreza, rural, population_density,
  keiko_2021_share, castillo_2021_share,
  c1..c5: vote share of each top-5 candidate (pct of valid votes)

Output: web/peru/presidencial2026/analisis/analisis_data.json
"""

import json, re
from pathlib import Path
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parents[1]
DATA    = ROOT / "data"
ANALISIS_CSV = DATA / "analisis" / "distrito_analisis.csv"
GJ_PATH = DATA / "peru_2026eg_distrito_primera.geojson"
AGG_JSON = DATA / "aggregate_stats.json"

WEB_ROOT = Path(__file__).resolve().parents[4] / "web" / "peru" / "presidencial2026"
OUT_DIR  = WEB_ROOT / "analisis"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "analisis_data.json"

# ── Top 5 candidates from aggregate stats ──────────────────────────────────
with open(AGG_JSON) as f:
    agg = json.load(f)

top5 = sorted(agg["candidatos"], key=lambda c: -c["votos"])[:5]
top5_names = [c["nombre"] for c in top5]
print("Top 5 candidates:")
for i, c in enumerate(top5, 1):
    print(f"  {i}. {c['nombre']} ({c['partido']}) — {c['pct_validos']:.1f}%")

# ── Load GeoJSON, build district lookup ────────────────────────────────────
print("\nLoading GeoJSON …")
with open(GJ_PATH) as f:
    gj = json.load(f)

geo_lookup = {}  # onpe_ubigeo (str, no leading zero) → dict
for feat in gj["features"]:
    p     = feat["properties"]
    onpe  = str(p["ubigeo_distrito"]).lstrip("0") or "0"
    validos = p.get("votos_validos", 0) or 0

    # Parse all_candidates JSON string
    cand_votes = {}
    raw = p.get("all_candidates", "")
    if isinstance(raw, str) and raw:
        try:
            cands = json.loads(raw)
            for c in cands:
                cand_votes[c["name"]] = c["votes"]
        except Exception:
            pass

    # Compute top-5 shares
    shares = []
    for c in top5:
        votes = cand_votes.get(c["nombre"], 0) or 0
        share = round(votes / validos * 100, 4) if validos > 0 else None
        shares.append(share)

    geo_lookup[onpe] = {
        "shares": shares,
        "nombre_distrito": p.get("nombre_distrito",""),
        "nombre_dept":     p.get("nombre_dept",""),
    }

print(f"  GeoJSON districts: {len(geo_lookup)}")

# ── Load analisis CSV ──────────────────────────────────────────────────────
print("Loading analisis CSV …")
df = pd.read_csv(ANALISIS_CSV)
# ubigeo column is ONPE (may be float after read if ints)
df["ubigeo"] = df["ubigeo"].apply(lambda v: str(int(v)) if pd.notna(v) else None)

# ── Build output records ───────────────────────────────────────────────────
records = []
skipped = 0

for _, row in df.iterrows():
    ubi = row["ubigeo"]
    if ubi is None:
        skipped += 1
        continue

    geo = geo_lookup.get(ubi)
    if geo is None:
        skipped += 1
        continue

    # Skip if missing key variables
    electores = row.get("electores")
    if pd.isna(electores) or electores <= 0:
        skipped += 1
        continue

    def v(val):
        return None if pd.isna(val) else round(float(val), 4)

    rec = {
        "u":  ubi,
        "n":  f"{geo['nombre_distrito'].title()} ({geo['nombre_dept'].title()})",
        "e":  int(electores),
        "pob": v(row.get("pobreza")),
        "rur": v(row.get("rural")),          # already in % (0–100) from build_analisis.py
        "den": v(row.get("population_density")),
        "k21": v(row.get("keiko_2021_share")),
        "c21": v(row.get("castillo_2021_share")),
        "agu": v(row.get("agua")),
        "tra": v(row.get("trabajo")),
        "sis": v(row.get("sis")),
        "edu": v(row.get("educacion")),
    }
    # Top-5 candidate shares
    for i, share in enumerate(geo["shares"]):
        rec[f"s{i+1}"] = share

    records.append(rec)

print(f"  Records: {len(records)}, skipped: {skipped}")

# ── Metadata ───────────────────────────────────────────────────────────────
variables = [
    {"key": "pob", "label": "Tasa de pobreza",          "unit": "%", "logX": False},
    {"key": "rur", "label": "Ruralidad",                 "unit": "%", "logX": False},
    {"key": "den", "label": "Densidad (electores/km²)",  "unit": "",  "logX": True},
    {"key": "agu", "label": "Agua 7 días/semana",        "unit": "%", "logX": False},
    {"key": "tra", "label": "Trabaja (tiene empleo)",    "unit": "%", "logX": False},
    {"key": "sis", "label": "Afiliado al SIS",           "unit": "%", "logX": False},
    {"key": "edu", "label": "Sec. o más (educación)",   "unit": "%", "logX": False},
    {"key": "k21", "label": "Voto Keiko 2021",           "unit": "%", "logX": False},
    {"key": "c21", "label": "Voto Castillo 2021",        "unit": "%", "logX": False},
]

output = {
    "top5": [
        {"nombre": c["nombre"], "partido": c["partido"],
         "color": c["color"], "pct": c["pct_validos"]}
        for c in top5
    ],
    "variables": variables,
    "districts":  records,
}

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, separators=(",",":"))

size_mb = OUT_FILE.stat().st_size / 1e6
print(f"\nSaved → {OUT_FILE}  ({size_mb:.2f} MB)")
