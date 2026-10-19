"""Base de poder de los gobernadores ERM 2026.

Para cada gobernador electo en primera vuelta y cada finalista de segunda vuelta mide
cuánto del consejo regional y de las alcaldías (provinciales y distritales) quedó en
manos de su partido —contando a sus alianzas por la familia `grupo_id` del catálogo
de organizaciones—, en número y ponderado por electores hábiles. Escribe
`data/gobernabilidad.json` y un SVG simplificado por región en `data/mapas/`.

    uv run --with shapely python articulos/gobernabilidad-erm-2026/scripts/build_data.py
"""
import collections
import csv
import json
import math
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

RAIZ = Path(__file__).resolve().parents[3]
ERM = RAIZ / 'peru/2026erm/data'
ORGS = RAIZ / 'articulos/erm-2026-candidatos/data/organizaciones_erm2026.csv'
SALIDA = Path(__file__).resolve().parents[1] / 'data'
ANCHO = 560          # ancho del lienzo SVG de cada región, en px
TOLERANCIA = 0.35    # Douglas-Peucker, en px del lienzo

CORTOS = {
    'ALIANZA ELECTORAL VENCEREMOS': 'Venceremos', 'RENOVACION POPULAR PERU': 'Renovación Popular',
    'ALIANZA RENOVACION POPULAR Y TORO': 'Renovación Popular y Toro', 'AHORA NACION - AN': 'Ahora Nación',
    'PARTIDO DEMOCRATICO SOMOS PERU': 'Somos Perú', 'ALIANZA PARA EL PROGRESO': 'APP',
    'PARTIDO PAIS PARA TODOS': 'País para Todos', 'LIBERTAD POPULAR': 'Libertad Popular',
    'AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL': 'Avanza País', 'PODEMOS PERU': 'Podemos Perú',
    'FUERZA POPULAR': 'Fuerza Popular', 'ACCION POPULAR': 'Acción Popular', 'FE EN EL PERU': 'Fe en el Perú',
    'FUERZA AREQUIPEÑA': 'Fuerza Arequipeña', 'ASI - JUNTOS POR EL PERU': 'Juntos por el Perú',
    'PARTIDO FRENTE DE LA ESPERANZA 2021': 'Frente de la Esperanza', 'PARTIDO POLITICO PRIN': 'PRIN',
    'PARTIDO POLITICO PERU PRIMERO': 'Perú Primero', 'APP - TRABAJA AYACUCHO': 'APP - Trabaja Ayacucho',
    'MOVIMIENTO REGIONAL AMAZONENSE UNIDOS AL CAMPO': 'Mov. Amazonense Unidos al Campo',
    'MOVIMIENTO REGIONAL VICTORIA AMAZONENSE': 'Mov. Victoria Amazonense',
}


def luminancia(h):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(int(h[i:i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def legible(h, fondo='#e2d8ca', minimo=2.0):
    """Oscurece el color del partido hasta que se distinga del gris de «ganó otro»."""
    while (luminancia(fondo) + 0.05) / (luminancia(h) + 0.05) < minimo:
        h = '#' + ''.join(f'{int(int(h[i:i + 2], 16) * 0.9):02x}' for i in (1, 3, 5))
    return h


def corto(nombre):
    return CORTOS.get(nombre, nombre.title())


def leer(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


carreras = {p.stem: leer(p) for p in (ERM / 'carrera').glob('*.json')}
electos = leer(ERM / 'electos.json')
colores = leer(ERM / 'colores.json')
cargos, nombres_org = electos['cargos'], electos['organizaciones']
familia = {}
with open(ORGS, encoding='utf-8') as f:
    for r in csv.DictReader(f):
        familia['jne-' + r['organizacion_id']] = 'jne-' + r['grupo_id']
fam = lambda o: familia.get(o, o)
with open(ERM / 'reference/distritos.csv', encoding='utf-8') as f:
    distritos = list(csv.DictReader(f))

electores = lambda rid: carreras[rid]['computo']['electores_habiles'] or 0

# ganador (familia, organización, nombre) por carrera ejecutiva
ganador = {}
for nombre, cargo, org, race, *_ in electos['filas']:
    if cargos[cargo] in ('GOBERNADOR REGIONAL', 'ALCALDE PROVINCIAL', 'ALCALDE DISTRITAL'):
        ganador[race] = (fam(org), org, nombre)

prov_de, dist_de, cercado = collections.defaultdict(set), collections.defaultdict(set), {}
for r in distritos:
    g = r['race_gobernador']
    if not g:
        continue
    prov_de[g].add(r['race_provincial'])
    if r['race_distrital']:
        dist_de[g].add(r['race_distrital'])
    else:
        cercado[r['ubigeo_distrito']] = r['race_provincial']

# electores del cercado = provincia menos sus distritos con carrera propia
electores_dist = {}
for r in distritos:
    if r['race_distrital']:
        electores_dist[r['ubigeo_distrito']] = electores(r['race_distrital'])
for u, rp in cercado.items():
    resto = sum(electores_dist.get(r['ubigeo_distrito'], 0) for r in distritos
                if r['race_provincial'] == rp and r['race_distrital'])
    electores_dist[u] = max(0, electores(rp) - resto)


def alcaldias(races, f):
    dec = sorted(x for x in races if x in ganador)
    w = {x: electores(x) for x in dec}
    W = sum(w.values())
    propias = [x for x in dec if ganador[x][0] == f]
    return {'n': len(propias), 'd': len(dec), 'total': len(races), 'pend': len(races) - len(dec),
            'w': round(sum(w[x] for x in propias) / W, 4) if W else 0,
            'electores': sum(w[x] for x in propias), 'electores_total': W}


def consejo(g, f):
    c = carreras[g]['consejo']
    asientos = []
    for circ in c['circunscripciones']:
        for e in circ['escanos']:
            if not e['organizacion']:
                asientos.append({'circ': circ['nombre'], 'fam': None, 'org': 'En disputa', 'nombre': ''})
                continue
            asientos.append({'circ': circ['nombre'], 'fam': fam(e['organizacion']), 'org': corto(e['nombre']),
                             'nombre': e['consejero']['nombre'].title()})
    n = c['n_escanos']
    propios = sum(a['fam'] == f for a in asientos)
    rivales = collections.Counter(a['fam'] for a in asientos if a['fam'] not in (f, None))
    bloques = [{'fam': k, 'org': next(a['org'] for a in asientos if a['fam'] == k), 'n': v}
               for k, v in rivales.most_common()]
    mayoria = n // 2 + 1
    return {'n': n, 'adjudicados': sum(a['fam'] is not None for a in asientos), 'propios': propios, 'mayoria': mayoria,
            'faltan': max(0, mayoria - propios), 'bloques': bloques,
            'asientos': [{'p': -1 if a['fam'] is None else int(a['fam'] == f), 'r': next((i for i, b in enumerate(bloques) if b['fam'] == a['fam']), -1),
                          'circ': a['circ'].title(), 'org': a['org'], 'nombre': a['nombre']} for a in asientos]}


regiones = sorted(k for k in carreras if k.startswith('01-'))
candidatos = []
for g in regiones:
    rr = carreras[g]
    if g in ganador:
        finalistas = [o for o in rr['organizaciones'] if fam(o['codigo']) == ganador[g][0]][:1]
        estado = 'electo'
    else:
        finalistas = [o for o in rr['organizaciones'] if (o.get('p_segunda') or 0) > 0.01]
        estado = 'segunda'
    for o in finalistas:
        f = fam(o['codigo'])
        prov, dist = alcaldias(prov_de[g], f), alcaldias(dist_de[g], f)
        con = consejo(g, f)
        metricas = [con['propios'] / con['n'], prov['n'] / prov['d'], prov['w'], dist['n'] / dist['d'], dist['w']]
        candidatos.append({
            'race': g, 'region': rr['nombre'].title(), 'estado': estado,
            'p_segunda': o.get('p_segunda'), 'nombre': o['candidato']['nombre'].title(),
            'foto': o['candidato'].get('foto'), 'org': corto(o['nombre']), 'fam': f,
            'color': legible((colores.get(o['codigo']) or colores.get(f) or ['#7a6858'])[0]),
            'pct_validos': o['pct_validos'], 'consejo': con, 'prov': prov, 'dist': dist,
            'indice': round(sum(metricas) / len(metricas), 4),
            'prov_ganadas': sorted(carreras[x]['ubigeo'] for x in prov_de[g] if ganador.get(x, ('',))[0] == f),
            'dist_ganadas': sorted([carreras[x]['ubigeo'] for x in dist_de[g] if ganador.get(x, ('',))[0] == f]
                                   + [u for u, rp in cercado.items() if rp in prov_de[g] and ganador.get(rp, ('',))[0] == f]),
        })

# escenario Ventanilla: la única alcaldía del Callao sin resolver
v = carreras['04-240106']
ventanilla = {'pct_actas': v['computo']['pct_actas'], 'electores': electores('04-240106'),
              'lideres': [{'org': corto(o['nombre']), 'votos': o['votos'], 'pct': o['pct_validos'], 'p_gana': o.get('p_gana')}
                          for o in v['organizaciones'][:2]]}
callao = next(c for c in candidatos if c['race'] == '01-240000')
d = callao['dist']
ventanilla['si_pierde'] = {'n': d['n'], 'd': d['d'] + 1, 'w': round(d['electores'] / (d['electores_total'] + ventanilla['electores']), 4)}
ventanilla['si_gana'] = {'n': d['n'] + 1, 'd': d['d'] + 1, 'w': 1.0}


# ── mapas ────────────────────────────────────────────────────────────────
def dp(pts, tol):
    if len(pts) < 4:
        return pts
    guardar, pila = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while pila:
        a, b = pila.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        mejor, im = -1, None
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            dist = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / L if L > 1e-9 else math.hypot(x0 - x1, y0 - y1)
            if dist > mejor:
                mejor, im = dist, i
        if im is not None and mejor > tol:
            guardar.add(im)
            pila += [(a, im), (im, b)]
    return [pts[i] for i in sorted(guardar)]


def anillos(geom):
    polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
    return [r for p in polys for r in p]


def proyectar(feats, ancho, tol):
    xs = [c[0] for f in feats for r in anillos(f['geometry']) for c in r]
    ys = [c[1] for f in feats for r in anillos(f['geometry']) for c in r]
    k = math.cos(math.radians((min(ys) + max(ys)) / 2))
    x0, y1 = min(xs), max(ys)
    esc = ancho / ((max(xs) - x0) * k)
    alto = (y1 - min(ys)) * esc
    out = []
    for f in feats:
        partes = []
        for r in anillos(f['geometry']):
            pts = dp([((c[0] - x0) * k * esc, (y1 - c[1]) * esc) for c in r], tol)
            if len(pts) < 3:
                continue
            partes.append('M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in pts) + 'Z')
        if partes:
            out.append({'u': f['properties']['ubigeo'], 'nombre': f['properties']['nombre'].title(), 'd': ''.join(partes)})
    return out, round(alto, 1)


def disolver(feats, ubigeo, nombre):
    """Une polígonos (provincias → departamento) para dibujar el borde exterior."""
    # cerrar las rendijas entre provincias vecinas y quedarse solo con el contorno exterior
    union = unary_union([shape(f['geometry']).buffer(0) for f in feats]).buffer(0.002).buffer(-0.002)
    partes = [Polygon(p.exterior) for p in getattr(union, 'geoms', [union]) if p.area > 1e-5]
    return {'properties': {'ubigeo': ubigeo, 'nombre': nombre}, 'geometry': mapping(MultiPolygon(partes))}


(SALIDA / 'mapas').mkdir(parents=True, exist_ok=True)
meta = {r['ubigeo_distrito']: r for r in distritos}
departamentos = []
for g in regiones:
    u = g[3:]
    prov = [f for f in leer(ERM / f'geo/{g}.geojson')['features'] if f['properties']['ubigeo'] != '140100']
    dist = [f for f in leer(ERM / f'geo/{g}-dist.geojson')['features'] if not f['properties']['ubigeo'].startswith('1401')]
    dep = disolver(prov, u, carreras[g]['nombre'])
    departamentos.append(dep)
    # una sola proyección para que el borde, las provincias y los distritos calcen
    todo, alto = proyectar([dep] + prov + dist, ANCHO, TOLERANCIA)
    borde, p, di = todo[0]['d'], todo[1:1 + len(prov)], todo[1 + len(prov):]
    for x in di:
        x['cercado'] = int(x['u'] in cercado)
        x['elect'] = electores_dist.get(x['u'], 0)
        rid = meta.get(x['u'], {}).get('race_distrital') or cercado.get(x['u'])
        x['pend'] = int(bool(rid) and rid not in ganador)
    for x in p:
        rid = '03-' + x['u']
        x['elect'] = electores(rid) if rid in carreras else 0
        x['pend'] = int(rid not in ganador)
    with open(SALIDA / f'mapas/{g}.json', 'w', encoding='utf-8') as f:
        json.dump({'ancho': ANCHO, 'alto': alto, 'borde': borde, 'prov': p, 'dist': di}, f, ensure_ascii=False, separators=(',', ':'))
# mapa nacional por departamento; Lima Metropolitana va aparte (no elige gobernador)
lima_met = [f for f in leer(ERM / 'geo/01-140000.geojson')['features'] if f['properties']['ubigeo'] == '140100']
departamentos.append(disolver(lima_met, 'lima-metropolitana', 'Lima Metropolitana'))
nac, alto_nac = proyectar(departamentos, 420, 0.6)
for x in nac:
    x['r'] = x.pop('u') if x['u'] == 'lima-metropolitana' else '01-' + x.pop('u')
with open(SALIDA / 'mapas/peru.json', 'w', encoding='utf-8') as f:
    json.dump({'ancho': 420, 'alto': alto_nac, 'dep': nac}, f, ensure_ascii=False, separators=(',', ':'))

with open(SALIDA / 'gobernabilidad.json', 'w', encoding='utf-8') as f:
    json.dump({'generado': electos['generado'], 'ventanilla': ventanilla, 'candidatos': candidatos},
              f, ensure_ascii=False, separators=(',', ':'))

for c in sorted(candidatos, key=lambda c: c['indice']):
    print(f"{c['estado']:7} {c['region'][:13]:13} {c['org'][:22]:22} índice {c['indice']:.2f}  consejo {c['consejo']['propios']}/{c['consejo']['n']} "
          f"(faltan {c['consejo']['faltan']})  prov {c['prov']['n']}/{c['prov']['d']} {c['prov']['w']:.0%}  dist {c['dist']['n']}/{c['dist']['d']} {c['dist']['w']:.0%}")
print('Ventanilla', ventanilla)
