#!/usr/bin/env python3
"""Directorio nacional de autoridades electas.

Las ~13,000 autoridades de una noche completa —ejecutivos y cuerpos
proporcionales— en un solo archivo buscable por nombre. Es lo que convierte al
sitio en referencia después de la noche: la pregunta «quién es el regidor de mi
distrito» no tiene hoy ninguna página que la responda sin ir carrera por carrera.

Se llena solo con quien ya está electo. A las ocho de la noche está vacío y crece
con el escrutinio; eso no es un defecto, es el dato. Un escaño en `por_definir`
no tiene titular y aquí no se inventa uno.

FORMA COLUMNAR
--------------
Trece mil registros con nombres de cargo y de organización repetidos en cada uno
pesan varias veces lo que deberían. Las filas van como listas posicionales y los
valores que se repiten salen a tablas de índice, que es el mismo formato que ya
usa el buscador de candidatos del artículo ERM 2026.

Lo derivable no se guarda: la foto se construye desde `hdv` y el logo desde el
código de organización, igual que hace el resto del sitio.

Uso:
    uv run python scripts/06_publica_electos.py --anio 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

CAMPOS = ["nombre", "cargo", "org", "race", "hdv", "sexo", "edad", "orden"]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--anio", default="2026", choices=("2022", "2026"))
    ap.add_argument("--publico", type=Path, default=None)
    args = ap.parse_args()

    bloque = RAIZ
    publico = args.publico or bloque / "data"
    meta = json.loads((publico / "meta.json").read_text(encoding="utf-8"))
    lugar = {c["race_id"]: c["nombre"] for c in meta.get("carreras", [])}
    tipo_de = {c["race_id"]: c["tipo"] for c in meta.get("carreras", [])}

    cargos: list[str] = []
    idx_cargo: dict[str, int] = {}
    orgs: dict[str, str] = {}
    filas: list[list] = []

    def icargo(nombre: str) -> int:
        if nombre not in idx_cargo:
            idx_cargo[nombre] = len(cargos)
            cargos.append(nombre)
        return idx_cargo[nombre]

    def agrega(p: dict, cargo: str, codigo: str, nombre_org: str, rid: str) -> None:
        if codigo and nombre_org:
            orgs.setdefault(codigo, nombre_org)
        filas.append([
            p.get("nombre"), icargo(cargo), codigo, rid,
            p.get("hoja_vida_id"), p.get("sexo"), p.get("edad"), p.get("orden"),
        ])

    for doc_path in sorted((publico / "carrera").glob("*.json")):
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        rid = doc.get("race_id") or doc_path.stem
        electos = doc.get("electos") or {}

        ej = electos.get("ejecutivo") or {}
        # Solo se publica a quien está electo. `segunda_vuelta` nombra a dos
        # listas y ninguna ha ganado todavía: meterlas aquí sería decir que sí.
        if ej.get("estado") == "electo":
            cod = ej.get("organizacion")
            nom = ej.get("organizacion_nombre")
            for p in ej.get("titular") or []:
                agrega(p, ej.get("cargo") or "EJECUTIVO", cod, nom, rid)
            for p in ej.get("acompanante") or []:
                agrega(p, ej.get("cargo_acompanante") or "ACOMPAÑANTE", cod, nom, rid)

        cuerpo = electos.get("cuerpo") or {}
        cargo_c = cuerpo.get("cargo") or "MIEMBRO DEL CUERPO"
        for b in cuerpo.get("por_organizacion") or []:
            for p in b.get("candidatos") or []:
                agrega(p, cargo_c, b.get("codigo"), b.get("nombre"), rid)

    # Solo las carreras que aportan a alguien: mandar las 2,118 con su nombre
    # cuando hay 40 electas es peso muerto en la primera hora de la noche.
    usadas = {f[3] for f in filas}
    doc = {
        "generado": datetime.now(timezone.utc).astimezone().isoformat(),
        "total": len(filas),
        "campos": CAMPOS,
        "cargos": cargos,
        "organizaciones": orgs,
        "carreras": {r: [lugar.get(r, r), tipo_de.get(r, "")] for r in sorted(usadas)},
        "filas": filas,
    }
    destino = publico / "electos.json"
    destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    mb = destino.stat().st_size / 1_048_576
    print(f"{len(filas):,} autoridades electas · {len(usadas):,} carreras · "
          f"{mb:.2f} MB → {destino}")
    por_cargo: dict[str, int] = {}
    for f in filas:
        por_cargo[cargos[f[1]]] = por_cargo.get(cargos[f[1]], 0) + 1
    for k, v in sorted(por_cargo.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<28} {v:>6,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
