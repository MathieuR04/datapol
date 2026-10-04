# Scripts ERM 2026

Numerados por etapa, en el orden en que corren. Todos se corren desde
`peru/2026erm/` con `uv run python scripts/<nombre>.py --help`.

## 00 — Preparación (estático, ya corrido)

Solo se vuelven a correr si cambia un insumo.

| Script | Hace | Escribe |
|---|---|---|
| `00a_candidatos_inscritos.py` | Registro JNE → candidaturas inscritas con `race_id` | `data/processed/candidatos_inscritos.*` |
| `00b_registro_carreras.py` | Las 2,118 carreras y los 1,892 distritos | `data/reference/carreras.csv`, `distritos.csv` |
| `00c_escanos_regidores.py` | Res. 0847-2025-JNE → regidores por concejo | `data/reference/regidores_2026.csv` |
| `00d_mesas.py` | SAIP de la ONPE → 89,935 mesas y 10,180 locales | `data/processed/mesas.*`, `data/reference/locales.csv` |
| `00e_tenientes.py` | Alcaldes que vuelven como teniente alcalde | `data/reference/tenientes.csv` |
| `00f_colores.py` | Un color por organización; las alianzas heredan el del ancla | `data/reference/colores_2026.csv`, `data/colores.json` |
| `00g_prepobla.py` | El sitio en cero: 2,118 páginas `por_definir` | `data/carrera/`, `meta.json`, `nacional.json` |
| `00h_fichas_hdv.py` | Fichas de hoja de vida por carrera, desde el sqlite del operador | `data/hdv/` |
| `00i_rla_historico.py` | López Aliaga en Lima por distrito: EG 2021, ERM 2022, EG 2026 | `data/rla.json` |

## 01 — Publicación estática (hoy, al cerrar candidatos)

| Script | Hace | Escribe |
|---|---|---|
| `01a_publica_candidatos.py` | Buscador de candidatos en trozos por circunscripción | `data/candidatos/` |
| `01b_publica_tenientes.py` | Tablero de tenientes alcalde | `data/tenientes.json` |

## 02–06 — La noche (cada ciclo)

| Script | Hace | Lo llama |
|---|---|---|
| `02a_scrape_distritos.py` | **Flujo A.** Totales por carrera (`totales` + participantes) | `actualizar_distritos.sh` |
| `02b_scrape_mesas.py` | **Flujo B.** Todas las actas de cada mesa | `actualizar_mesas.sh` |
| `03_consolida_mesas.py` | Último estado de cada acta → `computo_mesa` y `resultados_mesa` | `actualizar_mesas.sh` |
| `04_publica_resultados.py` | Cómputo oficial → `carrera/*.json`, `nacional.json`. **Solo resultados**: no proyecta ni llama ganadores. ~12 s con todas las actas | `_publica.sh` |
| `05_publica_electos.py` | Directorio nacional de autoridades electas | después de 04 |
| `06_publica_comparacion.py` | 2026 contra 2022 | después de 04 |

## m — Pasos manuales (una vez, con revisión humana)

No están en ningún ciclo: se corren a mano y su salida se revisa antes de usarla.

| Script | Hace | Escribe |
|---|---|---|
| `m1_crosswalk_organizaciones.py` | **Pendiente, opcional.** `04` ya cruza por nombre dentro de cada carrera; lo que no cruza queda en `processed/publica_sin_cruce.csv`. `m1` sirve para revisar esos casos a mano | `data/reference/crosswalk_organizaciones_2026.csv` |

El operador revisa la propuesta, corrige lo que haga falta en
`data/reference/crosswalk_manual.csv` (gana sobre lo propuesto) y el resultado
final queda en `data/reference/crosswalk_organizaciones_2026.csv`, versionado con
su reporte. `04` solo lee ese archivo final; si falta una organización, la
muestra con el nombre de la ONPE, sin foto ni ficha.

## Dónde quedan los resultados

| Qué | Ruta | |
|---|---|---|
| Respuesta cruda de la ONPE | `data/raw/onpe_vivo/{mesas,agregado}/{corte}/*.jsonl.gz` | inmutable, fuera de git |
| Actas por mesa, cada corte | `data/interim/mesas/actas/{corte}-NNNNN.parquet` | append-only |
| Votos por mesa, cada corte | `data/interim/mesas/votos/{corte}-NNNNN.parquet` | append-only |
| Totales por carrera, cada corte | `data/interim/agregado/{totales,participantes}/{corte}.parquet` | append-only |
| Checkpoints | `data/interim/{mesas,agregado}/estado.json` | |
| **Último estado por acta** | `data/processed/computo_mesa_ERM2026.parquet` | una fila por (mesa, tipo) |
| **Último voto por acta** | `data/processed/resultados_mesa_ERM2026.parquet` | una fila por (mesa, tipo, org); solo actas `C` |
| Mesas donde la ONPE contradice al maestro | `data/processed/mesas_discrepancia_maestro.csv` | manda la ONPE |
| Lo que ve el sitio | `data/carrera/*.json`, `data/nacional.json` | lo escribe 04 |

La carrera de cada acta sale del **ubigeo que trae la ONPE** en el acta, no del
número de mesa: en el maestro la carrera es función pura del distrito, así que
`(ubigeo, tipo) → race_id` es exacto.

### Los dos pipelines

```bash
cd ~/Documents/datapol/peru/2026erm
export ONPE_HOST=https://<subdominio>.onpe.gob.pe

bash scripts/actualizar_mesas.sh --limite 50 --once --no-push    # prueba corta
bash scripts/actualizar_mesas.sh                                 # bucle, cada 300 s
bash scripts/actualizar_distritos.sh --recurso <ruta>            # bucle, cada 90 s
```

| | Ciclo |
|---|---|
| `actualizar_distritos.sh` | 02a → 04 → git commit + push |
| `actualizar_mesas.sh` | 02b `--update` → 03 → 04 → git commit + push |
| `_publica.sh` | Paso común (04 + git), con candado para que los dos no se pisen |

Opciones de los dos: `--once`, `--no-push`, `--sleep N`, `--workers N`.

### Orden la primera vez que salga la ONPE

1. `actualizar_mesas.sh --limite 50 --once --no-push` — valida formato, deja crudo.
2. `03_consolida_mesas.py` escribe `docs/id_eleccion_descubrimiento.md`; con eso se
   llena `data/reference/id_eleccion.csv` (`id_eleccion,tipo`).
3. `02a_scrape_distritos.py --host … --recurso … --probar 01-150000` — confirma el
   recurso de participantes y los parámetros.
4. `m1_crosswalk_organizaciones.py`, revisión y `crosswalk_manual.csv`.
5. Los dos `.sh` en bucle. (Pueden arrancar antes del paso 4: archivan y
   consolidan igual; el sitio muestra el nombre de la ONPE hasta que haya crosswalk.)

## `src/datapol/` — librería

| Módulo | |
|---|---|
| `onpe.py` | Cliente ONPE (`curl_cffi`), crudo inmutable, parseo de actas |
| `fuentes.py` | Lectura de las fuentes del operador (`articulos/erm-2026-candidatos`, solo lectura) |
| `allocator.py`, `adjudicacion.py`, `estados.py` | Reparto de escaños y estados de carrera |
| `forecaster.py`, `forecast_mesas.py` | Proyección Monte Carlo por mesa |

## `archivo/` — no se usa hoy

| Script | Por qué está aquí |
|---|---|
| `watch_sorteo.py` | Fase 03 cancelada |
| `build_geo_nacional.py`, `recorta_geo.py` | Geometría ya construida en `data/geo/` |
| `noche_electoral.py` | Replay de la noche de 2022 |
| `publica_json.py` | Emisor de 2022: es la base de `04_publica_resultados.py` |

Los de `archivo/` quedaron con rutas de la nueva ubicación pero no se probaron
aquí.
