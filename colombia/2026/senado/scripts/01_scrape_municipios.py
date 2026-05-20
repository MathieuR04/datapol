"""
scrape_municipios.py  —  Senado 2026
Fast municipio-level scraper for MAP data.

Hits ~1,100 municipio endpoints instead of 14,430 puesto endpoints.
~13x fewer requests → finishes in seconds, perfect for frequent refreshes.

The Registraduría API returns the same JSON structure at every level;
passing a 7-digit mpio_reg_code gives the municipio aggregate directly.

URL pattern:
  puesto  → SE/1600001010046.json   (13 digits)
  municipio → SE/1600001.json        (7 digits)  ← this script
  dept    → SE/16.json              (2 digits)
  national → SE/00.json

Use --update to only re-fetch municipios where mesas_escrutadas < mesas_total.

Outputs:
  colombia/2026/senado/data/processed/resultados_municipios_raw.json
  colombia/2026/senado/data/processed/resultados_municipios.csv
  (then run aggregate.py → build_geojson.py to get map-ready GeoJSON)
"""

import asyncio
import aiohttp
import argparse
import json
import csv
import time
from pathlib import Path

SHARED = Path(__file__).parent.parent.parent.parent / "shared" / "data" / "processed"
OUT = Path(__file__).parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json"
HEADERS = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 20
TIMEOUT     = 30


def parse_mpio_json(code: str, data: dict) -> dict:
    """
    Parse the municipio-level JSON response.
    Structure is identical to puesto-level but already aggregated.
    Two camaras: cam=0 (nacional), cam=4 (indígena).
    """
    totales = data.get("totales", {}).get("act", {})

    nat_t, ind_t = {}, {}
    for camara in data.get("camaras", []):
        cam = int(camara.get("cam", 0))
        ct  = camara.get("totales", {}).get("act", {})
        if   cam == 0: nat_t = ct
        elif cam == 4: ind_t = ct

    record = {
        "mpio_reg_code_7":   code,
        "mesas_total":        totales.get("metota"),
        "mesas_escrutadas":   totales.get("mesesc"),
        "censo":              totales.get("centota"),
        "votantes":           nat_t.get("votant")  or totales.get("votant"),
        "abstencion":         nat_t.get("absten")  or totales.get("absten"),
        "votos_nulos":        nat_t.get("votnul")  or totales.get("votnul"),
        "votos_no_marcados":  nat_t.get("votnma")  or totales.get("votnma"),
        "votos_blanco":       nat_t.get("votbla")  or totales.get("votblan"),
        "votos_validos":      nat_t.get("votval")  or totales.get("votval"),
        "ind_votantes":       int(ind_t.get("votant") or 0),
        "ind_votos_validos":  int(ind_t.get("votval") or 0),
        "ind_votos_blanco":   int(ind_t.get("votbla") or ind_t.get("votblan") or 0),
        "ind_votos_nulos":    int(ind_t.get("votnul") or 0),
    }

    # Party totals per camara
    for camara in data.get("camaras", []):
        cam  = int(camara.get("cam", 0))
        pcol = "indig" if cam == 4 else "party"
        for pw in camara.get("partotabla", []):
            partido = pw.get("act", pw)
            codpar  = int(partido.get("codpar", 0))
            vot     = partido.get("vot")
            pkey    = f"{pcol}_{codpar:04d}"
            record[pkey] = record.get(pkey, 0) + (int(vot) if vot else 0)

    return record


async def fetch_one(session, sem, code):
    url = BASE_URL.format(code=code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404: return code, None, "404"
                    if resp.status != 200:
                        if attempt == 0: await asyncio.sleep(1); continue
                        return code, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    return code, data, None
            except asyncio.TimeoutError:
                if attempt == 0: await asyncio.sleep(2); continue
                return code, None, "timeout"
            except Exception as e:
                if attempt == 0: await asyncio.sleep(1); continue
                return code, None, str(e)
    return code, None, "semaphore"


async def scrape_all(codes):
    results, errors = [], []
    sem = asyncio.Semaphore(CONCURRENCY)
    t0  = time.time()
    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, c) for c in codes]
        done  = 0
        for coro in asyncio.as_completed(tasks):
            code, data, err = await coro
            done += 1
            if err:   errors.append({"mpio_reg_code_7": code, "error": err})
            elif data: results.append(parse_mpio_json(code, data))
            if done % 100 == 0 or done == len(codes):
                elapsed = time.time() - t0
                rate    = done / elapsed
                eta     = (len(codes) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(codes)}] ok={len(results)} err={len(errors)} "
                      f"rate={rate:.0f}/s eta={eta:.0f}s")
    return results, errors


def municipios_needing_update() -> list[str]:
    path = OUT / "results/colombia_2026_municipio_senado_nacional.csv"
    if not path.exists(): return []
    codes = []
    with open(path) as f:
        for row in csv.DictReader(f):
            me = int(row.get("mesas_escrutadas") or 0)
            mt = int(row.get("mesas_total") or 1)
            if me < mt:
                codes.append(row["mpio_reg_code_7"])
    return codes


def scrape(update_mode: bool = False):
    # Get unique municipio codes from puestos_master (excludes exterior)
    codes = []
    seen  = set()
    with open(METADATA / "colombia_2026_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            if row["is_exterior"] == "True": continue
            code = row["mpio_reg_code_7"]
            if code not in seen:
                seen.add(code)
                codes.append(code)

    if update_mode:
        update_codes = municipios_needing_update()
        if not update_codes:
            print("All municipios fully escrutados — nothing to update.")
            return
        codes = update_codes
        print(f"Update mode: {len(codes):,} municipios not yet fully escrutados …")
    else:
        print(f"Scraping {len(codes):,} municipio endpoints …")

    results, errors = asyncio.run(scrape_all(codes))
    print(f"\nDone: {len(results):,} ok, {len(errors):,} errors")

    if errors:
        with open(OUT / "scrape_errors.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["mpio_reg_code_7", "error"])
            w.writeheader(); w.writerows(errors)

    if not results: return

    all_keys = set()
    for r in results: all_keys.update(r.keys())

    if update_mode and (OUT / "results/colombia_2026_municipio_senado_nacional.csv").exists():
        existing = []
        with open(OUT / "results/colombia_2026_municipio_senado_nacional.csv") as f:
            reader  = csv.DictReader(f)
            existing = list(reader)
            all_keys.update(reader.fieldnames or [])
        new_codes = {r["mpio_reg_code_7"] for r in results}
        kept      = [r for r in existing if r["mpio_reg_code_7"] not in new_codes]
        results   = kept + results

    fieldnames = sorted(all_keys)
    with open(OUT / "results/colombia_2026_municipio_senado_nacional.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, 0) for k in fieldnames})

    print(f"Saved → resultados_municipios.csv  ({len(results):,} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape municipios not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
