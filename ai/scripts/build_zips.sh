#!/usr/bin/env bash
# Build the Marcaj upload ZIPs (and every other deliverable) from the challenge tiles.
#
#   scripts/build_zips.sh            # full run: model inference + whole-map unification (~3 min)
#   scripts/build_zips.sh --fast     # reuse cached canopies (exports/cache/canopies.json), skip the model (~1 min)
#
# Any other arguments are passed through to generate_from_file1.py.
#
# Writes:
#   exports/zips/siret3_challenge_tiles_part{1..5}of5.zip   upload these to Marcaj, one by one
#   exports/parts/*.xml, annotations_challenge.xml          CVAT 1.1 XML
#   exports/unified/*.geojson                               whole-map layers for the web app
#   measurements.csv, route.geojson                         submission files
set -euo pipefail

cd "$(dirname "$0")/.."

PY=.venv/bin/python
[ -x "$PY" ] || { echo "Missing $PY - create the venv first (see README section 2)." >&2; exit 1; }
[ -f weights/best.pt ] || { echo "Missing weights/best.pt." >&2; exit 1; }

EXTRA=()
for arg in "$@"; do
  if [ "$arg" = "--fast" ]; then
    if [ -f exports/cache/canopies.json ]; then
      EXTRA+=(--reuse-cache)
    else
      echo "No canopy cache yet - running the full inference instead." >&2
    fi
  else
    EXTRA+=("$arg")
  fi
done

mkdir -p exports
LOG=exports/generate_$(date +%Y%m%d_%H%M%S).log

"$PY" scripts/generate_from_file1.py \
  --file1 file1.txt \
  --weights weights/best.pt \
  --output annotations_challenge.xml \
  --output-parts-dir exports/parts \
  --create-zips \
  ${EXTRA[@]+"${EXTRA[@]}"} 2>&1 | tee "$LOG"

# The generator prints a validation verdict; stop if it did not pass
grep -q "Validation Status:        PASSED" "$LOG" || { echo "Validation did not pass - see $LOG" >&2; exit 1; }

echo
echo "ZIPs ready for Marcaj (upload all five before publishing):"
ls -lh exports/zips/*.zip
echo "Log: $LOG"
