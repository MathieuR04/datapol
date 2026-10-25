#!/usr/bin/env bash
# actualizar.sh — pipeline completo de la 2da vuelta Brasil 2026.
#
#   1. baixar.py 6258   resultados por município del TSE (solo los que no están al 100%)
#   2. site.py          archivos de la página (mapas, comparaciones, pronóstico por seções) en data/site/
#   (+ secoes.py en paralelo: boletines de urna seção por seção, para el pronóstico)
#   3. git              commit de data/site y push a datapol (como máximo cada MIN_PUSH_S)
#
# Uso:
#   ./actualizar.sh            ciclo continuo (cada CICLO_S segundos)
#   ./actualizar.sh --once     una sola pasada
#   ./actualizar.sh --no-push  sin commit/push
#
# Comparte el candado de publicación con el pipeline ERM 2026: los dos empujan al
# mismo repo y no deben tocar git a la vez.
set -u
cd "$(dirname "$0")" || exit 1
AQUI="$(pwd)"
DATAPOL_DIR="$(cd ../../.. && pwd)"
CICLO_S="${CICLO_S:-60}"
MIN_PUSH_S="${MIN_PUSH_S:-300}"   # GitHub Pages: ~10 despliegues/hora entre todos los pipelines
LOCK_DIR="${TMPDIR:-/tmp}/datapol-erm2026-publica.lock"
MARCA_PUSH="${TMPDIR:-/tmp}/datapol-brasil2026-ultimo-push"
RUTA="brasil/2026/segundo-turno/data/site"

ONCE=false; PUSH=true
for a in "$@"; do
  case "$a" in
    --once) ONCE=true ;;
    --no-push) PUSH=false ;;
  esac
done

publica() {
  local ahora ultimo ts
  ahora=$(date +%s); ultimo=$(cat "$MARCA_PUSH" 2>/dev/null || echo 0)
  if (( ahora - ultimo < MIN_PUSH_S )); then
    echo "  push en espera ($(( ahora - ultimo )) s desde el último, mínimo ${MIN_PUSH_S} s)"
    return
  fi
  if [[ -d "$LOCK_DIR" ]] && [[ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]]; then
    rmdir "$LOCK_DIR" 2>/dev/null
  fi
  for _ in $(seq 1 30); do mkdir "$LOCK_DIR" 2>/dev/null && break; sleep 4; done
  [[ -d "$LOCK_DIR" ]] || { echo "  sin candado de publicación — se omite este ciclo"; return; }
  (
    cd "$DATAPOL_DIR" || exit 1
    git add "$RUTA"
    if git diff --cached --quiet -- "$RUTA"; then echo "  sin cambios"; exit 0; fi
    ts="$(date '+%Y-%m-%d %H:%M')"
    git commit -q -m "data: Brasil 2da vuelta 2026 — $ts" -- "$RUTA"
    for intento in 1 2 3; do
      if git push -q; then date +%s > "$MARCA_PUSH"; echo "  ✔ publicado $ts"; break; fi
      echo "  push falló ($intento/3) — trayendo origin…"
      git pull --rebase --autostash -q || { git rebase --abort 2>/dev/null; echo "  conflicto — próximo ciclo"; break; }
      sleep 5
    done
  )
  rmdir "$LOCK_DIR" 2>/dev/null
}

# Urnas seção por seção (para el pronóstico): corre aparte, en paralelo, y se cierra
# junto con este script.
if ! pgrep -f "secoes.py --hilos" >/dev/null; then
  python3 -u secoes.py --hilos 48 --loop 20 >> data/secoes.log 2>&1 &
  PID_SECOES=$!
  trap 'kill $PID_SECOES 2>/dev/null' EXIT
fi

while true; do
  echo "── $(date '+%H:%M:%S')"
  python3 -u baixar.py 6258 --hilos "${HILOS:-32}"
  python3 -u site.py 2>&1 | grep -v -i warning
  $PUSH && publica
  $ONCE && break
  sleep "$CICLO_S"
done
