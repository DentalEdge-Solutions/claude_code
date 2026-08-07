#!/bin/sh
# Trend-aware, READ-ONLY per-client Google Ads audit. Orchestrates:
#   resolve client -> collect fresh (read-only cred, this client) -> deterministic
#   metrics snapshot -> fresh reports -> claude -p trend audit (reads fresh reports +
#   THIS client's vault history) -> vault-write (sole vault writer). No mutation.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
CLIENT=""
while [ $# -gt 0 ]; do
  case "$1" in --client) CLIENT="$2"; shift 2 ;; *) echo "usage: run-trend-audit.sh --client <slug>" >&2; exit 1 ;; esac
done
[ -n "$CLIENT" ] || { echo "usage: run-trend-audit.sh --client <slug>" >&2; exit 1; }

export VAULT_ROOT="$here/data/vaults"                     # host path == container /opt/data/vaults
CID="$(python3 "$here/bin/vault_lib.py" --client "$CLIENT" --field customer_id)"     # validates slug+id (exit 2 on bad)
PROJECT="$(python3 "$here/bin/vault_lib.py" --client "$CLIENT" --field project)"
case "$PROJECT" in ''|*[!A-Za-z0-9_-]*) echo "run-trend-audit: bad project '$PROJECT'" >&2; exit 1 ;; esac
TS="$(date -u +%Y-%m-%d_%H-%M-%S)"

echo "run-trend-audit: [$CLIENT] collecting fresh data (read-only)…" >&2
ADS_CUSTOMER_ID_OVERRIDE="$CID" "$here/collect-audit-data.sh"

ADS_DIR="${ADS_PROJECT_DIR:-$(cd "$here/../../../claude-google-ads" && pwd)}/audit_data"
SNAP="$(mktemp)"; trap 'rm -f "$SNAP"' EXIT
python3 "$here/bin/ads-metrics-snapshot.py" --audit-data "$ADS_DIR" --customer "$CID" > "$SNAP"

echo "run-trend-audit: [$CLIENT] producing report set…" >&2
"$here/run-audit-bundle.sh" "$PROJECT" --customer "$CID"

echo "run-trend-audit: [$CLIENT] trend audit (opus, plan mode)…" >&2
# PROJECT/CLIENT/TS passed via -e (never spliced into the inner source). claude is
# read-only (plan mode, Read/Grep/Glob); the draft is written by a redirect to
# /opt/data (writable), never the :ro mount.
docker compose -f "$here/docker-compose.yml" exec \
  -e PROJECT="$PROJECT" -e CLIENT="$CLIENT" -e TS="$TS" -T hermes-agent sh -lc '
  set -eu
  skill="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
  vault="/opt/data/vaults/$CLIENT"; reports="/opt/data/reports/$PROJECT"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  mkdir -p "/opt/data/audits/$PROJECT"
  out="/opt/data/audits/$PROJECT/$TS-audit.md"
  claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'
DRAFT="$here/data/audits/$PROJECT/$TS-audit.md"
[ -f "$DRAFT" ] || { echo "run-trend-audit: draft not produced: $DRAFT" >&2; exit 1; }
# (VAULT_ROOT was exported to the host path "$here/data/vaults" at the top.)

# Sole vault writer: ingest draft + metrics + timeline into the client vault.
# VAULT_ROOT is already exported to the host path above, so vault-write resolves
# the host registry and writes host-side under data/vaults/<slug>/.
python3 "$here/bin/vault-write.py" \
  --client "$CLIENT" --audit-file "$DRAFT" --metrics-file "$SNAP" --ts "$TS"

# Cross-client soft-isolation assertion — MUST fail closed (a security check).
VAULT_AUDIT="$here/data/vaults/$CLIENT/audits/$TS-audit.md"
[ -f "$VAULT_AUDIT" ] || { echo "run-trend-audit: vault audit not written where expected: $VAULT_AUDIT" >&2; exit 1; }
others="$(python3 - "$here/data/vaults/_registry/clients.json" "$CLIENT" <<'PY'
import json, sys
reg, me = sys.argv[1], sys.argv[2]
with open(reg) as f:
    clients = json.load(f).get("clients", {})
print(" ".join(s for s in clients if s != me))
PY
)" || { echo "run-trend-audit: could not enumerate clients for isolation check" >&2; exit 1; }
for other in $others; do
  if grep -qiw -- "$other" "$VAULT_AUDIT"; then
    echo "run-trend-audit: ASSERTION FAIL — draft references other client '$other'" >&2; exit 1
  fi
done
echo "run-trend-audit: [$CLIENT] done -> data/vaults/$CLIENT/audits/$TS-audit.md" >&2
