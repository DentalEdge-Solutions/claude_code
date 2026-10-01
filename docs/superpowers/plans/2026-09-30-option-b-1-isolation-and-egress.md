# Option B, part 1 — Isolation and egress: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Client data leaves the gateway, and the Opus draft runs in a per-client one-shot `ads-drafter` container that can reach only `api.anthropic.com`. It still runs as `sudo run-client-audit <client>`, which gains `--json` and `--list`.

**Architecture:** Vaults, reports and the transient draft move from `/opt/hermes-agent/data/` to `/var/lib/hermes/{vaults,reports,draft-out}/<client>/`, which no long-running container mounts.
- `run-client-audit.py` stops `exec`ing into the gateway. It starts an allow-list CONNECT proxy (`egress-proxy`) on an `internal` Docker network and runs `ads-drafter` there, with that client's vault and reports read-only, one writable output dir, and the Anthropic key per run from `/etc/hermes/.env.anthropic`.
- A migration script moves the existing vaults, and two small operator tools arrive: `install-env-secret.py` and `show-audit`.

**Tech Stack:** Python 3 stdlib only (`infra/hermes-agent/bin/`), Docker Compose (`tools` profile), POSIX sh wrappers, GitHub Actions (the existing "Bind agreement" job).

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` (§4, §5, §6, §7, §9, §10 PR 1). Parts 2 and 3 are `2026-09-30-option-b-2-chat-trigger.md` and `2026-09-30-option-b-3-review-tooling.md`.

## Global Constraints

- **Code:** Python stdlib only in `infra/hermes-agent/bin/`. Tests are `bin/<name>.test.py` (unittest), discovered by `infra/hermes-agent/bin/run-bin-tests.sh`, which must end `N/N suites passed` after every task.
- **Box paths:**
  - `VAULTS=/var/lib/hermes/vaults`, `REPORTS=/var/lib/hermes/reports`, `DRAFT_OUT=/var/lib/hermes/draft-out`;
  - each parent is `root:root 0711`; each `<client>/` below it is uid 10000, `0700`;
  - `AUDIT_DATA` and `AUDIT_LOGS` are unchanged.
- **Anthropic key:** `/etc/hermes/.env.anthropic`, `root:root 0400`, one line `ANTHROPIC_API_KEY=sk-ant-…`. It reaches only `ads-drafter`, as `-e ANTHROPIC_API_KEY` (the value in the compose client's env, never in argv). The gateway `.env` no longer needs a real Anthropic key for audits.
- **Google credential:** it reaches only `ads-collector` and `ads-reader`, exactly as today.
- **Egress:** the drafter sits only on network `drafter-net` (`internal: true`). `egress-proxy` allows exactly `api.anthropic.com:443`.
- **Never print, log or commit a customer id or credential value.** Screen output goes through `review_lib.Redactor`, as today.
- **Timeouts (seconds):** collect 900, snapshot 120, read 300, proxy 60, draft 1200, vault-write 120.
- **Exit codes of `run-client-audit`:** 0 ok, 1 a step failed, 2 a pre-check refused, 3 another audit is running.
- **Draft invocation:** the analyst prompt, model (`claude-opus-4-8`), `--permission-mode plan` and `--allowedTools "Read,Grep,Glob"` are unchanged except for the mount paths.
- **Unchanged:** the laptop's `run-trend-audit.sh`, `collect-audit-data.sh` and `run-audit-bundle.sh`. `vault_lib`'s default `VAULT_ROOT` stays `/opt/data/vaults`; box callers pass `VAULT_ROOT` explicitly.
- **`CHECKLIST.md` is not touched in this part.** Part 3 raises it to v1.11 once.

## Review Focus

1. **A container-planted symlink in `draft-out/<client>/` or `vaults/<client>/audits/`** (the drafter and vault-write run as uid 10000 and control those trees) must never be followed by root, for read or unlink. Task 4 pins it.
2. **The proxy must not be stopped only on success.** A drafter timeout, a failed isolation check or an exception must still stop `egress-proxy`. Task 4 tests every exit path.
3. **A missing or wrong-mode host parent** (`/var/lib/hermes/vaults` not `0711`, or not root-owned) must refuse before any container runs, not after a spend. Task 4 has the test.
4. **A `CONNECT` target with a trailing dot, mixed case, an IP literal or a bracketed IPv6 literal** must be decided exactly: `API.anthropic.com.:443` is allowed, `[::1]:443` and `1.2.3.4:443` are refused. Task 1 has the tests.
5. **`--json` must print exactly one JSON line on stdout on every exit path,** including a refused pre-check, a held lock and an unexpected exception. Human lines go to stderr. Task 5 tests each path.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/egress-proxy.py` | create | the stdlib CONNECT proxy with a host:port allow-list |
| `infra/hermes-agent/bin/egress-proxy.test.py` | create | its unit and loopback tests |
| `infra/hermes-agent/bin/client_audit_lib.py` | modify | `load_env_value`, `check_host_parent`, `check_client_dir`, `TS_RE`, `list_audit_ts` |
| `infra/hermes-agent/bin/client_audit_lib.test.py` | modify | tests for those |
| `infra/hermes-agent/docker-compose.yml` | modify | `ads-drafter`, `egress-proxy`, `drafter-net`; the `ads-reader` reports mount becomes per client |
| `infra/hermes-agent/deploy/audit-mounts-integration.test.py` | modify | the drafter's mounts, user and egress on real Docker |
| `infra/hermes-agent/bin/run-client-audit.py` | modify | new paths, the drafter step, the proxy lifecycle, the key file, `--json`, `--list` |
| `infra/hermes-agent/bin/run-client-audit.test.py` | modify | tests follow the new layout; new tests |
| `infra/hermes-agent/bin/install-env-secret.py` (+ `.test.py`) | create | installs or strips one `NAME=value` in an env file, validated and atomic, value read from a tty |
| `infra/hermes-agent/bin/migrate-client-data.py` (+ `.test.py`) | create | copy, verify, then remove `data/vaults` and `data/reports` |
| `infra/hermes-agent/bin/show-audit.py` (+ `.test.py`), `deploy/show-audit` | create | print a client's latest or named draft to the operator |
| `infra/hermes-agent/deploy/BRING-UP.md`, `infra/hermes-agent/README.md` | modify | the part-1 box steps and the path tables |

---

### Task 1: `egress-proxy.py`, an allow-list CONNECT proxy

**Files:**
- Create: `infra/hermes-agent/bin/egress-proxy.py`
- Test: `infra/hermes-agent/bin/egress-proxy.test.py`

**Interfaces:**
- Produces:
  - CLI `egress-proxy.py --listen HOST:PORT --allow HOST:PORT [--allow …]`;
  - module functions `parse_allow(values) -> frozenset[(str,int)]`, `decide(head: str, allow) -> (host, port)` (raises `Refused(reason)`), and `serve(listen, allow, log=sys.stderr) -> socketserver.ThreadingTCPServer`;
  - `reason` is one of `not-connect`, `bad-target`, `ip-literal`, `not-allowed`, `header-too-large`, `upstream-unreachable`.
  - The log line format is `egress-proxy: decision=<allow|deny> target=<host:port|invalid> reason=<r> up=<n> down=<n>`.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import importlib.util, io, os, socket, socketserver, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("egp", os.path.join(HERE, "egress-proxy.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

ALLOW = P.parse_allow(["api.anthropic.com:443"])


class TestDecide(unittest.TestCase):
    def head(self, line):
        return line + "\r\nHost: x\r\n"

    def test_allowed_host_exactly(self):
        self.assertEqual(P.decide(self.head("CONNECT api.anthropic.com:443 HTTP/1.1"), ALLOW),
                         ("api.anthropic.com", 443))

    def test_case_and_trailing_dot_normalised(self):
        self.assertEqual(P.decide(self.head("CONNECT API.Anthropic.com.:443 HTTP/1.1"), ALLOW),
                         ("api.anthropic.com", 443))

    def test_refusals(self):
        cases = {
            "GET http://api.anthropic.com/ HTTP/1.1": "not-connect",
            "CONNECT api.anthropic.com:80 HTTP/1.1": "not-allowed",
            "CONNECT example.com:443 HTTP/1.1": "not-allowed",
            "CONNECT evil.api.anthropic.com:443 HTTP/1.1": "not-allowed",
            "CONNECT 1.2.3.4:443 HTTP/1.1": "ip-literal",
            "CONNECT [::1]:443 HTTP/1.1": "ip-literal",
            "CONNECT api.anthropic.com HTTP/1.1": "bad-target",
            "CONNECT api.anthropic.com:44x HTTP/1.1": "bad-target",
            "CONNECT api.anthropic.com:443": "not-connect",
        }
        for line, reason in cases.items():
            with self.subTest(line=line):
                with self.assertRaises(P.Refused) as cm:
                    P.decide(self.head(line), ALLOW)
                self.assertEqual(cm.exception.reason, reason)

    def test_parse_allow_rejects_garbage(self):
        for bad in ("api.anthropic.com", ":443", "host:port"):
            with self.assertRaises(ValueError):
                P.parse_allow([bad])


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


class TestLoopback(unittest.TestCase):
    """A real proxy on 127.0.0.1 in front of a real echo server. 'localhost' is the allowed
    name, so the ip-literal rule is exercised on the refused path and not on the allowed one."""
    def setUp(self):
        self.echo = socketserver.TCPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=self.echo.serve_forever, daemon=True).start()
        self.eport = self.echo.server_address[1]
        self.log = io.StringIO()
        self.proxy = P.serve("127.0.0.1:0", P.parse_allow([f"localhost:{self.eport}"]), log=self.log)
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()
        self.pport = self.proxy.server_address[1]

    def tearDown(self):
        for s in (self.proxy, self.echo):
            s.shutdown(); s.server_close()

    def ask(self, line, then=b""):
        c = socket.create_connection(("127.0.0.1", self.pport), timeout=5)
        c.sendall(line.encode() + b"\r\nHost: x\r\n\r\n")
        status = c.recv(1024)
        body = b""
        if then:
            c.sendall(then); body = c.recv(1024)
        c.close()
        return status, body

    def test_allowed_tunnel_carries_bytes(self):
        status, body = self.ask(f"CONNECT localhost:{self.eport} HTTP/1.1", then=b"hi")
        self.assertTrue(status.startswith(b"HTTP/1.1 200"), status)
        self.assertEqual(body, b"echo:hi")

    def test_ip_literal_refused_403_and_logged_without_content(self):
        status, _ = self.ask(f"CONNECT 127.0.0.1:{self.eport} HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
        self.assertIn("decision=deny", self.log.getvalue())
        self.assertIn("reason=ip-literal", self.log.getvalue())

    def test_hostile_target_is_not_echoed_into_the_log(self):
        self.ask("CONNECT evil\x1b[31m.example:443 HTTP/1.1")
        self.assertNotIn("\x1b", self.log.getvalue())
        self.assertIn("target=invalid", self.log.getvalue())

    def test_oversized_header_refused(self):
        c = socket.create_connection(("127.0.0.1", self.pport), timeout=5)
        c.sendall(b"CONNECT localhost:1 HTTP/1.1\r\nX: " + b"a" * 9000)
        self.assertTrue(c.recv(1024).startswith(b"HTTP/1.1 403"))
        c.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/egress-proxy.test.py -v`
Expected: FAIL, since `egress-proxy.py` does not exist (`FileNotFoundError` from `spec_from_file_location`).

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""Allow-list HTTPS egress proxy for the ads-drafter (spec 2026-09-30 §5.2). Stdlib only.

  egress-proxy.py --listen 0.0.0.0:3128 --allow api.anthropic.com:443 [--allow host:port ...]

HTTP CONNECT to an allow-listed host:port is tunnelled; everything else gets 403 and the
connection closes. It never terminates TLS and never logs content: one line per decision
(target, decision, reason, byte counts). The drafter's network is `internal`, so this is
its only way out: no proxy, no draft."""
import argparse, ipaddress, re, select, socket, socketserver, sys

MAX_HEADER = 8192
IDLE_SECONDS = 300
_SAFE = re.compile(r"^[A-Za-z0-9.\-]{1,253}:[0-9]{1,5}$")


class Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_allow(values):
    out = set()
    for v in values:
        host, _, port = v.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"bad --allow value {v!r}: expected host:port")
        out.add((host.lower().rstrip("."), int(port)))
    return frozenset(out)


def _is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def decide(head, allow):
    parts = head.split("\r\n", 1)[0].split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or not parts[2].startswith("HTTP/1."):
        raise Refused("not-connect")
    target = parts[1]
    if target.startswith("[") and "]" in target:
        raise Refused("ip-literal")
    host, _, port = target.rpartition(":")
    if not host or not port.isdigit():
        raise Refused("bad-target")
    if _is_ip(host):
        raise Refused("ip-literal")
    key = (host.lower().rstrip("."), int(port))
    if key not in allow:
        raise Refused("not-allowed")
    return key


def _target_for_log(head):
    parts = head.split("\r\n", 1)[0].split(" ")
    t = parts[1] if len(parts) >= 2 else ""
    return t if _SAFE.match(t) else "invalid"


def _pump(a, b, first=b""):
    up = down = 0
    if first:
        b.sendall(first); up += len(first)
    socks = [a, b]
    while True:
        r, _, _ = select.select(socks, [], [], IDLE_SECONDS)
        if not r:
            return up, down
        for s in r:
            data = s.recv(65536)
            if not data:
                return up, down
            (b if s is a else a).sendall(data)
            if s is a:
                up += len(data)
            else:
                down += len(data)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        c, log = self.request, self.server.log
        c.settimeout(30)
        raw = b""
        try:
            while b"\r\n\r\n" not in raw:
                chunk = c.recv(4096)
                if not chunk:
                    return
                raw += chunk
                if len(raw) > MAX_HEADER:
                    raise Refused("header-too-large")
            head, rest = raw.split(b"\r\n\r\n", 1)
            text = head.decode("latin-1")
            host, port = decide(text, self.server.allow)
        except Refused as r:
            text = raw.split(b"\r\n", 1)[0].decode("latin-1")
            self._log("deny", _target_for_log(text), r.reason)
            c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        except OSError:
            return
        try:
            up = socket.create_connection((host, port), timeout=30)
        except OSError:
            self._log("deny", f"{host}:{port}", "upstream-unreachable")
            c.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        try:
            c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            c.settimeout(None); up.settimeout(None)
            n_up, n_down = _pump(c, up, rest)
            self._log("allow", f"{host}:{port}", "", n_up, n_down)
        finally:
            up.close()

    def _log(self, decision, target, reason, up=0, down=0):
        print(f"egress-proxy: decision={decision} target={target} reason={reason} up={up} down={down}",
              file=self.server.log, flush=True)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(listen, allow, log=sys.stderr):
    host, _, port = listen.rpartition(":")
    srv = _Server((host, int(port)), _Handler)
    srv.allow, srv.log = allow, log
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", required=True)
    ap.add_argument("--allow", action="append", required=True)
    a = ap.parse_args(argv)
    srv = serve(a.listen, parse_allow(a.allow))
    srv.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/egress-proxy.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole bin suite**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: ends `N/N suites passed`.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/egress-proxy.py infra/hermes-agent/bin/egress-proxy.test.py
git commit -m "feat(hermes): egress-proxy — allow-list CONNECT proxy for the drafter (Option B §5.2)"
```

---

### Task 2: `client_audit_lib` helpers for the new layout

**Files:**
- Modify: `infra/hermes-agent/bin/client_audit_lib.py` (append after `others_named`)
- Test: `infra/hermes-agent/bin/client_audit_lib.test.py` (append)

**Interfaces:**
- Produces:
  - `TS_RE` (compiled, `^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$`);
  - `load_env_value(path, name) -> str | None`;
  - `check_host_parent(path, uid=0, mode=0o711)`, which raises `PrecheckError`;
  - `check_client_dir(path, uid)`, which raises `PrecheckError`;
  - `list_audit_ts(dir_fd) -> list[str]`, sorted and regular files only.

- [ ] **Step 1: Write the failing tests** (append to `client_audit_lib.test.py`; it already imports `client_audit_lib as L`, `os`, `tempfile`, `unittest`. Add any that are missing.)

```python
class TestOptionBHelpers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_load_env_value_parses_as_data(self):
        p = os.path.join(self.d, "e")
        open(p, "w").write('export ANTHROPIC_API_KEY="sk-ant-x"\r\nOTHER=1\n')
        self.assertEqual(L.load_env_value(p, "ANTHROPIC_API_KEY"), "sk-ant-x")
        self.assertIsNone(L.load_env_value(p, "MISSING"))

    def test_check_host_parent(self):
        p = os.path.join(self.d, "vaults"); os.mkdir(p); os.chmod(p, 0o711)
        L.check_host_parent(p, uid=os.geteuid())                       # ok
        os.chmod(p, 0o755)
        with self.assertRaises(L.PrecheckError):
            L.check_host_parent(p, uid=os.geteuid())
        link = os.path.join(self.d, "link"); os.symlink(p, link)
        with self.assertRaises(L.PrecheckError):
            L.check_host_parent(link, uid=os.geteuid())
        with self.assertRaises(L.PrecheckError):
            L.check_host_parent(os.path.join(self.d, "absent"), uid=os.geteuid())

    def test_check_client_dir(self):
        p = os.path.join(self.d, "acme"); os.mkdir(p)
        L.check_client_dir(p, uid=os.geteuid())
        with self.assertRaises(L.PrecheckError):
            L.check_client_dir(p, uid=os.geteuid() + 1)
        link = os.path.join(self.d, "l"); os.symlink(p, link)
        with self.assertRaises(L.PrecheckError):
            L.check_client_dir(link, uid=os.geteuid())

    def test_list_audit_ts_regular_files_only(self):
        a = os.path.join(self.d, "audits"); os.mkdir(a)
        for n in ("2026-09-30_10-00-00-audit.md", "2026-10-01_09-00-00-audit.md", "notes.md"):
            open(os.path.join(a, n), "w").close()
        os.symlink("/etc/passwd", os.path.join(a, "2026-10-02_00-00-00-audit.md"))
        fd = os.open(a, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(L.list_audit_ts(fd), ["2026-09-30_10-00-00", "2026-10-01_09-00-00"])
        finally:
            os.close(fd)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py -v`
Expected: FAIL with `AttributeError: module 'client_audit_lib' has no attribute 'load_env_value'`.

- [ ] **Step 3: Implement** (append to `client_audit_lib.py`)

```python
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$")
_AUDIT_NAME_RE = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})-audit\.md$")


def load_env_value(path, name):
    """One NAME=value from an env file, parsed as DATA with load_cred_env's rules."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if line.startswith(name + "="):
                v = line.split("=", 1)[1]
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                return v
    return None


def check_host_parent(path, uid=0, mode=0o711):
    """A host parent like /var/lib/hermes/vaults: a real directory, owned by root, exactly
    0711 — traversable by uid 10000, listable and renamable by root only."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing; create it root:root {oct(mode)}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PrecheckError(f"{path} is a symlink or not a directory")
    if st.st_uid != uid or stat.S_IMODE(st.st_mode) != mode:
        raise PrecheckError(f"{path} must be owner uid {uid}, mode {oct(mode)}; "
                            f"is uid {st.st_uid}, mode {oct(stat.S_IMODE(st.st_mode))}")


def check_client_dir(path, uid):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing; register the client's vault first")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PrecheckError(f"{path} is a symlink or not a directory")
    if st.st_uid != uid:
        raise PrecheckError(f"{path} must be owned by uid {uid}; is uid {st.st_uid}")


def list_audit_ts(dir_fd):
    out = []
    for name in os.listdir(dir_fd):
        m = _AUDIT_NAME_RE.match(name)
        if m and stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
            out.append(m.group(1))
    return sorted(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/client_audit_lib.py infra/hermes-agent/bin/client_audit_lib.test.py
git commit -m "feat(hermes): client_audit_lib helpers for the Option B data layout"
```

---

### Task 3: Compose services `ads-drafter` and `egress-proxy`, and per-client reports for `ads-reader`

**Files:**
- Modify: `infra/hermes-agent/docker-compose.yml` (the `ads-reader` block, plus new services and a top-level `networks:`)
- Modify: `infra/hermes-agent/deploy/audit-mounts-integration.test.py`

**Interfaces:**
- Produces:
  - Compose service `ads-drafter`: entrypoint `["sh","-c"]`; its command is the draft script; it reads `HERMES_VAULT_DIR`, `HERMES_REPORTS_DIR` and `HERMES_DRAFT_OUT_DIR`, each defaulting to `/dev/null` (fail closed).
  - Service `egress-proxy`, which listens on `3128`.
  - Network `drafter-net`.
  - `ads-reader` reads `HERMES_REPORTS_DIR`, mounted at `/opt/data/reports/claude_google_ads`.

- [ ] **Step 1: Write the failing integration tests** (append to `TestAuditMounts` in `audit-mounts-integration.test.py`; in `setUpClass`, after `cls.data` is created, add the per-client dirs and extend `cls.env`)

In `setUpClass`, before `cls.env = …`:

```python
        for name in ("vault", "reports", "out"):
            p = os.path.join(cls.tmp, name + "/acme"); os.makedirs(p)
            os.chown(p, 10000, 10000); os.chmod(p, 0o700)
        cls.vault, cls.reports, cls.out = (os.path.join(cls.tmp, n + "/acme") for n in ("vault", "reports", "out"))
        open(os.path.join(cls.vault, "timeline.md"), "w").close()
```

Replace the `cls.env = dict(…)` line with:

```python
        cls.env = dict(os.environ, HERMES_AUDIT_DATA_DIR=cls.data, HERMES_SPOOL_DIR=cls.tmp,
                       HERMES_GOVERNANCE_DIR=os.path.join(cls.tmp, "governance"),
                       HERMES_AGENT_DIR=cls.agent, HERMES_ADS_REPO_DIR=os.path.join(cls.tmp, "claude-google-ads"),
                       HERMES_VAULT_DIR=cls.vault, HERMES_REPORTS_DIR=cls.reports, HERMES_DRAFT_OUT_DIR=cls.out)
```

Append the tests:

```python
    def test_reader_writes_per_client_reports(self):
        r = self.run_svc("--entrypoint", "sh", "ads-reader", "-c",
                         "echo x > /opt/data/reports/claude_google_ads/t.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.reports, "t.md")))

    def test_drafter_mounts_one_client_ro_and_writes_only_out(self):
        script = ("id -u; test -r /work/vault/timeline.md && echo VAULT_R; "
                  "touch /work/vault/x 2>/dev/null && echo VAULT_W; "
                  "touch /work/reports/x 2>/dev/null && echo REPORTS_W; "
                  "touch /work/out/draft.md && echo OUT_W; touch /etc/x 2>/dev/null && echo ROOTFS_W; "
                  "test -e /var/lib/hermes && echo HOST_VISIBLE; env | cut -d= -f1 | grep -E '^GOOGLE_ADS_' || true")
        r = self.run_svc("ads-drafter", script)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.split()
        self.assertEqual(out[0], "10000")
        self.assertIn("VAULT_R", out); self.assertIn("OUT_W", out)
        for bad in ("VAULT_W", "REPORTS_W", "ROOTFS_W", "HOST_VISIBLE"):
            self.assertNotIn(bad, out)
        self.assertFalse(any(x.startswith("GOOGLE_ADS_") for x in out))

    def test_drafter_has_no_route_out_except_the_proxy(self):
        sh(*self.compose, "up", "-d", "--no-deps", "egress-proxy", env=self.env)
        try:
            probe = ("import os,socket,sys\n"
                     "def direct():\n"
                     "  try: socket.create_connection(('1.1.1.1',443),timeout=5); return 'DIRECT_OK'\n"
                     "  except OSError: return 'DIRECT_BLOCKED'\n"
                     "def via(target):\n"
                     "  s=socket.create_connection(('egress-proxy',3128),timeout=10)\n"
                     "  s.sendall(('CONNECT %s HTTP/1.1\\r\\nHost: x\\r\\n\\r\\n'%target).encode())\n"
                     "  return s.recv(64).split(b'\\r\\n')[0].decode()\n"
                     "print(direct()); print(via('example.com:443')); print(via('api.anthropic.com:443'))\n")
            r = self.run_svc("ads-drafter", f"python3 -c \"{probe}\"")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(lines[0], "DIRECT_BLOCKED")
            self.assertIn("403", lines[1])
            self.assertIn("200", lines[2])
        finally:
            sh(*self.compose, "rm", "-sf", "egress-proxy", env=self.env, check=False)
```

Note: `run_svc` passes `--no-deps`, so the proxy is started explicitly, exactly as `run-client-audit` will start it.

- [ ] **Step 2: Run the tests to verify they fail** (Linux with Docker as root; on a Mac they print SKIPPED, so the RED is confirmed in CI)

Run: `sudo env HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/audit-mounts-integration.test.py -v`
Expected: FAIL with `no such service: ads-drafter`.

- [ ] **Step 3: Edit `docker-compose.yml`**

Replace the `ads-reader` service's `- ./data/reports:/opt/data/reports` line with:

```yaml
      - ${HERMES_REPORTS_DIR:-/dev/null}:/opt/data/reports/claude_google_ads
```

Append after `ads-reader` (still under `services:`):

```yaml
  # ---- Option B (spec 2026-09-30 §5): the Opus draft, per run and per client. Driven ONLY by
  # bin/run-client-audit.py, which sets the three HERMES_*_DIR variables and passes
  # ANTHROPIC_API_KEY as `-e NAME` (value from its env, read from /etc/hermes/.env.anthropic).
  # No env_file: never the gateway .env. Each dir defaults to /dev/null so a run without it fails
  # closed. Its only network is drafter-net (internal: no route out); egress-proxy is the one exit.
  ads-drafter:
    image: hermes-agent-claude
    profiles: ["tools"]
    user: "10000:10000"
    entrypoint: ["sh", "-c"]
    read_only: true
    tmpfs:
      - /tmp:size=256m,mode=1777
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 2g
    pids_limit: 256
    environment:
      HOME: /tmp
      HTTPS_PROXY: http://egress-proxy:3128
      HTTP_PROXY: http://egress-proxy:3128
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
      DISABLE_AUTOUPDATER: "1"
    networks: [drafter-net]
    volumes:
      - ../../../claude-google-ads:/projects/claude_google_ads:ro
      - ./masks/empty:/projects/claude_google_ads/.env:ro
      - ./skills/claude-code-ads-analyst:/opt/skills/claude-code-ads-analyst:ro
      - ${HERMES_VAULT_DIR:-/dev/null}:/work/vault:ro
      - ${HERMES_REPORTS_DIR:-/dev/null}:/work/reports:ro
      - ${HERMES_DRAFT_OUT_DIR:-/dev/null}:/work/out
  # The drafter's one exit: CONNECT to api.anthropic.com:443 only (bin/egress-proxy.py). Started
  # by run-client-audit for the draft step and removed in its `finally`.
  egress-proxy:
    image: hermes-agent-claude
    profiles: ["tools"]
    user: "10000:10000"
    entrypoint: ["python3", "/opt/cc-bin/egress-proxy.py", "--listen", "0.0.0.0:3128",
                 "--allow", "api.anthropic.com:443"]
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    networks: [default, drafter-net]
    volumes:
      - ./bin:/opt/cc-bin:ro

networks:
  drafter-net:
    internal: true
```

- [ ] **Step 4: Verify that compose renders, locally** (any OS with Docker)

Run: `cd infra/hermes-agent && HERMES_SPOOL_DIR=/tmp HERMES_GOVERNANCE_DIR=/tmp HERMES_AGENT_DIR=. HERMES_ADS_REPO_DIR=/tmp docker compose --env-file /dev/null config --services`
Expected: the list includes `ads-drafter` and `egress-proxy`, and there's no error.

- [ ] **Step 5: Push the branch and confirm the CI "Bind agreement" job passes** (it runs this integration test as root on Linux)

Run: `git push -u origin HEAD`, then `gh run watch`.
Expected: the job "Bind agreement (root, Linux, real proxy)" passes, including the three new tests.

- [ ] **Step 6: Commit** (before the push in Step 5)

```bash
git add infra/hermes-agent/docker-compose.yml infra/hermes-agent/deploy/audit-mounts-integration.test.py
git commit -m "feat(hermes): ads-drafter + egress-proxy services; per-client reports mount (Option B §4-§5)"
```

---

### Task 4: `run-client-audit` uses the new layout, the drafter and the proxy

**Files:**
- Modify: `infra/hermes-agent/bin/run-client-audit.py`
- Modify: `infra/hermes-agent/bin/run-client-audit.test.py`

**Interfaces:**
- Consumes: Task 2 (`L.load_env_value`, `L.check_host_parent`, `L.check_client_dir`) and Task 3 (the service names and env variables).
- Produces:
  - module constants `VAULTS`, `REPORTS`, `DRAFT_OUT` and `ANTHROPIC_CRED`;
  - `step_name(argv)` returns `proxy` for `up … egress-proxy` and `draft` for an `ads-drafter` run;
  - module-level `stop_proxy(root)`, which tests replace;
  - `read_transient(root, slug, ts)`, `remove_transient(root, slug, ts)` and `vault_draft_is_file(root, slug, ts)`, all with the new signatures.

- [ ] **Step 1: Update the test harness to the new layout** (`run-client-audit.test.py`)

In `FakeRunner.__call__`, replace the `draft` and `vault-write` branches with:

```python
        if name == "draft":
            d = self.root + "/var/lib/hermes/draft-out/acme-dental"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, ts + "-audit.md"), "w").write(self.draft_text)
        if name == "vault-write":
            v = self.root + "/var/lib/hermes/vaults/acme-dental/audits"
            os.makedirs(v, exist_ok=True)
            open(os.path.join(v, ts + "-audit.md"), "w").write(self.draft_text)
```

In `Base.setUp`, replace the `.env` line and the `data/` line with:

```python
        w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-x\n", 0o400)
        for parent in ("/var/lib/hermes/vaults", "/var/lib/hermes/reports", "/var/lib/hermes/draft-out"):
            os.makedirs(R(parent), exist_ok=True); os.chmod(R(parent), 0o711)
        os.makedirs(R("/var/lib/hermes/vaults/acme-dental"), exist_ok=True)
        self.proxy_stops = []
        RCA.stop_proxy = lambda root: self.proxy_stops.append(root)
```

- [ ] **Step 2: Replace the obsolete test classes and tests.** Delete `TestRootNeverFollowsGatewaySymlinks` and `TestReportsDirOwnership` entirely: they test `data/` helpers that this task removes. Then make these edits:
  - `test_all_steps_run_in_order_and_draft_lands_in_vault`: the expected names become `[collect…] + ["snapshot"] + [read…] + ["proxy", "draft", "vault-write"]`, and the path assertion becomes `/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md`.
  - `test_snapshot_stdout_alone_is_handed_to_the_container_uid`: remove its `data/reports` inode line and any assertion that uses it.
  - `test_symlinked_transient_draft_or_vault_draft_is_not_trusted`: the dict becomes `{"draft": s.root + "/var/lib/hermes/draft-out/acme-dental", "vault-write": s.root + "/var/lib/hermes/vaults/acme-dental/audits"}[name]`.
  - `test_transient_draft_is_removed_after_vault_write`, `test_transient_draft_is_removed_when_a_later_step_fails` and `test_draft_naming_another_client_fails_before_vault_write`: replace `/opt/hermes-agent/data/audits/claude_google_ads` with `/var/lib/hermes/draft-out/acme-dental`, and `/opt/hermes-agent/data/vaults/` with `/var/lib/hermes/vaults/`.
  - `test_dummy_anthropic_key_refused`: write `ANTHROPIC_API_KEY=dummy` to `/etc/hermes/.env.anthropic` (keep mode `0400`: `os.chmod(p, 0o600)`, write, `os.chmod(p, 0o400)`) instead of the gateway `.env`.
  - `test_draft_exec_still_targets_the_hermes_agent_project`: rename it to `test_draft_run_targets_the_drafter_in_the_hermes_agent_project`, and assert that the draft argv contains `"run"`, `"ads-drafter"` and the resolved `-f` path, and doesn't contain `"exec"` or `"hermes-agent"` as the service.
  - `test_draft_gets_its_values_inline_and_no_credential`: assert that the argv has `-e ANTHROPIC_API_KEY` (a name only), that `env["ANTHROPIC_API_KEY"] == "sk-ant-api03-x"`, that no `GOOGLE_ADS_*` is in the env or argv, and that `sk-ant` isn't in any argv element.

Then add the new tests:

```python
class TestOptionBLayout(Base):
    def test_draft_gets_one_client_dirs_and_the_key_by_name(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 0, text)
        d = [c for c in r.calls if RCA.step_name(c["argv"]) == "draft"][0]
        self.assertEqual(d["env"]["HERMES_VAULT_DIR"], "/var/lib/hermes/vaults/acme-dental")
        self.assertEqual(d["env"]["HERMES_REPORTS_DIR"], "/var/lib/hermes/reports/acme-dental")
        self.assertEqual(d["env"]["HERMES_DRAFT_OUT_DIR"], "/var/lib/hermes/draft-out/acme-dental")
        self.assertIn("ANTHROPIC_API_KEY", d["argv"])
        self.assertNotIn("sk-ant-api03-x", " ".join(d["argv"]))
        self.assertNotIn("sk-ant-api03-x", text)

    def test_readers_get_the_per_client_reports_dir(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        for c in r.calls:
            if RCA.step_name(c["argv"]).startswith("read:"):
                self.assertEqual(c["env"]["HERMES_REPORTS_DIR"], "/var/lib/hermes/reports/acme-dental")

    def test_proxy_started_before_draft_and_stopped_on_every_exit(self):
        for kw in ({}, {"fail_on": "draft"}, {"draft_text": "DRAFT names other-dental"},
                   {"raise_on": ("draft", OSError)}):
            with self.subTest(kw=kw):
                self.proxy_stops.clear()
                r = FakeRunner(self.root, **kw)
                self.run_main(r)
                names = [RCA.step_name(c["argv"]) for c in r.calls]
                self.assertEqual(names[names.index("draft") - 1], "proxy")
                self.assertEqual(len(self.proxy_stops), 1)

    def test_proxy_not_started_when_collection_fails(self):
        r = FakeRunner(self.root, fail_on="collect")
        self.run_main(r)
        self.assertNotIn("proxy", [RCA.step_name(c["argv"]) for c in r.calls])

    def test_reports_and_draft_out_reset_each_run(self):
        stale = self.root + "/var/lib/hermes/reports/acme-dental/old.md"
        os.makedirs(os.path.dirname(stale)); open(stale, "w").close()
        self.run_main(FakeRunner(self.root))
        self.assertFalse(os.path.exists(stale))

    def test_bad_host_parent_refused_before_any_step(self):
        os.chmod(self.root + "/var/lib/hermes/vaults", 0o755)
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_missing_client_vault_refused_before_any_step(self):
        os.rmdir(self.root + "/var/lib/hermes/vaults/acme-dental")
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_anthropic_key_file_wrong_mode_refused(self):
        os.chmod(self.root + "/etc/hermes/.env.anthropic", 0o600)
        rc, text = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 2)

    def test_symlink_in_draft_out_is_neither_read_nor_removed(self):
        """The drafter (uid 10000) plants a symlink where the draft should be: root must refuse
        to read it (rc 1, nothing reaches the vault) and must not unlink its target."""
        outside = tempfile.mkdtemp(); target = os.path.join(outside, "secret.md")
        open(target, "w").write("secret")
        fake = FakeRunner(self.root)
        def runner(argv, env, timeout, out, err):
            if RCA.step_name(argv) == "draft":        # plant instead of writing a draft
                d = self.root + "/var/lib/hermes/draft-out/acme-dental"
                os.symlink(target, os.path.join(d, "2026-10-01_12-00-00-audit.md"))
                return 0
            return fake(argv, env, timeout, out, err)
        rc, text = self.run_main(runner)
        self.assertEqual(rc, 1, text)
        self.assertEqual(open(target).read(), "secret")
        self.assertFalse(os.path.exists(self.root + "/var/lib/hermes/vaults/acme-dental/audits/"
                                        "2026-10-01_12-00-00-audit.md"))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -v`
Expected: FAIL. For example, `KeyError: 'HERMES_VAULT_DIR'`, the step list lacks `proxy`, or `AttributeError: … stop_proxy`.

- [ ] **Step 4: Implement the changes in `run-client-audit.py`**

1. Constants: replace the `LOCK` line's neighbours so the block reads:

```python
AUDIT_DATA = "/var/lib/hermes/audit-data"
AUDIT_LOGS = "/var/lib/hermes/audit-logs"   # root-only; never mounted into anything
VAULTS = "/var/lib/hermes/vaults"           # Option B §4: client data out of the gateway
REPORTS = "/var/lib/hermes/reports"
DRAFT_OUT = "/var/lib/hermes/draft-out"
ANTHROPIC_CRED = "/etc/hermes/.env" + ".anthropic"
HOST_PARENTS = (VAULTS, REPORTS, DRAFT_OUT)
LOCK = "/run/lock/hermes-client-audit.lock"
```

   and add `"proxy": 60` to `TIMEOUTS`.

2. Replace `DRAFT_SCRIPT` with the drafter version. The prompt text is unchanged except for the three paths:

```python
DRAFT_SCRIPT = r'''
  set -eu
  skill="/opt/skills/claude-code-ads-analyst/SKILL.md"
  vault="/work/vault"; reports="/work/reports"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  out="/work/out/$TS-audit.md"
  timeout -k 30 1150 claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Do NOT attempt ExitPlanMode and do NOT narrate your tools or environment; BEGIN your response with the DRAFT banner and output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'''
```

3. `step_name`: replace the `if "exec" in argv:` branch with:

```python
    if "ads-drafter" in argv:
        return "draft"
    if "egress-proxy" in argv and "up" in argv:
        return "proxy"
```

4. Delete `_data_dir`, `REPORTS_FIX`, `ensure_reports_dir` and `clear_reports`. Replace `read_transient`, `remove_transient` and `vault_draft_is_file` with:

```python
# draft-out/<slug> and vaults/<slug> are uid 10000's (the drafter and vault-write write them), so
# any name below the root-owned 0711 parent can be a planted symlink: reach them only through
# L.open_dir_below and act relative to that fd (F1).
def read_transient(root, slug, ts):
    fd = L.open_dir_below(root + DRAFT_OUT, (slug,))
    if fd is None:
        raise FileNotFoundError("the transient draft is missing")
    try:
        ffd = os.open(f"{ts}-audit.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace") as f:
        if not stat.S_ISREG(os.fstat(ffd).st_mode):
            raise L.UnsafePathError("the transient draft is not a regular file")
        return f.read()


def remove_transient(root, slug, ts):
    fd = L.open_dir_below(root + DRAFT_OUT, (slug,))
    if fd is None:
        return
    try:
        os.unlink(f"{ts}-audit.md", dir_fd=fd)
    except FileNotFoundError:
        pass
    finally:
        os.close(fd)


def vault_draft_is_file(root, slug, ts):
    fd = L.open_dir_below(root + VAULTS, (slug, "audits"))
    if fd is None:
        return False
    try:
        return stat.S_ISREG(os.stat(f"{ts}-audit.md", dir_fd=fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)


def stop_proxy(root):
    """Always called from _run's finally; harmless when the proxy never started."""
    return _quiet(_compose(root) + ["rm", "-sf", "egress-proxy"])
```

5. In `plan()`, replace everything from the `cred = …` line to the end of the function with:

```python
    cred = {**base, **{k: v for k, v in L.load_cred_env(root + CRED).items() if k in CRED_NAMES},
            "GOOGLE_ADS_CUSTOMER_ID": cid, "HERMES_AUDIT_DATA_DIR": data,
            "HERMES_REPORTS_DIR": REPORTS + "/" + slug}
    eflags = [x for n in CRED_NAMES for x in ("-e", n)]
    named = lambda step: _compose(root) + ["run", "--rm", "--no-deps", "-T", "--name", f"hermes-audit-{ts}-{step}"]
    run = lambda step: named(step) + eflags          # Google credential: collector and reader ONLY
    steps = [("collect", run(f"collect-{c}") + ["ads-collector", f"code/{c}.py"], cred) for c in COLLECTORS]
    steps.append(("snapshot", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/ads-metrics-snapshot.py",
                               "--audit-data", root + data, "--customer", cid, "--collected-at", collected_at], base))
    steps += [("read", run(f"read-{r}") + ["ads-reader", "--report", r, "--project", PROJECT], cred)
              for r in READERS]
    steps.append(("proxy", _compose(root) + ["up", "-d", "--no-deps", "egress-proxy"], base))
    key = L.load_env_value(root + ANTHROPIC_CRED, "ANTHROPIC_API_KEY") or ""
    draft_env = {**base, "ANTHROPIC_API_KEY": key, "HERMES_VAULT_DIR": VAULTS + "/" + slug,
                 "HERMES_REPORTS_DIR": REPORTS + "/" + slug, "HERMES_DRAFT_OUT_DIR": DRAFT_OUT + "/" + slug}
    # Non-secret, validated values inline (M9): slug (eligible_client), PROJECT (constant), ts (_iso).
    steps.append(("draft", named("draft") + ["-e", "ANTHROPIC_API_KEY", "-e", f"PROJECT={PROJECT}",
                                             "-e", f"CLIENT={slug}", "-e", f"TS={ts}",
                                             "ads-drafter", DRAFT_SCRIPT], draft_env))
    steps.append(("vault-write", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/vault-write.py", "--client", slug,
                                  "--audit-file", root + f"{DRAFT_OUT}/{slug}/{ts}-audit.md",
                                  "--metrics-file", root + AUDIT_LOGS + "/" + slug + "/snapshot.stdout", "--ts", ts,
                                  "--registry", root + REGISTRY],
                  {**base, "VAULT_ROOT": root + VAULTS, "TS": ts}))
    return steps
```

6. In `main()`, replace the pre-check block's first three lines (`check_secret_file` … the gateway `.env` check) with:

```python
        L.check_secret_file(root + CRED, uid=OWNER_UID, mode=0o400)
        L.check_secret_file(root + ANTHROPIC_CRED, uid=OWNER_UID, mode=0o400)
        if L.anthropic_key_state(root + ANTHROPIC_CRED) != "real":
            raise L.PrecheckError(f"{ANTHROPIC_CRED} holds no real Anthropic key")
        for parent in HOST_PARENTS:
            L.check_host_parent(root + parent, uid=OWNER_UID)
        L.check_client_dir(root + VAULTS + "/" + rec["slug"],
                           uid=os.geteuid() if DATA_UID is None else DATA_UID)
```

   In the dry-run printout, redact the key: build `shown_env = sorted(k for k in env if k != 'PATH')`. It's already names only, so no change is needed. Confirm by test.

7. In `_run()`:
   - After `L.reset_dir(data, **kw)`, add:

```python
    for parent in (REPORTS, DRAFT_OUT):               # last run's reports/draft never leak into this one
        L.reset_dir(root + parent + "/" + slug, **kw)
```

   - Delete the `if key == "read" and name.endswith(READERS[0]):` block.
   - In the vault-write isolation check, call `read_transient(root, slug, ts)`.
   - Set `vault_draft = f"{VAULTS}/{slug}/audits/{ts}-audit.md"`.
   - Change the `finally:` to:

```python
    finally:                        # the transient draft never outlives the run (I3); the proxy stops
        remove_transient(root, slug, ts)
        stop_proxy(root)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -v`
Expected: all PASS. Fix any remaining old-path assertion the edits in Step 2 missed: `grep -n "opt/hermes-agent/data" infra/hermes-agent/bin/run-client-audit.test.py` must print nothing.

- [ ] **Step 6: Run the whole bin suite, then commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`. Expected: `N/N suites passed`.

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py
git commit -m "feat(hermes): run-client-audit drafts in ads-drafter behind egress-proxy; client data under /var/lib/hermes (Option B §4-§5)"
```

---

### Task 5: `run-client-audit --json` and `--list`

**Files:**
- Modify: `infra/hermes-agent/bin/run-client-audit.py`
- Modify: `infra/hermes-agent/bin/run-client-audit.test.py`

**Interfaces:**
- Produces: the machine-readable contract that part 2's broker consumes, exactly one JSON line on stdout.
  - For a run: `{"status": "ok|refused|failed|busy", "reason": <str|null>, "exit_code": <int>, "ts": <TS|null>, "steps": [{"name": <class>, "rc": <int>, "seconds": <float>}], "vault_path": <str|null>}`.
  - `name` is one of `collect`, `snapshot`, `read`, `proxy`, `draft`, `isolation` and `vault-write`, aggregated per class (max rc, summed seconds).
  - `reason`:
    - `null` when ok;
    - `precheck` when refused;
    - `busy` when busy;
    - the failing class, or `internal`, when failed.
  - For a list: `{"status": "ok", "audits": [<TS>, …]}` (at most the newest 24), or `{"status": "refused", "reason": "precheck"}` with exit 2.
  - With `--json`, every human line goes to stderr.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestJson(Base):
    def run_json(self, runner, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RCA.main(["acme-dental", "--json", *extra], runner=runner, root=self.root, now="2026-10-01_12-00-00")
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, out.getvalue())
        return rc, json.loads(lines[0]), err.getvalue()

    def test_ok(self):
        rc, j, _ = self.run_json(FakeRunner(self.root))
        self.assertEqual((rc, j["status"], j["reason"], j["exit_code"]), (0, "ok", None, 0))
        self.assertEqual(j["vault_path"], "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md")
        self.assertEqual([s["name"] for s in j["steps"]],
                         ["collect", "snapshot", "read", "proxy", "draft", "vault-write"])
        self.assertEqual(set(j), {"status", "reason", "exit_code", "ts", "steps", "vault_path"})

    def test_failed_step_names_its_class(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, fail_on="read:audit_search_terms"))
        self.assertEqual((rc, j["status"], j["reason"]), (1, "failed", "read"))
        self.assertIsNone(j["vault_path"])

    def test_isolation_failure(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, draft_text="DRAFT names other-dental"))
        self.assertEqual((j["status"], j["reason"]), ("failed", "isolation"))

    def test_collector_errors_are_collect(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, error_file="x.ERROR.txt"))
        self.assertEqual((j["status"], j["reason"]), ("failed", "collect"))

    def test_precheck_refused(self):
        os.chmod(self.root + "/var/lib/hermes/vaults", 0o755)
        rc, j, err = self.run_json(FakeRunner(self.root))
        self.assertEqual((rc, j["status"], j["reason"]), (2, "refused", "precheck"))

    def test_unregistered_client_refused(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = RCA.main(["nobody", "--json"], runner=FakeRunner(self.root), root=self.root)
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.getvalue())["reason"], "precheck")

    def test_busy(self):
        import fcntl
        fd = os.open(self.root + RCA.LOCK, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, j, _ = self.run_json(FakeRunner(self.root))
        finally:
            os.close(fd)
        self.assertEqual((rc, j["status"], j["reason"]), (3, "busy", "busy"))

    def test_unexpected_error_is_internal(self):
        rc, j, _ = self.run_json(FakeRunner(self.root, raise_on=("collect", OSError)))
        self.assertEqual((rc, j["status"], j["reason"]), (1, "failed", "internal"))

    def test_json_never_carries_a_customer_id_or_key(self):
        rc, j, err = self.run_json(FakeRunner(self.root))
        blob = json.dumps(j)
        self.assertNotIn(CID, blob); self.assertNotIn("sk-ant", blob); self.assertNotIn(CID, err)


class TestList(Base):
    def run_list(self, client="acme-dental"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = RCA.main([client, "--list", "--json"], runner=FakeRunner(self.root), root=self.root)
        return rc, json.loads(out.getvalue())

    def test_lists_timestamps_only_and_takes_no_lock(self):
        a = self.root + "/var/lib/hermes/vaults/acme-dental/audits"; os.makedirs(a)
        for ts in ("2026-09-01_10-00-00", "2026-09-30_10-00-00"):
            open(f"{a}/{ts}-audit.md", "w").close()
        open(f"{a}/readme.md", "w").close()
        import fcntl
        fd = os.open(self.root + RCA.LOCK, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, j = self.run_list()
        finally:
            os.close(fd)
        self.assertEqual((rc, j), (0, {"status": "ok", "audits": ["2026-09-01_10-00-00", "2026-09-30_10-00-00"]}))

    def test_no_audits_yet(self):
        self.assertEqual(self.run_list(), (0, {"status": "ok", "audits": []}))

    def test_inactive_client_refused(self):
        rc, j = self.run_list("nobody")
        self.assertEqual((rc, j["status"]), (2, "refused"))

    def test_list_requires_json(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                RCA.main(["acme-dental", "--list"], runner=FakeRunner(self.root), root=self.root)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py TestJson TestList -v`
Expected: FAIL with `unrecognized arguments: --json`.

- [ ] **Step 3: Implement.** In `run-client-audit.py`, add after `step_name`:

```python
STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write")
LIST_LIMIT = 24


def step_class(name):
    return name.split(":", 1)[0]


def json_result(status, reason, rc, ts, results, vault_path):
    agg = {}
    for name, r, secs in results:
        c = step_class(name)
        prev = agg.get(c, {"name": c, "rc": 0, "seconds": 0.0})
        r_int = r if isinstance(r, int) else 1
        agg[c] = {"name": c, "rc": max(prev["rc"], r_int), "seconds": round(prev["seconds"] + secs, 1)}
    steps = [agg[c] for c in STEP_CLASSES if c in agg]
    return json.dumps({"status": status, "reason": reason, "exit_code": rc, "ts": ts,
                       "steps": steps, "vault_path": vault_path}, sort_keys=True)
```

Rework `main()` as follows:
- **Arguments:** add `ap.add_argument("--json", action="store_true")` and `ap.add_argument("--list", action="store_true")`. After parsing, `if a.list and not a.json: ap.error("--list requires --json")`.
- **Output routing:** when `a.json`, every human line goes to stderr. Define `say = lambda s: print(red.text(s), file=sys.stderr if a.json else sys.stdout)`, and give the unredacted early refusal the same `file=sys.stderr`.
- **A single JSON emit point.** Change `main` so each return goes through `emit(status, reason, rc, results=(), vault_path=None)`. It prints `json_result(...)` to stdout when `a.json` and returns rc. Concretely:
  - the first `eligible_client` refusal → `return emit("refused", "precheck", 2)`;
  - the pre-check block refusal → `return emit("refused", "precheck", 2)`;
  - `L.PrecheckError` from the lock → `return emit("busy", "busy", 3)`;
  - the `(OSError, ValueError, TypeError, AttributeError)` branch under the lock → `return emit("failed", "internal", 1, state["results"])`.
- **The list path,** after the `eligible_client` success and before the pre-check block:

```python
    if a.list:
        fd = L.open_dir_below(root + VAULTS, (rec["slug"], "audits"))
        audits = []
        if fd is not None:
            try:
                audits = L.list_audit_ts(fd)[-LIST_LIMIT:]
            finally:
                os.close(fd)
        print(json.dumps({"status": "ok", "audits": audits}, sort_keys=True))
        return 0
```

  Keep the list path's refusal (from `eligible_client`) as `print(json.dumps({"status": "refused", "reason": "precheck"}))` plus `return 2`, rather than the full run shape. Add that branch where the first refusal is handled: `if a.list: print(json.dumps({"status": "refused", "reason": "precheck"}, sort_keys=True)); return 2`.
- **`_run` reports its outcome:** give it an extra parameter `state` (a dict) that it fills with `state["results"] = results`, plus `state["reason"]` whenever it returns 1. The reasons are:
  - `"collect"` for the error-file and no-JSON branches;
  - `"isolation"` for the `named` branch;
  - `step_class(name)` for a failed step;
  - `"vault-write"` for the missing vault draft.
  
  On success it sets `state["vault_path"] = vault_draft`. `main` then does:

```python
    state = {"results": [], "reason": None, "vault_path": None}
    try:
        with L.AuditLock(root + LOCK):
            rc = _run(steps, rec, ts, root, runner, say, state)
    except L.PrecheckError as e:
        print(f"run-client-audit: {e}", file=sys.stderr); return emit("busy", "busy", 3)
    except (OSError, ValueError, TypeError, AttributeError) as e:
        say(f"run-client-audit: failed: {type(e).__name__}: {e}")
        return emit("failed", "internal", 1, state["results"])
    return emit("ok" if rc == 0 else "failed", state["reason"], rc, state["results"], state["vault_path"])
```

  with

```python
    def emit(status, reason, rc, results=(), vault_path=None):
        if a.json:
            print(json_result(status, reason, rc, ts if status != "refused" else None, list(results), vault_path))
        return rc
```

  `_run` must append to `state["results"]` as it goes (use `results = state["results"]` at its top), so the `internal` path still reports the steps that ran.
- **The isolation failure** must appear as a step: in `_run`'s isolation branch, append `("isolation", 1, 0.0)` to `results` before returning 1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -v`
Expected: all PASS, and the older tests (plain, non-JSON output) are unchanged.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py
git commit -m "feat(hermes): run-client-audit --json and --list (the broker's contract, Option B §3.5)"
```

---

### Task 6: `install-env-secret.py`, which installs or strips one secret, validated and atomic

**Files:**
- Create: `infra/hermes-agent/bin/install-env-secret.py`
- Test: `infra/hermes-agent/bin/install-env-secret.test.py`

**Interfaces:**
- Produces the CLI:
  - `install-env-secret.py set --file PATH --name NAME --prefix PREFIX --mode 0400|0600 [--owner-uid N --owner-gid N]`: the value is read from `/dev/tty` with echo off. In tests it comes from the injectable `read_value`.
  - `install-env-secret.py strip --file PATH --name NAME`.
- Behaviour:
  - It never prints the value, and a value not starting with `PREFIX` is refused.
  - It replaces the `NAME=` line or appends it, keeps every other line byte-for-byte, and writes a temp file in the same dir with `O_EXCL`, then `fsync`, `fchown`, `fchmod` and `rename`.
  - It refuses when `PATH` is a symlink.
  - Exit codes: 0 done, 2 refused.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import contextlib, importlib.util, io, os, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ies", os.path.join(HERE, "install-env-secret.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, ".env")

    def run_(self, argv, value=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S.main(argv, read_value=lambda: value)
        return rc, out.getvalue()

    def test_set_creates_with_mode_and_never_prints_value(self):
        rc, text = self.run_(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                              "--prefix", "sk-ant-", "--mode", "0400"], "sk-ant-SECRET")
        self.assertEqual(rc, 0, text)
        self.assertEqual(open(self.f).read(), "ANTHROPIC_API_KEY=sk-ant-SECRET\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.f).st_mode), 0o400)
        self.assertNotIn("SECRET", text)

    def test_set_replaces_only_its_line(self):
        open(self.f, "w").write("A=1\nOPENROUTER_API_KEY=sk-or-old\n# c\n")
        rc, _ = self.run_(["set", "--file", self.f, "--name", "OPENROUTER_API_KEY",
                           "--prefix", "sk-or-", "--mode", "0600"], "sk-or-new")
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f).read(), "A=1\nOPENROUTER_API_KEY=sk-or-new\n# c\n")

    def test_bad_prefix_empty_or_multiline_refused_and_file_untouched(self):
        open(self.f, "w").write("A=1\n")
        for v in ("nope", "", "sk-ant-a\nB=2", None):
            rc, _ = self.run_(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                               "--prefix", "sk-ant-", "--mode", "0400"], v)
            self.assertEqual(rc, 2)
            self.assertEqual(open(self.f).read(), "A=1\n")

    def test_strip_removes_every_assignment_of_the_name(self):
        open(self.f, "w").write("ANTHROPIC_API_KEY=sk-ant-x\nA=1\nexport ANTHROPIC_API_KEY=y\n")
        os.chmod(self.f, 0o600)
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "ANTHROPIC_API_KEY"])
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.f).st_mode), 0o600)   # mode preserved

    def test_symlink_refused(self):
        real = os.path.join(self.d, "real"); open(real, "w").write("A=1\n"); os.symlink(real, self.f)
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "A"])
        self.assertEqual(rc, 2)
        self.assertEqual(open(real).read(), "A=1\n")

    def test_bad_name_refused(self):
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "a b"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/install-env-secret.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Install or strip ONE secret in an env file (Option B §6, BRING-UP). Stdlib only.

  sudo install-env-secret.py set   --file F --name N --prefix P --mode 0400|0600 [--owner-uid U --owner-gid G]
  sudo install-env-secret.py strip --file F --name N

`set` reads the value from /dev/tty with echo off (never argv, never stdin of a paste), refuses
a value without the expected prefix, and replaces or appends the one NAME= line. Every other
line is kept byte-for-byte. The new file is written beside the old one (O_EXCL), fsync'd, given
its owner and mode on the fd, and renamed over it: a governed file is never half-written, and a
bad input never replaces a good file (the 2026-09-30 registry lesson). Never prints a value."""
import argparse, getpass, os, re, stat, sys

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _tty_value():
    try:
        return getpass.getpass("value (hidden): ")
    except (EOFError, OSError):
        return None


def _lines(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return [], None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"{path} is a symlink or not a regular file")
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines(keepends=True), st


def _is_assign(line, name):
    s = line.lstrip()
    if s.startswith("export "):
        s = s[len("export "):].lstrip()
    return s.startswith(name + "=")


def _write(path, lines, mode, uid, gid):
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, "".join(lines).encode("utf-8"))
        os.fsync(fd)
        if uid is not None:
            os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
    except BaseException:
        os.close(fd); os.unlink(tmp); raise
    os.close(fd)
    os.rename(tmp, path)


def main(argv=None, read_value=_tty_value):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set")
    for p in (s, sub.add_parser("strip")):
        p.add_argument("--file", required=True)
        p.add_argument("--name", required=True)
    s.add_argument("--prefix", required=True)
    s.add_argument("--mode", required=True, choices=("0400", "0600"))
    s.add_argument("--owner-uid", type=int)
    s.add_argument("--owner-gid", type=int)
    a = ap.parse_args(argv)
    try:
        if not NAME_RE.match(a.name):
            raise ValueError("invalid variable name")
        lines, st = _lines(a.file)
        kept = [l for l in lines if not _is_assign(l, a.name)]
        if a.cmd == "strip":
            if st is None:
                print(f"install-env-secret: {a.file} absent; nothing to strip"); return 0
            _write(a.file, kept, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
            print(f"install-env-secret: {a.name} removed from {a.file} ({len(lines) - len(kept)} line(s))")
            return 0
        v = read_value()
        if not v or "\n" in v or "\r" in v or not v.startswith(a.prefix):
            raise ValueError(f"refused: the value is empty, multi-line, or does not start with {a.prefix!r}")
        new = f"{a.name}={v}\n"
        idx = next((i for i, l in enumerate(lines) if _is_assign(l, a.name)), None)
        if idx is None:                                   # append, keeping a final newline
            out = kept + ([] if not kept or kept[-1].endswith("\n") else ["\n"]) + [new]
        else:                                             # replace in place; drop any later duplicates
            out = [new if i == idx else l for i, l in enumerate(lines)
                   if i == idx or not _is_assign(l, a.name)]
        uid = a.owner_uid if a.owner_uid is not None else (st.st_uid if st else None)
        gid = a.owner_gid if a.owner_gid is not None else (st.st_gid if st else None)
        _write(a.file, out, int(a.mode, 8), uid, gid)
        print(f"install-env-secret: {a.name} set in {a.file} (mode {a.mode})")
        return 0
    except (ValueError, OSError) as e:
        print(f"install-env-secret: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/install-env-secret.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/install-env-secret.py infra/hermes-agent/bin/install-env-secret.test.py
git commit -m "feat(hermes): install-env-secret — validated, atomic set/strip of one env secret"
```

---

### Task 7: `migrate-client-data.py`: copy, verify, then remove

**Files:**
- Create: `infra/hermes-agent/bin/migrate-client-data.py`
- Test: `infra/hermes-agent/bin/migrate-client-data.test.py`

**Interfaces:**
- Produces the CLI `migrate-client-data.py --agent-dir /opt/hermes-agent --dest-root /var/lib/hermes [--apply]`.
  - Without `--apply`, it prints the plan: client counts and file counts, never file contents.
  - With `--apply`, for each of `vaults` and `reports`, it copies `agent/data/<tree>/<client>/…` to `dest/<tree>/<client>/…`:
    - `vaults` keeps its layout;
    - `reports/claude_google_ads/*.md` is **not** migrated, because reports are per run and rebuilt on the next audit. The source reports tree is only removed.
  - It preserves uid, gid, mode and mtime, and refuses symlinks anywhere in the source (it never follows them).
  - It verifies per-file size and sha256, and only then removes the source trees.
  - Exit codes: 0 done, 1 a verify mismatch (source intact), 2 refused (a destination client dir already exists, a symlink, or `dest/<tree>` missing or not root `0711`).

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import contextlib, hashlib, importlib.util, io, os, stat, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mcd", os.path.join(HERE, "migrate-client-data.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


class T(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.agent = os.path.join(self.t, "agent"); self.dest = os.path.join(self.t, "dest")
        v = os.path.join(self.agent, "data/vaults/acme/audits"); os.makedirs(v)
        open(os.path.join(v, "2026-09-30_10-00-00-audit.md"), "w").write("draft")
        open(os.path.join(self.agent, "data/vaults/acme/timeline.md"), "w").write("t")
        os.chmod(os.path.join(self.agent, "data/vaults/acme"), 0o700)
        r = os.path.join(self.agent, "data/reports/claude_google_ads"); os.makedirs(r)
        open(os.path.join(r, "x.md"), "w").write("r")
        for tree in ("vaults", "reports"):
            os.makedirs(os.path.join(self.dest, tree)); os.chmod(os.path.join(self.dest, tree), 0o711)
        M.ROOT_UID = os.geteuid()

    def run_(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = M.main(["--agent-dir", self.agent, "--dest-root", self.dest, *extra])
        return rc, out.getvalue()

    def test_dry_run_changes_nothing(self):
        rc, text = self.run_()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))
        self.assertNotIn("draft", text.replace("drafts", ""))

    def test_apply_copies_verifies_and_removes(self):
        rc, text = self.run_("--apply")
        self.assertEqual(rc, 0, text)
        got = os.path.join(self.dest, "vaults/acme/audits/2026-09-30_10-00-00-audit.md")
        self.assertEqual(open(got).read(), "draft")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dest, "vaults/acme")).st_mode), 0o700)
        self.assertFalse(os.path.exists(os.path.join(self.agent, "data/vaults")))
        self.assertFalse(os.path.exists(os.path.join(self.agent, "data/reports")))

    def test_verify_mismatch_keeps_source(self):
        real = M._sha256
        calls = {"n": 0}
        def flaky(p):
            calls["n"] += 1
            return "0" * 64 if p.startswith(self.dest) else real(p)
        with mock.patch.object(M, "_sha256", flaky):
            rc, text = self.run_("--apply")
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "data/vaults/acme")))

    def test_symlink_in_source_refused_before_copying(self):
        os.symlink("/etc/passwd", os.path.join(self.agent, "data/vaults/acme/evil"))
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "vaults/acme")))

    def test_existing_destination_refused(self):
        os.makedirs(os.path.join(self.dest, "vaults/acme"))
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)

    def test_bad_dest_parent_refused(self):
        os.chmod(os.path.join(self.dest, "vaults"), 0o755)
        rc, _ = self.run_("--apply")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/migrate-client-data.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Move client data out of the gateway's data/ (Option B §4). Stdlib only. Run as root, gateway stopped.

  sudo python3 bin/migrate-client-data.py [--agent-dir /opt/hermes-agent] [--dest-root /var/lib/hermes] [--apply]

vaults/<client>/ is copied to <dest>/vaults/<client>/ with owner, mode and mtime preserved, then
every file is re-hashed at the destination; only when all match are data/vaults and data/reports
removed (reports are per run and rebuilt by the next audit, so they are not copied). A symlink
anywhere in the source, an existing destination client dir, or a destination parent that is
not root 0711 refuses before anything is copied. Never prints file contents."""
import argparse, hashlib, os, shutil, stat, sys

ROOT_UID = 0


class Refused(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(src):
    """(relpath, lstat) for every entry below src; a symlink anywhere refuses."""
    out = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                raise Refused(f"symlink in the source: {os.path.relpath(p, src)}")
            if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise Refused(f"not a file or directory: {os.path.relpath(p, src)}")
            out.append((os.path.relpath(p, src), st))
    return out


def _check_parent(p):
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        raise Refused(f"{p} is missing; create it root:root 0711 first")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) \
            or st.st_uid != ROOT_UID or stat.S_IMODE(st.st_mode) != 0o711:
        raise Refused(f"{p} must be a root-owned 0711 directory")


def _copy_client(src, dst, entries):
    st = os.lstat(src)
    os.mkdir(dst, 0o700)
    for rel, est in entries:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if stat.S_ISDIR(est.st_mode):
            os.mkdir(d, 0o700)
        else:
            shutil.copyfile(s, d, follow_symlinks=False)
    for rel, est in [("", st)] + sorted(entries, key=lambda e: -e[0].count(os.sep)):
        d = os.path.join(dst, rel) if rel else dst
        os.chown(d, est.st_uid, est.st_gid, follow_symlinks=False)
        os.chmod(d, stat.S_IMODE(est.st_mode))
        os.utime(d, ns=(est.st_atime_ns, est.st_mtime_ns))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent-dir", default="/opt/hermes-agent")
    ap.add_argument("--dest-root", default="/var/lib/hermes")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    agent = os.path.realpath(a.agent_dir)
    src_vaults = os.path.join(agent, "data", "vaults")
    src_reports = os.path.join(agent, "data", "reports")
    dst_vaults = os.path.join(a.dest_root, "vaults")
    try:
        _check_parent(dst_vaults)
        _check_parent(os.path.join(a.dest_root, "reports"))
        clients = sorted(os.listdir(src_vaults)) if os.path.isdir(src_vaults) else []
        plan = []
        for c in clients:
            src = os.path.join(src_vaults, c)
            if stat.S_ISLNK(os.lstat(src).st_mode):
                raise Refused(f"vault {c!r} is a symlink")
            if os.path.lexists(os.path.join(dst_vaults, c)):
                raise Refused(f"destination vault for {c!r} already exists")
            plan.append((c, src, _walk(src)))
        for tree in (src_reports,):
            if os.path.lexists(tree):
                _walk(tree)
    except (Refused, OSError) as e:
        print(f"migrate-client-data: refused: {e}", file=sys.stderr)
        return 2
    for c, _, entries in plan:
        files = sum(1 for _, st in entries if stat.S_ISREG(st.st_mode))
        print(f"vault {c}: {files} file(s) -> {dst_vaults}/{c}")
    print(f"reports: {'remove ' + src_reports if os.path.lexists(src_reports) else 'none'}")
    if not a.apply:
        print("dry run: nothing changed (re-run with --apply)")
        return 0
    for c, src, entries in plan:
        _copy_client(src, os.path.join(dst_vaults, c), entries)
    bad = []
    for c, src, entries in plan:
        for rel, st in entries:
            if stat.S_ISREG(st.st_mode):
                s, d = os.path.join(src, rel), os.path.join(dst_vaults, c, rel)
                if os.path.getsize(d) != st.st_size or _sha256(d) != _sha256(s):
                    bad.append(f"{c}/{rel}")
    if bad:
        print(f"migrate-client-data: VERIFY FAILED for {len(bad)} file(s); the source is intact, "
              f"remove {dst_vaults}/<client> and re-run", file=sys.stderr)
        return 1
    for tree in (src_vaults, src_reports):
        if os.path.lexists(tree):
            shutil.rmtree(tree)
    print("migrate-client-data: done; data/vaults and data/reports removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/migrate-client-data.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/migrate-client-data.py infra/hermes-agent/bin/migrate-client-data.test.py
git commit -m "feat(hermes): migrate-client-data — copy, verify, then remove data/vaults (Option B §4)"
```

---

### Task 8: `show-audit`, which lets the operator read a draft on the host

**Files:**
- Create: `infra/hermes-agent/bin/show-audit.py`, `infra/hermes-agent/deploy/show-audit`
- Test: `infra/hermes-agent/bin/show-audit.test.py`

**Interfaces:**
- Consumes: `L.open_dir_below`, `L.list_audit_ts`, `L.TS_RE`, `L.eligible_client`-style slug validation (`vault_lib.validate_slug`).
- Produces the CLI `show-audit <client> [--latest | --ts TS | --list]`, root only through the wrapper.
  - It prints the draft to stdout, reached through `open_dir_below(VAULTS, (slug, "audits"))` and an `O_NOFOLLOW` regular-file check.
  - Exit codes: 0, 1 not found, 2 refused.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import contextlib, importlib.util, io, os, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sa", os.path.join(HERE, "show-audit.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.a = self.root + "/var/lib/hermes/vaults/acme/audits"; os.makedirs(self.a)
        open(self.a + "/2026-09-01_10-00-00-audit.md", "w").write("OLD")
        open(self.a + "/2026-09-30_10-00-00-audit.md", "w").write("NEW")

    def run_(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S.main(list(argv), root=self.root)
        return rc, out.getvalue(), err.getvalue()

    def test_latest_is_default(self):
        self.assertEqual(self.run_("acme")[:2], (0, "NEW"))

    def test_named_ts(self):
        self.assertEqual(self.run_("acme", "--ts", "2026-09-01_10-00-00")[:2], (0, "OLD"))

    def test_list(self):
        rc, out, _ = self.run_("acme", "--list")
        self.assertEqual(out.split(), ["2026-09-01_10-00-00", "2026-09-30_10-00-00"])

    def test_bad_slug_and_bad_ts_refused(self):
        self.assertEqual(self.run_("../x")[0], 2)
        self.assertEqual(self.run_("acme", "--ts", "../../etc/passwd")[0], 2)

    def test_symlinked_draft_not_followed(self):
        os.symlink("/etc/hostname", self.a + "/2026-10-01_00-00-00-audit.md")
        rc, out, _ = self.run_("acme", "--ts", "2026-10-01_00-00-00")
        self.assertEqual(rc, 1); self.assertEqual(out, "")

    def test_no_audits(self):
        self.assertEqual(self.run_("other")[0], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/show-audit.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement `show-audit.py`**

```python
#!/usr/bin/env python3
"""Print one client's audit draft to the operator (Option B §2). Stdlib only.

  sudo show-audit <client> [--latest | --ts YYYY-MM-DD_HH-MM-SS | --list]

The vault is uid 10000's, so every name below /var/lib/hermes/vaults is reached with
open_dir_below and opened O_NOFOLLOW: a planted symlink is never followed by root."""
import argparse, os, stat, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import vault_lib as V

VAULTS = "/var/lib/hermes/vaults"


def main(argv=None, root="/"):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--latest", action="store_true")
    g.add_argument("--ts")
    g.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    root = root.rstrip("/")
    try:
        V.validate_slug(a.client)
        if a.ts is not None and not L.TS_RE.match(a.ts):
            raise ValueError("invalid --ts")
    except ValueError as e:
        print(f"show-audit: refused: {e}", file=sys.stderr); return 2
    fd = L.open_dir_below(root + VAULTS, (a.client, "audits"))
    if fd is None:
        print("show-audit: no audits for this client", file=sys.stderr); return 1
    try:
        tss = L.list_audit_ts(fd)
        if a.list:
            print("\n".join(tss)); return 0
        ts = a.ts or (tss[-1] if tss else None)
        if ts is None or ts not in tss:
            print("show-audit: no such audit", file=sys.stderr); return 1
        ffd = os.open(f"{ts}-audit.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as e:
        print(f"show-audit: {type(e).__name__}", file=sys.stderr); return 1
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace") as f:
        if not stat.S_ISREG(os.fstat(ffd).st_mode):
            print("show-audit: not a regular file", file=sys.stderr); return 1
        sys.stdout.write(f.read())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

   Create `deploy/show-audit`:

```sh
#!/bin/sh
# Installed as /usr/local/sbin/show-audit (symlink, BRING-UP "Chat-triggered audits", part 1).
# Root only: the vaults are uid 10000, 0700.
[ "$(id -u)" = 0 ] || { echo "show-audit: run with sudo" >&2; exit 2; }
exec python3 /opt/hermes-agent/bin/show-audit.py "$@"
```

   Run `chmod +x infra/hermes-agent/deploy/show-audit`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/show-audit.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/show-audit.py infra/hermes-agent/bin/show-audit.test.py infra/hermes-agent/deploy/show-audit
git commit -m "feat(hermes): show-audit — read a client's draft on the host (Option B §2)"
```

---

### Task 9: BRING-UP and README for part 1, then the PR

**Files:**
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (a new section "Chat-triggered audits — part 1: isolation and egress", after "Ads audits on the box")
- Modify: `infra/hermes-agent/README.md` (the path and secrets tables)

Documentation doesn't change behaviour, so this task has no test step. `units.test.py` and `run-bin-tests.sh` must still pass.

- [ ] **Step 1: Write the BRING-UP section.** It must contain exactly these steps, each command on its own line. Any prompt goes in its own one-line paste, and no `read` sits inside a multi-line paste.

```markdown
## Chat-triggered audits — part 1: isolation and egress (spec 2026-09-30 §4–§6)

Breaks the review-#5 binding; nothing here is live for chat until part 2 and review #6.

1. Pull: `cd /opt/projects/claude_code && git pull --ff-only`
2. Host parents (root 0711):
   `sudo install -d -o root -g root -m 0711 /var/lib/hermes/vaults /var/lib/hermes/reports /var/lib/hermes/draft-out`
3. Anthropic key to its own file. Run this ALONE (it prompts on the tty):
   `sudo python3 /opt/hermes-agent/bin/install-env-secret.py set --file /etc/hermes/.env.anthropic --name ANTHROPIC_API_KEY --prefix sk-ant- --mode 0400 --owner-uid 0 --owner-gid 0`
   Check: `sudo stat -c '%U:%G %a' /etc/hermes/.env.anthropic` → `root:root 400`.
4. Stop the gateway, migrate, check:
   `cd /opt/hermes-agent && sudo docker compose stop hermes-agent`
   `sudo python3 bin/migrate-client-data.py` (dry run: read the counts)
   `sudo python3 bin/migrate-client-data.py --apply; echo rc=$?` → `rc=0`
   `sudo ls -la /var/lib/hermes/vaults` → one `drwx------ 10000` dir per active client
5. Strip the key from the gateway env (part 2 retires claude-auth-init; until then the gateway
   needs no real key for audits):
   `sudo python3 bin/install-env-secret.py strip --file /opt/hermes-agent/.env --name ANTHROPIC_API_KEY`
   `sudo docker compose up -d --force-recreate hermes-agent`
6. Install show-audit: `sudo ln -sf /opt/hermes-agent/deploy/show-audit /usr/local/sbin/show-audit`
7. Manual audit on the spending client:
   `sudo run-client-audit <client> --dry-run` (the plan shows `proxy` then `draft`, env names only)
   `sudo run-client-audit <client>; echo rc=$?` → `rc=0`
   `sudo show-audit <client> | head -20` → the DRAFT banner
   `sudo run-client-audit <client> --list --json` → `{"audits": [...], "status": "ok"}`
8. Registering a NEW client from now on also creates
   `sudo install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/vaults/<client>` (replaces the
   data/vaults step of "Ads audits on the box" step 5). Offboarding removes
   `/var/lib/hermes/{vaults,reports,draft-out}/<client>` as well as `audit-data` and `audit-logs`.
```

- [ ] **Step 2: Edit the "Ads audits on the box" section's step 5** so its vault-creation line points at `/var/lib/hermes/vaults/<client>` (`10000:10000 0700`), with a note "(Option B part 1)". Update the README's secrets table: the Anthropic key's location becomes `/etc/hermes/.env.anthropic`, used by `ads-drafter` only. Add `vaults`, `reports` and `draft-out` to the README's path table.

- [ ] **Step 3: Run the full suites**

Run: `infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && node scripts/run-all-tests.js`
Expected: all pass.

- [ ] **Step 4: Commit, push and open the PR**

```bash
git add infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): BRING-UP + README for Option B part 1 (isolation and egress)"
git push -u origin HEAD
gh pr create --title "feat(hermes): Option B part 1 — client data out of the gateway; drafter behind an Anthropic-only proxy" --body "$(cat <<'EOF'
Implements spec docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md §4–§6 (PR 1 of 3).

- Vaults, reports and the transient draft move to /var/lib/hermes/{vaults,reports,draft-out}/<client>/ (never mounted into the gateway).
- The Opus draft runs in a one-shot ads-drafter (one client's vault and reports ro, uid 10000, read-only rootfs, no caps) on an internal network; egress-proxy allows only api.anthropic.com:443.
- The Anthropic key moves to /etc/hermes/.env.anthropic (root 0400), passed per run as -e.
- run-client-audit gains --json and --list (the broker contract for part 2); new tools: install-env-secret, migrate-client-data, show-audit.

Breaks the review-#5 binding by design. The box is not updated until parts 2 and 3 merge; review #6 follows.

Not exercised in CI: the real Anthropic call through the proxy (CI proves CONNECT reaches api.anthropic.com; no key is used).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: CI is green, including "Bind agreement (root, Linux, real proxy)".

---

## Self-review notes (done while writing)

- **Spec coverage:**
  - §4 → Tasks 2, 3, 4 and 7;
  - §5.1 and §5.2 → Tasks 1, 3 and 4;
  - §5.3 → Task 4 (the isolation check keeps reading the transient draft);
  - §6 (the Anthropic key file) → Tasks 4, 6 and 9;
  - §3.5 and the `--json` and `--list` contract → Task 5;
  - §2 `show-audit` → Task 8;
  - §10 PR 1 → Task 9.
- **Deferred to part 2:** the gateway secret (OpenRouter) and the retirement of `claude-auth-init`. **Deferred to part 3:** the review tooling.
- **Consistent names:** `VAULTS`, `REPORTS`, `DRAFT_OUT`, `ANTHROPIC_CRED`, `stop_proxy`, `step_class`, `json_result`, `L.list_audit_ts` and `L.TS_RE` are used identically in Tasks 2, 4, 5 and 8.
