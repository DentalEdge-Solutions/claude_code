#!/bin/sh
# Host-side wrapper: inject the STANDARD-ACCESS (WRITE) Google Ads credential
# per-invocation into the one-shot ads-mutator container, which Hermes has no shell
# in. The credential lives in the gitignored .env.gaw (NOT loaded by docker-compose
# env_file, NOT in the gateway env) — PARSED here (not sourced) and passed via
# `docker compose run -e` into that one-shot container. It never enters the gateway
# container at all.
#
# (Earlier wording here said it "reaches only this exec'd process" — true of
# delivery, false of visibility: /proc/<pid>/environ is readable by any same-UID
# process, and everything in the gateway container runs as the same user, so a
# same-container boundary was never real isolation. The one-shot, no-shell
# container is the actual boundary: there is no Hermes-controlled process running
# there to read it from.)
#
# Mirrors run-ads-report.sh, which does the same for the READ-ONLY credential; the
# two files are deliberately separate so the read path keeps its platform-level
# backstop.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"

# Resolves HERMES_GOVERNANCE_DIR (environment first, else parsed as DATA out of .env,
# which is Compose-interpolation-only and never exported) and exports the two host-side
# roots. Carries the R4 guard: an empty value would make Docker Compose bind-mount the
# governance paths at the FILESYSTEM ROOT.
. "$here/hostenv.sh"

# Pre-flight the executor's access to the governance store BEFORE anything runs. On a
# Linux VPS the executor is uid 10000 while the store is mode 700 owned by the deploy
# user, which makes the kill switch read as absent, client resolution raise, and
# append_log fail MID-APPLY — exit 3 after a live account change has landed. Refusing
# here converts that into a refusal before Google is reachable. No-op on non-Linux,
# where Docker Desktop remaps ownership and a stat-based prediction would be false.
python3 "$here/bin/preflight-governance-access.py" --root "$HERMES_GOVERNANCE_DIR"

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
# VAULT_ROOT and HERMES_GOVERNANCE_ROOT are exported by hostenv.sh above.
python3 "$here/bin/persist-run-record.py" --client "$client" < "$tmp_out" > /dev/null || true
exit "$rc"
