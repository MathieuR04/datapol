#!/usr/bin/env python3
r"""Léxico distintivo de cada materia en la exposición de motivos.

Segmenta las 436 páginas en las 8 materias y calcula, para cada una, qué términos
la distinguen del resto del documento.

POR QUÉ NO ES UN CONTEO DE FRECUENCIA. En un texto legal las palabras más
frecuentes de cualquier bloque son las mismas: marco, normativo, materia,
medidas, fortalecer, disposiciones. Un ranking por frecuencia devuelve ese fondo
común ocho veces y no distingue nada. Lo que se usa acá es el **log-odds ratio
con prior Dirichlet informado** (Monroe, Colaresi & Quinn 2008), que compara la
proporción de cada término dentro de la materia contra su proporción en el resto
del corpus, usando el propio corpus como prior. Eso descuenta el boilerplate
—una palabra igual de común en todas partes da z≈0— y además entrega un z-score,
así que se puede decir cuáles términos son *significativamente* propios de un
bloque en vez de mostrar una nube de palabras.

ADVERTENCIA DE INTERPRETACIÓN. Esto caracteriza el vocabulario de cada bloque;
NO mide cuánto le importa cada tema al gobierno. El largo de un bloque responde
a cuánta sustentación técnica exige la materia, no al interés político — por eso
el análisis de prioridades vive en la amplitud de los pedidos
(analiza_propuestas.py), no acá.

Run: python3 scripts/analiza_lexico.py
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "data", "ocr", "exposicion_motivos.txt")
PROPS = os.path.join(ROOT, "data", "propuestas.json")
OUT = os.path.join(ROOT, "data", "lexico.json")

# Los rótulos de materia en los motivos vienen en mayúsculas pero con el prefijo
# destrozado por el OCR (".", "c.", ",", "2.", "1."), así que se anclan por el
# texto del rótulo, no por su numeración, y se validan contra el orden a–h.
ANCLAS = [
    ("a", r"EN MATERIA PENAL, PROCESAL PENAL"),
    ("b", r"EN MATERIA DE MICRO Y PEQUEÑAS EMPRESAS"),
    ("c", r"EN MATERIA LABORAL Y PROMOCIÓN DEL EMPLEO"),
    ("d", r"EN MATERIA DE SIMPLIFICACIÓN ADMINISTRATIVA"),
    ("e", r"EN MATERIA DE DESARROLLO PRODUCTIVO"),
    ("f", r"EN MATERIA TRIBUTARIA, ADUANERA"),
    ("g", r"EN MATERIA DE REFORMA ESTRUCTURAL"),
    ("h", r"EN MATERIA DE VIVIENDA Y SANEAMIENTO"),
]

STOP = set("""
a al algo algun alguna algunas alguno algunos ambos ante antes aquel aquella aquellas aquello
aquellos aqui arriba asi aun aunque bajo bien cada casi como con contra cual cuales cuando
cuanto cuenta da dado de del demas dentro desde donde dos e el ella ellas ello ellos en entre
era eran es esa esas ese eso esos esta estan estas este esto estos fin fue fuera fueron ha
habia han hasta hay la las le les lo los mas me mediante menos mi mientras misma mismas mismo
mismos mucha muchas mucho muchos muy nada ni no nos nuestra nuestras nuestro nuestros o otra
otras otro otros para pero poco por porque puede pueden pues que se sea sean segun ser si sido
sin sobre solo son su sus tal tambien tanto te tiene tienen toda todas todo todos tras un una
unas uno unos y ya
articulo articulos ley leyes decreto decretos legislativo legislativa norma normas normativa
normativo marco materia materias medida medidas disposicion disposiciones proyecto propuesta
regulacion regular establecer modificar fortalecer permitir efecto efectos ámbito ambito
nacional nacionales publico publica publicos publicas peru estado sistema general
numeral numerales asimismo ademas cabe respecto asi conforme dicha dicho dichas dichos
tal tales ello esta este dicho actual actualmente vigente
""".split())

TOKEN_RE = re.compile(r"[a-záéíóúñü]{4,}")
TILDES = str.maketrans("áéíóúü", "aeiouu")


def tokens(txt: str) -> list[str]:
    return [w for w in TOKEN_RE.findall(txt.lower())
            if w.translate(TILDES) not in STOP and w not in STOP]


def segmenta() -> dict[str, str]:
    raw = open(SRC, encoding="utf-8").read()
    raw = re.sub(r"\n=== \[pág \d+\] ===\n", "\n", raw)
    pos = []
    for letra, pat in ANCLAS:
        m = re.search(pat, raw)
        if m is None:
            raise SystemExit(f"ancla no encontrada para materia {letra}: {pat!r}")
        pos.append((letra, m.start()))
    if [p for _, p in pos] != sorted(p for _, p in pos):
        raise SystemExit("las materias no aparecen en orden a–h; revisar anclas")
    seg = {}
    for i, (letra, ini) in enumerate(pos):
        fin = pos[i + 1][1] if i + 1 < len(pos) else len(raw)
        seg[letra] = raw[ini:fin]
    return seg


def log_odds(grupo: Counter, resto: Counter, a0: float = 500.0) -> dict[str, float]:
    """Monroe et al. (2008): log-odds con prior Dirichlet tomado del corpus."""
    fondo = grupo + resto
    tot_fondo = sum(fondo.values())
    n_i, n_j = sum(grupo.values()), sum(resto.values())
    out = {}
    for w, f in fondo.items():
        alpha = a0 * f / tot_fondo
        yi, yj = grupo.get(w, 0), resto.get(w, 0)
        num_i = (yi + alpha) / (n_i + a0 - yi - alpha)
        num_j = (yj + alpha) / (n_j + a0 - yj - alpha)
        delta = math.log(num_i) - math.log(num_j)
        var = 1.0 / (yi + alpha) + 1.0 / (yj + alpha)
        out[w] = delta / math.sqrt(var)
    return out


def main():
    seg = segmenta()
    props = json.load(open(PROPS, encoding="utf-8"))
    titulos = {m["letra"]: m["titulo"] for m in props["materias"]}
    n_props = {m["letra"]: m["n_propuestas"] for m in props["materias"]}

    toks = {k: Counter(tokens(v)) for k, v in seg.items()}
    total = sum(toks.values(), Counter())

    salida = {}
    for letra in sorted(seg):
        resto = total - toks[letra]
        z = log_odds(toks[letra], resto)
        # sólo términos con presencia real en el bloque
        top = sorted(((w, s) for w, s in z.items() if toks[letra][w] >= 12),
                     key=lambda x: -x[1])[:18]
        salida[letra] = {
            "titulo": titulos[letra],
            "n_propuestas": n_props[letra],
            "n_tokens": sum(toks[letra].values()),
            "distintivos": [{"termino": w, "z": round(s, 1), "n": toks[letra][w]}
                            for w, s in top],
        }
        print(f"\n{letra}. {titulos[letra][:70]}")
        print(f"   {n_props[letra]} propuestas · {sum(toks[letra].values()):,} tokens")
        print("   " + " · ".join(f"{w}({s:.0f})" for w, s in top[:12]))

    json.dump(salida, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
