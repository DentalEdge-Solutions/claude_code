"""Wrapper-level tests for run-ads-mutate.sh.

ZERO SPEND BY CONSTRUCTION. `docker` is a fake shell script on a temp PATH, so the
real ads-mutator container is never created and nothing can reach a Google Ads
account. The test asserts the wrapper's own control flow — which status it exits
with, and what it says on stderr — not anything about mutation.

S1-M2 is the reason this file exists. persist-run-record.py exits 2 for a
PersistRefused: a destination that could not be proven to stay inside the governance
store's records/ tree (F12 — it used to be the client vault), i.e. a symlink or
hardlink pointing out of it. That is an ATTACK DETECTION, and it was swallowed by
`|| true` — status discarded, stdout to /dev/null, leaving one line of stderr buried
in the executor's own output.

F12 review (I1): exit 2 now ALSO covers a plain setup mistake — a records/ tree that
`init-host-layout.py --apply` has not created yet. The banner therefore no longer
asserts an attack as fact; it names both causes and points at the
`persist-run-record:` line above it, which says which one fired.
TestPersistRefusalIsLoud below pins that wording.

The two properties are in tension and both matter, so both are pinned here:
  * the executor's status must still win (an exit-2 refusal is a promise the account
    was not touched, and persist must never be able to overwrite that promise), and
  * a persist refusal must still be impossible to miss.
A fix for either one alone would pass half of this file.
"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(os.path.dirname(HERE), "run-ads-mutate.sh")
sys.path.insert(0, HERE)
import governance_lib


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PF = _load("preflight_governance_access", "preflight-governance-access.py")

# PLATFORM GATE. The wrapper runs the pre-flight (run-ads-mutate.sh:34) before it does
# anything else, and the pre-flight is a NO-OP off Linux by design (PF.applies()), because
# bind-mount UID semantics are only direct there. Consequences, both measured 2026-08-30:
#   * on darwin these tests exercised the wrapper with an INCOMPLETE governance store and
#     never noticed, because the pre-flight stayed silent;
#   * on Linux the same fixture is refused at exit 2 before the wrapper reaches the persist
#     logic under test — 5 of 7 tests failed for a reason that had nothing to do with S1-M2.
# setUp now builds the COMPLETE store either way. On Linux the store must additionally be
# usable by EXECUTOR_UID, which holds when the suite itself runs as that uid — true inside
# the ads-mutator image, which is the identity that actually matters. Anywhere else on Linux
# we SKIP LOUDLY rather than fail confusingly or pass vacuously.
_UID_OK = (not PF.applies()) or os.getuid() == PF.EXECUTOR_UID
_SKIP_WHY = ("Linux pre-flight requires the store to be usable by uid %d; this suite is "
             "running as uid %d. Run it inside the ads-mutator image to exercise it for "
             "real." % (PF.EXECUTOR_UID, os.getuid()))

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
# /bin/cat, not cat: a test puts a failing `cat` first on PATH to prove the WRAPPER's
# own post-Compose `cat` cannot decide its status (F14).
printf '%%s\n' "$@" > "$(dirname "$0")/docker.argv"
printf '%%s\n' "${HERMES_EXIT_NONCE-<unset>}" >> "$(dirname "$0")/docker.nonces"
/bin/cat <<'HERMES_FAKE_DOCKER_EOF'
HERMES-RESULT-JSON %(payload)s
HERMES_FAKE_DOCKER_EOF
%(attest)s
exit %(rc)s
"""

_SAME = object()
FORGED_NONCE = "fedcba9876543210fedcba9876543210"


@unittest.skipUnless(_UID_OK, _SKIP_WHY)
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
        # The COMPLETE skeleton. The pre-flight stats every one of these (except
        # "records", which it deliberately never declares — spec 2026-09-23 §2.5, it
        # is host-side only) and refuses the whole run if any is missing; creating only
        # registry/ made this fixture pass on darwin (pre-flight silent) and fail on
        # Linux (pre-flight live). See the platform gate above. "records" IS created
        # here even though the pre-flight never checks it: persist_run_record_shim now
        # REFUSES rather than auto-creates a missing records/ tree (F12 review — the
        # layout row is a hard prerequisite, `init-host-layout.py --apply` owns it, not
        # a defensive os.makedirs at persist time), so this fixture has to lay it down
        # itself, the same way it lays down the other four.
        for _d in ("approvals", "control", "registry", "log", "seen", "records"):
            os.makedirs(os.path.join(self.gov, _d), exist_ok=True)
        self.records = governance_lib.records_dir(SLUG, root=self.gov)
        reg = governance_lib.clients_registry_path(self.gov)
        os.makedirs(os.path.dirname(reg), exist_ok=True)
        with open(reg, "w") as f:
            json.dump({"clients": {SLUG: {"project": "claude_google_ads",
                                          "customer_id": "1234567890",
                                          "status": "active"}}}, f)
        self.bin = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.bin)

    def _fake_docker(self, rc=0, attest_rc=_SAME, attest_times=1, extra=""):
        """attest_rc: the status the fake EXECUTOR attests (default: the same as rc; None:
        no line — Compose's own failure). extra: one more raw shell line (a forgery)."""
        if attest_rc is _SAME:
            attest_rc = rc
        lines = []
        if attest_rc is not None:
            lines = ["printf 'HERMES-EXIT %%s %d\\n' \"$HERMES_EXIT_NONCE\"" % attest_rc] \
                * attest_times
        if extra:
            lines.append(extra)
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as f:
            f.write(FAKE_DOCKER % {"payload": json.dumps(RESULT), "rc": rc,
                                   "attest": "\n".join(lines)})
        os.chmod(p, 0o755)

    def _run(self, executor_rc=0, **fake):
        self._fake_docker(executor_rc, **fake)
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["HERMES_GOVERNANCE_DIR"] = self.gov
        # F9: compose-only interpolation inputs. The wrapper never lets Compose read .env
        # (--env-file /dev/null), so they must come from the environment, as on the VPS.
        env["HERMES_AGENT_DIR"] = self.home
        env["HERMES_ADS_REPO_DIR"] = os.path.join(self.tmp, "ads-repo")
        env["HERMES_SPOOL_DIR"] = os.path.join(self.tmp, "spool")
        env.pop("VAULT_ROOT", None)          # hostenv.sh owns it; see the class docstring
        env.pop("HERMES_EXIT_NONCE", None)   # the wrapper must generate its own
        p = subprocess.run(
            ["/bin/sh", self.wrapper, "--client", SLUG, "--changeset", CID],
            capture_output=True, text=True, env=env, timeout=120)
        return p

    def _patch_wrapper(self, old, new):
        """Firing controls edit the fixture's TEMP COPY of the wrapper, never the tracked
        file. `old` must occur exactly once, so a control cannot silently patch nothing."""
        with open(self.wrapper) as f:
            text = f.read()
        self.assertEqual(text.count(old), 1, "control anchor %r not found once" % old)
        with open(self.wrapper, "w") as f:
            f.write(text.replace(old, new))

    def _nonces(self):
        with open(os.path.join(self.bin, "docker.nonces")) as f:
            return f.read().splitlines()

    def _poison_the_records_dir(self):
        """Make persist refuse for the reason that matters: a timeline symlinked out
        of the records directory (F12: no longer the vault). This is the containment
        refusal, not a generic I/O error."""
        outside = os.path.join(self.tmp, "outside.md")
        open(outside, "w").close()
        os.makedirs(self.records, exist_ok=True)
        os.symlink(outside, os.path.join(self.records, "timeline.md"))


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
        self.assertTrue(os.path.exists(os.path.join(self.records, "timeline.md")),
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
        self._poison_the_records_dir()
        p = self._run(executor_rc=0)
        self.assertIn("RUN RECORD NOT PERSISTED", p.stderr)
        self.assertIn("CONTAINMENT REFUSAL", p.stderr)
        # It must say what to do, not merely that something happened. F12: a refusal
        # now means something in the governance store's records/ tree, not the vault —
        # sending an operator to the wrong tree mid-incident costs real time.
        self.assertIn("records/<client>", p.stderr)
        self.assertIn("governance audit log", p.stderr)

    def test_the_banner_does_not_assert_an_attack_as_the_only_cause(self):
        """F12 review (I1). Exit 2 covers TWO causes now: a records/ tree that
        `init-host-layout.py --apply` has not created yet (the likeliest one, right
        after a pull) and a genuine containment refusal. The banner used to state the
        second as fact — "treat it as an attempt to make this step write outside
        records/" with no alternative offered — which hands an operator a security
        incident for a setup mistake. It must now name the setup cause, name the
        remediation, and point at the `persist-run-record:` line that distinguishes
        them."""
        self._poison_the_records_dir()
        p = self._run(executor_rc=0)
        self.assertIn("init-host-layout.py --apply", p.stderr)
        # The QUOTED form, not a bare "persist-run-record:" — the tool prints its own
        # prefixed line on this path anyway, so a bare substring would pass against a
        # banner that never mentioned it.
        self.assertIn("'persist-run-record:' line", p.stderr)
        self.assertIn("SETUP", p.stderr)
        # And it must not have become vague in the process: the containment reading is
        # still spelled out, it is just no longer the only one on offer.
        self.assertIn("symlink or hardlink", p.stderr)

    def test_the_refusal_does_not_hijack_the_executor_status(self):
        """The other half, and the reason `|| true` was there in the first place. A
        persist failure must be loud but must NEVER become the script's status: exit 0
        here still means the executor succeeded. A fix that simply propagated persist's
        status would pass the test above and fail this one."""
        self._poison_the_records_dir()
        self.assertEqual(self._run(executor_rc=0).returncode, 0)

    def test_it_does_not_mask_a_real_executor_failure_either(self):
        self._poison_the_records_dir()
        self.assertEqual(self._run(executor_rc=3).returncode, 3)

    def test_the_banner_names_the_executor_status_it_is_not_overriding(self):
        """The banner exists to be read next to the exit code. If it did not state
        which status still stands, it would read as though the run itself had failed."""
        self._poison_the_records_dir()
        p = self._run(executor_rc=3)
        self.assertIn("status (3) is UNCHANGED", p.stderr)

    def test_control_no_banner_when_persist_succeeds(self):
        """DISCRIMINATING CONTROL. A wrapper that printed the banner unconditionally
        would satisfy every assertion above while telling the operator nothing."""
        p = self._run(executor_rc=0)
        self.assertNotIn("CONTAINMENT REFUSAL", p.stderr)


class TestComposeNeverReadsEnv(Base):
    """F9 (spec §3.3): as hermes-broker, .env is 600 root:root and Compose aborts on it even
    with every variable exported (spike M4). The wrapper must pass --env-file /dev/null.
    Exercised for real, through Docker, by deploy/bind-agreement-integration.test.py."""

    def test_the_wrapper_passes_env_file_dev_null_before_run(self):
        p = self._run(executor_rc=0)
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = open(os.path.join(self.bin, "docker.argv")).read().splitlines()
        self.assertEqual(argv[:3], ["compose", "--env-file", "/dev/null"], argv)
        self.assertIn("run", argv)
        self.assertLess(argv.index("--env-file"), argv.index("run"))


class TestTheExitIsAttested(Base):
    """F14 (spec 2026-09-23 §3.2). The wrapper passes Compose's status through ONLY when
    exactly one `HERMES-EXIT <nonce> <rc>` line proves the executor chose it. Anything
    else is 4: "the executor may have run; possibly modified"."""

    def test_an_attested_status_passes_through(self):
        for rc in (0, 1, 2, 3):
            p = self._run(executor_rc=rc)
            self.assertEqual(p.returncode, rc, p.stderr)
            self.assertNotIn("EXECUTOR EXIT NOT VERIFIED", p.stderr)

    def test_an_unattested_2_is_not_verified(self):
        p = self._run(executor_rc=2, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=2)", p.stderr)
        self.assertIn("possibly modified", p.stderr)

    def test_compose_failing_with_1_is_not_verified(self):
        """THE F14 CASE: Compose exits 1 on its own (a refused create, a lost connection);
        no executor line exists."""
        p = self._run(executor_rc=1, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", p.stderr)

    def test_a_forged_line_with_the_wrong_nonce_is_not_verified(self):
        p = self._run(executor_rc=2, attest_rc=None,
                      extra="echo 'HERMES-EXIT %s 2'" % FORGED_NONCE)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_line_disagreeing_with_rc_is_not_verified(self):
        p = self._run(executor_rc=0, attest_rc=2)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_second_nonce_line_with_another_rc_is_not_verified(self):
        p = self._run(executor_rc=2,
                      extra="printf 'HERMES-EXIT %s 0\\n' \"$HERMES_EXIT_NONCE\"")
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_two_matching_lines_are_not_verified(self):
        p = self._run(executor_rc=2, attest_times=2)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_an_unknown_status_is_not_verified(self):
        p = self._run(executor_rc=137, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_failing_cat_after_compose_cannot_decide_the_status(self):
        cat = os.path.join(self.bin, "cat")
        with open(cat, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(cat, 0o755)
        p = self._run(executor_rc=2)
        self.assertEqual(p.returncode, 2, p.stderr)

    def test_the_nonce_is_passed_and_fresh_per_run(self):
        self._run(executor_rc=0)
        self._run(executor_rc=0)
        nonces = self._nonces()
        self.assertEqual(len(nonces), 2, nonces)
        for n in nonces:
            self.assertRegex(n, r"^[0-9a-f]{32}$")
        self.assertNotEqual(nonces[0], nonces[1])
        argv = open(os.path.join(self.bin, "docker.argv")).read().splitlines()
        i = argv.index("HERMES_EXIT_NONCE")
        self.assertEqual(argv[i - 1], "-e")
        self.assertLess(i, argv.index("ads-mutator"))

    def test_no_nonce_means_no_run(self):
        """Nonce generation failing must refuse BEFORE Compose — never run unattestable."""
        od = os.path.join(self.bin, "od")
        with open(od, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(od, 0o755)
        p = self._run(executor_rc=0)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("exit nonce", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.bin, "docker.argv")),
                         "Compose ran without a nonce")


class TestAttestationFiringControls(Base):
    """Each control breaks the fixture's TEMP COPY of the wrapper the way a regression
    would, and shows the matching test above would have caught it."""

    def test_control_a_wrapper_that_trusts_rc_passes_an_unattested_2(self):
        self._patch_wrapper("final=4  # F14", "final=$rc  # F14")
        p = self._run(executor_rc=2, attest_rc=None)
        self.assertEqual(p.returncode, 2, "control did not fire:\n" + p.stderr)

    def test_control_set_e_after_compose_lets_cat_decide(self):
        self._patch_wrapper("set +e  # F14", "set -e  # F14")
        cat = os.path.join(self.bin, "cat")
        with open(cat, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(cat, 0o755)
        p = self._run(executor_rc=2)
        self.assertEqual(p.returncode, 1, "control did not fire:\n" + p.stderr)


if __name__ == "__main__":
    unittest.main()
