#!/usr/bin/env python3
"""Las mesas de la EG 2026 como unidades de distritación.

Una fila por mesa: circunscripción de diputados (27), jerarquía administrativa
(provincia, distrito, local de votación), electores hábiles y coordenadas del
local. Las 27 circunscripciones son las de diputados 2026: 24 departamentos con
Lima partida en Lima Metropolitana y Lima Provincias, más Callao y PEX.

En el extranjero no hay coordenadas: la jerarquía es continente → país →
ciudad (ubigeo 9x) y se distrita en una dimensión.

Uso:
    uv run --with pandas --with pyarrow python scripts/01_unidades.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]
ED = Path.home() / "Documents/electoral_data/peru"


def circunscripcion(u: str, exterior: bool, dept: str) -> str:
    if exterior:
        return "PERUANOS EN EL EXTRANJERO"
    if u[:2] == "14":
        return "LIMA METROPOLITANA" if u[:4] == "1401" else "LIMA PROVINCIAS"
    return dept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--padron", type=Path,
                    default=DATAPOL / "peru/2026eg/metadata/peru_2026_mesa_electoral_roll.csv")
    ap.add_argument("--locales", type=Path, default=ED / "mapas_locales/locales_con_iiee.csv")
    ap.add_argument("--out", type=Path, default=AQUI / "data/mesas.parquet")
    a = ap.parse_args()

    r = pd.read_csv(a.padron)
    r["codigo_mesa"] = r.codigo_mesa.astype(str).str.zfill(6)
    r["ubigeo"] = r.ubigeo_distrito.astype(str).str.zfill(6)
    r["local"] = r.codigo_local_votacion.astype(str).str.lstrip("0")
    r["circ"] = [circunscripcion(u, e, d) for u, e, d in
                 zip(r.ubigeo, r.is_exterior, r.nombre_dept.str.upper())]

    loc = pd.read_csv(a.locales, dtype=str)
    loc["local"] = loc.codigoLocalVotacion.str.lstrip("0")
    loc = loc.drop_duplicates("local")[["local", "iiee_latitud", "iiee_longitud"]]
    r = r.merge(loc, on="local", how="left")
    r["lat"] = pd.to_numeric(r.iiee_latitud, errors="coerce")
    r["lon"] = pd.to_numeric(r.iiee_longitud, errors="coerce")

    # Jerarquía: provincia, distrito, local. En PEX: país, ciudad, local.
    r["prov"] = r.ubigeo.str[:4]
    out = r[["codigo_mesa", "circ", "prov", "ubigeo", "nombre_distrito", "nombre_provincia",
             "local", "nombre_local_votacion", "electores_habiles", "lat", "lon",
             "is_exterior"]].rename(columns={"electores_habiles": "electores",
                                             "nombre_local_votacion": "nombre_local",
                                             "is_exterior": "exterior"})
    sin = out[~out.exterior & out.lat.isna()]
    if len(sin):
        print(f"AVISO: {len(sin)} mesas del país sin coordenadas ({sin.electores.sum():,} electores)")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out, index=False)
    print(f"{len(out):,} mesas · {out.electores.sum():,} electores · "
          f"{out.circ.nunique()} circunscripciones → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
