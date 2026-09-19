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

# This script parses the OUTPUT of other programs -- `ufw status verbose`,
# `sshd -T`, `id -nG` -- rather than their structured data. ufw's status
# strings are gettext-wrapped, so under a translated locale "Status: active",
# "Default:" and "ALLOW IN" would silently become different text. The failure
# mode is not a visible error: a filter that stops matching returns an empty
# result, and a check built on "empty means clean" (check_firewall's `extra`)
# reports SAFE having measured nothing -- the same silent no-op Fix Round 1
# closed for plain-vs-verbose ufw output, reached this time through locale
# instead of verbosity. Pinned globally, once, rather than per call: later
# checks parsing more program output (Task 5's check_docker) would otherwise
# have to remember to pin it themselves.
export LC_ALL=C

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

ensure_base_packages() {
  note "installing base packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg ufw fail2ban unattended-upgrades
}

ensure_firewall() {
  # Converge, never reset. `ufw --force reset` would drop every rule mid-run --
  # on a re-run that is a window with no firewall on an internet-facing box.
  # Each command below is individually idempotent.
  ufw default deny incoming
  ufw default allow outgoing
  # Allowed BEFORE enable: a default-deny firewall enabled first locks the
  # operator out of the box they are provisioning.
  ufw allow OpenSSH
  ufw --force enable
  note "firewall active: inbound SSH only"
}

ensure_fail2ban() {
  systemctl enable --now fail2ban
  note "fail2ban enabled"
}

ensure_unattended_upgrades() {
  dpkg-reconfigure -f noninteractive unattended-upgrades
  systemctl enable --now unattended-upgrades
  note "unattended security upgrades enabled"
}

check_firewall() {
  # `ufw status verbose`, never plain `ufw status` -- verified against ufw's
  # own src/backend_iptables.py, whose get_status() has:
  #   if r.direction == "in" and not r.forward and not verbose and not show_count:
  #       dir_str = ""
  # Plain (non-verbose) `ufw status` therefore blanks the direction suffix
  # for an ordinary inbound rule: it renders as bare "ALLOW", not "ALLOW IN".
  # An anchored `ALLOW IN` filter against PLAIN output matches nothing at
  # all, so `extra` below would be unconditionally empty and this check
  # would report "no inbound rule beyond SSH" no matter what is actually
  # open -- a silent no-op on the one safety property this task exists to
  # add. Verbose reliably renders the direction for every rule, and also
  # prints the `Default:` policy line the check below needs.
  local status
  status="$(ufw status verbose 2>/dev/null || true)"

  if printf '%s\n' "$status" | grep -q '^Status: active'; then
    ok "firewall active"
  else
    bad "firewall inactive"
  fi

  # The default incoming policy is its own finding: ensure_firewall SETS it,
  # but nothing else here verifies it HOLDS, and a box whose default
  # incoming policy had been flipped to allow would otherwise pass this
  # check cleanly as long as no explicit rule happened to be present.
  local default_line
  default_line="$(printf '%s\n' "$status" | grep '^Default:' || true)"
  case "$default_line" in
    *"deny (incoming)"*) ok "default incoming policy is deny" ;;
    *) bad "default incoming policy is not deny: ${default_line:-no Default: line found}" ;;
  esac

  # Anything beyond SSH on an inbound allow list is a finding: no app port is
  # opened in this design, and the dashboard is reached over an SSH tunnel.
  #
  # The port field ($1) is matched IN FULL against `^(22|OpenSSH)$` (after
  # stripping an optional `/tcp` or `/udp` suffix), not merely checked for
  # containing "22" or "OpenSSH" anywhere in the line. A substring filter
  # (`!/22|OpenSSH/` against the whole line) would be satisfied by a rule on
  # port 8022 or 2222 -- both contain "22" as a substring -- silently hiding
  # an unexpected inbound rule. Under-reporting a security finding is the
  # wrong direction to fail in, so this is over-reporting on purpose: a
  # false "unexpected rule" is a nuisance; a hidden one is an open box.
  #
  # `ALLOW IN`, not bare `ALLOW`, is correct BECAUSE this is verbose output:
  # verbose also renders outbound rules as `ALLOW OUT`, so dropping the `IN`
  # requirement would misreport an outbound rule as inbound drift.
  local extra
  extra="$(printf '%s\n' "$status" | awk '/ALLOW IN/ { port=$1; sub(/\/(tcp|udp)$/,"",port); if (port !~ /^(22|OpenSSH)$/) print }' || true)"
  [ -z "$extra" ] && ok "no inbound rule beyond SSH" \
    || bad "unexpected inbound rule(s): ${extra}"
}

check_fail2ban() {
  systemctl is-active --quiet fail2ban && ok "fail2ban running" \
    || bad "fail2ban not running"
}

ensure_docker() {
  # Docker's own apt repository, never `curl https://get.docker.com | sh`: that
  # executes an unreviewed remote script as root, in a project that pins its base
  # image by digest and re-runs a security audit on every upgrade.
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -s /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  fi
  chmod a+r /etc/apt/keyrings/docker.asc
  # signed-by scopes the key to THIS repository; without it the key is trusted
  # for every repository configured on the box.
  # Parsed with os_release_field, never sourced -- the same reasoning as
  # assert_supported_os's os_release_field above: OS_RELEASE_FILE is
  # environment-overridable, and sourcing an environment-overridable path as
  # root is arbitrary code execution, not a refusal. Fix round 1 found this
  # identical `. "$OS_RELEASE_FILE"` pattern still live here after Task 2's
  # fix closed only the assert_supported_os call site.
  local arch codename
  arch="$(dpkg --print-architecture)"
  codename="$(os_release_field VERSION_CODENAME)"
  [ -n "$codename" ] || codename=noble
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$arch" "$codename" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  # NOTE: no user is added to the docker group here, deliberately. The proxy unit
  # grants it via SupplementaryGroups=docker to hermes-docker-proxy and nothing
  # else; deploy commands use sudo.
  note "docker installed: $(docker --version)"
}

check_docker() {
  systemctl is-active --quiet docker && ok "docker running" || bad "docker not running"

  # hermes-docker-proxy is the only user this design ever puts in the docker
  # group (README.md:957 step 1, which runs AFTER this script). Found here by
  # pattern-matching RESERVED_NAMES rather than typing the name a second
  # time, so the two lists cannot drift apart (Ruling 20).
  local n proxy_name
  proxy_name=""
  for n in "${RESERVED_NAMES[@]}"; do
    case "$n" in *docker-proxy*) proxy_name="$n" ;; esac
  done

  # Field 4 of `getent group` lists only SUPPLEMENTARY members. A user whose
  # PRIMARY gid is docker's gid has full Docker access -- host root -- and
  # NEVER appears there (confirmed during Task 4's format sweep against
  # multiple sources). Both sources are enumerated and unioned; the brief's
  # original single-source `getent group docker | cut -d: -f4` would miss
  # exactly this case (Ruling 19). Formats, per getent(1)/group(5)/passwd(5):
  #   group:  name:passwd:GID:member1,member2,...
  #   passwd: name:passwd:UID:GID:gecos:home:shell
  local group_line gid supplementary primary_members all_members offenders
  group_line="$(getent group docker 2>/dev/null || true)"
  gid="$(printf '%s' "$group_line" | cut -d: -f3)"
  supplementary="$(printf '%s' "$group_line" | cut -d: -f4)"

  primary_members=""
  if [ -n "$gid" ]; then
    primary_members="$(getent passwd 2>/dev/null \
      | awk -F: -v gid="$gid" '$4 == gid { print $1 }' || true)"
  fi

  all_members="$(printf '%s\n%s\n' "$(printf '%s' "$supplementary" | tr ',' '\n')" "$primary_members" \
    | sed '/^$/d' | sort -u || true)"

  # Allow exactly hermes-docker-proxy (Ruling 20): provision.sh runs BEFORE
  # README.md:957 step 1, so an empty group is correct at provision time, but
  # an operator re-running --check AFTER that step must not get a false alarm
  # from a bare "no members" rule -- a check that cries wolf gets ignored.
  offenders="$(printf '%s\n' "$all_members" | grep -vx -- "$proxy_name" || true)"
  if [ -z "$offenders" ]; then
    ok "docker group has no members beyond ${proxy_name:-hermes-docker-proxy}"
  else
    bad "docker group has unexpected member(s): $(printf '%s' "$offenders" | tr '\n' ' ')"
  fi
}

# apply_all and check_all are deliberately SEPARATE rather than one function
# branching on MODE. --check must be an independent observer of the host: if it
# shared code with apply it would tend to report what apply intended rather than
# what the box is. The cost is a little duplication; the benefit is that a check
# can contradict an apply, which is the only way it is worth running.
apply_all() {
  ensure_base_packages
  ensure_deploy_user
  ensure_authorized_key
  ensure_sshd_hardening
  ensure_firewall
  ensure_fail2ban
  ensure_unattended_upgrades
  ensure_docker
}

check_all() {
  check_deploy_user
  check_sshd_hardening
  check_firewall
  check_fail2ban
  check_docker
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
