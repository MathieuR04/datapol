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
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT    = SCRIPT_DIR.parent
CSV_PATH   = PROJECT / "data" / "erm2026_candidatos.csv"
OUT_PATH   = PROJECT / "buscador" / "data" / "candidatos.json"

# Party colors: a hand-editable project-local map { "ORG NAME": "#hex" }. Seeded
# from the EG2026 presidential palette (accent-insensitive match) and extendable by
# hand for parties it doesn't cover (regional movements, name variants). Empty/missing
# values mean "no color" → the finder shows the party name in the default text color.
COLORS_PATH = PROJECT / "data" / "party_colors.json"

TIPOS = [
    {"id": 4, "nombre": "REGIONAL",             "depth": 1},
    {"id": 5, "nombre": "MUNICIPAL PROVINCIAL", "depth": 2},
    {"id": 6, "nombre": "MUNICIPAL DISTRITAL",  "depth": 3},
]
CAND_CAMPOS = ["pos", "nombre", "dni", "cargo", "sexo", "edad", "prov_consejero"]
HEAD_PREFIX = ("GOBERNADOR", "ALCALDE")   # cabeza de lista by cargo


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def _norm(s):
    """Uppercase, trim, collapse spaces, strip accents — for party-name matching."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def load_party_colors() -> dict:
    """{normalized org name → #hex} from the project-local party_colors.json."""
    if not COLORS_PATH.exists():
        return {}
    raw = json.load(open(COLORS_PATH, encoding="utf-8"))
    return {_norm(k): v for k, v in raw.items() if v}


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
    party_colors = load_party_colors()
    orgs_seen, colores = set(), {}

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
            org = f0["organizacion"]
            if org not in orgs_seen:
                orgs_seen.add(org)
                hexc = party_colors.get(_norm(org))
                if hexc:
                    colores[org] = hexc
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
        "colores":          colores,
        "circ":             out_circ,
    }


def main():
    if not CSV_PATH.exists():
        print(f"  build_finder_json: {CSV_PATH.name} not found — skipping.")
        return
    data = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(OUT_PATH)
    mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"  build_finder_json: {data['total_candidatos']:,} candidatos / "
          f"{data['total_listas']:,} listas → {OUT_PATH.relative_to(PROJECT)} ({mb:.1f} MB)")


if __name__ == "__main__":
    main()
