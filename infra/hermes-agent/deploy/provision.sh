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

# Validated here rather than at the point of use: a bad key must be refused
# BEFORE any host mutation, not midway through apply. Runs in both modes when
# set, which also makes it reachable from the suite.
assert_ssh_pubkey_wellformed() {
  [ -n "$SSH_PUBKEY" ] || return 0
  case "$SSH_PUBKEY" in
    *"
"*) die "SSH_PUBKEY contains a newline; expected a single-line OpenSSH public key" ;;
  esac
  # Intentional word splitting: an OpenSSH public key is <type> <base64> [comment].
  # set -f around it: $SSH_PUBKEY is unquoted here on purpose to split it, but
  # unquoted expansion also pathname-expands *, ? and [...] against $PWD --
  # disable globbing for the split so a key containing those characters can't
  # have filenames substituted into it.
  set -f
  # shellcheck disable=SC2086
  set -- $SSH_PUBKEY
  set +f
  local type="${1:-}" body="${2:-}"
  case "$type" in
    ssh-ed25519|ssh-rsa|ssh-dss|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) : ;;
    *) die "SSH_PUBKEY type '${type:-<empty>}' is not a recognised OpenSSH key type; options or a command= prefix (as in authorized_keys) are not supported here -- expected a bare '<type> <base64> [comment]' key" ;;
  esac
  [ -n "$body" ] || die "SSH_PUBKEY has a type but no key material -- a truncated key would be written and then password login disabled, locking you out"
  case "$body" in
    *[!A-Za-z0-9+/=]*) die "SSH_PUBKEY key material contains characters that are not base64" ;;
  esac
  [ "${#body}" -ge 68 ] || die "SSH_PUBKEY key material is only ${#body} characters; the shortest real OpenSSH key body (ed25519) is 68 -- this looks truncated, and writing it would disable password login behind a key that cannot authenticate"
}

# PARSED, never sourced. os-release is documented as shell-sourceable, but this
# path is environment-overridable for testability, and sourcing an
# attacker-influenced file as root is arbitrary code execution rather than the
# refusal a gate owes. awk reads the fields without a shell ever seeing them.
os_release_field() {
  awk -F= -v key="$1" '$1==key {v=$2; gsub(/^"|"$/,"",v); print v; exit}' "$OS_RELEASE_FILE"
}

assert_supported_os() {
  [ "$FORCE_OS" -eq 1 ] && return 0
  [ -r "$OS_RELEASE_FILE" ] || die "cannot read ${OS_RELEASE_FILE} (os-release); pass --force-os to override"
  local name version
  name="$(os_release_field NAME)"
  version="$(os_release_field VERSION_ID)"
  case "$name" in
    Ubuntu*) : ;;
    *) die "refusing: this script targets Ubuntu, found '${name:-unknown}'; pass --force-os to override" ;;
  esac
  [ "$version" = "24.04" ] || \
    die "refusing: this script targets Ubuntu 24.04, found '${version:-unknown}'; pass --force-os to override"
}

SSHD_DROPIN=/etc/ssh/sshd_config.d/10-hermes-hardening.conf

# The sshd policy, declared ONCE and consumed by both ensure_ and check_.
# A previous design duplicated this list between the drop-in heredoc and the
# verification greps, and a test tried to police the duplication by parsing the
# script's own text. That test was defeated three separate ways (a deleted line,
# a commented-out block, a decoy substring in a trailing comment). Removing the
# duplication makes "applied but never verified" unconstructible instead of merely
# detectable.
SSHD_DIRECTIVES="PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
PubkeyAuthentication yes"

ensure_deploy_user() {
  if id "$DEPLOY_USER" >/dev/null 2>&1; then
    note "user ${DEPLOY_USER} already exists"
  else
    note "creating ${DEPLOY_USER}"
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
  fi
  # sudo, deliberately NOT docker. Both are root-equivalent -- the point is not
  # that sudo is weaker but that it is logged, that the box grows one
  # root-equivalent identity rather than two, and that an empty docker group
  # keeps `getent group docker` a meaningful check on the real host.
  usermod -aG sudo "$DEPLOY_USER"
}

ensure_authorized_key() {
  [ -n "$SSH_PUBKEY" ] || die "set SSH_PUBKEY to the deploy user's public key"
  local home akeys
  home="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
  akeys="${home}/.ssh/authorized_keys"
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "${home}/.ssh"
  touch "$akeys"
  # Append-if-absent. A truncating redirect would delete every other key on the
  # box, including on a re-run of this script.
  if grep -qxF "$SSH_PUBKEY" "$akeys"; then
    note "authorized key already present"
  else
    printf '%s\n' "$SSH_PUBKEY" >> "$akeys"
    note "authorized key appended"
  fi
  chmod 600 "$akeys"
  chown "${DEPLOY_USER}:${DEPLOY_USER}" "$akeys"
}

ensure_sshd_hardening() {
  install -d -m 755 /etc/ssh/sshd_config.d
  # A drop-in, not sed against sshd_config: 24.04 ships the Include, and
  # rewriting the same drop-in is naturally idempotent. Generated from
  # SSHD_DIRECTIVES rather than a literal heredoc so the applied policy and the
  # verified policy (check_sshd_hardening) can never drift apart.
  { printf '%s\n' "# Managed by infra/hermes-agent/deploy/provision.sh. Edits will be overwritten."
    printf '%s\n' "$SSHD_DIRECTIVES"; } > "$SSHD_DROPIN"
  chmod 644 "$SSHD_DROPIN"
  # Validate BEFORE reloading. A bad drop-in that reaches a reload is how a fresh
  # VPS is locked out; sshd -t is the difference between a refusal and a brick.
  sshd -t || die "sshd rejected the configuration; ${SSHD_DROPIN} left in place, NOT reloaded"
  # reload, never restart: the operator's live session is the recovery path while
  # the new configuration is being proven.
  systemctl reload ssh
  note "sshd hardened and reloaded"
}

check_deploy_user() {
  if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    bad "user ${DEPLOY_USER} missing"
    return 0
  fi
  ok "user ${DEPLOY_USER} exists"
  if id -nG "$DEPLOY_USER" 2>/dev/null | tr ' ' '\n' | grep -qx sudo; then
    ok "${DEPLOY_USER} is in the sudo group"
  else
    bad "${DEPLOY_USER} is NOT in the sudo group"
  fi
  if id -nG "$DEPLOY_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
    bad "${DEPLOY_USER} is in the docker group (unlogged path to host root)"
  else
    ok "${DEPLOY_USER} is not in the docker group"
  fi
}

check_sshd_hardening() {
  local out want key val
  out="$(sshd -T 2>/dev/null || true)"
  # `<<<` not a pipe: a `while read` on the right-hand side of a pipe runs in a
  # SUBSHELL, and every ok()/bad() increment to CHECKS and FAILED would be lost
  # when it exited -- the check would report nothing and finish() would see zero.
  while IFS= read -r want; do
    [ -n "$want" ] || continue
    key="${want%% *}"
    val="${want#* }"
    if printf '%s' "$out" | grep -qx "$(printf '%s %s' "$key" "$val" | tr 'A-Z' 'a-z')"; then
      ok "sshd: ${key} ${val}"
    else
      bad "sshd: ${key} is NOT ${val} on this host"
    fi
  done <<< "$SSHD_DIRECTIVES"
}

# apply_all and check_all are deliberately SEPARATE rather than one function
# branching on MODE. --check must be an independent observer of the host: if it
# shared code with apply it would tend to report what apply intended rather than
# what the box is. The cost is a little duplication; the benefit is that a check
# can contradict an apply, which is the only way it is worth running.
apply_all() {
  ensure_deploy_user
  ensure_authorized_key
  ensure_sshd_hardening
}

check_all() {
  check_deploy_user
  check_sshd_hardening
}

finish() {
  if [ "$MODE" = check ]; then
    # A check run that measured nothing is not a pass. Without this, an empty
    # or accidentally-disabled check_all reports "all checks passed" -- the
    # instrument claiming SAFE without having observed anything.
    [ "$CHECKS" -gt 0 ] || die "no checks ran -- the check set is empty, which is not a pass"
    [ "$FAILED" -eq 0 ] || die "${FAILED} check(s) failed"
    note "all checks passed (${CHECKS} checks)"
  fi
}

main() {
  assert_deploy_user_not_reserved
  assert_ssh_pubkey_wellformed
  assert_supported_os
  note "deploy user: ${DEPLOY_USER} (mode: ${MODE})"
  if [ "$MODE" = check ]; then check_all; else apply_all; fi
  finish
}

main "$@"
