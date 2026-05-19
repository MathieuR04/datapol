"""
05_aggregate.py
Aggregate puesto-level results to municipio and dept level.
National and exterior are kept together in full results; exterior is also
saved separately for future use (ranked list / corner inset map).
Outputs:
  resultados_municipios.csv    (national municipios, map-ready)
  resultados_departamentos.csv (national depts)
  resultados_exterior.csv      (exterior puestos aggregated by country/consulado group)
  resultados_nacional.csv      (single-row national totals)
"""

import pandas as pd
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "processed"


def compute_pcts(df: pd.DataFrame, cand_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["turnout_pct"]  = (df["votantes"] / df["censo"].replace(0, pd.NA) * 100).round(2)
    df["pct_blanco"]   = (df["votos_blanco"]  / df["votos_validos"].replace(0, pd.NA) * 100).round(2)
    df["pct_nulo"]     = (df["votos_nulos"]    / df["votantes"].replace(0, pd.NA) * 100).round(2)

    if cand_cols:
        # winner = candidate with most votes
        cand_df = df[cand_cols]
        df["winner_col"] = cand_df.idxmax(axis=1)
        df["winner_votes"] = cand_df.max(axis=1)
        df["winner_pct"] = (df["winner_votes"] / df["votos_validos"].replace(0, pd.NA) * 100).round(2)
        df["winner"] = df["winner_col"].str.split("|").str[1]

    return df


def aggregate():
    print("Loading data …")
    results = pd.read_csv(OUT / "resultados_puestos.csv", dtype={"puesto_code": str})
    master  = pd.read_csv(OUT / "puestos_master.csv",  dtype=str)
    mpio_bridge = pd.read_csv(OUT / "mpio_bridge.csv",  dtype=str)

    # Merge master info into results
    master["is_exterior"] = master["is_exterior"].map({"True": True, "False": False, True: True, False: False})
    df = results.merge(
        master[["puesto_code", "mpio_reg_code_7", "dept_reg_code", "is_exterior"]],
        on="puesto_code", how="left"
    )

    # Identify candidate columns
    cand_cols = [c for c in df.columns if c.startswith("cand_")]
    base_cols = ["votantes", "abstencion", "votos_nulos", "votos_no_marcados",
                 "votos_blanco", "votos_validos", "censo", "mesas_total", "mesas_escrutadas"]

    # ── national vs exterior ─────────────────────────────────────────────────
    nat = df[df["is_exterior"] == False].copy()   # is_exterior normalised to bool above
    ext = df[df["is_exterior"] == True].copy()
    print(f"  National puestos with results: {len(nat):,}")
    print(f"  Exterior puestos with results: {len(ext):,}")

    # ── municipio aggregation (national) ─────────────────────────────────────
    grp_cols = base_cols + cand_cols
    mpio_agg = (
        nat.groupby("mpio_reg_code_7")[grp_cols]
        .sum(numeric_only=True)
        .reset_index()
    )

    # Join bridge for DANE codes and names
    mpio_agg = mpio_agg.merge(
        mpio_bridge[["mpio_reg_code_7", "mpio_name_reg", "mpio_dane_code",
                     "mpio_name_dane", "dept_reg_code", "dept_dane_code"]],
        on="mpio_reg_code_7", how="left"
    )

    mpio_agg = compute_pcts(mpio_agg, cand_cols)
    mpio_agg.to_csv(OUT / "resultados_municipios.csv", index=False)
    print(f"  resultados_municipios.csv: {len(mpio_agg)} municipios")

    # ── dept aggregation (national) ──────────────────────────────────────────
    dept_agg = (
        nat.groupby("dept_reg_code")[grp_cols]
        .sum(numeric_only=True)
        .reset_index()
    )
    dept_bridge = pd.read_csv(OUT / "dept_bridge.csv", dtype=str)
    dept_agg = dept_agg.merge(
        dept_bridge[["dept_reg_code", "dept_name_reg", "dept_dane_code", "dept_name_dane"]],
        on="dept_reg_code", how="left"
    )
    dept_agg = compute_pcts(dept_agg, cand_cols)
    dept_agg.to_csv(OUT / "resultados_departamentos.csv", index=False)
    print(f"  resultados_departamentos.csv: {len(dept_agg)} depts")

    # ── exterior aggregation ─────────────────────────────────────────────────
    # Group by mpio_reg_code_7 which for exterior = country/consulado group
    ext_master = master[master["is_exterior"] == True][
        ["puesto_code", "mpio_reg_code_7", "mpio_name", "dept_name"]
    ]
    ext_agg = (
        ext.groupby("mpio_reg_code_7")[grp_cols]
        .sum(numeric_only=True)
        .reset_index()
    )
    ext_agg = ext_agg.merge(
        ext_master[["mpio_reg_code_7", "mpio_name", "dept_name"]].drop_duplicates(),
        on="mpio_reg_code_7", how="left"
    )
    ext_agg = compute_pcts(ext_agg, cand_cols)
    ext_agg.to_csv(OUT / "resultados_exterior.csv", index=False)
    print(f"  resultados_exterior.csv: {len(ext_agg)} exterior groups")

    # ── national totals (single row) ─────────────────────────────────────────
    nat_total = nat[grp_cols].sum(numeric_only=True).to_frame().T
    nat_total = compute_pcts(nat_total, cand_cols)
    nat_total.to_csv(OUT / "resultados_nacional.csv", index=False)
    print(f"  resultados_nacional.csv: national totals saved")

    # Print top-10 candidates nationally
    if cand_cols:
        totals = nat[cand_cols].sum().sort_values(ascending=False)
        print("\nTop 10 candidates (national):")
        for col, votes in totals.head(10).items():
            name = col.split("|")[1] if "|" in col else col
            print(f"  {name}: {int(votes):,}")

    return mpio_agg, dept_agg


if __name__ == "__main__":
    aggregate()
