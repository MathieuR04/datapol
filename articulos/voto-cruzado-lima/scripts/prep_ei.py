import sys, duckdb, pandas as pd
ABR = {'RENOVACION POPULAR':'RP','PARTIDO DEMOCRATICO SOMOS PERU':'SomosPeru','PODEMOS PERU':'Podemos',
 'PARTIDO FRENTE DE LA ESPERANZA 2021':'FE2021','AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL':'AvanzaPais',
 'ALIANZA PARA EL PROGRESO':'APP','FUERZA POPULAR':'FuerzaPop','PARTIDO MORADO':'Morado','ACCION POPULAR':'AccionPop',
 'JUNTOS POR EL PERU':'JP','PARTIDO POLITICO NACIONAL PERU LIBRE':'PeruLibre','BLANCO/NULO':'BlancoNulo'}
c = duckdb.connect()
for ubi in sys.argv[1:]:
    cat = c.sql(f"""select mesa, org, coalesce(p,0) p, coalesce(d,0) d from 'votos_mesa_lima.parquet' r
      join 'piso_mesa.parquet' f using(mesa) where f.ubi='{ubi}'
      union all select mesa, 'BLANCO/NULO', bp+np_, bd+nd from 'piso_mesa.parquet' where ubi='{ubi}'""").df()
    cat['org'] = cat.org.map(lambda o: ABR.get(o, o))
    def colapsa(col, pre):
        tot = cat.groupby('org')[col].sum(); sh = tot / tot.sum()
        keep = [o for o in sh.index if sh[o] >= 0.04 or o == 'BlancoNulo']
        t = cat.assign(k=cat.org.where(cat.org.isin(keep), 'Otros')).pivot_table(index='mesa', columns='k', values=col, aggfunc='sum', fill_value=0)
        orden = [o for o in sh.sort_values(ascending=False).index if o in keep and o != 'BlancoNulo'] + (['Otros'] if 'Otros' in t else []) + ['BlancoNulo']
        return t[orden].add_prefix(pre)
    P, D = colapsa('p', 'p_'), colapsa('d', 'd_')
    x = P.join(D); x = x[P.sum(1) > 0]
    assert (x.filter(like='p_').sum(1) == x.filter(like='d_').sum(1)).all()
    x.to_csv(f'ei_in_{ubi}.csv'); print(ubi, len(x), list(x.columns))
