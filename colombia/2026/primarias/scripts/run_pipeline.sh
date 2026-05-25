#!/usr/bin/env bash
# run_pipeline.sh — Full primarias data pipeline
#
# Usage:
#   ./scripts/run_pipeline.sh          # full run
#   ./scripts/run_pipeline.sh --update # re-fetch only incomplete municipios
#
# Must be run from the primarias/ directory (or any location; paths are relative
# to this script's location).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

UPDATE_FLAG=""
if [[ "${1:-}" == "--update" ]]; then
  UPDATE_FLAG="--update"
  echo "==> Running in UPDATE mode (incomplete / errored municipios only)"
fi

echo ""
echo "==> 01 — Build candidate JSONs"
python3 01_build_candidate_jsons.py

echo ""
echo "==> 02 — Scrape municipio results"
python3 02_scrape_municipios.py $UPDATE_FLAG

echo ""
echo "==> 03 — Build GeoJSONs"
python3 03_build_geojson.py

echo ""
echo "==> 04 — Aggregate national stats"
python3 04_aggregate_stats.py

echo ""
echo "==> Git — commit and push"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
MODE_LABEL="${UPDATE_FLAG:+update}${UPDATE_FLAG:-full}"
git add \
  colombia/2026/primarias/data/results/ \
  colombia/2026/primarias/data/*.json \
  colombia/2026/primarias/data/*.geojson \
  2>/dev/null || true
if git diff --cached --quiet; then
  echo "  Nothing to commit — data unchanged."
else
  git commit -m "data: Primarias 2026 results ${MODE_LABEL} — ${TIMESTAMP}"
  git push
  echo "  Pushed to remote."
fi

echo ""
echo "Done."
