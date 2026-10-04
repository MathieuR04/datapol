#!/usr/bin/env python3
"""Tablero de los alcaldes que vuelven como teniente alcalde.

Los casos salen del artículo `tenientes-alcalde-erm-2026`: 135 alcaldes electos
en 2022 que postulan a la posición 1 de la lista de regidores —que por ley es el
teniente alcalde— de **su propia** circunscripción. Aquí se publican solo los
**inscritos**, que son los que de verdad van a estar en la cédula, y se les pega
encima el resultado de su carrera.

La tabla de casos es estática y vive en `data/reference/tenientes.csv`, con el
`race_id` que este script necesita para el cruce. Lo que cambia cada ciclo es la
columna de la derecha: si ganó, si perdió, o con qué probabilidad va.

QUÉ SE PUBLICA POR CASO
-----------------------
  electo_alcalde   su lista ganó la alcaldía y él la encabezaba (vía directa):
                   es alcalde, que es exactamente lo que la ley le prohibía.
  electo_teniente  su lista ganó la alcaldía y él entra al concejo: teniente
                   alcalde de verdad, que es la vía indirecta funcionando.
  electo_regidor   entró al concejo pero su lista no ganó la alcaldía. Vuelve al
                   municipio, pero a la oposición.
  fuera            la carrera ya tiene resultado y él no está entre los electos.
  en_disputa       todavía no hay llamada. Va con `p_gana`, la probabilidad de
                   que su lista gane la alcaldía.

CÓMO SE CRUZA
-------------
El caso trae el nombre de su organización de 2026; el documento de la carrera
trae las organizaciones que compiten en ella. Se cruza por nombre plegado dentro
de **una sola carrera**, donde no puede haber dos listas de la misma
organización, así que no hay ambigüedad que resolver. Un caso que no cruza se
marca `sin_cruce` y se reporta: no se rellena con una suposición.

Uso:
    uv run python scripts/01b_publica_tenientes.py --anio 2026
    uv run python scripts/01b_publica_tenientes.py --anio 2022 \
        --ref data/reference/tenientes_2022.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def plano(s: str | None) -> str:
    """Pliega a ASCII en mayúsculas. El JNE escribe la misma organización de dos
    maneras según la fuente, y aquí las dos tienen que colisionar."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().replace("-", " ").split())


def _dni(s: str | None) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit()).zfill(8)


def resultado(caso: dict, doc: dict) -> dict:
    """Dónde terminó este caso, según el documento de su carrera."""
    dni = _dni(caso["dni"])
    orgs = doc.get("organizaciones") or []
    electos = doc.get("electos") or {}
    ejec = electos.get("ejecutivo") or {}
    cuerpo = electos.get("cuerpo") or {}

    # Su lista dentro de esta carrera.
    objetivo = plano(caso["organizacion_2026"])
    mia = next((o for o in orgs if plano(o.get("nombre")) == objetivo), None)

    salida = {
        "estado_carrera": (doc.get("pronostico") or {}).get("estado"),
        "pct_actas": (doc.get("computo") or {}).get("pct_actas"),
        "organizacion_codigo": (mia or {}).get("codigo"),
        "votos": (mia or {}).get("votos"),
        "pct_validos": (mia or {}).get("pct_validos"),
        "p_gana": (mia or {}).get("p_gana"),
        "escanos_lista": None,
        "resultado": "sin_cruce" if mia is None else "en_disputa",
    }
    if mia is None:
        return salida

    # ¿Ganó su lista la alcaldía? El ejecutivo se nombra por código de
    # organización, que es la llave del contrato.
    gano_lista = (
        ejec.get("estado") == "electo"
        and ejec.get("organizacion") == mia.get("codigo")
    )

    # ¿Está él entre los electos? Por DNI, que no depende de cómo se escriba el
    # nombre en cada fuente.
    en_ejecutivo = any(
        _dni(p.get("dni")) == dni for p in (ejec.get("titular") or [])
    )
    bloque = next(
        (b for b in (cuerpo.get("por_organizacion") or [])
         if b.get("codigo") == mia.get("codigo")),
        None,
    )
    salida["escanos_lista"] = (bloque or {}).get("escanos")
    en_concejo = any(
        _dni(p.get("dni")) == dni for p in ((bloque or {}).get("candidatos") or [])
    )

    if en_ejecutivo:
        salida["resultado"] = "electo_alcalde"
    elif en_concejo:
        salida["resultado"] = "electo_teniente" if gano_lista else "electo_regidor"
    elif salida["estado_carrera"] in ("electo", "empate", "sin_resultado"):
        # La carrera está resuelta y él no aparece en ningún sitio: perdió.
        salida["resultado"] = "fuera"
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--anio", default="2026", choices=("2022", "2026"))
    ap.add_argument("--ref", type=Path, default=None,
                    help="tabla de casos (por defecto, data/reference/tenientes.csv del bloque)")
    ap.add_argument("--publico", type=Path, default=None,
                    help="directorio publicado (por defecto, data/publico del bloque)")
    ap.add_argument("--todos", action="store_true",
                    help="incluye también las candidaturas aún no inscritas")
    args = ap.parse_args()

    bloque = RAIZ
    ref = args.ref or bloque / "data/reference/tenientes.csv"
    publico = args.publico or bloque / "data"

    if not ref.exists():
        print(f"no existe la tabla de casos: {ref}", file=sys.stderr)
        return 1

    with open(ref, newline="", encoding="utf-8") as f:
        casos = list(csv.DictReader(f))
    total = len(casos)
    if not args.todos:
        # Solo los que ya están en la cédula. Una candidatura en trámite todavía
        # puede caerse, y un tablero de resultados no puede seguir a alguien que
        # quizá no compita.
        casos = [c for c in casos if c["estado_candidato"] == "INSCRITO"]

    salida, sin_cruce, faltan = [], 0, 0
    for c in casos:
        doc_path = publico / "carrera" / f"{c['race_id']}.json"
        if not doc_path.exists():
            faltan += 1
            continue
        with open(doc_path, encoding="utf-8") as f:
            doc = json.load(f)
        vivo = resultado(c, doc)
        if vivo["resultado"] == "sin_cruce":
            sin_cruce += 1
        salida.append({
            "race_id": c["race_id"],
            "nivel": c["nivel"],
            "region": c["region"],
            "provincia": c["provincia"],
            "distrito": c["distrito"],
            "nombre": c["nombre"],
            "dni": c["dni"],
            "hoja_vida_id": c["hoja_vida_id"],
            "cargo_actual": c["cargo_actual"],
            "organizacion_2026": c["organizacion_2026"],
            "organizacion_2022": c["organizacion_2022"],
            "cambio_de_organizacion": c["cambio_de_organizacion"] == "True",
            "alcalde_de_la_lista": c["alcalde_de_la_lista"],
            "estado_alcalde": c["estado_alcalde"],
            "via": c["via"],
            **vivo,
        })

    def cuenta(campo, valores=None):
        d = {}
        for s in salida:
            d[s[campo]] = d.get(s[campo], 0) + 1
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))

    doc = {
        "generado": datetime.now(timezone.utc).astimezone().isoformat(),
        "casos_en_registro": total,
        "inscritos": len(salida),
        "por_via": cuenta("via"),
        "por_nivel": cuenta("nivel"),
        "marcador": cuenta("resultado"),
        "casos": sorted(salida, key=lambda c: (c["region"], c["provincia"],
                                               c["distrito"], c["nombre"])),
    }
    destino = publico / "tenientes.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    print(f"{len(salida)} de {total} casos inscritos · {destino}")
    for k, v in doc["marcador"].items():
        print(f"  {k:<16} {v:>4}")
    if faltan:
        print(f"  sin documento de carrera: {faltan}", file=sys.stderr)
    if sin_cruce:
        print(f"  sin cruce de organización: {sin_cruce}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
