#!/usr/bin/env python3
r"""Arma el JSON que consume el artículo → data/normas_web.json.

Sólo las normas nombradas en el ARTICULADO: es el texto que el Congreso vota y,
por tanto, lo único que delimita jurídicamente qué puede reescribir el Ejecutivo.
Las 185 que aparecen únicamente en la exposición de motivos son otro artículo.

Cada fila lleva el alcance —norma entera o artículo/disposición nombrada— porque
esa es la pregunta del artículo: qué podría técnicamente modificar el gobierno.

Run: python3 scripts/build_web_normas.py   (después de build_normas.py)
"""
from __future__ import annotations

import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
NORMAS = os.path.join(ROOT, "data", "normas.json")
PROPS = os.path.join(ROOT, "data", "propuestas.json")
OUT = os.path.join(ROOT, "data", "normas_web.json")

ORDEN_TIPO = {"Ley": 0, "Decreto Legislativo": 1, "Decreto Ley": 2, "Decreto de Urgencia": 3}


def main():
    nd = json.load(open(NORMAS, encoding="utf-8"))
    pd = json.load(open(PROPS, encoding="utf-8"))
    props = {p["id"]: p for p in pd["propuestas"]}
    mats = {m["letra"]: m["titulo"] for m in pd["materias"]}

    filas = []
    for n in nd["normas"]:
        if n["solo_en_motivos"]:
            continue
        filas.append({
            "tipo": n["tipo"],
            "numero": n["numero"],
            "nombre": n["nombre"],
            "nombre_externo": n.get("nombre_externo", False),
            "alcance": n.get("alcance"),
            "partes": n.get("partes", []),
            "propuestas": n["en_articulado"],
            "materias": sorted({p[0] for p in n["en_articulado"]}),
        })
    filas.sort(key=lambda f: (f["propuestas"][0][0], ORDEN_TIPO.get(f["tipo"], 9),
                              f["numero"].zfill(9)))

    usadas = sorted({p for f in filas for p in f["propuestas"]},
                    key=lambda i: (i[0], int(i[1:])))
    doc = {
        "generado": pd.get("fecha_presentacion"),
        "proyecto": pd["proyecto"],
        "resumen": {
            "n_normas": len(filas),
            "n_completa": sum(1 for f in filas if f["alcance"] == "completa"),
            "n_parcial": sum(1 for f in filas if f["alcance"] == "parcial"),
            "n_propuestas_total": len(pd["propuestas"]),
            "n_propuestas_con_norma": len(usadas),
            "por_tipo": dict(Counter(f["tipo"] for f in filas)),
        },
        "materias": [{"letra": k, "titulo": v} for k, v in mats.items()],
        "propuestas": {i: {"texto": props[i]["texto"], "materia": props[i]["materia"]}
                       for i in usadas},
        "normas": filas,
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    r = doc["resumen"]
    print(f"{r['n_normas']} normas · {r['n_completa']} enteras / {r['n_parcial']} acotadas · "
          f"invocadas por {r['n_propuestas_con_norma']} de {r['n_propuestas_total']} propuestas")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
