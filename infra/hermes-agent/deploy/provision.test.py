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
    """A check run that measured nothing must refuse, not pass. check_all is a
    stub in this task, so this is directly reachable now.

    NOTE FOR A LATER TASK: when real checks land in Task 3 this test must be
    updated -- it will otherwise fail for the right reason at the wrong time.

    Mutation that proves it: delete the CHECKS guard from finish(); this fails.
    """

    def test_a_check_run_that_measured_nothing_refuses(self):
        path = os_release("24.04")
        try:
            rc, _, err = run(["--check"], {"OS_RELEASE_FILE": path})
            self.assertNotEqual(rc, 0)
            self.assertIn("not a pass", err.lower(), err)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
