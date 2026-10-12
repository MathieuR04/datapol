#!/usr/bin/env python3
"""Sorteo de clases: qué 54 senadores habrían quedado electos.

Cada circunscripción tiene dos escaños y vota en dos de las tres elecciones;
en la tercera descansa. Su «clase» es el año en que descansa, y cada clase
tiene 9 circunscripciones: así cada elección renueva un tercio (18 de 54).
Los senadores de una circunscripción son los ganadores de los dos años en que
votó. Se sortean las clases muchas veces y se reporta el reparto de escaños
más probable bancada por bancada (ver abajo), con el rango por partido.

Uso:
    uv run --with pandas python scripts/02_simula.py [--n 100000]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
AÑOS = [2016, 2021, 2026]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100_000)
    ap.add_argument("--semilla", type=int, default=2026)
    a = ap.parse_args()

    g = pd.read_csv(AQUI / "data/ganadores.csv").pivot(index="circ", columns="anio", values="ganador")
    W = g[AÑOS].to_numpy()                                  # (27, 3)
    partidos = sorted(set(W.ravel()))
    idx = {p: i for i, p in enumerate(partidos)}
    Wi = np.vectorize(idx.get)(W)
    total_p = np.zeros(len(partidos), int)                  # 81 «senadores posibles»
    for x in Wi.ravel():
        total_p[x] += 1

    rng = np.random.default_rng(a.semilla)
    base = np.repeat([0, 1, 2], 9)
    escanos = np.empty((a.n, len(partidos)), int)
    sorteos = np.empty((a.n, 27), np.int8)
    for s in range(a.n):
        descansa = rng.permutation(base)                    # año en que descansa cada circ
        sorteos[s] = descansa
        quita = Wi[np.arange(27), descansa]
        escanos[s] = total_p - np.bincount(quita, minlength=len(partidos))
    cuenta = Counter(map(tuple, escanos))
    # «El más probable» se lee bancada por bancada: el número de escaños más
    # frecuente de cada partido. Esas modas no siempre suman 54; se toma el
    # reparto realizable que mejor las combina (máxima suma de log-probabilidad
    # marginal de cada bancada).
    marg = [np.bincount(escanos[:, i], minlength=escanos[:, i].max() + 1) / a.n
            for i in range(len(partidos))]
    modas_marg = [int(np.argmax(x)) for x in marg]
    vecs = np.array(list(cuenta))
    lp = sum(np.log(np.maximum(marg[i][vecs[:, i]], 1e-12)) for i in range(len(partidos)))
    moda = tuple(vecs[int(np.argmax(lp))])
    veces = cuenta[moda]
    resumen = {p: {"moda": int(moda[i]), "min": int(escanos[:, i].min()),
                   "p05": int(np.percentile(escanos[:, i], 5)),
                   "media": round(float(escanos[:, i].mean()), 2),
                   "p95": int(np.percentile(escanos[:, i], 95)), "max": int(escanos[:, i].max()),
                   "dist": np.bincount(escanos[:, i]).tolist()}
               for i, p in enumerate(partidos)}
    # Un sorteo concreto que da la moda, para dibujar sus mapas.
    k = int(np.where((escanos == np.array(moda)).all(axis=1))[0][0])
    clases_moda = {c: AÑOS[int(d)] for c, d in zip(g.index, sorteos[k])}
    fp = escanos[:, idx["FP"]]
    out = {"n": a.n, "moda": {p: int(moda[i]) for i, p in enumerate(partidos)},
           "p_moda": round(veces / a.n, 4), "partidos": resumen,
           "modas_bancada": {p: modas_marg[i] for i, p in enumerate(partidos)},
           "p_fp_mayoria": round(float((fp >= 28).mean()), 4),
           "posibles": {p: int(total_p[i]) for i, p in enumerate(partidos)},
           "descansa_moda": clases_moda}
    (AQUI / "data/simulacion.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"modas por bancada: {dict(zip(partidos, modas_marg))} (suman {sum(modas_marg)})")
    print(f"{a.n:,} sorteos · reparto más probable por bancada ({100 * veces / a.n:.2f}% de los sorteos):")
    for p, r in sorted(resumen.items(), key=lambda kv: -kv[1]["media"]):
        print(f"  {p:4s} moda {r['moda']:2d} · media {r['media']:5.2f} · 90%: {r['p05']}–{r['p95']} · "
              f"rango {r['min']}–{r['max']} · de {total_p[idx[p]]} posibles")
    print(f"P(FP ≥ 28, mayoría de 54) = {out['p_fp_mayoria']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
