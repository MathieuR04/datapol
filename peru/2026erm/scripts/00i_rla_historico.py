#!/usr/bin/env python3
"""Las tres elecciones previas de López Aliaga en Lima Metropolitana, por distrito.

Alimenta la pestaña RLA. La cuarta, ERM 2026 (alcaldía de Lima, carrera
`03-140100`), no va aquí: la página la lee en vivo de `carrera/03-140100.json`.

    EG 2021   presidencial, 1.ª vuelta   VOTOS_P13 (Renovación Popular)
    ERM 2022  alcaldía de Lima           código ONPE 00000003 (Renovación Popular)
    EG 2026   presidencial, 1.ª vuelta   cand_35 (López Aliaga)

El porcentaje es **sobre votos válidos** en las tres, que es como la ONPE reporta
y como se reportará ERM 2026.

VERIFICACIÓN DE LAS COLUMNAS
----------------------------
- EG 2021: VOTOS_P13 suma 11.75% nacional, el resultado oficial de López Aliaga;
  P11 (Fujimori) 13.41% y P16 (Castillo) 18.92% también cuadran.
- ERM 2022: `00000003` es «RENOVACION POPULAR» en `peru/2022erm/data/carrera/03-140100.json`.
- EG 2026: `cand_35` es «RAFAEL BERNARDO LÓPEZ ALIAGA CAZORLA» en
  `peru/2026eg/primera/data/candidates.json`.

Las tres fuentes usan el ubigeo electoral (Lima Metropolitana = 1401xx), el mismo
que ERM 2026. Un distrito que falte en una fuente sale `null`, no cero.

Uso:
    uv run python scripts/00i_rla_historico.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DATAPOL = RAIZ.parents[1]
HOME_DATA = Path.home() / "Documents/electoral_data/peru"


def eg2021(ruta: Path) -> pd.DataFrame:
    d = pd.read_csv(ruta, sep=";", dtype={"UBIGEO": str}, encoding="latin-1")
    d = d[d.UBIGEO.str.startswith("1401")]
    v = [f"VOTOS_P{i}" for i in range(1, 19)]
    d[v] = d[v].fillna(0)
    g = d.groupby("UBIGEO")[v].sum()
    return pd.DataFrame({"votos": g["VOTOS_P13"], "validos": g[v].sum(axis=1)})


def erm2022(ruta: Path) -> pd.DataFrame:
    c = json.load(open(ruta))
    filas = {x["ubigeo"]: (x["votos"].get("00000003", 0), sum(x["votos"].values()))
             for x in c["desagregado_niveles"]["distrito"]}
    return pd.DataFrame.from_dict(filas, orient="index", columns=["votos", "validos"])


def eg2026(ruta: Path) -> pd.DataFrame:
    d = pd.read_csv(ruta, dtype={"ubigeo_distrito": str})
    d = d[d.ubigeo_distrito.str.startswith("1401")].set_index("ubigeo_distrito")
    cands = [c for c in d.columns if c.startswith("cand_")]
    return pd.DataFrame({"votos": d["cand_35"], "validos": d[cands].sum(axis=1)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eg2021", type=Path, default=HOME_DATA / "historico/presidencial_2021.csv")
    ap.add_argument("--erm2022", type=Path,
                    default=DATAPOL / "peru/2022erm/data/carrera/03-140100.json")
    ap.add_argument("--eg2026", type=Path,
                    default=DATAPOL / "peru/2026eg/primera/data/results/peru_2026eg_distrito_primera.csv")
    ap.add_argument("--out", type=Path, default=RAIZ / "data/rla.json")
    a = ap.parse_args()

    dis = pd.read_csv(RAIZ / "data/reference/distritos.csv", dtype=str)
    dis = dis[dis.ubigeo_distrito.str.startswith("1401")].set_index("ubigeo_distrito")
    fuentes = {"eg2021": eg2021(a.eg2021), "erm2022": erm2022(a.erm2022),
               "eg2026": eg2026(a.eg2026)}

    distritos = []
    for u in sorted(dis.index):
        fila = {"ubigeo": u, "nombre": dis.loc[u, "nombre_distrito"]}
        for k, f in fuentes.items():
            if u in f.index and f.loc[u, "validos"] > 0:
                fila[k] = {"votos": int(f.loc[u, "votos"]), "validos": int(f.loc[u, "validos"])}
            else:
                fila[k] = None
        distritos.append(fila)

    total = {k: {"votos": int(f.votos.sum()), "validos": int(f.validos.sum())}
             for k, f in fuentes.items()}
    out = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ambito": "Lima Metropolitana (provincia de Lima, 43 distritos)",
        "medida": "porcentaje de votos válidos",
        "elecciones": [
            {"id": "eg2021", "etiqueta": "EG 2021", "cargo": "Presidente (1.ª vuelta)"},
            {"id": "erm2022", "etiqueta": "ERM 2022", "cargo": "Alcalde de Lima"},
            {"id": "eg2026", "etiqueta": "EG 2026", "cargo": "Presidente (1.ª vuelta)"},
            {"id": "erm2026", "etiqueta": "ERM 2026", "cargo": "Alcalde de Lima",
             "en_vivo": "carrera/03-140100.json"},
        ],
        "total": total,
        "distritos": distritos,
    }
    a.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

    print(f"{len(distritos)} distritos de Lima Metropolitana → {a.out}")
    for k, t in total.items():
        faltan = sum(d[k] is None for d in distritos)
        print(f"  {k:8} {100 * t['votos'] / t['validos']:5.1f}%  "
              f"({t['votos']:,} de {t['validos']:,} válidos)  distritos sin dato: {faltan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
