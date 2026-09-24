# F18 — Attach pass-through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Docker proxy switches a connection to raw pass-through only for a real `POST …/attach` that dockerd answers `101`; any other answer to an attach is relayed and the connection closed; nothing else ever stops being inspected.

**Architecture:** In `docker-create-proxy.py`, attach is defined once (`_ATTACH_RE`, `_is_attach`), the upstream status is read strictly (`_status_code`), and `_handle` reads dockerd's response head **before** deciding to pump. Upgrade → forward the response, forward any already-read client bytes, pump both ways. Attach not upgraded → relay, log, close. Non-attach → unchanged.

**Tech Stack:** Python 3 stdlib (`re`, `socket`, `threading`, `unittest`); Docker Compose on Linux CI.

**Spec:** `docs/superpowers/specs/2026-09-23-f18-attach-pass-through-design.md`

## Global Constraints

- **Mutation stays disabled. The kill switch is ABSENT and nothing in this plan creates it.**
- **The allow-list's contents are unchanged.** `decide()`, `configure()`, `_parse_head`, pinned values untouched. The attach entry in `ALLOWED` is re-expressed as `("POST", _ATTACH_RE)` — same pattern, same object used by `_is_attach`.
- **NEVER run `docker compose config`.** Never read or print `.env*`. Never run `docker`/`systemctl` locally.
- **Never edit a tracked file to run a mutation test.** Controls are in memory or on scratch copies under a temp dir.
- **Stage by explicit path only.** Never `git add -A`, `.`, `commit -a`, `.project-brain/`, `evals/`, `CLAUDE.md`.
- Pass-through only when `_is_attach(method, path)` **and** `_status_code(rhead) == 101`.
- Log lines, exact shapes: `UPGRADE POST <path> (101)` and `DENY-FOLLOWUP POST <path> (attach answered <status>, not upgraded; connection closed)` where `<status>` is an `int` or `None` — never raw upstream bytes.
- Required CI job names are gates: do not rename `Bind agreement (root, Linux, real proxy)` or `Test suites (node + hermes bin)`. Read `executed N, skipped M` on the PR and the merge commit.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Stream bytes that arrive in the same read as the 101 head** must reach the client (not be lost in `rrest`). Pinned in Task 2 (`test_a_101_attach_streams_both_ways` — the fake sends `STREAM-HELLO` in the same write as the head).
2. **An attach answered with a chunked error** must be relayed and the connection closed, like a Content-Length one. Pinned in Task 2 (`test_a_chunked_error_to_an_attach_is_relayed_then_closed`).
3. **An attach that follows an allowed request on the same keep-alive connection** must still upgrade. Pinned in Task 2 (`test_an_attach_after_a_ping_on_one_connection_still_upgrades`).
4. **The `DENY-FOLLOWUP` log line must not echo a garbled upstream status line.** Pinned in Task 2 (`test_a_garbled_status_is_logged_as_none`).
5. **Real Compose attach on Linux must actually be answered 101** — only CI settles it. Pinned in Task 3 (the `UPGRADE … (101)` assertion).

---

### Task 1: One definition of attach, and a strict status reader

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (define `_ATTACH_RE` directly before `ALLOWED = [`; replace the attach line inside `ALLOWED`; add `_is_attach` and `_status_code` directly after `_path_only`)
- Test: `infra/hermes-agent/bin/docker-create-proxy.test.py` (new class `TestAttachHelpers`, inserted directly before `class TestPlumbing(unittest.TestCase):`)

**Interfaces:**
- Produces: `_ATTACH_RE` (compiled `re.Pattern`); `_is_attach(method: str, path: str) -> bool`; `_status_code(rhead: bytes) -> int | None`. Task 2 consumes all three.

- [ ] **Step 1: Write the failing tests**

Insert before `class TestPlumbing(unittest.TestCase):`:

```python
class TestAttachHelpers(unittest.TestCase):
    """F18 (spec 2026-09-23). Attach is defined ONCE — the allow-list entry and the
    pass-through decision use the same pattern — and the upstream status is read strictly,
    so a garbled status line can never be mistaken for 101."""

    def test_a_real_attach_is_an_attach(self):
        self.assertTrue(PX._is_attach(
            "POST", "/v1.55/containers/abc/attach?stream=1&stdout=1&stderr=1"))
        self.assertTrue(PX._is_attach("POST", "/containers/abc/attach"))

    def test_look_alikes_are_not_attaches(self):
        for method, path in (("GET", "/_ping?x=/attach"),
                             ("DELETE", "/v1.55/containers/attach"),
                             ("GET", "/v1.55/containers/attach/json"),
                             ("POST", "/v1.55/containers/abc/attachx"),
                             ("POST", "/v1.55/containers/abc/attach/../../create"),
                             ("GET", "/v1.55/containers/abc/attach")):
            self.assertFalse(PX._is_attach(method, path), (method, path))

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
```

- [ ] **Step 2: Run to verify they fail**

Run (from `infra/hermes-agent/bin`): `python3 docker-create-proxy.test.py TestAttachHelpers -v 2>&1 | tail -6`
Expected: ERROR — `AttributeError: module 'docker_create_proxy' has no attribute '_is_attach'` (and `_ATTACH_RE`, `_status_code`).

- [ ] **Step 3: Implement**

Directly before `ALLOWED = [`, add:

```python
# F18: attach is defined ONCE. The allow-list entry below and _is_attach() use this same
# object, so "what may be requested" and "what may switch a connection to raw pass-through"
# cannot drift apart.
_ATTACH_RE = re.compile(_V + r"/containers/" + _ID + r"/attach")
```

Inside `ALLOWED`, replace the line `("POST",   re.compile(_V + r"/containers/" + _ID + r"/attach")),` with:

```python
    ("POST",   _ATTACH_RE),
```

Directly after the `_path_only` function, add:

```python
def _is_attach(method, path):
    """True only for a real attach: POST, and the path WITHOUT its query string fullmatches
    the attach pattern. A substring test over the whole target was F18: `GET /_ping?x=/attach`
    and `DELETE /containers/attach` both switched the connection to uninspected pass-through."""
    return method == "POST" and bool(_ATTACH_RE.fullmatch(_path_only(path) or ""))


def _status_code(rhead):
    """The upstream response's status as an int when it is exactly three ASCII digits in the
    second space-separated field of the status line, else None. Only an exact 101 may switch
    a connection to pass-through, so anything unusual reads as None, never as 101."""
    parts = rhead.split(b"\r\n", 1)[0].split(b" ")
    if len(parts) >= 2 and len(parts[1]) == 3 and parts[1].isdigit():
        return int(parts[1])
    return None
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 docker-create-proxy.test.py 2>&1 | tail -2` → `OK` (every existing test, including `TestEndpointAllowList`, still passes — the allow-list's meaning is unchanged).
Then from the repo root: `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `31/31`; `python3 infra/hermes-agent/bin/proxy-policy-sync.test.py 2>&1 | tail -2` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(printf 'fix(hermes): F18 — one definition of attach; a strict upstream status reader\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 2: Pass through only on an upgraded attach; otherwise relay and close

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (`_handle`: remove the `if "/attach" in path:` block; add the upgrade branch and the two relay-then-close exits; new module-level `_pump_both`)
- Test: `infra/hermes-agent/bin/docker-create-proxy.test.py` (module-level `_poll_never_received`; `TestPlumbing._assert_never_reached_upstream` delegates to it; new class `TestAttachPassThrough` after `TestPlumbing`)

**Interfaces:**
- Consumes: `_is_attach(method, path) -> bool`, `_status_code(rhead) -> int | None` (Task 1).
- Produces: `_pump_both(conn, up) -> None`; log lines `UPGRADE POST <path> (101)` and `DENY-FOLLOWUP POST <path> (attach answered <status>, not upgraded; connection closed)` (Task 3 asserts the first on Linux CI).

- [ ] **Step 1: Share the race-free non-receipt poll**

Directly after `_await_accepting` (module level) in the test file, add:

```python
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
```

Replace the body of `TestPlumbing._assert_never_reached_upstream` (keep its signature and docstring) with:

```python
        _poll_never_received(self, self.upstream_raw, marker, settle)
```

Run `python3 docker-create-proxy.test.py TestPlumbing 2>&1 | tail -2` → `OK` (pure refactor).

- [ ] **Step 2: Write the failing tests**

Insert after the end of `class TestPlumbing` (before the next top-level `class` or `if __name__`):

```python
class TestAttachPassThrough(unittest.TestCase):
    """F18 (spec 2026-09-23). The fake upstream here KEEPS each connection open and answers
    requests in order, like dockerd — TestPlumbing's fake closes after every reply, which is
    exactly why a bypass that needs a second request on the same connection was never
    exercised. An attach is answered with `self.attach_reply`; after a 101 the fake records
    what it receives in `self.upgraded_rx` and echoes it back prefixed `ECHO:`."""

    SMUGGLED = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 2\r\n\r\n{}")
    UPGRADE_101 = (b"HTTP/1.1 101 UPGRADED\r\nContent-Type: application/vnd.docker.raw-stream\r\n"
                   b"Connection: Upgrade\r\nUpgrade: tcp\r\n\r\nSTREAM-HELLO")
    NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\n{}"
    ATTACH = (b"POST /v1.55/containers/abc/attach?stream=1&stdout=1&stderr=1 HTTP/1.1\r\n"
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

    def _send_then_smuggle(self, first):
        """Send `first`, read its whole response, then send the smuggled create on the SAME
        connection. Returns (first_response, response_to_smuggled_or_b"")."""
        c = self._connect()
        c.sendall(first)
        r1 = self._recv_until(c, b"{}")
        try:
            c.sendall(self.SMUGGLED)
            r2 = self._recv_until(c, b"\r\n\r\n", timeout=1.0)
        except OSError:
            r2 = b""
        return r1, r2

    # ---- the three routes (all must let the create through BEFORE the fix) ------------

    def test_route_a_attach_in_the_query_string(self):
        r1, r2 = self._send_then_smuggle(b"GET /_ping?x=/attach HTTP/1.1\r\nHost: d\r\n\r\n")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"200 OK", r1)
        self.assertIn(b"403", r2, "the smuggled create was not inspected")

    def test_route_b_a_container_literally_named_attach(self):
        r1, r2 = self._send_then_smuggle(
            b"DELETE /v1.55/containers/attach HTTP/1.1\r\nHost: d\r\n\r\n")
        _poll_never_received(self, self.upstream_raw)
        self.assertIn(b"200 OK", r1)
        self.assertIn(b"403", r2, "the smuggled create was not inspected")

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
        r1, r2 = self._send_then_smuggle(self.ATTACH)
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 docker-create-proxy.test.py TestAttachPassThrough -v 2>&1 | tail -20`
Expected before the fix: routes a, b and c FAIL on `smuggled create reached the upstream socket` (the proxy pumps after any path containing `/attach`); `test_client_bytes_read_with_the_attach_are_forwarded_after_the_upgrade` FAILS (buf dropped); the 200 / garbled / chunked tests FAIL on non-receipt; `test_a_garbled_status_is_logged_as_none` FAILS (no such log line). `test_a_101_attach_streams_both_ways` and `test_an_attach_after_a_ping_on_one_connection_still_upgrades` may pass (the old code pumps). Record the exact per-test outcome in the report.

- [ ] **Step 4: Implement**

Add at module level, directly before `def _handle(conn, upstream_path):`:

```python
def _pump_both(conn, up):
    """Raw two-way relay for an UPGRADED attach, until either side closes. Only ever entered
    after dockerd answered 101 to a real attach — after that the connection carries the
    container's stdio stream, not the Docker API, so there is nothing left to inspect."""
    def pump(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
    threading.Thread(target=pump, args=(conn, up), daemon=True).start()
    pump(up, conn)
```

In `_handle`, delete the whole block from `if "/attach" in path:` through its `return` (the local `pump` definition, the thread start, `pump(up, conn)` and `return`).

Directly after the existing

```python
            rhead, rrest = _read_until_headers(up, b"")
            if rhead is None:
                return
```

insert:

```python
            # F18: decide on pass-through only AFTER dockerd has answered, and only for a real
            # attach it upgraded. Any other answer to an attach is relayed below and then the
            # connection is closed — after an attach there are exactly two outcomes, upgraded or
            # closed, and no request can follow one on the same connection.
            attach = _is_attach(method, path)
            status = _status_code(rhead)
            if attach and status == 101:
                conn.sendall(rhead + b"\r\n\r\n" + rrest)
                if buf:
                    # Client bytes already read past the attach request are the start of the
                    # stream (stdin); forward them rather than silently dropping them.
                    up.sendall(buf)
                print("UPGRADE %s %s (101)" % (method, path), file=sys.stderr)
                _pump_both(conn, up)
                return
```

In the chunked branch, change

```python
                conn.sendall(rhead + b"\r\n\r\n")
                _relay_chunked(conn, up, rrest)
                return
```

to

```python
                conn.sendall(rhead + b"\r\n\r\n")
                _relay_chunked(conn, up, rrest)
                if attach:
                    print("DENY-FOLLOWUP %s %s (attach answered %s, not upgraded; connection "
                          "closed)" % (method, path, status), file=sys.stderr)
                return
```

and change the final line of the Content-Length path

```python
            conn.sendall(rhead + b"\r\n\r\n" + rrest[:rclen])
```

to

```python
            conn.sendall(rhead + b"\r\n\r\n" + rrest[:rclen])
            if attach:
                print("DENY-FOLLOWUP %s %s (attach answered %s, not upgraded; connection "
                      "closed)" % (method, path, status), file=sys.stderr)
                return
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 docker-create-proxy.test.py 2>&1 | tail -2` → `OK` (all existing tests plus `TestAttachHelpers` and `TestAttachPassThrough`). Run `TestAttachPassThrough` 10 times in a loop and confirm 10/10 OK (socket tests must not be flaky): `for i in $(seq 10); do python3 docker-create-proxy.test.py TestAttachPassThrough 2>&1 | tail -1; done`.
From the repo root: `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `31/31`; `python3 infra/hermes-agent/bin/proxy-policy-sync.test.py 2>&1 | tail -2` → `OK`.

- [ ] **Step 6: Firing control (scratch copies only)**

Copy `docker-create-proxy.py` and `docker-create-proxy.test.py` (and anything the test loads by path from `bin/`) into `$(mktemp -d)`. In the COPY of the proxy, restore the old behaviour by changing `if attach and status == 101:` to `if "/attach" in path:`. Run the copy's `TestAttachPassThrough` 5 times: expect routes a, b, c and the 200/garbled/chunked tests to FAIL every time. Record the commands and counts in the report. Never edit the tracked files for this.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(printf 'fix(hermes): F18 — pass through only for an attach dockerd upgraded; else relay and close\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 3: Measure the real attach on Linux CI

**Files:**
- Modify: `infra/hermes-agent/deploy/bind-agreement-integration.test.py` (a module constant after `CREATE_DENIED`; one assertion in `test_the_broker_path_reaches_the_executor_and_the_kill_switch_refuses`)

**Interfaces:**
- Consumes: the `UPGRADE POST <path> (101)` log line (Task 2).

This file cannot run on darwin (root + Linux + Docker); its proof is the required CI job.

- [ ] **Step 1: Add the assertion**

After `CREATE_DENIED = re.compile(...)`, add:

```python
# F18: the real Compose attach is answered 101 and goes through the upgraded pass-through.
ATTACH_UPGRADED = re.compile(r"UPGRADE POST /v[0-9.]+/containers/[^ ]+/attach[^ ]* \(101\)")
```

In `test_the_broker_path_reaches_the_executor_and_the_kill_switch_refuses`, directly after `self.assertRegex(plog, CREATE_ALLOWED, …)`, add:

```python
        # F18, MEASURED: real attach traffic is answered 101 and streams through the fixed
        # path — the executor's "mutation is disabled" below only reaches us through it.
        self.assertRegex(plog, ATTACH_UPGRADED, "proxy log:\n%s\nwrapper:\n%s" % (plog, out))
```

- [ ] **Step 2: Check syntax and the local skip**

Run (repo root): `python3 -m py_compile infra/hermes-agent/deploy/bind-agreement-integration.test.py && python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py 2>&1 | tail -2` → compiles; reports not runnable here, exit 0. Also `grep -c "    def test_" infra/hermes-agent/deploy/bind-agreement-integration.test.py` → `6` (no test added or removed).

- [ ] **Step 3: Commit (no push — the controller pushes and reads CI)**

```bash
git add infra/hermes-agent/deploy/bind-agreement-integration.test.py
git commit -m "$(printf 'test(hermes): F18 — measure the upgraded attach on real Linux\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

- [ ] **Step 4 (controller): push, PR, read CI counts**

```bash
git push -u origin spec/f18-attach-pass-through
gh pr create --base main --title "fix(hermes): F18 — pass through only for an attach dockerd upgraded" --body "$(cat <<'BODY'
## Summary
F18: the Docker proxy switched a connection to raw pass-through whenever `/attach` appeared anywhere in an allowed request's target (query string included) — before dockerd had answered — and never inspected that connection again. Now attach is defined once (`_ATTACH_RE`, POST, query stripped, fullmatch), `_handle` reads dockerd's response head first, and only an attach answered exactly `101` is passed through (forwarding already-read client bytes); any other answer to an attach is relayed and the connection closed. Non-attach requests are unchanged. F19 (attach may target any container) is recorded, not fixed.

Spec: `docs/superpowers/specs/2026-09-23-f18-attach-pass-through-design.md`. Plan: `docs/superpowers/plans/2026-09-24-f18-attach-pass-through.md`. Allow-list contents unchanged; mutation disabled; kill switch absent.

## Test plan
- [x] TestAttachHelpers + TestAttachPassThrough (keep-alive fake upstream; all three routes let a smuggled create through before the fix and not after), all proxy tests, hermes bin 31/31
- [ ] CI: bind-agreement executed 6 skipped 0, including the new `UPGRADE POST …/attach… (101)` measurement; layout-integration 30/0 — on the PR and the merge commit
- [ ] Records (F18 fixed, F19 recorded, BRING-UP gate + rollout note) — follow-up commit on this PR

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
gh pr checks <PR> --watch
gh run view <run-id> --log | grep -oE "(bind-agreement|layout-integration): executed [0-9]+, skipped [0-9]+, failures [0-9]+, errors [0-9]+|[0-9]+/[0-9]+ suites passed" | sort -u
```

Expected: `bind-agreement: executed 6, skipped 0, failures 0, errors 0` · `layout-integration: executed 30, skipped 0` · `22/22` · `31/31`. **If the `ATTACH_UPGRADED` assertion fails, that is the finding** — read the proxy log in the failure output (a `DENY-FOLLOWUP … (attach answered 200 …)` means real Compose attach is not 101) before changing anything; never widen pass-through to make CI pass.

---

### Task 4: Records

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (F18 section heading + a fix paragraph; new F19 section after F18; the `**Still open:**` line; open-items list)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (the kill-switch gate line; a rollout note directly after the §6 part A rollout block)

- [ ] **Step 1: Findings record — F18 fixed**

Retitle `### F18: the proxy's attach pass-through skips inspection for the rest of the connection (recorded, not fixed)` to `### F18: the proxy's attach pass-through skips inspection for the rest of the connection — fixed (PR #<n>)` and append to the section:

```markdown
**Fix (PR #<n>, spec `2026-09-23-f18-attach-pass-through-design.md`).** Attach is defined once
(`_ATTACH_RE`, used by both the allow-list and `_is_attach`: POST, query string stripped,
fullmatch). `_handle` now reads dockerd's response head before deciding: only an attach answered
exactly `101` is passed through (forwarding the 101 head, any stream bytes read with it, and any
client bytes already read past the request); any other answer to an attach is relayed and the
connection closed; non-attach requests are unchanged. Tested with a keep-alive fake upstream (all
three routes let a smuggled create through before the fix and not after). **Measured on Linux CI**
(run <id>): the real Compose attach is logged `UPGRADE POST …/attach… (101)`.
```

- [ ] **Step 2: Findings record — F19 recorded**

Directly after the F18 section (before `## Final state of the box`), add:

```markdown
### F19: attach may target any container (recorded, not fixed)

**Found 2026-09-23 while designing the F18 fix.** The allow-list's attach entry matches any
container id (`_ID = [A-Za-z0-9_.-]+`), so the broker — the adversary the proxy exists to contain —
can `POST /containers/<id>/attach` to **any** container, including the Hermes gateway, and with
`stdin=1` write to its input once dockerd upgrades the connection. Unlike F18 this is not a parsing
or pass-through defect; it is a policy gap in `decide()`. Closing it needs a way for the proxy to
know which container ids are ads-mutator runs (not measured). **Whether it gates the kill switch is
assessed in its own cycle; it is listed as a gate until then.**
```

Replace the open-items entry `7. F18: the attach pass-through bypass. Gates the kill switch.` with:

```markdown
7. F18: the attach pass-through bypass — fixed (PR #<n>).
8. F19: attach may target any container. Listed as a kill-switch gate until assessed.
```

Replace the `**Still open:**` line's first sentence `audit-log truncation (§6 part B) and F18 (the attach pass-through bypass).` with `audit-log truncation (§6 part B) and F19 (attach may target any container; to be assessed). F18 is fixed (PR #<n>).` — keep the rest of that paragraph unchanged.

- [ ] **Step 3: BRING-UP**

Change the gate sentence `**Still required before the kill switch can be created:** audit-log truncation (§6 part B) and F18 — the proxy's attach pass-through, which after one allowed request stops inspecting the connection (findings record).` to:

```markdown
**Still required before the kill switch can be created:** audit-log truncation (§6 part B), and
F19 — attach may target any container — until it is assessed (findings record).
```

Keep the F14 parenthetical that follows it. Directly after the §6 part A rollout block's closing paragraph (the one ending `…identify the client and the header before touching the grammar.`), add:

````markdown
**After pulling F18** — no unit changes; the proxy runs its script from the repo:

```bash
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
systemctl is-active hermes-docker-proxy hermes-broker
```

Then re-run Phase 6: besides `rc=2` and `ALLOW POST …/containers/create`, the proxy journal must
show `UPGRADE POST /v…/containers/…/attach… (101)`. A `DENY-FOLLOWUP` for the real attach is a
finding (the rail failed closed) — understand it before changing anything.
````

- [ ] **Step 4: Verify and commit**

Fill `<n>` and `<id>` **only** from the real PR number and CI run (Task 3 Step 4). Then:
`python3 infra/hermes-agent/bin/proxy-policy-sync.test.py 2>&1 | tail -2` → `OK`; `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `31/31`; `grep -n "F18" infra/hermes-agent/deploy/BRING-UP.md` → only the rollout note's heading line.

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md infra/hermes-agent/deploy/BRING-UP.md
git commit -m "$(printf 'docs(hermes): F18 fixed and measured; F19 recorded as a kill-switch gate\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

- [ ] **Step 5 (controller):** push; re-read CI counts on the new head; `brain-capture` a `[decision]` (F18 fixed, PR, run id, `UPGRADE (101)` measured; F19 recorded); after the operator merges, read CI counts on the merge commit.
