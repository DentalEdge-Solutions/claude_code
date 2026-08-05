#!/bin/sh
# Host-side READ-ONLY collection: refresh audit_data/ by running the ads project's
# own collector(s) (SELECT-only) under the READ-ONLY credential from .env.ga. Runs on
# the HOST (must write the project tree); Hermes stays :ro. Parses .env.ga (never
# sources it). No mutation possible: read-only cred + SELECT-only collector.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
project_dir="${ADS_PROJECT_DIR:-$(cd "$here/../../../claude-google-ads" 2>/dev/null && pwd || true)}"
env_file="$here/.env.ga"
# Finalized collector set (Task-1 gate): audit_discovery.py (main dump) +
# negatives_audit.py (writes shared-negative coverage into audit_data/). Both are
# SELECT-only and verified working on the host under the read-only credential.
COLLECTORS="audit_discovery.py negatives_audit.py"

[ -n "$project_dir" ] && [ -d "$project_dir" ] || { echo "collect-audit-data: project dir not found (set ADS_PROJECT_DIR)" >&2; exit 1; }
[ -f "$env_file" ] || { echo "collect-audit-data: $env_file not found — provision the read-only credential (Inc-3)" >&2; exit 1; }
py="$project_dir/.venv/bin/python"
[ -x "$py" ] || { echo "collect-audit-data: $py not found — the ads project's .venv must exist on the host" >&2; exit 1; }

# Parse .env.ga as DATA (not shell code): assign the complete read-only set literally.
while IFS= read -r _l || [ -n "$_l" ]; do
  case "$_l" in ''|'#'*) continue ;; GOOGLE_ADS_*=*) : ;; *) continue ;; esac
  _k=${_l%%=*}; _v=${_l#*=}
  case "$_v" in \"*\") _v=${_v#\"}; _v=${_v%\"} ;; \'*\') _v=${_v#\'}; _v=${_v%\'} ;; esac
  export "$_k=$_v"
done < "$env_file"

if [ "${1:-}" = "--dry-run" ]; then
  for c in $COLLECTORS; do echo "would run (read-only cred): (cd $project_dir && .venv/bin/python code/$c)"; done
  exit 0
fi

for c in $COLLECTORS; do
  [ -f "$project_dir/code/$c" ] || { echo "collect-audit-data: collector not found: code/$c" >&2; exit 1; }
  echo "collect-audit-data: running code/$c under the read-only credential…" >&2
  ( cd "$project_dir" && .venv/bin/python "code/$c" )
done
date -u +%Y-%m-%dT%H:%M:%SZ    # collection timestamp = deliverable provenance
