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

import json
import pandas as pd
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "processed"

def load_party_lookup() -> dict:
    with open(OUT / "parties.json") as f:
        return json.load(f)  # codpar (4-digit str) → {nombre, color}


def compute_pcts(df: pd.DataFrame, party_cols: list[str], cand_cols: list[str],
                 party_lookup: dict, col_prefix: str = "party_") -> pd.DataFrame:
    df = df.copy()
    df["turnout_pct"]  = (df["votantes"] / df["censo"].replace(0, pd.NA) * 100).round(2).fillna(0)
    df["pct_blanco"]   = (df["votos_blanco"]  / df["votos_validos"].replace(0, pd.NA) * 100).round(2).fillna(0)
    df["pct_nulo"]     = (df["votos_nulos"]    / df["votantes"].replace(0, pd.NA) * 100).round(2).fillna(0)

    if party_cols:
        party_df = df[party_cols]
        df["winner_col"] = party_df.idxmax(axis=1)
        df["winner_votes"] = party_df.max(axis=1)
        df["winner_pct"] = (df["winner_votes"] / df["votos_validos"].replace(0, pd.NA) * 100).round(2).fillna(0)
        def decode_winner(col):
            if not isinstance(col, str): return ""
            code = col.replace(col_prefix, "")
            return party_lookup.get(code, {}).get("nombre", col)
        def decode_color(col):
            if not isinstance(col, str): return "#888"
            code = col.replace(col_prefix, "")
            return party_lookup.get(code, {}).get("color", "#888")
        df["winner"] = df["winner_col"].map(decode_winner)
        df["winner_color"] = df["winner_col"].map(decode_color)

    return df


def aggregate():
    print("Loading data …")
    party_lookup = load_party_lookup()
    results = pd.read_csv(OUT / "resultados_puestos.csv", dtype={"puesto_code": str})
    master  = pd.read_csv(OUT / "puestos_master.csv",  dtype=str)
    mpio_bridge = pd.read_csv(OUT / "mpio_bridge.csv",  dtype=str)

    # Merge master info into results
    master["is_exterior"] = master["is_exterior"].map({"True": True, "False": False, True: True, False: False})
    df = results.merge(
        master[["puesto_code", "mpio_reg_code_7", "dept_reg_code", "is_exterior"]],
        on="puesto_code", how="left"
    )

    # Identify party and candidate columns — nacional and indígena are separate
    party_cols = [c for c in df.columns if c.startswith("party_")]
    cand_cols  = [c for c in df.columns if c.startswith("cand_")]
    indig_cols = [c for c in df.columns if c.startswith("indig_")]
    icand_cols = [c for c in df.columns if c.startswith("icand_")]
    base_cols = ["votantes", "abstencion", "votos_nulos", "votos_no_marcados",
                 "votos_blanco", "votos_validos", "censo", "mesas_total", "mesas_escrutadas"]
    ind_base  = ["ind_votantes", "ind_votos_validos", "ind_votos_blanco", "ind_votos_nulos"]

    # ── national vs exterior ─────────────────────────────────────────────────
    nat = df[df["is_exterior"] == False].copy()   # is_exterior normalised to bool above
    ext = df[df["is_exterior"] == True].copy()
    print(f"  National puestos with results: {len(nat):,}")
    print(f"  Exterior puestos with results: {len(ext):,}")

    # ── municipio aggregation (national) ─────────────────────────────────────
    # Only nacional columns (party_/cand_); indígena kept separate below.
    ind_base_present = [c for c in ind_base if c in df.columns]
    grp_cols = base_cols + party_cols + cand_cols + indig_cols + icand_cols + ind_base_present
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

    mpio_agg = compute_pcts(mpio_agg, party_cols, cand_cols, party_lookup)
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
    dept_agg = compute_pcts(dept_agg, party_cols, cand_cols, party_lookup)
    dept_agg.to_csv(OUT / "resultados_departamentos.csv", index=False)
    print(f"  resultados_departamentos.csv: {len(dept_agg)} depts")

    # ── indígena constituency aggregation (municipio + dept, national only) ──
    ind_base_avail = [c for c in ind_base if c in nat.columns]
    if indig_cols and ind_base_avail:
        def _ind_agg(group_col):
            agg = (
                nat.groupby(group_col)[ind_base_avail + indig_cols + icand_cols]
                .sum(numeric_only=True)
                .reset_index()
            )
            # Rename so compute_pcts can work normally
            agg = agg.rename(columns={
                "ind_votantes":      "votantes",
                "ind_votos_validos": "votos_validos",
                "ind_votos_blanco":  "votos_blanco",
                "ind_votos_nulos":   "votos_nulos",
            })
            # Derive no_marcados (same formula as nacional: votantes - validos - nulos)
            agg["votos_no_marcados"] = agg["votantes"] - agg["votos_validos"] - agg["votos_nulos"]
            # Mesas are physical tables shared between constituencies — set as placeholder;
            # the correct values are joined below from nacional aggregation.
            agg["censo"] = 0
            agg["mesas_total"] = 0
            agg["mesas_escrutadas"] = 0
            return compute_pcts(agg, indig_cols, icand_cols, party_lookup, col_prefix="indig_")

        mpio_ind = _ind_agg("mpio_reg_code_7")
        mpio_ind = mpio_ind.merge(
            mpio_bridge[["mpio_reg_code_7", "mpio_name_reg", "mpio_dane_code",
                         "mpio_name_dane", "dept_reg_code", "dept_dane_code"]],
            on="mpio_reg_code_7", how="left"
        )
        # Overwrite mesas/censo with nacional values — same physical mesas serve both constituencies
        mpio_nat_mesas = mpio_agg[["mpio_reg_code_7", "censo", "mesas_total", "mesas_escrutadas"]]
        mpio_ind = mpio_ind.drop(columns=["censo", "mesas_total", "mesas_escrutadas"], errors="ignore")
        mpio_ind = mpio_ind.merge(mpio_nat_mesas, on="mpio_reg_code_7", how="left")
        mpio_ind["turnout_pct"] = (mpio_ind["votantes"] / mpio_ind["censo"].replace(0, pd.NA) * 100).round(2)
        mpio_ind.to_csv(OUT / "resultados_municipios_indigena.csv", index=False)
        print(f"  resultados_municipios_indigena.csv: {len(mpio_ind)} municipios")

        dept_ind = _ind_agg("dept_reg_code")
        dept_bridge = pd.read_csv(OUT / "dept_bridge.csv", dtype=str)
        dept_ind = dept_ind.merge(
            dept_bridge[["dept_reg_code", "dept_name_reg", "dept_dane_code", "dept_name_dane"]],
            on="dept_reg_code", how="left"
        )
        # Overwrite mesas/censo with nacional values
        dept_nat_mesas = dept_agg[["dept_reg_code", "censo", "mesas_total", "mesas_escrutadas"]]
        dept_ind = dept_ind.drop(columns=["censo", "mesas_total", "mesas_escrutadas"], errors="ignore")
        dept_ind = dept_ind.merge(dept_nat_mesas, on="dept_reg_code", how="left")
        dept_ind["turnout_pct"] = (dept_ind["votantes"] / dept_ind["censo"].replace(0, pd.NA) * 100).round(2)
        dept_ind.to_csv(OUT / "resultados_departamentos_indigena.csv", index=False)
        print(f"  resultados_departamentos_indigena.csv: {len(dept_ind)} depts")

    # ── exterior aggregation ─────────────────────────────────────────────────
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
    ext_agg = compute_pcts(ext_agg, party_cols, cand_cols, party_lookup)
    ext_agg.to_csv(OUT / "resultados_exterior.csv", index=False)
    print(f"  resultados_exterior.csv: {len(ext_agg)} exterior groups")

    # ── national totals (single row) ─────────────────────────────────────────
    nat_total = nat[grp_cols].sum(numeric_only=True).to_frame().T
    nat_total = compute_pcts(nat_total, party_cols, cand_cols, party_lookup)
    nat_total.to_csv(OUT / "resultados_nacional.csv", index=False)
    print(f"  resultados_nacional.csv: national totals saved")

    # ── nacional_parties.json (nacional + exterior, party_* only) ───────────
    # Sums only the nacional constituency columns (party_XXXX), which now
    # excludes the indígena constituency (indig_XXXX).  Exterior puestos are
    # included because they vote in the nacional list.
    if party_cols:
        all_party = df[party_cols].sum().sort_values(ascending=False)
        national_parties = []
        for col, votes in all_party.items():
            if int(votes) == 0:
                continue
            code = col.replace("party_", "")
            info = party_lookup.get(code, {})
            national_parties.append({
                "code": code,
                "nombre": info.get("nombre", code),
                "color": info.get("color", "#888"),
                "votes": int(votes),
            })
        with open(OUT / "national_parties.json", "w") as f:
            json.dump(national_parties, f, ensure_ascii=False, indent=2)
        print(f"  national_parties.json: {len(national_parties)} parties (nacional + exterior)")

        print("\nTop 10 parties (nacional + exterior):")
        for p in national_parties[:10]:
            print(f"  {p['nombre']}: {p['votes']:,}")

    # ── indigena_parties.json (circunscripción especial indígena) ────────────
    if indig_cols:
        all_indig = df[indig_cols].sum().sort_values(ascending=False)
        ind_total_valid = int(df["ind_votos_validos"].sum()) if "ind_votos_validos" in df.columns else 0
        indigena_parties = []
        for col, votes in all_indig.items():
            if int(votes) == 0:
                continue
            code = col.replace("indig_", "")
            info = party_lookup.get(code, {})
            indigena_parties.append({
                "code": code,
                "nombre": info.get("nombre", code),
                "color": info.get("color", "#888"),
                "votes": int(votes),
            })
        with open(OUT / "indigena_parties.json", "w") as f:
            json.dump(indigena_parties, f, ensure_ascii=False, indent=2)
        print(f"\n  indigena_parties.json: {len(indigena_parties)} parties")
        for p in indigena_parties[:6]:
            pct = p['votes']/ind_total_valid*100 if ind_total_valid else 0
            print(f"  {p['nombre']}: {p['votes']:,} ({pct:.1f}%)")

    return mpio_agg, dept_agg


if __name__ == "__main__":
    aggregate()
