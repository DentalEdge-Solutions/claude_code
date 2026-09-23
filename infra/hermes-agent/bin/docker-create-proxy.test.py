import importlib.util, itertools, json, os, socket, sys, time, unittest

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


def _await_accepting(path, timeout=5.0):
    """Wait until the listener ACCEPTS, not merely until its socket file exists.

    MEASURED 2026-09-18: `socketserver` binds — which creates the file — and only then
    calls listen(), so `os.path.exists(path)` is True during a window in which connect()
    raises ECONNREFUSED. Every socket test here waited on existence, so every one of them
    carried the race; CI lost it on main, on the Ruling 18 test, after a DOCS-ONLY merge
    that could not possibly have broken the code. Reproduced deliberately by stalling
    server_activate() between bind and listen: the existence check passes and the connect
    fails with exactly the CI error.

    Polling by connecting is the fix, because it tests the property the caller actually
    needs. The probe connection sends nothing, so it never reaches decide() and never
    causes an upstream connect.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.connect(path)
            probe.close()
            return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("proxy never began accepting on %s within %ss" % (path, timeout))


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


class TestParseHead(unittest.TestCase):
    """The framing hardening (spec 2026-09-23). `_parse_head` is the single place a request
    head is read. Anything it cannot parse unambiguously is refused, so the proxy and dockerd
    can never disagree about where a request ends. Every refusal test pins the REASON: a
    refusal for some unrelated reason must not satisfy it."""

    def assertRefused(self, head, reason):
        with self.assertRaises(PX.HeadRefused) as ctx:
            PX._parse_head(head)
        self.assertEqual(ctx.exception.reason, reason, head)
        return ctx.exception

    # ---- accepted ---------------------------------------------------------------------

    def test_real_client_heads_are_accepted(self):
        cases = [
            (b"GET /_ping HTTP/1.1\r\nHost: api.moby.localhost\r\n"
             b"User-Agent: Docker-Client/28.0.4 (linux)", ("GET", "/_ping", 0)),
            (b"POST /v1.55/containers/create?name=hermes-agent-ads-mutator-run-1 HTTP/1.1\r\n"
             b"Host: api.moby.localhost\r\nUser-Agent: compose/v2.38.2\r\n"
             b"Content-Type: application/json\r\nContent-Length: 812",
             ("POST", "/v1.55/containers/create?name=hermes-agent-ads-mutator-run-1", 812)),
            (b"POST /v1.55/containers/deadbeef/wait?condition=removed HTTP/1.1\r\n"
             b"Host: d\r\nContent-Length: 0",
             ("POST", "/v1.55/containers/deadbeef/wait?condition=removed", 0)),
            (b"POST /v1.55/containers/deadbeef/attach?stream=1&stdout=1 HTTP/1.1\r\n"
             b"Host: d\r\nConnection: Upgrade\r\nUpgrade: tcp",
             ("POST", "/v1.55/containers/deadbeef/attach?stream=1&stdout=1", 0)),
            (b"HEAD /_ping HTTP/1.1", ("HEAD", "/_ping", 0)),
        ]
        for head, want in cases:
            self.assertEqual(PX._parse_head(head), want, head)

    def test_a_colon_in_the_value_is_accepted(self):
        self.assertEqual(PX._parse_head(b"GET /_ping HTTP/1.1\r\nHost: localhost:2375"),
                         ("GET", "/_ping", 0))

    def test_an_empty_value_is_accepted(self):
        self.assertEqual(PX._parse_head(b"GET /_ping HTTP/1.1\r\nX-Empty:"),
                         ("GET", "/_ping", 0))

    def test_content_length_with_surrounding_whitespace_is_accepted(self):
        self.assertEqual(PX._parse_head(b"POST /v1.55/x HTTP/1.1\r\nContent-Length: \t5 "),
                         ("POST", "/v1.55/x", 5))

    def test_header_names_are_case_insensitive(self):
        self.assertEqual(PX._parse_head(b"POST /v1.55/x HTTP/1.1\r\ncontent-LENGTH: 7"),
                         ("POST", "/v1.55/x", 7))

    # ---- rule 4: line structure --------------------------------------------------------

    def test_a_bare_lf_inside_a_header_line_is_refused(self):
        """Form 4 (new, inferred): Go's textproto treats a bare LF as a line end, so dockerd
        would see a separate Transfer-Encoding line the old prefix check never saw."""
        self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nX-Pad: a\nTransfer-Encoding: chunked",
                           "malformed request")

    def test_a_bare_lf_pair_that_could_end_the_head_early_is_refused(self):
        self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nX-Pad: a\n\nPOST /v1.55/containers/create",
                           "malformed request")

    def test_a_bare_cr_is_refused(self):
        self.assertRefused(b"GET /_ping HTTP/1.1\r\nX-Pad: a\rb", "malformed request")

    def test_a_nul_is_refused(self):
        self.assertRefused(b"GET /_ping HTTP/1.1\r\nX-Pad: a\x00b", "malformed request")

    # ---- request line ------------------------------------------------------------------

    def test_malformed_request_lines_are_refused(self):
        for line in (b"GET /_ping",                      # 2 parts
                     b"GET /_ping HTTP/1.1 extra",       # 4 parts
                     b"GET  /_ping HTTP/1.1",            # double space
                     b"GET /_ping HTTP/1.0",             # not HTTP/1.1
                     b"GET /_p\x7fing HTTP/1.1",          # control char in target
                     b"G(T /_ping HTTP/1.1",             # method not a token
                     b""):                               # empty
            e = self.assertRefused(line + b"\r\nHost: d", "malformed request line")
            self.assertEqual((e.method, e.path), ("-", "-"), line)

    # ---- rules 1 and 2: header lines ---------------------------------------------------

    def test_obs_fold_is_refused(self):
        """Form 1 (measured 2026-09-17: the bytes reached the upstream)."""
        e = self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nX-Pad: pad\r\n\tTransfer-Encoding: chunked",
                               "malformed header line")
        self.assertEqual((e.method, e.path), ("POST", "/v1.55/x"))

    def test_a_leading_space_is_refused(self):
        self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\n Transfer-Encoding: chunked",
                           "malformed header line")

    def test_a_space_before_the_colon_is_refused(self):
        """Form 2 (measured 2026-09-17)."""
        self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nTransfer-Encoding : chunked",
                           "malformed header line")

    def test_other_malformed_header_lines_are_refused(self):
        for line in (b": no-name", b"No-Colon", b"X-Ctl: a\x01b", b"X-High: caf\xc3\xa9",
                     b"X-Del: a\x7fb"):
            self.assertRefused(b"GET /_ping HTTP/1.1\r\n" + line, "malformed header line")

    # ---- rule 3 and the framing headers ------------------------------------------------

    def test_duplicate_content_length_is_refused(self):
        """Form 3 (measured 2026-09-17: the old loop kept the LAST value)."""
        for pair in (b"Content-Length: 5\r\nContent-Length: 77",
                     b"Content-Length: 5\r\ncontent-length: 5"):
            self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\n" + pair, "duplicate Content-Length")

    def test_a_non_digit_content_length_is_refused(self):
        for v in (b"7_7", b"-5", b"+5", b"", b"5, 5", b"0x10"):
            self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nContent-Length: " + v,
                               "malformed Content-Length")

    def test_any_transfer_encoding_is_refused(self):
        for line in (b"Transfer-Encoding: chunked", b"transfer-encoding: gzip",
                     b"TRANSFER-ENCODING: identity"):
            self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\n" + line,
                               "Transfer-Encoding is not permitted on requests")

    def test_no_reason_ever_contains_request_bytes(self):
        """The reason goes to the client and the journal; attacker bytes must not."""
        marker = b"ZZ-MARKER-ZZ"
        for head in (b"GET /_ping HTTP/1.1\r\nX: " + marker + b"\x01",
                     b"GET /" + marker + b" HTTP/1.0",
                     b"POST /x HTTP/1.1\r\nContent-Length: " + marker):
            with self.assertRaises(PX.HeadRefused) as ctx:
                PX._parse_head(head)
            self.assertNotIn(marker.decode(), ctx.exception.reason)


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
        # The FULL bytes of each upstream receive, not just the first request line.
        # `upstream_saw` records `data.split(b"\r\n")[0]`, which cannot see a request
        # smuggled into the SAME sendall() as the allowed one it rides behind — and a
        # smuggled request is, by construction, always in that same sendall(). MEASURED:
        # against the pre-341ed1e proxy, `any("create" in line for line in upstream_saw)`
        # is False while the create is sitting in the received bytes verbatim, so the
        # non-receipt assertion — the one that actually proves the bypass is closed —
        # passed against the very code it was written to catch. Assert on these bytes.
        self.upstream_raw = []
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
                self.upstream_raw.append(data)
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
        _await_accepting(self.li_path)
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

    def test_a_create_with_a_chunked_body_is_refused(self):
        """A chunked body cannot be inspected before forwarding, and forwarding an
        uninspected create is the one thing this file exists to prevent.

        Since 341ed1e this is refused by the blanket Transfer-Encoding check, not by
        the `clen == 0` guard it was originally written against — the request carries
        `Transfer-Encoding: chunked`, so it never reaches that line. Renamed and
        reason-asserted to say so; the no-headers-at-all case the old name implied is
        covered distinctly by test_a_create_with_neither_header_is_refused below."""
        import threading, socket as _s, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        _await_accepting(self.li_path)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                  b"Transfer-Encoding: chunked\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
        self.assertIn(b"Transfer-Encoding is not permitted", resp,
                      "refused, but not by the Transfer-Encoding check this now exercises")

    def test_a_create_with_neither_header_is_refused(self):
        """Same refusal, but with NEITHER Content-Length NOR Transfer-Encoding present
        (clen defaults to 0). Code inspection says `clen == 0` already handles this,
        but it was untested — this covers the absent-headers case distinctly from the
        chunked case above.

        The REASON assertion is what makes this test discriminating. MEASURED: with
        `if is_create and clen == 0:` replaced by `if False:`, a 403-only assertion
        still passes, because decide() refuses the empty body anyway as `unparseable
        create body`. Defence in depth holds either way, but a 403-only test cannot
        tell the two layers apart and so proves nothing about the guard it names."""
        import threading, socket as _s, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        _await_accepting(self.li_path)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
        self.assertIn(b"cannot be inspected", resp,
                      "refused by decide() rather than by the clen == 0 guard")

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
        _await_accepting(self.li_path)
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

    def _start_proxy(self):
        import threading, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        _await_accepting(self.li_path)

    def test_a_cl_te_smuggled_create_is_refused_and_never_reaches_upstream(self):
        """THE CRITICAL: CL.TE request smuggling. `_handle` used to frame every
        request by Content-Length alone, but forward Transfer-Encoding verbatim
        to dockerd (a Go net/http server) for every allowed endpoint except
        /containers/create. dockerd frames by Transfer-Encoding when both
        headers are present, so an empty chunked body terminates the FIRST
        request for dockerd while the rest of the declared Content-Length body
        — an entirely uninspected second request — gets parsed and executed as
        its own call. Both assertions matter: the 403 alone does not prove the
        smuggled create was never sent to decide()/upstream — the upstream
        non-receipt assertion is what actually proves the bypass is closed."""
        import socket as _s
        self._start_proxy()
        smuggled = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                    b"Content-Length: 2\r\n\r\n{}")
        chunked_terminator = b"0\r\n\r\n"
        tail = chunked_terminator + smuggled
        req = (b"POST /v1.55/containers/deadbeef/wait?condition=removed HTTP/1.1\r\n"
               b"Host: d\r\nTransfer-Encoding: chunked\r\n"
               b"Content-Length: " + str(len(tail)).encode() + b"\r\n\r\n" + tail)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
        self.assertFalse(
            any(b"/containers/create" in b for b in self.upstream_raw),
            "smuggled create reached the upstream socket: %r" % self.upstream_raw)

    def test_a_cl_te_smuggled_create_behind_a_plain_get_is_refused(self):
        """Same hazard on a GET, to show the bug was never specific to POST
        bodies — any allowed endpoint carrying both headers was exploitable."""
        import socket as _s
        self._start_proxy()
        smuggled = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                    b"Content-Length: 2\r\n\r\n{}")
        chunked_terminator = b"0\r\n\r\n"
        tail = chunked_terminator + smuggled
        req = (b"GET /v1.55/version HTTP/1.1\r\nHost: d\r\n"
               b"Transfer-Encoding: chunked\r\n"
               b"Content-Length: " + str(len(tail)).encode() + b"\r\n\r\n" + tail)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
        self.assertFalse(
            any(b"/containers/create" in b for b in self.upstream_raw),
            "smuggled create reached the upstream socket: %r" % self.upstream_raw)

    def test_transfer_encoding_alone_on_an_allowed_endpoint_is_refused(self):
        """Transfer-Encoding with no Content-Length at all, on a non-create
        allowed path, must also be refused — the hazard is the header's mere
        presence on a request, not just the CL+TE combination."""
        import socket as _s
        self._start_proxy()
        req = (b"POST /v1.55/containers/deadbeef/wait?condition=removed HTTP/1.1\r\n"
               b"Host: d\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
        self.assertFalse(any(b"/containers/create" in b for b in self.upstream_raw))

    def test_an_ordinary_allowed_request_with_only_content_length_still_reaches_upstream(self):
        """POSITIVE CONTROL. Without this, a proxy that refuses every request
        carrying ANY body-framing header would also pass the three refusals
        above while silently breaking the production rail — this is the
        failure mode this project has already shipped once (Task 12's seam
        S4)."""
        import socket as _s
        self._start_proxy()
        req = (b"POST /v1.55/containers/deadbeef/wait?condition=removed HTTP/1.1\r\n"
               b"Host: d\r\nContent-Length: 0\r\n\r\n")
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        resp = c.recv(65536)
        c.close()
        self.assertNotIn(b"403", resp)
        self.assertTrue(
            any(line.startswith("POST /v1.55/containers/deadbeef/wait")
                for line in self.upstream_saw),
            "an ordinary allowed request never reached the upstream: %r" % self.upstream_saw)

    def _send(self, req):
        """Send one raw request, return what the client got back (b"" if the proxy
        closed without answering)."""
        import socket as _s
        self._start_proxy()
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        c.settimeout(2)
        try:
            resp = c.recv(65536)
        except OSError:
            resp = b""
        c.close()
        return resp

    def test_a_malformed_content_length_is_refused_not_crashed(self):
        """F4. `clen = int(...)` raised ValueError on a non-numeric Content-Length and
        _handle catches only OSError, so it escaped to socketserver as an unhandled
        traceback. It failed CLOSED — nothing was forwarded — but this file's own
        convention (see _relay_chunked) is that every path fails closed AND LOGGED
        rather than with a traceback, and any client on the proxy socket could fill
        the journal with them. A 403 is the observable difference: before, the client
        got nothing at all."""
        resp = self._send(b"POST /v1.55/containers/deadbeef/wait?condition=removed "
                          b"HTTP/1.1\r\nHost: d\r\nContent-Length: abc\r\n\r\n")
        self.assertIn(b"403", resp)
        self.assertIn(b"Content-Length", resp)
        self.assertFalse(any(b"/containers/create" in b for b in self.upstream_raw))

    def test_a_negative_content_length_is_refused(self):
        """MEASURED: Python's int() accepts "-5", and the framing below then does
        `body, buf = rest[:-5], rest[-5:]` — silently treating the last five bytes of
        the body as the start of the NEXT request. decide() sees a truncated body and
        the tail is re-parsed as a request line. Go rejects a negative Content-Length
        outright, so this is the proxy disagreeing with its own upstream about where a
        request ends, which is the exact shape of the Critical this file already closed."""
        resp = self._send(b"POST /v1.55/containers/deadbeef/wait?condition=removed "
                          b"HTTP/1.1\r\nHost: d\r\nContent-Length: -5\r\n\r\nXXXXX")
        self.assertIn(b"403", resp)

    def test_a_content_length_only_python_accepts_is_refused(self):
        """Python's int() accepts underscore separators, so `Content-Length: 7_7`
        parsed as 77 while Go's ParseUint rejects it — the proxy would frame 77 bytes
        as the body while dockerd 400s or frames differently. MEASURED during the
        341ed1e re-review: this form carried a smuggled create's bytes through to the
        upstream socket. Digits only, which is what RFC 9110 says a Content-Length
        is."""
        smuggled = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                    b"Content-Length: 2\r\n\r\n{}")
        tail = b"0\r\n\r\n" + smuggled
        resp = self._send(b"POST /v1.55/containers/deadbeef/wait?condition=removed "
                          b"HTTP/1.1\r\nHost: d\r\nContent-Length: 7_7\r\n\r\n" + tail)
        self.assertIn(b"403", resp)
        self.assertFalse(
            any(b"/containers/create" in b for b in self.upstream_raw),
            "a Content-Length only Python accepts carried a create to the upstream: %r"
            % self.upstream_raw)

    def test_a_request_after_a_chunked_response_cannot_smuggle_past_decide(self):
        """Same hazard class as the CL.TE fix above, on the RESPONSE side: real
        traffic (see docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md)
        has `GET /containers/json` return `Transfer-Encoding: chunked` and a
        `wait` follow on what the real Docker client treats as one logical
        session. This test found that `_handle` does NOT keep the proxy-side
        connection open after relaying a chunked response: the `return`
        immediately after `_relay_chunked(...)` in `_handle` unconditionally
        ends the per-connection loop, for both the well-formed case here and
        the malformed-chunk case already covered by
        test_a_malformed_chunk_size_line_closes_the_connection_cleanly above.
        A second request the client attempts on that same connection is
        therefore never decided — the connection is already gone, so the
        client's write fails outright (broken pipe) rather than the request
        being read, framed, or forwarded. This differs from the task brief's
        assumption that this path is exercised keep-alive-style in production;
        it is NOT a smuggling bypass (confirmed below: nothing from the
        never-sent second request reaches the fake upstream — there is no
        uninspected forwarding, only a closed connection), but it is a
        functional gap in connection reuse across a chunked response, left
        unchanged here as it is outside this wave's single assigned Critical
        (CL.TE request smuggling) and changing `_handle`'s control flow for it
        deserves its own review. See the final fix report's Concerns section."""
        import threading, socket as _s, time
        chunked_up_path = "/tmp/pxchunkup-%d-%d.sock" % (os.getpid(), next(_SOCK_SEQ))
        if os.path.exists(chunked_up_path):
            os.remove(chunked_up_path)
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(chunked_up_path)
        srv.listen(1)
        upstream_saw = []

        def chunked_upstream():
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                        b"5\r\nhello\r\n0\r\n\r\n")
            # If _handle ever loops back for a second request, it would open a
            # fresh forward to this same accepted upstream connection; record
            # whatever (if anything) arrives so the assertion below can prove
            # a never-decided request did not slip through as a second send.
            try:
                more = conn.recv(65536)
                if more:
                    upstream_saw.append(more.split(b"\r\n")[0].decode("latin1"))
            except OSError:
                pass
            conn.close()

        threading.Thread(target=chunked_upstream, daemon=True).start()
        self.addCleanup(srv.close)
        self.addCleanup(lambda: os.path.exists(chunked_up_path) and os.remove(chunked_up_path))

        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=chunked_up_path),
                         daemon=True).start()
        _await_accepting(self.li_path)

        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"GET /v1.55/containers/json HTTP/1.1\r\nHost: d\r\n\r\n")
        c.settimeout(2)
        first = b""
        while not first.endswith(b"0\r\n\r\n"):
            chunk = c.recv(65536)
            if not chunk:
                break
            first += chunk
        self.assertIn(b"chunked", first.lower())
        self.assertTrue(first.endswith(b"0\r\n\r\n"), "did not receive the full chunked body")

        with self.assertRaises(OSError):
            for _ in range(50):
                c.sendall(b"POST /v1.55/containers/deadbeef/wait?condition=removed "
                         b"HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n")
                time.sleep(0.02)
        c.close()
        self.assertFalse(
            any("wait" in line for line in upstream_saw),
            "a request the proxy never decided still reached the upstream: %r"
            % upstream_saw)


if __name__ == "__main__":
    unittest.main()
