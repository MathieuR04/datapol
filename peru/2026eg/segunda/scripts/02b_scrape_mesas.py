"""
02b_scrape_mesas.py — Peru 2026 EG Segunda Vuelta
Scrape polling-table (mesa) level presidencial results.

WHY curl_cffi
-------------
The ONPE API is behind a WAF that blocks non-browser TLS fingerprints.
curl_cffi with impersonate="chrome124" bypasses it; aiohttp/requests cannot.

ENDPOINT
--------
  GET /presentacion-backend/actas/buscar/mesa?codigoMesa=NNNNNN
  Returns up to 5 acta dicts (one per election). HTTP 204 = mesa absent.

We keep only idEleccion=10 (Presidencial).

OUTPUT
------
  data/results/peru_2026eg_mesa_segunda.csv

One row per mesa that exists and has a presidencial acta.
Columns:
  codigo_mesa, ubigeo_distrito,
  codigo_local_votacion, nombre_local_votacion,
  electores_habiles, votos_emitidos, votos_validos, votos_blancos, votos_nulos,
  actas_total (always 1), actas_contabilizadas (1 if estado==C else 0),
  estado_acta, ever_E, descripcion_error,
  cand_<codigo> … (one per candidate in candidates.json)

Prerequisites
-------------
  pip install curl_cffi
  Run 01_build_candidate_json.py first to populate 'codcan' in candidates.json.

Usage
-----
  python3 02b_scrape_mesas.py                        # full run (1 → 92766)
  python3 02b_scrape_mesas.py --start 1 --end 500    # test slice
  python3 02b_scrape_mesas.py --workers 8
  python3 02b_scrape_mesas.py --update               # re-fetch non-C actas
"""

import argparse
import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("curl_cffi not installed. Run: pip install curl_cffi")

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
RESULTS    = DATA_DIR / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

BASE_URL      = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend"
ID_ELECCION   = 10  # Confirmed: segunda vuelta uses same idEleccion=10 as primera (presidencial)
TOTAL_MESAS   = 92_791      # national + exterior sequential range

MESA_CSV   = RESULTS / "peru_2026eg_mesa_segunda.csv"
CKPT_FILE  = RESULTS / ".mesa_checkpoint.json"

FLUSH_EVERY    = 1_000      # write to CSV every N completed mesas
BATCH_PAUSE_N  = 10_000     # pause after every N requests
BATCH_PAUSE_S  = 5          # seconds to pause
DELAY_MIN      = 0.02
DELAY_MAX      = 0.08

_write_lock = Lock()


# ── Candidates ─────────────────────────────────────────────────────────────────

def load_candidates() -> tuple[dict[int, str], list[str]]:
    """Load candidates.json. Returns (codcan_map, cand_cols).
    codcan_map: {adAgrupacionPolitica int → cand_<codigo> column name}
    """
    path = DATA_DIR / "candidates.json"
    with open(path) as f:
        cands = json.load(f)

    missing_codcan = [c.get("nombre", c.get("codigo")) for c in cands if "codcan" not in c]
    if missing_codcan:
        print(f"WARN: {len(missing_codcan)} candidates missing 'codcan' in candidates.json.")
        print("  Run 01_build_candidate_json.py first to populate codcan.")
        print("  Candidate votes will NOT be mapped until codcan is set.")

    codcan_map = {c["codcan"]: f"cand_{c['codigo']}"
                  for c in cands if "codcan" in c}
    cand_cols  = [f"cand_{c['codigo']}" for c in cands]
    return codcan_map, cand_cols


# ── Session ─────────────────────────────────────────────────────────────────────

def make_session():
    s = cffi_requests.Session(impersonate="chrome124")
    s.headers.update({
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer":         "https://resultadosegundavuelta.onpe.gob.pe/main/actas",
        "Origin":          "https://resultadosegundavuelta.onpe.gob.pe",
    })
    return s


# ── Fetch ───────────────────────────────────────────────────────────────────────

def fetch_mesa(session, codigo: str, retries: int = 4):
    """Return list of acta dicts for this mesa, or None if absent/failed."""
    url = f"{BASE_URL}/actas/buscar/mesa"
    for attempt in range(retries):
        try:
            r = session.get(url, params={"codigoMesa": codigo}, timeout=20)
            if r.status_code == 204:
                return None
            if r.status_code == 429:
                time.sleep(60 * (attempt + 1))
                continue
            if r.status_code == 503:
                time.sleep(30)
                continue
            r.raise_for_status()
            text = r.text.strip()
            if not text:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            data = r.json().get("data") or []
            return data if data else None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"\n  [{codigo}] Failed: {e}")
                return None


# ── Parse ───────────────────────────────────────────────────────────────────────

def parse_acta(acta: dict, codcan_map: dict, cand_cols: list) -> dict:
    """Extract one CSV row from a presidencial acta dict."""
    codigo  = str(acta.get("codigoMesa") or "").zfill(6)
    ubigeo  = str(acta.get("idUbigeo") or "").zfill(6)
    estado  = acta.get("codigoEstadoActa") or ""

    timeline = acta.get("lineaTiempo") or []
    ever_E   = any(s.get("codigoEstadoActa") == "E" for s in timeline)
    errores  = " | ".join(filter(None, (
        s.get("descripcionEstadoActaResolucion") for s in timeline)))

    if not codigo or codigo == "000000":
        return None

    row = {
        "codigo_mesa":              codigo,
        "ubigeo_distrito":          ubigeo,
        "codigo_local_votacion":    str(acta.get("codigoLocalVotacion") or "").strip(),
        "nombre_local_votacion":    str(acta.get("nombreLocalVotacion") or "").strip(),
        "electores_habiles":        int(acta.get("totalElectoresHabiles") or 0),
        "votos_emitidos":           int(acta.get("totalVotosEmitidos")    or 0),
        "votos_validos":            int(acta.get("totalVotosValidos")     or 0),
        "votos_blancos":            0,
        "votos_nulos":              0,
        "actas_total":              1,
        "actas_contabilizadas":     1 if estado == "C" else 0,
        "estado_acta":              estado,
        "ever_E":                   ever_E,
        "descripcion_error":        errores,
    }
    for col in cand_cols:
        row[col] = 0

    detalle = acta.get("detalle") or []

    # Atomicity guard: if acta is Contabilizada and voters were cast but the
    # vote-breakdown list is empty, refuse the row entirely so the mesa stays
    # pending and gets re-fetched on the next --update run.  This prevents
    # saving a row with estado="C" but all candidate columns = 0, which would
    # cause --update to skip it forever and never recover the vote data.
    if estado == "C" and int(acta.get("totalVotosEmitidos") or 0) > 0 and not detalle:
        return None

    for entry in detalle:
        codap = int(entry.get("adAgrupacionPolitica") or 0)
        votos = int(entry.get("adVotos") or 0)
        if codap == 80:
            row["votos_blancos"] = votos
        elif codap == 81:
            row["votos_nulos"]   = votos
        else:
            col = codcan_map.get(codap)
            if col:
                row[col] = votos

    return row


# ── Checkpoint ──────────────────────────────────────────────────────────────────

def load_checkpoint() -> set:
    if CKPT_FILE.exists():
        with open(CKPT_FILE) as f:
            return set(json.load(f))
    return set()


def save_checkpoint(done: set):
    with open(CKPT_FILE, "w") as f:
        json.dump(sorted(done), f)


# ── CSV I/O ─────────────────────────────────────────────────────────────────────

def _fields(cand_cols: list) -> list:
    return (
        ["codigo_mesa", "ubigeo_distrito",
         "codigo_local_votacion", "nombre_local_votacion",
         "electores_habiles", "votos_emitidos", "votos_validos",
         "votos_blancos", "votos_nulos",
         "actas_total", "actas_contabilizadas",
         "estado_acta", "ever_E", "descripcion_error"]
        + cand_cols
    )


def init_csv(cand_cols: list):
    """Write header to a fresh CSV."""
    with open(MESA_CSV, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=_fields(cand_cols)).writeheader()


def append_rows(rows: list, cand_cols: list):
    if not rows:
        return
    fields = _fields(cand_cols)
    with _write_lock:
        with open(MESA_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            for row in rows:
                w.writerow({k: row.get(k, "") for k in fields})


def load_existing_rows() -> dict:
    """Return {codigo_mesa: row_dict} for resume/update."""
    if not MESA_CSV.exists():
        return {}
    with open(MESA_CSV, newline="") as f:
        return {r["codigo_mesa"]: r for r in csv.DictReader(f)}


def rewrite_csv(rows: dict, cand_cols: list):
    """Overwrite entire CSV from a dict of rows."""
    fields = _fields(cand_cols)
    with open(MESA_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in sorted(rows.values(), key=lambda r: r.get("codigo_mesa", "")):
            w.writerow({k: row.get(k, "") for k in fields})


# ── Worker ──────────────────────────────────────────────────────────────────────

class Worker:
    def __init__(self, wid: int):
        self.id      = wid
        self.session = make_session()

    def process(self, numero: int, codcan_map: dict, cand_cols: list):
        codigo = str(numero).zfill(6)
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        actas = fetch_mesa(self.session, codigo)
        if actas is None:
            return codigo, None
        for acta in actas:
            if acta.get("idEleccion") == ID_ELECCION:
                return codigo, parse_acta(acta, codcan_map, cand_cols)
        return codigo, None


# ── Full run ────────────────────────────────────────────────────────────────────

def run(start: int, end: int, n_workers: int, codcan_map: dict, cand_cols: list):
    done = load_checkpoint()
    todo = [i for i in range(start, end + 1) if str(i).zfill(6) not in done]

    print(f"\n{'='*60}")
    print(f"ONPE 2026 Scraper — Full Run")
    print(f"Range  : {start:,} → {end:,}  ({len(todo):,} to fetch)")
    print(f"Done   : {len(done):,} in checkpoint")
    print(f"Workers: {n_workers}    Output: {MESA_CSV.name}")
    print(f"{'='*60}\n")

    if not MESA_CSV.exists() or not done:
        init_csv(cand_cols)

    workers   = [Worker(i) for i in range(n_workers)]
    buffer    = []
    total_req = 0
    ok_count  = 0
    t0        = time.time()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(workers[i % n_workers].process, num, codcan_map, cand_cols): num
            for i, num in enumerate(todo)
        }
        for future in as_completed(futures):
            num = futures[future]
            total_req += 1
            try:
                codigo, row = future.result()
            except Exception as e:
                codigo = str(num).zfill(6)
                print(f"\n  Error on {codigo}: {e}")
                row = None

            if row is not None:
                buffer.append(row)
                ok_count += 1
            done.add(str(num).zfill(6))

            n_done = len(done)
            if n_done % 500 == 0 or n_done == len(todo) + len(done) - len(todo):
                elapsed = time.time() - t0
                rate    = total_req / elapsed if elapsed else 0
                eta     = (len(todo) - total_req) / rate if rate else 0
                print(f"  [{total_req:5d}/{len(todo)}]  found={ok_count}"
                      f"  {rate:.0f}/s  eta={eta:.0f}s")

            if len(buffer) >= FLUSH_EVERY:
                append_rows(buffer, cand_cols)
                buffer = []
                save_checkpoint(done)

            if total_req % BATCH_PAUSE_N == 0:
                print(f"  Pausing {BATCH_PAUSE_S}s …")
                time.sleep(BATCH_PAUSE_S)

    append_rows(buffer, cand_cols)
    save_checkpoint(done)
    print(f"\nDone: {ok_count:,} mesas with presidencial acta  →  {MESA_CSV.name}")


# ── Retry-nulls run ─────────────────────────────────────────────────────────────

def run_retry_nulls(n_workers: int, codcan_map: dict, cand_cols: list,
                    upper: int = TOTAL_MESAS):
    """Re-fetch codes that previously returned 204/null + any unchecked codes above old range."""
    done     = load_checkpoint()          # all codes ever tried (zero-padded strings)
    csv_rows = load_existing_rows()       # codes that actually yielded a row
    csv_codes = set(csv_rows.keys())

    # Codes tried but returned null
    nulls = sorted(done - csv_codes, key=lambda c: int(c))
    # Codes never tried (above old range)
    untried = [str(i).zfill(6) for i in range(1, upper + 1)
               if str(i).zfill(6) not in done]
    todo = nulls + untried

    print(f"\n{'='*60}")
    print(f"ONPE 2026 Scraper — Retry-Nulls Run")
    print(f"  Prev nulls (204 / no data): {len(nulls):,}")
    print(f"  Unchecked codes:            {len(untried):,}")
    print(f"  Total to retry:             {len(todo):,}")
    print(f"{'='*60}\n")

    if not todo:
        print("Nothing to retry.")
        return

    workers = [Worker(i) for i in range(n_workers)]
    new_rows = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(workers[i % n_workers].process, int(c), codcan_map, cand_cols): c
            for i, c in enumerate(todo)
        }
        for req_n, future in enumerate(as_completed(futures), 1):
            codigo = futures[future]
            try:
                _, row = future.result()
            except Exception as e:
                print(f"\n  Error on {codigo}: {e}")
                row = None

            done.add(codigo)
            if row is not None:
                csv_rows[codigo] = row
                new_rows.append(row)

            if req_n % 500 == 0 or req_n == len(todo):
                elapsed = time.time() - t0
                rate    = req_n / elapsed if elapsed else 0
                eta     = (len(todo) - req_n) / rate if rate else 0
                print(f"  [{req_n:5d}/{len(todo)}]  found={len(new_rows)}"
                      f"  {rate:.0f}/s  eta={eta:.0f}s")

            if req_n % BATCH_PAUSE_N == 0:
                print(f"  Pausing {BATCH_PAUSE_S}s …")
                time.sleep(BATCH_PAUSE_S)

    # Rewrite full CSV and update checkpoint
    rewrite_csv(csv_rows, cand_cols)
    save_checkpoint(done)
    print(f"\nRetry complete: {len(new_rows):,} new rows found  →  {MESA_CSV.name}")
    print(f"Total mesas in CSV: {len(csv_rows):,}")


# ── Update run ──────────────────────────────────────────────────────────────────

def run_update(n_workers: int, codcan_map: dict, cand_cols: list):
    """Re-fetch mesas whose acta is not yet Contabilizada, or is C but has no vote data."""
    existing = load_existing_rows()

    def _needs_update(row: dict) -> bool:
        estado = row.get("estado_acta", "")
        if not estado:
            return False               # no data at all (exterior / missing)
        if estado != "C":
            return True                # not yet counted
        # estado == "C" but vote breakdown may be missing (partial prior scrape):
        # if emitted > 0 but votos_validos == 0, we never got the detalle.
        def _int(v): return int(v) if str(v).strip() not in ("", "None") else 0
        return _int(row.get("votos_emitidos", 0)) > 0 and \
               _int(row.get("votos_validos",  0)) == 0

    pending = [r["codigo_mesa"] for r in existing.values() if _needs_update(r)]

    print(f"\n{'='*60}")
    print(f"ONPE 2026 Scraper — Update Run")
    print(f"Re-fetching {len(pending):,} non-Contabilizada mesas")
    print(f"{'='*60}\n")

    if not pending:
        print("Nothing to update — all mesas are Contabilizada or absent.")
        return

    workers = [Worker(i) for i in range(n_workers)]
    buffer  = []
    ok      = 0
    t0      = time.time()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(workers[i % n_workers].process, int(c), codcan_map, cand_cols): c
            for i, c in enumerate(pending)
        }
        for req_n, future in enumerate(as_completed(futures), 1):
            codigo = futures[future]
            try:
                _, row = future.result()
            except Exception as e:
                print(f"\n  Error on {codigo}: {e}")
                row = None
            if row is not None:
                # preserve ever_E: once True, never reverts
                prev_ever_E = str(existing.get(codigo, {}).get("ever_E", "")).lower() == "true"
                if prev_ever_E:
                    row["ever_E"] = True
                existing[codigo] = row
                ok += 1

            if req_n % 500 == 0 or req_n == len(pending):
                elapsed = time.time() - t0
                rate    = req_n / elapsed if elapsed else 0
                print(f"  [{req_n:5d}/{len(pending)}]  updated={ok}  {rate:.0f}/s")

            if req_n % BATCH_PAUSE_N == 0:
                print(f"  Pausing {BATCH_PAUSE_S}s …")
                time.sleep(BATCH_PAUSE_S)

    rewrite_csv(existing, cand_cols)
    print(f"\nUpdate complete: {ok:,} rows refreshed  →  {MESA_CSV.name}")


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Scrape ONPE 2026 mesa-level presidencial results")
    p.add_argument("--start",   type=int, default=1,           help="First mesa number (default: 1)")
    p.add_argument("--end",     type=int, default=TOTAL_MESAS, help=f"Last mesa number (default: {TOTAL_MESAS})")
    p.add_argument("--workers", type=int, default=20,          help="Parallel workers (default: 20)")
    p.add_argument("--update",        action="store_true", help="Re-fetch non-Contabilizada actas")
    p.add_argument("--retry-nulls",   action="store_true", help="Re-fetch codes that previously returned 204 + unchecked codes above old range")
    p.add_argument("--full-refresh",  action="store_true", help="Clear checkpoint + CSV and re-scrape everything from scratch (picks up new columns)")
    args = p.parse_args()

    codcan_map, cand_cols = load_candidates()

    if args.full_refresh:
        print("Full refresh: clearing checkpoint and CSV …")
        CKPT_FILE.unlink(missing_ok=True)
        MESA_CSV.unlink(missing_ok=True)
        run(start=1, end=92766, n_workers=args.workers,
            codcan_map=codcan_map, cand_cols=cand_cols)
        # Also scrape exterior range
        run(start=900001, end=904703, n_workers=args.workers,
            codcan_map=codcan_map, cand_cols=cand_cols)
    elif args.retry_nulls:
        run_retry_nulls(n_workers=args.workers, codcan_map=codcan_map, cand_cols=cand_cols)
    elif args.update:
        run_update(n_workers=args.workers, codcan_map=codcan_map, cand_cols=cand_cols)
    else:
        run(start=args.start, end=args.end, n_workers=args.workers,
            codcan_map=codcan_map, cand_cols=cand_cols)


if __name__ == "__main__":
    main()
