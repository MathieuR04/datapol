"""
02a_scrape_municipios_curl.py — Fallback scraper using curl subprocess.
Use when aiohttp gets 403 from CloudFront fingerprinting.
Sequential, slow (~15 min for 1189 municipios) but reliable.

Usage:
  python3 scripts/02a_scrape_municipios_curl.py           # full scrape
  python3 scripts/02a_scrape_municipios_curl.py --update  # errors only
"""

import argparse
import csv
import json
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

METADATA = Path(__file__).parent.parent.parent / "metadata"
OUT      = Path(__file__).parent.parent / "data"
RESULTS  = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://resultados.registraduria.gov.co/json/ACT/PR/{code}.json"
PRESIDENTIAL_CAM = 0
WORKERS  = 6     # parallel curl subprocesses
MPIO_CSV = RESULTS / "colombia_2026_municipio_primera.csv"


def load_candidates():
    with open(OUT / "candidates.json") as f:
        return json.load(f)

def build_codcan_map(candidates):
    return {c["codpar"]: c["code"] for c in candidates}

def fetch_curl(code):
    api_code = code[:2] + code[4:]
    url = BASE_URL.format(code=api_code)
    try:
        result = subprocess.run([
            "curl", "-s", "-m", "20",
            "-H", "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
            "-H", "Referer: https://resultados.registraduria.gov.co/",
            "-H", "Accept: application/json, */*",
            "-H", "Accept-Language: es-CO,es;q=0.9",
            url
        ], capture_output=True, text=True, timeout=25)
        if not result.stdout.strip():
            return None, "empty"
        data = json.loads(result.stdout)
        return data, None
    except json.JSONDecodeError:
        return None, "json_err"
    except Exception as e:
        return None, str(e)[:80]

def parse_mpio(code, data, codcan_map, cand_cols):
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
    for col in cand_cols:
        record[col] = 0
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) != PRESIDENTIAL_CAM:
            continue
        for entry in camara.get("partotabla", []):
            p = entry.get("act", entry)
            codpar = int(p.get("codpar", 0))
            vot = p.get("vot")
            cand_code = codcan_map.get(codpar)
            if cand_code:
                col = f"cand_{cand_code}"
                record[col] = record.get(col, 0) + (int(vot) if vot else 0)
    return record

def municipios_needing_update():
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

    print(f"{'Update' if update_mode else 'Full'} scrape (curl): {len(codes):,} municipios …")

    results, errors = [], []
    lock = threading.Lock()
    done = [0]
    t0 = time.time()

    def process(code):
        data, err = fetch_curl(code)
        with lock:
            done[0] += 1
            if err:
                errors.append({"mpio_reg_code_7": code, "error": err})
            elif data:
                results.append(parse_mpio(code, data, codcan_map, cand_cols))
            if done[0] % 50 == 0 or done[0] == len(codes):
                elapsed = time.time() - t0
                rate = done[0] / elapsed if elapsed else 0
                eta  = (len(codes) - done[0]) / rate if rate else 0
                print(f"  [{done[0]:,}/{len(codes):,}]  ok={len(results):,}  err={len(errors)}  {rate:.1f}/s  eta={eta:.0f}s    ",
                      end="\r", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(process, code) for code in codes]
        for f in as_completed(futures):
            f.result()

    print()
    print(f"Done: {len(results):,} ok  {len(errors):,} errors")

    err_path = OUT / "scrape_errors.csv"
    if errors:
        with open(err_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["mpio_reg_code_7", "error"])
            w.writeheader()
            w.writerows(errors)
    elif update_mode and err_path.exists():
        err_path.unlink()

    if not results:
        return

    fresh_codes = {r["mpio_reg_code_7"] for r in results}
    if update_mode and MPIO_CSV.exists():
        with open(MPIO_CSV) as f:
            existing = list(csv.DictReader(f))
        results = [r for r in existing if r["mpio_reg_code_7"] not in fresh_codes] + results

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
    with open(MPIO_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, 0) for k in fields})

    n_ext = sum(1 for r in results if str(r.get("mpio_reg_code_7", "")).startswith("88"))
    print(f"Saved: {len(results):,} rows  ({len(results)-n_ext} national + {n_ext} exterior)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    scrape(update_mode=args.update)
