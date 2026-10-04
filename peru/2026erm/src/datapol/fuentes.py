"""Acceso de solo lectura a las fuentes locales del operador.

Las fuentes se actualizan a diario por un flujo ajeno a este repo. **No se copian
ni se cachean**: se consultan siempre en su dirección original, de modo que cada
corrida vea el estado del día.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Direcciones de las fuentes del operador. Solo lectura, nunca se escriben.
BASE_OPERADOR = Path(os.environ.get(
    "ERM2026_CANDIDATOS",
    Path(__file__).resolve().parents[4] / "articulos/erm-2026-candidatos")) / "data"
CANDIDATOS_CSV = BASE_OPERADOR / "erm2026_candidatos.csv"
HDV_SQLITE = BASE_OPERADOR / "hdv" / "hdv_erm2026.sqlite"
ORGANIZACIONES_CSV = BASE_OPERADOR / "organizaciones_erm2026.csv"

# Todo lo que llega del JNE es texto. Los ubigeos y DNI llevan ceros a la
# izquierda que se pierden si pandas los interpreta como números.
_LEER_TEXTO = {"dtype": str, "keep_default_na": False, "na_values": [""]}


def normaliza(s: str | None) -> str | None:
    """Pliega a ASCII en mayúsculas para cruzar nombres entre fuentes.

    Las tablas de referencia están escritas sin eñes ni tildes y el JNE no, así
    que FERREÑAFE y FERRENAFE tienen que colisionar a propósito.
    """
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    plano = unicodedata.normalize("NFKD", str(s))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(plano.upper().replace("-", " ").split())


def lee_candidatos(ruta: Path = CANDIDATOS_CSV) -> pd.DataFrame:
    """Registro de candidaturas, tal cual, sin transformar."""
    df = pd.read_csv(ruta, **_LEER_TEXTO)
    # `distrito_electoral` viene siempre vacía y `ubigeo_postula` es un duplicado
    # exacto de `ubigeo` en las 101,617 filas. Ver docs/fuentes-locales.md.
    return df.drop(columns=["distrito_electoral", "ubigeo_postula"], errors="ignore")


def lee_organizaciones(ruta: Path = ORGANIZACIONES_CSV) -> pd.DataFrame:
    return pd.read_csv(ruta, **_LEER_TEXTO)


@dataclass
class Postulacion:
    """Circunscripción por la que postula un candidato, según su hoja de vida."""

    departamento: str | None
    provincia: str | None
    distrito: str | None


def lee_postulacion_hdv(
    hoja_vida_ids: list[int], ruta: Path = HDV_SQLITE
) -> dict[int, Postulacion]:
    """Extrae `strPostula*` de las hojas de vida pedidas.

    Es la única fuente que dice a qué distrito del Callao postula un consejero:
    el CSV de candidaturas colapsa los siete distritos en `CALLAO`.

    Los blobs están comprimidos con zlib puro, no gzip (cabecera 78 9c).
    """
    import json

    if not hoja_vida_ids:
        return {}

    salida: dict[int, Postulacion] = {}
    # mode=ro da una lectura consistente aunque el flujo diario esté escribiendo.
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        for lote in _por_lotes(sorted(set(hoja_vida_ids)), 500):
            marcas = ",".join("?" * len(lote))
            filas = con.execute(
                f"select hoja_vida_id, gz from raw where hoja_vida_id in ({marcas})",
                lote,
            ).fetchall()
            for hv_id, blob in filas:
                try:
                    datos = json.loads(zlib.decompress(blob).decode("utf8"))
                    p = datos["data"]["oDatosPersonales"]
                except (zlib.error, json.JSONDecodeError, KeyError, UnicodeDecodeError):
                    continue
                salida[hv_id] = Postulacion(
                    departamento=p.get("strPostulaDepartamento"),
                    provincia=p.get("strPostulaProvincia"),
                    distrito=p.get("strPostulaDistrito"),
                )
    finally:
        con.close()
    return salida


def _por_lotes(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


ALCALDES_2022_CSV = BASE_OPERADOR / "alcaldes_2022.csv"


def lee_alcaldes_2022(ruta: Path = ALCALDES_2022_CSV) -> pd.DataFrame:
    """Los 1,878 alcaldes en ejercicio, electos en ERM 2022.

    Es el padrón contra el que se identifica a un alcalde que vuelve a postular.
    El archivo trae BOM y el `distrito` vacío marca al alcalde **provincial**:
    no es un dato faltante, es cómo se distingue el nivel.
    """
    df = pd.read_csv(ruta, encoding="utf-8-sig", **_LEER_TEXTO)
    return df
