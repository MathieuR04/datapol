#!/usr/bin/env python3
"""Celdas del mapa: una por local de votación, y su grafo de vecindad.

Cada distrito administrativo se reparte entre sus locales (por ubigeo del
padrón; un local geocodificado fuera de su distrito se mete en él) con celdas
de Voronoi recortadas al polígono. Un polígono
sin locales se pega a la celda vecina más cercana. La vecindad es la del mapa
—dos celdas son vecinas si comparten borde—, así que un distrito armado
uniendo celdas vecinas es contiguo en el mapa.

Salida:
    data/celdas.parquet   local, ubigeo_poligono, geometry (WKB)
    data/vecinos.parquet  local_a, local_b

Uso:
    uv run --with geopandas --with scipy --with pyarrow python scripts/02_celdas.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import Voronoi
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]


def voronoi_celdas(pts: np.ndarray, marco) -> list:
    if len(pts) == 1:
        return [marco]
    minx, miny, maxx, maxy = marco.bounds
    r = max(maxx - minx, maxy - miny) * 10 + 1
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    lejos = np.array([[cx - r, cy - r], [cx - r, cy + r], [cx + r, cy - r], [cx + r, cy + r]])
    p = pts + np.random.default_rng(0).normal(0, 1e-7, pts.shape)
    vor = Voronoi(np.vstack([p, lejos]))
    out = []
    for i in range(len(pts)):
        reg = vor.regions[vor.point_region[i]]
        poly = Polygon(vor.vertices[reg]).buffer(0) if reg and -1 not in reg \
            else Point(pts[i]).buffer(1e-6)
        out.append(poly.intersection(marco))
    return out


def _pega(c: gpd.GeoDataFrame, piezas) -> int:
    """Pega cada pieza a la celda con la que comparte más borde."""
    idx = c.sindex
    col = c.columns.get_loc("geometry")
    n = 0
    for p in sorted(piezas, key=lambda p: -p.area):
        cand = idx.query(p.buffer(1e-6), predicate="intersects")
        if len(cand):
            borde = [c.geometry.iloc[i].buffer(1e-6).intersection(p.buffer(1e-6)).area for i in cand]
            k = cand[int(np.argmax(borde))]
        else:
            k = int(np.argmin(c.geometry.distance(p).to_numpy()))
        c.iat[k, col] = unary_union([c.geometry.iloc[k], p]).buffer(0)
        n += 1
    return n


def rellena(c: gpd.GeoDataFrame, g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Lo que de un distrito quedó sin celda (huecos del recorte) va a la vecina."""
    c = c.copy()
    huecos = []
    for _, fila in g.iterrows():
        mias = c[c.ubigeo_poligono == fila.ubigeo_distrito]
        falta = fila.geometry.difference(mias.union_all()) if len(mias) else fila.geometry
        huecos += [p for p in getattr(falta, "geoms", [falta])
                   if p.geom_type == "Polygon" and p.area > 1e-10]
    n = _pega(c, huecos)
    print(f"  {n} huecos rellenados")
    return c


def una_pieza(c: gpd.GeoDataFrame, punto: gpd.GeoSeries) -> gpd.GeoDataFrame:
    """Cada celda se queda con la pieza que contiene a su local.

    Recortar un Voronoi contra un distrito de forma irregular puede dejar la
    celda en dos pedazos; el pedazo lejano haría creer que dos celdas son
    vecinas cuando no lo son. Los pedazos sueltos se pegan a la celda con la
    que comparten más borde (o a la más cercana, si es una isla)."""
    sueltos = []
    geoms = []
    for lc, g in zip(c.local, c.geometry):
        partes = list(getattr(g, "geoms", [g]))
        if len(partes) == 1:
            geoms.append(g)
            continue
        partes = [p for p in partes if p.geom_type == "Polygon" and not p.is_empty]
        if not partes:
            geoms.append(g)
            continue
        pt = punto[lc]
        k = min(range(len(partes)), key=lambda i: partes[i].distance(pt))
        geoms.append(partes[k])
        sueltos += [p for i, p in enumerate(partes) if i != k and p.area > 0]
    c = c.copy()
    c["geometry"] = geoms
    _pega(c, sueltos)
    print(f"  {len(sueltos)} pedazos sueltos de celda reasignados")
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", type=Path,
                    default=DATAPOL / "peru/2026eg/metadata/peru_2026_distrito.geojson")
    ap.add_argument("--data", type=Path, default=AQUI / "data")
    a = ap.parse_args()

    g = gpd.read_file(a.geo)[["ubigeo_distrito", "geometry"]]
    g["geometry"] = g.geometry.buffer(0)
    g = g.dissolve("ubigeo_distrito").reset_index()      # algún ubigeo viene en dos piezas
    m = pd.read_parquet(a.data / "mesas.parquet")
    m = m[~m.exterior]
    # El ubigeo del local es el de la mayoría de sus electores (un mismo código
    # de local puede atender mesas de dos distritos).
    ub = (m.groupby(["local", "ubigeo"]).electores.sum().reset_index()
          .sort_values("electores").drop_duplicates("local", keep="last").set_index("local").ubigeo)
    loc = m.groupby("local").agg(lon=("lon", "first"), lat=("lat", "first")).reset_index()
    loc["ubigeo"] = loc.local.map(ub)
    pts = gpd.GeoDataFrame(loc, geometry=gpd.points_from_xy(loc.lon, loc.lat), crs=g.crs)
    # Polígono = el de su ubigeo (la geocodificación falla más que el padrón). Los
    # distritos nuevos sin polígono propio van al polígono de su provincia que
    # contiene el punto, o al más cercano de su provincia.
    con_poli = pts.ubigeo.isin(g.ubigeo_distrito)
    pts["ubigeo_distrito"] = pts.ubigeo.where(con_poli)
    for k in pts.index[~con_poli]:
        prov = g[g.ubigeo_distrito.str[:4] == pts.at[k, "ubigeo"][:4]]
        d = prov.geometry.distance(pts.at[k, "geometry"])
        pts.at[k, "ubigeo_distrito"] = prov.loc[d.idxmin(), "ubigeo_distrito"]
    poli = g.set_index("ubigeo_distrito").geometry
    # Un punto fuera de su polígono se mete adentro, al punto más cercano.
    from shapely.ops import nearest_points
    fuera = 0
    for k in pts.index:
        P = poli[pts.at[k, "ubigeo_distrito"]]
        if not P.contains(pts.at[k, "geometry"]):
            fuera += 1
            q = nearest_points(P.buffer(-0.0005) if not P.buffer(-0.0005).is_empty else P,
                               pts.at[k, "geometry"])[0]
            pts.at[k, "geometry"] = q
            pts.at[k, "lon"], pts.at[k, "lat"] = q.x, q.y
    j = pts

    filas, vacios = [], []
    for _, fila in g.iterrows():
        dentro = j[j.ubigeo_distrito == fila.ubigeo_distrito]
        if dentro.empty:
            vacios.append(fila)
            continue
        P = np.column_stack([dentro.lon, dentro.lat])
        for lc, celda in zip(dentro.local, voronoi_celdas(P, fila.geometry)):
            filas.append((lc, fila.ubigeo_distrito, celda))
    c = gpd.GeoDataFrame(filas, columns=["local", "ubigeo_poligono", "geometry"], crs=g.crs)

    # Polígonos sin locales: a la celda vecina más cercana.
    for fila in vacios:
        geom = fila.geometry
        toca = c[c.intersects(geom.buffer(1e-6))]
        if toca.empty:
            toca = c
        k = toca.geometry.distance(geom.representative_point()).idxmin()
        c.at[k, "geometry"] = unary_union([c.at[k, "geometry"], geom]).buffer(0)
    c = c.dissolve("local", aggfunc="first").reset_index()   # un local, una celda
    c = una_pieza(c, j.set_index("local").geometry)
    c = rellena(c, g)

    # Vecindad: comparten borde (no solo un punto).
    idx = c.sindex
    a_, b_ = idx.query(c.geometry.buffer(1e-7), predicate="intersects")
    sel = a_ < b_
    a_, b_ = a_[sel], b_[sel]
    largo = np.array([c.geometry.iloc[i].buffer(1e-7).intersection(c.geometry.iloc[k].buffer(1e-7)).area
                      for i, k in zip(a_, b_)])
    ok = largo > 1e-12
    vec = pd.DataFrame({"local_a": c.local.to_numpy()[a_[ok]], "local_b": c.local.to_numpy()[b_[ok]]})
    c.to_parquet(a.data / "celdas.parquet", index=False)
    vec.to_parquet(a.data / "vecinos.parquet", index=False)
    print(f"{len(c):,} celdas · {len(vec):,} vecindades · {len(vacios)} polígonos sin locales · "
          f"{fuera} locales reubicados dentro del polígono de su ubigeo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
