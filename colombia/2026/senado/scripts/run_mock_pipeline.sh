#!/usr/bin/env bash
# run_mock_pipeline.sh — Generate mock Senado 2026 results and rebuild outputs
#
# Steps:
#   1. Generate mock municipio CSVs (zero or random)
#   2. Build GeoJSONs
#   3. Seat allocation
#   4. Git commit  (no push — mock data stays local unless you push manually)
#
# Usage:
#   ./scripts/run_mock_pipeline.sh                # all-zero empty CSVs
#   ./scripts/run_mock_pipeline.sh --random 0.3   # ~30 % turnout, random votes
#   ./scripts/run_mock_pipeline.sh --random 0.5 --seed 7  # custom seed
#   ./scripts/run_mock_pipeline.sh --no-commit    # skip git commit
#
# Run from anywhere — script resolves its own directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

# ── Argument parsing ──────────────────────────────────────────────────────────
RANDOM_FRAC=""
SEED=""
COMMIT=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --random)
      shift
      if [[ $# -eq 0 || "$1" == --* ]]; then
        echo "ERROR: --random requires a fraction argument (e.g. --random 0.3)" >&2
        exit 1
      fi
      RANDOM_FRAC="$1"
      shift
      ;;
    --seed)
      shift
      SEED="$1"
      shift
      ;;
    --no-commit)
      COMMIT=false
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--random FRACTION] [--seed SEED] [--no-commit]" >&2
      exit 1
      ;;
  esac
done

# ── Banner ────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════"
echo " Senado 2026 — Mock Pipeline"
if [[ -n "$RANDOM_FRAC" ]]; then
  echo " Mode: random  (turnout ≈ ${RANDOM_FRAC})"
else
  echo " Mode: empty (all zeros)"
fi
echo "════════════════════════════════════════"

# ── 1. Generate mock CSVs ─────────────────────────────────────────────────────
echo ""
echo "▶ Step 1/4 — Generate mock municipio CSVs"

MOCK_ARGS="--overwrite"
if [[ -n "$RANDOM_FRAC" ]]; then
  MOCK_ARGS="$MOCK_ARGS --random $RANDOM_FRAC"
fi
if [[ -n "$SEED" ]]; then
  MOCK_ARGS="$MOCK_ARGS --seed $SEED"
fi

python3 "$SCRIPT_DIR/00_mock_results_municipio.py" $MOCK_ARGS

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

# ── 4. Git commit ─────────────────────────────────────────────────────────────
if $COMMIT; then
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

  if [[ -n "$RANDOM_FRAC" ]]; then
    MSG="mock: Senado 2026 random results (turnout ${RANDOM_FRAC})"
  else
    MSG="mock: Senado 2026 empty pre-election state"
  fi

  git -C "$REPO_ROOT" commit -m "$MSG" --allow-empty
  echo "✓ Committed (not pushed — run 'git push' manually when ready)"
else
  echo ""
  echo "  (--no-commit: skipping git commit)"
fi

echo ""
echo "════════════════════════════════════════"
echo " Done!"
echo "════════════════════════════════════════"
