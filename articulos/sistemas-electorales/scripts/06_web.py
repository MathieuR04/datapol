#!/usr/bin/env python3
"""Datos de la página: web/data.json y web/distritos_us.geojson.

`analisis` en data.json: por partido, su % en cada distrito, mejor y peor
distrito, mediana del ganador, segundos puestos y voto por zona (región natural
× ciudad/resto, ver `region`).

Uso:
    uv run --with pandas --with pyarrow --with geopandas python scripts/06_web.py
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]
# Congreso real 2026-2031, Cámara de Diputados (130), por organización.
REAL = {"00000008": 41, "00000010": 32, "00000016": 18, "00000035": 15,
        "00000014": 14, "00000002": 10}
SIGLA = {"00000008": "FP", "00000010": "JP", "00000016": "PBG", "00000035": "RP",
         "00000014": "PCO", "00000002": "AN", "00000023": "PPT", "00000032": "PP",
         "00000001": "APP", "00000020": "SP", "00000037": "UCD", "00000033": "PLG",
         "00000006": "FREPAP", "00000012": "APRA", "00000031": "SICREO",
         "00000021": "FE2021", "00000029": "PP1", "00000003": "VEN", "00000027": "PL"}


RUMBOS = ["Este", "Noreste", "Norte", "Noroeste", "Oeste", "Suroeste", "Sur", "Sureste"]

# Extranjero: región por país (ubigeo 91 África, 92 América, 93 Asia, 94 Europa, 95 Oceanía).
NORTEAMERICA = {"ESTADOS UNIDOS DE ÁMERICA", "CANADÁ", "MÉXICO"}
SUDAMERICA = {"ARGENTINA", "BOLIVIA", "BRASIL", "CHILE", "COLOMBIA", "ECUADOR",
              "PARAGUAY", "URUGUAY", "VENEZUELA"}
CONTINENTE = {"91": "África", "93": "Asia", "94": "Europa", "95": "Oceanía"}

# Zonas, a grandes rasgos: región natural por departamento, con excepciones por
# provincia; «ciudades» = distritos con ≥ CIUDAD electores por km².
SELVA = {"LORETO", "UCAYALI", "MADRE DE DIOS", "SAN MARTIN", "AMAZONAS"}
COSTA = {"TUMBES", "PIURA", "LAMBAYEQUE", "LA LIBERTAD", "LIMA PROVINCIAS", "ICA",
         "TACNA", "MOQUEGUA"}
EXCEPCION = {
    "Sierra": {"AYABACA", "HUANCABAMBA", "BOLIVAR", "GRAN CHIMU", "JULCAN", "OTUZCO", "PATAZ",
               "SANCHEZ CARRION", "SANTIAGO DE CHUCO", "CAJATAMBO", "CANTA", "HUAROCHIRI",
               "OYON", "YAUYOS", "CANDARAVE", "TARATA", "GENERAL SANCHEZ CERRO"},
    "Costa": {"SANTA", "CASMA", "HUARMEY", "CAMANA", "CARAVELI", "ISLAY"},
    "Selva": {"CHANCHAMAYO", "SATIPO", "LA CONVENCION", "LA CONVENCIÓN", "OXAPAMPA",
              "LEONCIO PRADO", "PUERTO INCA", "JAEN", "SAN IGNACIO"},
}
CIUDAD = 150
ZONAS = ["Lima y Callao", "Costa · ciudades", "Costa · resto", "Sierra · ciudades",
         "Sierra · resto", "Selva · ciudades", "Selva · resto", "Extranjero"]


def region(circ: str, prov: str) -> str:
    for z, provs in EXCEPCION.items():
        if prov in provs:
            return z
    return "Selva" if circ in SELVA else "Costa" if circ in COSTA else "Sierra"


def nombra_exterior(m: pd.DataFrame) -> dict[str, str]:
    """«Norteamérica», «Sudamérica – Norteamérica», «Europa 1»…: las regiones con
    al menos 10% de los electores del distrito, de mayor a menor."""
    def reg(r):
        if r.ubigeo[:2] != "92":
            return CONTINENTE[r.ubigeo[:2]]
        return ("Norteamérica" if r.nombre_provincia in NORTEAMERICA else
                "Sudamérica" if r.nombre_provincia in SUDAMERICA else "Centroamérica y Caribe")
    m = m.assign(reg=[reg(r) for r in m.itertuples()])
    nombres = {}
    for du, g in m.groupby("distrito_us"):
        s = g.groupby("reg").electores.sum().sort_values(ascending=False)
        nombres[du] = " – ".join(s[s / s.sum() >= 0.10].index)
    s = pd.Series(nombres)
    for nom, grupo in s.groupby(s):
        if len(grupo) > 1:
            for i, du in enumerate(sorted(grupo.index), 1):
                nombres[du] = f"{nom} {i}"
    return nombres


def analisis(D: Path, m: pd.DataFrame, res: pd.DataFrame, codigos: list[str]) -> dict:
    """Dónde gana y pierde cada partido: % por distrito, zonas y segundos puestos."""
    import geopandas as gpd
    v = pd.read_csv(D / "votos_distrito_us.csv").set_index("distrito_us")
    r = res.set_index("distrito_us")
    sh = v.div(r.validos, axis=0)
    g = gpd.read_file(D / "distritos_us.geojson").set_index("distrito_us")
    km2 = g.to_crs("EPSG:32718").area / 1e6
    dens = r.electores / km2.reindex(r.index)
    m = m.assign(reg=[region(c, p) for c, p in zip(m.circ, m.nombre_provincia)])
    reg = m.groupby(["distrito_us", "reg"]).electores.sum().reset_index() \
        .sort_values("electores").groupby("distrito_us").reg.last()
    zona = {}
    for du in r.index:
        c = r.circ[du]
        if c.startswith("PERUANOS"):
            zona[du] = "Extranjero"
        elif c in ("LIMA METROPOLITANA", "CALLAO"):
            zona[du] = "Lima y Callao"
        else:
            zona[du] = f"{reg[du]} · {'ciudades' if dens[du] >= CIUDAD else 'resto'}"
    zona = pd.Series(zona)
    vz = v.groupby(zona).sum()
    vz = vz.div(r.validos.groupby(zona).sum(), axis=0)
    gan, seg = r.ganador.astype(str).str.zfill(8), r.segundo.astype(str).str.zfill(8)
    partidos = {}
    for c in codigos:
        if c not in sh:
            continue
        s, w = sh[c], gan == c
        partidos[c] = {
            "mediana": round(float(s.median()), 4), "p90": round(float(s.quantile(0.9)), 4),
            "mejor": [s.idxmax(), round(float(s.max()), 4)],
            "peor": [s.idxmin(), round(float(s.min()), 4)],
            "ganados": int(w.sum()), "segundos": int((seg == c).sum()),
            "med_gana": round(float(r.pct1[w].median()), 4) if w.any() else None,
            "circ_gana": [[k, int(n)] for k, n in r.circ[w].value_counts().head(3).items()],
            "zona_pct": {z: round(float(vz.loc[z, c]), 4) for z in ZONAS if z in vz.index},
            "zona_esc": {z: int(((zona == z) & w).sum()) for z in ZONAS},
            "pcts": [round(float(x), 3) for x in s.reindex(r.index)],
        }
    p1 = r.pct1
    return {"orden": list(r.index), "zonas": ZONAS,
            "zona_n": {z: int((zona == z).sum()) for z in ZONAS},
            "zona": zona.reindex(r.index).tolist(),
            "ganador": {"media": round(float(p1.mean()), 4), "mediana": round(float(p1.median()), 4),
                        "min": [p1.idxmin(), round(float(p1.min()), 4)],
                        "max": [p1.idxmax(), round(float(p1.max()), 4)],
                        "bajo25": int((p1 < 0.25).sum()), "bajo20": int((p1 < 0.20).sum()),
                        "sobre50": int((p1 > 0.5).sum())},
            "partidos": partidos}


def bonito(x: str) -> str:
    """'SAN JUAN DE LURIGANCHO' → 'San Juan de Lurigancho'."""
    menores = {"de", "del", "la", "las", "los", "el", "y"}
    def palabra(i, w):
        if i and w in menores:
            return w
        return "-".join(t.capitalize() for t in w.split("-"))
    return " ".join(palabra(i, w) for i, w in enumerate(x.lower().split()))


def rumbo(dx: float, dy: float, escala: float) -> str:
    if np.hypot(dx, dy) < 0.25 * escala:
        return "Centro"
    return RUMBOS[int(round(np.degrees(np.arctan2(dy, dx)) / 45)) % 8]


def nombra(m: pd.DataFrame) -> dict[str, str]:
    """Nombre corto de cada distrito uninominal, por lo que lo compone.

    - Casi todo en un distrito administrativo (≥75%): su nombre; si ese distrito
      se reparte entre varios uninominales, más el rumbo (San Juan de
      Lurigancho Norte, … Centro).
    - Si no, casi todo en una provincia (≥75%) repartida en a lo sumo tres
      distritos uninominales: la provincia, con rumbo si se reparte.
    - Si no: los dos componentes más grandes, «A – B»."""
    m = m.copy()
    x, y = m.lon.fillna(0), m.lat.fillna(0)
    m["wx"], m["wy"] = x * m.electores, y * m.electores
    nombres = {}
    for nivel, col, nom in (("dist", "ubigeo", "nombre_distrito"), ("prov", "prov", "nombre_provincia")):
        g = m.groupby([col, "distrito_us"]).agg(e=("electores", "sum"), wx=("wx", "sum"),
                                                 wy=("wy", "sum"), n=(nom, "first")).reset_index()
        tot_du = m.groupby("distrito_us").electores.sum()
        g["share_du"] = g.e / g.distrito_us.map(tot_du)
        u = m.groupby(col).agg(e=("electores", "sum"), wx=("wx", "sum"), wy=("wy", "sum"))
        u["cx"], u["cy"] = u.wx / u.e, u.wy / u.e
        # Dispersión de la unidad, para decidir cuándo es «Centro».
        d2 = ((x - m[col].map(u.cx)) ** 2 + (y - m[col].map(u.cy)) ** 2) * m.electores
        u["esc"] = np.sqrt(d2.groupby(m[col]).sum() / u.e)
        trozos = g[g.e > 0].groupby(col).distrito_us.nunique()
        for r in g[g.share_du >= 0.75].itertuples():
            du = r.distrito_us
            if du in nombres:
                continue
            base = bonito(r.n)
            # Una provincia repartida en muchos distritos (Lima, Callao, Arequipa…)
            # no sirve de nombre: ahí se nombra por sus distritos.
            if nivel == "prov" and trozos[getattr(r, col)] > 3:
                continue
            if trozos[getattr(r, col)] > 1:
                c = u.loc[getattr(r, col)]
                base += " " + rumbo(r.wx / r.e - c.cx, r.wy / r.e - c.cy, c.esc)
            nombres[du] = base
    comp = (m.groupby(["distrito_us", "ubigeo"]).agg(e=("electores", "sum"), n=("nombre_distrito", "first"))
            .reset_index().sort_values("e", ascending=False))
    for du, g in comp.groupby("distrito_us", sort=False):
        if du not in nombres:
            nombres[du] = " – ".join(bonito(n) for n in g.n.head(2))
    # Repetidos dentro de la circunscripción: se numeran.
    s = pd.Series(nombres)
    circ = m.groupby("distrito_us").circ.first()
    for (_, nom), grupo in s.groupby([circ.reindex(s.index), s]):
        if len(grupo) > 1:
            for i, du in enumerate(sorted(grupo.index), 1):
                nombres[du] = f"{nom} {i}"
    return nombres


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=AQUI / "data")
    ap.add_argument("--web", type=Path, default=AQUI / "web")
    a = ap.parse_args()
    D = a.data

    col = {c["codigo"].zfill(8): c["color"] for c in
           json.load(open(DATAPOL / "peru/2026eg/primera/data/candidates.json"))}
    nac = pd.read_csv(D / "nacional_us.csv", dtype={"codigo": str})
    res = pd.read_csv(D / "resultados_us.csv", dtype={"ganador": str, "segundo": str})
    dis = pd.read_csv(D / "distritos_us.csv")
    rep = pd.read_csv(D / "reparto.csv")
    m = pd.read_parquet(D / "mesas.parquet").merge(pd.read_parquet(D / "asignacion.parquet"))
    # Nombres: los distritos administrativos que lo componen, de mayor a menor.
    comp = (m.groupby(["distrito_us", "ubigeo", "nombre_provincia", "nombre_distrito"]).electores.sum()
            .reset_index().sort_values("electores", ascending=False))
    total_adm = m.groupby("ubigeo").electores.sum()
    piezas = {}
    for du, g in comp.groupby("distrito_us", sort=False):
        piezas[du] = [[r.nombre_distrito.title(), r.nombre_provincia.title(), int(r.electores),
                       round(r.electores / total_adm[r.ubigeo], 3)]
                      for r in g.itertuples()]

    nac["color"] = nac.codigo.map(col).fillna("#9ca3af")
    nac["sigla"] = nac.codigo.map(SIGLA).fillna(nac.nombre.str[:6])
    partidos = [{"codigo": r.codigo, "nombre": r.nombre, "sigla": r.sigla, "color": r.color,
                 "votos": int(r.votos), "pct_votos": round(r.pct_votos, 5),
                 "escanos": int(r.escanos), "en_duda": int(r.escanos_en_duda),
                 "real": REAL.get(r.codigo, 0)}
                for r in nac.itertuples() if r.votos > 0]
    res = res.merge(dis[["distrito_us", "desv", "n_distritos", "n_locales"]], on="distrito_us")
    m_pais = m[~m.exterior]
    nombres = nombra(m_pais)
    # En el extranjero, por continente; los países van en `piezas`.
    nombres.update(nombra_exterior(m[m.exterior]))
    ext = m[m.exterior].groupby(["distrito_us", "nombre_provincia"]).electores.sum().reset_index() \
        .sort_values("electores", ascending=False)
    for du, g in ext.groupby("distrito_us", sort=False):
        piezas[du] = [[bonito(r.nombre_provincia), "", int(r.electores), 1.0] for r in g.itertuples()]
    distritos = {r.distrito_us: {
        "nombre": nombres.get(r.distrito_us, r.distrito_us),
        "circ": r.circ, "electores": int(r.electores), "desv": round(r.desv, 4),
        "g": r.ganador, "s": r.segundo, "p1": round(r.pct1, 4), "p2": round(r.pct2, 4),
        "margen": int(r.margen), "pend": int(r.electores_pend), "duda": bool(r.en_duda),
        "piezas": piezas[r.distrito_us]} for r in res.itertuples()}
    out = {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "fuente": str(res.fuente.iloc[0]) if "fuente" in res else "diputados",
           "pex_validos": round(float(res[res.circ.str.startswith("PERUANOS")].validos.sum()
                                      / res.validos.sum()), 5),
           "escanos": len(distritos),
           "pct_pendiente": round(float(res.electores_pend.sum() / res.electores.sum()), 4),
           "reparto": rep.to_dict("records"), "partidos": partidos, "distritos": distritos,
           "analisis": analisis(D, m, res, [p["codigo"] for p in partidos
                                            if p["escanos"] > 0 or p["pct_votos"] >= 0.03])}
    a.web.mkdir(exist_ok=True)
    (a.web / "data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    shutil.copy(D / "distritos_us.topojson", a.web / "distritos_us.topojson")
    shutil.copy(D / "circunscripciones.geojson", a.web / "circunscripciones.geojson")
    (a.web / "distritos_us.geojson").unlink(missing_ok=True)
    print(f"→ {a.web}/data.json ({len(distritos)} distritos, {len(partidos)} partidos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
