"""
build_analisis.py
Build district-level socioeconomic + electoral analysis CSV.

Sources:
  - INEI Mapa de Pobreza 2018          → pobreza (%)
  - Censo 2017 area urbano/rural        → rural share (%)
  - Ubigeo lookup (ONPE ↔ INEI)        → id_ubigeo
  - District GeoJSON (2026 election)   → area_km2, electores (2026 roll)
  - 2021 runoff results (mesa level)   → keiko_2021_share, castillo_2021_share

Output: analisis/distrito_analisis.csv
  ubigeo, departamento, provincia, distrito,
  electores, area_km2, population_density,
  keiko_2021_share, castillo_2021_share,
  rural, pobreza
"""
import json, re, unicodedata
import pandas as pd
from pathlib import Path
from pyproj import Geod
from shapely.geometry import shape

RAW      = Path(__file__).parent / "raw"
DATA     = Path(__file__).parent.parent          # .../data
OUT      = Path(__file__).parent / "distrito_analisis.csv"
GJ_PATH  = DATA / "peru_2026eg_distrito_primera.geojson"
CSV_2021 = RAW / "Resultados por mesa de la Segunda Elección Presidencial 2021.csv"

geod = Geod(ellps="WGS84")

# ── Helpers ────────────────────────────────────────────────────────────────
def norm(s):
    if not isinstance(s, str): return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.upper().strip())

def geod_area_km2(geom):
    """Geodetic area of a shapely geometry in km²."""
    area_m2, _ = geod.geometry_area_perimeter(geom)
    return abs(area_m2) / 1e6

# ── Pobreza ────────────────────────────────────────────────────────────────
print("Loading pobreza …")
pov = pd.read_excel(RAW / "pobreza.xlsx", sheet_name="Anexo1", header=None)
pov = pov.iloc[7:].copy()
pov.columns = ["ubigeo","departamento","provincia","distrito",
               "poblacion","ci_inf","ci_sup","grupo","ubicacion"]
pov = pov.dropna(subset=["ubigeo"]).copy()
pov["ubigeo_inei"]  = pov["ubigeo"].astype(str).str.strip().str.zfill(6)
pov["departamento"] = pov["departamento"].str.strip().str.title()
pov["provincia"]    = pov["provincia"].str.strip().str.title()
pov["distrito"]     = pov["distrito"].str.strip().str.title()
pov["pobreza"]      = ((pov["ci_inf"] + pov["ci_sup"]) / 2).round(4)
pov = pov[["ubigeo_inei","departamento","provincia","distrito","pobreza"]]

# ── Rural ──────────────────────────────────────────────────────────────────
print("Loading rural …")
rural_raw = pd.read_excel(RAW / "rural.xlsx", sheet_name="Output", header=None)
rural_records = {}
current_ubigeo = None

for _, row in rural_raw.iterrows():
    val = str(row[1]) if pd.notna(row[1]) else ""
    m = re.match(r"AREA\s*#\s*(\d+)", val)
    if m:
        current_ubigeo = m.group(1).zfill(6)
        rural_records[current_ubigeo] = 0.0
        continue
    if current_ubigeo and "Rural encuesta" in val:
        try:
            rural_records[current_ubigeo] = round(float(row[3]), 6)
        except Exception:
            pass

rural_df = pd.DataFrame(
    [{"ubigeo_inei": k, "rural": v} for k, v in rural_records.items()]
)

# ── Merge pobreza + rural ──────────────────────────────────────────────────
merged = pov.merge(rural_df, on="ubigeo_inei", how="outer")
merged = merged[merged["ubigeo_inei"].str.match(r"^\d{6}$", na=False)].copy()
merged = merged.sort_values("ubigeo_inei").reset_index(drop=True)
print(f"  Pobreza: {len(pov)} | Rural: {len(rural_df)} | Merged: {len(merged)}")

# ── ONPE id_ubigeo ─────────────────────────────────────────────────────────
print("Matching ONPE ubigeo …")
lookup = pd.read_csv(RAW / "ubigeo_lookup copy.csv", dtype=str)
lookup["n_dept"] = lookup["region"].apply(norm)
lookup["n_prov"] = lookup["provincia"].apply(norm)
lookup["n_dist"] = lookup["distrito"].apply(norm)
merged["n_dept"] = merged["departamento"].apply(norm)
merged["n_prov"] = merged["provincia"].apply(norm)
merged["n_dist"] = merged["distrito"].apply(norm)

lk1 = lookup.set_index(["n_dept","n_prov","n_dist"])["id_ubigeo"].to_dict()
merged["id_ubigeo"] = merged.apply(
    lambda r: lk1.get((r.n_dept, r.n_prov, r.n_dist)), axis=1)

lk2 = lookup.groupby(["n_dept","n_dist"])["id_ubigeo"].first().to_dict()
mask2 = merged["id_ubigeo"].isna()
merged.loc[mask2, "id_ubigeo"] = merged.loc[mask2].apply(
    lambda r: lk2.get((r.n_dept, r.n_dist)), axis=1)

MANUAL = {
    "021408": "22008",
    "030407": "30207",
    "050511": "50411",
    "100106": "90105",
    "120807": "110607",
    "150731": "140628",
    "190108": "180109",
    "211210": "200812",
    "230110": "220113",
    "250201": "250301",
}
for ubi, onpe in MANUAL.items():
    merged.loc[merged["ubigeo_inei"] == ubi, "id_ubigeo"] = onpe

merged = merged.drop(columns=["n_dept","n_prov","n_dist"])
print(f"  Matched: {merged['id_ubigeo'].notna().sum()}/{len(merged)} "
      f"({merged['id_ubigeo'].isna().sum()} NaN — expected)")

# ── Area + Electores from GeoJSON ──────────────────────────────────────────
print("Computing area from GeoJSON …")
with open(GJ_PATH) as f:
    gj = json.load(f)

geo_rows = []
for feat in gj["features"]:
    p    = feat["properties"]
    # GeoJSON ubigeo_distrito is ONPE format (6-digit zero-padded)
    # Strip leading zero to match our id_ubigeo (5-digit ONPE)
    onpe_ubi = str(p.get("ubigeo_distrito","")).lstrip("0") or "0"
    geom = shape(feat["geometry"])
    area = geod_area_km2(geom)
    geo_rows.append({
        "id_ubigeo": onpe_ubi,
        "area_km2":  round(area, 4),
        "electores": p.get("num_electores"),
    })

geo_df = pd.DataFrame(geo_rows)
print(f"  GeoJSON districts: {len(geo_df)}")

merged = merged.merge(geo_df, on="id_ubigeo", how="left")
print(f"  Area matched: {merged['area_km2'].notna().sum()}/{len(merged)}")

# Population density: electores per km²
merged["population_density"] = (
    merged["electores"] / merged["area_km2"]
).round(4)

# ── 2021 Runoff results ────────────────────────────────────────────────────
print("Loading 2021 runoff results …")
r21 = pd.read_csv(
    CSV_2021, sep=";", encoding="latin-1", dtype=str, index_col=False,
    usecols=range(15)   # read all 15 columns by position, then rename
)
# Rename positional columns to expected names
r21.columns = ["UBIGEO","DEPARTAMENTO","PROVINCIA","DISTRITO","TIPO_ELECCION",
               "MESA_DE_VOTACION","DESCRIP_ESTADO_ACTA","TIPO_OBSERVACION",
               "N_CVAS","N_ELEC_HABIL","VOTOS_P1","VOTOS_P2","VOTOS_VB","VOTOS_VN","VOTOS_VI"]
r21 = r21[["UBIGEO","VOTOS_P1","VOTOS_P2","VOTOS_VB","VOTOS_VN","VOTOS_VI"]]

# Numeric conversion
for col in ["VOTOS_P1","VOTOS_P2","VOTOS_VB","VOTOS_VN","VOTOS_VI"]:
    r21[col] = pd.to_numeric(r21[col], errors="coerce").fillna(0)

# 2021 UBIGEO is ONPE format (6-digit zero-padded) — strip to match id_ubigeo
r21["id_ubigeo"] = (r21["UBIGEO"].astype(str).str.strip()
                    .str.zfill(6).str.lstrip("0").replace("", "0"))
r21 = r21[r21["UBIGEO"].astype(str).str.strip().str.match(r"^\d{6}$")]

# Aggregate to district level
agg21 = r21.groupby("id_ubigeo")[["VOTOS_P1","VOTOS_P2","VOTOS_VB","VOTOS_VN","VOTOS_VI"]].sum().reset_index()
agg21["votos_validos_2021"] = agg21["VOTOS_P1"] + agg21["VOTOS_P2"]
agg21["castillo_2021_share"] = (
    agg21["VOTOS_P1"] / agg21["votos_validos_2021"] * 100
).round(4)
agg21["keiko_2021_share"] = (
    agg21["VOTOS_P2"] / agg21["votos_validos_2021"] * 100
).round(4)
agg21 = agg21[["id_ubigeo","castillo_2021_share","keiko_2021_share"]]
print(f"  2021 districts: {len(agg21)}")

merged = merged.merge(agg21, on="id_ubigeo", how="left")
print(f"  2021 matched: {merged['keiko_2021_share'].notna().sum()}/{len(merged)}")

# ── Final output ───────────────────────────────────────────────────────────
final = merged[[
    "id_ubigeo",
    "departamento", "provincia", "distrito",
    "electores", "area_km2", "population_density",
    "keiko_2021_share", "castillo_2021_share",
    "rural", "pobreza",
]].copy()

# Rename for clarity
final = final.rename(columns={
    "id_ubigeo":    "ubigeo",
    "departamento": "departamento",
    "provincia":    "provincia",
    "distrito":     "distrito",
    "electores":    "electores",
    "pobreza":      "pobreza",
})

final.to_csv(OUT, index=False)
print(f"\nSaved → {OUT}  ({len(final)} rows)")
print(f"NaN ubigeo:              {final['ubigeo'].isna().sum()}")
print(f"NaN area_km2:            {final['area_km2'].isna().sum()}")
print(f"NaN keiko_2021_share:    {final['keiko_2021_share'].isna().sum()}")
print(f"NaN castillo_2021_share: {final['castillo_2021_share'].isna().sum()}")
print(f"\nSample:\n{final.head(5).to_string()}")
