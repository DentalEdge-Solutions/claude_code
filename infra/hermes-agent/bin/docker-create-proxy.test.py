import importlib.util, itertools, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Monotonic, so every TestPlumbing test gets its OWN socket paths rather than sharing
# one pid-based pair across the whole process. MEASURED (fix round 1, Finding review):
# with a shared pid-based path, a PREVIOUS test's still-running `serve_forever()`
# daemon thread occasionally intercepts a LATER test's connection after the path is
# unlinked and rebound — reproduced directly by looping just the two original
# brief-verbatim TestPlumbing tests (~1/20 failures), and it surfaces at roughly 1/3 in
# a single ordinary run once a third and fourth socket-based test are added. Unique
# paths per test remove the shared resource the race depends on.
_SOCK_SEQ = itertools.count()


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
        "HostConfig": {"Binds": _binds_payload(), "NetworkMode": "hermes-agent_default"},
    }
    body.update(over)
    return json.dumps(body).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance", network="hermes-agent_default")

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

    def test_network_mode_container_join_is_refused(self):
        """The gap the old denylist left open: startswith("host") never catches
        NetworkMode="container:<id>", which joins another container's network
        namespace. NetworkMode is now an allow-list, not a denylist."""
        hc = {"Binds": _binds_payload(), "NetworkMode": "container:abc123"}
        ok, why = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)
        self.assertIn("NetworkMode", why)

    def test_network_mode_host_is_refused_by_the_allow_list(self):
        """Same outcome as test_host_network_is_refused, but proves it now holds
        because "host" fails the allow-list match, not because of a startswith
        denylist that no longer exists for NetworkMode."""
        hc = {"Binds": _binds_payload(), "NetworkMode": "host"}
        ok, why = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)
        self.assertIn("NetworkMode", why)

    def test_the_pinned_network_is_allowed(self):
        """POSITIVE CONTROL. Without this, a proxy that refuses every NetworkMode
        would also pass every refusal test above."""
        hc = {"Binds": _binds_payload(), "NetworkMode": "hermes-agent_default"}
        ok, why = self.allow(_create_body(HostConfig=hc))
        self.assertTrue(ok, why)

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


class TestPlumbing(unittest.TestCase):
    """The socket half. These use a fake upstream so no Docker daemon is needed."""

    def setUp(self):
        import tempfile, threading, socket as _s
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance", network="hermes-agent_default")
        # AF_UNIX paths cap near 104 bytes — /tmp, never a long temp path. Unique per
        # TEST, not just per process — see _SOCK_SEQ's comment above for why.
        n = next(_SOCK_SEQ)
        self.up_path = "/tmp/pxup-%d-%d.sock" % (os.getpid(), n)
        self.li_path = "/tmp/pxli-%d-%d.sock" % (os.getpid(), n)
        for p in (self.up_path, self.li_path):
            if os.path.exists(p):
                os.remove(p)
        self.upstream_saw = []
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(self.up_path)
        srv.listen(8)

        def fake_upstream():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                data = conn.recv(65536)
                self.upstream_saw.append(data.split(b"\r\n")[0].decode("latin1"))
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                conn.close()

        threading.Thread(target=fake_upstream, daemon=True).start()
        self.addCleanup(srv.close)
        for p in (self.up_path, self.li_path):
            self.addCleanup(lambda q=p: os.path.exists(q) and os.remove(q))

    def test_a_second_request_on_the_same_connection_is_also_inspected(self):
        """THE keep-alive bypass. A proxy that inspects the first request and then
        splices lets an attacker send a benign HEAD /_ping and then anything at all
        on the same connection. Measured while planning this: a first-request-only
        pass-through saw 3 of 14 real calls and looked like it had worked."""
        import threading, socket as _s
        t = threading.Thread(target=PX.serve,
                             kwargs=dict(listen=self.li_path, upstream=self.up_path),
                             daemon=True)
        t.start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            import time; time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"HEAD /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
        c.recv(65536)
        c.sendall(b"POST /v1.55/build HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp,
                      "second request on the connection was not inspected")
        self.assertNotIn("POST /v1.55/build HTTP/1.1", self.upstream_saw,
                         "a refused request reached the upstream socket")

    def test_a_create_with_no_content_length_is_refused(self):
        """A chunked body cannot be inspected before forwarding, and forwarding an
        uninspected create is the one thing this file exists to prevent."""
        import threading, socket as _s, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                  b"Transfer-Encoding: chunked\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)

    def test_a_create_with_neither_header_is_refused(self):
        """Same refusal, but with NEITHER Content-Length NOR Transfer-Encoding present
        (clen defaults to 0). Code inspection says `clen == 0` already handles this,
        but it was untested — this covers the absent-headers case distinctly from the
        chunked case above."""
        import threading, socket as _s, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)

    def test_a_malformed_chunk_size_line_closes_the_connection_cleanly(self):
        """Finding 2, fix round 1: a malformed (non-hex) chunk-size line from the
        upstream must not produce an unhandled traceback. Every other failure path in
        this file closes the connection and logs; this one now does too. Uses its own
        upstream fixture (not the shared fake_upstream from setUp) because it needs to
        answer with a specific malformed chunked response, not the fixed one."""
        import threading, socket as _s, time
        bad_up_path = "/tmp/pxbadup-%d-%d.sock" % (os.getpid(), next(_SOCK_SEQ))
        if os.path.exists(bad_up_path):
            os.remove(bad_up_path)
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(bad_up_path)
        srv.listen(1)

        def bad_upstream():
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                         b"NOTHEX\r\n")
            conn.close()

        threading.Thread(target=bad_upstream, daemon=True).start()
        self.addCleanup(srv.close)
        self.addCleanup(lambda: os.path.exists(bad_up_path) and os.remove(bad_up_path))

        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=bad_up_path),
                         daemon=True).start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"GET /v1.55/version HTTP/1.1\r\nHost: d\r\n\r\n")
        resp = c.recv(65536)
        self.assertIn(b"200 OK", resp)
        # The proxy must close cleanly (a plain EOF) after the malformed chunk-size
        # line, not hang and not crash with an unhandled traceback.
        more = c.recv(65536)
        self.assertEqual(more, b"", "connection did not close cleanly")
        c.close()


if __name__ == "__main__":
    unittest.main()
