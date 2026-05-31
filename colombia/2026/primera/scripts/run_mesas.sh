#!/usr/bin/env bash
# run_mesas.sh — Pipeline 2 (FORECAST): scrape mesas → forecast → push
#
# Runs in a continuous loop with a 3-minute pause between cycles.
# Each cycle: 02b --update → 05 → git commit + push
#
# This is the LOWER-PRIORITY pipeline — drives the forecast display.
# Start after run_municipios.sh is running. Run in a separate terminal window.
# Note: each 02b --update pass may take several minutes (126k mesas).
#
# Usage:
#   ./scripts/run_mesas.sh            # loop forever
#   ./scripts/run_mesas.sh --no-push  # skip git push (useful for testing)
#   ./scripts/run_mesas.sh --once     # single run, no loop

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
  echo " Mesas pipeline — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "══════════════════════════════════════════════════"

  echo "▶ 02b — scrape mesas (update)"
  python3 "$SCRIPT_DIR/02b_scrape_mesas.py" --update || {
    echo "  ⚠  02b exited with error — continuing anyway"
  }

  echo "▶ 05 — forecast"
  python3 "$SCRIPT_DIR/05_forecast.py" || {
    echo "  ⚠  05 exited with error — skipping commit"
    return
  }

  echo "▶ git — staging mesa data + forecast"
  git -C "$REPO_ROOT" add \
    "colombia/2026/primera/data/results/colombia_2026_mesa_primera.csv" \
    "colombia/2026/primera/data/forecast.json"

  TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
  git -C "$REPO_ROOT" commit \
    -m "data: mesas + forecast primera vuelta — $TIMESTAMP" \
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
