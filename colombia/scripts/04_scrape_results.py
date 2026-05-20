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
import argparse
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
    """Flatten one puesto JSON into a single result dict.

    The Registraduría SE endpoint contains two concurrent elections in one JSON:
      cam=0  Circunscripción Nacional Ordinaria  (100 seats)
      cam=4  Circunscripción Especial Indígena   (2 seats)
    They are stored in separate camaras[] entries with their own totales and
    partotabla.  We keep them separate:
      party_XXXX / cand_XXXX   → nacional (cam=0)
      indig_XXXX / icand_XXXX  → indígena (cam=4)
    Vote-count fields (votantes, votos_validos, …) come from the nacional camara.
    Mesa counts (mesas_total, mesas_escrutadas, censo) come from the top-level
    totales, which is physical-location data shared by both elections.
    """
    totales = data.get("totales", {}).get("act", {})

    # Pull per-camara vote totals so nacional and indígena counts stay separate.
    nat_t: dict = {}
    ind_t: dict = {}
    for camara in data.get("camaras", []):
        cam = int(camara.get("cam", 0))
        ct = camara.get("totales", {}).get("act", {})
        if cam == 0:
            nat_t = ct
        elif cam == 4:
            ind_t = ct

    # Prefer camara-level nacional counts; fall back to top-level for exterior
    # puestos which may only have one camara without the cam=4 entry.
    record = {
        "puesto_code":        code,
        "mesas_total":        totales.get("metota"),
        "mesas_escrutadas":   totales.get("mesesc"),
        "censo":              totales.get("centota"),
        # Nacional constituency vote counts
        "votantes":           nat_t.get("votant")  or totales.get("votant"),
        "abstencion":         nat_t.get("absten")  or totales.get("absten"),
        "votos_nulos":        nat_t.get("votnul")  or totales.get("votnul"),
        "votos_no_marcados":  nat_t.get("votnma")  or totales.get("votnma"),
        "votos_blanco":       nat_t.get("votbla")  or totales.get("votblan"),
        "votos_validos":      nat_t.get("votval")  or totales.get("votval"),
        # Indígena constituency vote counts (0 for exterior / non-indigenous puestos)
        "ind_votantes":       int(ind_t.get("votant") or 0),
        "ind_votos_validos":  int(ind_t.get("votval") or 0),
        "ind_votos_blanco":   int(ind_t.get("votbla") or ind_t.get("votblan") or 0),
        "ind_votos_nulos":    int(ind_t.get("votnul") or 0),
    }

    # Party totals + candidate votes — separated by cam value.
    # Composite candidate key avoids codcan=0 ("SOLO POR LA LISTA") collisions.
    for camara in data.get("camaras", []):
        cam = int(camara.get("cam", 0))
        pcol = "indig" if cam == 4 else "party"
        ccol = "icand" if cam == 4 else "cand"

        for partido_wrapper in camara.get("partotabla", []):
            partido = partido_wrapper.get("act", partido_wrapper)
            codpar = int(partido.get("codpar", 0))
            party_vot = partido.get("vot")
            pkey = f"{pcol}_{codpar:04d}"
            record[pkey] = record.get(pkey, 0) + (int(party_vot) if party_vot else 0)

            for cand in partido.get("cantotabla", []):
                codcan = int(cand.get("codcan", 0))
                cand_name = f"{cand.get('nomcan', '')} {cand.get('apecan', '')}".strip()
                ckey = f"{ccol}_{codpar:04d}_{codcan:06d}|{cand_name}"
                vot = cand.get("vot")
                record[ckey] = record.get(ckey, 0) + (int(vot) if vot else 0)

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


def puestos_needing_update() -> list[str]:
    """Return puesto codes with incomplete mesas + any previously errored puestos."""
    codes = set()

    path = OUT / "resultados_puestos.csv"
    if path.exists():
        df = pd.read_csv(path, dtype={"puesto_code": str},
                         usecols=["puesto_code", "mesas_total", "mesas_escrutadas"])
        df["mesas_total"]      = pd.to_numeric(df["mesas_total"],      errors="coerce").fillna(0)
        df["mesas_escrutadas"] = pd.to_numeric(df["mesas_escrutadas"], errors="coerce").fillna(0)
        incomplete = df[df["mesas_escrutadas"] < df["mesas_total"]]
        codes.update(incomplete["puesto_code"].tolist())

    err_path = OUT / "scrape_errors.csv"
    if err_path.exists():
        err_df = pd.read_csv(err_path, dtype={"puesto_code": str})
        codes.update(err_df["puesto_code"].tolist())

    return list(codes)


def scrape(update_mode: bool = False):
    master = pd.read_csv(OUT / "puestos_master.csv", dtype=str)

    if update_mode:
        codes = puestos_needing_update()
        if not codes:
            print("All puestos fully escrutados — nothing to update.")
            return
        print(f"Update mode: {len(codes):,} puestos not yet fully escrutados …")
    else:
        codes = master["puesto_code"].tolist()
        print(f"Scraping {len(codes):,} puestos (national + exterior) …")

    results, errors = asyncio.run(scrape_all(codes))

    print(f"\nDone: {len(results):,} ok, {len(errors):,} errors")

    if errors:
        pd.DataFrame(errors).to_csv(OUT / "scrape_errors.csv", index=False)

    new_df = pd.DataFrame(results).fillna(0)

    if update_mode:
        existing_path = OUT / "resultados_puestos.csv"
        if existing_path.exists():
            existing = pd.read_csv(existing_path, dtype={"puesto_code": str})
            updated_codes = set(new_df["puesto_code"])
            kept = existing[~existing["puesto_code"].isin(updated_codes)]
            # Align columns before concat
            all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
            new_df = pd.concat(
                [kept.reindex(columns=all_cols, fill_value=0),
                 new_df.reindex(columns=all_cols, fill_value=0)],
                ignore_index=True
            )
            print(f"  Merged: {len(new_df):,} total puesto rows")

    new_df.to_csv(OUT / "resultados_puestos.csv", index=False)
    print(f"Saved → resultados_puestos.csv  ({len(new_df):,} rows, {len(new_df.columns)} cols)")
    return new_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape puestos not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
