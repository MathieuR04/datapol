"""
03_build_geojson.py — Primera Vuelta 2026
Merge municipio-level election results into GeoJSON for the frontend.

Inputs:
  metadata/colombia_2026_municipio.geojson              ← base mpio map
  metadata/raw/00.geojson                               ← base dept map
  metadata/colombia_2026_municipio_electoral_roll.csv   ← censo / num_mesas per mpio
  data/results/colombia_2026_municipio_primera.csv
  data/candidates.json

Outputs (written to data/):
  colombia_2026_municipio_primera.geojson
  colombia_2026_dept_primera.geojson
"""

import json
import math
import pandas as pd
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"


def _clean(obj):
    """Replace float NaN/Inf with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


def load_candidate_lookup(path: Path) -> dict:
    """{code: {nombre, color}} from candidates.json."""
    with open(path) as f:
        cands = json.load(f)
    return {c["code"]: {"nombre": c.get("nombre", c["code"]),
                        "color":  c.get("color",  "#888")} for c in cands}


def compute_winner(row, cand_cols: list[str], cand_lkp: dict):
    """Return (winner_name, winner_color, winner_votes) from row data."""
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


def top5_json(row, cand_cols: list[str], cand_lkp: dict) -> str:
    """Return JSON string of top-5 candidates by votes."""
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
    top5 = sorted(entries, key=lambda x: -x["votes"])[:5]
    return json.dumps(top5, ensure_ascii=False)


def enrich(df: pd.DataFrame, cand_cols: list[str], cand_lkp: dict,
           censo_map: dict, mesas_map: dict) -> pd.DataFrame:
    """Add winner_*, turnout_pct, and top5_candidates to df in place."""
    df = df.copy()

    numeric = (["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas"] + cand_cols)
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # censo: scraped value if present and non-zero; else fall back to roll
    if "censo" in df.columns:
        scraped = pd.to_numeric(df["censo"], errors="coerce").fillna(0)
        roll    = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map), errors="coerce").fillna(0)
        df["censo"] = scraped.where(scraped > 0, roll).astype(int)
    else:
        df["censo"] = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map),
                                    errors="coerce").fillna(0).astype(int)

    # mesas_total: same fallback logic
    if "mesas_total" in df.columns:
        scraped_m = pd.to_numeric(df["mesas_total"], errors="coerce").fillna(0)
        roll_m    = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map), errors="coerce").fillna(0)
        df["mesas_total"] = scraped_m.where(scraped_m > 0, roll_m).astype(int)
    else:
        df["mesas_total"] = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map),
                                          errors="coerce").fillna(0).astype(int)

    votantes = pd.to_numeric(df["votantes"], errors="coerce").fillna(0)
    censo_s  = df["censo"].astype(float)
    df["turnout_pct"] = (
        (votantes / censo_s.replace(0, float("nan")) * 100).round(1).fillna(0)
    )

    winners = df.apply(lambda r: compute_winner(r, cand_cols, cand_lkp), axis=1)
    df["winner"]       = winners.map(lambda x: x[0])
    df["winner_color"] = winners.map(lambda x: x[1])
    df["winner_votes"] = winners.map(lambda x: x[2])
    df["top5_candidates"] = df.apply(
        lambda r: top5_json(r, cand_cols, cand_lkp), axis=1)

    return df


def build_mpio_geojson(df: pd.DataFrame, out_path: Path) -> None:
    with open(METADATA / "colombia_2026_municipio.geojson") as f:
        geo = json.load(f)

    result_dict = df.set_index("mpio_reg_code_7").to_dict(orient="index")

    keep = ["votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos",
            "votos_no_marcados", "mesas_total", "mesas_escrutadas",
            "turnout_pct", "winner", "winner_votes", "winner_color", "top5_candidates"]

    matched, kept_feats = 0, []
    for feat in geo["features"]:
        code7 = feat["properties"].get("mpio_reg_code_7", "")
        if str(code7).startswith("88"):
            continue          # exclude exterior — no geometry on Colombian map
        if code7 in result_dict:
            row = result_dict[code7]
            feat["properties"].update({k: row[k] for k in keep if k in row})
            matched += 1
        kept_feats.append(feat)

    geo["features"] = kept_feats
    print(f"  Mpio: {matched}/{len(kept_feats)} features matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


def build_dept_geojson(df: pd.DataFrame, cand_cols: list[str],
                       cand_lkp: dict, out_path: Path) -> None:
    with open(METADATA / "raw" / "00.geojson") as f:
        geo = json.load(f)

    agg_cols = ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas", "censo"]

    df = df.copy()
    df = df[~df["mpio_reg_code_7"].str.startswith("88")]   # exclude exterior
    df["dept_num"] = df["mpio_reg_code_7"].str[:2]

    numeric_cols = [c for c in agg_cols + cand_cols if c in df.columns]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    dept_agg = df.groupby("dept_num")[numeric_cols].sum().reset_index()

    for c in numeric_cols:
        dept_agg[c] = pd.to_numeric(dept_agg[c], errors="coerce").fillna(0)

    dept_cand_cols = [c for c in cand_cols if c in dept_agg.columns]

    dept_agg["turnout_pct"] = (
        dept_agg["votantes"].astype(float)
        / dept_agg["censo"].replace(0, float("nan")) * 100
    ).round(1).fillna(0)

    winners = dept_agg.apply(lambda r: compute_winner(r, dept_cand_cols, cand_lkp), axis=1)
    dept_agg["winner"]       = winners.map(lambda x: x[0])
    dept_agg["winner_color"] = winners.map(lambda x: x[1])
    dept_agg["winner_votes"] = winners.map(lambda x: x[2])
    dept_agg["top5_candidates"] = dept_agg.apply(
        lambda r: top5_json(r, dept_cand_cols, cand_lkp), axis=1)

    result_dict = dept_agg.set_index("dept_num").to_dict(orient="index")

    keep = ["votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos",
            "votos_no_marcados", "mesas_total", "mesas_escrutadas",
            "turnout_pct", "winner", "winner_votes", "winner_color", "top5_candidates"]

    matched, kept_feats = 0, []
    for feat in geo.get("features", []):
        key = str(feat["properties"].get("name", "")).zfill(2)
        if key not in result_dict:
            continue
        row = result_dict[key]
        feat["properties"].update({k: row[k] for k in keep if k in row})
        matched += 1
        kept_feats.append(feat)

    geo["features"] = kept_feats
    print(f"  Dept:  {matched} departments matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


def main():
    print("Loading lookups …")
    cand_lkp = load_candidate_lookup(OUT / "candidates.json")

    roll = pd.read_csv(METADATA / "colombia_2026_municipio_electoral_roll.csv", dtype=str)
    roll["censo"]     = pd.to_numeric(roll["censo"],     errors="coerce").fillna(0).astype(int)
    roll["num_mesas"] = pd.to_numeric(roll["num_mesas"], errors="coerce").fillna(0).astype(int)
    censo_map = roll.set_index("mpio_reg_code_7")["censo"].to_dict()
    mesas_map = roll.set_index("mpio_reg_code_7")["num_mesas"].to_dict()

    print("\nBuilding primera vuelta GeoJSONs …")
    csv_path = OUT / "results" / "colombia_2026_municipio_primera.csv"
    df = pd.read_csv(csv_path, dtype=str)
    cand_cols = [c for c in df.columns if c.startswith("cand_")]
    df = enrich(df, cand_cols, cand_lkp, censo_map, mesas_map)

    build_mpio_geojson(df, OUT / "colombia_2026_municipio_primera.geojson")
    build_dept_geojson(df, cand_cols, cand_lkp, OUT / "colombia_2026_dept_primera.geojson")


if __name__ == "__main__":
    main()
