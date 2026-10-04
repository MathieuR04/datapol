#!/usr/bin/env bash
# actualizar_mesas.sh — ERM 2026
# Pipeline por MESA de noche electoral (flujo B: proyección, desagregado por local).
#
# Ciclo: scrape_mesas (--update) → consolida → publica_resultados →
#        git commit + push
#
# El primer ciclo es el barrido completo (~15 min a 20 workers en EG 2026); los
# siguientes solo piden las mesas con alguna acta no contabilizada.
#
# Uso:
#   bash peru/2026erm/scripts/actualizar_mesas.sh --host https://...
#   bash peru/2026erm/scripts/actualizar_mesas.sh --host ... --once --no-push
#   bash peru/2026erm/scripts/actualizar_mesas.sh --host ... --limite 50 --once --no-push   # prueba
#
# --host también por entorno: ONPE_HOST.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERM_DIR="$(dirname "$SCRIPT_DIR")"                    # …/datapol/peru/2026erm
DATAPOL_DIR="$(dirname "$(dirname "$ERM_DIR")")"      # …/datapol

PUSH=true
LOOP=true
SLEEP_SECS=300
HOST="${ONPE_HOST:-}"
WORKERS=20
LIMITE=""

i=1
while [[ $i -le $# ]]; do
  arg="${!i}"
  case "$arg" in
    --no-push) PUSH=false ;;
    --once)    LOOP=false ;;
    --sleep)   i=$((i+1)); SLEEP_SECS="${!i}" ;;
    --host)    i=$((i+1)); HOST="${!i}" ;;
    --workers) i=$((i+1)); WORKERS="${!i}" ;;
    --limite)  i=$((i+1)); LIMITE="--limite ${!i}" ;;
  esac
  i=$((i+1))
done

if [[ -z "$HOST" ]]; then
  echo "Falta --host (o ONPE_HOST)." >&2
  exit 2
fi

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RESET="\033[0m"
step() { echo -e "\n${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }

source "$SCRIPT_DIR/_publica.sh"

run_once() {
  echo ""
  echo "══════════════════════════════════════════════════════════"
  echo " Mesas ERM 2026 — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  step "Flujo B — actas por mesa (--update)"
  # --update: las nuevas y las pendientes. Las resueltas nunca se repiden.
  # shellcheck disable=SC2086
  (cd "$ERM_DIR" && uv run python scripts/02b_scrape_mesas.py \
      --host "$HOST" --workers "$WORKERS" --update $LIMITE) || {
    warn "scrape_mesas falló — abortando ciclo"
    return
  }

  step "Consolida — último estado de cada acta"
  (cd "$ERM_DIR" && uv run python scripts/03_consolida_mesas.py)
  rc=$?
  if [[ $rc -eq 2 ]]; then
    warn "Falta data/reference/id_eleccion.csv — ver docs/id_eleccion_descubrimiento.md"
    return
  elif [[ $rc -ne 0 ]]; then
    warn "consolida falló — abortando ciclo"
    return
  fi

  publica "mesas"
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
