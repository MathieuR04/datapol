"""
03_build_geojson.py — Peru 2026 EG Primera Vuelta
Merge district-level election results into GeoJSON files for the frontend.

Key Peru differences from Colombia:
  - 3 geographic levels: distrito, provincia, departamento
  - No votos_no_marcados (only votos_blancos and votos_nulos)
  - Blank/null votes are NOT valid votes; votos_validos = sum of candidate votes only
  - denominator for turnout = num_electores from electoral roll

GEOMETRY APPROACH
-----------------
Province and department GeoJSONs are built by DISSOLVING the district GeoJSON,
not from separate province/dept shapefiles.  This guarantees:
  • No gaps or overlaps between province/dept polygons
  • Province borders in district view align exactly with province polygon edges
  • Rivers / lakes that form district borders don't leave cracks

Dissolved geometries are simplified with tolerance=0.001° (~111m) to keep
file sizes manageable.  The district GeoJSON is left unsimplified (full resolution).

Inputs:
  metadata/peru_2026_distrito.geojson          ← geometry source for ALL levels
  metadata/peru_2026_distrito_electoral_roll.csv
  data/results/peru_2026eg_distrito_primera.csv
  data/candidates.json

Outputs (written to data/):
  peru_2026eg_distrito_primera.geojson
  peru_2026eg_provincia_primera.geojson    ← dissolved from districts
  peru_2026eg_departamento_primera.geojson ← dissolved from districts
"""

import json
import math
import pandas as pd
import geopandas as gpd
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


def load_candidate_lookup(path: Path) -> dict:
    with open(path) as f:
        cands = json.load(f)
    return {c["codigo"]: {"nombre": c.get("nombre", c["codigo"]),
                          "color":  c.get("color", "#888")} for c in cands}


def compute_winner(row, cand_cols: list[str], cand_lkp: dict):
    best_code, best_votes = None, 0
    for col in cand_cols:
        code = col.replace("cand_", "")
        v = int(row.get(col) or 0)
        if v > best_votes:
            best_votes, best_code = v, code
    if best_code and best_votes > 0:
        info = cand_lkp.get(best_code, {})
        return info.get("nombre", best_code), info.get("color", "#888"), best_votes
    return None, None, 0


def all_candidates_json(row, cand_cols: list[str], cand_lkp: dict) -> str:
    entries = []
    for col in cand_cols:
        v = int(row.get(col) or 0)
        if not v:
            continue
        code = col.replace("cand_", "")
        info = cand_lkp.get(code, {})
        entries.append({"name":  info.get("nombre", code),
                        "color": info.get("color", "#888"),
                        "votes": v})
    return json.dumps(sorted(entries, key=lambda x: -x["votes"]), ensure_ascii=False)


def enrich(df: pd.DataFrame, cand_cols: list[str], cand_lkp: dict,
           electores_map: dict, mesas_map: dict) -> pd.DataFrame:
    df = df.copy()

    numeric = (["votos_validos", "votos_blancos", "votos_nulos",
                "actas_contabilizadas", "actas_total"] + cand_cols)
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # electores (eligible voters) from roll
    key_col = "ubigeo_distrito"
    df["num_electores"] = pd.to_numeric(
        df[key_col].map(electores_map), errors="coerce").fillna(0).astype(int)
    df["num_mesas"] = pd.to_numeric(
        df[key_col].map(mesas_map), errors="coerce").fillna(0).astype(int)

    # In Peru: votos emitidos = votos_validos + votos_blancos + votos_nulos
    df["votos_emitidos"] = df["votos_validos"] + df.get("votos_blancos", 0) + df.get("votos_nulos", 0)

    # turnout over eligible voters
    electores_s = df["num_electores"].astype(float)
    df["turnout_pct"] = (
        (df["votos_emitidos"] / electores_s.replace(0, float("nan")) * 100)
        .round(1).fillna(0)
    )

    winners = df.apply(lambda r: compute_winner(r, cand_cols, cand_lkp), axis=1)
    df["winner"]       = winners.map(lambda x: x[0])
    df["winner_color"] = winners.map(lambda x: x[1])
    df["winner_votes"] = winners.map(lambda x: x[2])
    df["all_candidates"] = df.apply(
        lambda r: all_candidates_json(r, cand_cols, cand_lkp), axis=1)

    return df


def build_geojson(df: pd.DataFrame, geo_path: Path, key_col: str,
                  out_path: Path) -> None:
    with open(geo_path) as f:
        geo = json.load(f)

    keep = ["votos_validos", "votos_blancos", "votos_nulos", "votos_emitidos",
            "num_electores", "num_mesas", "actas_contabilizadas", "actas_total",
            "turnout_pct", "winner", "winner_votes", "winner_color", "all_candidates"]

    result_dict = df.set_index(key_col).to_dict(orient="index")
    matched, kept = 0, []
    for feat in geo["features"]:
        code = str(feat["properties"].get(key_col, ""))
        if code in result_dict:
            row = result_dict[code]
            feat["properties"].update({k: row[k] for k in keep if k in row})
            matched += 1
        kept.append(feat)

    geo["features"] = kept
    geo_name = out_path.name
    level = key_col.replace("ubigeo_", "")
    print(f"  {level:14s}: {matched}/{len(kept)} features matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {geo_name}")


def aggregate_results(df: pd.DataFrame, group_col: str,
                      cand_cols: list[str], cand_lkp: dict) -> pd.DataFrame:
    """Aggregate distrito results up to province or dept level. Returns flat DataFrame."""
    agg_cols = ["votos_validos", "votos_blancos", "votos_nulos",
                "votos_emitidos", "num_electores", "num_mesas",
                "actas_contabilizadas", "actas_total"]

    df2 = df.copy()
    numeric_cols = [c for c in agg_cols + cand_cols if c in df2.columns]
    for c in numeric_cols:
        df2[c] = pd.to_numeric(df2[c], errors="coerce").fillna(0)

    agg = df2.groupby(group_col)[numeric_cols].sum().reset_index()
    for c in numeric_cols:
        agg[c] = pd.to_numeric(agg[c], errors="coerce").fillna(0)

    electores_s = agg["num_electores"].astype(float)
    agg["votos_emitidos"] = (agg["votos_validos"]
                             + agg["votos_blancos"].fillna(0)
                             + agg["votos_nulos"].fillna(0))
    agg["turnout_pct"] = (
        agg["votos_emitidos"] / electores_s.replace(0, float("nan")) * 100
    ).round(1).fillna(0)

    agg_cand_cols = [c for c in cand_cols if c in agg.columns]
    winners = agg.apply(lambda r: compute_winner(r, agg_cand_cols, cand_lkp), axis=1)
    agg["winner"]        = winners.map(lambda x: x[0])
    agg["winner_color"]  = winners.map(lambda x: x[1])
    agg["winner_votes"]  = winners.map(lambda x: x[2])
    agg["all_candidates"]= agg.apply(
        lambda r: all_candidates_json(r, agg_cand_cols, cand_lkp), axis=1)

    # Carry name columns from first district in each group
    for name_col in ["nombre_provincia", "nombre_dept", "nombre_distrito"]:
        if name_col in df2.columns:
            first = df2.groupby(group_col)[name_col].first().reset_index()
            agg = agg.merge(first, on=group_col, how="left")

    return agg


SIMPLIFY_TOL = 0.001   # degrees ≈ 111m — invisible at province/dept zoom levels


def build_dissolved_geojson(dist_geo_path: Path, df_agg: pd.DataFrame,
                             group_col: str, out_path: Path) -> None:
    """
    Build province or dept GeoJSON by dissolving the district GeoJSON.

    Steps:
      1. Load district GeoJSON into a GeoDataFrame.
      2. Dissolve by group_col (ubigeo_provincia or ubigeo_dept).
      3. Simplify to reduce file size.
      4. Merge with aggregated election data.
      5. Write output GeoJSON.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # suppress CRS buffer warnings

        gdf = gpd.read_file(dist_geo_path)
        if group_col not in gdf.columns:
            raise ValueError(f"'{group_col}' not found in district GeoJSON properties")

        # Dissolve — unary_union of all district polygons per group
        dissolved = gdf[[group_col, "geometry"]].dissolve(by=group_col).reset_index()

        # Simplify to reduce file size (preserve topology to avoid self-intersections)
        dissolved.geometry = dissolved.geometry.simplify(
            SIMPLIFY_TOL, preserve_topology=True)

        # Carry nombre columns from district gdf if available
        for col in ["nombre_provincia", "nombre_dept"]:
            if col in gdf.columns:
                first = gdf.groupby(group_col)[col].first().reset_index()
                dissolved = dissolved.merge(first, on=group_col, how="left")

    # Merge aggregated election data
    keep = ["votos_validos", "votos_blancos", "votos_nulos", "votos_emitidos",
            "num_electores", "num_mesas", "actas_contabilizadas", "actas_total",
            "turnout_pct", "winner", "winner_votes", "winner_color", "all_candidates"]
    merge_cols = [c for c in [group_col] + keep if c in df_agg.columns]
    dissolved = dissolved.merge(df_agg[merge_cols], on=group_col, how="left")

    # Build GeoJSON manually to control output
    features = []
    for _, row in dissolved.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        props = {}
        for col in dissolved.columns:
            if col == "geometry":
                continue
            v = row[col]
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            props[col] = v
        features.append({
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": props,
        })

    geo = {"type": "FeatureCollection", "features": features}
    level = group_col.replace("ubigeo_", "")
    print(f"  {level:14s}: {len(features)} dissolved features")

    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False, separators=(",", ":"))

    size_mb = out_path.stat().st_size / 1e6
    print(f"  Saved → {out_path.name}  ({size_mb:.1f} MB)")


def main():
    print("Loading lookups …")
    cand_lkp = load_candidate_lookup(DATA_DIR / "candidates.json")

    roll = pd.read_csv(METADATA / "peru_2026_distrito_electoral_roll.csv", dtype=str)
    roll["num_electores"] = pd.to_numeric(roll.get("num_electores", 0),
                                          errors="coerce").fillna(0).astype(int)
    roll["num_mesas"]     = pd.to_numeric(roll.get("num_mesas", 0),
                                          errors="coerce").fillna(0).astype(int)
    electores_map = roll.set_index("ubigeo_distrito")["num_electores"].to_dict()
    mesas_map     = roll.set_index("ubigeo_distrito")["num_mesas"].to_dict()

    print("\nLoading district results …")
    csv_path  = DATA_DIR / "results" / "peru_2026eg_distrito_primera.csv"
    df = pd.read_csv(csv_path, dtype=str)
    cand_cols = [c for c in df.columns if c.startswith("cand_")]

    # Merge roll columns for province/dept aggregation
    roll_join = roll[["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept", "is_exterior"]].copy()
    df = df.merge(roll_join, on="ubigeo_distrito", how="left")
    df["is_exterior"] = df["is_exterior"].fillna(False).astype(str).str.lower().isin(["true", "1"])

    df = enrich(df, cand_cols, cand_lkp, electores_map, mesas_map)

    # GeoJSONs use national rows only — exterior has no polygon geometry
    df_nat = df[~df["is_exterior"]].copy()

    dist_geo_path = METADATA / "peru_2026_distrito.geojson"

    print("\nBuilding GeoJSONs (national territory only) …")

    # ── District (direct join, full resolution) ────────────────────────────────
    build_geojson(
        df_nat, dist_geo_path,
        "ubigeo_distrito",
        DATA_DIR / "peru_2026eg_distrito_primera.geojson"
    )

    # ── Province & Dept (dissolved from districts) ─────────────────────────────
    # Dissolving from the district shapes guarantees:
    #   • no topology gaps between neighbouring polygons
    #   • province borders in district-view overlay align with polygon edges
    print(f"  (dissolving provinces from districts; simplify={SIMPLIFY_TOL}°) …")

    prov_agg = aggregate_results(df_nat, "ubigeo_provincia", cand_cols, cand_lkp)
    build_dissolved_geojson(
        dist_geo_path, prov_agg, "ubigeo_provincia",
        DATA_DIR / "peru_2026eg_provincia_primera.geojson"
    )

    dept_agg = aggregate_results(df_nat, "ubigeo_dept", cand_cols, cand_lkp)
    build_dissolved_geojson(
        dist_geo_path, dept_agg, "ubigeo_dept",
        DATA_DIR / "peru_2026eg_departamento_primera.geojson"
    )

    n_ext = df["is_exterior"].sum()
    if n_ext:
        print(f"\n  Note: {n_ext} exterior rows excluded from GeoJSONs (no geometry).")


if __name__ == "__main__":
    main()
