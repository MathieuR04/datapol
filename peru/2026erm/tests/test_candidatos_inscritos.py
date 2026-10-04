"""Tests de las reglas de `candidatos_inscritos`, sobre fixtures sintéticas.

No tocan las fuentes del operador: construyen el registro mínimo que ejercita
cada regla.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from _scripts import carga  # noqa: E402

_m = carga("00a_candidatos_inscritos")
asigna_race_id = _m.asigna_race_id
descarta_accesitarios = _m.descarta_accesitarios
mapa_provincias = _m.mapa_provincias
promueve_regidores = _m.promueve_regidores

COLS = [
    "proceso_id", "tipo_eleccion", "ubigeo", "departamento", "provincia",
    "distrito", "organizacion_id", "organizacion", "tipo_organizacion",
    "solicitud_lista_id", "estado_lista", "candidato_id", "dni", "candidato",
    "cargo", "posicion", "provincia_consejero", "estado_candidato",
    "hoja_vida_id",
]


def fila(**kw) -> dict:
    base = dict.fromkeys(COLS, None)
    base.update(
        proceso_id="126", estado_lista="INSCRITO", estado_candidato="INSCRITO",
        hoja_vida_id="0", organizacion_id="14", organizacion="X",
        tipo_organizacion="PARTIDOS POLITICOS",
    )
    base.update(kw)
    return base


def registro(filas: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLS)


def a_inscritos(todos: pd.DataFrame) -> pd.DataFrame:
    """Réplica de la preparación que hace `construye`, sin tocar disco."""
    ins = todos[
        (todos.estado_lista == "INSCRITO") & (todos.estado_candidato == "INSCRITO")
    ].copy()
    ins = ins.rename(
        columns={
            "candidato_id": "cand_id",
            "solicitud_lista_id": "lista_id",
            "organizacion_id": "id_jne",
        }
    )
    ins["posicion_num"] = ins.posicion.astype(int)
    ins["es_accesitario"] = ins.cargo == "ACCESITARIO"
    ins["origen_candidatura"] = "registro"
    ins["reemplaza_cand_id"] = pd.NA
    return ins


# --- race_id -----------------------------------------------------------------

def test_regional_separa_gobernador_de_consejero():
    """`tipo_eleccion` es REGIONAL para ambos, pero son carreras distintas."""
    todos = registro([
        fila(tipo_eleccion="MUNICIPAL PROVINCIAL", ubigeo="030100",
             departamento="APURIMAC", provincia="ABANCAY",
             solicitud_lista_id="1", candidato_id="1", cargo="ALCALDE PROVINCIAL",
             posicion="0"),
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="2", candidato_id="2",
             cargo="GOBERNADOR REGIONAL", posicion="1"),
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="2", candidato_id="3",
             cargo="CONSEJERO REGIONAL", posicion="1",
             provincia_consejero="ABANCAY"),
    ])
    avisos: list[str] = []
    out = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         avisos)
    por_cand = dict(zip(out.cand_id, out.race_id))
    assert por_cand["2"] == "01-030000", "gobernador: la circunscripción es el depto"
    assert por_cand["3"] == "02-030100", "consejero: la provincia que representa"
    assert avisos == []


def test_consejero_cruza_provincia_con_ene():
    """FERREÑAFE debe cruzar aunque la referencia se escriba sin eñe."""
    todos = registro([
        fila(tipo_eleccion="MUNICIPAL PROVINCIAL", ubigeo="140200",
             departamento="LAMBAYEQUE", provincia="FERREÑAFE",
             solicitud_lista_id="1", candidato_id="1",
             cargo="ALCALDE PROVINCIAL", posicion="0"),
        fila(tipo_eleccion="REGIONAL", ubigeo="140000", departamento="LAMBAYEQUE",
             solicitud_lista_id="2", candidato_id="2",
             cargo="CONSEJERO REGIONAL", posicion="1",
             provincia_consejero="FERRENAFE"),
    ])
    avisos: list[str] = []
    out = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         avisos)
    assert out.set_index("cand_id").race_id["2"] == "02-140200"


def test_consejero_sin_provincia_queda_nulo_y_avisa():
    """Regla dura: no se inventa. Sin provincia, race_id nulo y aviso."""
    todos = registro([
        fila(tipo_eleccion="REGIONAL", ubigeo="160000", departamento="LORETO",
             solicitud_lista_id="1", candidato_id="1", cargo="ACCESITARIO",
             posicion="1", provincia_consejero=None),
    ])
    avisos: list[str] = []
    out = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         avisos)
    assert out.race_id.isna().all()
    assert len(avisos) == 1 and "sin ubigeo de provincia" in avisos[0]


# --- Regla 1: promoción por vacancia de alcaldía ------------------------------

def plancha(estado_alcalde: str, estado_r1: str = "INSCRITO") -> pd.DataFrame:
    return registro([
        fila(tipo_eleccion="MUNICIPAL DISTRITAL", ubigeo="140140",
             departamento="LIMA", provincia="LIMA", distrito="SAN BORJA",
             solicitud_lista_id="9", candidato_id="100", dni="A",
             cargo="ALCALDE DISTRITAL", posicion="0",
             estado_candidato=estado_alcalde),
        fila(tipo_eleccion="MUNICIPAL DISTRITAL", ubigeo="140140",
             departamento="LIMA", provincia="LIMA", distrito="SAN BORJA",
             solicitud_lista_id="9", candidato_id="101", dni="B",
             cargo="REGIDOR DISTRITAL", posicion="1",
             estado_candidato=estado_r1),
        fila(tipo_eleccion="MUNICIPAL DISTRITAL", ubigeo="140140",
             departamento="LIMA", provincia="LIMA", distrito="SAN BORJA",
             solicitud_lista_id="9", candidato_id="102", dni="C",
             cargo="REGIDOR DISTRITAL", posicion="2"),
    ])


@pytest.mark.parametrize("caido", ["RENUNCIA", "EXCLUSION", "IMPROCEDENTE",
                                   "RETIRO", "TACHADO", "INADMISIBLE"])
def test_alcalde_caido_promueve_al_regidor_1(caido):
    todos = plancha(caido)
    ins = a_inscritos(todos)
    avisos: list[str] = []
    nuevas = promueve_regidores(ins, todos, avisos)

    assert len(nuevas) == 1
    p = nuevas.iloc[0]
    assert p.dni == "B", "promueve al regidor 1"
    assert p.cargo == "ALCALDE DISTRITAL"
    assert p.posicion == "0"
    assert p.origen_candidatura == "promocion_por_vacancia"
    assert p.reemplaza_cand_id == "100"
    assert p.cand_id == "101-ALC", "cand_id propio: es otra candidatura"
    assert avisos == []


def test_el_promovido_conserva_su_candidatura_a_regidor():
    """Puede resultar electo en ambas, así que quedan dos filas para la persona."""
    todos = plancha("RENUNCIA")
    ins = a_inscritos(todos)
    salida = pd.concat([ins, promueve_regidores(ins, todos, [])], ignore_index=True)

    filas_b = salida[salida.dni == "B"]
    assert len(filas_b) == 2
    assert set(filas_b.cargo) == {"ALCALDE DISTRITAL", "REGIDOR DISTRITAL"}
    assert filas_b.cand_id.nunique() == 2


def test_alcalde_en_pie_no_promueve_a_nadie():
    todos = plancha("INSCRITO")
    assert promueve_regidores(a_inscritos(todos), todos, []).empty


def test_cascada_cuando_el_regidor_1_tambien_cayo():
    """Si el reemplazo natural también cayó, baja al siguiente inscrito."""
    todos = plancha("RENUNCIA", estado_r1="IMPROCEDENTE")
    nuevas = promueve_regidores(a_inscritos(todos), todos, [])
    assert len(nuevas) == 1
    assert nuevas.iloc[0].dni == "C", "salta al regidor 2"


def test_regidor_1_en_tramite_no_se_salta():
    """ADMITIDO no es caída: no se le puede pasar por encima. Se reporta."""
    todos = plancha("RENUNCIA", estado_r1="ADMITIDO")
    avisos: list[str] = []
    nuevas = promueve_regidores(a_inscritos(todos), todos, avisos)
    assert nuevas.empty
    assert len(avisos) == 1 and "regidor 1 en ADMITIDO" in avisos[0]


# --- Regla 2: accesitarios ----------------------------------------------------

def consejo(estado_titular: str) -> pd.DataFrame:
    return registro([
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="5", candidato_id="200", dni="T",
             cargo="CONSEJERO REGIONAL", posicion="1",
             provincia_consejero="ABANCAY", estado_candidato=estado_titular),
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="5", candidato_id="201", dni="A",
             cargo="ACCESITARIO", posicion="1", provincia_consejero="ABANCAY"),
        fila(tipo_eleccion="MUNICIPAL PROVINCIAL", ubigeo="030100",
             departamento="APURIMAC", provincia="ABANCAY",
             solicitud_lista_id="6", candidato_id="202",
             cargo="ALCALDE PROVINCIAL", posicion="0"),
    ])


def test_accesitario_se_descarta_si_el_titular_esta_inscrito():
    todos = consejo("INSCRITO")
    ins = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         [])
    out, n = descarta_accesitarios(ins)
    assert n == 1
    assert "A" not in set(out.dni), "solo el titular puede resultar electo"
    assert "T" in set(out.dni)


def test_accesitario_se_conserva_si_el_titular_no_esta_inscrito():
    todos = consejo("EXCLUSION")
    ins = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         [])
    out, n = descarta_accesitarios(ins)
    assert n == 0
    assert "A" in set(out.dni), "sin titular en pie, el accesitario es relevante"


def test_accesitario_no_se_confunde_entre_provincias():
    """Mismo número de posición en otra provincia no cuenta como titular."""
    todos = registro([
        fila(tipo_eleccion="MUNICIPAL PROVINCIAL", ubigeo="030100",
             departamento="APURIMAC", provincia="ABANCAY",
             solicitud_lista_id="6", candidato_id="1",
             cargo="ALCALDE PROVINCIAL", posicion="0"),
        fila(tipo_eleccion="MUNICIPAL PROVINCIAL", ubigeo="030300",
             departamento="APURIMAC", provincia="ANDAHUAYLAS",
             solicitud_lista_id="7", candidato_id="2",
             cargo="ALCALDE PROVINCIAL", posicion="0"),
        # Titular en ABANCAY, accesitario en ANDAHUAYLAS, misma lista y posición.
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="5", candidato_id="200", dni="T",
             cargo="CONSEJERO REGIONAL", posicion="1",
             provincia_consejero="ABANCAY"),
        fila(tipo_eleccion="REGIONAL", ubigeo="030000", departamento="APURIMAC",
             solicitud_lista_id="5", candidato_id="201", dni="A",
             cargo="ACCESITARIO", posicion="1",
             provincia_consejero="ANDAHUAYLAS"),
    ])
    ins = asigna_race_id(a_inscritos(todos), mapa_provincias(todos), {}, Path("/x"),
                         [])
    out, n = descarta_accesitarios(ins)
    assert n == 0
    assert "A" in set(out.dni)
