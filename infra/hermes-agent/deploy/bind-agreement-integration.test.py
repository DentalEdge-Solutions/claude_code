#!/usr/bin/env python3
"""F9 Tier 2: ads-mutator's REAL binds, through the REAL proxy started with the unit's own
flags, driven the way the broker drives it.

WHAT RUNS. The box layout (BRING-UP Phase 2: a checkout under /opt/projects, /opt/hermes-agent
a symlink to it, the ads repo placeholder, the store from init-host-layout.py --apply). The
proxy with hermes-docker-proxy.service's ExecStart arguments (only --listen moved). As
hermes-broker, with hermes-broker.service's Environment= and .env 600 root:root:
/opt/hermes-agent/run-ads-mutate.sh — hostenv.sh, the pre-flight, `docker compose
--env-file /dev/null … run ads-mutator`, the proxy's create check, the real executor in a
stand-in image, which refuses because the kill switch is absent (exit 2).

WHERE IT RUNS. As root on Linux with Docker: the CI `bind-agreement` job runs it under sudo
with HERMES_REQUIRE_LINUX_INTEGRATION=1. Anywhere else it prints SKIPPED and exits 0, unless
that variable is set, in which case any skip is a FAILURE. It prints how many tests executed:
read that line on the PR run AND on the merge commit.

NOT FOR THE VPS. It creates /opt/projects/claude_code, /opt/hermes-agent, the governance
store and the spool, and REFUSES to run if any of them already exists. /opt/projects and
/var/lib/hermes (the store's and spool's shared parent) are shared parents it may ADOPT
rather than own — it narrows its own file-mode and ownership changes to the paths it
creates under them, and never widens an existing parent it did not create. Teardown removes
none of: /opt/projects, /var/lib/hermes, the hermes/hermes-broker/hermes-rail users and
groups, the hermes-agent-claude image tag, or /run/hermes-f9-it — it is written for an
ephemeral CI runner that is discarded whole, not for a host this suite must leave clean.

FIDELITY GAPS (say so, do not paper over): the proxy runs as root here, not as
hermes-docker-proxy (the socket's group, hermes-rail, is what the broker needs, and that is
reproduced); the image is a stand-in; systemd itself is not involved.
"""
import grp, json, os, pwd, re, shutil, subprocess, sys, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(AGENT, "bin"))
import bind_agreement as BA

REQUIRED = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
PROXY_UNIT = open(os.path.join(HERE, "hermes-docker-proxy.service"), encoding="utf-8").read()
BROKER_UNIT = open(os.path.join(HERE, "hermes-broker.service"), encoding="utf-8").read()
UNIT_ENV = BA.unit_environment(BROKER_UNIT)
AGENT_DIR = UNIT_ENV["HERMES_AGENT_DIR"]
ADS_REPO = UNIT_ENV["HERMES_ADS_REPO_DIR"]
STORE = UNIT_ENV["HERMES_GOVERNANCE_DIR"]
SPOOL = UNIT_ENV["HERMES_SPOOL_DIR"]
CHECKOUT = "/opt/projects/claude_code"
REAL_AGENT = os.path.join(CHECKOUT, "infra", "hermes-agent")
SOCK_DIR = "/run/hermes-f9-it"
IMAGE = "hermes-agent-claude"
BROKER = ["setpriv", "--reuid", "hermes-broker", "--regid", "hermes-broker",
          "--groups", "hermes,hermes-rail"]
CMD = ["--client", "slug-1", "--changeset", "20260922-120000-abcdef01",
       "--request", "00000000-0000-4000-8000-000000000000"]
BIN_PIN = "%s/bin:/opt/cc-bin:ro" % AGENT_DIR
CREATE_ALLOWED = re.compile(r"ALLOW POST /v[0-9.]+/containers/create")
CREATE_DENIED = re.compile(r"DENY POST /v[0-9.]+/containers/create")
# F18: the real Compose attach is answered 101 and goes through the upgraded pass-through.
ATTACH_UPGRADED = re.compile(r"UPGRADE POST /v[0-9.]+/containers/[^ ]+/attach[^ ]* \(101\)")
# F14: the real executor's attested exit line, nonce-bound (spec 2026-09-23 §3.1).
ATTESTED_2 = re.compile(r"^HERMES-EXIT [0-9a-f]{32} 2$", re.MULTILINE)
# F19: one raw request through the proxy socket, run AS hermes-broker (the adversary the
# proxy contains). Prints the whole response. A plain socket, not curl: no new dependency.
PROBE = r'''
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(10)
s.connect(sys.argv[1])
s.sendall(("%s %s HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n"
           % (sys.argv[2], sys.argv[3])).encode())
out = b""
while True:
    try:
        d = s.recv(65536)
    except OSError:
        break
    if not d:
        break
    out += d
sys.stdout.write(out.decode("latin1"))
'''
# F19: the refusal the target check logs for a container that is not an ads-mutator run.
TARGET_REFUSED = re.compile(r"DENY (?:GET|DELETE) (?:/v[0-9.]+)?/containers/[0-9a-f]{64}[^ ]* "
                            r"\(target is not an ads-mutator run: entrypoint mismatch\)")
PROXIES = []
_UNIT_PROXY = []


def run(argv, env=None, check=False, timeout=300):
    return subprocess.run(argv, env=env, capture_output=True, text=True, check=check,
                          timeout=timeout)


def why_not_runnable():
    if not sys.platform.startswith("linux"):
        return "not Linux"
    if os.geteuid() != 0:
        return "not root"
    if shutil.which("setpriv") is None:
        return "setpriv not found"
    if shutil.which("docker") is None or run(["docker", "info"]).returncode != 0:
        return "docker unavailable"
    if run(["docker", "compose", "version"]).returncode != 0:
        return "docker compose unavailable"
    for p in (CHECKOUT, AGENT_DIR, STORE, SPOOL, ADS_REPO):
        if os.path.lexists(p):
            return "%s already exists — this suite builds the box layout and must not run on a real host" % p
    return None


def root_env():
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(UNIT_ENV)
    env.pop("DOCKER_HOST", None)          # root talks to the real daemon for setup only
    return env


def setUpModule():
    why = why_not_runnable()
    if why:
        raise unittest.SkipTest(why)
    # README step 1's identities, idempotently (the same as layout-integration.test.py).
    run(["groupadd", "-f", "hermes-rail"], check=True)
    run(["groupadd", "-f", "hermes-broker"], check=True)
    if run(["getent", "group", "hermes"]).returncode != 0:
        run(["groupadd", "-g", "10000", "hermes"], check=True)
    if run(["id", "hermes-broker"]).returncode != 0:
        run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
             "-g", "hermes-broker", "hermes-broker"], check=True)
    # BRING-UP Phase 2: a checkout under /opt/projects, /opt/hermes-agent a SYMLINK to it.
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "data", ".env", ".env.gaw")
    shutil.copytree(AGENT, REAL_AGENT, ignore=skip, symlinks=True)
    # Narrowed to CHECKOUT (the tree this suite just created — why_not_runnable() already
    # refused if it pre-existed): copytree preserves sane modes on its own, this is
    # belt-and-braces, and it must never reach across /opt/projects into some OTHER
    # project a Linux developer keeps there.
    run(["chmod", "-R", "a+rX", CHECKOUT], check=True)
    os.symlink(REAL_AGENT, AGENT_DIR)
    os.makedirs(ADS_REPO, 0o755)
    # BRING-UP Phase 3: .env root 600, dummy values only. Includes every interpolation input.
    env_file = os.path.join(AGENT_DIR, ".env")
    with open(env_file, "w") as f:
        f.write("ANTHROPIC_API_KEY=placeholder-not-a-key\n")
        for k in ("HERMES_GOVERNANCE_DIR", "HERMES_SPOOL_DIR", "HERMES_AGENT_DIR",
                  "HERMES_ADS_REPO_DIR"):
            f.write("%s=%s\n" % (k, UNIT_ENV[k]))
    os.chown(env_file, 0, 0)
    os.chmod(env_file, 0o600)
    # The wrapper refuses without .env.gaw declaring the WRITE role. Placeholders only: the
    # executor refuses at the kill switch, before any credential is read.
    gaw = os.path.join(AGENT_DIR, ".env.gaw")
    with open(gaw, "w") as f:
        f.write("GOOGLE_ADS_CREDENTIAL_ROLE=write\n"
                "GOOGLE_ADS_DEVELOPER_TOKEN=placeholder-not-a-token\n"
                "GOOGLE_ADS_CLIENT_ID=placeholder-not-a-client-id\n"
                "GOOGLE_ADS_CLIENT_SECRET=placeholder-not-a-secret\n"
                "GOOGLE_ADS_REFRESH_TOKEN=placeholder-not-a-token\n"
                "GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890\n"
                "GOOGLE_ADS_CUSTOMER_ID=1234567890\n")
    os.chown(gaw, 0, grp.getgrnam("hermes-broker").gr_gid)
    os.chmod(gaw, 0o640)
    # BRING-UP Phase 2: `sudo install -d -m 755 -o root -g root /var/lib/hermes` — the shared
    # parent of STORE and SPOOL. check_ancestors (bin/host_layout.py) requires every directory
    # ABOVE the store/spool roots to already exist, be a real directory, root-owned and not
    # group/world-writable, or init-host-layout.py --apply refuses outright. exist_ok=True
    # because this parent may legitimately pre-exist (it is not one of the paths the suite
    # OWNS per why_not_runnable() — only STORE and SPOOL themselves are). The mode passed to
    # makedirs is subject to umask, so chmod/chown explicitly afterwards — but ONLY when this
    # suite is the one that created the directory: re-owning a pre-existing /var/lib/hermes
    # would silently override whatever ownership was already there. If it pre-exists and is
    # not suitable, init-host-layout.py --apply refuses on its own ancestor check below, which
    # is the correct outcome — this must not paper over that by forcing the mode/owner first.
    assert os.path.dirname(STORE) == os.path.dirname(SPOOL), (
        "STORE and SPOOL no longer share a parent — the BRING-UP Phase 2 install -d step "
        "creates one directory for both; if this ever diverges, this needs two.")
    shared_parent = os.path.dirname(STORE)
    shared_parent_created = not os.path.isdir(shared_parent)
    os.makedirs(shared_parent, exist_ok=True)
    if shared_parent_created:
        os.chmod(shared_parent, 0o755)
        os.chown(shared_parent, 0, 0)
    # README step 2: the store and spool, the documented way.
    r = run(["python3", os.path.join(AGENT_DIR, "bin", "init-host-layout.py"),
             "--store-root", STORE, "--spool-root", SPOOL, "--apply"], env=root_env())
    if r.returncode != 0:
        raise RuntimeError("init-host-layout --apply failed:\n" + r.stdout + r.stderr)
    # The stand-in image.
    fixtures = os.path.join(HERE, "fixtures")
    run(["docker", "build", "-q", "-t", IMAGE, "-f",
         os.path.join(fixtures, "executor-standin.Dockerfile"), fixtures], check=True)
    # The Compose network. On the box the running stack created it; the proxy does not
    # allow network creation. Created here AFTER the layout exists, so Docker lays nothing
    # down as root, then the container is removed.
    r = run(["docker", "compose", "--env-file", "/dev/null", "-f",
             os.path.join(AGENT_DIR, "docker-compose.yml"), "--profile", "tools",
             "create", "ads-mutator"], env=root_env())
    if r.returncode != 0:
        raise RuntimeError("network setup failed:\n" + r.stdout + r.stderr)
    remove_mutator_containers()


def tearDownModule():
    for p in PROXIES:
        p.kill()
        p.wait()
    remove_mutator_containers()


def remove_mutator_containers():
    ids = run(["docker", "ps", "-aq", "--filter",
               "label=com.docker.compose.service=ads-mutator"]).stdout.split()
    if ids:
        run(["docker", "rm", "-f"] + ids)


def start_proxy(name, args):
    """The real proxy with ARGS (the unit's ExecStart arguments), --listen moved to a test
    socket whose group is hermes-rail, as the unit's Group=hermes-rail makes it on the box."""
    os.makedirs(SOCK_DIR, exist_ok=True)
    os.chmod(SOCK_DIR, 0o755)
    sock = os.path.join(SOCK_DIR, name + ".sock")
    log = os.path.join(SOCK_DIR, name + ".log")
    args = list(args)
    i = args.index("--listen")
    args[i + 1] = sock
    p = subprocess.Popen(["python3", os.path.join(AGENT_DIR, "bin", "docker-create-proxy.py")]
                         + args, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    PROXIES.append(p)
    for _ in range(200):
        if os.path.exists(sock):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("proxy %s never created its socket; log:\n%s" % (name, open(log).read()))
    os.chown(sock, 0, grp.getgrnam("hermes-rail").gr_gid)
    return sock, log


def unit_proxy():
    """ONE proxy with the unit's own flags, shared by every class (two would fight over one
    socket path and truncate one log)."""
    if not _UNIT_PROXY:
        _UNIT_PROXY.append(start_proxy("unit", BA.unit_exec_args(PROXY_UNIT)))
    return _UNIT_PROXY[0]


def broker_env(sock, **over):
    """hermes-broker.service's Environment=, DOCKER_HOST pointed at SOCK, HOME as systemd
    would set it for this user (from passwd; the directory does not exist)."""
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
           "HOME": pwd.getpwnam("hermes-broker").pw_dir}
    env.update(UNIT_ENV)
    env["DOCKER_HOST"] = "unix://" + sock
    env.update(over)
    return env


def log_after(log, offset):
    with open(log) as f:
        f.seek(offset)
        return f.read()


class BrokerPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sock, cls.log = unit_proxy()

    def wrapper(self, sock, log, **over):
        offset = os.path.getsize(log)
        r = run(BROKER + [os.path.join(AGENT_DIR, "run-ads-mutate.sh")] + CMD,
                env=broker_env(sock, **over))
        return r, r.stdout + r.stderr, log_after(log, offset)


class TestTheBrokerPath(BrokerPath):
    def test_precondition_the_kill_switch_is_absent(self):
        self.assertFalse(os.path.lexists(os.path.join(STORE, "control", "mutation-enabled")))

    def test_the_broker_path_reaches_the_executor_and_the_kill_switch_refuses(self):
        self.assertFalse(os.path.lexists(os.path.join(STORE, "control", "mutation-enabled")))
        r, out, plog = self.wrapper(self.sock, self.log)
        self.assertRegex(plog, CREATE_ALLOWED, "proxy log:\n%s\nwrapper:\n%s" % (plog, out))
        # F18, MEASURED: real attach traffic is answered 101 and streams through the fixed
        # path — the executor's "mutation is disabled" below only reaches us through it.
        self.assertRegex(plog, ATTACH_UPGRADED, "proxy log:\n%s\nwrapper:\n%s" % (plog, out))
        # F19: the claim is that no call of the REAL RAIL is refused by the TARGET check —
        # BRING-UP's "no DENY … target" on the box, measured here first. Pre-existing
        # allow-list refusals Compose tolerates (measured on CI 2026-09-24: `GET /info`,
        # `GET /networks/<name>`) are out of F19's scope and are never allow-listed to
        # silence them — a broad `^DENY` here would fail on those, unrelated to F19.
        self.assertNotRegex(plog, re.compile(r"^DENY .*\(target ", re.MULTILINE), "proxy log:\n%s\nwrapper:\n%s" % (plog, out))
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("mutation is disabled", out)
        # F14: the nonce crossed `docker compose run -e` and the real proxy, and the real
        # executor attested its own refusal — the 2 above is PROVEN, not inferred.
        self.assertEqual(len(ATTESTED_2.findall(out)), 1, out)
        self.assertNotIn("EXECUTOR EXIT NOT VERIFIED", out)

    def test_the_static_model_matches_real_compose(self):
        """bind_agreement's model (verbatim absolute sources, bare -> :rw) against what real
        Compose puts in HostConfig.Binds, and both against the proxy unit's pins."""
        remove_mutator_containers()
        r = run(["docker", "compose", "--env-file", "/dev/null", "-f",
                 os.path.join(AGENT_DIR, "docker-compose.yml"), "--profile", "tools",
                 "create", "ads-mutator"], env=root_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        cid = run(["docker", "ps", "-aq", "--filter",
                   "label=com.docker.compose.service=ads-mutator"]).stdout.split()[0]
        binds = run(["docker", "inspect", "--format", "{{json .HostConfig.Binds}}", cid],
                    check=True).stdout
        remove_mutator_containers()
        real = sorted(json.loads(binds))
        compose_text = open(os.path.join(AGENT_DIR, "docker-compose.yml"), encoding="utf-8").read()
        self.assertEqual(real, sorted(BA.compose_binds(compose_text, UNIT_ENV)))
        self.assertEqual(real, sorted(BA.allow_binds(PROXY_UNIT)))


class TestTheTargetCheck(BrokerPath):
    """F19 (spec 2026-09-24): through the real proxy and the real dockerd, a container that is
    NOT an ads-mutator run — the same image with a different entrypoint, exactly the gateway's
    situation on the box — can be neither inspected nor deleted by the broker. The decoy
    carries a sentinel in its environment in place of the gateway's API keys."""

    def test_a_non_mutator_container_cannot_be_inspected_or_deleted(self):
        name = "hermes-f19-decoy"
        run(["docker", "rm", "-f", name], env=root_env())
        r = run(["docker", "run", "-d", "--name", name, "--entrypoint", "sleep",
                 "-e", "F19_DECOY=F19-SENTINEL", IMAGE, "600"], env=root_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.addCleanup(run, ["docker", "rm", "-f", name], env=root_env())
        cid = r.stdout.strip()
        self.assertRegex(cid, r"^[0-9a-f]{64}$")
        offset = os.path.getsize(self.log)
        env = broker_env(self.sock)
        # Paths are unversioned on purpose: the CI runner's dockerd (28.0.4) caps at API 1.48,
        # and a pinned /v1.55 was answered 400 on version, which made the security assertions
        # pass vacuously (run 36019974966). The proxy's grammar makes the version prefix optional;
        # dockerd serves unversioned paths at its own max version.
        inspect = run(BROKER + ["python3", "-c", PROBE, self.sock, "GET",
                                "/containers/%s/json" % cid], env=env, timeout=60)
        delete = run(BROKER + ["python3", "-c", PROBE, self.sock, "DELETE",
                               "/containers/%s?force=1" % cid], env=env, timeout=60)
        plog = log_after(self.log, offset)
        # The security properties FIRST: the decoy's environment never reached the broker, and
        # the decoy is still running.
        self.assertNotIn("F19-SENTINEL", inspect.stdout,
                         "the broker read a non-mutator container's environment")
        running = run(["docker", "inspect", "-f", "{{.State.Running}}", cid], env=root_env())
        self.assertEqual(running.stdout.strip(), "true", "the broker deleted a non-mutator container")
        self.assertTrue(inspect.stdout.startswith("HTTP/1.1 403"), inspect.stdout[:200])
        self.assertTrue(delete.stdout.startswith("HTTP/1.1 403"), delete.stdout[:200])
        self.assertEqual(len(TARGET_REFUSED.findall(plog)), 2, plog)


class TestFiringControls(BrokerPath):
    def test_one_altered_allow_bind_is_refused(self):
        args = BA.unit_exec_args(PROXY_UNIT)
        altered = [BIN_PIN.replace("/bin:", "/bin-elsewhere:") if a == BIN_PIN else a
                   for a in args]
        self.assertNotEqual(altered, args, "the control did not alter the bin pin")
        sock, log = start_proxy("altered", altered)
        r, out, plog = self.wrapper(sock, log)
        self.assertRegex(plog, CREATE_DENIED, plog)
        self.assertIn("bind set does not match", plog)
        # F14, MEASURED: the proxy refused the create, so Compose exited 1 on its own and
        # no executor ever ran to attest anything. The wrapper must say "unverified" (4),
        # never "nothing was mutated" (1) and never the executor's own refusal (2).
        self.assertEqual(r.returncode, 4, out)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", out)

    def test_one_wrong_path_in_the_broker_environment_is_refused(self):
        r, out, plog = self.wrapper(self.sock, self.log,
                                    HERMES_ADS_REPO_DIR="/opt/projects/elsewhere")
        self.assertRegex(plog, CREATE_DENIED, plog)
        self.assertIn("bind set does not match", plog)
        self.assertEqual(r.returncode, 4, out)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", out)

    def test_without_env_file_compose_cannot_read_env(self):
        """Spike M4, kept as a control: the defect --env-file /dev/null exists to avoid."""
        offset = os.path.getsize(self.log)
        r = run(BROKER + ["docker", "compose", "-f", os.path.join(AGENT_DIR, "docker-compose.yml"),
                          "run", "--rm", "--no-deps", "-T", "ads-mutator"] + CMD,
                env=broker_env(self.sock))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("permission denied", (r.stdout + r.stderr).lower())
        self.assertNotRegex(log_after(self.log, offset), CREATE_ALLOWED)


if __name__ == "__main__":
    why = why_not_runnable()
    if why:
        print("bind-agreement: SKIPPED — %s" % why)
        sys.exit(1 if REQUIRED else 0)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = res.testsRun - len(res.skipped)
    print("bind-agreement: executed %d, skipped %d, failures %d, errors %d"
          % (executed, len(res.skipped), len(res.failures), len(res.errors)))
    if not res.wasSuccessful():
        sys.exit(1)
    if REQUIRED and (res.skipped or executed == 0):
        print("bind-agreement: HERMES_REQUIRE_LINUX_INTEGRATION=1 and not every test "
              "executed — failing", file=sys.stderr)
        sys.exit(1)
