import importlib.util, os, re, shlex, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
COMPOSE = os.path.join(os.path.dirname(HERE), "docker-compose.yml")
BROKER = os.path.join(HERE, "hermes-broker.py")
DEPLOY = os.path.join(os.path.dirname(HERE), "deploy")
PROXY_UNIT = os.path.join(DEPLOY, "hermes-docker-proxy.service")
BROKER_UNIT = os.path.join(DEPLOY, "hermes-broker.service")
BRING_UP = os.path.join(DEPLOY, "BRING-UP.md")
WRAPPER = os.path.join(os.path.dirname(HERE), "run-ads-mutate.sh")
import bind_agreement as BA


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PX = _load("docker_create_proxy", "docker-create-proxy.py")


def _ads_mutator_block():
    """The ads-mutator service block, textually. YAML is not stdlib and the proxy may
    not grow a dependency, so neither may its guard."""
    text = open(COMPOSE, encoding="utf-8").read()
    start = text.index("\n  ads-mutator:")
    rest = text[start + 1:]
    m = re.search(r"\n  [a-z0-9-]+:\n", rest)
    return rest[:m.start()] if m else rest


class TestProxyMatchesCompose(unittest.TestCase):
    """If these drift, the proxy refuses the real rail — on the VPS, at runtime.
    The same coupling install.sh/uninstall.sh carry, and S3-b's REMEDY/README."""

    def test_the_pinned_entrypoint_matches_compose(self):
        block = _ads_mutator_block()
        m = re.search(r"entrypoint:\s*(\[[^\]]*\])", block)
        self.assertIsNotNone(m, "no entrypoint found in the ads-mutator block")
        declared = [s.strip().strip('"\'') for s in m.group(1).strip("[]").split(",")]
        self.assertEqual(declared, PX.PINNED_ENTRYPOINT)

    def test_seen_is_not_mounted_into_the_executor(self):
        """iter_seen_records (changeset_lib.py) still fails OPEN on a missing file,
        safe ONLY because the governed party cannot reach seen/. Phase B is the wave
        most likely to touch mounts, so the assertion lives here."""
        self.assertNotIn("/seen:", _ads_mutator_block())


class TestComposeBindsEqualThePinnedSet(unittest.TestCase):
    """F9. The strings Compose will send for ads-mutator, computed from the BROKER unit's
    environment (the broker is what runs Compose), must equal the PROXY unit's --allow-bind
    set, AS STRINGS. The count-and-shape check this replaces passed while every path was
    wrong: that is how F9 shipped. The model is checked against real Compose by
    deploy/bind-agreement-integration.test.py on Linux CI."""

    def setUp(self):
        self.compose = open(COMPOSE, encoding="utf-8").read()
        self.env = BA.unit_environment(open(BROKER_UNIT, encoding="utf-8").read())
        self.pinned = BA.allow_binds(open(PROXY_UNIT, encoding="utf-8").read())

    def test_compose_binds_equal_the_pinned_set(self):
        got = BA.compose_binds(self.compose, self.env)
        self.assertEqual(len(got), len(set(got)), "a bind is declared twice: %s" % got)
        self.assertEqual(sorted(got), sorted(self.pinned))

    def test_exactly_one_bind_is_writable_and_it_is_log(self):
        rw = [b for b in BA.compose_binds(self.compose, self.env) if not b.endswith(":ro")]
        self.assertEqual(len(rw), 1, rw)
        self.assertIn(":/opt/governance/log:", rw[0])

    def test_firing_control_a_moved_checkout_is_a_mismatch(self):
        env = dict(self.env, HERMES_AGENT_DIR="/opt/elsewhere")
        self.assertNotEqual(sorted(BA.compose_binds(self.compose, env)), sorted(self.pinned))

    def test_firing_control_a_relative_source_is_refused(self):
        drifted, n = re.subn(r"- \$\{HERMES_AGENT_DIR:\?[^}]*\}/bin:", "- ./bin:",
                             self.compose, count=1)
        self.assertEqual(n, 1, "the control did not find the bin source to drift")
        with self.assertRaises(ValueError):
            BA.compose_binds(drifted, self.env)

    def test_firing_control_a_broker_without_the_variable_is_refused(self):
        env = {k: v for k, v in self.env.items() if k != "HERMES_ADS_REPO_DIR"}
        with self.assertRaises(BA.Unresolved):
            BA.compose_binds(self.compose, env)


class TestProxyMatchesBrokerArgv(unittest.TestCase):
    def test_the_allowed_cmd_flags_match_what_the_broker_builds(self):
        """hermes-broker.py builds the executor's argv. A flag it starts passing that
        the proxy does not allow breaks the rail; a flag the proxy allows that the
        broker never passes is attack surface."""
        text = open(BROKER, encoding="utf-8").read()
        m = re.search(r"argv = \[MUTATE_SH,([^\]]*)\]", text)
        self.assertIsNotNone(m, "could not find the broker's argv construction")
        flags = set(re.findall(r'"(--[a-z-]+)"', m.group(1)))
        self.assertEqual(flags, set(PX.ALLOWED_CMD_FLAGS),
                         "broker argv flags and proxy ALLOWED_CMD_FLAGS have drifted")

    def test_projects_and_registry_are_not_allowed(self):
        """--projects selects the file read for runner and script_dir, i.e. which
        program runs, and log/ is the one writable mount."""
        self.assertNotIn("--projects", PX.ALLOWED_CMD_FLAGS)
        self.assertNotIn("--registry", PX.ALLOWED_CMD_FLAGS)


def _join_continuations(text):
    """Shell line continuations (a trailing backslash) collapse to a single logical line,
    the way the shell itself reads them, so a regex over the text sees one command."""
    return re.sub(r"\\\n[ \t]*", " ", text)


def _extract_compose_invocation(text, label):
    """The `docker compose --env-file ... run ... ads-mutator` invocation, stripped of
    whatever precedes it (a `sudo -u hermes-broker env -i ...` prefix in the runbook, plain
    in the wrapper) and whatever follows it (the wrapper's redirection/`$@`, the runbook's
    `--client ...` argv)."""
    joined = _join_continuations(text)
    m = re.search(r"docker compose\b.*?ads-mutator\b", joined)
    if not m:
        raise AssertionError("no 'docker compose ... ads-mutator' invocation found in %s" % label)
    return m.group(0)


def _phase_6_block(bring_up_text):
    m = re.search(r"## Phase 6: Confirm the Bind Agreement\b", bring_up_text)
    if not m:
        raise AssertionError("'## Phase 6: Confirm the Bind Agreement' heading not found in BRING-UP.md")
    m2 = re.search(r"```bash\n(.*?)```", bring_up_text[m.end():], re.DOTALL)
    if not m2:
        raise AssertionError("no fenced ```bash block found under the Phase 6 heading")
    return m2.group(1)


def _compose_flags(invocation):
    """(tokens, --env-file value, -f value) for a `docker compose ...` invocation string."""
    tokens = shlex.split(invocation)
    m = re.search(r"--env-file\s+(\S+)", invocation)
    env_file = m.group(1) if m else None
    m = re.search(r"(?<!--env-file )-f\s+(\S+)", invocation)
    compose_file = m.group(1).strip("\"'") if m else None
    return tokens, env_file, compose_file


def _ordered_subsequence(tokens, seq):
    """True iff every item of SEQ appears in TOKENS, in that relative order (not necessarily
    contiguous — the wrapper interleaves `-e GOOGLE_ADS_*` flags the runbook does not have)."""
    it = iter(tokens)
    return all(tok in it for tok in seq)


class TestRunbookMatchesTheWrapper(unittest.TestCase):
    """BRING-UP.md Phase 6 hand-pastes a `docker compose ... run ... ads-mutator` invocation
    into a production shell rather than calling run-ads-mutate.sh directly, because the
    wrapper refuses at that point in bring-up: it requires `.env.gaw` (the WRITE Google Ads
    credential), which does not exist yet during Phase 6. So Phase 6 exercises the same
    Compose invocation directly, and THIS test is what keeps the two equal — if the wrapper's
    invocation ever changes, this fails instead of the runbook silently drifting.

    Scope: only the Compose-LEVEL flags are compared (--env-file, -f <...>/docker-compose.yml,
    and the ordered presence of `run --rm --no-deps -T ads-mutator`). The wrapper's
    `-e GOOGLE_ADS_*` flags and the runbook's explicit `env -i ... HERMES_*=...` assignments
    (standing in for the broker unit's real `Environment=`) are legitimate, documented
    differences, not drift, and are deliberately not compared."""

    def setUp(self):
        self.wrapper_inv = _extract_compose_invocation(
            open(WRAPPER, encoding="utf-8").read(), "run-ads-mutate.sh")
        self.runbook_inv = _extract_compose_invocation(
            _phase_6_block(open(BRING_UP, encoding="utf-8").read()), "BRING-UP.md Phase 6")

    def test_both_pass_env_file_dev_null(self):
        _, w_env, _ = _compose_flags(self.wrapper_inv)
        _, r_env, _ = _compose_flags(self.runbook_inv)
        self.assertEqual(w_env, "/dev/null")
        self.assertEqual(r_env, "/dev/null")

    def test_both_point_at_a_docker_compose_yml(self):
        _, _, w_file = _compose_flags(self.wrapper_inv)
        _, _, r_file = _compose_flags(self.runbook_inv)
        self.assertTrue(w_file and w_file.endswith("docker-compose.yml"), w_file)
        self.assertTrue(r_file and r_file.endswith("docker-compose.yml"), r_file)

    def test_both_run_rm_no_deps_dash_t_ads_mutator_in_order(self):
        seq = ["run", "--rm", "--no-deps", "-T", "ads-mutator"]
        w_tokens, _, _ = _compose_flags(self.wrapper_inv)
        r_tokens, _, _ = _compose_flags(self.runbook_inv)
        self.assertTrue(_ordered_subsequence(w_tokens, seq), w_tokens)
        self.assertTrue(_ordered_subsequence(r_tokens, seq), r_tokens)

    def test_firing_control_a_dropped_env_file_flag_is_caught(self):
        """A test that cannot be shown failing proves nothing: drift the runbook text in
        memory (drop --env-file /dev/null, the way an editor slipping while trimming the
        block would) and confirm the same assertion this class relies on now fails."""
        drifted = self.runbook_inv.replace("--env-file /dev/null ", "")
        _, d_env, _ = _compose_flags(drifted)
        self.assertIsNone(d_env, "the control did not actually remove --env-file")
        with self.assertRaises(AssertionError):
            self.assertEqual(d_env, "/dev/null")


if __name__ == "__main__":
    unittest.main()
