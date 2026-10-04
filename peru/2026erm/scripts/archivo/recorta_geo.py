#!/usr/bin/env python3
"""Un geojson por carrera, con su geografía y nada más.

El archivo nacional pesa 17 MB y ninguna página lo necesita: la de un distrito
muestra ese distrito, la de una provincia sus distritos, la regional sus
provincias. Recortando por carrera cada página descarga solo lo suyo, **sin
simplificar geometrías** —que es lo que desalinea los bordes entre niveles— y
sin teselas ni servidor de mapas.

Los polígonos se copian tal cual del canónico. Un distrito aparece en varios
recortes (su provincia, su departamento) y eso duplica bytes en disco, pero el
disco es gratis y la coincidencia de bordes queda garantizada por construcción:
es literalmente la misma geometría.

Las provincias y los departamentos se **disuelven** desde los distritos con
`build_geo_nacional.disuelve`, que es una unión geométrica real (shapely). Aquí
**no se simplifica** —eso sigue siendo a propósito, para que los bordes casen
entre niveles—, solo se funden.

Dos intentos previos fallaron y conviene no repetirlos: emitir un MultiPolygon
con las piezas de los hijos deja las fronteras interiores dibujadas, y la
cancelación de aristas produce huecos falsos en cuanto los hijos se solapan, que
en esta geometría pasa. Ver el docstring de `build_geo_nacional`.

    01-XXXXXX       provincias del departamento
    01-XXXXXX-dist  distritos del departamento (para bajar de nivel en el mapa)
    03-XXXXXX       distritos de la provincia
    04-XXXXXX       el distrito solo
    02-XXXXXX       circunscripciones de consejero del departamento

El `-dist` existe porque el nivel al que se **adjudica** una carrera y el nivel
al que se **mira** el mapa no son el mismo: la de gobernador se gana en el
departamento, pero el lector quiere encontrar su distrito.

El de consejeros se emite **uno por departamento**, no uno por circunscripción:
emitir uno por circunscripción duplicaba el departamento hasta trece veces —solo
Cusco eran 15 MB de contenido idéntico—.

Uso:
    uv run python scripts/recorta_geo.py --anio 2022
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_geo_nacional import HUECO_MIN, _area, disuelve as funde  # noqa: E402
from shapely.geometry import mapping  # noqa: E402


def piezas(geom):  # noqa: D103
    t, c = geom["type"], geom["coordinates"]
    return c if t == "MultiPolygon" else [c]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anio", default="2026")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    base = RAIZ
    suf = ""
    car = pd.read_csv(base / f"data/reference/carreras{suf}.csv", dtype=str)
    g = json.load(open(RAIZ / f"data/reference/geo/distritos_{args.anio}.geojson"))

    por_dist = defaultdict(list)
    for f in g["features"]:
        por_dist[f["properties"]["ubigeo_distrito"]].append(f)

    def disuelve(ubigeo, nombre, hijos):
        geoms = [f["geometry"] for h in hijos for f in por_dist[h]]
        u = funde(geoms, ubigeo)
        gm = mapping(u)
        # Mismo filtro de huecos que en las capas nacionales: los de menos de
        # ~1 km² son residuo del solape de la fuente, no enclaves.
        polys = (gm["coordinates"] if gm["type"] == "MultiPolygon"
                 else [gm["coordinates"]])
        polys = [tuple(p[:1]) + tuple(h for h in p[1:] if _area(h) >= HUECO_MIN)
                 for p in polys]
        gm = ({"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1
              else {"type": "MultiPolygon", "coordinates": polys})
        return {"type": "Feature", "geometry": gm,
                "properties": {"ubigeo": ubigeo, "nombre": nombre}}

    dis = pd.read_csv(base / f"data/reference/distritos{suf}.csv", dtype=str)
    hijos_prov = dis.groupby(dis.ubigeo_provincia.str[:4]).ubigeo_distrito.apply(list)
    nom_prov = dict(zip(dis.ubigeo_provincia.str[:4], dis.nombre_provincia))
    nom_dist = dict(zip(dis.ubigeo_distrito, dis.nombre_distrito))
    dest = (args.out or base / "data/geo")
    dest.mkdir(parents=True, exist_ok=True)

    n, total = 0, 0
    for r in car.itertuples():
        rid, u, t = f"{r.tipo}-{r.ubigeo}", r.ubigeo, r.tipo
        if t == "02":
            continue      # se emiten aparte, uno por departamento
        if t == "01":
            # Provincias del departamento, disueltas desde sus distritos.
            fs = [disuelve(p + "00", nom_prov.get(p, ""), h)
                  for p, h in hijos_prov.items() if p[:2] == u[:2]]
        elif t == "03":
            fs = [{"type": "Feature", "geometry": f["geometry"],
                   "properties": {"ubigeo": d, "nombre": nom_dist.get(d, "")}}
                  for d in hijos_prov.get(u[:4], []) for f in por_dist[d]]
        else:
            fs = [{"type": "Feature", "geometry": f["geometry"],
                   "properties": {"ubigeo": u, "nombre": nom_dist.get(u, "")}}
                  for f in por_dist[u]]
        if not fs:
            continue
        ruta = dest / f"{rid}.geojson"
        tmp = ruta.with_suffix(".tmp")
        json.dump({"type": "FeatureCollection", "features": fs}, open(tmp, "w"),
                  separators=(",", ":"))
        tmp.replace(ruta)
        n += 1
        total += ruta.stat().st_size

    # --- capa distrital de cada departamento, para bajar de nivel en la página
    # regional, y circunscripciones de consejero, para el mapa del consejo.
    col_cons = "race_consejero" if "race_consejero" in dis.columns else None
    for dep, gd in dis.groupby(dis.ubigeo_departamento.str[:2]):
        fs = [{"type": "Feature", "geometry": f["geometry"],
               "properties": {"ubigeo": d, "nombre": nom_dist.get(d, "")}}
              for d in gd.ubigeo_distrito for f in por_dist[d]]
        if fs:
            ruta = dest / f"01-{dep}0000-dist.geojson"
            json.dump({"type": "FeatureCollection", "features": fs},
                      open(ruta, "w"), separators=(",", ":"))
            n += 1
            total += ruta.stat().st_size

        if not col_cons:
            continue
        # Una circunscripción de consejero es un grupo de distritos; en casi todo
        # el país coincide con la provincia, pero en el Callao son distritos, así
        # que se agrupa por el race_id y no por el ubigeo.
        circ = defaultdict(list)
        for r in gd.itertuples():
            rc = getattr(r, col_cons, None)
            if isinstance(rc, str) and rc:
                circ[rc[3:]].append(r.ubigeo_distrito)
        fs = []
        for u, hijos in sorted(circ.items()):
            nombre = (nom_prov.get(u[:4], "") if u.endswith("00")
                      else nom_dist.get(u, ""))
            fs.append(disuelve(u, nombre, hijos))
        if fs:
            ruta = dest / f"02-{dep}0000.geojson"
            json.dump({"type": "FeatureCollection", "features": fs},
                      open(ruta, "w"), separators=(",", ":"))
            n += 1
            total += ruta.stat().st_size

    tam = sorted(((f.stat().st_size, f.name) for f in dest.glob("*.geojson")),
                 reverse=True)
    print(f"{n:,} recortes · {total/1e6:.0f} MB en total · "
          f"mediana {sorted(s for s, _ in tam)[len(tam)//2]/1024:.0f} KB")
    print("  los cinco más pesados:")
    for s, nm in tam[:5]:
        print(f"    {nm:<18} {s/1024:>8,.0f} KB")
    print("  los cinco más livianos:")
    for s, nm in tam[-5:]:
        print(f"    {nm:<18} {s/1024:>8,.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
