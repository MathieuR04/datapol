# Presidencial 2026 — Scripts (Primera Vuelta, 31 mayo)

## Pipeline on election night

```
# 1. Scrape mesa-level results (run repeatedly throughout the night)
python scrape_mesas.py            # full initial scrape
python scrape_mesas.py --update   # subsequent updates (only incomplete mesas)

# 2. Aggregate to municipio + dept
python aggregate.py

# 3. Build GeoJSON for the frontend map
python build_geojson.py

# 4. Run Monte Carlo forecast (run after every aggregate cycle)
python forecast.py

# Then git add + push → GitHub Pages serves updated JSONs within ~60s
```

## Shared data (same tables as Senado)
These files in `../../data/processed/` are reused as-is:
- `puestos_master.csv` — all 14,430 puestos (national + exterior)
- `mpio_bridge.csv`, `dept_bridge.csv` — code-to-name mappings
- `colombia_municipios.geojson` — municipio boundaries
- `../raw/00.geojson` — department boundaries

## outputs (in `../../data/presidencial2026/processed/`)
| File | Description |
|------|-------------|
| `resultados_mesas.csv` | Raw mesa-level results |
| `resultados_municipios.csv` | Aggregated by municipio |
| `resultados_departamentos.csv` | Aggregated by dept |
| `results.json` | National totals + per-candidate votes |
| `forecast.json` | Monte Carlo runoff probabilities |
| `colombia_results_presidencial_map.geojson` | Map-ready municipio GeoJSON |
| `colombia_results_presidencial_dept.geojson` | Map-ready dept GeoJSON |

## Before election day: update BASE_URL in scrape_mesas.py
The Registraduría publishes results at a new URL for each election.
Pattern from Senado 2026: `resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/{code}.json`
Expected pattern for presidential: `resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json`
Verify by checking registraduria.gov.co on May 31.

## Candidate codcan mapping
On election day, fetch `00.json` summary and inspect the `camaras[].partotabla`
to map Registraduría's `codpar` values to our candidate codes.
Update `candidates.json` with `"codcan": <int>` field for each candidate.
