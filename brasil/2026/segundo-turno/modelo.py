#!/usr/bin/env python3
"""Projeção do 2º turno presidencial (Lula × Flávio Bolsonaro) por município.

Base: 1º turno por município (data/raw/6257). Ao vivo: 2º turno (data/raw/6258),
com votos por candidato e % de seções totalizadas (s.pst) em cada município.

Modelo
  1. Linha de base por município: b = Lula1 / (Lula1 + Flávio1) no 1º turno.
  2. Desvio observado nos municípios já apurados: d = logit(Lula2/válidos2) − logit(b).
     Regressão ponderada por votos apurados: d = μ_UF + β·(outros1 − média), com μ_UF
     encolhido para o μ nacional (pseudo-votos k).
  3. Votos que faltam por município: válidos esperados (válidos2 / pst, ou válidos1 ×
     razão de comparecimento da UF se pst < 20%) menos os já apurados.
  4. Monte Carlo: erro nacional comum + erro por UF + erro por município, aplicado aos
     votos que faltam. Saída: % final de Lula com intervalo de 90% e P(Lula vence).

Uso: python3 modelo.py [--sims 4000]
"""
import argparse, csv, json, time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LULA, FLAVIO = "13", "22"


def num(s):
    return float(str(s).replace(",", ".")) if s not in (None, "") else 0.0


def ler(ele):
    filas = []
    for f in (HERE / "data" / "raw" / ele).glob("*.json"):
        try:
            d = json.loads(f.read_bytes())
        except Exception:
            continue
        votos = {}
        for c in d["carg"]:
            for a in c.get("agr", []):
                for p in a["par"]:
                    for k in p["cand"]:
                        votos[k["n"]] = votos.get(k["n"], 0) + int(k.get("vap") or 0)
        filas.append({"id": f.stem, "uf": f.stem[:2], "lula": votos.get(LULA, 0), "flavio": votos.get(FLAVIO, 0),
                      "validos": int(d["v"]["vv"] or 0), "eleitorado": int(d["e"]["te"] or 0),
                      "pst": num(d["s"]["pst"]) / 100, "hg": d.get("hg", "")})
    return pd.DataFrame(filas).set_index("id")


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def projetar(sims=4000, k=200_000, seed=1):
    r1, r2 = ler("6257"), ler("6258")
    m = r1.join(r2, rsuffix="2", how="left").fillna({"lula2": 0, "flavio2": 0, "validos2": 0, "pst2": 0})
    m["uf"] = m.uf.fillna(m.uf2)
    m["base"] = m.lula / (m.lula + m.flavio).clip(lower=1)
    m["outros1"] = 1 - (m.lula + m.flavio) / m.validos.clip(lower=1)

    # Válidos esperados no 2º turno
    ap = m[m.pst2 >= 0.95]
    razao_br = ap.validos2.sum() / max(ap.validos.sum(), 1) if len(ap) else 0.97
    razao_uf = (ap.groupby("uf").validos2.sum() / ap.groupby("uf").validos.sum()).to_dict()
    esperado_base = m.validos * m.uf.map(razao_uf).fillna(razao_br)
    esperado_obs = m.validos2 / m.pst2.clip(lower=1e-6)
    m["esperado"] = np.where(m.pst2 >= 0.2, esperado_obs, esperado_base)
    m["falta"] = (m.esperado - m.validos2).clip(lower=0)

    # Desvio logit nos municípios com votos apurados
    # Para estimar el desvío: municipios del país con al menos 300 votos válidos contados
    # (las primeras urnas sueltas son demasiado ruidosas)
    obs = m[(m.validos2 >= 300) & (m.uf != "zz")].copy()
    tot = {"apurado": m.validos2.sum() / m.esperado.sum(), "lula_atual": m.lula2.sum() / max((m.lula2 + m.flavio2).sum(), 1)}
    # Previa: sin votos contados, la 2da vuelta repite el reparto Lula/Flávio de la 1ra
    # en cada municipio (desvío 0) y los votos de los otros candidatos se reparten en la
    # misma proporción (β = 0), con incertidumbre amplia. A medida que entran votos, la
    # estimación se aleja de la previa con peso W / (W + K0).
    K0 = 3_000_000
    W = obs.validos2.sum()
    if len(obs) >= 30:
        obs["d"] = logit(obs.lula2 / (obs.lula2 + obs.flavio2).clip(lower=1)) - logit(obs.base)
        obs["w"] = obs.validos2
        oc = obs.outros1 - np.average(obs.outros1, weights=obs.w)
        beta = np.sum(obs.w * oc * (obs.d - np.average(obs.d, weights=obs.w))) / max(np.sum(obs.w * oc ** 2), 1e-9)
        beta *= W / (W + K0)
        obs["d0"] = obs.d - beta * oc
        mu = np.average(obs.d0, weights=obs.w) * W / (W + K0)
        g = obs.groupby("uf").apply(lambda x: pd.Series({"w": x.w.sum(), "m": np.average(x.d0, weights=x.w)}))
        mu_uf = ((g.w * g.m + k * mu) / (g.w + k)).to_dict()
        resid = obs.d0 - obs.uf.map(mu_uf)
        sig_mun = min(max(np.sqrt(np.average(resid ** 2, weights=obs.w)), 0.03), 0.25)
        oc_media = np.average(obs.outros1, weights=obs.w)
        gw = g.w
    else:
        beta, mu, mu_uf, sig_mun, gw = 0.0, 0.0, {}, 0.12, pd.Series(dtype=float)
        oc_media = np.average(m.outros1, weights=m.validos)
    frac = tot["apurado"]
    peso = W / (W + K0)
    sig_nac = 0.15 * (1 - peso) + 0.08 * (1 - frac) * peso + 0.005
    sig_uf = pd.Series({u: 0.10 * k / (gw.get(u, 0) + k) + 0.01 for u in m.uf.unique()})
    tot["modo"] = "previa" if len(obs) < 30 else "conteo"

    rng = np.random.default_rng(seed)
    m["oc"] = m.outros1 - oc_media
    pred = logit(m.base) + m.uf.map(mu_uf).fillna(mu) + beta * m.oc
    falta = m.falta.values
    ufs = m.uf.values
    lista_uf = list(sig_uf.index)
    idx_uf = np.array([lista_uf.index(u) for u in ufs])
    final = np.empty(sims)
    # Margens em votos (Lula − Flávio) no total, no Brasil e no exterior (UF "zz")
    ext = (m.uf == "zz").values
    marg = {"total": np.empty(sims), "dom": np.empty(sims), "ext": np.empty(sims)}
    lula_obs, flav_obs = m.lula2.sum(), m.flavio2.sum()
    obs_l, obs_f = m.lula2.values, m.flavio2.values
    for s in range(sims):
        e = rng.normal(0, sig_nac) + rng.normal(0, sig_uf.values)[idx_uf] + rng.normal(0, sig_mun, len(m)) * (falta > 0)
        p = 1 / (1 + np.exp(-(pred.values + e)))
        lula_m = obs_l + falta * p
        flav_m = obs_f + falta * (1 - p)
        lula = lula_m.sum()
        final[s] = lula / (lula_obs + flav_obs + falta.sum())
        marg["total"][s] = lula - flav_m.sum()
        marg["dom"][s] = lula_m[~ext].sum() - flav_m[~ext].sum()
        marg["ext"][s] = lula_m[ext].sum() - flav_m[ext].sum()
    m["pred"] = 1 / (1 + np.exp(-pred))
    res = {"modo": tot["modo"], "beta": beta, "mu": mu, "sig_mun": sig_mun, "final_med": np.median(final),
           "lo": np.quantile(final, .05), "hi": np.quantile(final, .95), "p_lula": (final > .5).mean(), "margens": marg}
    return m, res, tot


def rodar(sims):
    m, res, tot = projetar(sims)
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{agora}] ", end="")
    print(f"apurado ~{tot['apurado']:.1%} dos válidos esperados · Lula agora {tot['lula_atual']:.2%}")
    if res is None:
        print("poucos municípios apurados para projetar")
    else:
        print(f"PROJEÇÃO Lula {res['final_med']:.2%} [90%: {res['lo']:.2%}–{res['hi']:.2%}] · P(Lula vence) {res['p_lula']:.1%}")
        print(f"  desvio logit nacional {res['mu']:+.3f}, β outros {res['beta']:+.2f}, σ município {res['sig_mun']:.3f}")
        uf = m.groupby("uf").agg(apur=("validos2", "sum"), esp=("esperado", "sum"), l2=("lula2", "sum"), f2=("flavio2", "sum"))
        uf["%apur"] = (uf.apur / uf.esp).round(3)
        uf["lula%"] = (uf.l2 / (uf.l2 + uf.f2)).round(3)
        print(uf[["%apur", "lula%"]].sort_values("%apur").to_string())
        hist = HERE / "data" / "historico.csv"
        novo = not hist.exists()
        with open(hist, "a", newline="") as fh:
            w = csv.writer(fh)
            if novo:
                w.writerow(["hora", "apurado", "lula_atual", "lula_proj", "lo", "hi", "p_lula"])
            w.writerow([agora, f"{tot['apurado']:.4f}", f"{tot['lula_atual']:.4f}", f"{res['final_med']:.4f}",
                        f"{res['lo']:.4f}", f"{res['hi']:.4f}", f"{res['p_lula']:.3f}"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--loop", type=int, default=0, help="segundos entre projeções (0 = uma só)")
    a = ap.parse_args()
    while True:
        rodar(a.sims)
        if not a.loop:
            break
        time.sleep(a.loop)


