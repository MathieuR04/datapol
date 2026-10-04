#!/usr/bin/env python3
"""Los alcaldes en ejercicio que vuelven como teniente alcalde.

LA REELECCIÓN INMEDIATA ESTÁ PROHIBIDA
--------------------------------------
Desde la Ley 30305 ningún alcalde puede ser reelegido para el período siguiente.
La vía que queda es entrar al concejo por la puerta de al lado: encabezar la
**lista de regidores** de su organización, que es el puesto de teniente alcalde.
Son 135 casos en ERM 2026, y no son una anécdota: 21 provinciales y 114
distritales, entre ellos la provincia de Lima.

DIRECTO E INDIRECTO
-------------------
La posición 1 de la lista de regidores es siempre la misma; lo que cambia es si
el candidato a alcalde de esa lista sigue en pie:

  · INDIRECTO — la cabeza de lista está viva. El alcalde vuelve al concejo como
    teniente alcalde, no al sillón. Gobierna otro y él se sienta al lado.

  · DIRECTO — la cabeza de lista se cayó (renunció, fue excluida, tachada o
    declarada improcedente), así que el teniente pasa a encabezar la lista y el
    alcalde en ejercicio compite **por la alcaldía**. La prohibición se vuelve
    letra muerta sin que nadie la haya derogado.

La distinción no es interpretación nuestra: sale del `estado_candidato` del
alcalde de la misma `solicitud_lista_id`. Sesenta y cinco de las caídas son
RENUNCIA, que es el dato que hace la historia.

QUÉ EMITE
---------
`data/reference/tenientes.csv`: una fila por caso, con el `race_id` de la carrera
a la que postula. Ese `race_id` es lo que permite que la noche del 4 de octubre
se una cada caso con su resultado y se vea, uno por uno, a quién le funcionó.

La tabla es **estática**: sale del registro del JNE, que está cerrado. Se
reconstruye cuando el registro cambia, no durante la noche.

Uso:
    uv run python scripts/00e_tenientes.py
    uv run python scripts/00e_tenientes.py --out data/reference/tenientes.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datapol.fuentes import (  # noqa: E402
    lee_alcaldes_2022,
    lee_candidatos,
    normaliza,
)

RAIZ = Path(__file__).resolve().parents[1]

# Estados en que la candidatura del alcalde de la lista está caída y no vuelve.
# `INADMISIBLE` es subsanable y por eso **no** entra: una lista inadmisible
# todavía puede quedar inscrita, y darla por caída convertiría en «directo» un
# caso que sigue siendo indirecto.
CAIDOS = frozenset({"EXCLUSION", "RENUNCIA", "RETIRO", "TACHADO", "IMPROCEDENTE"})

# El teniente alcalde es la posición 1 de la lista de regidores, y el nivel de la
# carrera sale del cargo: no se deduce del tipo de elección.
REGIDOR_A_TIPO = {"REGIDOR DISTRITAL": "04", "REGIDOR PROVINCIAL": "03"}

COLUMNAS = [
    "race_id",
    "tipo",
    "ubigeo",
    "nivel",
    "region",
    "provincia",
    "distrito",
    "dni",
    "nombre",
    "sexo",
    "edad",
    "candidato_id",
    "hoja_vida_id",
    "cargo_actual",
    "organizacion_2022",
    "organizacion_2026",
    "organizacion_id",
    "cambio_de_organizacion",
    "solicitud_lista_id",
    "estado_lista",
    "estado_candidato",
    "alcalde_de_la_lista",
    "estado_alcalde",
    "via",
]


def _clave_dni(s: pd.Series) -> pd.Series:
    """DNI a ocho dígitos. El registro del JNE los trae sin los ceros delante."""
    return s.fillna("").str.replace(r"\D", "", regex=True).str.zfill(8)


def construye(candidatos: pd.DataFrame, alcaldes: pd.DataFrame) -> pd.DataFrame:
    alc = alcaldes.copy()
    alc["dni_k"] = _clave_dni(alc["dni"])
    for c in ("region", "provincia", "distrito"):
        alc[c + "_k"] = alc[c].map(normaliza).fillna("")
    alc = alc[alc["dni_k"] != "00000000"]

    # Un alcalde se identifica por DNI **y** por su territorio: el mismo DNI en
    # otro distrito es otra persona o, peor, un homónimo del registro. Cruzar
    # solo por DNI mete casos que no son reelección de nadie.
    provinciales = alc[alc["distrito_k"] == ""].set_index(
        ["dni_k", "region_k", "provincia_k"]
    )
    distritales = alc[alc["distrito_k"] != ""].set_index(
        ["dni_k", "region_k", "provincia_k", "distrito_k"]
    )

    cand = candidatos.copy()
    cand = cand[cand["cargo"].isin(REGIDOR_A_TIPO)]
    cand = cand[cand["posicion"].astype(str).str.strip() == "1"]
    cand["dni_k"] = _clave_dni(cand["dni"])
    for origen, destino in (
        ("departamento", "region_k"),
        ("provincia", "provincia_k"),
        ("distrito", "distrito_k"),
    ):
        cand[destino] = cand[origen].map(normaliza).fillna("")

    # El alcalde que encabeza cada lista, para saber si sigue en pie.
    ejecutivo = candidatos[candidatos["cargo"].str.startswith("ALCALDE", na=False)]
    ejecutivo = ejecutivo.drop_duplicates("solicitud_lista_id").set_index(
        "solicitud_lista_id"
    )

    filas = []
    for r in cand.itertuples(index=False):
        if r.cargo == "REGIDOR DISTRITAL":
            clave = (r.dni_k, r.region_k, r.provincia_k, r.distrito_k)
            fuente, nivel = distritales, "distrital"
        else:
            clave = (r.dni_k, r.region_k, r.provincia_k)
            fuente, nivel = provinciales, "provincial"
        if clave not in fuente.index:
            continue
        previo = fuente.loc[clave]
        if isinstance(previo, pd.DataFrame):  # homónimo exacto: no se adivina
            continue

        alcalde = (
            ejecutivo.loc[r.solicitud_lista_id]
            if r.solicitud_lista_id in ejecutivo.index
            else None
        )
        # Una lista sin candidato a alcalde es una cabeza caída tanto como una
        # renunciada: en los dos casos el teniente termina encabezándola.
        estado_alcalde = (
            "SIN CANDIDATO" if alcalde is None else (alcalde.estado_candidato or "")
        )
        caida = estado_alcalde in CAIDOS or alcalde is None

        org_2022 = (previo.organizacion_politica or "").strip()
        org_2026 = (r.organizacion or "").strip()

        filas.append(
            {
                "race_id": f"{REGIDOR_A_TIPO[r.cargo]}-{r.ubigeo}",
                "tipo": REGIDOR_A_TIPO[r.cargo],
                "ubigeo": r.ubigeo,
                "nivel": nivel,
                "region": r.departamento,
                "provincia": r.provincia,
                "distrito": r.distrito,
                "dni": r.dni,
                "nombre": r.candidato,
                "sexo": r.sexo,
                "edad": r.edad,
                "candidato_id": r.candidato_id,
                "hoja_vida_id": r.hoja_vida_id,
                "cargo_actual": (
                    "ALCALDE DISTRITAL" if nivel == "distrital" else "ALCALDE PROVINCIAL"
                ),
                "organizacion_2022": org_2022,
                "organizacion_2026": org_2026,
                "organizacion_id": r.organizacion_id,
                # El salto de organización se juzga sobre el nombre plegado: el
                # JNE escribe la misma organización con y sin tildes.
                "cambio_de_organizacion": bool(org_2022)
                and normaliza(org_2022) != normaliza(org_2026),
                "solicitud_lista_id": r.solicitud_lista_id,
                "estado_lista": r.estado_lista,
                "estado_candidato": r.estado_candidato,
                "alcalde_de_la_lista": "" if alcalde is None else alcalde.candidato,
                "estado_alcalde": estado_alcalde,
                "via": "directo" if caida else "indirecto",
            }
        )

    df = pd.DataFrame(filas, columns=COLUMNAS)
    return df.sort_values(["region", "provincia", "distrito", "nombre"]).reset_index(
        drop=True
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--candidatos", type=Path, default=None,
                   help="registro de candidaturas ERM 2026 (por defecto, el del operador)")
    p.add_argument("--alcaldes", type=Path, default=None,
                   help="alcaldes electos en ERM 2022 (por defecto, el del operador)")
    p.add_argument("--carreras", type=Path,
                   default=RAIZ / "data/reference/carreras.csv",
                   help="registro de carreras, para validar cada race_id")
    p.add_argument("--out", type=Path, default=RAIZ / "data/reference/tenientes.csv")
    args = p.parse_args()

    candidatos = (
        lee_candidatos(args.candidatos) if args.candidatos else lee_candidatos()
    )
    alcaldes = (
        lee_alcaldes_2022(args.alcaldes) if args.alcaldes else lee_alcaldes_2022()
    )
    df = construye(candidatos, alcaldes)

    # Un `race_id` que no está en el registro es un caso que la noche electoral
    # no se podría unir con ningún resultado. Es un error, no un aviso.
    carreras = set(pd.read_csv(args.carreras, dtype=str)["race_id"])
    huerfanos = sorted(set(df["race_id"]) - carreras)
    if huerfanos:
        print(
            f"race_id fuera del registro de carreras: {len(huerfanos)} — {huerfanos[:5]}",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    vias = df["via"].value_counts()
    niveles = df["nivel"].value_counts()
    print(f"{len(df)} alcaldes en ejercicio encabezan una lista de regidores")
    print(f"  directo   {vias.get('directo', 0):>4}  la cabeza de lista se cayó")
    print(f"  indirecto {vias.get('indirecto', 0):>4}  vuelven como teniente alcalde")
    print(f"  provincial {niveles.get('provincial', 0):>3} · "
          f"distrital {niveles.get('distrital', 0):>3}")
    print(f"  cambiaron de organización: {int(df['cambio_de_organizacion'].sum())}")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
