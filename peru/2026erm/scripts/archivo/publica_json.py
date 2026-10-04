#!/usr/bin/env python3
"""Emisor del contrato: convierte un estado del cómputo en las páginas públicas.

Es la pieza que cierra el circuito. Toma un corte de la noche —qué actas han
llegado— y escribe los archivos que el frontend consume: uno por carrera, más el
resumen nacional. Después de esto, el forecaster deja de ser un experimento.

QUÉ HACE EN CADA CARRERA
------------------------
1. Agrega el cómputo oficial de lo contabilizado. Sin modelo: son las cifras de
   la ONPE tal cual.
2. Proyecta con `simula` (modelo C) y adjudica **cada simulación** con el
   allocator completo, topes de candidatos hábiles incluidos.
3. Deriva el estado del ejecutivo y el piso garantizado de cada lista.
4. Aplica la regla de salida: una llamada se retira **solo cuando deja de ser el
   escenario más probable**. Por eso el emisor recibe el estado previo y lo
   devuelve: la adherencia es una propiedad de la secuencia, no de un corte.

EL RESUMEN NACIONAL SALE DE LA PROYECCIÓN
-----------------------------------------
No del cómputo crudo. Cuenta autoridades **electas según nuestro pronóstico**, y
los gobernadores se reportan `X+Y`: ganados en primera vuelta más los que pasan
a segunda. Son estados distintos y un solo número mentiría.

Uso:
    uv run python scripts/publica_json.py --pct 0.5 --sims 500
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, namedtuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from datapol.adjudicacion import Entradas, adjudica  # noqa: E402
from datapol.estados import (ELECTO, EMPATE, POR_DEFINIR,  # noqa: E402
                             SEGUNDA_VUELTA, SIN_RESULTADO)
from noche_electoral import carga_todo, carreras, escenario_de  # noqa: E402
from datapol import forecast_mesas as F  # noqa: E402

CONF = 0.99

# Piso de escrutinio: cuánto hay que haber contado antes de afirmar algo firme.
#
# `CONF` dice cuán seguro tiene que estar el modelo; esto dice cuánta realidad
# tiene que haber visto. Son cosas distintas y hacían falta las dos: al 3% de
# actas el modelo llamaba Arequipa —gobernación, 118 de 3,945 actas— con 17
# puntos de ventaja. Acertó, pero ese 3% no es una muestra aleatoria: las actas
# entran ordenadas por local, así que el sesgo sistemático es justo lo que el
# margen no ve. El replay completo lo confirma: 15 llamadas incorrectas y 17
# retractaciones, con mediana de llamada al 0.8% contado.
#
# Cubre las dos afirmaciones fuertes de la página: la llamada («esta lista ganó»)
# y el piso garantizado de escaños («esta lista tiene 3 regidores asegurados»).
# Son cosas distintas, pero se apoyan en la misma muestra, así que lo que
# invalida a una invalida a la otra. Por debajo del piso se publican
# probabilidades y nada más.
#
# Una carrera de una sola mesa llega al 100% con su única acta y pasa el piso
# sin problema: ahí no hay nada que proyectar, la elección terminó.
PCT_MINIMO = 0.10


def piso(v, conf=CONF):
    s = sorted(v)
    return s[min(int(np.floor(len(s) * (1 - conf))), len(s) - 1)]


def escribe(ruta: Path, obj) -> None:
    """Atómica, y solo si de verdad cambió.

    Atómica porque nadie debe leer un JSON a medio escribir. Y solo si cambió
    porque la noche electoral son cientos de ciclos: reescribir las 2,113
    carreras cada vez —cuando en un ciclo típico se mueven unas pocas— hace que
    el publicador copie todo, que git guarde un blob nuevo por archivo y que las
    cachés se invaliden enteras. Un archivo idéntico conserva su mtime y no
    existe para nadie aguas abajo.
    """
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
    ap.add_argument("--pct", type=float, default=0.5,
                    help="fracción de actas contabilizadas a simular")
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--version", type=int, default=1)
    ap.add_argument("--estado-previo", type=Path,
                    help="json con las llamadas vigentes del corte anterior")
    ap.add_argument("--out", type=Path, default=RAIZ / "data")
    args = ap.parse_args()

    res, comp = carga_todo()
    # El cómputo sin filtrar, para poder contar las actas de una elección cuyas
    # actas están todas anuladas: `carga_todo` ya las descartó.
    comp_todo = pd.read_parquet(
        RAIZ / "data/processed/computo_mesa_ERM2022.parquet",
        columns=["tipo", "ubigeo_distrito", "electores", "votaron", "votos_validos",
                 "votos_blancos", "votos_nulos", "votos_impugnados"])
    todas = carreras(res, comp)
    del res
    ent = Entradas()
    cw = pd.read_csv(RAIZ / "data/reference/crosswalk_organizaciones_2022.csv",
                     dtype=str)
    nom_org = dict(zip(cw.codigo_onpe, cw.nombre_onpe))
    # El símbolo de la organización se sirve desde el JNE, igual que las fotos
    # de candidatos y que el buscador de candidatos ERM 2026. Es una URL
    # construida a partir del id del JNE: no hay nada que descargar.
    SIMBOLO = "https://sroppublico.jne.gob.pe/Consulta/Simbolo/GetSimbolo/{}"
    logo_org = {r.codigo_onpe: SIMBOLO.format(r.id_jne)
                for r in cw.itertuples() if pd.notna(r.id_jne)}
    # Plancha por carrera y organización, en orden de lista: el piso
    # garantizado se traduce a nombres tomando los primeros k.
    ins = pd.read_parquet(RAIZ / "data/processed/candidatos_inscritos_2022.parquet")
    ins["posicion"] = pd.to_numeric(ins.posicion, errors="coerce").fillna(999)
    ins = ins.sort_values(["race_id", "id_jne", "posicion"])
    jne_a_onpe = dict(zip(cw.id_jne, cw.codigo_onpe))
    ins["onpe"] = ins.id_jne.map(jne_a_onpe)

    # Ficha de hoja de vida: foto, educación y antecedentes.
    import sqlite3
    hdv = {}
    bd = RAIZ / "data/raw/hdv_erm2022.sqlite"
    if bd.exists():
        con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True)
        for r in con.execute("SELECT hoja_vida_id, foto, edu_max, n_penal, "
                             "n_obliga, domi_departamento, domi_provincia, "
                             "domi_distrito FROM meta"):
            hdv[str(r[0])] = {"foto": r[1], "educacion": r[2],
                              "sentencias_penales": r[3],
                              "obligaciones": r[4],
                              "domicilio": " / ".join(x for x in r[5:] if x)}
        con.close()
    print(f"hojas de vida en índice: {len(hdv):,}")

    # OJO CON EL ORDEN: este archivo lo **produce** `build_geo_nacional.py`, que
    # por tanto tiene que correr antes que este script. Correrlo después deja las
    # burbujas de escaños sobre el mapa del consejo posicionadas con los puntos
    # viejos, y los viejos eran centroides: en una provincia cóncava como
    # Putumayo el centroide cae fuera de ella y la burbuja aparece flotando sobre
    # la provincia vecina.
    cent = {}
    cp = RAIZ / "data/reference/geo/centroides_2022.json"
    if cp.exists():
        cent = json.load(open(cp))

    catalogo = {}
    meta_p = args.out / "meta.json"
    if meta_p.exists():
        catalogo = {c["race_id"]: c
                    for c in json.load(open(meta_p))["carreras"]}

    # Índice (race_id, onpe) -> filas ya ordenadas por posición. Antes cada
    # llamada a `plancha` barría las 73 mil filas del registro; con la ficha del
    # candidato en cada organización las llamadas se multiplican por diez y el
    # barrido dejaba de ser tolerable.
    #
    # Se agrupa a mano sobre arrays de numpy en vez de con `groupby().itertuples()`.
    # No es microoptimización: medido sobre el registro de 2022, ese groupby
    # tardaba **38.7 s** —construye 12,338 DataFrames y los materializa fila a
    # fila sobre columnas Arrow— frente a 0.6 s así. Son 61x, y en una noche de
    # cientos de ciclos es la diferencia entre un pipeline que respira y uno que
    # no. El perfil lo dejó claro: el allocator es el 7% del tiempo; mover datos
    # dentro de pandas era el grueso.
    #
    # Las filas siguen siendo namedtuples, así que `plancha` no se entera.
    _cols = list(ins.columns)
    _col = [ins[c].to_numpy() for c in _cols]
    _Fila = namedtuple("Fila", _cols)
    _ir, _io = _cols.index("race_id"), _cols.index("onpe")
    _idx = {}
    for _i in range(len(ins)):
        _idx.setdefault((_col[_ir][_i], _col[_io][_i]), []).append(
            _Fila(*[c[_i] for c in _col]))

    def plancha(rid, onpe, cargo, k, excluir=()):
        """Los primeros k candidatos de esa lista, con su ficha.

        `excluir` son DNI que ya ocupan otro cargo de la misma elección. Existe
        por la regla de promoción por vacancia: si el candidato a alcalde cae, el
        primer regidor **suma** la candidatura a la alcaldía sin perder la suya, y
        el registro guarda dos filas para la misma persona. Si gana la alcaldía,
        deja vacante su escaño de regidor y **la lista corre**. Sin excluirlo, se
        le adjudicaba el escaño que ya no puede ocupar y se dejaba fuera a quien
        de verdad entró: pasaba en 81 concejos de 2022.
        """
        filas = [r for r in _idx.get((rid, onpe), ())
                 if isinstance(r.cargo, str) and r.cargo.startswith(cargo)
                 and str(r.dni) not in excluir]
        out = []
        for r in filas[:k]:
            f = hdv.get(str(r.hoja_vida_id), {})
            out.append({"cand_id": str(r.cand_id), "orden": int(r.posicion),
                        "nombre": r.candidato, "dni": r.dni,
                        "sexo": r.sexo, "edad": (int(r.edad)
                                                 if pd.notna(r.edad) else None),
                        "hoja_vida_id": str(r.hoja_vida_id), **f})
        return out

    previo = ({} if not (args.estado_previo and args.estado_previo.exists())
              else json.load(open(args.estado_previo)))
    r0 = np.random.default_rng(args.semilla)
    locs = sorted({l for v in todas.values() for l in v[0].local.unique()})
    r0.shuffle(locs)
    rank = {l: i for i, l in enumerate(locs)}
    rng = np.random.default_rng(args.semilla)
    ahora = datetime.now(timezone.utc).astimezone().isoformat()

    nuevo_estado = {}
    # Una fila por carrera para el mapa nacional. Sin esto la página nacional no
    # puede colorear nada: `por_organizacion` son totales, no dice quién ganó dónde.
    por_carrera = []
    # Mapa de consejeros: un círculo por escaño en cada circunscripción,
    # pintado según qué lista lo está ganando. La unidad es el **escaño**, no
    # la lista, porque el mapa muestra composición y no votación.
    consejo = defaultdict(list)
    resumen = defaultdict(lambda: defaultdict(int))
    n_ok = 0
    for rid, (m, orgs, tipo, niv, n_e) in sorted(todas.items()):
        mm = m.assign(_r=m.local.map(rank)).sort_values(["_r", "mesa"])
        # El piso de una acta solo aplica cuando de verdad se contó algo. Con
        # `max(1, ...)` siempre puesto, `--pct 0` entregaba una acta por carrera
        # y el estado inicial —el que más gente va a ver, a las ocho de la noche,
        # antes de que la ONPE publique nada— no se podía reproducir ni probar.
        k = max(1, int(round(args.pct * len(mm)))) if args.pct > 0 else 0
        cont, falt = mm.iloc[:k], mm.iloc[k:]
        e = ent.de(rid)
        vc = cont[orgs].to_numpy(np.int64).sum(axis=0)

        estado, quienes, p_gana, pisos = POR_DEFINIR, [], {}, {}
        p_2v, p_primera, p_segunda = None, {}, {}
        if vc.sum() > 0 and len(orgs) >= 1:
            r = F.simula(cont, falt, orgs, args.sims, rng, tipo, niv, geo=True)
            # `sin_prior` ya no descarta la carrera: el forecaster ahora da un
            # prior de respaldo a las mesas que ningún nivel cubría. Lo que sí
            # cambia es qué se puede hacer con el resultado —ver `respaldo`—.
            if True:
                t = r["totales"]
                cu, seats = defaultdict(int), {a: [] for a in orgs}
                gana = defaultdict(int)
                # En una carrera de gobernador, «quién va primero» dice poco
                # cuando la segunda vuelta es casi segura. Lo que decide son dos
                # sucesos distintos: ganar en primera (superar el umbral) y
                # clasificar entre los dos primeros. Se cuentan por separado.
                p1c, p2c = defaultdict(int), defaultdict(int)
                n2v = 0
                for i in range(len(t)):
                    v = t[i]
                    vo = {a: int(x) for a, x in zip(orgs, v) if x > 0}
                    rp = None if tipo == "01" else adjudica(vo, tipo, n_e, e)
                    es = escenario_de(v, orgs, tipo, rp)
                    cu["|".join(map(str, es))] += 1
                    # `argmax` devuelve el primer índice del máximo, o sea que
                    # desempata en silencio: con un empate exacto le daba 100% a
                    # la lista de código más bajo. En Córculla, donde Perú Libre
                    # y Movimiento Regional Agua empataron a 83 votos, la página
                    # decía que Perú Libre ganaba con certeza. El crédito se
                    # reparte entre las empatadas.
                    mx = v.max()
                    lid = [orgs[i] for i in range(len(orgs)) if v[i] == mx]
                    for q in lid:
                        gana[q] += 1.0 / len(lid)
                    if es[0] == SEGUNDA_VUELTA:
                        n2v += 1
                        for q in es[1:]:
                            p2c[q] += 1
                    elif es[0] == ELECTO and tipo == "01":
                        p1c[es[1]] += 1
                    if rp is not None:
                        for a in orgs:
                            seats[a].append(rp.escanos.get(a, 0))
                mo = max(cu, key=cu.get)
                p_gana = {a: c / len(t) for a, c in gana.items()}
                if tipo == "01":
                    p_2v = n2v / len(t)
                    p_primera = {a: c / len(t) for a, c in p1c.items()}
                    p_segunda = {a: c / len(t) for a, c in p2c.items()}
                # CON PRIOR DE RESPALDO SE PUBLICAN PROBABILIDADES, NADA MÁS.
                # El piso garantizado y la llamada se quedan fuera: son las dos
                # cosas que no admiten una banda construida sobre dos actas. Es
                # el reparo del autor original, acotado a donde de verdad aplica.
                # El piso de escrutinio cubre las DOS afirmaciones fuertes de
                # esta página: la llamada («esta lista ganó») y el piso
                # garantizado de escaños («esta lista tiene 3 regidores
                # asegurados»). Son distintas, pero descansan en la misma muestra
                # —las primeras actas, ordenadas por local, no aleatorias—, así
                # que la que invalida a una invalida a la otra. Por debajo del
                # 10% se publican probabilidades y nada más.
                if r.get("respaldo") or len(cont) / len(mm) < PCT_MINIMO:
                    pisos = {}
                else:
                    pisos = {a: piso(seats[a]) for a in orgs if seats[a]}
                    # Regla de salida: solo se retira si deja de ser lo más probable.
                    ant = previo.get(rid, {})
                    if ant.get("estado", POR_DEFINIR) != POR_DEFINIR:
                        vig = "|".join([ant["estado"], *ant.get("quienes", [])])
                        if mo == vig or cu[vig] == max(cu.values()):
                            mo = vig
                    if cu[mo] / len(t) >= CONF or mo == "|".join(
                            [ant.get("estado", ""), *ant.get("quienes", [])]):
                        p = mo.split("|")
                        estado, quienes = p[0], p[1:]
        nuevo_estado[rid] = {"estado": estado, "quienes": quienes}
        if estado != POR_DEFINIR:
            n_ok += 1

        # Resumen nacional, desde la proyección y no desde el cómputo.
        if tipo == "01":
            if estado == ELECTO and quienes:
                resumen[quienes[0]]["gobernador_1v"] += 1
            elif estado == SEGUNDA_VUELTA:
                for q in quienes:
                    resumen[q]["gobernador_2v"] += 1
        elif estado == ELECTO and quienes:
            resumen[quienes[0]]["alcalde_prov" if tipo == "03"
                                else "alcalde_dist" if tipo == "04"
                                else "consejero"] += 1
        for a, kk in pisos.items():
            if kk:
                resumen[a][{"03": "regidor_prov", "04": "regidor_dist"}
                           .get(tipo, "consejero")] += kk

        cat = catalogo.get(rid, {})

        # Quién queda electo, o quiénes pasan a segunda vuelta, **con nombre**.
        # El mapa del resumen lo necesita para su tooltip: decir «gana tal
        # organización» obliga al lector a otro salto para saber quién es.
        ganadores = []
        if cat.get("cargo_ejecutivo") and estado in (ELECTO, SEGUNDA_VUELTA, EMPATE):
            for q in quienes:
                fichas = plancha(rid, q, cat["cargo_ejecutivo"], 1)
                ganadores.append({"codigo": q, "organizacion": nom_org.get(q, q),
                                  "candidato": fichas[0]["nombre"] if fichas else None})
        por_carrera.append({"race_id": rid, "tipo": tipo,
                            "ubigeo": rid[3:], "estado": estado,
                            "ganador": quienes[0] if quienes else None,
                            "ganadores": ganadores,
                            "pct_actas": round(len(cont) / len(mm), 3)})
        # Desagregado: se agrupa el cómputo por el nivel que corresponde a esta
        # carrera. No se deduce del tipo: lo declara el catálogo.
        col = {"provincia": "provincia", "distrito": "distrito",
               "local": "local", "circunscripcion": "distrito"}.get(
                   cat.get("desagrega_a"), "distrito")
        # El forecaster agrupa por prefijo (`provincia` son 4 dígitos), pero el
        # geojson se llavea con ubigeo canónico de 6. Emitir el prefijo dejaba
        # el mapa de las 25 carreras de gobernador en gris: cruce cero.
        def canon(u: str) -> str:
            u = str(u)
            return u + "0" * (6 - len(u)) if len(u) < 6 else u

        def agrega(columna):
            if columna not in cont.columns:
                return []
            filas, tot_u = [], mm.groupby(columna, observed=True).size()
            for u, g2 in cont.groupby(columna, observed=True):
                vv = g2[orgs].to_numpy(np.int64).sum(axis=0)
                filas.append({"ubigeo": canon(u), "actas": int(len(g2)),
                              "pct_actas": round(len(g2) / int(tot_u[u]), 3),
                              "votos": {a: int(x) for a, x in zip(orgs, vv)
                                        if x > 0}})
            return filas

        desag = agrega(col)
        # Una carrera de gobernador se juega en el departamento, pero el lector
        # quiere bajar a ver su distrito. El nivel al que se **adjudica** la
        # carrera y el nivel al que se **mira** el mapa no tienen por qué
        # coincidir: se emiten los dos y el frontend elige cuál pinta.
        desag_niveles = {col: desag}
        for extra in {"provincia": ["distrito"]}.get(cat.get("desagrega_a"), []):
            filas = agrega(extra)
            if filas:
                desag_niveles[extra] = filas
        if tipo == "02":
            # Un escaño no es un color: es una persona con nombre, foto y la
            # provincia por la que entra. La página del consejo los lista.
            asientos = []
            for a, kk in sorted(pisos.items(), key=lambda z: -z[1]):
                fichas = plancha(rid, a, "CONSEJERO", int(kk))
                for i in range(int(kk)):
                    asientos.append({
                        "organizacion": a, "nombre": nom_org.get(a, ""),
                        "logo": logo_org.get(a),
                        "consejero": fichas[i] if i < len(fichas) else None})
            asientos += [{"organizacion": None, "nombre": None, "logo": None,
                          "consejero": None}] * max(0, n_e - len(asientos))
            lider = (max(zip(orgs, vc), key=lambda z: z[1])[0]
                     if len(orgs) and vc.sum() > 0 else None)
            consejo[rid[3:5] + "0000"].append({
                "ubigeo": rid[3:], "nombre": cat.get("nombre", ""),
                "n_escanos": n_e,
                # Para el mapa del consejo: quién puntea en esta circunscripción.
                # Es una votación distinta de la de gobernador y el puntero no
                # tiene por qué ser el mismo.
                "lider": lider,
                "lider_nombre": nom_org.get(lider) if lider else None,
                "pct_actas": round(len(cont) / len(mm), 3),
                "centroide": cent.get(rid[3:]) or cent.get(rid[3:7] + "00"),
                "escanos": asientos})
        # DNI de quien se lleva el ejecutivo, para que no ocupe además un
        # escaño del cuerpo proporcional.
        dni_ejecutivo = set()
        if cat.get("cargo_ejecutivo") and estado == ELECTO and quienes:
            for c in plancha(rid, quienes[0], cat["cargo_ejecutivo"], 1):
                dni_ejecutivo.add(str(c["dni"]))

        tot_org = int(vc.sum())
        doc = {
            "race_id": rid, "tipo": tipo, "ubigeo": rid[3:],
            "nombre": catalogo.get(rid, {}).get("nombre", ""),
            # Sin sello por carrera: la página solo lee `generado` de nacional.json, y
            # un timestamp en cada archivo hacía que el contrato entero pareciera nuevo
            # en cada ciclo aunque no se hubiera movido un voto. "version": args.version,
            "computo": {
                "actas_esperadas": int(len(mm)),
                "actas_contabilizadas": int(len(cont)),
                "pct_actas": round(len(cont) / len(mm), 4),
                "electores_habiles": int(cont.electores.sum()),
                "votos_emitidos": int(cont.votaron.sum()),
                "votos_validos": tot_org,
                # La spec de la página de carrera los pide explícitamente y no
                # se pueden derivar de los votos por organización.
                "votos_blancos": int(cont.votos_blancos.sum()),
                "votos_nulos": int(cont.votos_nulos.sum()),
                "votos_impugnados": int(cont.votos_impugnados.sum()),
            },
            "organizaciones": [
                {"codigo": a, "nombre": nom_org.get(a, a),
                 "logo": logo_org.get(a),
                 # Quién encabeza la lista. Una carrera se lee por candidato tanto
                 # como por partido, y el nombre del partido solo no basta para
                 # saber a quién se está votando.
                 "candidato": (plancha(rid, a, cat.get("cargo_ejecutivo") or "", 1)
                               or [None])[0] if cat.get("cargo_ejecutivo") else None,
                 "votos": int(x), "pct_validos": round(x / tot_org, 5)
                 if tot_org else 0.0,
                 "p_gana": round(p_gana.get(a, 0.0), 4),
                 # Solo en gobernador: son los dos sucesos que de verdad importan.
                 "p_primera": (round(p_primera.get(a, 0.0), 4)
                               if tipo == "01" else None),
                 "p_segunda": (round(p_segunda.get(a, 0.0), 4)
                               if tipo == "01" else None)}
                for a, x in sorted(zip(orgs, vc), key=lambda z: -z[1])],
            "pronostico": {"estado": estado, "quienes": quienes,
                           # Proyección construida con el prior de respaldo: hay
                           # probabilidades, pero no piso garantizado ni llamada.
                           "respaldo": bool(r.get("respaldo")) if (
                               vc.sum() > 0 and len(orgs) >= 1) else False,
                           "p_segunda_vuelta": (round(p_2v, 4)
                                                if p_2v is not None else None),
                           "n_sims": args.sims},
            "electos": {
                "ejecutivo": ({"cargo": cat.get("cargo_ejecutivo"),
                               "cargo_acompanante": cat.get("cargo_acompanante"),
                               "estado": estado,
                               "organizacion": quienes[0] if quienes else None,
                               "organizacion_nombre": (nom_org.get(quienes[0])
                                                       if quienes else None),
                               "organizacion_logo": (logo_org.get(quienes[0])
                                                     if quienes else None),
                               # Titular y acompañante son cargos distintos y se
                               # piden por separado; antes salían de pedir «los
                               # dos primeros» de la plancha, que funcionaba de
                               # casualidad.
                               "titular": (plancha(rid, quienes[0],
                                                   cat["cargo_ejecutivo"], 1)
                                           if estado == ELECTO and quienes
                                           else []),
                               "acompanante": (
                                   plancha(rid, quienes[0],
                                           cat["cargo_acompanante"], 1)
                                   if (estado == ELECTO and quienes
                                       and cat.get("cargo_acompanante"))
                                   else [])}
                              if cat.get("cargo_ejecutivo") else None),
                # Quien ya se llevó el ejecutivo no ocupa además un escaño del
                # cuerpo: la lista corre. Ver `plancha`.
                "cuerpo": None if not cat.get("cargo_proporcional") else {
                           "n_escanos": n_e,
                                   "adjudicados": int(sum(pisos.values())),
                                   "en_disputa": int(n_e - sum(pisos.values())),
                           "cargo": cat.get("cargo_proporcional"),
                           "por_organizacion": [
                               {"codigo": a, "nombre": nom_org.get(a, a),
                                "logo": logo_org.get(a), "escanos": int(kk),
                                "candidatos": plancha(
                                    rid, a, cat.get("cargo_proporcional") or "",
                                    int(kk), excluir=dni_ejecutivo)}
                               for a, kk in sorted(pisos.items(),
                                                   key=lambda z: -z[1])
                               if kk]}},
            # Desagregado para el mapa, al nivel que declara el catálogo.
            "desagregado": desag,
            # Los mismos votos a cada nivel de geografía disponible. `desagregado`
            # es el nivel por defecto y siempre aparece aquí también.
            "desagregado_niveles": desag_niveles,
        }
        escribe(args.out / "carrera" / f"{rid}.json", doc)

    # --- ELECCIONES SIN UNA SOLA ACTA CONTABILIZABLE
    # `carga_todo` descarta las actas que no son NORMALES, así que un distrito
    # donde **todas** las actas quedaron anuladas no llega al bucle y se quedaba
    # sin página: quien entraba veía «no hay datos para 04-070918», que parece un
    # error del sitio cuando en realidad es el resultado. Pasó en tres distritos
    # de 2022: Recta, Manitea y Huamantanga.
    todas_ref = pd.read_csv(RAIZ / "data/reference/carreras_2022.csv", dtype=str)
    anuladas = 0
    for r in todas_ref.itertuples():
        rid = f"{r.tipo}-{r.ubigeo}"
        if rid in todas or rid.startswith("02-"):
            continue
        cat = catalogo.get(rid, {})
        mm_a = comp_todo[(comp_todo.tipo == r.tipo) &
                         (comp_todo.ubigeo_distrito == r.ubigeo)]
        n_mesas = int(len(mm_a))
        # Que una elección quede anulada **no se sabe de antemano**: se sabe
        # cuando sus actas llegan y la ONPE las anula. Emitirla como anulada
        # desde el corte cero era filtrar el resultado al estado inicial —a las
        # ocho de la noche nadie sabe todavía que esas actas van a caerse—. Así
        # que el corte manda también aquí: hasta que no entre la última acta,
        # la elección está por definir como cualquier otra.
        k_a = max(1, int(round(args.pct * n_mesas))) if args.pct > 0 else 0
        cont_a = mm_a.iloc[:k_a]
        anulada = bool(n_mesas) and k_a >= n_mesas
        estado_a = SIN_RESULTADO if anulada else POR_DEFINIR
        pct_a = round(k_a / n_mesas, 4) if n_mesas else 0.0
        por_carrera.append({"race_id": rid, "tipo": r.tipo, "ubigeo": r.ubigeo,
                            "estado": estado_a, "ganador": None,
                            "ganadores": [], "pct_actas": pct_a})
        escribe(args.out / "carrera" / f"{rid}.json", {
            "race_id": rid, "tipo": r.tipo, "ubigeo": r.ubigeo,
            "nombre": cat.get("nombre", ""),
            # Sin sello por carrera: la página solo lee `generado` de nacional.json, y
            # un timestamp en cada archivo hacía que el contrato entero pareciera nuevo
            # en cada ciclo aunque no se hubiera movido un voto. "version": args.version,
            # Las actas **sí se contabilizaron**: la ONPE las procesó y las
            # anuló. En Manitea son 1,547 electores, 1,547 que votaron y 1,547
            # votos nulos. Emitir ceros decía que no se había contado nada, que
            # además contradecía el 100% del resumen nacional.
            "computo": {"actas_esperadas": n_mesas,
                        "actas_contabilizadas": k_a,
                        "pct_actas": pct_a,
                        "electores_habiles": int(cont_a.electores.sum()),
                        "votos_emitidos": int(cont_a.votaron.sum()),
                        "votos_validos": int(cont_a.votos_validos.sum()),
                        "votos_blancos": int(cont_a.votos_blancos.sum()),
                        "votos_nulos": int(cont_a.votos_nulos.sum()),
                        "votos_impugnados": int(cont_a.votos_impugnados.sum())},
            # Las listas sí existieron y la gente sí votó: lo que pasó es que
            # todas las actas se anularon. Se emiten con cero votos, para que se
            # vea la diferencia entre «todavía no sabemos» y «no hubo elección
            # que contar».
            "organizaciones": [
                {"codigo": a_, "nombre": nom_org.get(a_, a_),
                 "logo": logo_org.get(a_), "votos": 0, "pct_validos": 0.0,
                 "p_gana": 0.0, "p_primera": None, "p_segunda": None,
                 "candidato": (plancha(rid, a_, cat.get("cargo_ejecutivo") or "", 1)
                               or [None])[0] if cat.get("cargo_ejecutivo") else None}
                for a_ in sorted({o for (rr, o) in _idx if rr == rid and o})],
            "pronostico": {"estado": estado_a, "quienes": [],
                           "p_segunda_vuelta": None, "n_sims": 0,
                           "respaldo": False},
            # Todas sus actas están anuladas. No es que falte información: es que
            # no hay elección que contar.
            "anulada": anulada,
            "electos": {"ejecutivo": ({"cargo": cat.get("cargo_ejecutivo"),
                                       "cargo_acompanante": cat.get("cargo_acompanante"),
                                       "estado": estado_a, "organizacion": None,
                                       "organizacion_nombre": None,
                                       "organizacion_logo": None,
                                       "titular": [], "acompanante": []}
                                      if cat.get("cargo_ejecutivo") else None),
                        "cuerpo": (None if not cat.get("cargo_proporcional") else
                                   {"n_escanos": cat.get("n_escanos") or 0,
                                    "adjudicados": 0,
                                    "en_disputa": cat.get("n_escanos") or 0,
                                    "cargo": cat.get("cargo_proporcional"),
                                    "por_organizacion": []})},
            "desagregado": [], "desagregado_niveles": {},
        })
        anuladas += int(anulada)
    if anuladas:
        print(f"{anuladas} elecciones sin acta contabilizable, emitidas como anuladas")

    # El consejo regional vive en la página del gobernador: es una sección de
    # la página regional, no una página propia.
    for dep, circs in consejo.items():
        rid = f"01-{dep}"
        ruta = args.out / "carrera" / f"{rid}.json"
        if not ruta.exists():
            continue
        doc = json.load(open(ruta))
        circs.sort(key=lambda c: c["ubigeo"])
        doc["consejo"] = {
            "n_escanos": sum(c["n_escanos"] for c in circs),
            "adjudicados": sum(1 for c in circs for e in c["escanos"]
                               if e["organizacion"]),
            "circunscripciones": circs}
        escribe(ruta, doc)
    print(f"consejo regional adjuntado a {len(consejo)} páginas regionales")

    # Toda organización que compite aparece en el resumen, gane o no. Antes solo
    # entraban las que habían ganado algo: la página nacional listaba 107 de 128
    # y las 21 restantes no existían para el lector, aunque hubieran presentado
    # listas en medio país.
    compiten = {}
    for r in ins.itertuples():
        # 80 blancos, 81 nulos, 82 impugnados: no son organizaciones.
        if r.onpe and r.onpe.lstrip("0") not in ("80", "81", "82"):
            compiten.setdefault(r.onpe, set()).add(r.lista_id)
    for a_, listas in compiten.items():
        resumen[a_]["listas"] = len(listas)
    for a_ in compiten:
        resumen[a_]                      # crea la fila vacía si no ganó nada

    escribe(args.out / "estado_llamadas.json", nuevo_estado)
    # Totales del país, para la cabecera. Se suman sobre las carreras de alcalde
    # distrital, que son las únicas que cubren todo el territorio **una sola vez**:
    # sumar todas las carreras contaría a cada elector tres o cuatro veces.
    # Dos denominadores distintos, y confundirlos rompe la cabecera:
    #
    #   `electores_habiles` es el **padrón entero**, conocido desde antes de la
    #   noche y que no se mueve. Sumarlo solo sobre lo escrutado hacía que a las
    #   ocho de la noche el país tuviera cero electores, y que a medio escrutinio
    #   la cabecera mostrara un padrón que no es el del Perú.
    #
    #   `participacion` se mide contra el padrón **de las actas contabilizadas**,
    #   que es lo único comparable con el voto ya contado. Medida contra el padrón
    #   entero daría 39% a mitad de noche y se leería como una abstención
    #   histórica en vez de como un escrutinio a medias.
    #
    # Las **actas** se cuentan sobre TODAS las carreras, no sobre las de tipo 04.
    # No es incoherencia con lo de arriba: son dos preguntas distintas. Un elector
    # es una persona y hay que contarla una vez, por eso el padrón se suma sobre
    # las distritales, que cubren el territorio exactamente una vez. Un acta es un
    # documento, y una misma mesa produce una por cada elección que vota —regional,
    # provincial, distrital—: todas hay que procesarlas, y el avance de la noche es
    # cuántas de ellas han entrado. Sumar solo las distritales escondería dos
    # tercios del trabajo.
    tot_el = tot_esc = tot_em = tot_va = 0
    act_cont = act_esp = 0
    for rid, (m, orgs, tipo, niv, n_e) in todas.items():
        mm = m.assign(_r=m.local.map(rank)).sort_values(["_r", "mesa"])
        k = max(1, int(round(args.pct * len(mm)))) if args.pct > 0 else 0
        act_cont += k
        act_esp += len(mm)
        if tipo != "04":
            continue
        c = mm.iloc[:k]
        tot_el += int(mm.electores.sum())
        tot_esc += int(c.electores.sum()); tot_em += int(c.votaron.sum())
        tot_va += int(c[orgs].to_numpy(np.int64).sum())

    # `pct` sale del conteo real de actas, no del parámetro de simulación: es lo
    # que la cabecera muestra, y tiene que cuadrar con el numerador y el
    # denominador que se enseñan al lado.
    nac = {"generado": ahora, "version": args.version,
           "pct": round(act_cont / act_esp, 4) if act_esp else 0.0,
           "actas_contabilizadas": act_cont, "actas_esperadas": act_esp,
           "electores_habiles": tot_el, "electores_escrutados": tot_esc,
           "votos_emitidos": tot_em, "votos_validos": tot_va,
           "participacion": round(tot_em / tot_esc, 4) if tot_esc else None,
           "carreras_llamadas": n_ok, "carreras": len(todas),
           "estados": {e: sum(1 for c in por_carrera if c["estado"] == e)
                       for e in sorted({c["estado"] for c in por_carrera})},
           # El mismo marcador abierto por nivel: 2,100 carreras distritales
           # tapan por completo lo que pasa en las 25 regionales.
           "estados_por_tipo": {
               t: {e: sum(1 for c in por_carrera
                          if c["tipo"] == t and c["estado"] == e)
                   for e in sorted({c["estado"] for c in por_carrera
                                    if c["tipo"] == t})}
               for t in sorted({c["tipo"] for c in por_carrera})},
           "por_carrera": sorted(por_carrera, key=lambda c: c["race_id"]),
           "organizaciones_nombre": {a: nom_org.get(a, a) for a in
                                     {c["ganador"] for c in por_carrera
                                      if c["ganador"]}},
           "por_organizacion": [
               {"codigo": a, "nombre": nom_org.get(a, a),
                "logo": logo_org.get(a), **v}
               for a, v in sorted(resumen.items(),
                                  key=lambda z: (-sum(v2 for k2, v2 in z[1].items()
                                                      if k2 != "listas"),
                                                 -z[1].get("listas", 0),
                                                 nom_org.get(z[0], z[0])))]}
    escribe(args.out / "nacional.json", nac)
    print(f"{len(todas):,} carreras · {n_ok:,} con llamada · "
          f"{args.pct:.0%} contabilizado")
    top = nac["por_organizacion"][:5]
    for o in top:
        g = f"{o.get('gobernador_1v',0)}+{o.get('gobernador_2v',0)}"
        print(f"  {o['nombre'][:30]:<32} gob {g:>5}  "
              f"prov {o.get('alcalde_prov',0):>3}  dist {o.get('alcalde_dist',0):>4}"
              f"  reg {o.get('regidor_prov',0):>4}/{o.get('regidor_dist',0):<5}"
              f"  cons {o.get('consejero',0):>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
