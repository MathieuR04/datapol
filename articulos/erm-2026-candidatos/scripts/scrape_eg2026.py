"""
scrape_eg2026.py — JNE candidates scraper, ELECCIONES GENERALES 2026 (idProceso 124)

Scrapes every candidate of every list across all 5 tipos de elección of EG2026
from the JNE plataforma histórico hidden JSON API. See docs/api-notes.md for the
full reverse-engineering write-up.

ENUMERATION (see api-notes §4)
------------------------------
For each tipo we call GetExpedientesLista ONCE with an EMPTY strUbigeoPostula.
Empirically (verified 2026-06-16) the empty postula returns ALL lists for that
tipo across ALL circunscripciones, with each list row carrying its own
strUbigeo / strDistritoElec. So NO departamento enumeration is needed — the
exterior continents (91-95) carry no diputado lists anyway, and Lima's
exterior district lives under ubigeo 140133, not under a continent code.

  GET /Candidato/GetExpedientesLista/124-{TE}--{FILT}      → lists for tipo TE
  GET /Candidato/GetCandidatos/{TE}-124-{idSolList}-{idExp} → candidates of a list

  FILT = "-----0-"  (empty Filtros block: exp-op-tipoOP-jee-estado-jurado(0)-ubigeoDesc)

The 5 tipos (124):  1 PRESIDENCIAL · 3 PARLAMENTO ANDINO · 15 DIPUTADOS ·
                    20 SENADORES DISTRITO ÚNICO · 21 SENADORES DISTRITO MÚLTIPLE

RELIABILITY (site is behind Imperva, see api-notes §6)
------------------------------------------------------
  · curl_cffi impersonate="chrome124"; one Session per worker thread, each
    bootstrapped by GET-ing the HTML Index page to acquire incap_* cookies.
  · 1-3 s random jitter between calls; bounded concurrency (--workers, default 3).
  · exponential backoff on non-200.
  · an HTML body where JSON is expected == Imperva challenge → long sleep,
    re-bootstrap the session's cookies, retry.
  · HTTP 000 / DNS / connection errors == retryable network noise → backoff, retry.

RESUMABLE
---------
  data/.eg2026_checkpoint.json holds the set of list keys ({TE}-{idSolList}-{idExp})
  already scraped. The CSV is rewritten in full from an in-memory store on each
  flush, so a mid-run crash/ban never loses or duplicates rows: on restart we
  reload the existing CSV, skip checkpointed lists, and continue.

OUTPUT
------
  data/eg2026_candidatos.csv — one candidate per row, list metadata flattened on.
  Column schema documented in CLAUDE.md.

USAGE
-----
  python3 scrape_eg2026.py                     # full crawl (resumes if interrupted)
  python3 scrape_eg2026.py --limit 5           # smoke test: first 5 lists only
  python3 scrape_eg2026.py --tipos 1,3         # restrict to some tipos
  python3 scrape_eg2026.py --workers 4
  python3 scrape_eg2026.py --full-refresh      # wipe checkpoint + CSV, start over

  pip install curl_cffi
"""

import argparse
import csv
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("curl_cffi not installed. Run: pip install curl_cffi")

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_CSV   = DATA_DIR / "eg2026_candidatos.csv"
CKPT_FILE = DATA_DIR / ".eg2026_checkpoint.json"

# ── API ──────────────────────────────────────────────────────────────────────
HOST        = "https://plataformahistorico.jne.gob.pe"
INDEX_URL   = f"{HOST}/ListaDeCandidatos/Index"
PROCESO_ID  = 124
PROCESO     = "ELECCIONES GENERALES 2026"
FILT        = "-----0-"                       # empty Filtros block

TIPOS = {                                     # idTipoEleccion → strTipoEleccion
    1:  "PRESIDENCIAL",
    3:  "PARLAMENTO ANDINO",
    15: "DIPUTADOS",
    20: "SENADORES DISTRITO ÚNICO",
    21: "SENADORES DISTRITO MÚLTIPLE",
}

SEXO_MAP = {"1": "M", "2": "F"}               # verified against EG2026 data

# ── Politeness / retry knobs ─────────────────────────────────────────────────
DELAY_MIN        = 1.0
DELAY_MAX        = 3.0
MAX_RETRIES      = 5
CHALLENGE_SLEEP  = 45      # seconds to back off when Imperva serves an HTML challenge
FLUSH_EVERY      = 50      # rewrite CSV + checkpoint every N newly-completed lists

# ── CSV schema (one candidate per row; list metadata flattened on) ───────────
COLUMNS = [
    # process / tipo
    "proceso_id", "proceso", "tipo_eleccion_id", "tipo_eleccion",
    # circunscripción (from the list row)
    "ubigeo", "distrito_electoral", "jurado_electoral",
    # organización política
    "organizacion_id", "organizacion", "tipo_organizacion",
    # list / expediente
    "expediente_id", "cod_expediente", "solicitud_lista_id", "estado_lista",
    "lista_cand_hombres", "lista_cand_mujeres",
    # candidate
    "candidato_id", "dni", "candidato", "apellido_paterno", "apellido_materno",
    "nombres", "sexo", "fecha_nacimiento", "edad",
    "cargo_id", "cargo", "posicion", "ubigeo_postula",
    "estado_candidato", "hoja_vida_id",
]

_store_lock = Lock()
_local = threading.local()   # per-thread curl_cffi session


# ── Session / fetch ──────────────────────────────────────────────────────────

def _new_session():
    """A fresh impersonated session, bootstrapped with Imperva cookies."""
    s = cffi_requests.Session(impersonate="chrome124")
    s.headers.update({"Referer": INDEX_URL})
    try:
        s.get(INDEX_URL, timeout=30)          # acquire visid_incap_* / incap_ses_*
    except Exception:
        pass                                   # cookies are nice-to-have, not required
    return s


def _session():
    if getattr(_local, "session", None) is None:
        _local.session = _new_session()
    return _local.session


def fetch_json(url: str):
    """GET url, return the parsed `data` list. Retries on the failure modes
    documented in api-notes §6. Raises RuntimeError if it never succeeds."""
    for attempt in range(MAX_RETRIES):
        try:
            r = _session().get(url, timeout=30)
        except Exception:
            # HTTP 000 / DNS / connection reset — retryable network noise
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue

        if r.status_code != 200:
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue

        body = r.text.lstrip()
        if body[:1] == "<":
            # HTML where JSON expected → Imperva challenge. Slow down, refresh cookies.
            time.sleep(CHALLENGE_SLEEP)
            _local.session = _new_session()
            continue

        try:
            return (r.json() or {}).get("data") or []
        except Exception:
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue

    raise RuntimeError(f"giving up after {MAX_RETRIES} retries: {url}")


def jitter():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ── Endpoint wrappers ────────────────────────────────────────────────────────

def get_lists(te: int) -> list[dict]:
    """All lists for a tipo (empty postula → every circunscripción)."""
    return fetch_json(f"{HOST}/Candidato/GetExpedientesLista/{PROCESO_ID}-{te}--{FILT}")


def get_candidates(te: int, id_sol: int, id_exp: int) -> list[dict]:
    return fetch_json(f"{HOST}/Candidato/GetCandidatos/{te}-{PROCESO_ID}-{id_sol}-{id_exp}")


# ── Row flattening ───────────────────────────────────────────────────────────

def list_key(te: int, lst: dict) -> str:
    return f"{te}-{lst['idSolicitudLista']}-{lst['idExpediente']}"


def flatten(te: int, lst: dict, cand: dict) -> dict:
    fecha = (cand.get("strFechaNacimiento") or "").split(" ")[0]   # drop " 00:00:00"
    return {
        "proceso_id":          PROCESO_ID,
        "proceso":             PROCESO,
        "tipo_eleccion_id":    te,
        "tipo_eleccion":       TIPOS.get(te, ""),
        "ubigeo":              lst.get("strUbigeo"),
        "distrito_electoral":  lst.get("strDistritoElec"),
        "jurado_electoral":    lst.get("strJuradoElectoral"),
        "organizacion_id":     lst.get("idOrganizacionPolitica"),
        "organizacion":        lst.get("strOrganizacionPolitica"),
        "tipo_organizacion":   lst.get("strTipoOrganizacion"),
        "expediente_id":       lst.get("idExpediente"),
        "cod_expediente":      lst.get("strCodExpediente"),
        "solicitud_lista_id":  lst.get("idSolicitudLista"),
        "estado_lista":        lst.get("strEstadoLista"),
        "lista_cand_hombres":  lst.get("intCandHombres"),
        "lista_cand_mujeres":  lst.get("intCandMujeres"),
        "candidato_id":        cand.get("idCandidato"),
        "dni":                 cand.get("strDocumentoIdentidad"),
        "candidato":           cand.get("strCandidato"),
        "apellido_paterno":    cand.get("strApellidoPaterno"),
        "apellido_materno":    cand.get("strApellidoMaterno"),
        "nombres":             cand.get("strNombreCompleto"),
        "sexo":                SEXO_MAP.get(cand.get("strSexo"), cand.get("strSexo")),
        "fecha_nacimiento":    fecha,
        "edad":                cand.get("intEdad"),
        "cargo_id":            cand.get("idCargoEleccion"),
        "cargo":               cand.get("strCargoEleccion"),
        "posicion":            cand.get("intPosicion"),
        "ubigeo_postula":      cand.get("strUbigeoPostula"),
        "estado_candidato":    cand.get("strEstadoExp"),
        "hoja_vida_id":        cand.get("idHojaVida"),
    }


# ── Persistence ──────────────────────────────────────────────────────────────

def load_state() -> tuple[dict[str, list[dict]], set[str]]:
    """Reload existing CSV (grouped by list key) and the checkpoint set."""
    store: dict[str, list[dict]] = {}
    if OUT_CSV.exists():
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k = f"{row['tipo_eleccion_id']}-{row['solicitud_lista_id']}-{row['expediente_id']}"
                store.setdefault(k, []).append(row)
    done: set[str] = set()
    if CKPT_FILE.exists():
        done = set(json.load(open(CKPT_FILE)))
    return store, done


def flush(store: dict[str, list[dict]], done: set[str]):
    tmp = OUT_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for rows in store.values():
            w.writerows(rows)
    tmp.replace(OUT_CSV)
    json.dump(sorted(done), open(CKPT_FILE, "w"))


# ── Main crawl ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Scrape EG2026 candidates from JNE.")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="cap total lists (smoke test)")
    ap.add_argument("--tipos", default="", help="comma ids, e.g. 1,3,15 (default all)")
    ap.add_argument("--full-refresh", action="store_true", help="wipe CSV + checkpoint")
    args = ap.parse_args()

    if args.full_refresh:
        OUT_CSV.unlink(missing_ok=True)
        CKPT_FILE.unlink(missing_ok=True)
        print("Full refresh: cleared CSV + checkpoint.")

    tipos = [int(t) for t in args.tipos.split(",") if t] if args.tipos else list(TIPOS)

    store, done = load_state()
    print(f"Resuming: {len(done):,} lists already done, {sum(len(v) for v in store.values()):,} rows on disk.")

    # 1) Enumerate all lists for the requested tipos (5 cheap calls).
    work: list[tuple[int, dict]] = []
    for te in tipos:
        lists = get_lists(te)
        jitter()
        new = [l for l in lists if list_key(te, l) not in done]
        print(f"  tipo {te:>2} {TIPOS.get(te,''):<26} {len(lists):>4} lists ({len(new)} to do)")
        work += [(te, l) for l in new]

    if args.limit:
        work = work[: args.limit]
    print(f"\nLists to scrape this run: {len(work):,}  (workers={args.workers})\n")

    # 2) Fetch candidates per list, concurrently.
    def task(item):
        te, lst = item
        jitter()
        cands = get_candidates(te, lst["idSolicitudLista"], lst["idExpediente"])
        return list_key(te, lst), [flatten(te, lst, c) for c in cands]

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(task, it): it for it in work}
        for fut in as_completed(futures):
            te, lst = futures[fut]
            try:
                key, rows = fut.result()
            except Exception as e:
                print(f"  ✗ {list_key(te, lst)} failed: {e}")
                continue
            with _store_lock:
                store[key] = rows
                done.add(key)
                completed += 1
                if completed % FLUSH_EVERY == 0:
                    flush(store, done)
                    print(f"  … {completed:,}/{len(work):,} lists  "
                          f"({sum(len(v) for v in store.values()):,} rows) — flushed")

    flush(store, done)
    total_rows = sum(len(v) for v in store.values())
    print(f"\nDone. {len(done):,} lists, {total_rows:,} candidate rows → {OUT_CSV}")


if __name__ == "__main__":
    main()
