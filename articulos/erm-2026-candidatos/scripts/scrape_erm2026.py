"""
scrape_erm2026.py — JNE candidates scraper, ELECCIONES REGIONALES Y MUNICIPALES 2026
(idProceso 126). Companion to scrape_eg2026.py — same schema, same reliability layer,
same flattened one-candidate-per-row CSV. See docs/api-notes.md.

  Output: data/erm2026_candidatos.csv  (columns identical to eg2026_candidatos.csv)

WHAT'S DIFFERENT FROM EG2026: circunscripción iteration
-------------------------------------------------------
EG2026 could enumerate with an empty strUbigeoPostula (one call per tipo returned
every circunscripción). ERM2026 is walked explicitly down the ubigeo tree to the
depth each tipo requires, driving every code from the API (JNE ubigeo is internal,
NOT INEI — never hardcode):

  tipo                      depth                strUbigeoPostula   ~circ
  REGIONAL            (4)   departamento         DD (2-digit)        25
  MUNICIPAL PROVINCIAL(5)   dep+provincia        DDPP (4-digit)     221
  MUNICIPAL DISTRITAL (6)   dep+prov+distrito    DDPPSS (6-digit)  ~2120  ← the big one

  ListUbigeoDepartamento            → DD codes
  ListUbigeoProvincia?id=DD         → PP codes under a departamento
  ListUbigeoDistrito/DDPP           → SS codes under a provincia
  GetExpedientesLista/126-{te}-{postula}-{FILT}  → lists in that circunscripción
  GetCandidatos/{te}-126-{idSolList}-{idExp}     → candidates of a list

The ubigeo tree is built once (to the depth the requested tipos need) and cached to
data/.erm2026_ubigeo_tree.json, so resumes/updates don't re-walk it.

RELIABILITY: identical to scrape_eg2026.py (Imperva cookie-bootstrap, 1-3 s jitter,
bounded workers, exponential backoff, HTML-challenge detection, HTTP-000 retry).

RESUMABILITY — checkpoint at the (tipo, ubigeo) circunscripción level
--------------------------------------------------------------------
  data/.erm2026_checkpoint.json:
    { "circ_done":  ["4-15", "5-1501", ...],   # circunscripciones fully processed
      "lists_done": [38614, 38602, ...] }       # idSolicitudLista whose candidates are in the CSV
  A circ is marked done only after all its lists are handled, so an interrupted run
  re-processes at most one circ, and per-list `lists_done` prevents re-fetching candidates.

  IMPORTANT — `circ_done` skipping applies ONLY to resuming an interrupted FRESH run.
  A circunscripción can legitimately return 0 lists right now (lists not registered
  yet — not just provincial cercados) and can gain lists later. So `circ_done` must
  NOT be read as "this circ is final". To pick up lists registered after a prior run
  (including in circunscripciones that were empty before), re-run with --update, which
  ignores `circ_done` and re-enumerates the ENTIRE tree. Never treat a completed FRESH
  crawl as complete coverage of a still-open process; --update is the catch-up path.

--update — handles BOTH new lists and status changes (keyed on idSolicitudLista)
--------------------------------------------------------------------------------
ERM lists are still being uploaded, so a circunscripción can gain lists, and a known
list's strEstadoLista can move (RECIBIDO → INSCRITO → …). The per-list ledger
data/.erm2026_state.json:
    { "<idSolicitudLista>": {"te":4,"postula":"15","idExpediente":343956,"estado":"RECIBIDO"} }

  Without --update : fresh crawl, resumable via the checkpoint above.
  With    --update : the discovery pass over the FULL tree is MANDATORY (circ_done is
                     ignored) — every circunscripción's GetExpedientesLista is re-fetched
                     and the returned idSolicitudLista set is diffed against the ledger:
                       · NEW    idSolicitudLista          → fetch candidates, append rows
                       · CHANGED strEstadoLista           → re-fetch candidates, replace rows + metadata
                       · unchanged                        → skip (cheap; no GetCandidatos)
                     This keeps a routine --update cheap on candidate fetches while still
                     discovering newly-uploaded lists.

USAGE
-----
  python3 scrape_erm2026.py                      # fresh full crawl (resumes if interrupted)
  python3 scrape_erm2026.py --tipos 4            # only REGIONAL (fast; smoke-friendly)
  python3 scrape_erm2026.py --limit 10           # only first 10 circunscripciones (smoke test)
  python3 scrape_erm2026.py --update             # diff-and-upsert against the ledger
  python3 scrape_erm2026.py --workers 3
  python3 scrape_erm2026.py --full-refresh       # wipe CSV + checkpoint + ledger
  python3 scrape_erm2026.py --rebuild-tree       # re-walk the ubigeo tree cache

  pip install curl_cffi
"""

import argparse
import csv
import json
import random
import subprocess
import sys
import threading
import time
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
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUT_CSV    = DATA_DIR / "erm2026_candidatos.csv"
CKPT_FILE  = DATA_DIR / ".erm2026_checkpoint.json"
STATE_FILE = DATA_DIR / ".erm2026_state.json"
TREE_FILE  = DATA_DIR / ".erm2026_ubigeo_tree.json"

# ── API ──────────────────────────────────────────────────────────────────────
HOST        = "https://plataformahistorico.jne.gob.pe"
INDEX_URL   = f"{HOST}/ListaDeCandidatos/Index"
PROCESO_ID  = 126
PROCESO     = "ELECCIONES REGIONALES Y MUNICIPALES 2026"
FILT        = "-----0-"

TIPOS = {                                     # idTipoEleccion → strTipoEleccion
    4: "REGIONAL",
    5: "MUNICIPAL PROVINCIAL",
    6: "MUNICIPAL DISTRITAL",
}
TIPO_DEPTH = {4: 1, 5: 2, 6: 3}               # ubigeo segments in strUbigeoPostula

SEXO_MAP = {"1": "M", "2": "F"}

# ── Politeness / retry knobs (same as EG) ────────────────────────────────────
DELAY_MIN        = 1.0
DELAY_MAX        = 3.0
MAX_RETRIES      = 5
CHALLENGE_SLEEP  = 45
FLUSH_EVERY      = 25      # circunscripciones between CSV/checkpoint flushes

# ── CSV schema ───────────────────────────────────────────────────────────────
# Superset of eg2026_candidatos.csv. The ERM-specific columns are the ubigeo name
# expansion (departamento/provincia/distrito, blanked per tier by the API) and
# provincia_consejero (the province a REGIONAL consejero/accesitario runs in —
# regional lists are region-wide so `provincia` is blank, but consejeros compete
# per-province, so that province lives in its own field for the search UI).
COLUMNS = [
    "proceso_id", "proceso", "tipo_eleccion_id", "tipo_eleccion",
    "ubigeo", "departamento", "provincia", "distrito",
    "distrito_electoral", "jurado_electoral",
    "organizacion_id", "organizacion", "tipo_organizacion",
    "expediente_id", "cod_expediente", "solicitud_lista_id", "estado_lista",
    "lista_cand_hombres", "lista_cand_mujeres",
    "candidato_id", "dni", "candidato", "apellido_paterno", "apellido_materno",
    "nombres", "sexo", "fecha_nacimiento", "edad",
    "cargo_id", "cargo", "posicion", "provincia_consejero",
    "ubigeo_postula", "estado_candidato", "hoja_vida_id",
]

_lock  = Lock()
_local = threading.local()

# Observability — bumped under _lock; surfaced in the final summary so a worker
# benchmark shows whether higher concurrency provokes Imperva.
_stats = {"challenges": 0, "non200": 0, "neterr": 0}

def _bump(key):
    with _lock:
        _stats[key] += 1


# ── Session / fetch (identical to EG) ────────────────────────────────────────

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


def fetch_json(url: str):
    """GET url → parsed `data` list, with the api-notes §6 retry behavior."""
    for attempt in range(MAX_RETRIES):
        try:
            r = _session().get(url, timeout=30)
        except Exception:
            _bump("neterr")                                      # HTTP 000 / DNS noise
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
        if r.status_code != 200:
            _bump("non200")
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
        body = r.text.lstrip()
        if body[:1] == "<":                                      # Imperva HTML challenge
            _bump("challenges")
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


# ── Ubigeo tree (built to the depth the requested tipos need, then cached) ────

def _deps():
    return [r["strUbiDepartamento"] for r in
            fetch_json(f"{HOST}/Candidato/ListUbigeoDepartamento")]


def _provs(dep):
    return [r["strUbiProvincia"] for r in
            fetch_json(f"{HOST}/Candidato/ListUbigeoProvincia?id={dep}")]


def _dists(dep, prov):
    return [r["strUbiDistrito"] for r in
            fetch_json(f"{HOST}/Candidato/ListUbigeoDistrito/{dep}{prov}")]


def load_tree() -> dict:
    if TREE_FILE.exists():
        return json.load(open(TREE_FILE))
    return {"departamentos": [], "provincias": {}, "distritos": {}}


def ensure_tree(tree: dict, max_depth: int) -> dict:
    """Fill the ubigeo tree up to max_depth (1=dep, 2=+prov, 3=+dist), caching as we go."""
    if not tree["departamentos"]:
        print("  building tree: departamentos …")
        tree["departamentos"] = _deps(); jitter()
        json.dump(tree, open(TREE_FILE, "w"))
    if max_depth >= 2:
        todo = [d for d in tree["departamentos"] if d not in tree["provincias"]]
        if todo:
            print(f"  building tree: provincias for {len(todo)} departamentos …")
            for dep in todo:
                tree["provincias"][dep] = _provs(dep); jitter()
            json.dump(tree, open(TREE_FILE, "w"))
    if max_depth >= 3:
        pairs = [(d, p) for d in tree["departamentos"] for p in tree["provincias"].get(d, [])]
        todo = [(d, p) for d, p in pairs if (d + p) not in tree["distritos"]]
        if todo:
            print(f"  building tree: distritos for {len(todo)} provincias …")
            for dep, prov in todo:
                tree["distritos"][dep + prov] = _dists(dep, prov); jitter()
            json.dump(tree, open(TREE_FILE, "w"))
    return tree


def build_thin_tree(max_depth: int) -> dict:
    """A minimal in-memory ubigeo tree for --sample: all departamentos, but only the
    FIRST departamento expanded into provincias and its first provincia into distritos
    (≈3 enumeration calls). NOT cached to disk, so it never shadows the full tree."""
    deps = _deps(); jitter()
    tree = {"departamentos": deps, "provincias": {}, "distritos": {}}
    if max_depth >= 2 and deps:
        d0 = deps[0]
        tree["provincias"][d0] = _provs(d0); jitter()
        if max_depth >= 3 and tree["provincias"][d0]:
            p0 = tree["provincias"][d0][0]
            tree["distritos"][d0 + p0] = _dists(d0, p0); jitter()
    return tree


def circ_postulas(te: int, tree: dict):
    """Yield the strUbigeoPostula strings for every circunscripción of a tipo."""
    depth = TIPO_DEPTH[te]
    for dep in tree["departamentos"]:
        if depth == 1:
            yield dep
            continue
        for prov in tree["provincias"].get(dep, []):
            if depth == 2:
                yield dep + prov
                continue
            for dist in tree["distritos"].get(dep + prov, []):
                yield dep + prov + dist


# ── Endpoint wrappers ────────────────────────────────────────────────────────

def get_lists(te: int, postula: str) -> list[dict]:
    return fetch_json(f"{HOST}/Candidato/GetExpedientesLista/{PROCESO_ID}-{te}-{postula}-{FILT}")


def get_candidates(te: int, id_sol: int, id_exp: int) -> list[dict]:
    return fetch_json(f"{HOST}/Candidato/GetCandidatos/{te}-{PROCESO_ID}-{id_sol}-{id_exp}")


# ── Row flattening (identical mapping to EG) ─────────────────────────────────

def flatten(te: int, lst: dict, cand: dict) -> dict:
    fecha = (cand.get("strFechaNacimiento") or "").split(" ")[0]
    return {
        "proceso_id":          PROCESO_ID,
        "proceso":             PROCESO,
        "tipo_eleccion_id":    te,
        "tipo_eleccion":       TIPOS.get(te, ""),
        "ubigeo":              lst.get("strUbigeo"),
        "departamento":        lst.get("strRegion"),       # tier-blanked by the API:
        "provincia":           lst.get("strProvincia"),    #   regional → only departamento
        "distrito":            lst.get("strDistrito"),      #   provincial → +provincia, etc.
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
        "provincia_consejero": cand.get("strProvinciaConsejero"),   # consejeros/accesitarios only
        "ubigeo_postula":      cand.get("strUbigeoPostula"),
        "estado_candidato":    cand.get("strEstadoExp"),
        "hoja_vida_id":        cand.get("idHojaVida"),
    }


# ── Persistence ──────────────────────────────────────────────────────────────

def load_csv_store() -> dict[str, list[dict]]:
    """Existing CSV grouped by idSolicitudLista (so re-fetched lists overwrite cleanly)."""
    store: dict[str, list[dict]] = {}
    if OUT_CSV.exists():
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                store.setdefault(row["solicitud_lista_id"], []).append(row)
    return store


def load_ckpt() -> dict:
    if CKPT_FILE.exists():
        c = json.load(open(CKPT_FILE))
        return {"circ_done": set(c.get("circ_done", [])),
                "lists_done": set(str(x) for x in c.get("lists_done", []))}
    return {"circ_done": set(), "lists_done": set()}


def load_state() -> dict:
    return json.load(open(STATE_FILE)) if STATE_FILE.exists() else {}


def flush(store, ckpt, state):
    tmp = OUT_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for rows in store.values():
            w.writerows(rows)
    tmp.replace(OUT_CSV)
    json.dump({"circ_done": sorted(ckpt["circ_done"]),
               "lists_done": sorted(int(x) for x in ckpt["lists_done"])},
              open(CKPT_FILE, "w"))
    json.dump(state, open(STATE_FILE, "w"))


# ── Per-circunscripción worker ───────────────────────────────────────────────

def process_circ(te: int, postula: str, update: bool, done: set, state: dict):
    """Discover lists in one circunscripción and fetch candidates for the ones that
    need it. Returns (te, postula, [(sl, lst, rows_or_None)]). rows_or_None is None
    when the list was skipped (unchanged) and its existing CSV rows must be kept."""
    jitter()
    lists = get_lists(te, postula)
    out = []
    for lst in lists:
        sl = str(lst["idSolicitudLista"])
        estado = lst.get("strEstadoLista")
        if update:
            prior = state.get(sl)
            need = (prior is None) or (prior.get("estado") != estado)
        else:
            need = sl not in done
        rows = None
        if need:
            jitter()
            cands = get_candidates(te, lst["idSolicitudLista"], lst["idExpediente"])
            rows = [flatten(te, lst, c) for c in cands]
        out.append((sl, lst, postula, estado, rows))
    return te, postula, out


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Scrape ERM2026 candidates from JNE.")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="cap total circunscripciones (taken tipo-by-tipo)")
    ap.add_argument("--sample", type=int, default=0,
                    help="first N circunscripciones PER tipo (cross-tipo smoke test; "
                         "uses a minimal in-memory ubigeo branch, no tree cache write)")
    ap.add_argument("--tipos", default="", help="comma ids 4,5,6 (default all)")
    ap.add_argument("--update", action="store_true", help="diff-and-upsert against the ledger")
    ap.add_argument("--full-refresh", action="store_true", help="wipe CSV + checkpoint + ledger")
    ap.add_argument("--rebuild-tree", action="store_true", help="re-walk the ubigeo tree cache")
    ap.add_argument("--no-build", action="store_true",
                    help="skip the JSON rebuild (commit CSV only, still pushes)")
    ap.add_argument("--no-push", action="store_true",
                    help="dry run: scrape + build but DON'T commit or push (leave git clean)")
    ap.add_argument("--with-hdv", action="store_true",
                    help="after the list update, also refresh the HDV warehouse "
                         "(scrape_hdv_erm2026: sentencias/educación) so one command updates everything")
    ap.add_argument("--hdv-workers", type=int, default=8, help="workers for the --with-hdv pass (6–9 safe)")
    args = ap.parse_args()

    if args.full_refresh:
        for p in (OUT_CSV, CKPT_FILE, STATE_FILE):
            p.unlink(missing_ok=True)
        print("Full refresh: cleared CSV + checkpoint + ledger.")
    if args.rebuild_tree:
        TREE_FILE.unlink(missing_ok=True)

    tipos = [int(t) for t in args.tipos.split(",") if t] if args.tipos else list(TIPOS)

    store = load_csv_store()
    ckpt  = load_ckpt()
    state = load_state()
    mode  = "UPDATE" if args.update else "FRESH"
    print(f"[{mode}] resuming: {len(ckpt['circ_done']):,} circ done, "
          f"{len(state):,} lists in ledger, "
          f"{sum(len(v) for v in store.values()):,} rows on disk.")

    # Build the ubigeo tree to the deepest requested tipo (thin branch when sampling).
    max_depth = max(TIPO_DEPTH[t] for t in tipos)
    tree = build_thin_tree(max_depth) if args.sample else ensure_tree(load_tree(), max_depth)

    # Build the circunscripción work list. In FRESH mode skip circ_done; in UPDATE
    # mode the discovery pass is mandatory (every circ re-enumerated).
    work = []
    for te in tipos:
        circs = list(circ_postulas(te, tree))
        if args.sample:
            circs = circs[: args.sample]
        todo = [(te, p) for p in circs
                if args.update or f"{te}-{p}" not in ckpt["circ_done"]]
        work += todo
        print(f"  tipo {te} {TIPOS[te]:<22} {len(circs):>5} circ ({len(todo)} to do)")
    if args.limit:
        work = work[: args.limit]
    print(f"\nCircunscripciones to process this run: {len(work):,}  (workers={args.workers})\n")

    new_lists = changed_lists = 0
    processed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(process_circ, te, p, args.update, ckpt["lists_done"], state): (te, p)
                for te, p in work}
        for fut in as_completed(futs):
            te, postula = futs[fut]
            try:
                te, postula, results = fut.result()
            except Exception as e:
                print(f"  ✗ circ {te}-{postula} failed: {e}")
                continue
            with _lock:
                for sl, lst, p, estado, rows in results:
                    if rows is not None:
                        if args.update and state.get(sl) and state[sl].get("estado") != estado:
                            changed_lists += 1
                        elif sl not in state:
                            new_lists += 1
                        store[sl] = rows
                        ckpt["lists_done"].add(sl)
                    state[sl] = {"te": te, "postula": p,
                                 "idExpediente": lst.get("idExpediente"), "estado": estado}
                ckpt["circ_done"].add(f"{te}-{postula}")
                processed += 1
                if processed % FLUSH_EVERY == 0:
                    flush(store, ckpt, state)
                    print(f"  … {processed:,}/{len(work):,} circ  "
                          f"({sum(len(v) for v in store.values()):,} rows; "
                          f"new={new_lists} changed={changed_lists}) — flushed")

    flush(store, ckpt, state)
    print(f"\nDone [{mode}]. circ_done={len(ckpt['circ_done']):,}  "
          f"lists={len(state):,}  rows={sum(len(v) for v in store.values()):,}  "
          f"new={new_lists}  changed={changed_lists}  → {OUT_CSV}")
    print(f"  http: challenges={_stats['challenges']}  "
          f"non200={_stats['non200']}  neterr={_stats['neterr']}  (all auto-retried)")

    # Single source of truth: regenerate all derived JSON (buscador candidatos.json,
    # partidos.json, repeticiones.json) from the fresh CSVs so nothing drifts.
    # Failure here must not invalidate a good scrape.
    artifacts = [OUT_CSV]
    if not args.no_build:
        try:
            import build_finder_json
            build_finder_json.main()
            artifacts += list(build_finder_json.OUTPUTS)
        except Exception as e:
            print(f"  ⚠ JSON rebuild failed ({e}); run scripts/build_finder_json.py manually.")

    # Auto-publish: stage the artifacts, commit + push if (and only if) something changed.
    # (HDV data is gitignored, so we publish the list update FIRST, then run the long HDV
    #  pass — a routine --update stays a fast push; the HDV backfill runs after.)
    if not args.no_push:
        publish(artifacts)
    else:
        print("  (--no-push: skipping commit + push; working tree left as-is)")

    # Optional HDV warehouse refresh — one command updates lists + hojas de vida.
    # Incremental (only new/changed HDVs), so it's cheap once the initial backfill exists.
    if args.with_hdv:
        print("\n── HDV pass (scrape_hdv_erm2026) ──")
        try:
            import scrape_hdv_erm2026
            scrape_hdv_erm2026.run(workers=args.hdv_workers, update=True)
        except Exception as e:
            print(f"  ⚠ HDV pass failed ({e}); run scripts/scrape_hdv_erm2026.py --update manually.")


def publish(artifacts):
    """Stage the data artifacts, and commit + push only if they actually changed.
    Reuses the election-night push pattern: pull --rebase (autostash) + push, retry 3×."""
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if repo.returncode != 0:
        print("  ⚠ not a git repo — skipping publish."); return
    root = repo.stdout.strip()

    def git(*a, **kw):
        return subprocess.run(["git", "-C", root, *a], text=True, **kw)

    paths = [str(p) for p in artifacts if Path(p).exists()]
    git("add", "--", *paths)

    # Guard: nothing staged different from HEAD → clean exit, no empty commit, no push.
    if git("diff", "--cached", "--quiet", "--", *paths).returncode == 0:
        print("  nothing changed — no commit, no push.")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    git("commit", "-m", f"data: actualizar candidatos ERM 2026 — {ts}", "--", *paths)
    print(f"  committed: data: actualizar candidatos ERM 2026 — {ts}")

    for attempt in (1, 2, 3):
        git("pull", "--rebase", "--autostash", "--quiet")
        if git("push").returncode == 0:
            print("  ✔ pushed to main."); return
        print(f"  push failed (attempt {attempt}/3) — retrying in 10s …")
        time.sleep(10)
    print("  ⚠ push failed after 3 attempts; commit is local — push manually.")


if __name__ == "__main__":
    main()
