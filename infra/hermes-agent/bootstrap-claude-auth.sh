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

# Fail CLOSED on the credential: if no key is provided, remove any existing
# (possibly stale/rotated-away) settings.json rather than leaving it in place.
# Exit 0 so the gateway can still run for non-Anthropic (e.g. control-plane)
# work — but a Hermes-launched `claude -p` will cleanly report "not logged in"
# instead of silently using a stale key.
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  rm -f "$DEST"
  echo "bootstrap-claude-auth: ANTHROPIC_API_KEY not set — cleared any stale $DEST" >&2
  exit 0
fi

mkdir -p "$CLAUDE_HOME/.claude"

# Build the JSON with json.dumps so the key value is properly escaped (a value
# containing " \ or newline can neither corrupt nor inject into the document).
# Write to a temp file, lock down perms explicitly (umask only affects NEW
# files; a pre-existing DEST would otherwise keep its old mode), then move
# atomically into place so there is never a window with content + wrong perms.
TMP="$DEST.tmp.$$"
umask 177
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" python3 -c '
import json, os
print(json.dumps({"env": {"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"]}}, indent=2))
' > "$TMP"
chmod 600 "$TMP"
mv -f "$TMP" "$DEST"
echo "bootstrap-claude-auth: wrote $DEST (0600)"
