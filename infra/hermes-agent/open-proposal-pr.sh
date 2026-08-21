#!/bin/sh
# Host-side operator entry point for the draft-PR write step (Increment 2). Reads the
# gitignored .env.pr (which is NOT in the gateway env_file) and passes the bot PAT into
# the gateway via `exec -e CLAUDE_CODE_PR_PAT` (name only — the value never lands on
# the host argv).
#
# WHAT THAT DOES AND DOES NOT GUARANTEE. It is true of DELIVERY that the PAT lands in
# one process's environment. It is false of VISIBILITY: /proc/<pid>/environ is readable
# by any same-UID process, and everything in the gateway container runs as `hermes`
# (uid 10000), so while this command is running an agent-launched process CAN read the
# PAT. Keeping the PAT out of `env_file` removes the resting exposure, not the timing
# window. The fix applied to the Ads WRITE credential — move the consumer into a
# one-shot container Hermes has no shell in — has not yet been applied here; this path
# still exec's into the gateway. The PAT carries org-repo Contents + Pull-requests
# write, so treat that window as real.
#
# .env.pr is PARSED AS DATA, never sourced. Sourcing executes the file as shell, so a
# `$(...)`, a backtick or a stray command in a credential file would run with the
# operator's privileges. Same rule and same implementation as run-ads-mutate.sh's
# handling of .env.gaw — this file was the one place the capsule's own written rule was
# being broken.
#
# Usage:  ./open-proposal-pr.sh --project claude_code [--proposal latest|<ts>] [--dry-run]
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$here/.env.pr" ] || { echo "missing $here/.env.pr (copy .env.pr.example, add the bot PAT)" >&2; exit 1; }
while IFS= read -r _line || [ -n "$_line" ]; do
  case "$_line" in
    ''|'#'*) continue ;;
    CLAUDE_CODE_PR_PAT=*) : ;;
    *) continue ;;
  esac
  _val=${_line#CLAUDE_CODE_PR_PAT=}
  case "$_val" in
    \"*\") _val=${_val#\"}; _val=${_val%\"} ;;
    \'*\') _val=${_val#\'}; _val=${_val%\'} ;;
  esac
  # `export "k=$v"` assigns the ALREADY-EXPANDED value literally: no command
  # substitution is performed on it, so `$(...)` inside a secret stays inert.
  export "CLAUDE_CODE_PR_PAT=$_val"
done < "$here/.env.pr"
if [ -z "${CLAUDE_CODE_PR_PAT:-}" ]; then
  echo "open-proposal-pr: $here/.env.pr sets no CLAUDE_CODE_PR_PAT — refusing" >&2
  exit 1
fi
exec docker compose -f "$here/docker-compose.yml" exec -e CLAUDE_CODE_PR_PAT -T \
  hermes-agent python3 /opt/cc-bin/open-proposal-pr.py "$@"
