"""
build_geojson.py  —  Colombia Presidencial 2026, Primera Vuelta
Merge election results into GeoJSON for the frontend map.

Outputs:
  presidencial2026/processed/colombia_results_presidencial_map.geojson  (municipio)
  presidencial2026/processed/colombia_results_presidencial_dept.geojson (dept)
"""

import json
import math
import csv
from pathlib import Path

SHARED = Path(__file__).parent.parent.parent / "data" / "processed"
RAW    = Path(__file__).parent.parent.parent / "data" / "raw"
OUT    = Path(__file__).parent.parent.parent / "data" / "presidencial2026" / "processed"


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


def load_candidates() -> dict:
    with open(OUT / "candidates.json") as f:
        return {c["code"]: c for c in json.load(f)}


def top5_row(row: dict, cand_lookup: dict, cand_cols: list[str]) -> str:
    entries = []
    for code in cand_cols:
        info = cand_lookup.get(code, {})
        entries.append({"name": info.get("nombre", code),
                        "color": info.get("color", "#888"),
                        "votes": int(float(row.get(code) or 0))})
    return json.dumps(sorted(entries, key=lambda x: -x["votes"])[:5], ensure_ascii=False)


def build():
    cand_lookup = load_candidates()

    # ── Municipio ──────────────────────────────────────────────────────────────
    print("Building municipio GeoJSON …")
    with open(SHARED / "colombia_municipios.geojson") as f:
        mpio_geo = json.load(f)

    mpio_rows = {}
    cand_cols = []
    mpio_csv = OUT / "resultados_municipios.csv"
    if mpio_csv.exists():
        with open(mpio_csv) as f:
            reader = csv.DictReader(f)
            cand_cols = [c for c in (reader.fieldnames or []) if c in cand_lookup]
            for row in reader:
                # Build mpio_reg_code_5 from mpio_reg_code_7
                code7 = row.get("mpio_reg_code_7","")
                code5 = code7[:2] + code7[4:] if len(code7) >= 7 else code7
                row["top5_candidates"] = top5_row(row, cand_lookup, cand_cols)
                mpio_rows[code5] = row

    matched = 0
    keep_cols = ["mpio_name_reg","mpio_dane_code","dept_reg_code","dept_dane_code",
                 "votantes","censo","votos_validos","votos_blanco","votos_nulos",
                 "votos_no_marcados","mesas_total","mesas_escrutadas",
                 "turnout_pct","pct_blanco","pct_nulo",
                 "winner","winner_votes","winner_pct","winner_color","top5_candidates"]
    for feat in mpio_geo["features"]:
        code5 = feat["properties"].get("mpio_reg_code_5","")
        if code5 in mpio_rows:
            row = mpio_rows[code5]
            feat["properties"].update({k: row[k] for k in keep_cols if k in row})
            matched += 1

    print(f"  Matched {matched}/{len(mpio_geo['features'])} municipios")
    out_path = OUT / "colombia_results_presidencial_map.geojson"
    with open(out_path, "w") as f:
        json.dump(_clean(mpio_geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")

    # ── Dept ───────────────────────────────────────────────────────────────────
    print("Building dept GeoJSON …")
    with open(RAW / "00.geojson") as f:
        dept_geo = json.load(f)

    dept_rows = {}
    dept_csv = OUT / "resultados_departamentos.csv"
    if dept_csv.exists():
        with open(dept_csv) as f:
            reader = csv.DictReader(f)
            cand_cols = [c for c in (reader.fieldnames or []) if c in cand_lookup]
            for row in reader:
                key = row.get("dept_reg_code","")[:2]
                row["top5_candidates"] = top5_row(row, cand_lookup, cand_cols)
                dept_rows[key] = row

    dept_keep = ["dept_name_reg","dept_dane_code","votantes","censo","votos_validos",
                 "votos_blanco","votos_nulos","votos_no_marcados","mesas_total",
                 "mesas_escrutadas","turnout_pct","pct_blanco","pct_nulo",
                 "winner","winner_votes","winner_pct","winner_color","top5_candidates"]
    dept_matched = 0
    kept = []
    for feat in dept_geo.get("features",[]):
        key = str(feat.get("properties",{}).get("name","")).zfill(2)
        if key not in dept_rows: continue
        row = dept_rows[key]
        feat["properties"].update({k: row[k] for k in dept_keep if k in row})
        dept_matched += 1
        kept.append(feat)
    dept_geo["features"] = kept

    print(f"  Matched {dept_matched} depts")
    dept_path = OUT / "colombia_results_presidencial_dept.geojson"
    with open(dept_path, "w") as f:
        json.dump(_clean(dept_geo), f, ensure_ascii=False)
    print(f"  Saved → {dept_path.name}")


if __name__ == "__main__":
    build()
