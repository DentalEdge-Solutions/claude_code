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
store and the spool, and REFUSES to run if any of them already exists.

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
    run(["chmod", "-R", "a+rX", "/opt/projects"], check=True)
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
    # makedirs is subject to umask, so chmod/chown explicitly afterwards.
    assert os.path.dirname(STORE) == os.path.dirname(SPOOL), (
        "STORE and SPOOL no longer share a parent — the BRING-UP Phase 2 install -d step "
        "creates one directory for both; if this ever diverges, this needs two.")
    shared_parent = os.path.dirname(STORE)
    os.makedirs(shared_parent, exist_ok=True)
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
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("mutation is disabled", out)

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
        self.assertNotEqual(r.returncode, 2, "a refused create must not look like the "
                                             "executor's own exit-2 refusal:\n" + out)

    def test_one_wrong_path_in_the_broker_environment_is_refused(self):
        r, out, plog = self.wrapper(self.sock, self.log,
                                    HERMES_ADS_REPO_DIR="/opt/projects/elsewhere")
        self.assertRegex(plog, CREATE_DENIED, plog)
        self.assertIn("bind set does not match", plog)
        self.assertNotEqual(r.returncode, 2, out)

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
