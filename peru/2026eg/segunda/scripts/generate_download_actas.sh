#!/bin/bash
# generate_download_actas.sh — Peru 2026 EG Segunda Vuelta
# Generates a browser console script to download acta PDFs from ONPE.
#
# Usage:
#   bash scripts/generate_download_actas.sh            | pbcopy  # con descripcion_error (priority)
#   bash scripts/generate_download_actas.sh --blank    | pbcopy  # sin descripcion_error
#   bash scripts/generate_download_actas.sh --all      | pbcopy  # todas las actas E
#
# Then paste into browser console at:
#   https://resultadosegundavuelta.onpe.gob.pe/main/actas

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$SCRIPT_DIR/../data/results"
TEMPLATE="$SCRIPT_DIR/download_actas_template.js"
CSV="$RESULTS_DIR/actas_jee.csv"

if [ ! -f "$CSV" ]; then
  echo "ERROR: $CSV not found. Run build_actas_jee.py first." >&2
  exit 1
fi

MODE="with_desc"
for arg in "$@"; do
  [[ "$arg" == "--blank" ]] && MODE="blank"
  [[ "$arg" == "--all"   ]] && MODE="all"
done

IDS=$(python3 -c "
import csv, sys

mode = '$MODE'
rows = []
with open('$CSV') as f:
    for row in csv.DictReader(f):
        desc = row.get('descripcion_error', '').strip()
        if   mode == 'with_desc' and desc:     rows.append(row['codigo_mesa'])
        elif mode == 'blank'     and not desc: rows.append(row['codigo_mesa'])
        elif mode == 'all':                    rows.append(row['codigo_mesa'])

label = {
    'with_desc': 'con descripcion_error',
    'blank':     'sin descripcion_error',
    'all':       'todas las actas E',
}[mode]
print('[\"' + '\",\"'.join(rows) + '\"]')
print(f'{label}: {len(rows)} mesas', file=sys.stderr)
")

JS_IDS=$(echo "$IDS" | head -1)
echo "$IDS" | tail -1 >&2

sed "s|__MESA_IDS__|$JS_IDS|g" "$TEMPLATE"
