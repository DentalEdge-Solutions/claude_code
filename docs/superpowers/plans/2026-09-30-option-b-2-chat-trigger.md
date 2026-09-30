# Option B, part 2 — The chat trigger: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hermes, in `hermes chat`, can run, check and list client audits through three MCP tools. Each request goes gateway → spool → sandboxed broker → job file → root runner → `run-client-audit --json`, and Hermes receives a whitelisted result that carries no client content.

**Architecture:** One manifest per app (`registry/apps/ads-audit.json`) declares everything specific to the app. `app_lib.py` holds the shared contract (manifest, request, job, done and result schemas, the ledger and atomic writes).
- `hermes-app-mcp.py` (in the gateway) writes requests.
- `hermes-app-broker.py` (systemd `hermes-app-broker@ads-audit`, an unprivileged user, `NoNewPrivileges`, no capabilities, no network) validates, enforces quota and the kill switch, and writes job files.
- `hermes-app-runner.py` (a root oneshot started by `hermes-app-runner@ads-audit.path`) executes the manifest's fixed argv and writes done files.
- The broker maps done files to results.
- The gateway loses `claude-auth-init` and gains an OpenRouter key, the MCP config and the `ads-audits` skill.

**Tech Stack:** Python 3 stdlib only, systemd (templated units and a `.path` unit), Docker Compose, the MCP stdio protocol (JSON-RPC 2.0, newline-delimited).

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` (§2, §3, §6, §7, §10 PR 2). **Prerequisite:** part 1 (`2026-09-30-option-b-1-isolation-and-egress.md`) is merged. This part consumes `run-client-audit --json/--list` and `install-env-secret.py`.

## Global Constraints

- **Code:** Python stdlib only in `infra/hermes-agent/bin/`. Tests are `bin/<name>.test.py`. `infra/hermes-agent/bin/run-bin-tests.sh` must end `N/N suites passed` after every task. `python3 infra/hermes-agent/deploy/units.test.py` must pass after Task 8.
- **Identifiers:** slugs match `governance_lib.SLUG_RE`, request and job ids match `governance_lib.REQUEST_ID_RE`, and spool filenames match `^[0-9a-f-]{36}\.json$`. There is exactly one definition of each: import it, never restate it.
- **Host paths** (with `<app>` = `ads-audit`, user `hermes-app-ads-audit`):
  - spool: `/var/lib/hermes/spool/apps/<app>/{requests,results}`, which the gateway sees as `/opt/data/spool/apps/<app>/…`;
  - state: `/var/lib/hermes/app-state/<app>/{state,jobs,running,done}`, plus `DISABLED`;
  - manifest: `/opt/hermes-agent/registry/apps/<app>.json`, which the gateway sees as `/opt/registry/apps/<app>.json`;
  - registry: `/var/lib/hermes/governance/registry/clients.json`.
- **Modes:**
  - `spool/apps` and `spool/apps/<app>`: `root:hermes 0750`; `requests`: `<user>:hermes 3770`; `results`: `<user>:hermes 2750`;
  - `app-state`: `root:root 0755`; `app-state/<app>`: `root:<user> 0750`; `state`, `jobs` and `done`: `<user>:<user> 0700`; `running`: `root:<user> 0750`;
  - spool files `0640`; done files `root:<user> 0640`.
- **Quotas** (per UTC day): `run` is 1 per client and 5 per box; `list` is 60 per box. A reservation counts whatever the outcome. `busy` releases it.
- **Result `status`** is one of `ok|refused|failed|busy`.
- **Result `reason`:**
  - `null` when ok;
  - from the broker: `bad_request`, `duplicate`, `inactive_client`, `quota`, `disabled`, `timeout`, `interrupted`, `internal`;
  - from `run-client-audit`: `precheck`, `busy`, or a step class (`collect`, `snapshot`, `read`, `proxy`, `draft`, `isolation`, `vault-write`).
- **Caps:** request files at most 1024 bytes; at most 64 requests per drain pass; requests older than 3600 s deleted unread; job files at most 512 bytes; done `stdout` at most 65536 bytes; results deleted after 7 days.
- **Timeouts:** the runner uses the manifest (`run` 1800 s, `list` 60 s). The MCP `run` waits 300 s and `list` 60 s. The MCP server `timeout` in the Hermes config is 360.
- **No free text from any step reaches Hermes.** Every result field is an enum, a number, a timestamp, a slug or a path matching a fixed regex.
- **Never print a customer id or credential value.** The journal gets one line per request: `request=<id> op=<op> client=<slug|-> status=<s> reason=<r>`.
- **Unchanged:** the mutation broker (`hermes-broker.service`), `spool_lib.py`, the mutation spool entries in `host_layout.LAYOUT`, and `CHECKLIST.md` (part 3).

## Review Focus

1. **A request filed while `DISABLED` exists, then `DISABLED` removed:** the request must stay refused. The refusal is final and the id is burned. Task 5 pins it.
2. **A box reboot mid-audit:** `running/` holds the job, and the broker's ledger has a reservation without a result. After the restart the runner writes `interrupted`, the broker maps it, and **nothing re-runs**. Task 7 (e2e) pins it.
3. **The same `request_id` filed twice** (Hermes retrying by rewriting the file) must not overwrite the first result. The duplicate is dropped with no second result file. Task 5.
4. **`run-client-audit` stdout that is valid JSON but out of contract** (an extra key, a `vault_path` for another client, a status that doesn't match rc) must become `failed: internal`, with nothing passed through. Task 2.
5. **A hostile gateway filling `requests/` with 10,000 files or a FIFO** must cost the broker bounded work per pass and never block it. Task 5.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/registry/apps/ads-audit.json` | create | the app manifest |
| `infra/hermes-agent/bin/app_lib.py` (+ `.test.py`) | create | manifest loader, schemas, result mapping, ledger, atomic write, path helpers |
| `infra/hermes-agent/bin/host_layout.py` (+ tests), `bin/init-host-layout.py` (+ tests) | modify | `app_layout(app)`, `plan_app`/`check_app`/`apply_app`; `init-host-layout --app` |
| `infra/hermes-agent/bin/hermes-app-mcp.py` (+ `.test.py`) | create | the stdio MCP server in the gateway |
| `infra/hermes-agent/bin/hermes-app-broker.py` (+ `.test.py`) | create | drain, admit, job, collect, recover |
| `infra/hermes-agent/bin/hermes-app-runner.py` (+ `.test.py`) | create | the root executor of the manifest argv |
| `infra/hermes-agent/bin/app-e2e.test.py` | create | MCP → broker → runner → stub command, end to end, in temp dirs |
| `infra/hermes-agent/deploy/hermes-app-broker@.service`, `hermes-app-runner@.service`, `hermes-app-runner@.path` | create | the units |
| `infra/hermes-agent/deploy/units.test.py` | modify | assertions for the new units |
| `infra/hermes-agent/docker-compose.yml`, `Dockerfile`, `bootstrap-claude-auth.sh` | modify, modify, delete | retire `claude-auth-init`; mount the `ads-audits` skill |
| `infra/hermes-agent/config.yaml.example`, `.env.example` | modify | `mcp_servers.ads_audit`; OpenRouter key; privacy routing per Task 1 |
| `infra/hermes-agent/skills/ads-audits/SKILL.md` | create | how Hermes uses the three tools |
| `infra/hermes-agent/bin/gateway-config.test.py` | create | static assertions on compose and config |
| `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` | modify | §13 Measurements (Task 1) |
| `infra/hermes-agent/deploy/BRING-UP.md`, `README.md` | modify | the part-2 box steps |

---

### Task 1: Measure the three unknowns and record them

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` (append `## 13. Measurements`)

No code. Each measurement's result decides a line in Task 9. Run them against the **pinned image** (`Dockerfile` `FROM nousresearch/hermes-agent@sha256:f7b3…`), locally.

- [ ] **Step 1: Does the pinned Hermes read an OpenRouter provider-preference config key?**

Run:
```bash
cd infra/hermes-agent && docker compose build hermes-agent >/dev/null
docker run --rm --entrypoint sh hermes-agent-claude -c \
  'grep -rIl --include=*.py -e "provider_routing" -e "data_collection" -e "\"zdr\"" / 2>/dev/null | grep -v -e /proc/ -e /sys/ | head -20'
```
If files are found, open each and record the exact config key path Hermes reads (e.g. `provider_routing.data_collection`) and whether it's sent in the OpenRouter request body. **Record:** `provider-routing key: <exact path> | none`.

- [ ] **Step 2: Is there a ZDR endpoint for the control-plane model?**

Run:
```bash
curl -s https://openrouter.ai/api/v1/models/deepseek/deepseek-v3.2/endpoints | python3 -m json.tool | head -80
```
**Record:** the providers listed, and any retention or ZDR field shown. If no ZDR-capable endpoint exists, record the first model from `config.yaml.example`'s alternates (`nousresearch/hermes-4-70b`, `qwen/qwen3-235b-a22b-2507`, `z-ai/glm-4.6`) that has one, by the same command.

- [ ] **Step 3: Does the pinned Hermes honour `mcp_servers.<name>.tools.include`?**

Run (after Task 4 exists, or with a throwaway stdio server that exposes two tools, `a` and `b`):
```bash
docker run --rm -v "$PWD/bin:/opt/cc-bin:ro" --entrypoint sh hermes-agent-claude -c \
  'grep -rIl --include=*.py -e "\"include\"" / 2>/dev/null | xargs grep -l "mcp" 2>/dev/null | head'
```
Then read the matching code path. **Record:** `tools.include supported: yes (file:line) | no`.

- [ ] **Step 4: Append the results to the spec as §13, and commit**

```markdown
## 13. Measurements (part 2, Task 1 — <date>)

| Question | Result | Consequence |
|---|---|---|
| Hermes provider-routing key | <exact key or none> | <config key used in config.yaml.example, or "account-level setting is authoritative; D10.5 records it"> |
| ZDR endpoint for the control-plane model | <providers / none> | <model kept, or model switched to X> |
| MCP `tools.include` | <yes file:line / no> | <include used; if no: the server exposes only the three tools anyway> |
```

```bash
git add docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md
git commit -m "docs(hermes): Option B §13 measurements — provider routing, ZDR endpoint, MCP include"
```

---

### Task 2: `app_lib.py` and the manifest: the shared contract

**Files:**
- Create: `infra/hermes-agent/registry/apps/ads-audit.json`
- Create: `infra/hermes-agent/bin/app_lib.py`
- Test: `infra/hermes-agent/bin/app_lib.test.py`

**Interfaces:**
- Produces (used by Tasks 4–7):
  - `Refused(ValueError)` (attribute `.reason`, default `"bad_request"`);
  - constants `APP_RE`, `FILENAME_RE`, `SLUG_RE`, `REQUEST_ID_RE`, `TS_RE`, `STATUSES`, `STEP_CLASSES`, `MAX_REQUEST_BYTES=1024`, `MAX_JOB_BYTES=512`, `MAX_STDOUT=65536`, `SPOOL_FILE_MODE=0o640`;
  - `Manifest` (namedtuple `app user command ops tools wait_seconds`) and `load_manifest(path, app) -> Manifest`;
  - `spool_dir(app, root="/var/lib/hermes/spool/apps")`, `state_dir(app, root="/var/lib/hermes/app-state")`;
  - `read_capped(path, cap) -> bytes` (O_NOFOLLOW, regular file only, `Refused` otherwise);
  - `parse_request(data, filename, manifest) -> dict` and `make_request(manifest, op, client) -> dict`;
  - `parse_job(data, filename) -> dict`, `parse_done(data, filename) -> dict`;
  - `refused_result(request_id, op, client, reason) -> dict`;
  - `map_done(request, done, manifest) -> dict`;
  - `write_json_atomic(dirpath, name, obj, mode=0o640, uid=None, gid=None)`;
  - `Ledger(path)` with methods `seen(rid)`, `append(event, request_id, op=None, client=None, now=None)`, `count(day, op, client=None)`, `unresolved() -> list[(rid, op, client)]`, `reserved(rid) -> (op, client) | None`.
  - Result dicts:
    - run: keys exactly `{request_id, op, client, status, reason, exit_code, ts, steps, vault_path}`;
    - list: keys exactly `{request_id, op, client, status, reason, audits}`;
    - a broker refusal of a malformed request: `op` and `client` may be `None`.

- [ ] **Step 1: Create the manifest** `infra/hermes-agent/registry/apps/ads-audit.json`

```json
{
  "app": "ads-audit",
  "user": "hermes-app-ads-audit",
  "command": "/usr/local/sbin/run-client-audit",
  "ops": {
    "run": {"args": ["--json"], "timeout": 1800, "quota": {"per_client_day": 1, "per_box_day": 5}},
    "list": {"args": ["--list", "--json"], "timeout": 60, "quota": {"per_box_day": 60}}
  },
  "tools": {"run": "ads_audit_run", "status": "ads_audit_status", "list": "ads_audit_list"},
  "wait_seconds": {"run": 300, "list": 60}
}
```

- [ ] **Step 2: Write the failing tests** `bin/app_lib.test.py`

```python
#!/usr/bin/env python3
import json, os, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); import sys; sys.path.insert(0, HERE)
import app_lib as A

MANIFEST = os.path.join(os.path.dirname(HERE), "registry", "apps", "ads-audit.json")
RID = "0f8e2c1a-1111-4222-8333-444455556666"


def m():
    return A.load_manifest(MANIFEST, "ads-audit")


class TestManifest(unittest.TestCase):
    def test_repo_manifest_loads(self):
        man = m()
        self.assertEqual(man.user, "hermes-app-ads-audit")
        self.assertEqual(man.ops["run"]["args"], ["--json"])
        self.assertEqual(man.tools["status"], "ads_audit_status")

    def test_unknown_key_or_wrong_app_refused(self):
        raw = json.load(open(MANIFEST))
        for mutate in (lambda d: d.update(extra=1), lambda d: d.update(app="other"),
                       lambda d: d.update(user="root"), lambda d: d.update(command="run-client-audit"),
                       lambda d: d["ops"]["run"]["args"].append("; rm -rf /"),
                       lambda d: d["ops"].update(undo={"args": [], "timeout": 1, "quota": {}})):
            d = json.loads(json.dumps(raw)); mutate(d)
            p = tempfile.mktemp(); json.dump(d, open(p, "w"))
            with self.subTest(d=d), self.assertRaises(ValueError):
                A.load_manifest(p, "ads-audit")


class TestRequest(unittest.TestCase):
    def good(self, **kw):
        d = {"request_id": RID, "app": "ads-audit", "op": "run", "client": "acme-dental"}; d.update(kw)
        return json.dumps(d).encode()

    def test_good(self):
        r = A.parse_request(self.good(), RID + ".json", m())
        self.assertEqual(r["client"], "acme-dental")

    def test_refusals(self):
        man = m()
        for data, name in ((self.good(), "x.json"), (self.good(request_id="0" * 36), RID + ".json"),
                           (self.good(app="other"), RID + ".json"), (self.good(op="undo"), RID + ".json"),
                           (self.good(client="../x"), RID + ".json"), (b"{", RID + ".json"),
                           (json.dumps({"request_id": RID}).encode(), RID + ".json"),
                           (self.good()[:-1] + b', "x": 1}', RID + ".json")):
            with self.subTest(data=data, name=name), self.assertRaises(A.Refused):
                A.parse_request(data, name, man)

    def test_make_request_round_trips(self):
        r = A.make_request(m(), "list", "acme-dental")
        self.assertEqual(A.parse_request(json.dumps(r).encode(), r["request_id"] + ".json", m()), r)


class TestReadCapped(unittest.TestCase):
    def test_symlink_fifo_and_oversize_refused(self):
        d = tempfile.mkdtemp()
        big = os.path.join(d, "big"); open(big, "wb").write(b"x" * 2000)
        link = os.path.join(d, "l"); os.symlink(big, link)
        fifo = os.path.join(d, "f"); os.mkfifo(fifo)
        for p in (big, link, fifo):
            with self.subTest(p=p), self.assertRaises(A.Refused):
                A.read_capped(p, 1024)


REQ = {"request_id": RID, "app": "ads-audit", "op": "run", "client": "acme-dental"}
OK_STDOUT = json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00",
                        "steps": [{"name": "collect", "rc": 0, "seconds": 10.0}],
                        "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"})


def done(rc=0, stdout=OK_STDOUT, **kw):
    d = {"job_id": RID, "rc": rc, "stdout": stdout + "\n", "timed_out": False, "interrupted": False}; d.update(kw)
    return d


class TestMapDone(unittest.TestCase):
    def test_ok(self):
        r = A.map_done(REQ, done(), m())
        self.assertEqual((r["status"], r["reason"], r["exit_code"]), ("ok", None, 0))
        self.assertEqual(set(r), {"request_id", "op", "client", "status", "reason", "exit_code", "ts",
                                  "steps", "vault_path"})

    def test_timeout_and_interrupted(self):
        self.assertEqual(A.map_done(REQ, done(rc=None, stdout="", timed_out=True), m())["reason"], "timeout")
        self.assertEqual(A.map_done(REQ, done(rc=None, stdout="", interrupted=True), m())["reason"], "interrupted")

    def test_out_of_contract_is_internal(self):
        bad = [
            json.dumps({**json.loads(OK_STDOUT), "extra": "x"}),
            json.dumps({**json.loads(OK_STDOUT), "vault_path": "/var/lib/hermes/vaults/other-dental/audits/2026-10-01_12-00-00-audit.md"}),
            json.dumps({**json.loads(OK_STDOUT), "status": "failed"}),        # rc 0 but failed
            json.dumps({**json.loads(OK_STDOUT), "reason": "free text here"}),
            json.dumps({**json.loads(OK_STDOUT), "steps": [{"name": "rm -rf", "rc": 0, "seconds": 1}]}),
            "not json", OK_STDOUT + "\n" + OK_STDOUT,
        ]
        for s in bad:
            with self.subTest(s=s):
                r = A.map_done(REQ, done(stdout=s), m())
                self.assertEqual((r["status"], r["reason"]), ("failed", "internal"))

    def test_busy_and_precheck(self):
        busy = json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None, "steps": [], "vault_path": None})
        self.assertEqual(A.map_done(REQ, done(rc=3, stdout=busy), m())["status"], "busy")
        pre = json.dumps({"status": "refused", "reason": "precheck", "exit_code": 2, "ts": None, "steps": [], "vault_path": None})
        self.assertEqual(A.map_done(REQ, done(rc=2, stdout=pre), m())["reason"], "precheck")

    def test_list(self):
        req = dict(REQ, op="list")
        r = A.map_done(req, done(stdout=json.dumps({"status": "ok", "audits": ["2026-10-01_12-00-00"]})), m())
        self.assertEqual((r["status"], r["audits"]), ("ok", ["2026-10-01_12-00-00"]))
        r = A.map_done(req, done(stdout=json.dumps({"status": "ok", "audits": ["../etc"]})), m())
        self.assertEqual(r["reason"], "internal")


class TestLedger(unittest.TestCase):
    def test_counts_seen_unresolved(self):
        L = A.Ledger(os.path.join(tempfile.mkdtemp(), "ledger.jsonl"))
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        L.append("reserved", "b" * 36, "run", "other", now="2026-10-01T11:00:00Z")
        L.append("released", "b" * 36, now="2026-10-01T11:05:00Z")
        L.append("reserved", "c" * 36, "run", "acme", now="2026-10-02T10:00:00Z")
        L.append("resulted", "c" * 36, now="2026-10-02T10:10:00Z")
        self.assertEqual(L.count("2026-10-01", "run"), 1)
        self.assertEqual(L.count("2026-10-01", "run", "acme"), 1)
        self.assertEqual(L.count("2026-10-01", "run", "other"), 0)
        self.assertTrue(L.seen("b" * 36)); self.assertFalse(L.seen("d" * 36))
        self.assertEqual(L.unresolved(), [("a" * 36, "run", "acme")])
        self.assertEqual(L.reserved("a" * 36), ("run", "acme"))

    def test_torn_last_line_ignored(self):
        p = os.path.join(tempfile.mkdtemp(), "l"); L = A.Ledger(p)
        L.append("reserved", "a" * 36, "run", "acme", now="2026-10-01T10:00:00Z")
        open(p, "a").write('{"event": "res')
        self.assertTrue(L.seen("a" * 36))


class TestWrite(unittest.TestCase):
    def test_atomic_mode(self):
        d = tempfile.mkdtemp()
        A.write_json_atomic(d, RID + ".json", {"a": 1})
        p = os.path.join(d, RID + ".json")
        self.assertEqual(json.load(open(p)), {"a": 1})
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/app_lib.test.py -v`
Expected: `ModuleNotFoundError: No module named 'app_lib'`.

- [ ] **Step 4: Implement `bin/app_lib.py`**

```python
#!/usr/bin/env python3
"""The per-app chat-trigger contract (Option B spec 2026-09-30 §2-§3). Stdlib only.

Everything the gateway client, the broker and the runner must agree on lives here, once:
the manifest, the four file schemas (request, job, done, result), the result whitelist, the
quota ledger and the atomic writer. Every parser treats its input as hostile: closed key sets,
byte caps, O_NOFOLLOW, regular-file checks. Nothing here decides policy (quota, kill switch,
client status) — that is the broker's; nothing here executes anything — that is the runner's."""
import collections, datetime, json, os, re, stat, tempfile, uuid

import governance_lib
from client_audit_lib import TS_RE

SLUG_RE = governance_lib.SLUG_RE
REQUEST_ID_RE = governance_lib.REQUEST_ID_RE
APP_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FILENAME_RE = re.compile(r"^[0-9a-f-]{36}\.json$")
_ARG_RE = re.compile(r"^--[a-z][a-z-]{0,31}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_REQUEST_BYTES, MAX_JOB_BYTES, MAX_MANIFEST_BYTES = 1024, 512, 16384
MAX_STDOUT = 65536
MAX_DONE_BYTES = MAX_STDOUT * 2 + 1024      # JSON-escaped stdout plus the envelope
SPOOL_FILE_MODE = 0o640
KNOWN_OPS = ("run", "list")
STATUSES = ("ok", "refused", "failed", "busy")
STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write")
BROKER_REASONS = ("bad_request", "duplicate", "inactive_client", "quota", "disabled",
                  "timeout", "interrupted", "internal")
COMMAND_REASONS = ("precheck", "busy", "internal") + STEP_CLASSES
LIST_LIMIT = 24
RC_STATUS = {0: "ok", 1: "failed", 2: "refused", 3: "busy"}

Manifest = collections.namedtuple("Manifest", "app user command ops tools wait_seconds")


class Refused(ValueError):
    def __init__(self, detail, reason="bad_request"):
        super().__init__(detail)
        self.reason = reason


def spool_dir(app, root="/var/lib/hermes/spool/apps"):
    return os.path.join(root, app)


def state_dir(app, root="/var/lib/hermes/app-state"):
    return os.path.join(root, app)


def read_capped(path, cap):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise Refused(f"cannot open: {type(e).__name__}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("not a regular file")
        if st.st_size > cap:
            raise Refused("too large")
        data = os.read(fd, cap + 1)
        if len(data) > cap:
            raise Refused("too large")
        return data
    finally:
        os.close(fd)


def _json(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise Refused("not JSON")


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def load_manifest(path, app):
    if not APP_RE.match(app):
        raise ValueError("invalid app name")
    with open(path, "rb") as f:
        raw = f.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    d = json.loads(raw)
    if set(d) != {"app", "user", "command", "ops", "tools", "wait_seconds"}:
        raise ValueError("manifest keys")
    if d["app"] != app or d["user"] != "hermes-app-" + app:
        raise ValueError("manifest app/user")
    if not isinstance(d["command"], str) or not os.path.isabs(d["command"]) or " " in d["command"]:
        raise ValueError("manifest command must be an absolute path")
    ops = d["ops"]
    if not isinstance(ops, dict) or not ops or not set(ops) <= set(KNOWN_OPS):
        raise ValueError("manifest ops")
    for name, op in ops.items():
        if set(op) != {"args", "timeout", "quota"} or not isinstance(op["args"], list) \
                or not all(isinstance(x, str) and _ARG_RE.match(x) for x in op["args"]) \
                or not _int(op["timeout"], 1, 7200) or not isinstance(op["quota"], dict) \
                or not set(op["quota"]) <= {"per_client_day", "per_box_day"} \
                or not all(_int(v, 1, 1000) for v in op["quota"].values()):
            raise ValueError(f"manifest op {name!r}")
    tools = d["tools"]
    if not isinstance(tools, dict) or set(tools) != set(ops) | {"status"} \
            or not all(isinstance(v, str) and _TOOL_RE.match(v) for v in tools.values()) \
            or len(set(tools.values())) != len(tools):
        raise ValueError("manifest tools")
    ws = d["wait_seconds"]
    if not isinstance(ws, dict) or set(ws) != set(ops) or not all(_int(v, 1, 600) for v in ws.values()):
        raise ValueError("manifest wait_seconds")
    return Manifest(d["app"], d["user"], d["command"], ops, tools, ws)


def _slug(v):
    return isinstance(v, str) and SLUG_RE.match(v) is not None


def parse_request(data, filename, manifest):
    if not FILENAME_RE.match(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"request_id", "app", "op", "client"}:
        raise Refused("bad keys")
    if not isinstance(d["request_id"], str) or not REQUEST_ID_RE.match(d["request_id"]) \
            or d["request_id"] + ".json" != filename:
        raise Refused("bad request_id")
    if d["app"] != manifest.app or d["op"] not in manifest.ops or not _slug(d["client"]):
        raise Refused("bad app/op/client")
    return d


def make_request(manifest, op, client):
    d = {"request_id": str(uuid.uuid4()), "app": manifest.app, "op": op, "client": client}
    return parse_request(json.dumps(d).encode(), d["request_id"] + ".json", manifest)


def parse_job(data, filename):
    if not FILENAME_RE.match(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"job_id", "op", "client"} \
            or not isinstance(d["job_id"], str) or d["job_id"] + ".json" != filename \
            or d["op"] not in KNOWN_OPS or not _slug(d["client"]):
        raise Refused("bad job")
    return d


def parse_done(data, filename):
    if not FILENAME_RE.match(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"job_id", "rc", "stdout", "timed_out", "interrupted"} \
            or d["job_id"] + ".json" != filename \
            or not (d["rc"] is None or _int(d["rc"], -255, 255)) \
            or not isinstance(d["stdout"], str) or len(d["stdout"]) > MAX_STDOUT \
            or not isinstance(d["timed_out"], bool) or not isinstance(d["interrupted"], bool):
        raise Refused("bad done")
    return d


def _base(request_id, op, client, status, reason):
    return {"request_id": request_id, "op": op, "client": client, "status": status, "reason": reason}


def refused_result(request_id, op, client, reason, status="refused"):
    r = _base(request_id, op, client, status, reason)
    if op == "list":
        r["audits"] = []
    else:
        r.update(exit_code=None, ts=None, steps=[], vault_path=None)
    return r


def _one_json_line(stdout):
    lines = [l for l in stdout.splitlines() if l.strip()]
    if len(lines) != 1:
        raise Refused("stdout is not exactly one line")
    d = _json(lines[0])
    if not isinstance(d, dict):
        raise Refused("stdout is not an object")
    return d


def _run_result(req, rc, p):
    if set(p) != {"status", "reason", "exit_code", "ts", "steps", "vault_path"}:
        raise Refused("keys")
    if RC_STATUS.get(rc) != p["status"] or p["exit_code"] != rc:
        raise Refused("status/rc")
    if not (p["reason"] is None if p["status"] == "ok" else p["reason"] in COMMAND_REASONS):
        raise Refused("reason")
    if not (p["ts"] is None or (isinstance(p["ts"], str) and TS_RE.match(p["ts"]))):
        raise Refused("ts")
    steps = p["steps"]
    if not isinstance(steps, list) or len(steps) > len(STEP_CLASSES) or not all(
            isinstance(s, dict) and set(s) == {"name", "rc", "seconds"} and s["name"] in STEP_CLASSES
            and _int(s["rc"], -255, 255) and isinstance(s["seconds"], (int, float))
            and not isinstance(s["seconds"], bool) and 0 <= s["seconds"] < 86400 for s in steps):
        raise Refused("steps")
    vp = p["vault_path"]
    if vp is not None:
        want = re.compile(r"^/var/lib/hermes/vaults/" + re.escape(req["client"])
                          + r"/audits/[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}-audit\.md$")
        if not isinstance(vp, str) or not want.match(vp) or p["status"] != "ok":
            raise Refused("vault_path")
    r = _base(req["request_id"], "run", req["client"], p["status"], p["reason"])
    r.update(exit_code=rc, ts=p["ts"], steps=[dict(s) for s in steps], vault_path=vp)
    return r


def _list_result(req, rc, p):
    if rc == 0 and set(p) == {"status", "audits"} and p["status"] == "ok" \
            and isinstance(p["audits"], list) and len(p["audits"]) <= LIST_LIMIT \
            and all(isinstance(t, str) and TS_RE.match(t) for t in p["audits"]):
        r = _base(req["request_id"], "list", req["client"], "ok", None)
        r["audits"] = list(p["audits"])
        return r
    if rc == 2 and p == {"status": "refused", "reason": "precheck"}:
        return refused_result(req["request_id"], "list", req["client"], "precheck")
    raise Refused("list payload")


def map_done(req, done, manifest):
    """The ONLY way command output becomes a result. Anything outside the contract is
    failed/internal, and nothing from the stdout is passed through."""
    rid, op, client = req["request_id"], req["op"], req["client"]
    if done["interrupted"]:
        return refused_result(rid, op, client, "interrupted", status="failed")
    if done["timed_out"]:
        return refused_result(rid, op, client, "timeout", status="failed")
    try:
        p = _one_json_line(done["stdout"])
        return _run_result(req, done["rc"], p) if op == "run" else _list_result(req, done["rc"], p)
    except Refused:
        return refused_result(rid, op, client, "internal", status="failed")


def write_json_atomic(dirpath, name, obj, mode=SPOOL_FILE_MODE, uid=None, gid=None):
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix="." + name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if uid is not None:
                os.fchown(f.fileno(), uid, gid)
            os.fchmod(f.fileno(), mode)
            json.dump(obj, f, sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, os.path.join(dirpath, name))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    """Append-only JSONL: one line per reserved/released/resulted/refused event. Host-only
    (app-state/<app>/state/ledger.jsonl, never mounted). A torn last line is ignored."""

    def __init__(self, path):
        self.path = path

    def _events(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except FileNotFoundError:
            return

    def append(self, event, request_id, op=None, client=None, now=None):
        now = now or utcnow()
        line = json.dumps({"event": event, "request_id": request_id, "op": op, "client": client,
                           "at": now, "day": now[:10]}, sort_keys=True) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, line.encode("utf-8")); os.fsync(fd)
        finally:
            os.close(fd)

    def seen(self, rid):
        return any(e.get("request_id") == rid for e in self._events())

    def reserved(self, rid):
        for e in self._events():
            if e.get("request_id") == rid and e.get("event") == "reserved":
                return e.get("op"), e.get("client")
        return None

    def count(self, day, op, client=None):
        res, rel = set(), set()
        for e in self._events():
            if e.get("event") == "reserved" and e.get("day") == day and e.get("op") == op \
                    and (client is None or e.get("client") == client):
                res.add(e["request_id"])
            elif e.get("event") == "released":
                rel.add(e.get("request_id"))
        return len(res - rel)

    def unresolved(self):
        reserved, closed = [], set()
        for e in self._events():
            if e.get("event") == "reserved":
                reserved.append((e["request_id"], e.get("op"), e.get("client")))
            elif e.get("event") in ("resulted", "released"):
                closed.add(e.get("request_id"))
        return [r for r in reserved if r[0] not in closed]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/app_lib.test.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/registry/apps/ads-audit.json infra/hermes-agent/bin/app_lib.py infra/hermes-agent/bin/app_lib.test.py
git commit -m "feat(hermes): app_lib + ads-audit manifest — the per-app chat-trigger contract (Option B §3)"
```

---

### Task 3: The host layout for an app: `host_layout.app_layout` and `init-host-layout --app`

**Files:**
- Modify: `infra/hermes-agent/bin/host_layout.py`
- Modify: `infra/hermes-agent/bin/init-host-layout.py`
- Test: `infra/hermes-agent/bin/host_layout.test.py`, `infra/hermes-agent/bin/init-host-layout.test.py` (append)

**Interfaces:**
- Produces:
  - `host_layout.DEFAULT_APPS_ROOT="/var/lib/hermes/spool/apps"` and `DEFAULT_STATE_ROOT="/var/lib/hermes/app-state"`;
  - `app_layout(app) -> tuple[Entry]` (root keys `apps` and `state`);
  - `plan_app(app, apps_root, state_root, resolver, ancestor_uids=(0,), ancestor_top="/")`, `check_app(...) -> list[str]` and `apply_app(..., geteuid=os.geteuid) -> list[str]`;
  - the CLI `init-host-layout --app ads-audit [--apps-root P --state-root P] (--check | --apply)`.

- [ ] **Step 1: Write the failing tests** (append to `host_layout.test.py`, which already builds `Resolver` fixtures; reuse its helper that maps names to the test user's uid and gid. If the file names it differently, follow the existing pattern for `plan()` tests.)

```python
class TestAppLayout(unittest.TestCase):
    def resolver(self):
        me, gid = os.geteuid(), os.getegid()
        return H.Resolver({"root": me, "hermes-app-ads-audit": me},
                          {"root": gid, "hermes": gid, "hermes-app-ads-audit": gid})

    def test_entries_and_modes(self):
        e = {(x.root_key, x.relpath): (x.owner, x.group, x.mode) for x in H.app_layout("ads-audit")}
        self.assertEqual(e[("apps", "ads-audit/requests")], ("hermes-app-ads-audit", "hermes", 0o3770))
        self.assertEqual(e[("apps", "ads-audit/results")], ("hermes-app-ads-audit", "hermes", 0o2750))
        self.assertEqual(e[("state", "ads-audit")], ("root", "hermes-app-ads-audit", 0o750))
        self.assertEqual(e[("state", "ads-audit/running")], ("root", "hermes-app-ads-audit", 0o750))
        for d in ("state", "jobs", "done"):
            self.assertEqual(e[("state", "ads-audit/" + d)], ("hermes-app-ads-audit",) * 2 + (0o700,))

    def test_bad_app_name_refused(self):
        with self.assertRaises(H.LayoutError):
            H.app_layout("../x")

    def test_plan_on_empty_tree_creates_everything(self):
        t = tempfile.mkdtemp()
        steps = H.plan_app("ads-audit", os.path.join(t, "spool/apps"), os.path.join(t, "app-state"),
                           self.resolver(), ancestor_uids=(os.geteuid(), 0), ancestor_top=t)
        self.assertTrue(all(s.action == "create" for s in steps if s.entry is not None))
        self.assertEqual(sum(1 for s in steps if s.entry is not None), len(H.app_layout("ads-audit")))

    def test_mutation_layout_unchanged(self):
        self.assertEqual(len(H.LAYOUT), 13)
```

   Before writing that last assertion, run `python3 -c "import sys; sys.path.insert(0,'infra/hermes-agent/bin'); import host_layout as H; print(len(H.LAYOUT))"`. Use the printed number: it pins that this task doesn't alter the mutation layout.

   Append to `init-host-layout.test.py`, following its existing `main([...], resolver_factory=…)` pattern:

```python
    def test_app_check_reports_missing(self):
        t = tempfile.mkdtemp()
        rc = IHL.main(["--app", "ads-audit", "--apps-root", os.path.join(t, "spool/apps"),
                       "--state-root", os.path.join(t, "app-state"), "--check"],
                      resolver_factory=self.resolver_factory, ancestor_uids=(os.geteuid(), 0), ancestor_top=t)
        self.assertEqual(rc, 2)
```

   (Use the module alias and `resolver_factory` fixture this test file already defines. If the fixture lacks the `hermes-app-ads-audit` names, extend it in `setUp`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v; python3 infra/hermes-agent/bin/init-host-layout.test.py -v`
Expected: FAIL with `AttributeError: … 'app_layout'` and `unrecognized arguments: --app`.

- [ ] **Step 3: Implement in `host_layout.py`.** Refactor `plan()`'s entry loop into a reusable function, and `apply()`'s creation body into `_apply_steps`, without changing their behaviour:

```python
DEFAULT_APPS_ROOT = "/var/lib/hermes/spool/apps"
DEFAULT_STATE_ROOT = "/var/lib/hermes/app-state"
_APP_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def app_layout(app):
    """Option B §3: one app's spool and state. The app dir under state/ is root-owned so only
    root can create or remove DISABLED; running/ is root's but group-readable, so the broker
    sees an in-flight job and never calls it interrupted."""
    if not _APP_RE.match(app):
        raise LayoutError("invalid app name %r" % app)
    u = "hermes-app-" + app
    return (
        Entry("apps", "", DIR, "root", "hermes", 0o750, None),
        Entry("apps", app, DIR, "root", "hermes", 0o750, None),
        Entry("apps", app + "/requests", DIR, u, "hermes", 0o3770, None),
        Entry("apps", app + "/results", DIR, u, "hermes", 0o2750, None),
        Entry("state", "", DIR, "root", "root", 0o755, None),
        Entry("state", app, DIR, "root", u, 0o750, None),
        Entry("state", app + "/state", DIR, u, u, 0o700, None),
        Entry("state", app + "/jobs", DIR, u, u, 0o700, None),
        Entry("state", app + "/done", DIR, u, u, 0o700, None),
        Entry("state", app + "/running", DIR, "root", u, 0o750, None),
    )


def _path(entry, roots):
    root = roots[entry.root_key]
    return root if not entry.relpath else os.path.join(root, entry.relpath)


def _plan_entries(layout, roots, resolver, ancestor_uids, ancestor_top):
    steps, seen = [], set()
    for root in roots.values():
        for path, detail in check_ancestors(root, ancestor_uids, ancestor_top):
            if (path, detail) not in seen:
                seen.add((path, detail))
                steps.append(Step("mismatch", path, detail, False, None))
    missing = []
    for e in layout:
        p = _path(e, roots)
        if any(p.startswith(m + os.sep) for m in missing):
            steps.append(Step("create", p, "missing, expected %s %s" % (e.kind, expected(e)), True, e))
            continue
        state, detail = _inspect(e, p, resolver)
        if state == "missing":
            steps.append(Step("create", p, detail, False, e))
            if e.kind == DIR:
                missing.append(p)
        else:
            steps.append(Step(state, p, detail, False, e))
    return steps


def plan_app(app, apps_root, state_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    for r in (apps_root, state_root):
        if not os.path.isabs(r):
            raise LayoutError("%r is not an absolute path" % r)
    return _plan_entries(app_layout(app), {"apps": apps_root, "state": state_root},
                         resolver, ancestor_uids, ancestor_top)


def check_app(app, apps_root, state_root, resolver, ancestor_uids=(0,), ancestor_top="/"):
    return ["%s: %s" % (s.path, s.detail)
            for s in plan_app(app, apps_root, state_root, resolver, ancestor_uids, ancestor_top)
            if s.action == "mismatch" or (s.action == "create" and not s.implied)]


def apply_app(app, apps_root, state_root, resolver, ancestor_uids=(0,), ancestor_top="/",
              geteuid=os.geteuid):
    if geteuid() != 0:
        raise LayoutError("--apply must run as root. Nothing was created.")
    return _apply_steps(plan_app(app, apps_root, state_root, resolver, ancestor_uids, ancestor_top),
                        resolver)
```

   Then:
   - make `plan()` call `_plan_entries(LAYOUT, {"store": store_root, "spool": spool_root}, resolver, ancestor_uids, ancestor_top)` after its overlap check;
   - add `"import re"` to the imports;
   - move `apply()`'s body, from `bad = [...]` through `return created`, into `def _apply_steps(steps, resolver):`, so that `apply()` becomes the root check, then `return _apply_steps(plan(...), resolver)`.
   
   Keep `entry_path()` (other callers use it), implemented as `return _path(entry, {"store": store_root, "spool": spool_root})`.

- [ ] **Step 4: Implement in `init-host-layout.py`.** Add the arguments and an app branch at the top of the `try:`:

```python
    ap.add_argument("--app", help="lay out one chat-trigger app's spool and state (Option B)")
    ap.add_argument("--apps-root", default=H.DEFAULT_APPS_ROOT)
    ap.add_argument("--state-root", default=H.DEFAULT_STATE_ROOT)
```

```python
        if args.app:
            a = (args.app, args.apps_root, args.state_root, resolver)
            if args.apply:
                for p in H.apply_app(*a, geteuid=geteuid, **kw):
                    print("created  %s" % p)
            problems = H.check_app(*a, **kw)
            if problems:
                print("init-host-layout: the app layout does not match:", file=sys.stderr)
                for p in problems:
                    print("  - %s" % p, file=sys.stderr)
                return EXIT_REFUSED
            print("init-host-layout: app layout OK")
            return EXIT_OK
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/host_layout.test.py -v && python3 infra/hermes-agent/bin/init-host-layout.test.py -v && infra/hermes-agent/bin/run-bin-tests.sh`
Expected: all PASS. The existing layout tests are unchanged and green.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/host_layout.py infra/hermes-agent/bin/init-host-layout.py infra/hermes-agent/bin/host_layout.test.py infra/hermes-agent/bin/init-host-layout.test.py
git commit -m "feat(hermes): host layout for chat-trigger apps (init-host-layout --app)"
```

---

### Task 4: `hermes-app-mcp.py`, the gateway's MCP server

**Files:**
- Create: `infra/hermes-agent/bin/hermes-app-mcp.py`
- Test: `infra/hermes-agent/bin/hermes-app-mcp.test.py`

**Interfaces:**
- Consumes: `app_lib.load_manifest`, `make_request`, `write_json_atomic`, `read_capped`, `REQUEST_ID_RE` and `SLUG_RE`.
- Produces:
  - the CLI `hermes-app-mcp.py --app ads-audit [--manifest-dir /opt/registry/apps] [--spool-root /opt/data/spool/apps]`;
  - `Server(manifest, spool, sleep=time.sleep, clock=time.monotonic, poll=2.0)` with `handle(msg: dict) -> dict | None`.
- Tool names come from `manifest.tools`. A tool call returns `{"content":[{"type":"text","text": <JSON of the result or {"status":"pending","request_id":…}>}], "isError": false}`. `isError: true` is only for invalid arguments or an unknown tool.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import importlib.util, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("mcp", os.path.join(HERE, "hermes-app-mcp.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")


class T(unittest.TestCase):
    def setUp(self):
        self.spool = tempfile.mkdtemp()
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        self.t = [0.0]
        self.s = M.Server(MAN, self.spool, sleep=lambda s: self.t.__setitem__(0, self.t[0] + s),
                          clock=lambda: self.t[0])

    def call(self, name, **args):
        r = self.s.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})
        return r["result"]

    def test_initialize_echoes_supported_version(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_exactly_three_tools(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(sorted(t["name"] for t in r["result"]["tools"]),
                         ["ads_audit_list", "ads_audit_run", "ads_audit_status"])

    def test_run_writes_a_valid_request_and_returns_pending(self):
        res = self.call("ads_audit_run", client="acme-dental")
        body = json.loads(res["content"][0]["text"])
        self.assertEqual(body["status"], "pending"); self.assertFalse(res["isError"])
        names = os.listdir(os.path.join(self.spool, "requests"))
        self.assertEqual(len(names), 1)
        req = A.parse_request(open(os.path.join(self.spool, "requests", names[0]), "rb").read(), names[0], MAN)
        self.assertEqual((req["op"], req["client"]), ("run", "acme-dental"))
        self.assertGreaterEqual(self.t[0], 300)            # waited the manifest's run budget

    def test_run_returns_the_result_when_it_appears(self):
        def sleep(s):
            names = os.listdir(os.path.join(self.spool, "requests"))
            rid = names[0][:-5]
            A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                                A.refused_result(rid, "run", "acme-dental", "quota"))
        self.s.sleep = sleep
        body = json.loads(self.call("ads_audit_run", client="acme-dental")["content"][0]["text"])
        self.assertEqual((body["status"], body["reason"]), ("refused", "quota"))

    def test_bad_slug_is_an_error_and_files_nothing(self):
        res = self.call("ads_audit_run", client="../etc")
        self.assertTrue(res["isError"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])

    def test_status_never_files_a_request(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        body = json.loads(self.call("ads_audit_status", request_id=rid)["content"][0]["text"])
        self.assertEqual(body, {"status": "pending", "request_id": rid})
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertTrue(self.call("ads_audit_status", request_id="../x")["isError"])

    def test_unknown_method_and_tool(self):
        self.assertEqual(self.s.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})["error"]["code"], -32601)
        self.assertTrue(self.call("delete_everything")["isError"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/hermes-app-mcp.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""The gateway's MCP stdio server for one chat-trigger app (Option B spec 2026-09-30 §3.1). Stdlib only.

  python3 /opt/cc-bin/hermes-app-mcp.py --app ads-audit

DELIBERATELY DUMB, like hermes-syscall.py: it writes a request into the app's spool and reads
a result back. It holds no credential, does no network I/O and makes no policy decision —
everything is decided by the host-side broker, which treats every byte written here as hostile.
A refusal is returned as a normal (non-error) tool result stating it is final, never as a
retryable error: a model that retries a refusal is a model applying pressure to a guard."""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DESCRIPTIONS = {
    "run": "Run a Google Ads trend audit for one registered client. Takes minutes. Returns a result "
           "with status ok|refused|failed|busy, or pending with a request_id. A refused or failed "
           "result is FINAL: do not call this tool again for that client today.",
    "list": "List the timestamps of a client's past audits. Returns timestamps only.",
    "status": "Check the result of an earlier request by its request_id. Files nothing.",
}


class Server:
    def __init__(self, manifest, spool, sleep=time.sleep, clock=time.monotonic, poll=2.0):
        self.m, self.spool, self.sleep, self.clock, self.poll = manifest, spool, sleep, clock, poll
        self.by_tool = {v: k for k, v in manifest.tools.items()}

    def _tools(self):
        out = []
        for op, name in sorted(self.m.tools.items()):
            if op == "status":
                schema = {"type": "object", "properties": {"request_id": {"type": "string"}},
                          "required": ["request_id"], "additionalProperties": False}
            else:
                schema = {"type": "object", "properties": {"client": {"type": "string",
                          "description": "the client's registered short name (slug)"}},
                          "required": ["client"], "additionalProperties": False}
            out.append({"name": name, "description": DESCRIPTIONS[op], "inputSchema": schema})
        return out

    def _result(self, rid):
        p = os.path.join(self.spool, "results", rid + ".json")
        try:
            return json.loads(A.read_capped(p, A.MAX_DONE_BYTES))
        except (A.Refused, ValueError):
            return None

    def _wait(self, rid, seconds):
        deadline = self.clock() + seconds
        while True:
            r = self._result(rid)
            if r is not None:
                return r
            if self.clock() >= deadline:
                return {"status": "pending", "request_id": rid}
            self.sleep(self.poll)

    def _text(self, obj, error=False):
        return {"content": [{"type": "text", "text": json.dumps(obj, sort_keys=True)}], "isError": error}

    def call(self, name, args):
        op = self.by_tool.get(name)
        if op is None or not isinstance(args, dict):
            return self._text({"error": "unknown tool"}, error=True)
        if op == "status":
            rid = args.get("request_id")
            if set(args) != {"request_id"} or not isinstance(rid, str) or not A.REQUEST_ID_RE.match(rid):
                return self._text({"error": "request_id must be a request id"}, error=True)
            return self._text(self._result(rid) or {"status": "pending", "request_id": rid})
        client = args.get("client")
        if set(args) != {"client"} or not isinstance(client, str) or not A.SLUG_RE.match(client):
            return self._text({"error": "client must be a registered short name"}, error=True)
        req = A.make_request(self.m, op, client)
        A.write_json_atomic(os.path.join(self.spool, "requests"), req["request_id"] + ".json", req)
        return self._text(self._wait(req["request_id"], self.m.wait_seconds[op]))

    def handle(self, msg):
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:                               # a notification: never answered
            return None
        if method == "initialize":
            want = (msg.get("params") or {}).get("protocolVersion")
            ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            res = {"protocolVersion": ver, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "hermes-app-" + self.m.app, "version": "1"}}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": self._tools()}
        elif method == "tools/call":
            p = msg.get("params") or {}
            res = self.call(p.get("name"), p.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/registry/apps")
    ap.add_argument("--spool-root", default="/opt/data/spool/apps")
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    s = Server(m, A.spool_dir(a.app, a.spool_root))
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = s.handle(msg) if isinstance(msg, dict) else None
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/hermes-app-mcp.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-app-mcp.py infra/hermes-agent/bin/hermes-app-mcp.test.py
git commit -m "feat(hermes): hermes-app-mcp — stdio MCP server, three tools, no policy (Option B §3.1)"
```

---

### Task 5: `hermes-app-broker.py`, which validates, admits, queues and reports

**Files:**
- Create: `infra/hermes-agent/bin/hermes-app-broker.py`
- Test: `infra/hermes-agent/bin/hermes-app-broker.test.py`

**Interfaces:**
- Consumes: `app_lib.*` (Task 2) and `vault_lib.load_registry(path)`.
- Produces:
  - the CLI `hermes-app-broker.py --app ads-audit (--once | --watch --interval 2) [--manifest-dir …] [--apps-root …] [--state-root …] [--registry …]`;
  - `Ctx(manifest, spool, state, registry, now=A.utcnow, log=print)`;
  - functions `recover(ctx)`, `drain_once(ctx)`, `collect_once(ctx)` and `expire_results(ctx, max_age=7*86400)`.
- Constants: `MAX_PER_PASS=64`, `REQUEST_MAX_AGE=3600`.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import importlib.util, io, json, os, sys, tempfile, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("brk", os.path.join(HERE, "hermes-app-broker.py"))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        self.spool, self.state = os.path.join(t, "spool"), os.path.join(t, "state")
        for d in (self.spool + "/requests", self.spool + "/results", self.state + "/state",
                  self.state + "/jobs", self.state + "/done", self.state + "/running"):
            os.makedirs(d)
        self.reg = os.path.join(t, "clients.json")
        json.dump({"clients": {"acme-dental": {"status": "active", "customer_id": "1234567890"},
                               "old-dental": {"status": "retired", "customer_id": "1234567891"},
                               "b-dental": {"status": "active", "customer_id": "1234567892"}}}, open(self.reg, "w"))
        self.day = "2026-10-01"
        self.logs = []
        self.ctx = B.Ctx(MAN, self.spool, self.state, self.reg, now=lambda: self.day + "T10:00:00Z",
                         log=self.logs.append)

    def file(self, op="run", client="acme-dental", rid=None, raw=None):
        r = A.make_request(MAN, op, client)
        if rid:
            r["request_id"] = rid
        name = r["request_id"] + ".json"
        open(os.path.join(self.spool, "requests", name), "wb").write(raw if raw is not None else json.dumps(r).encode())
        return r["request_id"]

    def result(self, rid):
        p = os.path.join(self.spool, "results", rid + ".json")
        return json.load(open(p)) if os.path.exists(p) else None

    def jobs(self):
        return sorted(os.listdir(os.path.join(self.state, "jobs")))


class TestAdmit(Base):
    def test_good_request_becomes_a_job_and_is_removed(self):
        rid = self.file()
        B.drain_once(self.ctx)
        self.assertEqual(self.jobs(), [rid + ".json"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertIsNone(self.result(rid))
        job = A.parse_job(open(os.path.join(self.state, "jobs", rid + ".json"), "rb").read(), rid + ".json")
        self.assertEqual((job["op"], job["client"]), ("run", "acme-dental"))

    def test_inactive_and_unknown_refused(self):
        for c in ("old-dental", "nobody"):
            rid = self.file(client=c); B.drain_once(self.ctx)
            self.assertEqual(self.result(rid)["reason"], "inactive_client")
        self.assertEqual(self.jobs(), [])

    def test_kill_switch_refuses_and_the_refusal_is_final(self):
        open(os.path.join(self.state, "DISABLED"), "w").close()
        rid = self.file(); B.drain_once(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "disabled")
        os.unlink(os.path.join(self.state, "DISABLED"))
        self.file(rid=rid); B.drain_once(self.ctx)                  # same id again
        self.assertEqual(self.result(rid)["reason"], "disabled")   # unchanged; no job
        self.assertEqual(self.jobs(), [])

    def test_quota_per_client_and_per_box(self):
        r1 = self.file(); B.drain_once(self.ctx)
        r2 = self.file(); B.drain_once(self.ctx)
        self.assertEqual(self.result(r2)["reason"], "quota")
        for c in ("b-dental",):
            self.file(client=c)
        B.drain_once(self.ctx)
        self.assertEqual(len(self.jobs()), 2)
        self.day = "2026-10-02"
        r3 = self.file(); B.drain_once(self.ctx)
        self.assertIsNone(self.result(r3))                          # a new day: admitted

    def test_duplicate_id_writes_no_second_result(self):
        rid = self.file(client="nobody"); B.drain_once(self.ctx)
        first = self.result(rid)
        self.file(rid=rid, client="acme-dental"); B.drain_once(self.ctx)
        self.assertEqual(self.result(rid), first)
        self.assertEqual(self.jobs(), [])

    def test_malformed_request_bad_request_result_when_id_known(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        open(os.path.join(self.spool, "requests", rid + ".json"), "w").write("{nope")
        B.drain_once(self.ctx)
        r = self.result(rid)
        self.assertEqual((r["status"], r["reason"], r["op"], r["client"]), ("refused", "bad_request", None, None))

    def test_junk_names_fifos_and_old_requests_removed_unread(self):
        os.mkfifo(os.path.join(self.spool, "requests", "0f8e2c1a-1111-4222-8333-444455556666.json"))
        open(os.path.join(self.spool, "requests", "junk.txt"), "w").close()
        rid = self.file(); old = time.time() - 7200
        os.utime(os.path.join(self.spool, "requests", rid + ".json"), (old, old))
        B.drain_once(self.ctx)                                        # must not block on the FIFO
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertEqual(self.jobs(), [])

    def test_bounded_work_per_pass(self):
        for _ in range(B.MAX_PER_PASS + 10):
            self.file(op="list")
        B.drain_once(self.ctx)
        self.assertEqual(len(os.listdir(os.path.join(self.spool, "requests"))), 10)

    def test_journal_line_has_no_customer_id(self):
        self.file(); B.drain_once(self.ctx)
        self.assertTrue(self.logs)
        self.assertFalse(any("1234567890" in l for l in self.logs))


class TestCollect(Base):
    def done(self, rid, rc, stdout, **kw):
        d = {"job_id": rid, "rc": rc, "stdout": stdout, "timed_out": False, "interrupted": False}; d.update(kw)
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json", d)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))

    def test_ok_result(self):
        rid = self.file(); B.drain_once(self.ctx)
        self.done(rid, 0, json.dumps({"status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_10-00-00",
                                      "steps": [], "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_10-00-00-audit.md"}))
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid)["status"], "ok")
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])

    def test_busy_releases_quota(self):
        rid = self.file(); B.drain_once(self.ctx)
        self.done(rid, 3, json.dumps({"status": "busy", "reason": "busy", "exit_code": 3, "ts": None,
                                      "steps": [], "vault_path": None}))
        B.collect_once(self.ctx)
        self.assertEqual(self.result(rid)["status"], "busy")
        rid2 = self.file(); B.drain_once(self.ctx)
        self.assertIsNone(self.result(rid2))                          # admitted again today

    def test_done_without_a_reservation_is_dropped(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        A.write_json_atomic(os.path.join(self.state, "done"), rid + ".json",
                            {"job_id": rid, "rc": 0, "stdout": "", "timed_out": False, "interrupted": False})
        B.collect_once(self.ctx)
        self.assertIsNone(self.result(rid))
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])


class TestRecover(Base):
    def test_reservation_with_nothing_in_flight_is_interrupted(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.unlink(os.path.join(self.state, "jobs", rid + ".json"))   # lost before the runner took it
        B.recover(self.ctx)
        self.assertEqual(self.result(rid)["reason"], "interrupted")

    def test_in_flight_job_is_left_alone(self):
        rid = self.file(); B.drain_once(self.ctx)
        os.rename(os.path.join(self.state, "jobs", rid + ".json"), os.path.join(self.state, "running", rid + ".json"))
        B.recover(self.ctx)
        self.assertIsNone(self.result(rid))


class TestExpire(Base):
    def test_old_results_removed(self):
        rid = self.file(client="nobody"); B.drain_once(self.ctx)
        p = os.path.join(self.spool, "results", rid + ".json"); old = time.time() - 8 * 86400
        os.utime(p, (old, old))
        B.expire_results(self.ctx)
        self.assertFalse(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/hermes-app-broker.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Per-app chat-trigger broker (Option B spec 2026-09-30 §3.3). Stdlib only.

  hermes-app-broker.py --app ads-audit --watch --interval 2      (systemd: hermes-app-broker@ads-audit)

Runs as hermes-app-<app>: NoNewPrivileges, no capabilities, no network, no Docker, no sudo. It
reads the only tree the gateway writes (spool/apps/<app>/requests), so every byte is hostile.
It decides admission (schema, replay, kill switch, client status, quota — reserved BEFORE the
job exists) and writes a job file for the root runner; it never executes anything. Results are
built only by app_lib.map_done's whitelist. Nothing re-runs on its own: a reservation whose job
vanished is reported `interrupted`, never re-queued."""
import argparse, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
import vault_lib as V

MAX_PER_PASS = 64
REQUEST_MAX_AGE = 3600


class Ctx:
    def __init__(self, manifest, spool, state, registry, now=A.utcnow, log=print):
        self.m, self.spool, self.state, self.registry, self.now, self.log = \
            manifest, spool, state, registry, now, log
        self.req_dir = os.path.join(spool, "requests")
        self.res_dir = os.path.join(spool, "results")
        self.ledger = A.Ledger(os.path.join(state, "state", "ledger.jsonl"))

    def d(self, name):
        return os.path.join(self.state, name)


def _say(ctx, rid, op, client, status, reason):
    ctx.log(f"hermes-app-broker[{ctx.m.app}]: request={rid} op={op or '-'} client={client or '-'} "
            f"status={status} reason={reason or '-'}")


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _result(ctx, result):
    A.write_json_atomic(ctx.res_dir, result["request_id"] + ".json", result)
    _say(ctx, result["request_id"], result["op"], result["client"], result["status"], result["reason"])


def _active(ctx, client):
    try:
        rec = V.load_registry(ctx.registry).get(client)
    except (OSError, ValueError):
        return False
    return isinstance(rec, dict) and rec.get("status") == "active"


def _refuse(ctx, rid, op, client, reason):
    ctx.ledger.append("refused", rid, op, client, now=ctx.now())
    _result(ctx, A.refused_result(rid, op, client, reason))


def _admit(ctx, req):
    rid, op, client = req["request_id"], req["op"], req["client"]
    if os.path.exists(ctx.d("DISABLED")):
        return _refuse(ctx, rid, op, client, "disabled")
    if not _active(ctx, client):
        return _refuse(ctx, rid, op, client, "inactive_client")
    day, q = ctx.now()[:10], ctx.m.ops[op]["quota"]
    if ("per_client_day" in q and ctx.ledger.count(day, op, client) >= q["per_client_day"]) or \
            ("per_box_day" in q and ctx.ledger.count(day, op) >= q["per_box_day"]):
        return _refuse(ctx, rid, op, client, "quota")
    ctx.ledger.append("reserved", rid, op, client, now=ctx.now())       # BEFORE the job exists
    A.write_json_atomic(ctx.d("jobs"), rid + ".json", {"job_id": rid, "op": op, "client": client}, mode=0o600)
    _say(ctx, rid, op, client, "queued", None)


def drain_once(ctx):
    try:
        names = os.listdir(ctx.req_dir)
    except FileNotFoundError:
        return
    now = time.time()
    todo = []
    for n in names:
        p = os.path.join(ctx.req_dir, n)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if not A.FILENAME_RE.match(n):
            if not n.startswith(".") or now - st.st_mtime > REQUEST_MAX_AGE:   # keep in-flight temp files
                _unlink(p)
            continue
        if now - st.st_mtime > REQUEST_MAX_AGE:
            _unlink(p); continue
        todo.append((st.st_mtime, n))
    for _, n in sorted(todo)[:MAX_PER_PASS]:
        p = os.path.join(ctx.req_dir, n)
        rid = n[:-5]
        try:
            req = A.parse_request(A.read_capped(p, A.MAX_REQUEST_BYTES), n, ctx.m)
        except A.Refused:
            if A.REQUEST_ID_RE.match(rid) and not ctx.ledger.seen(rid):
                _refuse(ctx, rid, None, None, "bad_request")
            _unlink(p); continue
        if ctx.ledger.seen(rid):
            _say(ctx, rid, req["op"], req["client"], "dropped", "duplicate")   # the first result stands
            _unlink(p); continue
        _admit(ctx, req)
        _unlink(p)


def collect_once(ctx):
    for n in sorted(os.listdir(ctx.d("done"))):
        p = os.path.join(ctx.d("done"), n)
        rid = n[:-5]
        try:
            done = A.parse_done(A.read_capped(p, A.MAX_DONE_BYTES), n)
        except A.Refused:
            done = None
        res = ctx.ledger.reserved(rid) if A.FILENAME_RE.match(n) else None
        if res is None:
            _unlink(p); continue
        op, client = res
        req = {"request_id": rid, "op": op, "client": client}
        if done is None:
            result = A.refused_result(rid, op, client, "internal", status="failed")
        else:
            result = A.map_done(req, done, ctx.m)
        if result["status"] == "busy":
            ctx.ledger.append("released", rid, now=ctx.now())
        ctx.ledger.append("resulted", rid, now=ctx.now())
        _result(ctx, result)
        _unlink(p)


def recover(ctx):
    for rid, op, client in ctx.ledger.unresolved():
        name = rid + ".json"
        if any(os.path.exists(os.path.join(ctx.d(d), name)) for d in ("jobs", "running", "done")):
            continue
        ctx.ledger.append("resulted", rid, now=ctx.now())
        _result(ctx, A.refused_result(rid, op, client, "interrupted", status="failed"))


def expire_results(ctx, max_age=7 * 86400):
    now = time.time()
    for n in os.listdir(ctx.res_dir):
        p = os.path.join(ctx.res_dir, n)
        try:
            if now - os.lstat(p).st_mtime > max_age:
                os.unlink(p)
        except FileNotFoundError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/hermes-agent/registry/apps")
    ap.add_argument("--apps-root", default="/var/lib/hermes/spool/apps")
    ap.add_argument("--state-root", default="/var/lib/hermes/app-state")
    ap.add_argument("--registry", default="/var/lib/hermes/governance/registry/clients.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    ctx = Ctx(m, A.spool_dir(a.app, a.apps_root), A.state_dir(a.app, a.state_root), a.registry,
              log=lambda s: print(s, flush=True))
    recover(ctx)
    while True:
        drain_once(ctx)
        collect_once(ctx)
        expire_results(ctx)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/hermes-app-broker.test.py -v`
Expected: all PASS. If `test_quota_per_client_and_per_box` fails on the per-box count, check that `count(day, op)` without a client counts every client's reservations. It must equal the per-box usage.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-app-broker.py infra/hermes-agent/bin/hermes-app-broker.test.py
git commit -m "feat(hermes): hermes-app-broker — hostile-input drain, quota, kill switch, job hand-off (Option B §3.3)"
```

---

### Task 6: `hermes-app-runner.py`, the root executor

**Files:**
- Create: `infra/hermes-agent/bin/hermes-app-runner.py`
- Test: `infra/hermes-agent/bin/hermes-app-runner.test.py`

**Interfaces:**
- Consumes: `app_lib.load_manifest`, `parse_job`, `read_capped`, `write_json_atomic` and `MAX_JOB_BYTES`/`MAX_STDOUT`.
- Produces:
  - the CLI `hermes-app-runner.py --app ads-audit [--manifest-dir …] [--state-root …]`;
  - `run_all(manifest, state, execute=_execute, owner=(uid, gid) | None)`;
  - `_execute(argv, timeout) -> (rc | None, stdout: str, timed_out: bool)`.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
import importlib.util, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("run", os.path.join(HERE, "hermes-app-runner.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")
RID = "0f8e2c1a-1111-4222-8333-444455556666"


class T(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        for d in ("jobs", "running", "done"):
            os.makedirs(os.path.join(self.state, d))
        self.calls = []

    def job(self, rid=RID, op="run", client="acme-dental", raw=None):
        data = raw if raw is not None else json.dumps({"job_id": rid, "op": op, "client": client})
        open(os.path.join(self.state, "jobs", rid + ".json"), "w").write(data)

    def execute(self, argv, timeout):
        self.calls.append((argv, timeout))
        self.assertTrue(os.path.exists(os.path.join(self.state, "running", RID + ".json")))  # moved first
        return 0, '{"status": "ok"}\n', False

    def done(self, rid=RID):
        return json.load(open(os.path.join(self.state, "done", rid + ".json")))

    def test_fixed_argv_per_op_and_done_written(self):
        self.job()
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [(["/usr/local/sbin/run-client-audit", "acme-dental", "--json"], 1800)])
        d = self.done()
        self.assertEqual((d["rc"], d["timed_out"], d["interrupted"]), (0, False, False))
        self.assertEqual(os.listdir(os.path.join(self.state, "jobs")), [])
        self.assertEqual(os.listdir(os.path.join(self.state, "running")), [])

    def test_list_argv(self):
        self.job(op="list")
        calls = []
        R.run_all(MAN, self.state, execute=lambda a, t: calls.append((a, t)) or (0, "", False), owner=None)
        self.assertEqual(calls, [(["/usr/local/sbin/run-client-audit", "acme-dental", "--list", "--json"], 60)])

    def test_leftover_running_becomes_interrupted_and_is_never_run(self):
        open(os.path.join(self.state, "running", RID + ".json"), "w").write(
            json.dumps({"job_id": RID, "op": "run", "client": "acme-dental"}))
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.done()["interrupted"])

    def test_malformed_job_never_executes(self):
        for raw in ('{"job_id": "%s", "op": "run", "client": "../x"}' % RID,
                    '{"job_id": "%s", "op": "undo", "client": "a"}' % RID, "junk"):
            with self.subTest(raw=raw):
                self.job(raw=raw)
                R.run_all(MAN, self.state, execute=self.execute, owner=None)
                self.assertEqual(self.calls, [])
                d = self.done(); self.assertIsNone(d["rc"])
                os.unlink(os.path.join(self.state, "done", RID + ".json"))

    def test_symlinked_job_not_followed(self):
        target = os.path.join(self.state, "t"); open(target, "w").write("x")
        os.symlink(target, os.path.join(self.state, "jobs", RID + ".json"))
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertTrue(os.path.exists(target))

    def test_real_execute_timeout_kills_the_group(self):
        rc, out, timed_out = R._execute(["/bin/sh", "-c", "sleep 30 & sleep 30"], 1)
        self.assertEqual((rc, timed_out), (None, True))

    def test_real_execute_caps_stdout(self):
        rc, out, _ = R._execute(["/bin/sh", "-c", "head -c 200000 /dev/zero | tr '\\0' a"], 10)
        self.assertEqual((rc, len(out)), (0, A.MAX_STDOUT))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/hermes-app-runner.test.py -v`
Expected: FAIL (the file doesn't exist).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Root runner for one chat-trigger app (Option B spec 2026-09-30 §3.4). Stdlib only.

  hermes-app-runner.py --app ads-audit        (systemd: hermes-app-runner@ads-audit, a oneshot
                                               started by hermes-app-runner@ads-audit.path)

The ONLY root code Option B adds. It reads only job files the broker user wrote, never the
spool. It executes exactly [manifest.command, <slug>, *manifest.ops[op].args] — no shell, the
slug one argv element — after moving the job into running/. Anything found in running/ at
start was cut off by a crash or reboot: it becomes an `interrupted` done file and is NEVER
re-run. Done files are root:<app user> 0640 in the broker-owned done/ dir."""
import argparse, os, pwd, signal, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A

KILL_GRACE = 30
SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def _execute(argv, timeout):
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, env=SAFE_ENV,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(timeout=KILL_GRACE)
                break
            except subprocess.TimeoutExpired:
                continue
        return None, "", True
    return p.returncode, out[:A.MAX_STDOUT].decode("utf-8", "replace"), False


def _done(state, job_id, rc, stdout, timed_out, interrupted, owner):
    uid, gid = owner if owner else (None, None)
    A.write_json_atomic(os.path.join(state, "done"), job_id + ".json",
                        {"job_id": job_id, "rc": rc, "stdout": stdout, "timed_out": timed_out,
                         "interrupted": interrupted}, mode=0o640, uid=uid, gid=gid)


def _oldest(d):
    names = [n for n in os.listdir(d) if A.FILENAME_RE.match(n)]
    return sorted(names, key=lambda n: os.lstat(os.path.join(d, n)).st_mtime)


def run_all(manifest, state, execute=_execute, owner=None):
    jobs, running = os.path.join(state, "jobs"), os.path.join(state, "running")
    for n in _oldest(running):                              # cut off earlier: report, never re-run
        _done(state, n[:-5], None, "", False, True, owner)
        os.unlink(os.path.join(running, n))
    while True:
        names = _oldest(jobs)
        if not names:
            return
        n = names[0]
        p = os.path.join(jobs, n)
        try:
            job = A.parse_job(A.read_capped(p, A.MAX_JOB_BYTES), n)
        except A.Refused:
            _done(state, n[:-5], None, "", False, False, owner)   # the broker maps this to internal
            os.unlink(p)
            continue
        os.rename(p, os.path.join(running, n))
        op = manifest.ops[job["op"]] if job["op"] in manifest.ops else None
        if op is None:
            rc, out, timed_out = None, "", False
        else:
            rc, out, timed_out = execute([manifest.command, job["client"]] + list(op["args"]), op["timeout"])
        _done(state, job["job_id"], rc, out, timed_out, False, owner)
        os.unlink(os.path.join(running, n))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/hermes-agent/registry/apps")
    ap.add_argument("--state-root", default="/var/lib/hermes/app-state")
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    pw = pwd.getpwnam(m.user)
    run_all(m, A.state_dir(a.app, a.state_root), owner=(0, pw.pw_gid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

   The test `test_malformed_job_never_executes` expects a done file with `rc` `None` for a job whose name is valid but whose content isn't. The code above writes it via `_done(state, n[:-5], …)`. `n` matched `FILENAME_RE` in `_oldest`, so the id is well-formed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/hermes-app-runner.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-app-runner.py infra/hermes-agent/bin/hermes-app-runner.test.py
git commit -m "feat(hermes): hermes-app-runner — root oneshot, fixed argv, never re-runs (Option B §3.4)"
```

---

### Task 7: End-to-end, from MCP through broker and runner to a stub command

**Files:**
- Create: `infra/hermes-agent/bin/app-e2e.test.py`

**Interfaces:**
- Consumes: Tasks 2 and 4–6. It uses a manifest copy whose `command` is a stub script in a temp dir that prints the `--json` contract.

- [ ] **Step 1: Write the test**

```python
#!/usr/bin/env python3
"""Option B end to end in temp dirs: MCP tool call -> spool -> broker -> job -> runner -> stub
command -> done -> broker -> result -> MCP. No Docker, no root: the runner's owner is None."""
import importlib.util, json, os, sys, tempfile, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A


def load(name, file):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


MCP, BRK, RUN = load("mcp", "hermes-app-mcp.py"), load("brk", "hermes-app-broker.py"), load("run", "hermes-app-runner.py")
STUB = """#!/bin/sh
slug="$1"; shift
if [ "$1" = "--list" ]; then echo '{"status": "ok", "audits": ["2026-09-30_10-00-00"]}'; exit 0; fi
echo "{\\"status\\": \\"ok\\", \\"reason\\": null, \\"exit_code\\": 0, \\"ts\\": \\"2026-10-01_12-00-00\\", \\"steps\\": [{\\"name\\": \\"draft\\", \\"rc\\": 0, \\"seconds\\": 1.0}], \\"vault_path\\": \\"/var/lib/hermes/vaults/$slug/audits/2026-10-01_12-00-00-audit.md\\"}"
"""


class E2E(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        stub = os.path.join(t, "stub"); open(stub, "w").write(STUB); os.chmod(stub, 0o755)
        raw = json.load(open(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json")))
        raw["command"] = stub
        mdir = os.path.join(t, "apps"); os.makedirs(mdir)
        json.dump(raw, open(os.path.join(mdir, "ads-audit.json"), "w"))
        self.m = A.load_manifest(os.path.join(mdir, "ads-audit.json"), "ads-audit")
        self.spool, self.state = os.path.join(t, "spool"), os.path.join(t, "state")
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        for d in ("state", "jobs", "running", "done"):
            os.makedirs(os.path.join(self.state, d))
        reg = os.path.join(t, "clients.json")
        json.dump({"clients": {"acme-dental": {"status": "active", "customer_id": "1234567890"}}}, open(reg, "w"))
        self.ctx = BRK.Ctx(self.m, self.spool, self.state, reg, log=lambda s: None)

    def pump(self, _secs):
        """The MCP server's sleep: one broker + runner + broker cycle per poll."""
        BRK.drain_once(self.ctx); RUN.run_all(self.m, self.state, owner=None); BRK.collect_once(self.ctx)

    def call(self, name, **args):
        s = MCP.Server(self.m, self.spool, sleep=self.pump)
        r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return json.loads(r["result"]["content"][0]["text"])

    def test_run_then_quota_then_list(self):
        r = self.call("ads_audit_run", client="acme-dental")
        self.assertEqual((r["status"], r["vault_path"]),
                         ("ok", "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"))
        r2 = self.call("ads_audit_run", client="acme-dental")
        self.assertEqual((r2["status"], r2["reason"]), ("refused", "quota"))
        l = self.call("ads_audit_list", client="acme-dental")
        self.assertEqual(l["audits"], ["2026-09-30_10-00-00"])
        self.assertEqual(self.call("ads_audit_status", request_id=r["request_id"])["status"], "ok")

    def test_reboot_mid_run_reports_interrupted_and_never_reruns(self):
        req = A.make_request(self.m, "run", "acme-dental")
        A.write_json_atomic(os.path.join(self.spool, "requests"), req["request_id"] + ".json", req)
        BRK.drain_once(self.ctx)
        n = req["request_id"] + ".json"
        os.rename(os.path.join(self.state, "jobs", n), os.path.join(self.state, "running", n))  # "reboot" here
        calls = []
        RUN.run_all(self.m, self.state, execute=lambda a, t: calls.append(a) or (0, "", False), owner=None)
        BRK.recover(self.ctx); BRK.collect_once(self.ctx)
        self.assertEqual(calls, [])
        r = json.load(open(os.path.join(self.spool, "results", n)))
        self.assertEqual((r["status"], r["reason"]), ("failed", "interrupted"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `python3 infra/hermes-agent/bin/app-e2e.test.py -v`
Expected: PASS. If `test_run_then_quota_then_list` returns `pending`, confirm that the MCP `_wait` calls `sleep` before its first re-check (it checks, then sleeps, then checks). The pump then runs once per poll, and the result appears on the second check.

- [ ] **Step 3: Commit**

```bash
git add infra/hermes-agent/bin/app-e2e.test.py
git commit -m "test(hermes): Option B end-to-end — MCP to broker to runner to result, and reboot-mid-run"
```

---

### Task 8: The systemd units

**Files:**
- Create: `infra/hermes-agent/deploy/hermes-app-broker@.service`, `infra/hermes-agent/deploy/hermes-app-runner@.service`, `infra/hermes-agent/deploy/hermes-app-runner@.path`
- Modify: `infra/hermes-agent/deploy/units.test.py`

- [ ] **Step 1: Write the failing tests** (append a class to `units.test.py`; `unit()` and `live_lines()` already exist)

```python
class TestAppUnits(unittest.TestCase):
    def directives(self, name):
        return live_lines(unit(name))

    def test_broker_is_sandboxed_and_unprivileged(self):
        d = self.directives("hermes-app-broker@.service")
        for want in ("User=hermes-app-%i", "Group=hermes-app-%i", "SupplementaryGroups=hermes",
                     "NoNewPrivileges=true", "CapabilityBoundingSet=", "AmbientCapabilities=",
                     "PrivateNetwork=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true",
                     "UMask=0077", "RestrictAddressFamilies=AF_UNIX",
                     "ReadWritePaths=/var/lib/hermes/spool/apps/%i /var/lib/hermes/app-state/%i"):
            self.assertIn(want, d)
        body = unit("hermes-app-broker@.service")
        for banned in ("docker", "DOCKER_HOST", "sudo", "User=root"):
            self.assertNotIn(banned, body)

    def test_runner_is_a_root_oneshot_on_the_fixed_script(self):
        d = self.directives("hermes-app-runner@.service")
        self.assertIn("Type=oneshot", d)
        self.assertIn("User=root", d)
        self.assertIn("ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-app-runner.py --app %i", d)

    def test_path_unit_watches_jobs(self):
        d = self.directives("hermes-app-runner@.path")
        self.assertIn("DirectoryNotEmpty=/var/lib/hermes/app-state/%i/jobs", d)
        self.assertIn("Unit=hermes-app-runner@%i.service", d)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/deploy/units.test.py -v`
Expected: FAIL with `FileNotFoundError` for `hermes-app-broker@.service`.

- [ ] **Step 3: Create the units**

`deploy/hermes-app-broker@.service`:

```ini
[Unit]
Description=Hermes chat-trigger broker for %i (validates requests; never executes anything)
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
# Option B spec 2026-09-30 §3.3, §6. Its own user, never root, never docker, no sudo entry: its only
# path to root is the job file the root runner reads (hermes-app-runner@%i). Group hermes (gid
# 10000): read the governance registry and the gateway's 0640 request files; write 0640 results.
User=hermes-app-%i
Group=hermes-app-%i
SupplementaryGroups=hermes
UMask=0077
ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-app-broker.py --app %i --watch --interval 2
Restart=on-failure
RestartSec=5
# Full sandbox — possible only because this unit never needs sudo (the reason the hand-off tray exists).
NoNewPrivileges=true
CapabilityBoundingSet=
AmbientCapabilities=
PrivateNetwork=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/hermes/spool/apps/%i /var/lib/hermes/app-state/%i
RestrictAddressFamilies=AF_UNIX
MemoryMax=128M

[Install]
WantedBy=multi-user.target
```

`deploy/hermes-app-runner@.path`:

```ini
[Unit]
Description=Start the Hermes app runner for %i when the broker queues a job

[Path]
DirectoryNotEmpty=/var/lib/hermes/app-state/%i/jobs
Unit=hermes-app-runner@%i.service

[Install]
WantedBy=paths.target
```

`deploy/hermes-app-runner@.service`:

```ini
[Unit]
Description=Hermes app runner for %i (root; runs the manifest's one fixed command)

[Service]
# Option B spec 2026-09-30 §3.4. Root because the command it runs (run-client-audit) needs root.
# It reads only job files written by hermes-app-%i, never the spool; per-job timeouts come from
# the manifest, so this unit's own limit only bounds a pathological queue.
Type=oneshot
User=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-app-runner.py --app %i
TimeoutStartSec=6h
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 infra/hermes-agent/deploy/units.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/deploy/hermes-app-broker@.service infra/hermes-agent/deploy/hermes-app-runner@.service infra/hermes-agent/deploy/hermes-app-runner@.path infra/hermes-agent/deploy/units.test.py
git commit -m "feat(hermes): systemd units for the app broker (sandboxed) and runner (path-activated)"
```

---

### Task 9: The gateway: retire `claude-auth-init`; add the MCP config, the OpenRouter key and the skill

**Files:**
- Modify: `infra/hermes-agent/docker-compose.yml`, `infra/hermes-agent/Dockerfile`
- Delete: `infra/hermes-agent/bootstrap-claude-auth.sh`
- Modify: `infra/hermes-agent/config.yaml.example`, `infra/hermes-agent/.env.example`
- Create: `infra/hermes-agent/skills/ads-audits/SKILL.md`
- Create: `infra/hermes-agent/bin/gateway-config.test.py`

- [ ] **Step 1: Write the failing static test**

```python
#!/usr/bin/env python3
"""Static assertions on the gateway's compose service and Hermes config (Option B §3.1, §6).
Text-level on purpose: stdlib has no YAML parser, and each check is a line that must or must not exist."""
import os, re, unittest
AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    return open(os.path.join(AGENT, p), encoding="utf-8").read()


def service_block(compose, name):
    m = re.search(r"^  %s:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^[a-z]|\Z)" % re.escape(name), compose, re.S | re.M)
    return m.group(1) if m else ""


class T(unittest.TestCase):
    def test_claude_auth_init_is_gone(self):
        c = read("docker-compose.yml")
        self.assertNotIn("claude-auth-init", c)
        self.assertNotIn("bootstrap-claude-auth", read("Dockerfile"))
        self.assertFalse(os.path.exists(os.path.join(AGENT, "bootstrap-claude-auth.sh")))

    def test_gateway_mounts_no_client_data(self):
        gw = service_block(read("docker-compose.yml"), "hermes-agent")
        self.assertTrue(gw)
        for bad in ("vaults", "reports", "audit-data", "draft-out", "app-state", "/etc/hermes"):
            self.assertNotIn(bad, gw)
        self.assertIn("./skills/ads-audits:/opt/data/skills/ads-audits:ro", gw)

    def test_mcp_server_config_is_exact(self):
        cfg = read("config.yaml.example")
        self.assertIn('args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]', cfg)
        self.assertIn("include: [ads_audit_run, ads_audit_status, ads_audit_list]", cfg)
        self.assertIn("env: {}", cfg)

    def test_env_example_names_openrouter_and_no_anthropic_for_gateway(self):
        env = read(".env.example")
        self.assertRegex(env, r"(?m)^OPENROUTER_API_KEY=$")
        self.assertNotRegex(env, r"(?m)^ANTHROPIC_API_KEY=")

    def test_skill_exists_and_names_the_tools(self):
        s = read("skills/ads-audits/SKILL.md")
        for t in ("ads_audit_run", "ads_audit_status", "ads_audit_list", "show-audit"):
            self.assertIn(t, s)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 infra/hermes-agent/bin/gateway-config.test.py -v`
Expected: FAIL on every test.

- [ ] **Step 3: Make the changes**

1. `docker-compose.yml`:
   - Delete the whole `claude-auth-init:` service and its comment block.
   - In `hermes-agent`, delete the `depends_on:` block, and change the `env_file` comment to `# OPENROUTER_API_KEY (Hermes's own reasoning); no Anthropic key — drafts run in ads-drafter`.
   - Add the volume `- ./skills/ads-audits:/opt/data/skills/ads-audits:ro  # Option B: how Hermes calls the audit tools` after the ads-analyst skill line.
2. `Dockerfile`: delete the auth-bootstrap comment block and the `COPY bootstrap-claude-auth.sh …` and `RUN chmod … bootstrap-claude-auth.sh` lines. Then `git rm infra/hermes-agent/bootstrap-claude-auth.sh`.
3. `.env.example`:
   - Uncomment `OPENROUTER_API_KEY=` and give it this comment: `# Hermes's own reasoning (OpenRouter). Dedicated key, credit limit $10/month (spec §6).`
   - Delete the `ANTHROPIC_API_KEY=` line and its comment, and replace them with `# No Anthropic key here: the drafter reads /etc/hermes/.env.anthropic per run (spec §6).`
4. `config.yaml.example`: append:

```yaml
# Option B (spec 2026-09-30 §3.1): the ONE app Hermes may trigger, as three MCP tools. The broker
# on the host is the boundary; this block only gives the model typed tools instead of a shell.
mcp_servers:
  ads_audit:
    command: "python3"
    args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]
    env: {}
    timeout: 360
    tools:
      include: [ads_audit_run, ads_audit_status, ads_audit_list]
      resources: false
      prompts: false
```

   Then apply Task 1's measurements:
   - **If** Task 1 Step 1 found a provider-routing key, add it verbatim under `model:` or at the path Task 1 recorded, set to deny data collection and require ZDR, with a comment citing §13.
   - **Otherwise** add the comment `# OpenRouter privacy (data_collection deny, ZDR) is set at the ACCOUNT level: this Hermes has no config key for it (spec §13).`
   - **If** Task 1 Step 2 switched the model, change `model.default` to the recorded model.
5. `skills/ads-audits/SKILL.md`:

```markdown
---
name: ads-audits
description: Use when the operator asks to run, check, or list a client's Google Ads audit. Calls the ads_audit_run, ads_audit_status and ads_audit_list tools. Never reads or summarizes audit content; the operator reads drafts on the host.
---

# Client Google Ads audits

You can trigger a client's Google Ads trend audit and report its outcome. You never see the
audit's content, and you must not try to: drafts are read by the operator on the host.

## Tools

- `ads_audit_run(client)`: starts an audit for a registered client (its short name). It takes
  a few minutes. You get back a result, or `pending` with a `request_id`.
- `ads_audit_status(request_id)`: checks a pending request. It files nothing.
- `ads_audit_list(client)`: lists the timestamps of the client's past audits.

## Reporting a result

| status | What to tell the operator | Then |
|---|---|---|
| `ok` | the audit is done, its timestamp `ts`, and that they can read it with `sudo show-audit <client>` | stop |
| `refused` | it was refused, and the `reason` in plain words (`quota`: one audit per client per day; `disabled`: audits are switched off; `inactive_client`: not an active client; `precheck`: the server refused before starting; `bad_request`, `duplicate`) | stop. **Never call the tool again for that client today.** |
| `failed` | it failed at step `reason` (e.g. `collect`, `draft`, `timeout`, `interrupted`) | suggest the manual command `sudo run-client-audit <client>`; do not retry |
| `busy` | another audit is running on the server | offer to try later; do not loop |
| `pending` | it is still running, and the `request_id` | check with `ads_audit_status` once, only when the operator asks |

## Never

- Call `ads_audit_run` twice for the same client in one conversation.
- Retry a `refused` or `failed` result.
- Write into or read from `/opt/data/spool` yourself, or use the terminal to reach the audit system.
- Guess a client's short name. If unsure, ask the operator.
```

- [ ] **Step 4: Run to verify it passes, plus the suites that parse compose**

Run: `python3 infra/hermes-agent/bin/gateway-config.test.py -v && infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py`
Expected: all pass. If `bind_agreement.test.py` or `docker-create-proxy.test.py` asserts on the `claude-auth-init` service, update those assertions to drop it. Their comments mention it as history only, so don't edit comments unless they're now false.

- [ ] **Step 5: Commit**

```bash
git add -A infra/hermes-agent/docker-compose.yml infra/hermes-agent/Dockerfile infra/hermes-agent/bootstrap-claude-auth.sh infra/hermes-agent/config.yaml.example infra/hermes-agent/.env.example infra/hermes-agent/skills/ads-audits infra/hermes-agent/bin/gateway-config.test.py
git commit -m "feat(hermes): gateway gets MCP audit tools + OpenRouter key; claude-auth-init retired (Option B §3.1, §6)"
```

---

### Task 10: BRING-UP and README for part 2, then the PR

**Files:**
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (a new section "Chat-triggered audits — part 2: the chat trigger")
- Modify: `infra/hermes-agent/README.md` (architecture: the broker, runner and MCP tools; the secrets table)

- [ ] **Step 1: Write the BRING-UP section** with exactly these steps (each command on its own line; the key prompt goes in its own paste):

```markdown
## Chat-triggered audits — part 2: the chat trigger (spec 2026-09-30 §3, §6)

Requires part 1 on the box. Still not live until review #6.

1. Pull: `cd /opt/projects/claude_code && git pull --ff-only`
2. The app user (no login, no home, primary group of its own, member of hermes):
   `sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin hermes-app-ads-audit`
   `sudo usermod -aG hermes hermes-app-ads-audit`
   `id hermes-app-ads-audit` → groups `hermes-app-ads-audit,hermes`, and NOT docker or sudo
3. Layout: `cd /opt/hermes-agent && sudo python3 bin/init-host-layout.py --app ads-audit --apply; echo rc=$?` → `rc=0`
   Registry readable by the broker: `sudo -u hermes-app-ads-audit test -r /var/lib/hermes/governance/registry/clients.json && echo REG_OK`
4. Units:
   `sudo cp deploy/hermes-app-broker@.service deploy/hermes-app-runner@.service deploy/hermes-app-runner@.path /etc/systemd/system/`
   `sudo systemctl daemon-reload`
   `sudo systemctl enable --now hermes-app-broker@ads-audit hermes-app-runner@ads-audit.path`
   `systemctl is-active hermes-app-broker@ads-audit hermes-app-runner@ads-audit.path` → `active active`
5. OpenRouter: in the OpenRouter console create a dedicated key with limit $10, reset monthly; set
   the account's privacy to deny data-collecting providers (and ZDR where offered). Then, ALONE:
   `sudo python3 bin/install-env-secret.py set --file /opt/hermes-agent/.env --name OPENROUTER_API_KEY --prefix sk-or- --mode 0600`
6. Gateway config: `sudo diff data/config.yaml config.yaml.example` (review anything Hermes wrote
   itself), then `sudo install -o 10000 -g 10000 -m 640 config.yaml.example data/config.yaml`
7. Recreate the gateway without the retired sidecar:
   `sudo docker compose up -d --build --remove-orphans hermes-agent`
   `sudo docker compose ps -a` → no `claude-auth-init`
   `sudo test ! -e /opt/hermes-agent/data/home/.claude/settings.json && echo NO_CLAUDE_KEY_FILE`
   (if present: `sudo rm -f /opt/hermes-agent/data/home/.claude/settings.json`)
8. Tools visible: `sudo docker compose exec hermes-agent hermes mcp list` → `ads_audit` with 3 tools
9. Kill switch (for the review and for emergencies):
   on:  `sudo touch /var/lib/hermes/app-state/ads-audit/DISABLED`
   off: `sudo rm /var/lib/hermes/app-state/ads-audit/DISABLED`
10. First chat audit: `sudo docker compose exec -it hermes-agent hermes chat`, then ask
    "Run the Google Ads audit for <client>." Expect `ok` within ~5 min (or `pending`; ask for its
    status later). Journal: `journalctl -u hermes-app-broker@ads-audit -n 20`.
```

- [ ] **Step 2: Update the README** architecture table: the control plane holds the OpenRouter key only, and the executor runs in `ads-drafter` with the key from `/etc/hermes/.env.anthropic`. Add a section "Chat-triggered apps" describing the manifest, MCP, broker, runner, results and kill switch in five bullets. Remove the "How the executor gets its key" section, since it describes the retired sidecar, and replace it with one sentence pointing to spec §6.

- [ ] **Step 3: Run all suites, then commit, push and open the PR**

Run: `infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && node scripts/run-all-tests.js`
Expected: all pass.

```bash
git add infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): BRING-UP + README for Option B part 2 (the chat trigger)"
git push -u origin HEAD
gh pr create --title "feat(hermes): Option B part 2 — Hermes triggers audits via MCP → broker → runner" --body "$(cat <<'EOF'
Implements spec docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md §3, §6 (PR 2 of 3).

- registry/apps/ads-audit.json: the one declared entry for the app (ops, fixed argv, quotas, tools).
- hermes-app-mcp (gateway): three MCP tools; no policy. hermes-app-broker@ (unprivileged, NoNewPrivileges, no caps, no network): schema, replay, kill switch, client status, quota reserved before the job. hermes-app-runner@ (root oneshot, path-activated): fixed argv, never re-runs an interrupted job.
- Results carry only whitelisted enums, numbers, timestamps and a regex-checked vault path — no free text from any step reaches Hermes.
- Gateway: claude-auth-init retired (no Anthropic key in the gateway), OpenRouter key, MCP config, ads-audits skill.

Not exercised in CI: systemd sandbox behaviour and path activation (units.test.py asserts the files; the e2e runs the same code without systemd).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (done while writing)

- **Spec coverage:**
  - §2 components → Tasks 2 and 4–9;
  - §3.1 → Tasks 4 and 9; §3.2 → Task 2; §3.3 → Task 5; §3.4 → Task 6; §3.5 → Task 2 (`RC_STATUS`, `map_done`);
  - §6 (OpenRouter, no gateway Anthropic key, no sudo, unit hardening) → Tasks 8–10;
  - §7 → Tasks 5–7 (interrupted, the kill switch, busy release, never re-run, journal lines);
  - §12's measurement gaps → Task 1.
- **Review Focus mapping:** 1 → `test_kill_switch_refuses_and_the_refusal_is_final`; 2 → the e2e reboot test; 3 → `test_duplicate_id_writes_no_second_result`; 4 → `test_out_of_contract_is_internal`; 5 → `test_junk_names_fifos_and_old_requests_removed_unread` and `test_bounded_work_per_pass`.
- **Consistent names:** `Ctx`, `drain_once`, `collect_once`, `recover`, `expire_results`, `run_all`, `_execute`, `Server.handle`, `A.map_done`, `A.refused_result`, `A.Ledger.{append,seen,count,unresolved,reserved}` and `A.write_json_atomic(dirpath, name, obj, mode, uid, gid)` are used identically across Tasks 2 and 4–7.
