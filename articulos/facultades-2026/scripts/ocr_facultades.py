#!/usr/bin/env python3
"""OCR de los dos documentos del pedido de facultades legislativas (PL 98/2026-PE).

Los dos PDFs son escaneos sin capa de texto. El problema no es la nitidez —el
escaneo es de imprenta digital, muy limpio— sino los **sellos de visado** que
las direcciones generales estampan en el margen izquierdo de cada página de la
exposición de motivos (C. BORDA G., E. VEGA R., J. RUIZ A., E. REBAZA I.).
Tesseract los lee como texto y los intercala en el cuerpo, rompiendo párrafos y
numeración. Por eso se recorta el margen antes de OCR: no es cosmética, es lo
que hace que la numeración de los 66 numerales sobreviva.

Resumible: salta las páginas cuyo .txt ya existe, así que se puede matar y
relanzar sin perder trabajo. Borra el PNG apenas termina la página (436 páginas
a 300 dpi son ~2 GB si se acumulan).

Uso: python3 ocr_facultades.py <pdf> <outdir> [--crop-left 0.14] [--workers 6]
"""
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image

DPI = 300


def n_pages(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise RuntimeError("no pude leer el número de páginas")


def do_page(args):
    pdf, outdir, pg, crop_left, crop_right = args
    txt = os.path.join(outdir, f"p{pg:04d}.txt")
    if os.path.exists(txt):
        return pg, "skip"
    stem = os.path.join(outdir, f"_pg{pg:04d}")
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-gray",
                    "-f", str(pg), "-l", str(pg), pdf, stem],
                   check=True, capture_output=True)
    # pdftoppm sufija el número de página con ancho variable
    png = next((os.path.join(outdir, f) for f in os.listdir(outdir)
                if f.startswith(f"_pg{pg:04d}-") and f.endswith(".png")), None)
    if png is None:
        return pg, "sin-png"
    try:
        im = Image.open(png)
        w, h = im.size
        im.crop((int(w * crop_left), 0, int(w * (1 - crop_right)), h)).save(png)
        subprocess.run(["tesseract", png, txt[:-4], "-l", "spa", "--psm", "6"],
                       check=True, capture_output=True)
    finally:
        if os.path.exists(png):
            os.remove(png)
    return pg, "ok"


def main():
    pdf, outdir = sys.argv[1], sys.argv[2]
    crop_left = float(sys.argv[sys.argv.index("--crop-left") + 1]) if "--crop-left" in sys.argv else 0.14
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    os.makedirs(outdir, exist_ok=True)
    total = n_pages(pdf)
    jobs = [(pdf, outdir, pg, crop_left, 0.02) for pg in range(1, total + 1)]
    print(f"{pdf}: {total} páginas · crop_left={crop_left} · workers={workers}", flush=True)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(do_page, j) for j in jobs]):
            pg, st = fut.result()
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  {done}/{total}", flush=True)
    # concatena en orden
    out = os.path.join(outdir, "_full.txt")
    with open(out, "w", encoding="utf-8") as f:
        for pg in range(1, total + 1):
            p = os.path.join(outdir, f"p{pg:04d}.txt")
            if os.path.exists(p):
                f.write(f"\n\n=== [pág {pg}] ===\n")
                f.write(open(p, encoding="utf-8").read())
    print("→", out, os.path.getsize(out), "bytes", flush=True)


if __name__ == "__main__":
    main()
