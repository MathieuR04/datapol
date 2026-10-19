#!/usr/bin/env bash
# actualizar_distritos.sh — ERM 2026
# EL pipeline de la noche (flujo A, de punta a punta). Flujo B —actas por mesa—
# queda fuera: ver OPERADOR.md.
#
# Ciclo: 02a scrape (carreras + distritos de carrera) → 04 emisor (cómputo,
#        proyección distrital, llamadas, electos) → 05 directorio de electos →
#        git commit + push (máximo uno cada 7 min) → espera → nuevo ciclo
#
# Cadencia: un ciclo cada --cada segundos, contados de inicio a inicio
# (por defecto 7200 = cada 2 horas; un ciclo dura ~35 min). En macOS el bucle
# se cubre solo con `caffeinate -i` mientras corre: el Mac no se duerme por
# inactividad, la pantalla sí se puede apagar. Tapa cerrada o sin corriente
# sí lo duermen.
#
# Uso:
#   bash peru/2026erm/scripts/actualizar_distritos.sh                 # bucle cada 2 h, publica
#   bash peru/2026erm/scripts/actualizar_distritos.sh --cada 3600     # cada hora
#   bash peru/2026erm/scripts/actualizar_distritos.sh --once --no-push
#   bash peru/2026erm/scripts/actualizar_distritos.sh --sin-desagregado   # solo carreras, más rápido
#
# --host y --recurso también se pueden dar por entorno: ONPE_HOST, ONPE_RECURSO.
# El endpoint de participantes de ERM 2026 se conoce y tiene un valor por defecto.
# Mismas convenciones que peru/2026eg/segunda/scripts/actualizar_distritos.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERM_DIR="$(dirname "$SCRIPT_DIR")"                    # …/datapol/peru/2026erm
DATAPOL_DIR="$(dirname "$(dirname "$ERM_DIR")")"      # …/datapol

PUSH=true
LOOP=true
CADA_S=7200
SLEEP_SECS=""
EXTRA=""
# Anunciado por la ONPE para ERM 2026 (El Comercio, Infobae, 4 oct.).
HOST="${ONPE_HOST:-https://resultadoelectoral.onpe.gob.pe}"
RECURSO="${ONPE_RECURSO:-resumen-general/participantes}"
WORKERS=10

i=1
while [[ $i -le $# ]]; do
  arg="${!i}"
  case "$arg" in
    --no-push) PUSH=false ;;
    --sin-desagregado) EXTRA="$EXTRA --sin-desagregado" ;;
    --once)    LOOP=false ;;
    --cada)    i=$((i+1)); CADA_S="${!i}" ;;
    --sleep)   i=$((i+1)); SLEEP_SECS="${!i}" ;;   # pausa fija tras cada ciclo (anula --cada)
    --host)    i=$((i+1)); HOST="${!i}" ;;
    --recurso) i=$((i+1)); RECURSO="${!i}" ;;
    --workers) i=$((i+1)); WORKERS="${!i}" ;;
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
  echo " Distritos ERM 2026 — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════════"

  # Dos pasadas por ciclo: las 2,118 carreras (~10 min) y se publica; luego
  # los ~5,580 distritos de carrera (~25 min) y se vuelve a publicar. Así el
  # cómputo del sitio no espera al barrido distrital.
  step "Flujo A — 1/2 totales por carrera"
  (cd "$ERM_DIR" && uv run python scripts/02a_scrape_distritos.py \
      --host "$HOST" --recurso "$RECURSO" --workers "$WORKERS" --sin-desagregado)
  rc=$?
  if [[ $rc -eq 3 ]]; then
    # Lo que bajó antes del challenge ya está en disco: se publica y se para.
    warn "La ONPE responde con el desafío anti-bot (WAF). Se publica lo ya bajado y se detiene: no se insiste."
    publica "carreras"
    exit 3
  elif [[ $rc -ne 0 ]]; then
    warn "scrape falló sin una sola respuesta útil — se publica el último estado en disco"
  fi
  publica "carreras"

  if [[ "$EXTRA" == *--sin-desagregado* ]]; then
    return
  fi
  step "Flujo A — 2/2 totales por distrito de carrera"
  (cd "$ERM_DIR" && uv run python scripts/02a_scrape_distritos.py \
      --host "$HOST" --recurso "$RECURSO" --workers "$WORKERS" --solo-distritos)
  rc=$?
  if [[ $rc -eq 3 ]]; then
    warn "La ONPE responde con el desafío anti-bot (WAF). Se publica lo ya bajado y se detiene: no se insiste."
    MIN_PUSH_S=0 publica "distritos"     # se detiene: no habrá próximo ciclo
    exit 3
  fi
  # Con --once no hay próximo ciclo que lleve lo que el límite de 7 min deje en
  # disco (18 oct.: la pasada de distritos quedó sin subir y el sitio mostraba
  # la proyección con distritos viejos).
  if $LOOP; then
    publica "distritos"
  else
    MIN_PUSH_S=0 publica "distritos"
  fi
}

if $LOOP; then
  # Que el Mac no se duerma mientras dure el bucle; muere con este proceso.
  if command -v caffeinate >/dev/null; then
    caffeinate -i -w $$ &
  fi
  while true; do
    inicio=$(date +%s)
    run_once
    if [[ -n "$SLEEP_SECS" ]]; then
      espera=$SLEEP_SECS
    else
      espera=$(( CADA_S - ($(date +%s) - inicio) ))
      (( espera < 60 )) && espera=60
    fi
    echo ""
    echo "  ⏱  Próximo ciclo a las $(date -r $(( $(date +%s) + espera )) '+%H:%M') (en $(( espera / 60 )) min) …"
    sleep "$espera"
  done
else
  run_once
fi
