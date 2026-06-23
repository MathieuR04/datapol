#!/usr/bin/env bash
# Refresh the World Cup forecast end to end:
#   1. pull the latest groups/standings/results from Wikipedia
#   2. parse them into tournament.json
#   3. fetch live per-match betting odds (ESPN/DraftKings) -> match_odds.json
#   4. (optional) snapshot Polymarket aggregate markets for the sanity panel
#   5. run the Monte Carlo -> forecast.json
#
# Usage:  bash scripts/build.sh [n_sims]
set -euo pipefail
cd "$(dirname "$0")/.."
N="${1:-40000}"

echo "==> [1/5] downloading Wikipedia source"
curl -s --max-time 60 "https://en.wikipedia.org/api/rest_v1/page/html/2026_FIFA_World_Cup" -o data/source_wikipedia.html
echo "    $(wc -c < data/source_wikipedia.html) bytes"

echo "==> [2/5] parsing tournament structure"
python3 scripts/parse_data.py

echo "==> [3/5] fetching per-match betting odds"
python3 scripts/fetch_match_odds.py

echo "==> [4/5] snapshotting Polymarket (sanity only)"
python3 scripts/fetch_odds.py || echo "    (polymarket snapshot failed; continuing)"

echo "==> [5/5] running simulation (n=$N)"
python3 scripts/simulate.py "$N"

echo "==> done. forecast.json updated."
