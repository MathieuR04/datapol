"""
analyze_erm.py
==============
EDA figures for the ERM 2026 primarias candidatos article.
Produces fig1–fig5 in figures/.

Run: python3 analyze_erm.py   (from the candidatos-primarias-erm folder)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
BG      = '#f5f0e8'
BORDER  = '#cfc0ab'
TEXT    = '#1a1209'
MUTED   = '#7a6858'
TERRA   = '#c4603a'
SAND    = '#d9c9b4'
ORANGE  = '#E85C1A'
GREEN   = '#2E9B57'
BLUE    = '#4A8FCA'

plt.rcParams.update({
    'font.family':      'DejaVu Sans',
    'axes.spines.top':  False,
    'axes.spines.right':False,
    'figure.dpi':       150,
    'axes.labelsize':   11,
    'xtick.labelsize':  9,
    'ytick.labelsize':  9,
    'figure.facecolor': BG,
    'axes.facecolor':   BG,
    'text.color':       TEXT,
    'axes.labelcolor':  TEXT,
    'xtick.color':      TEXT,
    'ytick.color':      TEXT,
    'axes.edgecolor':   BORDER,
})

Path('figures').mkdir(exist_ok=True)

# ── Load ──────────────────────────────────────────────────────────────────────
df = pd.read_excel('candidatos.xlsx')
is_desig = df['NOMBRES Y APELLIDOS'].str.strip() == 'DESIGNADO'
named    = df[~is_desig].copy()
desig    = df[is_desig].copy()

print(f"Total rows: {len(df):,}")
print(f"Named: {len(named):,}  |  DESIGNADO: {len(desig):,}  ({len(desig)/len(df)*100:.1f}%)")
print(f"Parties: {df['PRESENTACION'].nunique()}")

# ── Short party names ─────────────────────────────────────────────────────────
SHORT = {
    'ALIANZA PARA EL PROGRESO':                                    'Alianza para el Progreso',
    'PARTIDO DEMOCRATICO SOMOS PERU':                              'Somos Perú',
    'PARTIDO POLITICO PERU PRIMERO':                               'Perú Primero',
    'PODEMOS PERU':                                                'Podemos Perú',
    'AHORA NACION - AN':                                           'Ahora Nación',
    'ACCION POPULAR':                                              'Acción Popular',
    'PARTIDO POLITICO ADP':                                        'ADP',
    'RENOVACION POPULAR PERU':                                     'Renovación Popular',
    'PARTIDO PAIS PARA TODOS':                                     'País para Todos',
    'PROGRESEMOS':                                                 'Progresemos',
    'ALIANZA ELECTORAL VENCEREMOS':                                'Alianza Venceremos',
    'FUERZA CIUDADANA':                                            'Fuerza Ciudadana',
    'AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL':                 'Avanza País',
    'JUNTOS POR EL PERU':                                          'Juntos por el Perú',
    'FUERZA POPULAR':                                              'Fuerza Popular',
    'PARTIDO DEMOCRATA VERDE':                                     'Demócrata Verde',
    'PARTIDO APRISTA PERUANO':                                     'APRA',
    'LIBERTAD POPULAR':                                            'Libertad Popular',
    'FRENTE POPULAR AGRICOLA FIA DEL PERU':                        'FIA del Perú',
    'PARTIDO PATRIOTICO DEL PERU':                                 'Pat. Patriótico',
    'PARTIDO POPULAR CRISTIANO - PPC':                             'PPC',
    'PARTIDO CIVICO OBRAS':                                        'Cívico Obras',
    'BATALLA PERU':                                                'Batalla Perú',
    'PARTIDO FRENTE DE LA ESPERANZA 2021':                         'Fr. Esperanza 2021',
    'SALVEMOS AL PERU':                                            'Salvemos al Perú',
}
def short(name): return SHORT.get(name, name.title()[:28])


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 1 — Total named candidates by party (top 20)
# ═══════════════════════════════════════════════════════════════════════════════
party_total = named.groupby('PRESENTACION').size().sort_values(ascending=True).tail(20)
ylabels = [short(p) for p in party_total.index]

fig, ax = plt.subplots(figsize=(11, 7.5))
bars = ax.barh(ylabels, party_total.values, color=ORANGE, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.65)
for bar, val in zip(bars, party_total.values):
    ax.text(bar.get_width() + 80, bar.get_y() + bar.get_height()/2,
            f'{val:,}', va='center', ha='left', fontsize=8.5, color=MUTED)
ax.set_xlabel('Candidatos inscritos (con nombre)', fontsize=10, labelpad=8)
ax.set_title('Candidatos inscritos por partido — primarias ERM 2026\n(top 20, excluye DESIGNADO)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=max(party_total.values) * 1.18)
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
fig.tight_layout()
fig.savefig('figures/fig1_candidatos_por_partido.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig1")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 2 — DESIGNADO proportion by electoral tier
# ═══════════════════════════════════════════════════════════════════════════════
AMBITO_LABELS = {
    'GOBERNADOR Y VICEGOBERNADOR': 'Gobernador /\nVicegobernador',
    'CONSEJERO REGIONAL':          'Consejero\nRegional',
    'MUNICIPAL PROVINCIAL':        'Municipal\nProvincial',
    'MUNICIPAL DISTRITAL':         'Municipal\nDistrital',
}
order = ['GOBERNADOR Y VICEGOBERNADOR','CONSEJERO REGIONAL',
         'MUNICIPAL PROVINCIAL','MUNICIPAL DISTRITAL']

totals  = df.groupby('AMBITO').size()
desigs  = df.groupby('AMBITO').apply(lambda x: (x['NOMBRES Y APELLIDOS'].str.strip()=='DESIGNADO').sum(), include_groups=False)
pct_d   = (desigs / totals * 100).round(1)

fig, ax = plt.subplots(figsize=(10, 5.5))
x = np.arange(len(order))
w = 0.42
xlabels = [AMBITO_LABELS[a] for a in order]
pcts  = [pct_d[a] for a in order]
named_pcts = [100 - p for p in pcts]

b1 = ax.bar(x, named_pcts, w, label='Con nombre', color=ORANGE, alpha=0.85, edgecolor='white')
b2 = ax.bar(x, pcts, w, bottom=named_pcts, label='DESIGNADO', color=BORDER, alpha=0.85, edgecolor='white')

for i, (pct, tot) in enumerate(zip(pcts, [totals[a] for a in order])):
    ax.text(x[i], named_pcts[i] + pct/2, f'{pct:.0f}%',
            ha='center', va='center', fontsize=10, fontweight='bold', color=TEXT)
    ax.text(x[i], -5, f'n={tot:,}', ha='center', va='top', fontsize=8, color=MUTED)

ax.set_xticks(x); ax.set_xticklabels(xlabels, fontsize=10)
ax.set_ylabel('% de candidaturas', fontsize=10)
ax.set_ylim(-10, 115)
ax.set_title('Proporción de candidaturas DESIGNADO por nivel electoral',
             fontsize=12, fontweight='bold', pad=12)
ax.legend(fontsize=9, loc='upper right', framealpha=0.85, facecolor=BG)
ax.axhline(0, color=BORDER, lw=0.8)
ax.spines['bottom'].set_visible(False)
ax.tick_params(axis='x', length=0)
fig.tight_layout()
fig.savefig('figures/fig2_designado_por_nivel.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig2")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 3 — Gobernador coverage by party (# departamentos with named candidate)
# ═══════════════════════════════════════════════════════════════════════════════
gov_named = named[named['CARGO'] == 'GOBERNADOR']
gov_cov   = gov_named.groupby('PRESENTACION')['REGION'].nunique().sort_values(ascending=True).tail(20)
ylabels3  = [short(p) for p in gov_cov.index]

fig, ax = plt.subplots(figsize=(11, 7.5))
colors3 = [TERRA if v == 24 else (ORANGE if v >= 15 else BLUE) for v in gov_cov.values]
bars = ax.barh(ylabels3, gov_cov.values, color=colors3, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.65)
ax.axvline(24, color=MUTED, lw=1.2, ls='--', alpha=0.6, label='24 departamentos (total)')
for bar, val in zip(bars, gov_cov.values):
    ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2,
            str(val), va='center', ha='left', fontsize=9, color=MUTED)
ax.set_xlabel('Departamentos con candidato a Gobernador (con nombre)', fontsize=10, labelpad=8)
ax.set_title('Cobertura regional — candidatos a Gobernador por partido\n(top 20, excluye DESIGNADO)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=27)
ax.legend(fontsize=9, framealpha=0.85, facecolor=BG)
fig.tight_layout()
fig.savefig('figures/fig3_cobertura_gobernador.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig3")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 4 — Alcalde distrital coverage by party (# distritos)
# ═══════════════════════════════════════════════════════════════════════════════
alcd_named = named[named['CARGO'] == 'ALCALDE DISTRITAL']
alcd_cov   = (alcd_named.groupby('PRESENTACION')
              .apply(lambda x: x[['REGION','PROVINCIA','DISTRITO']].drop_duplicates().shape[0], include_groups=False)
              .sort_values(ascending=True).tail(20))
ylabels4   = [short(p) for p in alcd_cov.index]

fig, ax = plt.subplots(figsize=(11, 7.5))
bars = ax.barh(ylabels4, alcd_cov.values, color=GREEN, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.65)
ax.axvline(1892, color=MUTED, lw=1.2, ls='--', alpha=0.6, label='1,892 distritos (total)')
for bar, val in zip(bars, alcd_cov.values):
    pct = val / 1892 * 100
    ax.text(bar.get_width() + 10, bar.get_y() + bar.get_height()/2,
            f'{val:,}  ({pct:.0f}%)', va='center', ha='left', fontsize=8.5, color=MUTED)
ax.set_xlabel('Distritos con candidato a Alcalde Distrital (con nombre)', fontsize=10, labelpad=8)
ax.set_title('Cobertura distrital — alcaldes por partido · primarias ERM 2026\n(top 20, excluye DESIGNADO)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=2350)
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
ax.legend(fontsize=9, framealpha=0.85, facecolor=BG)
fig.tight_layout()
fig.savefig('figures/fig4_cobertura_distrital_partido.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig4")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 5 — Distrital coverage by region (% of distritos covered)
# ═══════════════════════════════════════════════════════════════════════════════
# Known district totals per region
DISTRITOS_POR_REGION = {
    'AMAZONAS': 84, 'ÁNCASH': 166, 'APURÍMAC': 80, 'AREQUIPA': 109,
    'AYACUCHO': 119, 'CAJAMARCA': 127, 'CALLAO': 6, 'CUSCO': 108,
    'HUANCAVELICA': 99, 'HUÁNUCO': 77, 'ICA': 43, 'JUNÍN': 123,
    'LA LIBERTAD': 83, 'LAMBAYEQUE': 38, 'LIMA METROPOLITANA': 43,
    'LIMA PROVINCIAS': 128, 'LORETO': 53, 'MADRE DE DIOS': 11,
    'MOQUEGUA': 20, 'PASCO': 29, 'PIURA': 64, 'PUNO': 109,
    'SAN MARTÍN': 77, 'TACNA': 27, 'TUMBES': 13, 'UCAYALI': 16,
}

alcd_all = alcd_named[['REGION','PROVINCIA','DISTRITO']].drop_duplicates()
region_cov = alcd_all.groupby('REGION').size().rename('covered')
region_df  = pd.DataFrame(region_cov)
region_df['total']   = region_df.index.map(DISTRITOS_POR_REGION)
region_df['missing'] = region_df['total'] - region_df['covered']
region_df['pct']     = region_df['covered'] / region_df['total'] * 100
region_df = region_df.sort_values('pct', ascending=True)

print("\nRegion coverage summary:")
print(region_df.sort_values('pct'))

fig, ax = plt.subplots(figsize=(11, 9))
y  = np.arange(len(region_df))
b1 = ax.barh(y, region_df['covered'], color=GREEN, alpha=0.85, edgecolor='white', linewidth=0.4, height=0.7, label='Con candidato')
b2 = ax.barh(y, region_df['missing'], left=region_df['covered'], color=BORDER, alpha=0.55, edgecolor='white', linewidth=0.4, height=0.7, label='Sin candidato')

for i, (_, row) in enumerate(region_df.iterrows()):
    ax.text(row['total'] + 1, i, f"{row['covered']:.0f}/{row['total']:.0f}  ({row['pct']:.0f}%)",
            va='center', ha='left', fontsize=8, color=MUTED)

ax.set_yticks(y)
ax.set_yticklabels(region_df.index, fontsize=9)
ax.set_xlabel('Número de distritos', fontsize=10, labelpad=8)
ax.set_title('Cobertura de alcaldías distritales por región · primarias ERM 2026\n(distritos con al menos un candidato a alcalde con nombre)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=max(region_df['total']) * 1.35)
ax.legend(fontsize=9, loc='lower right', framealpha=0.85, facecolor=BG)
fig.tight_layout()
fig.savefig('figures/fig5_cobertura_distrital_region.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig5")

print(f"\n✓ All figures → figures/")
print(f"\n=== KEY NUMBERS FOR ARTICLE ===")
print(f"Total candidaturas: {len(df):,}")
print(f"Named: {len(named):,}  ({len(named)/len(df)*100:.1f}%)")
print(f"DESIGNADO: {len(desig):,}  ({len(desig)/len(df)*100:.1f}%)")
print(f"Parties: {df['PRESENTACION'].nunique()}")
print(f"Gobernadores named: {len(named[named['CARGO']=='GOBERNADOR'])} / {len(df[df['CARGO']=='GOBERNADOR'])}")
print(f"% DESIGNADO gobernadores: {len(desig[desig['CARGO']=='GOBERNADOR'])/len(df[df['CARGO']=='GOBERNADOR'])*100:.1f}%")
print(f"Departamentos cubiertos (gobernador): {df[df['CARGO']=='GOBERNADOR']['REGION'].nunique()} / 24")
print(f"Provincias cubiertas (alcalde prov): {named[named['CARGO']=='ALCALDE PROVINCIAL'][['REGION','PROVINCIA']].drop_duplicates().shape[0]} / 196")
print(f"Distritos cubiertos (alcalde dist): {alcd_all.shape[0]} / 1892  ({alcd_all.shape[0]/1892*100:.1f}%)")
print(f"Distritos sin candidato: {1892 - alcd_all.shape[0]}")
