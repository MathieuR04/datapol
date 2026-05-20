"""
06_build_geojson.py
Merge election results into GeoJSON for the frontend.
Uses mpio_reg_code_5 (5-digit Registraduría code = map 'name' property) as join key.
Outputs:
  colombia_results_map.geojson    (municipio-level, national only)
  colombia_results_dept.geojson   (dept-level, national only)
"""

import json
import math
import pandas as pd
from pathlib import Path


def _clean(obj):
    """Recursively replace float NaN/Inf with None so output is valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

def load_party_lookup():
    OUT2 = Path(__file__).parent.parent / "data" / "processed"
    with open(OUT2 / "parties.json") as f:
        return json.load(f)  # "XXXX" → {nombre, color}

OUT = Path(__file__).parent.parent / "data" / "processed"


def build_geojson():
    print("Loading data …")
    party_lookup = load_party_lookup()

    with open(OUT / "colombia_municipios.geojson") as f:
        mpio_geo = json.load(f)

    mpio_results = pd.read_csv(OUT / "resultados_municipios.csv",
                               dtype={"mpio_reg_code_7": str, "mpio_dane_code": str})

    # Build mpio_reg_code_5 from mpio_reg_code_7: drop the "00" in positions 2:4
    # mpio_reg_code_7 = dd + "00" + mmm  →  mpio_reg_code_5 = dd + mmm
    mpio_results["mpio_reg_code_5"] = (
        mpio_results["mpio_reg_code_7"].str[:2] + mpio_results["mpio_reg_code_7"].str[4:]
    )

    # Columns to embed in GeoJSON (keep lightweight)
    keep_cols = [
        "mpio_reg_code_5", "mpio_name_reg", "mpio_name_dane",
        "mpio_dane_code", "dept_reg_code", "dept_dane_code",
        "votantes", "censo", "votos_validos", "votos_blanco",
        "votos_nulos", "votos_no_marcados", "mesas_total", "mesas_escrutadas",
        "turnout_pct", "pct_blanco", "pct_nulo",
        "winner", "winner_votes", "winner_pct", "winner_color",
    ]
    keep_cols = [c for c in keep_cols if c in mpio_results.columns]
    results_slim = mpio_results[keep_cols].copy()

    # Embed top-5 parties per municipio as JSON string
    party_cols = [c for c in mpio_results.columns if c.startswith("party_")]
    if party_cols:
        def top5_parties(row):
            entries = []
            for col in party_cols:
                code = col.replace("party_", "")
                info = party_lookup.get(code, {})
                entries.append({
                    "name": info.get("nombre", code),
                    "color": info.get("color", "#888"),
                    "votes": int(row[col])
                })
            top = sorted(entries, key=lambda x: -x["votes"])
            return json.dumps(top, ensure_ascii=False)
        results_slim["top5_candidates"] = mpio_results.apply(top5_parties, axis=1)

    results_dict = results_slim.set_index("mpio_reg_code_5").to_dict(orient="index")

    # Merge into features
    matched = 0
    for feat in mpio_geo["features"]:
        code5 = feat["properties"].get("mpio_reg_code_5", "")
        if code5 in results_dict:
            feat["properties"].update(results_dict[code5])
            matched += 1

    print(f"  Matched {matched}/{len(mpio_geo['features'])} features")

    out_path = OUT / "colombia_results_map.geojson"
    with open(out_path, "w") as f:
        json.dump(_clean(mpio_geo), f, ensure_ascii=False)
    print(f"  Saved → colombia_results_map.geojson")

    # ── dept-level GeoJSON ────────────────────────────────────────────────────
    with open(RAW := Path(__file__).parent.parent / "data" / "raw" / "00.geojson") as f:
        dept_geo = json.load(f)

    dept_results = pd.read_csv(OUT / "resultados_departamentos.csv", dtype=str)
    # dept_reg_code in results = dd + "00"; in map "00" features, 'name' = 2-digit dept num
    dept_results["dept_map_num"] = dept_results["dept_reg_code"].str[:2]

    dept_keep = [
        "dept_map_num", "dept_name_reg", "dept_name_dane", "dept_dane_code",
        "votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos", "votos_no_marcados",
        "mesas_total", "mesas_escrutadas", "turnout_pct", "pct_blanco", "pct_nulo",
        "winner", "winner_votes", "winner_pct", "winner_color",
    ]
    dept_keep = [c for c in dept_keep if c in dept_results.columns]

    # Add top5 parties per dept
    dept_party = [c for c in dept_results.columns if c.startswith("party_")]
    if dept_party:
        def dept_top5(row):
            entries = []
            for col in dept_party:
                code = col.replace("party_", "")
                info = party_lookup.get(code, {})
                entries.append({
                    "name": info.get("nombre", code),
                    "color": info.get("color", "#888"),
                    "votes": int(float(row[col]))
                })
            top = sorted(entries, key=lambda x: -x["votes"])
            return json.dumps(top, ensure_ascii=False)
        dept_results["top5_candidates"] = dept_results.apply(dept_top5, axis=1)
        dept_keep.append("top5_candidates")

    dept_dict = dept_results[dept_keep].set_index("dept_map_num").to_dict(orient="index")

    dept_matched = 0
    kept_features = []
    for feat in dept_geo.get("features", []):
        props = feat.get("properties", {})
        key = str(props.get("name", "")).zfill(2)
        if key not in dept_dict:
            continue  # drop Consulados and any unmapped features
        props.update(dept_dict[key])
        dept_matched += 1
        kept_features.append(feat)

    dept_geo["features"] = kept_features
    print(f"  Dept features matched: {dept_matched}/{len(dept_geo.get('features',[]))}")

    dept_out = OUT / "colombia_results_dept.geojson"
    with open(dept_out, "w") as f:
        json.dump(_clean(dept_geo), f, ensure_ascii=False)
    print(f"  Saved → colombia_results_dept.geojson")

    return matched


def build_indigena_geojson():
    """Build municipio and dept GeoJSON for the indigenous constituency."""
    party_lookup = load_party_lookup()

    mpio_csv = OUT / "resultados_municipios_indigena.csv"
    dept_csv = OUT / "resultados_departamentos_indigena.csv"
    if not mpio_csv.exists():
        print("  No resultados_municipios_indigena.csv — skipping indigenous GeoJSON")
        return

    with open(OUT / "colombia_municipios.geojson") as f:
        mpio_geo = json.load(f)

    mpio_ind = pd.read_csv(mpio_csv, dtype={"mpio_reg_code_7": str, "mpio_dane_code": str})
    mpio_ind["mpio_reg_code_5"] = (
        mpio_ind["mpio_reg_code_7"].str[:2] + mpio_ind["mpio_reg_code_7"].str[4:]
    )

    indig_cols = [c for c in mpio_ind.columns if c.startswith("indig_")]
    keep = ["mpio_reg_code_5", "mpio_name_reg", "mpio_dane_code",
            "dept_reg_code", "dept_dane_code",
            "votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos", "votos_no_marcados",
            "mesas_total", "mesas_escrutadas", "turnout_pct", "pct_blanco", "pct_nulo",
            "winner", "winner_votes", "winner_pct", "winner_color"]
    keep = [c for c in keep if c in mpio_ind.columns]
    slim = mpio_ind[keep].copy()

    if indig_cols:
        def top5_indig(row):
            entries = []
            for col in indig_cols:
                code = col.replace("indig_", "")
                info = party_lookup.get(code, {})
                entries.append({"name": info.get("nombre", code),
                                 "color": info.get("color", "#888"),
                                 "votes": int(row[col])})
            top = sorted(entries, key=lambda x: -x["votes"])
            return json.dumps(top, ensure_ascii=False)
        slim["top5_candidates"] = mpio_ind.apply(top5_indig, axis=1)

    results_dict = slim.set_index("mpio_reg_code_5").to_dict(orient="index")
    matched = 0
    for feat in mpio_geo["features"]:
        code5 = feat["properties"].get("mpio_reg_code_5", "")
        if code5 in results_dict:
            feat["properties"].update(results_dict[code5])
            matched += 1

    print(f"  Indigenous mpio matched: {matched}/{len(mpio_geo['features'])}")
    with open(OUT / "colombia_results_indigena_map.geojson", "w") as f:
        json.dump(_clean(mpio_geo), f, ensure_ascii=False)
    print("  Saved → colombia_results_indigena_map.geojson")

    # Dept
    with open(Path(__file__).parent.parent / "data" / "raw" / "00.geojson") as f:
        dept_geo = json.load(f)

    dept_ind = pd.read_csv(dept_csv, dtype=str)
    dept_ind["dept_map_num"] = dept_ind["dept_reg_code"].str[:2]
    dept_keep = ["dept_map_num", "dept_name_reg", "dept_name_dane", "dept_dane_code",
                 "votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos", "votos_no_marcados",
                 "mesas_total", "mesas_escrutadas", "turnout_pct", "pct_blanco", "pct_nulo",
                 "winner", "winner_votes", "winner_pct", "winner_color"]
    dept_indig_cols = [c for c in dept_ind.columns if c.startswith("indig_")]
    dept_keep = [c for c in dept_keep if c in dept_ind.columns]

    if dept_indig_cols:
        def dept_top5_indig(row):
            entries = []
            for col in dept_indig_cols:
                code = col.replace("indig_", "")
                info = party_lookup.get(code, {})
                v = int(float(row[col])) if row[col] not in ("", "nan") else 0
                entries.append({"name": info.get("nombre", code), "color": info.get("color", "#888"), "votes": v})
            return json.dumps(sorted(entries, key=lambda x: -x["votes"])[:5], ensure_ascii=False)
        dept_ind["top5_candidates"] = dept_ind.apply(dept_top5_indig, axis=1)
        dept_keep.append("top5_candidates")

    dept_dict = dept_ind[dept_keep].set_index("dept_map_num").to_dict(orient="index")
    dept_matched = 0
    kept = []
    for feat in dept_geo.get("features", []):
        key = str(feat.get("properties", {}).get("name", "")).zfill(2)
        if key not in dept_dict:
            continue
        feat["properties"].update(dept_dict[key])
        dept_matched += 1
        kept.append(feat)
    dept_geo["features"] = kept

    print(f"  Indigenous dept matched: {dept_matched}")
    with open(OUT / "colombia_results_indigena_dept.geojson", "w") as f:
        json.dump(_clean(dept_geo), f, ensure_ascii=False)
    print("  Saved → colombia_results_indigena_dept.geojson")


if __name__ == "__main__":
    build_geojson()
    build_indigena_geojson()
