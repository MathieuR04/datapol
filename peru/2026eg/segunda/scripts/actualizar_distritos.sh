#!/usr/bin/env bash
# actualizar_distritos.sh — Peru 2026 EG Segunda Vuelta
# Pipeline de noche electoral — resultados a nivel distrital.
#
# Ejecuta en orden:
#   02a  Scrape ONPE (solo distritos incompletos, --update)
#   03   GeoJSON distrital/provincial/departamental
#   04   Estadísticas nacionales (aggregate_stats.json)
#   06   Comparación 2021-2026
#   08   Datos análisis scatter-plot
# Luego hace git commit + push con timestamp.
#
# Uso:
#   bash scripts/actualizar_distritos.sh
#
# Requiere: curl_cffi, geopandas, pandas  (pip install curl_cffi geopandas pandas)

set -euo pipefail

# ── Rutas ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEGUNDA_DIR="$(dirname "$SCRIPT_DIR")"          # segunda/
DATAPOL_DIR="$(dirname "$(dirname "$(dirname "$SEGUNDA_DIR")")")"  # datapol/
DATA_DIR="$SEGUNDA_DIR/data"

# ── Colores para la terminal ───────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }
fail() { echo -e "${RED}✗  $*${RESET}"; exit 1; }

# ── 1. Scrape distritos (solo incompletos) ─────────────────────────────────────
step "02a — Scrape ONPE (--update)"
python3 "$SCRIPT_DIR/02a_scrape_distritos.py" --update || fail "02a falló"

# ── 2. GeoJSONs ────────────────────────────────────────────────────────────────
step "03 — Build GeoJSONs"
python3 "$SCRIPT_DIR/03_build_geojson.py" || fail "03 falló"

# ── 3. Estadísticas nacionales ─────────────────────────────────────────────────
step "04 — Aggregate stats"
python3 "$SCRIPT_DIR/04_aggregate_stats.py" || fail "04 falló"

# ── 4. Comparación 2021-2026 ───────────────────────────────────────────────────
step "06 — Comparison GeoJSONs"
python3 "$SCRIPT_DIR/06_build_comparison.py" || fail "06 falló"

# ── 5. Análisis scatter-plot ───────────────────────────────────────────────────
step "08 — Analisis data"
python3 "$SCRIPT_DIR/08_build_analisis.py" || fail "08 falló"

# ── 6. Git commit + push ───────────────────────────────────────────────────────
step "Git — staging archivos de resultados"

cd "$DATAPOL_DIR"

git add \
  "peru/2026eg/segunda/data/results/peru_2026eg_distrito_segunda.csv" \
  "peru/2026eg/segunda/data/peru_2026eg_distrito_segunda.geojson" \
  "peru/2026eg/segunda/data/peru_2026eg_provincia_segunda.geojson" \
  "peru/2026eg/segunda/data/peru_2026eg_departamento_segunda.geojson" \
  "peru/2026eg/segunda/data/aggregate_stats.json" \
  "peru/2026eg/segunda/data/comparison/peru_2026_segunda_distrito_comparison.geojson" \
  "peru/2026eg/segunda/data/comparison/peru_2026_segunda_provincia_comparison.geojson" \
  "peru/2026eg/segunda/data/comparison/peru_2026_segunda_departamento_comparison.geojson" \
  "peru/2026eg/segunda/data/analisis/analisis_data.json"

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

if git diff --cached --quiet; then
  warn "Sin cambios — nada que commitear."
else
  git commit -m "$(cat <<EOF
Actualizar resultados distritales segunda vuelta: $TIMESTAMP

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
  echo -e "\n${BOLD}${GREEN}▶ Git push${RESET}"
  git push
  echo -e "\n${GREEN}✔  Publicado en GitHub Pages — $TIMESTAMP${RESET}"
fi
