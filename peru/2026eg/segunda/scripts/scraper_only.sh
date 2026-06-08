#!/usr/bin/env bash
# scraper_only.sh — Runs ONLY the scrapers + pushes raw CSVs to git.
# Run this on the second computer. The main pipeline runs on the primary Mac.
#
# Usage:
#   bash scraper_only.sh            # loop forever (120s between cycles)
#   bash scraper_only.sh --once     # single run
#   bash scraper_only.sh --no-push  # don't push (for testing)
#   bash scraper_only.sh --distritos-only  # skip mesa scraper
#   bash scraper_only.sh --mesas-only      # skip district scraper

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
SEGUNDA_DIR="$SCRIPT_DIR/.."
DATA_DIR="$SEGUNDA_DIR/data"

LOOP=true
PUSH=true
DO_DIST=true
DO_MESA=true
SLEEP_SECS=120
WORKERS=10

for arg in "$@"; do
  [[ "$arg" == "--once"           ]] && LOOP=false
  [[ "$arg" == "--no-push"        ]] && PUSH=false
  [[ "$arg" == "--distritos-only" ]] && DO_MESA=false
  [[ "$arg" == "--mesas-only"     ]] && DO_DIST=false
done

# ── Check deps ──────────────────────────────────────────────────────────────────
python3 -c "import curl_cffi" 2>/dev/null || {
  echo "Installing curl_cffi…"
  pip3 install curl_cffi --quiet
}

# ── One cycle ────────────────────────────────────────────────────────────────────
run_once() {
  echo ""
  echo "══════════════════════════════════════════════════════"
  echo " Scraper — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════════"

  # Pull latest before scraping so we don't overwrite newer data
  echo "▶ git pull"
  git -C "$REPO_ROOT" pull --rebase --quiet || echo "  ⚠ pull failed — continuing"

  if $DO_DIST; then
    echo "▶ 02a — Scrape distritos (--update)"
    python3 "$SCRIPT_DIR/02a_scrape_distritos.py" --update || {
      echo "  ⚠ 02a falló — skipping commit"
      return
    }
  fi

  if $DO_MESA; then
    echo "▶ 02b — Scrape mesas (--update)"
    python3 "$SCRIPT_DIR/02b_scrape_mesas.py" --update --workers $WORKERS || {
      echo "  ⚠ 02b falló — continuando"
    }
  fi

  echo "▶ git — staging raw CSVs"
  git -C "$REPO_ROOT" add \
    "peru/2026eg/segunda/data/results/peru_2026eg_distrito_segunda.csv" \
    "peru/2026eg/segunda/data/results/peru_2026eg_mesa_segunda.csv"

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  if git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "  Sin cambios — nada que commitear."
  else
    git -C "$REPO_ROOT" commit -m "data: raw scrape segunda vuelta — $TIMESTAMP"
    if $PUSH; then
      for attempt in 1 2 3; do
        git -C "$REPO_ROOT" push && echo "  ✓ pushed — $TIMESTAMP" && break
        echo "  ⚠ push falló (intento $attempt/3) — reintentando en 10s…"
        sleep 10
        git -C "$REPO_ROOT" pull --rebase --quiet
      done
    else
      echo "  (--no-push: omitiendo push)"
    fi
  fi
}

if $LOOP; then
  while true; do
    run_once
    echo ""
    echo "  ⏱  Esperando ${SLEEP_SECS}s…"
    sleep "$SLEEP_SECS"
  done
else
  run_once
fi
