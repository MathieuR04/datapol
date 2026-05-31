"""
06_build_comparison.py — Colombia 2026 Primera Vuelta
Build comparison GeoJSONs: 2026 candidate performance vs 2022 reference candidate.

Comparisons
-----------
  A: Iván Cepeda 2026        vs Gustavo Petro 2022        (left bloc)
  B: De la Espriella 2026    vs Rodolfo Hernández 2022    (right)
  C: Paloma Valencia 2026    vs Fico Gutiérrez 2022       (centre-right)
  D: Sergio Fajardo 2026     vs Sergio Fajardo 2022       (centre)

Column mapping — 2022 CSV
--------------------------
  GUSTAVO_PETRO_vot          → Gustavo Petro 2022
  RODOLFO_HERNÁNDEZ_vot      → Rodolfo Hernández 2022
  FEDERICO_GUTIÉRREZ_vot     → Federico Fico Gutiérrez 2022
  SERGIO_FAJARDO_vot         → Sergio Fajardo 2022

Join key: 2022 CSV `codigo` == 2026 `mpio_reg_code_7` (Registraduría 7-digit code)

Outputs (data/comparison/)
--------------------------
  colombia_2026_primera_municipio_comparison.geojson
  colombia_2026_primera_departamento_comparison.geojson
"""

import csv, json, math
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"
COMP_DIR   = DATA_DIR / "comparison"
COMP_DIR.mkdir(parents=True, exist_ok=True)

CSV_2022   = COMP_DIR / "resultados_primera_vuelta_2022_boletin_68.csv"
CSV_2026   = DATA_DIR / "results" / "colombia_2026_municipio_primera.csv"
GEO_MPIO   = METADATA / "colombia_2026_municipio.geojson"
GEO_DEPT   = METADATA / "raw" / "00.geojson"

# ── 2022 candidate columns (all) — used for valid-vote denominator ───────────
COLS_2022_ALL = [
    "FEDERICO_GUTIÉRREZ_vot", "RODOLFO_HERNÁNDEZ_vot",
    "GUSTAVO_PETRO_vot",      "SERGIO_FAJARDO_vot",
    "JOHN MILTON_RODRÍGUEZ_vot", "ENRIQUE_GÓMEZ MARTÍNEZ_vot",
    "LUIS_PÉREZ_vot",            "INGRID_BETANCOURT_vot",
]

# ── Comparison definitions ───────────────────────────────────────────────────
COMPARISONS = {
    "A": {
        "label":     "Cepeda 2026 vs Petro 2022",
        "cand_2026": "cepeda",
        "col_2022":  "GUSTAVO_PETRO_vot",
        "name_26":   "Iván Cepeda",
        "name_22":   "Gustavo Petro",
    },
    "B": {
        "label":     "De la Espriella 2026 vs Hernández 2022",
        "cand_2026": "delaespriella",
        "col_2022":  "RODOLFO_HERNÁNDEZ_vot",
        "name_26":   "De la Espriella",
        "name_22":   "Rodolfo Hernández",
    },
    "C": {
        "label":     "Valencia 2026 vs Gutiérrez 2022",
        "cand_2026": "valencia",
        "col_2022":  "FEDERICO_GUTIÉRREZ_vot",
        "name_26":   "Paloma Valencia",
        "name_22":   "Fico Gutiérrez",
    },
    "D": {
        "label":     "Fajardo 2026 vs Fajardo 2022",
        "cand_2026": "fajardo",
        "col_2022":  "SERGIO_FAJARDO_vot",
        "name_26":   "Sergio Fajardo",
        "name_22":   "Sergio Fajardo",
    },
}


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):  return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_clean(v) for v in obj]
    return obj


# ── Load 2022 results ────────────────────────────────────────────────────────

def load_2022() -> dict:
    """Returns {mpio_reg_code_7: {col_2022: votes, ..., votos_validos_2022}}."""
    result = {}
    with open(CSV_2022, newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("codigo", "")).strip()
            if not code:
                continue
            r = {}
            for col in COLS_2022_ALL:
                try:    r[col] = int(row.get(col) or 0)
                except: r[col] = 0
            r["votos_validos_2022"] = sum(r.values())
            result[code] = r
    print(f"  2022: {len(result)} municipios loaded")
    return result


# ── Load 2026 results ────────────────────────────────────────────────────────

def load_2026() -> dict:
    """Returns {mpio_reg_code_7: {cand_XXXX: votes, ..., votos_validos}}."""
    result = {}
    with open(CSV_2026, newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("mpio_reg_code_7", "")).strip()
            if not code:
                continue
            r = {"votos_validos": int(row.get("votos_validos") or 0)}
            for k, v in row.items():
                if k.startswith("cand_"):
                    try:    r[k] = int(v or 0)
                    except: r[k] = 0
            result[code] = r
    print(f"  2026: {len(result)} municipios loaded")
    return result


# ── Build comparison stats per mpio ─────────────────────────────────────────

def build_stats(data22: dict, data26: dict) -> dict:
    """Returns {mpio_reg_code_7: comparison props dict}."""
    all_codes = set(data22) | set(data26)
    stats = {}
    for code in all_codes:
        r22  = data22.get(code, {})
        r26  = data26.get(code, {})
        vv22 = r22.get("votos_validos_2022", 0)
        vv26 = r26.get("votos_validos", 0)
        row  = {"votos_validos_2022": vv22, "votos_validos": vv26}
        for key, comp in COMPARISONS.items():
            v22 = r22.get(comp["col_2022"], 0)
            v26 = r26.get(f"cand_{comp['cand_2026']}", 0)
            pct22 = round(v22 / vv22 * 100, 4) if vv22 > 0 else None
            pct26 = round(v26 / vv26 * 100, 4) if vv26 > 0 else None
            diff  = round(pct26 - pct22, 4) if (pct22 is not None and pct26 is not None) else None
            row[f"votes22_{key}"] = v22
            row[f"votes26_{key}"] = v26
            row[f"pct22_{key}"]   = pct22
            row[f"pct26_{key}"]   = pct26
            row[f"diff_{key}"]    = diff
        stats[code] = row
    return stats


# ── Build municipio GeoJSON ──────────────────────────────────────────────────

def build_mpio_geojson(stats: dict) -> None:
    with open(GEO_MPIO) as f:
        geo = json.load(f)

    prop_keys = (["votos_validos_2022", "votos_validos"] +
                 [f"votes22_{k}" for k in COMPARISONS] +
                 [f"votes26_{k}" for k in COMPARISONS] +
                 [f"pct22_{k}"   for k in COMPARISONS] +
                 [f"pct26_{k}"   for k in COMPARISONS] +
                 [f"diff_{k}"    for k in COMPARISONS])

    matched = 0
    for feat in geo.get("features", []):
        code = str(feat["properties"].get("mpio_reg_code_7", "")).strip()
        if code not in stats:
            continue
        s = stats[code]
        for k in prop_keys:
            feat["properties"][k] = s.get(k)
        matched += 1

    out = COMP_DIR / "colombia_2026_primera_municipio_comparison.geojson"
    with open(out, "w") as f:
        json.dump(_clean(geo), f, ensure_ascii=False)
    print(f"  Municipio: {matched}/{len(geo['features'])} matched  → {out.name}  "
          f"({out.stat().st_size // 1024} KB)")


# ── Build departamento GeoJSON ────────────────────────────────────────────────

def build_dept_geojson(stats: dict) -> None:
    with open(GEO_DEPT) as f:
        raw_geo = json.load(f)

    # Aggregate stats to dept level (dept_num = first 2 chars of mpio_reg_code_7)
    dept_agg: dict[str, dict] = defaultdict(lambda: {
        "votos_validos_2022": 0, "votos_validos": 0,
        **{f"votes22_{k}": 0 for k in COMPARISONS},
        **{f"votes26_{k}": 0 for k in COMPARISONS},
    })

    for code, row in stats.items():
        if str(code).startswith("88"):
            continue   # skip exterior
        dept_num = str(code)[:2]
        d = dept_agg[dept_num]
        for field in ["votos_validos_2022", "votos_validos"] + \
                     [f"votes22_{k}" for k in COMPARISONS] + \
                     [f"votes26_{k}" for k in COMPARISONS]:
            d[field] = d.get(field, 0) + (row.get(field) or 0)

    # Recompute percentages and diffs from aggregated totals
    for dept_num, d in dept_agg.items():
        vv22 = d["votos_validos_2022"]
        vv26 = d["votos_validos"]
        for key in COMPARISONS:
            v22 = d.get(f"votes22_{key}", 0)
            v26 = d.get(f"votes26_{key}", 0)
            pct22 = round(v22 / vv22 * 100, 4) if vv22 > 0 else None
            pct26 = round(v26 / vv26 * 100, 4) if vv26 > 0 else None
            diff  = round(pct26 - pct22, 4) if (pct22 is not None and pct26 is not None) else None
            d[f"pct22_{key}"] = pct22
            d[f"pct26_{key}"] = pct26
            d[f"diff_{key}"]  = diff

    prop_keys = (["votos_validos_2022", "votos_validos"] +
                 [f"votes22_{k}" for k in COMPARISONS] +
                 [f"votes26_{k}" for k in COMPARISONS] +
                 [f"pct22_{k}"   for k in COMPARISONS] +
                 [f"pct26_{k}"   for k in COMPARISONS] +
                 [f"diff_{k}"    for k in COMPARISONS])

    matched, kept = 0, []
    for feat in raw_geo.get("features", []):
        key = str(feat["properties"].get("name", "")).zfill(2)
        if key not in dept_agg:
            continue
        d = dept_agg[key]
        feat["properties"]["dept_num"]    = key
        feat["properties"]["nombre_dept"] = feat["properties"].get("NOMBRE_DPT", "")
        for k in prop_keys:
            feat["properties"][k] = d.get(k)
        matched += 1
        kept.append(feat)

    raw_geo["features"] = kept
    out = COMP_DIR / "colombia_2026_primera_departamento_comparison.geojson"
    with open(out, "w") as f:
        json.dump(_clean(raw_geo), f, ensure_ascii=False)
    print(f"  Dept: {matched} departments matched  → {out.name}  "
          f"({out.stat().st_size // 1024} KB)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading 2022 results …")
    data22 = load_2022()

    if CSV_2026.exists():
        print("Loading 2026 results …")
        data26 = load_2026()
    else:
        print("  (no 2026 results yet — using zeros)")
        data26 = {}

    print("Building comparison stats …")
    stats = build_stats(data22, data26)

    print("Building municipio comparison GeoJSON …")
    build_mpio_geojson(stats)

    print("Building departamento comparison GeoJSON …")
    build_dept_geojson(stats)

    print("\nDone.")


if __name__ == "__main__":
    main()
