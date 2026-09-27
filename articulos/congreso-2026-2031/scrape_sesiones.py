#!/usr/bin/env python3
"""Descarga los PDF de «Votaciones y Asistencias» del Pleno, Congreso 2026-2031.

Desde julio de 2026 el Congreso es bicameral y cada cámara publica sus sesiones
en su propio sitio, con la misma tabla (tema WordPress compartido):

    https://diputados.congreso.gob.pe/sesiones-del-pleno/
    https://senado.congreso.gob.pe/sesiones_del_pleno/

    Fecha | Agenda | Acta | Diario de los Debates | Temas tratados |
    Votaciones y Asistencias | Video

Una fila por sesión (a veces dos con la misma fecha: matutina/vespertina).
**Se lee la columna por su encabezado, no el nombre del archivo**: los nombres
cambian sin aviso (ASISTENCIA-VOTACION-…, ASISTENCIA-PLENO-…, …finales.pdf,
Votaciones_y_Asistencias_…) y un archivo llamado sólo «ASISTENCIA» puede traer
las votaciones. Si la celda trae sólo asistencia (p. ej. las sesiones del Senado
del 12 y 18/08/2026), eso lo resuelve el parser, no este paso.

Todos los años legislativos vienen en el HTML estático: cada <tr> lleva
`data-periodo="2026-2027"` y las pestañas de año sólo filtran del lado del
cliente. `--periodo` filtra igual.

Salida: data/pdfs/<camara>/<archivo>.pdf + data/pdfs/manifest.csv
(camara, periodo, fecha, orden, url, archivo, bytes, sha256). Idempotente:
los archivos ya presentes no se vuelven a bajar, sólo se re-hashean.

Run: python3 scrape_sesiones.py [--camara diputados|senado] [--periodo 2026-2027] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html as html_lib
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import certifi   # python.org en macOS no trae CAs enlazadas
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "data" / "pdfs"
MANIFEST = PDF_DIR / "manifest.csv"

CAMARAS = {
    "diputados": "https://diputados.congreso.gob.pe/sesiones-del-pleno/",
    "senado": "https://senado.congreso.gob.pe/sesiones_del_pleno/",
}
COLUMNA = "Votaciones y Asistencias"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
              "datapol-scraper/1.0 (contacto: datapol.lat)")


def fetch(url: str) -> bytes:
    p = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit((p.scheme, p.netloc,
                                   urllib.parse.quote(p.path, safe="/%"),
                                   p.query, p.fragment))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=60) as r:
        return r.read()


def texto(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def sesiones(camara: str) -> list[dict]:
    """Filas de la tabla de sesiones: {periodo, fecha (ISO), orden, urls}."""
    page = fetch(CAMARAS[camara]).decode("utf-8", "replace")
    ths = [texto(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", page, re.S)]
    if COLUMNA not in ths:
        sys.exit(f"[{camara}] no encuentro la columna «{COLUMNA}» (encabezados: {ths}); "
                 "la página cambió.")
    col = ths.index(COLUMNA)

    out, vistos = [], {}
    for attrs, cuerpo in re.findall(r"<tr([^>]*)>(.*?)</tr>", page, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", cuerpo, re.S)
        if len(tds) <= col:
            continue
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto(tds[0]))
        if not m:
            print(f"  ⚠ [{camara}] fila sin fecha legible: {texto(tds[0])[:60]!r}")
            continue
        fecha = f"{m[3]}-{m[2]}-{m[1]}"
        per = re.search(r'data-periodo="([^"]+)"', attrs)
        # Dos sesiones el mismo día (matutina/vespertina) → orden 1, 2… en el
        # orden en que la página las lista.
        vistos[fecha] = vistos.get(fecha, 0) + 1
        out.append({
            "camara": camara,
            "periodo": per[1] if per else "",
            "fecha": fecha,
            "orden": vistos[fecha],
            "urls": [html_lib.unescape(u) for u in
                     re.findall(r'href="([^"]+\.pdf)"', tds[col], re.I)],
        })
    if not out:
        sys.exit(f"[{camara}] 0 sesiones: la página cambió o vino vacía.")
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--camara", choices=sorted(CAMARAS), help="default: ambas")
    ap.add_argument("--periodo", help="p. ej. 2026-2027 (default: todos)")
    ap.add_argument("--dry-run", action="store_true", help="listar sin descargar")
    args = ap.parse_args()

    filas = []
    for camara in ([args.camara] if args.camara else sorted(CAMARAS)):
        ss = [s for s in sesiones(camara)
              if not args.periodo or s["periodo"] == args.periodo]
        print(f"\n[{camara}] {len(ss)} sesiones")
        for s in sorted(ss, key=lambda s: (s["fecha"], s["orden"])):
            tag = f"{s['fecha']}#{s['orden']}"
            if not s["urls"]:
                print(f"  {tag}  — sin PDF de votaciones")
                continue
            for url in s["urls"]:
                nombre = urllib.parse.unquote(url.rsplit("/", 1)[-1])
                dest = PDF_DIR / camara / nombre
                if args.dry_run:
                    print(f"  {tag}  {nombre}")
                    continue
                if dest.exists():
                    print(f"  {tag}  {nombre}  (ya está)")
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    data = fetch(url)
                    if not data.startswith(b"%PDF"):
                        print(f"  ⚠ {tag}  {nombre}: la respuesta no es un PDF; se omite")
                        continue
                    dest.write_bytes(data)
                    print(f"  {tag}  {nombre}  ↓ {len(data)/1e6:.1f} MB")
                    time.sleep(1)   # cortesía
                filas.append({"camara": camara, "periodo": s["periodo"],
                              "fecha": s["fecha"], "orden": s["orden"], "url": url,
                              "archivo": str(dest.relative_to(PDF_DIR)),
                              "bytes": dest.stat().st_size, "sha256": sha256(dest)})

    if args.dry_run:
        print("\ndry run — no se descargó nada")
        return
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else ["camara"])
        w.writeheader()
        w.writerows(filas)
    print(f"\nwrote {MANIFEST.relative_to(HERE)} ({len(filas)} archivos)")


if __name__ == "__main__":
    main()
