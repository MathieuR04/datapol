#!/usr/bin/env python3
"""
build_organizaciones.py — mapa de organizaciones políticas ERM 2026 y su
agrupación en "categorías exteriores" (partido nacional + sus alianzas regionales).

EL PROBLEMA
-----------
Un mismo partido nacional compite bajo varios `organizacion_id` distintos porque
arma alianzas regionales con movimientos locales. Contarlos por separado infla el
número de organizaciones y esconde el alcance real de cada marca:

  ALIANZA PARA EL PROGRESO      (1257) 1,189 listas   ┐
  APP - LA CHOLITA              (3032)   119 listas   ├─ una sola marca: 1,415
  APP - TRABAJA AYACUCHO        (3031)   107 listas   ┘

A veces la alianza regional ni siquiera cambia de nombre: PARTIDO DEMOCRATICO
SOMOS PERU existe como partido (14, en 24 departamentos) *y* como alianza
electoral (3045, sólo Puno) — son complementarios, cero solapamiento.

EL MÉTODO — componentes conexas
-------------------------------
No se agrupa por parecido de nombre (frágil: "ALIANZA REGIONAL POR EL PERU" no
se parece a "PARTIDO UNIDAD Y PAZ", y sin embargo son la misma órbita). Se
construye un grafo bipartito:

    organización que compite  ←→  partido/movimiento que la integra

y cada **componente conexa** es una categoría exterior. La composición de las
alianzas es un hecho registral, no una inferencia: sale de la nota del JNE
sobre las 23 alianzas que solicitaron inscripción para las ERM 2026
(gob.pe/institucion/jne/noticias/1362445), transcrita en ALIANZAS abajo.

Un partido que integra una alianza cae SIEMPRE en el grupo de esa alianza
(decisión editorial), incluso si además presenta listas propias — por eso
PARTIDO POR EL ENTENDIMIENTO (3007) queda en la órbita de Renovación Popular
y PARTIDO UNIDAD Y PAZ (2944) en la de Alianza Regional por el Perú.

El nombre del grupo lo pone la organización con más listas del grupo (el "ancla"),
más el sufijo " + Aliados" sólo si el grupo tiene más de una organización.

NOTA — sólo se mapea lo que tiene listas. De las 23 alianzas solicitadas, 10
presentaron listas en ERM 2026; las otras 13 no aparecen en este archivo.

Salidas:
  data/organizaciones_erm2026.csv   — una fila por organizacion_id, con su grupo
  data/grupos_erm2026.csv           — una fila por grupo (agregados)
  data/grupos_erm2026.json          — lookup {organizacion_id → grupo} para reusar

PARA LA NOCHE ELECTORAL
-----------------------
El JSON existe para esto: cuando lleguen resultados por organización, sumarlos
por marca es `grupo_de(id)` y agrupar. No hay que reconstruir nada ni tener a
mano el CSV de 34 MB de candidatos:

    import sys; sys.path.append("scripts")
    from build_organizaciones import cargar_mapa, grupo_de
    mapa = cargar_mapa()
    votos_por_grupo[grupo_de(r["idOrganizacionPolitica"], mapa)] += r["votos"]

`grupo_de()` devuelve el nombre de la organización tal cual si el id no está en
el mapa, así que una organización nueva nunca rompe el conteo: aparece sola.
Los ids son los de `idOrganizacionPolitica` del JNE — los mismos que usa el
módulo AutoridadesProclamadas (§9 de docs/api-notes.md), o sea que el mapeo
sirve igual para candidatos que para autoridades electas.

MANTENIMIENTO: si un `--update` trae una alianza nueva con listas, hay que
agregar su composición a ALIANZAS a mano (sale de la nota del JNE); si no, esa
alianza queda como categoría propia en vez de sumarse a la marca que le toca.

Run: python3 scripts/build_organizaciones.py
     (leer data/erm2026_candidatos.csv; correr después de un --update)
"""
from __future__ import annotations
import json
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CAND = os.path.join(ROOT, "data", "erm2026_candidatos.csv")
OUT_ORGS = os.path.join(ROOT, "data", "organizaciones_erm2026.csv")
OUT_GRUPOS = os.path.join(ROOT, "data", "grupos_erm2026.csv")
OUT_JSON = os.path.join(ROOT, "data", "grupos_erm2026.json")

# ── Composición de las alianzas electorales que SÍ presentaron listas ──────────
# Fuente: JNE, "23 alianzas electorales solicitaron su inscripción ante el JNE
# para participar en las ERM 2026". Los nombres van en la forma canónica usada
# abajo en CANONICO; los integrantes que no compiten por su cuenta igual se
# listan (documentan la alianza y pueden enlazar grupos en el futuro).
ALIANZAS: dict[str, list[str]] = {
    "3028": ["NUEVO PERU POR EL BUEN VIVIR", "UP - UNIDAD POPULAR",
             "POPULAR VOCES DEL PUEBLO", "ADELANTE PUEBLO UNIDO",
             "RESURGIMIENTO UNIDO NACIONAL - RUNA"],
    "3031": ["ALIANZA PARA EL PROGRESO", "MOVIMIENTO REGIONAL TRABAJA AYACUCHO"],
    "3032": ["ALIANZA PARA EL PROGRESO", "MOVIMIENTO REGIONAL UNIDAD CIVICA LIMA"],
    "3033": ["PARTIDO DE LOS TRABAJADORES Y EMPRENDEDORES PTE PERU",
             "COMUNIDAD POLITICA INKA PERU"],
    "3034": ["RENOVACION POPULAR", "MOVIMIENTO REGIONAL PATRIA JOVEN"],
    "3036": ["FUERZA MODERNA", "PERUANOS UNIDOS: ¡SOMOS LIBRES!",
             "PARTIDO UNIDAD Y PAZ"],
    "3038": ["JUNTOS POR EL PERU",
             "MOVIMIENTO REGIONAL ACCION SOCIAL POR LA INTEGRACION - ASI"],
    "3040": ["RENOVACION POPULAR",
             "PARTIDO POR EL ENTENDIMIENTO, RECUPERACION Y LA UNIFICACION DEL PERU"],
    "3045": ["PARTIDO DEMOCRATICO SOMOS PERU",
             "MOVIMIENTO REGIONAL SENTIMIENTO AMAZONENSE REGIONAL"],
    "3046": ["COOPERACION POPULAR", "VERDAD Y HONRADEZ"],
}

# Partidos que compiten por su cuenta Y figuran como integrantes de alguna
# alianza de arriba: hay que declarar con qué nombre canónico enlazan.
# (Sólo estos cinco; el resto de organizaciones enlaza consigo misma.)
CANONICO: dict[str, str] = {
    "1257": "ALIANZA PARA EL PROGRESO",
    "1264": "JUNTOS POR EL PERU",
    "14":   "PARTIDO DEMOCRATICO SOMOS PERU",
    "2944": "PARTIDO UNIDAD Y PAZ",
    "3007": "PARTIDO POR EL ENTENDIMIENTO, RECUPERACION Y LA UNIFICACION DEL PERU",
}

# Etiqueta curada donde el ancla no nombra bien al grupo. Renovación Popular no
# tiene organización propia en ERM 2026 (compite sólo vía dos alianzas), así que
# el ancla se llamaría "RENOVACION POPULAR PERU" — el nombre de una de ellas.
ETIQUETA_GRUPO: dict[str, str] = {
    "3040": "RENOVACION POPULAR",
}

TIPO_TIER = {"4": "reg", "5": "prov", "6": "dist"}


class UnionFind:
    def __init__(self):
        self.padre: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.padre[rb] = ra


def asignar(orgs: dict[str, dict]) -> dict[str, dict]:
    """Asigna cada organización a su categoría exterior (componente conexa).

    Entrada: {organizacion_id: {"organizacion": nombre, "listas": n}}
    Salida:  {organizacion_id: {"grupo": etiqueta, "grupo_id": id del ancla,
                                "grupo_n_orgs": n, "es_ancla": bool}}

    Función pura y sin dependencias — la comparten build_organizaciones.main()
    (que escribe los CSV) y build_finder_json.build_partidos() (que arma el JSON
    del artículo), para que la agrupación no pueda divergir entre los dos.
    """
    uf = UnionFind()
    for oid in orgs:
        uf.find(f"org:{oid}")
        for miembro in ALIANZAS.get(oid, [CANONICO.get(oid, f"solo:{oid}")]):
            uf.union(f"org:{oid}", f"p:{miembro}")

    comp: dict[str, list[str]] = {}
    for oid in orgs:
        comp.setdefault(uf.find(f"org:{oid}"), []).append(oid)

    out: dict[str, dict] = {}
    for miembros in comp.values():
        # ancla = la organización con más listas (desempate por nombre, estable)
        ancla = min(miembros, key=lambda o: (-orgs[o]["listas"], orgs[o]["organizacion"]))
        base = ETIQUETA_GRUPO.get(ancla, orgs[ancla]["organizacion"])
        etiqueta = f"{base} + ALIADOS" if len(miembros) > 1 else base
        for oid in miembros:
            out[oid] = {"grupo": etiqueta, "grupo_id": ancla,
                        "grupo_n_orgs": len(miembros), "es_ancla": oid == ancla}
    return out


def cargar_mapa(path: str = OUT_JSON) -> dict:
    """Carga el lookup organizacion_id → grupo. Sin pandas y sin leer el CSV de
    candidatos: pensado para scripts de resultados en noche electoral."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def grupo_de(organizacion_id, mapa: dict, nombre: str | None = None) -> str:
    """Categoría exterior de una organización. Si el id no está en el mapa
    (organización nueva, o resultados de otro proceso) devuelve `nombre` — o el
    id — para que la organización aparezca sola en vez de romper el conteo."""
    o = mapa["orgs"].get(str(organizacion_id))
    return o["grupo"] if o else (nombre or str(organizacion_id))


def main() -> None:
    d = pd.read_csv(CAND, dtype=str)
    d["circ"] = d["tipo_eleccion_id"] + "|" + d["ubigeo"]

    # ── agregados por organización ────────────────────────────────────────────
    orgs = (d.groupby(["organizacion_id", "organizacion", "tipo_organizacion"])
              .agg(listas=("solicitud_lista_id", "nunique"),
                   candidatos=("candidato_id", "size"))
              .reset_index())

    tiers = (d.groupby(["organizacion_id", "tipo_eleccion_id"]).circ.nunique()
               .unstack(fill_value=0).rename(columns=TIPO_TIER))
    for c in ("reg", "prov", "dist"):
        if c not in tiers:
            tiers[c] = 0
    orgs = orgs.merge(tiers[["reg", "prov", "dist"]], left_on="organizacion_id",
                      right_index=True, how="left")

    deps = (d.groupby("organizacion_id").departamento
              .apply(lambda s: " | ".join(sorted(s.dropna().unique()))))
    orgs["departamentos"] = orgs.organizacion_id.map(deps)
    orgs["n_departamentos"] = orgs.departamentos.str.count(r"\|").add(1).fillna(0).astype(int)

    # ── componentes conexas organización ←→ integrante (función compartida) ───
    g = asignar({r.organizacion_id: {"organizacion": r.organizacion,
                                     "listas": int(r.listas)}
                 for r in orgs.itertuples()})
    for campo in ("grupo", "grupo_id", "grupo_n_orgs", "es_ancla"):
        orgs[campo] = orgs.organizacion_id.map(lambda o, c=campo: g[o][c])
    orgs["integrantes"] = orgs.organizacion_id.map(
        lambda o: " | ".join(ALIANZAS[o]) if o in ALIANZAS else "")

    cols = ["organizacion_id", "organizacion", "tipo_organizacion",
            "grupo_id", "grupo", "grupo_n_orgs", "es_ancla",
            "listas", "candidatos", "reg", "prov", "dist",
            "n_departamentos", "departamentos", "integrantes"]
    orgs = orgs[cols].sort_values(["grupo", "listas"], ascending=[True, False])
    orgs.to_csv(OUT_ORGS, index=False)

    # ── agregados por grupo ───────────────────────────────────────────────────
    # Un partido y sus alianzas nunca compiten en la misma circunscripción (la
    # ley lo impide), así que los totales del grupo son sumas simples; igual se
    # cuenta sobre circunscripciones únicas para que el archivo sea a prueba de
    # excepciones.
    g2o = dict(zip(orgs.organizacion_id, orgs.grupo))
    d["grupo"] = d.organizacion_id.map(g2o)
    gr = (d.groupby("grupo")
            .agg(listas=("solicitud_lista_id", "nunique"),
                 candidatos=("candidato_id", "size"),
                 circunscripciones=("circ", "nunique"))
            .reset_index())
    gt = (d.groupby(["grupo", "tipo_eleccion_id"]).circ.nunique()
            .unstack(fill_value=0).rename(columns=TIPO_TIER))
    for c in ("reg", "prov", "dist"):
        if c not in gt:
            gt[c] = 0
    gr = gr.merge(gt[["reg", "prov", "dist"]], on="grupo", how="left")
    gr = gr.merge(orgs.groupby("grupo").agg(
        n_orgs=("organizacion_id", "nunique"),
        organizaciones=("organizacion", lambda s: " | ".join(s))), on="grupo")
    gr = gr.sort_values("listas", ascending=False)
    gr.to_csv(OUT_GRUPOS, index=False)

    # ── lookup reusable (noche electoral): id → grupo, sin depender del CSV ───
    lookup = {
        "generado": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "proceso": "ERM 2026",
        "nota": ("organizacion_id es idOrganizacionPolitica del JNE. Un id "
                 "ausente significa organización no vista en ERM 2026: tratarla "
                 "como su propia categoría (ver grupo_de())."),
        "orgs": {r.organizacion_id: {"organizacion": r.organizacion,
                                     "tipo_organizacion": r.tipo_organizacion,
                                     "grupo": r.grupo, "grupo_id": r.grupo_id}
                 for r in orgs.itertuples()},
        "grupos": {g: sorted(s.organizacion_id)
                   for g, s in orgs.groupby("grupo")},
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, indent=1, sort_keys=False)

    # ── reporte ───────────────────────────────────────────────────────────────
    multi = gr[gr.n_orgs > 1]
    print(f"organizaciones: {len(orgs)}  →  grupos: {len(gr)}  "
          f"({len(multi)} con más de una organización)")
    print(f"  wrote {OUT_ORGS}")
    print(f"  wrote {OUT_GRUPOS}")
    print(f"  wrote {OUT_JSON}\n")
    print("Grupos con más de una organización:")
    for _, r in multi.iterrows():
        print(f"  {r.grupo:42s} {r.listas:5,d} listas  ({r.n_orgs} orgs)")
        for _, o in orgs[orgs.grupo == r.grupo].iterrows():
            marca = "*" if o.es_ancla else " "
            print(f"    {marca} {o.organizacion_id:>5s} {o.organizacion[:52]:52s} "
                  f"{o.listas:5,d}")
    solap = gr.listas.sum() - gr.circunscripciones.sum()
    print(f"\nsolapamiento intra-grupo (listas - circunscripciones únicas): {solap}")


if __name__ == "__main__":
    main()
