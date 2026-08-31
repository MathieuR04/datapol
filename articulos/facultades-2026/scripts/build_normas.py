#!/usr/bin/env python3
r"""Universo de normas que el pedido de facultades tocaría → data/normas.json.

QUÉ PREGUNTA CONTESTA: si el Congreso aprueba la delegación, ¿sobre qué cuerpo
normativo concreto queda habilitado el Ejecutivo a legislar por 120 días?

POR QUÉ HAY QUE LEER LAS DOS FUENTES Y NO SÓLO EL ARTICULADO. El articulado —el
texto que el Congreso vota— nombra 41 normas, pero 49 de sus 66 propuestas no
citan ninguna: dicen "legislar en materia de X". La exposición de motivos, en
cambio, sí nombra las normas que se piensa modificar, incluso para esas 49. O sea
que el documento que se vota delimita menos que el documento que lo explica, y el
alcance real sólo se ve cruzando ambos. Esa brecha es el hallazgo, no un
tecnicismo: mide cuánto de lo que el Ejecutivo ya tiene identificado para
modificar no quedó escrito en la norma habilitante.

Distingue por eso `en_articulado` (vinculante, es lo que el Congreso aprueba) de
`solo_en_motivos` (declarado, pero fuera del texto que se vota).

Run: python3 scripts/build_normas.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PROPS = os.path.join(ROOT, "data", "propuestas.json")
MOTIVOS = os.path.join(ROOT, "data", "ocr", "exposicion_motivos.txt")
OUT = os.path.join(ROOT, "data", "normas.json")

GRADO = r"(?:N\.?\s*[°º*”?¿'’\"]|Nº|N\.\s)"
TIPOS = r"(Decreto\s+Legislativo|Decreto\s+Ley|Decreto\s+Supremo|Ley|Decreto\s+de\s+Urgencia)"
# Los decretos supremos y de urgencia se numeran NNN-AAAA-SECTOR: capturar sólo el
# "006" los fusiona entre sí (hay decenas de "DS 006-" distintos), así que el
# sufijo va incluido en la llave cuando existe.
CITA_RE = re.compile(
    rf"{TIPOS}\s*{GRADO}\s*([0-9]{{3,5}}(?:\s*[-–]\s*[0-9]{{4}}(?:\s*[-–]\s*[A-ZÑ]{{2,10}})?)?)",
    re.IGNORECASE)
# El nombre viene detrás de la cita, tras coma: "Ley N.° 30096, Ley de Delitos Informáticos"
NOMBRE_RE = re.compile(
    r"^\s*,\s*((?:Nuevo\s+|Texto\s+[ÚU]nico\s+Ordenado\s+(?:de\s+la\s+)?)?"
    r"(?:Ley|C[oó]digo|Decreto|Reglamento|R[ée]gimen)[^.;:()]{4,90})")
# ...pero si sigue otra cita encadenada ("Código Penal y Decreto Legislativo N.° 957")
# el nombre se corta ahí, o se le pega el título de la norma siguiente.
CORTE_NOMBRE = re.compile(r"\s+(?:y|e)\s+(?:el\s+|la\s+)?(?:Decreto|Ley|Código|Texto)\b|,\s*(?:y\s+)?(?:el|la)\s+(?:Decreto|Ley)\b")

# Sólo estas tienen rango de ley, que es lo único que un decreto legislativo puede
# modificar. Los decretos supremos aparecen citados como contexto reglamentario y
# NO forman parte del universo de lo delegable.
RANGO_LEY = {"Ley", "Decreto Legislativo", "Decreto Ley", "Decreto de Urgencia"}

# CITAR NO ES QUERER MODIFICAR. La exposición de motivos nombra normas por dos
# razones muy distintas: porque se propone tocarlas, o porque describen el marco
# vigente ("conforme a la Ley N.° 27444..."). Contar todas como "lo que el
# Ejecutivo podría modificar" infla la cifra y la vuelve impublicable. Se mira la
# ventana de texto ANTERIOR a la cita —donde en castellano legal va el verbo que
# rige— y sólo cuenta como intención si aparece un verbo de modificación sin que
# medie un conector de mera referencia.
INTENCION_RE = re.compile(
    r"(?:modificar|modificaci[oó]n(?:es)?\s+(?:de|a|al)|derogar|derogaci[oó]n\s+(?:de|del)|"
    r"incorporar(?:se)?\s+(?:a|al|en)|adecuar|actualizar|sustituir|reformar|"
    r"precisar|ampliar|complementar)\b", re.IGNORECASE)
REFERENCIA_RE = re.compile(
    r"(?:conforme|de\s+acuerdo|seg[uú]n|establecid[oa]s?\s+en|previst[oa]s?\s+en|"
    r"regulad[oa]s?\s+(?:por|en)|dispuesto\s+por|en\s+el\s+marco\s+de|"
    r"contemplad[oa]s?\s+en|se[nñ]alad[oa]s?\s+en|al\s+amparo\s+de)\s*$", re.IGNORECASE)


# La exposición de motivos abre, por propuesta, una sección titulada "Medidas o
# contenidos normativos concretos que se pretenden aprobar, modificar o derogar".
# Ahí las normas van en viñetas, sin verbo propio — el verbo está en el título. Sin
# esta regla se pierden justamente las citas más operativas del documento.
SEC_MEDIDAS_RE = re.compile(r"Medidas\s+o\s+contenidos\s+normativos\s+concretos", re.IGNORECASE)
# El tramo se cierra con el PRÓXIMO encabezado de cualquier tipo (incluido otro
# "Medidas"), no sólo con "Objetivo": las fichas no siempre traen las cuatro
# secciones, y buscar sólo una hacía que un tramo se comiera varias propuestas —
# con tope de 6000 caracteres, los tramos cubrían el 88% del documento y la
# "intención" pasaba a ser universal, o sea inútil.
SEC_FIN_RE = re.compile(
    r"Objetivo\s+de\s+la\s+regulaci[oó]n|Medidas\s+o\s+contenidos|"
    r"An[aá]lisis\s+(?:costo|de\s+impacto)|Efecto\s+de\s+la\s+(?:vigencia|norma)|"
    r"Impacto\s+de\s+la\s+(?:vigencia|norma)|An[aá]lisis\s+costo[\s-]*beneficio",
    re.IGNORECASE)
TOPE_TRAMO = 2500


def tramos_medidas(texto: str) -> list[tuple[int, int]]:
    """Rangos [ini,fin) de las secciones de 'medidas concretas' del documento."""
    out = []
    for m in SEC_MEDIDAS_RE.finditer(texto):
        sig = SEC_FIN_RE.search(texto, m.end())
        fin = sig.start() if sig else len(texto)
        out.append((m.end(), min(fin, m.end() + TOPE_TRAMO)))
    return out


def hay_intencion(texto: str, ini: int, tramos: list[tuple[int, int]] | None = None) -> bool:
    """¿La cita que empieza en `ini` viene regida por un verbo de modificación?"""
    if tramos and any(a <= ini < b for a, b in tramos):
        return True
    ventana = texto[max(0, ini - 180):ini]
    ventana = ventana[max(ventana.rfind("."), ventana.rfind(";")) + 1:]
    if REFERENCIA_RE.search(ventana):
        return False
    return bool(INTENCION_RE.search(ventana))

CANON = {"ley": "Ley", "decreto legislativo": "Decreto Legislativo",
         "decreto ley": "Decreto Ley", "decreto supremo": "Decreto Supremo",
         "decreto de urgencia": "Decreto de Urgencia"}


# ALCANCE: ¿la delegación habilita tocar la norma entera o sólo una parte nombrada?
# Es la pregunta que de verdad importa —qué puede reescribir el Ejecutivo—, y en el
# articulado se resuelve mirando lo que antecede a la cita: "el artículo 6 de la
# Ley N.° 28587" acota; "modificar el Decreto Legislativo N.° 1095" no.
ALCANCE_RE = re.compile(
    r"((?:art[ií]culos?|numerales?)\s+[\dº°.,\s]{1,24}|"
    r"(?:[A-Za-zÁÉÍÓÚáéíóú]+\s+){0,3}[Dd]isposici[oó]n\s+[^,.;]{0,60}?)"
    r"\s+de(?:l)?\s+(?:la\s+)?$")

# Tres normas se citan sin denominación en ambos documentos. Los nombres vienen de
# fuente externa (El Peruano / plataforma normativa), no del pedido, y van marcados
# como tales para que no se confundan con lo transcrito del documento.
NOMBRES_EXTERNOS = {
    ("Decreto Legislativo", "1735"):
        "Decreto Legislativo que crea el Subsistema Especializado contra la Extorsión "
        "y sus Delitos Conexos (SEEDC) — publicado el 12 de febrero de 2026",
    ("Decreto Legislativo", "728"):
        "Ley de Fomento del Empleo — hoy vigente como TUO de la Ley de Formación y "
        "Promoción Laboral (DS 002-97-TR) y Ley de Productividad y Competitividad "
        "Laboral (DS 003-97-TR)",
    ("Decreto de Urgencia", "027-2009"):
        "Dicta medidas extraordinarias a favor de la actividad agraria y crea el "
        "Fondo AGROPERÚ — publicado el 23 de febrero de 2009",
}


def parte_citada(texto: str, ini: int) -> str | None:
    """Si la cita está acotada a un artículo o disposición, devuelve cuál."""
    m = ALCANCE_RE.search(texto[max(0, ini - 140):ini])
    return re.sub(r"\s+", " ", m.group(1)).strip(" ,;") if m else None


def limpia(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,;:")
    c = CORTE_NOMBRE.search(s)
    return s[:c.start()].strip(" ,;:") if c else s


def citas(texto: str, usar_tramos: bool = False):
    """Devuelve (tipo, numero, nombre_o_None, intencion_de_modificar) por cita."""
    tramos = tramos_medidas(texto) if usar_tramos else None
    for m in CITA_RE.finditer(texto):
        tipo = CANON.get(re.sub(r"\s+", " ", m.group(1)).lower(), m.group(1))
        num = re.sub(r"\s*[-–]\s*", "-", m.group(2))
        nm = NOMBRE_RE.match(texto[m.end():m.end() + 120])
        yield (tipo, num, (limpia(nm.group(1)) if nm else None),
               hay_intencion(texto, m.start(), tramos), parte_citada(texto, m.start()))


def main():
    d = json.load(open(PROPS, encoding="utf-8"))
    props = d["propuestas"]
    mats = {m["letra"]: m["titulo"] for m in d["materias"]}

    art = defaultdict(set)      # (tipo,num) → {ids de propuesta}
    partes = defaultdict(list)  # (tipo,num) → ["artículo 6", ...] en el articulado
    n_citas_art = Counter()     # (tipo,num) → nº de citas en el articulado
    nombres = defaultdict(Counter)
    intencion = set()           # claves con al menos una cita regida por verbo de modificación
    for p in props:
        for tipo, num, nom, quiere, parte in citas(p["texto"]):
            art[(tipo, num)].add(p["id"])
            n_citas_art[(tipo, num)] += 1
            if parte:
                partes[(tipo, num)].append(f'{parte} (propuesta {p["id"]})')
            if nom:
                nombres[(tipo, num)][nom] += 1
            # en el articulado toda cita es operativa: el numeral es el propio mandato
            intencion.add((tipo, num))

    # motivos, segmentado por materia con las mismas anclas que analiza_lexico
    from analiza_lexico import segmenta
    seg = segmenta()
    mot = defaultdict(set)      # (tipo,num) → {letras de materia}
    intencion_amplia = set(intencion)   # + las viñetas bajo "medidas concretas"
    for letra, txt in seg.items():
        for tipo, num, nom, quiere, _pt in citas(txt, usar_tramos=True):
            mot[(tipo, num)].add(letra)
            if nom:
                nombres[(tipo, num)][nom] += 1
            if quiere:
                intencion_amplia.add((tipo, num))
        for tipo, num, _nom, quiere, _p2 in citas(txt):   # sólo verbo rector, sin tramos
            if quiere:
                intencion.add((tipo, num))

    todas = sorted(set(art) | set(mot), key=lambda k: (k[0], k[1]))
    filas = []
    for clave in todas:
        tipo, num = clave
        if tipo not in RANGO_LEY:
            continue
        nom = nombres[clave].most_common(1)[0][0] if nombres[clave] else None
        externo = nom is None and clave in NOMBRES_EXTERNOS
        if externo:
            nom = NOMBRES_EXTERNOS[clave]
        # acotada sólo si TODAS sus citas del articulado nombran una parte
        pt = partes.get(clave, [])
        alcance = ("parcial" if pt and len(pt) == n_citas_art.get(clave, 0)
                   else "completa" if clave in art else None)
        filas.append({
            "tipo": tipo,
            "numero": num,
            "nombre": nom,
            "en_articulado": sorted(art.get(clave, [])),
            "materias_motivos": sorted(mot.get(clave, [])),
            "solo_en_motivos": clave not in art,
            "intencion_modificar": clave in intencion,
            "intencion_amplia": clave in intencion_amplia,
            "nombre_externo": externo,
            "alcance": alcance,
            "partes": pt,
        })

    en_art = [f for f in filas if not f["solo_en_motivos"]]
    solo_mot = [f for f in filas if f["solo_en_motivos"]]
    con_int = [f for f in filas if f["intencion_modificar"]]
    mot_int = [f for f in solo_mot if f["intencion_modificar"]]

    n_ds = len({k for k in set(art) | set(mot) if k[0] not in RANGO_LEY})
    print(f"NORMAS CON RANGO DE LEY IDENTIFICADAS: {len(filas)}")
    print(f"  (excluidos {n_ds} decretos supremos citados como contexto reglamentario)")
    print(f"  en el articulado (lo que el Congreso vota): {len(en_art)}")
    print(f"  sólo en la exposición de motivos:           {len(solo_mot)}")
    print()
    amplia = [f for f in filas if f["intencion_amplia"]]
    print("INTENCIÓN DE MODIFICAR — rango, no cifra única:")
    print(f"  piso  {len(con_int):>3}  regidas por un verbo de modificación (validado a mano, 8/8)")
    print(f"  techo {len(filas):>3}  toda norma con rango de ley nombrada en cualquiera de los dos textos")
    print(f"  (heurística por secciones de 'medidas concretas': {len(amplia)}, provisional — sus")
    print( "   tramos topan en el límite fijo, así que el parámetro manda sobre el dato;")
    print( "   la cifra exacta sale recién con la segmentación por propuesta.)")
    print(f"\n  de las {len(con_int)} del piso, {len(mot_int)} aparecen SÓLO en la exposición de motivos:")
    print( "  el Ejecutivo declara querer tocarlas pero no están en el texto que el Congreso vota.")
    print()
    for tipo, c in Counter(f["tipo"] for f in filas).most_common():
        ea = sum(1 for f in en_art if f["tipo"] == tipo)
        print(f"  {c:>4}  {tipo:<22} ({ea} en articulado)")

    comp = [f for f in en_art if f["alcance"] == "completa"]
    parc = [f for f in en_art if f["alcance"] == "parcial"]
    print(f"\nALCANCE de las {len(en_art)} del articulado:")
    print(f"  {len(comp):>3}  se citan enteras — la delegación habilita reescribir toda la norma")
    print(f"  {len(parc):>3}  acotadas a un artículo o disposición nombrada")
    for f in parc:
        print(f"        {f['tipo']} {f['numero']}: {'; '.join(f['partes'])}")

    print("\n── Normas nombradas en el articulado ──")
    for f in sorted(en_art, key=lambda x: (x["tipo"], x["numero"])):
        nom = f["nombre"] or "—"
        print(f"  {f['tipo']} {f['numero']:<6} {nom[:62]:<64} {','.join(f['en_articulado'])}")

    print("\n── Las más citadas sólo en motivos (top 20 por materias que la tocan) ──")
    for f in sorted(solo_mot, key=lambda x: -len(x["materias_motivos"]))[:20]:
        nom = f["nombre"] or "—"
        print(f"  [{','.join(f['materias_motivos'])}] {f['tipo']} {f['numero']:<6} {nom[:60]}")

    json.dump({
        "resumen": {
            "n_total": len(filas),
            "n_en_articulado": len(en_art),
            "n_solo_motivos": len(solo_mot),
            "por_tipo": dict(Counter(f["tipo"] for f in filas)),
        },
        "materias": mats,
        "normas": filas,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
