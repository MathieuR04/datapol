#!/usr/bin/env bash
# run_pipeline.sh — Primera Vuelta 2026 update pipeline
#
# Steps:
#   1. Update scrape — re-fetches incomplete/missing municipios and mesas only
#   2. Build GeoJSONs
#   3. Aggregate stats
#   4. Forecast
#   5. Git commit + push
#
# For a full rescrape run the scrapers manually first:
#   python3 scripts/02a_scrape_municipios.py
#   python3 scripts/02b_scrape_mesas.py
#
# Usage:
#   ./scripts/run_pipeline.sh            # update + push
#   ./scripts/run_pipeline.sh --no-push  # skip git push
#
# Run from anywhere — script resolves its own directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PUSH=true

for arg in "$@"; do
  [[ "$arg" == "--no-push" ]] && PUSH=false
done

echo "════════════════════════════════════════"
echo " Primera Vuelta 2026 — Update Pipeline"
echo "════════════════════════════════════════"

# ── 1. Scrape update ──────────────────────────────────────────────────────────
echo ""
echo "▶ Step 1/5 — Scrape update (incomplete municipios)"
python3 "$SCRIPT_DIR/02a_scrape_municipios.py" --update

echo ""
echo "▶ Step 2/5 — Scrape update (uncounted mesas)"
python3 "$SCRIPT_DIR/02b_scrape_mesas.py" --update

# ── 2. Build GeoJSONs ─────────────────────────────────────────────────────────
echo ""
echo "▶ Step 3/5 — Build GeoJSONs"
python3 "$SCRIPT_DIR/03_build_geojson.py"

# ── 3. Aggregate stats ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 4/5 — Aggregate stats"
python3 "$SCRIPT_DIR/04_aggregate_stats.py"

# ── 4. Forecast ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Step 5/5 — Forecast"
python3 "$SCRIPT_DIR/05_forecast.py"

# ── 5. Git commit + push ──────────────────────────────────────────────────────
echo ""
echo "▶ Git — staging data + frontend files"

git -C "$REPO_ROOT" add \
  "colombia/2026/primera/data/results/" \
  "colombia/2026/primera/data/candidates.json" \
  "colombia/2026/primera/data/aggregate_stats.json" \
  "colombia/2026/primera/data/forecast.json" \
  "colombia/2026/primera/data/colombia_2026_municipio_primera.geojson" \
  "colombia/2026/primera/data/colombia_2026_dept_primera.geojson" \
  "web/colombia/presidencial2026/index.html"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
git -C "$REPO_ROOT" commit -m "data: Primera Vuelta 2026 results update — $TIMESTAMP" \
  --allow-empty

if $PUSH; then
  echo "▶ Pushing …"
  git -C "$REPO_ROOT" push
  echo "✓ Pushed"
else
  echo "  (--no-push: skipping git push)"
fi

echo ""
echo "════════════════════════════════════════"
echo " Done!"
echo "════════════════════════════════════════"
