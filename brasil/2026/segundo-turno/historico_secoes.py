#!/usr/bin/env python3
"""¿En qué % de seções un candidato de 2da vuelta tiene menos votos que en la 1ra?
Seções del país (sin exterior), con ambas vueltas. TSE votacao_secao_<año>_BR.

Uso: python3 historico_secoes.py
"""
import zipfile
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
CANDS = {2022: {13: "Lula", 22: "Bolsonaro"}, 2018: {17: "Bolsonaro", 13: "Haddad"}, 2014: {13: "Dilma", 45: "Aécio"}}
KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]

for ano, cands in CANDS.items():
    z = zipfile.ZipFile(HERE / "data" / "abertos" / f"votacao_secao_{ano}_BR.zip")
    nome = next(n for n in z.namelist() if n.endswith(".csv"))
    cols = KEY + ["NR_TURNO", "CD_CARGO", "NR_VOTAVEL", "QT_VOTOS"]
    partes = []
    for ch in pd.read_csv(z.open(nome), sep=";", encoding="latin1", usecols=cols, chunksize=3_000_000):
        ch = ch[(ch.CD_CARGO == 1) & ch.NR_VOTAVEL.isin(list(cands)) & (ch.SG_UF != "ZZ")]
        partes.append(ch.groupby(KEY + ["NR_TURNO", "NR_VOTAVEL"]).QT_VOTOS.sum())
    v = pd.concat(partes).groupby(level=list(range(6))).sum().unstack(["NR_TURNO", "NR_VOTAVEL"]).dropna()
    print(f"\n{ano}: {len(v):,} seções con ambas vueltas")
    ambos = None
    for nr, nm in cands.items():
        d = v[(2, nr)] - v[(1, nr)]
        perde = d < 0
        ambos = perde if ambos is None else (ambos & perde)
        print(f"  {nm:10s} pierde votos en {perde.mean():6.1%} de seções ({perde.sum():,}) · mediana {d.median():+.0f}")
    print(f"  ambos pierden en {ambos.mean():.1%}")
