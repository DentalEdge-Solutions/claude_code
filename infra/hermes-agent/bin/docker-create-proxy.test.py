import importlib.util, itertools, json, os, re, socket, sys, time, unittest

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


def _poll_never_received(tc, raw, marker=b"/containers/create", settle=0.5):
    """Non-receipt, race-free: fake upstreams append on their own threads, so poll `raw` for
    `settle` seconds and fail the moment `marker` appears. Absence for the whole window is
    the pass."""
    deadline = time.monotonic() + settle
    while True:
        if any(marker in b for b in raw):
            tc.fail("smuggled create reached the upstream socket: %r" % raw)
        if time.monotonic() >= deadline:
            return
        time.sleep(0.01)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PX = _load("docker_create_proxy", "docker-create-proxy.py")

# F19: container ids are FULL 64-hex ids — the only form the real rail sends (box journal,
# 2026-09-24). MUT_ID is an ads-mutator run; GW_ID stands for the Hermes gateway.
MUT_ID = "deadbeef" * 8
GW_ID = "0badc0de" * 8

SENTINEL = "F19-SENTINEL"
# Synthetic inspect documents — never captured from a real gateway. The gateway's shares the
# mutator's image: only the entrypoint tells them apart (docker-compose.yml).
MUTATOR_DOC = {"Id": MUT_ID, "Config": {
    "Image": "hermes-agent-claude",
    "Entrypoint": ["python3", "/opt/cc-bin/apply-changeset.py"],
    "Env": ["HERMES_GOVERNANCE_ROOT=/opt/governance"]}}
GATEWAY_DOC = {"Id": GW_ID, "Config": {
    "Image": "hermes-agent-claude",
    "Entrypoint": ["/opt/hermes/docker/entrypoint.sh"],
    "Cmd": ["gateway", "run"],
    "Env": ["SECRET=" + SENTINEL]}}


def _mut(**config_over):
    """MUTATOR_DOC with Config fields overridden (a deep copy)."""
    doc = json.loads(json.dumps(MUTATOR_DOC))
    doc["Config"].update(config_over)
    return doc


HANG = object()   # a fake upstream reply that never comes


def _json_200(doc):
    body = json.dumps(doc).encode()
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\n\r\n" + body)


def _chunked_200(doc):
    body = json.dumps(doc).encode()
    half = len(body) // 2
    chunks = b"".join(b"%x\r\n%s\r\n" % (len(part), part) for part in (body[:half], body[half:]))
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n" + chunks + b"0\r\n\r\n")


def _one_shot_upstream(tc, reply):
    """A unix-socket server that accepts ONE connection, records the request head in `got`,
    and sends `reply` (bytes) then closes — or, for HANG, holds the connection open and never
    answers. Returns (path, got)."""
    import threading
    path = "/tmp/pxlk-%d-%d.sock" % (os.getpid(), next(_SOCK_SEQ))
    if os.path.exists(path):
        os.remove(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    got, held = [], []

    def run():
        try:
            c, _ = srv.accept()
        except OSError:
            return
        data = b""
        while b"\r\n\r\n" not in data:
            d = c.recv(65536)
            if not d:
                break
            data += d
        got.append(data)
        if reply is HANG:
            held.append(c)
            return
        try:
            c.sendall(reply)
        except OSError:
            pass
        c.close()

    threading.Thread(target=run, daemon=True).start()
    tc.addCleanup(srv.close)
    tc.addCleanup(lambda: [c.close() for c in held])
    tc.addCleanup(lambda: os.path.exists(path) and os.remove(path))
    return path, got


_INSPECT_HEAD = re.compile(rb"GET (?:/v[0-9]+\.[0-9]+)?/containers/([0-9a-f]{64})/json[ ?]")


def _lookup_reply(head, table):
    """The fake upstream's answer to an inspect `GET [/vX.Y]/containers/<id>/json` — the
    proxy's own lookup or a forwarded client inspect — from `table` (id -> doc dict, raw
    reply bytes, or HANG). An id not in the table gets a 404. None for any other request."""
    m = _INSPECT_HEAD.match(head)
    if not m:
        return None
    entry = table.get(m.group(1).decode(), b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\n{}")
    if isinstance(entry, dict):
        return _json_200(entry)
    return entry


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
            ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/start"),
            ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach"),
            ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait"),
            ("GET", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/json"),
            ("GET", "/v1.55/containers/json"),
            ("DELETE", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
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
        ok, _ = PX.decide("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/exec", b"")
        self.assertFalse(ok)

    def test_a_traversal_path_is_refused(self):
        ok, why = PX.decide("POST", "/v1.55/containers/create/../../build", b"")
        self.assertFalse(ok)
        self.assertIn("traversal", why)

    def test_container_scoped_entries_refuse_anything_but_a_full_id(self):
        """F19: names and short prefixes can come to mean a different container between the
        target check and the forward. Only the full 64-hex id is accepted."""
        bad_ids = ("hermes-agent-ads-mutator-run-1a2b", "deadbeefdead", ("DEADBEEF" * 8),
                   "deadbeef" * 8 + "d", ("deadbeef" * 8)[:63], "json2")
        for bad in bad_ids:
            for method, tail in (("GET", "/json"), ("POST", "/start"), ("POST", "/wait"),
                                 ("POST", "/attach"), ("DELETE", "")):
                path = "/v1.55/containers/%s%s" % (bad, tail)
                ok, why = PX.decide(method, path, b"")
                self.assertFalse(ok, "%s %s was allowed" % (method, path))
                self.assertIn("allow-list", why)

    def test_a_trailing_slash_after_the_id_is_refused(self):
        ok, _ = PX.decide("DELETE", "/v1.55/containers/%s/" % MUT_ID, b"")
        self.assertFalse(ok)

    def test_the_list_and_image_inspect_are_unchanged(self):
        for method, path in (("GET", "/v1.55/containers/json"),
                             ("GET", "/v1.55/containers/json?all=1&filters=x"),
                             ("GET", "/v1.55/images/hermes-agent-claude/json")):
            ok, why = PX.decide(method, path, b"")
            self.assertTrue(ok, "%s %s refused: %s" % (method, path, why))


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
            (b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed HTTP/1.1\r\n"
             b"Host: d\r\nContent-Length: 0",
             ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed", 0)),
            (b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach?stream=1&stdout=1 HTTP/1.1\r\n"
             b"Host: d\r\nConnection: Upgrade\r\nUpgrade: tcp",
             ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach?stream=1&stdout=1", 0)),
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
        for v in (b"7_7", b"-5", b"+5", b"", b"5, 5", b"0x10", b"1" * 20, b"1" * 5000):
            self.assertRefused(b"POST /v1.55/x HTTP/1.1\r\nContent-Length: " + v,
                               "malformed Content-Length")

    def test_a_19_digit_content_length_parses(self):
        self.assertEqual(
            PX._parse_head(b"POST /v1.55/x HTTP/1.1\r\nContent-Length: " + b"9" * 19),
            ("POST", "/v1.55/x", int("9" * 19)))

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


class TestAttachHelpers(unittest.TestCase):
    """F18 (spec 2026-09-23). Attach is defined ONCE — the allow-list entry and the
    pass-through decision use the same pattern — and the upstream status is read strictly,
    so a garbled status line can never be mistaken for 101."""

    def test_a_real_attach_is_an_attach(self):
        self.assertTrue(PX._is_attach(
            "POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach?stream=1&stdout=1&stderr=1"))
        self.assertTrue(PX._is_attach("POST", "/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach"))

    def test_look_alikes_are_not_attaches(self):
        for method, path in (("GET", "/_ping?x=/attach"),
                             ("DELETE", "/v1.55/containers/attach"),
                             ("GET", "/v1.55/containers/attach/json"),
                             ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attachx"),
                             ("POST", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach/../../create"),
                             ("GET", "/v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/attach")):
            self.assertFalse(PX._is_attach(method, path), (method, path))

    def test_an_attach_needs_a_full_id(self):
        self.assertFalse(PX._is_attach("POST", "/v1.55/containers/abc/attach?stream=1"))
        self.assertTrue(PX._is_attach("POST", "/v1.55/containers/%s/attach?stream=1" % MUT_ID))

    def test_the_allow_list_uses_the_same_attach_pattern(self):
        # IDENTITY, not equality: re.Pattern compares equal to a separately compiled copy of
        # the same pattern, so `in` would pass even if the two definitions drifted apart.
        self.assertTrue(any(m == "POST" and pat is PX._ATTACH_RE for m, pat in PX.ALLOWED))

    def test_status_codes_are_read_strictly(self):
        cases = [(b"HTTP/1.1 101 UPGRADED\r\nUpgrade: tcp", 101),
                 (b"HTTP/1.1 404 Not Found", 404),
                 (b"HTTP/1.1 200 OK\r\nContent-Length: 2", 200),
                 (b"HTTP/1.1  101 x", None),
                 (b"HTTP/1.1 1O1 x", None),
                 (b"HTTP/1.1 1010 x", None),
                 (b"HTTP/1.1", None),
                 (b"garbage", None),
                 (b"", None)]
        for rhead, want in cases:
            self.assertEqual(PX._status_code(rhead), want, rhead)


class TestTargetHelpers(Base):
    """F19 (spec 2026-09-24). Which container a request acts on, and whether dockerd's
    description of it is an ads-mutator run. Pure — no sockets."""

    def test_container_target_extracts_the_full_id(self):
        for path in ("/v1.55/containers/%s/json" % MUT_ID,
                     "/containers/%s/start" % MUT_ID,
                     "/v1.55/containers/%s/wait?condition=removed" % MUT_ID,
                     "/v1.55/containers/%s/attach?stderr=1&stdin=1&stdout=1&stream=1" % MUT_ID,
                     "/v1.55/containers/%s?force=1" % MUT_ID,
                     "/v1.55/containers/%s" % MUT_ID):
            self.assertEqual(PX.container_target(path), MUT_ID, path)

    def test_container_target_is_none_for_calls_that_name_no_container(self):
        for path in ("/v1.55/containers/json", "/v1.55/containers/json?all=1&filters=x",
                     "/v1.55/containers/create?name=hermes-agent-ads-mutator-run-1a2b",
                     "/_ping", "/v1.55/version", "/v1.55/networks", "/v1.55/volumes",
                     "/v1.55/images/hermes-agent-claude/json",
                     "/v1.55/containers/%sx/json" % MUT_ID,
                     "/v1.55/containers/%s/../x" % MUT_ID):
            self.assertIsNone(PX.container_target(path), path)

    def test_every_container_scoped_allow_list_entry_is_target_checked(self):
        """Iterates ALLOWED itself, so a future id-scoped entry cannot skip the check."""
        scoped = [(m, pat) for m, pat in PX.ALLOWED if PX._CID in pat.pattern]
        self.assertEqual(len(scoped), 5, scoped)
        for m, pat in scoped:
            sample = pat.pattern.replace(PX._V, "/v1.55").replace(PX._CID, MUT_ID)
            self.assertTrue(pat.fullmatch(sample), sample)
            self.assertEqual(PX.container_target(sample), MUT_ID, (m, sample))

    def test_no_container_entry_accepts_a_loose_id(self):
        for m, pat in PX.ALLOWED:
            p = pat.pattern
            self.assertNotIn("/containers/" + PX._ID, p, (m, p))
            if "/containers/" in p and not p.endswith(("/containers/create", "/containers/json")):
                self.assertIn(PX._CID, p, (m, p))

    def test_a_mutator_run_is_mutator_shaped(self):
        ok, why = PX.is_mutator_shaped(MUTATOR_DOC, MUT_ID)
        self.assertTrue(ok, why)

    def test_look_alikes_are_refused_with_a_fixed_reason(self):
        cases = [
            ("gateway: same image, other entrypoint", GATEWAY_DOC, GW_ID, "entrypoint mismatch"),
            ("claude-auth-init", {"Id": GW_ID, "Config": {
                "Image": "hermes-agent-claude",
                "Entrypoint": ["/usr/local/bin/bootstrap-claude-auth.sh"]}}, GW_ID,
             "entrypoint mismatch"),
            ("entrypoint as a string",
             _mut(Entrypoint="python3 /opt/cc-bin/apply-changeset.py"), MUT_ID,
             "entrypoint mismatch"),
            ("entrypoint null", _mut(Entrypoint=None), MUT_ID, "entrypoint mismatch"),
            ("entrypoint with an extra element",
             _mut(Entrypoint=["python3", "/opt/cc-bin/apply-changeset.py", "-x"]), MUT_ID,
             "entrypoint mismatch"),
            ("image with a tag", _mut(Image="hermes-agent-claude:latest"), MUT_ID,
             "image mismatch"),
            ("other image", _mut(Image="alpine"), MUT_ID, "image mismatch"),
            ("Config missing", {"Id": MUT_ID}, MUT_ID, "malformed inspect"),
            ("Config not an object", {"Id": MUT_ID, "Config": []}, MUT_ID, "malformed inspect"),
            ("id mismatch", MUTATOR_DOC, GW_ID, "id mismatch"),
            ("doc not an object", [MUTATOR_DOC], MUT_ID, "malformed inspect"),
            ("doc None", None, MUT_ID, "malformed inspect"),
        ]
        for label, doc, cid, want in cases:
            ok, why = PX.is_mutator_shaped(doc, cid)
            self.assertFalse(ok, label)
            self.assertEqual(why, "target is not an ads-mutator run: " + want, label)

    def test_a_reason_never_quotes_the_document(self):
        _, why = PX.is_mutator_shaped(GATEWAY_DOC, GW_ID)
        self.assertNotIn(SENTINEL, why)
        self.assertNotIn("entrypoint.sh", why)

    def test_an_unconfigured_proxy_refuses_everything(self):
        """Review focus: with PINNED_IMAGE unset, a doc with no Image must not match None."""
        self.addCleanup(PX.configure, image="hermes-agent-claude", binds=BINDS,
                        governance_root="/opt/governance", network="hermes-agent_default")
        PX.PINNED_IMAGE = None
        doc = {"Id": MUT_ID, "Config": {"Entrypoint": ["python3", "/opt/cc-bin/apply-changeset.py"]}}
        ok, why = PX.is_mutator_shaped(doc, MUT_ID)
        self.assertFalse(ok)
        self.assertEqual(why, "target is not an ads-mutator run: proxy not configured")


class TestLookupTarget(unittest.TestCase):
    """F19: the proxy's own question to dockerd. A fresh connection per lookup, stdlib
    http.client framing, and EVERY failure — foreseen or not — is a refusal."""

    def _lookup(self, reply, cid=MUT_ID):
        path, got = _one_shot_upstream(self, reply)
        return PX.lookup_target(path, cid), got

    def test_a_200_returns_the_document(self):
        (doc, why), _ = self._lookup(_json_200(MUTATOR_DOC))
        self.assertEqual((doc, why), (MUTATOR_DOC, ""))

    def test_the_request_is_unversioned_and_identifies_itself(self):
        _, got = self._lookup(_json_200(MUTATOR_DOC))
        head = got[0]
        self.assertTrue(head.startswith(("GET /containers/%s/json HTTP/1.1\r\n" % MUT_ID).encode()),
                        head)
        self.assertIn(b"User-Agent: " + PX.LOOKUP_UA.encode(), head)

    def test_a_chunked_reply_is_read(self):
        """Review focus: dockerd sends large JSON bodies chunked."""
        (doc, why), _ = self._lookup(_chunked_200(MUTATOR_DOC))
        self.assertEqual((doc, why), (MUTATOR_DOC, ""))

    def test_a_404_is_target_not_found(self):
        (doc, why), _ = self._lookup(b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\n{}")
        self.assertEqual((doc, why), (None, "target not found"))

    def test_other_statuses_fail(self):
        for status in (b"500 Internal Server Error", b"301 Moved", b"204 No Content"):
            (doc, why), _ = self._lookup(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n\r\n")
            self.assertEqual((doc, why), (None, "target lookup failed"), status)

    def test_bad_json_fails(self):
        (doc, why), _ = self._lookup(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nnot{j")
        self.assertEqual((doc, why), (None, "target lookup failed"))

    def test_an_unforeseen_exception_is_refused(self):
        """Review focus: an error nobody foresaw (not OSError/ValueError/HTTPException) must still be
        a refusal. Deterministic on every interpreter: the proxy's json.loads is swapped, scoped and
        restored, for one that raises a type nothing else raises."""
        import types

        class _Unforeseen(Exception):
            pass

        def boom(_s):
            raise _Unforeseen()

        self.addCleanup(setattr, PX, "json", PX.json)
        PX.json = types.SimpleNamespace(loads=boom, dumps=json.dumps)
        (doc, why), _ = self._lookup(_json_200(MUTATOR_DOC))
        self.assertEqual((doc, why), (None, "target lookup failed"))

    def test_a_garbled_status_line_is_refused(self):
        (doc, why), _ = self._lookup(b"HTTP/1.1 2OO OK\r\nContent-Length: 2\r\n\r\n{}")
        self.assertEqual((doc, why), (None, "target lookup failed"))

    def test_an_oversize_reply_fails(self):
        old = PX.MAX_BODY
        self.addCleanup(setattr, PX, "MAX_BODY", old)
        PX.MAX_BODY = 1000
        (doc, why), _ = self._lookup(b"HTTP/1.1 200 OK\r\nContent-Length: 2000\r\n\r\n"
                                     + b" " * 2000)
        self.assertEqual((doc, why), (None, "target lookup failed"))

    def test_an_oversize_chunked_reply_fails(self):
        """dockerd sends large inspect bodies chunked; read(MAX_BODY + 1) must bound that path too."""
        old = PX.MAX_BODY
        self.addCleanup(setattr, PX, "MAX_BODY", old)
        PX.MAX_BODY = 1000
        big = dict(MUTATOR_DOC, Pad="x" * 2000)
        (doc, why), _ = self._lookup(_chunked_200(big))
        self.assertEqual((doc, why), (None, "target lookup failed"))

    def test_no_answer_fails_within_the_timeout(self):
        old = PX.LOOKUP_TIMEOUT
        self.addCleanup(setattr, PX, "LOOKUP_TIMEOUT", old)
        PX.LOOKUP_TIMEOUT = 0.3
        t0 = time.monotonic()
        (doc, why), _ = self._lookup(HANG)
        self.assertEqual((doc, why), (None, "target lookup failed"))
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_an_unreachable_upstream_fails(self):
        doc, why = PX.lookup_target("/tmp/pxlk-does-not-exist-%d.sock" % os.getpid(), MUT_ID)
        self.assertEqual((doc, why), (None, "target lookup failed"))


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
                # F19: the proxy's target-check lookup arrives on its own connection first.
                reply = _lookup_reply(data, {MUT_ID: MUTATOR_DOC})
                conn.sendall(reply if reply is not None
                             else b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
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
        req = (b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed HTTP/1.1\r\n"
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
        req = (b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed HTTP/1.1\r\n"
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
        req = (b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed HTTP/1.1\r\n"
               b"Host: d\r\nContent-Length: 0\r\n\r\n")
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(req)
        resp = c.recv(65536)
        c.close()
        self.assertNotIn(b"403", resp)
        self.assertTrue(
            any(line.startswith("POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait")
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
        resp = self._send(b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed "
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
        resp = self._send(b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed "
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
        resp = self._send(b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed "
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
                c.sendall(b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed "
                         b"HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n")
                time.sleep(0.02)
        c.close()
        self.assertFalse(
            any("wait" in line for line in upstream_saw),
            "a request the proxy never decided still reached the upstream: %r"
            % upstream_saw)

    # ---- the framing hardening, end to end (spec 2026-09-23) ---------------------------
    # Each form carries a privileged create hidden in an allowed `wait` request. The proof is
    # NON-RECEIPT: `/containers/create` must appear nowhere in the upstream's raw bytes.

    SMUGGLED = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 2\r\n\r\n{}")
    WAIT = b"POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait?condition=removed HTTP/1.1\r\n"

    def _assert_never_reached_upstream(self, marker=b"/containers/create", settle=0.5):
        """Non-receipt, race-free: the fake upstream appends on its own thread, so poll for
        `settle` seconds and fail the moment the marker appears. Absence for the whole window
        is the pass."""
        _poll_never_received(self, self.upstream_raw, marker, settle)

    def _assert_smuggle_refused(self, req, reason):
        resp = self._send(req)
        self._assert_never_reached_upstream()
        self.assertIn(b"403", resp)
        self.assertIn(reason.encode(), resp)

    def test_an_obs_fold_smuggled_create_is_refused(self):
        tail = b"0\r\n\r\n" + self.SMUGGLED
        req = (self.WAIT + b"Host: d\r\nX-Pad: pad\r\n\tTransfer-Encoding: chunked\r\n"
               b"Content-Length: " + str(len(tail)).encode() + b"\r\n\r\n" + tail)
        self._assert_smuggle_refused(req, "malformed header line")

    def test_a_space_before_colon_smuggled_create_is_refused(self):
        tail = b"0\r\n\r\n" + self.SMUGGLED
        req = (self.WAIT + b"Host: d\r\nTransfer-Encoding : chunked\r\n"
               b"Content-Length: " + str(len(tail)).encode() + b"\r\n\r\n" + tail)
        self._assert_smuggle_refused(req, "malformed header line")

    def test_a_duplicate_content_length_smuggled_create_is_refused(self):
        req = (self.WAIT + b"Host: d\r\nContent-Length: 0\r\n"
               b"Content-Length: " + str(len(self.SMUGGLED)).encode() + b"\r\n\r\n"
               + self.SMUGGLED)
        self._assert_smuggle_refused(req, "duplicate Content-Length")

    def test_a_bare_lf_smuggled_create_is_refused(self):
        tail = b"0\r\n\r\n" + self.SMUGGLED
        req = (self.WAIT + b"Host: d\r\nX-Pad: a\nTransfer-Encoding: chunked\r\n"
               b"Content-Length: " + str(len(tail)).encode() + b"\r\n\r\n" + tail)
        self._assert_smuggle_refused(req, "malformed request")

    def test_a_refused_head_closes_the_connection(self):
        """After a head it could not parse there is no safe place to resume reading: the
        connection must close, so nothing sent after it reaches the upstream."""
        import socket as _s
        self._start_proxy()
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"GET /_ping HTTP/1.0\r\nHost: d\r\n\r\n")
        first = c.recv(65536)
        self.assertIn(b"403", first)
        self.assertIn(b"malformed request line", first)
        try:
            c.sendall(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            c.settimeout(2)
            second = c.recv(65536)
        except OSError:
            second = b""
        c.close()
        self.assertEqual(second, b"", "the proxy kept reading after a refused head")
        self.assertEqual(self.upstream_raw, [])

    def test_ordinary_heads_still_reach_upstream(self):
        """POSITIVE CONTROL for the grammar at the socket level: well-formed heads of the
        shapes real clients send are still forwarded. Separate connections on purpose: the
        fake upstream closes after each reply, so a keep-alive pair would fail for a reason
        unrelated to the grammar."""
        import socket as _s
        self._start_proxy()
        for req in (b"HEAD /_ping HTTP/1.1\r\nHost: d\r\n\r\n",
                    self.WAIT + b"Host: localhost:2375\r\nUser-Agent: compose/v2.38.2\r\n"
                                b"Content-Length: 0\r\n\r\n"):
            c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
            c.connect(self.li_path)
            c.sendall(req)
            self.assertNotIn(b"403", c.recv(65536), req)
            c.close()
        self.assertIn("HEAD /_ping HTTP/1.1", self.upstream_saw)
        self.assertTrue(any(l.startswith("POST /v1.55/containers/deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef/wait")
                            for l in self.upstream_saw), self.upstream_saw)


class _KeepAliveFakeMixin:
    """A fake upstream that KEEPS each connection open and answers requests in order, like
    dockerd (F18). An attach is answered with `self.attach_reply`; after a 101 the fake
    records what it receives in `self.upgraded_rx` and echoes it back prefixed `ECHO:`.
    F19: inspect requests are answered from `self.inspect_table`, and every parsed request
    head is recorded in `self.heads`."""

    SMUGGLED = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 2\r\n\r\n{}")
    UPGRADE_101 = (b"HTTP/1.1 101 UPGRADED\r\nContent-Type: application/vnd.docker.raw-stream\r\n"
                   b"Connection: Upgrade\r\nUpgrade: tcp\r\n\r\nSTREAM-HELLO")
    NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\n{}"
    ATTACH = (b"POST /v1.55/containers/" + MUT_ID.encode()
              + b"/attach?stream=1&stdout=1&stderr=1 HTTP/1.1\r\n"
              b"Host: d\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n")

    def setUp(self):
        import threading, socket as _s
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance", network="hermes-agent_default")
        n = next(_SOCK_SEQ)
        self.up_path = "/tmp/pxkaup-%d-%d.sock" % (os.getpid(), n)
        self.li_path = "/tmp/pxkali-%d-%d.sock" % (os.getpid(), n)
        for p in (self.up_path, self.li_path):
            if os.path.exists(p):
                os.remove(p)
        self.upstream_raw, self.upgraded_rx = [], []
        self.heads = []                                      # F19
        self.inspect_table = {MUT_ID: MUTATOR_DOC}           # F19
        self.attach_reply = self.NOT_FOUND
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(self.up_path)
        srv.listen(8)

        def serve_conn(c):
            buf, upgraded = b"", False
            while True:
                try:
                    d = c.recv(65536)
                except OSError:
                    return
                if not d:
                    return
                self.upstream_raw.append(d)
                if upgraded:
                    self.upgraded_rx.append(d)
                    c.sendall(b"ECHO:" + d)
                    continue
                buf += d
                while b"\r\n\r\n" in buf:
                    head, rest = buf.split(b"\r\n\r\n", 1)
                    clen = 0
                    for h in head.split(b"\r\n")[1:]:
                        if h.lower().startswith(b"content-length:"):
                            clen = int(h.split(b":", 1)[1])
                    if len(rest) < clen:
                        break
                    buf = rest[clen:]
                    self.heads.append(head)                  # F19
                    reply = _lookup_reply(head, self.inspect_table)   # F19
                    if reply is HANG:
                        continue
                    if reply is not None:
                        c.sendall(reply)
                        continue
                    method, target = head.split(b"\r\n")[0].split(b" ")[:2]
                    if method == b"POST" and target.split(b"?")[0].endswith(b"/attach"):
                        c.sendall(self.attach_reply)
                        if self.attach_reply.startswith(b"HTTP/1.1 101"):
                            upgraded = True
                            if buf:
                                self.upgraded_rx.append(buf)
                                buf = b""
                            break
                    else:
                        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")

        def accept_loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                threading.Thread(target=serve_conn, args=(c,), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()
        self.addCleanup(srv.close)
        for p in (self.up_path, self.li_path):
            self.addCleanup(lambda q=p: os.path.exists(q) and os.remove(q))
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        _await_accepting(self.li_path)

    def _connect(self):
        import socket as _s
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.settimeout(2)
        self.addCleanup(c.close)
        return c

    def _recv_until(self, c, needle, timeout=2.0):
        """Everything received until `needle` appears, the peer closes, or `timeout`."""
        got, deadline = b"", time.monotonic() + timeout
        while needle not in got and time.monotonic() < deadline:
            try:
                d = c.recv(65536)
            except OSError:
                break
            if not d:
                break
            got += d
        return got

    def _send_then_smuggle(self, first, first_needle=b"{}"):
        """Send `first`, read its whole response, then send the smuggled create on the SAME
        connection. Returns (first_response, response_to_smuggled_or_b"")."""
        c = self._connect()
        c.sendall(first)
        r1 = self._recv_until(c, first_needle)
        try:
            c.sendall(self.SMUGGLED)
            r2 = self._recv_until(c, b"\r\n\r\n", timeout=1.0)
        except OSError:
            r2 = b""
        return r1, r2


class TestAttachPassThrough(_KeepAliveFakeMixin, unittest.TestCase):
    """F18 (spec 2026-09-23). The fake upstream here KEEPS each connection open and answers
    requests in order, like dockerd — TestPlumbing's fake closes after every reply, which is
    exactly why a bypass that needs a second request on the same connection was never
    exercised. An attach is answered with `self.attach_reply`; after a 101 the fake records
    what it receives in `self.upgraded_rx` and echoes it back prefixed `ECHO:`."""

    # ---- the three routes (all must let the create through BEFORE the fix) ------------

    def test_route_a_attach_in_the_query_string(self):
        r1, r2 = self._send_then_smuggle(b"GET /_ping?x=/attach HTTP/1.1\r\nHost: d\r\n\r\n")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"200 OK", r1)
        self.assertIn(b"403", r2, "the smuggled create was not inspected")

    def test_route_b_a_container_literally_named_attach(self):
        """Since F19 the grammar refuses this before anything is forwarded: `attach` is not a
        64-hex id. The connection closes after the refusal, so the create cannot follow."""
        r1, r2 = self._send_then_smuggle(
            b"DELETE /v1.55/containers/attach HTTP/1.1\r\nHost: d\r\n\r\n",
            first_needle=b"}")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"403", r1)
        self.assertIn(b"allow-list", r1)
        self.assertEqual(r2, b"", "the connection stayed open after a refusal")

    def test_route_c_an_attach_answered_404(self):
        self.attach_reply = self.NOT_FOUND
        r1, r2 = self._send_then_smuggle(self.ATTACH)
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"404 Not Found", r1)
        self.assertEqual(r2, b"", "the connection stayed open after a non-upgraded attach")

    # ---- a genuine attach still works ----------------------------------------------------

    def test_a_101_attach_streams_both_ways(self):
        self.attach_reply = self.UPGRADE_101
        c = self._connect()
        c.sendall(self.ATTACH)
        got = self._recv_until(c, b"STREAM-HELLO")
        self.assertIn(b"101 UPGRADED", got)
        self.assertIn(b"STREAM-HELLO", got, "stream bytes sent with the 101 head were lost")
        c.sendall(b"PING-IN")
        self.assertIn(b"ECHO:PING-IN", self._recv_until(c, b"ECHO:PING-IN"))
        self.assertIn(b"PING-IN", b"".join(self.upgraded_rx))

    def test_client_bytes_read_with_the_attach_are_forwarded_after_the_upgrade(self):
        self.attach_reply = self.UPGRADE_101
        c = self._connect()
        c.sendall(self.ATTACH + b"EARLY-STDIN")
        self._recv_until(c, b"STREAM-HELLO")
        deadline = time.monotonic() + 1.0
        while b"EARLY-STDIN" not in b"".join(self.upgraded_rx) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(b"EARLY-STDIN", b"".join(self.upgraded_rx),
                      "bytes already read past the attach request were dropped")

    def test_an_attach_after_a_ping_on_one_connection_still_upgrades(self):
        self.attach_reply = self.UPGRADE_101
        c = self._connect()
        c.sendall(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
        self.assertIn(b"200 OK", self._recv_until(c, b"{}"))
        c.sendall(self.ATTACH)
        self.assertIn(b"STREAM-HELLO", self._recv_until(c, b"STREAM-HELLO"))

    # ---- any other answer to an attach: relay, then close --------------------------------

    def test_an_attach_answered_200_is_relayed_then_closed(self):
        self.attach_reply = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"
        r1, r2 = self._send_then_smuggle(self.ATTACH)
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"200 OK", r1)
        self.assertEqual(r2, b"")

    def test_an_attach_answered_with_a_garbled_status_is_relayed_then_closed(self):
        self.attach_reply = b"HTTP/1.1 1O1 X\r\nContent-Length: 2\r\n\r\n{}"
        r1, r2 = self._send_then_smuggle(self.ATTACH)
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"1O1", r1)
        self.assertEqual(r2, b"")

    def test_a_chunked_error_to_an_attach_is_relayed_then_closed(self):
        self.attach_reply = (b"HTTP/1.1 409 Conflict\r\nTransfer-Encoding: chunked\r\n\r\n"
                             b"2\r\n{}\r\n0\r\n\r\n")
        r1, r2 = self._send_then_smuggle(self.ATTACH, first_needle=b"0\r\n\r\n")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"409 Conflict", r1)
        self.assertEqual(r2, b"")

    def test_a_garbled_status_is_logged_as_none(self):
        import contextlib, io
        self.attach_reply = b"HTTP/1.1 1O1 ZZ-UPSTREAM-MARKER\r\nContent-Length: 2\r\n\r\n{}"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            c = self._connect()
            c.sendall(self.ATTACH)
            self._recv_until(c, b"{}")
            deadline = time.monotonic() + 1.0
            while "DENY-FOLLOWUP" not in err.getvalue() and time.monotonic() < deadline:
                time.sleep(0.01)
        log = err.getvalue()
        self.assertIn("attach answered None, not upgraded; connection closed", log)
        self.assertNotIn("ZZ-UPSTREAM-MARKER", log)

    def test_pipelined_bytes_after_a_non_upgraded_attach_are_never_forwarded(self):
        """`buf` may be forwarded only AFTER dockerd upgraded the connection. Sent in ONE
        write with an attach answered 404, the smuggled create must never reach dockerd."""
        self.attach_reply = self.NOT_FOUND
        c = self._connect()
        c.sendall(self.ATTACH + self.SMUGGLED)
        r1 = self._recv_until(c, b"{}")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"404 Not Found", r1)

    def test_a_malformed_content_length_on_an_attach_response_logs_deny_followup(self):
        """M1: the malformed-Content-Length early return, when it fires for an attach, must
        also log DENY-FOLLOWUP so the box's journal always shows why an attach connection
        closed — not just the reason the response itself couldn't be relayed."""
        import contextlib, io
        self.attach_reply = b"HTTP/1.1 404 Not Found\r\nContent-Length: abc\r\n\r\n"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            c = self._connect()
            c.sendall(self.ATTACH)
            deadline = time.monotonic() + 1.0
            while "DENY-FOLLOWUP" not in err.getvalue() and time.monotonic() < deadline:
                time.sleep(0.01)
        log = err.getvalue()
        self.assertIn("attach answered 404, not upgraded; connection closed", log)


class TestTargetCheck(_KeepAliveFakeMixin, unittest.TestCase):
    """F19 (spec 2026-09-24). A container-scoped call is forwarded only when dockerd says the
    target is an ads-mutator run. The proxy's lookup and a client inspect share a PATH, so
    "never reached upstream" is judged by the lookup's User-Agent (heads) and by the /v1.55
    prefix only client requests carry (raw bytes)."""

    CALLS = (("GET", "/json"), ("POST", "/start"), ("POST", "/wait?condition=removed"),
             ("POST", "/attach?stderr=1&stdin=1&stdout=1&stream=1"), ("DELETE", "?force=1"))

    def setUp(self):
        super().setUp()
        self.inspect_table[GW_ID] = GATEWAY_DOC
        self.attach_reply = self.UPGRADE_101

    def _req(self, method, cid, tail):
        extra = b"Connection: Upgrade\r\nUpgrade: tcp\r\n" if "/attach" in tail else b""
        return (("%s /v1.55/containers/%s%s HTTP/1.1\r\nHost: d\r\n" % (method, cid, tail))
                .encode() + extra + b"\r\n")

    def _client_heads_naming(self, cid):
        return [h for h in list(self.heads)
                if cid.encode() in h and PX.LOOKUP_UA.encode() not in h]

    def _assert_client_never_reached_upstream(self, cid, settle=0.5):
        deadline = time.monotonic() + settle
        while True:
            leaked = self._client_heads_naming(cid)
            if leaked:
                self.fail("a refused request reached the upstream: %r" % leaked)
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        _poll_never_received(self, self.upstream_raw, ("/v1.55/containers/" + cid).encode(), 0)

    def _await_client_head(self, method, cid, tail, timeout=2.0):
        want = ("%s /v1.55/containers/%s%s " % (method, cid, tail)).encode()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(h.startswith(want) for h in self._client_heads_naming(cid)):
                return True
            time.sleep(0.01)
        return False

    # ---- the gateway: every container-scoped call is refused before upstream -----------

    def test_every_container_scoped_call_at_the_gateway_is_refused(self):
        for method, tail in self.CALLS:
            with self.subTest(call=method + " " + tail):
                c = self._connect()
                c.sendall(self._req(method, GW_ID, tail))
                resp = self._recv_until(c, b"}")
                self._assert_client_never_reached_upstream(GW_ID)
                self.assertIn(b"403", resp)
                self.assertIn(b"target is not an ads-mutator run: entrypoint mismatch", resp)
                self.assertNotIn(b"101", resp)
                self.assertNotIn(SENTINEL.encode(), resp)

    def test_a_request_pipelined_behind_a_refused_target_never_reaches_upstream(self):
        """A target refusal must CLOSE the connection. Pipelined behind a refused gateway call, an
        otherwise-ALLOWED mutator inspect must never be forwarded (a `continue` instead of `return`
        would forward it)."""
        c = self._connect()
        c.sendall(self._req("POST", GW_ID, "/start") + self._req("GET", MUT_ID, "/json"))
        resp = self._recv_until(c, b"}")
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            self.assertFalse(any(h.startswith(("GET /v1.55/containers/%s/json " % MUT_ID).encode())
                                 for h in self._client_heads_naming(MUT_ID)),
                             "a request pipelined behind a refusal reached the upstream")
            time.sleep(0.01)
        self._assert_client_never_reached_upstream(GW_ID, settle=0)
        self.assertIn(b"403", resp)
        try:
            c.sendall(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            more = self._recv_until(c, b"\r\n\r\n", timeout=1.0)
        except OSError:
            more = b""
        self.assertEqual(more, b"", "the connection stayed open after a target refusal")

    # ---- a mutator run: every call is forwarded, and attach still upgrades -------------

    def test_every_container_scoped_call_at_a_mutator_run_is_forwarded(self):
        for method, tail in self.CALLS:
            with self.subTest(call=method + " " + tail):
                c = self._connect()
                c.sendall(self._req(method, MUT_ID, tail))
                needle = b"STREAM-HELLO" if "/attach" in tail else b"}"
                resp = self._recv_until(c, needle)
                self.assertNotIn(b"403", resp)
                self.assertIn(needle, resp)
                self.assertTrue(self._await_client_head(method, MUT_ID, tail),
                                "the allowed %s never reached the upstream" % method)

    # ---- per request, not per connection -----------------------------------------------

    def test_a_gateway_inspect_after_a_mutator_inspect_on_one_connection_is_refused(self):
        c = self._connect()
        c.sendall(self._req("GET", MUT_ID, "/json"))
        r1 = self._recv_until(c, b"]}}")
        c.sendall(self._req("GET", GW_ID, "/json"))
        r2 = self._recv_until(c, b"}")
        self._assert_client_never_reached_upstream(GW_ID)
        self.assertIn(b"200 OK", r1)
        self.assertIn(b"403", r2)
        self.assertNotIn(SENTINEL.encode(), r1 + r2)

    # ---- the lookup fails: refused, nothing forwarded ----------------------------------

    def test_every_lookup_failure_is_a_refusal(self):
        old_to, old_max = PX.LOOKUP_TIMEOUT, PX.MAX_BODY
        self.addCleanup(setattr, PX, "LOOKUP_TIMEOUT", old_to)
        self.addCleanup(setattr, PX, "MAX_BODY", old_max)
        PX.LOOKUP_TIMEOUT = 0.3
        PX.MAX_BODY = 1000
        cases = {
            "1" * 64: (b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 2\r\n\r\n{}",
                       b"target lookup failed"),
            "2" * 64: (HANG, b"target lookup failed"),
            "3" * 64: (b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nnot{j",
                       b"target lookup failed"),
            "4" * 64: (b"HTTP/1.1 200 OK\r\nContent-Length: 2000\r\n\r\n" + b" " * 2000,
                       b"target lookup failed"),
            "5" * 64: (None, b"target not found"),        # not in the table: the fake 404s
        }
        for cid, (reply, reason) in cases.items():
            if reply is not None:
                self.inspect_table[cid] = reply
        for cid, (_, reason) in cases.items():
            with self.subTest(cid=cid[:4]):
                c = self._connect()
                c.sendall(self._req("GET", cid, "/json"))
                resp = self._recv_until(c, b"}")
                self._assert_client_never_reached_upstream(cid)
                self.assertIn(b"403", resp)
                self.assertIn(reason, resp)

    # ---- the log: fixed reasons, no ALLOW for a refused call, no sentinel --------------

    def test_the_log_carries_a_fixed_reason_and_never_the_inspect(self):
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for method, tail in (("GET", "/json"), ("POST", "/attach?stdin=1&stream=1")):
                c = self._connect()
                c.sendall(self._req(method, GW_ID, tail))
                self._recv_until(c, b"}")
            deadline = time.monotonic() + 1.0
            while err.getvalue().count("entrypoint mismatch") < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
        log = err.getvalue()
        self.assertEqual(log.count("(target is not an ads-mutator run: entrypoint mismatch)"), 2, log)
        self.assertNotIn("ALLOW GET /v1.55/containers/" + GW_ID, log)
        self.assertNotIn("ALLOW POST /v1.55/containers/" + GW_ID, log)
        self.assertNotIn(SENTINEL, log)

    # ---- Compose's three parallel connections -------------------------------------------

    def test_compose_s_three_parallel_connections_all_pass(self):
        """Review focus: attach, start and wait arrive on three connections at once
        (docker-create-proxy.py header, trap 2); each does its own lookup."""
        import threading
        results = {}

        def one(method, tail, needle):
            c = self._connect()
            c.sendall(self._req(method, MUT_ID, tail))
            results[method + tail] = self._recv_until(c, needle)

        threads = [threading.Thread(target=one, args=a) for a in (
            ("POST", "/attach?stderr=1&stdin=1&stdout=1&stream=1", b"STREAM-HELLO"),
            ("POST", "/wait?condition=removed", b"}"),
            ("POST", "/start", b"}"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(len(results), 3, results)
        for k, resp in results.items():
            self.assertNotIn(b"403", resp, k)
        self.assertIn(b"STREAM-HELLO", results["POST/attach?stderr=1&stdin=1&stdout=1&stream=1"])


if __name__ == "__main__":
    unittest.main()
