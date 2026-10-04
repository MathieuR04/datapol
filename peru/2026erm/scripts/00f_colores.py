#!/usr/bin/env python3
"""Un color estable por organización política → `data/reference/colores_2022.csv`.

POR QUÉ UNO POR ORGANIZACIÓN Y NO «LAS TRES PRIMERAS + OTRAS»
-------------------------------------------------------------
Con tres colores el mapa se lee, pero la leyenda miente por omisión: 125 de las
128 organizaciones caen en un gris indistinto. Con un color por organización la
leyenda del mapa se vuelve inmanejable —nadie lee 128 entradas—, así que el
reparto es otro: **el mapa no lleva leyenda de partidos** y el color se explica
donde está el nombre, con una burbuja al costado de cada organización en las
tablas. La leyenda del mapa queda solo para los estados (en disputa, segunda
vuelta, no elige esta autoridad).

CÓMO SE ASIGNA
--------------
Por **orden alfabético del nombre**, no por tamaño: el color tiene que seguir a
la organización, no a su posición en la tabla. Si siguiera al ranking, cada vez
que una lista adelantara a otra durante la noche se repintarían las dos, y el
lector entendería que cambió algo que no cambió.

Los tonos salen de una vuelta por la rueda de color con paso áureo (137.508°),
que es lo que maximiza la separación entre índices contiguos, y la claridad
alterna en tres bandas para que dos tonos cercanos se distingan igual. Se emiten
dos versiones, una para fondo claro y otra para fondo oscuro.

HECHO A MANO
------------
`MANUAL` fija el color de las organizaciones con identidad cromática conocida.
Todo lo que esté ahí gana sobre el reparto automático. Está pensado para
completarse a mano: es una tabla de referencia versionada, no un derivado.

Uso:
    uv run python scripts/00f_colores.py --anio 2022
"""

from __future__ import annotations

import argparse
import colorsys
import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Color propio por organización. El valor es (hex, confianza).
#
#   "conocido"    — identidad cromática con la que la organización se presenta y
#                   con la que la prensa peruana la identifica.
#   "provisional" — tono asignado para que se distinga, **no** verificado contra
#                   la identidad real. Hay que revisarlo antes de publicar: el
#                   color de un partido se lee como identidad, y equivocado
#                   desinforma igual que un dato mal puesto.
#
# Los movimientos regionales no están aquí: son 115 y ninguno tiene identidad
# cromática de conocimiento general. Van por la rueda, y quien quiera los colores
# reales tiene `--logos`.
MANUAL: dict[str, tuple[str, str]] = {
    "ACCION POPULAR":                        ("#d8322b", "conocido"),
    "PARTIDO DEMOCRATICO SOMOS PERU":        ("#2a6fd4", "conocido"),
    "RENOVACION POPULAR":                    ("#4fc1ec", "conocido"),
    "FUERZA POPULAR":                        ("#f2831f", "conocido"),
    "PARTIDO POLITICO NACIONAL PERU LIBRE":  ("#a5121a", "conocido"),
    "PARTIDO MORADO":                        ("#6a3fa0", "conocido"),
    "PODEMOS PERU":                          ("#16b0a3", "conocido"),
    # Revisar: asignados para que se distingan, no verificados.
    "ALIANZA PARA EL PROGRESO":              ("#1b3c73", "provisional"),
    "AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL": ("#0f7b4f", "provisional"),
    "JUNTOS POR EL PERU":                    ("#c0357a", "provisional"),
    "PARTIDO FRENTE DE LA ESPERANZA 2021":   ("#e8b21c", "provisional"),
    "PARTIDO PATRIOTICO DEL PERU":           ("#6e5a3e", "provisional"),
}


# ERM 2026. Va por **grupo** (partido ancla + sus alianzas, de
# `organizaciones_erm2026.csv`): «APP - LA CHOLITA» se pinta como APP. Cada
# entrada trae su versión para fondo oscuro, porque aclarar no siempre separa:
# APP y Podemos aclarados quedaban a ΔE 7 en oscuro. Paleta revisada con
# CIEDE2000: todo par de esta tabla queda a ΔE ≥ 13 en claro y ≥ 12 en oscuro.
# El nombre es el del ancla del grupo.
MANUAL_2026: dict[str, tuple[str, str, str]] = {
    "ALIANZA PARA EL PROGRESO":              ("#1f5fd1", "#4f8cff", "conocido"),
    "PARTIDO DEMOCRATICO SOMOS PERU":        ("#0f9b8e", "#3fc9bb", "operador"),
    "PARTIDO POLITICO PERU PRIMERO":         ("#d7261e", "#f0675f", "conocido"),
    "PODEMOS PERU":                          ("#1b2a6b", "#a3acdb", "conocido"),
    "AHORA NACION - AN":                     ("#f08a8f", "#f7b0b4", "conocido"),
    "ACCION POPULAR":                        ("#8c1d2c", "#c2405a", "conocido"),
    "RENOVACION POPULAR PERU":               ("#4fc1ec", "#80d4f3", "conocido"),
    "PROGRESEMOS":                           ("#d4c400", "#ede04a", "logo"),
    "PARTIDO PAIS PARA TODOS":               ("#b8860b", "#e0ab2e", "conocido"),
    "FUERZA POPULAR":                        ("#f2831f", "#ff8f2a", "conocido"),
    "JUNTOS POR EL PERU":                    ("#8fd16a", "#a8de8a", "conocido"),
    "AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL": ("#d6249f", "#ea6cc4", "conocido"),
    "PARTIDO MORADO":                        ("#6a3fa0", "#9b74d0", "conocido"),
    "PARTIDO POLITICO NACIONAL PERU LIBRE":  ("#4a0b10", "#7a3b2a", "conocido"),
    "PARTIDO FRENTE DE LA ESPERANZA 2021":   ("#6b8e23", "#a3a83a", "logo"),
    "PARTIDO POPULAR CRISTIANO - PPC":       ("#1e7b3c", "#2a8a49", "conocido"),
    "PARTIDO DEMOCRATA VERDE":               ("#0aa150", "#2fd07a", "logo"),
}
# El resto va por la rueda, **apagado**: con 17 identidades saturadas, una rueda
# a saturación plena les disputa el ojo a los partidos que sí se nombran.
BANDAS_CLARO_2026 = [(0.30, 0.45), (0.24, 0.56), (0.34, 0.38)]
BANDAS_OSCURO_2026 = [(0.28, 0.60), (0.22, 0.70), (0.32, 0.52)]


def aclara(hexa: str, k: float) -> str:
    """Mismo tono, más claro. Para la versión de fondo oscuro."""
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(1, l + k), s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

PASO = 137.508          # ángulo áureo: separa al máximo los índices contiguos
BANDAS_CLARO = [(0.62, 0.42), (0.48, 0.55), (0.72, 0.34)]   # (sat, luz)
BANDAS_OSCURO = [(0.58, 0.58), (0.46, 0.68), (0.66, 0.50)]


def hexde(h, s, l) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anio", default="2026")
    p.add_argument("--crosswalk", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--publico", type=Path, default=None,
                   help="destino del colores.json del contrato")
    p.add_argument("--grupos", type=Path,
                   default=RAIZ.parents[1] / "articulos/erm-2026-candidatos/data/organizaciones_erm2026.csv",
                   help="organizaciones_erm2026.csv (organizacion_id → grupo_id). "
                        "Con él, cada alianza hereda el color de su ancla")
    a = p.parse_args()

    cw = a.crosswalk or RAIZ / f"data/reference/crosswalk_organizaciones_{a.anio}.csv"
    if not cw.exists():
        # Hasta que la ONPE publique, el crosswalk es el provisional (ids JNE).
        cw = RAIZ / "data/reference/crosswalk_organizaciones_provisional.csv"
    filas = list(csv.DictReader(open(cw, encoding="utf-8")))
    orgs = sorted({(f["codigo_onpe"], f["nombre_onpe"], f["tipo_organizacion"])
                   for f in filas}, key=lambda z: z[1])
    print(f"organizaciones: {len(orgs)}")

    # Grupo: organizacion_id → (grupo_id, nombre del ancla, ¿algún partido?).
    # `nacional` pasa a ser del grupo: una alianza de un partido nacional va en
    # el mapa con el color del partido, no con el ocre de los regionales. Es
    # nacional si **algún** miembro es partido: el ancla de Renovación Popular
    # + aliados es una alianza, pero el grupo incluye al PERU, que es partido.
    grupo = {}
    if a.grupos:
        g = list(csv.DictReader(open(a.grupos, encoding="utf-8")))
        ancla = {f["grupo_id"]: f["organizacion"] for f in g
                 if f["es_ancla"] == "True"}
        con_partido = {f["grupo_id"] for f in g
                       if f["tipo_organizacion"] == "PARTIDOS POLITICOS"}
        grupo = {f["organizacion_id"]: (f["grupo_id"], ancla.get(f["grupo_id"]),
                                        f["grupo_id"] in con_partido)
                 for f in g}
    manual = MANUAL_2026 if a.anio == "2026" else \
        {k: (v[0], aclara(v[0], .12), v[1]) for k, v in MANUAL.items()}
    bc, bo = (BANDAS_CLARO_2026, BANDAS_OSCURO_2026) if a.anio == "2026" \
        else (BANDAS_CLARO, BANDAS_OSCURO)

    salida = []
    for i, (cod, nombre, tipo) in enumerate(orgs):
        gid, ancla_nom, nac = grupo.get(cod.removeprefix("jne-"),
                                        (None, None, None))
        clave = ancla_nom or nombre
        if clave in manual:
            claro, oscuro, metodo = manual[clave]
            if ancla_nom and ancla_nom != nombre:
                metodo = f"grupo:{gid}"
        else:
            h = i * PASO
            sc, lc = bc[i % 3]
            so, lo = bo[i % 3]
            claro, oscuro, metodo = hexde(h, sc, lc), hexde(h, so, lo), "rueda"
        salida.append({"codigo_onpe": cod, "nombre": nombre,
                       "tipo_organizacion": tipo,
                       "nacional": int(nac if nac is not None
                                       else tipo == "PARTIDOS POLITICOS"),
                       "color_claro": claro, "color_oscuro": oscuro,
                       "metodo": metodo})

    dest = a.out or RAIZ \
        / f"data/reference/colores_{a.anio}.csv"
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(salida[0]))
        w.writeheader()
        w.writerows(salida)

    # OJO: esto se escapaba de `--out` y escribía siempre en el bloque 2022.
    # Generar los colores de 2026 pisaba en silencio los de 2022, que es el
    # proceso ya publicado. El destino sigue al año, como todo lo demás.
    base_anio = RAIZ
    pub = a.publico or base_anio / "data/colores.json"
    pub.parent.mkdir(parents=True, exist_ok=True)
    with open(pub, "w") as fh:
        # El tercer valor dice si es partido nacional. El mapa del resumen lo
        # usa para pintar de un solo ocre a los movimientos regionales: a escala
        # de país, 115 colores regionales son ruido, no información.
        json.dump({r["codigo_onpe"]: [r["color_claro"], r["color_oscuro"],
                                      r["nacional"]]
                   for r in salida}, fh, separators=(",", ":"))

    from collections import Counter
    c = Counter(r["metodo"] for r in salida)
    print(f"  {dest.name}: {len(salida)} filas · " +
          " · ".join(f"{v} {k}" for k, v in c.most_common()))
    prov = [r["nombre"] for r in salida if r["metodo"] == "provisional"]
    if prov:
        print("  POR REVISAR (color asignado, no verificado):")
        for x in prov:
            print(f"    - {x}")
    print(f"  {pub}: {pub.stat().st_size/1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
