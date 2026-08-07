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
import sqlite3
import unicodedata
import zlib
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT    = SCRIPT_DIR.parent
CSV_PATH   = PROJECT / "data" / "erm2026_candidatos.csv"
EG_CSV     = PROJECT / "data" / "eg2026_candidatos.csv"
ALC_CSV    = PROJECT / "data" / "alcaldes_2022.csv"
OUT_PATH   = PROJECT / "buscador" / "data" / "candidatos.json"

# HDV warehouse (gitignored, built by scrape_hdv_erm2026.py) → enriches the finder with
# educación / sentencias badges (light, in candidatos.json) and per-circunscripción ficha
# detail files (heavy, lazy-loaded by the frontend on "Ver ficha").
HDV_DB    = PROJECT / "data" / "hdv" / "hdv_erm2026.sqlite"
FICHA_DIR = PROJECT / "buscador" / "data" / "hdv"

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
OUTPUTS = [OUT_PATH, PARTIDOS_PATH, REPITEN_PATH, TENIENTES_PATH, COMPET_PATH, FICHA_DIR]

# Party-name color in the finder is by `tipo_org` (partido / alianza / movimiento),
# decided in the frontend — no per-party color map here.

TIPOS = [
    {"id": 4, "nombre": "REGIONAL",             "depth": 1},
    {"id": 5, "nombre": "MUNICIPAL PROVINCIAL", "depth": 2},
    {"id": 6, "nombre": "MUNICIPAL DISTRITAL",  "depth": 3},
]
# `edu` = 5-bit education bitmask (bit0 primaria … bit4 posgrado), or null when the
# candidate has no HDV (improcedente / not yet scraped). `sent` = total sentencias
# (penal + civil), or null when no HDV. Both drive the list-view badges; a null `edu`
# also means "no Ver ficha".
CAND_CAMPOS = ["pos", "nombre", "dni", "cargo", "sexo", "edad", "prov_consejero", "estado",
               "edu", "sent"]
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


def _cand_edu(light, hv):
    """(edu_bitmask, n_sentencias) for a candidate's hoja_vida_id, or (None, None)."""
    if hv and hv.isdigit() and hv != "0":
        lt = light.get(int(hv))
        if lt:
            return lt[0], lt[1] + lt[2]
    return None, None


def build(light=None) -> dict:
    light = light or {}
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
            cands = []
            for r in rows:
                edu, sent = _cand_edu(light, r["hoja_vida_id"])
                cands.append([_int(r["posicion"]), r["candidato"], r["dni"], r["cargo"],
                              r["sexo"], _int(r["edad"]), r["provincia_consejero"],
                              r["estado_candidato"], edu, sent])
            head = next((r for r in rows if (r["cargo"] or "").startswith(HEAD_PREFIX)), rows[0])
            f0 = rows[0]
            listas.append({
                "org":      f0["organizacion"],
                "org_id":   _int(f0["organizacion_id"]),   # → party símbolo (logo)
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
        out_circ[te][ubi] = {"ubi": ubi, "dep": dep, "prov": prov, "dist": dist, "listas": listas}

    return {
        "generado":         date.today().isoformat(),
        "total_candidatos": total_cands,
        "total_listas":     total_lists,
        "cand_campos":      CAND_CAMPOS,
        "tipos":            TIPOS,
        "circ":             out_circ,
    }


# ── HDV enrichment: educación/sentencias badges + per-circ ficha detail files ──
def _s(v):
    v = v.strip() if isinstance(v, str) else v
    return v or None


def _money(x):
    try:
        return "S/ " + f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return None


def _moneynum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0


def _box(titulo, meta, body=None, com=None, tone="info"):
    return {"t": titulo, "m": [m for m in meta if m], "b": body, "c": com, "tone": tone}


def extract_ficha(d):
    """From a GetHVConsolidado `data` dict → (edu_bitmask, n_penal, n_obliga, detail).
    `detail` is the JSON the frontend renders in the ficha modal (raw-derived parts only;
    name/cargo/party come from the candidate row at render time)."""
    dp = d.get("oDatosPersonales") or {}
    basica = d.get("oEduBasica") or {}
    nou = d.get("oEduNoUniversitaria") or {}
    univ = d.get("lEduUniversitaria") or []
    posg = d.get("lEduPosgrado") or ([d["oEduPosgrado"]] if d.get("oEduPosgrado") else [])
    tecnica = bool(nou) and nou.get("strTengoNoUniversitaria") == "1"
    bm = ((1 if basica.get("strEduPrimaria") == "1" else 0)
          | (2 if basica.get("strEduSecundaria") == "1" else 0)
          | (4 if tecnica else 0)
          | (8 if univ else 0)
          | (16 if posg else 0))

    sent = []
    for s in (d.get("lSentenciaPenal") or []):
        sent.append(_box("PENAL · " + (_s(s.get("strDelitoPenal")) or "—"),
            [("Exp. " + _s(s.get("strExpedientePenal"))) if _s(s.get("strExpedientePenal")) else None,
             _s(s.get("strOrganoJudiPenal")), _s(s.get("strFechaSentenciaPenal")),
             ("Modalidad: " + _s(s.get("strModalidad"))) if _s(s.get("strModalidad")) else None,
             ("Cumplimiento: " + _s(s.get("strCumpleFallo"))) if _s(s.get("strCumpleFallo")) else None],
            body=_s(s.get("strFalloPenal")), com=_s(s.get("strComentario")), tone="penal"))
    for s in (d.get("lSentenciaObliga") or []):
        sent.append(_box("CIVIL · " + (_s(s.get("strMateriaSentencia")) or "—"),
            [("Exp. " + _s(s.get("strExpedienteObliga"))) if _s(s.get("strExpedienteObliga")) else None,
             _s(s.get("strOrganoJuridicialObliga"))],
            body=_s(s.get("strFalloObliga")), com=_s(s.get("strComentario")), tone="civil"))

    edu = []
    if tecnica:
        edu.append(_box("Técnica — " + (_s(nou.get("strCarreraNoUni")) or ""),
            [_s(nou.get("strCentroEstudioNoUni")),
             "Concluida" if nou.get("strConcluidoNoUni") == "1" else "No concluida"]))
    for u in univ:
        edu.append(_box("Universitaria — " + (_s(u.get("strCarreraUni")) or ""),
            [_s(u.get("strUniversidad")),
             ("Egresado " + _s(u.get("strAnioBachiller"))) if _s(u.get("strAnioBachiller")) else
             ("Concluida" if u.get("strConcluidoEduUni") == "1" else None)]))
    for p in posg:
        grado = "Doctorado" if p.get("strEsDoctor") == "1" else "Maestría" if p.get("strEsMaestro") == "1" else "Posgrado"
        edu.append(_box(grado + " — " + (_s(p.get("strEspecialidadPosgrado")) or ""),
            [_s(p.get("strCenEstudioPosgrado")),
             ("Egresado " + _s(p.get("strAnioPosgrado"))) if _s(p.get("strAnioPosgrado")) else None]))

    exp = []
    for e in (d.get("lExperienciaLaboral") or []):
        yrs = (_s(e.get("strAnioTrabajoDesde")) + "–" + (_s(e.get("strAnioTrabajoHasta")) or "")) if _s(e.get("strAnioTrabajoDesde")) else None
        exp.append(_box(_s(e.get("strOcupacionProfesion")) or "—", [_s(e.get("strCentroTrabajo")), yrs]))

    bienes = []
    for b in (d.get("lBienInmueble") or []):
        bienes.append(_box("Inmueble · " + (_s(b.get("strTipoBienInmueble")) or ""),
            [_s(b.get("strInmuebleDireccion")),
             ("Partida SUNARP " + _s(b.get("strPartidaSunarp"))) if _s(b.get("strPartidaSunarp")) else None,
             ("Valor " + _money(b.get("decValor"))) if _moneynum(b.get("decValor")) else
             (("Autovalúo " + _money(b.get("decAutovaluo"))) if _moneynum(b.get("decAutovaluo")) else None)]))
    for b in (d.get("lBienMueble") or []):
        bienes.append(_box("Mueble · " + (_s(b.get("strVehiculo")) or "Bien mueble"),
            [_s(b.get("strCaracteristica")),
             ("Placa " + _s(b.get("strPlaca"))) if _s(b.get("strPlaca")) else None,
             ("Valor " + _money(b.get("decValor"))) if _moneynum(b.get("decValor")) else None]))
    ing = d.get("oIngresos") or {}
    renta = sum(_moneynum(ing.get(k)) for k in
                ["decRemuBrutaPublico","decRemuBrutaPrivado","decRentaIndividualPublico",
                 "decRentaIndividualPrivado","decOtroIngresoPublico","decOtroIngresoPrivado"])
    tray = [_box(_s(x.get("strCargoPartidario")) or "—", [_s(x.get("strOrgPolCargoPartidario"))])
            for x in (d.get("lCargoPartidario") or [])]

    detail = {
        "foto": _s(dp.get("UrlFoto")),
        "nac": " / ".join(x for x in [_s(dp.get("strNaciDepartamento")), _s(dp.get("strNaciProvincia")), _s(dp.get("strNaciDistrito"))] if x),
        "dom": " / ".join(x for x in [_s(dp.get("strDomiDepartamento")), _s(dp.get("strDomiProvincia")), _s(dp.get("strDomiDistrito"))] if x),
        "sent": sent, "edu": edu, "exp": exp, "bienes": bienes,
        "ing": _money(renta) if renta else None, "tray": tray,
    }
    return bm, len(d.get("lSentenciaPenal") or []), len(d.get("lSentenciaObliga") or []), detail


def build_hdv():
    """Read the HDV warehouse; return a `light` dict {hoja_vida_id → [edu_bitmask,n_penal,
    n_obliga]} for the list-view badges, and (over)write one ficha-detail file per
    circunscripción at buscador/data/hdv/<te>-<ubi>.json (keyed by DNI). Only files whose
    content actually changed are rewritten, so routine rebuilds barely touch git."""
    if not HDV_DB.exists():
        print("  build_finder_json: HDV warehouse not found — skipping educación/sentencias/ficha.")
        return {}

    eg_cargo = {}
    if EG_CSV.exists():
        for r in csv.DictReader(open(EG_CSV, newline="", encoding="utf-8")):
            eg_cargo.setdefault(_ndni(r["dni"]), r["cargo"])

    db = sqlite3.connect(HDV_DB)
    stored = {hv for (hv,) in db.execute("SELECT hoja_vida_id FROM meta WHERE ok=1")}

    circ = defaultdict(list)          # (te, ubi) → candidate rows
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["tipo_eleccion_id"] in ("4", "5", "6"):
                circ[(r["tipo_eleccion_id"], r["ubigeo"])].append(r)

    FICHA_DIR.mkdir(parents=True, exist_ok=True)
    light = {}
    n_fichas = files_written = 0
    for (te, ubi), rows in circ.items():
        fichas = {}
        for r in rows:
            hv = r["hoja_vida_id"]
            if not hv or not hv.isdigit() or hv == "0" or int(hv) not in stored:
                continue
            raw = db.execute("SELECT gz FROM raw WHERE hoja_vida_id=?", (int(hv),)).fetchone()
            if not raw:
                continue
            d = json.loads(zlib.decompress(raw[0])).get("data") or {}
            bm, npn, nob, detail = extract_ficha(d)
            light[int(hv)] = [bm, npn, nob]
            detail["eg"] = eg_cargo.get(_ndni(r["dni"]))   # ex-candidato EG2026 (annotation)
            fichas[r["dni"]] = detail
            n_fichas += 1
        if not fichas:
            continue
        path = FICHA_DIR / f"{te}-{ubi}.json"
        text = json.dumps(fichas, ensure_ascii=False, separators=(",", ":"))
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            files_written += 1
    db.close()
    print(f"  build_finder_json: HDV → {len(light):,} candidatos con ficha; "
          f"{n_fichas:,} fichas en {len(circ):,} circunscripciones ({files_written} archivos reescritos).")
    return light


def build_partidos() -> dict:
    """List counts by tipo, agrupadas por categoría exterior.

    Un partido nacional compite bajo varios organizacion_id cuando arma alianzas
    regionales (APP + APP-La Cholita + APP-Trabaja Ayacucho son una sola marca).
    La tabla del artículo muestra el total del grupo y despliega el desglose sólo
    cuando el grupo tiene más de una organización. La asignación de grupos la
    calcula build_organizaciones.asignar() — misma función que escribe
    data/organizaciones_erm2026.csv, para que artículo y CSV no diverjan.

    Una lista se cuenta una vez por (organización, tipo), deduplicada en
    idSolicitudLista para que varias filas de candidatos no la dupliquen."""
    import build_organizaciones

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
            oid = r["organizacion_id"]
            p = party.setdefault(oid, {"org": r["organizacion"],
                                       "tipo_org": r["tipo_organizacion"],
                                       "reg": 0, "prov": 0, "dist": 0})
            p[key] += 1

    for oid, p in party.items():
        p["listas"] = p["reg"] + p["prov"] + p["dist"]
    g = build_organizaciones.asignar(
        {oid: {"organizacion": p["org"], "listas": p["listas"]}
         for oid, p in party.items()})

    grupos = {}
    for oid, p in party.items():
        info = g[oid]
        gr = grupos.setdefault(info["grupo"], {
            "grupo": info["grupo"], "tipo_org": "", "reg": 0, "prov": 0,
            "dist": 0, "orgs": []})
        for k in ("reg", "prov", "dist"):
            gr[k] += p[k]
        if info["es_ancla"]:
            gr["tipo_org"] = p["tipo_org"]
        gr["orgs"].append({"org": p["org"], "tipo_org": p["tipo_org"],
                           "reg": p["reg"], "prov": p["prov"], "dist": p["dist"]})

    for gr in grupos.values():
        # el desglose sólo tiene sentido cuando hay más de una organización
        gr["orgs"] = sorted(gr["orgs"],
                            key=lambda o: (-o["reg"], -o["prov"], -o["dist"], o["org"])
                            ) if len(gr["orgs"]) > 1 else []

    out = sorted(grupos.values(),
                 key=lambda p: (-p["reg"], -p["prov"], -p["dist"], p["grupo"]))
    return {"generado": date.today().isoformat(), "totales": TOTALES,
            "n_orgs": len(party), "grupos": out}


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
    light = build_hdv()          # educación/sentencias badges + per-circ ficha files
    data = build(light)
    _write_json(OUT_PATH, data)
    mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"  build_finder_json: {data['total_candidatos']:,} candidatos / "
          f"{data['total_listas']:,} listas → {OUT_PATH.relative_to(PROJECT)} ({mb:.1f} MB)")

    partidos = build_partidos()
    _write_json(PARTIDOS_PATH, partidos)
    print(f"  build_finder_json: {partidos['n_orgs']} organizaciones → "
          f"{len(partidos['grupos'])} grupos → {PARTIDOS_PATH.name}")

    # CSV del mapeo organización → categoría exterior (mismo origen que el JSON)
    try:
        import build_organizaciones
        build_organizaciones.main()
    except Exception as e:
        print(f"  ⚠ build_organizaciones falló ({e}); corré el script a mano.")

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
