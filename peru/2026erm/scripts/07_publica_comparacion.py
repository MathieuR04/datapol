#!/usr/bin/env python3
"""Compara el desempeño de 2026 contra el de 2022.

Tres bloques, que son las tres preguntas que se hacen esa noche:

  · **Movimientos regionales** en conjunto. Son el actor que el marcador
    nacional esconde: en 2022 fueron 116 organizaciones y en 2026 son 22, y lo
    que importa no es cuál de ellas ganó sino cuánto pesa el bloque frente a los
    partidos nacionales.
  · **Alianza para el Progreso**, el partido con más listas del país.
  · **Somos Perú**.

EL DENOMINADOR IMPORTA
----------------------
Ganar 100 alcaldías de 2,000 listas no es lo mismo que ganar 100 de 300, así que
cada bloque lleva **las listas presentadas** junto a las carreras ganadas. Es
además lo único que tiene algo que decir a las ocho de la noche, cuando no hay un
solo voto contado: las listas se conocen desde antes y la comparación ya se
puede leer.

QUÉ ES UN BLOQUE EN CADA PROCESO
--------------------------------
El contrato de 2026 declara grupos —`REGIONALES` para los movimientos, y un
grupo por alianza electoral— y el de 2022 no los trae, así que ahí lo regional
se resuelve con el indicador de `colores.json`. No se deduce del tipo de
organización: deducirlo metía las alianzas en el saco de los regionales.

Donde un partido encabeza una alianza en 2026 y corrió solo en 2022, la
comparación es del grupo entero contra el partido, y el documento publica la
composición para que eso se pueda leer y no se confunda con crecimiento propio.

Uso:
    uv run python scripts/07_publica_comparacion.py
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

CAMPOS = ["listas", "gobernador_1v", "gobernador_2v", "alcalde_prov",
          "alcalde_dist", "consejero", "regidor_prov", "regidor_dist"]


def plano(s: str | None) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().replace("-", " ").split())


def suma(orgs: list[dict]) -> dict:
    return {k: sum(int(o.get(k) or 0) for o in orgs) for k in CAMPOS}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--antes", type=Path,
                    default=RAIZ.parent / "2022erm/data/nacional.json")
    ap.add_argument("--ahora", type=Path,
                    default=RAIZ / "data/nacional.json")
    ap.add_argument("--colores-antes", type=Path,
                    default=RAIZ.parent / "2022erm/data/colores.json")
    ap.add_argument("--out", type=Path,
                    default=RAIZ / "data/comparacion.json")
    args = ap.parse_args()

    for ruta in (args.antes, args.ahora):
        if not ruta.exists():
            print(f"falta {ruta}", file=sys.stderr)
            return 1

    antes = json.loads(args.antes.read_text(encoding="utf-8"))["por_organizacion"]
    ahora = json.loads(args.ahora.read_text(encoding="utf-8"))["por_organizacion"]

    # 2022 no declara grupos: lo nacional sale del tercer valor de `colores.json`,
    # que es el mismo indicador que usa el mapa del resumen.
    col = json.loads(args.colores_antes.read_text(encoding="utf-8"))
    def es_nacional_2022(cod: str) -> bool:
        v = col.get(cod) or []
        return bool(len(v) > 2 and v[2])

    def por_nombre(orgs: list[dict], patron: str) -> list[dict]:
        p = plano(patron)
        return [o for o in orgs if plano(o.get("nombre")) == p]

    def grupo_de(orgs: list[dict], semilla: dict | None) -> list[dict]:
        """El grupo al que pertenece una organización, o ella sola si no tiene."""
        if not semilla:
            return []
        g = semilla.get("grupo")
        if not g:
            return [semilla]
        return [o for o in orgs if o.get("grupo") == g]

    bloques = []

    # --- movimientos regionales, en bloque
    reg_antes = [o for o in antes if not es_nacional_2022(o["codigo"])]
    reg_ahora = [o for o in ahora if o.get("grupo") == "REGIONALES"]
    bloques.append({
        "clave": "regionales",
        "nombre": "Movimientos regionales",
        "nota": "Todos los movimientos regionales sumados, frente a los partidos "
                "nacionales. No es una organización: es el bloque.",
        "antes": {"n": len(reg_antes), "miembros": [], **suma(reg_antes)},
        "ahora": {"n": len(reg_ahora), "miembros": [], **suma(reg_ahora)},
    })

    # --- los dos partidos pedidos
    for clave, patron in (("app", "ALIANZA PARA EL PROGRESO"),
                          ("somos", "PARTIDO DEMOCRATICO SOMOS PERU")):
        a = por_nombre(antes, patron)
        # En 2026 el mismo nombre puede aparecer dos veces —el partido nacional y
        # una alianza departamental homónima—, así que se toma el de más listas
        # como semilla y se comparan sus grupos enteros.
        cand = por_nombre(ahora, patron)
        semilla = max(cand, key=lambda o: int(o.get("listas") or 0)) if cand else None
        b = grupo_de(ahora, semilla)
        if not a or not b:
            print(f"aviso: «{patron}» no aparece en los dos procesos, se omite",
                  file=sys.stderr)
            continue
        bloques.append({
            "clave": clave,
            "nombre": a[0]["nombre"],
            "logo": (b[0] if b else a[0]).get("logo"),
            "nota": ("En 2026 encabeza una alianza; se compara el grupo entero "
                     "contra el partido de 2022.") if len(b) > 1 else "",
            "antes": {"n": len(a),
                      "miembros": [o["nombre"] for o in a], **suma(a)},
            "ahora": {"n": len(b),
                      "miembros": [o["nombre"] for o in b], **suma(b)},
        })

    doc = {
        "generado": datetime.now(timezone.utc).astimezone().isoformat(),
        "campos": CAMPOS,
        "etiqueta_antes": "ERM 2022",
        "etiqueta_ahora": "ERM 2026",
        "bloques": bloques,
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    print(f"{len(bloques)} bloques → {args.out}")
    for b in bloques:
        print(f"  {b['nombre'][:34]:<36} "
              f"listas {b['antes']['listas']:>5} → {b['ahora']['listas']:<5}  "
              f"alc.dist {b['antes']['alcalde_dist']:>4} → {b['ahora']['alcalde_dist']:<4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
