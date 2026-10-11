#!/usr/bin/env python3
"""Polígonos de los distritos uninominales y de las circunscripciones, para el mapa.

Cada distrito es la unión de las celdas de sus locales (02_celdas.py, las mismas
cuya vecindad usó el trazado), así que sale contiguo. Un local partido por
mesas entre dos distritos se dibuja con el resto del local; el pedazo que pasó
al otro lado no tiene área (el reparto exacto está en asignacion.parquet).

Bordes suaves sin huecos: primero una partición plana exacta (malla), luego
`coverage_simplify` (simplifica sin abrir rendijas), luego la topología (arcos
compartidos) y cada arco se suaviza con Chaikin dejando fijos sus extremos.
Dos distritos vecinos comparten exactamente la misma línea.

Salida:
    data/distritos_us.geojson
    data/circunscripciones.geojson   (bordes regionales)

Uso:
    uv run --with geopandas --with pyarrow --with topojson python scripts/05_geo.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import topojson

AQUI = Path(__file__).resolve().parents[1]


def chaikin(arco, vueltas: int):
    p = np.asarray(arco, float)
    for _ in range(vueltas):
        if len(p) < 3:
            break
        q = 0.75 * p[:-1] + 0.25 * p[1:]
        r = 0.25 * p[:-1] + 0.75 * p[1:]
        medio = np.empty((2 * len(q), 2))
        medio[0::2], medio[1::2] = q, r
        p = np.vstack([p[:1], medio[1:-1], p[-1:]])
    return p.round(5).tolist()


def escribe_topojson(out: dict, ruta: Path, q: int = 100_000) -> None:
    """TopoJSON cuantizado y con deltas: cada borde compartido se guarda una vez."""
    import json
    arcos = out["arcs"]
    todos = np.vstack([np.asarray(x) for x in arcos])
    x0, y0 = todos.min(axis=0)
    x1, y1 = todos.max(axis=0)
    kx, ky = (x1 - x0) / (q - 1), (y1 - y0) / (q - 1)
    nuevos = []
    for arco in arcos:
        p = np.asarray(arco)
        iq = np.column_stack([np.round((p[:, 0] - x0) / kx), np.round((p[:, 1] - y0) / ky)]).astype(int)
        d = np.vstack([iq[:1], np.diff(iq, axis=0)])
        keep = np.ones(len(d), bool)
        keep[1:-1] = (d[1:-1] != 0).any(axis=1)      # puntos repetidos tras cuantizar
        iq = iq[keep]
        nuevos.append(np.vstack([iq[:1], np.diff(iq, axis=0)]).tolist())
    obj = {k: v for k, v in out["objects"].items()}
    tj = {"type": "Topology", "transform": {"scale": [kx, ky], "translate": [x0, y0]},
          "objects": obj, "arcs": nuevos}
    ruta.write_text(json.dumps(tj, separators=(",", ":")))


def malla(us: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Partición plana exacta: sin solapes ni rendijas entre distritos.

    Todos los bordes se cortan entre sí y se poligonizan; cada cara va al
    distrito que la contiene, y las caras de nadie (rendijas del recorte,
    lagos interiores) al vecino con el que comparten más borde."""
    from shapely.ops import polygonize
    lineas = shapely.union_all(shapely.boundary(us.geometry.values))
    caras = gpd.GeoDataFrame(geometry=list(polygonize(getattr(lineas, "geoms", [lineas]))), crs=us.crs)
    pts = gpd.GeoDataFrame(geometry=caras.representative_point(), crs=us.crs)
    j = gpd.sjoin(pts, us, predicate="within", how="left")
    caras["du"] = j[~j.index.duplicated()].distrito_us
    idx = caras.sindex
    for _ in range(5):                       # las rendijas pueden tocarse entre sí
        sin = caras.index[caras.du.isna()]
        if not len(sin):
            break
        for i in sin:
            cand = [k for k in idx.query(caras.geometry[i], predicate="touches")
                    if pd.notna(caras.du.iloc[k])]
            if cand:
                largo = [caras.geometry.iloc[k].intersection(caras.geometry[i]).length for k in cand]
                caras.loc[i, "du"] = caras.du.iloc[cand[int(np.argmax(largo))]]
    return caras.dropna(subset=["du"]).dissolve("du").reset_index() \
        .rename(columns={"du": "distrito_us"})[["distrito_us", "geometry"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=AQUI / "data")
    ap.add_argument("--simplifica", type=float, default=0.0015, help="grados, en la topología")
    ap.add_argument("--suaviza", type=int, default=2, help="vueltas de Chaikin")
    a = ap.parse_args()

    c = gpd.read_parquet(a.data / "celdas.parquet")
    c = c.merge(pd.read_parquet(a.data / "celda_distrito.parquet"), on="local")
    circ = pd.read_csv(a.data / "distritos_us.csv").set_index("distrito_us").circ
    us = c.dissolve("distrito_us").reset_index()[["distrito_us", "geometry"]]
    us["geometry"] = shapely.set_precision(shapely.force_2d(us.geometry.values), 1e-6)
    cov = malla(us)
    print(f"  malla válida: {shapely.coverage_is_valid(cov.geometry.values)}")
    cov["geometry"] = shapely.coverage_simplify(cov.geometry.values, a.simplifica)

    topo = topojson.Topology(cov.set_crs(4326, allow_override=True), prequantize=False)
    topo.output["arcs"] = [chaikin(arco, a.suaviza) for arco in topo.output["arcs"]]
    escribe_topojson(topo.output, a.data / "distritos_us.topojson")
    suave = topo.to_gdf().set_crs(4326, allow_override=True)
    suave["geometry"] = suave.geometry.buffer(0)
    suave["circ"] = suave.distrito_us.map(circ)
    suave["partes"] = suave.geometry.apply(lambda x: len(getattr(x, "geoms", [x])))
    todo = shapely.union_all(suave.geometry.values)
    huecos = sum(len(p.interiors) for p in getattr(todo, "geoms", [todo]))
    suave[["distrito_us", "geometry"]].to_file(a.data / "distritos_us.geojson", driver="GeoJSON",
                                               COORDINATE_PRECISION=5)
    # Contorno regional: de la misma malla, sin suavizar aparte, así calza con los distritos.
    regiones = suave.dissolve("circ").reset_index()[["circ", "geometry"]]
    regiones["geometry"] = regiones.geometry.simplify(0.001)
    regiones.to_file(a.data / "circunscripciones.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)
    print(f"  huecos entre distritos: {huecos}")
    print(f"{len(suave)} distritos ({(suave.partes > 1).sum()} en más de una pieza) · "
          f"{len(regiones)} circunscripciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
