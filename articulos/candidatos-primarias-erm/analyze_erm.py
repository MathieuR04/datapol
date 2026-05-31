"""
analyze_erm.py  (revised)
==========================
EDA figures for the ERM 2026 primarias candidatos article.
Produces fig1–fig5 in figures/.

Changes from v1:
  - Fig 2: DESIGNADO breakdown by CARGO type within each level (not by AMBITO)
  - Figs 3–5: coverage now INCLUDES DESIGNADO (a party with DESIGNADO alcalde
    still intends to compete there — eventually someone will be named)
  - Universe for alcaldías distritales = 1,696 (= 1,892 − 196 provincial
    capitals, which do NOT elect a separate alcalde distrital)
  - Coverage by party uses drop_duplicates() / nunique() to avoid double-
    counting parties that register multiple candidates per circunscripción

Run: python3 analyze_erm.py   (from the candidatos-primarias-erm folder)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────────
BG     = '#f5f0e8'
BORDER = '#cfc0ab'
TEXT   = '#1a1209'
MUTED  = '#7a6858'
TERRA  = '#c4603a'
SAND   = '#d9c9b4'
ORANGE = '#E85C1A'
GREEN  = '#2E9B57'
BLUE   = '#4A8FCA'

plt.rcParams.update({
    'font.family':       'DejaVu Sans',
    'axes.spines.top':   False,
    'axes.spines.right': False,
    'figure.dpi':        150,
    'axes.labelsize':    11,
    'xtick.labelsize':   9,
    'ytick.labelsize':   9,
    'figure.facecolor':  BG,
    'axes.facecolor':    BG,
    'text.color':        TEXT,
    'axes.labelcolor':   TEXT,
    'xtick.color':       TEXT,
    'ytick.color':       TEXT,
    'axes.edgecolor':    BORDER,
})

Path('figures').mkdir(exist_ok=True)

# ── Load ───────────────────────────────────────────────────────────────────────
df = pd.read_excel('candidatos.xlsx')
is_desig = df['NOMBRES Y APELLIDOS'].str.strip() == 'DESIGNADO'
named    = df[~is_desig].copy()
desig    = df[is_desig].copy()

print(f"Total filas:  {len(df):,}")
print(f"Con nombre:   {len(named):,}  ({len(named)/len(df)*100:.1f}%)")
print(f"DESIGNADO:    {len(desig):,}  ({len(desig)/len(df)*100:.1f}%)")
print(f"Partidos:     {df['PRESENTACION'].nunique()}")

# ── Short party names ──────────────────────────────────────────────────────────
SHORT = {
    'ALIANZA PARA EL PROGRESO':                          'Alianza para el Progreso',
    'PARTIDO DEMOCRATICO SOMOS PERU':                    'Somos Perú',
    'PARTIDO POLITICO PERU PRIMERO':                     'Perú Primero',
    'PODEMOS PERU':                                      'Podemos Perú',
    'AHORA NACION - AN':                                 'Ahora Nación',
    'ACCION POPULAR':                                    'Acción Popular',
    'PARTIDO POLITICO ADP':                              'ADP',
    'RENOVACION POPULAR PERU':                           'Renovación Popular',
    'PARTIDO PAIS PARA TODOS':                           'País para Todos',
    'PROGRESEMOS':                                       'Progresemos',
    'ALIANZA ELECTORAL VENCEREMOS':                      'Alianza Venceremos',
    'FUERZA CIUDADANA':                                  'Fuerza Ciudadana',
    'AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL':       'Avanza País',
    'JUNTOS POR EL PERU':                                'Juntos por el Perú',
    'FUERZA POPULAR':                                    'Fuerza Popular',
    'PARTIDO DEMOCRATA VERDE':                           'Demócrata Verde',
    'PARTIDO APRISTA PERUANO':                           'APRA',
    'LIBERTAD POPULAR':                                  'Libertad Popular',
    'FRENTE POPULAR AGRICOLA FIA DEL PERU':              'FIA del Perú',
    'PARTIDO PATRIOTICO DEL PERU':                       'Pat. Patriótico',
    'PARTIDO POPULAR CRISTIANO - PPC':                   'PPC',
    'PARTIDO CIVICO OBRAS':                              'Cívico Obras',
    'BATALLA PERU':                                      'Batalla Perú',
    'PARTIDO FRENTE DE LA ESPERANZA 2021':               'Fr. Esperanza 2021',
    'SALVEMOS AL PERU':                                  'Salvemos al Perú',
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
# FIG 2 — DESIGNADO % by CARGO type within each electoral level
#
# The ~20% overall DESIGNADO rate is a legal cap that applies to lists as a whole,
# so breaking down by AMBITO just shows that cap in every tier. The informative
# cut is by CARGO TYPE within each tier: lead positions (Gobernador, Alcalde)
# vs list positions (Consejero Regional, Regidor).
# ═══════════════════════════════════════════════════════════════════════════════

# Each spec: (cargo_filter_or_None, ambito_filter_or_None, display_label, group_label, is_lead)
# Note: Regional list members have AMBITO='CONSEJERO REGIONAL' but CARGO in
#       {TITULAR, ACCESITARIO, REEMPLAZANTE} — no CARGO called "CONSEJERO REGIONAL"
CARGO_SPECS = [
    ('GOBERNADOR',         'GOBERNADOR Y VICEGOBERNADOR', 'Gobernador',         'Regional',        True),
    (None,                 'CONSEJERO REGIONAL',           'Consejero Regional', 'Regional',        False),
    ('ALCALDE PROVINCIAL', 'MUNICIPAL PROVINCIAL',         'Alcalde Provincial', 'Mun. Provincial', True),
    ('REGIDOR',            'MUNICIPAL PROVINCIAL',         'Regidor Provincial', 'Mun. Provincial', False),
    ('ALCALDE DISTRITAL',  'MUNICIPAL DISTRITAL',          'Alcalde Distrital',  'Mun. Distrital',  True),
    ('REGIDOR',            'MUNICIPAL DISTRITAL',          'Regidor Distrital',  'Mun. Distrital',  False),
]

rows = []
for cargo, ambito, label, group, is_lead in CARGO_SPECS:
    mask = pd.Series([True] * len(df), index=df.index)
    if cargo:
        mask &= df['CARGO'] == cargo
    if ambito:
        mask &= df['AMBITO'] == ambito
    total = mask.sum()
    d     = (mask & is_desig).sum()
    rows.append({
        'label':   label,
        'group':   group,
        'is_lead': is_lead,
        'total':   total,
        'desig':   d,
        'pct':     d / total * 100 if total else 0,
    })

cargo_df = pd.DataFrame(rows)
print("\nDESIGNADO by cargo type:")
print(cargo_df[['label','total','desig','pct']].to_string(index=False))

# Horizontal bar chart, grouped visually by level
fig, ax = plt.subplots(figsize=(11, 6))
y = np.arange(len(cargo_df))

colors = [TERRA if r['is_lead'] else BLUE for _, r in cargo_df.iterrows()]
bars = ax.barh(y, cargo_df['pct'], color=colors, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.6)

for i, (_, row) in enumerate(cargo_df.iterrows()):
    ax.text(row['pct'] + 0.4, i,
            f"{row['pct']:.1f}%  (n={row['total']:,})",
            va='center', ha='left', fontsize=9, color=MUTED)

ax.set_yticks(y)
ax.set_yticklabels(cargo_df['label'], fontsize=10)
ax.set_xlabel('% de candidaturas marcadas DESIGNADO', fontsize=10, labelpad=8)
ax.set_xlim(right=max(cargo_df['pct']) * 1.55)
ax.set_title('Candidaturas DESIGNADO: más concentradas en las cabezas de lista',
             fontsize=12, fontweight='bold', pad=12)

# Visual group separators
group_ends = [1, 3, 5]  # after index 1, 3, 5
for ge in group_ends[:-1]:
    ax.axhline(ge + 0.5, color=BORDER, lw=1.0, ls='--', alpha=0.6)

# Group labels on the right side
group_info = [
    (0.5,  'REGIONAL'),
    (2.5,  'MUN. PROVINCIAL'),
    (4.5,  'MUN. DISTRITAL'),
]
for gy, gtxt in group_info:
    ax.text(ax.get_xlim()[1] * 0.97, gy, gtxt,
            va='center', ha='right', fontsize=7.5, fontweight='bold',
            color=MUTED, alpha=0.7)

# Legend
from matplotlib.patches import Patch
leg_elements = [
    Patch(facecolor=TERRA, alpha=0.85, label='Cabeza de lista (Gobernador / Alcalde)'),
    Patch(facecolor=BLUE,  alpha=0.85, label='Resto de lista (Consejero / Regidor)'),
]
ax.legend(handles=leg_elements, fontsize=9, loc='lower right', framealpha=0.85, facecolor=BG)

fig.tight_layout()
fig.savefig('figures/fig2_designado_por_cargo.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig2")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 3 — Gobernador coverage by party (# departamentos)
#
# INCLUDES DESIGNADO: a party with a DESIGNADO gobernador still intends to
# compete in that region — someone will eventually be named.
# Uses .nunique() on REGION to avoid double-counting parties with multiple
# formulae in the same region.
# ═══════════════════════════════════════════════════════════════════════════════
gov_all = df[df['CARGO'] == 'GOBERNADOR']
gov_cov = gov_all.groupby('PRESENTACION')['REGION'].nunique().sort_values(ascending=True).tail(20)
ylabels3 = [short(p) for p in gov_cov.index]

fig, ax = plt.subplots(figsize=(11, 7.5))
colors3 = [TERRA if v == 24 else (ORANGE if v >= 15 else BLUE) for v in gov_cov.values]
bars = ax.barh(ylabels3, gov_cov.values, color=colors3, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.65)
N_REGIONS = gov_all['REGION'].nunique()  # 25 in ONPE data (24 depts + Callao as own region)
ax.axvline(N_REGIONS, color=MUTED, lw=1.2, ls='--', alpha=0.6,
           label=f'{N_REGIONS} regiones (total)')
for bar, val in zip(bars, gov_cov.values):
    ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2,
            str(val), va='center', ha='left', fontsize=9, color=MUTED)
ax.set_xlabel('Regiones con candidato a Gobernador (incl. DESIGNADO)', fontsize=10, labelpad=8)
ax.set_title('Cobertura regional — candidatos a Gobernador por partido\n(top 20, incluye DESIGNADO)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=N_REGIONS + 3)
ax.legend(fontsize=9, framealpha=0.85, facecolor=BG)
fig.tight_layout()
fig.savefig('figures/fig3_cobertura_gobernador.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig3")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 4 — Alcalde distrital coverage by party
#
# Universe: 1,696 alcaldías distritales en contienda
#   = 1,892 distritos totales − 196 capitales provinciales
#   (cada capital de provincia no elige alcalde distrital separado)
#
# INCLUDES DESIGNADO. drop_duplicates() on (REGION, PROVINCIA, DISTRITO)
# prevents double-counting when a party registers multiple candidatos per
# circunscripción (e.g. Acción Popular with internal primaries).
# ═══════════════════════════════════════════════════════════════════════════════
TOTAL_ALCALDIAS_DISTRITALES = 1_696   # 1,892 − 196 provincial capitals

alcd_all = df[df['CARGO'] == 'ALCALDE DISTRITAL']
alcd_cov = (alcd_all
            .groupby('PRESENTACION')
            .apply(lambda x: x[['REGION','PROVINCIA','DISTRITO']].drop_duplicates().shape[0],
                   include_groups=False)
            .sort_values(ascending=True)
            .tail(20))
ylabels4 = [short(p) for p in alcd_cov.index]

fig, ax = plt.subplots(figsize=(11, 7.5))
bars = ax.barh(ylabels4, alcd_cov.values, color=GREEN, alpha=0.85,
               edgecolor='white', linewidth=0.5, height=0.65)
ax.axvline(TOTAL_ALCALDIAS_DISTRITALES, color=MUTED, lw=1.2, ls='--', alpha=0.6,
           label=f'{TOTAL_ALCALDIAS_DISTRITALES:,} alcaldías en contienda')
for bar, val in zip(bars, alcd_cov.values):
    pct = val / TOTAL_ALCALDIAS_DISTRITALES * 100
    ax.text(bar.get_width() + 8, bar.get_y() + bar.get_height()/2,
            f'{val:,}  ({pct:.0f}%)', va='center', ha='left', fontsize=8.5, color=MUTED)
ax.set_xlabel('Distritos con candidato a Alcalde Distrital (incl. DESIGNADO)', fontsize=10, labelpad=8)
ax.set_title('Cobertura distrital — alcaldes por partido · primarias ERM 2026\n(top 20, incluye DESIGNADO)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=TOTAL_ALCALDIAS_DISTRITALES * 1.22)
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
ax.legend(fontsize=9, framealpha=0.85, facecolor=BG)
fig.tight_layout()
fig.savefig('figures/fig4_cobertura_distrital_partido.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig4")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 5 — Competition intensity by region
#
# With DESIGNADO included, nearly all contested alcaldías distritales have at
# least one competing party — so "coverage" per region becomes trivially close
# to 100%. The more informative cut is competition intensity: on average, how
# many distinct parties contest each district in each region?
#
# We compute the number of unique parties per (REGION, PROVINCIA, DISTRITO)
# then average by REGION.
# ═══════════════════════════════════════════════════════════════════════════════
parties_per_dist = (alcd_all
                    .groupby(['REGION','PROVINCIA','DISTRITO'])['PRESENTACION']
                    .nunique()
                    .rename('n_parties'))

avg_competition = parties_per_dist.groupby(level='REGION').mean().sort_values(ascending=True)
n_districts_reg = parties_per_dist.groupby(level='REGION').count()

print("\nCompetition intensity by region (avg parties per district):")
for r in avg_competition.index:
    print(f"  {r:<25}  {avg_competition[r]:.2f} partidos/dist  ({n_districts_reg[r]} distritos)")

fig, ax = plt.subplots(figsize=(11, 9))
y = np.arange(len(avg_competition))
bars = ax.barh(y, avg_competition.values, color=BLUE, alpha=0.85,
               edgecolor='white', linewidth=0.4, height=0.7)
for i, (region, val) in enumerate(avg_competition.items()):
    nd = n_districts_reg[region]
    ax.text(val + 0.03, i,
            f'{val:.1f}  ({nd} distritos en contienda)',
            va='center', ha='left', fontsize=8.5, color=MUTED)

ax.set_yticks(y)
ax.set_yticklabels(avg_competition.index, fontsize=9)
ax.set_xlabel('Promedio de partidos con candidato a Alcalde Distrital por distrito', fontsize=10, labelpad=8)
ax.set_title('Intensidad de competencia distrital por región · primarias ERM 2026\n'
             '(partidos distintos compitiendo por alcaldía, en promedio por distrito)',
             fontsize=12, fontweight='bold', pad=12)
ax.set_xlim(right=max(avg_competition.values) * 1.35)
fig.tight_layout()
fig.savefig('figures/fig5_competencia_distrital_region.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig5")


print(f"\n✓ All figures → figures/")
print(f"\n=== KEY NUMBERS FOR ARTICLE ===")
print(f"Total candidaturas:          {len(df):,}")
print(f"Con nombre:                  {len(named):,}  ({len(named)/len(df)*100:.1f}%)")
print(f"DESIGNADO:                   {len(desig):,}  ({len(desig)/len(df)*100:.1f}%)")
print(f"Partidos:                    {df['PRESENTACION'].nunique()}")

# Gobernador
gov_desig = desig[desig['CARGO']=='GOBERNADOR']
gov_total = df[df['CARGO']=='GOBERNADOR']
print(f"\nGobernadores totales:        {len(gov_total):,}")
print(f"Gobernadores DESIGNADO:      {len(gov_desig):,}  ({len(gov_desig)/len(gov_total)*100:.1f}%)")
print(f"Regiones cubiertas (gob):    {gov_all['REGION'].nunique()} total en el padrón")

# Alcalde Provincial
alcp_all   = df[df['CARGO']=='ALCALDE PROVINCIAL']
alcp_desig = desig[desig['CARGO']=='ALCALDE PROVINCIAL']
print(f"\nAlcaldes Provinciales total: {len(alcp_all):,}")
print(f"Alcaldes Prov. DESIGNADO:    {len(alcp_desig):,}  ({len(alcp_desig)/len(alcp_all)*100:.1f}%)")
print(f"Provincias cubiertas (alcp): {alcp_all[['REGION','PROVINCIA']].drop_duplicates().shape[0]} / 196")

# Alcalde Distrital
alcd_desig_n = desig[desig['CARGO']=='ALCALDE DISTRITAL']
contested_dist = alcd_all[['REGION','PROVINCIA','DISTRITO']].drop_duplicates()
print(f"\nAlcaldes Distritales total:  {len(alcd_all):,}")
print(f"Alcaldes Dist. DESIGNADO:    {len(alcd_desig_n):,}  ({len(alcd_desig_n)/len(alcd_all)*100:.1f}%)")
print(f"Distritos en contienda:      {TOTAL_ALCALDIAS_DISTRITALES:,}  (1892 − 196 cap. provinciales)")
print(f"Distritos con candidato:     {len(contested_dist):,}  ({len(contested_dist)/TOTAL_ALCALDIAS_DISTRITALES*100:.1f}%)")
print(f"Distritos sin candidato:     {TOTAL_ALCALDIAS_DISTRITALES - len(contested_dist)}")
