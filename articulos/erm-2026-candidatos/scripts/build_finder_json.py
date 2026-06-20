"""
build_finder_json.py — regenerate the candidate-finder data from the ERM CSV.

SINGLE SOURCE OF TRUTH. Reads data/erm2026_candidatos.csv and (over)writes one file
buscador/data/candidatos.json. Idempotent: it always rebuilds the whole tree from the
current CSV, so the finder can never drift from the scraped data. It is called
automatically at the end of every scrape_erm2026.py run (see that script's --no-build
flag) and is also runnable standalone:

    python3 scripts/build_finder_json.py

JSON shape (one file, loaded once by buscador/index.html):
    {
      "generado": "2026-06-18",
      "total_candidatos": 79667, "total_listas": 7717,
      "cand_campos": ["pos","nombre","dni","cargo","sexo","edad","prov_consejero"],
      "tipos": [{"id":4,"nombre":"REGIONAL","depth":1}, ...],
      "circ": { "<tipoId>": { "<ubigeo>": {
          "dep": "...", "prov": "...", "dist": "...",
          "listas": [ { "org","tipo_org","estado","h","m",
                        "cabeza": {"nombre","cargo","dni"},
                        "cands": [ [pos,nombre,dni,cargo,sexo,edad,prov_consejero], ... ] } ] } } }
    }
Candidate rows are arrays (per cand_campos) to keep the single file compact.
"""

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT    = SCRIPT_DIR.parent
CSV_PATH   = PROJECT / "data" / "erm2026_candidatos.csv"
OUT_PATH   = PROJECT / "buscador" / "data" / "candidatos.json"

# Second output: per-party list-count table for the standalone article
# articulos/partidos-erm-2026/ (sibling of this project). Same single source (the CSV),
# regenerated on every scrape --update alongside the finder JSON.
PARTIDOS_PATH = PROJECT.parent / "partidos-erm-2026" / "data" / "partidos.json"

# Party-name color in the finder is by `tipo_org` (partido / alianza / movimiento),
# decided in the frontend — no per-party color map here.

TIPOS = [
    {"id": 4, "nombre": "REGIONAL",             "depth": 1},
    {"id": 5, "nombre": "MUNICIPAL PROVINCIAL", "depth": 2},
    {"id": 6, "nombre": "MUNICIPAL DISTRITAL",  "depth": 3},
]
CAND_CAMPOS = ["pos", "nombre", "dni", "cargo", "sexo", "edad", "prov_consejero"]
HEAD_PREFIX = ("GOBERNADOR", "ALCALDE")   # cabeza de lista by cargo

# Universe of circunscripciones per tipo, for territorial-coverage %:
# 25 regiones, 196 provincias, 1 696 distritos con elección distrital (1 892 − 196 cercados).
TOTALES = {"regional": 25, "provincial": 196, "distrital": 1696}
TE_KEY  = {"4": "reg", "5": "prov", "6": "dist"}


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def build() -> dict:
    # circ[(te, ubi)][sl] = [candidate rows];  cmeta[(te, ubi)] = (dep, prov, dist)
    circ  = defaultdict(lambda: defaultdict(list))
    cmeta = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            te, ubi, sl = r["tipo_eleccion_id"], r["ubigeo"], r["solicitud_lista_id"]
            circ[(te, ubi)][sl].append(r)
            cmeta[(te, ubi)] = (r["departamento"], r["provincia"], r["distrito"])

    out_circ = {str(t["id"]): {} for t in TIPOS}
    total_cands = total_lists = 0

    for (te, ubi), lists in circ.items():
        if te not in out_circ:           # ignore anything outside the 3 ERM tipos
            continue
        dep, prov, dist = cmeta[(te, ubi)]
        listas = []
        for sl, rows in lists.items():
            rows.sort(key=lambda r: _int(r["posicion"]))
            cands = [[_int(r["posicion"]), r["candidato"], r["dni"], r["cargo"],
                      r["sexo"], _int(r["edad"]), r["provincia_consejero"]] for r in rows]
            head = next((r for r in rows if (r["cargo"] or "").startswith(HEAD_PREFIX)), rows[0])
            f0 = rows[0]
            listas.append({
                "org":      f0["organizacion"],
                "tipo_org": f0["tipo_organizacion"],
                "estado":   f0["estado_lista"],
                "h":        _int(f0["lista_cand_hombres"]),
                "m":        _int(f0["lista_cand_mujeres"]),
                "cabeza":   {"nombre": head["candidato"], "cargo": head["cargo"], "dni": head["dni"]},
                "cands":    cands,
            })
            total_cands += len(cands)
            total_lists += 1
        listas.sort(key=lambda l: l["org"])
        out_circ[te][ubi] = {"dep": dep, "prov": prov, "dist": dist, "listas": listas}

    return {
        "generado":         date.today().isoformat(),
        "total_candidatos": total_cands,
        "total_listas":     total_lists,
        "cand_campos":      CAND_CAMPOS,
        "tipos":            TIPOS,
        "circ":             out_circ,
    }


def build_partidos() -> dict:
    """Per-party list counts by tipo. A list is counted once per (party, tipo) —
    deduped on idSolicitudLista so multiple candidate rows don't double-count it."""
    seen = set()
    party = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = TE_KEY.get(r["tipo_eleccion_id"])
            if not key:
                continue
            sl = r["solicitud_lista_id"]
            if sl in seen:
                continue
            seen.add(sl)
            org = r["organizacion"]
            p = party.setdefault(org, {"org": org, "tipo_org": r["tipo_organizacion"],
                                       "reg": 0, "prov": 0, "dist": 0})
            p[key] += 1
    partidos = sorted(party.values(),
                      key=lambda p: (-p["reg"], -p["prov"], -p["dist"], p["org"]))
    return {"generado": date.today().isoformat(), "totales": TOTALES, "partidos": partidos}


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def main():
    if not CSV_PATH.exists():
        print(f"  build_finder_json: {CSV_PATH.name} not found — skipping.")
        return
    data = build()
    _write_json(OUT_PATH, data)
    mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"  build_finder_json: {data['total_candidatos']:,} candidatos / "
          f"{data['total_listas']:,} listas → {OUT_PATH.relative_to(PROJECT)} ({mb:.1f} MB)")

    partidos = build_partidos()
    _write_json(PARTIDOS_PATH, partidos)
    print(f"  build_finder_json: {len(partidos['partidos'])} organizaciones → "
          f"{PARTIDOS_PATH.name}")


if __name__ == "__main__":
    main()
