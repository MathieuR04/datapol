#!/usr/bin/env python3
"""Regressão ecológica 1º → 2º turno por seção: para onde foi cada eleitor do 1º turno.

Unidade: seção (urna). Em cada seção, proporções do eleitorado apto:
  1º turno  Lula, Flávio, Cury, Renan, Caiado, outros, branco+nulo, abstenção
  2º turno  Lula, Flávio, branco+nulo, abstenção
O eleitorado apto vem do BU do 2º turno (o cadastro é o mesmo nos dois turnos); a
abstenção do 1º é aptos − votos do 1º. Seções incoerentes (votos do 1º > aptos) saem.

Modelo: Y = X · B, com B (8×4) de probabilidades de transição (linhas ≥ 0 que somam 1),
por mínimos quadrados ponderados pelo eleitorado. Estima-se por UF (reduz o viés
ecológico: a transição pode variar entre estados) e agrega-se ao nacional ponderando
cada linha pelo tamanho da categoria do 1º turno em cada UF.

Advertência: inferência ecológica supõe que, dentro de cada UF, a transição é igual
em todas as seções. Os números são estimativas do fluxo médio, não de indivíduos.

Uso: python3 regressao_ecologica.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import modelo_secoes as ms

HERE = Path(__file__).resolve().parent
ORIG = ["Lula", "Flávio", "Cury", "Renan", "Caiado", "Outros", "Branco/nulo", "Abstenção"]
DEST = ["Lula", "Flávio", "Branco/nulo", "Abstenção"]


def dados():
    b = pd.read_parquet(HERE / "data" / "secoes" / "base_1t_full.parquet")
    for c, w in (("mun", 5), ("zona", 4), ("secao", 4)):
        b[c] = b[c].astype(str).str.zfill(w)
    vc = [c for c in b.columns if c.startswith("v")]
    outros = [c for c in vc if c not in ("v13", "v22", "v70", "v14", "v55", "v95", "v96")]
    x = pd.DataFrame({"Lula": b.v13, "Flávio": b.v22, "Cury": b.v70, "Renan": b.v14, "Caiado": b.v55,
                      "Outros": b[outros].sum(axis=1), "Branco/nulo": b.v95 + b.v96})
    x[["uf", "mun", "zona", "secao"]] = b[["uf", "mun", "zona", "secao"]]
    bu = ms.lidas()
    d = x.merge(bu, on=["uf", "mun", "zona", "secao"])
    d = d[(d.uf != "zz") & d.apt.notna() & (d.apt > 0)]
    d["apt"] = d.apt.astype(float)
    votos1 = d[ORIG[:-1]].sum(axis=1)
    d = d[votos1 <= d.apt * 1.01]
    d["Abstenção"] = (d.apt - votos1).clip(lower=0)
    y = pd.DataFrame({"Lula": d.lula, "Flávio": d.flavio, "Branco/nulo": d.branco + d.nulo,
                      "Abstenção": (d.apt - d.comp).clip(lower=0)}, index=d.index)
    return d, y


def ajusta(X, Y, w):
    """min Σ w ||y − x B||², B ≥ 0, linhas somam 1."""
    K, J = X.shape[1], Y.shape[1]
    w = w / w.sum()                      # escala: sin esto SLSQP no converge
    A = (X * w[:, None]).T @ X
    C = (X * w[:, None]).T @ Y

    def f(v):
        B = v.reshape(K, J)
        return np.trace(B.T @ A @ B) - 2 * np.trace(B.T @ C)

    def g(v):
        B = v.reshape(K, J)
        return (2 * A @ B - 2 * C).ravel()

    cons = [{"type": "eq", "fun": lambda v, k=k: v.reshape(K, J)[k].sum() - 1} for k in range(K)]
    v0 = np.full(K * J, 1 / J)
    r = minimize(f, v0, jac=g, bounds=[(0, 1)] * (K * J), constraints=cons, method="SLSQP",
                 options={"maxiter": 2000, "ftol": 1e-15})
    if not r.success:
        print("   aviso: optimizador no convergió:", r.message)
    return r.x.reshape(K, J)


def main():
    d, y = dados()
    print(f"{len(d):,} seções do país com BU do 2º turno e 1º turno ({d.uf.nunique()} UFs)\n")
    fluxo = np.zeros((len(ORIG), len(DEST)))   # eleitores (contagem) de cada origem → destino
    por_uf = {}
    for uf, g in d.groupby("uf"):
        if len(g) < 200:
            continue
        X = (g[ORIG].values / g.apt.values[:, None])
        Y = (y.loc[g.index, DEST].values / g.apt.values[:, None])
        B = ajusta(X, Y, g.apt.values)
        por_uf[uf] = B
        fluxo += g[ORIG].sum().values[:, None] * B
    T = fluxo / fluxo.sum(axis=1, keepdims=True)
    tab = pd.DataFrame(100 * T, index=ORIG, columns=DEST).round(1)
    tab["Eleitores 1º (amostra)"] = fluxo.sum(axis=1).round(0).astype(int)
    print("Transição 1º → 2º turno (% de cada grupo do 1º turno), agregado das UFs:\n")
    print(tab.to_string())
    # Validação: totais do 2º turno implícitos vs observados
    pred = fluxo.sum(axis=0)
    obs = y.loc[d[d.uf.isin(por_uf)].index, DEST].sum().values
    print("\nTotais do 2º turno — implícitos vs observados (seções usadas):")
    for k, n in enumerate(DEST):
        print(f"  {n:12s} {pred[k]:>12,.0f} {obs[k]:>12,.0f}")
    tab.to_csv(HERE / "data" / "transicao_1t_2t.csv")
    pd.concat({u: pd.DataFrame(100 * B, index=ORIG, columns=DEST).round(1) for u, B in por_uf.items()}).to_csv(
        HERE / "data" / "transicao_1t_2t_uf.csv")


if __name__ == "__main__":
    main()
