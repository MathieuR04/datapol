"""
07_build_jee.py
Build three GeoJSONs (dept / provincia / distrito) for the Actas JEE tab.

For each geographic unit we compute:
  total_actas  — total polling tables (mesas)
  ever_e       — mesas where ever_E == True  (sent to JEE at any point)
  never_e      — mesas where ever_E == False
  ever_e_pct   — ever_e / total_actas * 100

  For each of the 10 base error types (deduped per acta):
    err_aritmetico, err_firmas, err_impugnada, err_ilegible,
    err_incompleta, err_reprocesada, err_extraviada, err_siniestrada,
    err_sin_datos, err_nulidad
  These can overlap (one acta can have multiple errors).

Output files go to web/peru/presidencial2026/jee/
"""

import json, re
from pathlib import Path

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[1]          # primera/
DATA      = ROOT / "data"
MESA_CSV  = DATA / "results" / "peru_2026eg_mesa_primera.csv"
GEOJSON   = {
    "dept":      DATA / "peru_2026eg_departamento_primera.geojson",
    "provincia": DATA / "peru_2026eg_provincia_primera.geojson",
    "distrito":  DATA / "peru_2026eg_distrito_primera.geojson",
}
WEB_ROOT  = Path(__file__).resolve().parents[4] / "web" / "peru" / "presidencial2026"
OUT_DIR   = WEB_ROOT / "jee"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Error type definitions ─────────────────────────────────────────────────────
# Maps a short key → the canonical string as it appears in descripcion_error
ERROR_TYPES = {
    "err_aritmetico": "Acta con error aritmético",
    "err_firmas":     "Acta sin firmas",
    "err_impugnada":  "Acta impugnada",
    "err_ilegible":   "Acta ilegible",
    "err_incompleta": "Acta incompleta",
    "err_reprocesada":"Acta reprocesada",
    "err_extraviada": "Acta extraviada",
    "err_siniestrada":"Acta siniestrada",
    "err_sin_datos":  "Acta sin datos",
    "err_nulidad":    "Acta con solicitud de nulidad",
}

def parse_errors(val):
    """Return a set of canonical error strings from a raw descripcion_error cell."""
    if not isinstance(val, str) or not val.strip():
        return set()
    parts = set()
    for segment in val.split("|"):
        for part in segment.split(","):
            parts.add(part.strip())
    return parts

# ── Load mesa data ─────────────────────────────────────────────────────────────
print("Loading mesa data …")
df = pd.read_csv(MESA_CSV, dtype=str)

df["ever_E_bool"] = df["ever_E"].str.strip().str.lower() == "true"

# Pre-compute one boolean column per error type
for key, label in ERROR_TYPES.items():
    df[key] = df["descripcion_error"].apply(lambda v: label in parse_errors(v))

# Derive ubigeo keys at each level
df["ubigeo_dept"]     = df["ubigeo_distrito"].str[:2].str.ljust(6, "0")
df["ubigeo_provincia"] = df["ubigeo_distrito"].str[:4].str.ljust(6, "0")
df["ubigeo_distrito_key"] = df["ubigeo_distrito"]

def aggregate(df, group_col):
    """Aggregate mesa-level data to a geographic level."""
    agg_dict = {
        "total_actas": ("ever_E_bool", "count"),
        "ever_e":      ("ever_E_bool", "sum"),
    }
    for key in ERROR_TYPES:
        agg_dict[key] = (key, "sum")

    grp = df.groupby(group_col).agg(**agg_dict).reset_index()
    grp["never_e"]    = grp["total_actas"] - grp["ever_e"]
    grp["ever_e_pct"] = (grp["ever_e"] / grp["total_actas"] * 100).round(2)
    return grp

agg_dept = aggregate(df, "ubigeo_dept")
agg_prov = aggregate(df, "ubigeo_provincia")
agg_dist = aggregate(df, "ubigeo_distrito_key")

print(f"  dept rows: {len(agg_dept)}, prov rows: {len(agg_prov)}, dist rows: {len(agg_dist)}")

# ── Merge into GeoJSONs ────────────────────────────────────────────────────────
JEE_PROPS = ["total_actas", "ever_e", "never_e", "ever_e_pct"] + list(ERROR_TYPES.keys())

KEEP_PROPS = {
    "dept":      ["ubigeo_dept", "nombre_dept"],
    "provincia": ["ubigeo_provincia", "nombre_provincia", "nombre_dept"],
    "distrito":  ["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept",
                  "nombre_distrito", "nombre_provincia", "nombre_dept"],
}
AGG_DICT = {
    "dept":      (agg_dept,      "ubigeo_dept"),
    "provincia": (agg_prov,      "ubigeo_provincia"),
    "distrito":  (agg_dist,      "ubigeo_distrito_key"),
}
UBIGEO_FIELD = {
    "dept":      "ubigeo_dept",
    "provincia": "ubigeo_provincia",
    "distrito":  "ubigeo_distrito",
}

for level, gj_path in GEOJSON.items():
    print(f"Building {level} …")
    with open(gj_path) as f:
        gj = json.load(f)

    agg_df, agg_col = AGG_DICT[level]
    ubigeo_field    = UBIGEO_FIELD[level]
    lookup          = agg_df.set_index(agg_col).to_dict("index")

    kept = dropped = 0
    new_features = []
    for feat in gj["features"]:
        p        = feat["properties"]
        ubigeo   = p.get(ubigeo_field, "")
        row      = lookup.get(ubigeo)
        if row is None:
            dropped += 1
            continue

        new_props = {k: p[k] for k in KEEP_PROPS[level] if k in p}
        for col in JEE_PROPS:
            v = row.get(col, 0)
            # Convert numpy types to native Python
            if hasattr(v, "item"):
                v = v.item()
            new_props[col] = v

        feat = dict(feat)
        feat["properties"] = new_props
        new_features.append(feat)
        kept += 1

    out_gj = {"type": "FeatureCollection", "features": new_features}
    out_path = OUT_DIR / f"jee_{level}.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_gj, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  {out_path.name}: {kept} features, {size_mb:.1f} MB (dropped {dropped})")

# ── National summary JSON ──────────────────────────────────────────────────────
total = int(df.shape[0])
ever_e = int(df["ever_E_bool"].sum())
summary = {
    "total_actas": total,
    "ever_e":      ever_e,
    "never_e":     total - ever_e,
    "ever_e_pct":  round(ever_e / total * 100, 2),
    "error_counts": {
        key: int(df[key].sum())
        for key in ERROR_TYPES
    }
}
out_summary = OUT_DIR / "jee_national.json"
with open(out_summary, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"National summary: {summary}")
print("Done.")
