"""
scrape_hdv_eg2026.py — JNE *hoja de vida* (HDV) scraper for **EG2026 candidates**.

EG2026 companion to scrape_hdv_erm2026.py (which the ERM docstring anticipated: "an EG2026
HDV pull, if ever needed, would be its own DB/script"). Reuses that module's reliability
layer (curl_cffi sessions, Imperva handling, retries) and sentencia/educación parsers via
import; only the paths, worklist, and schema live here.

WHY — the senate-domicile analysis: the HDV's `oDatosPersonales` carries the candidate's
declared **domicilio** (strDomiDepartamento/Provincia/Distrito + strUbigeoDomicilio) and
birthplace. That's the input for the "where do senators actually live" piece (national
district vs. departamental seats vs. Lima share). So unlike the ERM warehouse, `meta`
here also stores the parsed domicile/birthplace columns directly.

ENDPOINT (same as ERM):
    GET /HojaVida/GetHVConsolidado?param={idHojaVida}-0-{idOrganizacionPolitica}-{idProceso}
All ids come from data/eg2026_candidatos.csv (proceso_id 124). ~7.4k unique hoja_vida_id
(rows with hoja_vida_id "0" have no registered HDV and are skipped).

STORAGE — data/hdv/hdv_eg2026.sqlite (gitignored, same tiering as ERM: raw zlib JSON is
source of truth; parsed tables rebuildable offline via --reparse). The DB is its own
checkpoint — resumable by construction. EG2026 is a finished process, so this is a
one-shot crawl; there is no --update/sig machinery.

USAGE
-----
  python3 scripts/scrape_hdv_eg2026.py                # fetch all not-yet-stored HDVs (resumes)
  python3 scripts/scrape_hdv_eg2026.py --limit 20     # smoke test
  python3 scripts/scrape_hdv_eg2026.py --workers 12   # concurrency
  python3 scripts/scrape_hdv_eg2026.py --refetch      # force re-pull everything
  python3 scripts/scrape_hdv_eg2026.py --reparse      # rebuild parsed tables from raw (no network)
"""

import argparse
import csv
import json
import sqlite3
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reliability layer + parsers shared with the ERM HDV scraper (path-independent pieces only)
from scrape_hdv_erm2026 import (  # noqa: E402
    _s, _stats, edu_max, fetch_hdv, foto_filename, jitter,
    parse_obliga, parse_penal,
)

DATA_DIR = SCRIPT_DIR.parent / "data"
CAND_CSV = DATA_DIR / "eg2026_candidatos.csv"
HDV_DIR  = DATA_DIR / "hdv"
DB_PATH  = HDV_DIR / "hdv_eg2026.sqlite"

COMMIT_EVERY = 200


# ── Domicile / birthplace extraction ─────────────────────────────────────────

def parse_domicilio(data):
    """(ubigeo_domi, domi_dep, domi_prov, domi_dist, pais_naci, naci_dep, naci_prov,
    naci_dist) from oDatosPersonales. Names are the reliable tier (JNE-internal ubigeo
    codes don't match INEI); kept uppercase as delivered."""
    dp = data.get("oDatosPersonales") or {}
    return (
        _s(dp.get("strUbigeoDomicilio")),
        _s(dp.get("strDomiDepartamento")),
        _s(dp.get("strDomiProvincia")),
        _s(dp.get("strDomiDistrito")),
        _s(dp.get("strPaisNacimiento")),
        _s(dp.get("strNaciDepartamento")),
        _s(dp.get("strNaciProvincia")),
        _s(dp.get("strNaciDistrito")),
    )


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
            ok           INTEGER,         -- 1 fetched OK, 0 empty/failed
            n_penal      INTEGER,
            n_obliga     INTEGER,
            edu_max      INTEGER,
            foto         TEXT,
            ubigeo_domi  TEXT,            -- JNE-internal code (names below are the usable tier)
            domi_dep     TEXT,
            domi_prov    TEXT,
            domi_dist    TEXT,
            pais_naci    TEXT,
            naci_dep     TEXT,
            naci_prov    TEXT,
            naci_dist    TEXT,
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
    """(Re)write parsed sentencia rows for one HDV. Idempotent."""
    db.execute("DELETE FROM sentencia_penal  WHERE hoja_vida_id=?", (hoja_vida_id,))
    db.execute("DELETE FROM sentencia_obliga WHERE hoja_vida_id=?", (hoja_vida_id,))
    penal  = list(parse_penal(data))
    obliga = list(parse_obliga(data))
    db.executemany("INSERT INTO sentencia_penal VALUES (?,?,?,?,?,?,?,?,?)",
                   [(hoja_vida_id, *row) for row in penal])
    db.executemany("INSERT INTO sentencia_obliga VALUES (?,?,?,?,?,?)",
                   [(hoja_vida_id, *row) for row in obliga])
    return len(penal), len(obliga)


def upsert_meta_ok(db, hv, org, proc, dni, data, now):
    np_, no = store_parsed(db, hv, data)
    domi = parse_domicilio(data)
    db.execute("""INSERT OR REPLACE INTO meta
        (hoja_vida_id,org_id,proceso_id,dni,ok,n_penal,n_obliga,edu_max,foto,
         ubigeo_domi,domi_dep,domi_prov,domi_dist,pais_naci,naci_dep,naci_prov,naci_dist,
         fetched_at)
        VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (hv, org, proc, dni, np_, no, edu_max(data), foto_filename(data), *domi, now))


# ── Work list from the candidate CSV ─────────────────────────────────────────

def build_worklist():
    """Unique hoja_vida_id → (org_id, proceso_id, dni). EG2026 is a closed process, so
    no sig/change detection — presence in the DB is the skip condition."""
    by_hv = {}
    with open(CAND_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hv = (r.get("hoja_vida_id") or "").strip()
            if not hv.isdigit() or int(hv) <= 0:   # "0" = no HDV registered
                continue
            by_hv.setdefault(int(hv), (r.get("organizacion_id"), r.get("proceso_id"), r.get("dni")))
    return [(hv, *vals) for hv, vals in by_hv.items()]


# ── Reparse (offline) ────────────────────────────────────────────────────────

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
        domi = parse_domicilio(data)
        db.execute("""UPDATE meta SET n_penal=?, n_obliga=?, edu_max=?, foto=?,
                        ubigeo_domi=?, domi_dep=?, domi_prov=?, domi_dist=?,
                        pais_naci=?, naci_dep=?, naci_prov=?, naci_dist=?
                      WHERE hoja_vida_id=?""",
                   (np_, no, edu_max(data), foto_filename(data), *domi, hv))
        n += 1
        if n % 2000 == 0:
            db.commit()
            print(f"  … reparsed {n:,}")
    db.commit()
    print(f"[REPARSE] done: {n:,} HDVs.")


# ── Runner ───────────────────────────────────────────────────────────────────

def run(workers=8, limit=0, refetch=False, reparse_only=False):
    db = open_db()
    try:
        if reparse_only:
            reparse(db)
            return

        work = build_worklist()
        stored = {hv for (hv,) in db.execute("SELECT hoja_vida_id FROM meta WHERE ok=1")}
        todo = [w for w in work if refetch or w[0] not in stored]
        if limit:
            todo = todo[:limit]

        print(f"[HDV EG2026] {len(work):,} unique hoja_vida_id; {len(stored):,} already stored; "
              f"{len(todo):,} to fetch (workers={workers}).\n")
        if not todo:
            print("  Nothing to fetch. (--refetch to force, --reparse to rebuild parsed tables.)")
            return

        def worker(item):
            hv, org, proc, dni = item
            jitter()
            data, raw = fetch_hdv(hv, org, proc)
            return hv, org, proc, dni, data, raw

        done = ok = failed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(worker, it): it[0] for it in todo}
            for fut in as_completed(futs):
                hv = futs[fut]
                try:
                    hv, org, proc, dni, data, raw = fut.result()
                except Exception as e:
                    failed += 1
                    print(f"  ✗ hv={hv}: {e}")
                    continue
                now = datetime.now().isoformat(timespec="seconds")
                if data is None:                   # empty/failed payload — record the attempt
                    db.execute("""INSERT OR REPLACE INTO meta
                        (hoja_vida_id,org_id,proceso_id,dni,ok,n_penal,n_obliga,edu_max,foto,
                         ubigeo_domi,domi_dep,domi_prov,domi_dist,pais_naci,naci_dep,naci_prov,
                         naci_dist,fetched_at)
                        VALUES (?,?,?,?,0,0,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)""",
                        (hv, org, proc, dni, now))
                    failed += 1
                else:
                    db.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?)",
                               (hv, zlib.compress(raw), now))
                    upsert_meta_ok(db, hv, org, proc, dni, data, now)
                    ok += 1
                done += 1
                if done % COMMIT_EVERY == 0:
                    db.commit()
                    print(f"  … {done:,}/{len(todo):,}  ok={ok} empty/fail={failed}  "
                          f"[chal={_stats['challenges']} non200={_stats['non200']} "
                          f"neterr={_stats['neterr']}]")

        db.commit()
        con = db.execute("SELECT COUNT(*), SUM(ok), "
                         "SUM(CASE WHEN domi_dep IS NOT NULL THEN 1 ELSE 0 END) FROM meta").fetchone()
        print(f"\nDone [HDV EG2026]. this run: fetched={done:,} ok={ok:,} empty/fail={failed:,}")
        print(f"  warehouse: {con[0]:,} rows, {con[1] or 0:,} ok, {con[2] or 0:,} with domicilio → {DB_PATH}")
        print(f"  http: challenges={_stats['challenges']} non200={_stats['non200']} "
              f"neterr={_stats['neterr']} empty={_stats['empty']} (all auto-retried)")
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Scrape EG2026 candidate hojas de vida (HDV).")
    ap.add_argument("--workers", type=int, default=8, help="concurrency (default 8)")
    ap.add_argument("--limit", type=int, default=0, help="cap HDVs this run (smoke test)")
    ap.add_argument("--refetch", action="store_true", help="force re-fetch of every HDV")
    ap.add_argument("--reparse", action="store_true",
                    help="rebuild parsed tables from stored raw, no network")
    args = ap.parse_args()
    run(workers=args.workers, limit=args.limit, refetch=args.refetch,
        reparse_only=args.reparse)


if __name__ == "__main__":
    main()
