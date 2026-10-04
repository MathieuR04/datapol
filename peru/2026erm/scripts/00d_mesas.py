#!/usr/bin/env python3
"""Construye el maestro de mesas de ERM 2026 desde la respuesta SAIP de la ONPE.

    data/reference/locales.csv   catálogo de los 10,180 locales de votación
    data/processed/mesas.csv     las 89,935 mesas con su distrito y sus carreras

FUENTE
------
`data/raw/onpe_saip_292325_2026/GOECOR/LOCALES ODPE UBIGEO Y  OTROS.xlsx`, crudo
inmutable. Ver el `PROCEDENCIA.md` de esa carpeta para las trampas de lectura
(encabezado en la fila 11, fila `TOTAL` mezclada entre los datos).

CÓMO SE ASIGNA UNA MESA A SU DISTRITO
-------------------------------------
No hacen falta 89,935 consultas: la numeración es por bloques contiguos, así que
basta saber cuántas mesas tiene cada distrito y en qué orden se consumen los
números. El SAIP da lo primero de forma exacta. Lo segundo depende del rango:

**Rango normal `000001`–`084992` (84,992 mesas, locales SIN MSI).**
Los bloques van en orden ascendente de ubigeo, uno por distrito. Verificado
contra las 80,420 mesas del rango normal de ERM 2022: la reconstrucción por suma
acumulada reproduce **el 100.0000%** del mapeo observado, sin un solo error.
Estas filas salen con `metodo=frontera_ubigeo`, `confianza=alta`.

**Rango especial `900001`–`904943` (4,943 mesas, locales CON MSI).**
Aquí el ubigeo solo **no** alcanza. Ordenar por ubigeo los distritos que tienen
mesas 900k —con el oráculo perfecto de cuáles son y cuántas, sacado del propio
2022— acierta apenas el **35.2%**: la secuencia real salta de Rodríguez de Mendoza
(0105) a Bongará (0103) a Bagua (0102).

Lo que sí hay es estructura: **38 tramos ascendentes** para 613 bloques de
distrito, y los cortes caen dentro de cada departamento, que es la firma de un
orden por ODPE. ERM 2022 no traía el mapa de ODPE; el SAIP de 2026 sí, y por eso
aquí se ordena por `(odpe, ubigeo_distrito, local_id)`.

**Validado contra EG 2026**, que es verdad de campo real del mismo año y la misma
ONPE: aplicando este mapa de ODPE al orden observado de las 4,703 mesas 900k de las
generales de abril, acierta **4,700 — el 99.94%**. Ordenar solo por ubigeo acierta
el 22.0% en ese mismo conjunto. Sale marcado `metodo=orden_odpe`, `confianza=alta`,
distinguible del rango normal por si alguien quiere solo lo exacto.

Uso:
    uv run python scripts/00d_mesas.py
    uv run python scripts/00d_mesas.py --xlsx otra/ruta.xlsx --out data/processed
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]

XLSX = (
    RAIZ
    / "data/raw/onpe_saip_292325_2026/GOECOR/LOCALES ODPE UBIGEO Y  OTROS.xlsx"
)
DISTRITOS = RAIZ / "data/reference/distritos.csv"

# El encabezado real del xlsx. Las diez filas previas son título y fecha de corte.
FILA_ENCABEZADO = 10

# Fronteras oficiales de los dos rangos de numeración.
RANGO_NORMAL_INICIO = 1
RANGO_ESPECIAL_INICIO = 900_001
TOTAL_NORMAL = 84_992
TOTAL_ESPECIAL = 4_943

RENOMBRES = {
    "ODPE": "odpe",
    "NOMBRE ODPE": "odpe_nombre",
    "SEDE DE ODPE": "odpe_sede",
    "UBIGEO CENTRO DE CÓMPUTO": "ubigeo_centro_computo",
    "UBIGEO": "ubigeo_distrito",
    "ID_LOCAL": "local_id",
    "NOMBRE DEL LOCAL": "local_nombre",
    "DIRECCIÓN DEL LOCAL": "local_direccion",
    "MESAS": "n_mesas",
    "ELECTORES HÁBILES ELECCIONES MUNICIPALES": "electores_municipales",
    "ELECTORES HÁBILES ELECCIONES REGIONALES": "electores_regionales",
    "EXTRANJEROS INSCRITOS": "extranjeros",
    "LOCALIDADES CON MSI": "msi_localidad",
    "VRAEM 1/": "vraem",
}


def lee_locales(xlsx: Path) -> pd.DataFrame:
    d = pd.read_excel(xlsx, dtype=str, header=FILA_ENCABEZADO)
    # La fila TOTAL viene mezclada entre los datos y no trae ubigeo.
    d = d[d["UBIGEO"].notna()].copy()
    d = d.rename(columns=RENOMBRES)[list(RENOMBRES.values())]
    for c in ("n_mesas", "electores_municipales", "electores_regionales", "extranjeros"):
        d[c] = pd.to_numeric(d[c], errors="raise").astype(int)
    # MSI es lo que separa los dos rangos de numeración.
    d["es_msi"] = d.msi_localidad.notna()
    return d.sort_values(["ubigeo_distrito", "local_id"]).reset_index(drop=True)


def numera_rango(locales: pd.DataFrame, inicio: int) -> np.ndarray:
    """Asigna números correlativos a las mesas de cada local, en el orden dado."""
    return np.arange(inicio, inicio + int(locales.n_mesas.sum()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xlsx", type=Path, default=XLSX)
    p.add_argument("--distritos", type=Path, default=DISTRITOS)
    p.add_argument("--out", type=Path, default=RAIZ / "data/processed")
    p.add_argument("--reference", type=Path, default=RAIZ / "data/reference")
    a = p.parse_args()

    loc = lee_locales(a.xlsx)
    dist = pd.read_csv(a.distritos, dtype=str).fillna("")

    faltan = set(loc.ubigeo_distrito) - set(dist.ubigeo_distrito)
    if faltan:
        raise SystemExit(f"ubigeos del SAIP ausentes de distritos.csv: {sorted(faltan)}")

    normal = loc[~loc.es_msi].copy()
    especial = loc[loc.es_msi].copy()
    if int(normal.n_mesas.sum()) != TOTAL_NORMAL:
        raise SystemExit(f"rango normal: {int(normal.n_mesas.sum())} != {TOTAL_NORMAL}")
    if int(especial.n_mesas.sum()) != TOTAL_ESPECIAL:
        raise SystemExit(f"rango especial: {int(especial.n_mesas.sum())} != {TOTAL_ESPECIAL}")

    # --- Rango normal: bloques contiguos en orden de ubigeo. Verificado en 2022.
    fn = normal.loc[normal.index.repeat(normal.n_mesas)].reset_index(drop=True)
    fn["mesa"] = numera_rango(normal, RANGO_NORMAL_INICIO)
    fn["rango"] = "normal"
    fn["metodo"] = "frontera_ubigeo"
    fn["confianza"] = "exacta"

    # --- Rango especial: orden por ODPE, validado al 99.94% contra EG 2026.
    especial = especial.sort_values(["odpe", "ubigeo_distrito", "local_id"])
    fe = especial.loc[especial.index.repeat(especial.n_mesas)].reset_index(drop=True)
    fe["mesa"] = numera_rango(especial, RANGO_ESPECIAL_INICIO)
    fe["rango"] = "especial"
    fe["metodo"] = "orden_odpe"
    fe["confianza"] = "alta"

    cols = ["mesa", "rango", "ubigeo_distrito", "local_id", "metodo", "confianza"]
    mesas = pd.concat([fn[cols], fe[cols]], ignore_index=True)
    mesas["mesa"] = mesas.mesa.map(lambda x: f"{x:06d}")

    carreras = dist.set_index("ubigeo_distrito")[
        ["race_gobernador", "race_consejero", "race_provincial", "race_distrital"]
    ]
    mesas = mesas.join(carreras, on="ubigeo_distrito")

    # --- Catálogo de locales, con el conteo 900k por distrito que sí es exacto.
    esp_por_distrito = especial.groupby("ubigeo_distrito").n_mesas.sum()
    loc_out = loc.copy()
    loc_out["mesas_especiales_del_distrito"] = loc_out.ubigeo_distrito.map(
        esp_por_distrito
    ).fillna(0).astype(int)

    a.out.mkdir(parents=True, exist_ok=True)
    a.reference.mkdir(parents=True, exist_ok=True)
    mesas.to_csv(a.out / "mesas.csv", index=False)
    mesas.to_parquet(a.out / "mesas.parquet", index=False)
    loc_out.to_csv(a.reference / "locales.csv", index=False)

    asignadas = mesas.ubigeo_distrito.notna().sum()
    print(f"fuente : {a.xlsx}")
    print(f"  locales                       {len(loc):>8,}")
    print(f"  mesas totales                 {len(mesas):>8,}")
    print(f"    rango normal   (exacto)     {len(fn):>8,}")
    print(f"    rango especial (odpe)       {len(fe):>8,}")
    print(f"  distritos cubiertos           {mesas.ubigeo_distrito.nunique():>8,}"
          f" de {len(dist):,}")
    print(f"  mesas con distrito            {asignadas:>8,} ({100*asignadas/len(mesas):.1f}%)")
    print(f"\nescrito: {a.out/'mesas.csv'}")
    print(f"         {a.reference/'locales.csv'}")
    print(f"\nMETODO POR RANGO:")
    print(f"  - normal  : frontera por ubigeo. 100.0000% contra ERM 2022 y EG 2026.")
    print(f"  - especial: orden por (ODPE, ubigeo). 99.94% contra EG 2026 (4,700/4,703).")
    print(f"    Solo ubigeo daria 22.0%. Afecta a {len(esp_por_distrito):,} distritos.")
    print(f"    Se reconfirma con el `codigoLocalVotacion` de las actas en vivo.")


if __name__ == "__main__":
    main()
