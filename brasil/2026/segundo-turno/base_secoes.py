#!/usr/bin/env python3
"""Linha de base por seção: resultado do 1º turno presidencial (TSE, votacao_secao_2026_BR).

Saída: data/secoes/base_1t.parquet com uf, mun, zona, secao, local, lula1, flavio1, validos1.
Válidos = votos nominais (NR_VOTAVEL ≠ 95 branco, 96 nulo).
"""
import zipfile
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
z = zipfile.ZipFile(HERE / "data" / "abertos" / "votacao_secao_2026_BR.zip")
cols = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO", "NR_VOTAVEL", "QT_VOTOS", "NR_LOCAL_VOTACAO"]
partes = []
for ch in pd.read_csv(z.open("votacao_secao_2026_BR.csv"), sep=";", encoding="latin1", usecols=cols, chunksize=2_000_000):
    ch = ch[ch.CD_CARGO == 1]
    ch["lula1"] = ch.QT_VOTOS.where(ch.NR_VOTAVEL == 13, 0)
    ch["flavio1"] = ch.QT_VOTOS.where(ch.NR_VOTAVEL == 22, 0)
    ch["validos1"] = ch.QT_VOTOS.where(~ch.NR_VOTAVEL.isin([95, 96]), 0)
    partes.append(ch.groupby(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"])[["lula1", "flavio1", "validos1"]].sum())
    print(len(partes), flush=True)
b = pd.concat(partes).groupby(level=[0, 1, 2, 3, 4]).sum().reset_index()
b.columns = ["uf", "mun", "zona", "secao", "local", "lula1", "flavio1", "validos1"]
b["uf"] = b.uf.str.lower()
b.to_parquet(HERE / "data" / "secoes" / "base_1t.parquet")
print(len(b), "seções", b[["lula1", "flavio1", "validos1"]].sum().to_dict())
