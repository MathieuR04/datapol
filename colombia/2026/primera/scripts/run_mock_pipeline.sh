#!/usr/bin/env bash
# run_mock_pipeline.sh — Generate mock primera vuelta 2026 results and rebuild outputs
#
# Steps:
#   1. Generate mock municipio + mesa CSVs (all zeros)
#   2. Build GeoJSONs
#   3. Aggregate stats
#   4. Forecast (empty state)
#   5. Git commit  (no push — mock data stays local unless you push manually)
#
# Usage:
#   ./scripts/run_mock_pipeline.sh              # all-zero empty CSVs
#   ./scripts/run_mock_pipeline.sh --no-commit  # skip git commit
#
# Run from anywhere — script resolves its own directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

# ── Argument parsing ──────────────────────────────────────────────────────────
COMMIT=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-commit)
      COMMIT=false
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--no-commit]" >&2
      exit 1
      ;;
  esac
done

# ── Banner ────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════"
echo " Primera Vuelta 2026 — Mock Pipeline"
echo " Mode: empty (all zeros)"
echo "════════════════════════════════════════"

# ── 1. Generate mock CSVs ─────────────────────────────────────────────────────
echo ""
echo "▶ Step 1/4 — Generate mock municipio + mesa CSVs"
python3 "$SCRIPT_DIR/00_mock_results.py" --overwrite

# ── 2. Build GeoJSONs ─────────────────────────────────────────────────────────
echo ""
echo "▶ Step 2/4 — Build GeoJSONs"
python3 "$SCRIPT_DIR/03_build_geojson.py"

# ── 3. Aggregate stats ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 3/4 — Aggregate stats"
python3 "$SCRIPT_DIR/04_aggregate_stats.py"

# ── 4. Forecast ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Step 4/4 — Forecast (empty state)"
python3 "$SCRIPT_DIR/05_forecast.py"

# ── 5. Git commit ─────────────────────────────────────────────────────────────
if $COMMIT; then
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

  git -C "$REPO_ROOT" commit -m "mock: Primera Vuelta 2026 empty pre-election state" \
    --allow-empty
  echo "✓ Committed (not pushed — run 'git push' manually when ready)"
else
  echo ""
  echo "  (--no-commit: skipping git commit)"
fi

echo ""
echo "════════════════════════════════════════"
echo " Done!"
echo "════════════════════════════════════════"
