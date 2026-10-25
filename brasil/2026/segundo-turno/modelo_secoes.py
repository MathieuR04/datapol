#!/usr/bin/env python3
"""Projeção do 2º turno com base em seções (urnas), não em municípios inteiros.

Diferença frente a modelo.py: dentro de um município parcialmente apurado, as urnas
que já chegaram não representam as que faltam (bairros diferentes). Aqui cada urna
é comparada com o seu próprio 1º turno:

  1. Base por seção (data/secoes/base_1t.parquet): b = Lula1 / (Lula1 + Flávio1).
  2. Desvio nas urnas já lidas (data/secoes/bu/*.jsonl): d = logit(Lula2/(Lula2+Flávio2)) − logit(b),
     com β·(outros1 − média) para o voto dos demais candidatos do 1º turno.
  3. Desvio hierárquico: município → UF → nacional, cada nível encolhido para o de cima
     (pseudo-votos k_mun, k_uf), e o nacional para 0 (a prévia) com peso W / (W + K0).
  4. Votos que faltam por município: apurado oficial do TSE (arquivo do município) contra
     o esperado; a fração de Lula nos que faltam é a média, ponderada pelos válidos do 1º
     turno, da previsão das urnas ainda não lidas desse município.
  5. Monte Carlo: erro nacional + UF + município sobre os votos que faltam.

Interface igual à de modelo.projetar: devolve (m, res, tot).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import modelo

HERE = Path(__file__).resolve().parent


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def base():
    b = pd.read_parquet(HERE / "data" / "secoes" / "base_1t.parquet")
    b["mun"] = b.mun.astype(str).str.zfill(5)
    b["zona"] = b.zona.astype(str).str.zfill(4)
    b["secao"] = b.secao.astype(str).str.zfill(4)
    b["id"] = b.uf + b.mun
    b["b"] = b.lula1 / (b.lula1 + b.flavio1).clip(lower=1)
    b["outros1"] = 1 - (b.lula1 + b.flavio1) / b.validos1.clip(lower=1)
    return b


def lidas():
    filas = []
    for f in (HERE / "data" / "secoes" / "bu").glob("*.jsonl"):
        for ln in f.read_text().splitlines():
            if ln:
                filas.append(json.loads(ln))
    if not filas:
        return pd.DataFrame(columns=["uf", "mun", "zona", "secao", "lula", "flavio"])
    return pd.DataFrame(filas).drop_duplicates(["uf", "mun", "zona", "secao"], keep="last")


def projetar(sims=4000, k_mun=2_000, k_uf=50_000, K0=1_500_000, seed=1):
    # Municípios: apurado oficial e esperado (como em modelo.py)
    m, _, tot = modelo.projetar(sims=50)
    b = base()
    bu = lidas()
    s = b.merge(bu[["uf", "mun", "zona", "secao", "lula", "flavio"]], on=["uf", "mun", "zona", "secao"], how="left")
    s["lida"] = s.lula.notna()
    o = s[s.lida & ((s.lula + s.flavio) > 0) & (s.uf != "zz")].copy()
    tot["secoes_lidas"] = int(s.lida.sum())
    tot["secoes_total"] = int(len(s))

    W = float((o.lula + o.flavio).sum())
    if len(o) >= 50:
        o["w"] = o.lula + o.flavio
        o["d"] = logit(o.lula / o.w) - logit(o.b)
        oc_media = np.average(o.outros1, weights=o.w)
        oc = o.outros1 - oc_media
        beta = np.sum(o.w * oc * (o.d - np.average(o.d, weights=o.w))) / max(np.sum(o.w * oc ** 2), 1e-9)
        beta *= W / (W + K0)
        o["d0"] = o.d - beta * oc
        mu = np.average(o.d0, weights=o.w) * W / (W + K0)
        o["wd"] = o.w * o.d0
        g_uf = o.groupby("uf")[["w", "wd"]].sum()
        g_uf["m"] = g_uf.wd / g_uf.w
        mu_uf = (g_uf.w * g_uf.m + k_uf * mu) / (g_uf.w + k_uf)
        o["mu_uf"] = o.uf.map(mu_uf)
        g_m = o.groupby("id")[["w", "wd"]].sum()
        g_m["m"] = g_m.wd / g_m.w
        g_m["uf"] = g_m.index.str[:2]
        mu_m = (g_m.w * g_m.m + k_mun * g_m.uf.map(mu_uf)) / (g_m.w + k_mun)
        # Dispersão entre municípios (para os que não têm urnas lidas)
        dm = g_m.m - g_m.uf.map(mu_uf)
        sig_mun = float(np.clip(np.sqrt(np.average(dm ** 2, weights=g_m.w)), 0.03, 0.30))
        modo = "secoes"
    else:
        beta, mu, oc_media, sig_mun, modo = 0.0, 0.0, np.average(s.outros1, weights=s.validos1), 0.12, "previa"
        mu_uf, mu_m, g_uf, g_m = pd.Series(dtype=float), pd.Series(dtype=float), pd.DataFrame(columns=["w"]), pd.DataFrame(columns=["w"])

    # Previsão por urna não lida
    s["pred"] = logit(s.b) + beta * (s.outros1 - oc_media)
    s["mu"] = s.id.map(mu_m)
    s["mu"] = s.mu.fillna(s.uf.map(mu_uf)).fillna(mu)
    s["p"] = 1 / (1 + np.exp(-(s.pred + s.mu)))
    faltam = s[~s.lida]
    v = faltam.validos1.clip(lower=1)
    q = (faltam.p * v).groupby(faltam.id).sum() / v.groupby(faltam.id).sum()
    m["p_falta"] = q.reindex(m.index)
    # Municípios sem seções na base (ou todas lidas): usa o modelo municipal
    m["p_falta"] = m.p_falta.fillna(m.pred)

    frac = tot["apurado"]
    peso = W / (W + K0)
    sig_nac = 0.15 * (1 - peso) + 0.06 * (1 - frac) * peso + 0.004
    w_uf = g_uf.w if len(g_uf) else pd.Series(dtype=float)
    sig_uf = pd.Series({u: 0.10 * k_uf / (w_uf.get(u, 0) + k_uf) + 0.01 for u in m.uf.unique()})
    w_m = g_m.w.reindex(m.index).fillna(0) if len(g_m) else pd.Series(0.0, index=m.index)
    sig_m = (sig_mun * k_mun / (w_m + k_mun)).values

    rng = np.random.default_rng(seed)
    lista_uf = list(sig_uf.index)
    idx_uf = np.array([lista_uf.index(u) for u in m.uf.values])
    falta = m.falta.values
    lp = logit(m.p_falta.values)
    ext = (m.uf == "zz").values
    obs_l, obs_f = m.lula2.values, m.flavio2.values
    final = np.empty(sims)
    marg = {"total": np.empty(sims), "dom": np.empty(sims), "ext": np.empty(sims)}
    den = obs_l.sum() + obs_f.sum() + falta.sum()
    for i in range(sims):
        e = rng.normal(0, sig_nac) + rng.normal(0, sig_uf.values)[idx_uf] + rng.normal(0, 1, len(m)) * sig_m
        p = 1 / (1 + np.exp(-(lp + e)))
        lm, fm = obs_l + falta * p, obs_f + falta * (1 - p)
        final[i] = lm.sum() / den
        marg["total"][i] = lm.sum() - fm.sum()
        marg["dom"][i] = lm[~ext].sum() - fm[~ext].sum()
        marg["ext"][i] = lm[ext].sum() - fm[ext].sum()
    tot["modo"] = modo
    res = {"modo": modo, "beta": beta, "mu": mu, "sig_mun": sig_mun, "final_med": np.median(final),
           "lo": np.quantile(final, .05), "hi": np.quantile(final, .95), "p_lula": (final > .5).mean(),
           "margens": marg}
    return m, res, tot


if __name__ == "__main__":
    m, res, tot = projetar(2000)
    print({k: tot[k] for k in ("apurado", "secoes_lidas", "secoes_total", "modo")})
    print({k: round(float(v), 4) for k, v in res.items() if k not in ("margens", "modo")})
    a, r2, t2 = modelo.projetar(2000)
    print("municipal:", {k: round(float(v), 4) for k, v in r2.items() if k not in ("margens", "modo")})
