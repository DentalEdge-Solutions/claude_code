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

# R4 guard: if HERMES_GOVERNANCE_DIR is unset or empty, Docker Compose substitutes
# an empty string for ${HERMES_GOVERNANCE_DIR} in docker-compose.yml, which would
# bind-mount /approvals, /control, /registry and /log at the FILESYSTEM ROOT. Refuse
# before anything else runs.
if [ -z "${HERMES_GOVERNANCE_DIR:-}" ]; then
  echo "run-ads-mutate: HERMES_GOVERNANCE_DIR is unset or empty — refusing (an empty value would make Docker Compose bind-mount the governance paths at the filesystem root)" >&2
  exit 1
fi

# Parse --client out of "$@" so it can be handed to persist-run-record.py, which
# needs it to resolve the client vault. Supports both `--client X` and `--client=X`.
client=""
_prev=""
for _arg in "$@"; do
  case "$_prev" in
    --client) client="$_arg" ;;
  esac
  case "$_arg" in
    --client=*) client="${_arg#--client=}" ;;
  esac
  _prev="$_arg"
done
if [ -z "$client" ]; then
  echo "run-ads-mutate: --client is required" >&2
  exit 1
fi

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
# The executor runs in the one-shot ads-mutator container (not the gateway — see
# docker-compose.yml). Its exit status must survive the persist step: `cmd | persist`
# would take its status from persist, turning an exit-2 refusal into a false success.
# Capture to a temp file instead of piping, so `rc` is the executor's real status.
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT INT TERM
# `|| rc=$?` (not a bare command) so a non-zero exit here does not trip `set -e`
# before rc is captured.
rc=0
docker compose -f "$here/docker-compose.yml" run --rm --no-deps \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE \
  -T ads-mutator "$@" > "$tmp_out" 2>&1 || rc=$?
cat "$tmp_out"
# The executor's status ($rc) is what the operator relies on — an exit-2 refusal is a
# promise the client's account was not touched. persist-run-record.py failing for an
# unrelated reason (e.g. it cannot write the vault file) must not override that promise
# and, under `set -e`, a bare non-zero exit here would abort the script with persist's
# status instead. `|| true` keeps this compound command's own status zero so `set -e`
# does not fire; persist's own stderr (it prints its own errors there) still reaches
# the operator since only stdout is redirected.
VAULT_ROOT="$here/data/vaults" HERMES_GOVERNANCE_ROOT="${HERMES_GOVERNANCE_DIR}" \
  python3 "$here/bin/persist-run-record.py" --client "$client" < "$tmp_out" > /dev/null || true
exit "$rc"
