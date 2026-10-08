#!/usr/bin/env python3
"""Proyectos de ley 2026-2031 y sus firmantes (autor, coautores, adherentes).

Fuente: el backend del portal de proyectos (wb2server.congreso.gob.pe/spley-portal),
una SPA Angular que consulta

    POST https://api.congreso.gob.pe/spley-portal-service/proyecto-ley/lista-con-filtro
         {"perParId": 2026, "codTipoParl": "D"|"S", "pageSize": n, "rowStart": k}
         → lista paginada (rowsTotal), con `autores` como texto plano sin rol
    GET  https://api.congreso.gob.pe/spley-portal-service/expediente/<anio>/<num>?codTipoParl=D
         → detalle; `firmantes` trae tipoFirmanteId (1 Autor, 2 Coautor,
           3 Adherente) y congresistaId estable

En el detalle, <anio> y <num> van cifrados AES-ECB/PKCS7 en base64url sin
relleno, con la clave ENCRYPTION_KEY que trae el bundle público del portal
(`main-es2015.*.js`). Es lo mismo que hace el navegador de cualquier visitante;
si el portal cambia la clave, el detalle devuelve 400 y hay que releerla del
bundle. El servidor rechaza el User-Agent por defecto de urllib (403): se usa
el de scrape_sesiones.

Bicameralidad: casi toda iniciativa entra por Diputados (sufijo -CD); el Senado
tiene su propia numeración (-S), mayormente del Ejecutivo y otros proponentes.

Caché: data/proyectos/<camara>/<num>.json (el detalle crudo). Los firmantes
pueden cambiar después de presentado (adherentes que se suman), así que se
vuelve a bajar el detalle de los proyectos presentados en los últimos
--refrescar días (30 por defecto); --todo rebaja todos.

Salida: data/proyectos.csv (uno por proyecto) y data/firmantes.csv (uno por
firma: proyecto × congresista × rol).
Run: python3 scrape_proyectos.py [--camara D|S] [--todo] [--refrescar 30]
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scrape_sesiones import SSL_CONTEXT, USER_AGENT, fetch

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "proyectos"
API = "https://api.congreso.gob.pe/spley-portal-service"
PERIODO = 2026
CLAVE = b"ProdALg5ZrAsxBMD"   # ENCRYPTION_KEY del bundle del portal
ROLES = {1: "autor", 2: "coautor", 3: "adherente"}
CAMARAS = {"D": "diputados", "S": "senado"}
PAUSA = 0.25


def cifrar(s: str) -> str:
    p = padding.PKCS7(128).padder()
    datos = p.update(s.encode()) + p.finalize()
    e = Cipher(algorithms.AES(CLAVE), modes.ECB()).encryptor()
    c = e.update(datos) + e.finalize()
    return base64.urlsafe_b64encode(c).decode().rstrip("=")


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": USER_AGENT,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=60) as r:
        return json.load(r)


def lista(cod: str, paso: int = 200) -> list[dict]:
    filas, k = [], 0
    while True:
        d = post(f"{API}/proyecto-ley/lista-con-filtro",
                 {"perParId": PERIODO, "codTipoParl": cod, "pageSize": paso, "rowStart": k})
        lote = d["data"]["proyectos"]
        filas += lote
        total = lote[0]["rowsTotal"] if lote else 0
        k += paso
        if not lote or k >= total:
            break
        time.sleep(PAUSA)
    return filas


def detalle(num: int, cod: str) -> dict:
    url = f"{API}/expediente/{cifrar(str(PERIODO))}/{cifrar(str(num))}?codTipoParl={cod}"
    d = json.loads(fetch(url))
    if d.get("code") != 200:
        raise RuntimeError(f"{cod}{num}: {d.get('status')}")
    return d["data"]


def run(camaras=("D", "S"), todo: bool = False, refrescar: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    proyectos, firmas = [], []
    corte = (date.today() - timedelta(days=refrescar)).isoformat()
    for cod in camaras:
        carpeta = CACHE / CAMARAS[cod]
        carpeta.mkdir(parents=True, exist_ok=True)
        filas = lista(cod)
        bajados = 0
        for f in filas:
            path = carpeta / f"{f['pleyNum']}.json"
            if todo or not path.exists() or f["fecPresentacion"][:10] >= corte:
                path.write_text(json.dumps(detalle(f["pleyNum"], cod), ensure_ascii=False))
                bajados += 1
                time.sleep(PAUSA)
            d = json.loads(path.read_text())
            g = d["general"]
            proyectos.append({
                "camara": CAMARAS[cod], "num": f["pleyNum"], "proyecto": g["proyectoLey"],
                "fecha": g["fecPresentacion"][:10], "proponente": g["desProponente"],
                "grupo": g.get("desGpar"), "estado": g["desEstado"],
                "legislatura": g.get("desLegis"), "titulo": g["titulo"],
                "n_firmantes": len(d.get("firmantes") or []),
                "url": f"https://wb2server.congreso.gob.pe/spley-portal/#/"
                       f"{'diputados' if cod == 'D' else 'senado'}/expediente/{PERIODO}/{f['pleyNum']}",
            })
            for s in d.get("firmantes") or []:
                firmas.append({
                    "camara": CAMARAS[cod], "num": f["pleyNum"], "proyecto": g["proyectoLey"],
                    "fecha": g["fecPresentacion"][:10], "congresista_id": s["congresistaId"],
                    "nombre": s["nombre"], "rol": ROLES.get(s["tipoFirmanteId"], s["tipoFirmanteId"]),
                    "sexo": s.get("sexo"),
                })
        print(f"[{CAMARAS[cod]}] {len(filas)} proyectos ({bajados} detalles bajados)", flush=True)
    P, F = pd.DataFrame(proyectos), pd.DataFrame(firmas)
    P.to_csv(HERE / "data" / "proyectos.csv", index=False)
    F.to_csv(HERE / "data" / "firmantes.csv", index=False)
    print(f"wrote data/proyectos.csv ({len(P)}), data/firmantes.csv ({len(F)} firmas)")
    return P, F


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--camara", choices=["D", "S"])
    ap.add_argument("--todo", action="store_true", help="rebajar el detalle de todos")
    ap.add_argument("--refrescar", type=int, default=30)
    a = ap.parse_args()
    run((a.camara,) if a.camara else ("D", "S"), a.todo, a.refrescar)
