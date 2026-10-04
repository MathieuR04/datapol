#!/usr/bin/env python3
"""Último estado de cada acta → las dos tablas que consume el emisor del sitio.

Lee lo que dejó `02b_scrape_mesas.py` en `data/interim/mesas/` (append-only, un
archivo por volcado y por corte) y escribe, **con el mismo esquema que ERM
2022**, para que `publica_json` no tenga que saber de qué año viene:

    processed/computo_mesa_ERM2026.parquet      una fila por (mesa, tipo)
    processed/resultados_mesa_ERM2026.parquet   una fila por (mesa, tipo, org)

Más columnas que 2022 no tenía (`estado_acta`, `ever_observada`,
`ts_contabilizada`, `race_id`, `codigo_local`), que el emisor ignora y que el
forecaster puede usar.

EL MAPA idEleccion → TIPO
-------------------------
No se escribe a mano en el código (spec 06): vive en
`data/reference/id_eleccion.csv` (`id_eleccion,tipo`). Si falta, este script no
publica nada y escribe `docs/id_eleccion_descubrimiento.md` con lo observado y un
borrador. La regla segura del borrador: la elección que **no aparece en las mesas
de los cercados** es la distrital (04). Las otras tres hay que confirmarlas
mirando los nombres de las organizaciones o los campos descriptivos del acta.

QUÉ ENTRA AL CÓMPUTO
--------------------
`resultados` solo lleva actas `C`: el cómputo oficial es lo contabilizado. El
resto queda en `computo` con su estado, para el avance de actas. `observacion`
replica la etiqueta de 2022 (`CONTABILIZADAS NORMALES`) porque es lo que filtra
`carga_todo`.

`ever_observada` es monótona: es verdadera si lo fue en **cualquier** corte.

Uso:
    uv run python scripts/03_consolida_mesas.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
TIPOS = {"01", "02", "03", "04"}
RACE_COL = {"01": "race_gobernador", "02": "race_consejero",
            "03": "race_provincial", "04": "race_distrital"}


def descubre(con, data: Path, docs: Path) -> None:
    """Reporte para que el operador fije `id_eleccion.csv`."""
    mesas = pd.read_parquet(data / "processed/mesas.parquet",
                            columns=["mesa", "race_distrital"])
    cercado = set(mesas.loc[mesas.race_distrital.fillna("") == "", "mesa"])
    con.register("cercado", pd.DataFrame({"mesa": sorted(cercado)}))
    ids = con.execute("""
        SELECT id_eleccion, count(DISTINCT mesa) AS mesas,
               count(DISTINCT mesa) FILTER (WHERE mesa IN (SELECT mesa FROM cercado)) AS en_cercado
        FROM ultima GROUP BY 1 ORDER BY 1""").df()
    orgs = con.execute("""
        SELECT id_eleccion, agrupacion, count(*) n FROM votos_ult
        GROUP BY 1,2 QUALIFY row_number() OVER (PARTITION BY id_eleccion ORDER BY n DESC) <= 5
        ORDER BY 1, n DESC""").df()
    lin = ["# Descubrimiento de `idEleccion`", "",
           "Generado por `scripts/03_consolida_mesas.py`. **Borrador**: confirmar y copiar a",
           "`data/reference/id_eleccion.csv` (`id_eleccion,tipo`).", "",
           f"Mesas de cercado en el maestro: {len(cercado):,}.", "",
           "| id_eleccion | mesas | en cercado | borrador |", "|---|---|---|---|"]
    for r in ids.itertuples():
        b = "04 (no aparece en cercados)" if r.en_cercado == 0 and cercado else "01/02/03"
        lin.append(f"| {r.id_eleccion} | {r.mesas:,} | {r.en_cercado:,} | {b} |")
    lin += ["", "## Organizaciones más frecuentes por elección", ""]
    for i, g in orgs.groupby("id_eleccion"):
        lin.append(f"- **{i}**: " + " · ".join(g.agrupacion))
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "id_eleccion_descubrimiento.md").write_text("\n".join(lin) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=RAIZ / "data")
    ap.add_argument("--docs", type=Path, default=RAIZ / "docs")
    a = ap.parse_args(argv)

    dir_a = a.data / "interim/mesas/actas"
    dir_v = a.data / "interim/mesas/votos"
    if not any(dir_a.glob("*.parquet")):
        print("no hay actas en interim/mesas: corre 02b_scrape_mesas.py primero")
        return 1

    con = duckdb.connect()
    # Último corte por (mesa, elección). Los archivos de un mismo corte no se
    # pisan: una mesa aparece una sola vez por corte.
    con.execute(f"""
        CREATE TEMP TABLE todas AS
        SELECT * FROM read_parquet('{dir_a}/*.parquet', union_by_name=true)""")
    con.execute("""
        CREATE TEMP TABLE ultima AS
        SELECT t.* EXCLUDE (ever_observada),
               bool_or(t.ever_observada) OVER (PARTITION BY mesa, id_eleccion) AS ever_observada
        FROM todas t
        QUALIFY row_number() OVER (PARTITION BY mesa, id_eleccion ORDER BY corte DESC) = 1""")
    con.execute(f"""
        CREATE TEMP TABLE votos_ult AS
        SELECT v.* FROM read_parquet('{dir_v}/*.parquet', union_by_name=true) v
        JOIN ultima u USING (mesa, id_eleccion, corte)""")

    ref = a.data / "reference/id_eleccion.csv"
    if not ref.exists():
        descubre(con, a.data, a.docs)
        print(f"falta {ref}. Reporte -> {a.docs / 'id_eleccion_descubrimiento.md'}")
        return 2
    mapa = pd.read_csv(ref, dtype=str)
    mapa["id_eleccion"] = mapa.id_eleccion.astype(int)
    if not set(mapa.tipo) <= TIPOS or mapa.id_eleccion.duplicated().any():
        print(f"{ref}: tipos fuera de {sorted(TIPOS)} o id_eleccion repetido")
        return 2
    vistos = {r[0] for r in con.execute("SELECT DISTINCT id_eleccion FROM ultima").fetchall()}
    sin_tipo = vistos - set(mapa.id_eleccion)
    if sin_tipo:
        # Una elección sin tipo se deja fuera y se dice; no se adivina.
        print(f"AVISO: idEleccion sin tipo en {ref.name}: {sorted(sin_tipo)} — se excluyen")
    con.register("mapa", mapa)

    # LA CARRERA SALE DEL UBIGEO QUE TRAE EL ACTA, no del número de mesa. En el
    # maestro la carrera es función pura del distrito (1,892 distritos, un solo
    # valor por tipo, verificado el 4 de octubre), así que (ubigeo, tipo) →
    # race_id es exacto. El número de mesa → distrito, en cambio, es una
    # reconstrucción: 100% en el rango normal pero 99.94% en el 900k. Donde la
    # ONPE y el maestro discrepan, manda la ONPE y la discrepancia se reporta.
    mesas = pd.read_parquet(a.data / "processed/mesas.parquet").fillna("")
    por_dist = mesas.drop_duplicates("ubigeo_distrito")
    largo = pd.concat([pd.DataFrame({"ubigeo_distrito": por_dist.ubigeo_distrito, "tipo": t,
                                     "race_id": por_dist[c].replace("", None)})
                       for t, c in RACE_COL.items()])
    con.register("race_de", largo)
    con.register("maestro", mesas[["mesa", "ubigeo_distrito"]])

    computo = con.execute("""
        SELECT CAST(u.mesa AS BIGINT) AS mesa, m.tipo, u.ubigeo_distrito,
               u.nombre_local AS local, '' AS direccion_local, '' AS ccent_compu,
               u.electores, u.emitidos AS votaron,
               CASE WHEN u.estado_acta = 'C' THEN 'CONTABILIZADAS NORMALES'
                    ELSE 'NO CONTABILIZADA ' || u.estado_acta END AS observacion,
               u.validos AS votos_validos, u.blancos AS votos_blancos,
               u.nulos AS votos_nulos, u.impugnados AS votos_impugnados,
               u.codigo_local, u.estado_acta, u.ever_observada,
               u.ts_primer_estado, u.ts_contabilizada, u.corte, r.race_id
        FROM ultima u JOIN mapa m USING (id_eleccion)
        LEFT JOIN race_de r ON r.ubigeo_distrito = u.ubigeo_distrito AND r.tipo = m.tipo
        ORDER BY mesa, tipo""").df()
    discrepa = con.execute("""
        SELECT DISTINCT u.mesa, u.ubigeo_distrito AS ubigeo_onpe,
               x.ubigeo_distrito AS ubigeo_maestro
        FROM ultima u LEFT JOIN maestro x USING (mesa)
        WHERE x.ubigeo_distrito IS DISTINCT FROM u.ubigeo_distrito
        ORDER BY 1""").df()
    resultados = con.execute("""
        SELECT CAST(v.mesa AS BIGINT) AS mesa, m.tipo, u.ubigeo_distrito,
               v.codigo_onpe, v.agrupacion, v.votos, v.posicion_cedula
        FROM votos_ult v JOIN ultima u USING (mesa, id_eleccion, corte)
        JOIN mapa m USING (id_eleccion)
        WHERE u.estado_acta = 'C'
        ORDER BY mesa, tipo, codigo_onpe""").df()

    out = a.data / "processed"
    for nombre, df in (("computo_mesa_ERM2026", computo),
                       ("resultados_mesa_ERM2026", resultados)):
        tmp = out / f"{nombre}.tmp.parquet"
        df.to_parquet(tmp, index=False)
        tmp.replace(out / f"{nombre}.parquet")

    c = computo.groupby("tipo").agg(actas=("mesa", "size"),
                                    contab=("estado_acta", lambda s: (s == "C").sum()),
                                    sin_race=("race_id", lambda s: s.isna().sum()))
    print(c.to_string())
    # Mesas cuyo ubigeo ONPE no coincide con el maestro, o que el maestro no
    # conocía. No es un error del pipeline (manda la ONPE), pero hay que verlo.
    f_disc = out / "mesas_discrepancia_maestro.csv"
    discrepa.to_csv(f_disc, index=False)
    if len(discrepa):
        print(f"AVISO: {len(discrepa):,} mesas con ubigeo distinto al maestro o fuera de él -> {f_disc}")
    sin_race = computo[computo.race_id.isna()]
    if len(sin_race):
        print(f"AVISO: {len(sin_race):,} actas sin carrera (ubigeo/tipo fuera de carreras): "
              f"{sorted(set(sin_race.ubigeo_distrito + '/' + sin_race.tipo))[:10]}")
    resumen = {"cortes": int(con.execute("SELECT count(DISTINCT corte) FROM todas").fetchone()[0]),
               "ultimo_corte": str(computo.corte.max()),
               "actas": int(len(computo)),
               "contabilizadas": int((computo.estado_acta == "C").sum()),
               "filas_voto": int(len(resultados)),
               "mesas_discrepancia_maestro": int(len(discrepa)),
               "actas_sin_carrera": int(len(sin_race))}
    (out / "consolida_resumen.json").write_text(json.dumps(resumen, indent=1))
    print(resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
