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
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT    = SCRIPT_DIR.parent
CSV_PATH   = PROJECT / "data" / "erm2026_candidatos.csv"
EG_CSV     = PROJECT / "data" / "eg2026_candidatos.csv"
ALC_CSV    = PROJECT / "data" / "alcaldes_2022.csv"
OUT_PATH   = PROJECT / "buscador" / "data" / "candidatos.json"

# Second output: per-party list-count table for the standalone article
# articulos/partidos-erm-2026/ (sibling of this project). Same single source (the CSV),
# regenerated on every scrape --update alongside the finder JSON.
PARTIDOS_PATH = PROJECT.parent / "partidos-erm-2026" / "data" / "partidos.json"

# Third output: EG2026 ↔ ERM2026 "repeat candidates" aggregation for the article
# articulos/candidatos-eg-erm-2026/. Joins the two CSVs on normalized DNI.
REPITEN_PATH = PROJECT.parent / "candidatos-eg-erm-2026" / "data" / "repeticiones.json"

# Fourth output: sitting 2022 mayors re-installing themselves as posición-1 regidor
# (teniente alcalde) in their own circunscripción in ERM2026. Joins the ERM CSV to
# data/alcaldes_2022.csv on normalized DNI + same circunscripción.
TENIENTES_PATH = PROJECT.parent / "tenientes-alcalde-erm-2026" / "data" / "tenientes.json"

# Fifth output: competitividad — number of distinct lists per circunscripción (per
# level), and the "elected by default" set (circunscripciones with a single list, so
# that list's head candidate wins unopposed barring changes). For the article
# articulos/habemus-alcaldes-erm-2026/.
COMPET_PATH = PROJECT.parent / "habemus-alcaldes-erm-2026" / "data" / "competitividad.json"

# Every derived artifact this build (over)writes. The auto-publisher in
# scrape_erm2026.py stages exactly these (plus the CSVs), so adding an output here
# is enough to get it committed — nothing is missed by reading data another way.
OUTPUTS = [OUT_PATH, PARTIDOS_PATH, REPITEN_PATH, TENIENTES_PATH, COMPET_PATH]

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


# ── EG2026 ↔ ERM2026 repeat-candidate join ───────────────────────────────────
EG_RANK = {"PRESIDENTE DE LA REPÚBLICA": 1, "PRIMER VICEPRESIDENTE": 2,
           "SEGUNDO VICEPRESIDENTE": 2, "SENADORES": 3, "DIPUTADOS": 4,
           "REPRESENTANTE ANTE EL PARLAMENTO ANDINO": 5}
EG_LBL  = {1: "Presidencia", 2: "Vicepresidencia", 3: "Senado", 4: "Diputación",
           5: "Parlamento Andino"}
EG_ORDEN = ["Presidencia", "Vicepresidencia", "Senado", "Diputación", "Parlamento Andino"]
ERM_RANK = {"GOBERNADOR REGIONAL": 1, "VICEGOBERNADOR REGIONAL": 2, "ALCALDE PROVINCIAL": 3,
            "ALCALDE DISTRITAL": 4, "CONSEJERO REGIONAL": 5, "ACCESITARIO": 6,
            "REGIDOR PROVINCIAL": 7, "REGIDOR DISTRITAL": 8}
ERM_LBL  = {1: "Gobernación", 2: "Vicegobernación", 3: "Alcaldía provincial",
            4: "Alcaldía distrital", 5: "Consejería regional", 6: "Accesitario",
            7: "Regiduría provincial", 8: "Regiduría distrital"}
ERM_ORDEN = ["Gobernación", "Vicegobernación", "Alcaldía provincial", "Alcaldía distrital",
             "Consejería regional", "Accesitario", "Regiduría provincial", "Regiduría distrital"]


def _ndni(s):
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        s = str(int(s))
        return None if s == "0" else s
    return s.upper()


def _na(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _load_people(path):
    people = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = _ndni(r["dni"])
            if d:
                people[d].append(r)
    return people


def build_repeticiones() -> dict:
    """Distinct people (by normalized DNI) who ran in EG2026 and now run in ERM2026."""
    eg, erm = _load_people(EG_CSV), _load_people(CSV_PATH)
    rep = sorted(set(eg) & set(erm))

    def top(rows, rank):
        return min(rows, key=lambda r: rank.get(r["cargo"], 99))

    egt = {d: top(eg[d], EG_RANK) for d in rep}
    ert = {d: top(erm[d], ERM_RANK) for d in rep}
    eg_lbl  = lambda d: EG_LBL[EG_RANK[egt[d]["cargo"]]]
    erm_lbl = lambda d: ERM_LBL[ERM_RANK[ert[d]["cargo"]]]

    eg_dist  = Counter(eg_lbl(d) for d in rep)
    erm_dist = Counter(erm_lbl(d) for d in rep)
    flujo    = Counter((eg_lbl(d), erm_lbl(d)) for d in rep)
    depts    = Counter(ert[d]["departamento"] for d in rep)

    def card(d):
        return {"nombre": ert[d]["candidato"], "eg": eg_lbl(d),
                "eg_org": egt[d]["organizacion"], "erm": erm_lbl(d),
                "dep": ert[d]["departamento"], "prov": ert[d]["provincia"],
                "dist": ert[d]["distrito"], "erm_org": ert[d]["organizacion"],
                "switch": _na(egt[d]["organizacion"]) != _na(ert[d]["organizacion"])}

    presidenciales = [card(d) for d in rep if EG_RANK[egt[d]["cargo"]] <= 2]
    gobernadores   = [card(d) for d in rep if ert[d]["cargo"] == "GOBERNADOR REGIONAL"]
    edades = [int(ert[d]["edad"]) for d in rep if (ert[d]["edad"] or "").isdigit()]
    ejecutivo = sum(erm_dist[k] for k in ("Gobernación", "Vicegobernación",
                                          "Alcaldía provincial", "Alcaldía distrital"))

    return {
        "generado":  date.today().isoformat(),
        "n_repiten": len(rep),
        "n_eg":      len(eg),
        "n_erm":     len(erm),
        "pct_eg":    round(100 * len(rep) / len(eg), 1),
        "pct_erm":   round(100 * len(rep) / len(erm), 2),
        "n_pres_sen": eg_dist["Presidencia"] + eg_dist["Vicepresidencia"] + eg_dist["Senado"],
        "n_ejecutivo": ejecutivo,
        "n_gobernacion": erm_dist["Gobernación"],
        "eg_orden":  EG_ORDEN,
        "erm_orden": ERM_ORDEN,
        "eg_dist":   [{"label": k, "n": eg_dist[k]} for k in EG_ORDEN if eg_dist[k]],
        "erm_dist":  [{"label": k, "n": erm_dist[k]} for k in ERM_ORDEN if erm_dist[k]],
        "flujo":     [{"from": a, "to": b, "n": n} for (a, b), n in flujo.items()],
        "depts":     [{"dep": k, "n": n} for k, n in depts.most_common(8)],
        "sexo":      dict(Counter(egt[d]["sexo"] for d in rep)),
        "edad_media": round(sum(edades) / len(edades)) if edades else None,
        "presidenciales": presidenciales,
        "gobernadores":   sorted(gobernadores, key=lambda c: c["dep"]),
    }


# ── 2022 sitting mayors running for posición-1 regidor (teniente alcalde) ─────
def _ndni2(s):
    """DNI normalization safe for leading zeros: never numeric-coerce a string
    with leading zeros away. Strip whitespace; drop a trailing '.0' float artifact;
    strip leading zeros to a canonical comparable key."""
    s = (s or "").strip().split(".")[0]
    if not s or s in ("nan", "None"):
        return None
    return s.lstrip("0") or "0"


def _ntxt(s):
    """Accent/case-insensitive territory key for the circunscripción join."""
    s = unicodedata.normalize("NFKD", (s or "").strip().upper())
    return "".join(c for c in s if not unicodedata.combining(c))


def build_tenientes() -> dict:
    """Sitting 2022 mayors who, in ERM2026, take the posición-1 regidor slot (which
    by law IS the teniente alcalde / first successor) on a list in their OWN
    circunscripción — instead of running for alcalde. Level-aware join:
      · REGIDOR DISTRITAL pos 1  → 2022 distrital mayor of that exact (reg,prov,dist)
      · REGIDOR PROVINCIAL pos 1 → 2022 provincial mayor of that (reg,prov)
        (provincial mayors carry a blank `distrito` in alcaldes_2022.csv)
    A 2022 distrital mayor moving up to a provincial council is a DIFFERENT
    circunscripción and is intentionally excluded."""
    # 2022 mayors, split by level and keyed by (dni, territory)
    prov22, dist22 = {}, {}
    with open(ALC_CSV, newline="", encoding="utf-8-sig") as f:
        for a in csv.DictReader(f):
            d = _ndni2(a["dni"])
            if not d:
                continue
            reg, prov, dist = _ntxt(a["region"]), _ntxt(a["provincia"]), _ntxt(a["distrito"])
            if dist == "":                       # provincial mayor (cercado)
                prov22[(d, reg, prov)] = a
            else:                                # distrital mayor
                dist22[(d, reg, prov, dist)] = a

    casos = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["cargo"] not in ("REGIDOR PROVINCIAL", "REGIDOR DISTRITAL"):
                continue
            if str(r["posicion"]).strip() != "1":
                continue
            d = _ndni2(r["dni"])
            if not d:
                continue
            reg, prov, dist = _ntxt(r["departamento"]), _ntxt(r["provincia"]), _ntxt(r["distrito"])
            if r["cargo"] == "REGIDOR DISTRITAL":
                m = dist22.get((d, reg, prov, dist))
                nivel = "distrital"
            else:
                m = prov22.get((d, reg, prov))
                nivel = "provincial"
            if not m:
                continue
            org22 = (m.get("organizacion_politica") or "").strip()
            org26 = (r["organizacion"] or "").strip()
            casos.append({
                "dni":       r["dni"],
                "nombre":    r["candidato"],
                "nivel":     nivel,
                "region":    r["departamento"],
                "provincia": r["provincia"],
                "distrito":  r["distrito"],
                "org_2026":  org26,
                "estado":    r["estado_lista"],
                "org_2022":  org22,
                "switch":    bool(org22) and _na(org22) != _na(org26),
            })

    casos.sort(key=lambda c: (c["region"], c["provincia"], c["distrito"], c["nombre"]))
    por_region = Counter(c["region"] for c in casos)
    n_mismo  = sum(1 for c in casos if c["org_2022"] and not c["switch"])
    n_switch = sum(1 for c in casos if c["org_2022"] and c["switch"])
    return {
        "generado":     date.today().isoformat(),
        "total":        len(casos),
        "n_provincial": sum(1 for c in casos if c["nivel"] == "provincial"),
        "n_distrital":  sum(1 for c in casos if c["nivel"] == "distrital"),
        "n_mismo_partido": n_mismo,
        "n_cambio_partido": n_switch,
        "por_region":   [{"region": k, "n": n} for k, n in
                         sorted(por_region.items(), key=lambda kv: (-kv[1], kv[0]))],
        "casos":        casos,
    }


# ── Competitividad: lists per circunscripción + "elected by default" set ──────
NIVEL_META = {
    "4": ("regional",   "REGIONAL",             "GOBERNADOR REGIONAL", "regiones"),
    "5": ("provincial", "MUNICIPAL PROVINCIAL", "ALCALDE PROVINCIAL",  "provincias"),
    "6": ("distrital",  "MUNICIPAL DISTRITAL",  "ALCALDE DISTRITAL",   "distritos"),
}


def build_competitividad() -> dict:
    """Competitiveness = number of distinct LISTS (idSolicitudLista, not candidate
    rows) per circunscripción, computed SEPARATELY per election level — regional per
    departamento, provincial per provincia, distrital per distrito; levels are never
    pooled. ALL lists count regardless of estado_lista (IMPROCEDENTE/rejected lists
    are still appealable, so every list present counts; the code is structured so a
    viable-only filter could be added later). Circunscripciones with exactly ONE list
    → the head candidate (posición 1 / gobernador·alcalde) is elected by default,
    unopposed, barring changes."""
    # circ[(te, ubi)][sl] = [candidate rows];  cmeta[(te, ubi)] = (dep, prov, dist)
    circ  = defaultdict(lambda: defaultdict(list))
    cmeta = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            te = r["tipo_eleccion_id"]
            if te not in NIVEL_META:
                continue
            circ[(te, r["ubigeo"])][r["solicitud_lista_id"]].append(r)
            cmeta[(te, r["ubigeo"])] = (r["departamento"], r["provincia"], r["distrito"])

    # Per-level distribution + collect single-list ("default") circunscripciones,
    # and the most competitive circunscripciones.
    dist_por_nivel = {}                       # nivel → {"1":n,"2":n,...,"5+":n}
    n_circ_nivel   = {}                       # nivel → total circ with ≥1 list
    default_casos  = []
    competitivas   = []

    def lugar(nivel, dep, prov, dist):
        if nivel == "regional":
            return dep, ""
        if nivel == "provincial":
            return prov, dep
        return dist, f"{prov}, {dep}"

    for te, (nivel, _tipo, head_cargo, _u) in NIVEL_META.items():
        buckets = Counter()
        n = 0
        for (t, ubi), lists in circ.items():
            if t != te:
                continue
            n += 1
            k = len(lists)
            buckets["5+" if k >= 5 else str(k)] += 1
            dep, prov, dist = cmeta[(t, ubi)]
            place, sub = lugar(nivel, dep, prov, dist)
            competitivas.append({"nivel": nivel, "lugar": place, "sub": sub, "n_listas": k})
            if k == 1:
                rows = next(iter(lists.values()))
                head = next((x for x in rows if (x["cargo"] or "").startswith(HEAD_PREFIX)), rows[0])
                default_casos.append({
                    "nivel":     nivel,
                    "region":    dep,
                    "provincia": prov,
                    "distrito":  dist,
                    "lugar":     place,
                    "sub":       sub,
                    "cargo":     head["cargo"],
                    "nombre":    head["candidato"],
                    "org":       head["organizacion"],
                    "tipo_org":  head["tipo_organizacion"],
                    "estado":    head["estado_lista"],
                })
        dist_por_nivel[nivel] = {b: buckets.get(b, 0) for b in ("1", "2", "3", "4", "5+")}
        n_circ_nivel[nivel]   = n

    default_casos.sort(key=lambda c: (c["region"], c["provincia"], c["distrito"], c["nombre"]))
    competitivas.sort(key=lambda c: (-c["n_listas"], c["nivel"], c["lugar"]))

    niveles = [{"nivel": NIVEL_META[te][0], "tipo": NIVEL_META[te][1],
                "unidad": NIVEL_META[te][3],
                "n_circ": n_circ_nivel[NIVEL_META[te][0]],
                "n_default": sum(1 for c in default_casos if c["nivel"] == NIVEL_META[te][0]),
                "dist": dist_por_nivel[NIVEL_META[te][0]]}
               for te in ("4", "5", "6")]

    return {
        "generado":     date.today().isoformat(),
        "total":        len(default_casos),
        "n_regional":   sum(1 for c in default_casos if c["nivel"] == "regional"),
        "n_provincial": sum(1 for c in default_casos if c["nivel"] == "provincial"),
        "n_distrital":  sum(1 for c in default_casos if c["nivel"] == "distrital"),
        "niveles":      niveles,
        "casos":        default_casos,
        "competitivas": competitivas[:20],
    }


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

    if EG_CSV.exists():
        rep = build_repeticiones()
        _write_json(REPITEN_PATH, rep)
        print(f"  build_finder_json: {rep['n_repiten']} candidatos repiten EG↔ERM → "
              f"{REPITEN_PATH.name}")

    if ALC_CSV.exists():
        ten = build_tenientes()
        _write_json(TENIENTES_PATH, ten)
        print(f"  build_finder_json: {ten['total']} alcaldes 2022 → teniente alcalde "
              f"({ten['n_provincial']} prov / {ten['n_distrital']} dist) → {TENIENTES_PATH.name}")

    comp = build_competitividad()
    _write_json(COMPET_PATH, comp)
    print(f"  build_finder_json: {comp['total']} circunscripciones electas por default "
          f"({comp['n_regional']} reg / {comp['n_provincial']} prov / {comp['n_distrital']} dist) "
          f"→ {COMPET_PATH.name}")


if __name__ == "__main__":
    main()
