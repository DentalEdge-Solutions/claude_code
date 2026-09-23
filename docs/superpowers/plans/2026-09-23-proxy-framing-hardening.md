# Proxy framing hardening + UMask=0077 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Docker proxy refuses any request head it cannot parse unambiguously, so it and dockerd can never disagree about where a request ends; both units run with `UMask=0077`.

**Architecture:** A new pure function `_parse_head(head)` in `docker-create-proxy.py` enforces a strict grammar over the request line and header block and raises `HeadRefused(reason)` on any violation; `_handle` calls it first and closes the connection on refusal. Everything after parsing (`decide()`, body read, verbatim forward, response relay) is unchanged. `UMask=0077` is added to both systemd units.

**Tech Stack:** Python 3 stdlib (`re`, `unittest`), systemd unit files, Docker Compose on Linux CI.

**Spec:** `docs/superpowers/specs/2026-09-23-proxy-framing-hardening-design.md`

## Global Constraints

- **Mutation stays disabled. The kill switch is ABSENT and nothing in this plan creates it.**
- **Do not widen the proxy allow-list.** `decide()`, `configure()`, the `--allow-bind` set and the pinned values are untouched.
- **NEVER run `docker compose config`.** Never read or print `.env*`.
- **Never edit a tracked file to run a mutation test.** Controls are in-memory (a copied string, a patched value) or on a fixture's temp copy.
- **Stage by explicit path only.** Never `git add -A`, `.`, `commit -a`, `.project-brain/`, `evals/`, `CLAUDE.md`. The working tree carries unrelated operator changes.
- Refusal reasons, exact and fixed (never containing request bytes): `malformed request` · `malformed request line` · `malformed header line` · `duplicate Content-Length` · `malformed Content-Length` · `Transfer-Encoding is not permitted on requests`.
- Request version: exactly `HTTP/1.1`. Method: token `[!#$%&'*+.^_`|~0-9A-Za-z-]+`. Target: `[\x21-\x7e]+`. Header value (after stripping SP/HTAB): `[\t\x20-\x7e]*`.
- Log line on refusal: `DENY <method> <path> (<reason>)`, or `DENY - - (<reason>)` when the request line did not parse.
- `UMask=0077` on both `hermes-docker-proxy.service` and `hermes-broker.service`, in `[Service]`.
- Required CI job names are gates: **do not rename** `Bind agreement (root, Linux, real proxy)` or `Test suites (node + hermes bin)`. Read `executed N, skipped M` on the PR and on the merge commit.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Real Docker CLI / Compose traffic the grammar might refuse** (a non-ASCII `User-Agent`, `HTTP/1.0`, an unusual header). Only real clients settle it: Linux CI's bind-agreement job and the box's Phase 6 run. Task 1 pins the realistic heads that must pass (`test_real_client_heads_are_accepted`).
2. **A colon inside a header value** (`Host: localhost:2375`) must be accepted — only the first colon separates name from value. Pinned in Task 1 (`test_a_colon_in_the_value_is_accepted`).
3. **An empty header value** (`X-Empty:`) must be accepted, as Go accepts it. Pinned in Task 1 (`test_an_empty_value_is_accepted`).
4. **Whitespace around a Content-Length value** (`Content-Length:  5 `) is optional whitespace, not part of the value — must parse as 5. Pinned in Task 1 (`test_content_length_with_surrounding_whitespace_is_accepted`).
5. **A refused head mid-connection** must close the connection so a following request on it never reaches the upstream. Pinned in Task 2 (`test_a_refused_head_closes_the_connection`).

---

### Task 1: `_parse_head` — the strict grammar, as a pure function

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (add constants and `HeadRefused` / `_parse_head` directly after `MAX_BODY = 1024 * 1024`, `:257`)
- Test: `infra/hermes-agent/bin/docker-create-proxy.test.py` (new class `TestParseHead`, inserted directly before `class TestPlumbing(unittest.TestCase):`, `:305`)

**Interfaces:**
- Produces: `class HeadRefused(ValueError)` with attributes `.reason: str`, `.method: str` (default `"-"`), `.path: str` (default `"-"`); `def _parse_head(head: bytes) -> tuple[str, str, int]` returning `(method, path, content_length)`, `content_length` 0 when absent. Task 2 consumes both.

- [ ] **Step 1: Write the failing tests**

Insert before `class TestPlumbing(unittest.TestCase):`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run (from `infra/hermes-agent/bin`): `python3 docker-create-proxy.test.py TestParseHead -v 2>&1 | tail -8`
Expected: every test ERRORs with `AttributeError: module 'docker_create_proxy' has no attribute '_parse_head'` (or `HeadRefused`).

- [ ] **Step 3: Implement**

In `docker-create-proxy.py`, directly after `MAX_BODY = 1024 * 1024`, add:

```python


# ---- The framing hardening (spec 2026-09-23) -------------------------------------------
# This proxy forwards the ORIGINAL header block verbatim to dockerd, so its safety rests on
# one invariant: it and dockerd always agree where a request ends. Every head is therefore
# parsed ONCE, here, against a strict grammar, and anything not parseable unambiguously is
# refused — instead of depending on dockerd (Go net/http) being stricter than this file.
# Forms this closes (measurement plan 2026-09-17 §1): obs-fold continuation lines, a space
# before the colon, duplicate Content-Length, and (inferred, not measured) a bare LF, which
# Go's textproto treats as a line end while a split on CRLF does not.
_TOKEN_RE = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_TARGET_RE = re.compile(rb"[\x21-\x7e]+")
_VALUE_RE = re.compile(rb"[\t\x20-\x7e]*")
_DIGITS_RE = re.compile(rb"[0-9]+")


class HeadRefused(ValueError):
    """A request head this proxy will not forward. `reason` is one of a FIXED set of strings
    and never contains request bytes (it goes to the client and to the journal)."""

    def __init__(self, reason, method="-", path="-"):
        super().__init__(reason)
        self.reason = reason
        self.method = method
        self.path = path


def _parse_head(head):
    """(method, path, content_length) for a head that parses unambiguously, else raise
    HeadRefused. `head` is the bytes before the first CRLFCRLF."""
    lines = head.split(b"\r\n")
    for line in lines:
        if b"\r" in line or b"\n" in line or b"\x00" in line:
            raise HeadRefused("malformed request")
    parts = lines[0].split(b" ")
    if (len(parts) != 3 or not _TOKEN_RE.fullmatch(parts[0])
            or not _TARGET_RE.fullmatch(parts[1]) or parts[2] != b"HTTP/1.1"):
        raise HeadRefused("malformed request line")
    method, path = parts[0].decode("ascii"), parts[1].decode("ascii")
    clen = None
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        # The name must be a bare token that STARTS the line and is followed IMMEDIATELY by
        # ':'. An obs-fold line (leading SP/HTAB) and "Name : v" both fail here.
        if not sep or not _TOKEN_RE.fullmatch(name):
            raise HeadRefused("malformed header line", method, path)
        value = value.strip(b" \t")
        if not _VALUE_RE.fullmatch(value):
            raise HeadRefused("malformed header line", method, path)
        lname = name.lower()
        if lname == b"transfer-encoding":
            # <MOVE HERE, verbatim, the "CL.TE / TE.CL REQUEST SMUGGLING" comment block
            #  from _handle (it begins "# CL.TE / TE.CL REQUEST SMUGGLING. This proxy frames
            #  every request by Content-Length alone"). Task 2 deletes it from _handle.>
            raise HeadRefused("Transfer-Encoding is not permitted on requests", method, path)
        if lname == b"content-length":
            if clen is not None:
                # Refused even when both values agree: keeping one silently is exactly the
                # "which one wins" question this proxy must never answer differently from
                # dockerd.
                raise HeadRefused("duplicate Content-Length", method, path)
            # <MOVE HERE, verbatim, the "DIGITS ONLY. RFC 9110 defines Content-Length as
            #  1*DIGIT..." comment block from _handle. Task 2 deletes it from _handle.>
            if not _DIGITS_RE.fullmatch(value):
                raise HeadRefused("malformed Content-Length", method, path)
            clen = int(value)
    return method, path, (clen or 0)
```

The two `<MOVE HERE …>` markers are instructions, not code: in this task, **copy** the two named comment blocks from `_handle` (they sit above `if not h.split(b":", 1)[1].strip().isdigit():` and above `if has_te:`) into those positions, as `#` comments indented to match. Task 2 removes the originals. No marker text may remain in the file.

- [ ] **Step 4: Run to verify they pass, and nothing else broke**

Run: `python3 docker-create-proxy.test.py 2>&1 | tail -3`
Expected: `OK` — the 40 existing tests plus the new `TestParseHead` tests (`_handle` is untouched in this task). Then `grep -n "MOVE HERE" docker-create-proxy.py` → no output.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(printf 'fix(hermes): framing hardening — _parse_head, a strict request-head grammar\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 2: `_handle` refuses what `_parse_head` refuses

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (`_handle`, the block from `line = head.split(b"\r\n")[0].decode("latin1")` through the end of the `if bad_clen:` branch, `:352-414`)
- Test: `infra/hermes-agent/bin/docker-create-proxy.test.py` (`TestPlumbing`, new tests after `test_a_content_length_only_python_accepts_is_refused`)

**Interfaces:**
- Consumes: `HeadRefused` (`.reason`, `.method`, `.path`) and `_parse_head(head) -> (method, path, content_length)` from Task 1.

- [ ] **Step 1: Write the failing tests**

Append inside `class TestPlumbing`, after the last existing test method:

```python
    # ---- the framing hardening, end to end (spec 2026-09-23) ---------------------------
    # Each form carries a privileged create hidden in an allowed `wait` request. The proof is
    # NON-RECEIPT: `/containers/create` must appear nowhere in the upstream's raw bytes.

    SMUGGLED = (b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 2\r\n\r\n{}")
    WAIT = b"POST /v1.55/containers/deadbeef/wait?condition=removed HTTP/1.1\r\n"

    def _assert_smuggle_refused(self, req, reason):
        resp = self._send(req)
        self.assertIn(b"403", resp)
        self.assertIn(reason.encode(), resp)
        self.assertFalse(any(b"/containers/create" in b for b in self.upstream_raw),
                         "smuggled create reached the upstream socket: %r" % self.upstream_raw)

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
        self.assertTrue(any(l.startswith("POST /v1.55/containers/deadbeef/wait")
                            for l in self.upstream_saw), self.upstream_saw)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 docker-create-proxy.test.py TestPlumbing -v 2>&1 | tail -15`
Expected: the four `*_smuggled_create_is_refused` tests FAIL on the non-receipt assertion (`smuggled create reached the upstream socket`) — forms 1–3 as measured on 2026-09-17, form 4 as inferred; record in the report exactly which failed and how. `test_a_refused_head_closes_the_connection` FAILS (today `HTTP/1.0` is forwarded). `test_ordinary_heads_still_reach_upstream` PASSES.

- [ ] **Step 3: Implement**

In `_handle`, replace the whole block from `line = head.split(b"\r\n")[0].decode("latin1")` down to and including the `if bad_clen:` branch's `return` (the line after `print("DENY %s %s (malformed Content-Length)" ...)`) with:

```python
            # The framing hardening (spec 2026-09-23): the head is parsed ONCE, strictly,
            # by _parse_head, and anything it cannot parse unambiguously is refused. Close,
            # do not continue the loop: after an unparseable head there is no safe place to
            # resume reading. The reason is a fixed string; refused bytes never reach the
            # journal (method/path are logged only when the request line itself parsed).
            try:
                method, path, clen = _parse_head(head)
            except HeadRefused as e:
                _refuse(conn, e.reason)
                print("DENY %s %s (%s)" % (e.method, e.path, e.reason), file=sys.stderr)
                return
```

Keep everything from the `# Substring, not the regex fullmatch the rest of the file uses` comment and `is_create = "/containers/create" in path` onward exactly as it is. The two long comment blocks that stood in the removed region now live in `_parse_head` (Task 1) — confirm with `grep -c "CL.TE / TE.CL REQUEST SMUGGLING" docker-create-proxy.py` → `1` and `grep -c "DIGITS ONLY. RFC 9110" docker-create-proxy.py` → `1`.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 docker-create-proxy.test.py 2>&1 | tail -3` → `OK` (all existing tests unchanged, including `test_a_malformed_content_length_is_refused_not_crashed`, the three CL.TE tests and the positive control).
Then from the repo root: `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `hermes bin: 31/31 suites passed`; `python3 infra/hermes-agent/bin/proxy-policy-sync.test.py 2>&1 | tail -2` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(printf 'fix(hermes): framing hardening — _handle refuses any head _parse_head refuses\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 3: `UMask=0077` on both units

**Files:**
- Modify: `infra/hermes-agent/deploy/hermes-docker-proxy.service` (after `Type=simple` in `[Service]`, `:7`)
- Modify: `infra/hermes-agent/deploy/hermes-broker.service` (after `Type=simple` in `[Service]`, `:7`)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (comment above `os.chmod(listen, 0o660)` in `serve()`)
- Test: `infra/hermes-agent/deploy/units.test.py` (new class before `class TestSpoolPathContract`)

**Interfaces:** none consumed or produced in code.

- [ ] **Step 1: Write the failing tests**

Insert before `class TestSpoolPathContract(unittest.TestCase):`:

```python
class TestUMask(unittest.TestCase):
    """The §6 hardening (spec 2026-09-23 §3.3): both units run with UMask=0077, in [Service].
    systemd applies it only there; a UMask in [Unit] or [Install] is ignored silently."""

    @staticmethod
    def _service_umasks(body):
        section, found = None, []
        for line in live_lines(body):
            if line.startswith("[") and line.endswith("]"):
                section = line
            elif line.startswith("UMask="):
                found.append((section, line))
        return found

    def test_both_units_set_umask_0077_in_service(self):
        for name in ("hermes-docker-proxy.service", "hermes-broker.service"):
            self.assertEqual(self._service_umasks(unit(name)),
                             [("[Service]", "UMask=0077")], name)

    def test_control_a_unit_without_the_line_fails(self):
        body = unit("hermes-docker-proxy.service")
        stripped = "\n".join(l for l in body.splitlines() if not l.strip().startswith("UMask="))
        self.assertNotEqual(self._service_umasks(stripped), [("[Service]", "UMask=0077")])

    def test_control_a_umask_in_the_wrong_section_fails(self):
        body = "[Unit]\nUMask=0077\n[Service]\nType=simple\n"
        self.assertNotEqual(self._service_umasks(body), [("[Service]", "UMask=0077")])
```

- [ ] **Step 2: Run to verify it fails**

Run (repo root): `python3 infra/hermes-agent/deploy/units.test.py TestUMask -v 2>&1 | tail -6`
Expected: `test_both_units_set_umask_0077_in_service` FAILS (`[] != [('[Service]', 'UMask=0077')]`); both controls PASS.

- [ ] **Step 3: Implement**

In both unit files, directly after `Type=simple`, insert:

```ini
# §6 hardening (spec 2026-09-23 §3.3): files and sockets this unit creates start private.
# Everything shared is given its mode explicitly (the proxy's socket by chmod in serve();
# approvals, records and spool files by fchmod on the fd — F10a, F12).
UMask=0077
```

In `docker-create-proxy.py`'s `serve()`, directly above `os.chmod(listen, 0o660)`, add:

```python
    # Under the unit's UMask=0077 the socket is created 0600; this chmod is what opens it to
    # the hermes-rail group. Containment no longer rests only on RuntimeDirectoryMode=0750 —
    # the socket is private from the instant it exists (2026-09-17 handoff §6).
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 infra/hermes-agent/deploy/units.test.py 2>&1 | tail -2` → `OK`; `python3 infra/hermes-agent/bin/docker-create-proxy.test.py 2>&1 | tail -2` → `OK`; `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `31/31`; `node scripts/run-all-tests.js 2>&1 | tail -1` → `22/22`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/deploy/hermes-docker-proxy.service infra/hermes-agent/deploy/hermes-broker.service \
  infra/hermes-agent/deploy/units.test.py infra/hermes-agent/bin/docker-create-proxy.py
git commit -m "$(printf 'fix(hermes): UMask=0077 on the proxy and broker units\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 4: Linux CI — the real client through the stricter proxy

**Files:** none changed. The existing required job `Bind agreement (root, Linux, real proxy)` runs the real Compose client through the real proxy and must still get `ALLOW POST …/containers/create`.

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin spec/proxy-framing-hardening
gh pr create --base main --title "fix(hermes): proxy framing hardening + UMask=0077 (section 6 part A)" --body "$(cat <<'BODY'
## Summary
Section 6 part A of the 2026-09-17 handoff: the Docker proxy now parses every request head once, strictly (`_parse_head`), and refuses anything it cannot parse unambiguously — obs-fold, a space before the colon, duplicate Content-Length, and a bare LF/CR/NUL (the last inferred, not measured). The header block is still forwarded verbatim, but only after passing the grammar. Both units get `UMask=0077`.

Spec: `docs/superpowers/specs/2026-09-23-proxy-framing-hardening-design.md`. Plan: `docs/superpowers/plans/2026-09-23-proxy-framing-hardening.md`. Hardened without the VPS framing measurement, as the measurement plan's §6 allows. Allow-list unchanged; mutation disabled; kill switch absent.

## Test plan
- [x] docker-create-proxy tests (existing 40 + TestParseHead + four end-to-end smuggling forms), units.test.py, hermes bin 31/31, node 22/22
- [ ] CI: bind-agreement executed 6 skipped 0 with ALLOW on create; layout-integration executed 30 skipped 0 — on the PR and the merge commit
- [ ] Box: UMask=0077 on both units, socket 660, Phase 6 create ALLOW (operator, after merge)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

- [ ] **Step 2: Read the counts, not the colours**

```bash
gh pr checks <PR> --watch
gh run view <run-id> --log | grep -oE "(bind-agreement|layout-integration): executed [0-9]+, skipped [0-9]+, failures [0-9]+, errors [0-9]+|[0-9]+/[0-9]+ suites passed" | sort -u
```

Expected: `bind-agreement: executed 6, skipped 0, failures 0, errors 0` · `layout-integration: executed 30, skipped 0, …` · `22/22` · `31/31`.
**If bind-agreement fails with a `DENY … (malformed …)` in the proxy log: that is the finding** (Review Focus 1). Read which header the real client sent before changing anything; never loosen the grammar to make CI pass.

---

### Task 5: Records and the box rollout block

**Files:**
- Modify: `docs/evaluations/2026-09-17-f3-framing-disagreement-measurement-plan.md` (§1 table, §7)
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (the `**Still open:** the §6 hardening gates, including \`UMask=0077\`` line, `:256`)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (rehearsal-gate "Still required" paragraph; new rollout block)

- [ ] **Step 1: Measurement plan**

Append a row to §1's table:

```markdown
| 4 | `X-Pad: a\nTransfer-Encoding: chunked` (bare LF) | a split on CRLF sees one header; Go's textproto treats bare LF as a line end | **inferred 2026-09-23, not measured** |
```

Append at the end of §7:

```markdown
**Applied 2026-09-23 (PR #<n>), without the §5 measurement, as §6 allows.** `_parse_head`
enforces all three rules above plus a fourth — no bare CR, LF or NUL anywhere in the head
(form 4) — and also requires exactly `HTTP/1.1` and printable-ASCII header values. The positive
control was re-run on Linux CI (run <id>: `bind-agreement: executed 6, skipped 0`, `ALLOW` on
create). §5 stays blank: the measurement is now informative, not a prerequisite.
```

- [ ] **Step 2: Findings record**

Replace the line beginning `**Still open:** the §6 hardening gates, including \`UMask=0077\`` (keep any trailing clause of that paragraph that is still true) so it reads:

```markdown
**Still open:** audit-log truncation (§6 part B). The framing hardening and `UMask=0077` (§6
part A) landed in PR #<n>.
```

- [ ] **Step 3: BRING-UP**

Change `**Still required before the kill switch can be created:** the §6 hardening gates.` (keep the parenthetical about F14 that follows it) to:

```markdown
**Still required before the kill switch can be created:** audit-log truncation (§6 part B).
```

Directly after that paragraph, add:

````markdown
**After pulling the framing hardening (§6 part A), re-install both units** — they are copied into
`/etc/systemd/system/`, so a pull alone does not apply `UMask=0077`:

```bash
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-docker-proxy.service /etc/systemd/system/
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-broker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
sudo systemctl restart hermes-broker
systemctl show -p UMask hermes-docker-proxy hermes-broker          # UMask=0077, both
sudo stat -c '%U:%G %a %n' /run/hermes/docker-proxy.sock           # hermes-docker-proxy:hermes-rail 660
systemctl is-active hermes-docker-proxy hermes-broker              # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker      # not climbing
```

Then re-run Phase 6's pasted create: `rc=2`, `mutation is disabled`, and `ALLOW POST
/v…/containers/create` in `journalctl -u hermes-docker-proxy`. A `DENY … (malformed …)` there is
a finding — identify the client and the header before touching the grammar.
````

- [ ] **Step 4: Verify and commit**

Fill `<n>` and `<id>` **only** from the real PR number and CI run (Task 4). Then:
`python3 infra/hermes-agent/bin/proxy-policy-sync.test.py 2>&1 | tail -2` → `OK` (it reads BRING-UP's Phase 6 block, which this task does not touch); `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -1` → `31/31`.

```bash
git add docs/evaluations/2026-09-17-f3-framing-disagreement-measurement-plan.md \
  docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md infra/hermes-agent/deploy/BRING-UP.md
git commit -m "$(printf 'docs(hermes): record the framing hardening and the UMask rollout\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
git push
```

Re-read CI counts on the new head (Task 4 Step 2).

- [ ] **Step 5: Brain candidate (controller, unpromoted)**

`brain-capture` a `[decision]`: the framing hardening + `UMask=0077` landed (PR #<n>, CI run <id>); hardened without the VPS measurement; kill switch now gated only by §6 part B (audit-log truncation). Nothing under `.project-brain/` is staged.

- [ ] **Step 6: After the operator merges — the merge commit**

```bash
git checkout main && git pull --ff-only
gh run view <merge-run-id> --log | grep -oE "(bind-agreement|layout-integration): executed [0-9]+, skipped [0-9]+|[0-9]+/[0-9]+ suites passed" | sort -u
```

Expected: the same counts as on the PR.
