"""
04_scrape_results.py
Scrape puesto-level Senado results from Registraduría for ALL puestos
(national + exterior). Concurrency 20, retry once on failure.
Outputs:
  colombia/data/processed/resultados_puestos_raw.json
  colombia/data/processed/resultados_puestos.csv
"""

import asyncio
import aiohttp
import json
import pandas as pd
import time
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json"
HEADERS = {
    "Referer": "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, */*",
}
CONCURRENCY = 20
TIMEOUT = 30


def parse_puesto_json(code: str, data: dict) -> dict:
    """Flatten one puesto JSON into a single result dict."""
    totales = data.get("totales", {}).get("act", {})

    record = {
        "puesto_code":      code,
        "mesas_total":      totales.get("metota"),
        "mesas_escrutadas": totales.get("mesesc"),
        "censo":            totales.get("centota"),
        "votantes":         totales.get("votant"),
        "abstencion":       totales.get("absten"),
        "votos_nulos":      totales.get("votnul"),
        "votos_no_marcados":totales.get("votnma"),
        "votos_blanco":     totales.get("votblan"),
        "votos_validos":    totales.get("votval"),
    }

    # Flatten candidate votes: sum by (codcan, nomcan+apecan) across all camaras
    # partotabla entries are wrapped: {"act": {"codpar":..., "cantotabla": [...]}}
    candidate_votes: dict[str, int] = {}
    for camara in data.get("camaras", []):
        for partido_wrapper in camara.get("partotabla", []):
            partido = partido_wrapper.get("act", partido_wrapper)
            for cand in partido.get("cantotabla", []):
                codcan = int(cand.get("codcan", 0))
                name = f"{cand.get('nomcan', '')} {cand.get('apecan', '')}".strip()
                key = f"{codcan:06d}|{name}"
                vot = cand.get("vot")
                candidate_votes[key] = candidate_votes.get(key, 0) + (int(vot) if vot else 0)

    for key, vot in candidate_votes.items():
        record[f"cand_{key}"] = vot

    return record


async def fetch_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                    code: str) -> tuple[str, dict | None, str | None]:
    url = BASE_URL.format(code=code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404:
                        return code, None, "404"
                    if resp.status != 200:
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return code, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    return code, data, None
            except asyncio.TimeoutError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return code, None, "timeout"
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return code, None, str(e)
    return code, None, "semaphore_error"


async def scrape_all(codes: list[str]):
    results = []
    errors  = []
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
                results.append(parse_puesto_json(code, data))

            if done % 500 == 0 or done == len(codes):
                elapsed = time.time() - t0
                rate = done / elapsed
                remaining = (len(codes) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(codes)}] ok={len(results)} err={len(errors)} "
                      f"rate={rate:.0f}/s eta={remaining:.0f}s")

    return results, errors


def scrape():
    master = pd.read_csv(OUT / "puestos_master.csv", dtype=str)
    codes = master["puesto_code"].tolist()
    print(f"Scraping {len(codes):,} puestos (national + exterior) …")

    results, errors = asyncio.run(scrape_all(codes))

    print(f"\nDone: {len(results):,} ok, {len(errors):,} errors")

    # Save raw JSON
    raw_path = OUT / "resultados_puestos_raw.json"
    with open(raw_path, "w") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"Saved raw → {raw_path.name}")

    # Save errors log
    if errors:
        pd.DataFrame(errors).to_csv(OUT / "scrape_errors.csv", index=False)
        print(f"Errors logged → scrape_errors.csv")

    # Build wide CSV (one row per puesto, candidates as columns)
    df = pd.DataFrame(results).fillna(0)
    df.to_csv(OUT / "resultados_puestos.csv", index=False)
    print(f"Saved wide CSV → resultados_puestos.csv  ({len(df)} rows, {len(df.columns)} cols)")

    return df


if __name__ == "__main__":
    scrape()
