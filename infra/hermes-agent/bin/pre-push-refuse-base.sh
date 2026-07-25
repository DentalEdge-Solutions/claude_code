#!/bin/sh
# git pre-push hook: refuse any push whose remote ref is the protected base branch.
# git feeds "<local ref> <local sha> <remote ref> <remote sha>" lines on stdin.
# BASE_REF is injected by the installer (open-proposal-pr.py) as an env var.
base="refs/heads/${PREPUSH_BASE:-main}"
while read local_ref local_sha remote_ref remote_sha; do
  if [ "$remote_ref" = "$base" ]; then
    echo "pre-push: refusing to push to protected base $base" >&2
    exit 1
  fi
done
exit 0
