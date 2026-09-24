# F19 — Container-Scoped Calls Target Only Ads-Mutator Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Docker proxy forwards a container-scoped call (inspect, start, attach, wait, delete) only when the target is an ads-mutator run, so a compromised broker can no longer read the gateway's environment or act on any other container.

**Architecture:** The grammar narrows container ids to exactly 64 lowercase hex. After `decide()` allows a request and before any byte goes upstream, `_handle` asks dockerd about the target on a separate connection (`lookup_target`, stdlib `http.client`), and forwards only if the pure `is_mutator_shaped` finds the pinned image **and** the pinned entrypoint. Stateless, per request, fail-closed.

**Tech Stack:** Python 3 stdlib only (`http.client`, `json`, `re`, `socket`, `socketserver`); `unittest`; GitHub Actions Linux job with real dockerd; systemd on the box.

**Spec:** `docs/superpowers/specs/2026-09-24-f19-container-scope-design.md` (approved 2026-09-24). Read it before any task.

## Global Constraints

- **Mutation stays disabled. The kill switch is ABSENT and nothing in this plan creates it.**
- Stdlib only — `bin/docker-create-proxy.py` may not grow a dependency.
- **Never widen the allow-list to make anything pass.** A refusal is a refusal; find what the real client sent first.
- **Never run `docker compose config`; never read or print `.env`;** never quote a credential value.
- **Never edit a tracked file to run a firing control.** Controls run on scratch copies in a temp dir (recipe in Task 5).
- **Stage by explicit path only.** Never `git add -A`, `.`, or `commit -a`. Never stage `.project-brain/`, `evals/`, `CLAUDE.md`, `.obsidian/`, `infra/hermes-agent/CLAUDE.md`, `__pycache__/`.
- Required CI job names gate by NAME — never rename `Bind agreement (root, Linux, real proxy)` or `Test suites (node + hermes bin)`.
- Refusal reasons are **fixed strings**; nothing from an inspect reply is ever relayed, logged, or kept.
- `LOOKUP_UA = "hermes-docker-create-proxy-target-check"`; `LOOKUP_TIMEOUT = 5` (seconds, per socket operation).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- PR numbers, CI run ids and executed counts are written **only from real runs**.

## Review Focus

1. **Real dockerd may answer the inspect chunked** (large JSON bodies usually are) — the lookup must parse a chunked 200 as a normal reply. Pinned in Task 4 (`test_a_chunked_reply_is_read`).
2. **An unconfigured proxy** (`PINNED_IMAGE is None`) facing a doc with no `Image` must refuse, not match `None == None`. Pinned in Task 3 (`test_an_unconfigured_proxy_refuses_everything`).
3. **Compose's three parallel connections** (attach, start, wait) each doing their own lookup at once must all be forwarded. Pinned in Task 5 (`test_compose_s_three_parallel_connections_all_pass`).
4. **A lookup error nobody foresaw** (e.g. `RecursionError` from deeply nested JSON, a garbled status line) must become a refusal, not a crashed handler thread. Pinned in Task 4 (`test_deeply_nested_json_is_refused`, `test_a_garbled_status_line_is_refused`).
5. **A real id-scoped path carries a query string and a version prefix** (`/v1.55/containers/<id>/wait?condition=removed`, `…/attach?stderr=1&stdin=1&stdout=1&stream=1`, `DELETE …?force=1`) — `container_target` must still extract the id. Pinned in Task 3 (`test_container_target_extracts_the_full_id`).

---

## File Map

| File | Change | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/docker-create-proxy.py` | Modify | `_CID` grammar; `container_target`, `is_mutator_shaped` (pure); `_UnixHTTPConnection`, `lookup_target` (I/O); `_handle` wiring; header docstring |
| `infra/hermes-agent/bin/docker-create-proxy.test.py` | Modify | id constants and inspect docs; grammar, helper and lookup tests; `_KeepAliveFakeMixin` (extracted from `TestAttachPassThrough`); `TestTargetCheck`; fakes answer lookups |
| `infra/hermes-agent/deploy/bind-agreement-integration.test.py` | Modify | `TestTheTargetCheck` — decoy container on real dockerd |
| `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` | Modify | F19 → fixed; open items |
| `infra/hermes-agent/deploy/BRING-UP.md` | Modify | gate list drops F19; "After pulling F19" block |

Run the proxy suite with `python3 infra/hermes-agent/bin/docker-create-proxy.test.py [Class ...] -v` and all bin suites with `infra/hermes-agent/bin/run-bin-tests.sh`.

---

### Task 1: Linux CI decoy test, shown RED on today's proxy

The test comes **first** so CI can show it failing against the current proxy. CI runs only on pull requests to `main`, so this task ends by opening a **draft PR**.

**Files:**
- Modify: `infra/hermes-agent/deploy/bind-agreement-integration.test.py` (constants after `ATTESTED_2`, ~:60; new class after `TestTheBrokerPath`, before `class TestFiringControls`)

**Interfaces:**
- Consumes: `BrokerPath` (`self.sock`, `self.log`), `run`, `root_env`, `broker_env`, `log_after`, `BROKER`, `IMAGE` — all existing in this file.
- Produces: `PROBE` (str), `TARGET_REFUSED` (compiled regex), `TestTheTargetCheck`.

- [ ] **Step 1: Add the probe and the log pattern** after the `ATTESTED_2 = …` line:

```python
# F19: one raw request through the proxy socket, run AS hermes-broker (the adversary the
# proxy contains). Prints the whole response. A plain socket, not curl: no new dependency.
PROBE = r'''
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(10)
s.connect(sys.argv[1])
s.sendall(("%s %s HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n"
           % (sys.argv[2], sys.argv[3])).encode())
out = b""
while True:
    try:
        d = s.recv(65536)
    except OSError:
        break
    if not d:
        break
    out += d
sys.stdout.write(out.decode("latin1"))
'''
# F19: the refusal the target check logs for a container that is not an ads-mutator run.
TARGET_REFUSED = re.compile(r"DENY (?:GET|DELETE) /v1\.55/containers/[0-9a-f]{64}[^ ]* "
                            r"\(target is not an ads-mutator run: entrypoint mismatch\)")
```

- [ ] **Step 2: Add the test class** immediately before `class TestFiringControls(BrokerPath):`:

```python
class TestTheTargetCheck(BrokerPath):
    """F19 (spec 2026-09-24): through the real proxy and the real dockerd, a container that is
    NOT an ads-mutator run — the same image with a different entrypoint, exactly the gateway's
    situation on the box — can be neither inspected nor deleted by the broker. The decoy
    carries a sentinel in its environment in place of the gateway's API keys."""

    def test_a_non_mutator_container_cannot_be_inspected_or_deleted(self):
        name = "hermes-f19-decoy"
        run(["docker", "rm", "-f", name], env=root_env())
        r = run(["docker", "run", "-d", "--name", name, "--entrypoint", "sleep",
                 "-e", "F19_DECOY=F19-SENTINEL", IMAGE, "600"], env=root_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.addCleanup(run, ["docker", "rm", "-f", name], env=root_env())
        cid = r.stdout.strip()
        self.assertRegex(cid, r"^[0-9a-f]{64}$")
        offset = os.path.getsize(self.log)
        env = broker_env(self.sock)
        inspect = run(BROKER + ["python3", "-c", PROBE, self.sock, "GET",
                                "/v1.55/containers/%s/json" % cid], env=env, timeout=60)
        delete = run(BROKER + ["python3", "-c", PROBE, self.sock, "DELETE",
                               "/v1.55/containers/%s?force=1" % cid], env=env, timeout=60)
        plog = log_after(self.log, offset)
        # The security properties FIRST: the decoy's environment never reached the broker, and
        # the decoy is still running.
        self.assertNotIn("F19-SENTINEL", inspect.stdout,
                         "the broker read a non-mutator container's environment")
        running = run(["docker", "inspect", "-f", "{{.State.Running}}", cid], env=root_env())
        self.assertEqual(running.stdout.strip(), "true", "the broker deleted a non-mutator container")
        self.assertTrue(inspect.stdout.startswith("HTTP/1.1 403"), inspect.stdout[:200])
        self.assertTrue(delete.stdout.startswith("HTTP/1.1 403"), delete.stdout[:200])
        self.assertEqual(len(TARGET_REFUSED.findall(plog)), 2, plog)
```

- [ ] **Step 3: Syntax-check locally** (it SKIPs on Darwin; the proof is CI):

Run: `python3 -m py_compile infra/hermes-agent/deploy/bind-agreement-integration.test.py && python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py`
Expected: no compile error; `bind-agreement: SKIPPED — not Linux`.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/deploy/bind-agreement-integration.test.py
git commit -m "test(hermes): F19 — a non-mutator container through the real proxy (RED on today's proxy)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5 (controller, not the implementer): push and open a draft PR, then read RED**

```bash
git push -u origin spec/f19-container-scope
gh pr create --draft --base main --title "F19: container-scoped calls may target only ads-mutator runs" \
  --body "Draft. First push carries only the F19 Linux test, to show it RED on today's proxy. Spec: docs/superpowers/specs/2026-09-24-f19-container-scope-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Wait for the run. Expected on the `Bind agreement (root, Linux, real proxy)` job: **FAIL**, with `test_a_non_mutator_container_cannot_be_inspected_or_deleted` failing on `the broker read a non-mutator container's environment`, and `bind-agreement: executed 7, skipped 0, failures 1`. The other six pass. **Any other failure is a finding — stop.** Record the run id for the PR body.

---

### Task 2: The grammar — container ids are exactly 64 lowercase hex

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py:85-108` (`_ID`, `_ATTACH_RE`, `ALLOWED`)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.test.py` (constants after `PX = _load(...)`, `TestPositiveControls`, `TestEndpointAllowList`, `TestAttachHelpers`, `TestAttachPassThrough.test_route_b_…`, and every short container id in the file)

**Interfaces:**
- Produces: `PX._CID` (str regex `[0-9a-f]{64}`); test constants `MUT_ID`, `GW_ID` (64-hex str).

- [ ] **Step 1: Add the id constants** to the test file immediately after `PX = _load("docker_create_proxy", "docker-create-proxy.py")`:

```python
# F19: container ids are FULL 64-hex ids — the only form the real rail sends (box journal,
# 2026-09-24). MUT_ID is an ads-mutator run; GW_ID stands for the Hermes gateway.
MUT_ID = "deadbeef" * 8
GW_ID = "0badc0de" * 8
```

- [ ] **Step 2: Replace every short container id in the test file with `MUT_ID`'s value.** Mechanical, on the tracked test file (this is the change itself, not a firing control):

```bash
python3 - <<'EOF'
import re
p = "infra/hermes-agent/bin/docker-create-proxy.test.py"
s = open(p).read()
s2, n = re.subn(r"/containers/(?:deadbeef|abc123|abc)(?=[/?\" ])", "/containers/" + "deadbeef" * 8, s)
open(p, "w").write(s2)
print("replaced", n)
EOF
grep -nE "/containers/(deadbeef|abc123|abc)([/?\" ]|$)" infra/hermes-agent/bin/docker-create-proxy.test.py
```

Expected: `replaced` followed by a count > 20; the grep prints **nothing**. (`container:abc123` in the NetworkMode test and `20260101-000000-deadbeef` in the changeset are not `/containers/…` and must stay.)

- [ ] **Step 3: Write the failing grammar tests.** Add to `TestEndpointAllowList`:

```python
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
```

Add to `TestAttachHelpers`:

```python
    def test_an_attach_needs_a_full_id(self):
        self.assertFalse(PX._is_attach("POST", "/v1.55/containers/abc/attach?stream=1"))
        self.assertTrue(PX._is_attach("POST", "/v1.55/containers/%s/attach?stream=1" % MUT_ID))
```

- [ ] **Step 4: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestEndpointAllowList TestAttachHelpers -v`
Expected: FAIL — `test_container_scoped_entries_refuse_anything_but_a_full_id` (`… was allowed`), `test_a_trailing_slash_after_the_id_is_refused`, `test_an_attach_needs_a_full_id`. `test_the_list_and_image_inspect_are_unchanged` passes (it is a positive control).

- [ ] **Step 5: Implement.** In `docker-create-proxy.py` replace

```python
_ID = r"[A-Za-z0-9_.-]+"
```

with

```python
_ID = r"[A-Za-z0-9_.-]+"               # image names only: GET /images/<name>/json
# F19 (spec 2026-09-24): every container-scoped entry takes a FULL container id — 64
# lowercase hex, measured as the only form the real rail sends (box journal, 2026-09-24).
# A name or a short prefix could come to mean a different container between the target
# check and the forward; a full id cannot.
_CID = r"[0-9a-f]{64}"
```

In `_ATTACH_RE` and in the four other container-scoped `ALLOWED` entries, replace `_ID` with `_CID`, so the block reads:

```python
_ATTACH_RE = re.compile(_V + r"/containers/" + _CID + r"/attach")
```

```python
    ("POST",   re.compile(_V + r"/containers/" + _CID + r"/start")),
    ("POST",   _ATTACH_RE),
    ("POST",   re.compile(_V + r"/containers/" + _CID + r"/wait")),
    ("GET",    re.compile(_V + r"/containers/" + _CID + r"/json")),
    ("DELETE", re.compile(_V + r"/containers/" + _CID)),
```

The `/images/` entry keeps `_ID`.

- [ ] **Step 6: Fix the one F18 test whose premise changed.** `TestAttachPassThrough.test_route_b_a_container_literally_named_attach` sends `DELETE /v1.55/containers/attach`, which `decide()` now refuses outright (`attach` is not a 64-hex id). Replace its body with:

```python
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
```

- [ ] **Step 7: Run the whole proxy suite**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py`
Expected: `OK`. If a socket test fails because a request now names a short id, Step 2 missed it — fix the id, never the grammar.

- [ ] **Step 8: Firing control** — on a scratch copy, put `_ID` back in the start entry; the new test must fail:

```bash
S=$(mktemp -d) && cp infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py "$S/"
python3 - "$S/docker-create-proxy.py" <<'EOF'
import sys; p = sys.argv[1]; s = open(p).read()
a = 'r"/containers/" + _CID + r"/start"'; assert s.count(a) == 1
open(p, "w").write(s.replace(a, 'r"/containers/" + _ID + r"/start"'))
EOF
python3 "$S/docker-create-proxy.test.py" TestEndpointAllowList 2>&1 | tail -3; rm -rf "$S"
```

Expected: `FAILED (failures=1)`.

- [ ] **Step 9: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "fix(hermes): F19 — container-scoped entries take only a full 64-hex id

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The pure helpers — `container_target` and `is_mutator_shaped`

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (new block immediately before `def _handle`)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.test.py` (inspect docs after `GW_ID`; new class `TestTargetHelpers` after `TestAttachHelpers`)

**Interfaces:**
- Consumes: `_V`, `_CID`, `_path_only`, `ALLOWED`, `PINNED_IMAGE`, `PINNED_ENTRYPOINT`.
- Produces:
  - `container_target(path: str) -> str | None`
  - `is_mutator_shaped(doc: object, cid: str) -> tuple[bool, str]` — reasons: `"target is an ads-mutator run"` (ok) or `"target is not an ads-mutator run: " + one of "proxy not configured" | "malformed inspect" | "id mismatch" | "image mismatch" | "entrypoint mismatch"`
  - Test fixtures: `MUTATOR_DOC`, `GATEWAY_DOC`, `SENTINEL`, `_mut(**config_over) -> dict`

- [ ] **Step 1: Add the inspect fixtures** to the test file after `GW_ID`:

```python
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
```

- [ ] **Step 2: Write the failing tests** — new class after `TestAttachHelpers`:

```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestTargetHelpers -v`
Expected: ERROR on every test — `AttributeError: module 'docker_create_proxy' has no attribute 'container_target'` (or `is_mutator_shaped`).

- [ ] **Step 4: Implement** — insert immediately before `def _handle(conn, upstream_path):`:

```python
# ---- F19 (spec 2026-09-24): a container-scoped call may target only an ads-mutator run ----

# PREFIX match, deliberately wider than ALLOWED: every allowed path that BEGINS with a
# container id is checked, including any id-scoped entry added later. The list call
# /containers/json never matches (`json` is not 64 hex).
_TARGET_RE = re.compile(_V + r"/containers/(" + _CID + r")(?=/|\Z)")
_NOT_MUTATOR = "target is not an ads-mutator run: "


def container_target(path):
    """The full container id a request acts on, or None when it names no container."""
    p = _path_only(path)
    if p is None:
        return None
    m = _TARGET_RE.match(p)
    return m.group(1) if m else None


def is_mutator_shaped(doc, cid):
    """Pure. (True, reason) only when dockerd's inspect of `cid` shows the pinned image AND
    the pinned entrypoint — the two values create already enforces. The image alone is not
    enough: claude-auth-init, the gateway and ads-mutator all run `hermes-agent-claude`.
    Reasons are fixed strings; nothing from `doc` is ever quoted, because the gateway's
    inspect carries its API keys."""
    if PINNED_IMAGE is None:
        return False, _NOT_MUTATOR + "proxy not configured"
    if not isinstance(doc, dict):
        return False, _NOT_MUTATOR + "malformed inspect"
    if doc.get("Id") != cid:
        return False, _NOT_MUTATOR + "id mismatch"
    cfg = doc.get("Config")
    if not isinstance(cfg, dict):
        return False, _NOT_MUTATOR + "malformed inspect"
    if cfg.get("Image") != PINNED_IMAGE:
        return False, _NOT_MUTATOR + "image mismatch"
    if cfg.get("Entrypoint") != PINNED_ENTRYPOINT:
        return False, _NOT_MUTATOR + "entrypoint mismatch"
    return True, "target is an ads-mutator run"
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestTargetHelpers -v`
Expected: 9 tests, `OK`.

- [ ] **Step 6: Firing controls** — each on a fresh scratch copy; each must print `FAILED`:

```bash
fire() {  # $1 = old text (must occur once), $2 = new text, $3 = test class
  S=$(mktemp -d) && cp infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py "$S/"
  python3 - "$S/docker-create-proxy.py" "$1" "$2" <<'EOF'
import sys; p, a, b = sys.argv[1:]; s = open(p).read(); assert s.count(a) == 1, a
open(p, "w").write(s.replace(a, b))
EOF
  python3 "$S/docker-create-proxy.test.py" "$3" 2>&1 | tail -1; rm -rf "$S"
}
fire '    if cfg.get("Entrypoint") != PINNED_ENTRYPOINT:' '    if False:' TestTargetHelpers      # image-only
fire '    if PINNED_IMAGE is None:' '    if False:' TestTargetHelpers                              # no config guard
fire '(?=/|\Z)' '' TestTargetHelpers                                                              # no boundary
```

Expected: three lines, each `FAILED (failures=…)`.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "feat(hermes): F19 — container_target and is_mutator_shaped (pure)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The lookup — `lookup_target` over a fresh unix-socket connection

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (imports line ~83; new block after `is_mutator_shaped`)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.test.py` (helpers after `_mut`; new class `TestLookupTarget` after `TestTargetHelpers`)

**Interfaces:**
- Consumes: `MAX_BODY` (module global, read at call time), `json`, `socket`.
- Produces:
  - `LOOKUP_TIMEOUT = 5`, `LOOKUP_UA = "hermes-docker-create-proxy-target-check"` (module globals; tests may reassign `LOOKUP_TIMEOUT` and `MAX_BODY` and restore them)
  - `lookup_target(upstream_path: str, cid: str) -> tuple[object | None, str]` — `(doc, "")` on 200; `(None, "target not found")` on 404; `(None, "target lookup failed")` on anything else
  - Test helpers: `HANG` (sentinel object), `_json_200(doc) -> bytes`, `_one_shot_upstream(tc, reply) -> (path, got)`

- [ ] **Step 1: Add the test helpers** after `_mut`:

```python
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
```

- [ ] **Step 2: Write the failing tests** — new class after `TestTargetHelpers`:

```python
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

    def test_deeply_nested_json_is_refused(self):
        """Review focus: RecursionError is not a ValueError — it must still be a refusal."""
        body = b"[" * 100000 + b"]" * 100000
        (doc, why), _ = self._lookup(b"HTTP/1.1 200 OK\r\nContent-Length: "
                                     + str(len(body)).encode() + b"\r\n\r\n" + body)
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestLookupTarget -v`
Expected: ERROR on every test — `AttributeError: … has no attribute 'lookup_target'` (or `LOOKUP_UA`).

- [ ] **Step 4: Implement.** Change the import line to:

```python
import argparse, http.client, json, os, re, socket, socketserver, sys, threading
```

Insert immediately after `is_mutator_shaped`:

```python
LOOKUP_TIMEOUT = 5          # seconds, per socket operation; tests lower it
LOOKUP_UA = "hermes-docker-create-proxy-target-check"


class _UnixHTTPConnection(http.client.HTTPConnection):
    """http.client over an AF_UNIX socket. http.client does the response framing
    (Content-Length and chunked) — exactly the code this file must not hand-roll twice."""

    def __init__(self, unix_path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._unix_path = unix_path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self._unix_path)
        except BaseException:
            s.close()
            raise
        self.sock = s


def lookup_target(upstream_path, cid):
    """Ask dockerd what `cid` is, on a FRESH connection — never the client's, whose keep-alive
    stream the relay is framing (the F18 bug class). `cid` has already fullmatched 64 hex and
    the path is unversioned, so nothing the client sent reaches this request.

    Returns (doc, "") on 200, (None, "target not found") on 404, and (None, "target lookup
    failed") on anything else. `except Exception` is deliberate and confined to this unit:
    an error nobody foresaw must become a refusal, never a crash someone later "fixes" by
    skipping the check. The reply is returned to the caller only; it is never logged."""
    c = _UnixHTTPConnection(upstream_path, LOOKUP_TIMEOUT)
    try:
        c.request("GET", "/containers/%s/json" % cid, headers={"User-Agent": LOOKUP_UA})
        r = c.getresponse()
        if r.status == 404:
            return None, "target not found"
        if r.status != 200:
            return None, "target lookup failed"
        raw = r.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return None, "target lookup failed"
        return json.loads(raw.decode("utf-8")), ""
    except Exception:
        return None, "target lookup failed"
    finally:
        c.close()
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestLookupTarget -v`
Expected: 11 tests, `OK`.

- [ ] **Step 6: Firing control** — narrow the catch; the unforeseen-error tests must fail (define `fire` as in Task 3 Step 6 if this is a new shell):

```bash
fire '    except Exception:
        return None, "target lookup failed"' '    except OSError:
        return None, "target lookup failed"' TestLookupTarget
```

Expected: `FAILED (errors=…)` (`test_bad_json_fails`, `test_deeply_nested_json_is_refused`, `test_a_garbled_status_line_is_refused` raise).

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "feat(hermes): F19 — lookup_target asks dockerd on a fresh connection, fails closed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wire the check into `_handle`; the socket tests; migrate the fakes

**Security-critical — review on opus.**

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (`_handle`, the `ok, reason = decide(...)` block at ~:526-531)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.test.py` (`_lookup_reply` helper; `TestPlumbing.setUp`'s fake; `TestAttachPassThrough` → `_KeepAliveFakeMixin`; new `TestTargetCheck`)

**Interfaces:**
- Consumes: `container_target`, `lookup_target`, `is_mutator_shaped`, `LOOKUP_UA`, `LOOKUP_TIMEOUT`, `MAX_BODY` (Tasks 3–4); `HANG`, `_json_200`, `MUTATOR_DOC`, `GATEWAY_DOC`, `MUT_ID`, `GW_ID`, `SENTINEL` (test file).
- Produces: `_lookup_reply(head, table) -> bytes | HANG | None`; `_KeepAliveFakeMixin` (attributes `upstream_raw`, `upgraded_rx`, `heads`, `attach_reply`, `inspect_table`, `li_path`; methods `_connect`, `_recv_until`, `_send_then_smuggle`); `TestTargetCheck`.

- [ ] **Step 1: Add `_lookup_reply`** after `_one_shot_upstream`:

```python
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
```

Add `re` to the test file's import line: `import importlib.util, itertools, json, os, re, socket, sys, time, unittest`.

- [ ] **Step 2: `TestPlumbing`'s fake answers lookups.** In `TestPlumbing.setUp`, inside `fake_upstream`, replace

```python
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
```

with

```python
                # F19: the proxy's target-check lookup arrives on its own connection first.
                reply = _lookup_reply(data, {MUT_ID: MUTATOR_DOC})
                conn.sendall(reply if reply is not None
                             else b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
```

- [ ] **Step 3: Extract `TestAttachPassThrough`'s fake into a mixin.** Rename the class line and move its class attributes, `setUp`, `_connect`, `_recv_until` and `_send_then_smuggle` into a new mixin placed directly above it; `TestAttachPassThrough` keeps its docstring and every `test_` method. The mixin's `setUp` is the existing one with **three** additions marked `# F19`:

```python
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
```

`_connect`, `_recv_until` and `_send_then_smuggle` move into the mixin **unchanged**. Then:

```python
class TestAttachPassThrough(_KeepAliveFakeMixin, unittest.TestCase):
    """F18 (spec 2026-09-23). …(existing docstring, unchanged)…"""
    # every existing test_ method, unchanged
```

(The `ATTACH` constant already carries `MUT_ID` after Task 2's replacement; the version above just spells it with the constant.)

- [ ] **Step 4: Run the existing suites — the refactor must be behaviour-neutral**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py`
Expected: `OK`. (No wiring yet: the fakes answer lookups nobody sends.)

- [ ] **Step 5: Write the failing socket tests** — new class after `TestAttachPassThrough`:

```python
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

    def _await_client_head(self, method, cid, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(h.startswith(method.encode()) for h in self._client_heads_naming(cid)):
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
                self.assertTrue(self._await_client_head(method, MUT_ID),
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
```

- [ ] **Step 6: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestTargetCheck -v`
Expected: FAIL — `test_every_container_scoped_call_at_the_gateway_is_refused` (`a refused request reached the upstream`), the keep-alive test, `test_every_lookup_failure_is_a_refusal`, `test_the_log_carries_…`. The mutator-forwarded and parallel tests pass (positive controls).

- [ ] **Step 7: Implement.** In `_handle`, replace

```python
            ok, reason = decide(method, path, body)
            print("%s %s %s (%s)" % ("ALLOW" if ok else "DENY", method, path, reason),
                  file=sys.stderr)
```

with

```python
            ok, reason = decide(method, path, body)
            if ok:
                # F19 (spec 2026-09-24): a container-scoped call may target only an
                # ads-mutator run. Checked per REQUEST — a kept-alive connection can name a
                # different id each time — and before any byte of it goes upstream. ALLOW is
                # printed only after this, so it always means "forwarded".
                cid = container_target(path)
                if cid:
                    doc, reason = lookup_target(upstream_path, cid)
                    ok, reason = (is_mutator_shaped(doc, cid) if doc is not None
                                  else (False, reason))
            print("%s %s %s (%s)" % ("ALLOW" if ok else "DENY", method, path, reason),
                  file=sys.stderr)
```

Nothing else in `_handle` changes.

- [ ] **Step 8: Run the whole proxy suite, then every bin suite**

Run: `python3 infra/hermes-agent/bin/docker-create-proxy.test.py && infra/hermes-agent/bin/run-bin-tests.sh`
Expected: `OK`; `hermes bin: 31/31 suites passed`.

- [ ] **Step 9: Firing controls** — define `fire` as in Task 3 Step 6 if this is a new shell. Each must print `FAILED`:

```bash
fire '                if cid:' '                if False and cid:' TestTargetCheck                  # drop the check
fire '    m = _TARGET_RE.match(p)
    return m.group(1) if m else None' '    return None' TestTargetCheck                        # no target
fire '    if cfg.get("Entrypoint") != PINNED_ENTRYPOINT:' '    if False:' TestTargetCheck         # image-only
fire '            ok, reason = decide(method, path, body)
            if ok:' '            ok, reason = decide(method, path, body)
            print("ALLOW %s %s (pre-check)" % (method, path), file=sys.stderr)
            if ok:' TestTargetCheck                                                             # ALLOW before check
fire '                if cid:' '                if cid and up is None:' TestTargetCheck           # once per connection
```

Expected: five lines, each `FAILED (…)`.

- [ ] **Step 10: Loop the socket classes 30×**

```bash
for i in $(seq 30); do
  python3 infra/hermes-agent/bin/docker-create-proxy.test.py TestTargetCheck TestAttachPassThrough TestPlumbing TestLookupTarget >/dev/null 2>&1 || echo "FAIL run $i"
done; echo "loop done"
```

Expected: only `loop done`. Any `FAIL run N` is a flake to diagnose (rerun that class verbose) before continuing — never retry until green.

- [ ] **Step 11: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "fix(hermes): F19 — container-scoped calls are forwarded only to ads-mutator runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6 (controller): Push, CI on the PR

- [ ] **Step 1: Push**

```bash
git push
```

- [ ] **Step 2: Read the counts on the PR's run** (`gh run list --branch spec/f19-container-scope -L 1`, then `gh run view <id> --log | grep -E "executed [0-9]+, skipped"`)

Expected:
- `bind-agreement: executed 7, skipped 0, failures 0, errors 0` — the Compose rail still passes (`ALLOW` create, `UPGRADE … (101)` attach) **and** the decoy is refused.
- `layout-integration: executed 30, skipped 0`.
- `Test suites (node + hermes bin)`: node 22/22 · hermes bin 31/31.

A `target` DENY for the mutator's own calls in the bind-agreement log is a **finding**: stop, read what dockerd's inspect of the real mutator container contains (Image/Entrypoint only — never the environment), and bring it back. Never loosen the check.

- [ ] **Step 3: Whole-branch review on opus**, then ONE fix wave if it finds anything; re-run Task 5 Steps 8–10 after the fix wave.

---

### Task 7: Records

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (header docstring, the paragraph after the measured endpoint list, ~:41-50)
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (F19 section ~:413; open items ~:459; "Still open" ~:256)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (gate paragraph ~:450; new block after "After pulling F18")

- [ ] **Step 1: Header docstring.** After the paragraph ending `Adding an endpoint is a re-measurement, never a guess.` (the second one, ~:50) add:

```
F19 (spec 2026-09-24): every container-scoped entry takes a FULL 64-hex id, and before such a
call is forwarded the proxy asks dockerd, on its own connection, what the target is. Only a
container with the pinned image AND the pinned entrypoint — an ads-mutator run — passes. The
gateway shares the image, so the image alone would not do. The list call /containers/json is
left open on purpose: it reveals no environment, and every id it reveals is now refused.
```

- [ ] **Step 2: Findings record.** Retitle `### F19: container-scoped calls accept any container id (recorded, not fixed)` to `### F19: container-scoped calls accept any container id — fixed (PR #<n>)` and append to the section (fill `<n>` and run ids from the real runs only):

```markdown
**Assessed 2026-09-24: a real gap; it gated the kill switch.** Two allowed calls reached the
gateway's environment: `GET /containers/json` for its id, then `GET /containers/<id>/json`.

**Fixed (PR #<n>, spec `2026-09-24-f19-container-scope-design.md`).** Container-scoped entries take
only a full 64-hex id — measured as the only form the rail sends (box journal, 2026-09-24:
`3 GET /json`, `2 POST /attach`, `1 POST /start`, `1 POST /wait`, all 64 hex). Before forwarding,
the proxy inspects the target on its own connection and allows only the pinned image **and** the
pinned entrypoint. CI: RED on today's proxy (run <red-run-id>: the decoy's sentinel was read),
then `bind-agreement: executed 7, skipped 0` on the PR (run <pr-run-id>) and the merge commit
(run <merge-run-id>). **Residual, accepted:** the list call still enumerates containers (names,
labels, image, mounts — no environment); every id it reveals is now refused.
```

In "Open items, in order", replace item 8 with `8. F19: container-scoped calls accept any container id — fixed (PR #<n>).` In the "Still open" sentence at ~:256, drop F19 so it names only §6 part B.

- [ ] **Step 3: BRING-UP.** In the gate paragraph (~:450), replace `audit-log truncation (§6 part B), and\nF19 — container-scoped calls accept any container id (including inspect, which exposes a\ncontainer's environment) — until it is assessed (findings record).` with `audit-log truncation (§6 part B). (F19 — container-scoped calls accepted any container id — is fixed; see "After pulling F19".)` Then add after the "After pulling F18" block:

````markdown
**After pulling F19** — no unit changes; the proxy runs its script from the repo. **Before
pulling**, see today's gap with the instrument that will prove it closed (prints only a status
code, never a body):

```bash
command -v curl                                                    # a path
GW=$(sudo docker ps -q --no-trunc --filter label=com.docker.compose.service=hermes-agent); echo "${#GW}"   # 64
sudo -u hermes-broker curl -s -o /dev/null -w '%{http_code}\n' \
  --unix-socket /run/hermes/docker-proxy.sock "http://d/v1.55/containers/$GW/json"          # 200 — the gap
```

Then:

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
systemctl is-active hermes-docker-proxy hermes-broker                                    # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker                            # 0, 0
sudo -u hermes-broker curl -s -o /dev/null -w '%{http_code}\n' \
  --unix-socket /run/hermes/docker-proxy.sock "http://d/v1.55/containers/$GW/json"          # 403
sudo journalctl -u hermes-docker-proxy --since "-5 min" --no-pager \
  | grep -c 'target is not an ads-mutator run: entrypoint mismatch'                          # 1 per probe run since the restart
```

Then re-run Phase 6 and check the proxy journal:

```bash
sudo journalctl -u hermes-docker-proxy --since "-2 min" --no-pager | grep -E 'ALLOW POST .*/containers/create|UPGRADE|DENY'
```

Expected: one `ALLOW POST …/containers/create…`, one `UPGRADE POST …/attach… (101)`, and **no**
`DENY` line. A `target` DENY for the mutator's own calls is a finding — never widen the check.
````

- [ ] **Step 4: Run the suites** (the header docstring is inside a tracked `.py`)

Run: `node scripts/run-all-tests.js | tail -1 && infra/hermes-agent/bin/run-bin-tests.sh | tail -1`
Expected: `22/22 suites passed`; `hermes bin: 31/31 suites passed`.

- [ ] **Step 5: Commit, push, and update the PR body** with the RED run id, the PR run's counts, and the review outcome.

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md infra/hermes-agent/deploy/BRING-UP.md
git commit -m "docs(hermes): F19 fixed — findings, BRING-UP rollout, proxy header

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 6 (controller):** mark the PR ready; **ask the operator before merging**. After merge, read the merge commit's run: `bind-agreement: executed 7, skipped 0`; `layout-integration: executed 30, skipped 0`. Fill `<merge-run-id>` in a follow-up if the findings text was written before the merge.

- [ ] **Step 7:** a brain session-log entry (brain-capture: `[decision] F19 fixed …`). **Do not stage `.project-brain/`.**

---

### Task 8 (operator-run): Box rollout

Give the operator the "After pulling F19" block from BRING-UP **exactly**, with the expected result on each line, and ask them to stop at the first mismatch and paste the output. Check the kill switch first:

```bash
sudo test ! -e /var/lib/hermes/governance/control/mutation-enabled && echo "kill switch absent"
```

Record the result (`200 → 403`, the journal count, Phase 6's `ALLOW`/`UPGRADE (101)`/no DENY) in a small docs PR against the findings record and BRING-UP, same process as PR #51.
