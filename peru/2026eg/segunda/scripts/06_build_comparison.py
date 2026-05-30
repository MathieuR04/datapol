"""
06_build_comparison.py — Peru 2026 EG Segunda Vuelta
Build comparison GeoJSONs: 2026 runoff candidate vs 2021 runoff reference.

Comparisons
-----------
  A: Keiko Fujimori 2026         vs Keiko Fujimori 2021       (Fuerza Popular)
  B: Roberto Sánchez 2026        vs Pedro Castillo 2021        (left bloc)

Column mapping — 2021 segunda vuelta CSV
-----------------------------------------
  P1  → PARTIDO POLITICO NACIONAL PERU LIBRE → Pedro Castillo
  P2  → FUERZA POPULAR                       → Keiko Fujimori

Outputs (data/comparison/)
--------------------------
  peru_2026_segunda_distrito_comparison.geojson
  peru_2026_segunda_provincia_comparison.geojson
  peru_2026_segunda_departamento_comparison.geojson
"""

import csv, json, math
import pandas as pd
import geopandas as gpd
import shapely
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"
COMP_DIR   = DATA_DIR / "comparison"
RAW_DIR    = COMP_DIR / "raw"
OUT_DIR    = DATA_DIR / "comparison"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERU_CRS = "EPSG:32718"
MIN_COMPONENT_RATIO = 0.05

# ── Comparison definitions ──────────────────────────────────────────────────

COMPARISONS = {
    "A": {
        "label":     "Keiko 2026 vs Keiko 2021",
        "cand_2026": "01",          # Keiko (codigo in candidates.json)
        "col_2021":  "VOTOS_P2",    # Fuerza Popular — 2021 segunda vuelta
        "ref_name":  "Keiko Fujimori 2021",
        "new_name":  "Keiko Fujimori 2026",
        "color_pos": "#16a34a",     # green = better than 2021
        "color_neg": "#dc2626",     # red   = worse than 2021
    },
    "B": {
        "label":     "R. Sánchez 2026 vs Castillo 2021",
        "cand_2026": "02",          # Roberto Sánchez
        "col_2021":  "VOTOS_P1",    # Peru Libre — 2021 segunda vuelta
        "ref_name":  "Pedro Castillo 2021",
        "new_name":  "Roberto Sánchez 2026",
        "color_pos": "#16a34a",
        "color_neg": "#dc2626",
    },
}

# Columns in the 2021 segunda vuelta CSV
COLS_2021_ALL_P = ["VOTOS_P1", "VOTOS_P2"]
COLS_2021       = COLS_2021_ALL_P + ["VOTOS_VB", "VOTOS_VN"]


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


# ── Load 2021 segunda vuelta results ────────────────────────────────────────

def load_2021(csv_path: Path) -> pd.DataFrame:
    """Aggregate 2021 segunda vuelta mesa results to district level."""
    print("Loading 2021 segunda vuelta results …")
    rows = []
    with open(csv_path, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("TIPO_ELECCION", "").strip() != "PRESIDENCIAL":
                continue
            ubigeo = str(row.get("UBIGEO", "")).zfill(6)
            r = {"ubigeo_distrito": ubigeo}
            for col in COLS_2021_ALL_P + ["VOTOS_VB", "VOTOS_VN"]:
                try:    r[col] = int(row.get(col, 0) or 0)
                except: r[col] = 0
            r["n_elec_habil"] = int(row.get("N_ELEC_HABIL", 0) or 0)
            rows.append(r)

    df = pd.DataFrame(rows)
    agg_cols = [c for c in COLS_2021_ALL_P + ["VOTOS_VB", "VOTOS_VN", "n_elec_habil"]
                if c in df.columns]
    grp = df.groupby("ubigeo_distrito")[agg_cols].sum().reset_index()
    # Valid votes = sum of the two candidate columns only
    p_cols = [c for c in COLS_2021_ALL_P if c in grp.columns]
    grp["votos_validos_2021"] = grp[p_cols].sum(axis=1)
    print(f"  {len(grp)} districts in 2021 segunda vuelta data")
    return grp


# ── Load 2026 district results ───────────────────────────────────────────────

def load_2026(csv_path: Path) -> pd.DataFrame:
    print("Loading 2026 segunda vuelta results …")
    df = pd.read_csv(csv_path, dtype=str)
    df["ubigeo_distrito"] = df["ubigeo_distrito"].str.zfill(6)
    num_cols = [c for c in df.columns if c.startswith("cand_") or c in
                ("votos_validos", "votos_emitidos", "actas_contabilizadas", "actas_total")]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _clean_dissolved(geom):
    if geom is None or geom.is_empty:
        return geom
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    polys = [shapely.Polygon(p.exterior) for p in polys]
    if not polys:
        return geom
    max_area = max(p.area for p in polys)
    polys = [p for p in polys if p.area / max_area >= MIN_COMPONENT_RATIO]
    if len(polys) == 1:
        return polys[0]
    return shapely.MultiPolygon(polys)


def dissolve_geojson(dist_gdf: gpd.GeoDataFrame, group_col: str) -> gpd.GeoDataFrame:
    gdf = dist_gdf.copy()
    gdf.geometry = gdf.geometry.buffer(0)
    gdf_utm = gdf.to_crs(PERU_CRS)
    gdf_utm.geometry = gdf_utm.geometry.apply(
        lambda g: shapely.make_valid(shapely.set_precision(g, grid_size=1.0))
    )
    dissolved = gdf_utm.dissolve(by=group_col, as_index=False)
    dissolved.geometry = dissolved.geometry.apply(_clean_dissolved)
    return dissolved.to_crs("EPSG:4326")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    csv_2021 = RAW_DIR / "Resultados por mesa de la Segunda Elección Presidencial 2021.csv"
    if not csv_2021.exists():
        raise FileNotFoundError(f"Missing: {csv_2021}")

    csv_2026     = DATA_DIR / "results" / "peru_2026eg_distrito_segunda.csv"
    dist_geojson = METADATA / "peru_2026_distrito.geojson"

    df21 = load_2021(csv_2021)
    df26 = load_2026(csv_2026)

    print("Loading district geometry …")
    dist_gdf = gpd.read_file(dist_geojson)
    ubigeo_col = next((c for c in dist_gdf.columns if "ubigeo" in c.lower() and "dist" in c.lower()), None)
    if ubigeo_col is None:
        ubigeo_col = next((c for c in dist_gdf.columns if "ubigeo" in c.lower()), None)
    dist_gdf = dist_gdf.rename(columns={ubigeo_col: "ubigeo_distrito"})
    dist_gdf["ubigeo_distrito"] = dist_gdf["ubigeo_distrito"].astype(str).str.zfill(6)

    prov_col = next((c for c in dist_gdf.columns if "prov" in c.lower() and "ubigeo" in c.lower()), None)
    dept_col = next((c for c in dist_gdf.columns if ("dept" in c.lower() or "dep" in c.lower()) and "ubigeo" in c.lower()), None)
    print(f"  Province col: {prov_col}  |  Dept col: {dept_col}")

    # Rename for consistency
    if prov_col and prov_col != "ubigeo_provincia":
        dist_gdf = dist_gdf.rename(columns={prov_col: "ubigeo_provincia"})
        prov_col = "ubigeo_provincia"
    if dept_col and dept_col != "ubigeo_dept":
        dist_gdf = dist_gdf.rename(columns={dept_col: "ubigeo_dept"})
        dept_col = "ubigeo_dept"

    # Build comparison stats per district
    print("\nBuilding comparison stats …")
    p_cols_in_21 = [c for c in COLS_2021_ALL_P if c in df21.columns]
    stats = df21[["ubigeo_distrito", "votos_validos_2021"] + p_cols_in_21].copy()
    stats = stats.merge(
        df26[["ubigeo_distrito", "votos_validos"] +
              [f"cand_{c['cand_2026']}" for c in COMPARISONS.values()]],
        on="ubigeo_distrito", how="left"
    )

    for key, comp in COMPARISONS.items():
        col21 = comp["col_2021"]
        col26 = f"cand_{comp['cand_2026']}"
        stats[f"votes21_{key}"] = stats[col21]
        stats[f"votes26_{key}"] = stats[col26]
        stats[f"pct21_{key}"]   = stats[col21] / stats["votos_validos_2021"].replace(0, float("nan")) * 100
        stats[f"pct26_{key}"]   = stats[col26] / stats["votos_validos"].replace(0, float("nan")) * 100
        stats[f"diff_{key}"]    = stats[f"pct26_{key}"] - stats[f"pct21_{key}"]

    stats = stats.fillna(0)

    merged_gdf = dist_gdf.merge(stats, on="ubigeo_distrito", how="left")
    if prov_col:
        merged_gdf["ubigeo_provincia"] = dist_gdf["ubigeo_provincia"].astype(str).str.zfill(4)
    if dept_col:
        merged_gdf["ubigeo_dept"] = dist_gdf["ubigeo_dept"].astype(str).str.zfill(2)

    # ── District GeoJSON ─────────────────────────────────────────────────────
    print("\nBuilding district comparison GeoJSON …")
    prop_cols = (["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept",
                  "votos_validos_2021", "votos_validos"] +
                 [f"votes21_{k}" for k in COMPARISONS] +
                 [f"votes26_{k}" for k in COMPARISONS] +
                 [f"pct21_{k}"   for k in COMPARISONS] +
                 [f"pct26_{k}"   for k in COMPARISONS] +
                 [f"diff_{k}"    for k in COMPARISONS])
    prop_cols = [c for c in prop_cols if c in merged_gdf.columns]

    dist_out = merged_gdf[["ubigeo_distrito", "geometry"] +
                           [c for c in prop_cols if c != "ubigeo_distrito"]].copy()
    for ncol in ["nombre_distrito", "nombre_provincia", "nombre_dept"]:
        if ncol in dist_gdf.columns:
            dist_out[ncol] = dist_gdf[ncol].values

    dist_out = dist_out.round({c: 4 for c in dist_out.columns
                               if c.startswith(("pct", "diff"))})
    out_path = OUT_DIR / "peru_2026_segunda_distrito_comparison.geojson"
    dist_out.to_file(out_path, driver="GeoJSON")
    print(f"  Saved → {out_path.name}  ({out_path.stat().st_size//1024} KB)")

    geo_lookup = dist_gdf[["ubigeo_distrito"] +
                           ([prov_col] if prov_col else []) +
                           ([dept_col] if dept_col else [])].copy()

    # ── Province GeoJSON ─────────────────────────────────────────────────────
    if prov_col and "ubigeo_provincia" in merged_gdf.columns:
        print("Dissolving provinces …")
        stat_prov = stats.merge(geo_lookup, on="ubigeo_distrito", how="left")
        agg_dict = {"votos_validos_2021": "sum", "votos_validos": "sum",
                    **{col: "sum" for col in p_cols_in_21},
                    **{f"cand_{c['cand_2026']}": "sum" for c in COMPARISONS.values()}}
        if dept_col:
            agg_dict[dept_col] = "first"
        prov_votes = stat_prov.groupby("ubigeo_provincia").agg(agg_dict).reset_index()
        prov_votes["votos_validos_2021"] = prov_votes[p_cols_in_21].sum(axis=1)

        for key, comp in COMPARISONS.items():
            col21 = comp["col_2021"]
            col26 = f"cand_{comp['cand_2026']}"
            prov_votes[f"votes21_{key}"] = prov_votes[col21]
            prov_votes[f"votes26_{key}"] = prov_votes[col26]
            prov_votes[f"pct21_{key}"]   = prov_votes[col21] / prov_votes["votos_validos_2021"].replace(0, float("nan")) * 100
            prov_votes[f"pct26_{key}"]   = prov_votes[col26] / prov_votes["votos_validos"].replace(0, float("nan")) * 100
            prov_votes[f"diff_{key}"]    = prov_votes[f"pct26_{key}"] - prov_votes[f"pct21_{key}"]
        prov_votes = prov_votes.fillna(0)

        prov_geom = dissolve_geojson(
            merged_gdf[["ubigeo_provincia", "geometry"]].copy(), "ubigeo_provincia")
        prov_out = prov_geom.merge(prov_votes, on="ubigeo_provincia", how="left")

        if "nombre_provincia" in dist_gdf.columns:
            prov_names = dist_gdf.groupby(prov_col)["nombre_provincia"].first()
            prov_names.index = prov_names.index.astype(str).str.zfill(4)
            prov_out["nombre_provincia"] = prov_out["ubigeo_provincia"].map(prov_names)

        diff_cols = ([f"pct21_{k}" for k in COMPARISONS] +
                     [f"pct26_{k}" for k in COMPARISONS] +
                     [f"diff_{k}"  for k in COMPARISONS])
        prov_out = prov_out.round({c: 4 for c in diff_cols if c in prov_out.columns})
        out_path = OUT_DIR / "peru_2026_segunda_provincia_comparison.geojson"
        prov_out.to_file(out_path, driver="GeoJSON")
        print(f"  Saved → {out_path.name}  ({out_path.stat().st_size//1024} KB)")

    # ── Dept GeoJSON ─────────────────────────────────────────────────────────
    if dept_col and "ubigeo_dept" in merged_gdf.columns:
        print("Dissolving departments …")
        stat_dept = stats.merge(
            geo_lookup[["ubigeo_distrito"] + ([dept_col] if dept_col else [])],
            on="ubigeo_distrito", how="left")
        agg_dict_d = {"votos_validos_2021": "sum", "votos_validos": "sum",
                      **{col: "sum" for col in p_cols_in_21},
                      **{f"cand_{c['cand_2026']}": "sum" for c in COMPARISONS.values()}}
        dept_votes = stat_dept.groupby("ubigeo_dept").agg(agg_dict_d).reset_index()
        dept_votes["votos_validos_2021"] = dept_votes[p_cols_in_21].sum(axis=1)

        for key, comp in COMPARISONS.items():
            col21 = comp["col_2021"]
            col26 = f"cand_{comp['cand_2026']}"
            dept_votes[f"votes21_{key}"] = dept_votes[col21]
            dept_votes[f"votes26_{key}"] = dept_votes[col26]
            dept_votes[f"pct21_{key}"]   = dept_votes[col21] / dept_votes["votos_validos_2021"].replace(0, float("nan")) * 100
            dept_votes[f"pct26_{key}"]   = dept_votes[col26] / dept_votes["votos_validos"].replace(0, float("nan")) * 100
            dept_votes[f"diff_{key}"]    = dept_votes[f"pct26_{key}"] - dept_votes[f"pct21_{key}"]
        dept_votes = dept_votes.fillna(0)

        dept_geom = dissolve_geojson(
            merged_gdf[["ubigeo_dept", "geometry"]].copy(), "ubigeo_dept")
        dept_out = dept_geom.merge(dept_votes, on="ubigeo_dept", how="left")

        if "nombre_dept" in dist_gdf.columns:
            dept_names = dist_gdf.groupby(dept_col)["nombre_dept"].first()
            dept_names.index = dept_names.index.astype(str).str.zfill(2)
            dept_out["nombre_dept"] = dept_out["ubigeo_dept"].map(dept_names)

        diff_cols = ([f"pct21_{k}" for k in COMPARISONS] +
                     [f"pct26_{k}" for k in COMPARISONS] +
                     [f"diff_{k}"  for k in COMPARISONS])
        dept_out = dept_out.round({c: 4 for c in diff_cols if c in dept_out.columns})
        out_path = OUT_DIR / "peru_2026_segunda_departamento_comparison.geojson"
        dept_out.to_file(out_path, driver="GeoJSON")
        print(f"  Saved → {out_path.name}  ({out_path.stat().st_size//1024} KB)")

    print("\nDone.")


if __name__ == "__main__":
    main()
