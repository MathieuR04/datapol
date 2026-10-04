# Roadmap 2026 — construcción de datos

Objetivo: llegar al 4 de octubre de 2026 con todo lo estático congelado y
verificado, de modo que ese día solo haya que correr el pipeline.

| # | Fase | Depende de | Bloqueada por | Estado |
|---|---|---|---|---|
| 03 | ~~Sorteo de cédula~~ | — | — | [—] **cancelada**, ver docs/mesas.md y memoria |
| 00 | Fuentes locales de candidaturas | — | — | [x] 87,143 candidatos, 2,118 carreras |
| 01 | Registro de carreras y distritos | 00 | — | [x] cuadres exactos |
| 02 | Escaños por circunscripción | 00, 01 | — | [x] 13,148 cuadra |
| 04 | Mesas, locales y asignación a carreras | 01 | — | [x] 89,935 mesas, SAIP |
| 05 | Organizaciones y crosswalk ONPE↔JNE | 00 | — | [ ] por nombre + ámbito |
| 06 | Cliente en vivo | 01, 04 | — | [ ] |
| 07 | Pre-poblado y ensayo general | todas | — | [ ] |

## Orden real de ejecución (12 de setiembre de 2026)

**00, 01, 02 y 04 están hechas.** Queda la 05, la 06 y la 07.

La 05 ya no necesita el sorteo: se resuelve por nombre + ámbito. La 06 es lo único
que queda con dependencia externa. La 07 depende de todas.

**El camino crítico ya no es este bloque, es el frontend** (fase 07 del bloque
2022). Ver `2022/ROADMAP.md`.

## Estado de la fase 00 — hecha (12 de setiembre de 2026)

Reconstruida contra el registro del JNE ya cerrado: **87,143 candidaturas**, 10,797
listas, **las 2,118 carreras cubiertas**, 16 tests. Ver `docs/candidatos-inscritos.md`.

La corrida del 12 de agosto tenía 26,936 filas porque el JNE llevaba apenas ~27% de
listas inscritas. **Cualquier derivado de esa versión está mal y hay que rehacerlo.**

Único pendiente declarado: 44 consejeros cuya HDV trae el bloque `strPostula*`
vacío. Van con `race_id` nulo, no se rellenan.

## Fase 03 — CANCELADA

El puente ONPE↔JNE de organizaciones **no necesita la posición en cédula**: se
resuelve por nombre normalizado y, donde el nombre choca, por ámbito departamental.

La spec justificaba el puente por cédula con el choque entre los dos "PARTIDO
DEMOCRATICO SOMOS PERU" (id_jne 14 y 3045), que supuestamente el ámbito no
desempataba "porque las dos son nacionales". Contra los datos reales es falso: el 14
es el partido nacional (1,092 listas, 24 departamentos, **sin Puno**) y el 3045 es
una alianza que existe **solo en Puno** (37 listas). **No comparten ni una carrera.**

En ERM 2022, con 128 organizaciones —casi el doble que las 74 de 2026— el cruce por
nombre resolvió 126 y solo 2 fueron a `crosswalk_manual_2022.csv`.

`watch_sorteo.py` y `docs/sorteo.md` quedan como registro; no los corras.

## Estado de la fase 01 — hecha

`distritos.csv` (1,892) y `carreras.csv` (2,118) en `data/reference/`, con los 15
cuadres exactos. Ver `docs/registro-carreras.md`.

**Corrección a la spec:** son **1,892** distritos, no 1,896. El cuadre de la spec no
cerraba consigo mismo (1,896 − 196 ≠ 1,696).

## Estado de la fase 02 — hecha, con una confirmación pendiente

364 consejeros (Res. 0001-2026-JNE) + 10,842 regidores (conteo de candidatos) →
**13,148 autoridades, exacto**. Ver `docs/escanos.md`.

El PDF de la Res. 0847-2025-JNE **no fue necesario**: el conteo de candidatos, que la
spec planteaba como validación cruzada, reproduce el objetivo legal solo. Sigue
valiendo la pena conseguirlo para cruzar concejo por concejo, pero **ya no bloquea**:
hay `n_escanos` para las 2,118 carreras y se puede pre-poblar autoridades.

## Estado de la fase 04 — hecha, sin una sola petición de red

**89,935 mesas** con distrito y carreras, **10,180 locales**. Ver `docs/mesas.md`.

Los dos bloqueos que esta sección declaraba **ya no existen**, los dos resueltos por
la respuesta SAIP de la ONPE al Expediente 292325-2026, archivada en
`data/raw/onpe_saip_292325_2026/`:

1. ~~Token de AWS WAF~~ — `consultaelectoral.onpe.gob.pe` existía solo para sacar
   mesas y locales de a una consulta por DNI. **No lo persigas.**
2. ~~`n_mesas` por distrito~~ — viene en la fuente, por local.

Matiz a la nota vieja: es cierto que **los números de mesa** cambian entre procesos,
pero **la convención de numeración no**, y eso es lo que se reutiliza. El rango
normal se valida al 100.0000% contra ERM 2022 *y* contra EG 2026; el rango 900k se
ordena por `(ODPE, ubigeo)` y acierta el 99.94% contra EG 2026, donde ordenar solo
por ubigeo daría 22.0%.

## El snapshot diario ya no va

Estaba planteado como tarea permanente desde el primer día. **Se cancela**: las
fuentes locales las actualiza a diario un flujo aparte, así que la serie ya se está
capturando fuera de este repo.

En su lugar va `candidatos_inscritos`, que se reconstruye entero desde la fuente del
día y crece conforme el JNE inscribe listas. No acumula ni versiona: la fuente de
verdad es el registro del operador, y este repo solo lo deriva.

La cláusula del art. 6 del sorteo y el versionado de `cedula.csv` **caen con la
fase 03**.
