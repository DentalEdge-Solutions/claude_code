#!/bin/sh
# Host-side wrapper: inject the READ-ONLY Google Ads credential per-invocation and
# run the report inside the container. The credential lives in the gitignored
# .env.ga (NOT loaded by docker-compose env_file, NOT in the gateway env) — PARSED
# here (not sourced) and passed via `docker compose exec -e`, so it reaches ONLY
# this exec'd process, never the gateway/agent env. Mirrors open-proposal-pr.sh
# (Increment 2) but parses rather than sources so shell metacharacters in a
# credential value are never interpreted or executed.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env.ga" ]; then
  echo "run-ads-report: $here/.env.ga not found — copy .env.ga.example and fill in the READ-ONLY credential" >&2
  exit 1
fi
# Parse .env.ga as DATA (not shell code): read each line raw, split on the first '=',
# assign the value LITERALLY. `export "$k=$v"` performs no command substitution on the
# already-expanded value, so `$(...)`/backticks in a secret stay inert. Only GOOGLE_ADS_*.
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
done < "$here/.env.ga"
exec docker compose -f "$here/docker-compose.yml" exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -T hermes-agent python3 /opt/cc-bin/run-ads-report.py "$@"
