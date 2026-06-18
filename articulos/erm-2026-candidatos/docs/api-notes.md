# JNE Plataforma Histórico — hidden JSON API notes

Reverse-engineered from `https://plataformahistorico.jne.gob.pe/ListaDeCandidatos/Index`
and its AngularJS controller `/Content/js/controllers/candidato/BusquedaCtrl.js?v=3`
(plus the `getProceso` logic in the `/Content/files/main-js` bundle).

**Status: investigation only — no scraper written yet.** All endpoints below were verified
live with `curl` on 2026-06-16 and returned HTTP 200 JSON. Field names are taken verbatim
from the live responses.

> Host base used throughout: `https://plataformahistorico.jne.gob.pe`

---

## 0. TL;DR for the scraper design

- **Two processes:** `idProcesoElectoral` **124** = ELECCIONES GENERALES 2026, **126** = ELECCIONES REGIONALES Y MUNICIPALES 2026.
- **Walk:** for each process → each `idTipoEleccion` → each circunscripción (ubigeo) → `GetExpedientesLista` (lists) → for each list `GetCandidatos` (rows). One candidate per row; flatten the list metadata onto each row.
- **`--update` is justified:** EG2026 lists are already `INSCRITO` (final); ERM2026 lists are still `RECIBIDO` (in flight) and new ones keep appearing. An update run should re-fetch and upsert by `idSolicitudLista` / `idExpediente`.
- **No bulk export** exists — the EXPORTAR button is client-side only (see §7). Per-list scraping is required.
- **No auth/headers/cookies needed** (see §6). Behind Imperva; probe politely.

---

## 1. Process list — find `idProcesoElectoral`

The process picker stores `idProceso|nombre|sigla|idTipoProceso` in `localStorage.sessionPE`.
The list itself comes from:

```
GET /Resoluciones/GetListProcesosCR
```

Relevant rows (of 26 total):

| idProcesoElectoral | strProcesoElectoral | idTipoProceso |
|---|---|---|
| **124** | **ELECCIONES GENERALES 2026** | 3 |
| 125 | ELECCIONES PRIMARIAS PARA LAS ELECCIONES GENERALES 2026 | 84 |
| **126** | **ELECCIONES REGIONALES Y MUNICIPALES 2026** | 2 |
| 127 | SEGUNDA ELECCION PRESIDENCIAL ELECCIONES GENERALES 2026 | 3 |
| 128 | ELECCIONES PRIMARIAS PARA LAS ELECCIONES REGIONALES Y MUNICIPALES 2026 | 84 |

> Only **124** and **126** are in scope. (Watch for **127** if a presidential runoff happens.)

---

## 2 & 3. Tipos de elección per process

```
GET /Candidato/GetTipoEleccionbyProceso/{idProcesoElectoral}
```

**EG2026 (124) — 5 tipos:**

| idTipoEleccion | strTipoEleccion | ámbito |
|---|---|---|
| 1  | PRESIDENCIAL | nacional (sin ubigeo) |
| 3  | PARLAMENTO ANDINO | nacional (sin ubigeo) |
| 15 | DIPUTADOS | por departamento |
| 20 | SENADORES DISTRITO ÚNICO | nacional |
| 21 | SENADORES DISTRITO MÚLTIPLE | por departamento |

**ERM2026 (126) — 3 tipos:**

| idTipoEleccion | strTipoEleccion | ubigeo requerido |
|---|---|---|
| 4 | REGIONAL | departamento (2 díg.) |
| 5 | MUNICIPAL PROVINCIAL | dep+prov (4 díg.) |
| 6 | MUNICIPAL DISTRITAL | dep+prov+dist (6 díg.) |

`AngularJS` constants seen in the controller: `IDTIPOELECCION_REGI__` (=4) and
`IDTIPOELECCION_CONG__` toggle the departamento/provincia/distrito dropdown visibility.

---

## 4. `GetExpedientesLista` — the URL grammar (the `124-15-------0-` mystery solved)

The controller builds the path as:

```
GET /Candidato/GetExpedientesLista/{idProceso}-{idTipoEleccion}-{strUbigeoPostula}-{Filtros}
```

where

- `strUbigeoPostula` = `strUbiDepartamento + strUbiProvincia + strUbiDistrito` **concatenated into ONE path segment** (each piece is 2 digits; empty for nacional). It is **not** split into separate dash-delimited fields.
- `Filtros` = `strCodigoExp - strOP - strTipoOP - strJEE - strEstado - idJuradoElectoral - strUbigeoDesc` (7 fields joined by `-`). When unfiltered: all empty except `idJuradoElectoral=0` → the literal string `-----0-`.

So the screenshot value `124-15-------0-` decodes as:

```
124      idProceso (EG2026)
15       idTipoEleccion (DIPUTADOS)
(empty)  strUbigeoPostula  → the lone empty slot right after "15-"
-----0-  Filtros (all empty, jurado=0)
```

i.e. `"124" + "-" + "15" + "-" + "" + "-" + "-----0-"` → `124-15-------0-`. The "empty middle
segments" are the **Filtros** fields, not ubigeo segments.

**The ubigeo for #4 lives entirely in the single `strUbigeoPostula` slot:**

| tipo | strUbigeoPostula | example path |
|---|---|---|
| PRESIDENCIAL (1) | `""` | `124-1--` + `-----0-` = `124-1-------0-` |
| DIPUTADOS (15), dept | `DD` | `124-15-16--` ... |
| REGIONAL (4), dept | `DD` | `126-4-15-` + `-----0-` |
| MUNICIPAL PROVINCIAL (5) | `DDPP` | `126-5-1501-` + `-----0-` |
| MUNICIPAL DISTRITAL (6) | `DDPPSS` | `126-6-150101-` + `-----0-` |

### Verified examples

```bash
# EG2026 presidencial (nacional) → 36 listas, all INSCRITO
curl 'https://plataformahistorico.jne.gob.pe/Candidato/GetExpedientesLista/124-1--%2D%2D%2D%2D%2D0%2D'

# ERM2026 regional, departamento "15" → 4 listas, all RECIBIDO
curl 'https://plataformahistorico.jne.gob.pe/Candidato/GetExpedientesLista/126-4-15-%2D%2D%2D%2D%2D0%2D'
```

> ⚠ **JNE ubigeo codes are internal, NOT INEI.** Departamento `15` returned **LORETO**
> (JEE "MAYNAS", strUbigeo `150000`) — not Lima. Always enumerate codes from the API (§5);
> never hardcode INEI numbers.

Trimmed sample row (`GetExpedientesLista`, full field list available in live response):

```json
{
  "idTipoEleccion": 1,
  "strUbigeo": "000000",
  "idExpediente": 228123,
  "strCodExpediente": "EG.2026016326",
  "idOrganizacionPolitica": 3025,
  "strOrganizacionPolitica": "ALIANZA ELECTORAL VENCEREMOS",
  "idSolicitudLista": 37782,
  "strEstadoLista": "INSCRITO",
  "strTipoOrganizacion": "ALIANZAS ELECTORALES",
  "intCandHombres": 2,
  "intCandMujeres": 1,
  "strJuradoElectoral": "LIMA CENTRO 1",
  "strDistritoElec": "ÚNICO NACIONAL",
  "idPlanGobierno": 29733,
  "strRutaArchivo": "plan de gobierno - venceremos.pdf"
}
```

Key fields for the deliverables: `idSolicitudLista`, `idExpediente` (needed for `GetCandidatos`),
`strOrganizacionPolitica` + `idOrganizacionPolitica` (dashboard #2), `strEstadoLista` (update logic),
`strTipoOrganizacion`, `intCandHombres/Mujeres`, `strUbigeo`, `strJuradoElectoral`.

---

## `GetCandidatos` — one row per candidate

```
GET /Candidato/GetCandidatos/{idTipoEleccion}-{idProceso}-{idSolicitudLista}-{idExpediente}
```

Note the **different field order** vs `GetExpedientesLista` (tipoEleccion first, then proceso).

```bash
# Venceremos presidencial ticket → 3 candidatos
curl 'https://plataformahistorico.jne.gob.pe/Candidato/GetCandidatos/1-124-37782-228123'
```

Trimmed sample (the live record has ~90 fields, mostly null placeholders for the HDV detail view):

```json
{
  "idCandidato": 278257,
  "idSolicitudLista": 37782,
  "strDocumentoIdentidad": "41373494",
  "strCandidato": "RONALD DARWIN ATENCIO SOTOMAYOR",
  "strApellidoPaterno": "ATENCIO",
  "strApellidoMaterno": "SOTOMAYOR",
  "strNombreCompleto": "RONALD DARWIN",
  "strSexo": "1",
  "strFechaNacimiento": "30/09/1981 00:00:00",
  "intEdad": 44,
  "idCargoEleccion": 1,
  "strCargoEleccion": "PRESIDENTE DE LA REPÚBLICA",
  "intPosicion": 1,
  "strUbigeoPostula": "140100",
  "idHojaVida": 246962,
  "strEstadoExp": "INSCRITO"
}
```

Key fields: **`strDocumentoIdentidad` (DNI — the join key for overlap deliverable #1)**,
`strCandidato` / `strNombreCompleto`, `strSexo`, `intEdad`, `strCargoEleccion`, `intPosicion`,
`strUbigeoPostula`, `idHojaVida` (→ links to `/ListaDeCandidatos/DetalleHDV` CV detail if ever needed).

---

## 5. Circunscripción enumerators (to iterate all ubigeos)

```
GET /Candidato/ListUbigeoDepartamento                 → 25 departamentos (no params)
GET /Candidato/ListUbigeoProvincia?id={DD}            → provincias of departamento DD
GET /Candidato/ListUbigeoDistrito/{DD}{PP}            → distritos of provincia DD+PP (e.g. /1501)
GET /JEE/GetUbigeoporJEE?id={idTipoEleccion}-{idProceso}-{idJuradoElectoral}
```

- `ListUbigeoDepartamento` fields: `idUbigeo`, `strUbigeo` (6-digit), `strUbiDepartamento` (2-digit), `strDepartamento`.
- `ListUbigeoProvincia` fields: `strUbiProvincia` (2-digit), `strProvincia`.
- `ListUbigeoDistrito` fields: `strUbiDistrito` (2-digit), `strDistrito`.
- **`GetUbigeoporJEE`** (use `idJuradoElectoral=0` for all) returns the full circunscripción list with
  `strUbigeo`, `strUbiDepartamento/Provincia/Distrito`, `idJuradoElectoral`, `strJuradoElectoral`,
  `strDistritoElectoral`. For REGIONAL it returned 25 rows (one per región). This is the cleanest
  driver for enumerating circunscripciones per tipo — it already scopes to what each tipo needs.

Concatenate `strUbiDepartamento + strUbiProvincia + strUbiDistrito` to build `strUbigeoPostula` for §4.

Example:

```bash
curl 'https://plataformahistorico.jne.gob.pe/Candidato/ListUbigeoDepartamento'
curl 'https://plataformahistorico.jne.gob.pe/Candidato/ListUbigeoProvincia?id=15'
curl 'https://plataformahistorico.jne.gob.pe/Candidato/ListUbigeoDistrito/1501'
curl 'https://plataformahistorico.jne.gob.pe/JEE/GetUbigeoporJEE?id=4-126-0'
```

Sample `GetUbigeoporJEE` row:

```json
{"strUbigeo":"010000","strUbiDepartamento":"01","strUbiProvincia":"00","strUbiDistrito":"00",
 "strDepartamento":"AMAZONAS","idJuradoElectoral":2288,"strJuradoElectoral":"CHACHAPOYAS"}
```

---

## 6. Headers / cookies / WAF behavior

- **No headers required.** Bare `curl` (default curl UA, no Referer, no `X-Requested-With`, no cookies)
  returns `200 application/json`. A browser UA + `Referer` + `X-Requested-With: XMLHttpRequest`
  were used during testing but are **not** necessary.
- **Imperva (Incapsula)** fronts the site (`x-cdn: Imperva`; DNS `plataformahistorico.jne.gob.pe`
  → `3f6zf35.ng.impervadns.net` → `45.60.86.193`). The HTML page sets `visid_incap_3331854` and
  `incap_ses_*` cookies, but the JSON API did not require them in testing.
- **No rate-limit or challenge observed** at the gentle pace used (single requests, 2–3 s apart).
  Recommended for the real scraper anyway: realistic browser UA, persistent cookie jar (carry the
  `incap_*` cookies from one HTML page-load), 1–3 s jitter between calls, bounded concurrency,
  exponential backoff on any non-200 / HTML challenge body. Imperva can escalate to JS/CAPTCHA
  challenges under aggressive load — if a response comes back as HTML instead of JSON, that's the
  signal to slow down and refresh cookies.
- One transient **DNS resolution failure** occurred mid-session (sandbox network, not a block) and
  recovered on its own — treat `HTTP 000` / "could not resolve host" as retryable network noise,
  distinct from an Imperva challenge (which returns HTTP 200 with an HTML body).

---

## 7. EXPORTAR button — NOT a bulk-export endpoint

The EXPORTAR button is **100% client-side**. The controller's `Exportar` builds an HTML `<table>`
in JS from `$scope.exportData` (the list rows *currently loaded on screen* for one circunscripción)
and saves it via a `data:application/vnd.ms-excel` blob — `exportCols` are just column widths.
There is **no server round-trip and no candidate-level data** in it (only the list summary rows).

➡ **It cannot replace per-list scraping.** We still must walk `GetExpedientesLista` →
`GetCandidatos` for every circunscripción. (`descargarArchivo` is unrelated — it just opens a
plan-de-gobierno PDF via `strRutaArchivo`.)

---

## Endpoint reference (all GET)

| Purpose | Endpoint |
|---|---|
| List electoral processes | `/Resoluciones/GetListProcesosCR` |
| Tipos de elección for a process | `/Candidato/GetTipoEleccionbyProceso/{idProceso}` |
| Lists (expedientes) | `/Candidato/GetExpedientesLista/{idProceso}-{idTipoEleccion}-{ubigeo}-{filtros}` |
| Candidates in a list | `/Candidato/GetCandidatos/{idTipoEleccion}-{idProceso}-{idSolicitudLista}-{idExpediente}` |
| Departamentos | `/Candidato/ListUbigeoDepartamento` |
| Provincias of a dept | `/Candidato/ListUbigeoProvincia?id={DD}` |
| Distritos of a prov | `/Candidato/ListUbigeoDistrito/{DD}{PP}` |
| Circunscripciones by JEE | `/JEE/GetUbigeoporJEE?id={idTipoEleccion}-{idProceso}-{idJuradoElectoral}` |
| Jurados electorales (POST) | `/Home/GetListaJuradoElectoral` body `{idProcesoElectoral}` |

Not yet explored (CV / plan-de-gobierno detail, likely not needed for the 3 deliverables):
`/ListaDeCandidatos/DetalleExpediente`, `/ListaDeCandidatos/DetalleHDV`,
`/ListaDeCandidatos/ResumenPlanGobierno` (these are `POST`-via-form redirects to detail pages).
