#!/usr/bin/env python3
"""Vigila y archiva las publicaciones de la ONPE sobre el sorteo de cédula.

El sorteo del **18 de agosto de 2026** es irrepetible y no se sabe de antemano en
qué formato publicará la ONPE los resultados. Por eso este script **no parsea**:
archiva el crudo tal cual y avisa cuándo algo cambió. El parseo se puede rehacer
después; la descarga no (regla 4 de CLAUDE.md).

Cómo detecta cambios: GET condicional con `ETag` / `Last-Modified`. Un 304 es una
petición ya resuelta y no se vuelve a descargar. Cuando el servidor responde 200,
el contenido cambió: se archiva con fecha y se reporta.

Correrlo varias veces al día alrededor del 18. Es barato: en régimen estable son
siete peticiones condicionales que devuelven 304.

Uso:
    uv run python scripts/watch_sorteo.py                  # una ronda
    uv run python scripts/watch_sorteo.py --verbose
    uv run python scripts/watch_sorteo.py --intervalo 900  # ronda cada 15 min
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

try:
    from curl_cffi import requests
except ImportError:  # pragma: no cover
    print("Falta curl_cffi. El WAF de CloudFront bloquea requests/urllib.",
          file=sys.stderr)
    print("  uv add curl_cffi", file=sys.stderr)
    raise SystemExit(1)

RAIZ = Path(__file__).resolve().parents[2]
CONTACTO_POR_DEFECTO = os.environ.get("DATAPOL_CONTACTO", "https://datapol.lat")

# Cortesía: una petición cada tantos segundos, y reintentos con backoff.
PAUSA_ENTRE_PETICIONES = 2.0
REINTENTOS = 4
BACKOFF_BASE = 3.0


def agente(contacto: str) -> str:
    return f"datapol.lat monitor ERM2026 (+{contacto})"


def lee_fuentes(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf8") as fh:
        return list(csv.DictReader(fh))


def carga_checkpoint(ruta: Path) -> dict:
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf8"))
    return {}


def guarda_checkpoint(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: un checkpoint a medias es peor que ninguno.
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf8")
    tmp.replace(ruta)


def pide(url: str, previo: dict, contacto: str, verbose: bool):
    """GET condicional con backoff. Devuelve la respuesta o None si falló."""
    cabeceras = {"User-Agent": agente(contacto)}
    if previo.get("etag"):
        cabeceras["If-None-Match"] = previo["etag"]
    if previo.get("last_modified"):
        cabeceras["If-Modified-Since"] = previo["last_modified"]

    for intento in range(REINTENTOS):
        try:
            r = requests.get(url, impersonate="chrome124", timeout=60,
                             headers=cabeceras)
            if r.status_code in (200, 304):
                return r
            if verbose:
                print(f"    HTTP {r.status_code}, reintento {intento + 1}")
        except Exception as e:  # noqa: BLE001 - la red falla de muchas formas
            if verbose:
                print(f"    error de red: {e}")
        if intento < REINTENTOS - 1:
            time.sleep(BACKOFF_BASE * (2 ** intento))
    return None


def extension(tipo: str, url: str) -> str:
    if tipo == "pdf" or url.lower().endswith(".pdf"):
        return ".pdf"
    return ".html"


def urls_nuevas(html: str, base: str) -> list[str]:
    """Enlaces a PDF que aparezcan en una página vigilada.

    Si la ONPE publica el acta del sorteo como un PDF nuevo, va a colgar de una
    de estas páginas antes de que nadie lo sepa. Se reportan para añadirlos a
    `sorteo_fuentes.csv`.
    """
    encontrados = re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, re.I)
    return sorted({urljoin(base, u) for u in encontrados})


def revisa(fuentes: list[dict], destino: Path, checkpoint_ruta: Path,
           contacto: str, verbose: bool) -> int:
    estado = carga_checkpoint(checkpoint_ruta)
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cambios = 0

    for i, f in enumerate(fuentes):
        clave, url = f["clave"], f["url"]
        previo = estado.get(clave, {})
        if verbose:
            print(f"[{i + 1}/{len(fuentes)}] {clave}")

        r = pide(url, previo, contacto, verbose)
        if r is None:
            print(f"  FALLO   {clave}: no se pudo consultar {url}")
            continue

        if r.status_code == 304:
            if verbose:
                print("    304 sin cambios")
            continue

        cuerpo = r.content
        sha = hashlib.sha256(cuerpo).hexdigest()
        if sha == previo.get("sha256"):
            # 200 pero idéntico: el servidor no soporta condicional. No re-archiva.
            estado[clave] = {**previo, "visto_ts": sello}
            if verbose:
                print("    200 pero contenido idéntico")
            continue

        carpeta = destino / hoy
        carpeta.mkdir(parents=True, exist_ok=True)
        archivo = carpeta / f"{clave}_{sello}{extension(f.get('tipo', ''), url)}"
        archivo.write_bytes(cuerpo)

        primera_vez = "sha256" not in previo
        etiqueta = "NUEVO  " if primera_vez else "CAMBIO "
        print(f"  {etiqueta} {clave}  ->  {archivo.relative_to(destino.parent.parent)}"
              f"  ({len(cuerpo):,} bytes)")
        if not primera_vez:
            cambios += 1
            print(f"           sha anterior {previo['sha256'][:12]} "
                  f"-> nuevo {sha[:12]}")
            print(f"           visto por última vez sin cambios: "
                  f"{previo.get('visto_ts', '?')}")

        if archivo.suffix == ".html":
            pdfs = urls_nuevas(cuerpo.decode("utf8", errors="replace"), url)
            conocidos = {x["url"] for x in fuentes}
            for p in pdfs:
                if p not in conocidos:
                    print(f"           PDF no vigilado: {p}")

        estado[clave] = {
            "url": url,
            "sha256": sha,
            "etag": r.headers.get("etag"),
            "last_modified": r.headers.get("last-modified"),
            "bytes": len(cuerpo),
            "archivo": str(archivo),
            "visto_ts": sello,
        }
        guarda_checkpoint(checkpoint_ruta, estado)

        if i < len(fuentes) - 1:
            time.sleep(PAUSA_ENTRE_PETICIONES)

    guarda_checkpoint(checkpoint_ruta, estado)
    return cambios


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--fuentes", type=Path,
                   default=RAIZ / "data/reference/sorteo_fuentes.csv")
    p.add_argument("--destino", type=Path, default=RAIZ / "data/raw/sorteo",
                   help="dónde archivar el crudo")
    p.add_argument("--checkpoint", type=Path,
                   default=RAIZ / "data/raw/sorteo/.checkpoint.json")
    p.add_argument("--contacto", default=CONTACTO_POR_DEFECTO,
                   help="correo del User-Agent")
    p.add_argument("--intervalo", type=int, default=0,
                   help="segundos entre rondas; 0 = una sola ronda")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not args.fuentes.exists():
        print(f"ERROR: no existe {args.fuentes}", file=sys.stderr)
        return 1
    fuentes = lee_fuentes(args.fuentes)
    print(f"vigilando {len(fuentes)} fuentes -> {args.destino}")

    while True:
        inicio = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        print(f"\n--- ronda {inicio} ---")
        cambios = revisa(fuentes, args.destino, args.checkpoint, args.contacto,
                         args.verbose)
        print(f"--- fin de ronda: {cambios} cambio(s) ---")
        if cambios:
            print("\n>>> REVISAR: algo cambió en la publicación de la ONPE.")
        if args.intervalo <= 0:
            return 0
        time.sleep(args.intervalo)


if __name__ == "__main__":
    raise SystemExit(main())
