"""
02a_scrape_municipios.py — Primera Vuelta 2026
Scrape municipio-level presidential results (one row per municipio).

**TEMPLATE — MUST BE ADAPTED ON ELECTION DAY.**

Before running on election day:
  1. Confirm BASE_URL from the Registraduría results website.
  2. Verify PRESIDENTIAL_CAM (the cam index for the presidential race).
  3. Ensure candidates.json has "codcan" fields (run 01_build_candidate_json.py first).
  4. Test against a single municipio code before running the full scrape.

Output:
  data/results/colombia_2026_municipio_primera.csv
      1,189 rows: mpio_reg_code_7 + vote totals + cand_XXXX columns

Options:
  --update   Only re-fetch municipios where mesas_escrutadas < mesas_total
"""

import asyncio
import aiohttp
import argparse
import csv
import json
import time
from pathlib import Path

METADATA = Path(__file__).parent.parent.parent / "metadata"
OUT      = Path(__file__).parent.parent / "data"
RESULTS  = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# ⚠️  UPDATE THIS URL BEFORE ELECTION DAY
BASE_URL = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json"
HEADERS  = {
    "Referer":    "https://resultados1vuelta2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}

# ⚠️  VERIFY THIS ON ELECTION DAY (camara index for presidential race)
PRESIDENTIAL_CAM = 0

CONCURRENCY = 30
TIMEOUT     = 30

MPIO_CSV = RESULTS / "colombia_2026_municipio_primera.csv"


# ── Candidates ─────────────────────────────────────────────────────────────────

def load_candidates() -> list[dict]:
    """Load candidates from candidates.json; must have 'codcan' field."""
    path = OUT / "candidates.json"
    with open(path) as f:
        cands = json.load(f)
    missing = [c["code"] for c in cands if "codcan" not in c]
    if missing:
        raise RuntimeError(
            f"candidates.json is missing 'codcan' for: {missing}. "
            "Run 01_build_candidate_json.py first.")
    return cands


def build_codcan_map(candidates: list[dict]) -> dict[int, str]:
    """Map codcan (int) → candidate code string."""
    return {c["codcan"]: c["code"] for c in candidates}


# ── Parse ──────────────────────────────────────────────────────────────────────

def parse_mpio_json(code: str, data: dict, codcan_map: dict[int, str],
                    cand_cols: list[str]) -> dict:
    """Flatten one municipio JSON into a flat result row."""
    totales = data.get("totales", {}).get("act", {})

    pres_t = {}
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) == PRESIDENTIAL_CAM:
            pres_t = camara.get("totales", {}).get("act", {})
            break

    record = {
        "mpio_reg_code_7":   code,
        "mesas_total":        int(totales.get("metota")  or 0),
        "mesas_escrutadas":   int(totales.get("mesesc")  or 0),
        "censo":              int(totales.get("centota") or 0),
        "votantes":           int(pres_t.get("votant")  or totales.get("votant")  or 0),
        "votos_nulos":        int(pres_t.get("votnul")  or totales.get("votnul")  or 0),
        "votos_no_marcados":  int(pres_t.get("votnma")  or totales.get("votnma")  or 0),
        "votos_blanco":       int(pres_t.get("votbla")  or totales.get("votblan") or 0),
        "votos_validos":      int(pres_t.get("votval")  or totales.get("votval")  or 0),
    }

    # Zero-init all candidate columns
    for col in cand_cols:
        record[col] = 0

    # Parse candidate votes from the presidential camara
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) != PRESIDENTIAL_CAM:
            continue
        for entry in camara.get("partotabla", []):
            p      = entry.get("act", entry)
            codpar = int(p.get("codpar", 0))
            vot    = p.get("vot")
            cand_code = codcan_map.get(codpar)
            if cand_code:
                col = f"cand_{cand_code}"
                record[col] = record.get(col, 0) + (int(vot) if vot else 0)

    return record


# ── Network ────────────────────────────────────────────────────────────────────

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
                return code, None, str(e)[:120]
    return code, None, "failed"


async def scrape_all(codes, codcan_map, cand_cols):
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
            elif data: results.append(parse_mpio_json(code, data, codcan_map, cand_cols))
            if done % 100 == 0 or done == len(codes):
                e = time.time() - t0
                r = done / e if e else 0
                print(f"  [{done}/{len(codes)}]  ok={len(results)}  err={len(errors)}"
                      f"  {r:.0f}/s  eta={(len(codes)-done)/r:.0f}s" if r else "")
    return results, errors


# ── Write ──────────────────────────────────────────────────────────────────────

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, 0) for k in fieldnames})


# ── Update mode helpers ────────────────────────────────────────────────────────

def municipios_needing_update() -> list[str]:
    codes = set()
    if MPIO_CSV.exists():
        with open(MPIO_CSV) as f:
            reader = csv.DictReader(f)
            cand_cols = [c for c in (reader.fieldnames or []) if c.startswith("cand_")]
            for row in reader:
                me = int(row.get("mesas_escrutadas") or 0)
                mt = int(row.get("mesas_total")      or 0)
                if me < mt or mt == 0:
                    codes.add(row["mpio_reg_code_7"])
                elif int(row.get("votos_validos") or 0) > 0:
                    if all(int(row.get(c) or 0) == 0 for c in cand_cols):
                        codes.add(row["mpio_reg_code_7"])
    err_path = OUT / "scrape_errors.csv"
    if err_path.exists():
        with open(err_path) as f:
            for row in csv.DictReader(f):
                codes.add(row["mpio_reg_code_7"])
    return list(codes)


# ── Main ───────────────────────────────────────────────────────────────────────

def scrape(update_mode=False):
    candidates = load_candidates()
    codcan_map = build_codcan_map(candidates)
    cand_cols  = [f"cand_{c['code']}" for c in candidates]

    all_codes = []
    seen = set()
    with open(METADATA / "colombia_2026_municipio_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            c = row["mpio_reg_code_7"]
            if c not in seen:
                seen.add(c)
                all_codes.append(c)

    codes = municipios_needing_update() if update_mode else all_codes
    if update_mode and not codes:
        print("All municipios fully escrutados — nothing to update.")
        return
    print(f"{'Update' if update_mode else 'Full'} scrape: {len(codes):,} municipios …")

    results, errors = asyncio.run(scrape_all(codes, codcan_map, cand_cols))
    print(f"Done: {len(results):,} ok  {len(errors):,} errors")

    err_path = OUT / "scrape_errors.csv"
    if errors:
        write_csv(err_path, errors, ["mpio_reg_code_7", "error"])
    elif update_mode and err_path.exists():
        err_path.unlink()

    if not results:
        return

    fresh_codes = {r["mpio_reg_code_7"] for r in results}

    if update_mode and MPIO_CSV.exists():
        with open(MPIO_CSV) as f:
            existing = list(csv.DictReader(f))
        results = [r for r in existing if r["mpio_reg_code_7"] not in fresh_codes] + results

    # Ensure every electoral-roll code has a row
    scraped_codes = {r["mpio_reg_code_7"] for r in results}
    for c in all_codes:
        if c not in scraped_codes:
            results.append({"mpio_reg_code_7": c})

    order = {c: i for i, c in enumerate(all_codes)}
    results.sort(key=lambda r: order.get(r["mpio_reg_code_7"], 9999))

    fields = (
        ["mpio_reg_code_7", "censo", "votantes", "votos_nulos", "votos_no_marcados",
         "votos_blanco", "votos_validos", "mesas_total", "mesas_escrutadas"]
        + cand_cols
    )
    write_csv(MPIO_CSV, results, fields)
    n_ext = sum(1 for r in results if str(r.get("mpio_reg_code_7", "")).startswith("88"))
    print(f"Saved: {len(results):,} rows  ({len(results)-n_ext} national + {n_ext} exterior)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape municipios not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
