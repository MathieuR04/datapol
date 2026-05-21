"""
01_scrape_municipios.py  —  Senado 2026
Scrape municipio-level results in one pass (national + exterior).

The Registraduría API returns municipio aggregates at 7-digit codes — ~1,189
requests instead of 14,430 puesto requests.

Outputs (raw vote data only — no computed winner/pct columns):
  data/results/colombia_2026_municipio_senado_nacional.csv
      1,189 rows: mpio_reg_code_7 + vote totals + party_XXXX + ind_ columns
  data/results/colombia_2026_municipio_senado_indigena.csv
      rows with any indigenous vote: mpio_reg_code_7 + ind vote totals + indig_XXXX

Options:
  --update   Only re-fetch municipios where mesas_escrutadas < mesas_total
"""

import asyncio
import aiohttp
import argparse
import csv
import time
from pathlib import Path

METADATA = Path(__file__).parent.parent.parent / "metadata"
OUT      = Path(__file__).parent.parent / "data"
RESULTS  = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json"
HEADERS  = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 30
TIMEOUT     = 30


# ── Parse ──────────────────────────────────────────────────────────────────────

def parse_mpio_json(code: str, data: dict) -> dict:
    """
    Flatten one municipio JSON.  Two camaras:
      cam=0  →  nacional  (party_XXXX)
      cam=4  →  indígena  (indig_XXXX)
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
        "mesas_total":        int(totales.get("metota") or 0),
        "mesas_escrutadas":   int(totales.get("mesesc") or 0),
        # Nacional
        "votantes":           int(nat_t.get("votant")  or totales.get("votant")  or 0),
        "votos_nulos":        int(nat_t.get("votnul")  or totales.get("votnul")  or 0),
        "votos_no_marcados":  int(nat_t.get("votnma")  or totales.get("votnma")  or 0),
        "votos_blanco":       int(nat_t.get("votbla")  or totales.get("votblan") or 0),
        "votos_validos":      int(nat_t.get("votval")  or totales.get("votval")  or 0),
        # Indígena base counts
        "ind_votantes":       int(ind_t.get("votant") or 0),
        "ind_votos_validos":  int(ind_t.get("votval") or 0),
        "ind_votos_blanco":   int(ind_t.get("votbla") or ind_t.get("votblan") or 0),
        "ind_votos_nulos":    int(ind_t.get("votnul") or 0),
    }

    for camara in data.get("camaras", []):
        cam  = int(camara.get("cam", 0))
        pcol = "indig" if cam == 4 else "party"
        for pw in camara.get("partotabla", []):
            p   = pw.get("act", pw)
            cod = int(p.get("codpar", 0))
            vot = p.get("vot")
            key = f"{pcol}_{cod:04d}"
            record[key] = record.get(key, 0) + (int(vot) if vot else 0)

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
            if err:    errors.append({"mpio_reg_code_7": code, "error": err})
            elif data: results.append(parse_mpio_json(code, data))
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


# ── Main ───────────────────────────────────────────────────────────────────────

def municipios_needing_update():
    path = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
    if not path.exists(): return []
    codes = []
    with open(path) as f:
        for row in csv.DictReader(f):
            if int(row.get("mesas_escrutadas") or 0) < int(row.get("mesas_total") or 1):
                codes.append(row["mpio_reg_code_7"])
    return codes


def scrape(update_mode=False):
    # All 1,189 municipios from the electoral roll (national + exterior)
    all_codes = []
    seen      = set()
    with open(METADATA / "colombia_2026_municipio_electoral_roll.csv") as f:
        for row in csv.DictReader(f):
            c = row["mpio_reg_code_7"]
            if c not in seen:
                seen.add(c)
                all_codes.append(c)

    codes = municipios_needing_update() if update_mode else all_codes
    if update_mode and not codes:
        print("All municipios fully escrutados — nothing to update."); return
    print(f"{'Update' if update_mode else 'Full'} scrape: {len(codes):,} municipios "
          f"(national + exterior) …")

    results, errors = asyncio.run(scrape_all(codes))
    print(f"Done: {len(results):,} ok  {len(errors):,} errors")

    if errors:
        write_csv(OUT / "scrape_errors.csv", errors, ["mpio_reg_code_7", "error"])

    if not results: return

    # Merge with existing rows in update mode
    if update_mode:
        path = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
        if path.exists():
            with open(path) as f:
                existing  = list(csv.DictReader(f))
            new_codes = {r["mpio_reg_code_7"] for r in results}
            results   = [r for r in existing if r["mpio_reg_code_7"] not in new_codes] + results

    # Detect all party/indig column names from scraped data
    all_keys   = set()
    for r in results: all_keys.update(r.keys())
    party_cols = sorted(k for k in all_keys if k.startswith("party_"))
    indig_cols = sorted(k for k in all_keys if k.startswith("indig_"))

    # Ensure every electoral-roll code has a row (zeros for 404s / missing)
    scraped_codes = {r["mpio_reg_code_7"] for r in results}
    for c in all_codes:
        if c not in scraped_codes:
            results.append({"mpio_reg_code_7": c})   # all numeric fields default to 0 via write_csv

    # Sort to match electoral roll order
    order = {c: i for i, c in enumerate(all_codes)}
    results.sort(key=lambda r: order.get(r["mpio_reg_code_7"], 9999))

    # ── Nacional CSV ──────────────────────────────────────────────────────────
    nat_fields = (
        ["mpio_reg_code_7", "votantes", "votos_nulos", "votos_no_marcados",
         "votos_blanco", "votos_validos", "mesas_total", "mesas_escrutadas",
         "ind_votantes", "ind_votos_validos", "ind_votos_blanco", "ind_votos_nulos"]
        + party_cols
    )
    write_csv(RESULTS / "colombia_2026_municipio_senado_nacional.csv", results, nat_fields)
    n_ext = sum(1 for r in results if str(r.get("mpio_reg_code_7", "")).startswith("88"))
    print(f"Saved nacional:  {len(results):,} rows  "
          f"({len(results)-n_ext} national + {n_ext} exterior)")

    # ── Indigena CSV — all 1,189 rows, zeros where no indigenous voting ───────
    ind_rows = results   # full set; no filtering

    ind_out = []
    for r in ind_rows:
        ind_r = {
            "mpio_reg_code_7":   r["mpio_reg_code_7"],
            "votantes":           int(r.get("ind_votantes")      or 0),
            "votos_validos":      int(r.get("ind_votos_validos") or 0),
            "votos_blanco":       int(r.get("ind_votos_blanco")  or 0),
            "votos_nulos":        int(r.get("ind_votos_nulos")   or 0),
            "mesas_total":        int(r.get("mesas_total")       or 0),
            "mesas_escrutadas":   int(r.get("mesas_escrutadas")  or 0),
        }
        ind_r["votos_no_marcados"] = (
            ind_r["votantes"] - ind_r["votos_validos"] - ind_r["votos_nulos"]
        )
        for k in indig_cols:
            ind_r[k] = int(r.get(k) or 0)
        ind_out.append(ind_r)

    ind_fields = (
        ["mpio_reg_code_7", "votantes", "votos_validos", "votos_blanco",
         "votos_nulos", "votos_no_marcados", "mesas_total", "mesas_escrutadas"]
        + indig_cols
    )
    write_csv(RESULTS / "colombia_2026_municipio_senado_indigena.csv", ind_out, ind_fields)
    n_ext_i = sum(1 for r in ind_out if str(r.get("mpio_reg_code_7", "")).startswith("88"))
    print(f"Saved indigena:  {len(ind_out):,} rows  "
          f"({len(ind_out)-n_ext_i} national + {n_ext_i} exterior)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape municipios not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
