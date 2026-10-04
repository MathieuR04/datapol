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

## 01 — Publicación estática (hoy, al cerrar candidatos)

| Script | Hace | Escribe |
|---|---|---|
| `01a_publica_candidatos.py` | Buscador de candidatos en trozos por circunscripción | `data/candidatos/` |
| `01b_publica_tenientes.py` | Tablero de tenientes alcalde | `data/tenientes.json` |

## 02–07 — La noche

| Script | Hace | Lo llama |
|---|---|---|
| `02a_scrape_distritos.py` | **Flujo A.** Totales por carrera (`totales` + participantes) | `actualizar_distritos.sh` |
| `02b_scrape_mesas.py` | **Flujo B.** Todas las actas de cada mesa | `actualizar_mesas.sh` |
| `03_consolida_mesas.py` | Último estado de cada acta → `computo_mesa` y `resultados_mesa` | `actualizar_mesas.sh` |
| `04_crosswalk_organizaciones.py` | **Pendiente.** Código ONPE ↔ id JNE por nombre + ámbito | a mano, una vez |
| `05_publica_resultados.py` | **Pendiente.** Tablas → `carrera/*.json`, `nacional.json` | `_publica.sh` |
| `06_publica_electos.py` | Directorio nacional de autoridades electas | después de 05 |
| `07_publica_comparacion.py` | 2026 contra 2022 | después de 05 |

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
| `actualizar_distritos.sh` | 02a → 05 → git commit + push |
| `actualizar_mesas.sh` | 02b `--update` → 03 → 05 → git commit + push |
| `_publica.sh` | Paso común (05 + git), con candado para que los dos no se pisen |

Opciones de los dos: `--once`, `--no-push`, `--sleep N`, `--workers N`.

### Orden la primera vez que salga la ONPE

1. `actualizar_mesas.sh --limite 50 --once --no-push` — valida formato, deja crudo.
2. `03_consolida_mesas.py` escribe `docs/id_eleccion_descubrimiento.md`; con eso se
   llena `data/reference/id_eleccion.csv` (`id_eleccion,tipo`).
3. `02a_scrape_distritos.py --host … --recurso … --probar 01-150000` — confirma el
   recurso de participantes y los parámetros.
4. `04_crosswalk_organizaciones.py`.
5. Los dos `.sh` en bucle.

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
| `publica_json.py` | Emisor de 2022: es la base de `05_publica_resultados.py` |

Los de `archivo/` quedaron con rutas de la nueva ubicación pero no se probaron
aquí.
