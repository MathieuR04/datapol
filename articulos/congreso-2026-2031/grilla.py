"""Cuadrícula de votación del Senado en las sesiones del Pleno del Congreso.

En las sesiones conjuntas (www.congreso.gob.pe/sesiones-del-pleno/) cada
votación trae dos páginas: la de Diputados en su formato de siempre y la del
Senado como cuadrícula «REGISTRO NOMINAL»: 60 filas en dos mitades
(N.° | grupo | senador | SI | NO | ABST.), una ✓ en la columna del voto y
estados escritos (AUS, LO, LE, LP, LAP, LV) en la columna SI. Una «P» en una
columna cuenta como voto de esa columna (20/11/2026: 35 ✓ + 3 «P» en SI = 38
impreso). La fila de quien preside va vacía. Los totales por columna van
impresos en la cabecera (SI 38 | NO 10 | ABST. 4) y son la validación.

Casi todas son escaneos y la ✓ es imagen aun en las que traen capa de texto,
así que se lee de la imagen: líneas de la tabla → celdas → tinta. Una ✓ deja
~2-3 % de tinta en la celda; un texto (AUS, LE…) 7-12 %; para separar voto de
estado se lee la celda con alfabeto restringido.
"""
from __future__ import annotations

import re

import cv2
import numpy as np
import pytesseract

import parser as P

ESTADOS = {"P", "AUS", "LO", "LE", "LP", "LAP", "LV", "LSA"}
COLS = ("SI", "NO", "ABS")
VOTO_RAW = {"SI": "SI", "NO": "NO", "ABS": "Abst."}
MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "setiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["septiembre"] = 9


def _agrupar(v: np.ndarray, tol: int) -> list[int]:
    out: list[list[int]] = []
    for x in v:
        if out and x - out[-1][-1] <= tol:
            out[-1].append(int(x))
        else:
            out.append([int(x)])
    return [int(np.mean(o)) for o in out]


def lineas(gray: np.ndarray) -> tuple[list[int], list[int]]:
    h, w = gray.shape
    b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    hor = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 12, 1)))
    ver = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 25)))
    ys = _agrupar(np.where(hor.sum(1) > 255 * w * 0.3)[0], 4)
    xs = _agrupar(np.where(ver.sum(0) > 255 * h * 0.15)[0], 4)
    return ys, xs


def _ocr(img: np.ndarray, lang: str, cfg: str) -> str:
    img = cv2.copyMakeBorder(img, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(img, lang=lang, config=cfg).strip()


def leer_estado(celda: np.ndarray, lang: str) -> str | None:
    """Estado escrito en la celda (AUS, LE, P…) o None si es una ✓."""
    big = cv2.resize(celda, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    lecturas = []
    for im in (celda, big):
        for psm in (7, 8):
            t = _ocr(im, lang, f"--psm {psm} -c tessedit_char_whitelist=PAUSLOEVR")
            t = {"PP": "P", "OLE": "LE", "APO": "LAP"}.get(t, t)
            if t in ESTADOS:
                lecturas.append(t)
    if not lecturas:
        return None
    return max(set(lecturas), key=lambda t: (lecturas.count(t), len(t)))


def fecha_es(texto: str) -> str:
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", texto, re.I)
    if not m or P.strip_accents(m[2]).lower() not in MESES:
        return ""
    return f"{int(m[1]):02d}/{MESES[P.strip_accents(m[2]).lower()]:02d}/{m[3]}"


def es_grilla_votacion(gray: np.ndarray, lang: str) -> bool:
    """Cuadrícula de votación (no de asistencia): trae «ASUNTO»."""
    top = P.strip_accents(_ocr(gray[: int(gray.shape[0] * 0.2)], lang, "--psm 6")).upper()
    return "ASUNTO" in top and "NOMINAL" in top


def parse(gray: np.ndarray, res: "P.PageResult", lang: str) -> None:
    """Llena res (kind VOTACION, filas, cabecera) desde la cuadrícula."""
    ys, xs = lineas(gray)
    if len(xs) != 13:
        raise RuntimeError(f"cuadrícula: {len(xs)} líneas verticales (esperado 13)")
    d = np.diff(ys)
    ini = next((i for i in range(len(d) - 29)
                if d[i:i + 30].max() - d[i:i + 30].min() <= 10 and d[i] > 30), None)
    if ini is None or ini < 2:
        raise RuntimeError("cuadrícula: no encuentro 30 filas de paso parejo")
    filas = [(ys[ini + k], ys[ini + k + 1]) for k in range(30)]
    mitades = [xs[0:7], xs[6:13]]

    # cabecera: fecha, presidencia, asunto
    arriba = _ocr(gray[: ys[ini - 2]], lang, "--psm 6")
    res.date = fecha_es(arriba)
    m = re.search(r"Presidencia:?\s*([^\n]+)", arriba)
    if m:
        res.president = m.group(1).strip()
    asunto = _ocr(gray[ys[ini - 2]:ys[ini - 1], xs[0]:xs[-1]], lang, "--psm 6")
    res.asunto = re.sub(r"\s+", " ", re.sub(r"^\s*ASUNTO:?", "", asunto, flags=re.I)).strip()

    # totales impresos por columna (fila baja de la cabecera)
    y0, y1 = (ys[ini - 1] + ys[ini]) // 2, ys[ini]
    X = mitades[0]
    res.printed_cols = {k: P.ocr_digits(gray[y0 + 6:y1 - 6, X[3 + j] + 8:X[4 + j] - 8], lang)
                        for j, k in enumerate(COLS)}

    m_ = 8
    rows = []
    for h, X in enumerate(mitades):
        for k, (a, b) in enumerate(filas):
            nombre = _ocr(gray[a + m_:b - m_, X[2] + m_:X[3] - m_], lang, "--psm 7")
            grupo = _ocr(gray[a + m_:b - m_, X[1] + m_:X[2] - m_], lang, "--psm 7")
            marcas = []
            for j, col in enumerate(COLS):
                celda = gray[a + m_:b - m_, X[3 + j] + m_:X[4 + j] - m_]
                tinta = (celda < 128).mean()
                if tinta < 0.004:
                    continue
                est = leer_estado(celda, lang)
                if est is None and tinta > 0.05:
                    est = "?"
                marcas.append((col, est))
            if len(marcas) == 1:
                col, est = marcas[0]
                voto = VOTO_RAW[col] if est in (None, "P") else ("" if est == "?" else est)
            else:
                voto = ""
                if marcas:
                    res.warn(f"fila {h * 30 + k + 1} ({nombre}): varias marcas {marcas}")
            rows.append(P.TableRow(h, k, grupo, nombre, voto, (a, b, X[3], X[6])))
    res.rows = rows
    res.kind = "VOTACION"
    res.formato = "grilla"
