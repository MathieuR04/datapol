"""
analyze_recount_full.py
=======================
Extended analysis across all candidates.
Produces fig5, fig6, fig7 in data/figures/.

Run: python3 analyze_recount_full.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from scipy import stats
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
FP  = 'FUERZA POPULAR'
JPP = 'JUNTOS POR EL PERÚ'
RP  = 'RENOVACIÓN POPULAR'

COLORS_MAIN = {
    FP:  '#E85C1A',
    JPP: '#2E9B57',
    RP:  '#4A8FCA',
}
COLOR_GRAY = '#AAAAAA'

EXCLUDE_POSICION = {80, 81, 99}  # blancos, nulos, total
EXCLUDE_NAMES = {
    'FRENTE POPULAR AGRÍCOLA FÍA DEL PERÚ',
    'PARTIDO CIUDADANOS POR EL PERÚ',
    'VOTOS EN BLANCO',
    'VOTOS NULOS',
    'TOTAL DE CIUDADANOS QUE VOTARON',
}

SHORT_NAMES = {
    'ALIANZA ELECTORAL VENCEREMOS':                              'Venceremos',
    'PARTIDO PATRIÓTICO DEL PERÚ':                              'Pat. Perú',
    'PARTIDO CÍVICO OBRAS':                                     'Cív. Obras',
    'PARTIDO DEMÓCRATA VERDE':                                  'Dem. Verde',
    'PARTIDO DEL BUEN GOBIERNO':                                'Buen Gob.',
    'PARTIDO POLÍTICO PERÚ ACCIÓN':                             'Perú Acción',
    'PARTIDO POLÍTICO PRIN':                                    'PRIN',
    'PROGRESEMOS':                                              'Progresemos',
    'PARTIDO SICREO':                                           'Sicreo',
    'PARTIDO PAÍS PARA TODOS':                                  'País p/ Todos',
    'PARTIDO FRENTE DE LA ESPERANZA 2021':                      'Esperanza 2021',
    'PARTIDO POLÍTICO NACIONAL PERÚ LIBRE':                     'Perú Libre',
    'PRIMERO LA GENTE – COMUNIDAD, ECOLOGÍA, LIBERTAD Y PROGRESO': 'Primero la Gente',
    FP:                                                          'Fuerza Popular\n(Keiko)',
    JPP:                                                         'Juntos x Perú\n(Sánchez)',
    'PODEMOS PERÚ':                                             'Podemos Perú',
    'PARTIDO DEMOCRATICO FEDERAL':                              'Dem. Federal',
    'FE EN EL PERÚ':                                            'Fe en el Perú',
    'PARTIDO POLÍTICO INTEGRIDAD DEMOCRÁTICA':                  'Integridad Dem.',
    'ALIANZA PARA EL PROGRESO':                                 'Al. Progreso',
    'PARTIDO POLÍTICO COOPERACIÓN POPULAR':                     'Coop. Popular',
    'AHORA NACIÓN - AN':                                        'Ahora Nación',
    'LIBERTAD POPULAR':                                         'Libertad Pop.',
    'UN CAMINO DIFERENTE':                                      'Un Camino Dif.',
    'AVANZA PAÍS - PARTIDO DE INTEGRACIÓN SOCIAL':              'Avanza País',
    'PERÚ MODERNO':                                             'Perú Moderno',
    'PARTIDO POLÍTICO PERÚ PRIMERO':                            'Perú Primero',
    'SALVEMOS AL PERÚ':                                         'Salvemos Perú',
    'PARTIDO DEMOCRÁTICO SOMOS PERÚ':                           'Somos Perú',
    'PARTIDO APRISTA PERUANO':                                  'APRA',
    RP:                                                          'Renov. Popular\n(López Aliaga)',
    'PARTIDO DEMÓCRATA UNIDO PERÚ':                             'Dem. Unido',
    'FUERZA Y LIBERTAD':                                        'Fuerza y Lib.',
    'PARTIDO DE LOS TRABAJADORES Y EMPRENDEDORES PTE - PERÚ':  'PTE-Perú',
    'UNIDAD NACIONAL':                                          'Unidad Nac.',
    'PARTIDO MORADO':                                           'Partido Morado',
}

Path('data/figures').mkdir(parents=True, exist_ok=True)

BG = '#f5f0e8'

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
    'text.color':        '#1a1209',
    'axes.labelcolor':   '#1a1209',
    'xtick.color':       '#1a1209',
    'ytick.color':       '#1a1209',
    'axes.edgecolor':    '#cfc0ab',
})


def sig_label(p):
    if p < 0.001: return '***'
    if p < 0.01:  return '**'
    if p < 0.05:  return '*'
    return 'n.s.'


# ── Load & filter ─────────────────────────────────────────────────────────────
df = pd.read_csv('data/recount_analysis_all.csv')
df['mesa_id'] = df['mesa_id'].astype(str).str.zfill(6)

# Drop excluded parties
df = df[~df['partido_nombre'].isin(EXCLUDE_NAMES)].copy()
df = df[~df['partido_posicion'].isin(EXCLUDE_POSICION)].copy()

# Same filter as analyze_recount.py: drop mesas where ALL candidates are 0/NA
# in pre-recount OR in post-recount. Use wide pivot on the three anchor parties
# to replicate the original logic exactly.
wide = df.pivot(index='mesa_id', columns='partido_nombre',
                values=['votos_pre_recount', 'votos_post_recount', 'delta'])
wide.columns = ['_'.join(c) for c in wide.columns]
wide = wide.reset_index()

all_pre_zero  = (wide[[c for c in wide.columns if c.startswith('votos_pre_recount_')]]
                 .fillna(0) == 0).all(axis=1)
all_post_zero = (wide[[c for c in wide.columns if c.startswith('votos_post_recount_')]]
                 .fillna(0) == 0).all(axis=1)

wide_clean  = wide[~all_pre_zero & ~all_post_zero].copy()
valid_mesas = set(wide_clean['mesa_id'])
df          = df[df['mesa_id'].isin(valid_mesas)].dropna(subset=['delta']).copy()

print(f"Mesas: {len(wide)} total, {len(wide)-len(wide_clean)} dropped, {len(wide_clean)} analyzed")
print(f"Parties: {df['partido_nombre'].nunique()}\n")

# ── Compute per-party stats ───────────────────────────────────────────────────
party_stats = {}
for party, grp in df.groupby('partido_nombre'):
    d = grp['delta'].dropna().values
    if len(d) < 10:
        continue
    t, pv = stats.ttest_1samp(d, 0)
    ci = stats.t.interval(0.95, df=len(d)-1, loc=np.mean(d), scale=stats.sem(d))
    party_stats[party] = dict(n=len(d), mean=np.mean(d), ci=ci, t=t, p=pv)

# Sort by mean delta descending
sorted_parties = sorted(party_stats.keys(), key=lambda p: party_stats[p]['mean'], reverse=True)

# ── Print summary ─────────────────────────────────────────────────────────────
print("=" * 70)
print("ONE-SAMPLE t-TEST  H₀: μ_delta = 0  — all candidates")
print("=" * 70)
for p in sorted_parties:
    r = party_stats[p]
    sig = sig_label(r['p'])
    print(f"{p[:50]:<50} μ={r['mean']:+.3f}  95%CI=[{r['ci'][0]:+.3f},{r['ci'][1]:+.3f}]"
          f"  p={r['p']:.4f} {sig}")
print()



# ═══════════════════════════════════════════════════════════════════════════════
# FIG 5 — Horizontal mean delta + CI, most benefited at top
# ═══════════════════════════════════════════════════════════════════════════════
from matplotlib.patches import Patch

sorted_parties = sorted(party_stats.keys(), key=lambda p: party_stats[p]['mean'])

fig, ax = plt.subplots(figsize=(11, 13))
ylabels    = [SHORT_NAMES.get(p, p) for p in sorted_parties]
means      = [party_stats[p]['mean'] for p in sorted_parties]
ci_lo      = [party_stats[p]['mean'] - party_stats[p]['ci'][0] for p in sorted_parties]
ci_hi      = [party_stats[p]['ci'][1] - party_stats[p]['mean'] for p in sorted_parties]
bar_colors = [COLORS_MAIN.get(p, COLOR_GRAY) for p in sorted_parties]
y_pos = np.arange(len(sorted_parties))

ax.barh(y_pos, means, color=bar_colors, alpha=0.88, edgecolor='white', linewidth=0.6, height=0.65)
ax.errorbar(means, y_pos, xerr=[ci_lo, ci_hi],
            fmt='none', color='#333', capsize=3.5, capthick=1.3, lw=1.4)
ax.axvline(0, color='#555', lw=1.2, ls='--', alpha=0.7)

x_max = max(m + e for m, e in zip(means, ci_hi))
for i, (p, m, chi) in enumerate(zip(sorted_parties, means, ci_hi)):
    r = party_stats[p]
    ax.text(m + chi + 0.04, i, sig_label(r['p']),
            va='center', ha='left', fontsize=8, color='#333', fontweight='bold')
    ax.text(x_max + 0.20, i,
            f"mu={m:+.2f}  [{r['ci'][0]:+.2f}, {r['ci'][1]:+.2f}]",
            va='center', ha='left', fontsize=7.5, color='#444')

ax.set_yticks(y_pos); ax.set_yticklabels(ylabels, fontsize=9)
ax.set_xlabel('Delta promedio de votos por mesa', fontsize=11, labelpad=8)
ax.set_title('Cambio promedio de votos en el recuento - todos los candidatos\n(intervalo de confianza al 95%)',
             fontsize=12, fontweight='bold', pad=12)
ax.legend(handles=[
    Patch(facecolor=COLORS_MAIN[FP],  label='Fuerza Popular (Keiko Fujimori)'),
    Patch(facecolor=COLORS_MAIN[RP],  label='Renovacion Popular (Lopez Aliaga)'),
    Patch(facecolor=COLORS_MAIN[JPP], label='Juntos por el Peru (Sanchez)'),
    Patch(facecolor=COLOR_GRAY,       label='Otros candidatos'),
], fontsize=9, loc='lower right', framealpha=0.9)
ax.set_xlim(right=x_max + 2.2)

fig.tight_layout()
fig.savefig('data/figures/fig5_all_candidates_delta.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig5_all_candidates_delta.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 6 — Error aritmetico original vs cambio absoluto del recuento
# ═══════════════════════════════════════════════════════════════════════════════
df_full = pd.read_csv('data/recount_analysis_all.csv')
df_full['mesa_id'] = df_full['mesa_id'].astype(str).str.zfill(6)
df_full = df_full[df_full['mesa_id'].isin(valid_mesas)].copy()

parties_pre   = df_full[df_full['partido_posicion'] < 80].groupby('mesa_id')['votos_pre_recount'].sum()
blanknulo_pre = df_full[df_full['partido_posicion'].isin([80, 81])].groupby('mesa_id')['votos_pre_recount'].sum()
total_pre     = df_full[df_full['partido_posicion'] == 99].groupby('mesa_id')['votos_pre_recount'].first()
orig_disc     = (parties_pre.add(blanknulo_pre, fill_value=0) - total_pre).abs().dropna()
recount_chg   = (df_full[df_full['partido_posicion'] < 82]
                 .groupby('mesa_id')['delta']
                 .apply(lambda x: x.abs().sum()))
compare = pd.DataFrame({'orig': orig_disc, 'recount': recount_chg}).dropna()
t6, p6 = stats.ttest_rel(compare['recount'], compare['orig'])

print(f"\nFig 6: orig={compare['orig'].mean():.2f}, recount={compare['recount'].mean():.2f}, "
      f"t={t6:.3f}, p={p6:.4f} {sig_label(p6)}")

fig, ax = plt.subplots(figsize=(8, 6))
vals   = [compare['orig'].values, compare['recount'].values]
means6 = [v.mean() for v in vals]
cis6   = [stats.t.interval(0.95, df=len(v)-1, loc=v.mean(), scale=stats.sem(v)) for v in vals]
ci_lo6 = [m - ci[0] for m, ci in zip(means6, cis6)]
ci_hi6 = [ci[1] - m for m, ci in zip(means6, cis6)]
xlbls6 = ['Error aritmetico\nen acta original\n|Sigma votos - total|',
           'Cambio absoluto\ntotal del recuento\nSigma|Delta| por mesa']
ax.bar(xlbls6, means6, color=['#999', '#E85C1A'], alpha=0.88, edgecolor='white', linewidth=0.8, width=0.45)
ax.errorbar(xlbls6, means6, yerr=[ci_lo6, ci_hi6],
            fmt='none', color='#111', capsize=9, capthick=1.8, lw=2)
ci_tops6 = [m + e for m, e in zip(means6, ci_hi6)]
pad6 = max(ci_hi6) * 0.12
for i, (m, ct, ci) in enumerate(zip(means6, ci_tops6, cis6)):
    lines = ([sig_label(p6)] if i == 1 else []) + [f"mu = {m:.2f}", f"95% CI [{ci[0]:.2f}, {ci[1]:.2f}]"]
    ax.text(i, ct + pad6, '\n'.join(lines), ha='center', va='bottom', fontsize=9, color='#222', linespacing=1.5)
ax.set_ylabel('Votos por mesa', fontsize=11)
ax.set_title('Error aritmetico original vs. cambio absoluto del recuento\n(intervalo de confianza al 95%)',
             fontsize=12, fontweight='bold', pad=10)
ax.set_ylim(bottom=0, top=max(ci_tops6) + max(ci_hi6) * 2.5)
fig.tight_layout()
fig.savefig('data/figures/fig6_discrepancy_vs_recount.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig6_discrepancy_vs_recount.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 7 -- Two panels: log-scale scatter + residual plot showing Keiko as outlier
# ═══════════════════════════════════════════════════════════════════════════════
df_p = df.dropna(subset=["delta", "votos_post_recount"]).copy()
party_sum = df_p.groupby("partido_nombre").agg(
    mean_votes=("votos_post_recount", "mean"),
    mean_delta=("delta", "mean"),
    n=("delta", "count")
).reset_index()
party_sum = party_sum[party_sum["n"] >= 50]
party_sum["log_votes"] = np.log1p(party_sum["mean_votes"])

fp_row  = party_sum[party_sum["partido_nombre"] == FP].iloc[0]
jpp_row = party_sum[party_sum["partido_nombre"] == JPP].iloc[0]
rp_row  = party_sum[party_sum["partido_nombre"] == RP].iloc[0]

# Trend on all parties (log)
slope_all, intercept_all, r_all, _, se_all = stats.linregress(
    party_sum["log_votes"], party_sum["mean_delta"])
t_all  = slope_all / se_all
p_all  = 2 * stats.t.sf(abs(t_all), df=len(party_sum)-2)

# Trend on non-Keiko only
others = party_sum[party_sum["partido_nombre"] != FP]
slope_o, intercept_o, r_o, _, se_o = stats.linregress(
    others["log_votes"], others["mean_delta"])
t_o   = slope_o / se_o
p_o   = 2 * stats.t.sf(abs(t_o), df=len(others)-2)

fp_predicted = intercept_o + slope_o * fp_row["log_votes"]
fp_residual  = fp_row["mean_delta"] - fp_predicted

print(f"Fig 7 (all):   beta={slope_all:.4f}, p={p_all:.4f}, r={r_all:.3f}")
print(f"Fig 7 (no-FP): beta={slope_o:.4f},  p={p_o:.4f}, r={r_o:.3f}")
keiko_actual = fp_row["mean_delta"]
print(f"Keiko predicted={fp_predicted:.3f}, actual={keiko_actual:.3f}, residual={fp_residual:.3f}")

labels7 = {FP: "Fuerza Popular\n(Keiko)",
           JPP: "Juntos x Peru\n(Sanchez)",
           RP:  "Renov. Popular\n(Lopez Aliaga)"}

def scatter_all(ax):
    for _, row in party_sum.iterrows():
        p = row["partido_nombre"]
        color = COLORS_MAIN.get(p, COLOR_GRAY)
        ax.scatter(row["log_votes"], row["mean_delta"],
                   color=color, s=(90 if p in COLORS_MAIN else 45),
                   alpha=(0.9 if p in COLORS_MAIN else 0.55),
                   zorder=3, edgecolors="white", linewidths=0.5)

def annotate_three(ax):
    ann = {
        FP:  ((fp_row["log_votes"]-0.8,   fp_row["mean_delta"]+0.15),  fp_row),
        JPP: ((jpp_row["log_votes"]+0.1,  jpp_row["mean_delta"]-0.2),  jpp_row),
        RP:  ((rp_row["log_votes"]+0.1,   rp_row["mean_delta"]+0.15),  rp_row),
    }
    for p, (xytext, row) in ann.items():
        ax.annotate(labels7[p], xy=(row["log_votes"], row["mean_delta"]),
                    xytext=xytext, fontsize=8.5, fontweight="bold", color=COLORS_MAIN[p],
                    arrowprops=dict(arrowstyle="->", color=COLORS_MAIN[p], lw=1.2),
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=COLORS_MAIN[p], alpha=0.85))

x_log = np.linspace(party_sum["log_votes"].min(), party_sum["log_votes"].max(), 200)

fig, axes = plt.subplots(1, 2, figsize=(14, 7))
fig.suptitle("Mas votos implica mas distorsion en el recuento?",
             fontsize=13, fontweight="bold", y=1.01)

# -- Left: all parties, trend on all ----------------------------------------
ax = axes[0]
scatter_all(ax)
ax.plot(x_log, intercept_all + slope_all * x_log, color="#555", lw=1.8, ls="--", zorder=2,
        label=f"Tendencia (todos)  beta={slope_all:.3f}  p={p_all:.3f} {sig_label(p_all)}")
ax.axhline(0, color="#888", lw=0.8, ls=":", alpha=0.6)
annotate_three(ax)
ax.set_xlabel("log(votos promedio por mesa + 1)", fontsize=10)
ax.set_ylabel("Delta promedio de votos por mesa", fontsize=10)
ax.set_title("Tendencia general (escala log)", fontsize=11, fontweight="bold")
ax.legend(fontsize=8, loc="upper left", framealpha=0.88)

# -- Right: trend on non-Keiko, Keiko residual shown -------------------------
ax = axes[1]
for _, row in others.iterrows():
    p = row["partido_nombre"]
    color = COLORS_MAIN.get(p, COLOR_GRAY)
    ax.scatter(row["log_votes"], row["mean_delta"],
               color=color, s=(90 if p in COLORS_MAIN else 45),
               alpha=(0.9 if p in COLORS_MAIN else 0.55),
               zorder=3, edgecolors="white", linewidths=0.5)

ax.plot(x_log, intercept_o + slope_o * x_log, color="#555", lw=1.8, ls="--", zorder=2,
        label=f"Tendencia (sin Keiko)  beta={slope_o:.3f}  p={p_o:.3f} {sig_label(p_o)}")
ax.axhline(0, color="#888", lw=0.8, ls=":", alpha=0.6)

# Keiko: hollow predicted + filled actual + residual arrow
ax.scatter(fp_row["log_votes"], fp_predicted,
           s=90, facecolors="none", edgecolors=COLORS_MAIN[FP], linewidths=1.8, zorder=3)
ax.scatter(fp_row["log_votes"], fp_row["mean_delta"],
           color=COLORS_MAIN[FP], s=90, alpha=0.9, zorder=4, edgecolors="white", linewidths=0.5)
ax.annotate("", xy=(fp_row["log_votes"], fp_row["mean_delta"]),
            xytext=(fp_row["log_votes"], fp_predicted),
            arrowprops=dict(arrowstyle="->", color=COLORS_MAIN[FP], lw=2))
ax.text(fp_row["log_votes"]+0.08, (fp_row["mean_delta"]+fp_predicted)/2,
        f"Residual\n+{fp_residual:.2f}",
        fontsize=8.5, color=COLORS_MAIN[FP], va="center", fontweight="bold")
ax.annotate(labels7[FP],
            xy=(fp_row["log_votes"], fp_row["mean_delta"]),
            xytext=(fp_row["log_votes"]-0.8, fp_row["mean_delta"]+0.15),
            fontsize=8.5, fontweight="bold", color=COLORS_MAIN[FP],
            arrowprops=dict(arrowstyle="->", color=COLORS_MAIN[FP], lw=1.2),
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=COLORS_MAIN[FP], alpha=0.85))

for p, row in [(JPP, jpp_row), (RP, rp_row)]:
    offsets = {
        JPP: (jpp_row["log_votes"]+0.1, jpp_row["mean_delta"]-0.2),
        RP:  (rp_row["log_votes"]+0.1,  rp_row["mean_delta"]+0.15),
    }
    ax.annotate(labels7[p], xy=(row["log_votes"], row["mean_delta"]),
                xytext=offsets[p], fontsize=8.5, fontweight="bold", color=COLORS_MAIN[p],
                arrowprops=dict(arrowstyle="->", color=COLORS_MAIN[p], lw=1.2),
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=COLORS_MAIN[p], alpha=0.85))

ax.set_xlabel("log(votos promedio por mesa + 1)", fontsize=10)
ax.set_ylabel("", fontsize=10)
ax.set_title("Desviacion de Keiko respecto a la tendencia", fontsize=11, fontweight="bold")
ax.legend(fontsize=8, loc="upper left", framealpha=0.88)

fig.tight_layout()
fig.savefig("data/figures/fig7_votes_vs_delta_party.png", bbox_inches="tight", dpi=150)
plt.close()
print("Saved fig7_votes_vs_delta_party.png")

print("\nAll figures -> data/figures/")
