"""Arma data/voto_cruzado.json para el artículo.

Uso:
    python scripts/build_data.py --ei-seeds 11,12

Lee lo que ya está en data/ (piso_mesa.parquet, votos_mesa_lima.parquet,
cotas_mesa.parquet, ei/) más los registros de candidatos 2022 y 2026. No hace
ninguna petición de red.
"""
import argparse, json
from pathlib import Path
import duckdb, numpy as np, pandas as pd

AQUI = Path(__file__).resolve().parents[1]
ART = AQUI.parent
DATA = AQUI / 'data'
CAND22 = ART / 'erm/2022/data/raw/erm2022_candidatos.csv'
CAND26 = ART / 'erm-2026-candidatos/data/erm2026_candidatos.csv'
GEO = ART / 'erm/2022/data/reference/geo/distritos_2022.geojson'

ABR = {'RENOVACION POPULAR': 'RP', 'PARTIDO DEMOCRATICO SOMOS PERU': 'SomosPeru', 'PODEMOS PERU': 'Podemos',
       'PARTIDO FRENTE DE LA ESPERANZA 2021': 'FE2021', 'AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL': 'AvanzaPais',
       'ALIANZA PARA EL PROGRESO': 'APP', 'FUERZA POPULAR': 'FuerzaPop', 'PARTIDO MORADO': 'Morado',
       'ACCION POPULAR': 'AccionPop', 'JUNTOS POR EL PERU': 'JP', 'PARTIDO POLITICO NACIONAL PERU LIBRE': 'PeruLibre',
       'PARTIDO PATRIOTICO DEL PERU': 'Patriotico'}
NOMBRE = {'RP': 'Renovación Popular', 'SomosPeru': 'Somos Perú', 'Podemos': 'Podemos Perú',
          'FE2021': 'Frente de la Esperanza', 'AvanzaPais': 'Avanza País', 'APP': 'Alianza para el Progreso',
          'FuerzaPop': 'Fuerza Popular', 'Morado': 'Partido Morado', 'AccionPop': 'Acción Popular',
          'JP': 'Juntos por el Perú', 'PeruLibre': 'Perú Libre', 'Patriotico': 'Partido Patriótico',
          'Otros': 'Otros', 'BlancoNulo': 'Blanco o nulo'}
# Los cuatro casos y la organización cuyo candidato distrital explica el cruce.
CASOS = [('140130', 'AvanzaPais'), ('140114', 'APP'), ('140124', 'FuerzaPop'), ('140140', 'FuerzaPop')]


# El JNE y la ONPE publican sin tildes; se reponen solo en los nombres que salen en el artículo.
TILDES = {'Martin': 'Martín', 'Rimac': 'Rímac', 'Lurin': 'Lurín', 'Jesus': 'Jesús', 'Maria': 'María',
          'Ancon': 'Ancón', 'Pachacamac': 'Pachacámac', 'Cesar': 'César', 'Chacon': 'Chacón', 'Lopez': 'López',
          'Leon': 'León', 'Alvarez': 'Álvarez', 'Bazan': 'Bazán', 'Galvez': 'Gálvez', 'Sanchez': 'Sánchez',
          'Masias': 'Masías', 'Alegria': 'Alegría', 'Hernandez': 'Hernández'}
# Siglas para las etiquetas "Apellido (SIGLA)".
SIGLA = {'RP': 'RP', 'AvanzaPais': 'AvP', 'APP': 'APP', 'FuerzaPop': 'FP', 'SomosPeru': 'SP', 'Podemos': 'Podemos',
         'FE2021': 'FE', 'PeruLibre': 'PL', 'JP': 'JP', 'Morado': 'PM', 'AccionPop': 'AP', 'Patriotico': 'PPP'}


def titulo(s):
    t = s.title()
    for a in (' De ', ' Del ', ' La ', ' Los '):
        t = t.replace(a, a.lower())
    return ' '.join(TILDES.get(w, w) for w in t.split(' '))


def carga_ei(ubi, seeds):
    ch = []
    for s in seeds:
        c = pd.read_csv(DATA / 'ei' / f'ei_lambda_{ubi}_{s}.csv')
        c.columns = [k.removeprefix('lambda.') for k in c.columns]
        ch.append(c)
    A = np.stack([c.values for c in ch]); n = A.shape[1]
    W = A.var(1, ddof=1).mean(0); B = n * A.mean(1).var(0, ddof=1)
    rhat = np.sqrt(((n - 1) / n * W + B / n) / W)
    return pd.concat(ch, ignore_index=True), float(rhat.max()), int((rhat > 1.1).sum()), len(rhat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ei-seeds', default='11,12')
    args = ap.parse_args()
    seeds = [int(s) for s in args.ei_seeds.split(',')]
    c = duckdb.connect()
    c.sql(f"create view f as select * from '{DATA}/piso_mesa.parquet'")
    c.sql(f"create view r as select * from '{DATA}/votos_mesa_lima.parquet'")
    c.sql(f"create view b as select * from '{DATA}/cotas_mesa.parquet'")
    c.sql(f"""create view nom as select distinct lpad(ubigeo::varchar,6,'0') ubi, distrito nom
              from '{CAND22}' where ubigeo like '1401%' and distrito is not null""")

    # --- Lima entera
    lima = c.sql("""select count(*) mesas, sum(emit) emit, 1-sum(recto_max)/sum(emit) piso,
                    1-sum(recto_min)/sum(emit) techo from b""").df().iloc[0]
    q = c.sql("select quantile_cont(1-recto_max/emit,[.1,.5,.9]) from b").fetchone()[0]
    # el mismo piso con los distritos agregados, para mostrar lo que aporta la mesa
    piso_dist = c.sql("""with t as (select f.ubi, r.org, sum(coalesce(p,0)) p, sum(coalesce(d,0)) d
                                    from r join f using(mesa) group by 1,2),
                              e as (select ubi, sum(emit) emit, sum(bp+np_) bnp, sum(bd+nd) bnd from f group by 1)
                         select 1 - (sum(x.recto) + sum(least(bnp,bnd))) / sum(emit)
                         from e join (select ubi, sum(least(p,d)) recto from t group by 1) x using(ubi)""").fetchone()[0]

    # --- por distrito
    dist = c.sql("""select b.ubi, nom.nom, count(*) mesas, sum(emit) emit, 1-sum(recto_max)/sum(emit) piso
                    from b join nom using(ubi) group by all order by piso desc""").df()

    # --- votos por partido y distrito (porcentaje de válidos en cada cédula)
    pd_ = c.sql("""with t as (select f.ubi, r.org, sum(coalesce(p,0)) p, sum(coalesce(d,0)) d,
                     sum(least(coalesce(p,0),coalesce(d,0))) m from r join f using(mesa) group by 1,2),
                   v as (select ubi, sum(vp) vp, sum(vd) vd from f group by 1)
                   select t.*, v.vp, v.vd from t join v using(ubi)""").df()
    pd_['k'] = pd_.org.map(ABR)
    assert pd_.k.notna().all(), pd_[pd_.k.isna()].org.unique()
    tot = c.sql("select sum(vp) vp, sum(vd) vd from f").df().iloc[0]
    con_prov = pd_.groupby('k').p.sum().loc[lambda s: s > 0].index


    # --- candidatos a alcalde distrital 2022 en los casos
    cand = c.sql(f"""select lpad(ubigeo::varchar,6,'0') ubi, organizacion org, candidato, dni
                     from '{CAND22}' where cargo='ALCALDE DISTRITAL' and estado_lista='INSCRITO'
                     and ubigeo in ({','.join(repr(u) for u, _ in CASOS)})""").df()
    cand['k'] = cand.org.map(ABR)
    # apellido de cada candidato a alcalde (Lima y los cuatro distritos), solo si su candidatura siguió en pie
    ap = c.sql(f"""select lpad(ubigeo::varchar,6,'0') ubi, organizacion org, apellido_paterno ap
                   from '{CAND22}' where estado_lista='INSCRITO' and estado_candidato='INSCRITO'
                   and ((ubigeo='140100' and cargo='ALCALDE PROVINCIAL')
                        or (ubigeo in ({','.join(repr(u) for u, _ in CASOS)}) and cargo='ALCALDE DISTRITAL'))""").df()
    APELLIDO = {(u, ABR[o]): titulo(a) for u, o, a in ap.itertuples(index=False) if o in ABR}

    def etq(ubi, k):
        if k == 'Otros': return 'Otros'
        if k == 'BlancoNulo': return 'Blanco o nulo'
        a = APELLIDO.get((ubi, k))
        return f'{a} ({SIGLA[k]})' if a else f'{SIGLA[k]}, sin candidato'
    partidos = []
    for k in con_prov:
        x = pd_[(pd_.k == k)]
        y = x[x.d > 0]
        gana = y[y.d / y.vd > y.p / y.vp]
        partidos.append({
            'k': k, 'nombre': NOMBRE[k], 'etq_lima': etq('140100', k),
            'lima': round(100 * x.p.sum() / tot.vp, 2), 'distritos': round(100 * x.d.sum() / tot.vd, 2),
            'retiene': round(100 * x.m.sum() / x.p.sum(), 1),
            'n_lista_dist': int(len(y)), 'n_gana_dist': int(len(gana)),
            'puntos': [[u, round(100 * a / va, 2), round(100 * b_ / vd, 2), int(va)]
                       for u, a, b_, va, vd in y[['ubi', 'p', 'd', 'vp', 'vd']].itertuples(index=False)],
        })
    partidos.sort(key=lambda p: -p['lima'])

    c26 = c.sql(f"""select dni, organizacion org, cargo, estado_candidato from '{CAND26}'
                    where ubigeo='140100' and cargo='ALCALDE PROVINCIAL'""").df()

    casos = []
    for ubi, clave in CASOS:
        x = pd.read_csv(DATA / 'ei' / f'ei_in_{ubi}.csv')
        draws, rhat, malas, celdas = carga_ei(ubi, seeds)
        rows = list(dict.fromkeys(k.split('.')[0] for k in draws.columns))
        cols = list(dict.fromkeys(k.split('.')[1] for k in draws.columns))
        w = (x[rows].sum() / x[rows].sum().sum())
        same = [(r_, 'd_' + r_[2:]) for r_ in rows if 'd_' + r_[2:] in cols and r_ != 'p_Otros']
        recto = sum(w[a] * draws[f'{a}.{b_}'] for a, b_ in same)
        cz = 1 - recto
        # adónde fue en el distrito el votante de López Aliaga
        rp = [{'k': d_[2:], 'nombre': NOMBRE[d_[2:]], 'etq': etq(ubi, d_[2:]), 'media': round(100 * draws[f'p_RP.{d_}'].mean(), 1),
               'p05': round(100 * draws[f'p_RP.{d_}'].quantile(.05), 1),
               'p95': round(100 * draws[f'p_RP.{d_}'].quantile(.95), 1)} for d_ in cols]
        # de qué voto provincial se compone el voto distrital de la organización clave
        col = f'd_{clave}'
        masa = {r_: w[r_] * draws[f'{r_}.{col}'] for r_ in rows}
        total = sum(masa.values())
        comp = [{'k': r_[2:], 'nombre': NOMBRE[r_[2:]], 'etq': etq('140100', r_[2:]), 'media': round(100 * (masa[r_] / total).mean(), 1),
                 'p05': round(100 * (masa[r_] / total).quantile(.05), 1),
                 'p95': round(100 * (masa[r_] / total).quantile(.95), 1)} for r_ in rows]
        cc = cand[(cand.ubi == ubi) & (cand.k == clave)].iloc[0]
        en26 = c26[c26.dni == cc.dni]
        fila = dist[dist.ubi == ubi].iloc[0]
        s = pd_[pd_.ubi == ubi]
        gan = s.loc[s.d.idxmax()]
        casos.append({
            'ubi': ubi, 'nom': titulo(fila.nom), 'mesas': int(fila.mesas), 'piso': round(100 * fila.piso, 1),
            'cruzado': [round(100 * cz.mean(), 1), round(100 * cz.quantile(.05), 1), round(100 * cz.quantile(.95), 1)],
            'clave': clave, 'clave_nombre': NOMBRE[clave], 'candidato': titulo(cc.candidato),
            'clave_etq': etq(ubi, clave), 'rp_dist_etq': etq(ubi, 'RP'), 'rla_etq': etq('140100', 'RP'),
            'clave_lima': round(100 * s[s.k == clave].p.sum() / s.vp.iloc[0], 1),
            'clave_dist': round(100 * s[s.k == clave].d.sum() / s.vd.iloc[0], 1),
            'rp_lima': round(100 * s[s.k == 'RP'].p.sum() / s.vp.iloc[0], 1),
            'rp_dist': round(100 * s[s.k == 'RP'].d.sum() / s.vd.iloc[0], 1),
            'ganador_org': NOMBRE[gan.k], 'ganador_etq': etq(ubi, gan.k), 'ganador_pct': round(100 * gan.d / gan.vd, 1),
            'destino_rp': sorted(rp, key=lambda d_: -d_['media']),
            'origen_clave': sorted(comp, key=lambda d_: -d_['media']),
            'candidato_2026': None if en26.empty else {'org': en26.org.iloc[0], 'cargo': en26.cargo.iloc[0],
                                                       'estado': en26.estado_candidato.iloc[0]},
            'ei': {'rhat_max': round(rhat, 3), 'celdas_rhat_gt_1_1': malas, 'celdas': celdas,
                   'seeds': seeds, 'draws': int(len(draws))},
        })

    # --- geometría de Lima, coordenadas a 4 decimales
    g = json.load(open(GEO))
    def red(o):
        return [red(v) for v in o] if isinstance(o, list) and o and isinstance(o[0], list) else [round(v, 4) for v in o]
    feats = [{'type': 'Feature', 'properties': {'ubi': ft['properties']['ubigeo_distrito']},
              'geometry': {'type': ft['geometry']['type'], 'coordinates': red(ft['geometry']['coordinates'])}}
             for ft in g['features'] if ft['properties']['ubigeo_distrito'].startswith('1401')]

    out = {
        'lima': {'mesas': int(lima.mesas), 'emitidos': int(lima.emit), 'piso': round(100 * lima.piso, 1),
                 'techo': round(100 * lima.techo, 1), 'piso_distrital': round(100 * piso_dist, 1), 'piso_p10': round(100 * q[0], 1),
                 'piso_mediana': round(100 * q[1], 1), 'piso_p90': round(100 * q[2], 1)},
        'distritos': [{'ubi': u, 'nom': titulo(n), 'mesas': int(m), 'emit': int(e), 'piso': round(100 * p, 1)}
                      for u, n, m, e, p in dist.itertuples(index=False)],
        'partidos': partidos,
        'casos': casos,
        'geo': {'type': 'FeatureCollection', 'features': feats},
    }
    (DATA / 'voto_cruzado.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f"voto_cruzado.json: {len(out['distritos'])} distritos, {len(partidos)} partidos, {len(casos)} casos,"
          f" {(DATA / 'voto_cruzado.json').stat().st_size // 1024} KB")
    for cs in casos:
        print(f"  {cs['nom']:12s} piso {cs['piso']}  cruzado {cs['cruzado']}  rhat {cs['ei']['rhat_max']}"
              f"  {cs['candidato']} ({cs['clave_nombre']})  2026: {cs['candidato_2026']}")


if __name__ == '__main__':
    main()
