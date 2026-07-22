#!/bin/sh
# Bootstrap Claude Code auth for the Hermes-launched `claude` executor.
#
# WHY THIS EXISTS
#   Hermes deliberately SCRUBS secrets from the environment of the shell
#   commands it runs (verified: `printenv ANTHROPIC_API_KEY` inside the terminal
#   tool returns empty). So a Hermes-launched `claude -p` never sees the process
#   env — it can only read its key from Claude Code's own config file at
#   $HOME/.claude/settings.json. Hermes runs those subprocesses with
#   HOME=/opt/data/home, so the file must live at /opt/data/home/.claude/.
#
#   This script materializes that file from $ANTHROPIC_API_KEY (which the
#   container gets from the gitignored .env). Result: `.env` stays the single
#   human-facing source of truth; settings.json is a GENERATED artifact under
#   the gitignored data/ volume — never hand-edited, never committed, never
#   stale after a key rotation (just edit .env and recreate).
#
# Idempotent and safe to run on every container start.
set -eu

CLAUDE_HOME="${CLAUDE_SETTINGS_HOME:-/opt/data/home}"
DEST="$CLAUDE_HOME/.claude/settings.json"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "bootstrap-claude-auth: ANTHROPIC_API_KEY not set; skipping (claude -p will be unauthenticated)" >&2
  exit 0
fi

mkdir -p "$CLAUDE_HOME/.claude"
umask 177   # 0600 — readable only by the owner
printf '{\n  "env": {\n    "ANTHROPIC_API_KEY": "%s"\n  }\n}\n' "$ANTHROPIC_API_KEY" > "$DEST"
echo "bootstrap-claude-auth: wrote $DEST (0600)"
