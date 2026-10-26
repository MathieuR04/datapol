#!/usr/bin/env python3
"""Boletins de urna (BU) do 2º turno, seção por seção, a partir dos arquivos do TSE.

Fluxo por UF:
  config/<uf>/<uf>-p003221-cs.json   lista de seções; as recebidas têm "ha" (hora de recebimento)
  dados/<uf>/<mun>/<zona>/<secao>/p003221-<uf>-m<mun>-z<zona>-s<secao>-aux.json
                                      hash e nomes dos arquivos da urna
  dados/<uf>/<mun>/<zona>/<secao>/<hash>/<nome>-bu.dat
                                      BU em ASN.1 DER (≈1,4 KB)

Do BU interessa a eleição 6258 (presidente): comparecimento e votos por votável
(tipo 1 nominal com código 13/22, 2 branco, 3 nulo). O BU vem dentro de um envelope
DER; a decodificação é genérica (sem a especificação ASN.1): procura os nós
SEQUENCE com [1] tipoVoto e [2] quantidade.

Cache: data/secoes/bu/<uf>.jsonl (uma linha por seção já lida). Reanudável: cada
rodada só baixa as seções recebidas que ainda não estão no cache.

Uso: python3 secoes.py [--ufs ba,sp] [--hilos 48] [--loop 0]
"""
import argparse, json, ssl, time, urllib.error, urllib.request, concurrent.futures as cf
from pathlib import Path
import certifi

HERE = Path(__file__).resolve().parent
CTX = ssl.create_default_context(cafile=certifi.where())
B = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221"
CACHE = HERE / "data" / "secoes" / "bu"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe", "pi",
       "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]


def get(url, timeout=30):
    """Con 429 (Too Many Requests) el TSE pide bajar el ritmo: se espera y se reintenta,
    cada vez más. Con ~96 hilos el TSE bloqueó la lectura el 25/10; 8 hilos es el ritmo seguro."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 datapol-scraper/1.0"})
    for i in range(6):
        try:
            return urllib.request.urlopen(req, context=CTX, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < 5:
                time.sleep(30 * (i + 1))
                continue
            raise
        except Exception:
            if i >= 2:
                raise
            time.sleep(1 + 2 * i)


# ── DER genérico ────────────────────────────────────────────────────────────
def der(b):
    """Lista de nós (tag, construído, valor|filhos)."""
    out, i = [], 0
    while i < len(b):
        tag = b[i]; i += 1
        if tag & 0x1F == 0x1F:
            while b[i] & 0x80:
                i += 1
            i += 1
        n = b[i]; i += 1
        if n & 0x80:
            k = n & 0x7F
            n = int.from_bytes(b[i:i + k], "big"); i += k
        v = b[i:i + n]; i += n
        out.append((tag, bool(tag & 0x20), der(v) if tag & 0x20 else v))
    return out


def inteiro(v):
    return int.from_bytes(v, "big", signed=True) if v else 0


def bu_interno(b):
    """O BU vai num OCTET STRING grande dentro do envelope."""
    def busca(nos):
        for tag, cons, v in nos:
            if cons:
                r = busca(v)
                if r is not None:
                    return r
            elif tag == 0x04 and len(v) > 400:
                return v
        return None
    return busca(der(b))


def votos_presidente(bu):
    """{'apt': aptos, 'comp': comparecimento, 13: n, 22: n, 'branco': n, 'nulo': n}"""
    nos = der(bu)
    res = {}

    def eleicoes(lista):
        # ResultadoVotacaoPorEleicao: SEQUENCE que começa com INTEGER idEleicao
        for tag, cons, v in lista:
            if not cons:
                continue
            ints = [inteiro(x[2]) for x in v if x[0] == 0x02]
            if v and v[0][0] == 0x02 and inteiro(v[0][2]) == 6258:
                res["apt"] = ints[1] if len(ints) > 1 else None
                votaveis(v)
                return True
            if eleicoes(v):
                return True
        return False

    def votaveis(lista):
        for tag, cons, v in lista:
            if not cons:
                continue
            prims = {x[0]: x[2] for x in v if not x[1]}
            if 0x81 in prims and 0x82 in prims and len(v) <= 6:
                tipo, q = inteiro(prims[0x81]), inteiro(prims[0x82])
                if tipo == 1:
                    ident = [x for x in v if x[1]]
                    cod = None
                    if ident:
                        ints = [inteiro(y[2]) for y in ident[0][2] if not y[1]]
                        cod = ints[-1] if ints else None
                    res[cod] = res.get(cod, 0) + q
                elif tipo == 2:
                    res["branco"] = res.get("branco", 0) + q
                elif tipo == 3:
                    res["nulo"] = res.get("nulo", 0) + q
                continue
            # ResultadoVotacao: ENUMERATED tipoCargo + INTEGER comparecimento
            if v and v[0][0] == 0x0A and len(v) > 1 and v[1][0] == 0x02 and "comp" not in res:
                res["comp"] = inteiro(v[1][2])
            votaveis(v)

    eleicoes(nos)
    return res


# ── Seções ──────────────────────────────────────────────────────────────────
def recebidas(uf):
    cs = json.loads(get(f"{B}/config/{uf}/{uf}-p003221-cs.json", timeout=60))
    out, total = [], 0
    for a in cs["abr"]:
        for m in a["mu"]:
            for z in m["zon"]:
                for s in z["sec"]:
                    total += 1
                    if "ha" in s:
                        out.append((m["cd"], z["cd"], s["ns"]))
    return out, total


def uma(uf, mun, zona, sec):
    base = f"{B}/dados/{uf}/{mun}/{zona}/{sec}"
    aux = json.loads(get(f"{base}/p003221-{uf}-m{mun}-z{zona}-s{sec}-aux.json"))
    h = aux["hashes"][-1]
    nm = next(a["nm"] for a in h["arq"] if a["tp"] == "bu")
    r = votos_presidente(bu_interno(get(f"{base}/{h['hash']}/{nm}")))
    return {"uf": uf, "mun": mun, "zona": zona, "secao": sec, "hr": h.get("hr"),
            "apt": r.get("apt"), "comp": r.get("comp"), "lula": r.get(13, 0), "flavio": r.get(22, 0),
            "branco": r.get("branco", 0), "nulo": r.get("nulo", 0)}


def lidas(uf):
    f = CACHE / f"{uf}.jsonl"
    if not f.exists():
        return set()
    return {(d["mun"], d["zona"], d["secao"]) for d in map(json.loads, f.read_text().splitlines()) if d}


def rodada(ufs, hilos):
    CACHE.mkdir(parents=True, exist_ok=True)
    t0, novas, falhas, status = time.time(), 0, 0, {}
    for uf in ufs:
        try:
            rec, total = recebidas(uf)
        except Exception as e:
            print(f"  {uf}: cs falhou ({e!r})", flush=True)
            continue
        ja = lidas(uf)
        fila = [t for t in rec if t not in ja]
        status[uf] = (len(rec), total)
        if not fila:
            continue
        with open(CACHE / f"{uf}.jsonl", "a") as fh, cf.ThreadPoolExecutor(hilos) as ex:
            futs = [ex.submit(uma, uf, *t) for t in fila]
            for f in cf.as_completed(futs):
                try:
                    fh.write(json.dumps(f.result()) + "\n")
                    novas += 1
                except Exception:
                    falhas += 1
    rec = sum(a for a, _ in status.values())
    tot = sum(b for _, b in status.values())
    (HERE / "data" / "secoes" / "recebidas.json").write_text(json.dumps({"hora": time.strftime("%H:%M:%S"), "uf": status}))
    print(f"[{time.strftime('%H:%M:%S')}] seções: {novas} novas em {time.time() - t0:.0f}s, {falhas} falhas · "
          f"recebidas {rec}/{tot} ({100 * rec / max(tot, 1):.1f}%)", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ufs", default=",".join(UFS))
    ap.add_argument("--hilos", type=int, default=8)
    ap.add_argument("--loop", type=int, default=0)
    a = ap.parse_args()
    while True:
        rodada(a.ufs.split(","), a.hilos)
        if not a.loop:
            break
        time.sleep(a.loop)
