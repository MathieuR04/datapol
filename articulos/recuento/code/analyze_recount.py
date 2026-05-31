"""
analyze_recount_v2.py
=====================
Improved figures for the recount delta analysis.
Produces fig1–fig4 in data/figures/.

Run: python3 analyze_recount_v2.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyArrowPatch
from scipy import stats
from pathlib import Path

FP  = 'FUERZA POPULAR'
JPP = 'JUNTOS POR EL PERÚ'
RP  = 'RENOVACIÓN POPULAR'

COLORS = {
    FP:  '#E85C1A',
    JPP: '#2E9B57',
    RP:  '#4A8FCA',
}
SHORT = {
    FP:  'Fuerza Popular\n(Keiko Fujimori)',
    JPP: 'Juntos por el Perú\n(Roberto Sánchez)',
    RP:  'Renovación Popular\n(López Aliaga)',
}
SHORT1 = {
    FP:  'Keiko Fujimori',
    JPP: 'Roberto Sánchez',
    RP:  'López Aliaga',
}
PARTIES = [FP, JPP, RP]

Path('data/figures').mkdir(parents=True, exist_ok=True)

BG = '#f5f0e8'

plt.rcParams.update({
    'font.family':       'DejaVu Sans',
    'axes.spines.top':   False,
    'axes.spines.right': False,
    'figure.dpi':        150,
    'axes.labelsize':    11,
    'xtick.labelsize':   10,
    'ytick.labelsize':   10,
    'figure.facecolor':  BG,
    'axes.facecolor':    BG,
    'text.color':        '#1a1209',
    'axes.labelcolor':   '#1a1209',
    'xtick.color':       '#1a1209',
    'ytick.color':       '#1a1209',
    'axes.edgecolor':    '#cfc0ab',
})

# ── Load & filter ─────────────────────────────────────────────────────────────
df = pd.read_csv('data/recount_analysis.csv')
df['mesa_id'] = df['mesa_id'].astype(str).str.zfill(6)

wide = df.pivot(index='mesa_id', columns='partido_nombre',
                values=['votos_pre_recount', 'votos_post_recount', 'delta'])
wide.columns = ['_'.join(c) for c in wide.columns]
wide = wide.reset_index()

all_pre_zero  = ((wide[f'votos_pre_recount_{FP}']==0) &
                 (wide[f'votos_pre_recount_{JPP}']==0) &
                 (wide[f'votos_pre_recount_{RP}']==0))
all_post_zero = ((wide[f'votos_post_recount_{FP}']==0) &
                 (wide[f'votos_post_recount_{JPP}']==0) &
                 (wide[f'votos_post_recount_{RP}']==0))

wide_clean = wide[~all_pre_zero & ~all_post_zero].copy()
df_clean   = df[df['mesa_id'].isin(wide_clean['mesa_id'])].dropna(subset=['delta'])

print(f"Mesas: {len(wide)} total, {len(wide)-len(wide_clean)} dropped, {len(wide_clean)} analyzed\n")

def deltas(party):
    return df_clean[df_clean['partido_nombre'] == party]['delta'].values

# ── Compute stats ─────────────────────────────────────────────────────────────
sr = {}
for p in PARTIES:
    d = deltas(p)
    t, pv = stats.ttest_1samp(d, 0)
    ci = stats.t.interval(0.95, df=len(d)-1, loc=np.mean(d), scale=stats.sem(d))
    sr[p] = dict(n=len(d), mean=np.mean(d), std=np.std(d), t=t, p=pv, ci=ci)

d_fp  = df_clean[df_clean['partido_nombre']==FP ][['mesa_id','delta']].set_index('mesa_id').rename(columns={'delta':'d_fp'})
d_jpp = df_clean[df_clean['partido_nombre']==JPP][['mesa_id','delta']].set_index('mesa_id').rename(columns={'delta':'d_jpp'})
d_rp  = df_clean[df_clean['partido_nombre']==RP ][['mesa_id','delta']].set_index('mesa_id').rename(columns={'delta':'d_rp'})
paired = d_fp.join(d_jpp).join(d_rp).dropna()
paired['margin_fp_jpp'] = paired['d_fp'] - paired['d_jpp']
paired['margin_fp_rp']  = paired['d_fp'] - paired['d_rp']
paired['margin_jpp_rp'] = paired['d_jpp'] - paired['d_rp']

mr = {}
for label, col in [('Keiko − Sánchez', 'margin_fp_jpp'),
                   ('Keiko − López Aliaga', 'margin_fp_rp'),
                   ('Sánchez − López Aliaga', 'margin_jpp_rp')]:
    d = paired[col].values
    t, pv = stats.ttest_1samp(d, 0)
    ci = stats.t.interval(0.95, df=len(d)-1, loc=np.mean(d), scale=stats.sem(d))
    mr[col] = dict(label=label, n=len(d), mean=np.mean(d), ci=ci, t=t, p=pv)


def sig_label(p):
    if p < 0.001: return '***'
    if p < 0.01:  return '**'
    if p < 0.05:  return '*'
    return 'n.s.'


# ── Print results ─────────────────────────────────────────────────────────────
print("=" * 60)
print("1. ONE-SAMPLE t-TEST  H₀: μ_delta = 0")
print("=" * 60)
for p in PARTIES:
    r = sr[p]
    sig = sig_label(r['p'])
    print(f"\n{SHORT[p].replace(chr(10), ' ')}: n={r['n']}, μ={r['mean']:.3f}, "
          f"95%CI=[{r['ci'][0]:.3f},{r['ci'][1]:.3f}], t={r['t']:.3f}, p={r['p']:.4f} {sig}")

print("\n" + "=" * 60)
print("2. MARGIN TEST  H₀: Δ(margin) = 0")
print("=" * 60)
for col, r in mr.items():
    sig = sig_label(r['p'])
    print(f"\n{r['label']}: n={r['n']}, μ={r['mean']:.3f}, "
          f"95%CI=[{r['ci'][0]:.3f},{r['ci'][1]:.3f}], t={r['t']:.3f}, p={r['p']:.4f} {sig}")
print()


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 1 — Histograms (integer bins, clean layout, no overlap)
# ═══════════════════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))
fig.suptitle('Cambio de votos por mesa en el recuento  (Δ = post − pre)',
             fontsize=13, fontweight='bold', y=1.01)

for ax, party in zip(axes, PARTIES):
    d   = deltas(party)
    r   = sr[party]
    lo  = int(np.floor(d.min()))
    hi  = int(np.ceil(d.max()))
    bins = np.arange(lo - 0.5, hi + 1.5, 1)   # one integer per bin

    ax.hist(d, bins=bins, color=COLORS[party], edgecolor='white', linewidth=0.6, alpha=0.92)

    sig = sig_label(r['p'])
    ax.text(0.04, 0.97, f"p = {r['p']:.3f}  {sig}",
            transform=ax.transAxes, ha='left', va='top', fontsize=9,
            bbox=dict(boxstyle='round,pad=0.35', fc='white', ec='#ccc', alpha=0.9))

    ax.set_title(SHORT[party], fontsize=10, fontweight='bold',
                 color=COLORS[party], pad=8)
    ax.set_xlabel('Δ votos por mesa', labelpad=6)
    ax.set_ylabel('N° mesas' if party == FP else '', labelpad=6)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))

fig.tight_layout()
fig.savefig('data/figures/fig1_distributions.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig1_distributions.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 2 — Won / Same / Lost (cleaner labels, no overlap)
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(11, 6))

cats  = ['Ganó votos\n(Δ > 0)', 'Sin cambio\n(Δ = 0)', 'Perdió votos\n(Δ < 0)']
x     = np.arange(len(cats))
w     = 0.24
offsets = [-w, 0, w]

for i, party in enumerate(PARTIES):
    d   = deltas(party)
    n   = len(d)
    pcts = [100*np.sum(d>0)/n, 100*np.sum(d==0)/n, 100*np.sum(d<0)/n]
    bars = ax.bar(x + offsets[i], pcts, w,
                  label=SHORT1[party],
                  color=COLORS[party], alpha=0.92, edgecolor='white', linewidth=0.8)
    for bar, pct in zip(bars, pcts):
        if pct > 1.5:
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + 0.8,
                    f'{pct:.0f}%',
                    ha='center', va='bottom', fontsize=9.5, fontweight='bold',
                    color='#222')

ax.set_xticks(x)
ax.set_xticklabels(cats, fontsize=11)
ax.set_ylabel('% de mesas', fontsize=11)
ax.set_ylim(0, 105)
ax.set_title('¿Qué candidato ganó o perdió votos en el recuento?',
             fontsize=12, fontweight='bold', pad=12)
ax.legend(fontsize=10, loc='upper right', framealpha=0.85)
ax.axhline(0, color='#aaa', lw=0.8)

fig.tight_layout()
fig.savefig('data/figures/fig2_won_lost.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig2_won_lost.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 3 — Mean delta + 95% CI per candidate
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(9, 6))

xlabels = [SHORT[p].replace('\n', '\n') for p in PARTIES]
means   = [sr[p]['mean'] for p in PARTIES]
ci_lo   = [sr[p]['mean'] - sr[p]['ci'][0] for p in PARTIES]
ci_hi   = [sr[p]['ci'][1] - sr[p]['mean'] for p in PARTIES]
colors  = [COLORS[p] for p in PARTIES]

bars = ax.bar(xlabels, means, color=colors, alpha=0.92,
              edgecolor='white', linewidth=0.8, width=0.45)
ax.errorbar(xlabels, means, yerr=[ci_lo, ci_hi],
            fmt='none', color='#111', capsize=9, capthick=1.8, lw=2)
ax.axhline(0, color='#333', lw=1.2, ls='--', alpha=0.7)

# mu, CI, and sig — all above the upper CI whisker
ci_top = [m + e for m, e in zip(means, ci_hi)]
pad = max(ci_hi) * 0.12
for i, (party, m, ct) in enumerate(zip(PARTIES, means, ci_top)):
    r   = sr[party]
    sig = sig_label(r['p'])
    label = (f"{sig}\n"
             f"μ = {r['mean']:.3f}\n"
             f"95% CI [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}]")
    ax.text(i, ct + pad, label,
            ha='center', va='bottom', fontsize=8.5, color='#222', linespacing=1.5,
            fontweight='normal')

ax.set_ylabel('Δ promedio de votos por mesa', fontsize=11)
ax.set_title('Cambio promedio de votos en el recuento\n(intervalo de confianza al 95%)',
             fontsize=12, fontweight='bold', pad=10)
ax.set_ylim(bottom=min(means) - max(ci_lo) * 1.6,
            top=max(ci_top) + max(ci_hi) * 1.6)

fig.tight_layout()
fig.savefig('data/figures/fig3_mean_delta_ci.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig3_mean_delta_ci.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 4 — Margin changes: mean + CI (the key narrative figure)
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 6.5))

comps = [
    ('margin_fp_jpp', FP,  'Keiko\nvs. Sánchez'),
    ('margin_fp_rp',  FP,  'Keiko\nvs. López Aliaga'),
    ('margin_jpp_rp', JPP, 'Sánchez\nvs. López Aliaga'),
]

xlabels = [c[2] for c in comps]
means_m = [mr[c[0]]['mean'] for c in comps]
ci_lo_m = [mr[c[0]]['mean'] - mr[c[0]]['ci'][0] for c in comps]
ci_hi_m = [mr[c[0]]['ci'][1] - mr[c[0]]['mean'] for c in comps]
bar_colors = [COLORS[c[1]] for c in comps]

bars = ax.bar(xlabels, means_m, color=bar_colors, alpha=0.88,
              edgecolor='white', linewidth=0.8, width=0.45)
ax.errorbar(xlabels, means_m, yerr=[ci_lo_m, ci_hi_m],
            fmt='none', color='#111', capsize=10, capthick=2, lw=2.2)
ax.axhline(0, color='#333', lw=1.5, ls='--', alpha=0.75)

# mu, CI, and sig — all above the upper CI whisker
ci_tops = [m + e for m, e in zip(means_m, ci_hi_m)]
pad = max(ci_hi_m) * 0.12
for i, (c, m, ct) in enumerate(zip(comps, means_m, ci_tops)):
    col   = c[0]
    r     = mr[col]
    sig   = sig_label(r['p'])
    label = (f"{sig}\n"
             f"μ = {r['mean']:.3f}\n"
             f"95% CI [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}]")
    ax.text(i, ct + pad, label,
            ha='center', va='bottom', fontsize=8.5, color='#222', linespacing=1.5)

ax.set_ylabel('Δ margen promedio por mesa\n(+ = primer candidato gana margen)', fontsize=11)
ax.set_title('Cambio de margen en el recuento por mesa\n(intervalo de confianza al 95%)',
             fontsize=12, fontweight='bold', pad=10)
ax.set_ylim(bottom=min(means_m) - max(ci_lo_m) * 2,
            top=max(ci_tops) + max(ci_hi_m) * 1.8)

fig.tight_layout()
fig.savefig('data/figures/fig4_margin_ci.png', bbox_inches='tight', dpi=150, facecolor=BG)
plt.close()
print("Saved fig4_margin_ci.png")

print("\n✓ All figures → data/figures/")
