#!/usr/bin/env python3
"""Contrato en cero: las páginas existen antes de que haya un solo voto.

A las ocho de la noche del 4 de octubre, cuando la ONPE todavía no ha publicado
nada, el sitio tiene que estar entero y navegable: las 2,118 carreras con su
nombre, sus listas, sus candidatos y sus escaños en juego, y el escrutinio en
cero. No una página de «próximamente».

Eso no lo puede hacer `publica_json`, que parte del cómputo de la ONPE. Este
script parte del **registro del JNE**, que está cerrado desde antes, y emite el
mismo contrato con los votos a cero y todas las carreras `por_definir`.

Sirve para tres cosas, y las tres importan:

1. Es lo que se ve al abrir la noche, y lo que más gente verá.
2. Permite construir y revisar el frontend de 2026 **hoy**, sin esperar a la
   ONPE.
3. Es la prueba de que el registro está completo: si una carrera no tiene
   listas aquí, tampoco las tendrá esa noche.

SOBRE EL CÓDIGO DE ORGANIZACIÓN
-------------------------------
El código de la ONPE no existe hasta que la ONPE publica. Aquí se usa el id del
JNE con prefijo `jne-`, que es lo honesto: deja ver a simple vista que es
provisional y no puede chocar con un código ONPE de ocho dígitos. El crosswalk
de la fase 05 los traduce esa noche.

Uso:
    uv run python scripts/00g_prepobla.py --anio 2026
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]

SIMBOLO = "https://sroppublico.jne.gob.pe/Consulta/Simbolo/GetSimbolo/{}"
# El sqlite de 2026 guarda **solo el nombre del archivo** de la foto
# (`{guid}.jpg`), no la URL, al contrario que el de 2022. Sin anteponer el host
# el navegador la resuelve contra la propia página y da 404: la ficha sale sin
# cara. Base verificada (200, image/jpeg, sin auth) — ver api-notes.md.
FOTO = "https://mpesije.jne.gob.pe/apidocs/{}"
POR_DEFINIR = "por_definir"


def escribe(ruta: Path, obj) -> None:
    """Igual que en `publica_json`: atómica y solo si cambió."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if ruta.exists():
        try:
            if ruta.read_text() == nuevo:
                return
        except OSError:
            pass
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(nuevo)
    tmp.replace(ruta)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anio", default="2026")
    ap.add_argument("--version", type=int, default=1)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--grupos", type=Path,
                    default=RAIZ.parents[1] / "articulos/erm-2026-candidatos/data/grupos_erm2026.json",
                    help="lookup organizacion_id -> grupo (alianzas del JNE)")
    ap.add_argument("--hdv", type=Path,
                    default=RAIZ.parents[1] / "articulos/erm-2026-candidatos/data/hdv/hdv_erm2026.sqlite",
                    help="sqlite de hojas de vida; es de solo lectura")
    args = ap.parse_args()

    base = RAIZ
    suf = ""
    out = args.out or base / "data"
    ahora = datetime.now(timezone.utc).astimezone().isoformat()

    car = pd.read_csv(base / f"data/reference/carreras{suf}.csv", dtype=str)
    dis = pd.read_csv(base / f"data/reference/distritos{suf}.csv", dtype=str)
    cent = {}
    cp = RAIZ / f"data/reference/geo/centroides_{args.anio}.json"
    if cp.exists():
        cent = json.load(open(cp))

    # Hoja de vida: foto, educación y antecedentes. Sin esto la página sale sin
    # caras, que es la mitad de lo que la gente entra a ver.
    hdv = {}
    if args.hdv and Path(args.hdv).exists():
        import sqlite3
        con = sqlite3.connect(f"file:{args.hdv}?mode=ro", uri=True)
        for r in con.execute("SELECT hoja_vida_id, foto, edu_max, n_penal, "
                             "n_obliga FROM meta"):
            hdv[str(r[0])] = {
                "foto": (FOTO.format(r[1]) if r[1] and "://" not in r[1]
                         else r[1]),
                "educacion": r[2],
                "sentencias_penales": r[3], "obligaciones": r[4]}
        con.close()
    print(f"hojas de vida en índice: {len(hdv):,}")
    ins = pd.read_parquet(base / f"data/processed/candidatos_inscritos{suf}.parquet")
    mes = pd.read_parquet(base / f"data/processed/mesas{suf}.parquet")
    catalogo = {c["race_id"]: c
                for c in json.load(open(out / "meta.json"))["carreras"]}

    # Actas esperadas por carrera. `carreras.csv` trae la columna `n_mesas` vacía,
    # así que se cuenta desde la asignación mesa -> carrera, que es la fuente de
    # verdad y además la que usará el cliente en vivo.
    esperadas: dict[str, int] = defaultdict(int)
    for col in ("race_gobernador", "race_consejero",
                "race_provincial", "race_distrital"):
        if col in mes.columns:
            for rid, n in mes[col].value_counts().items():
                if isinstance(rid, str) and rid:
                    esperadas[rid] += int(n)

    ins = ins.copy()
    ins["posicion"] = pd.to_numeric(ins.posicion, errors="coerce").fillna(999)
    ins = ins.sort_values(["race_id", "id_jne", "posicion"])

    # Mismo agrupado a mano que en `publica_json`: `groupby().itertuples()` sobre
    # columnas Arrow cuesta decenas de segundos y aquí no hace falta.
    cols = list(ins.columns)
    col = [ins[c].to_numpy() for c in cols]
    ix = {c: i for i, c in enumerate(cols)}
    porlista: dict[tuple, list[int]] = defaultdict(list)
    for i in range(len(ins)):
        porlista[(col[ix["race_id"]][i], col[ix["id_jne"]][i])].append(i)

    def ficha(i: int) -> dict:
        g = lambda c: col[ix[c]][i]          # noqa: E731
        edad = g("edad")
        return {"cand_id": str(g("cand_id")), "orden": int(g("posicion")),
                "nombre": g("candidato"), "dni": g("dni"), "sexo": g("sexo"),
                "edad": int(edad) if pd.notna(edad) else None,
                "hoja_vida_id": str(g("hoja_vida_id")),
                # El domicilio sale del registro del JNE, no del sqlite de hojas
                # de vida: esa base guarda foto, educación y antecedentes, pero
                # no dónde vive el candidato.
                "domicilio": " / ".join(
                    x for x in (g("departamento"), g("provincia"), g("distrito"))
                    if isinstance(x, str) and x),
                **hdv.get(str(g("hoja_vida_id")),
                          {"foto": None, "educacion": None,
                           "sentencias_penales": None, "obligaciones": None})}

    # Jerarquía geográfica, para que el mapa de cada carrera tenga sus piezas
    # aunque todavía no haya un voto. Sin esto la página filtra los niveles
    # vacíos y la carrera sale sin mapa: `dispo` se queda en cero.
    # Las piezas de cada mapa salen de **quién vota en esa carrera**, no de la
    # geografía. No es lo mismo: Lima Metropolitana está dentro del departamento
    # de Lima pero sus 43 distritos no eligen gobernador ni consejero, así que
    # pintarlos en el mapa regional dibuja una provincia que no participa. Lo
    # mismo al revés con los 196 cercados, que no eligen alcalde distrital.
    # `distritos.csv` ya declara, distrito a distrito, en qué carrera vota.
    prov_de_carrera, dist_de_carrera = {}, {}
    for r in dis.itertuples():
        prov = r.ubigeo_provincia[:4]
        for campo in ("race_gobernador", "race_provincial"):
            rc = getattr(r, campo, None)
            if isinstance(rc, str) and rc:
                dist_de_carrera.setdefault(rc, []).append(r.ubigeo_distrito)
                if campo == "race_gobernador":
                    prov_de_carrera.setdefault(rc, set()).add(prov + "00")

    def vacio(ubis):
        return [{"ubigeo": u, "actas": 0, "pct_actas": 0.0, "votos": {}}
                for u in sorted(ubis)]

    # Consejo regional: las circunscripciones con sus escaños, todos en disputa.
    #
    # Los escaños van como **plazas vacías**, una por escaño, no como lista
    # vacía. El mapa del consejo dibuja un punto por entrada de `escanos`: con
    # `[]` la píldora de cada circunscripción sale sin contenido y se ve un punto
    # diminuto, en vez de los N puntos grises que muestran cuántos escaños hay
    # en juego ahí. El hemiciclo no cambia —solo cuenta las que tienen
    # `organizacion`—, así que los 16 siguen saliendo en disputa.
    consejo = {}
    for r in car[car.tipo == "02"].itertuples():
        dep = r.ubigeo[:2]
        n_es = int(r.n_escanos or 0)
        consejo.setdefault(dep, []).append({
            "ubigeo": r.ubigeo, "nombre": r.nombre_circunscripcion,
            "n_escanos": n_es, "lider": None,
            "lider_nombre": None, "pct_actas": 0.0,
            "centroide": cent.get(r.ubigeo),
            "escanos": [{"organizacion": None, "nombre": None, "logo": None,
                         "consejero": None} for _ in range(n_es)]})

    # Alianzas. Una alianza electoral **no es un movimiento regional**: agrupa a
    # varios partidos bajo un ancla y en el sumario se lee junta. Deducirlo del
    # tipo de organización metía las diez alianzas en el saco de los regionales.
    #
    # La pertenencia no se recalcula aquí: se consume `grupos_erm2026.json`, que
    # ya la resuelve —incluidas las etiquetas curadas, como Renovación Popular,
    # que no tiene organización propia y compite solo vía dos alianzas—. Un id
    # ausente del mapa es una organización no vista: va sola, nunca se pierde.
    grupo_de, grupo_nom = {}, {}
    if args.grupos and Path(args.grupos).exists():
        gj = json.load(open(args.grupos))
        tam = defaultdict(int)
        for v in gj.get("orgs", {}).values():
            tam[v["grupo_id"]] += 1
        for oid, v in gj.get("orgs", {}).items():
            cod = f"jne-{oid}"
            if tam[v["grupo_id"]] > 1:
                clave = f"g{v['grupo_id']}"
                grupo_nom[clave] = v["grupo"]
            elif v["tipo_organizacion"] == "MOVIMIENTOS REGIONALES O DEPARTAMENTALES":
                clave = "REGIONALES"
                grupo_nom[clave] = "MOVIMIENTOS REGIONALES"
            else:
                continue                      # partido nacional suelto: fila propia
            grupo_de[cod] = clave
        print(f"alianzas: {sum(1 for k in grupo_nom if k != 'REGIONALES')} "
              f"· organizaciones agrupadas: {len(grupo_de):,}")

    nom_org = {}
    listas_por_org = defaultdict(int)
    por_carrera, n = [], 0
    for r in car.itertuples():
        rid = f"{r.tipo}-{r.ubigeo}"
        cat = catalogo.get(rid, {})
        n_e = int(cat.get("n_escanos") or 0)
        n_mesas = esperadas.get(rid, 0)

        listas = sorted({k for k in porlista if k[0] == rid})
        orgs = []
        for _, jne in listas:
            filas = porlista[(rid, jne)]
            nombre = col[ix["organizacion"]][filas[0]]
            nom_org[f"jne-{jne}"] = nombre
            listas_por_org[f"jne-{jne}"] += 1
            cargo_ej = cat.get("cargo_ejecutivo") or ""
            titular = [i for i in filas
                       if isinstance(col[ix["cargo"]][i], str)
                       and col[ix["cargo"]][i].startswith(cargo_ej)] if cargo_ej else []
            orgs.append({
                "codigo": f"jne-{jne}", "nombre": nombre,
                "logo": SIMBOLO.format(jne),
                "candidato": ficha(titular[0]) if titular else None,
                "votos": 0, "pct_validos": 0.0,
                "p_gana": None, "p_primera": None, "p_segunda": None})

        # A qué nivel se ve el mapa de esta carrera. No es derivable del tipo a
        # secas: la de gobernador se mira por provincia y también por distrito;
        # la provincial por distrito; la distrital se pinta entera, porque de los
        # locales de votación no hay geometría.
        if r.tipo == "01":
            niveles = {"provincia": vacio(prov_de_carrera.get(rid, [])),
                       "distrito": vacio(dist_de_carrera.get(rid, []))}
        elif r.tipo == "03":
            niveles = {"distrito": vacio(dist_de_carrera.get(rid, []))}
        elif r.tipo == "04":
            niveles = {"distrito": vacio([r.ubigeo])}
        else:
            niveles = {}
        desag = niveles.get("provincia") or niveles.get("distrito") or []

        escribe(out / "carrera" / f"{rid}.json", {
            "race_id": rid, "tipo": r.tipo, "ubigeo": r.ubigeo,
            "nombre": cat.get("nombre", r.nombre_circunscripcion),
            "version": args.version,
            "computo": {"actas_esperadas": n_mesas, "actas_contabilizadas": 0,
                        "pct_actas": 0.0, "electores_habiles": 0,
                        "votos_emitidos": 0, "votos_validos": 0,
                        "votos_blancos": 0, "votos_nulos": 0,
                        "votos_impugnados": 0},
            "organizaciones": orgs,
            "pronostico": {"estado": POR_DEFINIR, "quienes": [],
                           "p_segunda_vuelta": None, "n_sims": 0,
                           "respaldo": False},
            "electos": {
                "ejecutivo": ({"cargo": cat.get("cargo_ejecutivo"),
                               "cargo_acompanante": cat.get("cargo_acompanante"),
                               "estado": POR_DEFINIR, "organizacion": None,
                               "organizacion_nombre": None,
                               "organizacion_logo": None,
                               "titular": [], "acompanante": []}
                              if cat.get("cargo_ejecutivo") else None),
                "cuerpo": (None if not cat.get("cargo_proporcional") else
                           {"n_escanos": n_e, "adjudicados": 0,
                            "en_disputa": n_e,
                            "cargo": cat.get("cargo_proporcional"),
                            "por_organizacion": []})},
            "anulada": False,
            "desagregado": desag,
            "desagregado_niveles": niveles,
        })
        por_carrera.append({"race_id": rid, "tipo": r.tipo, "ubigeo": r.ubigeo,
                            "estado": POR_DEFINIR, "ganador": None,
                            "ganadores": [], "pct_actas": 0.0})
        n += 1

    # El consejo regional vive en la página del gobernador, no en una propia:
    # es una sección de la región. Igual que en `publica_json`.
    for dep, circs in consejo.items():
        ruta = out / "carrera" / f"01-{dep}0000.json"
        if not ruta.exists():
            continue
        doc = json.loads(ruta.read_text())
        circs.sort(key=lambda c: c["ubigeo"])
        doc["consejo"] = {"n_escanos": sum(c["n_escanos"] for c in circs),
                          "adjudicados": 0, "circunscripciones": circs}
        escribe(ruta, doc)

    # Tabla de organizaciones del resumen: todas a cero, con su número de listas.
    # A cero no dice quién gana —nadie ha ganado nada— pero sí quién se presenta
    # y con cuánta extensión, que es la lectura que toca antes de que abran.
    CAMPOS = ["gobernador_1v", "gobernador_2v", "alcalde_prov", "alcalde_dist",
              "consejero", "regidor_prov", "regidor_dist"]
    por_org = sorted(
        ({"codigo": c, "nombre": nom_org[c],
          "logo": SIMBOLO.format(c.removeprefix("jne-")),
          **{k: 0 for k in CAMPOS}, "listas": listas_por_org[c],
          # El grupo es explícito en el contrato: el navegador no tiene cómo
          # saber qué partidos forman una alianza.
          "grupo": grupo_de.get(c),
          "grupo_nombre": grupo_nom.get(grupo_de.get(c))}
         for c in nom_org),
        key=lambda o: (-o["listas"], o["nombre"]))

    total_actas = sum(esperadas.get(c["race_id"], 0) for c in por_carrera)
    escribe(out / "nacional.json", {
        "generado": ahora, "version": args.version, "pct": 0.0,
        "actas_contabilizadas": 0, "actas_esperadas": total_actas,
        "electores_habiles": 0, "electores_escrutados": 0,
        "votos_emitidos": 0, "votos_validos": 0, "participacion": None,
        "carreras_llamadas": 0, "carreras": len(por_carrera),
        "estados": {POR_DEFINIR: len(por_carrera)},
        "estados_por_tipo": {t: {POR_DEFINIR: sum(1 for c in por_carrera
                                                  if c["tipo"] == t)}
                             for t in sorted({c["tipo"] for c in por_carrera})},
        "por_carrera": sorted(por_carrera, key=lambda c: c["race_id"]),
        "organizaciones_nombre": nom_org,
        "por_organizacion": por_org})

    listas = len({k for k in porlista})
    print(f"{n:,} carreras en cero · {listas:,} listas · "
          f"{len(por_org)} organizaciones · {total_actas:,} actas esperadas")
    print(f"consejo adjuntado a {len(consejo)} páginas regionales")
    sin = [c["race_id"] for c in por_carrera
           if not any(k[0] == c["race_id"] for k in porlista)]
    print(f"carreras sin una sola lista: {len(sin)}"
          + (f" — {', '.join(sin[:5])}" if sin else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
