#!/usr/bin/env python3
"""Tier 2 for F10: the store and spool layout under REAL Linux uids, gids and modes.

WHY A SEPARATE SUITE. Tier 1 (bin/host_layout.test.py and friends) runs as one
unprivileged user. It proves the table and the checks. It cannot prove that the gateway
(uid 10000) and the broker (hermes-broker) can each do what they must and nothing more.
That needs root, to create the identities, and setpriv, to become them.

WHERE IT RUNS. As root on Linux: the CI `tests` job runs it under sudo with
HERMES_REQUIRE_LINUX_INTEGRATION=1. Anywhere else it prints SKIPPED and exits 0 —
unless that variable is set, in which case any skip is a FAILURE. It prints how many
tests executed. Read that line in the CI log on the PR and on the merge commit: a green
job that executed 0 tests proves nothing.

NOT FOR THE VPS. It creates users and groups (idempotently, README step 1's names) and
writes under /var/lib. Run it on a CI runner, not on the deploy target.

UNPROVEN HERE (spec §5.3): systemd's ProtectSystem=strict with the new ReadWritePaths;
the real gateway identity inside the hermes-agent image; compose's :? interpolation
against a real .env.
"""
import os, shutil, stat, subprocess, sys, tempfile, unittest, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
REQUIRED = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
GATEWAY = ["setpriv", "--reuid", "10000", "--regid", "10000", "--clear-groups"]
# The broker unit's identity: User/Group hermes-broker, SupplementaryGroups hermes-rail hermes.
BROKER = ["setpriv", "--reuid", "hermes-broker", "--regid", "hermes-broker",
          "--groups", "hermes,hermes-rail"]
CID = "20260921-000000-abcdef01"
CLIENT = "slug-1"          # sanctioned fixture, deliberately NOT registered


def why_not_runnable():
    if not sys.platform.startswith("linux"):
        return "not Linux"
    if os.geteuid() != 0:
        return "not root"
    if shutil.which("setpriv") is None:
        return "setpriv not found"
    return None


def run(argv, env=None, check=False):
    return subprocess.run(argv, env=env, capture_output=True, text=True, check=check)


def setUpModule():
    why = why_not_runnable()
    if why:
        raise unittest.SkipTest(why)
    run(["groupadd", "-f", "hermes-rail"], check=True)
    run(["groupadd", "-f", "hermes-broker"], check=True)
    g = run(["getent", "group", "hermes"])
    if g.returncode != 0:
        run(["groupadd", "-g", "10000", "hermes"], check=True)
    elif g.stdout.split(":")[2] != "10000":
        raise RuntimeError("group 'hermes' is gid %s here, not 10000"
                           % g.stdout.split(":")[2])
    if run(["id", "hermes-broker"]).returncode != 0:
        run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
             "-g", "hermes-broker", "hermes-broker"], check=True)


class Layout(unittest.TestCase):
    """A fresh layout per test, created the documented way: init-host-layout.py --apply,
    as root, from a private copy of bin/ that both identities can read."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="hermes-f10-it-", dir="/var/lib")
        self.addCleanup(shutil.rmtree, self.base, True)
        os.chmod(self.base, 0o755)
        agent = os.path.join(self.base, "agent")
        os.mkdir(agent, 0o755)
        self.bin = os.path.join(agent, "bin")
        skip = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(os.path.join(AGENT, "bin"), self.bin, ignore=skip)
        shutil.copytree(os.path.join(AGENT, "registry"), os.path.join(agent, "registry"),
                        ignore=skip)
        run(["chmod", "-R", "a+rX", agent], check=True)
        self.store = os.path.join(self.base, "governance")
        self.spool = os.path.join(self.base, "spool")
        self.env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                    "HERMES_SPOOL_ROOT": self.spool, "HERMES_GOVERNANCE_ROOT": self.store,
                    "VAULT_ROOT": os.path.join(self.base, "vaults")}
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def py(self, name):
        return os.path.join(self.bin, name)

    def path(self, *parts):
        return os.path.join(self.spool, *parts)

    def layout_tool(self, *flags, who=()):
        return run(list(who) + ["python3", self.py("init-host-layout.py"),
                                "--store-root", self.store, "--spool-root", self.spool,
                                *flags], env=self.env)

    def gateway(self, *argv):
        return run(GATEWAY + list(argv), env=self.env)

    def broker(self, *argv):
        return run(BROKER + list(argv), env=self.env)

    def gw_os(self, fn, *args):
        """os.<fn>(*args) as the gateway. True if it succeeded."""
        r = self.gateway("python3", "-c", "import os, sys; os.%s(*sys.argv[1:])" % fn, *args)
        return r.returncode == 0

    def gw_create(self, p):
        r = self.gateway("python3", "-c", "import sys; open(sys.argv[1], 'w').close()", p)
        return r.returncode == 0

    def gw_plant_dir(self, mode, content=True):
        """The gateway mkdirs a UUID-named entry in requests/, optionally non-empty."""
        p = self.path("requests", "%s.json" % uuid.uuid4())
        code = ("import os, sys; os.mkdir(sys.argv[1]);"
                "sys.argv[3] == '1' and open(os.path.join(sys.argv[1], 'x'), 'w').close();"
                "os.chmod(sys.argv[1], int(sys.argv[2], 8))")
        r = self.gateway("python3", "-c", code, p, mode, "1" if content else "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        return p

    def submit(self):
        r = self.gateway("python3", self.py("hermes-syscall.py"), "apply",
                         "--client", CLIENT, "--changeset", CID)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def fetch(self, rid):
        return self.gateway("python3", self.py("hermes-syscall.py"), "result",
                            "--request-id", rid)

    def drain(self):
        r = self.broker("python3", self.py("hermes-broker.py"), "--once")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def assert_check_names(self, needle):
        r = self.layout_tool("--check")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(needle, r.stderr)


class TestGates(Layout):
    def test_layout_check_passes_as_the_broker(self):
        r = self.layout_tool("--check", who=BROKER)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_preflight_passes_as_the_broker_on_a_fresh_store(self):
        """The state the bring-up never reached."""
        r = self.broker("python3", self.py("preflight-governance-access.py"),
                        "--root", self.store)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_preflight_on_a_missing_root_is_one_line(self):
        r = self.broker("python3", self.py("preflight-governance-access.py"),
                        "--root", os.path.join(self.base, "absent"))
        self.assertEqual(r.returncode, 2)
        lines = [l for l in r.stderr.splitlines() if l.startswith("  - ")]
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn("missing", lines[0])

    def test_bootstrap_logs_accepts_the_fresh_store(self):
        r = run(["python3", self.py("migrate-governance.py"), "--bootstrap-logs",
                 "--apply", "--governance-root", self.store], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_layout_under_tmp_is_refused_and_nothing_is_created(self):
        """Firing control for the ancestor check: /tmp is world-writable."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        r = run(["python3", self.py("init-host-layout.py"), "--apply",
                 "--store-root", os.path.join(tmp, "g"),
                 "--spool-root", os.path.join(tmp, "s")], env=self.env)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("writable", r.stderr)
        self.assertEqual(os.listdir(tmp), [])

    def test_the_bring_up_store_is_refused_until_it_is_removed(self):
        """Spec §3.4: the VPS store is an empty 700 root:root dir. Refuse, rmdir, apply."""
        shutil.rmtree(self.store)
        os.mkdir(self.store, 0o700)
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 2)
        self.assertIn("expected root:hermes 0750", r.stderr)
        os.rmdir(self.store)
        r = self.layout_tool("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)


class TestRoundTrip(Layout):
    def test_gateway_request_broker_result_gateway_read(self):
        rid = self.submit()
        req = self.path("requests", rid + ".json")
        st = os.stat(req)
        self.assertEqual((st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)),
                         (10000, 10000, 0o640))
        self.drain()
        self.assertFalse(os.path.exists(req))
        r = self.fetch(rid)
        self.assertNotIn("result_unreadable", r.stdout)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)   # refused: unregistered
        self.assertIn("refused", r.stdout)

    def test_firing_control_0600_spool_files_break_the_round_trip(self):
        """F10a reinstated in this test's private copy of the code: the same round trip
        must now fail with result_unreadable. Proves the test above can go red."""
        p = self.py("spool_lib.py")
        with open(p) as f:
            src = f.read()
        needle = "SPOOL_FILE_MODE = 0o640"
        self.assertEqual(src.count(needle), 1, "control is vacuous: the constant moved")
        with open(p, "w") as f:
            f.write(src.replace(needle, "SPOOL_FILE_MODE = 0o600"))
        rid = self.submit()
        self.drain()
        self.assertIn("result_unreadable", self.fetch(rid).stdout)


class TestAttackProbes(Layout):
    """As uid 10000, against the correct layout: each attack fails."""

    def test_the_gateway_cannot_remove_rename_or_list_quarantine(self):
        q = self.path("requests", ".quarantine")
        self.assertFalse(self.gw_os("rename", q, q + "-moved"))
        self.assertFalse(self.gw_os("rmdir", q))
        self.assertFalse(self.gw_os("listdir", q))

    def test_the_gateway_cannot_rename_requests_or_results(self):
        self.assertFalse(self.gw_os("rename", self.path("requests"), self.path("r2")))
        self.assertFalse(self.gw_os("rename", self.path("results"), self.path("r3")))

    def test_the_gateway_cannot_forge_a_result(self):
        self.assertFalse(self.gw_create(self.path("results", "%s.json" % uuid.uuid4())))

    # Firing controls: each wrong layout lets the attack through, and --check names it.

    def test_control_without_the_sticky_bit_the_gateway_renames_quarantine(self):
        os.chmod(self.path("requests"), 0o2770)
        q = self.path("requests", ".quarantine")
        self.assertTrue(self.gw_os("rename", q, q + "-moved"))
        self.assert_check_names("expected hermes-broker:hermes 3770")

    def test_control_a_group_writable_results_lets_the_gateway_forge(self):
        os.chmod(self.path("results"), 0o2770)
        self.assertTrue(self.gw_create(self.path("results", "%s.json" % uuid.uuid4())))
        self.assert_check_names("expected hermes-broker:hermes 2750")

    def test_control_without_a_precreated_quarantine_the_gateway_claims_it(self):
        q = self.path("requests", ".quarantine")
        os.rmdir(q)
        self.assertTrue(self.gw_os("mkdir", q))
        self.assert_check_names(".quarantine")


class TestQuarantineOwnership(Layout):
    def test_control_a_planted_directory_goes_to_the_real_quarantine(self):
        p = self.gw_plant_dir("777")               # writable, so it CAN be moved
        self.drain()
        self.assertFalse(os.path.exists(p))
        self.assertEqual(len(os.listdir(self.path("requests", ".quarantine"))), 1)

    def test_a_gateway_created_quarantine_is_refused(self):
        q = self.path("requests", ".quarantine")
        os.rmdir(q)
        self.assertTrue(self.gw_os("mkdir", q))
        r = self.gateway("python3", "-c", "import os, sys; os.chmod(sys.argv[1], 0o777)", q)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.gw_plant_dir("777")
        r = self.drain()
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(os.listdir(q), [])
        self.assertIn(".quarantine", r.stderr)


class TestPlantedDirectories(Layout):
    """R1: the drain survives what it cannot remove, and still serves real requests."""

    def test_empty_is_removed_non_empty_stays_and_the_real_request_is_served(self):
        empty = self.gw_plant_dir("700", content=False)
        full = self.gw_plant_dir("700")
        rid = self.submit()
        for _ in range(2):                        # the residual repeats; nothing sticks
            r = self.drain()
            self.assertFalse(os.path.exists(empty))
            self.assertTrue(os.path.isdir(full))
            self.assertIn(os.path.basename(full), r.stderr)
        f = self.fetch(rid)
        self.assertEqual(f.returncode, 2, f.stdout)
        self.assertNotIn("result_unreadable", f.stdout)


class TestSpoolMountPoint(Layout):
    """F10b's premise: inside the container, a bind-mounted spool cannot be renamed."""

    def setUp(self):
        super().setUp()
        if shutil.which("docker") is None or run(["docker", "info"]).returncode != 0:
            self.skipTest("docker unavailable")
        self.data = os.path.join(self.base, "data")
        os.mkdir(self.data)
        os.chown(self.data, 10000, 10000)
        os.chmod(self.data, 0o700)

    def mv(self, *mounts):
        argv = ["docker", "run", "--rm", "--user", "10000:10000"]
        for m in mounts:
            argv += ["-v", m]
        return run(argv + ["busybox:1.36", "mv", "/opt/data/spool", "/opt/data/moved"])

    def test_the_gateway_cannot_move_the_bind_mounted_spool(self):
        r = self.mv(self.data + ":/opt/data", self.spool + ":/opt/data/spool")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.path.isdir(self.path("requests")))

    def test_control_a_spool_under_data_is_movable(self):
        os.mkdir(os.path.join(self.data, "spool"))
        os.chown(os.path.join(self.data, "spool"), 10000, 10000)
        r = self.mv(self.data + ":/opt/data")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.data, "moved")))


if __name__ == "__main__":
    why = why_not_runnable()
    if why:
        print("layout-integration: SKIPPED — %s" % why)
        sys.exit(1 if REQUIRED else 0)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = res.testsRun - len(res.skipped)
    print("layout-integration: executed %d, skipped %d, failures %d, errors %d"
          % (executed, len(res.skipped), len(res.failures), len(res.errors)))
    if not res.wasSuccessful():
        sys.exit(1)
    if REQUIRED and (res.skipped or executed == 0):
        print("layout-integration: HERMES_REQUIRE_LINUX_INTEGRATION=1 and not every test "
              "executed — failing", file=sys.stderr)
        sys.exit(1)
