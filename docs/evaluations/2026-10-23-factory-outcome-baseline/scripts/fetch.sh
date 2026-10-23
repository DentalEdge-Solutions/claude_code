#!/usr/bin/env bash
# P1-01 B0 outcome baseline: fetch PR data (read-only GitHub GETs only).
# Usage: fetch.sh <repo-dir> <data-dir>
# Run on 2026-10-23 against DentalEdge-Solutions/claude_code; HEAD was cbb6d4e04dc22f72c274e7b44c9740a8a2e2f165.
# PR bodies are live GitHub data: a later edit to a body changes the input. The fetched JSON is kept in <data-dir>.
set -euo pipefail
REPO_DIR="$1"; DATA="$2"
cd "$REPO_DIR"
mkdir -p "$DATA/pr-bodies"
gh pr list --state merged --limit 500 \
  --json number,title,mergedAt,createdAt,headRefName,mergeCommit,additions,deletions,changedFiles,author \
  > "$DATA/prs-merged-all.json"
for n in $(python3 -I -c "import json,sys;print(' '.join(str(p['number']) for p in json.load(open(sys.argv[1]))))" "$DATA/prs-merged-all.json"); do
  gh pr view "$n" --json number,title,body,mergedAt,createdAt,mergeCommit,additions,deletions,changedFiles,files,reviews,comments,commits,headRefName,baseRefName \
    > "$DATA/pr-bodies/$n.json"
done
