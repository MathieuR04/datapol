#!/usr/bin/env bash
# procesar_only.sh — Pulls fresh CSVs from git, then builds GeoJSONs, stats,
# forecast, comparison and JEE. Does NOT scrape ONPE.
# Use this on the primary Mac when the scraper runs on a second computer.
#
# Usage:
#   bash scripts/procesar_only.sh            # loop forever (90s between cycles)
#   bash scripts/procesar_only.sh --once     # single run
#   bash scripts/procesar_only.sh --no-push  # skip git push

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

LOOP=true
PUSH=true
SLEEP_SECS=90

for arg in "$@"; do
  [[ "$arg" == "--once"    ]] && LOOP=false
  [[ "$arg" == "--no-push" ]] && PUSH=false
done

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RESET="\033[0m"
step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }

run_once() {
  echo ""
  echo "══════════════════════════════════════════════════════════"
  echo " Procesar pipeline — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  step "git pull — fetching latest CSVs from scraper"
  git -C "$REPO_ROOT" stash --quiet 2>/dev/null || true
  git -C "$REPO_ROOT" pull --rebase --quiet || warn "pull falló — usando datos locales"
  git -C "$REPO_ROOT" stash pop --quiet 2>/dev/null || true

  step "03 — Build GeoJSONs"
  python3 "$SCRIPT_DIR/03_build_geojson.py" || {
    warn "03 falló — abortando ciclo"
    return
  }

  step "04 — Aggregate stats"
  python3 "$SCRIPT_DIR/04_aggregate_stats.py" || {
    warn "04 falló — abortando ciclo"
    return
  }

  step "05 — Forecast"
  python3 "$SCRIPT_DIR/05_forecast.py" || warn "05 falló — continuando"

  step "06 — Comparison GeoJSONs"
  python3 "$SCRIPT_DIR/06_build_comparison.py" || warn "06 falló — continuando"

  step "07 — JEE GeoJSONs"
  python3 "$SCRIPT_DIR/07_build_jee.py" || warn "07 falló — continuando"

  step "08 — Analisis"
  python3 "$SCRIPT_DIR/08_build_analisis.py" || warn "08 falló — continuando"

  step "git — staging outputs"
  cd "$REPO_ROOT"
  git add \
    "peru/2026eg/segunda/data/peru_2026eg_distrito_segunda.geojson" \
    "peru/2026eg/segunda/data/peru_2026eg_provincia_segunda.geojson" \
    "peru/2026eg/segunda/data/peru_2026eg_departamento_segunda.geojson" \
    "peru/2026eg/segunda/data/aggregate_stats.json" \
    "peru/2026eg/segunda/data/forecast.json" \
    "peru/2026eg/segunda/data/forecast_national.json" \
    "peru/2026eg/segunda/data/forecast_exterior.json" \
    "peru/2026eg/segunda/data/comparison/peru_2026_segunda_distrito_comparison.geojson" \
    "peru/2026eg/segunda/data/comparison/peru_2026_segunda_provincia_comparison.geojson" \
    "peru/2026eg/segunda/data/comparison/peru_2026_segunda_departamento_comparison.geojson" \
    "peru/2026eg/segunda/data/jee/jee_dept.geojson" \
    "peru/2026eg/segunda/data/jee/jee_provincia.geojson" \
    "peru/2026eg/segunda/data/jee/jee_distrito.geojson" \
    "peru/2026eg/segunda/data/jee/jee_national.json" \
    "peru/2026eg/segunda/data/analisis/analisis_data.json" 2>/dev/null || true

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  if git diff --cached --quiet; then
    warn "Sin cambios — nada que commitear."
  else
    git commit -m "data: procesar segunda vuelta — $TIMESTAMP"
    if $PUSH; then
      step "git push"
      for attempt in 1 2 3; do
        git push && echo -e "\n${GREEN}✔  Publicado — $TIMESTAMP${RESET}" && break
        warn "Push falló (intento $attempt/3) — reintentando en 10s…"
        sleep 10
        git pull --rebase --quiet
      done
    else
      warn "(--no-push: omitiendo push)"
    fi
  fi
}

if $LOOP; then
  while true; do
    run_once
    echo ""
    echo "  ⏱  Esperando ${SLEEP_SECS}s antes del próximo ciclo…"
    sleep "$SLEEP_SECS"
  done
else
  run_once
fi
