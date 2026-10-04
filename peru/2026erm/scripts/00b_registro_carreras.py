#!/usr/bin/env python3
"""Construye `distritos.csv` y `carreras.csv`, las dos tablas espinales.

`distritos.csv` es la tabla que elimina las excepciones: cada distrito declara en
qué carreras participa, con `race_id` o nulo. Ningún script debe volver a derivar
esas reglas — se leen de aquí (shared/ARQUITECTURA.md §2).

Las excepciones se declaran como **datos**:

  - Distritos de Lima Metropolitana (`1401xx`): sin gobernador ni consejero.
  - Distritos del Callao: `race_consejero` a nivel de distrito, no de provincia.
  - Cercados (capitales de provincia): sin carrera distrital, porque los gobierna
    la municipalidad provincial.
  - Cuatro provincias donde el cercado no es el `01`, en
    `data/reference/cercados_excepcion.csv`.

Uso:
    uv run python scripts/00b_registro_carreras.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datapol.fuentes import CANDIDATOS_CSV, lee_candidatos, normaliza  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

UBIGEO_CALLAO = "24"
UBIGEO_LIMA_METROPOLITANA = "1401"


def construye_distritos(df: pd.DataFrame, excepciones: pd.DataFrame,
                        consejeros: pd.DataFrame, callao: pd.DataFrame,
                        catalogo: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    avisos: list[str] = []

    provincias = (
        df[df.tipo_eleccion == "MUNICIPAL PROVINCIAL"][
            ["ubigeo", "departamento", "provincia"]
        ]
        .drop_duplicates()
        .rename(columns={"ubigeo": "ubigeo_provincia"})
    )
    con_carrera = (
        df[df.tipo_eleccion == "MUNICIPAL DISTRITAL"][
            ["ubigeo", "departamento", "provincia", "distrito"]
        ]
        .drop_duplicates()
        .rename(columns={"ubigeo": "ubigeo_distrito", "distrito": "nombre_distrito"})
    )
    con_carrera["es_cercado"] = False

    # Un cercado por provincia. Normalmente el `01`; cuatro no lo son.
    override = dict(zip(excepciones.ubigeo_provincia, excepciones.ubigeo_cercado))
    cercados = provincias.copy()
    cercados["ubigeo_distrito"] = [
        override.get(u, u[:4] + "01") for u in cercados.ubigeo_provincia
    ]
    # El nombre del cercado no está en el registro: no tiene carrera distrital y
    # por tanto no genera filas. No se inventa.
    cercados["nombre_distrito"] = pd.NA
    cercados["es_cercado"] = True
    cercados = cercados[
        ["ubigeo_distrito", "departamento", "provincia", "nombre_distrito", "es_cercado"]
    ]

    choque = set(cercados.ubigeo_distrito) & set(con_carrera.ubigeo_distrito)
    if choque:
        avisos.append(
            f"{len(choque)} cercados colisionan con un distrito que sí tiene "
            f"carrera: {sorted(choque)}. Falta una excepción en "
            f"cercados_excepcion.csv."
        )

    d = pd.concat([con_carrera, cercados], ignore_index=True)
    d["ubigeo_provincia"] = d.ubigeo_distrito.str[:4] + "00"
    d["ubigeo_departamento"] = d.ubigeo_distrito.str[:2] + "0000"
    d = d.rename(columns={"departamento": "nombre_departamento",
                          "provincia": "nombre_provincia"})

    # --- Las excepciones, como datos ---
    es_lima_metro = d.ubigeo_distrito.str.startswith(UBIGEO_LIMA_METROPOLITANA)
    es_callao = d.ubigeo_distrito.str.startswith(UBIGEO_CALLAO)

    # Gobernador: todo el país menos Lima Metropolitana, que no elige.
    d["race_gobernador"] = [
        None if lm else f"01-{u}"
        for lm, u in zip(es_lima_metro, d.ubigeo_departamento)
    ]

    # Consejero: la provincia; en el Callao, el distrito. Lima Metropolitana no
    # elige consejeros.
    d["race_consejero"] = [
        None if lm else (f"02-{ud}" if c else f"02-{up}")
        for lm, c, ud, up in zip(
            es_lima_metro, es_callao, d.ubigeo_distrito, d.ubigeo_provincia
        )
    ]

    # Provincial: todos los distritos participan en la carrera de su provincia.
    d["race_provincial"] = "03-" + d.ubigeo_provincia

    # Distrital: todos menos los cercados.
    d["race_distrital"] = [
        None if cerc else f"04-{u}"
        for cerc, u in zip(d.es_cercado, d.ubigeo_distrito)
    ]

    # Los cercados no tienen carrera distrital y por tanto no aparecen en el
    # registro de candidaturas: su nombre sale del catálogo de ubigeos.
    nombres_catalogo = dict(zip(catalogo.ubigeo_distrito, catalogo.nombre_distrito))
    d["nombre_distrito"] = [
        nombres_catalogo.get(u, n) if (n is None or pd.isna(n)) else n
        for u, n in zip(d.ubigeo_distrito, d.nombre_distrito)
    ]

    # El catálogo es una fuente independiente del registro: si difieren en qué
    # distritos existen, hay que saberlo.
    solo_registro = set(d.ubigeo_distrito) - set(catalogo.ubigeo_distrito)
    solo_catalogo = set(catalogo.ubigeo_distrito) - set(d.ubigeo_distrito)
    if solo_registro or solo_catalogo:
        avisos.append(
            f"El catálogo y el registro no coinciden: {len(solo_registro)} solo en "
            f"el registro {sorted(solo_registro)[:5]}, {len(solo_catalogo)} solo en "
            f"el catálogo {sorted(solo_catalogo)[:5]}."
        )
    # Y donde ambos nombran el mismo distrito, deben decir lo mismo.
    con_carrera_nombres = dict(
        zip(con_carrera.ubigeo_distrito, con_carrera.nombre_distrito)
    )
    discrepan = [
        (u, n, nombres_catalogo[u])
        for u, n in con_carrera_nombres.items()
        if u in nombres_catalogo and normaliza(n) != normaliza(nombres_catalogo[u])
    ]
    if discrepan:
        avisos.append(
            f"{len(discrepan)} distritos con nombre distinto entre registro y "
            f"catálogo: {discrepan[:5]}"
        )

    d = d.rename(columns={"es_cercado": "es_capital_provincia"})
    d = d[[
        "ubigeo_distrito", "ubigeo_provincia", "ubigeo_departamento",
        "nombre_distrito", "nombre_provincia", "nombre_departamento",
        "race_gobernador", "race_consejero", "race_provincial", "race_distrital",
        "es_capital_provincia",
    ]].sort_values("ubigeo_distrito").reset_index(drop=True)

    sin_carrera = d[[c for c in d.columns if c.startswith("race_")]].isna().all(axis=1)
    if sin_carrera.any():
        avisos.append(f"{int(sin_carrera.sum())} distritos sin ninguna carrera.")

    # El consejo del Callao debe cubrir exactamente las 7 circunscripciones de la
    # tabla de referencia.
    callao_ref = set(consejeros[consejeros.departamento == "CALLAO"].provincia.map(normaliza))
    n_callao = int(es_callao.sum())
    if n_callao != len(callao_ref):
        avisos.append(
            f"El Callao tiene {n_callao} distritos pero la referencia declara "
            f"{len(callao_ref)} circunscripciones de consejero."
        )
    return d, avisos


def construye_carreras(d: pd.DataFrame, df: pd.DataFrame,
                       consejeros: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    avisos: list[str] = []
    filas = []

    # Una carrera por race_id distinto que aparezca en distritos.csv, con su
    # circunscripción y el nivel al que corresponde.
    niveles = {
        "race_gobernador": ("01", "departamento", "gobernador", "—"),
        "race_consejero": ("02", "provincia", None, "consejero"),
        "race_provincial": ("03", "provincia", "alcalde_provincial", "regidor_provincial"),
        "race_distrital": ("04", "distrito", "alcalde_distrital", "regidor_distrital"),
    }
    for col, (tipo, nivel, ejec, prop) in niveles.items():
        vistos = d[col].dropna().unique()
        for race_id in vistos:
            ubigeo = race_id.split("-")[1]
            filas.append({
                "race_id": race_id, "tipo": tipo, "ubigeo": ubigeo,
                "nivel_circunscripcion": nivel,
                "cargo_ejecutivo": ejec, "cargo_proporcional": prop,
            })

    c = pd.DataFrame(filas)
    # El nivel del consejero del Callao es distrito, no provincia: se corrige
    # aquí porque la circunscripción lo dice, no el tipo de elección (regla 9).
    es_callao_consejero = (c.tipo == "02") & c.ubigeo.str.startswith(UBIGEO_CALLAO)
    c.loc[es_callao_consejero, "nivel_circunscripcion"] = "distrito"

    # Nombres, desde distritos.csv.
    nombres_dep = dict(zip(d.ubigeo_departamento, d.nombre_departamento))
    nombres_prov = dict(zip(d.ubigeo_provincia, d.nombre_provincia))
    nombres_dist = dict(zip(d.ubigeo_distrito, d.nombre_distrito))
    def nombre(u: str):
        # El cercado no tiene nombre en el registro, así que su entrada en
        # nombres_dist es NA y hay que saltarla explícitamente: `or` sobre pd.NA
        # revienta.
        for tabla in (nombres_dist, nombres_prov, nombres_dep):
            v = tabla.get(u)
            if v is not None and not pd.isna(v):
                return v
        return pd.NA

    c["nombre_circunscripcion"] = [nombre(u) for u in c.ubigeo]

    # n_escanos de consejeros, desde la resolución del JNE (fase 02 lo completa
    # para regidores).
    ref = consejeros.copy()
    ref["k"] = [
        (normaliza(dep), normaliza(prov))
        for dep, prov in zip(ref.departamento, ref.provincia)
    ]
    escanos_consejero = dict(zip(ref.k, ref.consejeros_total))

    prov_por_ubigeo = {
        u: (normaliza(dep), normaliza(prov))
        for u, dep, prov in zip(d.ubigeo_provincia, d.nombre_departamento,
                                d.nombre_provincia)
    }
    # En el Callao la llave de la referencia es el nombre del distrito.
    dist_por_ubigeo = {
        u: (normaliza(dep), normaliza(nom))
        for u, dep, nom in zip(d.ubigeo_distrito, d.nombre_departamento,
                               d.nombre_distrito)
        if nom is not None and not pd.isna(nom)
    }

    def escanos(fila):
        if fila.tipo != "02":
            return pd.NA
        llave = (dist_por_ubigeo if fila.nivel_circunscripcion == "distrito"
                 else prov_por_ubigeo).get(fila.ubigeo)
        return escanos_consejero.get(llave, pd.NA)

    c["n_escanos"] = [escanos(f) for f in c.itertuples()]
    c["fuente_n_escanos"] = [
        "Res. 0001-2026-JNE" if t == "02" and not pd.isna(n) else pd.NA
        for t, n in zip(c.tipo, c.n_escanos)
    ]

    # --- Regidores, por conteo de candidatos ---
    # La lista de regidores no incluye al alcalde y es de largo par por la ley de
    # paridad, mientras el número de regidores es impar: n = candidatos - 1.
    # Se toma el máximo por concejo, porque una lista incompleta subestima.
    regidores = df[df.cargo.isin({"REGIDOR PROVINCIAL", "REGIDOR DISTRITAL"})]
    por_lista = regidores.groupby(["ubigeo", "solicitud_lista_id"]).size()
    n_regidores = (por_lista.groupby("ubigeo").max() - 1).to_dict()

    es_municipal = c.tipo.isin({"03", "04"})
    c.loc[es_municipal, "n_escanos"] = [
        n_regidores.get(u, pd.NA) for u in c.loc[es_municipal, "ubigeo"]
    ]
    c.loc[es_municipal, "fuente_n_escanos"] = [
        pd.NA if pd.isna(n_regidores.get(u, pd.NA)) else "conteo_candidatos_erm2026"
        for u in c.loc[es_municipal, "ubigeo"]
    ]

    municipales = c[es_municipal]
    sin_escanos = municipales[municipales.n_escanos.isna()]
    if len(sin_escanos):
        avisos.append(
            f"{len(sin_escanos)} concejos sin n_escanos: no tienen ninguna lista "
            f"en el registro. {sorted(sin_escanos.race_id)[:8]}"
        )
    pares = municipales[
        municipales.n_escanos.notna() & (municipales.n_escanos % 2 == 0)
    ]
    if len(pares):
        avisos.append(
            f"{len(pares)} concejos con número PAR de regidores, que es imposible: "
            f"{sorted(pares.race_id)[:8]}"
        )
    fuera = municipales[
        municipales.n_escanos.notna()
        & ~municipales.n_escanos.between(5, 15)
        & (municipales.race_id != "03-140100")  # Lima Metropolitana, 39 por ley
    ]
    if len(fuera):
        avisos.append(
            f"{len(fuera)} concejos fuera del rango legal 5–15: "
            f"{sorted(fuera.race_id)[:8]}"
        )

    # Segunda vuelta y umbral: solo el gobernador la tiene. Alcalde provincial y
    # distrital, mayoría simple y nunca segunda vuelta
    # (shared/REGLAS-ELECTORALES.md).
    c["tiene_segunda_vuelta"] = c.tipo == "01"
    c["umbral_primera_vuelta"] = [0.30 if t == "01" else pd.NA for t in c.tipo]

    # id_tipo_jne: el tipo de elección con que el JNE indexa sus servicios.
    # Consejero comparte el 4 (REGIONAL) con gobernador; no es un tipo aparte.
    c["id_tipo_jne"] = c.tipo.map({"01": "4", "02": "4", "03": "5", "04": "6"})

    # `estado` arranca en normal; la fase 07 lo mueve a sin_eleccion o suspendida
    # si el JNE lo declara.
    c["estado"] = "normal"

    # Se pueblan en fases posteriores: electores y mesas salen de la ONPE
    # (fase 04); n_escanos de regidores, de la Res. 0847-2025-JNE (fase 02).
    for col in ("electores_habiles", "n_mesas", "jee", "odpe"):
        c[col] = pd.NA

    faltan = c[(c.tipo == "02") & c.n_escanos.isna()]
    if len(faltan):
        avisos.append(
            f"{len(faltan)} carreras de consejero sin n_escanos resuelto: "
            f"{sorted(faltan.race_id)[:8]}"
        )

    c = c[[
        "race_id", "tipo", "id_tipo_jne", "ubigeo", "nivel_circunscripcion",
        "nombre_circunscripcion", "cargo_ejecutivo", "cargo_proporcional",
        "n_escanos", "fuente_n_escanos", "umbral_primera_vuelta",
        "tiene_segunda_vuelta", "electores_habiles", "n_mesas", "jee", "odpe",
        "estado",
    ]].sort_values(["tipo", "ubigeo"]).reset_index(drop=True)
    return c, avisos


def cuadres(d: pd.DataFrame, c: pd.DataFrame, consejeros: pd.DataFrame) -> list[str]:
    """Los números no son aproximados. Si no dan, hay un error."""
    fallos = []

    def chequea(etiqueta, obtenido, esperado):
        marca = "OK  " if obtenido == esperado else "MAL "
        print(f"  {marca} {etiqueta:44s} {obtenido:>6,}  esperado {esperado:>6,}")
        if obtenido != esperado:
            fallos.append(f"{etiqueta}: {obtenido} != {esperado}")

    print("\nCUADRES — distritos")
    chequea("filas de distritos.csv", len(d), 1892)
    chequea("cercados (sin carrera distrital)", int(d.es_capital_provincia.sum()), 196)
    chequea("distritos con carrera distrital", int(d.race_distrital.notna().sum()), 1696)
    chequea("Lima Metropolitana sin gobernador",
            int(d.race_gobernador.isna().sum()), 43)
    chequea("Lima Metropolitana sin consejero",
            int(d.race_consejero.isna().sum()), 43)
    chequea("Callao con consejero distrital",
            int((d.race_consejero.notna()
                 & d.ubigeo_distrito.str.startswith(UBIGEO_CALLAO)
                 & (d.race_consejero == "02-" + d.ubigeo_distrito)).sum()), 7)

    print("\nCUADRES — carreras")
    por_tipo = c.tipo.value_counts()
    chequea("gobernador (01)", int(por_tipo.get("01", 0)), 25)
    chequea("consejero (02)", int(por_tipo.get("02", 0)), 201)
    chequea("alcalde provincial (03)", int(por_tipo.get("03", 0)), 196)
    chequea("alcalde distrital (04)", int(por_tipo.get("04", 0)), 1696)
    chequea("total de carreras", len(c), 2118)
    chequea("race_id duplicados", int(c.race_id.duplicated().sum()), 0)

    print("\nCUADRES — escaños")
    n_consejeros = int(c[c.tipo == "02"].n_escanos.fillna(0).sum())
    n_regidores = int(c[c.tipo.isin({"03", "04"})].n_escanos.fillna(0).sum())
    chequea("Σ consejeros (Res. 0001-2026-JNE)", n_consejeros, 364)
    chequea("filas de la referencia", len(consejeros), 201)
    chequea("Σ regidores (conteo de candidatos)", n_regidores, 10842)

    # La identidad completa de shared/REGLAS-ELECTORALES.md.
    n_gob = int((c.tipo == "01").sum())
    n_alc_prov = int((c.tipo == "03").sum())
    n_alc_dist = int((c.tipo == "04").sum())
    autoridades = (n_gob * 2) + n_consejeros + n_alc_prov + n_alc_dist + n_regidores
    print("\nCUADRE FINAL — autoridades")
    print(f"       {n_gob} gobernadores + {n_gob} vicegobernadores")
    print(f"     + {n_consejeros} consejeros")
    print(f"     + {n_alc_prov} alcaldes provinciales + {n_alc_dist} distritales")
    print(f"     + {n_regidores:,} regidores")
    chequea("total de autoridades en disputa", autoridades, 13148)
    return fallos


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--candidatos", type=Path, default=CANDIDATOS_CSV)
    p.add_argument("--referencia", type=Path, default=RAIZ / "data/reference")
    p.add_argument("--out", type=Path, default=RAIZ / "data/reference")
    args = p.parse_args()

    df = lee_candidatos(args.candidatos)
    excepciones = pd.read_csv(args.referencia / "cercados_excepcion.csv", dtype=str)
    consejeros = pd.read_csv(args.referencia / "consejeros_2026.csv")
    callao = pd.read_csv(
        args.referencia / "callao_circunscripciones_consejero.csv", dtype=str
    )

    catalogo = pd.read_csv(args.referencia / "distritos_catalogo.csv", dtype=str)
    d, avisos_d = construye_distritos(df, excepciones, consejeros, callao, catalogo)
    c, avisos_c = construye_carreras(d, df, consejeros)

    args.out.mkdir(parents=True, exist_ok=True)
    d.to_csv(args.out / "distritos.csv", index=False)
    c.to_csv(args.out / "carreras.csv", index=False)
    print(f"escrito: {args.out / 'distritos.csv'}  ({len(d):,} filas)")
    print(f"         {args.out / 'carreras.csv'}   ({len(c):,} filas)")

    fallos = cuadres(d, c, consejeros)

    avisos = avisos_d + avisos_c
    if avisos:
        print("\nAVISOS:")
        for a in avisos:
            print(f"  - {a}")

    if fallos:
        print(f"\n{len(fallos)} CUADRE(S) NO DAN. No se avanza hasta resolverlos.")
        return 1
    print("\nTodos los cuadres dan exacto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
