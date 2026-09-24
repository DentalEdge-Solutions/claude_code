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
against a real .env. Also unproven: F12 §2.3's root guard and approve-changeset.py's
own CLI path — TestApprovalOwnership drives changeset_lib.write_snapshot_bytes /
write_approval directly (the same calls approve-changeset.py makes), not the CLI
itself, because exercising the CLI end to end needs a vault this fixture does not
build.
"""
import grp, json, os, pwd, shutil, stat, subprocess, sys, tempfile, unittest, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
REQUIRED = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
GATEWAY = ["setpriv", "--reuid", "10000", "--regid", "10000", "--clear-groups"]
# The broker unit's identity: User/Group hermes-broker, SupplementaryGroups hermes-rail hermes.
BROKER = ["setpriv", "--reuid", "hermes-broker", "--regid", "hermes-broker",
          "--groups", "hermes,hermes-rail"]
CID = "20260921-000000-abcdef01"
CLIENT = "slug-1"          # sanctioned fixture, deliberately NOT registered

# §6B. Run as GATEWAY or BROKER against one log file. Prints one JSON object: each
# operation's outcome ("OK" or its errno name) and the line count around them. Only ever
# pointed at a test fixture's log inside this test's own store.
PROBE = r'''
import errno, json, os, sys
p = sys.argv[1]
def lines():
    with open(p, "rb") as f:
        return f.read().count(b"\n")
def attempt(fn):
    try:
        fn()
        return "OK"
    except OSError as e:
        return errno.errorcode.get(e.errno, str(e.errno))
def append():
    with open(p, "a") as f:
        f.write("{}\n")
def overwrite():
    fd = os.open(p, os.O_WRONLY)
    try:
        os.pwrite(fd, b"X", 0)
    finally:
        os.close(fd)
out = {"before": lines(), "append": attempt(append)}
out["after_append"] = lines()
out["overwrite"] = attempt(overwrite)
out["o_trunc"] = attempt(lambda: os.close(os.open(p, os.O_WRONLY | os.O_TRUNC)))
out["truncate"] = attempt(lambda: os.truncate(p, 0))
out["after"] = lines()
print(json.dumps(out))
'''


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

    def assert_check_names(self, needle, path=None):
        """needle must appear in --check's stderr. With `path`, pin it to ONE line that
        also names that path — several entries in the layout table share an
        owner:group mode (e.g. results/ and approvals/ are both hermes-broker:hermes
        2750), so a bare substring match can be right for the wrong reason."""
        r = self.layout_tool("--check")
        self.assertEqual(r.returncode, 2, r.stdout)
        if path is None:
            self.assertIn(needle, r.stderr)
        else:
            lines = r.stderr.splitlines()
            self.assertTrue(any(path in l and needle in l for l in lines),
                            "no stderr line names both %r and %r:\n%s"
                            % (path, needle, r.stderr))


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
        tmp = tempfile.mkdtemp(dir="/tmp")
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
        self.assert_check_names("expected hermes-broker:hermes 2750", self.path("results"))

    def test_control_without_a_precreated_quarantine_the_gateway_claims_it(self):
        q = self.path("requests", ".quarantine")
        os.rmdir(q)
        self.assertTrue(self.gw_os("mkdir", q))
        self.assert_check_names(".quarantine")

    def test_control_a_writable_spool_root_lets_the_gateway_rename_requests(self):
        os.chmod(self.spool, 0o770)
        self.assertTrue(self.gw_os("rename", self.path("requests"), self.path("r2")))
        self.assert_check_names("expected root:hermes 0750", self.spool)

    def test_control_a_group_readable_quarantine_lets_the_gateway_list_it(self):
        q = self.path("requests", ".quarantine")
        os.chmod(q, 0o750)
        os.chown(q, -1, 10000)
        self.assertTrue(self.gw_os("listdir", q))
        self.assert_check_names(".quarantine")

    def test_control_without_the_sticky_bit_the_gateway_removes_quarantine(self):
        os.chmod(self.path("requests"), 0o2770)
        q = self.path("requests", ".quarantine")
        self.assertTrue(self.gw_os("rmdir", q))
        self.assert_check_names("expected hermes-broker:hermes 3770")


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


class TestRunRecords(Layout):
    """F12 half B, with real identities: the broker writes run records into the store, the
    gateway cannot, and the hermes group can read them."""

    SLUG = "slug-1"

    def register_client(self):
        """vault_lib.resolve refuses an unregistered slug, so the record path needs one."""
        reg = os.path.join(self.store, "registry", "clients.json")
        with open(reg, "w") as f:
            json.dump({"clients": {self.SLUG: {"project": "claude_google_ads",
                                               "customer_id": "1234567890",
                                               "status": "active"}}}, f)
        run(["chown", "root:hermes", reg], check=True)
        run(["chmod", "0640", reg], check=True)

    def persist_as_broker(self, payload):
        """Drive the real CLI the wrapper drives, on stdin, as hermes-broker."""
        p = subprocess.run(BROKER + ["python3", self.py("persist-run-record.py"),
                                     "--client", self.SLUG],
                           input=payload, capture_output=True, text=True, env=self.env)
        return p

    def test_the_broker_writes_a_record_the_group_can_read(self):
        self.register_client()
        cid = "20260923-120000-abcdef01"
        payload = ('HERMES-RESULT-JSON {"changeset_id": "%s", "status": "ok", "applied": 1, '
                   '"finished_at": "2026-09-23T12:00:00Z", "operator": "operator", '
                   '"actions": []}\n' % cid)
        p = self.persist_as_broker(payload)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rec = os.path.join(self.store, "records", self.SLUG, cid + ".result.json")
        st = os.stat(rec)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640, rec)
        self.assertEqual(grp.getgrgid(st.st_gid).gr_name, "hermes")
        self.assertTrue(os.path.isfile(os.path.join(self.store, "records", self.SLUG,
                                                    "timeline.md")))
        # The mode and the gid name are necessary but not sufficient — the per-slug
        # directory also has to be traversable by group hermes. Have an actual hermes
        # member (uid 10000, gid 10000 == group hermes) read the record back.
        r = self.gateway("python3", "-c", "import sys; open(sys.argv[1]).read()", rec)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_gateway_cannot_write_into_records(self):
        """The refusal has to come from the records/slug-1/ directory's real MODE, not
        from the directory not existing yet. Create it the production way first
        (persist_as_broker, which makes it hermes-broker:hermes 02750 through the real
        persist path), then attempt the write and pin the cause to a permission error."""
        self.register_client()
        cid = "20260923-130000-abcdef02"
        payload = ('HERMES-RESULT-JSON {"changeset_id": "%s", "status": "ok", "applied": 1, '
                   '"finished_at": "2026-09-23T13:00:00Z", "operator": "operator", '
                   '"actions": []}\n' % cid)
        p = self.persist_as_broker(payload)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        target = os.path.join(self.store, "records", self.SLUG, "planted.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1], 'w').write('x')", target)
        self.assertNotEqual(r.returncode, 0, "the gateway wrote into records/: %s" % r.stdout)
        self.assertIn("Permission denied", r.stderr)

    def test_control_a_group_writable_records_dir_lets_the_gateway_write(self):
        """Proves the refusal above comes from the MODE, not from something unrelated."""
        self.register_client()
        d = os.path.join(self.store, "records", self.SLUG)
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o770)
        run(["chgrp", "hermes", d], check=True)
        target = os.path.join(d, "planted.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1], 'w').write('x')", target)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestApprovalOwnership(Layout):
    """F12 half A, the exact failure the finding records: root approves, then the broker
    must be able to reserve. Before the fix the lock sidecar is root-owned 0600 and
    reserve_approval fails on the first apply."""

    SLUG = "slug-1"
    CID = "20260923-120000-abcdef01"

    def approve_as_root(self):
        """Write the snapshot + approval the way approve-changeset does, as root."""
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import changeset_lib as C, datetime;"
            "d = C.write_snapshot_bytes(%r, %r, b'{\"actions\": []}\\n');"
            "C.write_approval(%r, %r, d, 'operator',"
            " datetime.datetime(2026, 9, 23, 12, 0, 0, tzinfo=datetime.timezone.utc), 24)"
            % (self.bin, self.SLUG, self.CID, self.SLUG, self.CID))
        return run(["python3", "-c", code], env=self.env)

    def reserve_as_broker(self):
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import changeset_lib as C, datetime;"
            "C.reserve_approval(%r, %r, '00000000-0000-4000-8000-000000000000',"
            " datetime.datetime(2026, 9, 23, 12, 5, 0, tzinfo=datetime.timezone.utc))"
            % (self.bin, self.SLUG, self.CID))
        return run(BROKER + ["python3", "-c", code], env=self.env)

    def test_root_approves_and_the_broker_can_reserve(self):
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = os.path.join(self.store, "approvals", self.SLUG)
        # R2: the directory itself must be OWNED by hermes-broker (not merely group
        # hermes) or the broker cannot create the .tmp files it needs inside it. Tier 2
        # is the only place that can check this — Tier 1 has no second identity.
        self.assertEqual(pwd.getpwuid(os.stat(d).st_uid).pw_name, "hermes-broker", d)
        lock = os.path.join(d, self.CID + ".approval.lock")
        st = os.stat(lock)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o660, lock)
        self.assertEqual(pwd.getpwuid(st.st_uid).pw_name, "hermes-broker")
        r = self.reserve_as_broker()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The broker's own egid is hermes-broker, not hermes — only the directory's
        # setgid bit keeps the REWRITTEN approval record's group at hermes after this
        # write-back. If that bit were ever lost, this is the assertion that would
        # catch it (the R1 failure mode, one directory over).
        approval = os.path.join(d, self.CID + ".approval.json")
        self.assertEqual(grp.getgrgid(os.stat(approval).st_gid).gr_name, "hermes",
                         approval)

    def test_firing_control_a_root_owned_0600_lock_breaks_reserve(self):
        """F12 as it was: this is the state the fix removes. If this ever passes, the
        assertion above is not proving what it claims."""
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lock = os.path.join(self.store, "approvals", self.SLUG,
                            self.CID + ".approval.lock")
        os.chown(lock, 0, 0)
        os.chmod(lock, 0o600)
        r = self.reserve_as_broker()
        self.assertNotEqual(r.returncode, 0,
                            "the broker reserved through a root-owned 0600 lock")

    def test_firing_control_a_root_owned_02755_approvals_dir_breaks_reserve(self):
        """R2 as it was before this fix: the sidecar control above covers Task 3 only.
        Nothing else forces the approvals/<slug>/ DIRECTORY back to its pre-R2 shape —
        root-owned, group hermes with no write bit. reserve_approval opens the
        (correctly-owned) lock sidecar fine, then fails at _atomic_write_json's
        open(tmp, "w") — a different failure site from the sidecar control's, and this
        is the control that names it."""
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = os.path.join(self.store, "approvals", self.SLUG)
        os.chown(d, 0, 0)
        os.chmod(d, 0o2755)
        r = self.reserve_as_broker()
        self.assertNotEqual(r.returncode, 0, "the broker wrote into a root-owned 02755 dir")

    def test_the_executor_uid_can_read_the_approval(self):
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        approval = os.path.join(self.store, "approvals", self.SLUG,
                                self.CID + ".approval.json")
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1]).read()", approval)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_control_a_0600_approval_is_unreadable_to_the_executor(self):
        r = self.approve_as_root()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        approval = os.path.join(self.store, "approvals", self.SLUG,
                                self.CID + ".approval.json")
        os.chmod(approval, 0o600)
        r = self.gateway("python3", "-c",
                         "import sys; open(sys.argv[1]).read()", approval)
        self.assertNotEqual(r.returncode, 0)


class TestTheRunnerSupportsAppendOnly(Layout):
    """Spec §6 Tier 2 (4). Every §6B test below depends on the runner's filesystem holding
    the append-only flag. If it cannot, that must FAIL — under
    HERMES_REQUIRE_LINUX_INTEGRATION=1 a skip is already a failure, and this is not a skip:
    a runner that silently cannot seal would make every EPERM assertion below meaningless."""

    def test_chattr_a_takes_on_this_filesystem(self):
        p = os.path.join(self.base, "fs-guard")
        open(p, "w").close()
        r = run(["chattr", "+a", p])
        self.addCleanup(run, ["chattr", "-a", p])      # LIFO: runs before Layout's rmtree
        self.assertEqual(r.returncode, 0, r.stderr)
        flags = run(["lsattr", p], check=True).stdout.split()[0]
        self.assertIn("a", flags)


class TestAuditLogsAreAppendOnly(Layout):
    """§6B (spec 2026-09-24-s6b-audit-log-append-only-design.md). A log bootstrapped the
    documented way (root, migrate-governance.py --bootstrap-logs --apply) must admit
    appends and refuse truncation and overwrite — for the executor (uid 10000) AND the
    broker, which is in gid 10000 and so holds group write on the file. Measured on the box
    2026-09-24: before sealing, both could truncate."""

    SLUG = "s6b-client"

    def setUp(self):
        super().setUp()
        self.register_client()
        # Registered AFTER Layout's rmtree cleanup, so it runs FIRST (LIFO): rmtree cannot
        # remove an append-only file. A no-op when the file is absent or unsealed.
        self.addCleanup(run, ["chattr", "-a", self.log()])

    def register_client(self):
        reg = os.path.join(self.store, "registry", "clients.json")
        with open(reg, "w") as f:
            json.dump({"clients": {self.SLUG: {"project": "claude_google_ads",
                                               "customer_id": "1234567890",
                                               "status": "active"}}}, f)
        run(["chown", "root:hermes", reg], check=True)
        run(["chmod", "0640", reg], check=True)

    def bootstrap(self):
        r = run(["python3", self.py("migrate-governance.py"), "--bootstrap-logs", "--apply",
                 "--governance-root", self.store], env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(self.log()))

    def log(self):
        return os.path.join(self.store, "log", "%s.jsonl" % self.SLUG)

    def probe(self, who):
        r = run(list(who) + ["python3", "-c", PROBE, self.log()], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def lsattr_flags(self, path):
        return run(["lsattr", path], check=True).stdout.split()[0]

    def _assert_append_only_for(self, who):
        self.bootstrap()
        out = self.probe(who)
        # The security property FIRST (canon lesson "check why a RED is red"): on the
        # exact errno, not "some error". Truncation is what resets the caps.
        self.assertEqual(out["o_trunc"], "EPERM", out)
        self.assertEqual(out["truncate"], "EPERM", out)
        self.assertEqual(out["overwrite"], "EPERM", out)
        self.assertEqual(out["after"], out["after_append"], out)
        # ... and the one legitimate write still works.
        self.assertEqual(out["append"], "OK", out)
        self.assertEqual(out["after_append"], out["before"] + 1, out)
        self.assertIn("a", self.lsattr_flags(self.log()))

    def test_the_executor_cannot_truncate_a_bootstrapped_log(self):
        self._assert_append_only_for(GATEWAY)

    def test_the_broker_cannot_truncate_a_bootstrapped_log(self):
        self._assert_append_only_for(BROKER)

    def test_append_log_still_works_on_a_bootstrapped_log_as_the_executor(self):
        """Review Focus 3. The real writer, not the probe: append_log also fsyncs the log/
        DIRECTORY fd. A regression guard — it passes on pre-§6B code too."""
        self.bootstrap()
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import changeset_lib as C; "
                "C.append_log(sys.argv[2], {'ts': '2026-09-24T00:00:00Z', "
                "'changeset_id': '20260924-000000-abcdef01', 'status': 'applied'})")
        r = self.gateway("python3", "-c", code, self.bin, self.SLUG)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log(), "rb") as f:
            self.assertEqual(f.read().count(b"\n"), 1)

    def test_control_without_the_seal_call_the_executor_truncates(self):
        """FIRING CONTROL for the property tests: the same bootstrap with the seal call
        removed from THIS TEST'S COPY of bin/ (never the tracked file) leaves truncation
        open — so those tests fail when the seal is missing, not by accident."""
        shim = os.path.join(self.bin, "migrate_governance_shim.py")
        with open(shim) as f:
            src = f.read()
        needle = "governance_lib.set_append_only(dst)\n"
        self.assertEqual(src.count(needle), 1)
        with open(shim, "w") as f:
            f.write(src.replace(needle, "pass\n"))
        self.bootstrap()
        out = self.probe(GATEWAY)
        self.assertEqual(out["o_trunc"], "OK", out)
        self.assertNotIn("a", self.lsattr_flags(self.log()))

    def test_the_preflight_refuses_a_log_whose_flag_was_cleared(self):
        self.bootstrap()
        pf = ("python3", self.py("preflight-governance-access.py"), "--root", self.store)
        r = self.broker(*pf)
        self.assertEqual(r.returncode, 0, r.stderr)
        run(["chattr", "-a", self.log()], check=True)
        r = self.broker(*pf)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not append-only", r.stderr)
        self.assertNotIn(self.SLUG, r.stderr)          # counts, never slugs


class TestAppendOnlyHelper(Layout):
    """§6B Tier 2 (1): governance_lib's ioctl numbers and 4-byte buffer against the real
    kernel, cross-checked with lsattr — the same tool the box measurement used."""

    def g(self, code, path):
        """Run `code` with G = the copied governance_lib, as root. Returns the result."""
        return run(["python3", "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); import governance_lib as G; "
                    + code, self.bin, path], env=self.env)

    def fresh(self, name):
        p = os.path.join(self.base, name)
        open(p, "w").close()
        self.addCleanup(run, ["chattr", "-a", p])      # before Layout's rmtree (LIFO)
        return p

    def lsattr_flags(self, path):
        return run(["lsattr", path], check=True).stdout.split()[0]

    def test_set_then_read_agrees_with_lsattr(self):
        p = self.fresh("sealed")
        r = self.g("G.set_append_only(sys.argv[2]); print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True")
        self.assertIn("a", self.lsattr_flags(p))

    def test_a_plain_file_reads_false(self):
        p = self.fresh("plain")
        r = self.g("print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "False")
        self.assertNotIn("a", self.lsattr_flags(p))

    def test_a_symlink_is_refused(self):
        target = self.fresh("target")
        run(["chattr", "+a", target], check=True)
        link = os.path.join(self.base, "link")
        os.symlink(target, link)
        r = self.g("G.is_append_only(sys.argv[2])", link)
        self.assertNotEqual(r.returncode, 0)
        # O_NOFOLLOW -> ELOOP; the traceback prints its strerror.
        self.assertIn("Too many levels of symbolic links", r.stderr)

    def test_control_a_wrong_flag_constant_is_caught_only_by_lsattr(self):
        """FIRING CONTROL for the lsattr cross-check. With the constant set to NODUMP (0x40,
        harmless) the helper sets and "verifies" the wrong bit and reports success — only
        lsattr shows the file is not append-only. This is why test_set_then_read_agrees_
        with_lsattr asserts lsattr and not just the helper's own answer."""
        p = self.fresh("wrong-constant")
        r = self.g("G.LOG_APPEND_ONLY_FL = 0x40; G.set_append_only(sys.argv[2]); "
                   "print(G.is_append_only(sys.argv[2]))", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True")      # the helper is fooled
        self.assertNotIn("a", self.lsattr_flags(p))     # lsattr is not


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
