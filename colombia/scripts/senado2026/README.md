# Senado 2026 — Scripts

These scripts produced the final Senado 2026 election data.
Run order (from repo root `colombia/`):

| Step | Script | Inputs | Outputs |
|------|--------|--------|---------|
| 1 | `../01_parse_divipole.py` | `data/raw/Divipole*.pdf` | `data/processed/puestos_master.csv` |
| 2 | `../02_parse_nomenclator.py` | `data/raw/nomenclator.json` | `data/processed/parties.json` |
| 3 | `../03_build_bridge.py` | `data/processed/puestos_master.csv` | `data/processed/mpio_bridge.csv`, `dept_bridge.csv` |
| 4 | `04_scrape_results.py` | `puestos_master.csv` | `data/processed/resultados_puestos.csv` |
| 4b | `04b_scrape_mesas.py` | `puestos_master.csv` | `data/processed/resultados_mesas.csv` |
| 5 | `05_aggregate.py` | `resultados_puestos.csv` | `resultados_municipios.csv`, `resultados_departamentos.csv`, `national_parties.json`, `indigena_parties.json` |
| 6 | `06_build_geojson.py` | GeoJSON + CSVs | `colombia_results_map.geojson`, `colombia_results_dept.geojson`, indigena variants |
| 7 | `07_seat_allocation.py` | `national_parties.json` | `senate_seats.json` |

**Re-run on election night:** `python 04_scrape_results.py --update` → then 5 → 6 → 7.

**Shared data** (do not delete — also used by presidencial2026):
- `data/processed/puestos_master.csv` — polling table registry
- `data/processed/mpio_bridge.csv`, `dept_bridge.csv` — code→name bridges
- `data/processed/colombia_municipios.geojson` — municipio boundaries
- `data/raw/00.geojson` — department boundaries
