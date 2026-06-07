#!/usr/bin/env bash
# actualizar_mesas.sh — Peru 2026 EG Segunda Vuelta
# Pipeline MESA de noche electoral — pronóstico y JEE.
#
# Ciclo: 02b --update → 05 → 07 → git commit + push
#
# Uso:
#   bash scripts/actualizar_mesas.sh            # loop continuo (default 180s)
#   bash scripts/actualizar_mesas.sh --no-push  # sin git push (testing)
#   bash scripts/actualizar_mesas.sh --once     # ejecutar una sola vez
#   bash scripts/actualizar_mesas.sh --sleep 60 # intervalo personalizado
#
# Requiere: curl_cffi, geopandas, pandas

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEGUNDA_DIR="$(dirname "$SCRIPT_DIR")"
DATAPOL_DIR="$(dirname "$(dirname "$(dirname "$SEGUNDA_DIR")")")"

PUSH=true
LOOP=true
SLEEP_SECS=180

# ── Parse args ──────────────────────────────────────────────────────────────────
i=1
while [[ $i -le $# ]]; do
  arg="${!i}"
  case "$arg" in
    --no-push) PUSH=false ;;
    --once)    LOOP=false ;;
    --sleep)
      i=$((i+1)); SLEEP_SECS="${!i}" ;;
  esac
  i=$((i+1))
done

# ── Colores ─────────────────────────────────────────────────────────────────────
BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }

# ── Un ciclo ─────────────────────────────────────────────────────────────────────
run_once() {
  echo ""
  echo "══════════════════════════════════════════════════════════"
  echo " Mesas pipeline — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  step "02b — Scrape ONPE mesas (--update)"
  python3 "$SCRIPT_DIR/02b_scrape_mesas.py" --update --workers 50 || {
    warn "02b falló — abortando ciclo"
    return
  }

  step "05 — Forecast (probabilidad de ganar)"
  python3 "$SCRIPT_DIR/05_forecast.py" || {
    warn "05 falló — continuando de todas formas"
  }

  step "07 — JEE GeoJSONs"
  python3 "$SCRIPT_DIR/07_build_jee.py" || {
    warn "07 falló — continuando de todas formas"
  }

  step "Git — staging archivos de mesas"
  cd "$DATAPOL_DIR"
  git add \
    "peru/2026eg/segunda/data/results/peru_2026eg_mesa_segunda.csv" \
    "peru/2026eg/segunda/data/forecast.json" \
    "peru/2026eg/segunda/data/jee/jee_dept.geojson" \
    "peru/2026eg/segunda/data/jee/jee_provincia.geojson" \
    "peru/2026eg/segunda/data/jee/jee_distrito.geojson" \
    "peru/2026eg/segunda/data/jee/jee_national.json" 2>/dev/null || true

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  if git diff --cached --quiet; then
    warn "Sin cambios — nada que commitear."
  else
    git commit -m "data: mesas segunda vuelta — $TIMESTAMP"
    if $PUSH; then
      step "Git push"
      git push && echo -e "\n${GREEN}✔  Publicado — $TIMESTAMP${RESET}"
    else
      warn "(--no-push: omitiendo push)"
    fi
  fi
}

# ── Bucle principal ──────────────────────────────────────────────────────────────
if $LOOP; then
  while true; do
    run_once
    echo ""
    echo "  ⏱  Esperando ${SLEEP_SECS}s antes del próximo ciclo …"
    sleep "$SLEEP_SECS"
  done
else
  run_once
fi
