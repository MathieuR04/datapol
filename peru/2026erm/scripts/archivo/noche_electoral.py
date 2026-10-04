#!/usr/bin/env python3
"""Simulación de una noche electoral completa sobre ERM 2022.

Recorre las 2,116 carreras con un solo reloj —un orden de llegada nacional
construido sobre los locales de votación— y en cada corte hace lo que haría el
producto en vivo: proyectar, adjudicar, y decidir qué se publica.

QUÉ CUENTA COMO LLAMADA
-----------------------
Tres cosas, y las tres se retractan igual de feo si salen mal:

  · **ejecutivo** — `('1V', org)` o `('2V', par)` en gobernador, `('gana', org)`
    en alcaldías. Se llama cuando el escenario aparece en >= `--conf` de las
    simulaciones.
  · **escaño** — el piso garantizado de cada lista: el mayor k que obtiene en
    >= `--conf` de las simulaciones. Llamar «esta lista tiene 3» es afirmar que
    esos tres asientos ya están adjudicados.
  · **empate** — declarar que un escaño se va a sorteo **también es una
    llamada**. La ley lo resuelve por azar, así que decirlo es una afirmación
    verificable y se contabiliza como cualquier otra.

RETRACTACIÓN
------------
Una llamada retractada es un piso que baja, o un escenario ejecutivo que cambia
o desaparece, entre dos cortes consecutivos. De cada retractación interesa saber
si **al final se materializó igual** —el caso de Perú Libre en Loreto, que
perdió el escaño proyectado y terminó ganándolo— o si el modelo había estado
sencillamente equivocado. Son dos errores muy distintos: el primero es una banda
demasiado optimista, el segundo es un sesgo.

DOS RELOJES
-----------
`interno`  — cada carrera avanza en décimos de **sus propias** actas. Es la
             vista que aísla el comportamiento del modelo por carrera.
`nacional` — décimos del cómputo **del país**. Es la vista del producto: a las
             once de la noche, ¿cuántas autoridades se pueden publicar?

Uso:
    uv run python scripts/noche_electoral.py --sims 100 --semilla 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from datapol.adjudicacion import Entradas, adjudica  # noqa: E402
from datapol.estados import (ELECTO, EMPATE, POR_DEFINIR,  # noqa: E402
                             SEGUNDA_VUELTA, SIN_RESULTADO)
from datapol.forecast_mesas import NIVELES_POR_TIPO, UMBRAL_1V, simula  # noqa: E402

NIVELES = {"provincia": ("local", "distrito", "provincia"),
           "distrito": ("local", "distrito")}


def carga_todo():
    """Un solo pase por los parquet; después se rebana en memoria."""
    res = pd.read_parquet(RAIZ / "data/processed/resultados_mesa_ERM2022.parquet")
    comp = pd.read_parquet(RAIZ / "data/processed/computo_mesa_ERM2022.parquet")
    comp = comp[comp.observacion.fillna("").str.upper().str.contains("NORMAL")]
    # blancos/nulos/impugnados no los usa el forecaster, pero la página de
    # carrera los pide y no se pueden derivar del voto por organización.
    comp = comp[["mesa", "tipo", "ubigeo_distrito", "local", "electores", "votaron",
                 "votos_blancos", "votos_nulos", "votos_impugnados"]]
    return res, comp


def carreras(res, comp):
    """-> {race_id: (frame de mesas, orgs, tipo, niveles, n_escanos)}."""
    car = pd.read_csv(RAIZ / "data/reference/carreras_2022.csv", dtype=str)
    cons = pd.read_csv(RAIZ / "data/reference/consejeros_2022.csv", dtype=str)
    nivel_circ = dict(zip("02-" + cons.ubigeo_circunscripcion,
                          cons.nivel_circunscripcion))
    n_esc = {r.tipo + "-" + r.ubigeo: (int(float(r.n_escanos))
                                       if pd.notna(r.n_escanos) else 0)
             for r in car.itertuples()}

    salida = {}
    for tipo, g in res.groupby("tipo"):
        c = comp[comp.tipo == tipo]
        piv = g.pivot_table(index=["ubigeo_distrito", "mesa"], columns="codigo_onpe",
                            values="votos", aggfunc="sum", fill_value=0).reset_index()
        orgs_all = [x for x in piv.columns if x not in ("ubigeo_distrito", "mesa")]
        m = c.merge(piv, on=["ubigeo_distrito", "mesa"], how="inner")
        m["distrito"] = m.ubigeo_distrito
        m["provincia"] = m.ubigeo_distrito.str[:4]
        m["departamento"] = m.ubigeo_distrito.str[:2]
        m["local"] = m.ubigeo_distrito + "_" + m.local.fillna("SIN_LOCAL")

        if tipo == "01":
            clave, niv = "departamento", NIVELES_POR_TIPO["01"]
            grupos = [(f"01-{d}0000", gg, niv) for d, gg in m.groupby(clave)]
        elif tipo == "02":
            grupos = []
            for u, gg in m.groupby("provincia"):
                rid = f"02-{u}00"
                if rid in n_esc:
                    grupos.append((rid, gg, NIVELES["provincia"]))
            for u, gg in m.groupby("distrito"):
                rid = f"02-{u}"
                if rid in n_esc and nivel_circ.get(rid) == "distrito":
                    grupos.append((rid, gg, NIVELES["distrito"]))
        elif tipo == "03":
            grupos = [(f"03-{u}00", gg, NIVELES["provincia"])
                      for u, gg in m.groupby("provincia")]
        else:
            grupos = [(f"04-{u}", gg, NIVELES["distrito"])
                      for u, gg in m.groupby("distrito")]

        for rid, gg, niv in grupos:
            if rid not in n_esc:
                continue
            # Una carrera de **lista única** es legítima y hay que proyectarla:
            # en ERM 2022 hubo 19 distritos con una sola organización en la
            # papeleta.
            usa = [o for o in orgs_all if gg[o].to_numpy().sum() > 0]
            salida[rid] = (gg.reset_index(drop=True), usa, tipo, niv, n_esc[rid])
    return salida


def escenario_de(votos: np.ndarray, orgs, tipo: str, rep) -> tuple:
    """Estado de la carrera. Cinco valores; ver `datapol.estados`.

    **El estado describe al ejecutivo, no al cuerpo proporcional.** Antes se leía
    `rep.empate`, que el allocator calcula como «empate por la alcaldía **o**
    empate por algún escaño». Con eso, un empate entre dos listas por el último
    regidor dejaba toda la elección marcada como EMPATE aunque el alcalde se
    hubiera ganado por treinta puntos: en San Pedro de Laraos, Concertación sacó
    56.8% contra 16.2% y la página decía que no había nada resuelto.

    Los escaños empatados siguen declarándose donde corresponde —`en_disputa` del
    cuerpo—, que es donde esa información significa algo.
    """
    if len(votos) == 0 or votos.sum() <= 0:
        return (SIN_RESULTADO,)
    o = np.argsort(-votos)
    primeros = [orgs[i] for i in range(len(orgs)) if votos[i] == votos[o[0]]]
    if tipo == "01":
        # Con umbral y segunda vuelta, un empate solo es indefinición si toca al
        # puesto que decide: el primero cuando supera el umbral, o cualquiera de
        # los dos que pasan cuando no.
        if votos[o[0]] / votos.sum() >= UMBRAL_1V:
            return ((EMPATE, *sorted(primeros)) if len(primeros) > 1
                    else (ELECTO, orgs[o[0]]))
        segundos = [orgs[i] for i in range(len(orgs)) if votos[i] == votos[o[1]]]
        if len(primeros) > 1 or len(segundos) > 1:
            return (EMPATE, *sorted(set(primeros) | set(segundos)))
        return (SEGUNDA_VUELTA, *sorted((orgs[o[0]], orgs[o[1]])))
    if len(primeros) > 1:
        return (EMPATE, *sorted(primeros))
    return (ELECTO, orgs[int(np.argmax(votos))])


def piso(vals, conf):
    s = sorted(vals)
    return s[min(int(np.floor(len(s) * (1 - conf))), len(s) - 1)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--paso", type=float, default=0.10)
    ap.add_argument("--conf", type=float, default=0.99)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--limite", type=int, help="solo las primeras N carreras")
    ap.add_argument("--solo", help="lista de race_id separados por coma")
    ap.add_argument("--out", type=Path,
                    default=RAIZ / "data/processed/noche_electoral_2022.parquet")
    args = ap.parse_args()

    print("cargando…", flush=True)
    res, comp = carga_todo()
    todas = carreras(res, comp)
    del res
    # Toda carrera del registro tiene que aparecer, aunque no haya quedado ni
    # un acta contabilizable: su pronóstico es «anulada».
    car_todas = pd.read_csv(RAIZ / "data/reference/carreras_2022.csv", dtype=str)
    sin_res = sorted(set(car_todas.tipo + "-" + car_todas.ubigeo) - set(todas))
    if args.solo:
        pedidas = set(args.solo.split(","))
        todas = {k: v for k, v in todas.items() if k in pedidas}
        sin_res = [a for a in sin_res if a in pedidas]
    print(f"{len(todas):,} carreras", flush=True)

    ent = Entradas()
    rng = np.random.default_rng(args.semilla)

    # Reloj nacional: un orden de llegada sobre los locales del país.
    locs = sorted({l for v in todas.values() for l in v[0].local.unique()})
    rng.shuffle(locs)
    rank = {l: i for i, l in enumerate(locs)}
    n_loc = len(locs)

    cortes = np.arange(args.paso, 1.0 + 1e-9, args.paso)
    filas = []
    for k, (rid, (m, orgs, tipo, niv, n_e)) in enumerate(sorted(todas.items())):
        m = m.assign(_r=m.local.map(rank)).sort_values(["_r", "mesa"])
        V = m[orgs].to_numpy(np.int64)
        tot_real = V.sum(axis=0)
        e = ent.de(rid)
        rep_real = (None if tipo == "01" else
                    adjudica({a: int(v) for a, v in zip(orgs, tot_real)},
                             tipo, n_e, e))
        esc_real = escenario_de(tot_real, orgs, tipo, rep_real)
        real_esc = {} if rep_real is None else {a: v for a, v in
                                                rep_real.escanos.items() if v}

        for reloj in ("interno", "nacional"):
            for frac in cortes:
                if reloj == "interno":
                    kk = max(1, int(round(frac * len(m))))
                else:
                    kk = int((m._r < frac * n_loc).sum())
                cont, falt = m.iloc[:kk], m.iloc[kk:]
                if len(cont) == 0:
                    filas.append((rid, tipo, reloj, round(frac, 2), 0,
                                  POR_DEFINIR, "", 0, 0, n_e))
                    continue
                r = simula(cont, falt, orgs, args.sims, rng, tipo, niv)
                if r["sin_prior"]:
                    filas.append((rid, tipo, reloj, round(frac, 2), kk,
                                  POR_DEFINIR, "", 0, 1, n_e))
                    continue
                tot = r["totales"]
                escen: dict = {}
                seats = {a: [] for a in orgs}
                for i in range(args.sims):
                    v = tot[i]
                    votos = {a: int(x) for a, x in zip(orgs, v) if x > 0}
                    rep = (None if tipo == "01"
                           else adjudica(votos, tipo, n_e, e))
                    es = escenario_de(v, orgs, tipo, rep)
                    escen[es] = escen.get(es, 0) + 1
                    if rep is not None:
                        for a in orgs:
                            seats[a].append(rep.escanos.get(a, 0))
                mejor, cnt = max(escen.items(), key=lambda kv: kv[1])
                llamado = mejor if cnt / args.sims >= args.conf else None
                pisos = ({a: piso(seats[a], args.conf) for a in orgs}
                         if any(seats.values()) else {})
                filas.append((rid, tipo, reloj, round(frac, 2), kk,
                              "|".join(map(str, llamado)) if llamado
                              else POR_DEFINIR,
                              "|".join(f"{a}:{v}" for a, v in pisos.items() if v),
                              sum(pisos.values()), 0, n_e))
        if (k + 1) % 200 == 0:
            print(f"   {k+1:,}/{len(todas):,}", flush=True)
        if args.limite and k + 1 >= args.limite:
            break

    for rid in sin_res:
        for reloj in ("interno", "nacional"):
            for frac in cortes:
                filas.append((rid, rid[:2], reloj, round(frac, 2), 0,
                              SIN_RESULTADO, "", 0, 0, 0))

    t = pd.DataFrame(filas, columns=["race_id", "tipo", "reloj", "frac", "actas",
                                     "llamado", "pisos", "electos", "sin_prior",
                                     "n_escanos"])
    # Verdad final, para juzgar cada llamada.
    verdad = [(rid, SIN_RESULTADO, "") for rid in sin_res]
    for rid, (m, orgs, tipo, niv, n_e) in sorted(todas.items()):
        tot = m[orgs].to_numpy(np.int64).sum(axis=0)
        rep = (None if tipo == "01" else
               adjudica({a: int(v) for a, v in zip(orgs, tot)}, tipo, n_e,
                        ent.de(rid)))
        verdad.append((rid, "|".join(map(str, escenario_de(tot, orgs, tipo, rep))),
                       "|".join(f"{a}:{v}" for a, v in
                                (rep.escanos.items() if rep else []) if v)))
    v = pd.DataFrame(verdad, columns=["race_id", "esc_real", "pisos_real"])
    t = t.merge(v, on="race_id", how="left")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t.to_parquet(args.out, index=False)
    print(f"escrito: {args.out}  ({len(t):,} filas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
