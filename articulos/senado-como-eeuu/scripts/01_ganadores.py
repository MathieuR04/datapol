#!/usr/bin/env python3
"""Ganador (partido más votado, sin valla) de cada circunscripción en 2016, 2021 y 2026.

- 2016, Congreso: tabla «Sumario de los resultados por circunscripción» de
  es.wikipedia.org/wiki/Elecciones_parlamentarias_de_Perú_de_2016 (solo trae a
  los partidos con escaños; Cajamarca, Arequipa y Moquegua verificados contra
  las páginas de cada distrito electoral, que traen a todos: en Cajamarca ganó
  Democracia Directa, 39.41%, que no pasó la valla). En 2016 Lima y los peruanos
  en el extranjero votaban juntos: ganó Fuerza Popular, y se asigna a ambas.
- 2021, Congreso: ONPE, resultados por mesa (congresal_raw_2021.csv).
- 2026, Senado regional: resultados por circunscripción al 100%
  (elecciones-peru-2026/data/resultados.csv).

Uso:
    uv run --with pandas --with duckdb python scripts/01_ganadores.py
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
ED = Path.home() / "Documents/electoral_data"
ESP = {"VOTOS NULOS", "VOTOS EN BLANCO", "VOTOS IMPUGNADOS"}

# (ganador, % válidos, segundo, %) — Wikipedia, tabla por circunscripción 2016.
G2016 = {
    "AMAZONAS": ("FP", 42.9, "APP", 12.2), "ANCASH": ("FP", 39.3, "APP", 14.9),
    "APURIMAC": ("FA", 39.2, "FP", 31.3), "AREQUIPA": ("PPK", 22.37, "FA", 20.46),
    "AYACUCHO": ("FA", 41.4, "FP", 33.3), "CAJAMARCA": ("DD", 39.41, "FP", 28.93),
    "CALLAO": ("FP", 37.8, "PPK", 23.0), "CUSCO": ("FA", 32.1, "APP", 12.3),
    "HUANCAVELICA": ("FA", 37.1, "FP", 33.9), "HUANUCO": ("FP", 34.8, "FA", 23.3),
    "ICA": ("FP", 41.2, "PPK", 13.6), "JUNIN": ("FP", 37.6, "FA", 15.8),
    "LA LIBERTAD": ("FP", 37.8, "APP", 22.2), "LAMBAYEQUE": ("FP", 43.8, "AlP", 12.5),
    "LIMA METROPOLITANA": ("FP", 37.0, "PPK", 24.9), "LIMA PROVINCIAS": ("FP", 51.7, "PPK", 12.1),
    "LORETO": ("FP", 39.8, "PPK", 15.9), "MADRE DE DIOS": ("FP", 34.2, "APP", 14.2),
    "MOQUEGUA": ("PPK", 26.22, "FP", 20.35), "PASCO": ("FP", 38.0, "APP", 14.9),
    "PIURA": ("FP", 50.3, "APP", 10.3), "PUNO": ("FA", 33.3, "FP", 21.6),
    "SAN MARTIN": ("FP", 50.0, "FA", 20.4), "TACNA": ("FA", 35.1, "FP", 20.5),
    "TUMBES": ("FP", 60.1, "APP", 15.2), "UCAYALI": ("FP", 44.4, "APP", 21.7),
}
SIGLA = {"FUERZA POPULAR": "FP", "PARTIDO POLITICO NACIONAL PERU LIBRE": "PL",
         "ALIANZA PARA EL PROGRESO": "APP", "RENOVACION POPULAR": "RP", "ACCION POPULAR": "AP",
         "JUNTOS POR EL PERU": "JP", "PARTIDO DEL BUEN GOBIERNO": "PBG",
         "PARTIDO CIVICO OBRAS": "PCO", "AHORA NACION - AN": "AN", "UNION POR EL PERU": "UPP",
         "AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL": "AvP", "UN CAMINO DIFERENTE": "UCD",
         "PARTIDO PAIS PARA TODOS": "PPT"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


def top2(df: pd.DataFrame, año: int) -> list[dict]:
    df = df[~df.p.map(norm).isin({norm(x) for x in ESP})].copy()
    df["pct"] = 100 * df.v / df.groupby("c").v.transform("sum")
    filas = []
    for c, g in df.sort_values("v", ascending=False).groupby("c"):
        a, b = g.iloc[0], g.iloc[1]
        filas.append({"circ": c, "anio": año, "ganador": SIGLA.get(norm(a.p), norm(a.p)),
                      "pct": round(a.pct, 2), "segundo": SIGLA.get(norm(b.p), norm(b.p)),
                      "pct2": round(b.pct, 2)})
    return filas


def main() -> int:
    filas = [{"circ": c, "anio": 2016, "ganador": g, "pct": p, "segundo": s, "pct2": p2}
             for c, (g, p, s, p2) in G2016.items()]
    filas.append({"circ": "PERUANOS EN EL EXTRANJERO", "anio": 2016, "ganador": "FP",
                  "pct": None, "segundo": None, "pct2": None})

    q = f"""select case when try_cast(UBIGEO as int) >= 900000 then 'PERUANOS EN EL EXTRANJERO'
                   when DEPARTAMENTO = 'LIMA' and PROVINCIA = 'LIMA' then 'LIMA METROPOLITANA'
                   when DEPARTAMENTO = 'LIMA' then 'LIMA PROVINCIAS' else DEPARTAMENTO end c,
              DESCRIPCION_OP p, sum(try_cast(N_TOTAL_VOTOS as bigint)) v
            from read_csv('{ED}/peru/valla_electoral/data/congresal_raw_2021.csv', delim=';', all_varchar=true)
            group by 1, 2"""
    filas += top2(duckdb.sql(q).df(), 2021)

    r = pd.read_csv(ED / "elecciones-peru-2026/data/resultados.csv")
    r = r[(r.cargo == "senador") & (r.dept != "Nacional")]
    r = r.assign(c=r.dept.map(norm).replace({"LIMA": "LIMA METROPOLITANA",
                                             "PEX": "PERUANOS EN EL EXTRANJERO"}),
                 p=r.party, v=r.votes)[["c", "p", "v"]]
    filas += top2(r, 2026)

    df = pd.DataFrame(filas).sort_values(["circ", "anio"])
    assert df.groupby("anio").circ.nunique().eq(27).all(), df.groupby("anio").circ.nunique()
    df.to_csv(AQUI / "data/ganadores.csv", index=False)
    print(df.pivot(index="circ", columns="anio", values="ganador").to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
