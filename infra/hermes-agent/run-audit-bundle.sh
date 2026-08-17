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
# --customer is REQUIRED. .env.ga no longer pins GOOGLE_ADS_CUSTOMER_ID, so omitting
# it would fail once per reader inside run-ads-report.py with a "missing injected
# credential vars" message that reads like a broken credential rather than a missing
# argument. Refuse up front with the actual cause.
if [ -z "$CUSTOMER" ]; then
  echo "run-audit-bundle: --customer <digits> is required (.env.ga pins no default" >&2
  echo "  account by design). Resolve it from the client vault rather than hardcoding:" >&2
  echo "  run-trend-audit.sh --client <slug> does this for you." >&2
  exit 1
fi

READERS="account_overview audit_search_terms audit_analyze"   # Task-1 finalized (matches read_execute.allow)
echo "run-audit-bundle: producing report set for $PROJECT" >&2
for r in $READERS; do
  echo "  -> $r" >&2
  "$here/run-ads-report.sh" --project "$PROJECT" --report "$r" --customer "$CUSTOMER"
done
echo "run-audit-bundle: done" >&2
