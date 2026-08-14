#!/bin/sh
# Host-side wrapper: inject the STANDARD-ACCESS (WRITE) Google Ads credential
# per-invocation and run the applier inside the container. The credential lives in
# the gitignored .env.gaw (NOT loaded by docker-compose env_file, NOT in the gateway
# env) — PARSED here (not sourced) and passed via `docker compose exec -e`, so it
# reaches ONLY this exec'd process. Mirrors run-ads-report.sh, which does the same
# for the READ-ONLY credential; the two files are deliberately separate so the read
# path keeps its platform-level backstop.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env.gaw" ]; then
  echo "run-ads-mutate: $here/.env.gaw not found — copy .env.gaw.example and fill in the WRITE credential" >&2
  exit 1
fi
# Parse .env.gaw as DATA (not shell code): read each line raw, split on the first '=',
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
done < "$here/.env.gaw"
if [ "${GOOGLE_ADS_CREDENTIAL_ROLE:-}" != "write" ]; then
  echo "run-ads-mutate: .env.gaw must set GOOGLE_ADS_CREDENTIAL_ROLE=write (got '${GOOGLE_ADS_CREDENTIAL_ROLE:-}')" >&2
  exit 1
fi
exec docker compose -f "$here/docker-compose.yml" exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE \
  -T hermes-agent python3 /opt/cc-bin/apply-changeset.py "$@"
