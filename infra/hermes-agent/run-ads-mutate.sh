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
#
# Exit status (F14): 0/1/2/3 are the EXECUTOR's, passed through only when it attested
# them (`HERMES-EXIT <nonce> <rc>`); 1 is also this script's own refusals before Compose.
# 4 = the executor's exit could not be verified — treat the account as possibly modified.
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
# F14 (spec 2026-09-23 §3.2): a fresh per-run nonce. The executor echoes it on its
# attested exit line, and the status below is trusted only when that line matches.
# Failing to make one is refused HERE, before anything runs: an unattestable run would
# always end as 4 anyway, and exit 1 before Compose is still an honest "nothing ran".
nonce=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n') || nonce=""
case "$nonce" in
  *[!0-9a-f]*) nonce="" ;;
esac
if [ "${#nonce}" -ne 32 ]; then
  echo "run-ads-mutate: could not generate the exit nonce — refusing before anything runs" >&2
  exit 1
fi
export HERMES_EXIT_NONCE="$nonce"
# The executor runs in the one-shot ads-mutator container (not the gateway — see
# docker-compose.yml). Its exit status must survive the persist step: `cmd | persist`
# would take its status from persist, turning an exit-2 refusal into a false success.
# Capture to a temp file instead of piping, so `rc` is the executor's real status.
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT INT TERM
# `|| rc=$?` (not a bare command) so a non-zero exit here does not trip `set -e`
# before rc is captured.
rc=0
# F9: --env-file /dev/null — Compose must never open .env here. On the VPS this runs as
# hermes-broker and .env is 600 root:root (it holds ANTHROPIC_API_KEY); Compose aborts on an
# unreadable .env even when every variable is exported (spec 2026-09-22 §2, M4). The
# interpolation inputs come from the environment instead: the broker unit on the VPS,
# hostenv.sh (parsing .env as data) locally.
docker compose --env-file /dev/null -f "$here/docker-compose.yml" run --rm --no-deps \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -e GOOGLE_ADS_CREDENTIAL_ROLE -e HERMES_EXIT_NONCE \
  -T ads-mutator "$@" > "$tmp_out" 2>&1 || rc=$?
# F14: from here on NOTHING may end this script except the single `exit "$final"` at the
# bottom. Under `set -e` a failing `cat` (or grep, or anything) would exit with ITS status
# — 1, which the broker reads as "nothing was mutated" — about a run that may have applied.
set +e  # F14
cat "$tmp_out"
# Trust Compose's status only when the executor attested it: exactly one line
# `HERMES-EXIT <nonce> <rc>` for THIS run's nonce, and no other line for this nonce.
# Anything else — Compose's own failure (possibly after the container started), a
# killed container, a forged or disagreeing line, an unreadable file — is 4.
final=4  # F14: unverified until the attestation below proves otherwise
case "$rc" in
  0|1|2|3)
    exact=$(grep -Fxc "HERMES-EXIT $nonce $rc" "$tmp_out" 2>/dev/null)
    any=$(grep -c "^HERMES-EXIT $nonce " "$tmp_out" 2>/dev/null)
    if [ "$exact" = "1" ] && [ "$any" = "1" ]; then
      final=$rc
    fi
    ;;
esac
if [ "$final" -eq 4 ]; then
  echo "" >&2
  echo "!!! ================================================================" >&2
  echo "!!! EXECUTOR EXIT NOT VERIFIED (compose rc=$rc) — the executor may have" >&2
  echo "!!! run; treat the account as possibly modified; reconcile from the" >&2
  echo "!!! governance audit log before doing anything else with this client." >&2
  echo "!!! ================================================================" >&2
  echo "" >&2
fi
# The executor's status ($rc) is what the operator relies on — an exit-2 refusal is a
# promise the client's account was not touched. persist-run-record.py failing for an
# unrelated reason (e.g. it cannot write the vault file) must not override that promise
# and, under `set -e`, a bare non-zero exit here would abort the script with persist's
# status instead. So persist's status never becomes the script's status.
#
# S1-M2: but it must not VANISH either, which `|| true` made it do. persist-run-record
# exits 2 for a PersistRefused. That is not a routine I/O failure — but as of F12 it is
# not necessarily an attack either, and the banner below no longer says it is. TWO
# causes now share exit 2: a missing records/ tree (the shim refuses rather than
# building it with the wrong mode — the likeliest cause, an operator who pulled and has
# not run `init-host-layout.py --apply` yet), and a containment refusal (a destination
# that could not be proven to stay inside records/, i.e. a symlink or hardlink pointing
# out of it — that one IS an attack detection). The `persist-run-record:` line printed
# immediately above the banner distinguishes them. Either way it must not be swallowed:
# `|| true` left the loudest signal this rail produces as one line of stderr in the
# middle of the executor's own output, with the exit status discarded entirely.
#
# `|| prc=$?` instead of `|| true` — the same pattern the executor invocation above
# uses — so `set -e` still does not fire, $rc still decides the script's status, and a
# non-zero persist gets an unmissable banner of its own.
# VAULT_ROOT and HERMES_GOVERNANCE_ROOT are exported by hostenv.sh above.
prc=0
python3 "$here/bin/persist-run-record.py" --client "$client" < "$tmp_out" > /dev/null || prc=$?
if [ "$prc" -ne 0 ]; then
  echo "" >&2
  echo "!!! ================================================================" >&2
  echo "!!! RUN RECORD NOT PERSISTED — persist-run-record.py exited $prc" >&2
  echo "!!!" >&2
  echo "!!! Exit 2 is a REFUSAL, not an I/O hiccup. The 'persist-run-record:' line" >&2
  echo "!!! just above says which one. Two causes, in order of likelihood:" >&2
  echo "!!!   1. SETUP — the governance store has no records/ tree yet. Most common" >&2
  echo "!!!      right after a pull: run 'sudo python3 bin/init-host-layout.py --apply'" >&2
  echo "!!!      (then '--check' as hermes-broker). Nothing was attacked." >&2
  echo "!!!   2. CONTAINMENT REFUSAL — the destination could not be proven to stay" >&2
  echo "!!!      inside records/: a symlink or hardlink pointing out of it. Treat that" >&2
  echo "!!!      as an attempt to make this step write outside records/, and inspect" >&2
  echo "!!!      the governance store's records/<client> directory before re-running." >&2
  echo "!!!" >&2
  echo "!!! The executor's own status ($final) is UNCHANGED and is still what says" >&2
  echo "!!! whether the account was touched. This banner is about the RECORD of the" >&2
  echo "!!! run, which is now missing — reconcile from the governance audit log." >&2
  echo "!!! ================================================================" >&2
  echo "" >&2
fi
exit "$final"
