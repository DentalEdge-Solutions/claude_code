import importlib.util, os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
COMPOSE = os.path.join(os.path.dirname(HERE), "docker-compose.yml")
BROKER = os.path.join(HERE, "hermes-broker.py")


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

    def test_every_compose_volume_is_representable_as_an_allow_bind(self):
        """The proxy takes binds as flags, so this asserts SHAPE and count — the
        unit supplies the resolved paths, and Task 5's unit test pins those."""
        block = _ads_mutator_block()
        vols = re.findall(r"^\s+- (\S+:\S+)$", block, re.M)
        self.assertEqual(len(vols), 7,
                         "compose declares %d volumes; the proxy's unit supplies 7 "
                         "--allow-bind flags. Update both together." % len(vols))
        rw = [v for v in vols if not v.endswith(":ro")]
        self.assertEqual(len(rw), 1, "exactly one writable mount is expected: log/")
        self.assertIn("/log:", rw[0])

    def test_seen_is_not_mounted_into_the_executor(self):
        """iter_seen_records (changeset_lib.py) still fails OPEN on a missing file,
        safe ONLY because the governed party cannot reach seen/. Phase B is the wave
        most likely to touch mounts, so the assertion lives here."""
        self.assertNotIn("/seen:", _ads_mutator_block())


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


if __name__ == "__main__":
    unittest.main()
