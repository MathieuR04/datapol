#!/usr/bin/env python3
r"""Pedido de facultades vs. plan de gobierno de Fuerza Popular → data/comparacion_plan.json.

LA PREGUNTA: la delegación no puede ni debe cubrir todo el plan de gobierno —para
eso están el presupuesto y la gestión ordinaria—, y este es además el primer
pedido de un gobierno que empieza. Así que lo que entra no dice qué se abandona,
dice qué se puso primero. La comparación mide priorización, no incumplimiento.

MÉTODO. Tres decisiones, cada una tomada tras ver fallar la alternativa:

1. LA UNIDAD DE COMPARACIÓN ES LA PROMESA, NO EL CAPÍTULO. Cada capítulo del plan
   trae `X.Y.2. Nuestras propuestas` y `X.Y.3. Primeros 100 días`, con las
   promesas en viñetas de una a cuatro líneas — tamaño comparable al de un
   numeral del pedido. Emparejar contra el capítulo entero (que incluye
   diagnóstico y tablas de metas) fracasó de forma medible: el capítulo más largo
   se volvía un sumidero que atraía propuestas sin relación con él, porque BM25
   premia al documento largo con vocabulario diverso. Comparando viñeta contra
   numeral el problema desaparece: los dos lados miden lo mismo.

2. EL CORTE ES UN z POR PROPUESTA, NO UN BM25 ABSOLUTO. Fijar "BM25 > 3" a mano es
   elegir el resultado: con el umbral bajo todo tiene correlato en el plan y con
   el umbral alto nada lo tiene. La primera versión intentó calibrarlo con una
   nula por permutación —consultas de tokens barajados del plan— y quedó peor:
   una consulta aleatoria sacada del propio vocabulario del plan encuentra buen
   calce entre 700 promesas, mientras que las propuestas reales usan léxico
   jurídico escaso en el plan, así que la nula terminaba *por encima* de los
   casos verdaderos y descartaba 58 de 66.
   El estadístico que sí compara lo comparable es interno a cada propuesta:
   z = (mejor puntaje − media de sus 700 puntajes) / desviación. Pregunta si la
   mejor coincidencia **sobresale entre las demás**, y como se normaliza contra la
   propia distribución de esa propuesta, el desajuste de vocabulario entre los dos
   documentos se cancela.

3. SE REPORTA EL MARGEN. Cuando la primera y la segunda coincidencia empatan, la
   asignación es dudosa y va marcada como tal en vez de contarse como firme.

Run: python3 scripts/compara_plan.py
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PLAN = os.path.join(ROOT, "data", "ocr", "plan_gobierno_fp2026.txt")
PROPS = os.path.join(ROOT, "data", "propuestas.json")
OUT = os.path.join(ROOT, "data", "comparacion_plan.json")

from analiza_lexico import STOP, TILDES, TOKEN_RE

# `3.10. PERUANOS EN EL EXTRANJERO – PEX Y POLÍTICA` no entraba en una clase de
# caracteres estrecha, y por eso el capítulo anterior se tragaba la cola del
# documento (7.116 palabras contra 772–3.312 del resto) y actuaba de sumidero.
SEC_RE = re.compile(r"^(\d\.\d{1,2})\.\s+([A-ZÁÉÍÓÚÑ][^a-z]{3,70})\s*$")
SUB_RE = re.compile(r"^(\d\.\d{1,2}\.\d)\.\s+(.+?)\s*$")
FIN_RE = re.compile(r"^(RENDICI[ÓO]N DE CUENTAS|BIBLIOGRAF|ANEXO)")
PROMESA_SEC = re.compile(r"nuestras\s+propuestas|primeros\s+100\s+d[ií]as", re.IGNORECASE)
VINETA_RE = re.compile(r"^\s*[•·▪◦*]\s*(.+)")
Z_MIN = 4.0        # cuántas desviaciones debe sobresalir la mejor coincidencia


def toks(txt: str) -> list[str]:
    return [w for w in TOKEN_RE.findall(txt.lower())
            if w.translate(TILDES) not in STOP and w not in STOP]


def carga_promesas():
    """Devuelve (capitulos, promesas). Una promesa = una viñeta bajo
    'Nuestras propuestas' o 'Primeros 100 días'."""
    lineas = open(PLAN, encoding="utf-8").read().split("\n")
    # El índice del PDF ya nombra "RENDICIÓN DE CUENTAS ... 133", así que cortar en
    # la PRIMERA aparición deja el documento vacío. Vale la última.
    fins = [i for i, l in enumerate(lineas) if FIN_RE.match(l.strip())]
    corte = fins[-1] if fins else len(lineas)

    marcas, pilar = [], None
    for i, l in enumerate(lineas[:corte]):
        s = l.strip()
        mp = re.match(r"^PILAR ESTRAT[ÉE]GICO (\d+):\s*(.+?)\s*$", s)
        if mp:
            pilar = f"{mp.group(1)}. {mp.group(2).title()}"
            continue
        m = SEC_RE.match(s)
        if m:
            marcas.append((i, m.group(1), re.sub(r"\s+", " ", m.group(2)).title(), pilar))
    # el índice del PDF repite los títulos: vale la última aparición, que abre texto
    ult = {}
    for i, cod, tit, pil in marcas:
        ult[cod] = (i, tit, pil)
    orden = sorted(ult.items(), key=lambda kv: kv[1][0])

    caps, promesas = {}, []
    for j, (cod, (ini, tit, pil)) in enumerate(orden):
        fin = orden[j + 1][1][0] if j + 1 < len(orden) else corte
        caps[cod] = {"codigo": cod, "titulo": tit, "pilar": pil,
                     "n_palabras": len(" ".join(lineas[ini:fin]).split())}
        dentro, buf = False, []

        def vuelca():
            if buf:
                t = re.sub(r"\s+", " ", " ".join(buf)).strip()
                if len(t.split()) >= 5:
                    promesas.append({"id": f"{cod}#{len(promesas)}", "capitulo": cod,
                                     "titulo_cap": tit, "pilar": pil, "texto": t})
                buf.clear()

        for l in lineas[ini:fin]:
            s = l.strip()
            if s.startswith("==="):
                continue
            ms = SUB_RE.match(s)
            if ms:
                vuelca()
                dentro = bool(PROMESA_SEC.search(ms.group(2)))
                continue
            if not dentro or not s:
                continue
            mv = VINETA_RE.match(s)
            if mv:
                vuelca()
                buf.append(mv.group(1))
            elif buf:
                buf.append(s)
        vuelca()
    return caps, promesas


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tf = {d: Counter(t) for d, t in docs.items()}
        self.len = {d: len(t) for d, t in docs.items()}
        self.avg = sum(self.len.values()) / max(1, len(self.len))
        df = Counter()
        for t in self.tf.values():
            df.update(t.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def score(self, q, doc):
        tf, dl, s = self.tf[doc], self.len[doc], 0.0
        for w in q:
            f = tf.get(w, 0)
            if f:
                s += self.idf.get(w, 0) * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        return s

    def mejores(self, q, k=3):
        sc = sorted(((self.score(q, d), d) for d in self.tf), reverse=True)
        return sc[:k]


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def coseno(a: Counter, b: Counter) -> float:
    inter = set(a) & set(b)
    if not inter:
        return 0.0
    num = sum(a[w] * b[w] for w in inter)
    return num / (math.sqrt(sum(v * v for v in a.values()))
                  * math.sqrt(sum(v * v for v in b.values())))


def matriz_agregada(caps, promesas, props, tit):
    """Similitud materia(pedido) × capítulo(plan) sobre texto AGREGADO.

    Es el nivel al que la comparación sí resiste. El emparejamiento numeral-a-viñeta
    fracasa porque los dos documentos hablan idiomas distintos —el pedido en
    lenguaje delegante ("modificar el marco normativo en materia de…") y el plan en
    lenguaje de campaña ("construcción de 1.25 millones de viviendas")—, y con
    textos de 60 palabras el solapamiento léxico que queda es ruido: ninguna de las
    66 cae bajo el corte y 38 quedan ambiguas. Agregando por materia y por capítulo
    cada bolsa junta miles de tokens, la señal emerge sobre el ruido, y el
    resultado pasa control de plausibilidad: Orden Ciudadano casa con la materia
    penal, MYPE con la de micro y pequeñas empresas, Agua y Saneamiento con la de
    vivienda y saneamiento — sin que nada de eso esté codificado a mano.
    """
    bolsa_mat = defaultdict(Counter)
    for p in props:
        bolsa_mat[p["materia"]].update(toks(p["texto"]))
    bolsa_cap = {c: Counter(toks(" ".join(x["texto"] for x in promesas
                                          if x["capitulo"] == c))) for c in caps}
    letras = sorted(bolsa_mat)
    filas = []
    for c in caps:
        sims = {l: round(coseno(bolsa_mat[l], bolsa_cap[c]) * 100, 1) for l in letras}
        mejor = max(sims, key=sims.get)
        filas.append({"capitulo": c, "titulo": caps[c]["titulo"], "pilar": caps[c]["pilar"],
                      "sim": sims, "materia_mas_cercana": mejor, "max": sims[mejor]})
    return letras, filas


def main():
    caps, promesas = carga_promesas()
    d = json.load(open(PROPS, encoding="utf-8"))
    props = d["propuestas"]
    print(f"capítulos del plan: {len(caps)}   promesas (viñetas): {len(promesas)}   "
          f"propuestas del pedido: {len(props)}\n")

    ptoks = {p["id"]: toks(p["texto"]) for p in promesas}
    bm = BM25(ptoks)
    qs = {p["id"]: toks(p["texto"]) for p in props}

    por_id = {x["id"]: x for x in promesas}
    porcap = defaultdict(list)
    sin_cap, dudosas = [], []
    for p in props:
        q = qs[p["id"]]
        todos = [(bm.score(q, dd), dd) for dd in ptoks]
        todos.sort(reverse=True)
        vals = [s for s, _ in todos]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1e-9
        (s1, id1), (s2, _) = todos[0], todos[1]
        z = (s1 - mu) / sd
        prom = por_id[id1]
        p["plan_score"] = round(s1, 2)
        p["plan_z"] = round(z, 2)
        p["plan_margen"] = round((s1 - s2) / s1 if s1 else 0.0, 3)
        p["plan_promesa"] = prom["texto"][:220]
        p["plan_capitulo"] = prom["capitulo"] if z >= Z_MIN else None
        if p["plan_capitulo"] is None:
            sin_cap.append(p)
        else:
            porcap[prom["capitulo"]].append(p["id"])
            if p["plan_margen"] < 0.10:
                dudosas.append(p)
    zs = sorted(p["plan_z"] for p in props)
    print(f"z de la mejor coincidencia: mín {zs[0]:.1f}  mediana {zs[len(zs)//2]:.1f}  "
          f"máx {zs[-1]:.1f}   (corte z ≥ {Z_MIN})\n")

    print(f"{'CAP':<6}{'TÍTULO':<32}{'PROM':>6}{'FACULT':>8}   propuestas")
    for cod, c in caps.items():
        n_prom = sum(1 for x in promesas if x["capitulo"] == cod)
        ids = porcap.get(cod, [])
        print(f"{cod:<6}{c['titulo'][:30]:<32}{n_prom:>6}{len(ids):>8}   {','.join(ids)}")

    print(f"\nSIN CORRELATO EN EL PLAN (z < {Z_MIN}): {len(sin_cap)} de {len(props)}")
    for p in sin_cap:
        print(f"   {p['id']:<5} [z={p['plan_z']:>4.1f}] {p['texto'][:84]}")

    print(f"\nASIGNACIONES DUDOSAS (margen < 0.10): {len(dudosas)}")
    print("   " + ", ".join(p["id"] for p in dudosas))

    tit = {m["letra"]: m["titulo"] for m in d["materias"]}
    letras, filas = matriz_agregada(caps, promesas, props, tit)
    print("\n── MATRIZ AGREGADA materia(pedido) × capítulo(plan), coseno ×100 ──")
    print(f"{'CAP':<5}{'TÍTULO':<31}" + "".join(f"{l:>5}" for l in letras) + "   MAX")
    for f in sorted(filas, key=lambda x: -x["max"]):
        print(f"{f['capitulo']:<5}{f['titulo'][:29]:<31}"
              + "".join(f"{f['sim'][l]:>5.0f}" for l in letras) + f"  {f['max']:>5.0f}")
    huerfanos = [f for f in filas if f["max"] < 15]
    print(f"\nCapítulos del plan sin contraparte clara en el pedido (max < 15):")
    for f in huerfanos:
        print(f"   [{f['max']:>4.0f}] {f['capitulo']} {f['titulo']}")

    cods = list(caps)
    rho = spearman([sum(1 for x in promesas if x["capitulo"] == c) for c in cods],
                   [len(porcap.get(c, [])) for c in cods])
    print(f"\nSpearman(promesas del plan, facultades pedidas) = {rho:+.2f}  (n={len(cods)})")

    json.dump({
        "z_min": Z_MIN,
        "spearman": round(rho, 3),
        "capitulos": [caps[c] | {"n_promesas": sum(1 for x in promesas if x["capitulo"] == c),
                                 "facultades": porcap.get(c, [])} for c in cods],
        "sin_correlato": [p["id"] for p in sin_cap],
        "dudosas": [p["id"] for p in dudosas],
        "matriz_agregada": filas, "materias_orden": letras,
        "propuestas": props,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
