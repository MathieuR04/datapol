"""
02b_scrape_mesas.py — Primera Vuelta 2026
Scrape mesa-level presidential results (one row per polling table).

**TEMPLATE — MUST BE ADAPTED ON ELECTION DAY.**

Before running on election day:
  1. Confirm BASE_URL from the Registraduría results website (mesa-level endpoint).
  2. Verify PRESIDENTIAL_CAM (the cam index for the presidential race).
  3. Ensure candidates.json has "codcan" fields (run 01_build_candidate_json.py first).
  4. Confirm the API structure for mesa-level data (may differ from municipio endpoint).
  5. Test against a small set of mesas before running the full scrape (~126,647 rows).

Output:
  data/results/colombia_2026_mesa_primera.csv
      126,647 rows: mesa_code + mpio_reg_code_7 + vote totals + cand_XXXX columns

Options:
  --update   Only re-fetch mesas where mesas_escrutadas == 0
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

# ⚠️  UPDATE THIS URL BEFORE ELECTION DAY (mesa-level endpoint)
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

MESA_CSV = RESULTS / "colombia_2026_mesa_primera.csv"


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

def parse_mesa_json(mesa_code: str, mpio_code: str, data: dict,
                    codcan_map: dict[int, str], cand_cols: list[str]) -> dict:
    """Flatten one mesa JSON into a flat result row."""
    totales = data.get("totales", {}).get("act", {})

    pres_t = {}
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) == PRESIDENTIAL_CAM:
            pres_t = camara.get("totales", {}).get("act", {})
            break

    record = {
        "mesa_code":          mesa_code,
        "mpio_reg_code_7":    mpio_code,
        "censo":              int(totales.get("centota") or 0),
        "mesas_escrutadas":   int(totales.get("mesesc")  or 0),
        "votantes":           int(pres_t.get("votant")  or totales.get("votant")  or 0),
        "votos_nulos":        int(pres_t.get("votnul")  or totales.get("votnul")  or 0),
        "votos_no_marcados":  int(pres_t.get("votnma")  or totales.get("votnma")  or 0),
        "votos_blanco":       int(pres_t.get("votbla")  or totales.get("votblan") or 0),
        "votos_validos":      int(pres_t.get("votval")  or totales.get("votval")  or 0),
    }

    for col in cand_cols:
        record[col] = 0

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

async def fetch_one(session, sem, mesa_code, mpio_code):
    url = BASE_URL.format(code=mesa_code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404: return mesa_code, mpio_code, None, "404"
                    if resp.status != 200:
                        if attempt == 0: await asyncio.sleep(1); continue
                        return mesa_code, mpio_code, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    return mesa_code, mpio_code, data, None
            except asyncio.TimeoutError:
                if attempt == 0: await asyncio.sleep(2); continue
                return mesa_code, mpio_code, None, "timeout"
            except Exception as e:
                if attempt == 0: await asyncio.sleep(1); continue
                return mesa_code, mpio_code, None, str(e)[:120]
    return mesa_code, mpio_code, None, "failed"


async def scrape_all(mesa_pairs, codcan_map, cand_cols):
    results, errors = [], []
    sem = asyncio.Semaphore(CONCURRENCY)
    t0  = time.time()
    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, mc, mp) for mc, mp in mesa_pairs]
        done  = 0
        for coro in asyncio.as_completed(tasks):
            mesa_code, mpio_code, data, err = await coro
            done += 1
            if err:
                errors.append({"mesa_code": mesa_code, "error": err})
            elif data:
                results.append(parse_mesa_json(mesa_code, mpio_code, data, codcan_map, cand_cols))
            if done % 500 == 0 or done == len(mesa_pairs):
                e = time.time() - t0
                r = done / e if e else 0
                print(f"  [{done}/{len(mesa_pairs)}]  ok={len(results)}  err={len(errors)}"
                      f"  {r:.0f}/s  eta={(len(mesa_pairs)-done)/r:.0f}s" if r else "")
    return results, errors


# ── Write ──────────────────────────────────────────────────────────────────────

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, 0) for k in fieldnames})


# ── Update mode helpers ────────────────────────────────────────────────────────

def mesas_needing_update(all_pairs: list[tuple]) -> list[tuple]:
    """Return (mesa_code, mpio_code) pairs where mesas_escrutadas == 0."""
    if not MESA_CSV.exists():
        return all_pairs
    counted = set()
    with open(MESA_CSV) as f:
        for row in csv.DictReader(f):
            if int(row.get("mesas_escrutadas") or 0) > 0:
                counted.add(row["mesa_code"])
    err_path = OUT / "scrape_errors_mesas.csv"
    errored  = set()
    if err_path.exists():
        with open(err_path) as f:
            errored = {row["mesa_code"] for row in csv.DictReader(f)}
    return [(mc, mp) for mc, mp in all_pairs if mc not in counted or mc in errored]


# ── Main ───────────────────────────────────────────────────────────────────────

def scrape(update_mode=False):
    candidates = load_candidates()
    codcan_map = build_codcan_map(candidates)
    cand_cols  = [f"cand_{c['code']}" for c in candidates]

    # Load all mesas from electoral roll
    all_pairs = []
    with open(METADATA / "colombia_2026_mesa_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            all_pairs.append((row["mesa_code"], row["mpio_reg_code_7"]))

    pairs = mesas_needing_update(all_pairs) if update_mode else all_pairs
    if update_mode and not pairs:
        print("All mesas counted — nothing to update.")
        return
    print(f"{'Update' if update_mode else 'Full'} scrape: {len(pairs):,} mesas …")

    results, errors = asyncio.run(scrape_all(pairs, codcan_map, cand_cols))
    print(f"Done: {len(results):,} ok  {len(errors):,} errors")

    err_path = OUT / "scrape_errors_mesas.csv"
    if errors:
        write_csv(err_path, errors, ["mesa_code", "error"])
    elif update_mode and err_path.exists():
        err_path.unlink()

    if not results:
        return

    fresh_codes = {r["mesa_code"] for r in results}

    if update_mode and MESA_CSV.exists():
        with open(MESA_CSV) as f:
            existing = list(csv.DictReader(f))
        results = [r for r in existing if r["mesa_code"] not in fresh_codes] + results

    # Ensure every roll mesa has a row
    scraped_codes = {r["mesa_code"] for r in results}
    for mc, mp in all_pairs:
        if mc not in scraped_codes:
            results.append({"mesa_code": mc, "mpio_reg_code_7": mp})

    order = {mc: i for i, (mc, _) in enumerate(all_pairs)}
    results.sort(key=lambda r: order.get(r["mesa_code"], 999999))

    fields = (
        ["mesa_code", "mpio_reg_code_7", "censo",
         "mesas_escrutadas", "votantes", "votos_nulos", "votos_no_marcados",
         "votos_blanco", "votos_validos"]
        + cand_cols
    )
    write_csv(MESA_CSV, results, fields)
    print(f"Saved: {len(results):,} mesa rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape mesas not yet counted")
    args = parser.parse_args()
    scrape(update_mode=args.update)
