"""Adjudicación completa: del vector de votos a los escaños, con topes reales.

`allocator.py` es la función pura. Este módulo la alimenta: arma, para cada una
de las 2,116 carreras, los dos diccionarios que el reparto necesita y que no se
pueden deducir de los votos.

    disponibles — cuántos candidatos hábiles conserva cada lista. Una lista no
                  puede ocupar más escaños que gente le queda en pie. En ERM
                  2022 hubo 26 concejos donde la lista ganadora tenía menos
                  regidores inscritos que el premio a la mayoría y solo se llevó
                  los que tenía; el resto pasó a las siguientes. Sin este tope el
                  reparto sale mal en esos 26.

    promovidos  — cuántos regidores subieron a la candidatura a alcalde porque
                  el titular cayó. Solo liberan su escaño de regidor **si su
                  lista gana la alcaldía**.

LA LLAVE
--------
Los votos vienen con `codigo_onpe`; el registro de candidaturas con `id_jne`.
El puente es `crosswalk_organizaciones_2022.csv`, construido y validado aparte.
Toda organización que aparezca en los votos y **no** tenga lista en el registro
se deja fuera de `disponibles` a propósito: el allocator la trata como
«no sabemos» y reparte sin topar, que es distinto de «lista sin nadie en pie».

ACCESITARIOS
------------
No cuentan como hábiles para ocupar un escaño de consejero: van en igual número
que los titulares y **no se proclaman**. Se excluyen del conteo.

SALIDA — `data/processed/entradas_adjudicacion_2022.parquet`

    race_id, codigo_onpe, disponibles, promovidos

Uso:
    uv run python -c "from datapol.adjudicacion import construye; construye()"
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .allocator import (Reparto, construye_disponibles, reparte_concejo,
                        reparte_consejo_regional)

RAIZ = Path(__file__).resolve().parents[2]
SALIDA = RAIZ / "data/processed/entradas_adjudicacion_2022.parquet"


def _puente() -> dict[str, str]:
    """id_jne -> codigo_onpe."""
    c = pd.read_csv(RAIZ / "data/reference/crosswalk_organizaciones_2022.csv",
                    dtype=str)
    return dict(zip(c.id_jne, c.codigo_onpe))


def construye(forzar: bool = False) -> pd.DataFrame:
    if SALIDA.exists() and not forzar:
        return pd.read_parquet(SALIDA)

    jne_a_onpe = _puente()
    ins = pd.read_parquet(RAIZ / "data/processed/candidatos_inscritos_2022.parquet")
    reg = pd.read_csv(RAIZ / "data/raw/erm2022_candidatos.csv", dtype=str,
                      usecols=["ubigeo", "tipo_eleccion_id", "cargo",
                               "organizacion_id", "ubigeo_provincia_consejero"],
                      low_memory=False)

    # race_id del registro crudo. El JNE no trae el tipo de carrera: trae el tipo
    # de **elección**, y REGIONAL cubre dos carreras distintas —gobernador y
    # consejeros— que se separan por el cargo. Y la circunscripción de consejero
    # es la provincia, salvo en el Callao, donde el JNE usa un ubigeo de
    # pseudo-provincia (240100) por cada distrito real (240101).
    callao = pd.read_csv(
        RAIZ / "data/reference/callao_circunscripciones_consejero_2022.csv",
        dtype=str)
    jne_a_onpe_ubigeo = dict(zip(callao.ubigeo_jne,
                                 callao.ubigeo_circunscripcion))
    es_consejero = reg.cargo.fillna("").str.startswith(("CONSEJERO", "ACCESITARIO"))
    tipo = pd.Series("", index=reg.index)
    tipo[reg.tipo_eleccion_id == "4"] = "01"
    tipo[(reg.tipo_eleccion_id == "4") & es_consejero] = "02"
    tipo[reg.tipo_eleccion_id == "5"] = "03"
    tipo[reg.tipo_eleccion_id == "6"] = "04"
    circ = reg.ubigeo.where(tipo != "02",
                            reg.ubigeo_provincia_consejero
                               .map(lambda u: jne_a_onpe_ubigeo.get(u, u)))
    reg = reg.assign(race_id=tipo + "-" + circ.fillna(""))
    reg = reg[tipo.ne("") & circ.notna()]
    conocidas = (reg.groupby("race_id").organizacion_id
                    .apply(lambda s: set(s.dropna())).to_dict())

    # Hábiles: solo el cuerpo proporcional, sin accesitarios.
    prop = ins[ins.cargo.str.startswith(("REGIDOR", "CONSEJERO"))
               & ~ins.es_accesitario.astype(bool)]
    habiles = (prop.groupby(["race_id", "id_jne"]).size()
               .rename("habiles").reset_index())
    prom = (ins[ins.origen_candidatura == "promocion_por_vacancia"]
            .groupby(["race_id", "id_jne"]).size()
            .rename("promovidos").reset_index())

    filas = []
    hab_por_carrera = {k: dict(zip(g.id_jne, g.habiles))
                       for k, g in habiles.groupby("race_id")}
    prom_por_carrera = {k: dict(zip(g.id_jne, g.promovidos))
                        for k, g in prom.groupby("race_id")}
    for race_id in sorted(set(conocidas) | set(hab_por_carrera)):
        disp = construye_disponibles(conocidas.get(race_id, set()),
                                     hab_por_carrera.get(race_id, {}))
        pr = prom_por_carrera.get(race_id, {})
        for id_jne, n in disp.items():
            onpe = jne_a_onpe.get(id_jne)
            if onpe is None:
                continue
            filas.append((race_id, onpe, int(n), int(pr.get(id_jne, 0))))

    t = pd.DataFrame(filas, columns=["race_id", "codigo_onpe",
                                     "disponibles", "promovidos"])
    t.to_parquet(SALIDA, index=False)
    return t


class Entradas:
    """Acceso por carrera a `disponibles` y `promovidos`, ya en código ONPE."""

    def __init__(self, tabla: pd.DataFrame | None = None):
        t = construye() if tabla is None else tabla
        self._disp: dict[str, dict[str, int]] = {}
        self._prom: dict[str, dict[str, int]] = {}
        for race_id, g in t.groupby("race_id"):
            self._disp[race_id] = dict(zip(g.codigo_onpe, g.disponibles))
            p = {o: n for o, n in zip(g.codigo_onpe, g.promovidos) if n}
            if p:
                self._prom[race_id] = p

    def de(self, race_id: str) -> dict:
        d = self._disp.get(race_id)
        return {"disponibles": d,
                "promovidos": self._prom.get(race_id)}


def adjudica(votos: dict[str, int], tipo: str, n_escanos: int,
             entradas: dict | None = None) -> Reparto:
    """Reparto de una carrera con los topes reales aplicados."""
    e = entradas or {}
    if tipo == "02":
        return reparte_consejo_regional(votos, n_escanos,
                                        disponibles=e.get("disponibles"))
    return reparte_concejo(votos, n_escanos,
                           disponibles=e.get("disponibles"),
                           promovidos=e.get("promovidos"))
