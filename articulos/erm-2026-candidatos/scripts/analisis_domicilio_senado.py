"""
analisis_domicilio_senado.py — where senators (and senate candidates) actually live.

Thesis check for the senate-model article: the 2026 senate was sold as territorial
empowerment — 24 departamento seats + 30 national-district seats + 4 Lima + 1 Callao +
1 peruanos en el extranjero (PEX) = 60. In practice, how many senators are domiciled in
the capital? And did parties fill the *national* district (meant to capture national
interests) with Lima candidates?

Inputs
  data/eg2026_candidatos.csv        — all EG2026 candidates (hoja_vida_id join key)
  data/parlamentarios_2026.csv      — the 190 elected (60 senadores, 130 diputados)
  data/hdv/hdv_eg2026.sqlite        — meta.domi_dep/domi_prov/domi_dist from the HDVs
                                      (built by scrape_hdv_eg2026.py)

Outputs
  prints the full report, and writes:
  data/domicilio_senadores.csv           — one row per elected senator + domicile
  data/domicilio_senado_unico_partido.csv — per-party Lima share of national-district lists

Definitions
  "Lima Metropolitana" = domi_dep LIMA & domi_prov LIMA (the capital proper).
  "Lima + Callao"      = Lima Metropolitana ∪ domi_dep CALLAO.
  Department names are compared accent-stripped/uppercased (Áncash ↔ ANCASH).
"""

import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent.parent / "data"


def norm(s):
    """Accent-strip + uppercase for name joins (Áncash → ANCASH)."""
    if not isinstance(s, str):
        return None
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()


def load():
    eg = pd.read_csv(DATA / "eg2026_candidatos.csv", dtype=str)
    par = pd.read_csv(DATA / "parlamentarios_2026.csv", dtype=str)
    db = sqlite3.connect(DATA / "hdv" / "hdv_eg2026.sqlite")
    meta = pd.read_sql("SELECT hoja_vida_id, dni, ok, domi_dep, domi_prov, domi_dist "
                       "FROM meta WHERE ok=1", db)
    db.close()
    meta["hoja_vida_id"] = meta["hoja_vida_id"].astype(str)
    return eg, par, meta


def attach_domicilio(df_dni, eg, meta):
    """dni → domicile via any EG2026 candidacy's hoja_vida_id (same person, same CV)."""
    hv = (eg[eg["hoja_vida_id"] != "0"][["dni", "hoja_vida_id"]]
          .drop_duplicates("dni"))
    out = df_dni.merge(hv, on="dni", how="left").merge(
        meta[["hoja_vida_id", "domi_dep", "domi_prov", "domi_dist"]],
        on="hoja_vida_id", how="left")
    out["lima_met"] = (out["domi_dep"] == "LIMA") & (out["domi_prov"] == "LIMA")
    out["lima_callao"] = out["lima_met"] | (out["domi_dep"] == "CALLAO")
    return out


def pct(n, d):
    return f"{n}/{d} ({100*n/d:.0f}%)" if d else "n/a"


def seat_modality(circ):
    if circ == "Nacional":
        return "NACIONAL (30)"
    if circ == "Lima":
        return "LIMA (4)"
    if circ == "Callao":
        return "CALLAO (1)"
    if circ == "PEX":
        return "PEX (1)"
    return "DEPARTAMENTAL (24)"


def main():
    eg, par, meta = load()

    # ── (a) the 60 elected senators ──────────────────────────────────────────
    sen = attach_domicilio(par[par["cargo"] == "senador"].copy(), eg, meta)
    sen["modalidad"] = sen["circunscripcion"].map(seat_modality)
    missing = sen["domi_dep"].isna().sum()

    print("═" * 72)
    print("A. LOS 60 SENADORES ELECTOS — ¿dónde viven?")
    print("═" * 72)
    if missing:
        print(f"  ⚠ {missing} senador(es) sin domicilio en el warehouse HDV\n")

    order = ["NACIONAL (30)", "DEPARTAMENTAL (24)", "LIMA (4)", "CALLAO (1)", "PEX (1)"]
    rows = []
    for mod in order:
        g = sen[sen["modalidad"] == mod]
        rows.append((mod, len(g), int(g["lima_met"].sum()), int(g["lima_callao"].sum())))
    tot = ("TOTAL", len(sen), int(sen["lima_met"].sum()), int(sen["lima_callao"].sum()))

    print(f"  {'modalidad':<22}{'senadores':>10}{'Lima Met.':>12}{'Lima+Callao':>13}")
    for mod, n, lm, lc in rows + [tot]:
        print(f"  {mod:<22}{n:>10}{pct(lm, n):>12}{pct(lc, n):>13}")

    print("\n  Domicilio (departamento) de los 30 del distrito NACIONAL:")
    nac = sen[sen["modalidad"] == "NACIONAL (30)"]
    print(nac["domi_dep"].fillna("(sin HDV)").value_counts().to_string(header=False))

    # departamental senators: do they live in the department they represent?
    dep = sen[sen["modalidad"] == "DEPARTAMENTAL (24)"].copy()
    dep["circ_norm"] = dep["circunscripcion"].map(norm)
    dep["vive_en_su_dep"] = dep.apply(
        lambda r: (r["circ_norm"] == "LIMA PROVINCIAS"
                   and r["domi_dep"] == "LIMA" and r["domi_prov"] != "LIMA")
        or (r["circ_norm"] != "LIMA PROVINCIAS" and r["circ_norm"] == r["domi_dep"]),
        axis=1)
    print(f"\n  Senadores departamentales que viven en el departamento que representan: "
          f"{pct(int(dep['vive_en_su_dep'].sum()), len(dep))}")
    fuera = dep[~dep["vive_en_su_dep"]]
    if len(fuera):
        print("  Los que no:")
        for _, r in fuera.iterrows():
            print(f"    · {r['name']} ({r['circunscripcion']}) vive en "
                  f"{r['domi_dist']}, {r['domi_prov']}, {r['domi_dep']}")

    sen_out = sen[["circunscripcion", "modalidad", "partido", "name", "dni",
                   "domi_dep", "domi_prov", "domi_dist", "lima_met", "lima_callao"]]
    sen_out.to_csv(DATA / "domicilio_senadores.csv", index=False)

    # ── contexto: los 130 diputados ──────────────────────────────────────────
    dip = attach_domicilio(par[par["cargo"] == "diputado"].copy(), eg, meta)
    print("\n" + "─" * 72)
    print(f"  Contexto diputados: Lima Met. {pct(int(dip['lima_met'].sum()), len(dip))}, "
          f"Lima+Callao {pct(int(dip['lima_callao'].sum()), len(dip))}")

    # ── (b) candidatos al senado por distrito único (nacional) ───────────────
    print("\n" + "═" * 72)
    print("B. CANDIDATOS AL SENADO — DISTRITO ÚNICO NACIONAL (listas INSCRITAS)")
    print("═" * 72)
    uni = eg[(eg["tipo_eleccion_id"] == "20") & (eg["estado_lista"] == "INSCRITO")].copy()
    uni = uni.merge(meta[["hoja_vida_id", "domi_dep", "domi_prov", "domi_dist"]],
                    on="hoja_vida_id", how="left")
    uni["lima_met"] = (uni["domi_dep"] == "LIMA") & (uni["domi_prov"] == "LIMA")
    uni["lima_callao"] = uni["lima_met"] | (uni["domi_dep"] == "CALLAO")
    con_hdv = uni["domi_dep"].notna()
    print(f"  Candidatos: {len(uni)}  (con domicilio HDV: {int(con_hdv.sum())}, "
          f"sin HDV: {int((~con_hdv).sum())})")
    n = int(con_hdv.sum())
    print(f"  Viven en Lima Metropolitana: {pct(int(uni['lima_met'].sum()), n)}")
    print(f"  Lima+Callao:                 {pct(int(uni['lima_callao'].sum()), n)}")

    print("\n  Departamento de domicilio (todos los candidatos del distrito nacional):")
    print(uni.loc[con_hdv, "domi_dep"].value_counts().to_string(header=False))

    # cabezas de lista (posición 1–5: los "jaladores")
    uni["posicion"] = uni["posicion"].astype(int)
    top5 = uni[(uni["posicion"] <= 5) & con_hdv]
    print(f"\n  Top-5 de cada lista (jaladores) en Lima Met.: "
          f"{pct(int(top5['lima_met'].sum()), len(top5))}")

    # per-party
    g = (uni[con_hdv].groupby("organizacion")
         .agg(candidatos=("dni", "size"), lima_met=("lima_met", "sum"))
         .reset_index())
    g["pct_lima_met"] = (100 * g["lima_met"] / g["candidatos"]).round(0).astype(int)
    g = g.sort_values(["pct_lima_met", "candidatos"], ascending=False)
    print("\n  Por partido (% de su lista nacional domiciliado en Lima Met.):")
    for _, r in g.iterrows():
        print(f"    {r['pct_lima_met']:>3}%  {r['organizacion']}  "
              f"({r['lima_met']}/{r['candidatos']})")
    g.to_csv(DATA / "domicilio_senado_unico_partido.csv", index=False)

    print("\n  → data/domicilio_senadores.csv, data/domicilio_senado_unico_partido.csv")


if __name__ == "__main__":
    main()
