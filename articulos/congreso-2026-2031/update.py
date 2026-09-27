#!/usr/bin/env python3
"""Actualiza el tablero de votaciones del Congreso 2026-2031 de punta a punta.

    python3 update.py            # todo + commit/push si cambió algo
    python3 update.py --no-push  # todo, sin tocar git
    python3 update.py --sin-fotos --no-scrape   # rehacer sólo con lo que hay

Pasos (cada uno incremental, así que correrlo seguido es barato):
  1. scrape_sesiones  PDFs nuevos de la columna «Votaciones y Asistencias»
  2. roster           padrón oficial + fotos (sólo baja fotos que falten)
  3. parse_all        OCR de los PDF nuevos o re-publicados (caché por sha256)
  4. estimate         puntos ideales, línea oficialismo/oposición, métricas
  5. build_web        web/<camara>.json para el tablero
  6. git              commit «data: actualizar votaciones congreso — fecha» + push
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLICAR = ["web", "data/roster.json", "data/fotos", "data/votos.csv",
            "data/modelo_diputados.json", "data/modelo_senado.json"]


def paso(titulo: str) -> None:
    print(f"\n━━ {titulo} ━━", flush=True)


def publicar() -> None:
    git = ["git", "-C", str(HERE)]
    subprocess.run(git + ["add", "--"] + PUBLICAR, check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        print("  sin cambios que publicar")
        return
    msg = f"data: actualizar votaciones congreso — {datetime.now():%Y-%m-%d %H:%M}"
    subprocess.run(git + ["commit", "-m", msg, "--"] + PUBLICAR, check=True)
    subprocess.run(git + ["push"], check=True)
    print(f"  publicado: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-scrape", action="store_true")
    ap.add_argument("--sin-fotos", action="store_true")
    ap.add_argument("--force-parse", action="store_true", help="re-OCR de todos los PDF")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    if not a.no_scrape:
        paso("1 · sesiones y PDFs")
        subprocess.run([sys.executable, str(HERE / "scrape_sesiones.py")], check=True)
    paso("2 · padrón y fotos")
    import roster
    roster.run(fotos=not a.sin_fotos)
    paso("3 · OCR de votaciones")
    import parse_all
    parse_all.run(force=a.force_parse, jobs=a.jobs)
    paso("4 · puntos ideales")
    import estimate
    estimate.run()
    paso("5 · JSON del tablero")
    import build_web
    build_web.run()
    if not a.no_push:
        paso("6 · publicar")
        publicar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
