#!/usr/bin/env python3
r"""Extrae las 66 propuestas del articulado del PL 98/2026-PE a data/propuestas.json.

Entrada: data/ocr/articulado.txt (OCR de las 20 páginas, ver ocr_facultades.py).
Salida:  data/propuestas.json — una entrada por numeral, con su materia, el texto
         literal reconstruido, el verbo rector y las normas que cita.

TRES COSAS QUE EL OCR OBLIGA A MANEJAR, y por qué el parser no puede ser ingenuo:

1. El grado del ordinal (`N.°`) sale de siete formas distintas — N.* N.” N.? N.º
   N* Nº N.°— según cómo cayó el escaneo. Si se busca la forma canónica se pierden
   la mayoría de las citas de normas, que son el insumo del análisis de qué se
   reescribiría. Por eso GRADO acepta cualquiera de ellas.

2. Los rótulos de materia no son uniformes: `a.` lleva punto, `f` lo perdió, `h. —`
   ganó una raya. Un `^[a-h]\.` recto se come dos de las ocho materias.

3. Los numerales vienen con separadores erráticos (`1.`, `2.  `, `1. —`). Y en un
   caso el OCR leyó un 6 como 5 (materia e, minería) — verificado contra el escaneo
   original: el documento dice 6. Como la secuencia de la fuente es correlativa en
   las ocho materias, se **renumera secuencialmente** y se guarda en `n_ocr` lo que
   el OCR había leído, para que cualquier discrepancia quede auditable en vez de
   silenciosa.

Run: python3 scripts/build_propuestas.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "data", "ocr", "articulado.txt")
OUT = os.path.join(ROOT, "data", "propuestas.json")

GRADO = r"(?:N\.?\s*[°º*”?¿'’\"]|Nº|N\.\s)"
NORMA_RE = re.compile(
    rf"(Decreto\s+Legislativo|Decreto\s+Ley|Decreto\s+Supremo|Ley)\s*{GRADO}\s*([0-9]{{3,5}})",
    re.IGNORECASE,
)
MATERIA_RE = re.compile(r"^\s*([a-h])\s*[\.\)]?\s*[—\-–]?\s+(En\s+materia|En\s+el\s+marco)\b")
NUMERAL_RE = re.compile(r"^\s*([0-9]{1,2})\s*[\.\)]\s*[—\-–]?\s*(\S.*)$")
PAG_RE = re.compile(r"^=== \[pág (\d+)\] ===$")

# Ruido de escaneo: el sello circular "REPÚBLICA DEL PERÚ" cae partido en líneas
# cortas sin sentido en la cabecera de varias páginas.
RUIDO_RE = re.compile(
    r"^\s*(?:[A-Za-z0-9ÁÉÍÓÚÑñ]{1,4}|.*?(?:UBLICA DEL|uICA DEL|AueA DEL|ALCA DE|BLICA DEL).*|"
    r"CÁMARA DE DIPUTADOS|ÁREA DE TRÁMITE.*|RECIBIDO|PROPOSICIÓN LEGISLATIVA|"
    r"FIRMADO DIGITALMENTE.*|RU \d+-CR|\d{5}-\d{4}-\d{4}-CD)\s*$"
)


def normaliza(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(rf"{GRADO}\s*", "N.° ", s)
    return re.sub(r"\s+([,.;:])", r"\1", s)


def normas_citadas(texto: str) -> list[dict]:
    vistas, out = set(), []
    for tipo, num in NORMA_RE.findall(texto):
        t = re.sub(r"\s+", " ", tipo).title()
        t = {"Ley": "Ley", "Decreto Legislativo": "Decreto Legislativo",
             "Decreto Ley": "Decreto Ley", "Decreto Supremo": "Decreto Supremo"}.get(t, t)
        clave = (t, num)
        if clave not in vistas:
            vistas.add(clave)
            out.append({"tipo": t, "numero": num})
    return out


def verbo_rector(texto: str) -> str:
    m = re.match(r"([A-ZÁÉÍÓÚ][a-záéíóúñ]+)", texto.strip())
    return m.group(1) if m else ""


def parse():
    lineas = open(SRC, encoding="utf-8").read().split("\n")

    # El articulado empieza en "Artículo 2"; antes va el oficio y el objeto. Y hay
    # que cortar en las disposiciones finales: sin ese corte, el último numeral (h7)
    # se traga artículo 3, firmas y anexo — 318 palabras donde el pedido tiene 90.
    inicio = next(i for i, l in enumerate(lineas) if "Materias de la delegación" in l)
    fin = next((i for i, l in enumerate(lineas)
                if i > inicio and "DISPOSICIONES COMPLEMENTARIAS" in l), len(lineas))

    materias: dict[str, dict] = {}
    orden: list[str] = []
    mat_actual = None
    buf: list[str] = []
    props: list[dict] = []
    pag = 0
    por_materia_abierta: dict[str, bool] = {}   # materia vista, primer numeral aún no

    def cierra():
        """Vuelca el buffer al último numeral abierto (las líneas de continuación)."""
        if props and buf:
            props[-1]["_lineas"].extend(buf)
        buf.clear()

    for raw in lineas[inicio:fin]:
        mp = PAG_RE.match(raw)
        if mp:
            pag = int(mp.group(1))
            continue
        if RUIDO_RE.match(raw) or not raw.strip():
            continue

        mm = MATERIA_RE.match(raw)
        if mm:
            cierra()
            mat_actual = mm.group(1).lower()
            materias[mat_actual] = {"letra": mat_actual, "_lineas": [raw.strip()], "pag": pag}
            por_materia_abierta[mat_actual] = True
            orden.append(mat_actual)
            continue

        mn = NUMERAL_RE.match(raw)
        if mn and mat_actual:
            cierra()
            por_materia_abierta[mat_actual] = False
            props.append({
                "materia": mat_actual,
                "n_ocr": int(mn.group(1)),
                "pag": pag,
                "_lineas": [mn.group(2)],
            })
            continue

        # Mientras no haya aparecido el primer numeral de la materia, las líneas
        # sueltas son la continuación de su título (los rótulos ocupan 2–3 líneas).
        if mat_actual and por_materia_abierta[mat_actual]:
            materias[mat_actual]["_lineas"].append(raw.strip())
        elif props and mat_actual:
            buf.append(raw.strip())
    cierra()

    # Renumeración secuencial por materia + ensamblado del texto.
    por_mat = Counter()
    salida = []
    for p in props:
        por_mat[p["materia"]] += 1
        n = por_mat[p["materia"]]
        texto = normaliza(" ".join(p["_lineas"]))
        salida.append({
            "id": f'{p["materia"]}{n}',
            "materia": p["materia"],
            "n": n,
            "n_ocr": p["n_ocr"],
            "ocr_discrepa": n != p["n_ocr"],
            "pagina": p["pag"],
            "verbo_rector": verbo_rector(texto),
            "texto": texto,
            "n_palabras": len(texto.split()),
            "normas_citadas": normas_citadas(texto),
        })

    mats = []
    for letra in orden:
        titulo = normaliza(" ".join(materias[letra]["_lineas"]))
        titulo = re.sub(rf"^{letra}\s*[\.\)]?\s*[—\-–]?\s*", "", titulo).rstrip(":")
        mats.append({"letra": letra, "titulo": titulo,
                     "n_propuestas": por_mat[letra], "pagina": materias[letra]["pag"]})
    return mats, salida


def main():
    mats, props = parse()
    doc = {
        "proyecto": "00098-2026-2031-CD",
        "titulo": ("Ley que delega en el Poder Ejecutivo la facultad de legislar en materia de "
                   "seguridad ciudadana; fortalecimiento de micro y pequeñas empresas; promoción "
                   "del empleo; desarrollo productivo; régimen tributario; simplificación "
                   "administrativa y otras materias"),
        "oficio": "245-2026-PR",
        "fecha_presentacion": "2026-08-28",
        "plazo_dias": 120,
        "fuente": "Cámara de Diputados, expediente 98/2026 (archivo 413527)",
        "materias": mats,
        "propuestas": props,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"materias: {len(mats)}  propuestas: {len(props)}  → {OUT}")
    for m in mats:
        print(f"  {m['letra']}. {m['n_propuestas']:>2}  {m['titulo'][:78]}")
    disc = [p["id"] for p in props if p["ocr_discrepa"]]
    print(f"\nrenumerados (OCR discrepaba): {disc or 'ninguno'}")
    normas = Counter((n["tipo"], n["numero"]) for p in props for n in p["normas_citadas"])
    print(f"citas de normas: {sum(normas.values())} ({len(normas)} normas distintas)")
    sin = [p["id"] for p in props if not p["normas_citadas"]]
    print(f"propuestas sin norma citada: {len(sin)}/{len(props)}")


if __name__ == "__main__":
    main()
