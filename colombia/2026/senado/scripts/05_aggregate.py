"""
05_aggregate.py
Aggregate puesto-level results to municipio level.

Inputs:
  data/resultados_puestos.csv
  metadata/colombia_2026_mesa_electoral_roll.csv  ← puesto → mpio mapping

Outputs:
  data/results/colombia_2026_municipio_senado_nacional.csv
      1,189 rows: 1,122 national municipios + 67 exterior groups
  data/results/colombia_2026_municipio_senado_indigena.csv
      same geography, indigenous-constituency columns only
  data/national_parties.json
  data/indigena_parties.json
"""

import json
import pandas as pd
from pathlib import Path

OUT      = Path(__file__).parent.parent / "data"
METADATA = Path(__file__).parent.parent.parent / "metadata"
RESULTS  = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


def load_party_lookup() -> dict:
    """
    Build {code_4digit_str: {nombre, color}} from existing party JSON outputs.
    Falls back to empty dict if neither file exists (first run — winner field
    will just show the raw code).
    """
    lkp = {}
    for path in [OUT / "national_parties.json", OUT / "indigena_parties.json"]:
        if path.exists():
            with open(path) as f:
                for p in json.load(f):
                    lkp[str(p["code"]).zfill(4)] = {
                        "nombre": p.get("nombre", p["code"]),
                        "color":  p.get("color",  "#888"),
                    }
    return lkp


def compute_pcts(df: pd.DataFrame, party_cols: list[str],
                 party_lookup: dict, col_prefix: str = "party_") -> pd.DataFrame:
    df = df.copy()
    df["turnout_pct"] = (df["votantes"] / df["censo"].replace(0, pd.NA) * 100).round(2).fillna(0)
    df["pct_blanco"]  = (df["votos_blanco"]  / df["votos_validos"].replace(0, pd.NA) * 100).round(2).fillna(0)
    df["pct_nulo"]    = (df["votos_nulos"]   / df["votantes"].replace(0, pd.NA) * 100).round(2).fillna(0)

    if party_cols:
        party_df = df[party_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
        df["winner_col"]   = party_df.idxmax(axis=1).where(party_df.max(axis=1) > 0, "")
        df["winner_votes"] = party_df.max(axis=1).astype(int)
        df["winner_pct"]   = (df["winner_votes"] / df["votos_validos"].replace(0, pd.NA) * 100).round(2).fillna(0)

        def decode(col, key, fallback):
            if not isinstance(col, str) or not col:
                return fallback
            code = col.replace(col_prefix, "").zfill(4)
            return party_lookup.get(code, {}).get(key, col if key == "nombre" else fallback)

        df["winner"]       = df["winner_col"].map(lambda c: decode(c, "nombre", ""))
        df["winner_color"] = df["winner_col"].map(lambda c: decode(c, "color",  "#888"))

    return df


def aggregate():
    print("Loading data …")
    party_lookup = load_party_lookup()

    results = pd.read_csv(OUT / "resultados_puestos.csv", dtype={"puesto_code": str})

    # puesto → mpio mapping (from mesa roll, deduplicated to puesto level)
    puesto_map = pd.read_csv(
        METADATA / "colombia_2026_mesa_electoral_roll.csv",
        dtype=str,
        usecols=["puesto_code", "mpio_reg_code_7", "dept_reg_code", "is_exterior"],
    ).drop_duplicates("puesto_code")
    puesto_map["is_exterior"] = puesto_map["is_exterior"].map(
        {"True": True, "False": False, True: True, False: False}
    )

    df = results.merge(puesto_map, on="puesto_code", how="left")

    party_cols = [c for c in df.columns if c.startswith("party_")]
    cand_cols  = [c for c in df.columns if c.startswith("cand_")]
    indig_cols = [c for c in df.columns if c.startswith("indig_")]
    icand_cols = [c for c in df.columns if c.startswith("icand_")]
    base_cols  = ["votantes", "abstencion", "votos_nulos", "votos_no_marcados",
                  "votos_blanco", "votos_validos", "censo", "mesas_total", "mesas_escrutadas"]
    ind_base   = [c for c in ["ind_votantes", "ind_votos_validos",
                               "ind_votos_blanco", "ind_votos_nulos"] if c in df.columns]

    grp_cols = [c for c in base_cols + party_cols + cand_cols
                             + indig_cols + icand_cols + ind_base if c in df.columns]

    # ── nacional: all puestos (national + exterior) grouped by mpio ──────────
    mpio_agg = (
        df.groupby("mpio_reg_code_7")[grp_cols]
        .sum(numeric_only=True)
        .reset_index()
    )
    mpio_agg = compute_pcts(mpio_agg, party_cols, party_lookup)
    mpio_agg.to_csv(RESULTS / "colombia_2026_municipio_senado_nacional.csv", index=False)
    n_nat = (mpio_agg["mpio_reg_code_7"].str.startswith("88") == False).sum()
    n_ext = mpio_agg["mpio_reg_code_7"].str.startswith("88").sum()
    print(f"  nacional: {n_nat} national + {n_ext} exterior municipios")

    # ── indigena: all puestos (national + exterior) ───────────────────────────
    if indig_cols and ind_base:
        ind_grp = [c for c in ind_base + indig_cols + icand_cols
                   + ["mesas_total", "mesas_escrutadas"] if c in df.columns]
        ind_agg = (
            df.groupby("mpio_reg_code_7")[ind_grp]
            .sum(numeric_only=True)
            .reset_index()
        )
        ind_agg = ind_agg.rename(columns={
            "ind_votantes":      "votantes",
            "ind_votos_validos": "votos_validos",
            "ind_votos_blanco":  "votos_blanco",
            "ind_votos_nulos":   "votos_nulos",
        })
        ind_agg["votos_no_marcados"] = (
            ind_agg["votantes"] - ind_agg["votos_validos"] - ind_agg["votos_nulos"]
        )
        ind_agg["censo"] = 0   # physical censo is shared; use nacional for turnout
        ind_agg = compute_pcts(ind_agg, indig_cols, party_lookup, col_prefix="indig_")
        # Re-compute turnout from nacional censo (same physical tables)
        nat_censo = mpio_agg[["mpio_reg_code_7", "censo"]].rename(columns={"censo": "nat_censo"})
        ind_agg = ind_agg.merge(nat_censo, on="mpio_reg_code_7", how="left")
        ind_agg["turnout_pct"] = (
            ind_agg["votantes"] / ind_agg["nat_censo"].replace(0, pd.NA) * 100
        ).round(2).fillna(0)
        ind_agg = ind_agg.drop(columns=["nat_censo"])

        # Only keep rows with at least one indigenous vote
        has_votes = ind_agg[indig_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) > 0
        ind_agg = ind_agg[has_votes]
        ind_agg.to_csv(RESULTS / "colombia_2026_municipio_senado_indigena.csv", index=False)
        n_nat_i = (ind_agg["mpio_reg_code_7"].str.startswith("88") == False).sum()
        n_ext_i = ind_agg["mpio_reg_code_7"].str.startswith("88").sum()
        print(f"  indigena: {n_nat_i} national + {n_ext_i} exterior municipios")

    # ── national_parties.json ─────────────────────────────────────────────────
    if party_cols:
        totals = df[party_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum()
        national_parties = []
        for col, votes in totals.sort_values(ascending=False).items():
            if int(votes) == 0:
                continue
            code = col.replace("party_", "").zfill(4)
            info = party_lookup.get(code, {})
            national_parties.append({
                "code":   code,
                "nombre": info.get("nombre", code),
                "color":  info.get("color",  "#888"),
                "votes":  int(votes),
            })
        with open(OUT / "national_parties.json", "w") as f:
            json.dump(national_parties, f, ensure_ascii=False, indent=2)
        print(f"  national_parties.json: {len(national_parties)} parties")
        for p in national_parties[:5]:
            print(f"    {p['nombre']}: {p['votes']:,}")

    # ── indigena_parties.json ─────────────────────────────────────────────────
    if indig_cols:
        ind_totals = df[indig_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum()
        indigena_parties = []
        for col, votes in ind_totals.sort_values(ascending=False).items():
            if int(votes) == 0:
                continue
            code = col.replace("indig_", "").zfill(4)
            info = party_lookup.get(code, {})
            indigena_parties.append({
                "code":   code,
                "nombre": info.get("nombre", code),
                "color":  info.get("color",  "#888"),
                "votes":  int(votes),
            })
        with open(OUT / "indigena_parties.json", "w") as f:
            json.dump(indigena_parties, f, ensure_ascii=False, indent=2)
        print(f"  indigena_parties.json: {len(indigena_parties)} parties")


if __name__ == "__main__":
    aggregate()
