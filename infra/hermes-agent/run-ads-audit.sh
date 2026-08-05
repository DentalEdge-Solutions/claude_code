#!/bin/sh
# Produce the ads-analyst audit DRAFT (READ-ONLY). Runs `claude -p` inside the
# container over the scrubbed reports (/opt/data/reports) + SOP docs (:ro mount),
# following the ads-analyst skill, and persists the draft to /opt/data/audits via a
# shell redirect. claude itself only Reads/Greps/Globs (plan mode); the redirect
# writes to /opt/data (writable state volume), never the :ro project mount.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-claude_google_ads}"
# Validate the project name up front: it flows into container paths and the inner
# shell/prompt, so reject anything that could inject shell or traverse paths.
case "$PROJECT" in
  ''|*[!A-Za-z0-9_-]*)
    echo "run-ads-audit: invalid project name: '$PROJECT' (allowed: A-Za-z0-9_-)" >&2; exit 1 ;;
esac
# Pass PROJECT as an ENV VAR (-e), referenced as "$PROJECT" inside the inner script —
# NOT spliced into the inner source (which would let its value execute as code).
exec docker compose -f "$here/docker-compose.yml" exec -e PROJECT="$PROJECT" -T hermes-agent sh -lc '
  set -eu
  skill="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
  ls /opt/data/reports/"$PROJECT"/*.md >/dev/null 2>&1 || { echo "run-ads-audit: no reports in /opt/data/reports/$PROJECT — run ./run-audit-bundle.sh first" >&2; exit 1; }
  mkdir -p /opt/data/audits/"$PROJECT"
  out=/opt/data/audits/"$PROJECT"/$(date -u +%Y-%m-%d_%H-%M-%S)-audit.md
  claude -p "Read and follow $skill EXACTLY. Produce the Google Ads audit DRAFT for project $PROJECT using the scrubbed reports in /opt/data/reports/$PROJECT/ and the SOP/benchmark docs in /projects/$PROJECT/. Output ONLY the deliverable markdown, no preamble." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'
