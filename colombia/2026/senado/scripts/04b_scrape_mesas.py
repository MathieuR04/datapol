"""
04b_scrape_mesas.py
Scrape mesa-level Senado results — the finest granularity available.
Each mesa code = puesto_code (13 chars) + mesa_num zero-padded to 6 digits.

Modes:
  python3 04b_scrape_mesas.py           # full scrape of all ~126k mesas
  python3 04b_scrape_mesas.py --update  # only re-scrape mesas for puestos
                                        # not yet fully escrutados

Outputs:
  colombia/data/processed/resultados_mesas.csv
      one row per mesa: mesa_code, puesto_code, mesa_num, + vote columns
  colombia/data/processed/resultados_mesas_errors.csv
"""

import asyncio
import aiohttp
import argparse
import json
import pandas as pd
import time
from pathlib import Path

OUT = Path(__file__).parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json"
HEADERS = {
    "Referer": "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, */*",
}
CONCURRENCY = 80
TIMEOUT = 45


def build_mesa_codes(master: pd.DataFrame, puesto_filter: set[str] | None = None) -> list[tuple[str, str, int]]:
    """
    Return list of (mesa_code, puesto_code, mesa_num) for all mesas to scrape.
    If puesto_filter is given, only include those puestos.
    """
    master["num_mesas"] = pd.to_numeric(master["num_mesas"], errors="coerce").fillna(0).astype(int)
    codes = []
    for _, row in master.iterrows():
        pcode = row["puesto_code"]
        if puesto_filter is not None and pcode not in puesto_filter:
            continue
        for i in range(1, row["num_mesas"] + 1):
            codes.append((f"{pcode}{i:06d}", pcode, i))
    return codes


def parse_mesa_json(mesa_code: str, puesto_code: str, mesa_num: int, data: dict) -> dict:
    totales = data.get("totales", {}).get("act", {})
    record = {
        "mesa_code":        mesa_code,
        "puesto_code":      puesto_code,
        "mesa_num":         mesa_num,
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
    for camara in data.get("camaras", []):
        for partido_wrapper in camara.get("partotabla", []):
            partido = partido_wrapper.get("act", partido_wrapper)
            for cand in partido.get("cantotabla", []):
                codcan = int(cand.get("codcan", 0))
                name = f"{cand.get('nomcan', '')} {cand.get('apecan', '')}".strip()
                key = f"cand_{codcan:06d}|{name}"
                vot = cand.get("vot")
                record[key] = record.get(key, 0) + (int(vot) if vot else 0)
    return record


async def fetch_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                    mesa_code: str, puesto_code: str, mesa_num: int
                    ) -> tuple[str, str, int, dict | None, str | None]:
    url = BASE_URL.format(code=mesa_code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404:
                        return mesa_code, puesto_code, mesa_num, None, "404"
                    if resp.status != 200:
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return mesa_code, puesto_code, mesa_num, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    return mesa_code, puesto_code, mesa_num, data, None
            except asyncio.TimeoutError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return mesa_code, puesto_code, mesa_num, None, "timeout"
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return mesa_code, puesto_code, mesa_num, None, str(e)[:120]
    return mesa_code, puesto_code, mesa_num, None, "failed"


async def scrape_all(mesa_tuples: list[tuple[str, str, int]]):
    results, errors = [], []
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    total = len(mesa_tuples)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, mc, pc, mn) for mc, pc, mn in mesa_tuples]
        done = 0
        for coro in asyncio.as_completed(tasks):
            mesa_code, puesto_code, mesa_num, data, err = await coro
            done += 1
            if err and err != "404":
                errors.append({"mesa_code": mesa_code, "puesto_code": puesto_code, "error": err})
            elif data:
                results.append(parse_mesa_json(mesa_code, puesto_code, mesa_num, data))

            if done % 2000 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed
                remaining = (total - done) / rate if rate > 0 else 0
                print(f"  [{done:,}/{total:,}] ok={len(results):,} err={len(errors)} "
                      f"rate={rate:.0f}/s eta={remaining/60:.1f}min")
    return results, errors


def load_existing() -> pd.DataFrame | None:
    path = OUT / "resultados_mesas.csv"
    if path.exists():
        print(f"  Loading existing {path.name} …")
        return pd.read_csv(path, dtype={"mesa_code": str, "puesto_code": str})
    return None


def puestos_needing_update() -> set[str]:
    """Return puesto codes where mesas_escrutadas < mesas_total in puesto results."""
    puesto_path = OUT / "resultados_puestos.csv"
    if not puesto_path.exists():
        raise FileNotFoundError("Run 04_scrape_results.py first to get puesto-level results.")
    puestos = pd.read_csv(puesto_path, dtype={"puesto_code": str},
                          usecols=["puesto_code", "mesas_total", "mesas_escrutadas"])
    puestos["mesas_total"]      = pd.to_numeric(puestos["mesas_total"],      errors="coerce").fillna(0)
    puestos["mesas_escrutadas"] = pd.to_numeric(puestos["mesas_escrutadas"], errors="coerce").fillna(0)
    incomplete = puestos[puestos["mesas_escrutadas"] < puestos["mesas_total"]]
    print(f"  Puestos not fully escrutados: {len(incomplete):,} / {len(puestos):,}")
    return set(incomplete["puesto_code"])


def merge_update(existing: pd.DataFrame, new_results: list[dict]) -> pd.DataFrame:
    """Merge new mesa results into existing DataFrame, replacing updated rows."""
    if not new_results:
        return existing
    new_df = pd.DataFrame(new_results)
    # Drop old rows for updated puestos, append new
    updated_puestos = set(new_df["puesto_code"])
    kept = existing[~existing["puesto_code"].isin(updated_puestos)]
    merged = pd.concat([kept, new_df], ignore_index=True)
    # Align columns (new candidates may appear)
    return merged


def scrape(update_mode: bool = False):
    print(f"Mode: {'UPDATE (incomplete puestos only)' if update_mode else 'FULL'}")

    master = pd.read_csv(OUT / "colombia_2026_electoral_roll.csv", dtype=str)

    puesto_filter = None
    if update_mode:
        puesto_filter = puestos_needing_update()
        if not puesto_filter:
            print("All puestos fully escrutados — nothing to update.")
            return
        print(f"  Scraping mesas for {len(puesto_filter):,} puestos …")

    mesa_tuples = build_mesa_codes(master, puesto_filter)
    print(f"  Total mesas to fetch: {len(mesa_tuples):,}")

    results, errors = asyncio.run(scrape_all(mesa_tuples))
    print(f"\nDone: {len(results):,} ok, {len(errors)} errors")

    if errors:
        pd.DataFrame(errors).to_csv(OUT / "resultados_mesas_errors.csv", index=False)

    if not results:
        print("No results — nothing to save.")
        return

    new_df = pd.DataFrame(results)

    if update_mode:
        existing = load_existing()
        if existing is not None:
            new_df = merge_update(existing, results)
            print(f"  Merged: {len(new_df):,} total mesa rows")

    new_df.to_csv(OUT / "resultados_mesas.csv", index=False)
    print(f"Saved → resultados_mesas.csv  ({len(new_df):,} rows, {len(new_df.columns)} cols)")

    return new_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape mesas for puestos not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
