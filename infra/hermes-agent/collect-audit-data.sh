#!/bin/sh
# Host-side READ-ONLY collection: refresh audit_data/ by running the ads project's
# own collector(s) (SELECT-only) under the READ-ONLY credential from .env.ga. Runs on
# the HOST (must write the project tree); Hermes stays :ro. Parses .env.ga (never
# sources it). No mutation possible: read-only cred + SELECT-only collector.
set -eu
# Reject unknown args so a typo (e.g. --dryrun) fails CLOSED instead of silently
# falling through to a live run — the dry-run gate must not be bypassable.
DASHBOARD=0
for _a in "$@"; do
  case "$_a" in
    --dry-run) : ;;
    --with-dashboard) DASHBOARD=1 ;;
    *) echo "collect-audit-data: unknown argument: $_a (accepted: --dry-run, --with-dashboard)" >&2; exit 1 ;;
  esac
done
DRY=0
for _a in "$@"; do [ "$_a" = "--dry-run" ] && DRY=1; done
here="$(cd "$(dirname "$0")" && pwd)"
project_dir="${ADS_PROJECT_DIR:-$(cd "$here/../../../claude-google-ads" 2>/dev/null && pwd || true)}"
env_file="$here/.env.ga"
# Collector set. All are SELECT-only and verified working on the host under the
# READ-ONLY credential.
#
#   audit_discovery.py    main dump (Task-1 gate)
#   negatives_audit.py    shared-negative coverage (Task-1 gate)
#   audit_assets_rsa.py   RSA/asset detail        ) added 2026-08-18
#   assess_supplemental.py supplemental windows   )
#
# The last two live HERE rather than in the registry's read_execute.allow because
# they WRITE into the project tree (audit_data/). Hermes mounts projects :ro, so
# in-container they die with `OSError: [Errno 30] Read-only file system` at the
# first write — after having already spent the API calls. Collection is the
# host-side path that is allowed to write the tree, so it is where they belong.
COLLECTORS="audit_discovery.py negatives_audit.py audit_assets_rsa.py assess_supplemental.py"

# build_dashboard_data.py also writes the tree, but to landing/data/ — it renders a
# dashboard payload rather than collecting audit data, so it is opt-in via
# --with-dashboard instead of running on every audit.
DASHBOARD_COLLECTOR="build_dashboard_data.py"

[ -n "$project_dir" ] && [ -d "$project_dir" ] || { echo "collect-audit-data: project dir not found (set ADS_PROJECT_DIR)" >&2; exit 1; }
[ -f "$env_file" ] || { echo "collect-audit-data: $env_file not found — provision the read-only credential (Inc-3)" >&2; exit 1; }
py="$project_dir/.venv/bin/python"
[ -x "$py" ] || { echo "collect-audit-data: $py not found — the ads project's .venv must exist on the host" >&2; exit 1; }
# Pre-flight: ALL collectors must exist before we run ANY (no partial refresh).
[ "$DASHBOARD" = 1 ] && COLLECTORS="$COLLECTORS $DASHBOARD_COLLECTOR"
for c in $COLLECTORS; do
  [ -f "$project_dir/code/$c" ] || { echo "collect-audit-data: collector not found: code/$c" >&2; exit 1; }
done

# Parse .env.ga as DATA (not shell code): assign the complete read-only set literally.
while IFS= read -r _l || [ -n "$_l" ]; do
  case "$_l" in ''|'#'*) continue ;; GOOGLE_ADS_*=*) : ;; *) continue ;; esac
  _k=${_l%%=*}; _v=${_l#*=}
  case "$_v" in \"*\") _v=${_v#\"}; _v=${_v%\"} ;; \'*\') _v=${_v#\'}; _v=${_v%\'} ;; esac
  export "$_k=$_v"
done < "$env_file"

# Per-client override (digits only). run-trend-audit.sh sets this to target one
# client's account; it wins over the .env.ga CUSTOMER_ID for this invocation.
if [ "${ADS_CUSTOMER_ID_OVERRIDE+x}" = "x" ]; then
  case "$ADS_CUSTOMER_ID_OVERRIDE" in
    *[!0-9]*|'') echo "collect-audit-data: invalid ADS_CUSTOMER_ID_OVERRIDE (digits only)" >&2; exit 1 ;;
  esac
  export GOOGLE_ADS_CUSTOMER_ID="$ADS_CUSTOMER_ID_OVERRIDE"
fi

# Fail closed on a missing target. .env.ga no longer pins GOOGLE_ADS_CUSTOMER_ID —
# there is deliberately no implicit default account — so an unset override used to
# fall through and run every collector against an empty customer id. Refuse instead:
# an unresolved target must never become "whichever account the file happened to name".
if [ -z "${GOOGLE_ADS_CUSTOMER_ID:-}" ]; then
  echo "collect-audit-data: no target account. .env.ga does not pin GOOGLE_ADS_CUSTOMER_ID" >&2
  echo "  by design; set ADS_CUSTOMER_ID_OVERRIDE=<digits> (run-trend-audit.sh does this" >&2
  echo "  from the client vault, which is the resolved-not-hardcoded path)." >&2
  exit 1
fi

if [ "$DRY" = 1 ]; then
  echo "effective GOOGLE_ADS_CUSTOMER_ID: $GOOGLE_ADS_CUSTOMER_ID"
  for c in $COLLECTORS; do echo "would run (read-only cred): (cd $project_dir && .venv/bin/python code/$c)"; done
  exit 0
fi

for c in $COLLECTORS; do
  echo "collect-audit-data: running code/$c under the read-only credential…" >&2
  ( cd "$project_dir" && .venv/bin/python "code/$c" )
done
date -u +%Y-%m-%dT%H:%M:%SZ    # collection timestamp = deliverable provenance
