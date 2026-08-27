"""Wrapper-level tests for run-ads-mutate.sh.

ZERO SPEND BY CONSTRUCTION. `docker` is a fake shell script on a temp PATH, so the
real ads-mutator container is never created and nothing can reach a Google Ads
account. The test asserts the wrapper's own control flow — which status it exits
with, and what it says on stderr — not anything about mutation.

S1-M2 is the reason this file exists. persist-run-record.py exits 2 for a
PersistRefused: a destination that could not be proven to stay inside the client
vault, i.e. a symlink or hardlink pointing out of it. That is an ATTACK DETECTION,
and it was swallowed by `|| true` — status discarded, stdout to /dev/null, leaving
one line of stderr buried in the executor's own output.

The two properties are in tension and both matter, so both are pinned here:
  * the executor's status must still win (an exit-2 refusal is a promise the account
    was not touched, and persist must never be able to overwrite that promise), and
  * a persist refusal must still be impossible to miss.
A fix for either one alone would pass half of this file.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(os.path.dirname(HERE), "run-ads-mutate.sh")
sys.path.insert(0, HERE)
import governance_lib

SLUG = "acme-dental"
CID = "20260824-101500-abcdef01"
RESULT = {"changeset_id": CID, "status": "ok", "applied": 1,
          "finished_at": "2026-08-24T10:15:00Z", "operator": "operator",
          "actions": []}

# A QUOTED heredoc, not `echo "..."`. The payload is JSON, so a double-quoted echo
# lets the shell eat every inner quote and the marker line arrives unparseable —
# parse_result then returns None, persist does nothing, exits 0, and every assertion
# about a persist refusal passes vacuously. That happened while writing this file and
# is exactly why the controls below assert persist actually RAN.
FAKE_DOCKER = """#!/bin/sh
# Stands in for the real `docker`. Emits what the executor would have printed and
# exits with the status this test asked for. It NEVER creates a container.
cat <<'HERMES_FAKE_DOCKER_EOF'
HERMES-RESULT-JSON %(payload)s
HERMES_FAKE_DOCKER_EOF
exit %(rc)s
"""


class Base(unittest.TestCase):
    """Runs the wrapper from an ISOLATED COPY of its own directory.

    That is not cosmetic. hostenv.sh sets `export VAULT_ROOT="$here/data/vaults"`,
    unconditionally and after any inherited value — so a VAULT_ROOT passed in the
    environment is overridden, and a naive harness silently persists into the REAL
    data/vaults tree beside real clients. `here` is the script's own directory, so the
    only way to redirect it is to run the script from somewhere else.

    The wrapper and hostenv.sh are COPIED FRESH from the real files on every run, and
    bin/ is symlinked to the real bin/, so this always exercises the current content of
    the shipped script rather than a drifting duplicate.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "hermes")
        os.makedirs(self.home)
        real_home = os.path.dirname(HERE)
        for name in ("run-ads-mutate.sh", "hostenv.sh"):
            shutil.copy2(os.path.join(real_home, name), os.path.join(self.home, name))
        os.symlink(HERE, os.path.join(self.home, "bin"))
        self.wrapper = os.path.join(self.home, "run-ads-mutate.sh")
        # The wrapper refuses without a .env.gaw declaring the WRITE role. Every value
        # here is an obvious placeholder and none is a credential: the fake `docker`
        # ignores them entirely, and nothing in this file ever reaches an ads API.
        with open(os.path.join(self.home, ".env.gaw"), "w") as f:
            f.write("GOOGLE_ADS_CREDENTIAL_ROLE=write\n"
                    "GOOGLE_ADS_DEVELOPER_TOKEN=placeholder-not-a-token\n"
                    "GOOGLE_ADS_CLIENT_ID=placeholder-not-a-client-id\n"
                    "GOOGLE_ADS_CLIENT_SECRET=placeholder-not-a-secret\n"
                    "GOOGLE_ADS_REFRESH_TOKEN=placeholder-not-a-token\n"
                    "GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890\n"
                    "GOOGLE_ADS_CUSTOMER_ID=1234567890\n")

        self.vaults = os.path.join(self.home, "data", "vaults")
        self.vault = os.path.join(self.vaults, SLUG)
        os.makedirs(os.path.join(self.vault, "changes"))

        self.gov = os.path.join(self.tmp, "governance")
        reg = governance_lib.clients_registry_path(self.gov)
        os.makedirs(os.path.dirname(reg))
        with open(reg, "w") as f:
            json.dump({"clients": {SLUG: {"project": "claude_google_ads",
                                          "customer_id": "1234567890",
                                          "status": "active"}}}, f)
        self.bin = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.bin)

    def _fake_docker(self, rc=0):
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as f:
            f.write(FAKE_DOCKER % {"payload": json.dumps(RESULT), "rc": rc})
        os.chmod(p, 0o755)

    def _run(self, executor_rc=0):
        self._fake_docker(executor_rc)
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["HERMES_GOVERNANCE_DIR"] = self.gov
        env.pop("VAULT_ROOT", None)          # hostenv.sh owns it; see the class docstring
        p = subprocess.run(
            ["/bin/sh", self.wrapper, "--client", SLUG, "--changeset", CID],
            capture_output=True, text=True, env=env, timeout=120)
        return p

    def _poison_the_vault(self):
        """Make persist refuse for the reason that matters: a timeline symlinked out
        of the vault. This is the containment refusal, not a generic I/O error."""
        outside = os.path.join(self.tmp, "outside.md")
        open(outside, "w").close()
        os.symlink(outside, os.path.join(self.vault, "timeline.md"))


class TestControlsFirst(Base):
    """Without these the failure tests below prove nothing: they would be satisfied by
    a wrapper that refused everything, or by a fake docker that never ran."""

    def test_control_a_clean_run_exits_zero_and_persists(self):
        p = self._run(executor_rc=0)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(HERE), "data",
                                                     "vaults", SLUG)),
                         "the harness wrote into the REAL vault tree")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("HERMES-RESULT-JSON", p.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.vault, "timeline.md")),
                        "persist did not run at all — the fixture is not exercising it")
        self.assertNotIn("RUN RECORD NOT PERSISTED", p.stderr)

    def test_control_the_executor_status_is_passed_through(self):
        """An exit-2 refusal is a promise the account was not touched. It must survive
        the persist step, which is why the executor's output is captured to a file
        rather than piped."""
        p = self._run(executor_rc=2)
        self.assertEqual(p.returncode, 2)


class TestPersistRefusalIsLoud(Base):
    def test_a_containment_refusal_is_announced_unmissably(self):
        self._poison_the_vault()
        p = self._run(executor_rc=0)
        self.assertIn("RUN RECORD NOT PERSISTED", p.stderr)
        self.assertIn("CONTAINMENT REFUSAL", p.stderr)
        # It must say what to do, not merely that something happened.
        self.assertIn("inspect the vault", p.stderr)
        self.assertIn("governance audit log", p.stderr)

    def test_the_refusal_does_not_hijack_the_executor_status(self):
        """The other half, and the reason `|| true` was there in the first place. A
        persist failure must be loud but must NEVER become the script's status: exit 0
        here still means the executor succeeded. A fix that simply propagated persist's
        status would pass the test above and fail this one."""
        self._poison_the_vault()
        self.assertEqual(self._run(executor_rc=0).returncode, 0)

    def test_it_does_not_mask_a_real_executor_failure_either(self):
        self._poison_the_vault()
        self.assertEqual(self._run(executor_rc=3).returncode, 3)

    def test_the_banner_names_the_executor_status_it_is_not_overriding(self):
        """The banner exists to be read next to the exit code. If it did not state
        which status still stands, it would read as though the run itself had failed."""
        self._poison_the_vault()
        p = self._run(executor_rc=3)
        self.assertIn("status (3) is UNCHANGED", p.stderr)

    def test_control_no_banner_when_persist_succeeds(self):
        """DISCRIMINATING CONTROL. A wrapper that printed the banner unconditionally
        would satisfy every assertion above while telling the operator nothing."""
        p = self._run(executor_rc=0)
        self.assertNotIn("CONTAINMENT REFUSAL", p.stderr)


if __name__ == "__main__":
    unittest.main()
