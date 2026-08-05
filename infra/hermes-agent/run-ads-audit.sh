#!/bin/sh
# Produce the ads-analyst audit DRAFT (READ-ONLY). Runs `claude -p` inside the
# container over the scrubbed reports (/opt/data/reports) + SOP docs (:ro mount),
# following the ads-analyst skill, and persists the draft to /opt/data/audits via a
# shell redirect. claude itself only Reads/Greps/Globs (plan mode); the redirect
# writes to /opt/data (writable state volume), never the :ro project mount.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-claude_google_ads}"
SKILL="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
exec docker compose -f "$here/docker-compose.yml" exec -T hermes-agent sh -lc '
  set -eu
  proj="'"$PROJECT"'"
  skill="'"$SKILL"'"
  ls /opt/data/reports/"$proj"/*.md >/dev/null 2>&1 || { echo "run-ads-audit: no reports in /opt/data/reports/$proj — run ./run-audit-bundle.sh first" >&2; exit 1; }
  mkdir -p /opt/data/audits/"$proj"
  out=/opt/data/audits/"$proj"/$(date -u +%Y-%m-%d_%H-%M-%S)-audit.md
  claude -p "Read and follow $skill EXACTLY. Produce the Google Ads audit DRAFT for project $proj using the scrubbed reports in /opt/data/reports/$proj/ and the SOP/benchmark docs in /projects/$proj/. Output ONLY the deliverable markdown, no preamble." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'
