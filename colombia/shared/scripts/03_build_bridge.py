"""
03_build_bridge.py
Parse colombia_all_maps.json to build Registraduría↔DANE code bridges.
Outputs:
  colombia/data/processed/dept_bridge.csv
  colombia/data/processed/mpio_bridge.csv
  colombia/data/processed/colombia_municipios.geojson  (~1,122 features, national only)
"""

import json
import pandas as pd
from pathlib import Path

RAW = Path(__file__).parent.parent / "data" / "raw"
OUT = Path(__file__).parent.parent / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)


def build_bridge():
    print("Loading colombia_all_maps.json …")
    with open(RAW / "colombia_all_maps.json") as f:
        all_maps = json.load(f)

    print(f"  Map keys: {sorted(all_maps.keys())}")

    dept_rows = []
    mpio_rows = []
    all_features = []

    # ── "00" key = national dept-level map ───────────────────────────────────
    dept_map = all_maps.get("00", {})
    for feat in dept_map.get("features", []):
        props = feat.get("properties", {})
        # name = 2-digit Registraduría dept number; DPTO = DANE 2-digit
        dept_map_num   = str(props.get("name", "")).zfill(2)
        dept_reg_code  = dept_map_num + "00"          # 4-char (matches nomenclator l2 'c')
        dept_dane_code = str(props.get("DPTO", props.get("DPTO_CCDGO", ""))).zfill(2)
        dept_name_reg  = props.get("NOMBRE_DPT", props.get("NOMBRE", ""))
        dept_name_dane = props.get("DANE", {}).get("dpto_cnmbr", dept_name_reg)
        if isinstance(dept_name_dane, dict):
            dept_name_dane = dept_name_reg

        dept_rows.append({
            "dept_map_num":   dept_map_num,
            "dept_reg_code":  dept_reg_code,
            "dept_name_reg":  dept_name_reg,
            "dept_dane_code": dept_dane_code,
            "dept_name_dane": dept_name_dane,
        })

    dept_df = pd.DataFrame(dept_rows)
    dept_df.to_csv(OUT / "dept_bridge.csv", index=False)
    print(f"\ndept_bridge.csv: {len(dept_df)} depts")

    # ── dept-level maps "01"–"34" etc = municipio features ───────────────────
    for map_key, geojson in all_maps.items():
        if map_key == "00" or map_key == "88":
            continue
        if not isinstance(geojson, dict) or "features" not in geojson:
            continue

        for feat in geojson["features"]:
            props = feat.get("properties", {})

            # Registraduría 5-digit mpio code (e.g. "01001")
            mpio_reg_code_5 = str(props.get("name", "")).zfill(5)
            # First 4 chars = dept_reg_code in nomenclator format
            dept_reg_code   = mpio_reg_code_5[:2] + "00"
            # First 7 chars in nomenclator mpio format = dept(4) + mpio(3)
            # Reconstruct: dept(2) + "00" + mpio(3) = mpio_reg_code_5[:2] + "00" + mpio_reg_code_5[2:]
            mpio_reg_code_7 = mpio_reg_code_5[:2] + "00" + mpio_reg_code_5[2:]

            mpio_name_reg  = props.get("NOMBRE", "")
            mpio_dane_code = str(props.get("MPIO_CCNCT", "")).zfill(5)
            dept_dane_code = str(props.get("DPTO_CCDGO", mpio_dane_code[:2] if mpio_dane_code else "")).zfill(2)
            dane_sub = props.get("DANE", {})
            mpio_name_dane = dane_sub.get("mpio_cnmbr", mpio_name_reg) if isinstance(dane_sub, dict) else mpio_name_reg

            mpio_rows.append({
                "mpio_reg_code_5": mpio_reg_code_5,
                "mpio_reg_code_7": mpio_reg_code_7,
                "mpio_name_reg":   mpio_name_reg,
                "mpio_dane_code":  mpio_dane_code,
                "mpio_name_dane":  mpio_name_dane,
                "dept_reg_code":   dept_reg_code,
                "dept_dane_code":  dept_dane_code,
            })

            # Keep feature for GeoJSON output (strip heavy props, add bridge keys)
            lean_feat = {
                "type": "Feature",
                "properties": {
                    "mpio_reg_code_5": mpio_reg_code_5,
                    "mpio_reg_code_7": mpio_reg_code_7,
                    "mpio_name_reg":   mpio_name_reg,
                    "mpio_dane_code":  mpio_dane_code,
                    "mpio_name_dane":  mpio_name_dane,
                    "dept_reg_code":   dept_reg_code,
                    "dept_dane_code":  dept_dane_code,
                },
                "geometry": feat.get("geometry"),
            }
            all_features.append(lean_feat)

    mpio_df = pd.DataFrame(mpio_rows).drop_duplicates(subset="mpio_reg_code_5")
    mpio_df.to_csv(OUT / "mpio_bridge.csv", index=False)
    print(f"mpio_bridge.csv: {len(mpio_df)} municipios")

    # ── merged national GeoJSON ───────────────────────────────────────────────
    geojson_out = {
        "type": "FeatureCollection",
        "features": all_features,
    }
    out_path = OUT / "colombia_municipios.geojson"
    with open(out_path, "w") as f:
        json.dump(geojson_out, f, ensure_ascii=False)
    print(f"colombia_municipios.geojson: {len(all_features)} features")
    print(f"\nAll outputs saved to colombia/data/processed/")

    return dept_df, mpio_df


if __name__ == "__main__":
    build_bridge()
