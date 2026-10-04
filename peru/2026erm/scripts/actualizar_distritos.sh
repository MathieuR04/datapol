#!/usr/bin/env bash
# actualizar_distritos.sh — ERM 2026
# Pipeline DISTRITAL de noche electoral (flujo A, ALTA PRIORIDAD: alimenta mapas,
# resultados, participación y avance).
#
# Ciclo: scrape_agregado → publica_resultados → git commit + push
#
# Uso:
#   bash peru/2026erm/scripts/actualizar_distritos.sh --host https://... --recurso RUTA
#   bash peru/2026erm/scripts/actualizar_distritos.sh --host ... --recurso ... --once --no-push
#   bash peru/2026erm/scripts/actualizar_distritos.sh --host ... --recurso ... --sleep 60
#
# --host y --recurso también se pueden dar por entorno: ONPE_HOST, ONPE_RECURSO.
# Mismas convenciones que peru/2026eg/segunda/scripts/actualizar_distritos.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERM_DIR="$(dirname "$SCRIPT_DIR")"                    # …/datapol/peru/2026erm
DATAPOL_DIR="$(dirname "$(dirname "$ERM_DIR")")"      # …/datapol

PUSH=true
LOOP=true
SLEEP_SECS=90
HOST="${ONPE_HOST:-}"
RECURSO="${ONPE_RECURSO:-}"
WORKERS=10

i=1
while [[ $i -le $# ]]; do
  arg="${!i}"
  case "$arg" in
    --no-push) PUSH=false ;;
    --once)    LOOP=false ;;
    --sleep)   i=$((i+1)); SLEEP_SECS="${!i}" ;;
    --host)    i=$((i+1)); HOST="${!i}" ;;
    --recurso) i=$((i+1)); RECURSO="${!i}" ;;
    --workers) i=$((i+1)); WORKERS="${!i}" ;;
  esac
  i=$((i+1))
done

if [[ -z "$HOST" || -z "$RECURSO" ]]; then
  echo "Falta --host o --recurso (o ONPE_HOST / ONPE_RECURSO)." >&2
  exit 2
fi

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RESET="\033[0m"
step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }

source "$SCRIPT_DIR/_publica.sh"

run_once() {
  echo ""
  echo "══════════════════════════════════════════════════════════"
  echo " Distritos ERM 2026 — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  step "Flujo A — totales por carrera"
  (cd "$ERM_DIR" && uv run python scripts/02a_scrape_distritos.py \
      --host "$HOST" --recurso "$RECURSO" --workers "$WORKERS") || {
    warn "scrape_agregado falló — abortando ciclo"
    return
  }

  publica "distritos"
}

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
