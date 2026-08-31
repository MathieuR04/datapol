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

# Sólo estas tienen rango de ley, que es el rango de un decreto legislativo y por
# tanto el universo que la delegación pone en juego (art. 104 de la Constitución).
#
# Los decretos supremos quedan fuera, pero NO porque un decreto legislativo no
# pueda tocarlos —sí puede, es norma de rango superior—: quedan fuera porque el
# Ejecutivo ya los modifica cuando quiere por su potestad reglamentaria ordinaria
# (art. 118 inc. 8), con delegación o sin ella. Contarlos le atribuiría al pedido
# un poder que el gobierno tiene igual. Se citan como marco reglamentario vigente,
# y de hecho ninguno aparece en el articulado: los 36 salen de la exposición de
# motivos.
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

# DENOMINACIONES DE LAS 42 DEL ARTICULADO — transcritas a mano, no por patrón.
#
# Extraerlas con una expresión regular fallaba de dos maneras a la vez y las dos
# se veían en la tabla publicada: el corte por longitud partía nombres largos a
# media palabra («…en cooperativas agra»), y como el nombre de la norma y la
# cláusula de finalidad de la propuesta van seguidos sin puntuación que los
# separe, el patrón se tragaba la segunda («Ley General de Inspección del Trabajo
# con la finalidad de fortalecer de manera expresa las competencias…»). No hay
# regla de puntuación que distinga una de otra, así que son 42 y se revisan a
# mano; el patrón queda sólo como respaldo para lo que aparezca a futuro.
DENOMINACIONES: dict[tuple[str, str], str] = {
    ("Ley", "26702"): "Ley General del Sistema Financiero y del Sistema de Seguros y Orgánica de la Superintendencia de Banca y Seguros",
    ("Ley", "27287"): "Ley de Títulos Valores",
    ("Ley", "27829"): "Ley que crea el Bono Familiar Habitacional (BFH)",
    ("Ley", "28587"): "Ley Complementaria a la Ley de Protección al Consumidor en Materia de Servicios Financieros",
    ("Ley", "28806"): "Ley General de Inspección del Trabajo",
    ("Ley", "28832"): "Ley para asegurar el desarrollo eficiente de la Generación Eléctrica",
    ("Ley", "29148"): "Ley que establece la implementación y el funcionamiento del Fondo de Garantía para el Campo y del Seguro Agropecuario",
    ("Ley", "29230"): "Ley que impulsa la inversión pública regional y local con participación del sector privado",
    ("Ley", "29338"): "Ley de Recursos Hídricos",
    ("Ley", "30096"): "Ley de Delitos Informáticos",
    ("Ley", "30230"): "Ley que establece medidas tributarias, simplificación de procedimientos y permisos para la promoción y dinamización de la inversión en el país",
    ("Ley", "30424"): "Ley que regula la responsabilidad administrativa de las personas jurídicas por el delito de cohecho activo transnacional",
    ("Ley", "30852"): "Ley que aprueba la exoneración de requisitos a familias damnificadas con viviendas colapsadas o inhabitables con el Bono Familiar Habitacional y con el Bono de Protección de Viviendas Vulnerables a los Riesgos Sísmicos",
    ("Ley", "31071"): "Ley de compras estatales de alimentos de origen de la agricultura familiar",
    ("Ley", "31143"): "Ley que protege de la usura a los consumidores de los servicios financieros",
    ("Ley", "31145"): "Ley de saneamiento físico-legal y formalización de predios rurales a cargo de los Gobiernos Regionales",
    ("Ley", "31335"): "Ley de perfeccionamiento de la asociatividad de los productores agrarios en cooperativas agrarias",
    ("Ley", "31410"): "Ley que crea el Servicio Civil de Graduandos para el Sector Agrario (SECIGRA Agrario)",
    ("Ley", "31526"): "Ley que crea el Bono de Arrendamiento de Vivienda para Emergencias",
    ("Ley", "31872"): "Ley que modifica la Ley 28890, Ley que crea Sierra y Selva Exportadora",
    ("Ley", "32065"): "Ley que establece medidas para asegurar el acceso universal al agua potable",
    ("Ley", "32332"): "Ley que implementa la plataforma Denuncia Digital para el registro de denuncias digitales por delitos contra el patrimonio",
    ("Ley", "32490"): "Ley que establece medidas extraordinarias contra los delitos de extorsión y sicariato en las empresas de transporte público y transporte de mercancías",
    ("Ley", "32645"): "Ley que crea el Colegio Profesional de Artistas del Perú (CPAP)",
    ("Decreto Legislativo", "635"): "Código Penal",
    ("Decreto Legislativo", "654"): "Código de Ejecución Penal",
    ("Decreto Legislativo", "728"): "Dictan Ley de Fomento del Empleo",
    ("Decreto Legislativo", "957"): "Nuevo Código Procesal Penal",
    ("Decreto Legislativo", "1060"): "Decreto Legislativo que regula el Sistema Nacional de Innovación Agraria",
    ("Decreto Legislativo", "1094"): "Código Penal Militar Policial",
    ("Decreto Legislativo", "1095"): "Decreto Legislativo que establece reglas de empleo y uso de la fuerza por parte de las Fuerzas Armadas en el territorio nacional",
    ("Decreto Legislativo", "1141"): "Decreto Legislativo de Fortalecimiento y Modernización del Sistema de Inteligencia Nacional (SINA) y de la Dirección Nacional de Inteligencia (DINI)",
    ("Decreto Legislativo", "1182"): "Decreto Legislativo que regula el uso de los datos derivados de las telecomunicaciones para la identificación, localización y geolocalización de equipos de comunicación",
    ("Decreto Legislativo", "1192"): "Decreto Legislativo que aprueba la Ley Marco de Adquisición y Expropiación de inmuebles, transferencia de inmuebles de propiedad del Estado y liberación de interferencias para la ejecución de obras de infraestructura",
    ("Decreto Legislativo", "1280"): "Decreto Legislativo que aprueba la Ley del Servicio Universal de Agua Potable y Saneamiento",
    ("Decreto Legislativo", "1338"): "Decreto Legislativo que crea el Registro Nacional de Equipos Terminales Móviles para la Seguridad",
    ("Decreto Legislativo", "1400"): "Decreto Legislativo que aprueba el Régimen de Garantía Mobiliaria",
    ("Decreto Legislativo", "1409"): "Decreto Legislativo que promociona la formalización y dinamización de la micro, pequeña y mediana empresa mediante el régimen societario alternativo denominado Sociedad por Acciones Cerrada Simplificada",
    ("Decreto Legislativo", "1688"): "Decreto Legislativo que regula obligaciones y sanciones administrativas para las empresas operadoras de servicios públicos de telecomunicaciones en relación con las comunicaciones ilegales en establecimientos penitenciarios y centros juveniles",
    ("Decreto Ley", "25844"): "Ley de Concesiones Eléctricas",
    ("Decreto de Urgencia", "027-2009"): "Dictan medidas extraordinarias a favor de las actividades agrarias",
}

# La única de las 42 que el expediente cita por número y sin denominación en los
# dos documentos. El nombre viene de la norma publicada, no del pedido, y por eso
# va marcado aparte en la tabla.
NOMBRES_EXTERNOS = {
    ("Decreto Legislativo", "1735"):
        "Decreto Legislativo que crea el Subsistema Especializado contra la Extorsión "
        "y sus Delitos Conexos (SEEDC), publicado el 12 de febrero de 2026",
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
        # La lista revisada a mano manda sobre lo que saque el patrón.
        externo = clave in NOMBRES_EXTERNOS
        nom = (DENOMINACIONES.get(clave) or NOMBRES_EXTERNOS.get(clave)
               or (nombres[clave].most_common(1)[0][0] if nombres[clave] else None))
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
    faltan = [f"{f['tipo']} {f['numero']}" for f in en_art if not f["nombre"]]
    if faltan:
        print(f"\n  ⚠ sin denominación revisada: {faltan}")
    else:
        print(f"\n  denominaciones: {len(en_art)}/{len(en_art)} revisadas a mano")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
