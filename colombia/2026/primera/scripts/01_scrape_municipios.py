"""
scrape_municipios.py  —  Presidencial 2026, Primera Vuelta
Fast municipio-level scraper for MAP data. ~1,100 requests, done in seconds.
Run frequently (every 1-5 min) for live map updates.

URL pattern: update BASE_URL on election day (May 31, 2026).
Expected: https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json
where {code} is the 7-digit mpio_reg_code_7 for municipio-level aggregates.

Outputs:
  colombia/2026/presidencial_1ra/data/processed/resultados_municipios.csv
  colombia/2026/presidencial_1ra/data/processed/results.json  (updated header stats)
"""

import asyncio
import aiohttp
import argparse
import json
import csv
import datetime
import time
from pathlib import Path
from collections import defaultdict

SHARED = Path(__file__).parent.parent.parent.parent / "shared" / "data" / "processed"
OUT = Path(__file__).parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

# ── UPDATE on election day ────────────────────────────────────────────────────
BASE_URL    = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json"
SUMMARY_URL = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/00.json"
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "Referer":    "https://resultados1vuelta2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 20
TIMEOUT     = 30


def load_candidate_lookup() -> dict[int, str]:
    """Return {codpar (Registraduria int) → candidate_code (our string)} from candidates.json."""
    cand_path = OUT / "candidates.json"
    if not cand_path.exists():
        return {}
    with open(cand_path) as f:
        cands = json.load(f)
    return {c["codcan"]: c["code"] for c in cands if "codcan" in c}


def parse_mpio_json(code: str, data: dict, cand_lookup: dict) -> dict:
    """
    Parse municipio-level presidential JSON.
    Presidential: partotabla lists candidates directly (one entry per candidate).
    codpar in partotabla = codcan of the candidate.
    """
    totales = data.get("totales", {}).get("act", {})
    record = {
        "mpio_reg_code_7":   code,
        "mesas_total":        totales.get("metota"),
        "mesas_escrutadas":   totales.get("mesesc"),
        "censo":              totales.get("centota"),
        "votantes":           totales.get("votant"),
        "votos_nulos":        totales.get("votnul"),
        "votos_no_marcados":  totales.get("votnma"),
        "votos_blanco":       totales.get("votbla") or totales.get("votblan"),
        "votos_validos":      totales.get("votval"),
    }

    for camara in data.get("camaras", []):
        for cw in camara.get("partotabla", []):
            cand  = cw.get("act", cw)
            codpar = int(cand.get("codpar", 0))
            vot    = cand.get("vot")
            if codpar > 0:
                key = cand_lookup.get(codpar, f"cand_{codpar:04d}")
                record[key] = record.get(key, 0) + (int(vot) if vot else 0)

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


async def scrape_all(codes, cand_lookup):
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
            if err:    errors.append({"mpio_reg_code_7": code, "error": err})
            elif data: results.append(parse_mpio_json(code, data, cand_lookup))
            if done % 100 == 0 or done == len(codes):
                elapsed = time.time() - t0
                rate    = done / elapsed
                eta     = (len(codes) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(codes)}] ok={len(results)} err={len(errors)} "
                      f"rate={rate:.0f}/s eta={eta:.0f}s")
    return results, errors


def municipios_needing_update() -> list[str]:
    path = OUT / "results/colombia_2026_municipio_primera.csv"
    if not path.exists(): return []
    codes = []
    with open(path) as f:
        for row in csv.DictReader(f):
            me = int(row.get("mesas_escrutadas") or 0)
            mt = int(row.get("mesas_total") or 1)
            if me < mt:
                codes.append(row["mpio_reg_code_7"])
    return codes


def update_results_json(rows: list[dict], cand_lookup_rev: dict):
    """Update national totals in results.json after scraping."""
    results_path = OUT / "results.json"
    if not results_path.exists(): return

    with open(results_path) as f:
        results = json.load(f)

    # Sum national totals
    totals = defaultdict(float)
    for r in rows:
        for k in ("votantes","votos_validos","votos_blanco","votos_nulos",
                  "mesas_total","mesas_escrutadas"):
            try: totals[k] += float(r.get(k) or 0)
            except (ValueError, TypeError): pass
        for code_str in cand_lookup_rev.values():
            try: totals[code_str] += float(r.get(code_str) or 0)
            except (ValueError, TypeError): pass

    results["votantes"]         = int(totals["votantes"])
    results["votos_validos"]    = int(totals["votos_validos"])
    results["votos_blanco"]     = int(totals["votos_blanco"])
    results["votos_nulos"]      = int(totals["votos_nulos"])
    results["mesas_escrutadas"] = int(totals["mesas_escrutadas"])
    censo = float(results.get("censo") or 1)
    results["turnout_pct"] = round(totals["votantes"] / censo * 100, 2)
    mt = totals["mesas_total"] or 1
    results["pct_mesas"] = round(totals["mesas_escrutadas"] / mt * 100, 2)
    vv = totals["votos_validos"] or 1
    for c in results.get("candidates", []):
        v = int(totals.get(c["code"], 0))
        c["votes"]    = v
        c["vote_pct"] = round(v / vv * 100, 2)
    results["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"

    with open(results_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  results.json updated  ({results['pct_mesas']:.1f}% mesas, "
          f"turnout {results['turnout_pct']:.1f}%)")


def scrape(update_mode: bool = False):
    cand_lookup = load_candidate_lookup()   # codpar → code string

    codes, seen = [], set()
    with open(METADATA / "colombia_2026_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            if row["is_exterior"] == "True": continue
            code = row["mpio_reg_code_7"]
            if code not in seen:
                seen.add(code); codes.append(code)

    if update_mode:
        upd = municipios_needing_update()
        if not upd:
            print("All municipios fully escrutados — nothing to update."); return
        codes = upd
        print(f"Update mode: {len(codes):,} municipios not yet fully escrutados …")
    else:
        print(f"Scraping {len(codes):,} municipio endpoints (presidencial) …")

    results, errors = asyncio.run(scrape_all(codes, cand_lookup))
    print(f"\nDone: {len(results):,} ok, {len(errors):,} errors")

    if errors:
        with open(OUT / "scrape_errors.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["mpio_reg_code_7","error"])
            w.writeheader(); w.writerows(errors)

    if not results: return

    all_keys = set()
    for r in results: all_keys.update(r.keys())

    if update_mode and (OUT / "results/colombia_2026_municipio_primera.csv").exists():
        existing = []
        with open(OUT / "results/colombia_2026_municipio_primera.csv") as f:
            reader   = csv.DictReader(f)
            existing = list(reader)
            all_keys.update(reader.fieldnames or [])
        new_codes = {r["mpio_reg_code_7"] for r in results}
        kept      = [r for r in existing if r["mpio_reg_code_7"] not in new_codes]
        results   = kept + results

    fieldnames = sorted(all_keys)
    with open(OUT / "results/colombia_2026_municipio_primera.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, 0) for k in fieldnames})

    print(f"Saved → resultados_municipios.csv  ({len(results):,} rows)")
    update_results_json(results, {v: v for v in cand_lookup.values()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    scrape(update_mode=args.update)
