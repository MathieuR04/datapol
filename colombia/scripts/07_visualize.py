"""
07_visualize.py
QA visualizations using geopandas + matplotlib.
Outputs to colombia/data/processed/plots/
  turnout_municipios.png
  winner_municipios.png
  top10_candidates_bar.png
  votes_dept.png
"""

import json
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from pathlib import Path

OUT   = Path(__file__).parent.parent / "data" / "processed"
PLOTS = OUT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.spines.left":   False,
    "axes.spines.bottom": False,
})


def load_geodata():
    gdf = gpd.read_file(OUT / "colombia_results_map.geojson")
    dept_gdf = gpd.read_file(OUT / "colombia_results_dept.geojson")
    for col in ["turnout_pct", "winner_pct", "votos_validos", "votantes"]:
        if col in gdf.columns:
            gdf[col] = pd.to_numeric(gdf[col], errors="coerce")
        if col in dept_gdf.columns:
            dept_gdf[col] = pd.to_numeric(dept_gdf[col], errors="coerce")
    return gdf, dept_gdf


def plot_turnout(gdf):
    fig, ax = plt.subplots(1, 1, figsize=(10, 14))
    gdf_valid = gdf[gdf["turnout_pct"].notna()]
    gdf_valid.plot(
        column="turnout_pct", ax=ax, legend=True,
        cmap="YlOrRd", vmin=20, vmax=80,
        missing_kwds={"color": "#cccccc", "label": "Sin datos"},
        legend_kwds={"label": "Participación (%)", "shrink": 0.6},
        linewidth=0.1, edgecolor="#888888",
    )
    no_data = gdf[gdf["turnout_pct"].isna()]
    if len(no_data): no_data.plot(ax=ax, color="#cccccc", linewidth=0.1, edgecolor="#888888")
    ax.set_title("Participación electoral por municipio\nSenado Colombia 2026",
                 fontsize=16, fontweight="bold", pad=15)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(PLOTS / "turnout_municipios.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  turnout_municipios.png")


def plot_winner(gdf):
    fig, ax = plt.subplots(1, 1, figsize=(10, 14))

    winner_col = "winner" if "winner" in gdf.columns else None
    if not winner_col:
        print("  winner column not found, skipping winner map")
        return

    gdf = gdf.copy()
    top_winners = gdf[winner_col].value_counts().head(10).index.tolist()
    gdf["winner_display"] = gdf[winner_col].where(gdf[winner_col].isin(top_winners), other="OTROS")

    palette = [
        "#E63946", "#457B9D", "#2A9D8F", "#E9C46A", "#F4A261",
        "#264653", "#A8DADC", "#6A0572", "#1D3557", "#606C38",
        "gray",
    ]
    categories = gdf["winner_display"].dropna().unique().tolist()
    color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(categories)}
    gdf["color"] = gdf["winner_display"].map(color_map).fillna("#cccccc")

    no_data_w = gdf[gdf["winner_display"].isna()]
    if len(no_data_w): no_data_w.plot(ax=ax, color="#cccccc", linewidth=0.1, edgecolor="#888888")
    for cat, grp in gdf.groupby("winner_display"):
        grp.plot(ax=ax, color=color_map.get(cat, "#cccccc"),
                 linewidth=0.1, edgecolor="#888888")

    patches = [mpatches.Patch(color=c, label=lbl) for lbl, c in color_map.items()]
    ax.legend(handles=patches, loc="lower left", fontsize=7, framealpha=0.8,
              title="Candidato ganador", title_fontsize=8)
    ax.set_title("Candidato ganador por municipio\nSenado Colombia 2026",
                 fontsize=16, fontweight="bold", pad=15)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(PLOTS / "winner_municipios.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  winner_municipios.png")


def plot_top10_bar():
    nat = pd.read_csv(OUT / "resultados_nacional.csv")
    cand_cols = [c for c in nat.columns if c.startswith("cand_")]
    if not cand_cols:
        print("  No candidate columns in resultados_nacional.csv, skipping bar chart")
        return

    totals = nat[cand_cols].iloc[0].sort_values(ascending=False)
    top10 = totals.head(10)
    names  = [c.split("|")[1] if "|" in c else c for c in top10.index]
    votes  = top10.values.astype(int)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = plt.cm.tab10.colors[:len(names)]
    bars = ax.barh(names[::-1], votes[::-1], color=colors[::-1])
    ax.set_xlabel("Votos", fontsize=12)
    ax.set_title("Top 10 candidatos — Senado Colombia 2026", fontsize=14, fontweight="bold")
    for bar, v in zip(bars, votes[::-1]):
        ax.text(v + max(votes) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=9)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
    fig.tight_layout()
    fig.savefig(PLOTS / "top10_candidates_bar.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  top10_candidates_bar.png")


def plot_votes_dept(dept_gdf):
    fig, ax = plt.subplots(1, 1, figsize=(10, 14))
    dept_gdf = dept_gdf.copy()
    dept_gdf["votos_validos"] = pd.to_numeric(dept_gdf.get("votos_validos", pd.NA), errors="coerce")
    dept_gdf_valid = dept_gdf[dept_gdf["votos_validos"].notna()]
    dept_gdf_valid.plot(
        column="votos_validos", ax=ax, legend=True,
        cmap="Blues",
        missing_kwds={"color": "#cccccc"},
        legend_kwds={"label": "Votos válidos", "shrink": 0.6,
                     "format": plt.FuncFormatter(lambda x, _: f"{int(x):,}")},
        linewidth=0.3, edgecolor="#555555",
    )
    dept_no_data = dept_gdf[dept_gdf["votos_validos"].isna()]
    if len(dept_no_data): dept_no_data.plot(ax=ax, color="#cccccc", linewidth=0.3, edgecolor="#555555")
    ax.set_title("Votos válidos por departamento\nSenado Colombia 2026",
                 fontsize=16, fontweight="bold", pad=15)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(PLOTS / "votes_dept.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  votes_dept.png")


def visualize():
    print("Loading GeoJSON data …")
    gdf, dept_gdf = load_geodata()
    print(f"  Municipios: {len(gdf)}  |  Depts: {len(dept_gdf)}")

    print("Producing plots …")
    plot_turnout(gdf)
    plot_winner(gdf)
    plot_top10_bar()
    plot_votes_dept(dept_gdf)

    print(f"\nAll plots saved → colombia/data/processed/plots/")


if __name__ == "__main__":
    visualize()
