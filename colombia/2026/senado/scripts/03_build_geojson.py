"""
06_build_geojson.py
Merge municipio-level election results into GeoJSON for the frontend.

Inputs:
  metadata/colombia_2026_municipio.geojson          ← base mpio map
  metadata/raw/00.geojson                            ← base dept map
  metadata/colombia_2026_municipio_electoral_roll.csv ← censo per mpio
  data/results/colombia_2026_municipio_senado_nacional.csv
  data/results/colombia_2026_municipio_senado_indigena.csv
  data/national_parties.json
  data/indigena_parties.json

Outputs (written to data/):
  colombia_2026_municipio_senado_nacional.geojson
  colombia_2026_dept_senado_nacional.geojson
  colombia_2026_municipio_senado_indigena.geojson
  colombia_2026_dept_senado_indigena.geojson
"""

import json
import math
import pandas as pd
from pathlib import Path

OUT      = Path(__file__).parent.parent / "data"
METADATA = Path(__file__).parent.parent.parent / "metadata"


def _clean(obj):
    """Replace float NaN/Inf with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


def load_party_lookup():
    """
    {code_4digit_str: {nombre, color}} from national + indigena party JSONs.
    """
    lkp = {}
    for path in [OUT / "national_parties.json", OUT / "indigena_parties.json"]:
        if path.exists():
            for p in json.load(open(path)):
                lkp[str(p["code"]).zfill(4)] = {
                    "nombre":       p.get("nombre", p["code"]),
                    "display_name": p.get("display_name", ""),
                    "color":        p.get("color",  "#888"),
                }
    return lkp


def compute_winner(row, party_cols, prefix, lkp):
    """Return (winner_name, winner_color, winner_votes, winner_pct) from raw cols."""
    best_col, best_v = None, 0
    for col in party_cols:
        v = int(row.get(col, 0) or 0)
        if v > best_v:
            best_v, best_col = v, col
    if not best_col:
        return "", "#888", 0, 0.0
    code    = best_col.replace(prefix, "").zfill(4)
    info    = lkp.get(code, {})
    vv      = int(row.get("votos_validos", 0) or 0)
    wpct    = round(best_v / vv * 100, 2) if vv else 0.0
    name    = info.get("display_name") or info.get("nombre", code)
    return name, info.get("color", "#888"), best_v, wpct


def top5_json(row, party_cols, prefix, lkp):
    entries = []
    for col in party_cols:
        v = int(row.get(col, 0) or 0)
        if not v: continue
        code = col.replace(prefix, "").zfill(4)
        info = lkp.get(code, {})
        entries.append({"name": info.get("display_name") or info.get("nombre", code),
                        "color": info.get("color", "#888"),
                        "votes": v})
    return json.dumps(sorted(entries, key=lambda x: -x["votes"]), ensure_ascii=False)


def enrich(df, party_cols, prefix, lkp, censo_map, mesas_map):
    """Add winner_*, turnout_pct, pct_* and top5_candidates to df in place."""
    df = df.copy()
    for col in ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas"] + party_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # censo: scraped value takes priority; fall back to electoral roll if absent/zero.
    if "censo" in df.columns:
        scraped = pd.to_numeric(df["censo"], errors="coerce").fillna(0)
        roll    = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map), errors="coerce").fillna(0)
        df["censo"] = scraped.where(scraped > 0, roll).astype(int)
    else:
        df["censo"] = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map), errors="coerce").fillna(0).astype(int)

    # mesas_total: scraped value takes priority; fall back to electoral roll num_mesas.
    if "mesas_total" in df.columns:
        scraped_m = pd.to_numeric(df["mesas_total"], errors="coerce").fillna(0)
        roll_m    = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map), errors="coerce").fillna(0)
        df["mesas_total"] = scraped_m.where(scraped_m > 0, roll_m).astype(int)
    else:
        df["mesas_total"] = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map), errors="coerce").fillna(0).astype(int)
    votantes  = pd.to_numeric(df["votantes"],     errors="coerce").fillna(0)
    validos   = pd.to_numeric(df["votos_validos"],errors="coerce").fillna(0)
    blanco    = pd.to_numeric(df["votos_blanco"], errors="coerce").fillna(0)
    nulos     = pd.to_numeric(df["votos_nulos"],  errors="coerce").fillna(0)
    censo_s   = df["censo"].astype(float)
    df["turnout_pct"] = (votantes / censo_s.replace(0, float("nan"))   * 100).round(2).fillna(0)
    df["pct_blanco"]  = (blanco   / validos.replace(0, float("nan"))   * 100).round(2).fillna(0)
    df["pct_nulo"]    = (nulos    / votantes.replace(0, float("nan"))  * 100).round(2).fillna(0)

    winners = df.apply(lambda r: compute_winner(r, party_cols, prefix, lkp), axis=1)
    df["winner"]       = winners.map(lambda x: x[0])
    df["winner_color"] = winners.map(lambda x: x[1])
    df["winner_votes"] = winners.map(lambda x: x[2])
    df["winner_pct"]   = winners.map(lambda x: x[3])
    df["top5_candidates"] = df.apply(lambda r: top5_json(r, party_cols, prefix, lkp), axis=1)
    return df


def build_mpio_geojson(df, out_path, label):
    with open(METADATA / "colombia_2026_municipio.geojson") as f:
        geo = json.load(f)

    result_dict = df.set_index("mpio_reg_code_7").to_dict(orient="index")

    keep = ["votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos",
            "votos_no_marcados", "mesas_total", "mesas_escrutadas",
            "turnout_pct", "pct_blanco", "pct_nulo",
            "winner", "winner_votes", "winner_pct", "winner_color", "top5_candidates"]

    matched, kept_feats = 0, []
    for feat in geo["features"]:
        code7 = feat["properties"].get("mpio_reg_code_7", "")
        if str(code7).startswith("88"):
            continue                    # exclude exterior — world-map geometry
        if code7 in result_dict:
            row = result_dict[code7]
            feat["properties"].update({k: row[k] for k in keep if k in row})
            matched += 1
        kept_feats.append(feat)

    geo["features"] = kept_feats
    print(f"  {label} mpio: {matched}/{len(kept_feats)} features matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


def build_dept_geojson(df, out_path, label):
    with open(METADATA / "raw" / "00.geojson") as f:
        geo = json.load(f)

    # Aggregate mpio → dept
    agg_cols = ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas", "censo"]
    party_cols = [c for c in df.columns if c.startswith("party_") or c.startswith("indig_")]
    prefix     = "indig_" if any(c.startswith("indig_") for c in party_cols) else "party_"

    df = df.copy()
    df = df[~df["mpio_reg_code_7"].str.startswith("88")]   # exclude exterior
    df["dept_num"] = df["mpio_reg_code_7"].str[:2]

    numeric_cols = [c for c in agg_cols + party_cols if c in df.columns]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    dept_agg = df.groupby("dept_num")[numeric_cols].sum().reset_index()

    # Ensure aggregated columns are numeric (guards against all-zero / object dtype)
    for c in numeric_cols:
        dept_agg[c] = pd.to_numeric(dept_agg[c], errors="coerce").fillna(0)

    # Re-derive winner / pcts at dept level
    lkp = load_party_lookup()
    dept_party_cols = [c for c in party_cols if c in dept_agg.columns]
    dept_agg["turnout_pct"] = (dept_agg["votantes"].astype(float) / dept_agg["censo"].replace(0, float("nan")) * 100).round(2).fillna(0)
    dept_agg["pct_blanco"]  = (dept_agg["votos_blanco"].astype(float) / dept_agg["votos_validos"].replace(0, float("nan")) * 100).round(2).fillna(0)
    dept_agg["pct_nulo"]    = (dept_agg["votos_nulos"].astype(float)  / dept_agg["votantes"].replace(0, float("nan")) * 100).round(2).fillna(0)

    winners = dept_agg.apply(lambda r: compute_winner(r, dept_party_cols, prefix, lkp), axis=1)
    dept_agg["winner"]         = winners.map(lambda x: x[0])
    dept_agg["winner_color"]   = winners.map(lambda x: x[1])
    dept_agg["winner_votes"]   = winners.map(lambda x: x[2])
    dept_agg["winner_pct"]     = winners.map(lambda x: x[3])
    dept_agg["top5_candidates"] = dept_agg.apply(
        lambda r: top5_json(r, dept_party_cols, prefix, lkp), axis=1)

    result_dict = dept_agg.set_index("dept_num").to_dict(orient="index")

    keep = ["votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos",
            "votos_no_marcados", "mesas_total", "mesas_escrutadas",
            "turnout_pct", "pct_blanco", "pct_nulo",
            "winner", "winner_votes", "winner_pct", "winner_color", "top5_candidates"]

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
    print(f"  {label} dept:  {matched} departments matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


def main():
    print("Loading lookups …")
    lkp = load_party_lookup()

    # Electoral roll → censo and num_mesas per mpio (fallbacks when not in results CSV)
    roll = pd.read_csv(METADATA / "colombia_2026_municipio_electoral_roll.csv", dtype=str)
    roll["censo"]     = pd.to_numeric(roll["censo"],     errors="coerce").fillna(0).astype(int)
    roll["num_mesas"] = pd.to_numeric(roll["num_mesas"], errors="coerce").fillna(0).astype(int)
    censo_map = roll.set_index("mpio_reg_code_7")["censo"].to_dict()
    mesas_map = roll.set_index("mpio_reg_code_7")["num_mesas"].to_dict()

    # ── Nacional ─────────────────────────────────────────────────────────────
    print("\nBuilding nacional GeoJSONs …")
    nat = pd.read_csv(OUT / "results/colombia_2026_municipio_senado_nacional.csv", dtype=str)
    party_cols = [c for c in nat.columns if c.startswith("party_")]
    nat = enrich(nat, party_cols, "party_", lkp, censo_map, mesas_map)

    build_mpio_geojson(nat, OUT / "colombia_2026_municipio_senado_nacional.geojson", "Nacional")
    build_dept_geojson(nat, OUT / "colombia_2026_dept_senado_nacional.geojson",      "Nacional")

    # ── Indígena ─────────────────────────────────────────────────────────────
    print("\nBuilding indígena GeoJSONs …")
    ind = pd.read_csv(OUT / "results/colombia_2026_municipio_senado_indigena.csv", dtype=str)
    indig_cols = [c for c in ind.columns if c.startswith("indig_")]
    ind = enrich(ind, indig_cols, "indig_", lkp, censo_map, mesas_map)

    build_mpio_geojson(ind, OUT / "colombia_2026_municipio_senado_indigena.geojson", "Indígena")
    build_dept_geojson(ind, OUT / "colombia_2026_dept_senado_indigena.geojson",      "Indígena")


if __name__ == "__main__":
    main()
