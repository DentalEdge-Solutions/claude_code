import importlib.util, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PX = _load("docker_create_proxy", "docker-create-proxy.py")

GOV = "/var/lib/hermes/governance"
PROJ = "/opt/hermes-agent"
BINDS = [
    ("%s/approvals" % GOV, "/opt/governance/approvals", "ro"),
    ("%s/control" % GOV, "/opt/governance/control", "ro"),
    ("%s/registry" % GOV, "/opt/governance/registry", "ro"),
    ("%s/log" % GOV, "/opt/governance/log", "rw"),
    ("/opt/projects/claude-google-ads", "/projects/claude_google_ads", "ro"),
    ("%s/registry" % PROJ, "/opt/registry", "ro"),
    ("%s/bin" % PROJ, "/opt/cc-bin", "ro"),
]


def _binds_payload(overrides=None):
    out = []
    for src, dst, mode in BINDS:
        out.append("%s:%s:%s" % (src, dst, mode))
    return overrides if overrides is not None else out


def _create_body(**over):
    body = {
        "Image": "hermes-agent-claude",
        "Entrypoint": ["python3", "/opt/cc-bin/apply-changeset.py"],
        "Cmd": ["--client", "acme-dental",
                "--changeset", "20260101-000000-deadbeef",
                "--request", "00000000-0000-0000-0000-000000000000"],
        "Env": ["HERMES_GOVERNANCE_ROOT=/opt/governance",
                "GOOGLE_ADS_DEVELOPER_TOKEN=x"],
        "HostConfig": {"Binds": _binds_payload()},
    }
    body.update(over)
    return json.dumps(body).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance")

    def allow(self, body=None, path="/v1.55/containers/create", method="POST"):
        return PX.decide(method, path, body if body is not None else _create_body())


class TestPositiveControls(Base):
    """Without these, every refusal below would also pass against a proxy that
    refuses everything — which breaks the rail and is the failure mode this
    project has already shipped once (Task 12's seam S4)."""

    def test_the_real_create_is_allowed(self):
        ok, why = self.allow()
        self.assertTrue(ok, why)

    def test_each_allowed_endpoint_is_allowed(self):
        for method, path in (
            ("HEAD", "/_ping"),
            ("GET", "/v1.55/version"),
            ("GET", "/v1.55/images/hermes-agent-claude/json"),
            ("POST", "/v1.55/containers/abc123/start"),
            ("POST", "/v1.55/containers/abc123/attach"),
            ("POST", "/v1.55/containers/abc123/wait"),
            ("GET", "/v1.55/containers/abc123/json"),
            ("GET", "/v1.55/containers/json"),
            ("DELETE", "/v1.55/containers/abc123"),
        ):
            ok, why = PX.decide(method, path, b"")
            self.assertTrue(ok, "%s %s refused: %s" % (method, path, why))


class TestEndpointAllowList(Base):
    def test_an_unlisted_endpoint_is_refused(self):
        ok, why = PX.decide("POST", "/v1.55/build", b"")
        self.assertFalse(ok)
        self.assertIn("allow-list", why)

    def test_exec_create_is_refused(self):
        """docker exec into the running executor would be arbitrary code with the
        rail's own mounts."""
        ok, _ = PX.decide("POST", "/v1.55/containers/abc123/exec", b"")
        self.assertFalse(ok)

    def test_a_traversal_path_is_refused(self):
        ok, why = PX.decide("POST", "/v1.55/containers/create/../../build", b"")
        self.assertFalse(ok)
        self.assertIn("traversal", why)


class TestImageAndEntrypoint(Base):
    def test_a_different_image_is_refused(self):
        ok, why = self.allow(_create_body(Image="alpine"))
        self.assertFalse(ok)
        self.assertIn("image", why)

    def test_an_overridden_entrypoint_is_refused(self):
        """THE gap this task exists to close. A pinned image whose entrypoint is
        free is arbitrary code execution in that image."""
        ok, why = self.allow(_create_body(Entrypoint=["/bin/sh", "-c", "id"]))
        self.assertFalse(ok)
        self.assertIn("entrypoint", why.lower())

    def test_a_missing_entrypoint_is_refused(self):
        body = json.loads(_create_body())
        del body["Entrypoint"]
        ok, _ = self.allow(json.dumps(body).encode())
        self.assertFalse(ok)

    def test_a_user_override_is_refused(self):
        ok, why = self.allow(_create_body(User="0"))
        self.assertFalse(ok)
        self.assertIn("user", why.lower())


class TestCmdFlags(Base):
    def test_projects_flag_is_refused(self):
        """--projects selects the file read for runner and script_dir
        (changeset_lib.read_mutate_execute), i.e. WHICH PROGRAM RUNS. log/ is the
        one writable mount, so an attacker writes a YAML there and points at it."""
        ok, why = self.allow(_create_body(
            Cmd=["--client", "acme-dental", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000",
                 "--projects", "/opt/governance/log/evil.yaml"]))
        self.assertFalse(ok)
        self.assertIn("--projects", why)

    def test_registry_flag_is_refused(self):
        ok, why = self.allow(_create_body(
            Cmd=["--client", "acme-dental", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000",
                 "--registry", "/opt/governance/log/evil.json"]))
        self.assertFalse(ok)
        self.assertIn("--registry", why)

    def test_a_malformed_slug_is_refused(self):
        ok, _ = self.allow(_create_body(
            Cmd=["--client", "../etc", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000"]))
        self.assertFalse(ok)


class TestBinds(Base):
    def test_an_extra_bind_is_refused(self):
        ok, why = self.allow(_create_body(HostConfig={"Binds": _binds_payload(
            _binds_payload() + ["/etc/shadow:/x:ro"])}))
        self.assertFalse(ok)
        self.assertIn("bind", why.lower())

    def test_etc_shadow_alone_is_refused(self):
        """The old denylist matched '/etc' exactly, so '/etc/shadow' passed."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": ["/etc/shadow:/x:ro"]}))
        self.assertFalse(ok)

    def test_the_governance_store_mounted_rw_is_refused(self):
        """The worst case: it hands the governed party the approvals directory and
        the kill switch."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": [
            "%s:/opt/governance:rw" % GOV]}))
        self.assertFalse(ok)

    def test_a_permitted_source_with_rw_instead_of_ro_is_refused(self):
        """The flag is part of the match, not decoration. A read-only mount turned
        writable is the whole attack."""
        bad = ["%s:%s:rw" % (s, d) if m == "ro" else "%s:%s:%s" % (s, d, m)
               for s, d, m in BINDS]
        ok, why = self.allow(_create_body(HostConfig={"Binds": bad}))
        self.assertFalse(ok)
        self.assertIn("bind", why.lower())

    def test_the_docker_socket_is_refused(self):
        ok, _ = self.allow(_create_body(HostConfig={"Binds": [
            "/var/run/docker.sock:/var/run/docker.sock:rw"]}))
        self.assertFalse(ok)

    def test_a_missing_bind_is_refused(self):
        """Exact set: fewer is as wrong as more, because a missing :ro mount could
        be re-supplied by a symlink inside a writable one."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": _binds_payload()[:-1]}))
        self.assertFalse(ok)


class TestHostConfigAndEnv(Base):
    def test_privileged_is_refused(self):
        hc = {"Binds": _binds_payload(), "Privileged": True}
        ok, why = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)
        self.assertIn("Privileged", why)

    def test_mounts_api_is_refused(self):
        """Mounts is the newer API for the same capability — left open it bypasses
        the Binds allow-list entirely."""
        hc = {"Binds": _binds_payload(),
              "Mounts": [{"Type": "bind", "Source": "/etc", "Target": "/x"}]}
        ok, _ = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)

    def test_host_network_is_refused(self):
        hc = {"Binds": _binds_payload(), "NetworkMode": "host"}
        ok, _ = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)

    def test_a_redirected_governance_root_is_refused(self):
        """Left free, an attacker repoints the root at a fake store built inside
        the one writable mount."""
        ok, why = self.allow(_create_body(
            Env=["HERMES_GOVERNANCE_ROOT=/opt/governance/log/fake"]))
        self.assertFalse(ok)
        self.assertIn("HERMES_GOVERNANCE_ROOT", why)

    def test_the_credential_vars_stay_free(self):
        """POSITIVE CONTROL. They carry the credential and vary per run; a check
        that pinned them would refuse every real call."""
        ok, why = self.allow(_create_body(
            Env=["HERMES_GOVERNANCE_ROOT=/opt/governance",
                 "GOOGLE_ADS_REFRESH_TOKEN=whatever", "GOOGLE_ADS_CUSTOMER_ID=1234567890"]))
        self.assertTrue(ok, why)


class TestBodyHandling(Base):
    def test_an_unparseable_body_is_refused(self):
        ok, why = self.allow(b"{not json")
        self.assertFalse(ok)
        self.assertIn("unparseable", why)

    def test_a_non_object_body_is_refused(self):
        ok, _ = self.allow(b"[]")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
