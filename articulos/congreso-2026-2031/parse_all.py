#!/usr/bin/env python3
"""Parsea todos los PDF del manifiesto, incrementalmente, y consolida.

Caché por PDF en data/parsed/<camara>/<stem>.{csv,json}; el .json guarda el
sha256 del PDF, así que un PDF re-publicado con otro contenido se re-parsea
solo, y uno ya parseado no se vuelve a tocar (el OCR es lo caro).

Salidas consolidadas:
  data/votos.csv     una fila por miembro × votación (voto final, tras constancias)
  data/paginas.csv   una fila por página: tipo, fecha, asunto, validación, avisos

Run: python3 parse_all.py [--force] [--jobs 4]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import pandas as pd

import parser as P

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CACHE = DATA / "parsed"


def run(force: bool = False, jobs: int = 4) -> pd.DataFrame:
    roster = json.loads((DATA / "roster.json").read_text(encoding="utf-8"))
    with open(DATA / "pdfs" / "manifest.csv", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    for m in manifest:
        pdf = DATA / "pdfs" / m["archivo"]
        stem = pdf.stem
        out_csv = CACHE / m["camara"] / f"{stem}.csv"
        out_json = out_csv.with_suffix(".json")
        if not force and out_json.exists():
            prev = json.loads(out_json.read_text(encoding="utf-8"))
            if prev.get("sha256") == m["sha256"]:
                continue
        print(f"parseando [{m['camara']}] {pdf.name} …", flush=True)
        df, meta = P.parse_pdf(str(pdf), m["camara"], roster, jobs=jobs)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)
        out_json.write_text(json.dumps(
            {"sha256": m["sha256"], "camara": m["camara"], "fecha_sesion": m["fecha"],
             "orden": m["orden"], "url": m["url"], "paginas": meta},
            ensure_ascii=False, indent=1), encoding="utf-8")
        v = [p for p in meta if p["kind"] == "VOTACION"]
        ok = sum(p["validacion"] == "ok" for p in v)
        print(f"  {len(meta)} págs, {len(v)} votaciones, {ok}/{len(v)} validadas", flush=True)

    # ── consolidar ──
    votos, paginas = [], []
    for m in manifest:
        stem = Path(m["archivo"]).stem
        base = CACHE / m["camara"] / stem
        if not base.with_suffix(".json").exists():
            continue
        meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        for p in meta["paginas"]:
            paginas.append({
                "camara": m["camara"], "pdf": stem, "fecha_sesion": m["fecha"],
                "orden_sesion": m["orden"], "url": m["url"], "pagina": p["page"],
                "tipo": p["kind"], "fecha": p["date"], "hora": p["time"],
                "asunto": p["asunto"], "validacion": p["validacion"],
                "n_filas": p["n_filas"], "constancia": p["constancia_text"],
                "nota": p.get("nota", ""),
                "avisos": " | ".join(p["warnings"]),
            })
        if base.with_suffix(".csv").stat().st_size > 1:
            try:
                d = pd.read_csv(base.with_suffix(".csv"), keep_default_na=False, dtype=str)
            except pd.errors.EmptyDataError:
                continue
            d["fecha_sesion"], d["url"] = m["fecha"], m["url"]
            votos.append(d)
    pg = pd.DataFrame(paginas)
    pg.to_csv(DATA / "paginas.csv", index=False)
    vt = pd.concat(votos, ignore_index=True) if votos else pd.DataFrame()
    vt.to_csv(DATA / "votos.csv", index=False)

    v = pg[pg.tipo == "VOTACION"]
    print("\n── resumen ──")
    for cam, g in v.groupby("camara"):
        print(f"  {cam:<10} {len(g):>4} votaciones · validación: "
              + ", ".join(f"{k} {n}" for k, n in g.validacion.value_counts().items()))
    otros = pg[~pg.tipo.isin(["VOTACION", "ASISTENCIA"])]
    if len(otros):
        print("  páginas no votación/asistencia:",
              ", ".join(f"{r.pdf}:p{r.pagina} {r.tipo}" for r in otros.itertuples()))
    print(f"wrote data/votos.csv ({len(vt):,} filas), data/paginas.csv ({len(pg)} págs)")
    return vt


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="re-parsear todo")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    run(a.force, a.jobs)
