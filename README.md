# datapol

Multi-country Latin American electoral intelligence platform.

## Countries

- **Colombia** — Congressional elections March 2026 (Senado)

## Structure

```
datapol/
├── colombia/
│   ├── data/
│   │   ├── raw/          ← source files (PDF, JSON, GeoJSON)
│   │   └── processed/    ← generated CSVs, GeoJSONs, plots
│   └── scripts/          ← Python pipeline (run in order 01–07)
└── web/                  ← frontend (Leaflet, vanilla JS)
```

## Colombia pipeline

```bash
cd colombia/scripts
pip install -r requirements.txt

python3 01_parse_divipole.py
python3 02_parse_nomenclator.py
python3 03_build_bridge.py
python3 04_scrape_results.py
python3 05_aggregate.py
python3 06_build_geojson.py
python3 07_visualize.py
```

Outputs land in `colombia/data/processed/`.
