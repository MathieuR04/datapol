#!/usr/bin/env python3
"""Flujo A → el sitio entero. Corre en cada ciclo de `actualizar_distritos.sh`.

Lee lo que dejó `02a_scrape_distritos.py` (totales por carrera y por distrito de
carrera, vía `datapol.agregado.consolida`) y **rellena los mismos archivos que
dejó `00g_prepobla.py` en cero**:

    data/carrera/{race_id}.json   cómputo, votos, desagregado, proyección, electos
    data/nacional.json            avance, carreras ganadas por organización y nivel

Ya no hay actas por mesa (flujo B queda fuera, ver OPERADOR.md). Todo sale de
totales oficiales de la ONPE a nivel de carrera y de distrito.

CÓMPUTO
-------
El de la carrera es el de la ONPE tal cual. Si la petición de la carrera falló
(pasa con algunas gobernaciones, que responden 403 a nivel departamento) y sí
están sus distritos, se publica la **suma de sus distritos**, que son cifras
oficiales igual, y la página lo dice (`computo.fuente`). Blancos, nulos e
impugnados no vienen en flujo A: van `null`, no cero. Emitidos − válidos sí,
como `votos_blancos_nulos`.

PROYECCIÓN — VARIABILIDAD DISTRITAL
-----------------------------------
`forecaster.simula_totales`, estratificado por distrito:

- gobernador: los distritos de la región, con la provincia como nivel intermedio;
- consejero y alcalde provincial: los distritos de la provincia;
- alcalde distrital (y consejero del Callao): una sola unidad, la carrera. Ahí la
  incertidumbre es la Dirichlet calibrada contra el error medido por avance de
  actas (`concentracion_calibrada`).

Votos válidos esperados de un distrito = sus válidos × actas totales / actas
contadas. Un distrito sin actas aún recibe las actas que declara la ONPE (o las
del maestro de mesas, si todavía no hay respuesta) por los válidos por acta de
la carrera.

Cada simulación da un escenario (electo, segunda vuelta, empate) y, para los
cuerpos proporcionales, un reparto completo con topes de candidatos hábiles.

LLAMADAS
--------
Una carrera se llama cuando su escenario más probable alcanza `CONF` **y** se ha
contado al menos `PCT_MINIMO` de sus actas y `MIN_ACTAS` actas (o todas). El
mismo umbral rige para los pisos de escaños garantizados. Es la misma regla de la noche de
2022 (spec 07), con la salvedad de que aquí las actas llegan por distrito y no
por local: el sesgo de composición dentro de un distrito no se ve.

Una llamada se mantiene mientras siga siendo el escenario más probable. Si deja
de serlo **se revoca y se dice**: `interim/llamadas/ledger.csv` registra cada
llamada y cada revocación con su hora (regla 7), y el ciclo imprime ALERTA.

Es idempotente en todo lo demás: cada corrida recalcula desde el consolidado.

Uso:
    uv run python scripts/04_publica_resultados.py
    uv run python scripts/04_publica_resultados.py --sims 400 --semilla 7
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import zlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from datapol.adjudicacion import adjudica  # noqa: E402
from datapol.agregado import consolida  # noqa: E402
from datapol.allocator import construye_disponibles  # noqa: E402
from datapol.estados import (ELECTO, EMPATE, POR_DEFINIR,  # noqa: E402
                             SEGUNDA_VUELTA, SIN_RESULTADO, es_llamada)
from datapol.forecaster import UMBRAL_1V, simula_totales  # noqa: E402

CONF = 0.99
PCT_MINIMO = 0.10
# Además del porcentaje, un mínimo de actas: en un distrito de ocho mesas, una
# sola acta ya es el 12.5%, y una mesa es un local, no una muestra. La
# calibración de `forecaster` se midió en distritos con 10+ mesas. Una carrera
# con menos actas que esto se puede llamar al 100%.
MIN_ACTAS = 3
SIMBOLO = "https://sroppublico.jne.gob.pe/Consulta/Simbolo/GetSimbolo/{}"
COL_RACE = {"01": "race_gobernador", "02": "race_consejero",
            "03": "race_provincial", "04": "race_distrital"}
CAMPO_RESUMEN = {"03": "alcalde_prov", "04": "alcalde_dist", "02": "consejero"}
CAMPO_CUERPO = {"03": "regidor_prov", "04": "regidor_dist", "02": "consejero"}


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def escribe(ruta: Path, obj) -> bool:
    """Atómica, y solo si cambió. Devuelve si escribió."""
    nuevo = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if ruta.exists() and ruta.read_text() == nuevo:
        return False
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(nuevo)
    tmp.replace(ruta)
    return True


def piso(v, conf=CONF) -> int:
    s = sorted(v)
    return int(s[min(int(np.floor(len(s) * (1 - conf))), len(s) - 1)])


def techo(v, conf=CONF) -> int:
    """El simétrico del piso: más escaños que esto no saca con `conf`. Con
    techo 0 la lista no entra al concejo en ningún escenario plausible."""
    s = sorted(v)
    return int(s[max(int(np.ceil(len(s) * conf)) - 1, 0)])


def escenario(v: np.ndarray, orgs: list[str], tipo: str) -> tuple:
    """Estado del ejecutivo para un vector de votos. Ver `datapol.estados`."""
    if len(v) == 0 or v.sum() <= 0:
        return (SIN_RESULTADO,)
    o = np.argsort(-v, kind="stable")
    primeros = [orgs[i] for i in range(len(orgs)) if v[i] == v[o[0]]]
    if tipo == "01" and len(v) > 1 and v[o[0]] / v.sum() < UMBRAL_1V:
        segundos = [orgs[i] for i in range(len(orgs)) if v[i] == v[o[1]]]
        if len(primeros) > 1 or len(segundos) > 1:
            return (EMPATE, *sorted(set(primeros) | set(segundos)))
        return (SEGUNDA_VUELTA, *sorted((orgs[o[0]], orgs[o[1]])))
    if len(primeros) > 1:
        return (EMPATE, *sorted(primeros))
    return (ELECTO, orgs[o[0]])


class Planchas:
    """Candidatos por (carrera, lista), en orden, con la ficha de la página."""

    def __init__(self, ruta: Path):
        p = pd.read_parquet(ruta)
        p = p.astype(object).where(p.notna(), None)
        self._idx: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in p.to_dict("records"):
            self._idx[(r["race_id"], f"jne-{r['id_jne']}")].append(r)
        # Entradas del allocator, en código de página (`jne-…`).
        self.disp: dict[str, dict[str, int]] = {}
        self.prom: dict[str, dict[str, int]] = {}
        por_carrera = defaultdict(set)
        hab = defaultdict(lambda: defaultdict(int))
        prom = defaultdict(lambda: defaultdict(int))
        for (rid, cod), filas in self._idx.items():
            por_carrera[rid].add(cod)
            for r in filas:
                c = r["cargo"] or ""
                # Accesitarios no cuentan: no se proclaman.
                if c.startswith(("REGIDOR", "CONSEJERO")) and not r["es_accesitario"]:
                    hab[rid][cod] += 1
                if r["origen_candidatura"] == "promocion_por_vacancia":
                    prom[rid][cod] += 1
        for rid, cods in por_carrera.items():
            self.disp[rid] = construye_disponibles(cods, dict(hab[rid]))
            if prom[rid]:
                self.prom[rid] = dict(prom[rid])

    def entradas(self, rid: str) -> dict:
        return {"disponibles": self.disp.get(rid), "promovidos": self.prom.get(rid)}

    def de(self, rid: str, cod: str, cargo: str, k: int, excluir=()) -> list[dict]:
        out = []
        for r in self._idx.get((rid, cod), ()):
            if len(out) >= k:
                break
            if not cargo or not (r["cargo"] or "").startswith(cargo) or str(r["dni"]) in excluir:
                continue
            out.append({"cand_id": r["cand_id"], "orden": int(r["posicion"]),
                        "nombre": r["candidato"], "dni": r["dni"], "sexo": r["sexo"],
                        "edad": int(r["edad"]) if r["edad"] is not None else None,
                        "hoja_vida_id": r["hoja_vida_id"], "domicilio": r["domicilio"],
                        "foto": r["foto"], "educacion": r["educacion"],
                        "sentencias_penales": r["sentencias_penales"],
                        "obligaciones": r["obligaciones"]})
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=RAIZ / "data")
    ap.add_argument("--sims", type=int, default=400)
    ap.add_argument("--semilla", type=int, default=7)
    a = ap.parse_args(argv)
    D = a.data

    uni, vot = consolida(D)
    if uni.empty:
        print("no hay agregados: corre 02a_scrape_distritos.py primero")
        return 1

    car = pd.read_csv(D / "reference/carreras.csv", dtype=str)
    dis = pd.read_csv(D / "reference/distritos.csv", dtype=str).fillna("")
    meta = json.loads((D / "meta.json").read_text())
    catalogo = {c["race_id"]: c for c in meta["carreras"]}
    planchas = Planchas(D / "reference/planchas_2026.parquet")

    # Padrón por distrito (locales de la ONPE, SAIP 292325) y actas por
    # distrito (maestro de mesas): las dos cosas que se saben antes de la noche.
    loc = pd.read_csv(D / "reference/locales.csv", dtype={"ubigeo_distrito": str})
    elec_mun = loc.groupby("ubigeo_distrito").electores_municipales.sum().to_dict()
    elec_reg = loc.groupby("ubigeo_distrito").electores_regionales.sum().to_dict()
    mesas = pd.read_parquet(D / "processed/mesas.parquet", columns=["ubigeo_distrito"])
    mesas_dist = mesas.ubigeo_distrito.value_counts().to_dict()
    distritos_de = {rid: sorted(g.ubigeo_distrito)
                    for col in COL_RACE.values()
                    for rid, g in dis[dis[col] != ""].groupby(col)}

    # Crosswalk revisado, si ya existe.
    cw = {}
    f_cw = D / "reference/crosswalk_organizaciones_2026.csv"
    if f_cw.exists():
        x = pd.read_csv(f_cw, dtype=str).dropna(subset=["codigo_onpe", "id_jne"])
        cw = {r.codigo_onpe: f"jne-{r.id_jne}" for r in x.itertuples()}

    # Índices del consolidado.
    fila = {(r["race_id"], r["ubigeo"]): r for r in uni.to_dict("records")}
    votos_u = defaultdict(dict)                       # (rid, ubigeo) -> {onpe: votos}
    nombre_onpe = {}
    for r in vot.itertuples(index=False):
        votos_u[(r.race_id, r.ubigeo)][r.codigo_onpe] = int(r.votos)
        nombre_onpe[r.codigo_onpe] = r.agrupacion

    # Llamadas vigentes del ciclo anterior, y el ledger append-only.
    d_ll = D / "interim/llamadas"
    d_ll.mkdir(parents=True, exist_ok=True)
    f_prev = d_ll / "estado.json"
    previo = json.loads(f_prev.read_text()) if f_prev.exists() else {}
    f_ledger = d_ll / "ledger.csv"
    nuevo_ledger = not f_ledger.exists()
    ledger = open(f_ledger, "a", newline="")
    lw = csv.writer(ledger)
    if nuevo_ledger:
        lw.writerow(["ts", "evento", "race_id", "estado", "quienes", "p", "pct_actas"])

    ahora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    sin_cruce, escritos, alertas = [], 0, []
    nuevo_estado, por_carrera = {}, []
    resumen = defaultdict(lambda: defaultdict(int))
    votos_org_tipo = defaultdict(lambda: defaultdict(int))
    consejo = defaultdict(dict)                # dep -> ubigeo circ -> datos
    tot = defaultdict(int)
    escanos_tipo = defaultdict(lambda: {"total": 0, "adjudicados": 0})
    # Para la pestaña PARTIDO: por carrera, votos y escaños garantizados de cada
    # lista. Compacto: [n_escanos, válidos, {codigo: [votos, escaños]}].
    por_partido = {}
    n_desfase = int(uni.desfase.sum())
    n_suma = 0

    for r in car.itertuples():
        rid, tipo = r.race_id, r.tipo
        f = D / "carrera" / f"{rid}.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        cat = catalogo.get(rid, {})
        n_e = int(cat.get("n_escanos") or 0)

        # --- organizaciones: las inscritas, a cero, más las que solo trae la ONPE
        doc["organizaciones"] = [o for o in doc["organizaciones"]
                                 if not str(o["codigo"]).startswith("onpe-")]
        orgs_doc = doc["organizaciones"]
        por_nombre = {norm(o["nombre"]): o for o in orgs_doc}
        por_codigo = {o["codigo"]: o for o in orgs_doc}
        for o in orgs_doc:
            o.update({"votos": 0, "pct_validos": 0.0, "p_gana": None,
                      "p_primera": None, "p_segunda": None})

        def cod_de(cod_onpe: str) -> str:
            o = (por_codigo.get(cw.get(cod_onpe))
                 or por_nombre.get(norm(nombre_onpe.get(cod_onpe)))
                 # Ya creada en esta carrera por otra unidad: la misma, no otra.
                 or por_codigo.get(f"onpe-{cod_onpe}"))
            if o is None:
                o = {"codigo": f"onpe-{cod_onpe}", "nombre": nombre_onpe.get(cod_onpe, cod_onpe),
                     "logo": None, "candidato": None, "votos": 0, "pct_validos": 0.0,
                     "p_gana": None, "p_primera": None, "p_segunda": None}
                orgs_doc.append(o)
                por_codigo[o["codigo"]] = o
                sin_cruce.append({"race_id": rid, "codigo_onpe": cod_onpe,
                                  "agrupacion": o["nombre"]})
            return o["codigo"]

        # --- unidades: la carrera y sus distritos
        dists = distritos_de.get(rid, []) if r.nivel_circunscripcion != "distrito" else []
        filas_d = {u: fila.get((rid, u)) for u in dists}
        vd = {u: {cod_de(k): v for k, v in votos_u.get((rid, u), {}).items()} for u in dists}
        hay_d = any(x is not None for x in filas_d.values())

        fr = fila.get((rid, ""))

        def suma_distritos():
            vr_ = defaultdict(int)
            for u in dists:
                for c, v in vd[u].items():
                    vr_[c] += v
            ok = [x for x in filas_d.values() if x is not None]
            return vr_, {
                "actas_total": sum(int(x["actas_total"]) for x in ok)
                + sum(mesas_dist.get(u, 0) for u, x in filas_d.items() if x is None),
                "actas_contabilizadas": sum(int(x["actas_contabilizadas"]) for x in ok),
                "emitidos": sum(int(x["emitidos"]) for x in ok),
                "validos": sum(int(x["validos"]) for x in ok),
                "participacion": None, "jee": sum(int(x["actas_jee"] or 0) for x in ok),
                "blancos": None, "nulos": None, "impugnados": None,
                "desfase": any(bool(x["desfase"]) for x in ok)}

        if fr is not None:
            vr = {}
            for k, v in votos_u.get((rid, ""), {}).items():
                c = cod_de(k)
                vr[c] = vr.get(c, 0) + v
            fuente = "onpe_carrera"
            comp = {"actas_total": int(fr["actas_total"]),
                    "actas_contabilizadas": int(fr["actas_contabilizadas"]),
                    "emitidos": int(fr["emitidos"]), "validos": int(fr["validos"]),
                    "participacion": fr["participacion_onpe"], "jee": fr["actas_jee"],
                    "blancos": fr["blancos"], "nulos": fr["nulos"],
                    "impugnados": fr["impugnados"], "desfase": bool(fr["desfase"])}
            # La petición de la carrera puede quedarse atrás de la de sus
            # distritos: las gobernaciones a nivel departamento dan 403 por
            # rachas, y el último corte bueno se queda. El 6 de octubre Cusco
            # mostraba 3,857 actas con sus distritos ya en 3,889. Si los
            # distritos llevan más actas contadas, mandan ellos: son cifras
            # oficiales igual, solo más recientes.
            if hay_d:
                vr_d, comp_d = suma_distritos()
                if comp_d["actas_contabilizadas"] > comp["actas_contabilizadas"]:
                    fuente, vr, comp, n_suma = "suma_distritos", vr_d, comp_d, n_suma + 1
        elif hay_d:
            # Sin la carrera, la suma de sus distritos: cifras oficiales igual.
            fuente, n_suma = "suma_distritos", n_suma + 1
            vr, comp = suma_distritos()
        else:
            fuente, vr, comp = None, {}, None

        for o in orgs_doc:
            o["votos"] = int(vr.get(o["codigo"], 0))
        validos = sum(o["votos"] for o in orgs_doc)
        for o in orgs_doc:
            o["pct_validos"] = round(o["votos"] / validos, 6) if validos else 0.0
            votos_org_tipo[o["codigo"]][tipo] += o["votos"]
        # Orden canónico y semilla por carrera: con los mismos datos, la misma
        # proyección. Si no, una carrera cerca del umbral se llama y se
        # desllama por puro ruido de Monte Carlo según el orden de la página.
        codigos = sorted(o["codigo"] for o in orgs_doc)
        rng = np.random.default_rng([a.semilla, zlib.crc32(rid.encode())])

        esp = comp["actas_total"] if comp else int(doc["computo"].get("actas_esperadas") or 0)
        cont = comp["actas_contabilizadas"] if comp else 0
        pct = cont / esp if esp else 0.0
        # La proyección distrital solo vale si los distritos van al día con la
        # carrera. En la primera pasada del ciclo la carrera es nueva y los
        # distritos son los del ciclo anterior: el 18 de octubre Canta
        # (provincial) estaba 48/48 con distritos en 46/48 y AN salía al 93%,
        # y Cusco simulaba sobre las actas del 6 de octubre (59,5% en 1.ª
        # vuelta con 33% y 14 actas por contar). Si van atrás, la carrera se
        # proyecta como un bloque; al 100% eso ya no simula nada.
        usa_d = hay_d and (fuente == "suma_distritos"
                           or suma_distritos()[1]["actas_contabilizadas"] >= cont)
        elec = elec_reg if tipo in ("01", "02") else elec_mun
        d_padron = dists or [r.ubigeo]
        emit = comp["emitidos"] if comp else 0
        doc["computo"] = {
            "actas_esperadas": esp, "actas_contabilizadas": cont,
            "pct_actas": round(pct, 6),
            "actas_jee": int(comp["jee"] or 0) if comp else 0,
            # Padrón entero de la circunscripción (locales ONPE), no el de lo contado.
            "electores_habiles": int(sum(elec.get(u, 0) for u in d_padron)) or None,
            "votos_emitidos": emit, "votos_validos": validos,
            "votos_blancos": comp["blancos"] if comp else None,
            "votos_nulos": comp["nulos"] if comp else None,
            "votos_impugnados": comp["impugnados"] if comp else None,
            "votos_blancos_nulos": (emit - validos) if comp and emit >= validos else None,
            "participacion": comp["participacion"] if comp else None,
            "fuente": fuente, "desfase": comp["desfase"] if comp else False,
        }
        tot["actas_esp"] += esp
        tot["actas_cont"] += cont
        if tipo == "03":                       # cubre el país una sola vez
            tot["emitidos"] += emit
            tot["validos"] += validos
            tot["electores"] += int(sum(elec_mun.get(u, 0) for u in dists))

        # --- desagregado para el mapa
        def celda(u, filas_u, votos_u_):
            a_ = sum(int(x["actas_contabilizadas"]) for x in filas_u if x is not None)
            t_ = (sum(int(x["actas_total"]) for x in filas_u if x is not None)
                  or sum(mesas_dist.get(d, 0) for d in u[1]))
            return {"ubigeo": u[0], "actas": a_, "pct_actas": round(a_ / t_, 6) if t_ else 0.0,
                    "votos": {k: v for k, v in votos_u_.items() if v}}

        niveles = doc.get("desagregado_niveles") or {}
        if tipo == "04" or (tipo == "02" and r.nivel_circunscripcion == "distrito"):
            if "distrito" in niveles:
                niveles["distrito"] = [celda((r.ubigeo, [r.ubigeo]), [fr], vr)]
        else:
            if "distrito" in niveles:
                niveles["distrito"] = [celda((x["ubigeo"], [x["ubigeo"]]),
                                             [filas_d.get(x["ubigeo"])], vd.get(x["ubigeo"], {}))
                                       for x in niveles["distrito"]]
            if "provincia" in niveles:
                fil = []
                for x in niveles["provincia"]:
                    ds = [d for d in dists if d[:4] == x["ubigeo"][:4]]
                    vv = defaultdict(int)
                    for d in ds:
                        for c, v in vd[d].items():
                            vv[c] += v
                    fil.append(celda((x["ubigeo"], ds), [filas_d[d] for d in ds], vv))
                niveles["provincia"] = fil
        doc["desagregado_niveles"] = niveles
        doc["desagregado"] = niveles.get("provincia") or niveles.get("distrito") or []

        # --- proyección
        estado, quienes, pisos, techos, p_esc = POR_DEFINIR, [], {}, None, None
        p_2v, respaldo, n_sims = None, False, 0
        if usa_d:
            V = np.array([[vd[u].get(c, 0) for c in codigos] for u in dists], float)
            at = np.array([int(filas_d[u]["actas_total"]) if filas_d[u] is not None
                           else mesas_dist.get(u, 0) for u in dists], float)
            ac = np.array([int(filas_d[u]["actas_contabilizadas"]) if filas_d[u] is not None
                           else 0 for u in dists], float)
            provs = np.array([u[:4] if tipo == "01" else r.ubigeo[:4] for u in dists])
        elif fr is not None:
            V = np.array([[vr.get(c, 0) for c in codigos]], float)
            at, ac = np.array([esp], float), np.array([cont], float)
            provs = np.array([r.ubigeo[:4]])
        else:
            V = None
        if V is not None and len(codigos) and V.sum() > 0:
            vpa = V.sum() / max(ac[V.sum(axis=1) > 0].sum(), 1.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                T = np.where((ac > 0) & (V.sum(axis=1) > 0),
                             V.sum(axis=1) * at / np.clip(ac, 1, None), at * vpa)
            T = np.maximum(T, V.sum(axis=1))
            sims = simula_totales(V, T, provs, a.sims, rng)
            if sims is not None:
                n_sims = a.sims
                faltan = bool((T - V.sum(axis=1)).sum() > 0.5)
                cuenta = defaultdict(int)
                gana = defaultdict(float)
                p1, p2 = defaultdict(int), defaultdict(int)
                n2v = 0
                cuerpo = bool(cat.get("cargo_proporcional")) and n_e > 0
                base_ok = pct >= PCT_MINIMO and cont >= min(MIN_ACTAS, esp)
                hace_pisos = cuerpo and base_ok
                asientos = defaultdict(list)
                filas_sim = sims if faltan else sims[:1]
                peso = 1.0 / len(filas_sim)
                for v in filas_sim:
                    vi = np.rint(v).astype(np.int64)
                    es = escenario(vi, codigos, tipo)
                    cuenta["|".join(es)] += 1
                    mx = vi.max()
                    lid = [codigos[i] for i in range(len(codigos)) if vi[i] == mx]
                    for q in lid:
                        gana[q] += peso / len(lid)
                    if es[0] == SEGUNDA_VUELTA:
                        n2v += 1
                        for q in es[1:]:
                            p2[q] += 1
                    elif es[0] == ELECTO and tipo == "01":
                        p1[es[1]] += 1
                    if hace_pisos:
                        rp = adjudica({c: int(x) for c, x in zip(codigos, vi) if x > 0},
                                      tipo, n_e, planchas.entradas(rid))
                        for c in codigos:
                            asientos[c].append(rp.escanos.get(c, 0))
                n = len(filas_sim)
                for o in orgs_doc:
                    o["p_gana"] = round(gana.get(o["codigo"], 0.0), 4)
                    if tipo == "01":
                        o["p_primera"] = round(p1.get(o["codigo"], 0) / n, 4)
                        o["p_segunda"] = round(p2.get(o["codigo"], 0) / n, 4)
                if tipo == "01":
                    p_2v = round(n2v / n, 4)
                mo = max(cuenta, key=cuenta.get)
                p_esc = cuenta[mo] / n
                if hace_pisos:
                    pisos = {c: piso(s) for c, s in asientos.items() if s}
                    techos = {c: techo(s) for c, s in asientos.items() if s}

                # Regla de salida: lo vigente se mantiene mientras siga siendo
                # lo más probable; lo nuevo entra con CONF y PCT_MINIMO.
                ant = previo.get(rid) or {}
                vig = "|".join([ant["estado"], *ant.get("quienes", [])]) if ant else None
                if vig and es_llamada(ant["estado"]) and cuenta.get(vig, 0) == max(cuenta.values()):
                    mo = vig
                    p_esc = cuenta[vig] / n
                if mo == vig or (p_esc >= CONF and base_ok):
                    partes = mo.split("|")
                    estado, quienes = partes[0], partes[1:]

        # Ledger: toda llamada nueva y toda revocación quedan escritas.
        ant = previo.get(rid) or {}
        ant_k = "|".join([ant.get("estado", POR_DEFINIR), *ant.get("quienes", [])])
        nue_k = "|".join([estado, *quienes])
        if ant_k != nue_k:
            if es_llamada(ant.get("estado", POR_DEFINIR)):
                lw.writerow([ahora, "revocada", rid, ant["estado"], "|".join(ant.get("quienes", [])),
                             "", round(pct, 4)])
                alertas.append(f"{rid}: {ant_k} → {nue_k}")
            if es_llamada(estado):
                lw.writerow([ahora, "llamada", rid, estado, "|".join(quienes),
                             round(p_esc or 0, 4), round(pct, 4)])
        nuevo_estado[rid] = {"estado": estado, "quienes": quienes}

        doc["pronostico"] = {"estado": estado, "quienes": quienes,
                             "p_segunda_vuelta": p_2v, "n_sims": n_sims,
                             "respaldo": respaldo,
                             "p_escenario": round(p_esc, 4) if p_esc is not None else None,
                             "modelo": "distrital" if usa_d else "carrera"}

        # --- electos
        org_de = {o["codigo"]: o for o in orgs_doc}
        gan = quienes[0] if quienes else None
        ej = (doc.get("electos") or {}).get("ejecutivo")
        dni_ej = set()
        if ej is not None:
            titular = (planchas.de(rid, gan, cat.get("cargo_ejecutivo") or "", 1)
                       if estado == ELECTO and gan else [])
            dni_ej = {str(c["dni"]) for c in titular}
            ej.update({"estado": estado, "organizacion": gan,
                       "organizacion_nombre": org_de[gan]["nombre"] if gan in org_de else None,
                       "organizacion_logo": org_de[gan].get("logo") if gan in org_de else None,
                       "titular": titular,
                       "acompanante": (planchas.de(rid, gan, cat["cargo_acompanante"], 1)
                                       if estado == ELECTO and gan and cat.get("cargo_acompanante")
                                       else [])})
        cu = (doc.get("electos") or {}).get("cuerpo")
        if cu is not None:
            asignados = sum(pisos.values())
            escanos_tipo[tipo]["total"] += n_e
            escanos_tipo[tipo]["adjudicados"] += int(asignados)
            cu.update({"adjudicados": int(asignados), "en_disputa": int(n_e - asignados),
                       # Máximo plausible de escaños por lista (None = sin base
                       # todavía). Lo usa Reelección para descartar a quien no
                       # entra en ningún escenario.
                       "techos": techos,
                       "por_organizacion": [
                           {"codigo": c, "nombre": org_de[c]["nombre"],
                            "logo": org_de[c].get("logo"), "escanos": int(k),
                            "candidatos": planchas.de(rid, c, cat.get("cargo_proporcional") or "",
                                                      int(k), excluir=dni_ej)}
                           for c, k in sorted(pisos.items(), key=lambda z: -z[1]) if k]})

        # --- consejo regional, para la página de la región
        if tipo == "02":
            asientos_c = []
            for c, k in sorted(pisos.items(), key=lambda z: -z[1]):
                fichas = planchas.de(rid, c, "CONSEJERO", int(k))
                for i in range(int(k)):
                    asientos_c.append({"organizacion": c, "nombre": org_de[c]["nombre"],
                                       "logo": org_de[c].get("logo"),
                                       "consejero": fichas[i] if i < len(fichas) else None})
            asientos_c += [{"organizacion": None, "nombre": None, "logo": None,
                            "consejero": None}] * max(0, n_e - len(asientos_c))
            lider = max(orgs_doc, key=lambda o: o["votos"]) if validos else None
            consejo[r.ubigeo[:2] + "0000"][r.ubigeo] = {
                "lider": lider["codigo"] if lider else None,
                "lider_nombre": lider["nombre"] if lider else None,
                "pct_actas": round(pct, 6), "escanos": asientos_c}

        # --- resumen nacional, desde las llamadas
        if tipo == "01":
            if estado == ELECTO and gan:
                resumen[gan]["gobernador_1v"] += 1
            elif estado == SEGUNDA_VUELTA:
                for q in quienes:
                    resumen[q]["gobernador_2v"] += 1
        elif estado == ELECTO and gan and tipo in ("03", "04"):
            resumen[gan][CAMPO_RESUMEN[tipo]] += 1
        for c, k in pisos.items():
            if k:
                resumen[c][CAMPO_CUERPO[tipo]] += k
        ganadores = []
        if estado in (ELECTO, SEGUNDA_VUELTA, EMPATE) and cat.get("cargo_ejecutivo"):
            for q in quienes:
                o = org_de.get(q, {})
                ganadores.append({"codigo": q, "organizacion": o.get("nombre", q),
                                  "candidato": (o.get("candidato") or {}).get("nombre")})
        por_carrera.append({"race_id": rid, "tipo": tipo, "ubigeo": r.ubigeo,
                            "estado": estado, "ganador": gan, "ganadores": ganadores,
                            "pct_actas": round(pct, 4)})

        por_partido[rid] = [n_e, validos,
                            {o["codigo"]: [o["votos"], int(pisos.get(o["codigo"], 0))]
                             for o in orgs_doc if o["votos"] or pisos.get(o["codigo"])}]
        doc["organizaciones"].sort(key=lambda o: (-o["votos"], o["nombre"]))
        # El sello solo se mueve si cambió algo de la página.
        previo_doc = json.loads(f.read_text())
        previo_doc.pop("actualizado", None)
        sin_sello = {k: v for k, v in doc.items() if k != "actualizado"}
        if json.dumps(previo_doc, sort_keys=True) != json.dumps(sin_sello, sort_keys=True):
            doc["actualizado"] = ahora
            escritos += escribe(f, doc)

    # --- consejo en la página regional
    for dep, circs in consejo.items():
        f = D / "carrera" / f"01-{dep}.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        con = doc.get("consejo")
        if not con:
            continue
        for c in con["circunscripciones"]:
            c.update(circs.get(c["ubigeo"], {}))
        con["adjudicados"] = sum(1 for c in con["circunscripciones"]
                                 for e in c["escanos"] if e["organizacion"])
        previo_doc = json.loads(f.read_text())
        previo_doc.pop("actualizado", None)
        sin_sello = {k: v for k, v in doc.items() if k != "actualizado"}
        if json.dumps(previo_doc, sort_keys=True) != json.dumps(sin_sello, sort_keys=True):
            doc["actualizado"] = ahora
            escritos += escribe(f, doc)

    ledger.close()
    tmp = f_prev.with_suffix(".tmp")
    tmp.write_text(json.dumps(nuevo_estado, separators=(",", ":")))
    tmp.replace(f_prev)

    # --- nacional
    nac = json.loads((D / "nacional.json").read_text())
    pct_nac = tot["actas_cont"] / tot["actas_esp"] if tot["actas_esp"] else 0.0
    estados = defaultdict(int)
    estados_tipo = defaultdict(lambda: defaultdict(int))
    for c in por_carrera:
        estados[c["estado"]] += 1
        estados_tipo[c["tipo"]][c["estado"]] += 1
    nac.update({
        "generado": ahora, "version": int(nac.get("version", 0)) + 1,
        "pct": round(pct_nac, 6),
        "actas_contabilizadas": tot["actas_cont"], "actas_esperadas": tot["actas_esp"],
        "electores_habiles": tot["electores"] or nac.get("electores_habiles"),
        # Sin mesas no se conoce el padrón de lo ya contado: no hay
        # participación comparable a mitad de escrutinio. Se publica solo al 100%.
        "electores_escrutados": None,
        "votos_emitidos": tot["emitidos"], "votos_validos": tot["validos"],
        "participacion": (round(tot["emitidos"] / tot["electores"], 6)
                          if pct_nac >= 1 and tot["electores"] else None),
        "carreras_llamadas": sum(1 for c in por_carrera if es_llamada(c["estado"])),
        "carreras": len(por_carrera),
        "estados": dict(estados),
        "estados_por_tipo": {t: dict(v) for t, v in sorted(estados_tipo.items())},
        "por_carrera": sorted(por_carrera, key=lambda c: c["race_id"]),
        "modo": "proyeccion_distrital",
        # Escaños de los cuerpos proporcionales: consejo regional (02), regidores
        # provinciales (03) y distritales (04). `adjudicados` son pisos
        # garantizados; el resto está por definir.
        "escanos_por_tipo": {t: dict(v) for t, v in sorted(escanos_tipo.items())},
    })
    nombres = dict(nac.get("organizaciones_nombre") or {})
    filas_org = {o["codigo"]: o for o in nac.get("por_organizacion", [])}
    CAMPOS = ["gobernador_1v", "gobernador_2v", "alcalde_prov", "alcalde_dist",
              "consejero", "regidor_prov", "regidor_dist"]
    for cod in set(resumen) - set(filas_org):
        # Una lista sin cruce que gana algo entra igual, con el nombre de la ONPE.
        nom = next((x["agrupacion"] for x in sin_cruce if f"onpe-{x['codigo_onpe']}" == cod), cod)
        filas_org[cod] = {"codigo": cod, "nombre": nom, "logo": None, "listas": 0,
                          "grupo": None, "grupo_nombre": None}
        nombres[cod] = nom
    for cod, o in filas_org.items():
        for k in CAMPOS:
            o[k] = int(resumen.get(cod, {}).get(k, 0))
        o["votos"] = dict(votos_org_tipo.get(cod, {}))
    nac["organizaciones_nombre"] = nombres
    nac["por_organizacion"] = sorted(
        filas_org.values(),
        key=lambda o: (-sum(o[k] for k in CAMPOS), -o.get("listas", 0), o["nombre"]))
    escribe(D / "nacional.json", nac)
    escribe(D / "partidos.json", {"generado": ahora, "carreras": por_partido})

    (D / "processed").mkdir(exist_ok=True)
    pd.DataFrame(sin_cruce, columns=["race_id", "codigo_onpe", "agrupacion"]).to_csv(
        D / "processed/publica_sin_cruce.csv", index=False)
    print(f"{escritos:,} páginas reescritas · actas {tot['actas_cont']:,}/{tot['actas_esp']:,} "
          f"({100 * pct_nac:.2f}%) · llamadas {nac['carreras_llamadas']:,} · "
          f"listas sin cruce {len(sin_cruce)}")
    print(f"  estados: {dict(estados)}")
    if n_suma:
        print(f"  {n_suma} carreras publicadas como suma de sus distritos (la carrera no respondió o se quedó atrás)")
    if n_desfase:
        print(f"  {n_desfase} unidades sin corte coherente reciente (totales y participantes desfasados)")
    if sin_cruce:
        print("  sin cruce -> processed/publica_sin_cruce.csv (entran con el nombre de la ONPE)")
    for x in alertas:
        print(f"\033[1;31mALERTA — llamada revocada: {x}\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
