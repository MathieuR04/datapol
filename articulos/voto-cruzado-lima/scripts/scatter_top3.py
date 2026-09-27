"""Scatter provincial vs distrital por distrito, top 3 partidos. Uso: python scatter_top3.py DATA_DIR OUT_PNG"""
import sys, duckdb, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data, out = sys.argv[1], sys.argv[2]
FONDO, TINTA, SUAVE, LINEA = '#ede8df', '#2b2926', '#7a746b', '#d6cfc3'
plt.rcParams.update({'font.family': 'Helvetica Neue', 'font.size': 10, 'text.color': TINTA,
                     'axes.labelcolor': SUAVE, 'xtick.color': SUAVE, 'ytick.color': SUAVE})
c = duckdb.connect()
d = c.sql(f"""select f.ubi, any_value(n.nom) nom, r.org, sum(coalesce(p,0)) p, sum(coalesce(d,0)) d,
    sum(least(coalesce(p,0),coalesce(d,0))) m
  from '{data}/votos_mesa_lima.parquet' r join '{data}/piso_mesa.parquet' f using(mesa)
  join (select ubi::varchar ubi, nom from '{data}/distritos_cotas.csv') n on n.ubi=f.ubi group by 1,3""").df()
v = c.sql(f"select ubi, sum(vp) vp, sum(vd) vd from '{data}/piso_mesa.parquet' group by 1").df()
d = d.merge(v, on='ubi'); d['sp'] = 100*d.p/d.vp; d['sd'] = 100*d.d/d.vd
CORTO = {'SAN JUAN DE LURIGANCHO': 'SJL', 'SAN JUAN DE MIRAFLORES': 'SJM', 'SAN MARTIN DE PORRES': 'SMP',
         'VILLA EL SALVADOR': 'VES', 'VILLA MARIA DEL TRIUNFO': 'VMT', 'SANTIAGO DE SURCO': 'Surco',
         'MAGDALENA DEL MAR': 'Magdalena'}
nombre = lambda s: CORTO.get(s, s.title().replace(' De ', ' de ').replace(' Del ', ' del ').replace(' La ', ' la '))
PARTIDOS = [('RENOVACION POPULAR', 'Renovación Popular', '#1f8fc4'),
            ('PODEMOS PERU', 'Podemos Perú', '#12877d'),
            ('PARTIDO DEMOCRATICO SOMOS PERU', 'Somos Perú', '#2a5bb8')]
# Etiquetas elegidas a mano, pegadas a su punto (sin líneas guía). El lado va a mano
# porque la nube es densa: r derecha, l izquierda, t arriba, b abajo.
ETIQUETAS = {
    'RENOVACION POPULAR': {'SAN ISIDRO': 'r', 'SANTIAGO DE SURCO': 'r', 'MIRAFLORES': 'r', 'SAN BORJA': 'r',
                           'LA MOLINA': 'r', 'MAGDALENA DEL MAR': 'r', 'LURIN': 'l'},
    'PODEMOS PERU': {'SAN MARTIN DE PORRES': 'l', 'SAN JUAN DE LURIGANCHO': 'r', 'VILLA EL SALVADOR': 'r',
                     'CIENEGUILLA': 'r', 'LURIN': 'r', 'COMAS': 'b', 'MIRAFLORES': 'b'},
    'PARTIDO DEMOCRATICO SOMOS PERU': {'INDEPENDENCIA': 'r', 'PUENTE PIEDRA': 'l',
                                       'SAN JUAN DE LURIGANCHO': 'l', 'MAGDALENA DEL MAR': 'r',
                                       'VILLA EL SALVADOR': 'l'},
}
fig, axs = plt.subplots(1, 3, figsize=(15, 5.9), sharex=True, sharey=True, facecolor=FONDO)
for ax, (org, lab, col) in zip(axs, PARTIDOS):
    x = d[(d.org == org) & (d.d > 0)].copy()          # sin lista distrital: fuera
    ax.set_facecolor(FONDO)
    ax.plot([0, 65], [0, 65], color=SUAVE, lw=.9, ls=(0, (4, 3)), zorder=1)
    ax.text(58, 60.5, 'mismo voto', rotation=45, rotation_mode='anchor', fontsize=8, color=SUAVE, ha='right')
    ax.scatter(x.sp, x.sd, s=18 + x.vp/1800, color=col, alpha=.8, edgecolor=FONDO, lw=1.2, zorder=3)
    lados = ETIQUETAS[org]
    faltan = set(lados) - set(x.nom)
    assert not faltan, faltan
    for r in x[x.nom.isin(lados)].itertuples():
        rad = np.sqrt((18 + r.vp/1800) / np.pi) + 3          # radio del punto, en pt, más aire
        dx, dy, ha, va = {'r': (rad, 0, 'left', 'center'), 'l': (-rad, 0, 'right', 'center'),
                          't': (0, rad, 'center', 'bottom'), 'b': (0, -rad, 'center', 'top')}[lados[r.nom]]
        ax.annotate(nombre(r.nom), (r.sp, r.sd), xytext=(dx, dy), textcoords='offset points',
                    ha=ha, va=va, fontsize=9, color=TINTA, zorder=4)
    ret = x.m.sum() / d[d.org == org].p.sum()
    ax.set_title(lab, loc='left', fontsize=13, fontweight='bold', color=col, pad=26)
    ax.text(0, 1.035, f"Lima {100*d[d.org==org].p.sum()/v.vp.sum():.1f}% · distritos {100*d[d.org==org].d.sum()/v.vd.sum():.1f}%"
            f" · retiene al menos {100*ret:.0f}%", transform=ax.transAxes, fontsize=9, color=SUAVE)
    ax.set_xlim(0, 65); ax.set_ylim(0, 65); ax.set_aspect('equal')
    ax.set_xticks(range(0, 61, 20)); ax.set_yticks(range(0, 61, 20))
    ax.xaxis.set_major_formatter('{x:.0f}%'); ax.yaxis.set_major_formatter('{x:.0f}%')
    ax.grid(color=LINEA, lw=.6, zorder=0); ax.tick_params(length=3, color=SUAVE)
    for lado in ('top', 'right'): ax.spines[lado].set_visible(False)
    for lado in ('left', 'bottom'): ax.spines[lado].set_color(SUAVE); ax.spines[lado].set_linewidth(.8)
    ax.set_xlabel('Voto para alcalde de Lima')
axs[0].set_ylabel('Voto para alcalde distrital')
fig.text(.012, .965, 'El voto por Lima no baja al distrito', fontsize=17, fontweight='bold')
fig.text(.012, .925, 'Cada punto es un distrito: % de votos válidos del partido en la cédula provincial y en la distrital. '
         'Tamaño: votos válidos. Solo distritos donde el partido presentó lista.', fontsize=10, color=SUAVE)
fig.text(.012, .02, '"Retiene al menos": parte de su voto provincial que, mesa por mesa, necesariamente también votó por el partido en el distrito.  '
         'Fuente: ONPE, ERM 2022, resultados por mesa. Excluye el Cercado. datapol.lat', fontsize=8, color=SUAVE)
fig.subplots_adjust(left=.05, right=.99, top=.80, bottom=.13, wspace=.12)
fig.savefig(out, dpi=160, facecolor=FONDO)
