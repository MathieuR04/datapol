#!/usr/bin/env python3
"""Flujo B: resultados por mesa desde `/actas/buscar/mesa`.

Una petición trae **todas** las elecciones de la mesa (gobernador, consejero,
alcalde provincial y, fuera de los cercados, alcalde distrital), así que el
barrido es del orden de las mesas, no de mesas × elecciones.

EL UNIVERSO DE MESAS
--------------------
Sale de `data/processed/mesas.parquet` (89,935, de la SAIP de la ONPE), no de un
rango ciego. `--rango 1-84992` agrega códigos fuera del maestro, para confirmar
en producción que no aparecen mesas que no conocíamos: un 204 es «no existe».

QUÉ SE ESCRIBE
--------------
Todo bajo `data/` del bloque 2026, nada se sobrescribe:

    raw/onpe_vivo/mesas/{corte}/NNNNN.jsonl.gz        respuesta tal cual
    interim/mesas/actas/{corte}-NNNNN.parquet         una fila por (mesa, elección)
    interim/mesas/votos/{corte}-NNNNN.parquet         una fila por (mesa, elección, org)
    interim/mesas/estado.json                         checkpoint

`03_consolida_mesas.py` arma desde ahí el último estado de cada acta.

CHECKPOINT Y MODO INCREMENTAL
-----------------------------
`estado.json` guarda, por mesa, `resuelta` (todas sus actas `C`), `pendiente`
o `inexistente` (204). Una mesa se marca **después** de que su crudo y sus filas
estén en disco. Una petición fallida no marca nada: se repite en la siguiente
corrida. (El 02b de EG 2026 la daba por hecha y la perdía para siempre.)

Sin `--update` se piden las mesas que no están en el checkpoint. Con
`--update`, además, las `pendiente`. Las `resuelta` no se vuelven a pedir salvo
con `--forzar`.

Uso:
    uv run python scripts/02b_scrape_mesas.py --host https://resultados.onpe.gob.pe
    uv run python scripts/02b_scrape_mesas.py --host ... --update
    uv run python scripts/02b_scrape_mesas.py --host ... --limite 50     # prueba corta
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from datapol.onpe import (CONTABILIZADA, Cliente, Crudo, actas_de,  # noqa: E402
                          nuevo_corte, parsea_acta)

RUTA = "actas/buscar/mesa"
VOLCAR_CADA = 2_000          # mesas por volcado a disco
PAUSA_CADA, PAUSA_S = 10_000, 5


def escribe_json(ruta: Path, obj) -> None:
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    tmp.replace(ruta)


def universo(data: Path, rango: str | None) -> list[str]:
    mesas = pd.read_parquet(data / "processed/mesas.parquet", columns=["mesa"]).mesa
    codigos = set(mesas.astype(str).str.zfill(6))
    if rango:
        for tramo in rango.split(","):
            a, b = (int(x) for x in tramo.split("-"))
            codigos |= {str(i).zfill(6) for i in range(a, b + 1)}
    return sorted(codigos)


def procesa(cuerpo: str, corte: str):
    """Cuerpo de una mesa -> (filas de acta, filas de voto, ¿resuelta?, rechazadas)."""
    actas, votos, rech = [], [], 0
    for a in actas_de(cuerpo):
        f, v = parsea_acta(a, corte)
        if f is None:
            rech += 1
            continue
        actas.append(f)
        votos.extend(v)
    resuelta = bool(actas) and rech == 0 and all(
        f["estado_acta"] == CONTABILIZADA for f in actas)
    return actas, votos, resuelta, rech


class Volcador:
    """Crudo → filas → checkpoint, en ese orden y desde un solo hilo."""

    def __init__(self, data: Path, corte: str, estado: dict, ruta_estado: Path):
        self.crudo = Crudo(data / "raw/onpe_vivo/mesas", corte)
        self.dir_a = data / "interim/mesas/actas"
        self.dir_v = data / "interim/mesas/votos"
        self.dir_a.mkdir(parents=True, exist_ok=True)
        self.dir_v.mkdir(parents=True, exist_ok=True)
        self.corte, self.estado, self.ruta_estado = corte, estado, ruta_estado
        self.actas, self.votos, self.marcas = [], [], {}
        self.n = 0

    def agrega(self, mesa, status, cuerpo, actas, votos, marca):
        self.crudo.guarda(RUTA, {"codigoMesa": mesa}, status, cuerpo)
        self.actas.extend(actas)
        self.votos.extend(votos)
        self.marcas[mesa] = marca

    def vuelca(self):
        if not self.marcas:
            return
        self.crudo.vuelca()
        sufijo = f"{self.corte}-{self.n:05d}.parquet"
        for d in (self.dir_a, self.dir_v):
            if (d / sufijo).exists():           # append-only: nunca se pisa
                raise FileExistsError(d / sufijo)
        if self.actas:
            pd.DataFrame(self.actas).to_parquet(self.dir_a / sufijo, index=False)
        if self.votos:
            pd.DataFrame(self.votos).to_parquet(self.dir_v / sufijo, index=False)
        self.estado.update(self.marcas)
        escribe_json(self.ruta_estado, self.estado)
        self.n += 1
        self.actas, self.votos, self.marcas = [], [], {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True,
                    help="p. ej. https://resultadoserm2026.onpe.gob.pe (sin barra final)")
    ap.add_argument("--data", type=Path, default=RAIZ / "data")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--update", action="store_true",
                    help="volver a pedir también las mesas pendientes")
    ap.add_argument("--forzar", action="store_true",
                    help="volver a pedir incluso las resueltas")
    ap.add_argument("--rango", help="códigos extra fuera del maestro, p. ej. 1-84992,900001-904943")
    ap.add_argument("--limite", type=int, help="pedir solo las primeras N (prueba)")
    a = ap.parse_args(argv)

    ruta_estado = a.data / "interim/mesas/estado.json"
    ruta_estado.parent.mkdir(parents=True, exist_ok=True)
    estado = json.loads(ruta_estado.read_text()) if ruta_estado.exists() else {}

    todas = universo(a.data, a.rango)
    if a.forzar:
        todo = todas
    elif a.update:
        todo = [m for m in todas if estado.get(m) not in ("resuelta", "inexistente")]
    else:
        todo = [m for m in todas if m not in estado]
    if a.limite:
        todo = todo[: a.limite]

    corte = nuevo_corte()
    print(f"corte {corte} · {len(todo):,} mesas por pedir "
          f"(checkpoint: {Counter(estado.values()) or 'vacío'})")
    if not todo:
        return 0

    cli = Cliente(host=a.host.rstrip("/"))
    vol = Volcador(a.data, corte, estado, ruta_estado)
    marcas, fallidas, rechazadas = Counter(), [], 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(cli.get, RUTA, {"codigoMesa": m}): m for m in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            mesa = futs[fut]
            status, cuerpo = fut.result()
            if status == 204:
                vol.agrega(mesa, 204, None, [], [], "inexistente")
                marcas["inexistente"] += 1
            elif status == 200:
                try:
                    actas, votos, resuelta, rech = procesa(cuerpo, corte)
                except (ValueError, KeyError, TypeError):
                    # Cuerpo que no es el JSON esperado: se archiva, no se marca.
                    vol.crudo.guarda(RUTA, {"codigoMesa": mesa}, 200, cuerpo)
                    fallidas.append(mesa)
                    continue
                rechazadas += rech
                marca = "resuelta" if resuelta else "pendiente"
                vol.agrega(mesa, 200, cuerpo, actas, votos, marca)
                marcas[marca] += 1
            else:
                fallidas.append(mesa)

            if i % VOLCAR_CADA == 0:
                vol.vuelca()
            if i % 1000 == 0 or i == len(todo):
                dt = time.time() - t0
                print(f"  [{i:6,}/{len(todo):,}] {i/dt:5.0f}/s  "
                      f"{dict(marcas)}  fallidas={len(fallidas)}  "
                      f"429={cli.contadores['429']} 503={cli.contadores['503']} "
                      f"403={cli.contadores['403']}", flush=True)
            if i % PAUSA_CADA == 0:
                time.sleep(PAUSA_S)
    vol.vuelca()
    if cli.bloqueado:
        print("\nDETENIDO: la ONPE responde con el desafío anti-bot de AWS WAF "
              "(x-amzn-waf-action: challenge). No se marcó ninguna mesa como hecha; "
              "no tiene sentido insistir desde esta conexión.")
        return 3

    dt = time.time() - t0
    print(f"\nlisto en {dt:,.0f} s · {dict(marcas)} · fallidas {len(fallidas)} · "
          f"actas rechazadas por la guarda {rechazadas}")
    print(f"contadores HTTP: {cli.contadores}")
    if fallidas:
        f = a.data / f"interim/mesas/fallidas-{corte}.txt"
        f.write_text("\n".join(sorted(fallidas)) + "\n")
        print(f"  fallidas -> {f} (se repiten solas en la siguiente corrida)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
