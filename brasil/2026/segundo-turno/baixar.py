#!/usr/bin/env python3
"""Resultados por município do TSE (presidente), 1º ou 2º turno.

Fonte: resultados.tse.jus.br/oficial/ele2026/<eleição>/dados/<uf>/<uf><mun>-c0001-e<eleição>-u.json
  6257 = 1º turno (04/10), 6258 = 2º turno (25/10). Lista de municípios: config/mun-e006258-cm.json.
Cada arquivo traz votos por candidato, seções totalizadas (s.pst) e eleitorado (e.te).

Saída: data/raw/<eleição>/<uf><mun>.json (sobrescreve a cada rodada).
Uso: python3 baixar.py 6257 [--hilos 16]
"""
import argparse, json, ssl, time, urllib.request, concurrent.futures as cf
from pathlib import Path
import certifi

HERE = Path(__file__).resolve().parent
CTX = ssl.create_default_context(cafile=certifi.where())
BASE = "https://resultados.tse.jus.br/oficial/ele2026"


def municipios():
    m = json.loads((HERE / "data" / "municipios.json").read_text())
    return [(a["cd"], x["cd"]) for a in m["abr"] for x in a["mu"]]


def baixar(ele, uf, cd):
    url = f"{BASE}/{ele}/dados/{uf}/{uf}{cd}-c0001-e00{ele}-u.json"
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 datapol-scraper/1.0"})
            return urllib.request.urlopen(req, context=CTX, timeout=30).read()
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def pendentes(ele, out):
    """Municípios a baixar nesta rodada: os que não estão 100% apurados, os maiores
    primeiro (eleitorado do 1º turno), para que a projeção melhore mais rápido."""
    tam = {}
    for f in (HERE / "data" / "raw" / "6257").glob("*.json"):
        try:
            tam[f.stem] = int(json.loads(f.read_bytes())["e"]["te"])
        except Exception:
            pass
    fila = []
    for uf, cd in municipios():
        f = out / f"{uf}{cd}.json"
        if f.exists():
            try:
                if json.loads(f.read_bytes())["s"]["pst"] == "100,00":
                    continue
            except Exception:
                pass
        fila.append((uf, cd))
    return sorted(fila, key=lambda t: -tam.get(t[0] + t[1], 0))


def rodada(ele, hilos):
    out = HERE / "data" / "raw" / ele
    out.mkdir(parents=True, exist_ok=True)
    t0, falhas = time.time(), 0
    with cf.ThreadPoolExecutor(hilos) as ex:
        futs = {ex.submit(baixar, ele, uf, cd): (uf, cd) for uf, cd in pendentes(ele, out)}
        for f in cf.as_completed(futs):
            uf, cd = futs[f]
            b = f.result()
            if b is None:
                falhas += 1
                continue
            (out / f"{uf}{cd}.json").write_bytes(b)
    print(f"{ele}: {len(futs)} municípios em {time.time() - t0:.0f}s, {falhas} falhas", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ele")
    ap.add_argument("--hilos", type=int, default=16)
    ap.add_argument("--loop", type=int, default=0, help="segundos entre rodadas (0 = uma só)")
    a = ap.parse_args()
    while True:
        rodada(a.ele, a.hilos)
        if not a.loop:
            break
        time.sleep(a.loop)
