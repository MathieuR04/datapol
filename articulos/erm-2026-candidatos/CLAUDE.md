# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This folder (`articulos/erm-2026-candidatos/`) is one subproject inside the larger **datapol**
repo. The sections below describe *this* subproject; see the bottom for the datapol conventions
it inherits.

## Goal

Scrape **all candidates** from the JNE *plataforma histórico* (Jurado Nacional de Elecciones,
Peru) for two electoral processes, then produce three analysis/visualization deliverables and two
articles — everything living in this folder.

The two processes:

1. **ELECCIONES GENERALES 2026 (EG2026)** — 5 tipos de elección (e.g. presidencial, senado,
   diputados, parlamento andino, …).
2. **ELECCIONES REGIONALES Y MUNICIPALES 2026 (ERM2026)** — election types `REGIONAL`,
   `MUNICIPAL PROVINCIAL`, `MUNICIPAL DISTRITAL`, iterated over **ubigeo** (the scraper walks the
   territorial codes because lists are scoped per region/province/district).

> **ERM2026 lists are still being uploaded** by the JNE as of this writing, so the scraper must
> support an `--update` flag that re-fetches and fills in newly-published lists without
> re-scraping everything from scratch.

## Scraper

Hits the JNE plataforma histórico JSON API. Two endpoints:

- `/Candidato/GetExpedientesLista` — returns the **lists** (expedientes / listas de candidatos)
  for a given process / election type / ubigeo.
- `/Candidato/GetCandidatos` — returns the **candidates within a single list**.

**Output shape:** one **candidate per row**, with the parent list's metadata flattened onto every
row, written to **CSV**. (Organización política, tipo de elección, ubigeo, expediente, etc. are
repeated on each candidate row.)

API specifics are fully documented in **`docs/api-notes.md`** (endpoints, process/tipo ids, the
`GetExpedientesLista` URL grammar, ubigeo encoding, WAF behavior). Read it before touching the
scrapers.

## EG2026 scraper — `scripts/scrape_eg2026.py`

Scrapes all candidates of ELECCIONES GENERALES 2026 (`idProceso 124`) across its 5 tipos de
elección. **Enumeration is one `GetExpedientesLista` call per tipo with an empty `strUbigeoPostula`**
— empirically that returns every list across every circunscripción, with each list row carrying its
own `strUbigeo`/`strDistritoElec`, so no departamento iteration is needed (verified: DIPUTADOS empty
postula = 912 lists across 27 circunscripciones). Then `GetCandidatos` per list. Reliability:
`curl_cffi` chrome impersonation, per-thread cookie-bootstrapped sessions, 1–3 s jitter, bounded
workers, exponential backoff, Imperva-challenge detection (HTML-where-JSON-expected → refresh
cookies), and a resumable checkpoint (`data/.eg2026_checkpoint.json` keyed by `{tipo}-{idSolList}-{idExp}`;
CSV rewritten in full from an in-memory store each flush, so crashes neither lose nor duplicate rows).

Run: `python3 scripts/scrape_eg2026.py` (resumes automatically); `--limit N` smoke test;
`--tipos 1,3`; `--full-refresh`.

### Output schema — `data/eg2026_candidatos.csv`

One candidate per row; the parent list's metadata is flattened onto every row. The ~90 null HDV
placeholder fields from `GetCandidatos` are dropped — only the columns below are kept.

| column | source field | notes |
|---|---|---|
| `proceso_id` / `proceso` | constant | 124 / "ELECCIONES GENERALES 2026" |
| `tipo_eleccion_id` / `tipo_eleccion` | `idTipoEleccion` / map | 1 PRESIDENCIAL, 3 PARLAMENTO ANDINO, 15 DIPUTADOS, 20 SENADORES DISTRITO ÚNICO, 21 SENADORES DISTRITO MÚLTIPLE |
| `ubigeo` | list `strUbigeo` | circunscripción of the list (JNE-internal code) |
| `distrito_electoral` | list `strDistritoElec` | e.g. "LIMA METROPOLITANA", "ÚNICO NACIONAL" |
| `jurado_electoral` | list `strJuradoElectoral` | JEE |
| `organizacion_id` / `organizacion` | `idOrganizacionPolitica` / `strOrganizacionPolitica` | dashboard #2 key |
| `tipo_organizacion` | `strTipoOrganizacion` | e.g. "ALIANZAS ELECTORALES" |
| `expediente_id` / `cod_expediente` | `idExpediente` / `strCodExpediente` | e.g. "EG.2026016326" |
| `solicitud_lista_id` | `idSolicitudLista` | list id (checkpoint key) |
| `estado_lista` | `strEstadoLista` | INSCRITO / RECIBIDO / IMPROCEDENTE … |
| `lista_cand_hombres` / `lista_cand_mujeres` | `intCandHombres` / `intCandMujeres` | list-level counts |
| `candidato_id` | `idCandidato` | |
| `dni` | `strDocumentoIdentidad` | **overlap deliverable #1 join key** |
| `candidato` | `strCandidato` | full name |
| `apellido_paterno` / `apellido_materno` | `strApellidoPaterno` / `strApellidoMaterno` | |
| `nombres` | `strNombreCompleto` | given names only |
| `sexo` | `strSexo` mapped | `1`→`M`, `2`→`F` (verified) |
| `fecha_nacimiento` | `strFechaNacimiento` | `dd/mm/yyyy` (time stripped) |
| `edad` | `intEdad` | |
| `cargo_id` / `cargo` | `idCargoEleccion` / `strCargoEleccion` | e.g. "PRESIDENTE DE LA REPÚBLICA" |
| `posicion` | `intPosicion` | order on the list |
| `ubigeo_postula` | `strUbigeoPostula` | candidate's postulation ubigeo |
| `estado_candidato` | `strEstadoExp` | |
| `hoja_vida_id` | `idHojaVida` | → CV detail endpoint if ever needed |

## ERM2026 scraper — `scripts/scrape_erm2026.py`

Companion to the EG scraper for ELECCIONES REGIONALES Y MUNICIPALES 2026 (`idProceso 126`):
**identical schema, reliability layer, and CSV output** → `data/erm2026_candidatos.csv`. The only
real difference is circunscripción iteration — ERM is walked down the ubigeo tree to the depth each
tipo needs (driven entirely from `ListUbigeoDepartamento`/`ListUbigeoProvincia`/`ListUbigeoDistrito`,
never hardcoded), because (unlike EG) each tipo is scoped to a territory:

| tipo | `strUbigeoPostula` depth | circunscripciones |
|---|---|---|
| REGIONAL (4) | `DD` (departamento) | **25** |
| MUNICIPAL PROVINCIAL (5) | `DDPP` (dep+prov) | **196** |
| MUNICIPAL DISTRITAL (6) | `DDPPSS` (dep+prov+dist) | **1,696 active** |

For MUNICIPAL DISTRITAL the tree yields ~**1,892** distrito nodes, but the **196 provincial-capital
*cercados* hold no distrital-mayor election** (they're governed by the municipalidad provincial), so
~196 of those `GetExpedientesLista` calls return 0 lists — **this is expected, not a failure**. The
worker handles empty circunscripciones cleanly (marks the circ done, writes no rows). Net active
distrital circunscripciones ≈ 1,696.

The ubigeo tree is built once to the deepest requested depth and cached
(`data/.erm2026_ubigeo_tree.json`). Resumability is checkpointed at the **(tipo, ubigeo)**
circunscripción level (`data/.erm2026_checkpoint.json`: `circ_done` + `lists_done`).

**`circ_done` is resume-only, never "final coverage".** A circunscripción can return 0 lists
simply because lists aren't registered yet (not only provincial *cercados*), and can gain lists
later — ERM uploads are ongoing. So a completed FRESH crawl is a point-in-time snapshot, not full
coverage; **re-run with `--update`** (which ignores `circ_done` and re-walks the whole tree) to pick
up newly-registered lists, including in circunscripciones that were empty before.

**Extra ERM columns vs. EG** (the CSV is otherwise the EG schema): `departamento` / `provincia` /
`distrito` are the ubigeo name expansion for the search UI, taken from the list's
`strRegion`/`strProvincia`/`strDistrito` (the API already blanks the tiers that don't apply —
regional fills only departamento, provincial +provincia, distrital all three). `provincia_consejero`
is the province a REGIONAL consejero/accesitario competes in (from the candidate's
`strProvinciaConsejero`); blank for gobernador/vicegobernador and all non-regional cargos.

## HDV scraper — `scripts/scrape_hdv_erm2026.py` (hojas de vida, ERM2026 only)

Second scraping tier: for every ERM2026 candidate's `hoja_vida_id`, pulls the **full
consolidated hoja de vida** in one call — `GET /HojaVida/GetHVConsolidado?param={idHojaVida}-0-{organizacion_id}-{proceso_id}`
(all three ids already in `data/erm2026_candidatos.csv`; no discovery walk). Same
`curl_cffi`/Imperva reliability layer as the list scraper. See `docs/api-notes.md` §8.

The headline payload is **V. Relación de Sentencias** (`lSentenciaPenal` = penales,
`lSentenciaObliga` = civiles), matching the JNE búsqueda-avanzada CIVILES/PENALES filter;
the same response also carries educación, patrimonio (bienes/ingresos), and the photo
filename (`oDatosPersonales.UrlFoto`). Base rate ≈ 3.5% of candidates have ≥1 sentencia.

**Storage — SQLite warehouse `data/hdv/hdv_erm2026.sqlite` (gitignored; "local now, R2
later").** Heavy (~800 MB full) and re-derivable, so it stays off git. Keeps the **raw**
JSON (zlib-compressed, `raw` table) as source of truth AND **parsed** tables
(`sentencia_penal`, `sentencia_obliga`, plus a `meta` summary with `n_penal`/`n_obliga`/
`edu_max`/`foto`). `--reparse` rebuilds the parsed tables from stored raw with **no
network**, so widening the parser (bienes, ingresos, …) never needs a re-scrape. The DB
is its own checkpoint (resumable). Skips the ~6k rows with `hoja_vida_id == "0"` (no HDV).

**Incremental `--update`:** a `sig` (hash of a person's candidacies' estados) is stored per
HDV; only NEW or sig-changed HDVs are re-fetched (HDVs rarely change, so it's cheap). Run:
`python3 scripts/scrape_hdv_erm2026.py --update` (`--limit N` smoke; `--workers 8`;
`--refetch` force-all; `--reparse` offline).

**One-command update workflow.** `scrape_hdv_erm2026.run()` is importable, and
`scrape_erm2026.py --update --with-hdv --workers 9` runs the whole chain: list update →
`build_finder_json` → commit/push the list data (HDV is gitignored) → incremental HDV
refresh. The first HDV backfill is a one-time ~8–9 h run (92.6k candidates); subsequent
`--update`s are quick. **Not yet wired into the buscador** — that integration (sentencias/
educación in the dropdown + a per-candidate detail popup) is the next design step.

## Candidate finder — `buscador/` (Goal 3)

A self-contained article at `buscador/index.html` (vanilla HTML/JS, datapol terracotta/sand,
Spanish, shared `/shared/` nav) that lets users find candidates: pick tipo → cascading
departamento/provincia/distrito selectors (depth per tipo) → list cards (party, tipo de
organización, cabeza de lista, H/M counts, `estado_lista` badge) that expand to the full candidate
table (posición, nombre, DNI, cargo, sexo, edad; +province-of-candidacy for regional consejeros).

**Finder is ERM-only.** EG2026 is *not* in the finder — it's used only for the Goal-1 DNI-overlap
count. (So the earlier EG/ERM harmonization concern doesn't apply here.)

**Single source of truth — no double update.** `scripts/build_finder_json.py` reads
`data/erm2026_candidatos.csv` and (over)writes one file `buscador/data/candidatos.json` (~8 MB raw,
~1.8 MB gzipped; nested `circ[tipoId][ubigeo] → {dep,prov,dist,listas}`, candidate rows packed as
arrays per `cand_campos`). It is **idempotent** (always a full rebuild from the current CSV) and runs
**automatically at the end of every `scrape_erm2026.py` run** (hooked in `main()`; `--no-build` opts
out; failure there never invalidates a scrape). So `python3 scripts/scrape_erm2026.py --update`
refreshes the CSV *and* the finder in one command — the page can never drift from the scrape. It's
also runnable standalone: `python3 scripts/build_finder_json.py`.

**Worker tuning:** benchmarked on the regional tier — 3/6/9 workers ran 72s/43s/31s with **zero**
Imperva challenges. 6–9 workers are safe at observed volume; the script reports
`challenges/non200/neterr` counts in its final line so a long distrital run can be watched for WAF
escalation.

**`--update` (two cases, both keyed on `idSolicitudLista`):** the discovery pass over the full tree
is mandatory — every circunscripción's `GetExpedientesLista` is re-fetched and diffed against the
per-list ledger `data/.erm2026_state.json` (`{idSolicitudLista → {te, postula, idExpediente, estado}}`):
**new** `idSolicitudLista` → fetch candidates & append; **changed** `strEstadoLista` (e.g. RECIBIDO→INSCRITO)
→ re-fetch & replace rows; **unchanged** → skip (no `GetCandidatos`). A routine `--update` is thus
cheap on candidate fetches but always re-discovers newly-uploaded lists. Run: `python3 scripts/scrape_erm2026.py`
(fresh, resumes); `--update`; `--tipos 4`; `--limit N` (cap circunscripciones); `--full-refresh`; `--rebuild-tree`.

## Deliverables (all in this folder)

1. **DNI overlap** between the two processes — how many candidates (by DNI) appear in *both*
   EG2026 and ERM2026, reported as a count **and** a percentage.
2. **Per-political-organization dashboard** — for each organización política, how many lists it
   fielded, broken down by election type.
3. **Candidate finder** — a standalone `index.html` in its **own subfolder** that lets a user
   search candidates. It reads **pre-generated static JSON** (no backend; same static-site model as
   the rest of datapol). The scraper/analysis step produces those JSON files; the page only reads them.

## Articles

Two articles will be written here, **each as its own folder containing an `index.html`** (matching
the `articulos/<slug>/index.html` pattern used elsewhere in datapol).

## Inherited datapol conventions

This subproject lives in the datapol repo (https://datapol.lat), a **fully static site** on GitHub
Pages — no backend, no build step. Relevant conventions:

- **Static delivery:** data is generated by Python scrapers/scripts, committed to git, and fetched
  directly by vanilla-JS frontends. A `git push` to `main` redeploys and goes live in ~60s.
- **Frontend:** plain self-contained HTML files with inline `<style>`/`<script>`; **no** TypeScript,
  Node, npm, bundler, or test suite. Shared nav/styles live at the repo's `/shared/...` (absolute
  paths). UI copy is in **Spanish**. Shared terracotta/sand palette (`--bg:#f5f0e8`,
  `--terra:#c4603a`, …).
- **Python:** scrapers use `pandas` and often `curl_cffi`/`aiohttp`; deps installed ad hoc (no
  `requirements.txt`). Serve locally from the **repo root** so relative data paths resolve:
  `python3 -m http.server 7823 --directory /Users/mathieurojas/Documents/datapol`.
- **Commits:** data-update commits follow `data: <verb> <thing> — YYYY-MM-DD HH:MM`.
