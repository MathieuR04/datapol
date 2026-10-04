#!/usr/bin/env python3
"""Construye `candidatos_inscritos` a partir del registro de candidaturas del JNE.

Toma solo lo que está en estado INSCRITO —lista y candidato— y le aplica las dos
reglas que el registro no expresa por sí solo:

  1. Si el candidato a alcalde cae (renuncia, exclusión, tacha, improcedencia),
     el primer regidor inscrito **suma** la candidatura a la alcaldía sin perder
     la suya. Puede resultar electo en ambas o solo como regidor, así que quedan
     dos filas para la misma persona.
  2. El accesitario a consejero regional solo se incluye si su titular no está
     inscrito. Mientras el titular esté en pie, es el único que puede salir electo.

El archivo crece con los días, conforme el JNE va pasando listas a INSCRITO.

Las fuentes se leen en su dirección original y **nunca se modifican ni se copian**:
se actualizan a diario por un flujo ajeno a este repo.

Uso:
    uv run python scripts/00a_candidatos_inscritos.py
    uv run python scripts/00a_candidatos_inscritos.py --out data/processed
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datapol.fuentes import (  # noqa: E402
    CANDIDATOS_CSV,
    HDV_SQLITE,
    lee_candidatos,
    lee_postulacion_hdv,
    normaliza,
)

RAIZ = Path(__file__).resolve().parents[1]

# --- Vocabulario del JNE -----------------------------------------------------
# El estado del candidato es independiente del de su lista: una lista INSCRITO
# puede llevar candidatos caídos. Ver docs/fuentes-locales.md §1.6.

# Estados en que la candidatura está firmemente caída y no vuelve.
CAIDOS = frozenset(
    {"EXCLUSION", "RENUNCIA", "RETIRO", "TACHADO", "IMPROCEDENTE", "INADMISIBLE"}
)

EJECUTIVO_MUNICIPAL = frozenset({"ALCALDE DISTRITAL", "ALCALDE PROVINCIAL"})
REGIDOR = frozenset({"REGIDOR DISTRITAL", "REGIDOR PROVINCIAL"})
CONSEJO_REGIONAL = frozenset({"CONSEJERO REGIONAL", "ACCESITARIO"})

# cargo -> tipo de race_id. Ojo: `tipo_eleccion` no basta, porque REGIONAL
# contiene tanto la carrera de gobernador (01) como las de consejero (02).
TIPO_POR_CARGO = {
    "GOBERNADOR REGIONAL": "01",
    "VICEGOBERNADOR REGIONAL": "01",
    "CONSEJERO REGIONAL": "02",
    "ACCESITARIO": "02",
    "ALCALDE PROVINCIAL": "03",
    "REGIDOR PROVINCIAL": "03",
    "ALCALDE DISTRITAL": "04",
    "REGIDOR DISTRITAL": "04",
}

COLUMNAS_SALIDA = [
    "cand_id", "lista_id", "race_id", "tipo_carrera", "ubigeo_circunscripcion",
    "id_jne", "organizacion", "tipo_organizacion",
    "cargo", "posicion", "es_accesitario",
    "dni", "candidato", "apellido_paterno", "apellido_materno", "nombres",
    "sexo", "fecha_nacimiento", "edad",
    "departamento", "provincia", "distrito",
    "hoja_vida_id", "estado_lista", "estado_candidato",
    "origen_candidatura", "reemplaza_cand_id",
]


# --- Circunscripciones -------------------------------------------------------

def mapa_provincias(df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(departamento, provincia) normalizados -> ubigeo de provincia.

    Se construye del propio registro: las filas MUNICIPAL PROVINCIAL traen las
    196 provincias con su ubigeo. No hay colisión de nombre de provincia entre
    departamentos, así que el par identifica unívocamente.
    """
    prov = df[df.tipo_eleccion == "MUNICIPAL PROVINCIAL"]
    return {
        (normaliza(d), normaliza(p)): u
        for d, p, u in zip(prov.departamento, prov.provincia, prov.ubigeo)
    }


def mapa_callao(ruta: Path) -> dict[str, str]:
    """Distrito del Callao normalizado -> ubigeo de circunscripción.

    En el Callao la circunscripción de consejero es el distrito, no la provincia,
    y el registro colapsa los siete bajo `CALLAO`. Se declara como dato, no como
    lógica (ver shared/ARQUITECTURA.md).
    """
    ref = pd.read_csv(ruta, dtype=str)
    return {normaliza(d): u for d, u in zip(ref.distrito, ref.ubigeo_circunscripcion)}


def resuelve_consejeros_callao(
    base: pd.DataFrame, callao: dict[str, str], hdv_ruta: Path, avisos: list[str]
) -> pd.Series:
    """Ubigeo de circunscripción de los consejeros del Callao, vía hoja de vida.

    `strPostulaDistrito` de la HDV es la única fuente que lo dice. La alternativa
    —segmentar la secuencia de posiciones— **no sirve**: los cinco distritos de un
    escaño son indistinguibles por tamaño de bloque y el orden real no coincide
    con el de la tabla de referencia. Ver docs/fuentes-locales.md §1.5.
    """
    es_callao = (base.departamento == "CALLAO") & base.cargo.isin(CONSEJO_REGIONAL)
    salida = pd.Series(pd.NA, index=base.index, dtype="object")
    if not es_callao.any():
        return salida

    filas = base[es_callao]
    con_hdv = filas[filas.hoja_vida_id != "0"]
    postulaciones = lee_postulacion_hdv(
        [int(h) for h in con_hdv.hoja_vida_id], hdv_ruta
    )

    sin_resolver = 0
    for idx, hv in zip(filas.index, filas.hoja_vida_id):
        p = postulaciones.get(int(hv)) if hv != "0" else None
        ubigeo = callao.get(normaliza(p.distrito)) if p and p.distrito else None
        if ubigeo is None:
            sin_resolver += 1
        salida.at[idx] = ubigeo

    if sin_resolver:
        avisos.append(
            f"{sin_resolver} de {len(filas)} candidatos de consejo del Callao "
            f"quedaron sin distrito: no tienen hoja de vida o su "
            f"`strPostulaDistrito` no cruzó contra la tabla de referencia. "
            f"Van con race_id nulo."
        )
    return salida


def asigna_race_id(
    base: pd.DataFrame, provincias: dict, callao: dict, hdv_ruta: Path,
    avisos: list[str],
) -> pd.DataFrame:
    base = base.copy()
    base["tipo_carrera"] = base.cargo.map(TIPO_POR_CARGO)

    ubigeo = pd.Series(pd.NA, index=base.index, dtype="object")

    # Gobernador y vicegobernador: el departamento, que es el ubigeo de la fila.
    # Municipales: la circunscripción es también el propio ubigeo de la fila.
    directo = base.tipo_carrera.isin({"01", "03", "04"})
    ubigeo[directo] = base.loc[directo, "ubigeo"]

    # Consejo regional: la provincia que representa el candidato, no el
    # departamento. En el Callao, el distrito.
    consejo = base.tipo_carrera == "02"
    fuera_callao = consejo & (base.departamento != "CALLAO")
    ubigeo[fuera_callao] = [
        provincias.get((normaliza(d), normaliza(p)))
        for d, p in zip(
            base.loc[fuera_callao, "departamento"],
            base.loc[fuera_callao, "provincia_consejero"],
        )
    ]
    en_callao = consejo & (base.departamento == "CALLAO")
    if en_callao.any():
        resueltos = resuelve_consejeros_callao(base, callao, hdv_ruta, avisos)
        ubigeo[en_callao] = resueltos[en_callao]

    sin_prov = int((fuera_callao & ubigeo.isna()).sum())
    if sin_prov:
        faltan = sorted(
            {
                f"{d}/{p}"
                for d, p, u in zip(
                    base.loc[fuera_callao, "departamento"],
                    base.loc[fuera_callao, "provincia_consejero"],
                    ubigeo[fuera_callao],
                )
                if pd.isna(u)
            }
        )
        avisos.append(
            f"{sin_prov} consejeros sin ubigeo de provincia resuelto: {faltan}. "
            f"Van con race_id nulo."
        )

    base["ubigeo_circunscripcion"] = ubigeo
    base["race_id"] = [
        None if pd.isna(u) else f"{t}-{u}"
        for t, u in zip(base.tipo_carrera, ubigeo)
    ]
    return base


# --- Reglas ------------------------------------------------------------------

def promueve_regidores(
    inscritos: pd.DataFrame, todos: pd.DataFrame, avisos: list[str]
) -> pd.DataFrame:
    """Regla 1: el alcalde caído lo reemplaza el primer regidor inscrito.

    El reemplazo **conserva** su candidatura a regidor, así que se devuelve una
    fila adicional, no una modificación. Puede resultar electo en ambas.
    """
    municipales = todos[
        (todos.estado_lista == "INSCRITO") & todos.cargo.isin(EJECUTIVO_MUNICIPAL)
    ]
    vacantes = municipales[municipales.estado_candidato.isin(CAIDOS)]
    if vacantes.empty:
        return pd.DataFrame(columns=inscritos.columns)

    nuevas, sin_reemplazo = [], []
    for _, alcalde in vacantes.iterrows():
        lista = alcalde.solicitud_lista_id

        # Si el regidor 1 no está inscrito pero tampoco cayó, no se le puede
        # saltar: la promoción queda sin resolver y se reporta.
        r1 = todos[
            (todos.solicitud_lista_id == lista)
            & todos.cargo.isin(REGIDOR)
            & (todos.posicion == "1")
        ]
        if not r1.empty:
            estado_r1 = r1.iloc[0].estado_candidato
            if estado_r1 != "INSCRITO" and estado_r1 not in CAIDOS:
                sin_reemplazo.append(
                    (lista, alcalde.estado_candidato, f"regidor 1 en {estado_r1}")
                )
                continue

        # Candidatos a regidor de esa lista que sí están inscritos, por posición.
        plancha = inscritos[
            (inscritos.lista_id == lista) & inscritos.cargo.isin(REGIDOR)
        ].sort_values("posicion_num")
        if plancha.empty:
            sin_reemplazo.append(
                (lista, alcalde.estado_candidato, "sin regidor inscrito")
            )
            continue

        sucesor = plancha.iloc[0].copy()
        sucesor["cargo"] = alcalde.cargo
        sucesor["posicion"] = "0"
        sucesor["posicion_num"] = 0
        sucesor["origen_candidatura"] = "promocion_por_vacancia"
        sucesor["reemplaza_cand_id"] = alcalde.candidato_id
        sucesor["cand_id"] = f"{sucesor['cand_id']}-ALC"
        nuevas.append(sucesor)

    if sin_reemplazo:
        detalle = "; ".join(
            f"lista {l} (alcalde {e}, {m})" for l, e, m in sin_reemplazo
        )
        avisos.append(
            f"{len(sin_reemplazo)} vacancias de alcaldía sin promoción resuelta: "
            f"{detalle}. No se promovió a nadie."
        )

    return pd.DataFrame(nuevas) if nuevas else pd.DataFrame(columns=inscritos.columns)


def descarta_accesitarios(inscritos: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Regla 2: el accesitario sobra mientras su titular esté inscrito.

    Solo el titular puede resultar electo. El accesitario se conserva únicamente
    cuando su titular no está inscrito, que es cuando pasa a ser relevante.
    """
    acc = inscritos.cargo == "ACCESITARIO"
    if not acc.any():
        return inscritos, 0

    titulares = {
        (r.lista_id, r.ubigeo_circunscripcion, r.posicion)
        for r in inscritos[inscritos.cargo == "CONSEJERO REGIONAL"].itertuples()
    }
    tiene_titular = pd.Series(
        [
            (r.lista_id, r.ubigeo_circunscripcion, r.posicion) in titulares
            for r in inscritos.itertuples()
        ],
        index=inscritos.index,
    )
    a_descartar = acc & tiene_titular
    return inscritos[~a_descartar].copy(), int(a_descartar.sum())


# --- Orquestación ------------------------------------------------------------

def construye(
    candidatos_csv: Path, hdv_sqlite: Path, callao_ref: Path
) -> tuple[pd.DataFrame, list[str], dict]:
    avisos: list[str] = []
    todos = lee_candidatos(candidatos_csv)

    inscritos = todos[
        (todos.estado_lista == "INSCRITO") & (todos.estado_candidato == "INSCRITO")
    ].copy()

    inscritos = inscritos.rename(
        columns={
            "candidato_id": "cand_id",
            "solicitud_lista_id": "lista_id",
            "organizacion_id": "id_jne",
        }
    )
    inscritos["posicion_num"] = inscritos.posicion.astype(int)
    inscritos["es_accesitario"] = inscritos.cargo == "ACCESITARIO"
    inscritos["origen_candidatura"] = "registro"
    inscritos["reemplaza_cand_id"] = pd.NA

    inscritos = asigna_race_id(
        inscritos, mapa_provincias(todos), mapa_callao(callao_ref), hdv_sqlite, avisos
    )

    n_antes = len(inscritos)
    promovidos = promueve_regidores(inscritos, todos, avisos)
    inscritos, n_accesitarios = descarta_accesitarios(inscritos)

    salida = pd.concat([inscritos, promovidos], ignore_index=True)
    salida = salida.sort_values(
        ["race_id", "lista_id", "posicion_num"], na_position="last"
    ).reset_index(drop=True)

    resumen = {
        "candidatos_inscritos": n_antes,
        "accesitarios_descartados": n_accesitarios,
        "promociones_por_vacancia": len(promovidos),
        "filas_salida": len(salida),
        "listas": salida.lista_id.nunique(),
        "carreras": salida.race_id.nunique(),
        "sin_race_id": int(salida.race_id.isna().sum()),
    }
    return salida[COLUMNAS_SALIDA], avisos, resumen


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--candidatos", type=Path, default=CANDIDATOS_CSV,
                   help="CSV del registro de candidaturas (solo lectura)")
    p.add_argument("--hdv", type=Path, default=HDV_SQLITE,
                   help="sqlite de hojas de vida (solo lectura)")
    p.add_argument("--callao-ref", type=Path,
                   default=RAIZ / "data/reference/callao_circunscripciones_consejero.csv")
    p.add_argument("--out", type=Path, default=RAIZ / "data/processed",
                   help="directorio de salida")
    args = p.parse_args()

    for ruta in (args.candidatos, args.hdv, args.callao_ref):
        if not ruta.exists():
            print(f"ERROR: no existe {ruta}", file=sys.stderr)
            return 1

    salida, avisos, resumen = construye(args.candidatos, args.hdv, args.callao_ref)

    args.out.mkdir(parents=True, exist_ok=True)
    parquet = args.out / "candidatos_inscritos.parquet"
    csv = args.out / "candidatos_inscritos.csv"
    salida.to_parquet(parquet, index=False)
    salida.to_csv(csv, index=False)

    print(f"fuente  : {args.candidatos}")
    print(f"corrida : {date.today().isoformat()}")
    for k, v in resumen.items():
        print(f"  {k:30s} {v:>7,}")
    print(f"\nescrito: {parquet}")
    print(f"         {csv}")

    if avisos:
        print("\nAVISOS (no se rellenó nada, se dejó explícito):")
        for a in avisos:
            print(f"  - {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
