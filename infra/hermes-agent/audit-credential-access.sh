#!/bin/sh
# Measure what a Google Ads credential can ACTUALLY do, and compare it to what it
# is declared to do. Credential-scoped, not project-scoped: it takes a credential
# file and asks Google about that credential, so it works unchanged for whatever
# project replaces claude-google-ads and for every project after that.
#
# Structurally non-mutating: the mutate probe is validate_only, hardcoded in
# bin/audit-credential-access.py with no flag to disable it.
#
# Usage:
#   ./audit-credential-access.sh --cred .env.ga
#   ./audit-credential-access.sh --cred .env.gaw --customer <digits>
#   ./audit-credential-access.sh --all
#
# --customer overrides the customer id for this run WITHOUT editing the file,
# so a credential pinned to one account can be measured against an authorised
# one. Exit 3 = declared role and measured access level disagree.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"

CRED=""; CUSTOMER=""; ALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cred)     CRED="${2:?--cred needs a value}"; shift 2 ;;
    --customer) CUSTOMER="${2:?--customer needs a value}"; shift 2 ;;
    --all)      ALL=1; shift ;;
    *) echo "audit-credential-access: unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Every GOOGLE_ADS_* var this tool injects. Cleared before each credential is parsed.
CRED_VARS="GOOGLE_ADS_DEVELOPER_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET
GOOGLE_ADS_REFRESH_TOKEN GOOGLE_ADS_LOGIN_CUSTOMER_ID GOOGLE_ADS_CUSTOMER_ID
GOOGLE_ADS_CREDENTIAL_ROLE"

audit_one() {
  _cred="$1"

  # Clear ALL of them first. export persists across calls in the same shell, so in
  # --all mode a key present in one credential file and absent from the next would be
  # silently inherited — and the tool would confidently report on a credential that
  # does not exist. That is live, not theoretical: .env.ga no longer pins
  # GOOGLE_ADS_CUSTOMER_ID while .env.gaw does, so a different loop order would have
  # audited the read credential against the write credential's target account.
  for _v in $CRED_VARS; do
    unset "$_v" 2>/dev/null || true
  done
  if [ ! -f "$here/$_cred" ]; then
    echo "audit-credential-access: $here/$_cred not found" >&2
    return 1
  fi
  case "$_cred" in
    */*) echo "audit-credential-access: --cred must be a bare filename" >&2; return 1 ;;
  esac

  # Parse as DATA (never source): split on the first '=', assign literally, so
  # shell metacharacters inside a credential value stay inert.
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      ''|'#'*) continue ;;
      GOOGLE_ADS_*=*) : ;;
      *) continue ;;
    esac
    _key=${_line%%=*}
    _val=${_line#*=}
    case "$_val" in
      \"*\") _val=${_val#\"}; _val=${_val%\"} ;;
      \'*\') _val=${_val#\'}; _val=${_val%\'} ;;
    esac
    export "$_key=$_val"
  done < "$here/$_cred"

  if [ -n "$CUSTOMER" ]; then
    case "$CUSTOMER" in
      *[!0-9]*) echo "audit-credential-access: --customer must be digits" >&2; return 1 ;;
    esac
    export GOOGLE_ADS_CUSTOMER_ID="$CUSTOMER"
  fi

  CREDENTIAL_LABEL="$_cred"
  export CREDENTIAL_LABEL

  docker compose -f "$here/docker-compose.yml" exec \
    -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
    -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
    -e GOOGLE_ADS_CREDENTIAL_ROLE -e CREDENTIAL_LABEL \
    -T hermes-agent /opt/ads-venv/bin/python3 /opt/cc-bin/audit-credential-access.py
}

rc_total=0
if [ "$ALL" = 1 ]; then
  for c in .env.ga .env.gaw; do
    [ -f "$here/$c" ] || continue
    echo "===== $c ====="
    audit_one "$c" || rc_total=$?
  done
else
  [ -n "$CRED" ] || { echo "audit-credential-access: --cred or --all required" >&2; exit 1; }
  audit_one "$CRED" || rc_total=$?
fi
exit "$rc_total"
