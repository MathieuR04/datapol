#!/usr/bin/env bash
# Pipeline completo: unidades → celdas → distritos → resultados → mapa → web.
# Tras un `scraper.py --update` de las actas basta con `--desde 04`
# (los distritos no dependen de los votos).
set -euo pipefail
cd "$(dirname "$0")/.."
DESDE="${2:-01}"; [[ "${1:-}" == "--desde" ]] || DESDE=01
UV="uv run --with pandas --with pyarrow --with scipy --with geopandas --with duckdb --with topojson python"
[[ "$DESDE" > "01" ]] || $UV scripts/01_unidades.py
[[ "$DESDE" > "02" ]] || $UV scripts/02_celdas.py
[[ "$DESDE" > "03" ]] || $UV scripts/03_distritos.py
[[ "$DESDE" > "04" ]] || $UV scripts/04_resultados.py
[[ "$DESDE" > "05" ]] || $UV scripts/05_geo.py
$UV scripts/06_web.py
