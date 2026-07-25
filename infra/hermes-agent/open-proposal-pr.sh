#!/bin/sh
# Host-side operator entry point for the draft-PR write step (Increment 2). Sources
# the gitignored .env.pr (which is NOT in the gateway env_file) and passes the bot
# PAT into a one-off container exec via `-e CLAUDE_CODE_PR_PAT` (name only — the
# value never lands on the host argv). The PAT therefore reaches ONLY this exec'd
# process, never the gateway or any agent-launched subprocess.
#
# Usage:  ./open-proposal-pr.sh --project claude_code [--proposal latest|<ts>] [--dry-run]
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$here/.env.pr" ] || { echo "missing $here/.env.pr (copy .env.pr.example, add the bot PAT)" >&2; exit 1; }
set -a; . "$here/.env.pr"; set +a
exec docker compose -f "$here/docker-compose.yml" exec -e CLAUDE_CODE_PR_PAT -T \
  hermes-agent python3 /opt/cc-bin/open-proposal-pr.py "$@"
