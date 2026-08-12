#!/bin/sh
# Produce the full READ-ONLY report set the ads-analyst consumes, by running each
# allow-listed reader via the Inc-3 wrapper (run-ads-report.sh). Read-only; each
# reader is allow-list-enforced by run-ads-report.py. The reader set MATCHES the
# registry read_execute.allow (finalized in the Task-1 gate).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1-claude_google_ads}"; shift 2>/dev/null || true
CUSTOMER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --customer)
      [ $# -ge 2 ] || { echo "run-audit-bundle: --customer requires a value" >&2; exit 1; }
      CUSTOMER="$2"
      case "$CUSTOMER" in *[!0-9]*|'') echo "run-audit-bundle: invalid --customer (digits only)" >&2; exit 1 ;; esac
      shift 2
      ;;
    *) echo "run-audit-bundle: unknown arg: $1" >&2; exit 1 ;;
  esac
done
READERS="account_overview audit_search_terms audit_analyze"   # Task-1 finalized (matches read_execute.allow)
echo "run-audit-bundle: producing report set for $PROJECT" >&2
for r in $READERS; do
  echo "  -> $r" >&2
  if [ -n "$CUSTOMER" ]; then
    "$here/run-ads-report.sh" --project "$PROJECT" --report "$r" --customer "$CUSTOMER"
  else
    "$here/run-ads-report.sh" --project "$PROJECT" --report "$r"   # prints each report path
  fi
done
echo "run-audit-bundle: done" >&2
