"""
scrape_mesas.py  —  Colombia Presidencial 2026, Primera Vuelta
Scrape mesa-level presidential results from Registraduría.
Concurrency 20, retry once on failure.

URL pattern discovered on election day — update BASE_URL below.
Expected: https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json
                     or similar (check Registraduría website on May 31, 2026)

Outputs:
  colombia/data/presidencial2026/processed/resultados_mesas.csv
  colombia/data/presidencial2026/processed/scrape_errors.csv
  colombia/data/presidencial2026/processed/results.json  (updated stats)
"""

import asyncio
import aiohttp
import argparse
import json
import csv
import time
from pathlib import Path

SHARED = Path(__file__).parent.parent.parent / "data" / "processed"          # senado shared data
OUT    = Path(__file__).parent.parent.parent / "data" / "presidencial2026" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

# ── UPDATE THIS on election day once Registraduría publishes results ──────────
BASE_URL   = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json"
SUMMARY_URL = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/00.json"
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "Referer":    "https://resultados1vuelta2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 20
TIMEOUT     = 30

# Candidate registry — populated from candidates.json; keys are Registraduría codcan
CANDIDATES_FILE = OUT / "candidates.json"


def load_candidates() -> dict[int, dict]:
    """Return {codcan: {code, nombre, partido, color}} from candidates.json."""
    with open(CANDIDATES_FILE) as f:
        cands = json.load(f)
    return {c["codcan"]: c for c in cands if "codcan" in c}


def parse_mesa_json(code: str, data: dict, cand_lookup: dict) -> dict:
    """
    Flatten one puesto JSON into a result dict.
    Presidential election: single camara, candidates listed directly in partotabla.
    """
    totales = data.get("totales", {}).get("act", {})
    record = {
        "puesto_code":       code,
        "mesas_total":       totales.get("metota"),
        "mesas_escrutadas":  totales.get("mesesc"),
        "censo":             totales.get("centota"),
        "votantes":          totales.get("votant"),
        "votos_nulos":       totales.get("votnul"),
        "votos_no_marcados": totales.get("votnma"),
        "votos_blanco":      totales.get("votbla") or totales.get("votblan"),
        "votos_validos":     totales.get("votval"),
    }

    # Presidential: partotabla contains one entry per candidate (codpar = candidate id)
    for camara in data.get("camaras", []):
        for cand_wrapper in camara.get("partotabla", []):
            cand = cand_wrapper.get("act", cand_wrapper)
            codcan = int(cand.get("codpar", 0))
            vot = cand.get("vot")
            if codcan > 0:
                info = cand_lookup.get(codcan, {})
                ckey = info.get("code", f"cand_{codcan:04d}")
                record[ckey] = record.get(ckey, 0) + (int(vot) if vot else 0)

    return record


async def fetch_one(session, sem, code):
    url = BASE_URL.format(code=code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404:
                        return code, None, "404"
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
    return code, None, "semaphore_error"


async def scrape_all(codes: list[str], cand_lookup: dict):
    results, errors = [], []
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, c) for c in codes]
        done = 0
        for coro in asyncio.as_completed(tasks):
            code, data, err = await coro
            done += 1
            if err:
                errors.append({"puesto_code": code, "error": err})
            elif data:
                results.append(parse_mesa_json(code, data, cand_lookup))
            if done % 500 == 0 or done == len(codes):
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (len(codes) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(codes)}] ok={len(results)} err={len(errors)} "
                      f"rate={rate:.0f}/s eta={eta:.0f}s")
    return results, errors


def puestos_needing_update() -> list[str]:
    path = OUT / "resultados_mesas.csv"
    if not path.exists():
        return []
    codes = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("mesas_escrutadas", 0) or 0) < int(row.get("mesas_total", 1) or 1):
                codes.append(row["puesto_code"])
    return codes


def scrape(update_mode: bool = False):
    # Load shared puestos_master (same tables as Senado)
    master_path = METADATA / "colombia_2026_municipio_electoral_roll.csv"
    codes = []
    with open(master_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            codes.append(row["puesto_code"])

    # Load candidate lookup (will be empty codcan until Registraduría publishes)
    try:
        cand_lookup = load_candidates()
    except Exception:
        print("WARNING: candidates.json not found or has no codcan field — candidate columns will use generic keys")
        cand_lookup = {}

    if update_mode:
        update_codes = puestos_needing_update()
        if not update_codes:
            print("All puestos fully escrutados — nothing to update.")
            return
        codes = update_codes
        print(f"Update mode: {len(codes):,} puestos not yet fully escrutados …")
    else:
        print(f"Scraping {len(codes):,} puestos …")

    results, errors = asyncio.run(scrape_all(codes, cand_lookup))
    print(f"\nDone: {len(results):,} ok, {len(errors):,} errors")

    if errors:
        keys = set()
        for e in errors: keys.update(e.keys())
        with open(OUT / "scrape_errors.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sorted(keys))
            w.writeheader(); w.writerows(errors)

    if not results:
        print("No results to save.")
        return

    # Write CSV (merge with existing in update mode)
    all_keys = set()
    for r in results: all_keys.update(r.keys())

    if update_mode and (OUT / "resultados_mesas.csv").exists():
        existing = []
        with open(OUT / "resultados_mesas.csv") as f:
            reader = csv.DictReader(f)
            existing = list(reader)
            all_keys.update(reader.fieldnames or [])
        new_codes = {r["puesto_code"] for r in results}
        kept = [r for r in existing if r["puesto_code"] not in new_codes]
        results = kept + results

    fieldnames = sorted(all_keys)
    with open(OUT / "resultados_mesas.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, 0) for k in fieldnames})

    print(f"Saved → resultados_mesas.csv  ({len(results):,} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape puestos not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
