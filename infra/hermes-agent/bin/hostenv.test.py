"""hostenv.sh, sourced the way run-ads-mutate.sh and changeset.sh source it.

F9 (spec §3.3, R1): it parses FOUR variables from .env as data, each only when unset, and it
must never open .env when it does not need to — on the VPS the broker sources it with every
value set by its unit and .env 600 root:root, and a failed redirect under `set -eu` aborts.
Runs as an ordinary user everywhere; the unreadable case is skipped only when run as root
(root can read a 000 file)."""
import os, shutil, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTENV = os.path.join(os.path.dirname(HERE), "hostenv.sh")
KEYS = ("HERMES_GOVERNANCE_DIR", "HERMES_AGENT_DIR", "HERMES_ADS_REPO_DIR", "HERMES_SPOOL_DIR")

PRINT = ('set -eu; here="$1"; . "$here/hostenv.sh"; '
         'for k in ' + " ".join(KEYS) + '; do eval "v=\\${$k:-}"; echo "$k=$v"; done')


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        shutil.copy2(HOSTENV, os.path.join(self.home, "hostenv.sh"))

    def write_env(self, text, mode=0o600):
        p = os.path.join(self.home, ".env")
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        self.addCleanup(os.chmod, p, 0o600)       # so rmtree can always remove it

    def source(self, **env):
        base = {"PATH": os.environ["PATH"]}
        base.update(env)
        p = subprocess.run(["/bin/sh", "-c", PRINT, "sh", self.home],
                           capture_output=True, text=True, env=base)
        vals = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
        return p, vals


class TestParsing(Base):
    def test_all_four_are_read_from_env_as_data(self):
        self.write_env("ANTHROPIC_API_KEY=placeholder-not-a-key\n"
                       "HERMES_GOVERNANCE_DIR=/g\nHERMES_AGENT_DIR=/a\n"
                       "HERMES_ADS_REPO_DIR='/r'\nHERMES_SPOOL_DIR=\"./data/spool\"\n")
        p, v = self.source()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(v, {"HERMES_GOVERNANCE_DIR": "/g", "HERMES_AGENT_DIR": "/a",
                             "HERMES_ADS_REPO_DIR": "/r", "HERMES_SPOOL_DIR": "./data/spool"})

    def test_an_environment_value_wins_per_variable(self):
        self.write_env("HERMES_GOVERNANCE_DIR=/g\nHERMES_AGENT_DIR=/from-file\n")
        p, v = self.source(HERMES_AGENT_DIR="/from-env")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(v["HERMES_AGENT_DIR"], "/from-env")
        self.assertEqual(v["HERMES_GOVERNANCE_DIR"], "/g")

    def test_no_other_key_leaks_into_the_environment(self):
        self.write_env("HERMES_GOVERNANCE_DIR=/g\nANTHROPIC_API_KEY=placeholder-not-a-key\n")
        p = subprocess.run(["/bin/sh", "-c", 'set -eu; here="$1"; . "$here/hostenv.sh"; env',
                            "sh", self.home], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"]})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("ANTHROPIC_API_KEY", p.stdout)


class TestUnreadableEnv(Base):
    def setUp(self):
        super().setUp()
        if os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        self.write_env("HERMES_GOVERNANCE_DIR=/g\n", mode=0o000)

    def test_all_set_means_env_is_never_opened(self):
        """The VPS case: the broker unit sets all four; .env is 600 root:root."""
        p, v = self.source(HERMES_GOVERNANCE_DIR="/g", HERMES_AGENT_DIR="/a",
                           HERMES_ADS_REPO_DIR="/r", HERMES_SPOOL_DIR="/s")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Permission denied", p.stderr)
        self.assertEqual(v["HERMES_AGENT_DIR"], "/a")

    def test_firing_control_an_unset_governance_dir_still_refuses(self):
        """An unreadable .env is skipped, not trusted: the R4 guard must still fire."""
        p, _ = self.source(HERMES_AGENT_DIR="/a")
        self.assertEqual(p.returncode, 1)
        self.assertIn("HERMES_GOVERNANCE_DIR is unset or empty", p.stderr)


if __name__ == "__main__":
    unittest.main()
