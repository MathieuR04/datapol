#!/usr/bin/env bash
# run_pipeline.sh — Senado 2026 update pipeline
#
# Steps:
#   1. Update scrape (re-fetches incomplete/missing municipios only)
#   2. Build GeoJSONs
#   3. Seat allocation
#   4. Git commit + push
#
# For a full rescrape of all 1,189 municipios run 02a manually first:
#   python3 scripts/02a_scrape_municipios.py
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
echo " Senado 2026 — Update Pipeline"
echo "════════════════════════════════════════"

# ── 1. Update scrape ──────────────────────────────────────────────────────────
echo ""
echo "▶ Step 1/4 — Scrape update (incomplete municipios)"
python3 "$SCRIPT_DIR/02a_scrape_municipios.py" --update

# ── 2. Build GeoJSONs ─────────────────────────────────────────────────────────
echo ""
echo "▶ Step 2/4 — Build GeoJSONs"
python3 "$SCRIPT_DIR/03_build_geojson.py"

# ── 3. Aggregate stats ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 3/4 — Aggregate stats"
python3 "$SCRIPT_DIR/04_aggregate_stats.py"

# ── 4. Seat allocation ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 4/4 — Seat allocation"
python3 "$SCRIPT_DIR/05_seat_allocation.py"

# ── 5. Git commit + push ──────────────────────────────────────────────────────
echo ""
echo "▶ Git — staging data + frontend files"

git -C "$REPO_ROOT" add \
  "colombia/2026/senado/data/results/" \
  "colombia/2026/senado/data/national_parties.json" \
  "colombia/2026/senado/data/indigena_parties.json" \
  "colombia/2026/senado/data/aggregate_stats.json" \
  "colombia/2026/senado/data/senate_seats.json" \
  "colombia/2026/senado/data/colombia_2026_municipio_senado_nacional.geojson" \
  "colombia/2026/senado/data/colombia_2026_dept_senado_nacional.geojson" \
  "colombia/2026/senado/data/colombia_2026_municipio_senado_indigena.geojson" \
  "colombia/2026/senado/data/colombia_2026_dept_senado_indigena.geojson" \
  "web/colombia/congreso2026/index.html"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M')"
git -C "$REPO_ROOT" commit -m "data: Senado 2026 results update — $TIMESTAMP" \
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
