# VPS Provisioning and Bring-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an idempotent `provision.sh` that takes a bare Ubuntu 24.04 box to a hardened Docker host, a stdlib-only test suite that guards it, and a bring-up runbook that carries an operator from a bought VPS to the point `README.md:957` step 1 already assumes.

**Architecture:** One shell script with two independent top-level paths — `apply` and `--check`. `--check` re-derives every fact from the host rather than sharing code with `apply`, so it is an independent observer of the box rather than a restatement of what `apply` intended. Testability is designed in: the reserved-name guard runs before the OS gate so it is reachable on any host, and the OS gate reads `OS_RELEASE_FILE` so tests point it at a fixture instead of the runner's real OS. That turns four guards into behavioural tests rather than text assertions.

**Tech Stack:** Bash (no dependencies beyond coreutils, `ufw`, `apt`), Python 3 stdlib `unittest` for the test suite, GitHub Actions for CI.

**Spec:** `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md`

## Global Constraints

- Target is **Ubuntu 24.04 LTS**; the script refuses any other release unless `--force-os` is passed (spec §3.5).
- `provision.sh` starts with `set -euo pipefail` (spec §3).
- The deploy user is **never** added to the `docker` group; deploy commands use `sudo` (spec §3.1).
- **No pipe-to-shell** anywhere — Docker comes from its apt repository (spec §3.3).
- **No `ufw --force reset`** — converge only (spec §3).
- **No truncating redirect** onto `authorized_keys` — append if absent (spec §3).
- Tests are **Python 3 stdlib only** (project norm: the proxy may not grow a dependency, and neither may its guards).
- Tests live in `deploy/` and are invoked as their **own CI step** — `run-bin-tests.sh` discovers `bin/*.test.py` only.
- **`provision.sh` knows nothing about Hermes** beyond `RESERVED_NAMES`. The Hermes users, groups, governance store and units stay `README.md:957`'s job (spec §1).
- **No kill switch is created by any artifact here.** Mutation stays disabled.
- No credential value, sha12, client name, customer id or campaign id in any tracked file. The runbook uses placeholders only.
- `main` is protected — land via PR, and check CI on the **merge commit**, not only the PR.
- **Stage by explicit path only.** Never `git add -A`, `git add .project-brain/`, or `git add evals/`. The operator's 5 tracked and 46 untracked working-tree entries are not part of this work.

## File Structure

| File | Responsibility |
|---|---|
| `infra/hermes-agent/deploy/provision.sh` (create) | Host hardening + Docker Engine. Two paths: apply, `--check`. |
| `infra/hermes-agent/deploy/provision.test.py` (create) | Guards the script. Behavioural where reachable, textual only where it cannot be. |
| `.github/workflows/ci.yml` (modify, after line 108) | Registers the suite as its own step. |
| `infra/hermes-agent/deploy/BRING-UP.md` (create) | The operator runbook, phases 0–6. |
| `infra/hermes-agent/.env.example` (modify) | Corrects the `HERMES_GOVERNANCE_DIR` placeholder. |
| `infra/hermes-agent/README.md` (modify, near line 957) | Links the deploy sequence to the runbook. |

---

### Task 1: Script skeleton, reserved-name guard, and the CI step

The guard that makes spec §2.1 impossible, plus the harness every later task extends. CI registration is folded in here so every subsequent task's suite runs in CI from the start.

**Files:**
- Create: `infra/hermes-agent/deploy/provision.sh`
- Create: `infra/hermes-agent/deploy/provision.test.py`
- Modify: `.github/workflows/ci.yml` (after line 108)

**Interfaces:**
- Consumes: nothing.
- Produces: `provision.sh` accepting `--check` and `--force-os`; env vars `DEPLOY_USER` (default `hermesops`), `SSH_PUBKEY`, `OS_RELEASE_FILE` (default `/etc/os-release`); shell array `RESERVED_NAMES`; helpers `die()`, `note()`, `ok()`, `bad()`; `MODE` (`apply`|`check`). Later tasks add functions and call them from `main`.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/deploy/provision.test.py`:

```python
"""WHAT THIS PROVES, AND WHAT IT DOES NOT.

Some of this suite RUNS provision.sh and asserts on its exit status and stderr.
Those tests observe behaviour and are worth what they look like. The rest assert
on the script's TEXT, because the behaviour they describe needs a root Ubuntu
host -- and a text assertion proves only that the script SAYS the right thing.

Nothing here proves a box ends up hardened: not that ufw is active, not that
sshd rejects passwords, not that Docker installed. Only `provision.sh --check`
against a real host observes any of that, and BRING-UP.md phase 1 is where it
runs.

Six tests in this project have passed for reasons unrelated to their claims, and
reading found none of them. Every text assertion below is therefore written to be
proven by making it fail against a deliberately broken copy of the script -- see
each test's docstring for the mutation that proves it.

Discovery note: run-bin-tests.sh globs bin/*.test.py, so this file is invisible
to it, exactly as deploy/units.test.py is. CI invokes it as its own step.
"""
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "provision.sh")


def script_text():
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def run(args=(), env=None):
    """Run provision.sh and capture (returncode, stdout, stderr)."""
    e = dict(os.environ)
    e.pop("DEPLOY_USER", None)
    e.pop("SSH_PUBKEY", None)
    if env:
        e.update(env)
    p = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=e)
    return p.returncode, p.stdout, p.stderr


class TestShellHygiene(unittest.TestCase):
    def test_the_script_parses(self):
        """bash -n executes the real parser, so this is not a text assertion."""
        p = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_it_is_strict(self):
        """Mutation that proves it: delete the line; this fails."""
        self.assertIn("set -euo pipefail", script_text())


class TestReservedNames(unittest.TestCase):
    """The spec's 2.1 finding. A deploy user named `hermes` makes adduser create a
    GROUP named hermes at the next free gid; README.md:957 step 1's
    `getent group hermes || groupadd -g 10000 hermes` then skips, gid 10000 never
    exists, and the governance store is unreadable to the uid-10000 executor --
    exit 3 mid-apply, after a live account change has landed.

    These RUN the script. The guard is placed before the OS gate precisely so it is
    reachable on any host, which is what makes these behavioural rather than textual.
    """

    def test_each_reserved_name_is_refused(self):
        for name in ("hermes", "hermes-broker", "hermes-docker-proxy", "hermes-rail"):
            rc, _, err = run(["--check"], {"DEPLOY_USER": name})
            self.assertNotEqual(rc, 0, "DEPLOY_USER=%s was accepted" % name)
            self.assertIn("reserved", err.lower(), err)

    def test_the_refusal_names_the_remedy(self):
        """A refusal an operator cannot act on gets worked around at 2am."""
        _, _, err = run(["--check"], {"DEPLOY_USER": "hermes"})
        self.assertIn("hermesops", err)

    def test_an_ordinary_name_clears_this_guard(self):
        """The half of a control that usually goes unchecked: show the instrument
        reporting 'safe' when the target really is safe. An ordinary name must NOT
        be refused for being reserved -- it may still fail later checks."""
        _, _, err = run(["--check"], {"DEPLOY_USER": "hermesops"})
        self.assertNotIn("reserved", err.lower(), err)

    def test_the_default_is_not_reserved(self):
        _, _, err = run(["--check"])
        self.assertNotIn("reserved", err.lower(), err)


class TestArgumentHandling(unittest.TestCase):
    def test_an_unknown_argument_is_refused(self):
        rc, _, err = run(["--definitely-not-a-flag"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown argument", err.lower(), err)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: every test ERRORs — `provision.sh` does not exist yet.

- [ ] **Step 3: Write the minimal script**

Create `infra/hermes-agent/deploy/provision.sh`:

```bash
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
# runner's real release. Defaults to the real file on a real box.
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"

MODE=apply
FORCE_OS=0
FAILED=0

die()  { printf 'provision: %s\n' "$*" >&2; exit 1; }
note() { printf '[provision] %s\n' "$*"; }
ok()   { printf '  OK    %s\n' "$*"; }
bad()  { printf '  DRIFT %s\n' "$*" >&2; FAILED=$((FAILED + 1)); }

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

main() {
  assert_deploy_user_not_reserved
  note "deploy user: ${DEPLOY_USER} (mode: ${MODE})"
}

main "$@"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: 7 tests, all PASS.

- [ ] **Step 5: Prove the reserved-name guard actually guards**

Temporarily empty the array — `RESERVED_NAMES=()` — then run the suite.
Expected: `test_each_reserved_name_is_refused` and `test_the_refusal_names_the_remedy` FAIL.
Restore the array and re-run; expected: all PASS.

An inert mutation is itself a finding: if the suite stays green with the array emptied, stop and investigate rather than accepting the green.

- [ ] **Step 6: Register the suite in CI**

In `.github/workflows/ci.yml`, directly after the existing systemd-unit step (line 107–108), add:

```yaml
      - name: Provisioning script suite
        run: python3 infra/hermes-agent/deploy/provision.test.py
```

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/deploy/provision.sh \
        infra/hermes-agent/deploy/provision.test.py \
        .github/workflows/ci.yml
git commit -m "$(cat <<'MSG'
feat(hermes/deploy): provision.sh skeleton and the reserved-name guard

A deploy user named `hermes` would make adduser create a group named hermes at
the next free gid; README.md:957 step 1's guard would then skip creating gid
10000, and the governance store would be unreadable to the uid-10000 executor --
exit 3 mid-apply. The guard runs before the OS gate, which also makes it
reachable on any host and so behaviourally testable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: OS gate and `--check` scaffolding

**Files:**
- Modify: `infra/hermes-agent/deploy/provision.sh`
- Modify: `infra/hermes-agent/deploy/provision.test.py`

**Interfaces:**
- Consumes: `die()`, `note()`, `ok()`, `bad()`, `MODE`, `FORCE_OS`, `OS_RELEASE_FILE`, `FAILED` from Task 1.
- Produces: `assert_supported_os()`; `check_all()` and `apply_all()` dispatched from `main`; `finish()` which exits 1 when `FAILED` is non-zero. Later tasks append their `ensure_*` call to `apply_all` and their `check_*` call to `check_all`.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/deploy/provision.test.py`, before the `if __name__` block:

```python
import tempfile


def os_release(version_id, name="Ubuntu"):
    """Write a throwaway os-release fixture and return its path."""
    fd, path = tempfile.mkstemp(prefix="os-release-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write('NAME="%s"\nVERSION_ID="%s"\n' % (name, version_id))
    return path


class TestOsGate(unittest.TestCase):
    """Every behaviour this script relies on is 24.04-specific: sshd_config.d
    Include, socket-activated ssh, and the apt source. A silent partial success on
    another release is worse than a refusal.

    OS_RELEASE_FILE is injected so these run identically on darwin and on the CI
    runner -- asserting against the runner's real OS would make the result depend
    on where the suite happened to run.
    """

    def test_a_wrong_release_is_refused(self):
        path = os_release("22.04")
        try:
            rc, _, err = run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertNotEqual(rc, 0)
            self.assertIn("24.04", err)
        finally:
            os.unlink(path)

    def test_a_non_ubuntu_distro_is_refused(self):
        path = os_release("40", name="Fedora")
        try:
            rc, _, err = run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertNotEqual(rc, 0)
            self.assertIn("ubuntu", err.lower())
        finally:
            os.unlink(path)

    def test_force_os_bypasses_the_gate(self):
        """The escape hatch has to work, or it will be removed at 2am."""
        path = os_release("22.04")
        try:
            _, _, err = run(["--check", "--force-os"], {"OS_RELEASE_FILE": path})
            self.assertNotIn("24.04", err)
        finally:
            os.unlink(path)

    def test_the_supported_release_clears_the_gate(self):
        """Control: the instrument must report 'safe' when the target IS safe."""
        path = os_release("24.04")
        try:
            _, _, err = run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertNotIn("refusing", err.lower())
        finally:
            os.unlink(path)

    def test_a_missing_os_release_is_refused(self):
        rc, _, err = run(["--check"], {"OS_RELEASE_FILE": "/nonexistent/os-release"})
        self.assertNotEqual(rc, 0)
        self.assertIn("os-release", err.lower())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: the five `TestOsGate` tests FAIL — no gate exists, so the script exits 0 and prints nothing matching.

- [ ] **Step 3: Implement the gate and the two paths**

In `provision.sh`, add after `assert_deploy_user_not_reserved()`:

```bash
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
    [ "$FAILED" -eq 0 ] || { printf 'provision: %d check(s) failed\n' "$FAILED" >&2; exit 1; }
    note "all checks passed"
  fi
}
```

Replace `main()` with:

```bash
main() {
  assert_deploy_user_not_reserved
  assert_supported_os
  note "deploy user: ${DEPLOY_USER} (mode: ${MODE})"
  if [ "$MODE" = check ]; then check_all; else apply_all; fi
  finish
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: 12 tests, all PASS.

- [ ] **Step 5: Prove the gate guards**

Change `[ "$version" = "24.04" ]` to `[ -n "$version" ]`, then run the suite.
Expected: `test_a_wrong_release_is_refused` FAILS. Restore and re-run; all PASS.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/deploy/provision.sh infra/hermes-agent/deploy/provision.test.py
git commit -m "$(cat <<'MSG'
feat(hermes/deploy): OS gate and the apply/check split

apply_all and check_all are separate rather than one function branching on mode:
--check has to be an independent observer of the host, or it reports what apply
intended rather than what the box is.

OS_RELEASE_FILE is injectable so the gate's tests do not depend on where the
suite runs.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: Deploy user and SSH hardening

The lockout-sensitive task. Validate-then-reload, a drop-in rather than `sed -i`, and an appended key rather than a truncating redirect.

**Files:**
- Modify: `infra/hermes-agent/deploy/provision.sh`
- Modify: `infra/hermes-agent/deploy/provision.test.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces: `ensure_deploy_user()`, `ensure_authorized_key()`, `ensure_sshd_hardening()`, `check_deploy_user()`, `check_sshd_hardening()`; constant `SSHD_DROPIN=/etc/ssh/sshd_config.d/10-hermes-hardening.conf`.

- [ ] **Step 1: Write the failing test**

Append to `provision.test.py`, before the `if __name__` block:

```python
def line_index(needle, text=None):
    """Index of the first line containing needle, or -1."""
    lines = (text if text is not None else script_text()).splitlines()
    for i, line in enumerate(lines):
        if needle in line:
            return i
    return -1


class TestSshHardening(unittest.TestCase):
    """These are TEXT assertions: exercising sshd needs a root Ubuntu host. They
    prove the script says the right thing, not that a box ends up hardened.
    `--check` on a real host is what observes that (BRING-UP.md phase 1).
    """

    def test_validation_precedes_every_reload(self):
        """The anti-lockout gate. Ordering, not presence: `sshd -t` appearing
        anywhere in the file would satisfy a substring check while sitting AFTER
        the reload, which is the same bug as an ExecStartPre that never runs.

        Mutation that proves it: move the `sshd -t` line below the reload; this
        fails while a substring check would not.
        """
        validate = line_index("sshd -t")
        self.assertNotEqual(validate, -1, "no sshd -t validation found")
        text = script_text().splitlines()
        reloads = [i for i, l in enumerate(text)
                   if "systemctl" in l and "reload" in l and "ssh" in l]
        self.assertTrue(reloads, "no ssh reload found")
        for r in reloads:
            self.assertLess(validate, r,
                            "sshd -t (line %d) must precede the reload on line %d"
                            % (validate + 1, r + 1))

    def test_it_reloads_rather_than_restarts(self):
        """restart drops the operator's live session -- the one recovery path open
        while the new config is being proven."""
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if "systemctl" in s and "ssh" in s:
                self.assertNotIn("restart", s, s)

    def test_hardening_uses_a_dropin_not_sed(self):
        """24.04 ships `Include /etc/ssh/sshd_config.d/*.conf`. Rewriting the main
        file with sed is neither idempotent nor reviewable."""
        text = script_text()
        self.assertIn("/etc/ssh/sshd_config.d/", text)
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            self.assertNotIn("sed -i", s, "sed -i against sshd_config: %s" % s)

    def test_the_dropin_sets_the_four_directives(self):
        text = script_text()
        for directive in ("PasswordAuthentication no",
                          "PermitRootLogin no",
                          "KbdInteractiveAuthentication no",
                          "PubkeyAuthentication yes"):
            self.assertIn(directive, text)


class TestAuthorizedKeys(unittest.TestCase):
    def test_the_key_is_appended_never_truncated(self):
        """`>` destroys every other key on the box, including on a re-run.

        Mutation that proves it: change the append to `> "$akeys"`; this fails.
        """
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#") or "authorized_keys" not in s:
                continue
            self.assertNotIn("> ", s.replace(">> ", ""),
                             "truncating redirect onto authorized_keys: %s" % s)

    def test_it_checks_before_appending(self):
        """Idempotency: a re-run must not add a second copy of the same key."""
        self.assertIn("grep -qxF", script_text())


class TestDeployUserGroups(unittest.TestCase):
    def test_the_deploy_user_never_joins_the_docker_group(self):
        """Operator decision 2026-09-18. docker-group membership is an unlogged
        path to host root; keeping it empty also makes `getent group docker` a
        meaningful check on the real box, so units.test.py's 'the broker is not in
        docker' invariant becomes true of the HOST and not only of the unit files.

        Mutation that proves it: add `usermod -aG docker "$DEPLOY_USER"`; this fails.
        """
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if "usermod" in s or "adduser" in s or "gpasswd" in s:
                self.assertNotIn("docker", s, s)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: `test_validation_precedes_every_reload`, `test_hardening_uses_a_dropin_not_sed`, `test_the_dropin_sets_the_four_directives` and `test_it_checks_before_appending` FAIL. The three negative assertions pass vacuously for now — Step 5 proves they can fail.

- [ ] **Step 3: Implement**

Add to `provision.sh`, after `assert_supported_os()`:

```bash
SSHD_DROPIN=/etc/ssh/sshd_config.d/10-hermes-hardening.conf

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
  # rewriting the same drop-in is naturally idempotent.
  cat > "$SSHD_DROPIN" <<'DROPIN'
# Managed by infra/hermes-agent/deploy/provision.sh. Edits will be overwritten.
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
DROPIN
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
  id "$DEPLOY_USER" >/dev/null 2>&1 && ok "user ${DEPLOY_USER} exists" \
    || bad "user ${DEPLOY_USER} missing"
  if id -nG "$DEPLOY_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
    bad "${DEPLOY_USER} is in the docker group (unlogged path to host root)"
  else
    ok "${DEPLOY_USER} is not in the docker group"
  fi
}

check_sshd_hardening() {
  local out
  out="$(sshd -T 2>/dev/null || true)"
  printf '%s' "$out" | grep -qx 'passwordauthentication no' \
    && ok "sshd: passwords refused" || bad "sshd: passwords still accepted"
  printf '%s' "$out" | grep -qx 'permitrootlogin no' \
    && ok "sshd: root login refused" || bad "sshd: root login still permitted"
}
```

Then wire them up:

```bash
apply_all() {
  ensure_deploy_user
  ensure_authorized_key
  ensure_sshd_hardening
}

check_all() {
  check_deploy_user
  check_sshd_hardening
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: 19 tests, all PASS.

- [ ] **Step 5: Prove the three negative assertions can fail**

They passed vacuously in Step 2 — an assertion that has never failed proves nothing. Apply each mutation, run the suite, confirm the named test fails, then revert:

| Mutation | Must fail |
|---|---|
| Move the `sshd -t ...` line below `systemctl reload ssh` | `test_validation_precedes_every_reload` |
| Change `>> "$akeys"` to `> "$akeys"` | `test_the_key_is_appended_never_truncated` |
| Add `usermod -aG docker "$DEPLOY_USER"` to `ensure_deploy_user` | `test_the_deploy_user_never_joins_the_docker_group` |

If any mutation leaves the suite green, that is the finding — stop and fix the assertion before continuing.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/deploy/provision.sh infra/hermes-agent/deploy/provision.test.py
git commit -m "$(cat <<'MSG'
feat(hermes/deploy): deploy user and SSH hardening

Drop-in rather than sed against sshd_config, `sshd -t` before the reload, reload
rather than restart, and an appended authorized_key rather than a truncating
redirect that would delete every other key on the box.

The deploy user goes in sudo, never docker: an empty docker group keeps
`getent group docker` a meaningful check on the real host, so units.test.py's
"the broker is not in docker" invariant becomes true of the box and not only of
the unit files.

Each negative assertion was proven by making it fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: Firewall, fail2ban, and unattended upgrades

**Files:**
- Modify: `infra/hermes-agent/deploy/provision.sh`
- Modify: `infra/hermes-agent/deploy/provision.test.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `ensure_base_packages()`, `ensure_firewall()`, `ensure_fail2ban()`, `ensure_unattended_upgrades()`, `check_firewall()`, `check_fail2ban()`.

- [ ] **Step 1: Write the failing test**

Append to `provision.test.py`:

```python
class TestFirewall(unittest.TestCase):
    def test_it_never_resets_the_firewall(self):
        """`ufw --force reset` drops every rule mid-run. On a re-run that is a
        window with no firewall, on a box reachable from the internet.

        Mutation that proves it: add `ufw --force reset`; this fails.
        """
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if "ufw" in s:
                self.assertNotIn("reset", s, s)

    def test_ssh_is_allowed_before_the_firewall_is_enabled(self):
        """Ordering: enabling a default-deny firewall before allowing SSH locks the
        operator out of the box they are provisioning.

        Mutation that proves it: move the `ufw allow OpenSSH` line below
        `ufw --force enable`; this fails.
        """
        allow = line_index("ufw allow OpenSSH")
        enable = line_index("ufw --force enable")
        self.assertNotEqual(allow, -1, "no `ufw allow OpenSSH` found")
        self.assertNotEqual(enable, -1, "no `ufw --force enable` found")
        self.assertLess(allow, enable,
                        "OpenSSH must be allowed (line %d) before enable (line %d)"
                        % (allow + 1, enable + 1))

    def test_the_default_policy_is_deny_incoming(self):
        self.assertIn("ufw default deny incoming", script_text())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: `test_ssh_is_allowed_before_the_firewall_is_enabled` and `test_the_default_policy_is_deny_incoming` FAIL.

- [ ] **Step 3: Implement**

Add to `provision.sh`:

```bash
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
  if ufw status 2>/dev/null | grep -q '^Status: active'; then
    ok "firewall active"
  else
    bad "firewall inactive"
  fi
  # Anything beyond SSH on an inbound allow list is a finding: no app port is
  # opened in this design, and the dashboard is reached over an SSH tunnel.
  local extra
  extra="$(ufw status 2>/dev/null | awk '/ALLOW IN/ && !/22|OpenSSH/ {print}' || true)"
  [ -z "$extra" ] && ok "no inbound rule beyond SSH" \
    || bad "unexpected inbound rule(s): ${extra}"
}

check_fail2ban() {
  systemctl is-active --quiet fail2ban && ok "fail2ban running" \
    || bad "fail2ban not running"
}
```

Extend the two paths — `ensure_base_packages` runs first because everything after it needs those packages:

```bash
apply_all() {
  ensure_base_packages
  ensure_deploy_user
  ensure_authorized_key
  ensure_sshd_hardening
  ensure_firewall
  ensure_fail2ban
  ensure_unattended_upgrades
}

check_all() {
  check_deploy_user
  check_sshd_hardening
  check_firewall
  check_fail2ban
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: 22 tests, all PASS.

- [ ] **Step 5: Prove the two ordering and negative assertions can fail**

| Mutation | Must fail |
|---|---|
| Add `ufw --force reset` above `ufw default deny incoming` | `test_it_never_resets_the_firewall` |
| Move `ufw allow OpenSSH` below `ufw --force enable` | `test_ssh_is_allowed_before_the_firewall_is_enabled` |

Revert both after confirming. An inert mutation is itself a finding.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/deploy/provision.sh infra/hermes-agent/deploy/provision.test.py
git commit -m "$(cat <<'MSG'
feat(hermes/deploy): firewall, fail2ban, unattended upgrades

Converge rather than reset: `ufw --force reset` would drop every rule mid-run,
which on a re-run is a window with no firewall on an internet-facing box. SSH is
allowed before enable, asserted by line index rather than presence.

check_firewall treats any inbound rule beyond SSH as drift -- no app port is
opened in this design and the dashboard is reached over a tunnel.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 5: Docker Engine from the apt repository

**Files:**
- Modify: `infra/hermes-agent/deploy/provision.sh`
- Modify: `infra/hermes-agent/deploy/provision.test.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `ensure_docker()`, `check_docker()`.

- [ ] **Step 1: Write the failing test**

Append to `provision.test.py`:

```python
class TestDockerInstall(unittest.TestCase):
    def test_nothing_is_piped_into_a_shell(self):
        """`curl ... | sh` executes an unreviewed remote script as root. This
        project pins its base image by digest and re-audits on every upgrade; a
        piped root installer in the provisioning path contradicts that for no gain.

        Mutation that proves it: add `curl -fsSL https://get.docker.com | sh`;
        this fails.
        """
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            self.assertNotRegex(s, r"\|\s*(sudo\s+)?(ba)?sh\b",
                                "pipe-to-shell: %s" % s)

    def test_docker_comes_from_the_apt_repository(self):
        text = script_text()
        self.assertIn("download.docker.com", text)
        self.assertIn("docker-ce", text)
        self.assertIn("docker-compose-plugin", text)

    def test_the_repository_key_lands_in_a_keyring(self):
        """An apt source without a signed-by keyring trusts the key for every
        repository on the box."""
        text = script_text()
        self.assertIn("/etc/apt/keyrings/docker.asc", text)
        self.assertIn("signed-by=", text)

    def test_the_docker_group_is_left_empty_of_humans(self):
        """Task 3 asserts the deploy user never joins it. This asserts the script
        never adds ANY user to docker -- the proxy unit's SupplementaryGroups is
        the only membership this design has, and systemd grants that, not this
        script."""
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if "docker" in s and ("usermod" in s or "gpasswd" in s or "adduser" in s):
                self.fail("script adds a user to the docker group: %s" % s)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: `test_docker_comes_from_the_apt_repository` and `test_the_repository_key_lands_in_a_keyring` FAIL.

- [ ] **Step 3: Implement**

Add to `provision.sh`:

```bash
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
  local arch codename
  arch="$(dpkg --print-architecture)"
  codename="$(. "$OS_RELEASE_FILE" >/dev/null 2>&1; printf '%s' "${VERSION_CODENAME:-noble}")"
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
  local members
  members="$(getent group docker | cut -d: -f4)"
  # README.md:957 step 1 puts hermes-docker-proxy in this group, and
  # units.test.py asserts the broker is not in it. Keeping every human out is
  # what makes this check meaningful on the real host.
  [ -z "$members" ] && ok "docker group has no direct members" \
    || bad "docker group has members: ${members}"
}
```

Extend the two paths:

```bash
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/deploy/provision.test.py -v`
Expected: 26 tests, all PASS.

- [ ] **Step 5: Prove the pipe-to-shell assertion can fail**

Add `curl -fsSL https://get.docker.com | sh` to `ensure_docker`, run the suite.
Expected: `test_nothing_is_piped_into_a_shell` FAILS. Revert and re-run.

- [ ] **Step 6: Run every suite, then commit**

```bash
python3 infra/hermes-agent/deploy/provision.test.py
python3 infra/hermes-agent/deploy/units.test.py
infra/hermes-agent/bin/run-bin-tests.sh
node scripts/run-all-tests.js
```

Expected: 26/26, 11/11, 27/27 suites, 22/22 suites. Capture each exit status directly — never `cmd | tail`, which takes its status from `tail` and has misreported an exit code three times in this project.

```bash
git add infra/hermes-agent/deploy/provision.sh infra/hermes-agent/deploy/provision.test.py
git commit -m "$(cat <<'MSG'
feat(hermes/deploy): Docker Engine from the apt repository

Never `curl https://get.docker.com | sh`: that runs an unreviewed remote script
as root in a project that pins its base image by digest. The key lands in a
keyring and the source is signed-by scoped, so it is not trusted for every
repository on the box.

No user is added to the docker group. The proxy unit grants it via
SupplementaryGroups and nothing else does, which is what makes check_docker's
"no direct members" assertion meaningful on the real host.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 6: The runbook, the `.env.example` correction, and the README link

**Files:**
- Create: `infra/hermes-agent/deploy/BRING-UP.md`
- Modify: `infra/hermes-agent/.env.example` (the `HERMES_GOVERNANCE_DIR` block)
- Modify: `infra/hermes-agent/README.md` (the `## VPS deploy sequence` heading area, ~line 957)

**Interfaces:**
- Consumes: `provision.sh` and its `--check` mode from Tasks 1–5.
- Produces: no code. `BRING-UP.md` is the entry point `README.md` links to.

- [ ] **Step 1: Write `infra/hermes-agent/deploy/BRING-UP.md`**

Write the runbook with these seven phases, in order. Content requirements per phase:

**Phase 0 — buy the box.** Hostinger KVM 2 (2 vCPU / 8 GB RAM / 100 GB NVMe), Ubuntu 24.04 LTS, plain OS template — **not** a Docker-preinstalled image, since this project pins deliberately. Sizing rationale: the amd64 base image is 33 layers / 0.95 GB compressed (measured 2026-09-18 against the registry), so budget ~10 GB for Docker alone; 8 GB RAM because the gateway spawns `claude -p` executor subprocesses and one-shot mutator containers. Generate the keypair locally with `ssh-keygen -t ed25519`.

**Phase 1 — harden.** Copy `provision.sh` to the box. Run as root:
`DEPLOY_USER=hermesops SSH_PUBKEY="ssh-ed25519 AAAA..." bash provision.sh`, then
`bash provision.sh --check`.

State the **lockout protocol** as a numbered sequence, because SSH hardening is the ordinary way a fresh VPS is bricked:
1. Keep the original root session open. Do not close it.
2. In a **second** terminal, prove `ssh hermesops@<ip>` works with the key.
3. Prove `sudo -v` works as `hermesops`.
4. Only then close the first session.
5. Recovery if locked out: Hostinger's browser console (VPS → Overview → Browser terminal), which does not use SSH.

Also in this phase, verify the gid-10000 precondition **before** README:957 runs, since the spec's §2.1 is an inference until observed:
```
getent group hermes    # expect: empty, or a group at gid 10000
getent group docker    # expect: no members yet
```
A group named `hermes` at any gid other than 10000 is the §2.1 collision. Stop and reconcile deliberately.

**Phase 2 — lay out the box.** State the layout as a table and name the units as the reason it is not free-choice:

| Path | Holds | Required by |
|---|---|---|
| `/opt/projects/claude_code` | this repo | `../../../claude-google-ads` must resolve to `/opt/projects/claude-google-ads` |
| `/opt/projects/claude-google-ads` | the ads repo | `hermes-docker-proxy.service:36` |
| `/opt/hermes-agent` | `bin/`, `registry/`, `data/spool` | `hermes-broker.service:17,22,27,29`; `hermes-docker-proxy.service:26,37,38` |
| `/var/lib/hermes/governance` | the governance store | `hermes-broker.service:20,21,28,36`; `hermes-docker-proxy.service:32-35` |

Note explicitly that `/opt/hermes-agent` and `/opt/projects/claude_code/infra/hermes-agent` must end up being the same directory, and that whether a symlink satisfies Docker's bind-source comparison is **the open question phase 5 measures** — do not assume it either way.

**Phase 3 — `.env`.** `cp .env.example .env`, set `ANTHROPIC_API_KEY` (dummy this wave) and `HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance`. Two prohibitions in bold: **never run `docker compose config`** (it renders `env_file` secrets in cleartext), and **no real client credentials this wave** — real money-spending credentials are gated behind a security review that is downstream of this runbook.

**Phase 4 — build and start.** `sudo docker compose up -d --build`, then the README "First run" smoke checks (`hermes gateway status`, `claude --version`).

**Phase 5 — measure the bind paths.** Reproduce the spec §5 phase 5 commands verbatim, with the reasoning: the proxy is not running yet, so its log is not the instrument; `HostConfig.Binds` is the same string set it would compare.
```
sudo docker compose --profile tools create ads-mutator
sudo docker inspect <container> --format '{{json .HostConfig.Binds}}'
sudo docker rm <container>
```
Then diff each bind source against the seven `--allow-bind` values in `hermes-docker-proxy.service`. **On any mismatch: stop.** Record it as a finding, do not widen the allow-list. State why in one line — a rail that refuses is a refusal, not a breach, and widening a policy to make bring-up pass is the reflex the handoff's §3 and §5 name.

**Phase 6 — hand off.** To `README.md:957` steps 1–5, then to `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md` §2–§5. State plainly: **the kill switch is not created by this runbook, and mutation stays disabled.**

Close with a short "What this runbook does not do" block: it does not create the Hermes users or groups, install the units, provision credentials, or enable mutation.

- [ ] **Step 2: Verify every path and line citation in the runbook**

```bash
sed -n '17p;20p;21p;22p;27p;28p;29p;36p' infra/hermes-agent/deploy/hermes-broker.service
sed -n '26p;32,38p' infra/hermes-agent/deploy/hermes-docker-proxy.service
```
Expected: each cited line contains the path the table claims. A document that cites a line number wrongly is worse than one that cites none, because it will be trusted.

- [ ] **Step 3: Correct `.env.example`**

Replace the `HERMES_GOVERNANCE_DIR` block's last two lines with:

```
# Absolute host path to the governance store. NOT free-choice: the systemd units
# hardcode this value (hermes-broker.service:20-21, hermes-docker-proxy.service:32-35),
# so a different path here means the proxy DENIES the mutator's binds at runtime.
# Must be OUTSIDE this repo (bind-mounted into the container) and OUTSIDE ./data.
# Create it mode 700. Compose does not expand ~, so write the path in full.
HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance
```

- [ ] **Step 4: Link the runbook from the README**

Immediately under the `## VPS deploy sequence` heading (line 957), insert:

```markdown
> **Provisioning a box first?** `deploy/BRING-UP.md` covers phases 0–5 — buying and
> hardening the host, the on-box layout these units require, `.env`, the compose
> build, and the bind-path measurement — and hands off to step 1 below. The steps
> here assume a host that already has Docker, both repos, and the governance store.
```

- [ ] **Step 5: Verify the full suite and the redaction scan**

```bash
python3 infra/hermes-agent/deploy/provision.test.py
python3 infra/hermes-agent/deploy/units.test.py
infra/hermes-agent/bin/run-bin-tests.sh
node scripts/run-all-tests.js
```
Expected: 26/26, 11/11, 27/27, 22/22.

Then confirm no client-identifying string entered any new file, and **pair the scan with a live control** — a scan whose control does not fire proves nothing:
```bash
grep -rniE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}' \
  infra/hermes-agent/deploy/BRING-UP.md \
  infra/hermes-agent/deploy/provision.sh \
  infra/hermes-agent/deploy/provision.test.py ; echo "scan exit: $?"
printf 'control: 555-123-4567\n' | grep -niE '[0-9]{3}-[0-9]{3}-[0-9]{4}'
```
Expected: the scan finds nothing (exit 1), and the control DOES match — proving the pattern fires.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/deploy/BRING-UP.md \
        infra/hermes-agent/.env.example \
        infra/hermes-agent/README.md
git commit -m "$(cat <<'MSG'
docs(hermes): VPS bring-up runbook, and pin the governance path

BRING-UP.md carries an operator from a bought box to the point README.md:957
step 1 assumes: hardening with a lockout protocol, the on-box layout the units
dictate, .env, the compose build, and the bind-path measurement that stops on a
mismatch rather than widening the allow-list.

.env.example's HERMES_GOVERNANCE_DIR placeholder becomes the value the units
actually hardcode. A different path there means the proxy denies the mutator's
binds at runtime -- fail-closed, but diagnosed as a broken rail rather than a
path mismatch.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Landing the work

- [ ] **Push and open the PR**

```bash
git push -u origin feat/hermes-vps-provisioning
gh pr create --base main --title "VPS provisioning and bring-up" --body "$(cat <<'BODY'
Provisions the deploy target the 2026-09-17 handoff assumes but which does not
exist: an idempotent `provision.sh`, its suite, and `deploy/BRING-UP.md`.

Spec: `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md`

## What is proven

- `provision.sh --check` refuses every reserved DEPLOY_USER, refuses a non-24.04
  release, and refuses an unknown argument. These RUN the script; the guard sits
  before the OS gate so it is reachable on any host.
- Every negative and ordering assertion was proven by making it fail: emptied
  RESERVED_NAMES, `sshd -t` moved below the reload, `>` for `>>` on
  authorized_keys, `usermod -aG docker`, `ufw --force reset`, `ufw allow OpenSSH`
  moved below enable, and a piped `get.docker.com` installer.

## What is NOT proven

**No artifact here has run on any Linux host.** The suite asserts on the
script's text and on its refusals; it does not prove a box ends up hardened —
not that ufw is active, not that sshd rejects passwords, not that Docker
installed. `provision.sh --check` against a real box is the first thing that
observes any of it, and BRING-UP.md phase 1 is where that happens.

Two spec findings stay open by design: §2.1 (the gid-10000 collision) is an
inference until phase 1 measures it, and §2.3 (compose bind paths vs the proxy
allow-list) is measured in phase 5, which stops on a mismatch rather than
widening the allow-list.

## Scope

No systemd unit, proxy, allow-list or `units.test.py` change. No kill switch is
created; mutation stays disabled.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

- [ ] **Check CI on the merge commit**

After merge, `gh run list --branch main --limit 3` and confirm the run whose `headSha` is the **merge commit** is green. A PR being green does not mean `main` is green — `main` went red on `10c7ed2`, a docs-only merge whose own PR run had passed minutes earlier.
