#!/usr/bin/env python3
"""Facciones de AN, PBG y PCO en las tres leyes del presupuesto 2027 (Pleno del
Congreso, 20/11/2026), con las dos cámaras juntas.

Fuente: el tablero de votaciones (../congreso-2026-2031/data/votos.csv, columna
`conjunta`) y su padrón (roster.json, fotos). Cada parlamentario va al bando de
su voto en la Ley de Presupuesto (la votación final); su voto en Endeudamiento y
Equilibrio Financiero se muestra como trayectoria.

Salida: data/facciones.json, incrustado también en index.html
Run: python3 scripts/build.py
"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
TAB = HERE.parent / "congreso-2026-2031" / "data"
PARTIDOS = ["FP", "RP", "JP", "AN", "PBG", "PCO"]
LEYES = [("endeudamiento", "ENDEUDAMIENTO", "Endeudamiento"),
         ("equilibrio", "EQUILIBRIO", "Equilibrio Financiero"),
         ("presupuesto", "LEY DE PRESUPUESTO DEL SECTOR", "Presupuesto")]
VOTO = {"SI": "SI", "NO": "NO", "ABS": "ABS"}   # el resto: no votó

# Nombres de trabajo de cada bando (por partido y voto en la Ley de Presupuesto).
# La prensa no bautiza estas facciones; los nombres se apoyan en lo reportado
# (ver la revisión de fuentes en el artículo).
BANDOS = {
    # Cada bando lleva el nombre de su integrante más visible (vocero, fundador o
    # quien explicó el voto en público).
    "AN": {"ABS": "Ala López Chau", "NO": "Ala Huilca"},
    "PBG": {"SI": "Ala Figallo", "NO": "Ala Alayza"},
    "PCO": {"SI": "Ala Barragán", "ABS": "Ala Agripina Flores"},
}
NOTAS = {
    "gavidia-rodriguez-jorge-octavio": "Anunció su renuncia al partido el 26/10; sigue en el padrón oficial del PBG.",
}


def main():
    v = pd.read_csv(TAB / "votos.csv", dtype=str, keep_default_na=False)
    roster = json.loads((TAB / "roster.json").read_text(encoding="utf-8"))
    j = v[v.conjunta != ""]
    dips = j[j.camara == "diputados"].drop_duplicates("conjunta")
    ley_de = {}
    votaciones = []
    for key, pat, nombre in LEYES:
        c = dips[dips.asunto.str.contains(pat)]
        assert len(c) == 1, (key, len(c))
        cid = c.conjunta.iloc[0]
        ley_de[cid] = key
        tot = {}
        for cam, g in j[j.conjunta == cid].groupby("camara"):
            vc = g.voto.value_counts()
            tot[cam] = {k: int(vc.get(k, 0)) for k in ("SI", "NO", "ABS")}
        prov = "PROVISIONAL" in cid
        votaciones.append({"key": key, "nombre": nombre, "fecha": c.fecha.iloc[0],
                           "asunto": c.asunto.iloc[0], "totales": tot, "provisional": prov})
    sub = j[j.conjunta.isin(ley_de)]
    votos = {(r.miembro_id, ley_de[r.conjunta]): r.voto for r in sub.itertuples()}

    miembros = []
    for m in roster:
        # sin filtrar por «condicion»: la API trae a García Huby como «electo» aunque vota
        if m["grupo"] not in PARTIDOS:
            continue
        tray = {k: votos.get((m["id"], k), "") for k, _, _ in LEYES}
        final = VOTO.get(tray["presupuesto"], "NV")
        miembros.append({
            "id": m["id"], "slug": m["slug"], "nombre": m["nombre"],
            "apellidos": m["apellidos"], "camara": m["camara"], "grupo": m["grupo"],
            "foto": f"../congreso-2026-2031/data/{m['foto']}" if m.get("foto") else None,
            "trayectoria": {k: VOTO.get(x, "NV") for k, x in tray.items()},
            "voto_raw": tray, "bando": final,
            "nota": NOTAS.get(m["slug"], ""),
        })
    out = {"votaciones": votaciones, "bandos": BANDOS, "miembros": miembros}
    (HERE / "data" / "facciones.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # El artículo lleva los datos incrustados (se abre sin servidor y no hace fetch).
    page = HERE / "index.html"
    html = page.read_text(encoding="utf-8")
    a, b = "<!--DATA-->", "<!--/DATA-->"
    i, j = html.index(a) + len(a), html.index(b)
    blob = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    page.write_text(html[:i] + f'<script id="data" type="application/json">{blob}</script>' + html[j:],
                    encoding="utf-8")
    df = pd.DataFrame(miembros)
    print(df.groupby(["grupo", "bando", "camara"]).size().unstack(fill_value=0))
    for vv in votaciones:
        print(vv["key"], vv["totales"], "provisional" if vv["provisional"] else "")


if __name__ == "__main__":
    main()
