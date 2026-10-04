#!/usr/bin/env python3
"""Parsea la Res. 0847-2025-JNE y cruza sus regidores contra el conteo de candidatos.

El artículo 1 de la resolución lista solo los concejos con población **mayor a
25,000** habitantes. El artículo 2 cierra: a todo concejo no listado le corresponden
**5 regidores**. Excepción legal: Lima Metropolitana, 39.

La segunda fuente es el registro de candidaturas: `n_regidores = candidatos − 1`,
porque la lista no incluye al alcalde y es de largo par por la ley de paridad.

Este script las compara y **lista cada discrepancia individualmente**, como exige
`specs/02-escanos.md`. No promedia ni elige en silencio.

Requiere `pdftotext` (poppler). Uso:
    uv run python scripts/00c_escanos_regidores.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datapol.fuentes import CANDIDATOS_CSV, lee_candidatos, normaliza  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

# La tabla del artículo 1 va desde el "conforme se detalla a continuación" hasta el
# artículo 2. Acotarla importa: antes hay la tabla de rangos de población del
# considerando 8, y después la de cuota de comunidades, que tiene otras columnas y
# se parecería lo bastante como para colarse.
INICIO_TABLA = re.compile(r"conforme se detalla a", re.I)
FIN_TABLA = re.compile(r"^\s*2\.\s+PRECISAR", re.I)

# El encabezado "NÚMERO DE / REGIDORES" se parte en dos líneas y la primera se
# filtra a la columna de distrito de la primera fila de cada página.
RUIDO = re.compile(
    r"Jurado Nacional|Resoluci|DEPARTAMENTO|REGIDORES|N.º 0847|NÚMERO DE|^\s*\d+\s*$",
    re.I,
)

# Las columnas derivan un par de caracteres entre páginas, así que no se corta por
# posición fija: se parte por corridas de dos o más espacios y cada fragmento se
# asigna a la columna cuyo inicio tiene más cerca.
LIMITE_DEPARTAMENTO = 12
LIMITE_PROVINCIA = 28

REGIDORES_POR_DEFECTO = 5  # Artículo 2: todo concejo no listado.
LIMA_METROPOLITANA = "140100"
REGIDORES_LIMA = 39


def _fragmentos(linea: str) -> list[tuple[int, str]]:
    """Trozos separados por dos o más espacios, con su columna de inicio."""
    return [
        (m.start(), m.group().strip())
        for m in re.finditer(r"\S+(?: \S+)*", linea)
        if m.group().strip()
    ]


def texto_del_pdf(pdf: Path) -> list[str]:
    r = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.split("\n")


def parsea_tabla(lineas: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Extrae (departamento, provincia, distrito, n_regidores) del artículo 1.

    Solo el número de regidores. La tabla de cuota de comunidades campesinas y
    nativas del artículo 3 queda fuera del rango y no se toca.
    """
    avisos: list[str] = []
    filas = []
    # Prefijos colgantes: una línea sin número que continúa la siguiente, como
    # "RODRÍGUEZ DE" sobre "MENDOZA" o "NUEVO" sobre "CHIMBOTE".
    pendiente = {"provincia": "", "distrito": ""}

    dentro = False
    for cruda in lineas:
        if not dentro:
            dentro = bool(INICIO_TABLA.search(cruda))
            continue
        if FIN_TABLA.search(cruda):
            break
        if not cruda.strip() or RUIDO.search(cruda):
            continue

        trozos = _fragmentos(cruda)
        if not trozos:
            continue

        columnas = {"departamento": "", "provincia": "", "distrito": ""}
        numero = None
        for inicio, texto in trozos:
            if texto.isdigit():
                numero = int(texto)
            elif inicio < LIMITE_DEPARTAMENTO:
                columnas["departamento"] = texto
            elif inicio < LIMITE_PROVINCIA:
                columnas["provincia"] = texto
            else:
                columnas["distrito"] = texto

        if numero is None:
            # Continuación: se acumula para pegarla a la fila siguiente. Se
            # **acumula**, no se reemplaza: "CORONEL GREGORIO ALBARRACÍN" ocupa
            # tres líneas antes de "LANCHIPA".
            for campo in ("provincia", "distrito"):
                if columnas[campo] and not columnas["departamento"]:
                    pendiente[campo] = f"{pendiente[campo]} {columnas[campo]}".strip()
            continue

        if not columnas["departamento"]:
            avisos.append(f"Fila con número pero sin departamento: {cruda!r}")
            continue

        for campo in ("provincia", "distrito"):
            if pendiente[campo]:
                columnas[campo] = f"{pendiente[campo]} {columnas[campo]}".strip()
                pendiente[campo] = ""

        filas.append({
            "departamento": columnas["departamento"],
            "provincia": columnas["provincia"],
            "distrito": columnas["distrito"] or None,
            "n_regidores_resolucion": numero,
        })

    if not filas:
        avisos.append("No se encontró ninguna fila: ¿cambió el formato del PDF?")
    return pd.DataFrame(filas), avisos


# La extracción del PDF se come una letra en una fila: el departamento y la
# provincia de Tumbes salen como "TUMES". No es un error de la resolución, es del
# renderizado. Se declara como dato para no meter emparejamiento difuso.
ERRATAS_PDF = {"TUMES": "TUMBES"}


def a_ubigeo(tabla: pd.DataFrame, distritos: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Resuelve cada fila de la resolución al ubigeo de su concejo."""
    avisos: list[str] = []

    por_provincia = {
        (normaliza(dep), normaliza(prov)): u
        for u, dep, prov in zip(distritos.ubigeo_provincia,
                                distritos.nombre_departamento,
                                distritos.nombre_provincia)
    }
    por_distrito = {
        (normaliza(dep), normaliza(prov), normaliza(dist)): u
        for u, dep, prov, dist in zip(distritos.ubigeo_distrito,
                                      distritos.nombre_departamento,
                                      distritos.nombre_provincia,
                                      distritos.nombre_distrito)
        if dist is not None and not pd.isna(dist)
    }

    def limpia(s):
        n = normaliza(s)
        return ERRATAS_PDF.get(n, n)

    ubigeos, sin_resolver = [], []
    for r in tabla.itertuples():
        # Sin distrito = concejo provincial. Ojo: pandas guarda el None como NaN,
        # así que `is None` no sirve.
        if pd.isna(r.distrito):
            u = por_provincia.get((limpia(r.departamento), limpia(r.provincia)))
        else:
            u = por_distrito.get(
                (limpia(r.departamento), limpia(r.provincia), limpia(r.distrito))
            )
        if u is None:
            sin_resolver.append(f"{r.departamento}/{r.provincia}/{r.distrito}")
        ubigeos.append(u)

    tabla = tabla.copy()
    tabla["ubigeo"] = ubigeos
    if sin_resolver:
        avisos.append(
            f"{len(sin_resolver)} filas de la resolución sin ubigeo resuelto: "
            f"{sin_resolver}"
        )
    return tabla, avisos


def conteo_de_candidatos(df: pd.DataFrame) -> dict[str, int]:
    regidores = df[df.cargo.isin({"REGIDOR PROVINCIAL", "REGIDOR DISTRITAL"})]
    por_lista = regidores.groupby(["ubigeo", "solicitud_lista_id"]).size()
    return (por_lista.groupby("ubigeo").max() - 1).to_dict()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--pdf", type=Path,
                   default=RAIZ / "data/reference/res_0847_2025_JNE_regidores.pdf")
    p.add_argument("--distritos", type=Path,
                   default=RAIZ / "data/reference/distritos.csv")
    p.add_argument("--candidatos", type=Path, default=CANDIDATOS_CSV)
    p.add_argument("--out", type=Path,
                   default=RAIZ / "data/reference/regidores_2026.csv")
    args = p.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: no existe {args.pdf}", file=sys.stderr)
        return 1

    distritos = pd.read_csv(args.distritos, dtype=str)
    tabla, av1 = parsea_tabla(texto_del_pdf(args.pdf))
    tabla, av2 = a_ubigeo(tabla, distritos)
    print(f"filas del artículo 1 parseadas: {len(tabla):,}")

    # Todos los concejos del país: 196 provinciales + 1,696 distritales.
    concejos = pd.concat([
        pd.DataFrame({"ubigeo": sorted(set(distritos.ubigeo_provincia)),
                      "nivel": "provincial"}),
        pd.DataFrame({"ubigeo": sorted(
            distritos[distritos.es_capital_provincia == "False"].ubigeo_distrito),
            "nivel": "distrital"}),
    ], ignore_index=True)

    # Artículo 1 donde diga algo; artículo 2 (5 regidores) en el resto.
    de_resolucion = dict(zip(tabla.ubigeo.dropna(),
                             tabla.loc[tabla.ubigeo.notna(), "n_regidores_resolucion"]))
    concejos["n_resolucion"] = [
        REGIDORES_LIMA if u == LIMA_METROPOLITANA
        else de_resolucion.get(u, REGIDORES_POR_DEFECTO)
        for u in concejos.ubigeo
    ]
    concejos["fuente"] = [
        "Res. 0847-2025-JNE art. 1" if u in de_resolucion or u == LIMA_METROPOLITANA
        else "Res. 0847-2025-JNE art. 2 (regla de cierre)"
        for u in concejos.ubigeo
    ]

    conteo = conteo_de_candidatos(lee_candidatos(args.candidatos))
    concejos["n_candidatos"] = [conteo.get(u) for u in concejos.ubigeo]

    total_res = int(concejos.n_resolucion.sum())
    total_cand = int(concejos.n_candidatos.fillna(0).sum())
    print(f"\nΣ regidores según la resolución : {total_res:,}")
    print(f"Σ regidores según candidatos    : {total_cand:,}")
    print(f"objetivo legal                  : 10,842")

    disc = concejos[concejos.n_resolucion != concejos.n_candidatos]
    print(f"\nconcejos comparados             : {len(concejos):,}")
    print(f"DISCREPANCIAS                   : {len(disc):,}")

    if len(disc):
        d = disc.merge(
            distritos[["ubigeo_distrito", "nombre_distrito", "nombre_provincia",
                       "nombre_departamento"]],
            left_on="ubigeo", right_on="ubigeo_distrito", how="left")
        print("\ncada una, sin promediar ni elegir en silencio:")
        for r in d.itertuples():
            nombre = (f"{r.nombre_departamento}/{r.nombre_provincia}/"
                      f"{r.nombre_distrito}" if isinstance(r.nombre_distrito, str)
                      else r.ubigeo)
            print(f"  {r.ubigeo}  {nombre[:52]:52s} resolución={r.n_resolucion:>3} "
                  f"candidatos={r.n_candidatos}")

    concejos.to_csv(args.out, index=False)
    print(f"\nescrito: {args.out}")

    for a in av1 + av2:
        print(f"AVISO: {a}")

    ok = total_res == 10842 and len(disc) == 0
    print("\nLas dos fuentes coinciden y suman 10,842." if ok
          else "\nRevisar: las fuentes no coinciden del todo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
