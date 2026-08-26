#!/bin/sh
# Host-side entry point for the UNCREDENTIALED half of the mutation rail.
#
#   ./changeset.sh propose --client <slug> --from actions.json
#   ./changeset.sh approve --client <slug> --changeset <id> --operator <name> \
#       --expect-sha256 <hex>
#
# Both wrapped commands hold NO credential and perform no network I/O — they are
# structurally incapable of touching a Google Ads account. This wrapper adds nothing
# but the two host-side roots (see hostenv.sh): without them, `python3
# bin/propose-changeset.py` run from a shell resolves the CONTAINER paths
# /opt/governance/registry/clients.json and /opt/data/vaults and fails with
# "client registry not found".
#
# Deliberately NOT a wrapper for apply/undo. Those need the write credential and stay
# in run-ads-mutate.sh, which is the file an operator should have to name on purpose.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"

cmd="${1:-}"
if [ "$#" -ge 1 ]; then shift; fi
case "$cmd" in
  propose|approve) : ;;
  *)
    echo "usage: $0 propose|approve [args...]" >&2
    echo "  $0 propose --client <slug> --from actions.json" >&2
    echo "  $0 approve --client <slug> --changeset <id> --operator <name> --expect-sha256 <hex>" >&2
    echo "  (omit --expect-sha256 on a first attempt to print the digest and action summary you need to build it)" >&2
    exit 1 ;;
esac

. "$here/hostenv.sh"
exec python3 "$here/bin/${cmd}-changeset.py" "$@"
