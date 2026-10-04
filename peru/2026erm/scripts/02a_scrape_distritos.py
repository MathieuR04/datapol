#!/usr/bin/env python3
"""Flujo A: totales oficiales por carrera, cada 60–90 s.

Dos peticiones por carrera, al nivel de **su** circunscripción (columna
`nivel_circunscripcion` de `carreras.csv`, nunca derivada del tipo):

    resumen-general/totales      actas totales y contabilizadas, emitidos
    {recurso de participantes}   votos por organización (incluye 80/81/82)

Son 2,118 carreras → ~4,240 peticiones por ciclo. A 5 workers, en EG 2026 el
equivalente distrital (~4,200) tomaba ~3 min; para caber en 90 s hacen falta
~10 workers, y **eso no se sube sin mirar los 429** (API-ONPE.md).

LO QUE HAY QUE CONFIRMAR CON EL SITIO EN VIVO
---------------------------------------------
- El nombre del recurso de participantes. En EG fue
  `eleccion-presidencial/participantes-ubicacion-geografica-nombre`; en ERM
  cambia por tipo de elección. Va por `--recurso`, con `{tipo}` sustituible si
  difiere entre tipos (p. ej. `--recurso-01 ... --recurso-04`).
- Cómo se nombran los ubigeos por nivel. `--probar RACE_ID` hace las dos
  peticiones de una carrera y las imprime, sin escribir nada más que el crudo.

CHECKPOINT
----------
Una carrera con 100% de actas contabilizadas se marca `resuelta` en
`interim/agregado/estado.json` y no se vuelve a pedir (salvo `--forzar`). Una
petición fallida no marca nada.

Salida, append-only:

    raw/onpe_vivo/agregado/{corte}/NNNNN.jsonl.gz
    interim/agregado/totales/{corte}.parquet         una fila por carrera
    interim/agregado/participantes/{corte}.parquet   una fila por (carrera, org)

Uso:
    uv run python scripts/02a_scrape_distritos.py --host https://... --recurso RUTA --probar 01-150000
    uv run python scripts/02a_scrape_distritos.py --host https://... --recurso RUTA
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from datapol.onpe import (COD_BLANCOS, COD_IMPUGNADOS, COD_NULOS,  # noqa: E402
                          Cliente, Crudo, nuevo_corte)

TOTALES = "resumen-general/totales"
FILTRO = {"departamento": "ubigeo_nivel_01", "provincia": "ubigeo_nivel_02",
          "distrito": "ubigeo_nivel_03"}


def ubigeos(ubigeo: str, nivel: str) -> tuple[str, str, str]:
    """(departamento, provincia, distrito) como los pide la API: 6 dígitos con
    ceros, vacíos por debajo del nivel de la carrera."""
    dep, prov = ubigeo[:2] + "0000", ubigeo[:4] + "00"
    if nivel == "departamento":
        return dep, "", ""
    if nivel == "provincia":
        return dep, prov, ""
    return dep, prov, ubigeo


def params(race: dict, id_eleccion: int) -> tuple[dict, dict]:
    nivel = race["nivel_circunscripcion"]
    d, p, di = ubigeos(race["ubigeo"], nivel)
    tot = {"idAmbitoGeografico": 1, "idEleccion": id_eleccion, "tipoFiltro": FILTRO[nivel],
           "idUbigeoDepartamento": d, "idUbigeoProvincia": p, "idUbigeoDistrito": di}
    par = {"tipoFiltro": FILTRO[nivel], "idAmbitoGeografico": 1,
           "ubigeoNivel1": d, "ubigeoNivel2": p, "ubigeoNivel3": di,
           "listContinentals": "", "listCountries": "", "idEleccion": id_eleccion}
    # La API no siempre tolera parámetros vacíos: se mandan solo los que tienen valor.
    return ({k: v for k, v in tot.items() if v != ""},
            {k: v for k, v in par.items() if v != "" or k.startswith("list")})


def data_de(cuerpo: str | None):
    if cuerpo is None:
        return None
    d = json.loads(cuerpo)
    if isinstance(d, dict) and "data" in d:
        return d["data"] if d.get("success", True) else None
    return d


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def parsea(race_id: str, corte: str, tot: dict, part: list) -> tuple[dict, list[dict]]:
    esp = {COD_BLANCOS: 0, COD_NULOS: 0, COD_IMPUGNADOS: 0}
    filas = []
    for e in part or []:
        cod = _int(e.get("codigoAgrupacionPolitica"))
        v = _int(e.get("totalVotosValidos"))
        if cod in esp:
            esp[cod] = v
            continue
        filas.append({"corte": corte, "race_id": race_id, "codigo_onpe": str(cod),
                      "agrupacion": (e.get("nombreAgrupacionPolitica")
                                     or e.get("descripcion") or "").strip(),
                      "votos": v})
    t = {"corte": corte, "race_id": race_id,
         "actas_total": _int(tot.get("totalActas")),
         "actas_contabilizadas": _int(tot.get("contabilizadas")),
         "emitidos": _int(tot.get("totalVotosEmitidos")),
         "validos": sum(f["votos"] for f in filas),
         "blancos": esp[COD_BLANCOS], "nulos": esp[COD_NULOS],
         "impugnados": esp[COD_IMPUGNADOS],
         "totales_json": json.dumps(tot, ensure_ascii=False)}
    return t, filas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--recurso", required=True,
                    help="ruta del endpoint de participantes; admite {tipo}")
    for t in ("01", "02", "03", "04"):
        ap.add_argument(f"--recurso-{t}", help=f"recurso solo para el tipo {t}")
    ap.add_argument("--data", type=Path, default=RAIZ / "data")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--tipos", default="01,02,03,04")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--probar", metavar="RACE_ID")
    a = ap.parse_args(argv)

    ref = a.data / "reference/id_eleccion.csv"
    if not ref.exists():
        print(f"falta {ref}: córrelo después de que 03_consolida_mesas.py haya descubierto los idEleccion")
        return 2
    id_de_tipo = {r.tipo: int(r.id_eleccion)
                  for r in pd.read_csv(ref, dtype=str).itertuples()}
    car = pd.read_csv(a.data / "reference/carreras.csv", dtype=str)
    car = car[car.tipo.isin(a.tipos.split(","))]
    if a.probar:
        car = car[car.race_id == a.probar]
        if car.empty:
            print(f"{a.probar} no está en carreras.csv")
            return 2

    recurso = {t: (getattr(a, f"recurso_{t}") or a.recurso).format(tipo=t)
               for t in ("01", "02", "03", "04")}

    ruta_estado = a.data / "interim/agregado/estado.json"
    ruta_estado.parent.mkdir(parents=True, exist_ok=True)
    estado = json.loads(ruta_estado.read_text()) if ruta_estado.exists() else {}
    races = [r._asdict() for r in car.itertuples(index=False)
             if a.forzar or a.probar or estado.get(r.race_id) != "resuelta"]

    corte = nuevo_corte()
    cli = Cliente(host=a.host.rstrip("/"), referer="/main/resumen")
    crudo = Crudo(a.data / "raw/onpe_vivo/agregado", corte)
    print(f"corte {corte} · {len(races):,} carreras por pedir")
    t0 = time.time()

    def una(r):
        pt, pp = params(r, id_de_tipo[r["tipo"]])
        st_t, c_t = cli.get(TOTALES, pt)
        st_p, c_p = cli.get(recurso[r["tipo"]], pp)
        return r, (pt, st_t, c_t), (pp, st_p, c_p)

    totales, part, fallidas = [], [], []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for r, (pt, st_t, c_t), (pp, st_p, c_p) in pool.map(una, races):
            crudo.guarda(TOTALES, pt, st_t, c_t)
            crudo.guarda(recurso[r["tipo"]], pp, st_p, c_p)
            if a.probar:
                print(f"\n--- {TOTALES} {pt}\n{st_t} {c_t[:1500] if c_t else c_t}")
                print(f"\n--- {recurso[r['tipo']]} {pp}\n{st_p} {c_p[:1500] if c_p else c_p}")
            try:
                tot, par = data_de(c_t), data_de(c_p)
            except ValueError:
                tot = par = None
            # Las dos o ninguna: una carrera a medias no se escribe.
            if st_t != 200 or st_p != 200 or tot is None or par is None:
                fallidas.append(r["race_id"])
                continue
            if isinstance(tot, list):
                tot = tot[0] if tot else {}
            t, filas = parsea(r["race_id"], corte, tot, par)
            totales.append(t)
            part.extend(filas)
    crudo.vuelca()
    if a.probar:
        return 0

    for nombre, filas in (("totales", totales), ("participantes", part)):
        d = a.data / f"interim/agregado/{nombre}"
        d.mkdir(parents=True, exist_ok=True)
        if filas:
            f = d / f"{corte}.parquet"
            if f.exists():
                raise FileExistsError(f)
            pd.DataFrame(filas).to_parquet(f, index=False)
    for t in totales:
        if t["actas_total"] and t["actas_contabilizadas"] >= t["actas_total"]:
            estado[t["race_id"]] = "resuelta"
    tmp = ruta_estado.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, separators=(",", ":")))
    tmp.replace(ruta_estado)

    dt = time.time() - t0
    print(f"listo en {dt:.0f} s · {len(totales):,} carreras · fallidas {len(fallidas)} · "
          f"resueltas acumuladas {sum(v == 'resuelta' for v in estado.values()):,}")
    print(f"contadores HTTP: {cli.contadores}")
    if fallidas:
        print("  fallidas:", " ".join(sorted(fallidas)[:20]), "…" if len(fallidas) > 20 else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
