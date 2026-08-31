#!/usr/bin/env python3
r"""Análisis del articulado: amplitud de cada pedido, normas y entidades.

Lee data/propuestas.json y escribe data/analisis.json.

LA MÉTRICA CENTRAL ES LA AMPLITUD, NO EL VOLUMEN. Cuánto se escribió para
justificar una propuesta no mide prioridad — una medida tributaria exige más
sustentación técnica que una penal por técnica legislativa, no por interés del
gobierno. Lo que sí mide poder es cuán acotado está el pedido, y eso se lee del
propio texto delegante con criterios auditables:

  ACOTADA  cita normas Y artículos concretos  → el Ejecutivo puede tocar eso y nada más
  MEDIA    cita normas, sin artículos         → puede reescribir esas normas enteras
  ABIERTA  no cita ninguna norma              → "legislar en materia de X": cheque abierto

La distinción importa porque el Congreso vota una lista de 66 líneas como si sus
elementos fueran comparables, y no lo son: `Modificar el artículo 6 de la Ley
N.° 28587` y `Legislar en materia de promoción del empleo` ocupan un renglón cada
uno y entregan cantidades de poder incomparables.

Run: python3 scripts/analiza_propuestas.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "data", "propuestas.json")
OUT = os.path.join(ROOT, "data", "analisis.json")

ART_RE = re.compile(r"art[ií]culos?\s+([0-9]+)", re.IGNORECASE)

# Entidades detectadas en un pase previo sobre el texto (siglas + nombre largo).
# Se busca cualquiera de las variantes; se cuenta PRESENCIA por propuesta, nunca
# repeticiones — repetir una sigla mide redacción, no poder.
ENTIDADES = {
    "SUNAT": [r"\bSUNAT\b", r"Superintendencia Nacional de Aduanas"],
    "SUNAFIL": [r"\bSUNAFIL\b", r"Superintendencia Nacional de Fiscalización Laboral"],
    "INPE": [r"\bINPE\b", r"Instituto Nacional Penitenciario"],
    "PNP": [r"\bPNP\b", r"Policía Nacional"],
    "Fuerzas Armadas": [r"Fuerzas Armadas"],
    "MIGRACIONES": [r"\bMIGRACIONES\b", r"Superintendencia Nacional de Migraciones"],
    "INDECI": [r"\bINDECI\b", r"Instituto Nacional de Defensa Civil"],
    "INDECOPI": [r"\bINDECOPI\b"],
    "SBS": [r"\bSBS\b", r"Superintendencia de Banca"],
    "SERVIR": [r"\bSERVIR\b", r"Autoridad Nacional del Servicio Civil"],
    "PRODUCE": [r"\bPRODUCE\b", r"Ministerio de la Producción"],
    "MIDAGRI": [r"\bMIDAGRI\b", r"Ministerio de Desarrollo Agrario"],
    "MINCETUR": [r"\bMINCETUR\b"],
    "PCM": [r"\bPCM\b", r"Presidencia del Consejo de Ministros"],
    "DINI": [r"\bDINI\b", r"Dirección Nacional de Inteligencia"],
    "SEDAPAL": [r"\bSEDAPAL\b"],
    "Gobiernos regionales": [r"[Gg]obiernos [Rr]egionales"],
    "Gobiernos locales": [r"[Gg]obiernos [Ll]ocales", r"municipal(?:es|idad)"],
    "Contraloría": [r"Contralor[ií]a"],
    "Poder Judicial": [r"Poder Judicial"],
    "Ministerio Público": [r"Ministerio P[úu]blico"],
}


def clasifica(p: dict) -> tuple[str, int]:
    arts = len(set(ART_RE.findall(p["texto"])))
    if not p["normas_citadas"]:
        return "abierta", arts
    return ("acotada" if arts else "media"), arts


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    props = d["propuestas"]
    mats = {m["letra"]: m for m in d["materias"]}

    for p in props:
        amp, arts = clasifica(p)
        p["amplitud"] = amp
        p["n_articulos_citados"] = arts
        p["entidades"] = sorted(
            e for e, pats in ENTIDADES.items()
            if any(re.search(pat, p["texto"]) for pat in pats)
        )

    # ── amplitud global y por materia ──
    glob = Counter(p["amplitud"] for p in props)
    por_mat = defaultdict(Counter)
    for p in props:
        por_mat[p["materia"]][p["amplitud"]] += 1

    print(f"{'':4}{'MATERIA':<52}{'TOT':>5}{'ABIER':>7}{'MEDIA':>7}{'ACOT':>6}{'%ABIER':>8}")
    for letra in sorted(mats):
        c = por_mat[letra]
        t = sum(c.values())
        print(f"  {letra}. {mats[letra]['titulo'][:48]:<50}{t:>5}"
              f"{c['abierta']:>7}{c['media']:>7}{c['acotada']:>6}{c['abierta']/t*100:>7.0f}%")
    t = len(props)
    print(f"  {'TOTAL':<52}{t:>5}{glob['abierta']:>7}{glob['media']:>7}"
          f"{glob['acotada']:>6}{glob['abierta']/t*100:>7.0f}%")

    # ── normas por tipo ──
    normas = Counter()
    for p in props:
        for n in p["normas_citadas"]:
            normas[(n["tipo"], n["numero"])] += 1
    tipos = Counter(t for t, _ in normas)
    print(f"\nNormas distintas citadas: {len(normas)}")
    for tipo, c in tipos.most_common():
        print(f"  {c:>3}  {tipo}")

    # ── entidades ──
    ent = Counter(e for p in props for e in p["entidades"])
    print(f"\nEntidades nombradas en el articulado (propuestas en que aparecen):")
    for e, c in ent.most_common():
        print(f"  {c:>3}  {e}")

    # ── verbos rectores ──
    verbos = Counter(p["verbo_rector"] for p in props)
    print(f"\nVerbo rector:")
    for v, c in verbos.most_common():
        print(f"  {c:>3}  {v}")

    json.dump({
        "proyecto": d["proyecto"],
        "resumen": {
            "n_propuestas": t,
            "amplitud": dict(glob),
            "n_normas_distintas": len(normas),
            "normas_por_tipo": dict(tipos),
        },
        "amplitud_por_materia": {k: dict(v) for k, v in por_mat.items()},
        "entidades": dict(ent),
        "verbos": dict(verbos),
        "normas": [{"tipo": tp, "numero": nu, "n_propuestas": c}
                   for (tp, nu), c in normas.most_common()],
        "materias": d["materias"],
        "propuestas": props,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
