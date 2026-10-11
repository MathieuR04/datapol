#!/usr/bin/env python3
"""Ganador de cada distrito uninominal con los votos de la EG 2026.

Fuente por defecto: primera vuelta presidencial (todas las actas contabilizadas),
con el partido de cada candidato. `--fuente diputados` usa las actas de
diputados, que en el snapshot disponible tienen 12.9% del electorado pendiente.

Mayoría simple (first-past-the-post), sin valla. Se suman los votos por
organización de las mesas contabilizadas de cada distrito. Las mesas sin acta
contabilizada (en el JEE en el snapshot) no se imputan: se reportan, y un
distrito se marca `en_duda` cuando sus electores pendientes, con la
participación del distrito, alcanzan para voltear el margen.

Uso:
    uv run --with duckdb --with pandas --with pyarrow python scripts/03_resultados.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]
ACTAS = Path.home() / "Documents/electoral_data/peru/actas"
ESPECIALES = ("80", "81", "82")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--actas", type=Path, default=ACTAS)
    ap.add_argument("--fuente", choices=["presidencial", "diputados"], default="presidencial")
    ap.add_argument("--presidencial", type=Path,
                    default=DATAPOL / "peru/2026eg/primera/data/results/peru_2026eg_mesa_primera.csv")
    ap.add_argument("--out", type=Path, default=AQUI / "data")
    a = ap.parse_args()

    con = duckdb.connect()
    asig = pd.read_parquet(a.out / "asignacion.parquet")
    mesas = pd.read_parquet(a.out / "mesas.parquet")
    if a.fuente == "diputados":
        meta = con.sql(f"""select codigo_mesa, codigo_estado_acta estado, votos_emitidos, votos_validos
            from '{a.actas}/mesas_metadata.parquet' where eleccion = 'diputados'""").df()
        vot = con.sql(f"""select codigo_mesa, partido_codigo codigo, any_value(partido_nombre) nombre,
                sum(votos) votos
            from '{a.actas}/actas_resultados.parquet'
            where eleccion = 'diputados' and partido_codigo not in {ESPECIALES} and votos > 0
            group by all""").df()
    else:
        p = pd.read_csv(a.presidencial)
        p["codigo_mesa"] = p.codigo_mesa.astype(str).str.zfill(6)
        meta = p.rename(columns={"estado_acta": "estado"})[
            ["codigo_mesa", "estado", "votos_emitidos", "votos_validos"]]
        cands = [c for c in p.columns if c.startswith("cand_")]
        vot = p.melt(id_vars="codigo_mesa", value_vars=cands, var_name="codigo", value_name="votos")
        vot = vot[vot.votos > 0]
        vot["codigo"] = vot.codigo.str[5:].str.zfill(8)
        partido = {c["codigo"].zfill(8): c["partido"] for c in
                   json.load(open(DATAPOL / "peru/2026eg/primera/data/candidates.json"))}
        vot["nombre"] = vot.codigo.map(partido).fillna(vot.codigo)
    m = mesas.merge(asig, on="codigo_mesa").merge(meta, on="codigo_mesa", how="left")
    m["contada"] = m.estado == "C"
    d = m.groupby("distrito_us").agg(circ=("circ", "first"), electores=("electores", "sum"),
                                     mesas=("codigo_mesa", "size"), contadas=("contada", "sum"),
                                     emitidos=("votos_emitidos", "sum"),
                                     validos=("votos_validos", "sum"))
    d["electores_contados"] = m[m.contada].groupby("distrito_us").electores.sum()
    d["electores_pend"] = d.electores - d.electores_contados.fillna(0)

    v = vot.merge(asig, on="codigo_mesa")
    tab = v.groupby(["distrito_us", "codigo"]).votos.sum().unstack(fill_value=0)
    nombres = vot.groupby("codigo").nombre.first()
    top = tab.apply(lambda r: r.nlargest(2), axis=1)
    orden = tab.to_numpy().argsort(axis=1)[:, ::-1]
    cods = tab.columns.to_numpy()
    d.loc[tab.index, "ganador"] = cods[orden[:, 0]]
    d.loc[tab.index, "segundo"] = cods[orden[:, 1]]
    vals = tab.to_numpy()
    import numpy as np
    r = np.arange(len(tab))
    d.loc[tab.index, "v1"] = vals[r, orden[:, 0]]
    d.loc[tab.index, "v2"] = vals[r, orden[:, 1]]
    d["margen"] = d.v1 - d.v2
    part = d.emitidos / d.electores_contados
    d["en_duda"] = d.margen < d.electores_pend * part
    d["pct1"] = d.v1 / d.validos
    d["pct2"] = d.v2 / d.validos
    d["fuente"] = a.fuente
    d.reset_index().to_csv(a.out / "resultados_us.csv", index=False)
    tab.to_csv(a.out / "votos_distrito_us.csv")

    nac = vot.groupby("codigo").votos.sum()
    res = pd.DataFrame({"nombre": nombres, "votos": nac, "pct_votos": nac / nac.sum(),
                        "escanos": d.ganador.value_counts()}).fillna({"escanos": 0})
    res["pct_escanos"] = res.escanos / len(d)
    res["escanos_en_duda"] = d[d.en_duda].ganador.value_counts()
    res = res.fillna({"escanos_en_duda": 0}).sort_values(["escanos", "votos"], ascending=False)
    res.index.name = "codigo"
    res.to_csv(a.out / "nacional_us.csv")

    pend = m[~m.contada]
    print(f"mesas sin acta contabilizada: {len(pend):,} de {len(m):,} "
          f"({pend.electores.sum() / m.electores.sum():.1%} de electores)")
    print(f"distritos con ganador en duda: {int(d.en_duda.sum())} de {len(d)}\n")
    print(res[res.escanos > 0].assign(pct_votos=lambda x: (100 * x.pct_votos).round(1),
                                      pct_escanos=lambda x: (100 * x.pct_escanos).round(1))
          .to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
