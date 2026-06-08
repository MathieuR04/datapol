"""
02a_scrape_distritos.py — Peru 2026 EG Segunda Vuelta
Scrape district-level presidencial results directly from ONPE API.

Hits two GET endpoints per district (~2102 districts, runs in ~1-2 min):
  GET /resumen-general/totales?idAmbitoGeografico=...&idEleccion=10
      &tipoFiltro=ubigeo_nivel_03&idUbigeoDepartamento=...
      &idUbigeoProvincia=...&idUbigeoDistrito=...

  GET /resumen-general/participantes  (same params)

The totales endpoint returns actas counts + vote totals.
The participantes endpoint returns per-candidate vote breakdown.

NOTE: curl_cffi required — AWS CloudFront WAF returns empty bodies to
standard Python HTTP clients (urllib/requests/aiohttp).

Output:
  data/results/peru_2026eg_distrito_segunda.csv

One row per district (national + exterior).

Options:
  --update   Only re-fetch districts where actas_contabilizadas < actas_total
"""

import argparse
import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("curl_cffi not installed. Run: pip install curl_cffi")

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
METADATA   = SCRIPT_DIR.parent.parent / "metadata"
RESULTS    = DATA_DIR / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DIST_CSV = RESULTS / "peru_2026eg_distrito_segunda.csv"
ROLL_CSV = METADATA / "peru_2026_distrito_electoral_roll.csv"

BASE_URL    = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend/"
ID_ELECCION = 10  # Confirmed: segunda vuelta uses same idEleccion=10 as primera (presidencial)
TIPO_FILTRO = "ubigeo_nivel_03"
CONCURRENCY = 5
DELAY_MIN   = 0.02
DELAY_MAX   = 0.08


# ── Candidates ──────────────────────────────────────────────────────────────────

def load_candidates() -> tuple[dict[int, str], list[str]]:
    """Returns (codcan_map, cand_cols). codcan → column name."""
    with open(DATA_DIR / "candidates.json") as f:
        cands = json.load(f)
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
        "Referer":         "https://resultadosegundavuelta.onpe.gob.pe/main/presidenciales",
        "Origin":          "https://resultadosegundavuelta.onpe.gob.pe",
    })
    return s


# ── Ubigeo helpers ──────────────────────────────────────────────────────────────

def _is_exterior(ubigeo: str) -> bool:
    return ubigeo.startswith("9")


def _build_params(ubigeo_dist: str, ubigeo_prov: str, ubigeo_dept: str) -> dict:
    """Build query params; ubigeos sent as zero-padded strings (API requires this)."""
    amb = 2 if _is_exterior(ubigeo_dist) else 1
    return {
        "idAmbitoGeografico":  amb,
        "idEleccion":          ID_ELECCION,
        "tipoFiltro":          TIPO_FILTRO,
        "idUbigeoDepartamento": ubigeo_dept,
        "idUbigeoProvincia":   ubigeo_prov,
        "idUbigeoDistrito":    ubigeo_dist,
    }


def _build_params_nivel(ubigeo_dist: str, ubigeo_prov: str, ubigeo_dept: str) -> dict:
    """Build params for eleccion-presidencial/participantes-ubicacion-geografica-nombre.
    This endpoint uses ubigeoNivel1/2/3 (zero-padded strings) and returns codes 80/81."""
    amb = 2 if _is_exterior(ubigeo_dist) else 1
    return {
        "tipoFiltro":       TIPO_FILTRO,
        "idAmbitoGeografico": amb,
        "ubigeoNivel1":     ubigeo_dept,
        "ubigeoNivel2":     ubigeo_prov,
        "ubigeoNivel3":     ubigeo_dist,
        "listContinentals": "",
        "listCountries":    "",
        "idEleccion":       ID_ELECCION,
    }


# ── Fetch ───────────────────────────────────────────────────────────────────────

def _get(session, path: str, params: dict, retries: int = 3):
    url = BASE_URL + path
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 204:
                return None
            if r.status_code == 429:
                time.sleep(60 * (attempt + 1))
                continue
            if r.status_code not in (200, 404):
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            if r.status_code == 404:
                return None
            text = r.text.strip()
            if not text:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            d = r.json()
            return d.get("data") if d.get("success") else None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return None
    return None


def fetch_district(session, ubigeo_dist: str, ubigeo_prov: str,
                   ubigeo_dept: str, codcan_map: dict, cand_cols: list) -> dict | None:
    """Fetch totales + participantes for one district; return combined row."""
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    params       = _build_params(ubigeo_dist, ubigeo_prov, ubigeo_dept)
    params_nivel = _build_params_nivel(ubigeo_dist, ubigeo_prov, ubigeo_dept)

    totales       = _get(session, "resumen-general/totales", params)
    participantes = _get(session,
                         "eleccion-presidencial/participantes-ubicacion-geografica-nombre",
                         params_nivel)

    # Both endpoints must succeed — if either fails the whole district is
    # skipped so we never write a partially-filled row.
    if totales is None or participantes is None:
        return None

    votos_emitidos = int((totales or {}).get("totalVotosEmitidos", 0) or 0)

    row = {
        "ubigeo_distrito":      ubigeo_dist,
        "votos_validos":        0,
        "votos_emitidos":       votos_emitidos,
        "votos_blancos":        0,
        "votos_nulos":          0,
        "actas_contabilizadas": int((totales or {}).get("contabilizadas", 0) or 0),
        "actas_total":          int((totales or {}).get("totalActas",      0) or 0),
    }
    for col in cand_cols:
        row[col] = 0

    for entry in (participantes or []):
        codap = int(entry.get("codigoAgrupacionPolitica") or 0)
        votos = int(entry.get("totalVotosValidos")        or 0)
        if codap == 80:
            row["votos_blancos"] = votos
        elif codap == 81:
            row["votos_nulos"] = votos
        else:
            col = codcan_map.get(codap)
            if col:
                row[col] = votos

    # votos_validos = sum of candidate votes (Peru definition; authoritative over totales endpoint)
    row["votos_validos"] = sum(row[col] for col in cand_cols)

    return row


# ── CSV ─────────────────────────────────────────────────────────────────────────

def _fields(cand_cols: list) -> list:
    return (
        ["ubigeo_distrito", "votos_validos", "votos_blancos", "votos_nulos",
         "votos_emitidos", "actas_contabilizadas", "actas_total"]
        + cand_cols
    )


def write_csv(rows: list, cand_cols: list):
    fields = _fields(cand_cols)
    rows_sorted = sorted(rows, key=lambda r: r.get("ubigeo_distrito", ""))
    with open(DIST_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows_sorted:
            w.writerow({k: row.get(k, 0) for k in fields})


def load_existing() -> dict:
    if not DIST_CSV.exists():
        return {}
    with open(DIST_CSV, newline="") as f:
        return {r["ubigeo_distrito"]: r for r in csv.DictReader(f)}


# ── Main scrape ─────────────────────────────────────────────────────────────────

def scrape(update_mode: bool = False):
    codcan_map, cand_cols = load_candidates()

    # Load roll
    roll: list[tuple[str, str, str]] = []  # (ubigeo_dist, ubigeo_prov, ubigeo_dept)
    seen: set[str] = set()
    with open(ROLL_CSV) as f:
        for row in csv.DictReader(f):
            u = row["ubigeo_distrito"]
            if u not in seen:
                seen.add(u)
                roll.append((u, row["ubigeo_provincia"], row["ubigeo_dept"]))

    if update_mode and DIST_CSV.exists():
        existing = load_existing()
        def _needs_update(row: dict) -> bool:
            def _int(v): return int(v) if str(v).strip() not in ("", "None") else 0
            at = _int(row.get("actas_total", 0))
            ac = _int(row.get("actas_contabilizadas", 0))
            vv = _int(row.get("votos_validos", 0))
            return at == 0 or ac < at or vv == 0
        todo = [
            (u, p, d) for u, p, d in roll
            if u not in existing or _needs_update(existing[u])
        ]
        if not todo:
            print("All districts fully contabilizados — nothing to update.")
            return
    else:
        existing = {}
        todo = roll

    print(f"{'Update' if update_mode else 'Full'} scrape: {len(todo):,} districts …")

    workers  = [make_session() for _ in range(CONCURRENCY)]
    results  = []
    errors   = []
    t0       = time.time()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(fetch_district, workers[i % CONCURRENCY], u, p, d, codcan_map, cand_cols): u
            for i, (u, p, d) in enumerate(todo)
        }
        for done_n, future in enumerate(as_completed(futures), 1):
            ubigeo = futures[future]
            try:
                row = future.result()
            except Exception as e:
                row = None
                errors.append(ubigeo)
            if row is not None:
                results.append(row)
            else:
                errors.append(ubigeo)

            if done_n % 100 == 0 or done_n == len(todo):
                elapsed = time.time() - t0
                rate = done_n / elapsed if elapsed else 0
                eta  = (len(todo) - done_n) / rate if rate else 0
                print(f"  [{done_n:4d}/{len(todo)}]  ok={len(results)}  err={len(errors)}"
                      f"  {rate:.0f}/s  eta={eta:.0f}s")

    # Merge with existing if update
    if update_mode:
        existing.update({r["ubigeo_distrito"]: r for r in results})
        all_rows = list(existing.values())
    else:
        scraped = {r["ubigeo_distrito"] for r in results}
        # Zero-stub rows for districts that returned no data
        stubs = [{"ubigeo_distrito": u} for u, _, _ in roll if u not in scraped]
        all_rows = results + stubs

    write_csv(all_rows, cand_cols)
    print(f"\nSaved: {len(all_rows):,} rows → {DIST_CSV.name}")
    if errors:
        err_path = DATA_DIR / "scrape_errors_distritos.csv"
        with open(err_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ubigeo_distrito"])
            w.writeheader()
            for u in errors:
                w.writerow({"ubigeo_distrito": u})
        print(f"  {len(errors)} errors → {err_path.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape ONPE district-level presidencial results")
    parser.add_argument("--update", action="store_true",
                        help="Only re-fetch incomplete districts")
    args = parser.parse_args()
    scrape(update_mode=args.update)
