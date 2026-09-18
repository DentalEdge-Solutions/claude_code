#!/usr/bin/env bash
# Idempotent Ubuntu 24.04 hardening for a Hermes deploy target.
#
# Takes a bare box to: a non-root deploy account with key-only SSH, a
# default-deny firewall, fail2ban, unattended security upgrades, and Docker
# Engine. It stops there.
#
# It knows NOTHING about Hermes beyond the names it must refuse (RESERVED_NAMES
# below). The Hermes users, groups, governance store and systemd units are
# infra/hermes-agent/README.md:957's job; duplicating that sequence here would
# create a second source of truth that drifts from a merged, measured one.
#
# Usage, as root on the box:
#   DEPLOY_USER=hermesops SSH_PUBKEY="ssh-ed25519 AAAA..." bash provision.sh
#   bash provision.sh --check     # verify only; changes nothing, non-zero on drift
#
# Spec:    docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md
# Runbook: infra/hermes-agent/deploy/BRING-UP.md
set -euo pipefail

# Names owned by the Hermes tier (README.md:957 step 1). See the spec's 2.1: a
# deploy user named `hermes` silently costs gid 10000 and breaks the executor's
# read of the governance store. Refuse rather than document.
RESERVED_NAMES=(hermes hermes-broker hermes-docker-proxy hermes-rail)

DEPLOY_USER="${DEPLOY_USER:-hermesops}"
SSH_PUBKEY="${SSH_PUBKEY:-}"
# Injectable so the suite can point the OS gate at a fixture instead of the
# runner's real release. Defaults to the real file on a real box. Unused by
# Task 1: the OS gate that reads this lands in Task 2.
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"

MODE=apply
# Set by --force-os below; unused by Task 1 -- consumed by Task 2's OS gate,
# which this flag lets an operator override.
FORCE_OS=0

die()  { printf 'provision: %s\n' "$*" >&2; exit 1; }
note() { printf '[provision] %s\n' "$*"; }

# CHECKS/FAILED back ok()/bad()/finish(): a --check run tallies every check it
# performs so finish() can tell "zero drift" apart from "zero checks ran".
CHECKS=0
FAILED=0
ok()   { printf '  OK    %s\n' "$*"; CHECKS=$((CHECKS + 1)); }
bad()  { printf '  DRIFT %s\n' "$*" >&2; FAILED=$((FAILED + 1)); CHECKS=$((CHECKS + 1)); }

while [ $# -gt 0 ]; do
  case "$1" in
    --check)    MODE=check ;;
    --force-os) FORCE_OS=1 ;;
    *)          die "unknown argument: $1" ;;
  esac
  shift
done

# Runs FIRST, before the OS gate and before any host inspection: it costs
# nothing, it is the one guard whose failure is silent and expensive, and being
# first is what makes it reachable -- and therefore testable -- on any host.
assert_deploy_user_not_reserved() {
  local n
  for n in "${RESERVED_NAMES[@]}"; do
    if [ "$DEPLOY_USER" = "$n" ]; then
      die "DEPLOY_USER=${DEPLOY_USER} is reserved for the Hermes tier (README.md:957 step 1); use another name, e.g. hermesops"
    fi
  done
}

assert_supported_os() {
  [ "$FORCE_OS" -eq 1 ] && return 0
  [ -r "$OS_RELEASE_FILE" ] || die "cannot read ${OS_RELEASE_FILE} (os-release); pass --force-os to override"
  local name version
  name="$(. "$OS_RELEASE_FILE" >/dev/null 2>&1; printf '%s' "${NAME:-}")"
  version="$(. "$OS_RELEASE_FILE" >/dev/null 2>&1; printf '%s' "${VERSION_ID:-}")"
  case "$name" in
    Ubuntu*) : ;;
    *) die "refusing: this script targets Ubuntu, found '${name:-unknown}'; pass --force-os to override" ;;
  esac
  [ "$version" = "24.04" ] || \
    die "refusing: this script targets Ubuntu 24.04, found '${version:-unknown}'; pass --force-os to override"
}

# apply_all and check_all are deliberately SEPARATE rather than one function
# branching on MODE. --check must be an independent observer of the host: if it
# shared code with apply it would tend to report what apply intended rather than
# what the box is. The cost is a little duplication; the benefit is that a check
# can contradict an apply, which is the only way it is worth running.
apply_all() {
  :
}

check_all() {
  :
}

finish() {
  if [ "$MODE" = check ]; then
    # A check run that measured nothing is not a pass. Without this, an empty
    # or accidentally-disabled check_all reports "all checks passed" -- the
    # instrument claiming SAFE without having observed anything.
    [ "$CHECKS" -gt 0 ] || die "no checks ran -- the check set is empty, which is not a pass"
    [ "$FAILED" -eq 0 ] || { printf 'provision: %d check(s) failed\n' "$FAILED" >&2; exit 1; }
    note "all checks passed (${CHECKS} checks)"
  fi
}

main() {
  assert_deploy_user_not_reserved
  assert_supported_os
  note "deploy user: ${DEPLOY_USER} (mode: ${MODE})"
  if [ "$MODE" = check ]; then check_all; else apply_all; fi
  finish
}

main "$@"
