"""Tests del maestro de mesas.

Los de `lee_locales` y `numera_rango` corren sobre fixtures sintéticas. Los de
cuadre leen la salida ya construida en `data/processed/`, que es barata de releer
y es lo que de verdad consume el resto del pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from _scripts import carga  # noqa: E402

_m = carga("00d_mesas")
RANGO_ESPECIAL_INICIO = _m.RANGO_ESPECIAL_INICIO
RANGO_NORMAL_INICIO = _m.RANGO_NORMAL_INICIO
TOTAL_ESPECIAL = _m.TOTAL_ESPECIAL
TOTAL_NORMAL = _m.TOTAL_NORMAL
numera_rango = _m.numera_rango

MESAS = RAIZ / "data/processed/mesas.csv"
LOCALES = RAIZ / "data/reference/locales.csv"

pytestmark = pytest.mark.skipif(
    not MESAS.exists(), reason="corre antes scripts/build_mesas.py"
)


@pytest.fixture(scope="module")
def mesas() -> pd.DataFrame:
    return pd.read_csv(MESAS, dtype=str)


@pytest.fixture(scope="module")
def locales() -> pd.DataFrame:
    return pd.read_csv(LOCALES, dtype={"ubigeo_distrito": str, "local_id": str})


# --- numeración -------------------------------------------------------------

def test_numera_rango_es_correlativo():
    loc = pd.DataFrame({"n_mesas": [3, 1, 2]})
    assert list(numera_rango(loc, 1)) == [1, 2, 3, 4, 5, 6]


def test_numera_rango_respeta_el_inicio():
    loc = pd.DataFrame({"n_mesas": [2]})
    assert list(numera_rango(loc, 900_001)) == [900_001, 900_002]


# --- cuadres duros ----------------------------------------------------------

def test_total_de_mesas(mesas):
    assert len(mesas) == TOTAL_NORMAL + TOTAL_ESPECIAL == 89_935


def test_los_dos_rangos_cuadran(mesas):
    assert (mesas.rango == "normal").sum() == TOTAL_NORMAL
    assert (mesas.rango == "especial").sum() == TOTAL_ESPECIAL


def test_numeros_de_mesa_unicos_y_en_rango(mesas):
    assert mesas.mesa.is_unique
    n = mesas[mesas.rango == "normal"].mesa.astype(int)
    e = mesas[mesas.rango == "especial"].mesa.astype(int)
    assert n.min() == RANGO_NORMAL_INICIO and n.max() == TOTAL_NORMAL
    assert e.min() == RANGO_ESPECIAL_INICIO
    assert e.max() == RANGO_ESPECIAL_INICIO + TOTAL_ESPECIAL - 1


def test_el_rango_normal_cubre_los_1892_distritos(mesas):
    n = mesas[mesas.rango == "normal"]
    assert n.ubigeo_distrito.nunique() == 1_892


def test_los_bloques_del_rango_normal_son_contiguos(mesas):
    """Un distrito, un tramo. Es la propiedad que hace válida la reconstrucción."""
    n = mesas[mesas.rango == "normal"].sort_values("mesa")
    u = n.ubigeo_distrito.values
    tramos = 1 + (u[1:] != u[:-1]).sum()
    assert tramos == n.ubigeo_distrito.nunique()


def test_el_rango_normal_es_monotono_en_ubigeo(mesas):
    n = mesas[mesas.rango == "normal"].sort_values("mesa")
    u = n.ubigeo_distrito.values
    assert (u[1:] >= u[:-1]).all()


# --- lo pendiente se declara, no se rellena ---------------------------------

def test_cada_rango_declara_su_metodo(mesas):
    """El método distingue lo exacto de lo validado, y no hay tercera categoría."""
    n = mesas[mesas.rango == "normal"]
    e = mesas[mesas.rango == "especial"]
    assert (n.metodo == "frontera_ubigeo").all() and (n.confianza == "exacta").all()
    assert (e.metodo == "orden_odpe").all() and (e.confianza == "alta").all()
    assert set(mesas.metodo) == {"frontera_ubigeo", "orden_odpe"}


def test_el_rango_especial_cubre_sus_distritos(mesas):
    e = mesas[mesas.rango == "especial"]
    assert e.ubigeo_distrito.notna().all()
    assert e.ubigeo_distrito.nunique() == 809


# --- enlace con las carreras ------------------------------------------------

def test_toda_mesa_tiene_carrera_provincial(mesas):
    """Todo elector del país elige alcalde provincial, sin excepción."""
    assert mesas.race_provincial.notna().all()


def test_los_cercados_no_tienen_carrera_distrital(mesas):
    n = mesas[mesas.rango == "normal"]
    sin = n[n.race_distrital.isna()]
    assert sin.ubigeo_distrito.nunique() == 196


def test_lima_metropolitana_no_elige_regional(mesas):
    lima = mesas[(mesas.rango == "normal")
                 & mesas.ubigeo_distrito.str.startswith("1401", na=False)]
    assert lima.race_gobernador.isna().all()
    assert lima.race_consejero.isna().all()


# --- catálogo de locales ----------------------------------------------------

def test_locales_suman_las_mesas(locales):
    assert locales.n_mesas.sum() == 89_935
    assert locales[~locales.es_msi].n_mesas.sum() == TOTAL_NORMAL
    assert locales[locales.es_msi].n_mesas.sum() == TOTAL_ESPECIAL


def test_electores_municipales_cuadran_con_el_padron(locales):
    """26,314,648 del padrón aprobado + 76 extranjeros inscritos."""
    assert locales.electores_municipales.sum() == 26_314_724
    assert locales.extranjeros.sum() == 76


def test_local_id_unico_dentro_del_distrito(locales):
    assert not locales.duplicated(["ubigeo_distrito", "local_id"]).any()
