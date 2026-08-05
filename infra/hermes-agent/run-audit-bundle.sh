#!/bin/sh
# Produce the full READ-ONLY report set the ads-analyst consumes, by running each
# allow-listed reader via the Inc-3 wrapper (run-ads-report.sh). Read-only; each
# reader is allow-list-enforced by run-ads-report.py. The reader set MATCHES the
# registry read_execute.allow (finalized in the Task-1 gate).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-claude_google_ads}"
READERS="account_overview audit_search_terms audit_analyze"   # Task-1 finalized (matches read_execute.allow)
echo "run-audit-bundle: producing report set for $PROJECT" >&2
for r in $READERS; do
  echo "  -> $r" >&2
  "$here/run-ads-report.sh" --project "$PROJECT" --report "$r"   # prints each report path
done
echo "run-audit-bundle: done" >&2
