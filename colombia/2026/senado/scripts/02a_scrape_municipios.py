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
import json
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
        "mesas_total":        int(totales.get("metota")  or 0),
        "mesas_escrutadas":   int(totales.get("mesesc")  or 0),
        "censo":              int(totales.get("centota") or 0),
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
        ccol = "icand" if cam == 4 else "cand"
        for pw in camara.get("partotabla", []):
            p    = pw.get("act", pw)
            cod  = int(p.get("codpar", 0))
            vot  = p.get("vot")
            pkey = f"{pcol}_{cod:04d}"
            record[pkey] = record.get(pkey, 0) + (int(vot) if vot else 0)
            # candidate votes within each party
            for cand in p.get("cantotabla", []):
                codcan   = int(cand.get("codcan", 0))
                nom      = f"{cand.get('nomcan','').strip()} {cand.get('apecan','').strip()}".strip()
                cand_vot = cand.get("vot")
                ckey     = f"{ccol}_{cod:04d}_{codcan:06d}|{nom}"
                record[ckey] = record.get(ckey, 0) + (int(cand_vot) if cand_vot else 0)

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


def write_preferencial_csv(path: Path, rows: list[dict],
                            cand_cols: list[str], prefix: str) -> None:
    """
    Aggregate candidate votes across all municipio rows and write a tall
    preferencial CSV: party_code, candidate_code, candidate_name, votes.

    Column name format: <prefix>XXXX_YYYYYY|Candidate Name
    e.g. cand_0018_000042|JOSE ANTONIO GARCIA
         icand_0099_000001|ABELARDO RAMOS
    """
    # Sum each candidate column across all municipios
    totals = {col: 0 for col in cand_cols}
    for r in rows:
        for col in cand_cols:
            totals[col] += int(r.get(col) or 0)

    records = []
    for col in cand_cols:
        rest = col[len(prefix):]            # XXXX_YYYYYY|Name
        under = rest.index("_")
        party_code = rest[:under]           # "XXXX"
        rest2 = rest[under + 1:]            # "YYYYYY|Name"
        pipe = rest2.index("|") if "|" in rest2 else len(rest2)
        candidate_code = rest2[:pipe]       # "YYYYYY"
        candidate_name = rest2[pipe + 1:] if "|" in rest2 else ""
        records.append({
            "party_code":     party_code,
            "candidate_code": candidate_code,
            "candidate_name": candidate_name,
            "votes":          totals[col],
        })

    records.sort(key=lambda r: (r["party_code"], -r["votes"]))

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["party_code", "candidate_code", "candidate_name", "votes"])
        w.writeheader()
        w.writerows(records)
    print(f"  Saved preferencial: {path.name}  ({len(records)} candidates)")


# ── Main ───────────────────────────────────────────────────────────────────────

def municipios_needing_update():
    codes = set()

    # 1. Municipios with incomplete mesas reporting
    nat_path = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
    if nat_path.exists():
        with open(nat_path) as f:
            reader = csv.DictReader(f)
            party_cols = [c for c in (reader.fieldnames or []) if c.startswith("party_")]
            for row in reader:
                me = int(row.get("mesas_escrutadas") or 0)
                mt = int(row.get("mesas_total")      or 0)
                if me < mt or mt == 0:
                    codes.add(row["mpio_reg_code_7"])
                # Nacional party breakdown missing despite having valid votes
                elif int(row.get("votos_validos") or 0) > 0:
                    if all(int(row.get(c) or 0) == 0 for c in party_cols):
                        codes.add(row["mpio_reg_code_7"])

    # 2. Indigena party breakdown missing despite having valid votes
    ind_path = RESULTS / "colombia_2026_municipio_senado_indigena.csv"
    if ind_path.exists():
        with open(ind_path) as f:
            reader = csv.DictReader(f)
            indig_cols = [c for c in (reader.fieldnames or []) if c.startswith("indig_")]
            for row in reader:
                if int(row.get("votos_validos") or 0) > 0:
                    if all(int(row.get(c) or 0) == 0 for c in indig_cols):
                        codes.add(row["mpio_reg_code_7"])

    # 3. Codes that errored in the last scrape
    err_path = OUT / "scrape_errors.csv"
    if err_path.exists():
        with open(err_path) as f:
            for row in csv.DictReader(f):
                codes.add(row["mpio_reg_code_7"])

    return list(codes)


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

    err_path = OUT / "scrape_errors.csv"
    if errors:
        write_csv(err_path, errors, ["mpio_reg_code_7", "error"])
    elif update_mode and err_path.exists():
        err_path.unlink()   # all previously-errored codes now OK — clear the file

    if not results: return

    # Remember which codes were freshly scraped BEFORE merging with the nacional CSV.
    # The nacional CSV only has party_ columns (not indig_), so merged rows from it
    # lose all indig_ data.  We need fresh_codes later to restore indigena data.
    fresh_codes = {r["mpio_reg_code_7"] for r in results}

    # Merge with existing rows in update mode
    if update_mode:
        path = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
        if path.exists():
            with open(path) as f:
                existing  = list(csv.DictReader(f))
            results   = [r for r in existing if r["mpio_reg_code_7"] not in fresh_codes] + results

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

    cand_cols  = sorted(k for k in all_keys if k.startswith("cand_"))
    icand_cols = sorted(k for k in all_keys if k.startswith("icand_"))

    # ── Nacional CSV ──────────────────────────────────────────────────────────
    nat_fields = (
        ["mpio_reg_code_7", "censo", "votantes", "votos_nulos", "votos_no_marcados",
         "votos_blanco", "votos_validos", "mesas_total", "mesas_escrutadas",
         "ind_votantes", "ind_votos_validos", "ind_votos_blanco", "ind_votos_nulos"]
        + party_cols + cand_cols
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
        for k in indig_cols + icand_cols:
            ind_r[k] = int(r.get(k) or 0)
        ind_out.append(ind_r)

    # In update mode: rows from the nacional CSV merge have no indig_ columns.
    # Restore indig_ party votes + icand_ candidate votes for non-freshly-scraped rows.
    if update_mode:
        ind_existing_path = RESULTS / "colombia_2026_municipio_senado_indigena.csv"
        if ind_existing_path.exists():
            with open(ind_existing_path) as f:
                reader      = csv.DictReader(f)
                old_indig   = {row["mpio_reg_code_7"]: row for row in reader}
            for ind_r in ind_out:
                code = ind_r["mpio_reg_code_7"]
                if code not in fresh_codes and code in old_indig:
                    old = old_indig[code]
                    for k in indig_cols + icand_cols:
                        ind_r[k] = int(old.get(k) or 0)

    ind_fields = (
        ["mpio_reg_code_7", "votantes", "votos_validos", "votos_blanco",
         "votos_nulos", "votos_no_marcados", "mesas_total", "mesas_escrutadas"]
        + indig_cols + icand_cols
    )
    write_csv(RESULTS / "colombia_2026_municipio_senado_indigena.csv", ind_out, ind_fields)
    n_ext_i = sum(1 for r in ind_out if str(r.get("mpio_reg_code_7", "")).startswith("88"))
    print(f"Saved indigena:  {len(ind_out):,} rows  "
          f"({len(ind_out)-n_ext_i} national + {n_ext_i} exterior)")

    # ── Preferencial CSVs (nationally aggregated candidate votes) ────────────
    # Candidate columns (cand_/icand_) are kept in the municipio CSVs so that
    # update-mode merges can carry forward per-municipio contributions correctly.
    # These preferencial files aggregate the same data into a tall, clean format
    # (one row per candidate) for seat allocation and future analysis.
    write_preferencial_csv(
        RESULTS / "colombia_2026_senado_nacional_preferencial.csv",
        results, cand_cols, "cand_")
    write_preferencial_csv(
        RESULTS / "colombia_2026_senado_indigena_preferencial.csv",
        ind_out, icand_cols, "icand_")

    # Party JSONs (national_parties.json / indigena_parties.json) are static
    # metadata files (code, nombre, display_name, color).  They are created once
    # by 01_build_party_jsons.py and never modified by the scraper.
    # All vote totals are derived from the CSVs in data/results/ by 05_seat_allocation.py.


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="Only re-scrape municipios not yet fully escrutados")
    args = parser.parse_args()
    scrape(update_mode=args.update)
