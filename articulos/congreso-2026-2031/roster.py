#!/usr/bin/env python3
"""Padrón oficial de ambas cámaras, con foto, desde la API de WordPress de cada sitio.

    https://diputados.congreso.gob.pe/wp-json/wp/v2/diputado   (130)
    https://senado.congreso.gob.pe/wp-json/wp/v2/senador        (60)

Cada registro trae el nombre como «Apellidos, Nombres» (`title.rendered`), el
perfil (`link`), la foto oficial (featured media) y, dentro de `class_list`,
las taxonomías: `grupo_parlamentario-*`, `partido_politico-*`,
`distrito_electoral-*`, `genero-*`, `condicion-*`.

Es la **fuente de verdad del padrón**: el parser OCR ajusta cada nombre leído
del PDF contra esta lista (en vez de inventar el padrón por consenso entre
páginas, como en 2021), así que partido y foto vienen resueltos por la API.

Ojo: el grupo parlamentario de la API es el *actual*. Para el voto histórico
vale el código de bancada impreso en cada PDF (lo guarda el parser); si alguien
cambia de bancada, se verá como diferencia entre ambos.

Salida: data/roster.json  +  data/fotos/<camara>/<slug>.jpg (miniatura 240px).
Run: python3 roster.py [--sin-fotos]
"""
from __future__ import annotations

import argparse
import html as html_lib
import io
import json
import re
import unicodedata
from pathlib import Path

from scrape_sesiones import fetch

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "roster.json"
FOTOS = HERE / "data" / "fotos"
FOTO_PX = 240

API = {
    "diputados": ("https://diputados.congreso.gob.pe", "diputado", 130),
    "senado": ("https://senado.congreso.gob.pe", "senador", 60),
}

# slug de la taxonomía → código de bancada impreso en los PDF de votación.
# El Senado imprime a veces OBRAS en vez de PCO; el parser lo normaliza.
GRUPOS = {
    "fuerza-popular": ("FP", "Fuerza Popular"),
    "juntos-por-el-peru": ("JP", "Juntos por el Perú"),
    "partido-del-buen-gobierno": ("PBG", "Partido del Buen Gobierno"),
    "renovacion-popular": ("RP", "Renovación Popular"),
    "partido-civico-obras": ("PCO", "Partido Cívico Obras"),
    "ahora-nacion": ("AN", "Ahora Nación"),
}


def norm(s: str) -> str:
    """Clave de comparación: mayúsculas, sin tildes, sin puntuación."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z ]+", " ", s.upper()).split())


def taxo(classes: list[str], prefijo: str) -> str | None:
    for c in classes:
        if c.startswith(prefijo + "-"):
            return c[len(prefijo) + 1:]
    return None


def miembros(camara: str) -> list[dict]:
    base, tipo, esperado = API[camara]
    out, page = [], 1
    while True:
        url = (f"{base}/wp-json/wp/v2/{tipo}?per_page=100&page={page}"
               "&_embed=wp:featuredmedia")
        lote = json.loads(fetch(url))
        if not lote:
            break
        out += lote
        if len(lote) < 100:
            break
        page += 1

    filas = []
    for x in out:
        cl = x.get("class_list") or []
        titulo = html_lib.unescape(x["title"]["rendered"]).strip()
        apellidos, _, nombres = titulo.partition(",")
        g = taxo(cl, "grupo_parlamentario")
        cod, gnombre = GRUPOS.get(g, (None, g))
        if g and g not in GRUPOS:
            print(f"  ⚠ [{camara}] grupo sin código: {g!r} ({titulo}) — agregarlo a GRUPOS")
        media = (x.get("_embedded", {}).get("wp:featuredmedia") or [{}])[0]
        filas.append({
            "id": f"{camara[0]}{x['id']}",
            "camara": camara,
            "slug": x["slug"],
            "nombre": titulo,
            "apellidos": apellidos.strip(),
            "nombres": nombres.strip(),
            "clave": norm(f"{apellidos} {nombres}"),
            "grupo": cod,
            "grupo_nombre": gnombre,
            "partido": taxo(cl, "partido_politico"),
            "distrito": taxo(cl, "distrito_electoral"),
            "genero": taxo(cl, "genero"),
            "condicion": taxo(cl, "condicion"),
            "perfil": x.get("link"),
            "foto_url": media.get("source_url"),
        })
    n_ej = sum(f["condicion"] == "en-ejercicio" for f in filas)
    print(f"[{camara}] {len(filas)} miembros ({n_ej} en ejercicio; esperado {esperado})")
    if len(filas) < esperado:
        print(f"  ⚠ [{camara}] faltan miembros en la API")
    return filas


def bajar_foto(m: dict) -> str | None:
    """Miniatura JPEG local; se reutiliza si ya existe."""
    if not m["foto_url"]:
        return None
    dest = FOTOS / m["camara"] / f"{m['slug']}.jpg"
    rel = str(dest.relative_to(HERE / "data"))
    if dest.exists():
        return rel
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(fetch(m["foto_url"])))
    except Exception as e:
        print(f"  ⚠ foto de {m['nombre']}: {e}")
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im, mask=im.split()[-1])
        im = fondo
    im.thumbnail((FOTO_PX, FOTO_PX * 2))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(dest, "JPEG", quality=82, optimize=True)
    return rel


def run(fotos: bool = True) -> list[dict]:
    todos = []
    for camara in API:
        ms = miembros(camara)
        if fotos:
            for m in ms:
                m["foto"] = bajar_foto(m)
            print(f"  fotos: {sum(bool(m['foto']) for m in ms)}/{len(ms)}")
        todos += ms
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE)}")
    return todos


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sin-fotos", action="store_true")
    run(fotos=not ap.parse_args().sin_fotos)
