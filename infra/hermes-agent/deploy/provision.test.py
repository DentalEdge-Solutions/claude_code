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
