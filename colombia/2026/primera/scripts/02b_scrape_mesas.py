"""
02b_scrape_mesas.py — Primera Vuelta 2026
Scrape mesa-level presidential results (one row per polling table).

**MUST BE ADAPTED ON ELECTION DAY:**
  1. Confirm BASE_URL from the Registraduría results website (mesa-level endpoint).
  2. Verify PRESIDENTIAL_CAM (the cam index for the presidential race).
  3. Ensure candidates.json has "codcan" fields (run 01_build_candidate_json.py first).

Output:
  data/results/colombia_2026_mesa_primera.csv
      126,647 rows: mesa_code + mpio_reg_code_7 + counted + vote totals + cand_XXXX columns

Options:
  --update   Only re-fetch mesas where counted == 0 (plus any that previously errored)
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
BASE_URL = "https://resultados.registraduria.gov.co/json/ACT/PR/{code}.json"
HEADERS  = {
    "Referer":          "https://resultados.registraduria.gov.co/",
    "Origin":           "https://resultados.registraduria.gov.co",
    "User-Agent":       "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
    "Accept":           "application/json, text/javascript, */*; q=0.01",
    "Accept-Language":  "es-CO,es;q=0.9,en;q=0.8",
    "Accept-Encoding":  "gzip, deflate, br",
    "X-Requested-With": "XMLHttpRequest",
    "Connection":       "keep-alive",
}

# ⚠️  VERIFY THIS ON ELECTION DAY
PRESIDENTIAL_CAM = 0

CONCURRENCY  = 10
TIMEOUT      = 25
DELAY        = 0.1     # seconds between requests to avoid 403
FLUSH_EVERY  = 1_000   # rows before flushing to CSV

MESA_CSV     = RESULTS / "colombia_2026_mesa_primera.csv"
ERRORS_CSV   = OUT / "scrape_errors_mesas.csv"
CHECKPOINT   = OUT / ".mesa_checkpoint.json"   # tracks counted + errored codes


# ── Candidates ─────────────────────────────────────────────────────────────────

def load_candidates() -> list[dict]:
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
    return {c["codpar"]: c["code"] for c in candidates}


# ── Parse ──────────────────────────────────────────────────────────────────────

def parse_mesa_json(mesa_code: str, mpio_code: str, data: dict,
                    codcan_map: dict[int, str], cand_cols: list[str]) -> dict:
    totales = data.get("totales", {}).get("act", {})

    # counted = 1 if this mesa has been escrutada
    counted = 1 if int(totales.get("mesesc") or 0) > 0 else 0

    pres_t = {}
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) == PRESIDENTIAL_CAM:
            pres_t = camara.get("totales", {}).get("act", {})
            break

    record = {
        "mesa_code":         mesa_code,
        "mpio_reg_code_7":   mpio_code,
        "counted":           counted,
        "votantes":          int(pres_t.get("votant")  or totales.get("votant")  or 0),
        "votos_nulos":       int(pres_t.get("votnul")  or totales.get("votnul")  or 0),
        "votos_no_marcados": int(pres_t.get("votnma")  or totales.get("votnma")  or 0),
        "votos_blanco":      int(pres_t.get("votbla")  or totales.get("votblan") or 0),
        "votos_validos":     int(pres_t.get("votval")  or totales.get("votval")  or 0),
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
            code   = codcan_map.get(codpar)
            if code:
                col = f"cand_{code}"
                record[col] = record.get(col, 0) + (int(vot) if vot else 0)

    return record


# ── Checkpoint ─────────────────────────────────────────────────────────────────

def load_checkpoint() -> tuple[set, set]:
    """Returns (counted_codes, errored_codes)."""
    if CHECKPOINT.exists():
        with open(CHECKPOINT) as f:
            d = json.load(f)
        return set(d.get("counted", [])), set(d.get("errored", []))
    return set(), set()

def save_checkpoint(counted: set, errored: set):
    with open(CHECKPOINT, "w") as f:
        json.dump({"counted": sorted(counted), "errored": sorted(errored)}, f)


# ── CSV helpers ────────────────────────────────────────────────────────────────

FIELDNAMES = None   # set once at first flush

def open_writer(path: Path, fieldnames: list[str], append: bool):
    mode = "a" if append else "w"
    f = open(path, mode, newline="")
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not append:
        w.writeheader()
    return f, w

def flush_rows(rows: list[dict], fieldnames: list[str], first_flush: bool):
    """Append rows to MESA_CSV."""
    f, w = open_writer(MESA_CSV, fieldnames, append=not first_flush)
    for row in rows:
        w.writerow({k: row.get(k, 0) for k in fieldnames})
    f.close()


# ── Network ────────────────────────────────────────────────────────────────────

async def fetch_one(session, sem, mesa_code, mpio_code):
    # mesa_code is 19-digit (e.g. "1600001120031000001"); API uses 17-digit (dept2+mpio3+rest12)
    api_code = mesa_code[:2] + mesa_code[4:]
    url = BASE_URL.format(code=api_code)
    async with sem:
        await asyncio.sleep(DELAY)
        for attempt in range(3):
            try:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 404:
                        return mesa_code, mpio_code, None, "404"
                    if resp.status == 403:
                        await asyncio.sleep(2 + attempt * 2)
                        continue
                    if resp.status != 200:
                        if attempt < 2:
                            await asyncio.sleep(1)
                            continue
                        return mesa_code, mpio_code, None, f"HTTP {resp.status}"
                    data = await resp.json(content_type=None)
                    return mesa_code, mpio_code, data, None
            except asyncio.TimeoutError:
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                return mesa_code, mpio_code, None, "timeout"
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                return mesa_code, mpio_code, None, str(e)[:120]
    return mesa_code, mpio_code, None, "failed"


async def scrape_async(pairs, codcan_map, cand_cols, counted_set, errored_set):
    sem       = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 10, ssl=False)

    fields = (["mesa_code", "mpio_reg_code_7", "counted",
               "votantes", "votos_nulos", "votos_no_marcados",
               "votos_blanco", "votos_validos"] + cand_cols)

    batch        = []
    errors       = []
    first_flush  = not MESA_CSV.exists()
    done         = 0
    t0           = time.time()
    total        = len(pairs)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, mc, mp) for mc, mp in pairs]
        for coro in asyncio.as_completed(tasks):
            mesa_code, mpio_code, data, err = await coro
            done += 1

            if err:
                errors.append({"mesa_code": mesa_code, "error": err})
                errored_set.add(mesa_code)
            elif data is not None:
                row = parse_mesa_json(mesa_code, mpio_code, data, codcan_map, cand_cols)
                batch.append(row)
                if row["counted"]:
                    counted_set.add(mesa_code)
                errored_set.discard(mesa_code)
            else:
                errors.append({"mesa_code": mesa_code, "error": "no_data"})

            # Batch flush
            if len(batch) >= FLUSH_EVERY:
                flush_rows(batch, fields, first_flush)
                first_flush = False
                save_checkpoint(counted_set, errored_set)
                batch = []

            if done % 500 == 0 or done == total:
                elapsed = time.time() - t0
                rate    = done / elapsed if elapsed else 0
                eta     = (total - done) / rate if rate else 0
                print(f"  [{done:,}/{total:,}]  counted={len(counted_set):,}  "
                      f"err={len(errors)}  {rate:.0f}/s  eta={eta:.0f}s    ",
                      end="\r", flush=True)

    # Final flush
    if batch:
        flush_rows(batch, fields, first_flush)

    save_checkpoint(counted_set, errored_set)
    print()  # newline after \r progress
    return errors


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

    counted_set, errored_set = load_checkpoint()

    if update_mode:
        # Re-fetch: uncounted mesas + previously errored ones
        pairs = [(mc, mp) for mc, mp in all_pairs
                 if mc not in counted_set or mc in errored_set]
        if not pairs:
            print("All mesas counted — nothing to update.")
            return
        print(f"Update scrape: {len(pairs):,} mesas remaining "
              f"({len(all_pairs)-len(pairs):,} already counted) …")
    else:
        pairs = all_pairs
        counted_set.clear()
        errored_set.clear()
        if MESA_CSV.exists():
            MESA_CSV.unlink()
        print(f"Full scrape: {len(pairs):,} mesas …")

    errors = asyncio.run(
        scrape_async(pairs, codcan_map, cand_cols, counted_set, errored_set)
    )

    if errors:
        with open(ERRORS_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["mesa_code", "error"])
            w.writeheader()
            w.writerows(errors)
        print(f"  {len(errors)} errors saved to {ERRORS_CSV.name}")
    elif ERRORS_CSV.exists():
        ERRORS_CSV.unlink()

    # Ensure every roll mesa has a row (fill zeros for any not yet fetched)
    if MESA_CSV.exists():
        with open(MESA_CSV) as f:
            present = {row["mesa_code"] for row in csv.DictReader(f)}
    else:
        present = set()

    missing = [(mc, mp) for mc, mp in all_pairs if mc not in present]
    if missing:
        fields = (["mesa_code", "mpio_reg_code_7", "counted",
                   "votantes", "votos_nulos", "votos_no_marcados",
                   "votos_blanco", "votos_validos"] + cand_cols)
        with open(MESA_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            for mc, mp in missing:
                w.writerow({"mesa_code": mc, "mpio_reg_code_7": mp, "counted": 0})

    total_counted = len(counted_set)
    print(f"Done: {total_counted:,}/{len(all_pairs):,} mesas counted  "
          f"({total_counted/len(all_pairs)*100:.1f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape uncounted mesas")
    args = parser.parse_args()
    scrape(update_mode=args.update)
