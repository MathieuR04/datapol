#!/usr/bin/env bash
# actualizar_distritos.sh — Peru 2026 EG Segunda Vuelta
# Pipeline DISTRITAL de noche electoral (ALTA PRIORIDAD — alimenta el mapa).
#
# Ciclo: 02a --update → 03 → 04 → 06 → 08 → git commit + push
#
# Uso:
#   bash scripts/actualizar_distritos.sh            # loop continuo (default 120s)
#   bash scripts/actualizar_distritos.sh --no-push  # sin git push (testing)
#   bash scripts/actualizar_distritos.sh --once     # ejecutar una sola vez
#   bash scripts/actualizar_distritos.sh --sleep 60 # intervalo personalizado
#
# Requiere: curl_cffi, geopandas, pandas

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEGUNDA_DIR="$(dirname "$SCRIPT_DIR")"
DATAPOL_DIR="$(dirname "$(dirname "$(dirname "$SEGUNDA_DIR")")")"

PUSH=true
LOOP=true
SLEEP_SECS=120

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
  echo " Distritos pipeline — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  step "02a — Scrape ONPE distritos (--update)"
  python3 "$SCRIPT_DIR/02a_scrape_distritos.py" --update || {
    warn "02a falló — abortando ciclo"
    return
  }

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

  step "06 — Comparison GeoJSONs"
  python3 "$SCRIPT_DIR/06_build_comparison.py" || {
    warn "06 falló — continuando de todas formas"
  }

  step "08 — Analisis scatter-plot"
  python3 "$SCRIPT_DIR/08_build_analisis.py" || {
    warn "08 falló — continuando de todas formas"
  }

  step "Git — staging archivos distritales"
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
    "peru/2026eg/segunda/data/analisis/analisis_data.json" 2>/dev/null || true

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  if git diff --cached --quiet; then
    warn "Sin cambios — nada que commitear."
  else
    git commit -m "data: distritos segunda vuelta — $TIMESTAMP"
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
