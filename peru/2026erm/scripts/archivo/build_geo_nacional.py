#!/usr/bin/env python3
"""Tres mapas nacionales para la página de resumen.

    geo/nacional-01.geojson   25 departamentos   (carreras de gobernador)
    geo/nacional-03.geojson  196 provincias      (alcaldías provinciales)
    geo/nacional-04.geojson  1,891 distritos     (alcaldías distritales)

y de paso reescribe `data/reference/geo/centroides_{anio}.json`, que es de donde
salen las posiciones de las burbujas de escaños sobre el mapa del consejo.
**Son `representative_point`, no centroides.** El centroide de una forma cóncava
cae fuera de ella: en el archivo anterior las burbujas de varias provincias
quedaban flotando sobre el vecino, y ocho provincias ni siquiera figuraban.

POR QUÉ NO SE REUSA `recorta_geo.py`
------------------------------------
Ese script recorta **sin simplificar**, a propósito: los bordes entre niveles
tienen que coincidir al pixel cuando haces zoom a una provincia. Aquí es al
revés. El canónico pesa 16.3 MB y esta es la página que la spec manda optimizar
primero, con un presupuesto de 2 segundos en 3G. Un mapa nacional de 1,891
distritos se ve a ~900 px de ancho: guardar vértices separados por menos de un
pixel es pagar bytes por nada.

LA DISOLUCIÓN ES UNA UNIÓN GEOMÉTRICA DE VERDAD
-----------------------------------------------
Agrupar las piezas de los hijos en un MultiPolygon no sirve: el trazo de un
`<path>` recorre todos sus subtrazos, así que el mapa de gobernador salía con las
fronteras distritales dibujadas dentro de cada departamento.

**Una primera versión lo resolvió por cancelación de aristas** —una arista
compartida por dos distritos aparece dos veces y se descarta; las que aparecen
una sola vez son el borde— y produjo mapas mal. La Convención (Cusco) salía con
cinco huecos blancos, uno de ~3,000 km².

El método asume que los hijos **teselan** el padre: sin solapes ni vacíos. La
geometría canónica no cumple eso. En La Convención la suma de las áreas de sus 18
distritos es 2.9421 grados² y la de su unión real 2.6486: **se solapan un 10%**.
Con solapes hay aristas interiores que no encuentran pareja, sobreviven como si
fueran borde, y se cosen en anillos espurios que se pintan como huecos.

Y la validación que se había hecho no podía detectarlo: comprobaba que ninguna
arista apareciera más de dos veces, y un solape no viola eso.

Así que se usa `shapely.unary_union`, que resuelve solapes y vacíos, devuelve los
huecos reales como anillos interiores, y de paso simplifica preservando la
topología. Es una dependencia nueva y vale la pena: la alternativa es reimplementar
un motor de geometría, que es exactamente lo que acaba de fallar.

CÓMO SE ADELGAZA, en orden de cuánto ahorra
-------------------------------------------
1. **Redondeo de coordenadas** a `--decimales` (5 por defecto, ~1 m). Ahorra
   mucho sobre los 12 decimales del canónico y no se nota a ningún zoom.
2. **Simplificación preservando topología** (`shapely.simplify`), con tolerancia
   en grados. La tolerancia sube para las capas más agregadas, que se ven más
   chicas.
3. **Descarte de piezas diminutas** bajo `area_min`, y de **huecos** diminutos
   bajo `HUECO_MIN`. Las piezas son islotes que a escala nacional no ocupan ni un
   pixel. Los huecos son otra cosa: residuo del solape entre distritos de la
   fuente. Sin filtrarlos, las capas nacionales salen con 1,545 motas blancas de
   menos de 1 km² cada una, que se leen como errores de datos. Los diez huecos
   grandes que quedan sí son enclaves y se conservan.

Los ubigeos se emiten **canónicos de 6 dígitos** en las tres capas, que es como
se llavea `por_carrera` en `nacional.json`.

QUIÉN NO PARTICIPA
------------------
No todo el territorio vota en todas las carreras, y pintarlo como «sin datos»
miente: dice «todavía no sabemos» donde lo correcto es «aquí no se elige».

- **Gobernador.** Lima Metropolitana no elige autoridad regional: sus funciones
  las ejerce la alcaldía de Lima. Así que la provincia de Lima **no forma parte**
  de la carrera del Gobierno Regional de Lima y sale como pieza aparte, marcada.
- **Alcaldía distrital.** Los 196 cercados —capitales de provincia, Iquitos entre
  ellas— los gobierna directamente la municipalidad provincial.
- **Alcaldía provincial.** Aquí no hay excepción: vota el país entero.

Sale como `"no_participa": true` en las propiedades del feature, y el frontend lo
dibuja con trama en vez de color. No se deduce del ubigeo: se lee de
`data/reference/distritos_{anio}.csv`, que es donde vive esa verdad.

Uso:
    uv run python scripts/build_geo_nacional.py --anio 2022
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import topojson as tp
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely import force_2d

RAIZ = Path(__file__).resolve().parents[2]

# Tolerancia de simplificación y área mínima por capa, en grados. Las capas más
# agregadas se dibujan más chicas, así que aguantan más tolerancia.
# El mapa **hace zoom**, así que la tolerancia no se calcula contra el ancho
# inicial sino contra el detalle que se verá al acercarse. Una primera versión la
# puso en torno a medio pixel de la vista completa (0.007–0.020 grados) y los
# bordes salían dentados en cuanto uno se acercaba: a zoom 10 esas tolerancias
# son decenas de pixeles. Estas están un orden de magnitud por debajo.
# LA SIMPLIFICACIÓN ES TOPOLÓGICA, NO POLÍGONO A POLÍGONO
# -------------------------------------------------------
# Hicieron falta tres intentos, y los dos primeros fallan de maneras distintas:
#
# 1. Simplificar **cada capa por su cuenta**: la frontera entre dos provincias
#    sale con unos vértices en `nacional-03` y con otros en `nacional-04`, así
#    que al superponerlas no casan.
# 2. Simplificar los distritos y **unirlos** para las capas de arriba: los
#    vértices casan, pero simplificar cada polígono por separado mueve los suyos
#    sin mover los del vecino, así que dos distritos contiguos dejan de compartir
#    la arista y `unary_union` ya no puede fundirlos. Queda una línea interior
#    dibujada como si fuera frontera de departamento —la que se veía entre
#    Mórrope y Olmos, dentro de Lambayeque—.
#
# La solución es simplificar la **topología**: se extraen los arcos compartidos
# una sola vez, se simplifican esos arcos, y cada distrito se reconstruye con
# ellos. Dos vecinos siguen compartiendo exactamente la misma arista, así que la
# unión es limpia; y como las capas de arriba se disuelven de esos mismos
# distritos, los bordes casan entre niveles. Es lo que hace TopoJSON, y por eso
# se usa `topojson` en vez de reimplementarlo.
TOL = 0.0010          # ~110 m; medio pixel a zoom 10
CAPAS = {
    # `race` es la columna de la tabla de referencia que decide si ese distrito
    # participa; `fuera` es el nivel al que se agrupan los que no participan.
    "01": {"nivel": "departamento", "area_min": 0.0040,
           "race": "race_gobernador", "fuera": "provincia"},
    "03": {"nivel": "provincia",    "area_min": 0.0020,
           "race": "race_provincial", "fuera": "provincia"},
    "04": {"nivel": "distrito",     "area_min": 0.0006,
           "race": "race_distrital", "fuera": "distrito"},
}


# Superficie mínima de un hueco para considerarlo un enclave y no residuo del
# solape entre polígonos de la fuente. ~1.2 km².
HUECO_MIN = 1e-4


def _area(anillo) -> float:
    """Área por la fórmula del cordón, sin signo."""
    a = 0.0
    for i in range(len(anillo) - 1):
        a += (anillo[i][0] * anillo[i + 1][1]
              - anillo[i + 1][0] * anillo[i][1])
    return abs(a) / 2


def disuelve(geoms: list, ubigeo: str):
    """Une varias geometrías en una sola, resolviendo solapes y vacíos.

    `buffer(0)` normaliza polígonos inválidos —anillos que se autointersecan,
    orientación al revés— que `unary_union` rechazaría. En la geometría canónica
    hay unos cuantos.
    """
    piezas = []
    for g in geoms:
        try:
            piezas.append((g if hasattr(g, "geom_type") else shape(g)).buffer(0))
        except Exception:
            continue
    return unary_union(piezas) if piezas else None


def adelgaza(geom, tol: float, area_min: float, dec: int) -> list:
    """Simplifica y redondea; devuelve polígonos en coordenadas GeoJSON.

    `area_min` descarta islotes, **nunca la pieza principal**. Aplicarlo a secas
    borraba 34 distritos enteros del mapa nacional: los de Lima son más chicos
    que el umbral que sirve para descartar una isla. Un distrito que no se pinta
    es un distrito en el que nadie puede hacer clic.

    Los **huecos reales** —enclaves— sobreviven como anillos interiores del
    polígono, que es como GeoJSON los representa y como Leaflet los dibuja.
    """
    if geom is None or geom.is_empty:
        return []
    if tol > 0:
        s = geom.simplify(tol, preserve_topology=True)
        if not s.is_empty:
            geom = s
    trozos = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    trozos = [t for t in trozos if t.geom_type == "Polygon" and not t.is_empty]
    if not trozos:
        return []
    trozos.sort(key=lambda t: -t.area)
    salida = []
    for i, t in enumerate(trozos):
        if i and t.area < area_min:
            continue
        anillos = mapping(t)["coordinates"]
        # El anillo 0 es el exterior; los demás son huecos y se filtran por área.
        anillos = (anillos[:1] +
                   tuple(h for h in anillos[1:] if _area(h) >= HUECO_MIN))
        # 14 distritos del canónico traen coordenadas 3D (lon, lat, altitud) y
        # shapely las conserva. La altitud no pinta nada en un mapa plano.
        salida.append([[[round(q[0], dec), round(q[1], dec)] for q in anillo]
                       for anillo in anillos])
    return salida


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anio", default="2026")
    p.add_argument("--reference", type=Path, default=None)
    p.add_argument("--decimales", type=int, default=4)
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()

    # Los dos bloques guardan su referencia en su propio directorio, con la misma
    # convención que `build_catalogo`: 2022 lleva sufijo de año porque conviven
    # varios procesos en el banco de pruebas; 2026 no, porque solo hay uno. Las
    # geometrías en cambio viven juntas, que es de donde salen ambos años.
    base = RAIZ
    suf = ""
    destino = a.out or base / "data/geo"

    fuente = RAIZ / f"data/reference/geo/distritos_{a.anio}.geojson"
    gj = json.load(open(fuente))
    ref_p = a.reference or base / f"data/reference/distritos{suf}.csv"
    ref = {}
    with open(ref_p, newline="", encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            ref[fila["ubigeo_distrito"]] = fila
    print(f"referencia: {ref_p.name} — {len(ref):,} distritos")
    print(f"fuente: {fuente.name} — {len(gj['features']):,} distritos, "
          f"{fuente.stat().st_size/1e6:.1f} MB")

    # Simplificación topológica: una sola vez, sobre los arcos compartidos.
    print(f"simplificando la topología de {len(gj['features']):,} distritos "
          f"(tol={TOL}) …")
    ubis = [f["properties"]["ubigeo_distrito"] for f in gj["features"]]
    # force_2d: unos cuantos polígonos del INEI traen coordenada Z y topojson
    # apila los arrays de coordenadas, así que mezclar 2D y 3D lo revienta.
    formas = [force_2d(shape(f["geometry"]).buffer(0)) for f in gj["features"]]
    topo = tp.Topology(formas, prequantize=False, shared_coords=True)
    simplificado = json.loads(topo.toposimplify(TOL).to_geojson())
    simple = {}
    for u, f in zip(ubis, simplificado["features"]):
        g = shape(f["geometry"]).buffer(0)
        if g.is_empty:
            continue
        simple[u] = unary_union([simple[u], g]) if u in simple else g

    puntos = {}
    for tipo, cfg in CAPAS.items():
        nivel = cfg["nivel"]
        crudos, nombres, fuera = defaultdict(list), {}, set()
        for f in gj["features"]:
            pr = f["properties"]
            r = ref.get(pr["ubigeo_distrito"])
            participa = bool((r or {}).get(cfg["race"], "").strip())
            # Quien no participa se agrupa por su cuenta, para no contaminar la
            # pieza de quienes sí lo hacen: si Lima Metropolitana entrara en el
            # departamento de Lima, la región saldría pintada de más.
            lvl = nivel if participa else cfg["fuera"]
            u = pr[f"ubigeo_{lvl}"]
            nombres[u] = pr[f"nombre_{lvl}"]
            if not participa:
                fuera.add(u)
            if pr["ubigeo_distrito"] in simple:
                crudos[u].append(simple[pr["ubigeo_distrito"]])

        feats = []
        for u in sorted(crudos):
            # Los hijos ya vienen simplificados: aquí solo se unen. Simplificar
            # otra vez rompería la coincidencia de bordes entre capas.
            polys = adelgaza(unary_union(crudos[u]), 0.0,
                             cfg["area_min"], a.decimales)
            if not polys:
                continue
            # `representative_point` está garantizado dentro del polígono;
            # `centroid` no lo está en cuanto la forma es cóncava.
            try:
                rp = disuelve([{"type": "MultiPolygon", "coordinates": polys}
                               if len(polys) > 1 else
                               {"type": "Polygon", "coordinates": polys[0]}], u)
                pt = rp.representative_point()
                puntos[u] = [round(pt.x, 5), round(pt.y, 5)]
            except Exception:
                pass
            props = {"ubigeo": u, "nombre": nombres[u]}
            if u in fuera:
                props["no_participa"] = True
            feats.append({
                "type": "Feature",
                "properties": props,
                "geometry": ({"type": "Polygon", "coordinates": polys[0]}
                             if len(polys) == 1
                             else {"type": "MultiPolygon", "coordinates": polys})})

        destino.mkdir(parents=True, exist_ok=True)
        ruta = destino / f"nacional-{tipo}.geojson"
        with open(ruta, "w") as fh:
            json.dump({"type": "FeatureCollection", "features": feats},
                      fh, separators=(",", ":"))
        nf = sum(1 for f in feats if f["properties"].get("no_participa"))
        print(f"  nacional-{tipo}.geojson  {len(feats):>5,} piezas  "
              f"{ruta.stat().st_size/1e3:>6.0f} KB"
              f"{f'   ({nf} no participan)' if nf else ''}")
    ruta_pt = RAIZ / f"data/reference/geo/centroides_{a.anio}.json"
    with open(ruta_pt, "w") as fh:
        json.dump(puntos, fh, separators=(",", ":"), sort_keys=True)
    print(f"  centroides_{a.anio}.json  {len(puntos):>7,} puntos "
          f"(representative_point, siempre dentro)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
