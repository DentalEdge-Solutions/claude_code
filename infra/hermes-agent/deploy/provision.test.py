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
import re
import shutil
import subprocess
import tempfile
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
        """`set -euo pipefail` must be ACTIVE, not merely present. assertIn() is
        satisfied by `# set -euo pipefail` exactly as well as by the real
        directive -- the same false pass as this project's
        assertIn("ExecStartPre", body) satisfied by `#ExecStartPre=`.

        Mutation that proves it: comment the line out; this fails.
        """
        self.assertRegex(script_text(), r"(?m)^set -euo pipefail$")

    def test_strictness_precedes_the_first_command(self):
        """The constraint is positional. A directive set after the first command
        leaves everything above it running unstrict.

        Mutation that proves it: move the directive below RESERVED_NAMES; this fails.
        """
        strict_at = None
        first_cmd_at = None
        for i, raw in enumerate(script_text().splitlines()):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "set -euo pipefail":
                strict_at = i
                break
            if first_cmd_at is None:
                first_cmd_at = i
        self.assertIsNotNone(strict_at, "no active `set -euo pipefail` found")
        self.assertIsNone(
            first_cmd_at,
            "a command at line %d runs before `set -euo pipefail`"
            % ((first_cmd_at or 0) + 1))


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
            self.assertIn("is reserved for the hermes tier", err.lower(), err)

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
        """The fixture path deliberately avoids the substring 'os-release' so this
        pins the DIE MESSAGE, not the path it was handed.

        Mutation that proves it: delete the '(os-release)' annotation from the
        die message; this fails.
        """
        rc, _, err = run(["--check"], {"OS_RELEASE_FILE": "/nonexistent/foo"})
        self.assertNotEqual(rc, 0)
        self.assertIn("os-release", err.lower())

    def test_an_empty_os_release_is_refused(self):
        fd, path = tempfile.mkstemp(prefix="os-release-empty-", text=True)
        os.close(fd)
        try:
            rc, _, err = run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertNotEqual(rc, 0)
            self.assertIn("ubuntu", err.lower(), err)
        finally:
            os.unlink(path)

    def test_a_hostile_os_release_is_not_executed(self):
        """The gate must PARSE os-release, never source it. The path is
        environment-overridable, so sourcing turns a safety gate into arbitrary
        code execution as root. The failure mode for hostile content must be a
        refusal or a clean parse -- never execution.

        Mutation that proves it: restore the `. "$OS_RELEASE_FILE"` parsing; this fails.
        """
        marker = os.path.join(tempfile.gettempdir(),
                              "provision-sourced-%d" % os.getpid())
        if os.path.exists(marker):
            os.unlink(marker)
        fd, path = tempfile.mkstemp(prefix="os-release-hostile-", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('NAME="Ubuntu"\nVERSION_ID="24.04"\nPWNED=$(touch %s)\n' % marker)
        try:
            run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertFalse(
                os.path.exists(marker),
                "os-release was SOURCED: the embedded command ran and created %s" % marker)
        finally:
            os.unlink(path)
            if os.path.exists(marker):
                os.unlink(marker)


class TestCheckModeIsNotVacuous(unittest.TestCase):
    """A check run that measured nothing must refuse, not pass."""

    def test_a_check_run_that_measured_nothing_refuses(self):
        """The zero-check guard. Now that check_all() performs real checks, the
        only honest way to exercise the guard is against a copy of the script
        whose check set has been emptied -- which is precisely the regression the
        guard exists to catch: a check silently commented out.

        Mutation that proves it: delete the CHECKS guard from finish(); this fails.
        """
        text = script_text()
        neutered = re.sub(r"(?ms)^check_all\(\) \{.*?^\}",
                          "check_all() {\n  :\n}", text)
        # Prove the mutation actually applied. A substitution that silently did
        # nothing would leave this test passing against the UNMUTATED script.
        self.assertNotEqual(neutered, text, "could not neuter check_all -- regex is stale")
        fd, path = tempfile.mkstemp(prefix="provision-nochecks-", suffix=".sh", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(neutered)
        osr = os_release("24.04")
        try:
            p = subprocess.run(["bash", path, "--check"], capture_output=True, text=True,
                               env=dict(os.environ, OS_RELEASE_FILE=osr))
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("not a pass", p.stderr.lower(), p.stderr)
        finally:
            os.unlink(path)
            os.unlink(osr)


def line_index(needle, text=None):
    """Index of the first CODE line containing needle, or -1. Comment lines are
    skipped: an explanatory comment mentioning the needle (e.g. a remark like
    "sshd -t is the difference between a refusal and a brick" sitting next to
    the real invocation) would otherwise satisfy an ordering check without
    ever moving when the real line does -- the same false-pass class this
    suite's own docstring warns about, just relocated into this helper rather
    than into the test that calls it.
    """
    lines = (text if text is not None else script_text()).splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            continue
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
        """Filters comment lines first, like every other test in this class --
        an unfiltered assertIn would be satisfied by the directive appearing
        in an explanatory comment as readily as in the drop-in heredoc itself.
        """
        lines = [l.strip() for l in script_text().splitlines()
                 if not l.strip().startswith("#")]
        text = "\n".join(lines)
        for directive in ("PasswordAuthentication no",
                          "PermitRootLogin no",
                          "KbdInteractiveAuthentication no",
                          "PubkeyAuthentication yes"):
            self.assertIn(directive, text)

    def test_sshd_directives_is_exactly_the_expected_policy(self):
        """A policy test, not a parity test: SSHD_DIRECTIVES is now the single
        source of truth ensure_sshd_hardening applies and check_sshd_hardening
        verifies, so there is nothing left to reconcile -- just a fixed
        expectation of what that one list must say.

        (History: this used to be a parity test comparing two text-derived
        sets, and was defeated three separate ways -- a deleted grep line, a
        commented-out block, and a decoy substring in a trailing comment like
        `true  # grep -qx '...'` that survived comment-filtering because the
        LIVE line didn't start with `#`, while the regex still matched the
        comment fragment on it. A text-derived parity test cannot tell "this
        executes" from "this appears". Removing the duplication in provision.sh
        -- one list, consumed by both sides -- makes that whole class of defeat
        unconstructible rather than merely harder to fool.)

        Mutation that proves it: remove one directive from SSHD_DIRECTIVES;
        this fails.
        """
        m = re.search(r'(?m)^SSHD_DIRECTIVES="(.*?)"', script_text(), re.DOTALL)
        self.assertIsNotNone(m, "SSHD_DIRECTIVES not found -- regex is stale")
        lines = [l for l in m.group(1).splitlines() if l.strip()]
        self.assertEqual(set(lines), {
            "PasswordAuthentication no",
            "PermitRootLogin no",
            "KbdInteractiveAuthentication no",
            "PubkeyAuthentication yes",
        })

    def test_check_sshd_hardening_reads_the_shared_list_not_literals(self):
        """The single-source-of-truth test: check_sshd_hardening must consume
        SSHD_DIRECTIVES rather than hardcode any directive name, or the two
        sides could drift apart again -- silently, since a hardcoded literal
        parses and runs just as well as a variable reference.

        Mutation that proves it: hardcode one directive back into
        check_sshd_hardening (e.g. `grep -qx 'permitrootlogin no'`) instead of
        reading SSHD_DIRECTIVES; this fails.
        """
        text = script_text()
        m = re.search(r"(?ms)^check_sshd_hardening\(\) \{.*?^\}", text)
        self.assertIsNotNone(m, "check_sshd_hardening not found -- regex is stale")
        body = m.group(0)
        self.assertIn("$SSHD_DIRECTIVES", body,
                     "check_sshd_hardening does not reference SSHD_DIRECTIVES")
        for literal in ("passwordauthentication", "permitrootlogin",
                        "kbdinteractiveauthentication", "pubkeyauthentication"):
            self.assertNotIn(literal, body.lower(),
                             "check_sshd_hardening hardcodes '%s' instead of "
                             "reading it from SSHD_DIRECTIVES" % literal)


class TestAuthorizedKeys(unittest.TestCase):
    def test_the_key_is_appended_never_truncated(self):
        """`>` destroys every other key on the box, including on a re-run.

        Mutation that proves it: change the append to `> "$akeys"`; this fails.

        Filters on the variable name `akeys`, not the literal string
        "authorized_keys": the implementation names the path once
        (`akeys="${home}/.ssh/authorized_keys"`) and every subsequent write
        addresses it as `$akeys`, so a filter on the literal string would only
        ever inspect that one assignment line -- never the write itself --
        making the assertion pass no matter what the write does.

        The assertion itself is a regex, not `assertNotIn("> ", s.replace(">>
        ", ""))`: that string-replace approach is whitespace-sensitive and
        misses a truncating redirect written without a space, e.g.
        `>"$akeys"`. `(?<!>)>\\s*"?\\$akeys` matches a bare `>` (not part of
        `>>`) immediately before `$akeys`, with or without a space or an
        opening quote in between.
        """
        for line in script_text().splitlines():
            s = line.strip()
            if s.startswith("#") or "akeys" not in s:
                continue
            self.assertNotRegex(s, r'(?<!>)>\s*"?\$akeys',
                                "truncating redirect onto authorized_keys: %s" % s)

    def test_it_checks_before_appending(self):
        """Idempotency: a re-run must not add a second copy of the same key."""
        self.assertIn("grep -qxF", script_text())


class TestSshPubkeyValidation(unittest.TestCase):
    """assert_ssh_pubkey_wellformed runs from main(), right after the
    reserved-name guard and before the OS gate, whenever SSH_PUBKEY is set.
    Unlike most of this file's SSH-related assertions, these are BEHAVIOURAL:
    moving validation out of ensure_authorized_key and into its own gate made
    it reachable in --check mode on any host, with no root and no Ubuntu
    required.

    The four "refused" tests below pin a distinctive fragment of their own
    die message, not the shared "SSH_PUBKEY" substring these tests used
    earlier: the four die messages are already distinct, and a shared
    substring cannot tell "refused for THIS reason" from "refused for any
    reason" -- which matters because a guard mutated to reject everything
    (see the positive control) would still satisfy a shared-substring check
    on all four, masking exactly the kind of regression this file exists to
    catch. The positive control's check stays broad on purpose: its job is to
    detect ANY SSH_PUBKEY-related refusal of a well-formed key, regardless of
    the wording a broken guard might use.
    """

    def test_an_unrecognised_key_type_is_refused(self):
        """A string that isn't OpenSSH key syntax at all.

        Mutation that proves it: delete the key-type `case` block (or its
        default `die` arm) from assert_ssh_pubkey_wellformed; this fails.
        """
        rc, _, err = run(["--check"], {"SSH_PUBKEY": "not-a-key"})
        self.assertNotEqual(rc, 0)
        self.assertIn("not a recognised", err.lower(), err)

    def test_a_type_with_no_key_material_is_refused(self):
        """`ssh-rsa` alone with nothing after it -- the shape of a copy-paste
        that grabbed only the first word.

        Mutation that proves it: delete the `[ -n "$body" ] || die ...` line
        from assert_ssh_pubkey_wellformed; this fails.
        """
        rc, _, err = run(["--check"], {"SSH_PUBKEY": "ssh-rsa"})
        self.assertNotEqual(rc, 0)
        self.assertIn("no key material", err.lower(), err)

    def test_a_truncated_key_body_is_refused(self):
        """The single most likely real failure: a base64 body clipped
        mid-paste. A valid type with a short, all-alphabetic body would clear
        the type check, the non-empty check, and the base64-charset check --
        only the length floor catches it.

        Mutation that proves it: delete the length-floor check
        (`[ "${#body}" -ge 68 ] || die ...`) from assert_ssh_pubkey_wellformed;
        with nothing else to catch this input, the function returns
        successfully and this fails.
        """
        rc, _, err = run(["--check"], {"SSH_PUBKEY": "ssh-ed25519 AAAAshort"})
        self.assertNotEqual(rc, 0)
        self.assertIn("looks truncated", err.lower(), err)

    def test_a_multiline_value_is_refused(self):
        """A trailing `*` in a shell case pattern spans newlines: without an
        explicit newline check, `set -- $SSH_PUBKEY` word-splits on the
        embedded newline and silently drops everything after line one, so a
        key with a valid-looking first line and garbage after it would pass
        every remaining check.

        Mutation that proves it: delete the newline-detecting `case` arm from
        assert_ssh_pubkey_wellformed; word-splitting then absorbs the injected
        line as if it were never there, and this fails.
        """
        body = "A" * 43
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI%s\nextra-garbage-line" % body
        rc, _, err = run(["--check"], {"SSH_PUBKEY": key})
        self.assertNotEqual(rc, 0)
        self.assertIn("contains a newline", err.lower(), err)

    def test_a_wellformed_key_is_not_refused(self):
        """Positive control. Without this, a guard that rejects EVERYTHING
        would still look correct by every test above's ORIGINAL design (a
        shared "was SOMETHING refused" check) -- none of them would catch a
        guard that refuses valid input too, since they only ever supply
        invalid input. Synthetic key, not a real one: 68 characters is the
        shortest genuine ed25519 body, so this also exercises the length
        boundary.

        Checks for the general absence of any SSH_PUBKEY-related refusal
        (not one specific phrase), so it catches a guard that rejects
        everything under whatever wording that rejection uses.

        Mutation that proves it: make assert_ssh_pubkey_wellformed `die`
        unconditionally right after the `[ -n "$SSH_PUBKEY" ] || return 0`
        line; this fails. Since the other four tests in this class now pin
        their OWN reason-specific fragment (not a shared substring), an
        unconditional die legitimately fails them too -- that is the correct
        signal, not over-sensitivity: an unconditional die really does destroy
        the per-case behaviour those four exist to describe, and a suite that
        reports that fact is right to.
        """
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI" + "A" * 43 + " test@example"
        rc, _, err = run(["--check"], {"SSH_PUBKEY": key})
        self.assertNotIn("ssh_pubkey", err.lower(),
                         "a well-formed key was refused: %s" % err)


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

    def test_check_deploy_user_verifies_the_sudo_grant(self):
        """ensure_deploy_user actively grants sudo; the docker test above
        asserts an ABSENCE, but a --check that never confirms sudo holds would
        stay green on a host where `usermod -aG sudo` silently failed or was
        later reverted, even though every subsequent deploy command needs it.

        Mutation that proves it: delete the sudo check from check_deploy_user;
        this fails.
        """
        text = script_text()
        m = re.search(r"(?ms)^check_deploy_user\(\) \{.*?^\}", text)
        self.assertIsNotNone(m, "check_deploy_user not found -- regex is stale")
        body = m.group(0)
        self.assertRegex(body, r"grep -qx sudo\b",
                         "check_deploy_user does not verify the deploy user holds sudo")


class TestCheckModeVerdictIsTrustworthy(unittest.TestCase):
    """The only test in this suite that runs --check end to end against a
    mocked host and observes its VERDICT, rather than parsing the script's
    text. Every other check_* assertion in this file is textual.

    History: mutation (k) during this task's fix rounds showed why that gap
    matters. Piping into `while read` (instead of `<<<`) in
    check_sshd_hardening runs the loop in a SUBSHELL, so its ok()/bad() calls
    still PRINT (stdout is inherited through the pipe) but their increments to
    CHECKS and FAILED are silently lost when the subshell exits. The measured
    result on a host where every sshd directive is out of compliance: four
    real DRIFT lines print, immediately followed by "all checks passed", exit
    0 -- a silent false pass in --check, which is the one mechanism this
    entire script exists to provide. None of this file's other 31 tests would
    notice, because the pipe and the `<<<` version produce IDENTICAL script
    text; only running the check and reading its verdict distinguishes them.

    Mocks `id` to make check_deploy_user PASS (user exists, in sudo, not in
    docker) and `sshd -T` to print NOTHING (every directive then reports
    drift), so the failure is isolated to the sshd loop. That isolation is the
    point: if check_deploy_user also failed, its main-shell bad() would keep
    FAILED above zero on its own, masking a lost sshd-loop failure and making
    this test pass for the wrong reason.

    This does NOT prove a real host ends up hardened -- ufw, fail2ban and
    unattended-upgrades are outside this task's scope, and even sshd's real
    state is never touched. It proves the narrower, load-bearing claim: --check
    cannot report success while a check reported drift.

    Mutation that proves it: change `<<<` to a pipe in check_sshd_hardening;
    this test fails while the rest of the suite stays green.
    """

    def test_check_cannot_report_success_while_a_check_reports_drift(self):
        mockdir = tempfile.mkdtemp(prefix="provision-mockbin-")
        osr = os_release("24.04")
        try:
            id_mock = os.path.join(mockdir, "id")
            with open(id_mock, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n"
                        'if [ "$1" = "-nG" ]; then echo "hermesops sudo"; exit 0; fi\n'
                        "exit 0\n")
            os.chmod(id_mock, 0o755)

            sshd_mock = os.path.join(mockdir, "sshd")
            with open(sshd_mock, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n"
                        'if [ "$1" = "-T" ]; then exit 0; fi\n'
                        "exit 0\n")
            os.chmod(sshd_mock, 0o755)

            e = dict(os.environ)
            e.pop("DEPLOY_USER", None)
            e.pop("SSH_PUBKEY", None)
            e["OS_RELEASE_FILE"] = osr
            e["PATH"] = mockdir + os.pathsep + e["PATH"]
            p = subprocess.run(["bash", SCRIPT, "--check"], capture_output=True,
                               text=True, env=e)
            combined = (p.stdout + p.stderr).lower()

            self.assertNotEqual(
                p.returncode, 0,
                "--check exited 0 despite mocked sshd reporting every directive "
                "out of compliance:\nSTDOUT:\n%s\nSTDERR:\n%s" % (p.stdout, p.stderr))
            self.assertNotIn("all checks passed", combined,
                             "--check claimed success alongside drift:\n%s" % combined)
            self.assertIn("failed", combined,
                         "--check's failure summary is missing:\n%s" % combined)
        finally:
            os.unlink(osr)
            shutil.rmtree(mockdir)


if __name__ == "__main__":
    unittest.main()
