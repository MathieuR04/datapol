#!/usr/bin/env python3
"""Datos de la página: web/data.json (ganadores, simulación, colores) y
web/circunscripciones.geojson (26 circunscripciones del territorio, livianas).

Uso:
    uv run --with geopandas --with pandas python scripts/03_web.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]
PARTIDOS = {
    "FP": ("Fuerza Popular", "#EA580C"), "PL": ("Perú Libre", "#B91C1C"),
    "JP": ("Juntos por el Perú", "#15803D"), "FA": ("Frente Amplio", "#84CC16"),
    "RP": ("Renovación Popular", "#0EA5E9"), "APP": ("Alianza para el Progreso", "#1E3A8A"),
    "PPK": ("Peruanos por el Kambio", "#DB2777"), "AP": ("Acción Popular", "#F87171"),
    "DD": ("Democracia Directa", "#78350F"), "PBG": ("Partido del Buen Gobierno", "#FACC15"),
    "PCO": ("Partido Cívico Obras", "#0D9488"),
}
ORDEN = ["PL", "FA", "JP", "DD", "PBG", "PCO", "PPK", "AP", "APP", "RP", "FP"]   # izq → der


def bonito(x: str) -> str:
    menores = {"de", "del", "la", "las", "los", "el", "en"}
    return " ".join(w if i and w in menores else w.capitalize()
                    for i, w in enumerate(x.lower().split()))


def main() -> int:
    g = pd.read_csv(AQUI / "data/ganadores.csv")
    sim = json.loads((AQUI / "data/simulacion.json").read_text())
    circs = {}
    for c, d in g.groupby("circ"):
        nombre = "Peruanos en el Extranjero" if c.startswith("PERUANOS") else bonito(c)
        nombre = nombre.replace("Junin", "Junín").replace("Huanuco", "Huánuco").replace(
            "Apurimac", "Apurímac").replace("San Martin", "San Martín").replace("Ancash", "Áncash")
        circs[c] = {"nombre": nombre, "anios": {
            str(r.anio): {"g": r.ganador, "p": None if pd.isna(r.pct) else r.pct,
                          "s": None if pd.isna(r.segundo) else r.segundo,
                          "p2": None if pd.isna(r.pct2) else r.pct2}
            for r in d.itertuples()}}
    out = {"circs": circs, "sim": sim, "orden": ORDEN,
           "partidos": {k: {"nombre": n, "color": c} for k, (n, c) in PARTIDOS.items()}}
    (AQUI / "web").mkdir(exist_ok=True)
    (AQUI / "web/data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

    d = gpd.read_file(DATAPOL / "peru/2026eg/metadata/peru_2026_distrito.geojson")
    u = d.ubigeo_distrito
    d["circ"] = np.where(u.str[:4] == "1401", "LIMA METROPOLITANA",
                np.where(u.str[:2] == "14", "LIMA PROVINCIAS",
                         d.nombre_dept.str.upper().map(
                             lambda s: __import__("unicodedata").normalize("NFKD", s)
                             .encode("ascii", "ignore").decode())))
    r = d[["circ", "geometry"]].dissolve("circ").reset_index()
    r["geometry"] = r.geometry.buffer(0.002).buffer(-0.002).simplify(0.012)
    faltan = set(circs) - set(r.circ) - {"PERUANOS EN EL EXTRANJERO"}
    assert not faltan, faltan
    r.to_file(AQUI / "web/circunscripciones.geojson", driver="GeoJSON", COORDINATE_PRECISION=3)
    print(f"→ web/data.json · web/circunscripciones.geojson ({len(r)} circunscripciones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
