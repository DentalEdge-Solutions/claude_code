#!/usr/bin/env bash
# P1-01 B0 outcome baseline: full re-run.
# Usage: run.sh <repo-dir> <data-dir> [--refetch]
# Without --refetch it reuses the fetched PR JSON in <data-dir> (fetched 2026-10-23), so a re-run
# reproduces the numbers exactly; with --refetch it calls fetch.sh first (PR bodies may have changed).
# The three hand-coded inputs (review-coding-manual.csv, spec-plan-match-verification-manual.csv,
# fix-attribution-validation-manual.csv) must be present in <data-dir>.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$1"; DATA="$2"; SHA=cbb6d4e04dc22f72c274e7b44c9740a8a2e2f165
git -C "$REPO" cat-file -e "$SHA^{commit}"
if [ "${3:-}" = "--refetch" ]; then "$HERE/fetch.sh" "$REPO" "$DATA"; fi
python3 -I "$HERE/extract_review_text.py" "$DATA"
python3 -I "$HERE/measure.py" "$REPO" "$SHA" "$DATA" > "$DATA/measure-stdout.json"
python3 -I "$HERE/verify.py" "$DATA" > "$DATA/verify-stdout.txt"
echo "summary: $DATA/summary.json, $DATA/verify-summary.json"
