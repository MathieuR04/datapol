#!/usr/bin/env bash
# run_municipios.sh — Pipeline 1 (MAPA): scrape municipios → GeoJSON → stats → push
#
# Runs in a continuous loop with a 3-minute pause between cycles.
# Each cycle: 02a --update → 03 → 04 → git commit + push
#
# This is the HIGH-PRIORITY pipeline — drives the map visualization.
# Start this first. Run in a dedicated terminal window.
#
# Usage:
#   ./scripts/run_municipios.sh            # loop forever
#   ./scripts/run_municipios.sh --no-push  # skip git push (useful for testing)
#   ./scripts/run_municipios.sh --once     # single run, no loop

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PUSH=true
LOOP=true
SLEEP_SECS=180

for arg in "$@"; do
  [[ "$arg" == "--no-push" ]] && PUSH=false
  [[ "$arg" == "--once"    ]] && LOOP=false
done

run_once() {
  echo ""
  echo "══════════════════════════════════════════════════"
  echo " Municipios pipeline — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════"

  echo "▶ 02a — scrape municipios (update, curl fallback)"
  python3 "$SCRIPT_DIR/02a_scrape_municipios_curl.py" --update || {
    echo "  ⚠  02a exited with error — continuing anyway"
  }

  echo "▶ 03 — build GeoJSONs"
  python3 "$SCRIPT_DIR/03_build_geojson.py" || {
    echo "  ⚠  03 exited with error — skipping commit"
    return
  }

  echo "▶ 04 — aggregate stats"
  python3 "$SCRIPT_DIR/04_aggregate_stats.py" || {
    echo "  ⚠  04 exited with error — skipping commit"
    return
  }

  echo "▶ 05 — forecast (municipio projection)"
  python3 "$SCRIPT_DIR/05_forecast.py" || {
    echo "  ⚠  05 exited with error — continuing anyway"
  }

  echo "▶ 06 — build comparison GeoJSONs"
  python3 "$SCRIPT_DIR/06_build_comparison.py" || {
    echo "  ⚠  06 exited with error — continuing anyway"
  }

  echo "▶ git — staging municipio data"
  git -C "$REPO_ROOT" add \
    "colombia/2026/primera/data/results/colombia_2026_municipio_primera.csv" \
    "colombia/2026/primera/data/aggregate_stats.json" \
    "colombia/2026/primera/data/forecast.json" \
    "colombia/2026/primera/data/colombia_2026_municipio_primera.geojson" \
    "colombia/2026/primera/data/colombia_2026_dept_primera.geojson" \
    "colombia/2026/primera/data/comparison/colombia_2026_primera_municipio_comparison.geojson" \
    "colombia/2026/primera/data/comparison/colombia_2026_primera_departamento_comparison.geojson"

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  git -C "$REPO_ROOT" commit \
    -m "data: municipios primera vuelta — $TIMESTAMP" \
    --allow-empty

  if $PUSH; then
    echo "▶ push"
    git -C "$REPO_ROOT" push && echo "  ✓ pushed"
  else
    echo "  (--no-push: skipping)"
  fi
}

if $LOOP; then
  while true; do
    run_once
    echo ""
    echo "  ⏱  Waiting ${SLEEP_SECS}s before next cycle …"
    sleep "$SLEEP_SECS"
  done
else
  run_once
fi
