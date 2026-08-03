#!/bin/sh
# Host-side wrapper: inject the READ-ONLY Google Ads credential per-invocation and
# run the report inside the container. The credential lives in the gitignored
# .env.ga (NOT loaded by docker-compose env_file, NOT in the gateway env) — sourced
# here and passed via `docker compose exec -e`, so it reaches ONLY this exec'd
# process, never the gateway/agent env. Mirrors open-proposal-pr.sh (Increment 2).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env.ga" ]; then
  echo "run-ads-report: $here/.env.ga not found — copy .env.ga.example and fill in the READ-ONLY credential" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; . "$here/.env.ga"; set +a
exec docker compose -f "$here/docker-compose.yml" exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -T hermes-agent python3 /opt/cc-bin/run-ads-report.py "$@"
