"""
02_scrape_municipios.py — Scrape municipio-level primarias (consultas) results.

Hits the Registraduría CN endpoint for all 1,189 municipio codes and produces
four CSVs in data/results/:

  colombia_2026_municipio_primarias_soluciones.csv   (codpar 30 candidates)
  colombia_2026_municipio_primarias_gran.csv          (codpar 31 candidates)
  colombia_2026_municipio_primarias_frente.csv        (codpar 32 candidates)
  colombia_2026_municipio_primarias_interconsultas.csv (per-consulta totals)

All four CSVs share the same geographic / turnout metadata:
  mpio_reg_code_7, mesas_total, mesas_escrutadas, censo,
  votantes, votos_nulos, votos_no_marcados, votos_blanco, votos_validos

The per-consulta CSVs add candidate vote columns:
  cand_30_YYYYYY|Nombre  (soluciones)
  cand_31_YYYYYY|Nombre  (gran)
  cand_32_YYYYYY|Nombre  (frente)

The interconsultas CSV adds consulta totals:
  consulta_30, consulta_31, consulta_32

Options:
  --update   Only re-fetch municipios where mesas_escrutadas < mesas_total
             (determined from the interconsultas CSV, which is always written)
"""

import asyncio
import aiohttp
import argparse
import csv
import json
import time
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
METADATA    = SCRIPT_DIR.parent.parent / "metadata"
OUT         = SCRIPT_DIR.parent / "data"
RESULTS     = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

BASE_URL    = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/CN/{code}.json"
HEADERS     = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json, */*",
}
CONCURRENCY = 30
TIMEOUT     = 30

# codpar → (slug, cand_prefix)
CONSULTAS = {
    30: ("soluciones", "cand_30"),
    31: ("gran",       "cand_31"),
    32: ("frente",     "cand_32"),
}

COMMON_FIELDS = [
    "mpio_reg_code_7", "mesas_total", "mesas_escrutadas", "censo",
    "votantes", "votos_nulos", "votos_no_marcados", "votos_blanco", "votos_validos",
]


# ── Parse ──────────────────────────────────────────────────────────────────────

def parse_mpio_json(code: str, data: dict) -> dict:
    """Flatten one municipio CN JSON into a flat record dict."""
    tt = data.get("totales", {}).get("act", {})

    record: dict = {
        "mpio_reg_code_7":   code,
        "mesas_total":       int(tt.get("metota")  or 0),
        "mesas_escrutadas":  int(tt.get("mesesc")  or 0),
        "censo":             int(tt.get("centota") or 0),
        "votantes":          int(tt.get("votant")  or 0),
        "votos_nulos":       int(tt.get("votnul")  or 0),
        "votos_no_marcados": int(tt.get("votnma")  or 0),
        "votos_blanco":      int(tt.get("votblan") or tt.get("votbla") or 0),
        "votos_validos":     int(tt.get("votval")  or 0),
    }

    for cam in data.get("camaras", []):
        if int(cam.get("cam", -1)) != 0:
            continue
        for pw in cam.get("partotabla", []):
            p      = pw.get("act", pw)
            codpar = int(p.get("codpar", -1))
            if codpar not in CONSULTAS:
                continue
            slug, prefix = CONSULTAS[codpar]

            # Consulta total (used by interconsultas CSV)
            total_col = f"consulta_{codpar}"
            record[total_col] = record.get(total_col, 0) + int(p.get("vot") or 0)

            # Per-candidate columns
            for cand in p.get("cantotabla") or []:
                codcan = int(cand.get("codcan", 0))
                nom    = (
                    f"{cand.get('nomcan','').strip()} "
                    f"{cand.get('apecan','').strip()}"
                ).strip()
                vot    = int(cand.get("vot") or 0)
                key    = f"{prefix}_{codcan:06d}|{nom}"
                record[key] = record.get(key, 0) + vot

    return record


# ── Network ────────────────────────────────────────────────────────────────────

async def fetch_one(session, sem, code: str):
    url = BASE_URL.format(code=code)
    async with sem:
        for attempt in range(2):
            try:
                async with session.get(
                    url, headers=HEADERS,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT)
                ) as resp:
                    if resp.status == 404:
                        return code, None, "404"
                    if resp.status != 200:
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return code, None, f"HTTP {resp.status}"
                    d = await resp.json(content_type=None)
                    return code, d, None
            except asyncio.TimeoutError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return code, None, "timeout"
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return code, None, str(e)[:120]
    return code, None, "failed"


async def scrape_all(codes: list[str]):
    results, errors = [], []
    sem       = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5, ssl=False)
    t0        = time.time()

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, sem, c) for c in codes]
        done  = 0
        for coro in asyncio.as_completed(tasks):
            code, data, err = await coro
            done += 1
            if err:
                errors.append({"mpio_reg_code_7": code, "error": err})
            elif data:
                results.append(parse_mpio_json(code, data))
            if done % 100 == 0 or done == len(codes):
                elapsed = time.time() - t0
                rate    = done / elapsed if elapsed else 0
                eta     = (len(codes) - done) / rate if rate else 0
                print(f"  [{done}/{len(codes)}]  ok={len(results)}  "
                      f"err={len(errors)}  {rate:.0f}/s  eta={eta:.0f}s")

    return results, errors


# ── Write ──────────────────────────────────────────────────────────────────────

def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, 0) for k in fieldnames})
    print(f"  Saved → {path.name}  ({len(rows)} rows)")


# ── Update helpers ─────────────────────────────────────────────────────────────

def codes_needing_update() -> list[str]:
    """Return mpio codes that are incomplete or errored."""
    codes: set[str] = set()

    inter_path = RESULTS / "colombia_2026_municipio_primarias_interconsultas.csv"
    if inter_path.exists():
        with open(inter_path) as f:
            for row in csv.DictReader(f):
                me = int(row.get("mesas_escrutadas") or 0)
                mt = int(row.get("mesas_total")      or 0)
                if me < mt or mt == 0:
                    codes.add(row["mpio_reg_code_7"])

    err_path = OUT / "scrape_errors_primarias.csv"
    if err_path.exists():
        with open(err_path) as f:
            for row in csv.DictReader(f):
                codes.add(row["mpio_reg_code_7"])

    return list(codes)


def merge_with_existing(fresh: list[dict], fresh_codes: set[str],
                        existing_path: Path) -> list[dict]:
    """Combine freshly-scraped rows with unchanged existing rows."""
    if not existing_path.exists():
        return fresh
    with open(existing_path) as f:
        old = [r for r in csv.DictReader(f)
               if r["mpio_reg_code_7"] not in fresh_codes]
    return old + fresh


# ── Main ───────────────────────────────────────────────────────────────────────

def scrape(update_mode: bool = False) -> None:
    # Load all mpio codes from electoral roll
    all_codes: list[str] = []
    seen: set[str]       = set()
    roll_path = METADATA / "colombia_2026_municipio_electoral_roll.csv"
    with open(roll_path) as f:
        for row in csv.DictReader(f):
            c = row["mpio_reg_code_7"]
            if c not in seen:
                seen.add(c)
                all_codes.append(c)

    codes = codes_needing_update() if update_mode else all_codes
    if update_mode and not codes:
        print("All municipios fully escrutados — nothing to update.")
        return

    print(f"{'Update' if update_mode else 'Full'} scrape: "
          f"{len(codes):,} municipios …")

    results, errors = asyncio.run(scrape_all(codes))
    print(f"Done: {len(results):,} ok  {len(errors):,} errors")

    # Save / clear errors file
    err_path = OUT / "scrape_errors_primarias.csv"
    if errors:
        write_csv(err_path, errors, ["mpio_reg_code_7", "error"])
    elif update_mode and err_path.exists():
        err_path.unlink()

    if not results:
        return

    fresh_codes = {r["mpio_reg_code_7"] for r in results}

    # In update mode, merge with existing data
    if update_mode:
        inter_path = RESULTS / "colombia_2026_municipio_primarias_interconsultas.csv"
        old_rows   = merge_with_existing(results, fresh_codes, inter_path)
        results    = old_rows   # replace with merged set for consistent output

    # Collect all column names from scraped data
    all_keys = set()
    for r in results:
        all_keys.update(r.keys())

    # Sort candidate/consulta columns
    cand_cols = {codpar: sorted(k for k in all_keys if k.startswith(f"cand_{codpar}_"))
                 for codpar in CONSULTAS}
    inter_cols = [f"consulta_{cp}" for cp in sorted(CONSULTAS)]

    # Fill missing rows (zeros for 404 / missing municipios)
    scraped = {r["mpio_reg_code_7"] for r in results}
    for c in all_codes:
        if c not in scraped:
            results.append({"mpio_reg_code_7": c})

    # Sort by electoral roll order
    order = {c: i for i, c in enumerate(all_codes)}
    results.sort(key=lambda r: order.get(r["mpio_reg_code_7"], 9999))

    # ── Write per-consulta CSVs ───────────────────────────────────────────────
    for codpar, (slug, _prefix) in CONSULTAS.items():
        fields = COMMON_FIELDS + cand_cols[codpar]
        path   = RESULTS / f"colombia_2026_municipio_primarias_{slug}.csv"
        write_csv(path, results, fields)

    # ── Write interconsultas CSV ──────────────────────────────────────────────
    inter_fields = COMMON_FIELDS + inter_cols
    inter_path   = RESULTS / "colombia_2026_municipio_primarias_interconsultas.csv"
    write_csv(inter_path, results, inter_fields)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape primarias municipio results")
    parser.add_argument("--update", action="store_true",
                        help="Only re-fetch incomplete / errored municipios")
    args = parser.parse_args()
    scrape(update_mode=args.update)
