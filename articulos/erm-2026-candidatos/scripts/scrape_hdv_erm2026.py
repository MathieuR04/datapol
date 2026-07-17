"""
scrape_hdv_erm2026.py — JNE *hoja de vida* (HDV) scraper for **ERM2026 candidates only**.

Companion to scrape_erm2026.py. Where that script gets the candidate LISTS, this one
walks every candidate's `hoja_vida_id` and pulls the full consolidated CV — the same
data the JNE "plataforma histórico" renders under DetalleHDV, including the centerpiece
of this deliverable:

  V. RELACIÓN DE SENTENCIAS
    · lSentenciaPenal   → sentencias PENALES  (delito, fallo, modalidad, cumplimiento)
    · lSentenciaObliga  → sentencias CIVILES / que obligan a pago (materia, fallo)

plus, for free in the same payload: education, patrimonio (bienes/ingresos), and the
candidate's photo filename (oDatosPersonales.UrlFoto). See docs/api-notes.md.

ENDPOINT (one GET returns the entire HDV as a single `data` object):

    GET /HojaVida/GetHVConsolidado?param={idHojaVida}-0-{idOrganizacionPolitica}-{idProceso}

All three ids are already in data/erm2026_candidatos.csv (hoja_vida_id / organizacion_id
/ proceso_id), so no discovery walk is needed — the work list is just the CSV's unique
hoja_vida_id set (~92.6k).

STORAGE — a single SQLite warehouse: data/hdv/hdv_erm2026.sqlite  (gitignored; "local now,
R2 later"). ERM2026-only — an EG2026 HDV pull, if ever needed, would be its own DB/script.
Two concerns kept apart:
  · raw(hoja_vida_id)   — the ENTIRE response, zlib-compressed. Source of truth; lets us
                          extract new fields later (bienes, ingresos, …) WITHOUT re-scraping.
  · parsed tables       — what we've extracted so far (sentencias + a small summary).
`--reparse` rebuilds the parsed tables from stored raw with NO network — so widening the
parser is cheap and offline. The DB itself is the checkpoint: resumable by construction.

RELIABILITY: identical to scrape_erm2026.py (curl_cffi chrome impersonation, per-thread
cookie-bootstrapped sessions, 1–3 s jitter, exponential backoff, Imperva HTML-challenge
detection → refresh cookies, HTTP-000 retry). Plain urllib gets Imperva-blocked; curl_cffi
does not (verified: 200/200 at 8 workers).

INCREMENTAL / --update: a candidate's HDV is keyed by hoja_vida_id; we store a `sig`
(a hash of that person's candidacies' estados from the CSV). A row is (re)fetched when it
is NEW or its `sig` changed; unchanged rows are skipped. HDVs rarely change once registered,
so a routine --update is cheap. `--refetch` forces a full re-pull regardless of sig.

USAGE
-----
  python3 scripts/scrape_hdv_erm2026.py                # fetch all not-yet-stored HDVs (resumes)
  python3 scripts/scrape_hdv_erm2026.py --limit 200    # smoke test: first 200 HDVs
  python3 scripts/scrape_hdv_erm2026.py --workers 8    # concurrency (6–9 safe; default 8)
  python3 scripts/scrape_hdv_erm2026.py --update       # re-pull only new/changed (sig diff)
  python3 scripts/scrape_hdv_erm2026.py --refetch      # force re-pull everything
  python3 scripts/scrape_hdv_erm2026.py --reparse      # rebuild parsed tables from raw (no network)

It is also chained automatically at the end of `scrape_erm2026.py --update --with-hdv`
via run() below, so one command refreshes lists + HDVs together.

  pip install curl_cffi
"""

import argparse
import csv
import hashlib
import json
import random
import sqlite3
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("curl_cffi not installed. Run: pip install curl_cffi")

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
CAND_CSV   = DATA_DIR / "erm2026_candidatos.csv"
HDV_DIR    = DATA_DIR / "hdv"
DB_PATH    = HDV_DIR / "hdv_erm2026.sqlite"

# ── API ──────────────────────────────────────────────────────────────────────
HOST      = "https://plataformahistorico.jne.gob.pe"
INDEX_URL = f"{HOST}/ListaDeCandidatos/Index"

# ── Politeness / retry knobs (same as the list scraper) ──────────────────────
DELAY_MIN, DELAY_MAX = 1.0, 3.0
MAX_RETRIES          = 5
CHALLENGE_SLEEP      = 45
COMMIT_EVERY         = 200      # HDVs between DB commits / progress lines

# Education levels, matching the "Grado Académico" filter on the JNE búsqueda avanzada:
# 1 PRIMARIA · 2 SECUNDARIA · 3 TÉCNICO · 4 UNIVERSITARIO · 5 POSGRADO(+)
EDU_PRIMARIA, EDU_SECUNDARIA, EDU_TECNICO, EDU_UNIV, EDU_POSGRADO = 1, 2, 3, 4, 5

_lock   = Lock()
_local  = threading.local()
_stats  = {"challenges": 0, "non200": 0, "neterr": 0, "empty": 0}


def _bump(key):
    with _lock:
        _stats[key] += 1


# ── Session / fetch (copied from scrape_erm2026; returns the `data` OBJECT) ───

def _new_session():
    s = cffi_requests.Session(impersonate="chrome124")
    s.headers.update({"Referer": INDEX_URL})
    try:
        s.get(INDEX_URL, timeout=30)
    except Exception:
        pass
    return s


def _session():
    if getattr(_local, "session", None) is None:
        _local.session = _new_session()
    return _local.session


def fetch_hdv(hoja_vida_id, org_id, proceso_id):
    """GET GetHVConsolidado → (data_dict, raw_bytes). Retries per api-notes §6.
    Returns (None, None) on a genuinely empty/failed payload after retries."""
    url = f"{HOST}/HojaVida/GetHVConsolidado?param={hoja_vida_id}-0-{org_id}-{proceso_id}"
    for attempt in range(MAX_RETRIES):
        try:
            r = _session().get(url, timeout=30)
        except Exception:
            _bump("neterr")
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
        if r.status_code != 200:
            _bump("non200")
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
        body = r.text.lstrip()
        if body[:1] == "<":                              # Imperva HTML challenge
            _bump("challenges")
            time.sleep(CHALLENGE_SLEEP)
            _local.session = _new_session()
            continue
        try:
            payload = r.json() or {}
        except Exception:
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
        data = payload.get("data")
        if not data:                                     # 200 but no CV body
            _bump("empty")
            return None, None
        return data, r.content
    raise RuntimeError(f"giving up after {MAX_RETRIES} retries: hv={hoja_vida_id}")


def jitter():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ── Parsing ──────────────────────────────────────────────────────────────────

def _s(v):
    return None if v is None else str(v).strip() or None


def parse_penal(data):
    """Rows for sentencia_penal from data['lSentenciaPenal']."""
    for it in (data.get("lSentenciaPenal") or []):
        yield (
            it.get("intItemSentenciaPenal"),
            _s(it.get("strExpedientePenal")),
            _s(it.get("strFechaSentenciaPenal")),
            _s(it.get("strOrganoJudiPenal")),
            _s(it.get("strDelitoPenal")),
            _s(it.get("strFalloPenal")),
            _s(it.get("strModalidad")),
            _s(it.get("strCumpleFallo")),
        )


def parse_obliga(data):
    """Rows for sentencia_obliga from data['lSentenciaObliga']."""
    for it in (data.get("lSentenciaObliga") or []):
        yield (
            it.get("intItemSentenciaObliga"),
            _s(it.get("strMateriaSentencia")),
            _s(it.get("strExpedienteObliga")),
            _s(it.get("strOrganoJuridicialObliga")),
            _s(it.get("strFalloObliga")),
        )


def edu_max(data):
    """Best-effort highest education level (see EDU_* constants). Conservative; can be
    refined later from stored raw via --reparse without re-scraping."""
    if data.get("lEduPosgrado") or data.get("oEduPosgrado"):
        return EDU_POSGRADO
    if data.get("lEduUniversitaria"):
        return EDU_UNIV
    nou = data.get("oEduNoUniversitaria")
    if nou and (nou.get("strConcluidoEduNoUniversitaria") == "1"
                or nou.get("strTengoEduNoUniversitaria") == "1"):
        return EDU_TECNICO
    basica = data.get("oEduBasica") or {}
    if basica.get("strEduSecundaria") == "1":
        return EDU_SECUNDARIA
    if basica.get("strEduPrimaria") == "1":
        return EDU_PRIMARIA
    return 0


def foto_filename(data):
    return _s((data.get("oDatosPersonales") or {}).get("UrlFoto"))


# ── SQLite warehouse ─────────────────────────────────────────────────────────

def open_db():
    HDV_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            hoja_vida_id INTEGER PRIMARY KEY,
            org_id       INTEGER,
            proceso_id   INTEGER,
            dni          TEXT,
            sig          TEXT,            -- hash of candidacies' estados (change detection)
            ok           INTEGER,         -- 1 fetched OK, 0 empty/failed
            n_penal      INTEGER,
            n_obliga     INTEGER,
            edu_max      INTEGER,
            foto         TEXT,
            fetched_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS raw (
            hoja_vida_id INTEGER PRIMARY KEY,
            gz           BLOB,            -- zlib-compressed raw JSON response
            fetched_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS sentencia_penal (
            hoja_vida_id INTEGER, item INTEGER, expediente TEXT, fecha TEXT,
            organo TEXT, delito TEXT, fallo TEXT, modalidad TEXT, cumple TEXT
        );
        CREATE TABLE IF NOT EXISTS sentencia_obliga (
            hoja_vida_id INTEGER, item INTEGER, materia TEXT, expediente TEXT,
            organo TEXT, fallo TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_penal_hv  ON sentencia_penal(hoja_vida_id);
        CREATE INDEX IF NOT EXISTS ix_obliga_hv ON sentencia_obliga(hoja_vida_id);
    """)
    db.commit()
    return db


def store_parsed(db, hoja_vida_id, data):
    """(Re)write the parsed sentencia rows + meta summary for one HDV. Idempotent."""
    db.execute("DELETE FROM sentencia_penal  WHERE hoja_vida_id=?", (hoja_vida_id,))
    db.execute("DELETE FROM sentencia_obliga WHERE hoja_vida_id=?", (hoja_vida_id,))
    penal  = list(parse_penal(data))
    obliga = list(parse_obliga(data))
    db.executemany(
        "INSERT INTO sentencia_penal VALUES (?,?,?,?,?,?,?,?,?)",
        [(hoja_vida_id, *row) for row in penal])
    db.executemany(
        "INSERT INTO sentencia_obliga VALUES (?,?,?,?,?,?)",
        [(hoja_vida_id, *row) for row in obliga])
    return len(penal), len(obliga)


# ── Work list from the candidate CSV ─────────────────────────────────────────

def _ndni(s):
    return (s or "").strip() or None


def build_worklist():
    """Unique hoja_vida_id → (org_id, proceso_id, dni, sig). `sig` folds in every
    candidacy's estado so --update can detect a changed CV. One person maps to one org
    per proceso, so first-seen org/proceso is stable."""
    by_hv = {}
    estados = {}                         # hoja_vida_id → set of estado strings
    with open(CAND_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hv = _ndni(r.get("hoja_vida_id"))
            if not hv or not hv.isdigit():
                continue
            hv = int(hv)
            if hv <= 0:                 # 6k+ rows carry hoja_vida_id "0" = no HDV registered
                continue
            if hv not in by_hv:
                by_hv[hv] = (r.get("organizacion_id"), r.get("proceso_id"), r.get("dni"))
            estados.setdefault(hv, set()).add(r.get("estado_candidato") or "")
    work = []
    for hv, (org, proc, dni) in by_hv.items():
        sig = hashlib.md5("|".join(sorted(estados[hv])).encode()).hexdigest()[:12]
        work.append((hv, org, proc, dni, sig))
    return work


# ── Reparse (offline: rebuild parsed tables from stored raw) ──────────────────

def reparse(db):
    rows = db.execute("SELECT hoja_vida_id, gz FROM raw").fetchall()
    print(f"[REPARSE] {len(rows):,} stored HDVs → rebuilding parsed tables (no network)…")
    n = 0
    for hv, gz in rows:
        try:
            data = json.loads(zlib.decompress(gz)).get("data") or {}
        except Exception:
            continue
        np_, no = store_parsed(db, hv, data)
        db.execute("UPDATE meta SET n_penal=?, n_obliga=?, edu_max=?, foto=? WHERE hoja_vida_id=?",
                   (np_, no, edu_max(data), foto_filename(data), hv))
        n += 1
        if n % 2000 == 0:
            db.commit()
            print(f"  … reparsed {n:,}")
    db.commit()
    print(f"[REPARSE] done: {n:,} HDVs.")


# ── Runner (importable — scrape_erm2026.py --with-hdv calls run(update=True)) ──

def run(workers=8, limit=0, update=False, refetch=False, reparse_only=False):
    """Fetch/refresh the HDV warehouse. Returns a small dict summary. Safe to import
    and call from scrape_erm2026.py so `--update --with-hdv` is a single command."""
    if not CAND_CSV.exists():
        print(f"  scrape_hdv_erm2026: {CAND_CSV.name} not found — skipping HDV pass.")
        return {"skipped": True}

    db = open_db()
    try:
        if reparse_only:
            reparse(db)
            return {"reparsed": True}

        work = build_worklist()
        total_unique = len(work)
        stored = {hv: (sig, ok) for hv, sig, ok in
                  db.execute("SELECT hoja_vida_id, sig, ok FROM meta").fetchall()}
        todo = []
        for hv, org, proc, dni, sig in work:
            if refetch:
                todo.append((hv, org, proc, dni, sig)); continue
            prev = stored.get(hv)
            if prev is None:
                todo.append((hv, org, proc, dni, sig))
            elif update and prev[0] != sig:
                todo.append((hv, org, proc, dni, sig))
            # else: already have it (and, in --update, unchanged) → skip
        if limit:
            todo = todo[:limit]

        mode = "REFETCH" if refetch else ("UPDATE" if update else "FRESH")
        print(f"[HDV {mode}] {total_unique:,} unique hoja_vida_id; "
              f"{len(stored):,} already stored; {len(todo):,} to fetch (workers={workers}).\n")
        if not todo:
            print("  Nothing to fetch. (--refetch to force, --reparse to rebuild parsed tables.)")
            return {"fetched": 0, "ok": 0, "failed": 0}

        def worker(item):
            hv, org, proc, dni, sig = item
            jitter()
            data, raw = fetch_hdv(hv, org, proc)
            return hv, org, proc, dni, sig, data, raw

        done = ok = failed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(worker, it): it[0] for it in todo}
            for fut in as_completed(futs):
                hv = futs[fut]
                try:
                    hv, org, proc, dni, sig, data, raw = fut.result()
                except Exception as e:
                    failed += 1
                    print(f"  ✗ hv={hv}: {e}")
                    continue
                now = datetime.now().isoformat(timespec="seconds")
                if data is None:                   # empty/failed payload — record the attempt
                    db.execute("""INSERT INTO meta
                        (hoja_vida_id,org_id,proceso_id,dni,sig,ok,n_penal,n_obliga,edu_max,foto,fetched_at)
                        VALUES (?,?,?,?,?,0,0,0,0,NULL,?)
                        ON CONFLICT(hoja_vida_id) DO UPDATE SET sig=excluded.sig, ok=0, fetched_at=excluded.fetched_at""",
                        (hv, org, proc, dni, sig, now))
                    failed += 1
                else:
                    db.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?)",
                               (hv, zlib.compress(raw), now))
                    np_, no = store_parsed(db, hv, data)
                    db.execute("""INSERT INTO meta
                        (hoja_vida_id,org_id,proceso_id,dni,sig,ok,n_penal,n_obliga,edu_max,foto,fetched_at)
                        VALUES (?,?,?,?,?,1,?,?,?,?,?)
                        ON CONFLICT(hoja_vida_id) DO UPDATE SET
                            org_id=excluded.org_id, proceso_id=excluded.proceso_id, dni=excluded.dni,
                            sig=excluded.sig, ok=1, n_penal=excluded.n_penal, n_obliga=excluded.n_obliga,
                            edu_max=excluded.edu_max, foto=excluded.foto, fetched_at=excluded.fetched_at""",
                        (hv, org, proc, dni, sig, np_, no, edu_max(data), foto_filename(data), now))
                    ok += 1
                done += 1
                if done % COMMIT_EVERY == 0:
                    db.commit()
                    print(f"  … {done:,}/{len(todo):,}  ok={ok} empty/fail={failed}  "
                          f"[chal={_stats['challenges']} non200={_stats['non200']} "
                          f"neterr={_stats['neterr']}]")

        db.commit()
        con = db.execute("SELECT COUNT(*), SUM(ok), "
                         "SUM(CASE WHEN n_penal>0 OR n_obliga>0 THEN 1 ELSE 0 END) FROM meta").fetchone()
        print(f"\nDone [HDV {mode}]. this run: fetched={done:,} ok={ok:,} empty/fail={failed:,}")
        print(f"  warehouse: {con[0]:,} rows, {con[1] or 0:,} ok, {con[2] or 0:,} with ≥1 sentencia → {DB_PATH}")
        print(f"  http: challenges={_stats['challenges']} non200={_stats['non200']} "
              f"neterr={_stats['neterr']} empty={_stats['empty']} (all auto-retried)")
        return {"fetched": done, "ok": ok, "failed": failed}
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Scrape ERM2026 candidate hojas de vida (HDV).")
    ap.add_argument("--workers", type=int, default=8, help="concurrency (6–9 safe; default 8)")
    ap.add_argument("--limit", type=int, default=0, help="cap HDVs this run (smoke test)")
    ap.add_argument("--update", action="store_true",
                    help="re-fetch only NEW or changed (sig diff) HDVs")
    ap.add_argument("--refetch", action="store_true", help="force re-fetch of every HDV")
    ap.add_argument("--reparse", action="store_true",
                    help="rebuild parsed tables from stored raw, no network")
    args = ap.parse_args()
    run(workers=args.workers, limit=args.limit, update=args.update,
        refetch=args.refetch, reparse_only=args.reparse)


if __name__ == "__main__":
    main()
