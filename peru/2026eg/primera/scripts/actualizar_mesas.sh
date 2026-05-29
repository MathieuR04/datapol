#!/usr/bin/env bash
# actualizar_mesas.sh
# Pipeline de noche electoral — resultados a nivel de mesa de votación.
#
# Ejecuta en orden:
#   02b  Scrape ONPE (solo mesas no-Contabilizadas, --update)
#   05   Forecast (proyección de resultados)
#   07   JEE GeoJSONs + national summary
# Luego hace git commit + push con timestamp.
#
# Uso:
#   bash scripts/actualizar_mesas.sh
#
# Requiere: curl_cffi, geopandas, pandas  (pip install curl_cffi geopandas pandas)

set -euo pipefail

# ── Rutas ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIMERA_DIR="$(dirname "$SCRIPT_DIR")"
DATAPOL_DIR="$(dirname "$(dirname "$(dirname "$PRIMERA_DIR")")")"
DATA_DIR="$PRIMERA_DIR/data"
WEB_DIR="$DATAPOL_DIR/web/peru/presidencial2026"

# ── Colores para la terminal ───────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }
fail() { echo -e "${RED}✗  $*${RESET}"; exit 1; }

# ── 1. Scrape mesas (solo no-Contabilizadas) ───────────────────────────────────
step "02b — Scrape ONPE mesas (--update)"
python3 "$SCRIPT_DIR/02b_scrape_mesas.py" --update || fail "02b falló"

# ── 2. Forecast ────────────────────────────────────────────────────────────────
step "05 — Forecast"
python3 "$SCRIPT_DIR/05_forecast.py" || fail "05 falló"

# ── 3. JEE GeoJSONs ────────────────────────────────────────────────────────────
step "07 — JEE GeoJSONs"
python3 "$SCRIPT_DIR/07_build_jee.py" || fail "07 falló"

# ── 4. Git commit + push ───────────────────────────────────────────────────────
step "Git — staging archivos de resultados"

cd "$DATAPOL_DIR"

git add \
  "peru/2026eg/primera/data/results/peru_2026eg_mesa_primera.csv" \
  "peru/2026eg/primera/data/forecast.json" \
  "web/peru/presidencial2026/jee/jee_dept.geojson" \
  "web/peru/presidencial2026/jee/jee_provincia.geojson" \
  "web/peru/presidencial2026/jee/jee_distrito.geojson" \
  "web/peru/presidencial2026/jee/jee_national.json"

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

if git diff --cached --quiet; then
  warn "Sin cambios — nada que commitear."
else
  git commit -m "$(cat <<EOF
Actualizar resultados mesas: $TIMESTAMP

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
  echo -e "\n${BOLD}${GREEN}▶ Git push${RESET}"
  git push
  echo -e "\n${GREEN}✔  Publicado en GitHub Pages — $TIMESTAMP${RESET}"
fi
