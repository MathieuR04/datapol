#!/usr/bin/env python3
"""1º turno presidencial por seção com todos os votáveis (para a regressão ecológica).

Saída: data/secoes/base_1t_full.parquet — uma coluna por votável (v13, v22, …, v95 branco,
v96 nulo) + chave da seção. Também imprime o total nacional por votável.
"""
import zipfile
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
z = zipfile.ZipFile(HERE / "data" / "abertos" / "votacao_secao_2026_BR.zip")
cols = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]
partes, nomes = [], {}
for ch in pd.read_csv(z.open("votacao_secao_2026_BR.csv"), sep=";", encoding="latin1", usecols=cols, chunksize=3_000_000):
    ch = ch[ch.CD_CARGO == 1]
    nomes.update(dict(zip(ch.NR_VOTAVEL, ch.NM_VOTAVEL)))
    partes.append(ch.groupby(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_VOTAVEL"]).QT_VOTOS.sum())
v = pd.concat(partes).groupby(level=list(range(5))).sum().unstack("NR_VOTAVEL", fill_value=0)
v.columns = [f"v{c}" for c in v.columns]
v = v.reset_index()
v.columns = ["uf", "mun", "zona", "secao"] + list(v.columns[4:])
v["uf"] = v.uf.str.lower()
v.to_parquet(HERE / "data" / "secoes" / "base_1t_full.parquet")
tot = v.filter(like="v").sum().sort_values(ascending=False)
for c, n in tot.items():
    print(f"{c:5s} {n:>12,}  {nomes.get(int(c[1:]), '')}")
