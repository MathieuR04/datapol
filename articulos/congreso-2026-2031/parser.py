#!/usr/bin/env python3
"""Votaciones nominales de los PDF «Asistencia y votación», Congreso bicameral 2026-2031.

Heredero de articulos/congressional_votes_parsing/parse_votaciones.py (Congreso
2021-2026). El núcleo OCR es el mismo y está probado: render a 300 DPI → canal
azul (borra los sellos azules) → cajas de palabras de Tesseract → filas
reconstruidas geométricamente (nunca la segmentación de líneas de Tesseract).
Lo que cambia para 2026:

* **Padrón oficial en vez de padrón por consenso.** Cada fila se asigna a un
  miembro de data/roster.json (API de la cámara) con una asignación óptima
  uno-a-uno por página (Hungarian). Así los nombres truncados («DOMINGUEZ
  HERRERA,») y los errores de OCR se resuelven contra la lista real, y partido
  y foto salen de ahí.
* **Tamaño de cámara variable**: 130 diputados, 60 senadores.
* **Validación por bancada.** Cada página imprime dos cuadros: «Resultado de
  VOTACIÓN» (totales) y «Grupo Parlamentario» (Si/No/Abst/Sin Resp. por
  bancada). En Diputados el sello tapa a menudo la parte baja del primero; el
  segundo queda libre y además es más exigente (cuadra bancada por bancada),
  así que es el control principal. Se compara el conteo *antes* de aplicar la
  constancia, porque así está impreso.
* **Constancias** nombran «senador(es)/diputado(s)» además de «congresista(s)»,
  y se leen con un OCR aparte sobre un recorte que arranca en la columna del
  cuadro de bancadas, para dejar el sello fuera.
* Las páginas de tabla con ✓ («VOTACIÓN NOMINAL», votación manual) se marcan
  TABLA_CHECK y se omiten (decisión 2026-09-27: son pocas y procedimentales).

Uso como librería: `parse_pdf(path, camara, roster) -> (votos_df, paginas)`.
CLI de prueba: python3 parser.py <pdf> --camara senado [--pages 3-5]
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytesseract
from scipy.optimize import linear_sum_assignment

from config import ALIAS_GRUPO, TAMANO_CAMARA

log = logging.getLogger("parser")
HERE = Path(__file__).resolve().parent

PARTY_CODES = {"FP", "JP", "PBG", "RP", "PCO", "AN"} | set(ALIAS_GRUPO)

# Formas canónicas de las marcas de voto (ya normalizadas por `vote_key`).
VOTE_KEYS = {"SI", "NO", "AUS", "SINRES", "ABST", "LO", "LE", "LP", "LV",
             "L25A", "SUS", "***"}

# Cuadro «Resultado de VOTACIÓN»: prefijo de etiqueta → clave de conteo.
SUMMARY_LABELS = [
    ("a favor", "SI"), ("en contra", "NO"), ("abstencion", "ABS"),
    ("sin respuesta", "SINRES"), ("ausente", "AUS"),
    ("lic. oficial", "LIC"), ("lic oficial", "LIC"),
    ("lic. por enfermedad", "LIC"), ("lic por enfermedad", "LIC"),
    ("lic. personal", "LIC"), ("lic personal", "LIC"),
    ("lic. por viaje", "LIC"), ("lic por viaje", "LIC"),
    ("suspendido", "SUS"),
]

CONSTANCIA_DIR = {"a favor": "SI", "en contra": "NO", "en abstencion": "ABS"}
ROL = r"(?:congresistas?|senador(?:a|es|as)?|diputad[oa]s?)"

N_COLUMNS = 3


# ── helpers ──────────────────────────────────────────────────────────────────

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_key(s: str) -> str:
    s = strip_accents(s).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", s).split())


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def canon_party(raw: str) -> str:
    up = norm_key(raw).replace(" ", "")
    if up in PARTY_CODES:
        return ALIAS_GRUPO.get(up, up)
    if not up:
        return ""
    best = max(PARTY_CODES, key=lambda p: ratio(up, p))
    return ALIAS_GRUPO.get(best, best) if ratio(up, best) >= 0.6 else ""


def vote_key(tok: str) -> str:
    """Token de voto → forma canónica para anclar la columna ('NO—' → 'NO')."""
    t = strip_accents(tok).upper().strip(" .,:;'\"”“—–-+")
    return t if t in VOTE_KEYS else ("***" if t.startswith("**") else "")


def normalize_vote(raw: str) -> str | None:
    # Palabras antes que símbolos: un «+» suelto de la columna vecina pegado a
    # una marca («+ AUS», Senado 09/09 y 16/09) no debe convertirla en SÍ.
    for w in re.findall(r"[A-Z0-9]+", strip_accents(raw).upper()):
        if w.startswith("SIN"):
            return "SINRES"
        if w.startswith("ABST"):
            return "ABS"
        if w.startswith("AUS"):
            return "AUS"
        if re.fullmatch(r"L(O|E|P|V|25A)", w):
            return "LIC"
        if w.startswith("SUS"):
            return "SUS"
    flat = strip_accents(raw).upper().replace(" ", "")
    flat = re.sub(r"^[^A-Z0-9*+]+", "", flat)   # «— SI», «“SI»
    if not flat:
        return None
    if flat.startswith("SIN"):
        return "SINRES"
    if flat.startswith("ABST"):
        return "ABS"
    if flat.startswith("AUS"):
        return "AUS"
    if flat.startswith(("SI", "S1", "5I")) or "+" in flat:
        return "SI"
    if flat.startswith(("NO", "N0")) or re.search(r"[-—–]{2,}", flat):
        return "NO"
    if re.fullmatch(r"L[A-Z0-9]{1,3}", flat):   # LO/LE/LP/LV/L25A
        return "LIC"
    if flat.startswith("SUS"):
        return "SUS"
    if "*" in flat:
        return "PRESIDENTE"
    return None


# ── modelo ───────────────────────────────────────────────────────────────────

@dataclass
class TableRow:
    col: int
    idx: int
    party_raw: str
    name_raw: str
    vote_raw: str
    box: tuple = ()    # (y0, y1, x0, x1) de la celda de voto, para re-OCR


@dataclass
class PageResult:
    page: int
    kind: str = "UNKNOWN"      # VOTACION | ASISTENCIA | TABLA_CHECK | UNKNOWN | ERROR
    date: str = ""
    time: str = ""
    asunto: str = ""
    president: str = ""
    rows: list = field(default_factory=list)
    printed_totals: dict = field(default_factory=dict)
    printed_grupos: dict = field(default_factory=dict)
    constancia_text: str = ""
    validacion: str = ""       # ok | mismatch | sin_validar
    nota: str = ""             # texto bajo el pie («se anunciaron 115 votos…»)
    warnings: list = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        log.warning("p%d: %s", self.page, msg)


# ── render + OCR (idéntico a 2021) ───────────────────────────────────────────

def render_page(pdf_path: str, page: int, dpi: int) -> np.ndarray:
    cmd = ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
           "-singlefile", pdf_path]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"pdftoppm falló en p{page}")
    img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
    return img[:, :, 0]   # canal azul: borra los sellos


def deskew(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, None, fx=0.25, fy=0.25)
    binv = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    merged = cv2.morphologyEx(binv, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)))
    lines = cv2.HoughLinesP(merged, 1, np.pi / 720, threshold=80,
                            minLineLength=small.shape[1] // 4, maxLineGap=8)
    if lines is None:
        return gray
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1))
              for x1, y1, x2, y2 in lines.reshape(-1, 4)]
    angles = [a for a in angles if abs(a) < 3]
    if not angles or abs(np.median(angles)) < 0.15:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(np.median(angles)), 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)


def ocr_words(gray: np.ndarray, lang: str, psm: int = 6) -> pd.DataFrame:
    # Output.DICT, no DATAFRAME: pandas convertiría un «NA» en NaN.
    raw = pytesseract.image_to_data(gray, lang=lang, config=f"--psm {psm}",
                                    output_type=pytesseract.Output.DICT)
    df = pd.DataFrame(raw)
    df = df[df.conf.astype(float) > 0].copy()
    df["text"] = df.text.astype(str).str.strip()
    df = df[df.text != ""]
    df["cx"] = df.left + df.width / 2
    df["cy"] = df.top + df.height / 2
    return df.reset_index(drop=True)


def ocr_digits(img: np.ndarray, lang: str) -> int | None:
    """Número de una celda: varias lecturas (2 escalas × 2 modos), mayoría."""
    if img.size == 0:
        return None
    img = cv2.copyMakeBorder(img, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    reads = []
    for im in (img, big):
        for psm in (7, 8):
            t = pytesseract.image_to_string(
                im, lang=lang,
                config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
            t = re.sub(r"\D", "", t)
            if t:
                reads.append(t)
    if not reads:
        # Celda en blanco o un «0» que el whitelist no reconoce: si casi no
        # hay tinta, es 0.
        ink = (img < 128).mean()
        return 0 if ink < 0.002 else None
    val, n = Counter(reads).most_common(1)[0]
    return int(val if n >= 2 else reads[0])


def cluster_by_gap(values: np.ndarray, gap: float) -> list[np.ndarray]:
    order = np.argsort(values)
    groups, cur = [], [order[0]]
    for i in order[1:]:
        if values[i] - values[cur[-1]] > gap:
            groups.append(np.array(cur))
            cur = [i]
        else:
            cur.append(i)
    groups.append(np.array(cur))
    return groups


def reconstruct_lines(words: pd.DataFrame, gap: float) -> list[str]:
    if words.empty:
        return []
    out = []
    for g in cluster_by_gap(words.cy.to_numpy(float), gap):
        sub = words.iloc[g].sort_values("left")
        out.append((float(sub.cy.mean()), " ".join(sub.text)))
    return [t for _, t in sorted(out)]


def anchor_top(words: pd.DataFrame, pattern: str) -> float | None:
    hits = words[words.text.str.contains(pattern, case=False, regex=True, na=False)]
    return float(hits.top.min()) if len(hits) else None


# ── encabezado ───────────────────────────────────────────────────────────────

def parse_header(words: pd.DataFrame, res: PageResult, scale: float) -> None:
    head = words[words.top < 620 * scale]
    # Por líneas reconstruidas: ordenar por `top` intercala palabras de una
    # misma línea y separa «VOTACIÓN:» de «Fecha:».
    lines = reconstruct_lines(head, 16 * scale)
    text = "\n".join(lines)
    flat = strip_accents(text).upper()
    if "NOMINAL" in flat:
        res.kind = "TABLA_CHECK"
    elif re.search(r"VOTACION\s*:?\s*FECHA", flat):
        res.kind = "VOTACION"
    elif re.search(r"ASISTENCIA\s*:?\s*FECHA", flat):
        res.kind = "ASISTENCIA"
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        res.date = m.group(1)
    m = re.search(r"Hora:?\s*(\d{1,2}:\d{2})\s*(am|pm|a\.\s?m\.|p\.\s?m\.)?", text, re.I)
    if m:
        res.time = (m.group(1) + " " + (m.group(2) or "")).strip()
    for line in lines:
        m = re.search(r"Presidente:\s*(.{6,})", line)
        if m:
            res.president = m.group(1).strip()
            break


# ── tabla de votos ───────────────────────────────────────────────────────────

def parse_table(words: pd.DataFrame, res: PageResult, scale: float) -> dict:
    resultados_top = anchor_top(words, r"^Resultados?$")
    if resultados_top is None:
        resultados_top = anchor_top(words, r"^Grupo$")
    if resultados_top is None:
        res.warn("sin ancla 'Resultado'; se usa 72% de la página")
        resultados_top = words.cy.max() * 0.72

    asunto_top = anchor_top(words, r"^Asunto:?$")
    header_bottom = (asunto_top + 30 * scale) if asunto_top else 500 * scale

    body = words[(words.cy > header_bottom) & (words.cy < resultados_top - 10)]
    party = body[body.text.map(lambda t: norm_key(t) in PARTY_CODES)]
    if len(party) < 15:
        raise RuntimeError(f"sólo {len(party)} códigos de bancada en la tabla")

    groups = cluster_by_gap(party.left.to_numpy(float), gap=300 * scale)
    groups = sorted(groups, key=lambda g: party.left.to_numpy(float)[g].min())
    groups = [g for g in groups if len(g) >= 3]   # basura suelta
    if len(groups) != N_COLUMNS:
        raise RuntimeError(f"se esperaban 3 columnas de bancada, hay {len(groups)}")
    col_x = [float(np.median(party.left.to_numpy(float)[g])) for g in groups]

    table_top = party.top.min() - 10 * scale
    table_bot = party.top.max() + party.height.max() + 10 * scale
    table = body[(body.cy > table_top) & (body.cy < table_bot)]

    margin = 40 * scale
    bounds = [col_x[0] - margin, col_x[1] - margin, col_x[2] - margin,
              float(words.left.max() + 1000)]
    rows: list[TableRow] = []
    for c in range(N_COLUMNS):
        band = table[(table.left >= bounds[c]) & (table.left < bounds[c + 1])]
        if band.empty:
            res.warn(f"columna {c} vacía")
            continue
        vt = band[band.text.map(lambda t: vote_key(t) != "")]
        # La marca de voto es la última palabra de la fila; el borde izquierdo
        # más frecuente de los tokens de voto ancla la subcolumna.
        vote_x = (float(vt.left.quantile(0.2)) if len(vt) >= 5
                  else bounds[c + 1] - 160 * scale)
        tops = np.sort(band[band.text.map(lambda t: norm_key(t) in PARTY_CODES)]
                       .top.to_numpy(float))
        pitch = float(np.median(np.diff(tops))) if len(tops) > 5 else 44 * scale
        pitch = max(pitch, 30 * scale)
        kept = []
        for g in cluster_by_gap(band.cy.to_numpy(float), gap=0.5 * pitch):
            sub = band.iloc[g].sort_values("left")
            p_t, n_t, v_t = [], [], []
            for _, w in sub.iterrows():
                if w.left >= vote_x - 30 * scale:
                    v_t.append(w.text)
                elif w.left < col_x[c] + 110 * scale and not n_t:
                    p_t.append(w.text)
                else:
                    n_t.append(w.text)
            # «— SI»: el guion de relleno a veces cae antes de la subcolumna
            if n_t and not v_t and vote_key(n_t[-1]):
                v_t = [n_t.pop()]
            box = (int(sub.top.min() - 8 * scale), int((sub.top + sub.height).max() + 8 * scale),
                   int(vote_x - 40 * scale), int(bounds[c + 1] - 20 * scale)
                   if c < N_COLUMNS - 1 else int(vote_x + 200 * scale))
            row = TableRow(c, len(kept), "".join(p_t), " ".join(n_t), " ".join(v_t), box)
            if (canon_party(row.party_raw) or normalize_vote(row.vote_raw)
                    or len(norm_key(row.name_raw)) >= 8):
                kept.append(row)
        for i, r in enumerate(kept):
            r.idx = i
        rows += kept
    res.rows = rows
    return {"col_x": col_x, "resultados_top": resultados_top,
            "table_top": table_top, "table_bot": table_bot,
            "header_bottom": header_bottom}


VOTE_WHITELIST = "SINOAUSLEPVRbstinoaues*+-—25."


def reocr_votes(gray, res: PageResult, lang: str) -> None:
    """Segunda lectura de las marcas que el OCR de página completa no entendió.

    Tesseract en página completa lee a veces un «SI» limpio como «ES» o «E»
    (conf ~55). Sobre la celda sola, con alfabeto restringido y cuatro
    lecturas, sale bien; se toma la mayoría de las que normalizan."""
    for r in res.rows:
        if normalize_vote(r.vote_raw) is not None or not r.box:
            continue
        y0, y1, x0, x1 = r.box
        crop = gray[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        votos = []
        for im in (crop, big):
            for psm in (7, 8):
                t = pytesseract.image_to_string(
                    im, lang=lang,
                    config=f"--psm {psm} -c tessedit_char_whitelist={VOTE_WHITELIST}").strip()
                v = normalize_vote(t)
                if v:
                    votos.append((v, t))
        if votos:
            best = Counter(v for v, _ in votos).most_common(1)[0][0]
            raw = next(t for v, t in votos if v == best)
            log.info("p%d: re-OCR %r → %r", res.page, r.vote_raw, raw)
            r.vote_raw = raw


def parse_asunto(words: pd.DataFrame, res: PageResult, geom: dict, scale: float):
    zone = words[(words.cy > geom["header_bottom"] - 45 * scale)
                 & (words.cy < geom["table_top"])]
    zone = zone[~zone.text.str.fullmatch(r"Asunto:?", case=False)]
    res.asunto = re.sub(r"\s+", " ", " ".join(reconstruct_lines(zone, 18 * scale))).strip()
    if not res.asunto:
        res.warn("asunto vacío")


# ── cuadros de resultados ────────────────────────────────────────────────────

def grupo_geometry(words: pd.DataFrame, geom: dict, scale: float) -> dict | None:
    """Ubica el cuadro «Grupo Parlamentario»: x de los códigos, filas y
    centros de las columnas Si/No/Abst/Sin Resp."""
    below = words[words.cy > geom["resultados_top"] - 20 * scale]
    hdr = below[below.text.str.fullmatch(r"Grupo", case=False)]
    if hdr.empty:
        return None
    hy, hx = float(hdr.cy.iloc[0]), float(hdr.left.iloc[0])
    hline = below[(below.cy - hy).abs() < 20 * scale]
    cols = {}
    for key, pat in (("SI", r"^S[iíl1]"), ("NO", r"^N[o0]"),
                     ("ABS", r"bst"), ("SINRES", r"^Sin$")):
        t = hline[hline.text.str.contains(pat, regex=True) & (hline.left > hx + 400 * scale)]
        if len(t):
            cols[key] = float(t.cx.iloc[0]) + (25 * scale if key == "SINRES" else 0)
    codes = below[(below.cy > hy + 15 * scale) & ((below.left - hx).abs() < 60 * scale)
                  & below.text.map(lambda t: norm_key(t) in PARTY_CODES)]
    if len(cols) < 3 or codes.empty:
        return None
    return {"x": hx, "y": hy, "cols": cols,
            "rows": [(canon_party(r.text), float(r.top), float(r.top + r.height))
                     for r in codes.itertuples()]}


def parse_grupos(gray, gg: dict, scale: float, lang: str) -> dict:
    xs = sorted(gg["cols"].values())
    half = (min(np.diff(xs)) if len(xs) > 1 else 150 * scale) * 0.42
    out = {}
    for party, y0, y1 in gg["rows"]:
        fila = {}
        for key, cx in gg["cols"].items():
            crop = gray[int(y0 - 6 * scale):int(y1 + 6 * scale),
                        int(cx - half):int(cx + half)]
            fila[key] = ocr_digits(crop, lang)
        out[party] = fila
    return out


def parse_totals(words, gray, geom: dict, gg: dict | None, scale: float,
                 lang: str) -> dict:
    """Cuadro «Resultado de VOTACIÓN» (etiquetas a la izquierda, número al lado)."""
    x_max = (gg["x"] - 30 * scale) if gg else geom["col_x"][1] - 60 * scale
    zone = words[(words.cy > geom["resultados_top"]) & (words.left < x_max)]
    if zone.empty:
        return {}
    digits = zone[zone.text.str.fullmatch(r"\d{1,3}")]
    x_num = float(digits.cx.median()) if len(digits) >= 3 else x_max - 120 * scale
    counts: Counter = Counter()
    for g in cluster_by_gap(zone.cy.to_numpy(float), 16 * scale):
        sub = zone.iloc[g]
        label = strip_accents(" ".join(
            sub[sub.cx < x_num - 50 * scale].sort_values("left").text)).lower()
        key = next((k for pre, k in SUMMARY_LABELS if label.startswith(pre)), None)
        if key is None:
            continue
        y0, y1 = int(sub.top.min() - 5 * scale), int((sub.top + sub.height).max() + 5 * scale)
        v = ocr_digits(gray[y0:y1, int(x_num - 70 * scale):int(x_num + 70 * scale)], lang)
        if v is not None:
            counts[key] += v
    return dict(counts)


def parse_constancia(gray, words, geom: dict, gg: dict | None, scale: float,
                     lang: str) -> str:
    """OCR aparte del párrafo «deja constancia», recortado desde la columna del
    cuadro de bancadas hacia la derecha (el sello queda a la izquierda)."""
    x0 = int((gg["x"] if gg else geom["col_x"][1] - 150 * scale) - 20 * scale)
    y0 = int((max(r[2] for r in gg["rows"]) if gg else geom["resultados_top"]) + 8 * scale)
    foot = words[(words.cy > y0) & words.text.str.startswith("***")]
    y1 = int(foot.top.min() - 5 * scale) if len(foot) else gray.shape[0] - int(80 * scale)
    if y1 - y0 < 30 * scale:
        return ""
    text = pytesseract.image_to_string(gray[y0:y1, x0:], lang=lang, config="--psm 6")
    text = re.sub(r"\s+", " ", text.replace("-\n", "")).strip()
    return limpiar_constancia(text) if "constancia" in strip_accents(text).lower() else ""


def parse_nota(gray, words, scale: float, lang: str) -> str:
    """Observaciones impresas bajo el pie «*** En este reporte…» (p. ej. votos
    anunciados ≠ registrados). Ancho completo: van a la izquierda."""
    foot = words[words.text.str.startswith("***") & (words.cy > gray.shape[0] * 0.5)]
    if foot.empty:
        return ""
    y0 = int((foot.top + foot.height).max() + 10 * scale)
    if gray.shape[0] - y0 < 25 * scale:
        return ""
    text = pytesseract.image_to_string(gray[y0:, :], lang=lang, config="--psm 6")
    text = re.sub(r"\s+", " ", text).strip()
    return text if es_prosa(text) else ""


def limpiar_constancia(text: str) -> str:
    """Corta el párrafo en la primera «oración» que ya no es prosa: el recorte
    alcanza a veces el sello y el OCR agrega basura tras el punto final
    («… Ventura Ángel. / DE LA F v % CS A o yo LA…»)."""
    out = []
    for o in re.split(r"(?<=\.)\s+", text):
        if not es_prosa(o) and out:
            break
        # basura *dentro* de la oración (el sello cae sobre el renglón): se
        # corta en la primera ficha que no es palabra de prosa ni nombre
        toks = o.split()
        for i, t in enumerate(toks):
            if re.fullmatch(r"[A-ZÁÉÍÓÚÑ]{2,}[,.;]?|[^\wÁÉÍÓÚÑáéíóúñ,.;:()«»]+", t) and i > 3:
                o = " ".join(toks[:i]).rstrip(",;") + "."
                out.append(o)
                return " ".join(out).strip()
        out.append(o)
    return " ".join(out).strip()


def nombre_limpio(name: str) -> str:
    """Primer tramo de palabras con forma de apellido/nombre («Manay Pillaca DED P
    DE Dip…» → «Manay Pillaca»): capitalizadas o conectores de apellido."""
    keep = []
    for t in name.split():
        t = t.strip(";:,.")          # «Valqui Calderón;» → «Calderón»
        if re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+|de|del|la|las|los|De|Del|La", t):
            keep.append(t)
        else:
            break
    return " ".join(keep)


def es_prosa(text: str) -> bool:
    """¿Texto real o ruido del borde del escaneo? El ruido OCR sale en
    mayúsculas sueltas («LL LT DA E TL…»); una observación del acta es prosa
    en minúsculas."""
    return len(re.findall(r"\b[a-záéíóúñ]{3,}\b", text)) >= 5


def constancia_corrections(res: PageResult) -> list[tuple[str, str]]:
    if not res.constancia_text:
        return []
    flat = strip_accents(res.constancia_text)
    out, matched = [], False
    # «…deja constancia del voto a favor de los senadores A y B, y del voto en
    #  contra del diputado C.» — cada cláusula termina en el siguiente «del voto».
    for m in re.finditer(
            r"(?:del voto|de la votacion|de su voto) (a favor|en contra|en abstencion)\s+"
            # «del los senadores» aparece tal cual en un acta (Senado 18/08/2026)
            r"(?:del l[oa]s|del|de l[oa]s?|de la|de)\s+" + ROL + r"\s+"
            r"(.+?)(?=,?\s+y del voto |\s+del voto |\.|$)", flat, re.I):
        matched = True
        vote = CONSTANCIA_DIR[m.group(1).lower()]
        for name in re.split(r"[,;]|\sy\s", m.group(2)):
            name = nombre_limpio(name.strip()) or name
            name = re.sub(r"[^A-Za-z ]+", " ", strip_accents(name)).strip()
            if len(name) >= 4:
                out.append((name, vote))
    # «El diputado X deja constancia de (que) su voto (es) a favor…»
    for m in re.finditer(
            r"(?:El|La)\s+" + ROL + r"\s+(.+?),?\s+deja constancia de "
            r"(?:que )?su voto (?:es )?(a favor|en contra|en abstencion)", flat, re.I):
        matched = True
        # «El senador Torres Morales, presidente del Senado…»: el nombre es lo
        # que va antes de la primera coma.
        out.append((m.group(1).split(",")[0].strip(), CONSTANCIA_DIR[m.group(2).lower()]))
    if not matched:
        res.warn(f"constancia sin interpretar: {res.constancia_text[:160]!r}")
    return out


# ── asignación al padrón ─────────────────────────────────────────────────────

def row_score(name_raw: str, m: dict) -> float:
    ap_raw, coma, nom_raw = name_raw.partition(",")
    ap, nom = norm_key(ap_raw), norm_key(nom_raw)
    if not coma:   # se perdió la coma: comparar contra el prefijo del nombre completo
        full = norm_key(f"{m['apellidos']} {m['nombres']}")
        return ratio(ap, full[:len(ap) + 2])
    ap_m = norm_key(m["apellidos"])
    # El padrón de la API a veces trae menos apellidos que el PDF («Duarte» vs
    # «DUARTE PATIÑO DE PEZET»): se acepta también el prefijo, con castigo.
    s_ap = max(ratio(ap, ap_m), 0.9 * ratio(ap[:len(ap_m)], ap_m))
    if not nom:
        return s_ap
    s_nom = ratio(nom, norm_key(m["nombres"])[:len(nom) + 2])
    return 0.8 * s_ap + 0.2 * s_nom


def surname_score(name: str, m: dict) -> float:
    """Nombre de una constancia («Del Águila Cárdenas») contra un miembro."""
    n = norm_key(name)
    ap, full = norm_key(m["apellidos"]), norm_key(f"{m['nombres']} {m['apellidos']}")
    # prefijo en ambos sentidos: la API a veces trae menos apellidos que el acta
    # («Duarte» vs «Duarte Patiño»), igual que en row_score
    pref = 0.95 * ratio(n[:len(ap)], ap) if len(ap) >= 5 else 0
    return max(ratio(n, ap), ratio(n, full), ratio(n, ap[:len(n) + 2]), pref)


def match_constancia(name: str, members: list[dict]) -> tuple[int | None, float]:
    sc = sorted(((surname_score(name, m), i) for i, m in enumerate(members)), reverse=True)
    best, i = sc[0]
    runner = sc[1][0] if len(sc) > 1 else 0
    if best < 0.75 or (best - runner < 0.04 and best < 0.97):
        return None, best
    return i, best


# ── página ───────────────────────────────────────────────────────────────────

def process_page(pdf: str, page: int, dpi: int, lang: str) -> tuple[PageResult, dict]:
    res = PageResult(page=page)
    scale = dpi / 300.0
    gray = deskew(render_page(pdf, page, dpi))
    parse_header(ocr_words(gray[: int(gray.shape[0] * 0.18)], lang), res, scale)
    if res.kind != "VOTACION":
        return res, {}
    words = ocr_words(gray, lang)
    parse_header(words, res, scale)
    res.kind = "VOTACION"
    geom = parse_table(words, res, scale)
    reocr_votes(gray, res, lang)
    parse_asunto(words, res, geom, scale)
    gg = grupo_geometry(words, geom, scale)
    if gg:
        res.printed_grupos = parse_grupos(gray, gg, scale, lang)
    else:
        res.warn("no se ubicó el cuadro por bancada")
    res.printed_totals = parse_totals(words, gray, geom, gg, scale, lang)
    res.constancia_text = parse_constancia(gray, words, geom, gg, scale, lang)
    res.nota = parse_nota(gray, words, scale, lang)
    return res, geom


def assign_rows(p: PageResult, members: list[dict]) -> dict[int, TableRow]:
    """Asignación óptima uno-a-uno filas ↔ miembros."""
    cost = np.array([[1 - row_score(r.name_raw, m) for m in members] for r in p.rows])
    ri, mi = linear_sum_assignment(cost)
    out = {}
    for r, m in zip(ri, mi):
        s = 1 - cost[r, m]
        if s < 0.55:
            p.warn(f"fila {p.rows[r].name_raw!r} ≈ {members[m]['nombre']!r} "
                   f"con score bajo ({s:.2f}); se descarta")
            continue
        out[m] = p.rows[r]
    return out


def fill_grupos(grupos: dict, totals: dict, n: int) -> dict:
    """Celdas ilegibles del cuadro por bancada, deducidas del total impreso:
    si en una columna falta exactamente una celda, vale total − resto."""
    g = {k: dict(v) for k, v in grupos.items()}
    if sum(totals.values()) != n:    # totales mal leídos: no se usan para deducir
        return g
    for k in ("SI", "NO", "ABS"):
        if k not in totals:
            continue
        faltan = [p for p, f in g.items() if f.get(k) is None]
        if len(faltan) == 1:
            resto = sum(f[k] for p, f in g.items() if p != faltan[0])
            if 0 <= totals[k] - resto:
                g[faltan[0]][k] = totals[k] - resto
    return g


def validate(p: PageResult, recs: list[dict], n: int) -> None:
    """Conteo propio (antes de constancias) contra los cuadros impresos.

    Control principal: Si/No/Abst por bancada (sólo celdas legibles, con al
    menos 2/3 del cuadro leído). Secundario: los totales, si suman el tamaño
    de la cámara (si el sello se comió una etiqueta, no suman y se omite)."""
    checks, fails, grupos_ok = 0, [], False
    ours: dict = {}
    for r in recs:
        ours.setdefault(r["grupo_pdf"], Counter())[r["voto_tabla"]] += 1
    if p.printed_grupos:
        g = fill_grupos(p.printed_grupos, p.printed_totals, n)
        celdas = [(party, k, f.get(k)) for party, f in g.items() for k in ("SI", "NO", "ABS")]
        legibles = [c for c in celdas if c[2] is not None]
        if len(legibles) >= 2 * len(celdas) / 3:
            checks += 1
            antes = len(fails)
            tamano = {party: sum(c.values()) for party, c in ours.items()}
            for party, k, want in legibles:
                got = ours.get(party, Counter())[k]
                if want > tamano.get(party, 0):
                    # Imposible (más votos que miembros: «47» por «17»): es la
                    # lectura del cuadro la que falla, no la nuestra.
                    p.warn(f"celda impresa ilegible {party} {k}={want} (la bancada tiene "
                           f"{tamano.get(party, 0)}); se ignora")
                    continue
                if got != want:
                    fails.append(f"{party} {k}: nuestro {got} vs impreso {want}")
            grupos_ok = len(fails) == antes
    if p.printed_totals and sum(p.printed_totals.values()) == n:
        checks += 1
        tally = Counter("SINRES" if r["voto_tabla"] == "PRESIDENTE" else r["voto_tabla"]
                        for r in recs)
        dif = [f"total {k}: registro {tally[k]} vs impreso {want}"
               for k, want in p.printed_totals.items() if tally[k] != want]
        # El cuadro de totales puede recoger lo *anunciado* en sala y no lo
        # registrado (13/08/2026: «se anunciaron 115 votos a favor, habiéndose
        # registrado 120»; lo dice la nota al pie). Si el cuadro por bancada
        # cuadra con nuestra lectura, la lectura es correcta y la diferencia
        # es del documento: se anota, no se marca como error.
        if dif and grupos_ok:
            p.warn("totales impresos difieren del registro por bancada — " + "; ".join(dif))
        else:
            fails += dif
    p.validacion = "sin_validar" if not checks else ("mismatch" if fails else "ok")
    if fails:
        p.warn("no cuadra con lo impreso — " + "; ".join(fails))


def assemble(p: PageResult, members: list[dict], camara: str, pdf_stem: str) -> list[dict]:
    n = TAMANO_CAMARA[camara]
    slot = assign_rows(p, members)
    if len(p.rows) != n:
        p.warn(f"{len(p.rows)} filas leídas (esperado {n})")
    recs = []
    for i, m in enumerate(members):
        r = slot.get(i)
        if r is None:
            if m.get("condicion") == "en-ejercicio":
                p.warn(f"sin fila para {m['nombre']}")
            continue
        v = normalize_vote(r.vote_raw)
        if v is None:
            if p.president and surname_score(p.president.split(",")[0], m) > 0.85:
                v = "PRESIDENTE"
            else:
                p.warn(f"voto ilegible {r.vote_raw!r} de {m['nombre']}")
                v = "ILEGIBLE"
        recs.append({
            "camara": camara, "vote_id": f"{pdf_stem}:p{p.page:03d}",
            "pdf": pdf_stem, "pagina": p.page, "fecha": p.date, "hora": p.time,
            "asunto": p.asunto, "miembro_id": m["id"], "nombre": m["nombre"],
            "grupo": m["grupo"], "grupo_pdf": canon_party(r.party_raw) or m["grupo"],
            "voto_tabla": v, "voto": v, "voto_raw": r.vote_raw, "fuente": "tabla",
        })
    validate(p, recs, n)
    by_id = {r["miembro_id"]: r for r in recs}
    for name, vote in constancia_corrections(p):
        i, s = match_constancia(name, members)
        if i is None:
            p.warn(f"constancia: no identifico a {name!r} (score {s:.2f})")
            continue
        rec = by_id.get(members[i]["id"])
        if rec and rec["voto"] != vote:
            rec["voto"], rec["fuente"] = vote, "constancia"
    return recs


def pick_lang() -> str:
    local = HERE / "tessdata" / "spa.traineddata"
    if local.exists():
        os.environ["TESSDATA_PREFIX"] = str(local.parent)
        return "spa"
    return "spa" if "spa" in pytesseract.get_languages() else "eng"


def n_pages(pdf: str) -> int:
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))


def parse_pdf(pdf: str, camara: str, roster: list[dict], pages=None,
              dpi: int = 300, jobs: int = 4) -> tuple[pd.DataFrame, list[dict]]:
    """→ (votos: una fila por miembro×votación, páginas: metadatos + advertencias)."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    lang = pick_lang()
    members = [m for m in roster if m["camara"] == camara]
    pages = pages or list(range(1, n_pages(pdf) + 1))
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(process_page, pdf, pg, dpi, lang): pg for pg in pages}
        for fut, pg in futs.items():
            try:
                results.append(fut.result()[0])
            except Exception as e:
                bad = PageResult(page=pg, kind="ERROR")
                bad.warn(str(e))
                results.append(bad)
    results.sort(key=lambda r: r.page)
    stem = Path(pdf).stem
    recs = []
    for p in results:
        if p.kind == "VOTACION" and p.rows:
            recs += assemble(p, members, camara, stem)
    meta = []
    for p in results:
        d = asdict(p)
        d.pop("rows")
        d["n_filas"] = len(p.rows)
        meta.append(d)
    return pd.DataFrame(recs), meta


if __name__ == "__main__":
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("--camara", required=True, choices=sorted(TAMANO_CAMARA))
    ap.add_argument("--pages", help="3-6 o 3,5,9")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pages = None
    if a.pages:
        pages = []
        for part in a.pages.split(","):
            lo, _, hi = part.partition("-")
            pages += list(range(int(lo), int(hi or lo) + 1))
    roster = json.loads((HERE / "data" / "roster.json").read_text())
    df, meta = parse_pdf(a.pdf, a.camara, roster, pages, jobs=a.jobs)
    for p in meta:
        if p["kind"] == "VOTACION":
            print(f"p{p['page']:>3} {p['date']} {p['time']:>8} filas={p['n_filas']:>3} "
                  f"{p['validacion']:<11} {p['asunto'][:70]}")
        else:
            print(f"p{p['page']:>3} {p['kind']}")
    if len(df):
        print(df.groupby("vote_id").voto.value_counts().unstack(fill_value=0).to_string())
        print("constancias aplicadas:", (df.fuente == "constancia").sum())
    if a.output:
        df.to_csv(a.output, index=False)
