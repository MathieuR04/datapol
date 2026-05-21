"""
aggregate.py  —  Colombia Presidencial 2026, Primera Vuelta
Roll up mesa-level results to municipio, dept, and national.

Outputs:
  presidencial2026/processed/resultados_municipios.csv
  presidencial2026/processed/resultados_departamentos.csv
  presidencial2026/processed/results.json   (updated with live totals)
"""

import json
import csv
from pathlib import Path
from collections import defaultdict

SHARED = Path(__file__).parent.parent.parent / "data" / "processed"
OUT    = Path(__file__).parent.parent.parent / "data" / "presidencial2026" / "processed"


def load_bridge(path) -> dict:
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            out[row.get("mpio_reg_code_7") or row.get("dept_reg_code")] = row
    return out


def sum_rows(rows: list[dict], keys: list[str]) -> dict:
    totals = defaultdict(float)
    for row in rows:
        for k in keys:
            try: totals[k] += float(row.get(k) or 0)
            except (ValueError, TypeError): pass
    return dict(totals)


def aggregate():
    print("Loading mesa data …")
    mesas = []
    with open(OUT / "resultados_mesas.csv") as f:
        reader = csv.DictReader(f)
        mesas = list(reader)
        fieldnames = reader.fieldnames or []

    cand_cols = [c for c in fieldnames
                 if c not in ("puesto_code","mesas_total","mesas_escrutadas",
                               "censo","votantes","votos_nulos","votos_no_marcados",
                               "votos_blanco","votos_validos","mpio_reg_code_7","dept_reg_code")]

    base_cols = ["mesas_total","mesas_escrutadas","censo","votantes",
                 "votos_nulos","votos_no_marcados","votos_blanco","votos_validos"]

    # Load master for geography
    master = {}
    with open(METADATA / "colombia_2026_municipio_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            master[row["puesto_code"]] = row

    # Attach geography to mesa rows
    for m in mesas:
        info = master.get(m["puesto_code"], {})
        m["mpio_reg_code_7"] = info.get("mpio_reg_code_7","")
        m["dept_reg_code"]   = info.get("dept_reg_code","")
        m["is_exterior"]     = info.get("is_exterior","False")

    nat = [m for m in mesas if m["is_exterior"] != "True"]

    mpio_bridge = load_bridge(METADATA / "mpio_bridge.csv")
    dept_bridge = {}
    with open(METADATA / "dept_bridge.csv") as f:
        for row in csv.DictReader(f):
            dept_bridge[row["dept_reg_code"]] = row

    def winner_col(group_row: dict) -> tuple[str,str]:
        best_code, best_v = "", 0
        with open(OUT / "candidates.json") as f:
            cands = json.load(f)
        for c in cands:
            v = float(group_row.get(c["code"], 0) or 0)
            if v > best_v:
                best_v = v; best_code = c["code"]
        if not best_code: return ("","")
        with open(OUT / "candidates.json") as f:
            cands_lookup = {c["code"]: c for c in json.load(f)}
        info = cands_lookup.get(best_code, {})
        return info.get("nombre", best_code), info.get("color","#888")

    def aggregate_group(rows: list[dict], group_key: str, bridge: dict, bridge_key: str):
        groups = defaultdict(list)
        for r in rows:
            groups[r[group_key]].append(r)
        out_rows = []
        for key, group in groups.items():
            row = sum_rows(group, base_cols + cand_cols)
            row[group_key] = key
            binfo = bridge.get(key, {})
            row.update({k: v for k,v in binfo.items() if k != group_key})
            vv = float(row.get("votos_validos") or 0)
            vo = float(row.get("votantes") or 0)
            ce = float(row.get("censo") or 0)
            row["turnout_pct"]  = round(vo/ce*100, 2) if ce else 0
            row["pct_blanco"]   = round(float(row.get("votos_blanco",0) or 0)/vv*100,2) if vv else 0
            row["pct_nulo"]     = round(float(row.get("votos_nulos",0) or 0)/vo*100,2) if vo else 0
            row["winner"], row["winner_color"] = winner_col(row)
            bv = max((float(row.get(c,0) or 0) for c in cand_cols), default=0)
            row["winner_votes"] = int(bv)
            row["winner_pct"]   = round(bv/vv*100, 2) if vv else 0
            out_rows.append(row)
        return out_rows

    mpio_rows = aggregate_group(nat, "mpio_reg_code_7", mpio_bridge, "mpio_reg_code_7")
    dept_rows = aggregate_group(nat, "dept_reg_code",   dept_bridge, "dept_reg_code")

    # Write CSVs
    def write_csv(path, rows):
        if not rows: return
        keys = sorted({k for r in rows for k in r})
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    write_csv(OUT / "results/colombia_2026_municipio_primera.csv", mpio_rows)
    write_csv(OUT / "resultados_departamentos.csv", dept_rows)
    print(f"  resultados_municipios.csv: {len(mpio_rows)} municipios")
    print(f"  resultados_departamentos.csv: {len(dept_rows)} depts")

    # Update results.json national totals
    nat_totals = sum_rows(nat, base_cols + cand_cols)
    results_path = OUT / "results.json"
    with open(results_path) as f:
        results = json.load(f)
    results["votantes"]          = int(nat_totals.get("votantes", 0))
    results["votos_validos"]     = int(nat_totals.get("votos_validos", 0))
    results["votos_blanco"]      = int(nat_totals.get("votos_blanco", 0))
    results["votos_nulos"]       = int(nat_totals.get("votos_nulos", 0))
    results["mesas_escrutadas"]  = int(nat_totals.get("mesas_escrutadas", 0))
    results["turnout_pct"]       = round(
        float(nat_totals.get("votantes",0)) / float(results.get("censo",1)) * 100, 2)
    results["pct_mesas"]         = round(
        float(nat_totals.get("mesas_escrutadas",0)) /
        float(nat_totals.get("mesas_total",1)) * 100, 2)
    vv = float(nat_totals.get("votos_validos", 0))
    for c in results["candidates"]:
        v = int(nat_totals.get(c["code"], 0))
        c["votes"]    = v
        c["vote_pct"] = round(v/vv*100, 2) if vv else 0
    import datetime
    results["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"
    with open(results_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("  results.json updated")


if __name__ == "__main__":
    aggregate()
