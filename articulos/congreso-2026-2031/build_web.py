#!/usr/bin/env python3
"""Empaqueta votos + modelo en el JSON estático que lee el tablero.

Salida: web/<camara>.json (una por cámara), pensado para fetch directo desde
index.html (sitio estático, sin backend):

  meta        generado, conteos, diagnósticos del modelo, línea oficialismo/oposición
  miembros    [{id, nombre, grupo, bloque, foto, perfil, distrito, x, y, dist,
                asistencia, lealtad, con_oficialismo, cruzado, rank_bisagra}]
  partidos    [{grupo, nombre, bloque, n, x, y, sx, sy, lealtad}]
  votaciones  [{id, fecha, hora, asunto, pdf, disputada, validacion,
                total{SI,NO,…}, grupos{FP:{SI,NO,…}}, v}]

`v` es el voto de cada miembro como un string con un carácter por miembro, en
el orden de `miembros` (S sí, N no, A abstención, a ausente, L licencia,
R sin respuesta, P preside, · sin dato) — ~130 bytes por votación en vez de
130 objetos.

Run: python3 build_web.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import OFICIALISMO, OPOSICION
from parser import (PageResult, constancia_corrections, es_prosa, match_constancia)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
WEB = HERE / "web"

CODIGO = {"SI": "S", "NO": "N", "ABS": "A", "AUS": "a", "LIC": "L", "SUS": "L",
          "SINRES": "R", "PRESIDENTE": "P"}


def bloque(g: str | None) -> str:
    return "oficialismo" if g in OFICIALISMO else "oposicion" if g in OPOSICION else "otro"


def fecha_iso(d: str) -> str:
    try:
        return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return d


def constancias(texto: str, miembros: list[dict]) -> list[dict]:
    if not texto:
        return []
    p = PageResult(page=0)
    p.constancia_text = texto
    out, vistos = [], set()
    for nombre, voto in constancia_corrections(p):
        i, _ = match_constancia(nombre, miembros)
        if i is not None and miembros[i]["id"] not in vistos:
            vistos.add(miembros[i]["id"])
            out.append({"id": miembros[i]["id"], "voto": CODIGO[voto]})
    return out


def build(camara: str, votos: pd.DataFrame, paginas: pd.DataFrame, roster: list[dict]) -> dict:
    modelo = json.loads((DATA / f"modelo_{camara}.json").read_text(encoding="utf-8"))
    mm = {m["id"]: m for m in modelo["miembros"]}
    rs = [m for m in roster if m["camara"] == camara]
    # orden estable: bloque, grupo, apellidos
    rs.sort(key=lambda m: (bloque(m["grupo"]), m["grupo"] or "", m["apellidos"]))
    idx = {m["id"]: i for i, m in enumerate(rs)}

    miembros = []
    for m in rs:
        e = mm.get(m["id"], {})
        miembros.append({
            "id": m["id"], "nombre": m["nombre"], "grupo": m["grupo"],
            "bloque": bloque(m["grupo"]), "foto": m.get("foto"), "perfil": m["perfil"],
            "distrito": m["distrito"], "condicion": m["condicion"],
            **{k: e.get(k) for k in ("x", "y", "dist_linea", "asistencia", "lealtad",
                                     "con_oficialismo", "cruzado", "rank_bisagra",
                                     "n_emitidos", "n_registrado")},
        })

    nombres = {m["grupo"]: m["grupo_nombre"] for m in rs if m["grupo"]}
    partidos = [{**p, "nombre": nombres.get(p["grupo"], p["grupo"]),
                 "bloque": bloque(p["grupo"])} for p in modelo.get("partidos", [])]

    d = votos[votos.camara == camara]
    pg = paginas[(paginas.camara == camara) & (paginas.tipo == "VOTACION")]
    disputadas = set(modelo.get("votaciones_modelo", []))
    vots = []
    for r in pg.itertuples():
        vid = f"{r.pdf}:p{int(r.pagina):03d}"
        g = d[d.vote_id == vid]
        if g.empty:
            continue
        chars = ["·"] * len(rs)
        for x in g.itertuples():
            if x.miembro_id in idx:
                chars[idx[x.miembro_id]] = CODIGO.get(x.voto, "·")
        por_grupo = {k: sub.voto.value_counts().to_dict() for k, sub in g.groupby("grupo")}
        vots.append({
            "id": vid, "fecha": fecha_iso(r.fecha) or r.fecha_sesion, "hora": r.hora,
            "asunto": r.asunto, "pdf": f"{r.url}#page={int(r.pagina)}",
            "disputada": vid in disputadas, "validacion": r.validacion,
            # Sólo lo que importa de la constancia: quién y qué voto dejó
            # registrado, ya cruzado con el padrón (nunca el párrafo OCR).
            "constancias": constancias(r.constancia, rs),
            "total": g.voto.value_counts().to_dict(), "grupos": por_grupo,
            "v": "".join(chars),
        })
    vots.sort(key=lambda v: (v["fecha"], v["hora"], v["id"]))

    meta = {k: modelo.get(k) for k in (
        "n_votaciones", "n_disputadas", "n_miembros_modelo", "min_votos_miembro",
        "lambda2", "lambda3", "clasif_1d", "clasif_2d", "ganancia_dim2", "pre_1d",
        "robustez_mds", "robustez_pca", "linea")}
    meta.update({
        "camara": camara, "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "oficialismo": sorted(OFICIALISMO), "oposicion": sorted(OPOSICION),
        "desde": vots[0]["fecha"] if vots else None, "hasta": vots[-1]["fecha"] if vots else None,
        "validadas": sum(v["validacion"] == "ok" for v in vots),
    })
    return {"meta": meta, "miembros": miembros, "partidos": partidos, "votaciones": vots}


def revisar(paginas: pd.DataFrame) -> pd.DataFrame:
    """Lista interna (no se publica en la página) de votaciones a rehacer a mano.

    Hoy: actas con una observación al pie — p. ej. 13/08/2026 en Diputados,
    «se anunciaron 115 votos a favor, habiéndose registrado 120» —, donde el
    resultado oficial puede no coincidir con el registro que usa el tablero; y
    páginas que no cuadraron con el cuadro impreso."""
    v = paginas[paginas.tipo == "VOTACION"].copy()
    v["motivo"] = ""
    v.loc[v.nota.map(es_prosa), "motivo"] = "observación en el acta"
    v.loc[v.validacion != "ok", "motivo"] = (
        v.loc[v.validacion != "ok", "motivo"].str.cat(["no cuadra con el cuadro impreso"]
                                                     * (v.validacion != "ok").sum(), sep="; ")
        .str.strip("; "))
    out = v[v.motivo != ""].assign(pdf_url=lambda d: d.url + "#page=" + d.pagina.astype(str))
    return out[["camara", "fecha", "hora", "pdf", "pagina", "asunto", "motivo", "nota", "pdf_url"]]


def run(camaras=("diputados", "senado")) -> None:
    votos = pd.read_csv(DATA / "votos.csv", keep_default_na=False, dtype=str)
    paginas = pd.read_csv(DATA / "paginas.csv", keep_default_na=False, dtype=str)
    roster = json.loads((DATA / "roster.json").read_text(encoding="utf-8"))
    WEB.mkdir(exist_ok=True)
    rv = revisar(paginas)
    rv.to_csv(DATA / "revisar.csv", index=False)
    if len(rv):
        print(f"⚠ {len(rv)} votaciones para revisar a mano → data/revisar.csv")
    for cam in camaras:
        out = build(cam, votos, paginas, roster)
        p = WEB / f"{cam}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {p.relative_to(HERE)} ({p.stat().st_size/1e3:.0f} KB, "
              f"{len(out['votaciones'])} votaciones, {len(out['miembros'])} miembros)")


if __name__ == "__main__":
    run()
