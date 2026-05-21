"""
05_scrape_mesa_censo.py
Scrape registered-voter census (centota) for every mesa from the Registraduría
senate endpoint and fill the `censo` column in colombia_2026_mesa_electoral_roll.csv.

The senate endpoint returns census data per mesa even before election day — it is
the physical roll of voters assigned to each voting table.

Usage:
  python3 05_scrape_mesa_censo.py            # scrape all ~126k mesas
  python3 05_scrape_mesa_censo.py --update   # only re-scrape rows where censo is null/0

Reads:  colombia/2026/metadata/colombia_2026_mesa_electoral_roll.csv
Writes: same file (updates censo column in place)
        colombia/2026/metadata/raw/mesa_censo_errors.csv  (failed requests)
"""

import asyncio
import aiohttp
import argparse
import time
import pandas as pd
from pathlib import Path

METADATA = Path(__file__).parent.parent
OUT      = METADATA  # errors file goes in raw/

BASE_URL    = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json"
HEADERS     = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 80
TIMEOUT     = 45


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    mesa_code: str,
) -> tuple[str, int | None, str | None]:
    """Return (mesa_code, censo, error_str)."""
    url = BASE_URL.format(code=mesa_code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404:
                        return mesa_code, None, "404"
                    if resp.status != 200:
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return mesa_code, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    censo = data.get("totales", {}).get("act", {}).get("centota")
                    return mesa_code, (int(censo) if censo is not None else None), None
            except asyncio.TimeoutError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return mesa_code, None, "timeout"
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return mesa_code, None, str(e)[:120]
    return mesa_code, None, "failed"


async def scrape_all(mesa_codes: list[str]) -> tuple[dict[str, int], list[dict]]:
    """Returns (censo_map, errors) where censo_map: mesa_code → censo."""
    censo_map: dict[str, int] = {}
    errors: list[dict] = []
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    total = len(mesa_codes)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, mc) for mc in mesa_codes]
        done = 0
        for coro in asyncio.as_completed(tasks):
            mesa_code, censo, err = await coro
            done += 1
            if err and err != "404":
                errors.append({"mesa_code": mesa_code, "error": err})
            elif censo is not None:
                censo_map[mesa_code] = censo

            if done % 5000 == 0 or done == total:
                elapsed = time.time() - t0
                rate    = done / elapsed if elapsed > 0 else 0
                eta     = (total - done) / rate / 60 if rate > 0 else 0
                print(f"  [{done:,}/{total:,}]  ok={len(censo_map):,}  "
                      f"err={len(errors)}  rate={rate:.0f}/s  eta={eta:.1f}min")

    return censo_map, errors


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only scrape mesas where censo is currently null or 0")
    args = parser.parse_args()

    roll_path = METADATA / "colombia_2026_mesa_electoral_roll.csv"
    if not roll_path.exists():
        raise FileNotFoundError(
            f"{roll_path.name} not found. Run 04_build_mesa_electoral_roll.py first."
        )

    print(f"Loading {roll_path.name} …")
    df = pd.read_csv(roll_path, dtype={"mesa_code": str, "puesto_code": str})

    # Ensure censo column exists
    if "censo" not in df.columns:
        df["censo"] = None

    # Decide which rows to scrape
    if args.update:
        mask = df["censo"].isna() | (pd.to_numeric(df["censo"], errors="coerce").fillna(0) == 0)
        to_scrape = df.loc[mask, "mesa_code"].tolist()
        print(f"  --update: {len(to_scrape):,} mesas with missing/zero censo")
    else:
        to_scrape = df["mesa_code"].tolist()
        print(f"  Full scrape: {len(to_scrape):,} mesas")

    if not to_scrape:
        print("Nothing to scrape. All rows already have censo.")
        return

    print(f"Scraping census data (concurrency={CONCURRENCY}) …")
    censo_map, errors = asyncio.run(scrape_all(to_scrape))

    # Apply results back to dataframe
    df["censo"] = df["mesa_code"].map(censo_map).combine_first(df["censo"])
    df["censo"] = pd.to_numeric(df["censo"], errors="coerce").astype("Int64")

    df.to_csv(roll_path, index=False)
    print(f"\nSaved → {roll_path}")

    filled   = df["censo"].notna().sum()
    missing  = df["censo"].isna().sum()
    print(f"  Filled: {filled:,}  Still missing: {missing:,}  Errors: {len(errors)}")

    if errors:
        err_path = METADATA / "raw" / "mesa_censo_errors.csv"
        pd.DataFrame(errors).to_csv(err_path, index=False)
        print(f"  Errors → {err_path}")


if __name__ == "__main__":
    main()
