"""
03_build_geojson.py — Merge primarias (consultas) results into GeoJSON for the frontend.

Reads the four results CSVs and the candidate/party JSONs produced by scripts 01 and 02,
then writes eight GeoJSON files (municipio + departamento for each of the four views).

Inputs:
  metadata/colombia_2026_municipio.geojson
  metadata/raw/00.geojson
  metadata/colombia_2026_municipio_electoral_roll.csv
  data/results/colombia_2026_municipio_primarias_soluciones.csv
  data/results/colombia_2026_municipio_primarias_gran.csv
  data/results/colombia_2026_municipio_primarias_frente.csv
  data/results/colombia_2026_municipio_primarias_interconsultas.csv
  data/soluciones_candidates.json
  data/gran_candidates.json
  data/frente_candidates.json
  data/interconsultas_parties.json

Outputs (written to data/):
  colombia_2026_municipio_primarias_soluciones.geojson
  colombia_2026_dept_primarias_soluciones.geojson
  colombia_2026_municipio_primarias_gran.geojson
  colombia_2026_dept_primarias_gran.geojson
  colombia_2026_municipio_primarias_frente.geojson
  colombia_2026_dept_primarias_frente.geojson
  colombia_2026_municipio_primarias_interconsultas.geojson
  colombia_2026_dept_primarias_interconsultas.geojson

Notes on winner percentage:
  votos_validos in all four CSVs is the TOTAL valid-vote pool across all three consultas
  (sum of all party votes in all consultas + blank votes). Candidate / consulta percentages
  are computed against this shared denominator, so the three per-consulta views are
  directly comparable and add up correctly when summed across views.
"""

import json
import math
import pandas as pd
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"
RESULTS    = OUT / "results"

# codpar → (slug, cand_prefix)
CONSULTAS = {
    30: ("soluciones", "cand_30_"),
    31: ("gran",       "cand_31_"),
    32: ("frente",     "cand_32_"),
}

KEEP_FIELDS = [
    "votantes", "censo", "votos_validos", "votos_blanco", "votos_nulos",
    "votos_no_marcados", "mesas_total", "mesas_escrutadas",
    "turnout_pct", "pct_blanco", "pct_nulo",
    "winner", "winner_votes", "winner_pct", "winner_color",
    "consulta_votes_total",   # sum of cand/consulta votes in this view (winner strength denominator)
    "top5_candidates",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(obj):
    """Replace float NaN/Inf with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


def load_lookup(json_path: Path) -> dict:
    """
    Load candidates/parties JSON → {code_str: {nombre, display_name, color, image_id}}.

    Candidate codes are 6-digit strings (e.g. "000027").
    Consulta/party codes are the codpar string (e.g. "30", "31", "32").
    """
    lkp = {}
    if not json_path.exists():
        print(f"  WARNING: lookup file not found: {json_path.name}")
        return lkp
    for entry in json.load(open(json_path)):
        code = str(entry["code"])
        lkp[code] = {
            "nombre":       entry.get("nombre", code),
            "display_name": entry.get("display_name", entry.get("nombre", code)),
            "color":        entry.get("color", "#888"),
            "image_id":     entry.get("image_id"),
        }
    return lkp


def _col_to_code(col: str, prefix: str) -> str:
    """
    Strip column prefix and extract the lookup key.

    Examples:
      "cand_30_000027|ROY BARRERAS MOTOA", prefix="cand_30_"  → "000027"
      "consulta_30",                        prefix="consulta_" → "30"
    """
    raw = col[len(prefix):]
    return raw.split("|")[0]


# ── Winner / top-5 ─────────────────────────────────────────────────────────────

def compute_winner(row, cand_cols: list, prefix: str, lkp: dict):
    """Return (winner_name, winner_color, winner_votes, winner_pct)."""
    best_col, best_v = None, 0
    for col in cand_cols:
        v = int(row.get(col, 0) or 0)
        if v > best_v:
            best_v, best_col = v, col
    if not best_col:
        return "", "#888", 0, 0.0
    code = _col_to_code(best_col, prefix)
    info = lkp.get(code, {})
    vv   = int(row.get("votos_validos", 0) or 0)
    wpct = round(best_v / vv * 100, 2) if vv else 0.0
    name = info.get("display_name") or info.get("nombre", code)
    return name, info.get("color", "#888"), best_v, wpct


def top5_json(row, cand_cols: list, prefix: str, lkp: dict) -> str:
    entries = []
    for col in cand_cols:
        v = int(row.get(col, 0) or 0)
        if not v:
            continue
        code = _col_to_code(col, prefix)
        info = lkp.get(code, {})
        entries.append({
            "name":     info.get("display_name") or info.get("nombre", code),
            "color":    info.get("color", "#888"),
            "votes":    v,
            "image_id": info.get("image_id"),
        })
    return json.dumps(sorted(entries, key=lambda x: -x["votes"]), ensure_ascii=False)


# ── Enrichment ─────────────────────────────────────────────────────────────────

def enrich(df: pd.DataFrame, cand_cols: list, prefix: str, lkp: dict,
           censo_map: dict, mesas_map: dict) -> pd.DataFrame:
    """Add winner_*, turnout_pct, pct_* and top5_candidates to df in place."""
    df = df.copy()
    numeric_base = ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                    "votos_no_marcados", "mesas_total", "mesas_escrutadas"]
    for col in numeric_base + cand_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # censo: CSV value takes priority; fall back to electoral roll.
    if "censo" in df.columns:
        scraped = pd.to_numeric(df["censo"], errors="coerce").fillna(0)
        roll    = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map), errors="coerce").fillna(0)
        df["censo"] = scraped.where(scraped > 0, roll).astype(int)
    else:
        df["censo"] = pd.to_numeric(df["mpio_reg_code_7"].map(censo_map),
                                    errors="coerce").fillna(0).astype(int)

    # mesas_total: CSV value takes priority; fall back to electoral roll.
    if "mesas_total" in df.columns:
        scraped_m = pd.to_numeric(df["mesas_total"], errors="coerce").fillna(0)
        roll_m    = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map), errors="coerce").fillna(0)
        df["mesas_total"] = scraped_m.where(scraped_m > 0, roll_m).astype(int)
    else:
        df["mesas_total"] = pd.to_numeric(df["mpio_reg_code_7"].map(mesas_map),
                                          errors="coerce").fillna(0).astype(int)

    votantes = df["votantes"].astype(float)
    validos  = df["votos_validos"].astype(float)
    blanco   = df["votos_blanco"].astype(float)
    nulos    = df["votos_nulos"].astype(float)
    censo_f  = df["censo"].astype(float)

    df["turnout_pct"] = (votantes / censo_f.replace(0, float("nan")) * 100).round(2).fillna(0)
    df["pct_blanco"]  = (blanco   / validos.replace(0, float("nan")) * 100).round(2).fillna(0)
    df["pct_nulo"]    = (nulos    / votantes.replace(0, float("nan")) * 100).round(2).fillna(0)

    winners = df.apply(lambda r: compute_winner(r, cand_cols, prefix, lkp), axis=1)
    df["winner"]               = winners.map(lambda x: x[0])
    df["winner_color"]         = winners.map(lambda x: x[1])
    df["winner_votes"]         = winners.map(lambda x: x[2])
    df["winner_pct"]           = winners.map(lambda x: x[3])
    # Sum of all candidate/consulta votes in this view → used by frontend for color intensity
    if cand_cols:
        df["consulta_votes_total"] = df[[c for c in cand_cols if c in df.columns]].sum(axis=1).astype(int)
    else:
        df["consulta_votes_total"] = 0
    df["top5_candidates"] = df.apply(
        lambda r: top5_json(r, cand_cols, prefix, lkp), axis=1)
    return df


# ── GeoJSON builders ───────────────────────────────────────────────────────────

def build_mpio_geojson(df: pd.DataFrame, out_path: Path, label: str) -> None:
    with open(METADATA / "colombia_2026_municipio.geojson") as f:
        geo = json.load(f)

    result_dict = df.set_index("mpio_reg_code_7").to_dict(orient="index")
    matched, kept_feats = 0, []

    for feat in geo["features"]:
        code7 = feat["properties"].get("mpio_reg_code_7", "")
        if str(code7).startswith("88"):
            continue                    # exclude exterior-world geometry
        if code7 in result_dict:
            row = result_dict[code7]
            feat["properties"].update({k: row[k] for k in KEEP_FIELDS if k in row})
            matched += 1
        kept_feats.append(feat)

    geo["features"] = kept_feats
    print(f"  {label} mpio: {matched}/{len(kept_feats)} features matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


def build_dept_geojson(df: pd.DataFrame, out_path: Path, label: str,
                       cand_cols: list, prefix: str, lkp: dict) -> None:
    with open(METADATA / "raw" / "00.geojson") as f:
        geo = json.load(f)

    agg_base = ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas", "censo"]

    df = df.copy()
    df = df[~df["mpio_reg_code_7"].str.startswith("88")]   # exclude exterior
    df["dept_num"] = df["mpio_reg_code_7"].str[:2]

    numeric_cols = [c for c in agg_base + cand_cols if c in df.columns]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    dept_agg = df.groupby("dept_num")[numeric_cols].sum().reset_index()
    for c in numeric_cols:
        dept_agg[c] = pd.to_numeric(dept_agg[c], errors="coerce").fillna(0)

    dept_cand_cols = [c for c in cand_cols if c in dept_agg.columns]

    dept_agg["turnout_pct"] = (
        dept_agg["votantes"].astype(float)
        / dept_agg["censo"].replace(0, float("nan")) * 100
    ).round(2).fillna(0)
    dept_agg["pct_blanco"] = (
        dept_agg["votos_blanco"].astype(float)
        / dept_agg["votos_validos"].replace(0, float("nan")) * 100
    ).round(2).fillna(0)
    dept_agg["pct_nulo"] = (
        dept_agg["votos_nulos"].astype(float)
        / dept_agg["votantes"].replace(0, float("nan")) * 100
    ).round(2).fillna(0)

    winners = dept_agg.apply(
        lambda r: compute_winner(r, dept_cand_cols, prefix, lkp), axis=1)
    dept_agg["winner"]               = winners.map(lambda x: x[0])
    dept_agg["winner_color"]         = winners.map(lambda x: x[1])
    dept_agg["winner_votes"]         = winners.map(lambda x: x[2])
    dept_agg["winner_pct"]           = winners.map(lambda x: x[3])
    if dept_cand_cols:
        dept_agg["consulta_votes_total"] = dept_agg[[c for c in dept_cand_cols if c in dept_agg.columns]].sum(axis=1).astype(int)
    else:
        dept_agg["consulta_votes_total"] = 0
    dept_agg["top5_candidates"] = dept_agg.apply(
        lambda r: top5_json(r, dept_cand_cols, prefix, lkp), axis=1)

    result_dict = dept_agg.set_index("dept_num").to_dict(orient="index")

    matched, kept_feats = 0, []
    for feat in geo.get("features", []):
        key = str(feat["properties"].get("name", "")).zfill(2)
        if key not in result_dict:
            continue
        row = result_dict[key]
        feat["properties"].update({k: row[k] for k in KEEP_FIELDS if k in row})
        matched += 1
        kept_feats.append(feat)

    geo["features"] = kept_feats
    print(f"  {label} dept:  {matched} departments matched")
    with open(out_path, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Saved → {out_path.name}")


# ── Per-view driver ────────────────────────────────────────────────────────────

def build_view(slug: str, prefix: str, csv_path: Path, cands_path: Path,
               censo_map: dict, mesas_map: dict) -> None:
    """Build mpio + dept GeoJSONs for one consulta or interconsultas."""
    if not csv_path.exists():
        print(f"  SKIP {slug}: CSV not found ({csv_path.name})")
        return

    print(f"\nBuilding {slug} GeoJSONs …")
    df  = pd.read_csv(csv_path, dtype=str)
    lkp = load_lookup(cands_path)

    cand_cols = [c for c in df.columns if c.startswith(prefix)]
    if not cand_cols:
        print(f"  WARNING: no columns with prefix '{prefix}' in {csv_path.name}")

    df = enrich(df, cand_cols, prefix, lkp, censo_map, mesas_map)

    build_mpio_geojson(
        df,
        OUT / f"colombia_2026_municipio_primarias_{slug}.geojson",
        slug.capitalize(),
    )
    build_dept_geojson(
        df,
        OUT / f"colombia_2026_dept_primarias_{slug}.geojson",
        slug.capitalize(),
        cand_cols,
        prefix,
        lkp,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Loading electoral roll …")
    roll = pd.read_csv(METADATA / "colombia_2026_municipio_electoral_roll.csv", dtype=str)
    roll["censo"]     = pd.to_numeric(roll["censo"],     errors="coerce").fillna(0).astype(int)
    roll["num_mesas"] = pd.to_numeric(roll["num_mesas"], errors="coerce").fillna(0).astype(int)
    censo_map = roll.set_index("mpio_reg_code_7")["censo"].to_dict()
    mesas_map = roll.set_index("mpio_reg_code_7")["num_mesas"].to_dict()

    # ── Per-consulta views (soluciones / gran / frente) ───────────────────────
    for _codpar, (slug, prefix) in CONSULTAS.items():
        build_view(
            slug,
            prefix,
            RESULTS / f"colombia_2026_municipio_primarias_{slug}.csv",
            OUT     / f"{slug}_candidates.json",
            censo_map,
            mesas_map,
        )

    # ── Interconsultas view (consulta_30 / consulta_31 / consulta_32) ─────────
    build_view(
        "interconsultas",
        "consulta_",
        RESULTS / "colombia_2026_municipio_primarias_interconsultas.csv",
        OUT     / "interconsultas_parties.json",
        censo_map,
        mesas_map,
    )

    print("\nDone — 8 GeoJSONs written.")


if __name__ == "__main__":
    main()
