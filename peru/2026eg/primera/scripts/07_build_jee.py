"""
07_build_jee.py
Build three GeoJSONs (dept / provincia / distrito) for the Actas JEE tab.

Universe = all 92,766 actas.
ever_E = True  → acta was sent to JEE at some point (5,891 actas).

Per geography we compute:
  total_actas   — total actas
  ever_e        — actas with ever_E=True
  ever_e_pct    — ever_e / total_actas * 100

  Within ever_e, current estado_acta breakdown:
    estado_C    — Contabilizada
    estado_E    — Enviada al JEE (still there)
    estado_P    — Pendiente

  Within ever_e, error type counts (deduped per acta, can overlap):
    err_aritmetico, err_firmas, err_impugnada, err_ilegible,
    err_incompleta, err_reprocesada, err_extraviada, err_siniestrada,
    err_sin_datos, err_nulidad

Output: peru/2026eg/primera/data/jee/
"""

import json
from pathlib import Path
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[1]
DATA      = ROOT / "data"
METADATA  = ROOT.parent / "metadata"
MESA_CSV  = DATA / "results" / "peru_2026eg_mesa_primera.csv"
MESA_ROLL = METADATA / "peru_2026_mesa_electoral_roll.csv"
GEOJSON  = {
    "dept":      DATA / "peru_2026eg_departamento_primera.geojson",
    "provincia": DATA / "peru_2026eg_provincia_primera.geojson",
    "distrito":  DATA / "peru_2026eg_distrito_primera.geojson",
}
OUT_DIR  = DATA / "jee"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Error type definitions ─────────────────────────────────────────────────────
ERROR_TYPES = {
    "err_aritmetico":  "Acta con error aritmético",
    "err_firmas":      "Acta sin firmas",
    "err_impugnada":   "Acta impugnada",
    "err_ilegible":    "Acta ilegible",
    "err_incompleta":  "Acta incompleta",
    "err_reprocesada": "Acta reprocesada",
    "err_extraviada":  "Acta extraviada",
    "err_siniestrada": "Acta siniestrada",
    "err_sin_datos":   "Acta sin datos",
    "err_nulidad":     "Acta con solicitud de nulidad",
}

def parse_errors(val):
    if not isinstance(val, str) or not val.strip():
        return set()
    parts = set()
    for segment in val.split("|"):
        for part in segment.split(","):
            p = part.strip()
            if p:
                parts.add(p)
    return parts

# ── Load ───────────────────────────────────────────────────────────────────────
print("Loading mesa data …")
df = pd.read_csv(MESA_CSV, dtype=str)

df["ever_E_bool"] = df["ever_E"].str.strip().str.lower() == "true"

# Error flags (only meaningful for ever_E=True rows, but computed for all)
for key, label in ERROR_TYPES.items():
    df[key] = df["descripcion_error"].apply(lambda v, l=label: l in parse_errors(v))

# Ubigeo keys at each level
df["ubigeo_dept"]         = df["ubigeo_distrito"].str[:2].str.ljust(6, "0")
df["ubigeo_provincia"]    = df["ubigeo_distrito"].str[:4].str.ljust(6, "0")
df["ubigeo_distrito_key"] = df["ubigeo_distrito"]

# ── Aggregate ─────────────────────────────────────────────────────────────────
def aggregate(df, group_col):
    # Total actas + ever_e count
    agg_dict = {
        "total_actas": ("ever_E_bool", "count"),
        "ever_e":      ("ever_E_bool", "sum"),
    }
    # Error counts across ALL ever_E actas (regardless of estado)
    for key in ERROR_TYPES:
        agg_dict[key] = (key, "sum")

    grp = df.groupby(group_col).agg(**agg_dict).reset_index()
    grp["ever_e_pct"] = (grp["ever_e"] / grp["total_actas"] * 100).round(2)

    # Estado breakdown + per-status error counts within ever_E actas
    ever_e_df = df[df["ever_E_bool"]]
    for estado in ["C", "E", "P"]:
        sub_df = ever_e_df[ever_e_df["estado_acta"] == estado]
        # Count actas with this status
        sub = sub_df.groupby(group_col).size().rename(f"estado_{estado}")
        grp = grp.merge(sub, on=group_col, how="left")
        grp[f"estado_{estado}"] = grp[f"estado_{estado}"].fillna(0).astype(int)
        # Count each error type within this status
        if len(sub_df) > 0:
            for key in ERROR_TYPES:
                sub_err = sub_df.groupby(group_col)[key].sum().rename(f"{key}_{estado}")
                grp = grp.merge(sub_err, on=group_col, how="left")
                grp[f"{key}_{estado}"] = grp[f"{key}_{estado}"].fillna(0).astype(int)
        else:
            for key in ERROR_TYPES:
                grp[f"{key}_{estado}"] = 0

    return grp

agg_dept = aggregate(df, "ubigeo_dept")
agg_prov = aggregate(df, "ubigeo_provincia")
agg_dist = aggregate(df, "ubigeo_distrito_key")
print(f"  dept rows: {len(agg_dept)}, prov: {len(agg_prov)}, dist: {len(agg_dist)}")

# ── GeoJSONs ──────────────────────────────────────────────────────────────────
_estado_err_cols = [f"{k}_{e}" for e in ["C","E","P"] for k in ERROR_TYPES]
JEE_PROPS = (
    ["total_actas", "ever_e", "ever_e_pct", "estado_C", "estado_E", "estado_P"]
    + list(ERROR_TYPES.keys())
    + _estado_err_cols
)
KEEP_PROPS = {
    "dept":      ["ubigeo_dept", "nombre_dept"],
    "provincia": ["ubigeo_provincia", "nombre_provincia", "nombre_dept"],
    "distrito":  ["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept",
                  "nombre_distrito", "nombre_provincia", "nombre_dept"],
}
AGG_DICT = {
    "dept":      (agg_dept, "ubigeo_dept"),
    "provincia": (agg_prov, "ubigeo_provincia"),
    "distrito":  (agg_dist, "ubigeo_distrito_key"),
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
        p      = feat["properties"]
        ubigeo = p.get(ubigeo_field, "")
        row    = lookup.get(ubigeo)
        if row is None:
            dropped += 1
            continue

        new_props = {k: p[k] for k in KEEP_PROPS[level] if k in p}
        for col in JEE_PROPS:
            v = row.get(col, 0)
            if hasattr(v, "item"):
                v = v.item()
            new_props[col] = v

        feat = dict(feat)
        feat["properties"] = new_props
        new_features.append(feat)
        kept += 1

    out_path = OUT_DIR / f"jee_{level}.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": new_features},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"  {out_path.name}: {kept} features, {out_path.stat().st_size/1e6:.1f} MB")

# ── Exterior prefixes ─────────────────────────────────────────────────────────
EXTERIOR_PREFIXES = {"91", "92", "93", "94", "95"}
EXTERIOR_REGION_NAMES = {
    "91": "Misiones diplomáticas",
    "92": "Latinoamérica y Caribe",
    "93": "Asia y Oceanía",
    "94": "Europa",
    "95": "Norteamérica",
}

# Province name lookup (ubigeo_provincia → nombre_provincia) from roll
_roll_prov = pd.read_csv(MESA_ROLL, dtype=str, usecols=["ubigeo_provincia", "nombre_provincia"])
PROV_NAMES = _roll_prov.drop_duplicates("ubigeo_provincia").set_index("ubigeo_provincia")["nombre_provincia"].to_dict()

df["is_exterior"] = df["ubigeo_distrito"].str[:2].isin(EXTERIOR_PREFIXES)
df["ext_region"]  = df["ubigeo_distrito"].str[:2].map(EXTERIOR_REGION_NAMES)

def status_summary(sub, include_flat_errors=False):
    ever_e_sub = sub[sub["ever_E_bool"]]
    total = int(sub.shape[0])
    ever_e = int(ever_e_sub.shape[0])
    out = {
        "total_actas": total,
        "ever_e":      ever_e,
        "ever_e_pct":  round(ever_e / total * 100, 2) if total > 0 else 0,
        "estado_C":    int((ever_e_sub["estado_acta"] == "C").sum()),
        "estado_E":    int((ever_e_sub["estado_acta"] == "E").sum()),
        "estado_P":    int((ever_e_sub["estado_acta"] == "P").sum()),
        "error_counts_by_estado": {
            estado: {
                key: int(ever_e_sub[ever_e_sub["estado_acta"] == estado][key].sum())
                for key in ERROR_TYPES
            }
            for estado in ["C", "E", "P"]
        },
    }
    if include_flat_errors:
        for key in ERROR_TYPES:
            out[key] = int(ever_e_sub[key].sum())
    return out

# ── National summary ──────────────────────────────────────────────────────────
ever_e_df = df[df["ever_E_bool"]]
total  = int(df.shape[0])
ever_e = int(ever_e_df.shape[0])

# Domestic (non-exterior) stats
dom_df = df[~df["is_exterior"]]

# Exterior: by region
ext_df = df[df["is_exterior"]]
ext_regions = []
for prefix, name in EXTERIOR_REGION_NAMES.items():
    sub = df[df["ubigeo_distrito"].str[:2] == prefix]
    if len(sub) == 0:
        continue
    s = status_summary(sub)
    s["nombre"] = name
    ext_regions.append(s)

# Exterior: by province (country) — for detail list in frontend
ext_provinces = []
for ubigeo_prov, grp in ext_df.groupby("ubigeo_provincia"):
    s = status_summary(grp, include_flat_errors=True)
    s["ubigeo_provincia"] = ubigeo_prov
    s["nombre"]  = PROV_NAMES.get(ubigeo_prov, ubigeo_prov)
    s["region"]  = EXTERIOR_REGION_NAMES.get(ubigeo_prov[:2], "Exterior")
    ext_provinces.append(s)
ext_provinces.sort(key=lambda x: -x["total_actas"])

summary = {
    "total_actas": total,
    "ever_e":      ever_e,
    "ever_e_pct":  round(ever_e / total * 100, 2),
    "estado_C":    int((ever_e_df["estado_acta"] == "C").sum()),
    "estado_E":    int((ever_e_df["estado_acta"] == "E").sum()),
    "estado_P":    int((ever_e_df["estado_acta"] == "P").sum()),
    "error_counts": {key: int(df[key].sum()) for key in ERROR_TYPES},
    "error_counts_by_estado": {
        estado: {
            key: int(ever_e_df[ever_e_df["estado_acta"] == estado][key].sum())
            for key in ERROR_TYPES
        }
        for estado in ["C", "E", "P"]
    },
    # Domestic summary (excludes exterior)
    "domestico": status_summary(dom_df),
    # Exterior summary + per-region and per-province (country) breakdown
    "exterior": {
        **status_summary(ext_df),
        "regiones":   ext_regions,
        "provincias": ext_provinces,
    },
}
out_summary = OUT_DIR / "jee_national.json"
with open(out_summary, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"National summary: {summary['total_actas']} actas, {summary['ever_e']} ever_E, exterior: {summary['exterior']['total_actas']} actas")
print("Done.")
