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


def mockbin(**scripts):
    """Create a directory of mock executables for PATH injection, one per
    keyword argument. Each value is the complete script body (shebang
    included), written verbatim and chmod 0o755.

    Extracted from a mock-PATH harness that used to live inline inside a
    single test (TestCheckModeVerdictIsTrustworthy); every behavioural test
    in this file that needs to fake `id`, `sshd`, `systemctl` or `ufw` now
    goes through this one implementation instead of copy-pasting
    tempfile.mkdtemp/chmod/PATH-prepend boilerplate per test.

    Caller owns cleanup (shutil.rmtree(mockdir)) -- see run_check_all() for
    the common case that does this for you.
    """
    mockdir = tempfile.mkdtemp(prefix="provision-mockbin-")
    for name, body in scripts.items():
        path = os.path.join(mockdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, 0o755)
    return mockdir


def mock_env(mockdir, os_release_path, extra=None):
    """The env dict for a `--check` run against mocked PATH binaries and an
    injected OS_RELEASE_FILE fixture. Strips the caller's real DEPLOY_USER/
    SSH_PUBKEY so the reserved-name and pubkey gates never fire, and
    prepends mockdir onto PATH so the mocked binaries shadow the real ones.
    """
    e = dict(os.environ)
    e.pop("DEPLOY_USER", None)
    e.pop("SSH_PUBKEY", None)
    e["OS_RELEASE_FILE"] = os_release_path
    e["PATH"] = mockdir + os.pathsep + e["PATH"]
    if extra:
        e.update(extra)
    return e


# Mock bodies that make their respective check_* pass cleanly, so a test that
# is only interested in ONE check's behaviour can hold every other check
# steady at "OK" -- the same isolation TestCheckModeVerdictIsTrustworthy's
# docstring describes: an unrelated failure would keep FAILED above zero on
# its own and mask the thing under test.
ID_MOCK_ALL_GOOD = (
    "#!/bin/sh\n"
    'if [ "$1" = "-nG" ]; then echo "hermesops sudo"; exit 0; fi\n'
    "exit 0\n"
)

SSHD_MOCK_ALL_GOOD = (
    "#!/bin/sh\n"
    'if [ "$1" = "-T" ]; then\n'
    "  echo 'passwordauthentication no'\n"
    "  echo 'permitrootlogin no'\n"
    "  echo 'kbdinteractiveauthentication no'\n"
    "  echo 'pubkeyauthentication yes'\n"
    "  exit 0\n"
    "fi\n"
    "exit 0\n"
)

SYSTEMCTL_MOCK_ALL_GOOD = (
    "#!/bin/sh\n"
    'if [ "$1" = "is-active" ]; then exit 0; fi\n'
    "exit 0\n"
)


# Fix Round 1 finding: check_firewall must run `ufw status verbose`, never
# plain `ufw status`. Verified against ufw's OWN source
# (src/backend_iptables.py, get_status()):
#
#   if r.direction == "in" and not r.forward and not verbose and not show_count:
#       dir_str = ""
#
# The per-rule direction suffix ("ALLOW IN" vs bare "ALLOW") is rendered
# ONLY under verbose (or numbered, or a forward rule) output. Plain `ufw
# status` also omits the `Logging:`/`Default:`/`New profiles:` header lines
# entirely -- those exist only in verbose output too. The first version of
# this mock baked "ALLOW IN" into ITS OWN plain-mode fixture without
# checking any of this against ufw's real behaviour, so the mock and the
# (at the time, broken) implementation shared the same false belief about
# the outside world and agreed with each other while both were wrong ("no
# inbound rule beyond SSH" printed on a real host no matter what was
# actually open). This mock now distinguishes the two invocations for real,
# so a regression back to plain `ufw status` is caught by mutation (n) in
# task-4-report.md rather than silently continuing to pass.
UFW_PLAIN_STATUS_FALLBACK = (
    "Status: active\n"
    "\n"
    "To                         Action      From\n"
    "--                         ------      ----\n"
    "OpenSSH                    ALLOW       Anywhere\n"
    "22/tcp                     ALLOW       Anywhere\n"
)


# Fix Round 2 finding: ufw's status strings are gettext-wrapped, so every
# string this file's fixtures and provision.sh's check_firewall match against
# ("Status: active", "Default:", "ALLOW IN") is locale-dependent. Under a
# translated locale those strings become different text, the ALLOW IN filter
# stops matching, and check_firewall reports "no inbound rule beyond SSH"
# having measured nothing -- the same silent no-op Fix Round 1 closed for
# plain-vs-verbose output, reached this time through locale instead of
# verbosity. provision.sh now pins `export LC_ALL=C` near its top, before
# anything parses program output. This mock models gettext by inspecting
# $LC_ALL and switching to an illustrative translated rendering whenever it
# is anything other than C/C.UTF-8/POSIX (empty/unset counts as C, matching
# ufw's own fallback). The French wording below is illustrative only, NOT a
# transcription of any real locale file -- the property under test is that
# the script PINS the locale, not that any particular translation is
# accurate. See test_locale_is_pinned_even_under_a_hostile_parent_environment
# and mutation (q) in task-4-report.md.
UFW_TRANSLATED_VERBOSE_STATUS_ILLUSTRATIVE = (
    "Statut : actif\n"
    "Journalisation : activee (faible)\n"
    "Defaut : refuser (entrant), autoriser (sortant), desactive (route)\n"
    "Nouveaux profils : ignorer\n"
    "\n"
    "Vers                       Action                Depuis\n"
    "--                         ------                ------\n"
    "OpenSSH                    AUTORISER ENTRANT      N'importe ou\n"
    "22/tcp                     AUTORISER ENTRANT      N'importe ou\n"
)

UFW_TRANSLATED_PLAIN_STATUS_ILLUSTRATIVE = (
    "Statut : actif\n"
    "\n"
    "Vers                       Action       Depuis\n"
    "--                         ------       ------\n"
    "OpenSSH                    AUTORISER    N'importe ou\n"
    "22/tcp                     AUTORISER    N'importe ou\n"
)


def ufw_mock(verbose_status_body, plain_status_body=UFW_PLAIN_STATUS_FALLBACK,
             translated_verbose_status_body=UFW_TRANSLATED_VERBOSE_STATUS_ILLUSTRATIVE,
             translated_plain_status_body=UFW_TRANSLATED_PLAIN_STATUS_ILLUSTRATIVE):
    """A `ufw` mock, locale-aware. Inspects $LC_ALL exactly the way it will
    be invoked by provision.sh's (mocked) child-process environment:

    - $LC_ALL is C, C.UTF-8, POSIX, or unset/empty -> "pinned" -> English:
      `ufw status verbose` prints verbose_status_body; plain `ufw status`
      prints plain_status_body (by default UFW_PLAIN_STATUS_FALLBACK, a
      fixed realistic plain rendering with no `Default:`/`Logging:` lines
      and no `IN` direction suffix, per ufw's own source -- see the Fix
      Round 1 comment above UFW_PLAIN_STATUS_FALLBACK).
    - anything else -> "hostile" -> the illustrative translated bodies,
      regardless of which verbose/plain body the caller supplied -- this
      mock is modelling "the strings change under gettext", not
      reproducing a specific locale's exact rendering of a specific rule
      set.

    All four heredoc delimiters are quoted so none of the four bodies are
    ever subject to shell expansion.
    """
    return (
        "#!/bin/sh\n"
        'locale_ok=0\n'
        'case "$LC_ALL" in\n'
        '  ""|C|C.UTF-8|POSIX) locale_ok=1 ;;\n'
        'esac\n'
        'if [ "$1" = "status" ] && [ "$2" = "verbose" ]; then\n'
        '  if [ "$locale_ok" = "1" ]; then\n'
        "cat <<'UFWEOF'\n"
        + verbose_status_body.rstrip("\n") + "\n"
        "UFWEOF\n"
        "  else\n"
        "cat <<'UFWFREOF'\n"
        + translated_verbose_status_body.rstrip("\n") + "\n"
        "UFWFREOF\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "status" ]; then\n'
        '  if [ "$locale_ok" = "1" ]; then\n'
        "cat <<'UFWPLAINEOF'\n"
        + plain_status_body.rstrip("\n") + "\n"
        "UFWPLAINEOF\n"
        "  else\n"
        "cat <<'UFWPLAINFREOF'\n"
        + translated_plain_status_body.rstrip("\n") + "\n"
        "UFWPLAINFREOF\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


UFW_CLEAN_STATUS = (
    "Status: active\n"
    "Logging: on (low)\n"
    "Default: deny (incoming), allow (outgoing), disabled (routed)\n"
    "New profiles: skip\n"
    "\n"
    "To                         Action      From\n"
    "--                         ------      ----\n"
    "OpenSSH                    ALLOW IN    Anywhere\n"
    "22/tcp                     ALLOW IN    Anywhere\n"
)

UFW_ALLOW_INCOMING_DEFAULT_STATUS = (
    "Status: active\n"
    "Logging: on (low)\n"
    "Default: allow (incoming), allow (outgoing), disabled (routed)\n"
    "New profiles: skip\n"
    "\n"
    "To                         Action      From\n"
    "--                         ------      ----\n"
    "OpenSSH                    ALLOW IN    Anywhere\n"
)


def run_check_all(ufw_status, extra_env=None):
    """Run `--check` with id/sshd/systemctl mocked to PASS and `ufw` mocked
    to report ufw_status for `ufw status verbose`. Returns (returncode,
    stdout, stderr). Owns and cleans up its own mockdir and OS_RELEASE_FILE
    fixture, so any drift the caller observes is attributable to the ufw
    state it passed in, not to an unrelated check or a leaked fixture.

    extra_env, when given, is merged into the CHILD's environment on top of
    the mocked PATH/OS_RELEASE_FILE -- used to simulate a hostile parent
    environment (e.g. a translated LC_ALL) that provision.sh's own
    `export LC_ALL=C` must override rather than inherit.
    """
    mockdir = mockbin(
        id=ID_MOCK_ALL_GOOD,
        sshd=SSHD_MOCK_ALL_GOOD,
        systemctl=SYSTEMCTL_MOCK_ALL_GOOD,
        ufw=ufw_mock(ufw_status),
    )
    osr = os_release("24.04")
    try:
        env = mock_env(mockdir, osr, extra=extra_env)
        p = subprocess.run(["bash", SCRIPT, "--check"], capture_output=True,
                           text=True, env=env)
        return p.returncode, p.stdout, p.stderr
    finally:
        os.unlink(osr)
        shutil.rmtree(mockdir)


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


class TestFirewall(unittest.TestCase):
    """Textual: exercising ufw needs a root Ubuntu host. These prove
    ensure_firewall says the right thing; TestCheckFirewallBehavioural below
    proves check_firewall's VERDICT is trustworthy.
    """

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


class TestCheckModeVerdictIsTrustworthy(unittest.TestCase):
    """Runs --check end to end against a mocked host and observes its
    VERDICT, rather than parsing the script's text. Every check_* assertion
    in this file outside this class and TestCheckFirewallBehavioural is
    textual.

    History: mutation (k) during this task's fix rounds showed why that gap
    matters. Piping into `while read` (instead of `<<<`) in
    check_sshd_hardening runs the loop in a SUBSHELL, so its ok()/bad() calls
    still PRINT (stdout is inherited through the pipe) but their increments to
    CHECKS and FAILED are silently lost when the subshell exits. The measured
    result on a host where every sshd directive is out of compliance: four
    real DRIFT lines print, immediately followed by "all checks passed", exit
    0 -- a silent false pass in --check, which is the one mechanism this
    entire script exists to provide. None of this file's other tests would
    notice, because the pipe and the `<<<` version produce IDENTICAL script
    text; only running the check and reading its verdict distinguishes them.

    Uses ID_MOCK_ALL_GOOD (user exists, in sudo, not in docker),
    SYSTEMCTL_MOCK_ALL_GOOD and a clean ufw_mock() so check_deploy_user,
    check_fail2ban and check_firewall all PASS, and mocks `sshd -T` to print
    NOTHING (every directive then reports drift) so the failure is isolated
    to the sshd loop. That isolation is the point: if any other check also
    failed, its main-shell bad() would keep FAILED above zero on its own,
    masking a lost sshd-loop failure and making this test pass for the wrong
    reason.

    This does NOT prove a real host ends up hardened -- even sshd's real
    state is never touched. It proves the narrower, load-bearing claim:
    --check cannot report success while a check reported drift.

    Mutation that proves it: change `<<<` to a pipe in check_sshd_hardening;
    this test fails while the rest of the suite stays green.
    """

    def test_check_cannot_report_success_while_a_check_reports_drift(self):
        mockdir = mockbin(
            id=ID_MOCK_ALL_GOOD,
            sshd="#!/bin/sh\n"
                 'if [ "$1" = "-T" ]; then exit 0; fi\n'
                 "exit 0\n",
            systemctl=SYSTEMCTL_MOCK_ALL_GOOD,
            ufw=ufw_mock(UFW_CLEAN_STATUS),
        )
        osr = os_release("24.04")
        try:
            env = mock_env(mockdir, osr)
            p = subprocess.run(["bash", SCRIPT, "--check"], capture_output=True,
                               text=True, env=env)
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


class TestCheckFirewallBehavioural(unittest.TestCase):
    """check_firewall gets BEHAVIOURAL coverage, not only text assertions
    (Ruling 17): every defect found in Tasks 1-3 was in something that
    VERIFIES, never in the acting code, and check_sshd_hardening's
    subshell bug (see TestCheckModeVerdictIsTrustworthy) shipped past a
    31-test suite made entirely of textual check_* assertions.

    Fix Round 1 history: the first version of this class passed with mock
    fixtures that baked "ALLOW IN" into a PLAIN `ufw status` response --
    exactly the same unverified assumption check_firewall's first
    implementation made about real ufw output. Both were wrong in the same
    way, so they agreed with each other: the tests below would have stayed
    green on an implementation that silently never detected anything, on a
    real host, no matter what was open. Every fixture here now goes through
    ufw_mock(), which is verbose-aware and verified against ufw's own
    source (see the module-level comment above UFW_PLAIN_STATUS_FALLBACK) --
    a behavioural test is only as good as its mock's fidelity to reality.

    Each test here runs `--check` through run_check_all(), which mocks
    id/sshd/systemctl to PASS so check_deploy_user, check_sshd_hardening and
    check_fail2ban stay green -- any drift observed is attributable to the
    `ufw status verbose` text passed in, not to an unrelated check.
    """

    def test_reports_drift_for_an_unexpected_inbound_rule(self):
        """A rule beyond SSH is a finding: no app port is opened in this
        design, and the dashboard is reached over an SSH tunnel.

        Mutation that proves it: delete the `extra` block from
        check_firewall (or replace it with an unconditional ok()); this
        fails.
        """
        rc, out, err = run_check_all(
            "Status: active\n"
            "Logging: on (low)\n"
            "Default: deny (incoming), allow (outgoing), disabled (routed)\n"
            "New profiles: skip\n"
            "\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "OpenSSH                    ALLOW IN    Anywhere\n"
            "9999/tcp                   ALLOW IN    Anywhere\n"
        )
        combined = (out + err).lower()
        self.assertNotEqual(rc, 0,
                            "unexpected inbound rule was not flagged:\n%s" % combined)
        self.assertIn("unexpected inbound rule", combined, combined)
        self.assertIn("9999", combined, combined)

    def test_does_not_report_drift_for_a_clean_firewall(self):
        """Positive control -- the half of a check that usually goes
        unchecked. Without this, a check_firewall that flagged EVERY inbound
        rule (including OpenSSH/22 itself) would pass the test above just as
        well as a correct one; only this test would catch it. Also the
        positive control for the default-policy check below: UFW_CLEAN_STATUS
        carries `Default: deny (incoming), ...`, so this must stay green
        alongside test_reports_drift_when_default_incoming_policy_is_not_deny.
        """
        rc, out, err = run_check_all(UFW_CLEAN_STATUS)
        combined = (out + err).lower()
        self.assertEqual(rc, 0, "a clean firewall was reported as drift:\n%s" % combined)
        self.assertNotIn("unexpected inbound rule", combined, combined)
        self.assertNotIn("firewall inactive", combined, combined)
        self.assertNotIn("default incoming policy is not deny", combined, combined)

    def test_ruling_4_regression_port_8022_is_not_hidden(self):
        """Ruling 4: the brief's original filter was
        `awk '/ALLOW IN/ && !/22|OpenSSH/ {print}'`, which excludes any LINE
        containing the substring "22" ANYWHERE -- and "8022" ends in "22", so
        a rule on port 8022 would be silently hidden by that filter. The
        anchored filter actually in provision.sh matches the port FIELD in
        full against `^(22|OpenSSH)$` (after stripping an optional `/tcp` or
        `/udp` suffix), which "8022" does not satisfy, so it is reported.

        Mutation that proves it: restore the original unanchored filter
        (`!/22|OpenSSH/` against the whole line); this fails, while
        test_does_not_report_drift_for_a_clean_firewall stays green -- proof
        that the anchoring, not merely re-flagging everything, is what fixes
        this.
        """
        rc, out, err = run_check_all(
            "Status: active\n"
            "Logging: on (low)\n"
            "Default: deny (incoming), allow (outgoing), disabled (routed)\n"
            "New profiles: skip\n"
            "\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "OpenSSH                    ALLOW IN    Anywhere\n"
            "8022/tcp                   ALLOW IN    Anywhere\n"
        )
        combined = (out + err).lower()
        self.assertNotEqual(rc, 0, "port 8022 was silently hidden:\n%s" % combined)
        self.assertIn("8022", combined, combined)

    def test_reports_drift_when_default_incoming_policy_is_not_deny(self):
        """Fix Round 1: ensure_firewall SETS `ufw default deny incoming`, but
        until now nothing verified it HOLDS. A box whose default incoming
        policy had been flipped to allow (by an operator, another tool, or a
        `ufw reset`-adjacent mistake) would otherwise pass check_firewall
        cleanly as long as no unexpected explicit rule happened to be
        present -- exactly the gap UFW_ALLOW_INCOMING_DEFAULT_STATUS
        reproduces: no unexpected rule, only the default policy flipped.

        Positive control: test_does_not_report_drift_for_a_clean_firewall,
        which carries `Default: deny (incoming)` and must stay green.

        Mutation that proves it: delete the default-policy `case` block from
        check_firewall; this fails.
        """
        rc, out, err = run_check_all(UFW_ALLOW_INCOMING_DEFAULT_STATUS)
        combined = (out + err).lower()
        self.assertNotEqual(rc, 0,
                            "an allow-incoming default policy was not flagged:\n%s" % combined)
        self.assertIn("default incoming policy is not deny", combined, combined)

    def test_locale_is_pinned_even_under_a_hostile_parent_environment(self):
        """Fix Round 2: ufw's status strings are gettext-wrapped, so
        "Status: active", "Default:" and "ALLOW IN" are all locale-dependent.
        Under a translated locale the ALLOW IN filter would stop matching and
        this check would report "no inbound rule beyond SSH" having measured
        nothing -- the same silent no-op Fix Round 1 closed for
        plain-vs-verbose ufw output, reached this time through locale
        instead of verbosity.

        Runs with a hostile LC_ALL (fr_FR.UTF-8) already set in the PARENT
        environment -- what a deploy operator's own translated shell would
        hand the script -- against a ufw fixture that mocks translated
        output under any locale other than C/C.UTF-8/POSIX (see ufw_mock()
        and the module comment above UFW_TRANSLATED_VERBOSE_STATUS_ILLUSTRATIVE).
        If provision.sh pins `LC_ALL=C` before it runs `ufw`, the mock still
        receives C and returns English, and drift on the unexpected rule is
        still detected -- proving the script OVERRIDES the inherited value
        rather than inheriting it. If it does not, the mock returns the
        (non-matching) translated text and the drift silently disappears.

        Mutation that proves it: delete the `export LC_ALL=C` line near the
        top of provision.sh; this fails.
        """
        rc, out, err = run_check_all(
            "Status: active\n"
            "Logging: on (low)\n"
            "Default: deny (incoming), allow (outgoing), disabled (routed)\n"
            "New profiles: skip\n"
            "\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "OpenSSH                    ALLOW IN    Anywhere\n"
            "9999/tcp                   ALLOW IN    Anywhere\n",
            extra_env={"LC_ALL": "fr_FR.UTF-8"},
        )
        combined = (out + err).lower()
        self.assertNotEqual(
            rc, 0,
            "drift was not detected under a hostile parent LC_ALL "
            "(the script is inheriting the locale instead of pinning it):\n%s" % combined)
        self.assertIn("unexpected inbound rule", combined, combined)
        self.assertIn("9999", combined, combined)


class TestApplyAllWiring(unittest.TestCase):
    """apply_all cannot be run outside root Ubuntu, so this is a text
    assertion -- but a targeted one: it checks that every ensure_* function
    this task adds is actually CALLED from apply_all, in the dependency
    order the brief requires (base packages before anything that needs
    them; deploy-user/ssh/firewall/fail2ban/unattended-upgrades after).
    A function defined but never wired in is invisible to every other test
    in this file, textual or behavioural.

    Mutation that proves it: delete any one of the four `ensure_*` calls
    added by this task from apply_all's body; this fails.
    """

    def test_apply_all_calls_every_new_ensure_step_in_order(self):
        text = script_text()
        m = re.search(r"(?ms)^apply_all\(\) \{.*?^\}", text)
        self.assertIsNotNone(m, "apply_all not found -- regex is stale")
        body = m.group(0)
        steps = ["ensure_base_packages", "ensure_deploy_user",
                 "ensure_authorized_key", "ensure_sshd_hardening",
                 "ensure_firewall", "ensure_fail2ban",
                 "ensure_unattended_upgrades"]
        positions = [body.find(s) for s in steps]
        for step, pos in zip(steps, positions):
            self.assertNotEqual(pos, -1, "%s is not called from apply_all" % step)
        self.assertEqual(positions, sorted(positions),
                         "apply_all calls its ensure_* steps out of order: %s"
                         % list(zip(steps, positions)))


if __name__ == "__main__":
    unittest.main()
