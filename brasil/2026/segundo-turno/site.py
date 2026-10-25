#!/usr/bin/env python3
"""Arquivos para a página electoral/brasil/2026/segundo-turno, no mesmo formato da
2ª volta do Peru (peru/2026eg/segunda/data), para reaproveitar o mesmo index.html.

Equivalências: departamento → estado (UF); distrito → município; provincia → estado
(o Brasil não tem nível intermediário comparável; a página mostra o mesmo mapa).
"Actas" = seções. Exterior = UF "zz".

Comparações (chaves A–D da página):
  A  Flávio 2º turno vs Flávio 1º turno      B  Lula 2º turno vs Lula 1º turno
  C  Flávio 2026 vs Bolsonaro 2º turno 2022  D  Lula 2026 vs Lula 2º turno 2022
  (pct sobre válidos de cada eleição; C e D só se existir data/abertos/2022_2t_mun.csv)

Saída: data/site/{candidates,aggregate_stats,forecast,forecast_national,forecast_exterior}.json,
       brasil_2026_{distrito,provincia,departamento}_segunda.geojson,
       comparison/brasil_2026_segunda_{nivel}_comparison.geojson, results/brasil_2026_distrito_segunda.csv
Uso: python3 site.py [--loop 60]
"""
import argparse, json, time, urllib.request, ssl, warnings
from datetime import datetime, timezone
from pathlib import Path

import certifi
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
warnings.filterwarnings("ignore")
OUT = HERE / "data" / "site"
CTX = ssl.create_default_context(cafile=certifi.where())
LULA_COLOR, FLAVIO_COLOR = "#C8102E", "#1D4ED8"
CANDS = [
    {"codigo": "01", "src": "c13", "nombre": "LULA", "partido": "PT", "color": LULA_COLOR, "imagen": "images/lula.jpeg"},
    {"codigo": "02", "src": "c22", "nombre": "FLÁVIO BOLSONARO", "partido": "PL", "color": FLAVIO_COLOR, "imagen": "images/flavio.jpeg"},
]
UF_NOME = {"ac": "ACRE", "al": "ALAGOAS", "am": "AMAZONAS", "ap": "AMAPÁ", "ba": "BAHIA", "ce": "CEARÁ",
           "df": "DISTRITO FEDERAL", "es": "ESPÍRITO SANTO", "go": "GOIÁS", "ma": "MARANHÃO", "mg": "MINAS GERAIS",
           "ms": "MATO GROSSO DO SUL", "mt": "MATO GROSSO", "pa": "PARÁ", "pb": "PARAÍBA", "pe": "PERNAMBUCO",
           "pi": "PIAUÍ", "pr": "PARANÁ", "rj": "RIO DE JANEIRO", "rn": "RIO GRANDE DO NORTE", "ro": "RONDÔNIA",
           "rr": "RORAIMA", "rs": "RIO GRANDE DO SUL", "sc": "SANTA CATARINA", "se": "SERGIPE", "sp": "SÃO PAULO",
           "to": "TOCANTINS", "zz": "EXTERIOR"}


def num(s):
    return float(str(s).replace(",", ".")) if s not in (None, "") else 0.0


def ler_mun(ele):
    """Por município: votos de Lula/Flávio, válidos, brancos, nulos, comparecimento, eleitorado, seções."""
    filas = []
    for f in (HERE / "data" / "raw" / ele).glob("*.json"):
        try:
            d = json.loads(f.read_bytes())
        except Exception:
            continue
        v = {}
        for c in d["carg"]:
            for a in c.get("agr", []):
                for p in a["par"]:
                    for k in p["cand"]:
                        v[k["n"]] = v.get(k["n"], 0) + int(k.get("vap") or 0)
        filas.append({"id": f.stem, "uf": f.stem[:2], "c13": v.get("13", 0), "c22": v.get("22", 0),
                      "validos": int(d["v"]["vv"] or 0), "brancos": int(d["v"]["vb"] or 0),
                      "nulos": int(d["v"]["tvn"] or 0), "emitidos": int(d["e"]["c"] or 0),
                      "eleitores": int(d["e"]["te"] or 0), "secoes_tot": int(d["s"]["st"] or 0),
                      "secoes": int(d["s"]["ts"] or 0)})
    return pd.DataFrame(filas).set_index("id")


def geo():
    """Malha municipal simplificada (código IBGE) e estados por dissolução, uma vez."""
    import geopandas as gpd
    cache = HERE / "data" / "geo" / "malha.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    partes = [gpd.read_file(f) for f in sorted((HERE / "data" / "geo").glob("mun-*.json"))]
    g = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=partes[0].crs)[["id", "geometry"]]
    g["geometry"] = g.geometry.make_valid().simplify(0.008, preserve_topology=True).buffer(0)
    g.to_parquet(cache)
    return g


def sem_buracos(geom, min_area=0.05):
    """Tira os buracos minúsculos que a dissolução deixa (mantém os grandes, como o DF dentro de GO)."""
    from shapely.geometry import MultiPolygon, Polygon
    def um(p):
        return Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area > min_area])
    if geom.geom_type == "Polygon":
        return um(geom)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([um(p) for p in geom.geoms if p.area > 1e-4])
    return geom


def cand_json(r):
    lst = [{"name": c["nombre"], "color": c["color"], "votes": int(r[c["src"]])} for c in CANDS]
    return json.dumps(sorted(lst, key=lambda x: -x["votes"]), ensure_ascii=False)


def props(df):
    out = df.copy()
    out["votos_validos"] = df.validos
    out["votos_blancos"] = df.brancos
    out["votos_nulos"] = df.nulos
    out["votos_emitidos"] = df.emitidos
    out["num_electores"] = df.eleitores
    out["num_mesas"] = df.secoes
    out["actas_contabilizadas"] = df.secoes_tot
    out["actas_total"] = df.secoes
    out["turnout_pct"] = (100 * df.emitidos / df.eleitores.clip(lower=1)).round(1)
    lula_gana = df.c13 >= df.c22
    vazio = (df.c13 + df.c22) == 0
    out["winner"] = np.where(vazio, "", np.where(lula_gana, "LULA", "FLÁVIO BOLSONARO"))
    out["winner_votes"] = np.where(lula_gana, df.c13, df.c22)
    out["winner_color"] = np.where(vazio, "#cccccc", np.where(lula_gana, LULA_COLOR, FLAVIO_COLOR))
    out["all_candidates"] = [cand_json(r) for _, r in df.iterrows()]
    return out


def comparacao(r2, r1, r22):
    """Colunas pct21_X / pct26_X / diff_X / votes21_X / votes26_X / vv21_X por chave."""
    c = pd.DataFrame(index=r2.index)
    c["votos_validos"] = r2.validos
    pares = {"A": ("c22", r1, "c22"), "B": ("c13", r1, "c13")}
    if r22 is not None:
        pares |= {"C": ("c22", r22, "c22"), "D": ("c13", r22, "c13")}
    for k, (col, ref, rcol) in pares.items():
        ref = ref.reindex(r2.index)
        c[f"votes26_{k}"] = r2[col]
        c[f"votes21_{k}"] = ref[rcol].fillna(0)
        c[f"vv21_{k}"] = ref.validos.fillna(0)
        c[f"pct26_{k}"] = (100 * r2[col] / r2.validos.replace(0, np.nan)).round(4)
        c[f"pct21_{k}"] = (100 * ref[rcol] / ref.validos.replace(0, np.nan)).round(4)
        c[f"diff_{k}"] = (c[f"pct26_{k}"] - c[f"pct21_{k}"]).round(4)
    c["votos_validos_2021"] = r1.reindex(r2.index).validos.fillna(0)
    return c


def nivel(df, chave):
    soma = [x for x in df.columns if df[x].dtype.kind in "if" and not x.startswith(("pct", "diff"))]
    return df.groupby(chave)[soma].sum()


def recalc_pct(c):
    for k in "ABCD":
        if f"votes26_{k}" in c:
            c[f"pct26_{k}"] = (100 * c[f"votes26_{k}"] / c.votos_validos.replace(0, np.nan)).round(4)
            c[f"pct21_{k}"] = (100 * c[f"votes21_{k}"] / c[f"vv21_{k}"].replace(0, np.nan)).round(4)
            c[f"diff_{k}"] = (c[f"pct26_{k}"] - c[f"pct21_{k}"]).round(4)
    return c


def escrever_geo(g, df, campos, destino):
    import geopandas as gpd
    x = g.merge(df[campos], left_on="key", right_index=True, how="left")
    x = gpd.GeoDataFrame(x.drop(columns=["key"]), geometry="geometry", crs=g.crs)
    x = x.replace({np.nan: None})
    destino.write_text(x.to_json(drop_id=True))


def battle(samples, nome_a="LULA", nome_b="FLÁVIO BOLSONARO"):
    s = np.asarray(samples)
    lula_lidera = np.median(s) >= 0
    m = s if lula_lidera else -s
    a, b = (CANDS[0], CANDS[1]) if lula_lidera else (CANDS[1], CANDS[0])
    counts, edges = np.histogram(m, bins=40)
    return {"cand_2nd": a["codigo"], "cand_3rd": b["codigo"], "nombre_2nd": a["nombre"], "nombre_3rd": b["nombre"],
            "color_2nd": a["color"], "color_3rd": b["color"], "prob_2nd_pct": round(100 * (m > 0).mean(), 1),
            "prob_3rd_pct": round(100 * (m <= 0).mean(), 1), "mean_margin_votes": int(m.mean()),
            "ci_lo_votes": int(np.quantile(m, .05)), "ci_hi_votes": int(np.quantile(m, .95)),
            "ci_lo_99_votes": int(np.quantile(m, .005)), "ci_hi_99_votes": int(np.quantile(m, .995)),
            "margin_distribution": {"edges": [int(e) for e in edges], "counts": [int(c) for c in counts]}}


def nacional():
    url = "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 datapol-scraper/1.0"})
    return json.loads(urllib.request.urlopen(req, context=CTX, timeout=30).read())


def rodar():
    import modelo
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cfg = json.loads((HERE / "data" / "municipios.json").read_text())
    info = {a["cd"] + x["cd"]: {"ibge": x.get("cdi"), "nome": x["nm"], "uf": a["cd"]} for a in cfg["abr"] for x in a["mu"]}
    r2, r1 = ler_mun("6258"), ler_mun("6257")
    r2 = r2.reindex(r1.index).fillna(0)
    r2["uf"] = r1.uf
    arq22 = HERE / "data" / "abertos" / "2022_2t_mun.csv"
    r22 = pd.read_csv(arq22, dtype={"id": str}).set_index("id") if arq22.exists() else None

    base = pd.DataFrame({k: v for k, v in info.items()}).T
    df = r2.join(base[["ibge", "nome"]])
    df["ubigeo_distrito"] = df.ibge.fillna("")
    df["ubigeo_dept"] = df.uf
    df["ubigeo_provincia"] = df.uf
    df["nombre_distrito"] = df.nome
    df["nombre_dept"] = df.uf.map(UF_NOME)
    df["nombre_provincia"] = df.nombre_dept

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison").mkdir(exist_ok=True)
    (OUT / "results").mkdir(exist_ok=True)
    (OUT / "candidates.json").write_text(json.dumps([{k: v for k, v in c.items() if k != "src"} for c in CANDS], ensure_ascii=False, indent=2))

    # Geometrias: município pelo código IBGE; estado por dissolução
    import geopandas as gpd
    g = geo()
    gm = g.rename(columns={"id": "key"})
    gm["key"] = gm.key.astype(str)
    gu = g.copy()
    gu["key"] = gu.id.astype(str).str[:2]
    ibge_uf = {str(v["ibge"])[:2]: v["uf"] for v in info.values() if v.get("ibge")}
    gu["key"] = gu.key.map(ibge_uf)
    cache_uf = HERE / "data" / "geo" / "estados.parquet"
    if cache_uf.exists():
        gu = gpd.read_parquet(cache_uf)
    else:
        gu["geometry"] = gu.geometry.buffer(0.0005)
        gu = gu.dissolve(by="key").reset_index()[["key", "geometry"]]
        gu["geometry"] = gu.geometry.buffer(-0.0005).simplify(0.01)
        gu["geometry"] = gu.geometry.apply(sem_buracos)
        gu.to_parquet(cache_uf)

    campos_d = ["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept", "nombre_distrito", "nombre_provincia", "nombre_dept",
                "votos_validos", "votos_blancos", "votos_nulos", "votos_emitidos", "num_electores", "num_mesas",
                "actas_contabilizadas", "actas_total", "turnout_pct", "winner", "winner_votes", "winner_color", "all_candidates"]
    pd_ = props(df)
    dist = pd_[pd_.ubigeo_distrito != ""].set_index("ubigeo_distrito", drop=False)
    escrever_geo(gm, dist, campos_d, OUT / "brasil_2026_distrito_segunda.geojson")

    num = ["c13", "c22", "validos", "brancos", "nulos", "emitidos", "eleitores", "secoes_tot", "secoes"]
    uf = df.groupby("uf")[num].sum()
    uf["ubigeo_dept"] = uf.index
    uf["ubigeo_provincia"] = uf.index
    uf["nombre_dept"] = uf.index.map(UF_NOME)
    uf["nombre_provincia"] = uf.nombre_dept
    pu = props(uf)
    campos_u = [c for c in campos_d if c not in ("ubigeo_distrito", "nombre_distrito")]
    escrever_geo(gu, pu, campos_u, OUT / "brasil_2026_departamento_segunda.geojson")
    escrever_geo(gu, pu, campos_u, OUT / "brasil_2026_provincia_segunda.geojson")

    # Comparações
    comp = comparacao(r2, r1, r22)
    comp_d = recalc_pct(comp.copy())
    comp_d = comp_d.join(df[["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept", "nombre_distrito", "nombre_provincia", "nombre_dept"]])
    comp_d = comp_d[comp_d.ubigeo_distrito != ""].set_index("ubigeo_distrito", drop=False)
    escrever_geo(gm, comp_d, list(comp_d.columns), OUT / "comparison" / "brasil_2026_segunda_distrito_comparison.geojson")
    comp_u = recalc_pct(nivel(comp.join(df[["uf"]]), "uf"))
    comp_u["ubigeo_dept"] = comp_u.index
    comp_u["ubigeo_provincia"] = comp_u.index
    comp_u["nombre_dept"] = comp_u.index.map(UF_NOME)
    comp_u["nombre_provincia"] = comp_u.nombre_dept
    for nv in ("departamento", "provincia"):
        escrever_geo(gu, comp_u, list(comp_u.columns), OUT / "comparison" / f"brasil_2026_segunda_{nv}_comparison.geojson")

    # CSV por município
    csv = df[df.ubigeo_distrito != ""][["ubigeo_distrito", "validos", "brancos", "nulos", "emitidos", "secoes_tot", "secoes", "c13", "c22"]]
    csv.columns = ["ubigeo_distrito", "votos_validos", "votos_blancos", "votos_nulos", "votos_emitidos",
                   "actas_contabilizadas", "actas_total", "cand_01", "cand_02"]
    csv.to_csv(OUT / "results" / "brasil_2026_distrito_segunda.csv", index=False)

    # Totais nacionais (arquivo BR do TSE, com exterior)
    n = nacional()
    votos = {}
    for c in n["carg"]:
        for a in c.get("agr", []):
            for p in a["par"]:
                for k in p["cand"]:
                    votos[{"13": "01", "22": "02"}.get(k["n"], k["n"])] = int(k.get("vap") or 0)
    vv = int(n["v"]["vv"] or 0)
    emit = int(n["e"]["c"] or 0)
    agg = {"n_distritos": int((dist.votos_validos > 0).sum()), "num_electores": int(n["e"]["te"]),
           "votos_emitidos": emit, "votos_validos": vv, "votos_blancos": int(n["v"]["vb"] or 0),
           "votos_nulos": int(n["v"]["tvn"] or 0), "actas_contabilizadas": int(n["s"]["st"]),
           "actas_total": int(n["s"]["ts"]), "participacion_pct": num_br(n["e"]["pc"]),
           "actas_pct": num_br(n["s"]["pst"]),
           "candidatos": [c | {"votos": votos.get(c["codigo"], 0),
                               "pct_validos": round(100 * votos.get(c["codigo"], 0) / vv, 3) if vv else 0,
                               "pct_emitidos": round(100 * votos.get(c["codigo"], 0) / emit, 3) if emit else 0}
                          for c in CANDS],
           "generated_at": now}
    (OUT / "aggregate_stats.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2))

    # Projeção
    m, res, tot = modelo.projetar(4000)
    fc = {"generated_at": now, "pct_actas": agg["actas_pct"], "mesas_contabilizadas": agg["actas_contabilizadas"],
          "mesas_remaining": agg["actas_total"] - agg["actas_contabilizadas"], "mesas_total": agg["actas_total"],
          "mesas_in_analysis": agg["actas_contabilizadas"], "n_sims": 4000}
    if res is not None:
        p = float(res["p_lula"])
        fc["candidates"] = [c | {"votes": votos.get(c["codigo"], 0), "pct_emitidos": agg["candidatos"][i]["pct_emitidos"],
                                 "prob_runoff": round(100 * (p if c["codigo"] == "01" else 1 - p), 1)}
                            for i, c in enumerate(CANDS)]
        fc["battle"] = battle(res["margens"]["total"])
        fc["battle_domestic"] = battle(res["margens"]["dom"])
        fc["battle_exterior"] = battle(res["margens"]["ext"])
        fc["lula_pct_proj"] = round(100 * float(res["final_med"]), 2)
        fc["lula_pct_lo"] = round(100 * float(res["lo"]), 2)
        fc["lula_pct_hi"] = round(100 * float(res["hi"]), 2)
        (OUT / "forecast_national.json").write_text(json.dumps(fc["battle_domestic"], ensure_ascii=False))
        (OUT / "forecast_exterior.json").write_text(json.dumps(fc["battle_exterior"], ensure_ascii=False))
    (OUT / "forecast.json").write_text(json.dumps(fc, ensure_ascii=False))
    print(f"[{time.strftime('%H:%M:%S')}] site: seções {agg['actas_pct']}% · Lula {agg['candidatos'][0]['pct_validos']}%"
          + (f" · proj {fc.get('lula_pct_proj')}% P={fc['candidates'][0]['prob_runoff']}%" if res is not None else ""), flush=True)


def num_br(s):
    return round(num(s), 2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0)
    a = ap.parse_args()
    while True:
        try:
            rodar()
        except Exception as e:
            print("erro:", repr(e), flush=True)
            if not a.loop:
                raise
        if not a.loop:
            break
        time.sleep(a.loop)
