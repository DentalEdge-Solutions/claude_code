# Hermes Governed Mutation Syscall — Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the governed mutation rail *reachable* by Hermes — a request spool, a deliberately dumb in-container client, a host-side broker that drains it, and a Docker socket proxy — without giving Hermes any influence over what executes.

**Architecture:** Hermes writes a four-key identifier-only JSON request into `data/spool/requests/` (already read-write to the gateway via the existing `./data:/opt/data` mount). A single-threaded host-side broker validates it against a closed schema, records the `request_id` in the host-owned governance store's seen-set, reserves the approval *before* execution, then shells out to the unchanged `run-ads-mutate.sh` with two validated identifiers. Results land in `data/spool/results/` for Hermes to read. No request field is ever interpolated into a command string, and no Hermes-writable byte becomes an executed action.

**Tech Stack:** Python 3 **stdlib only** (no third-party imports anywhere in `bin/`), POSIX `sh`, Docker Compose, systemd (VPS only).

**Spec:** `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` — §6.2, §6.3, §6.4, §8, §12, and the corrected §7. Read it alongside this plan; the plan argues from it.

**Builds on:** `docs/superpowers/plans/2026-08-19-hermes-runtime-boundary.md` (Plan 1, merged at `b9cb1e2`) and its ledger `.superpowers/sdd/2026-08-19-hermes-runtime-boundary/progress.md` (rulings R19–R21).

**Upstream check:** `docs/evaluations/2026-08-24-upstream-hermes-release-check.md` — no upstream feature removes any component below. Verified 2026-08-24 against `NousResearch/hermes-agent`; our pinned image already *is* the Quicksilver release (v0.19.0). Do not upgrade the gateway during this plan.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec and the capsule's hard rules.

- **Stdlib only.** No third-party imports in `infra/hermes-agent/bin/`. `python3`, never `python`.
- **Closed request schema.** Exactly `{request_id, op, client, changeset}`. Any extra key is a **refusal**, not an ignored field (§8.2).
- **`op` is the literal `"apply"`.** No other value in v1. The syscall exposes `apply` only — **never `undo`** (§17.2: undo bypasses the kill switch and caps and needs no approval).
- **No model in the mutation path** (§17.1). Change-sets stay operator-authored. Hermes cannot author a change-set, only request application of one an operator wrote and approved.
- **No request field is ever interpolated into a command string.** The broker passes two validated identifiers as `--client` / `--changeset` in an `argv` list — never a shell string.
- **The seen-set lives in the governance store**, at `governance/seen/<slug>.jsonl`, never in the spool. A replay record Hermes can delete is not replay protection (§8).
- **Reservation precedes execution.** `reserved_at` + `request_id` are written to the approval record *before* the executor is spawned; `outcome` after. An approval carrying `reserved_at` is refused regardless of whether `outcome` was ever written (§7).
- **Fail-closed everywhere.** A missing, unreadable, or malformed limit must never become an unlimited one — the existing `read_mutate_execute` caps rule, extended to the new quotas.
- **Mutation stays DISABLED at rest.** No kill-switch file at `~/.hermes/governance/control/`. If a task enables it, that task turns it off again.
- **`main` is protected in both repos.** Open a PR; never push to `main`.
- **Redaction.** No client names, account ids, campaign ids, metrics, or drafts in git, specs, plans, tests, reports, or telemetry. Use `<slug-1>` / `<digits>`.
- **Never print a credential value**, and never write one — or its sha12 — into a tracked file.
- **Never run `docker compose config`** — it renders `env_file` secrets in cleartext.
- **Live verification** runs against the authorised **dormant pilot client only**, resolved via `vault_lib.resolve('<slug>')`. Never hardcode a customer id.

### Test discipline (non-negotiable; these are earned rules)

- **Both suites green:** `node scripts/run-all-tests.js` (21/21) and `infra/hermes-agent/bin/run-bin-tests.sh`.
- **Baseline measured 2026-08-24: 20 suites, 302 tests.** Per-suite counts are in the table below. **Confirm the test COUNT changed**, not merely that the suite says OK — a stray mid-file `unittest.main()` has previously caused six new tests to never run while appearing to pass.
- **Every negative test pairs with a positive control.** A probe proves nothing until it has refused what it should refuse — and, where the outcome is "it still works", a control that must SUCCEED.
- **Every task states its mutation proof**: the specific one-line edit to the implementation that must turn the new test red. Plan 1 shipped five tests that could not fail against the bug they existed to detect. The mutation proof is part of the task, not a review afterthought.

| Suite | Baseline tests |
|---|---|
| `apply-changeset.test.py` | 37 |
| `changeset_lib.test.py` | 78 |
| `approve-changeset.test.py` | 21 |
| `persist-run-record.test.py` | 18 |
| `registry-invariants.test.py` | 17 |
| `preflight-governance-access.test.py` | 9 |
| `governance_lib.test.py` | 9 |
| (13 others) | 113 |
| **Total** | **302 across 20 suites** |

---

## Deviations from the spec, recorded up front

Three, each with a reason. Silence here would be the failure mode this capsule keeps paying for.

**D1 — The socket proxy's allow-list is wider than "create/start on one image".** §6.4 specifies a proxy restricted to `create` and `start`. But `run-ads-mutate.sh` invokes `docker compose run --rm --no-deps`, and the Compose CLI needs considerably more of the Engine API than two endpoints: version negotiation, image inspection, container create/start/attach/wait/delete, and network inspection. A proxy allowing literally two endpoints breaks the rail. **Resolution:** Task 10 enumerates the exact endpoint set empirically (by logging what a real invocation requests) rather than guessing, and pins the *create* request by body inspection. The security property is preserved in substance — a broker compromise yields the ability to start that one image, not host root — but the endpoint list is longer than the spec's shorthand. The spec is amended by Task 13.

**D2 — We write our own proxy rather than adopting one.** The requirement "create/start on **one image**" cannot be met by an endpoint-level ACL proxy, because the image name lives in the JSON *body* of `POST /containers/create`, not in the method or path. Enforcing it requires body inspection. A general-purpose socket proxy that filters by method+path would satisfy the letter of §6.4 and none of its intent. A ~200-line stdlib proxy is also auditable in one sitting, which a third-party image is not, and it adds no supply-chain surface to the one component whose compromise is worst.

**D3 — Phase B is gated, not optional.** Tasks 1–9 (Phase A) produce a working, fully-tested syscall against a directly-reachable Docker socket. That is acceptable on a single-user dev machine. Tasks 10–11 (Phase B) add the socket proxy and systemd units. **Phase B must land before any VPS deploy**, because on a VPS the broker's Docker access is host root. Phase A must not be described as "done" in any deploy context without Phase B.

---

## Premises checked before this plan was written

Three assumptions the plan leans on were measured on 2026-08-24 rather than assumed. Two of the three were **wrong on first guess**, which is the reason this section exists.

| Premise | Result |
|---|---|
| `read_mutate_execute` ignores unknown keys in the `caps:` block, so the new quotas can live there without coupling the executor to a broker concern | **TRUE** — it iterates `CAP_KEYS` only; `read_block` still surfaces the quota keys for the separate reader. Task 3's design depends on this. |
| `os.replace` supports `dir_fd`, so the openat chain can end in an atomic swap | **FALSE on darwin.** `os.replace not in os.supports_dir_fd`; `os.rename`, `os.open`, `os.unlink`, `os.mkdir` all are. Task 8 uses `os.rename`. |
| `grep -rn "approve-changeset"` finds the call sites that Task 9 breaks | **FALSE.** It returns two prose mentions and zero call sites — the wrapper is invoked as `./changeset.sh approve`. Task 9 searches for `approve`. |

The second and third would each have surfaced as a mid-task failure with a confident-looking plan behind them.

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `infra/hermes-agent/bin/spool_lib.py` | Spool path contract, closed-schema validation, hostile-input reading. Imports only `governance_lib` — bottom of the dependency graph, like `governance_lib` itself. |
| `infra/hermes-agent/bin/spool_lib.test.py` | Suite for the above. |
| `infra/hermes-agent/bin/hermes-syscall.py` | In-container client. Two operations: write a request, read a result. No credential, no network, no policy. |
| `infra/hermes-agent/bin/hermes-syscall.test.py` | Suite for the above. |
| `infra/hermes-agent/bin/hermes-broker.py` | Host-side broker: drain loop, validation, quotas, reservation, subprocess invocation, result writing. |
| `infra/hermes-agent/bin/hermes-broker.test.py` | Suite for the above. |
| `infra/hermes-agent/bin/docker-create-proxy.py` | Phase B. Unix-socket → unix-socket Docker API proxy with a body-inspecting allow-list. |
| `infra/hermes-agent/bin/docker-create-proxy.test.py` | Suite for the above. |
| `infra/hermes-agent/deploy/hermes-broker.service` | Phase B. systemd unit for the broker. |
| `infra/hermes-agent/deploy/hermes-docker-proxy.service` | Phase B. systemd unit for the proxy. |

**Modified files**

| File | Change |
|---|---|
| `infra/hermes-agent/bin/changeset_lib.py` | Add `reserve_approval`, `record_outcome`, `seen_contains`, `append_seen`, `read_spool_quotas`, `SPOOL_QUOTA_KEYS`. |
| `infra/hermes-agent/bin/changeset_lib.test.py` | Tests for the above. |
| `infra/hermes-agent/bin/persist_run_record_shim.py` | Residuals (a) hardlinks, (b) openat dirfd chain, (c) `makedirs` ordering. |
| `infra/hermes-agent/bin/persist-run-record.test.py` | Tests for the above. |
| `infra/hermes-agent/bin/approve-changeset.py` | Residual (d) — bind the review→approve window. |
| `infra/hermes-agent/bin/approve-changeset.test.py` | Tests for the above. |
| `infra/hermes-agent/registry/projects.yaml` | Two new fail-closed quota keys under `mutate_execute.caps`. |
| `infra/hermes-agent/bin/registry-invariants.test.py` | Assert the new keys are present and well-formed. |
| `infra/hermes-agent/README.md` | Syscall, spool, broker, quotas, proxy, deploy sequence. |
| `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` | Record D1. |

**Deliberately unchanged:** `run-ads-mutate.sh` (its CLI is the broker's contract), `apply-changeset.py` (the eleven guards are untouched), `run-ads-report.sh` and `bin/run-ads-report.py` (frozen), `docker-compose.yml`'s `hermes-agent` service (the spool needs no new mount — `./data:/opt/data` is already read-write and `./bin:/opt/cc-bin:ro` already delivers `hermes-syscall.py`).

> **Verify that last claim before relying on it** (Task 1, Step 1). It is the kind of convenient assumption this capsule has been burned by.

---

# PHASE A — the syscall, locally verifiable end to end

---

### Task 1: `spool_lib.py` — path contract, closed schema, hostile-input reading

The spool is the **one surface Hermes can write**, so every read of it is hostile-input handling (§8). This module is the only place that parses it.

**Files:**
- Create: `infra/hermes-agent/bin/spool_lib.py`
- Create: `infra/hermes-agent/bin/spool_lib.test.py`

**Interfaces:**
- Consumes: `governance_lib.SLUG_RE`, `governance_lib.CHANGESET_ID_RE` (already exported; `governance_lib` imports nothing from `bin/`, so there is no cycle).
- Produces, for Tasks 2, 6, 7:
  - `DEFAULT_SPOOL_ROOT: str = "/opt/data/spool"`
  - `MAX_REQUEST_BYTES: int = 4096`
  - `REQUEST_KEYS: frozenset = {"request_id", "op", "client", "changeset"}`
  - `OPS: tuple = ("apply",)`
  - `FILENAME_RE`, `REQUEST_ID_RE` — compiled patterns
  - `class SpoolRefused(ValueError)`
  - `spool_root() -> str`
  - `requests_dir(root=None) -> str`, `results_dir(root=None) -> str`
  - `request_path(request_id, root=None) -> str`, `result_path(request_id, root=None) -> str`
  - `read_request_bytes(path) -> bytes`
  - `validate_request(obj, filename) -> dict`
  - `load_request(path) -> dict`
  - `write_result(request_id, payload, root=None) -> str`

- [ ] **Step 1: Verify the two mount assumptions before building on them**

An empty grep is not evidence. Confirm both mounts exist *and* that the check can see a known-present line.

Run:
```bash
cd infra/hermes-agent
grep -n '\./data:/opt/data'  docker-compose.yml     # must hit (spool is reachable rw)
grep -n '\./bin:/opt/cc-bin:ro' docker-compose.yml  # must hit (syscall is delivered)
grep -n 'NO-SUCH-MOUNT-CONTROL'  docker-compose.yml # must MISS — proves grep discriminates
```
Expected: first two print a line each; the third prints nothing and exits 1. If either of the first two misses, stop — the plan's "no compose change needed" claim is false and Task 7 must add the mount.

- [ ] **Step 2: Write the failing test**

Create `infra/hermes-agent/bin/spool_lib.test.py`:

```python
import json, os, stat, tempfile, unittest, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spool_lib as S

GOOD_ID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"
GOOD = {"request_id": GOOD_ID, "op": "apply", "client": "pilot-1",
        "changeset": "20260824-101500-abcdef01"}


class TestPaths(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("HERMES_SPOOL_ROOT", None)

    def tearDown(self):
        os.environ.pop("HERMES_SPOOL_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_SPOOL_ROOT"] = self._saved

    def test_default_is_the_container_path(self):
        self.assertEqual(S.spool_root(), "/opt/data/spool")

    def test_env_overrides_for_host_callers(self):
        os.environ["HERMES_SPOOL_ROOT"] = "/tmp/spool"
        self.assertEqual(S.requests_dir(), "/tmp/spool/requests")
        self.assertEqual(S.results_dir(), "/tmp/spool/results")

    def test_request_and_result_paths(self):
        self.assertEqual(S.request_path(GOOD_ID, "/tmp/s"),
                         "/tmp/s/requests/%s.json" % GOOD_ID)
        self.assertEqual(S.result_path(GOOD_ID, "/tmp/s"),
                         "/tmp/s/results/%s.json" % GOOD_ID)

    def test_bad_request_id_never_becomes_a_path(self):
        for bad in ("../../etc/passwd", "no-slashes/here", GOOD_ID + "\n", "", "A" * 36):
            with self.assertRaises(S.SpoolRefused):
                S.request_path(bad, "/tmp/s")


class TestValidate(unittest.TestCase):
    def test_accepts_the_exact_four_keys(self):
        got = S.validate_request(dict(GOOD), GOOD_ID + ".json")
        self.assertEqual(got["client"], "pilot-1")
        self.assertEqual(got["changeset"], "20260824-101500-abcdef01")

    def test_extra_key_is_a_refusal_not_an_ignored_field(self):
        obj = dict(GOOD); obj["operator"] = "root"
        with self.assertRaises(S.SpoolRefused) as cm:
            S.validate_request(obj, GOOD_ID + ".json")
        self.assertIn("operator", str(cm.exception))

    def test_missing_key_refuses(self):
        obj = dict(GOOD); del obj["changeset"]
        with self.assertRaises(S.SpoolRefused):
            S.validate_request(obj, GOOD_ID + ".json")

    def test_op_undo_is_refused(self):
        # §17.2: undo bypasses the kill switch and the caps and needs no approval.
        # The syscall exposes apply only. This test is the enforcement of that rule.
        obj = dict(GOOD); obj["op"] = "undo"
        with self.assertRaises(S.SpoolRefused):
            S.validate_request(obj, GOOD_ID + ".json")

    def test_any_op_other_than_apply_is_refused(self):
        for op in ("Apply", "apply ", "", "validate_only", None, 1):
            obj = dict(GOOD); obj["op"] = op
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_bad_slug_refuses(self):
        for slug in ("../etc", "UPPER", "pilot 1", "", "a" * 65, "pilot-1\n"):
            obj = dict(GOOD); obj["client"] = slug
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_bad_changeset_id_refuses(self):
        for cid in ("20260824-101500-ABCDEF01", "nope", "", "20260824-101500-abcdef0"):
            obj = dict(GOOD); obj["changeset"] = cid
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_filename_must_match_request_id(self):
        other = "1111aaaa-2222-4bbb-8ccc-3333dddd4444"
        with self.assertRaises(S.SpoolRefused) as cm:
            S.validate_request(dict(GOOD), other + ".json")
        self.assertIn("does not match", str(cm.exception))

    def test_non_object_refuses(self):
        for junk in ([], "string", 7, None):
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(junk, GOOD_ID + ".json")


class TestHostileReads(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, GOOD_ID + ".json")

    def _write(self, data):
        with open(self.p, "wb") as f:
            f.write(data)

    def test_control_a_wellformed_file_loads(self):
        # THE POSITIVE CONTROL. Every refusal below is meaningless unless this passes:
        # it proves the reader can actually read a legitimate request.
        self._write(json.dumps(GOOD).encode())
        self.assertEqual(S.load_request(self.p)["client"], "pilot-1")

    def test_oversized_file_refuses_and_is_not_read_whole(self):
        self._write(b"{" + b"x" * (S.MAX_REQUEST_BYTES * 4))
        with self.assertRaises(S.SpoolRefused) as cm:
            S.read_request_bytes(self.p)
        self.assertIn("cap", str(cm.exception))

    def test_symlink_refuses_rather_than_dereferences(self):
        target = os.path.join(self.d, "target.json")
        with open(target, "w") as f:
            json.dump(GOOD, f)
        link = os.path.join(self.d, "1111aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.symlink(target, link)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(link)
        # control: the same bytes at a real path DO load, so the refusal is about the
        # symlink and not about the content.
        self.assertEqual(S.load_request(target)["client"], "pilot-1")

    def test_directory_in_place_of_a_request_refuses(self):
        d = os.path.join(self.d, "2222aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.mkdir(d)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(d)

    def test_fifo_refuses_without_blocking(self):
        p = os.path.join(self.d, "3333aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.mkfifo(p)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(p)

    def test_malformed_json_refuses(self):
        self._write(b"{not json")
        with self.assertRaises(S.SpoolRefused):
            S.load_request(self.p)

    def test_non_utf8_refuses(self):
        self._write(b'{"request_id": "\xff\xfe"}')
        with self.assertRaises(S.SpoolRefused):
            S.load_request(self.p)


class TestWriteResult(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_result_is_written_and_readable(self):
        p = S.write_result(GOOD_ID, {"status": "refused", "exit_code": 2}, self.root)
        with open(p) as f:
            self.assertEqual(json.load(f)["exit_code"], 2)

    def test_result_write_is_atomic_leaving_no_tmp_behind(self):
        S.write_result(GOOD_ID, {"status": "ok"}, self.root)
        leftovers = [n for n in os.listdir(S.results_dir(self.root)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/spool_lib.test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'spool_lib'`.

- [ ] **Step 4: Write the implementation**

Create `infra/hermes-agent/bin/spool_lib.py`:

```python
#!/usr/bin/env python3
"""Request-spool contract for the governed mutation syscall. Stdlib-only.

The spool is the ONE surface Hermes can write, so every read here is hostile-input
handling (spec §8), not parsing. This module holds the whole of that discipline:
a closed four-key schema where an extra key REFUSES rather than being ignored, a
byte cap enforced twice, O_NOFOLLOW, and a regular-file assertion on the FD.

It imports only governance_lib, so it sits beside governance_lib at the bottom of the
dependency graph and shares that module's identifier regexes rather than restating
them. Restating them is how two validators drift into disagreeing about what a slug is.

It holds NO credential, performs NO network I/O, and makes NO policy decision. Whether
a validated request is ALLOWED is the broker's business; this module only decides
whether the bytes on disk are a well-formed request at all.
"""
import errno, json, os, re, stat, tempfile

import governance_lib

DEFAULT_SPOOL_ROOT = "/opt/data/spool"

# A few KB. A well-formed request is ~150 bytes; anything approaching this is either a
# mistake or an attempt to make the broker read an unbounded file into memory.
MAX_REQUEST_BYTES = 4096

REQUEST_KEYS = frozenset(("request_id", "op", "client", "changeset"))
OPS = ("apply",)                      # v1: apply only. NEVER undo — spec §17.2.

# Exactly the spec's §8.1 character class. Deliberately not tightened to a strict uuid4
# pattern: the filename and the request_id are cross-checked against each other, and a
# gratuitous divergence from the written spec is a worse defect than a permissive
# charset over a value that is never interpolated anywhere.
FILENAME_RE = re.compile(r"^[0-9a-f-]{36}\.json$")
REQUEST_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


class SpoolRefused(ValueError):
    """A request that cannot be proven well-formed. Subclasses ValueError so callers
    with an existing fail-closed ValueError handler refuse rather than crash."""


def spool_root():
    return os.environ.get("HERMES_SPOOL_ROOT", DEFAULT_SPOOL_ROOT)


def _root(root):
    return root or spool_root()


def requests_dir(root=None):
    return os.path.join(_root(root), "requests")


def results_dir(root=None):
    return os.path.join(_root(root), "results")


def _rid(request_id):
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise SpoolRefused("invalid request_id: %r" % (request_id,))
    return request_id


def request_path(request_id, root=None):
    return os.path.join(requests_dir(root), "%s.json" % _rid(request_id))


def result_path(request_id, root=None):
    return os.path.join(results_dir(root), "%s.json" % _rid(request_id))


def _open_regular_ro(path):
    """Open for reading with O_NOFOLLOW, then assert on the FD that it is a regular
    file of acceptable size.

    O_NONBLOCK matters: without it, opening a fifo that Hermes planted would BLOCK the
    single-threaded broker forever — a denial of service that looks like a hang, not a
    refusal. With it, the open succeeds and the fstat below rejects it as non-regular.

    Checked on the FD, never on the path, so nothing can be swapped between the test
    and the read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):
            raise SpoolRefused("%s is a symlink, refusing to follow it" % path)
        raise SpoolRefused("%s cannot be opened: %s" % (path, e))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SpoolRefused("%s is not a regular file, refusing" % path)
        if st.st_size > MAX_REQUEST_BYTES:
            raise SpoolRefused("%s is %d bytes, over the %d-byte cap — refusing"
                               % (path, st.st_size, MAX_REQUEST_BYTES))
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_request_bytes(path):
    """Read at most MAX_REQUEST_BYTES + 1 bytes and refuse if the file delivered more.

    The size is checked TWICE on purpose. The fstat in _open_regular_ro rejects a file
    that is already oversized; the bounded read rejects one that GREW between the fstat
    and the read, which is a writer Hermes controls and can therefore arrange.
    """
    fd = _open_regular_ro(path)
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        raise SpoolRefused("%s exceeded the %d-byte cap while being read — refusing"
                           % (path, MAX_REQUEST_BYTES))
    return data


def validate_request(obj, filename):
    """Validate a parsed request against the closed schema. Returns the request dict.

    Order follows spec §8: filename shape, exact key set, op, identifiers, then the
    filename/request_id cross-check. Replay is NOT checked here — the seen-set lives in
    the governance store and belongs to the broker (§8), because a replay record Hermes
    could reach is not replay protection.
    """
    if not FILENAME_RE.fullmatch(filename):
        raise SpoolRefused("filename %r does not match the request-file pattern" % filename)
    if not isinstance(obj, dict):
        raise SpoolRefused("request must be a JSON object, got %s" % type(obj).__name__)

    keys = set(obj)
    if keys != REQUEST_KEYS:
        extra = sorted(keys - REQUEST_KEYS)
        missing = sorted(REQUEST_KEYS - keys)
        raise SpoolRefused(
            "request schema is closed: extra=%s missing=%s — an unexpected key is a "
            "refusal, never an ignored field" % (extra, missing))

    op = obj["op"]
    if op not in OPS:
        raise SpoolRefused(
            "op %r is not permitted; v1 accepts only %r (undo is operator-only — it "
            "bypasses the kill switch and the caps and requires no approval)" % (op, OPS[0]))

    rid = obj["request_id"]
    if not isinstance(rid, str) or not REQUEST_ID_RE.fullmatch(rid):
        raise SpoolRefused("invalid request_id: %r" % (rid,))
    if filename != "%s.json" % rid:
        raise SpoolRefused("filename %r does not match request_id %r" % (filename, rid))

    client = obj["client"]
    if not isinstance(client, str) or not governance_lib.SLUG_RE.fullmatch(client):
        raise SpoolRefused("invalid client slug: %r" % (client,))

    cid = obj["changeset"]
    if not isinstance(cid, str) or not governance_lib.CHANGESET_ID_RE.fullmatch(cid):
        raise SpoolRefused("invalid changeset id: %r" % (cid,))

    return dict(obj)


def load_request(path):
    """read_request_bytes + JSON parse + validate_request, against the file's basename."""
    data = read_request_bytes(path)
    try:
        obj = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SpoolRefused("%s is not valid UTF-8 JSON: %s" % (path, e))
    return validate_request(obj, os.path.basename(path))


def write_result(request_id, payload, root=None):
    """Write <spool>/results/<request_id>.json atomically. Returns the path.

    A result is written on EVERY outcome including refusal (spec §12), so FILE
    EXISTENCE is the discriminator between "the broker has not processed this yet" and
    "the broker processed it and refused". Those are different events, and emptiness
    cannot separate them.
    """
    path = result_path(request_id, root)
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd infra/hermes-agent && python3 bin/spool_lib.test.py`
Expected: `OK`, `Ran 23 tests`.

- [ ] **Step 6: Prove the tests can fail — the mutation proof**

A test that cannot fail against the bug it exists to detect is worse than no test. Make each edit, confirm the named test goes RED, then revert.

| Edit `spool_lib.py` | Test that must turn RED |
|---|---|
| `if keys != REQUEST_KEYS:` → `if not REQUEST_KEYS <= keys:` | `test_extra_key_is_a_refusal_not_an_ignored_field` |
| `OPS = ("apply",)` → `OPS = ("apply", "undo")` | `test_op_undo_is_refused` |
| Delete `| os.O_NOFOLLOW` from the `os.open` flags | `test_symlink_refuses_rather_than_dereferences` |
| Delete the `st.st_size > MAX_REQUEST_BYTES` check | `test_oversized_file_refuses_and_is_not_read_whole` |
| `if filename != "%s.json" % rid:` → `if False:` | `test_filename_must_match_request_id` |

Run after each: `python3 bin/spool_lib.test.py`. Expected: FAIL naming that test. **Then `git checkout -- bin/spool_lib.py` before the next edit.**

- [ ] **Step 7: Run the whole suite and confirm the count changed**

Run: `cd infra/hermes-agent && ./bin/run-bin-tests.sh`
Expected: `hermes bin: 21/21 suites passed` — **21, not 20**. A new suite that is silently not discovered is the exact failure this check exists for.

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/spool_lib.py infra/hermes-agent/bin/spool_lib.test.py
git commit -m "feat(hermes): spool path contract with closed schema and hostile-input reads"
```

---

### Task 2: `hermes-syscall.py` — the deliberately dumb in-container client

Its power is bounded entirely by what the broker accepts. It holds no credential, performs no network I/O, and contains no policy — anything it could decide would be a decision a model could influence.

**Files:**
- Create: `infra/hermes-agent/bin/hermes-syscall.py`
- Create: `infra/hermes-agent/bin/hermes-syscall.test.py`

**Interfaces:**
- Consumes: `spool_lib.requests_dir`, `spool_lib.result_path`, `spool_lib.validate_request`, `spool_lib.REQUEST_KEYS`, `spool_lib.SpoolRefused` (Task 1).
- Produces, for Task 12's live gate: CLI `apply --client SLUG --changeset ID` (prints the `request_id`, exit 0) and `result --request-id RID`. Exit codes: `0` applied, `2` refused, `3` failed after a live mutation, `4` **no result yet** (distinct from refusal), `1` usage.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/hermes-syscall.test.py`:

```python
import importlib.util, io, json, os, sys, tempfile, unittest, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spool_lib as S


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _load("hermes_syscall", "hermes-syscall.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_SPOOL_ROOT")
        os.environ["HERMES_SPOOL_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HERMES_SPOOL_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_SPOOL_ROOT"] = self._saved

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = K.main(argv)
        return rc, out.getvalue(), err.getvalue()


class TestApply(Base):
    def test_writes_a_request_the_spool_validator_accepts(self):
        rc, out, _ = self.run_cli(["apply", "--client", "pilot-1",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, 0)
        rid = out.strip()
        p = S.request_path(rid, self.root)
        # The client and the broker must agree on what a request is. Round-tripping
        # through the BROKER's validator is the only check that proves they do.
        got = S.load_request(p)
        self.assertEqual(got["op"], "apply")
        self.assertEqual(got["client"], "pilot-1")
        self.assertEqual(set(got), set(S.REQUEST_KEYS))

    def test_each_call_gets_a_fresh_request_id(self):
        rids = {self.run_cli(["apply", "--client", "pilot-1",
                              "--changeset", "20260824-101500-abcdef01"])[1].strip()
                for _ in range(5)}
        self.assertEqual(len(rids), 5)

    def test_no_partial_file_is_ever_visible_to_the_broker(self):
        self.run_cli(["apply", "--client", "pilot-1",
                      "--changeset", "20260824-101500-abcdef01"])
        names = os.listdir(S.requests_dir(self.root))
        # Exactly one visible request; any temp file must be dot-prefixed so the
        # broker's FILENAME_RE scan cannot pick up a half-written request.
        visible = [n for n in names if not n.startswith(".")]
        self.assertEqual(len(visible), 1)
        self.assertTrue(S.FILENAME_RE.fullmatch(visible[0]))

    def test_bad_slug_is_refused_client_side_without_writing_anything(self):
        rc, _, err = self.run_cli(["apply", "--client", "../etc",
                                   "--changeset", "20260824-101500-abcdef01"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.isdir(S.requests_dir(self.root))
                         and os.listdir(S.requests_dir(self.root)))
        self.assertIn("client", err)

    def test_undo_is_not_a_subcommand(self):
        rc, _, _ = self.run_cli(["undo", "--client", "pilot-1",
                                 "--changeset", "20260824-101500-abcdef01"])
        self.assertNotEqual(rc, 0)


class TestResult(Base):
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"

    def _result(self, payload):
        S.write_result(self.RID, payload, self.root)

    def test_missing_result_is_pending_not_refused(self):
        # "No data" and "zero data" are different events; file EXISTENCE is the
        # discriminator. Collapsing these two would let a model read a pending
        # request as a refusal, or worse, a refusal as pending and retry it.
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 4)
        self.assertIn("pending", out.lower())

    def test_applied_result_exits_zero(self):
        self._result({"status": "applied", "classification": "accepted_applied",
                      "exit_code": 0})
        rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 0)

    def test_refusal_exits_two_and_is_not_rendered_as_retryable(self):
        self._result({"status": "refused", "classification": "refused_preflight",
                      "exit_code": 2, "detail": "guard 1: mutation is disabled"})
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 2)
        low = out.lower()
        self.assertIn("refused", low)
        # A model that retries a refusal is a model applying pressure to a guard.
        for word in ("retry", "try again", "temporar", "transient"):
            self.assertNotIn(word, low)

    def test_failure_after_mutation_is_its_own_exit_code(self):
        self._result({"status": "failed", "classification": "failed_after_mutation",
                      "exit_code": 3})
        rc, _, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, 3)

    def test_classification_is_surfaced_verbatim(self):
        self._result({"status": "refused", "classification": "refused_quota",
                      "exit_code": 2})
        _, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertIn("refused_quota", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/hermes-syscall.test.py`
Expected: FAIL — `FileNotFoundError` on `hermes-syscall.py`.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/hermes-syscall.py`:

```python
#!/usr/bin/env python3
"""The in-container mutation syscall client. Stdlib-only.

DELIBERATELY DUMB. It does exactly two things: write a well-formed request into the
spool, and read back a result. It holds no credential, performs no network I/O, and
contains NO POLICY — its power is bounded entirely by what the broker accepts. Anything
it could decide would be a decision a model could influence.

It exposes `apply` only. There is no `undo` subcommand and there must never be one:
undo deliberately bypasses the kill switch and the daily caps so that cleanup is never
blocked by the switch that stopped the damage, and it requires no approval. A
Hermes-callable undo would be an unapproved account change on demand (spec §17.2).

It never re-interprets the broker's classification. In particular a refusal is never
rendered as an error that looks retryable, because a model that retries a refusal is a
model applying pressure to a guard (spec §12).

Invoked in-container as:  python3 /opt/cc-bin/hermes-syscall.py apply --client <slug> --changeset <id>
"""
import argparse, json, os, sys, tempfile, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spool_lib as S

# Exit codes. `4` is NOT an error: it means the broker has not written a result yet,
# which is a different event from a refusal and must never collapse into one.
EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_FAILED_AFTER_MUTATION, EXIT_PENDING = 0, 1, 2, 3, 4

_EXIT_BY_CODE = {0: EXIT_OK, 2: EXIT_REFUSED, 3: EXIT_FAILED_AFTER_MUTATION}


def submit(client, changeset, root=None):
    """Write one request atomically and return its request_id.

    The temp file is DOT-PREFIXED so it cannot match the broker's FILENAME_RE scan: a
    broker that picked up a half-written request would be reading torn JSON from the
    one writer it does not trust.
    """
    request_id = str(uuid.uuid4())
    req = {"request_id": request_id, "op": "apply",
           "client": client, "changeset": changeset}
    # Validate our own output against the BROKER's validator before writing. If these
    # two ever disagree about what a request is, the disagreement should surface here
    # and not as an unexplained refusal in a log the operator has to go find.
    S.validate_request(req, "%s.json" % request_id)

    d = S.requests_dir(root)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % request_id)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(req, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return request_id


def fetch(request_id, root=None):
    """Return (exit_code, text). Absent result => PENDING, never a refusal."""
    path = S.result_path(request_id, root)
    if not os.path.isfile(path):
        return EXIT_PENDING, ("pending: the broker has not written a result for %s yet. "
                              "This is not a refusal — a refusal always writes a result "
                              "file." % request_id)
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return EXIT_REFUSED, "unreadable result for %s: %s" % (request_id, e)
    if not isinstance(rec, dict):
        return EXIT_REFUSED, "malformed result for %s" % request_id

    # Surfaced VERBATIM. No re-wording, no severity re-grading, no advice about what to
    # do next — the broker's classification is the answer.
    status = rec.get("status", "?")
    classification = rec.get("classification", "?")
    code = rec.get("exit_code")
    lines = ["request %s" % request_id,
             "  status         %s" % status,
             "  classification %s" % classification,
             "  exit_code      %s" % code]
    if rec.get("detail"):
        lines.append("  detail         %s" % rec["detail"])
    return _EXIT_BY_CODE.get(code, EXIT_REFUSED), "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hermes-syscall",
        description="Request application of an OPERATOR-AUTHORED, OPERATOR-APPROVED "
                    "change-set. This client cannot author a change-set, cannot approve "
                    "one, and cannot undo one.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply", help="file a request to apply an approved change-set")
    a.add_argument("--client", required=True)
    a.add_argument("--changeset", required=True)

    r = sub.add_parser("result", help="read the broker's result for a request")
    r.add_argument("--request-id", dest="request_id", required=True)

    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    try:
        if args.cmd == "apply":
            print(submit(args.client, args.changeset))
            return EXIT_OK
        code, text = fetch(args.request_id)
        print(text)
        return code
    except S.SpoolRefused as e:
        print("hermes-syscall: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except OSError as e:
        print("hermes-syscall: %s" % e, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd infra/hermes-agent && python3 bin/hermes-syscall.test.py`
Expected: `OK`, `Ran 11 tests`.

- [ ] **Step 5: Mutation proof**

| Edit `hermes-syscall.py` | Test that must turn RED |
|---|---|
| In `fetch`, return `EXIT_REFUSED` instead of `EXIT_PENDING` for a missing file | `test_missing_result_is_pending_not_refused` |
| Append `" — retry later"` to the refusal text | `test_refusal_exits_two_and_is_not_rendered_as_retryable` |
| `prefix=".%s." % request_id` → `prefix="%s." % request_id` | `test_no_partial_file_is_ever_visible_to_the_broker` |
| Add an `undo` subparser calling `submit` | `test_undo_is_not_a_subcommand` |

Revert with `git checkout -- bin/hermes-syscall.py` after each.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/hermes-syscall.py infra/hermes-agent/bin/hermes-syscall.test.py
git commit -m "feat(hermes): hermes-syscall, the identifier-only in-container client"
```

---

### Task 3: per-client spool quotas, fail-closed, configured beside the existing caps

Refused requests do not consume the applies cap, so without a quota **nothing bounds how many Hermes can file** — a denial of service on the broker and unbounded log noise (§8).

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (add after `read_mutate_execute`, ~line 262)
- Modify: `infra/hermes-agent/bin/changeset_lib.test.py` (append a class above the trailing `unittest.main()`)
- Modify: `infra/hermes-agent/registry/projects.yaml` (the `mutate_execute.caps` block)
- Modify: `infra/hermes-agent/bin/registry-invariants.test.py`

**Interfaces:**
- Consumes: `changeset_lib.read_block`, `changeset_lib._CAP_VALUE_RE` (existing).
- Produces, for Task 6: `SPOOL_QUOTA_KEYS: tuple`, `read_spool_quotas(path, project) -> {"max_pending_requests": int, "accepted_requests_per_client_day": int}`.

> **Why a separate reader rather than adding to `CAP_KEYS`:** `read_mutate_execute` iterates `CAP_KEYS` and requires every one of them, so adding the quotas there would make `apply-changeset.py` refuse whenever a quota is missing — coupling the *executor* to a *broker* concern. `read_block` already collects every cap key it finds, so the two new keys ride along in the same `caps:` block and a separate fail-closed reader requires them only of the broker.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, **above** the trailing `if __name__ == "__main__":` block (a mid-file `unittest.main()` has previously caused new tests to never run):

```python
class TestSpoolQuotas(unittest.TestCase):
    HEAD = ("version: 1\n"
            "projects:\n"
            "  proj:\n"
            "    workdir: /projects/proj\n"
            "    mutate_execute:\n"
            "      runner: /opt/ads-venv/bin/python3\n"
            "      script_dir: code\n"
            "      allow:\n"
            "        - mutate_campaign_negative\n"
            "      caps:\n")

    def _reg(self, caps_lines):
        fd, p = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(self.HEAD + caps_lines)
        self.addCleanup(os.unlink, p)
        return p

    FULL = ("        actions_per_changeset: 25\n"
            "        actions_per_client_day: 100\n"
            "        applies_per_client_day: 5\n"
            "        approval_ttl_hours: 24\n"
            "        max_pending_requests: 8\n"
            "        accepted_requests_per_client_day: 20\n")

    def test_reads_both_quotas(self):
        q = C.read_spool_quotas(self._reg(self.FULL), "proj")
        self.assertEqual(q["max_pending_requests"], 8)
        self.assertEqual(q["accepted_requests_per_client_day"], 20)

    def test_missing_quota_refuses_rather_than_becoming_unlimited(self):
        for drop in ("max_pending_requests", "accepted_requests_per_client_day"):
            partial = "".join(l for l in self.FULL.splitlines(True)
                              if not l.strip().startswith(drop + ":"))
            with self.assertRaises(ValueError) as cm:
                C.read_spool_quotas(self._reg(partial), "proj")
            self.assertIn(drop, str(cm.exception))

    def test_malformed_quota_refuses(self):
        for bad in ("0", "-1", "abc", "", "1e6", "999999999"):
            broken = self.FULL.replace("max_pending_requests: 8",
                                       "max_pending_requests: %s" % bad)
            with self.assertRaises(ValueError):
                C.read_spool_quotas(self._reg(broken), "proj")

    def test_control_the_existing_caps_still_parse_unchanged(self):
        # THE POSITIVE CONTROL for this task: adding two keys to the caps block must
        # not disturb the executor's own cap reader. If this breaks, the quotas were
        # added in the wrong place.
        m = C.read_mutate_execute(self._reg(self.FULL), "proj")
        self.assertEqual(m["caps"]["applies_per_client_day"], 5)
        self.assertEqual(m["caps"]["approval_ttl_hours"], 24)
        self.assertNotIn("max_pending_requests", m["caps"])

    def test_duplicate_quota_key_still_refuses(self):
        dup = self.FULL + "        max_pending_requests: 9999\n"
        with self.assertRaises(ValueError):
            C.read_spool_quotas(self._reg(dup), "proj")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/changeset_lib.test.py`
Expected: FAIL — `AttributeError: module 'changeset_lib' has no attribute 'read_spool_quotas'`.

- [ ] **Step 3: Write the implementation**

Insert into `infra/hermes-agent/bin/changeset_lib.py` immediately after `read_mutate_execute`:

```python
# Spool quotas live in the SAME caps: block as the mutation caps — tuning them stays a
# config edit, never a code change (spec §8) — but they are read SEPARATELY. They bound
# the BROKER, not the executor: refused requests never consume applies_per_client_day,
# so without these nothing bounds how many requests Hermes can file. Keeping them out
# of CAP_KEYS is what stops apply-changeset.py refusing over a broker-only setting.
SPOOL_QUOTA_KEYS = ("max_pending_requests", "accepted_requests_per_client_day")


def read_spool_quotas(path, project):
    """Per-client spool quotas, fail-closed exactly like the mutation caps.

    An unreadable limit must never become an unlimited one — the same rule the caps
    already follow, and the reason a missing key raises instead of defaulting.
    """
    got = read_block(path, project, "mutate_execute")
    quotas = {}
    for k in SPOOL_QUOTA_KEYS:
        v = got["caps"].get(k)
        if v is None:
            raise ValueError(
                f"missing spool quota {k!r} for project {project!r} — quotas are "
                "fail-closed; an unreadable limit must never become an unlimited one")
        if not _CAP_VALUE_RE.fullmatch(v) or int(v) < 1:
            raise ValueError(f"invalid spool quota {k}={v!r} — must be a positive integer")
        quotas[k] = int(v)
    return quotas
```

- [ ] **Step 4: Add the keys to the registry**

In `infra/hermes-agent/registry/projects.yaml`, extend the `mutate_execute.caps` block (currently ending at `approval_ttl_hours: 24`):

```yaml
      caps:                        # fail-closed: missing or malformed => refuse
        actions_per_changeset: 25      # largest batch a human can review in one sitting
        actions_per_client_day: 100
        applies_per_client_day: 5      # load-bearing cap against malfunction
        approval_ttl_hours: 24
        # --- spool quotas (Plan 2). Read by the BROKER, not the executor. Refused
        # requests never consume applies_per_client_day, so without these nothing
        # bounds how many requests Hermes can file: unbounded log noise and a
        # denial of service on a single-threaded broker.
        max_pending_requests: 8            # unprocessed requests allowed to queue per client
        accepted_requests_per_client_day: 20   # accepted (not merely filed) per client per UTC day
```

- [ ] **Step 5: Assert the keys are present in the real registry**

Append to `infra/hermes-agent/bin/registry-invariants.test.py`, above the trailing `unittest.main()`:

```python
class TestSpoolQuotasDeclared(unittest.TestCase):
    def test_the_real_registry_declares_both_quotas(self):
        # The unit tests above use synthetic registries. This one asserts against the
        # FILE THAT SHIPS — a quota that parses in a fixture but is absent from
        # projects.yaml is a broker that refuses every request on the VPS.
        q = C.read_spool_quotas(REGISTRY, "claude_google_ads")
        self.assertGreaterEqual(q["max_pending_requests"], 1)
        self.assertGreaterEqual(q["accepted_requests_per_client_day"], 1)

    def test_quotas_are_not_absurdly_large(self):
        # A quota of 999999 is a quota in name only. This is a smoke check against a
        # careless edit, not a policy statement.
        q = C.read_spool_quotas(REGISTRY, "claude_google_ads")
        self.assertLessEqual(q["max_pending_requests"], 100)
        self.assertLessEqual(q["accepted_requests_per_client_day"], 500)
```

> If `registry-invariants.test.py` does not already bind `REGISTRY` and `C`, reuse whatever names that file already uses for the shipped registry path and `changeset_lib`; do not introduce a second convention.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd infra/hermes-agent && python3 bin/changeset_lib.test.py && python3 bin/registry-invariants.test.py`
Expected: `Ran 83 tests` (78 + 5) and `Ran 19 tests` (17 + 2), both `OK`.

- [ ] **Step 7: Mutation proof**

| Edit | Test that must turn RED |
|---|---|
| `if v is None:` → `if False:` in `read_spool_quotas` | `test_missing_quota_refuses_rather_than_becoming_unlimited` |
| `or int(v) < 1` → `or int(v) < 0` | `test_malformed_quota_refuses` (the `0` case) |
| Delete `max_pending_requests` from `projects.yaml` | `test_the_real_registry_declares_both_quotas` |
| Add the two quota keys to `CAP_KEYS` | `test_control_the_existing_caps_still_parse_unchanged` |

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py \
        infra/hermes-agent/registry/projects.yaml infra/hermes-agent/bin/registry-invariants.test.py
git commit -m "feat(hermes): fail-closed per-client spool quotas beside the mutation caps"
```

---

### Task 4: reservation and the replay seen-set — both in the governance store

Two mechanisms, one task, because they share the same property: **Hermes must not be able to reach either of them.** The seen-set lives in `governance/seen/<slug>.jsonl`, not in the spool — a replay record Hermes can delete is not replay protection (§8). The reservation is written *before* the executor is spawned — a crash must cost an unusable approval, never a duplicate account change (§7).

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (add after `append_log`, ~line 490)
- Modify: `infra/hermes-agent/bin/changeset_lib.test.py`

**Interfaces:**
- Consumes: `governance_lib.seen_path` (already exists — Plan 1 added it for exactly this), `governance_lib.approval_path`, `changeset_lib._atomic_write_json`, `changeset_lib.ISO`, `changeset_lib._require_str`.
- Produces, for Task 6:
  - `append_seen(slug, request_id, now) -> None`
  - `seen_contains(slug, request_id) -> bool`
  - `reserve_approval(slug, cid, request_id, now) -> dict`
  - `record_outcome(slug, cid, outcome, now) -> dict`

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/changeset_lib.test.py`, above the trailing `unittest.main()`:

```python
class TestSeenSet(unittest.TestCase):
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_unseen_then_seen(self):
        self.assertFalse(C.seen_contains("pilot-1", self.RID))
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertTrue(C.seen_contains("pilot-1", self.RID))

    def test_the_seen_set_is_written_into_the_governance_store(self):
        # The WHOLE POINT. If this lands in the spool, Hermes can delete it and every
        # request_id becomes replayable.
        C.append_seen("pilot-1", self.RID, NOW)
        expected = governance_lib.seen_path("pilot-1", self.root)
        self.assertTrue(os.path.isfile(expected))
        self.assertNotIn("spool", expected)

    def test_seen_is_per_client_not_global(self):
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertFalse(C.seen_contains("pilot-2", self.RID))

    def test_unreadable_seen_set_refuses_rather_than_reporting_unseen(self):
        # Fail-closed. An unreadable seen-set reported as "not seen" would ADMIT every
        # replay — the same shape as the caps rule: an unreadable limit must never
        # become an unlimited one.
        p = governance_lib.seen_path("pilot-1", self.root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.mkdir(p)                      # a directory where the file should be
        with self.assertRaises(ValueError):
            C.seen_contains("pilot-1", self.RID)

    def test_control_a_readable_seen_set_does_not_raise(self):
        # The positive control for the refusal above.
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertTrue(C.seen_contains("pilot-1", self.RID))


class TestReservation(unittest.TestCase):
    CID = "20260824-101500-abcdef01"
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"
    DIGEST = "a" * 64

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        C.write_approval("pilot-1", self.CID, self.DIGEST, "operator", NOW, 24)

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_reserving_records_the_timestamp_and_the_request(self):
        rec = C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        self.assertEqual(rec["request_id"], self.RID)
        self.assertEqual(rec["reserved_at"], NOW.strftime(C.ISO))

    def test_a_reserved_approval_no_longer_verifies(self):
        # This is the single-use property, asserted through the EXECUTOR's own guard
        # rather than by re-reading the file — verify_approval is what actually stops
        # the second apply, so that is what must be shown to refuse.
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError) as cm:
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)
        self.assertIn("already reserved", str(cm.exception))

    def test_control_an_unreserved_approval_verifies(self):
        # The positive control: without it, the refusal above could be caused by
        # anything at all.
        self.assertEqual(
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)["sha256"],
            self.DIGEST)

    def test_double_reservation_refuses(self):
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError):
            C.reserve_approval("pilot-1", self.CID, "1111aaaa-2222-4bbb-8ccc-3333dddd4444", NOW)

    def test_reserving_a_nonexistent_approval_refuses(self):
        with self.assertRaises(ValueError):
            C.reserve_approval("pilot-1", "20260824-101500-99999999", self.RID, NOW)

    def test_outcome_requires_a_prior_reservation(self):
        # An outcome without a reservation means the ordering was inverted somewhere.
        with self.assertRaises(ValueError):
            C.record_outcome("pilot-1", self.CID, "applied", NOW)

    def test_outcome_is_recorded_after_reservation(self):
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        rec = C.record_outcome("pilot-1", self.CID, "applied", NOW)
        self.assertEqual(rec["outcome"], "applied")
        self.assertEqual(rec["request_id"], self.RID)

    def test_an_interrupted_apply_is_not_a_reusable_approval(self):
        # Reserved but no outcome ever written — the crash case. The approval must
        # still be dead. This is the ordering property from spec §7 stated as a test:
        # a crash costs an unusable approval, never a duplicate account change.
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError):
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/changeset_lib.test.py`
Expected: FAIL — `AttributeError: ... has no attribute 'append_seen'`.

- [ ] **Step 3: Write the implementation**

Insert into `infra/hermes-agent/bin/changeset_lib.py` after `append_log`:

```python
# --- replay protection -------------------------------------------------------------
# The seen-set lives in the GOVERNANCE STORE, never in the spool. That is the whole
# point: the spool is the one tree Hermes can write, and a replay record Hermes can
# delete is not replay protection (spec §8).

def append_seen(slug, request_id, now):
    """Record an accepted request_id, fsynced before returning.

    Written BEFORE the broker acts on the request. If the process dies between this
    append and the apply, the id is burned and the request is refused as a replay —
    which costs a re-request, whereas the opposite ordering costs a duplicate account
    change.
    """
    p = governance_lib.seen_path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rec = {"request_id": _require_str(request_id, "request_id"),
           "seen_at": now.strftime(ISO)}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # fsync the DIRECTORY as well, for the same reason append_log does: on the first
    # append the file is newly created, and fsyncing its contents does not persist the
    # directory entry that names it. Losing that entry loses the whole replay history,
    # which seen_contains would then read as a legitimate "never seen".
    dfd = os.open(os.path.dirname(p), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def seen_contains(slug, request_id):
    """True when this request_id has already been accepted for this client.

    FAIL-CLOSED: an unreadable or malformed seen-set RAISES rather than returning
    False. Returning False there would admit every replay — the same failure shape as
    an unreadable cap becoming an unlimited one.
    """
    request_id = _require_str(request_id, "request_id")
    p = governance_lib.seen_path(slug)
    if not os.path.exists(p):
        return False                       # never written for this client yet
    try:
        with open(p, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if not isinstance(rec, dict) or "request_id" not in rec:
                    raise ValueError("seen-set %s line %d is malformed" % (p, lineno))
                if rec["request_id"] == request_id:
                    return True
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(
            "unreadable seen-set for %r (%s) — refusing rather than treating every "
            "request_id as unseen" % (slug, e))
    return False


# --- approval reservation ----------------------------------------------------------
# Written by the BROKER, host-side: the approvals directory is mounted :ro inside the
# executor container, so the executor cannot do this itself.

def _load_approval(slug, cid):
    p = approval_path(slug, cid)
    if not os.path.isfile(p):
        raise ValueError(f"no approval record for change-set {cid!r}")
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"unreadable approval record for {cid!r}: {e}")
    if not isinstance(rec, dict):
        raise ValueError(f"malformed approval record for {cid!r}")
    return p, rec


def reserve_approval(slug, cid, request_id, now):
    """Mark an approval consumed BEFORE the executor is invoked. Returns the record.

    THE ORDERING IS LOAD-BEARING (spec §7). Consuming after success leaves a window:
    if the broker or the host dies between the mutations landing and the mark being
    written, the approval is still live and the same change-set can be applied a second
    time. Reserving first means a crash costs an unusable approval, which a human
    recovers by approving again.

    Safe against concurrent reservation only because the broker holds a per-slug
    advisory lock around the whole request (see hermes-broker.py). This function does
    a read-modify-write and is NOT itself atomic against a second writer.
    """
    p, rec = _load_approval(slug, cid)
    if "reserved_at" in rec:
        raise ValueError(
            "approval for %r is already reserved (reserved_at=%s) — approvals are "
            "single-use" % (cid, rec.get("reserved_at")))
    rec["reserved_at"] = now.strftime(ISO)
    rec["request_id"] = _require_str(request_id, "request_id")
    _atomic_write_json(p, rec)
    return rec


def record_outcome(slug, cid, outcome, now):
    """Phase two of the two-phase record: what actually happened. Returns the record.

    Requires a prior reservation. An outcome with no reservation would mean the
    ordering was inverted somewhere, and that is exactly the defect this refuses to
    paper over.
    """
    p, rec = _load_approval(slug, cid)
    if "reserved_at" not in rec:
        raise ValueError(
            f"approval {cid!r} has no reserved_at — refusing to record an outcome for "
            "an apply that was never reserved; the reservation must precede execution")
    rec["outcome"] = _require_str(outcome, "outcome")
    rec["finished_at"] = now.strftime(ISO)
    _atomic_write_json(p, rec)
    return rec
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/hermes-agent && python3 bin/changeset_lib.test.py`
Expected: `Ran 96 tests` (83 + 13), `OK`.

- [ ] **Step 5: Mutation proof**

| Edit `changeset_lib.py` | Test that must turn RED |
|---|---|
| `governance_lib.seen_path(slug)` → a path under `spool_lib.spool_root()` | `test_the_seen_set_is_written_into_the_governance_store` |
| In `seen_contains`, `raise ValueError(...)` → `return False` in the `except` | `test_unreadable_seen_set_refuses_rather_than_reporting_unseen` |
| In `reserve_approval`, `if "reserved_at" in rec:` → `if False:` | `test_double_reservation_refuses` |
| In `record_outcome`, delete the `reserved_at` precondition | `test_outcome_requires_a_prior_reservation` |

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py
git commit -m "feat(hermes): governance-store replay seen-set and pre-execution approval reservation"
```

---

### Task 5: broker — validation, quotas, replay, and refusal (no execution yet)

The broker is privileged code and must be reviewed as such: small, no network listener, a closed input schema, hostile-input handling. This task builds everything **up to** the decision to execute, and proves that on every refusal path **the subprocess is never spawned**.

**Files:**
- Create: `infra/hermes-agent/bin/hermes-broker.py`
- Create: `infra/hermes-agent/bin/hermes-broker.test.py`
- Modify: `infra/hermes-agent/bin/governance_lib.py` (add `lock_path`)
- Modify: `infra/hermes-agent/bin/governance_lib.test.py`

**Interfaces:**
- Consumes: all of Tasks 1, 3, 4; `vault_lib.resolve`; `changeset_lib.registry_projects_path`.
- Produces, for Task 6:
  - `governance_lib.lock_path(slug, root=None) -> str`
  - `MAX_SPOOL_FILES: int = 256`
  - `class Decision` — `namedtuple("Decision", "accept classification detail")`
  - `classify(req, quotas, pending_count, now) -> Decision`
  - `drain(root=None, runner=None, now=None) -> list[dict]` — one pass; `runner` is a callable `(argv) -> (returncode, stdout)`, defaulting to the real subprocess runner in Task 6.

- [ ] **Step 1: Add the lock path (the broker's mutual exclusion lives host-side)**

Append to `infra/hermes-agent/bin/governance_lib.py`:

```python
def lock_path(slug, root=None):
    """Per-client advisory lock for the broker. Lives under control/, which is mounted
    :ro into the executor and not mounted at all into the gateway — so no container can
    take, hold, or delete it. A lock in the spool would be a lock the thing being
    serialised can remove."""
    return os.path.join(_root(root), "control", ".locks", "%s.lock" % _slug(slug))
```

Append to `infra/hermes-agent/bin/governance_lib.test.py`, above the trailing `unittest.main()`:

```python
class TestLockPath(unittest.TestCase):
    def test_lock_path(self):
        self.assertEqual(G.lock_path("acme-dental", "/tmp/gov"),
                         "/tmp/gov/control/.locks/acme-dental.lock")

    def test_lock_path_is_not_in_the_spool(self):
        self.assertNotIn("spool", G.lock_path("acme-dental", "/tmp/gov"))

    def test_bad_slug_refuses(self):
        for bad in ("../etc", "UPPER", "acme-dental\n", ""):
            with self.assertRaises(ValueError):
                G.lock_path(bad, "/tmp/gov")
```

- [ ] **Step 2: Write the failing broker test**

Create `infra/hermes-agent/bin/hermes-broker.test.py`:

```python
import datetime, importlib.util, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spool_lib as S
import changeset_lib as C
import governance_lib


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("hermes_broker", "hermes-broker.py")

NOW = datetime.datetime(2026, 8, 24, 10, 15, 0, tzinfo=datetime.timezone.utc)
CID = "20260824-101500-abcdef01"
SLUG = "pilot-1"
DIGEST = "a" * 64

REGISTRY_YAML = """version: 1
projects:
  testproj:
    workdir: /projects/testproj
    mutate_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
        max_pending_requests: 2
        accepted_requests_per_client_day: 3
"""


class RecordingRunner:
    """A runner that records every invocation and NEVER executes anything.

    The point of this class is a single assertion used throughout: on a refusal,
    `calls` must stay EMPTY. Asserting only that the result says "refused" would pass
    against a broker that refused *after* mutating a live account.
    """

    def __init__(self, rc=0, stdout=""):
        self.calls = []
        self.rc = rc
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return self.rc, self.stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp()
        self.spool = tempfile.mkdtemp()
        self.regdir = tempfile.mkdtemp()
        self.registry = os.path.join(self.regdir, "projects.yaml")
        with open(self.registry, "w") as f:
            f.write(REGISTRY_YAML)
        self.clients = os.path.join(self.regdir, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {SLUG: {"customer_id": "1234567890",
                                          "project": "testproj",
                                          "status": "active"}}}, f)
        self._env = {k: os.environ.get(k) for k in
                     ("HERMES_GOVERNANCE_ROOT", "HERMES_SPOOL_ROOT", "VAULT_ROOT")}
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        os.environ["HERMES_SPOOL_ROOT"] = self.spool
        os.environ["VAULT_ROOT"] = os.path.join(self.regdir, "vaults")
        os.makedirs(os.path.join(self.gov, "registry"), exist_ok=True)
        with open(governance_lib.clients_registry_path(self.gov), "w") as f:
            json.dump({"clients": {SLUG: {"customer_id": "1234567890",
                                          "project": "testproj",
                                          "status": "active"}}}, f)
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def file_request(self, **over):
        req = {"request_id": over.pop("request_id", str(__import__("uuid").uuid4())),
               "op": "apply", "client": SLUG, "changeset": CID}
        req.update(over)
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        name = over.get("_filename", "%s.json" % req["request_id"])
        with open(os.path.join(d, name), "w") as f:
            json.dump(req, f)
        return req["request_id"]

    def drain(self, runner):
        return B.drain(spool=self.spool, projects=self.registry,
                       runner=runner, now=NOW)

    def result_for(self, rid):
        with open(S.result_path(rid, self.spool)) as f:
            return json.load(f)


class TestRefusalsNeverExecute(Base):
    def test_control_a_valid_request_DOES_execute(self):
        # THE POSITIVE CONTROL for this whole class. Every "never spawned" assertion
        # below is worthless unless the broker can actually be made to spawn.
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(len(r.calls), 1)
        self.assertEqual(self.result_for(rid)["classification"], "accepted_applied")

    def test_extra_key_refuses_without_spawning(self):
        rid = self.file_request(operator="root")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_request")

    def test_op_undo_refuses_without_spawning(self):
        rid = self.file_request(op="undo")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_filename_mismatch_refuses_without_spawning(self):
        rid = self.file_request(_filename="1111aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_replayed_request_id_refuses_without_spawning(self):
        rid = self.file_request()
        self.drain(RecordingRunner())          # first pass consumes it
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)   # fresh approval
        self.file_request(request_id=rid)      # same id, filed again
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_replay_survives_deletion_of_the_whole_spool(self):
        # The property that justifies putting the seen-set in the governance store.
        # Hermes deleting the spool must not re-admit a used request_id.
        rid = self.file_request()
        self.drain(RecordingRunner())
        import shutil
        shutil.rmtree(self.spool)
        C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
        self.file_request(request_id=rid)
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_replay")

    def test_pending_quota_refuses_the_excess_without_spawning(self):
        # max_pending_requests is 2 in the fixture registry.
        for _ in range(5):
            self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertLessEqual(len(r.calls), 2)
        classifications = [json.load(open(os.path.join(S.results_dir(self.spool), n)))
                           ["classification"] for n in os.listdir(S.results_dir(self.spool))]
        self.assertIn("refused_quota", classifications)

    def test_daily_accepted_quota_refuses_without_spawning(self):
        # accepted_requests_per_client_day is 3 in the fixture registry.
        for _ in range(3):
            self.file_request()
            self.drain(RecordingRunner())
            C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
        self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_symlinked_request_refuses_without_spawning(self):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        target = os.path.join(self.spool, "elsewhere.json")
        with open(target, "w") as f:
            json.dump({"request_id": "1111aaaa-2222-4bbb-8ccc-3333dddd4444",
                       "op": "apply", "client": SLUG, "changeset": CID}, f)
        os.symlink(target, os.path.join(d, "1111aaaa-2222-4bbb-8ccc-3333dddd4444.json"))
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])

    def test_a_result_is_written_on_every_outcome(self):
        # §12: file EXISTENCE is the discriminator between "not processed yet" and
        # "processed and refused". A refusal that writes nothing is indistinguishable
        # from a broker that is down.
        rid = self.file_request(op="undo")
        self.drain(RecordingRunner())
        self.assertTrue(os.path.isfile(S.result_path(rid, self.spool)))

    def test_the_request_file_is_removed_after_processing(self):
        rid = self.file_request()
        self.drain(RecordingRunner())
        self.assertFalse(os.path.isfile(S.request_path(rid, self.spool)))


class TestNoInterpolation(Base):
    def test_the_runner_receives_an_argv_list_of_validated_identifiers_only(self):
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        argv = r.calls[0]
        self.assertIsInstance(argv, list)
        self.assertIn("--client", argv)
        self.assertIn("--changeset", argv)
        self.assertEqual(argv[argv.index("--client") + 1], SLUG)
        self.assertEqual(argv[argv.index("--changeset") + 1], CID)
        # No request field reaches the command as anything but these two values.
        self.assertNotIn(rid, argv)
        # And undo is never passed, on any path.
        self.assertNotIn("--undo", argv)

    def test_a_shell_metacharacter_slug_never_reaches_the_runner(self):
        rid = self.file_request(client="pilot-1; rm -rf /")
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])


class TestGlobalCeiling(Base):
    def test_an_absurd_number_of_request_files_is_refused_wholesale(self):
        d = S.requests_dir(self.spool)
        os.makedirs(d, exist_ok=True)
        for i in range(B.MAX_SPOOL_FILES + 5):
            with open(os.path.join(d, "%036d.json" % i), "w") as f:
                f.write("{}")
        r = RecordingRunner()
        out = self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertTrue(any(o.get("classification") == "refused_spool_overflow"
                            for o in out))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py`
Expected: FAIL — `FileNotFoundError` on `hermes-broker.py`.

- [ ] **Step 4: Write the broker's validation core**

Create `infra/hermes-agent/bin/hermes-broker.py` (the execution half arrives in Task 6; write the whole file now with `_run_subprocess` stubbed to raise, so Task 6 has one obvious hole to fill):

```python
#!/usr/bin/env python3
"""Host-side broker: drains the request spool and invokes the governed mutation rail.

PRIVILEGED CODE. It runs on the host, it can start containers, and it is the only
component that reads a tree Hermes can write. It is deliberately small, has no network
listener, accepts a closed input schema, and treats every byte of the spool as hostile.

WHAT IT WILL NOT DO, BY CONSTRUCTION:
  * It never interpolates a request field into a command string. The two validated
    identifiers are passed as separate argv elements to a fixed program. There is no
    shell anywhere in this file.
  * It never passes --undo. Undo bypasses the kill switch and the caps and needs no
    approval, so it stays operator-only (spec §17.2).
  * It never trusts the spool for replay state. The seen-set is in the governance
    store, which no container mounts.
  * It never executes before reserving. A crash must cost an unusable approval, never
    a duplicate account change (spec §7).

The single-threaded drain plus a per-client advisory lock is what makes the
read-modify-write in changeset_lib.reserve_approval safe.
"""
import argparse, collections, datetime, errno, fcntl, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import governance_lib
import spool_lib as S
import vault_lib

HERE = os.path.dirname(os.path.abspath(__file__))
MUTATE_SH = os.path.join(os.path.dirname(HERE), "run-ads-mutate.sh")

# A ceiling on how many request files one drain will even look at. Without it, Hermes
# can make the broker's directory scan itself the denial of service — the per-client
# quotas cannot help, because attributing a file to a client requires parsing it.
MAX_SPOOL_FILES = 256

# Subprocess wall-clock ceiling. A hung executor must not wedge a single-threaded
# broker forever.
RUNNER_TIMEOUT_SECONDS = 900

Decision = collections.namedtuple("Decision", "accept classification detail")

ACCEPT = Decision(True, "accepted", "")


def _utcday(now):
    return now.strftime("%Y-%m-%d")


class _ClientLock:
    """flock on a host-only path under control/.locks/. Not in the spool: a lock the
    serialised party can delete is not a lock."""

    def __init__(self, slug):
        self.path = governance_lib.lock_path(slug)
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


def _accepted_today(slug, now):
    """How many request_ids were accepted for this client today, read from the
    governance-store seen-set. Fail-closed: an unreadable seen-set raises."""
    p = governance_lib.seen_path(slug)
    if not os.path.exists(p):
        return 0
    day = _utcday(now)
    n = 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ('"seen_at": "%s' % day) in line:
                    n += 1
    except OSError as e:
        raise ValueError("unreadable seen-set for %r: %s" % (slug, e))
    return n


def classify(req, quotas, pending_count, accepted_today, now):
    """Decide whether a SCHEMA-VALID request may proceed. Pure; no side effects.

    Kept pure and separate from drain() so the ordering of the checks is reviewable in
    one screen, and so each refusal reason can be tested without a filesystem.
    """
    if pending_count > quotas["max_pending_requests"]:
        return Decision(False, "refused_quota",
                        "client has %d pending requests, over the max_pending_requests "
                        "limit of %d" % (pending_count, quotas["max_pending_requests"]))
    if accepted_today >= quotas["accepted_requests_per_client_day"]:
        return Decision(False, "refused_quota",
                        "client has already had %d requests accepted today, at the "
                        "accepted_requests_per_client_day limit of %d"
                        % (accepted_today, quotas["accepted_requests_per_client_day"]))
    return ACCEPT


def _write_result(rid, spool, classification, status, exit_code, detail, now):
    return S.write_result(rid, {
        "request_id": rid,
        "status": status,
        "classification": classification,
        "exit_code": exit_code,
        "detail": detail,
        "finished_at": now.strftime(C.ISO),
    }, spool)


def _discard(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
```

*(the drain loop and `_run_subprocess` follow in Task 6 — do not write them yet)*

- [ ] **Step 5: Write the drain loop's refusal paths**

Append to `infra/hermes-agent/bin/hermes-broker.py`:

```python
def _scan(spool):
    """Return (names, overflow). Only names matching the request-file pattern; a
    dot-prefixed temp file from a half-written request cannot match."""
    d = S.requests_dir(spool)
    if not os.path.isdir(d):
        return [], False
    names = sorted(n for n in os.listdir(d) if S.FILENAME_RE.fullmatch(n))
    return names[:MAX_SPOOL_FILES], len(names) > MAX_SPOOL_FILES


def _parse_all(spool, names):
    """Parse every candidate once. Returns (parsed, rejected) where parsed is a list of
    (name, req) and rejected is a list of (name, reason)."""
    parsed, rejected = [], []
    d = S.requests_dir(spool)
    for name in names:
        try:
            parsed.append((name, S.load_request(os.path.join(d, name))))
        except S.SpoolRefused as e:
            rejected.append((name, str(e)))
    return parsed, rejected


def drain(spool=None, projects=None, runner=None, now=None):
    """One pass over the spool. Returns a list of outcome dicts (also written as
    result files). `runner` is a callable (argv) -> (returncode, stdout)."""
    spool = spool or S.spool_root()
    projects = projects or C.registry_projects_path()
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    runner = runner or _run_subprocess
    outcomes = []

    names, overflow = _scan(spool)
    if overflow:
        # Refuse the whole drain rather than servicing an arbitrary prefix. Attributing
        # files to clients requires parsing them, so a flooded spool cannot be triaged
        # per-client — and quietly working through the first 256 would make the flood
        # look like normal operation.
        outcomes.append({"classification": "refused_spool_overflow",
                         "detail": "more than %d request files present; refusing the "
                                   "entire drain" % MAX_SPOOL_FILES})
        return outcomes

    parsed, rejected = _parse_all(spool, names)

    for name, reason in rejected:
        rid = name[:-len(".json")]
        if S.REQUEST_ID_RE.fullmatch(rid):
            outcomes.append({"request_id": rid, "classification": "refused_request",
                             "detail": reason})
            _write_result(rid, spool, "refused_request", "refused", 2, reason, now)
        _discard(os.path.join(S.requests_dir(spool), name))

    pending = collections.Counter(req["client"] for _, req in parsed)

    for name, req in parsed:
        rid, slug, cid = req["request_id"], req["client"], req["changeset"]
        path = os.path.join(S.requests_dir(spool), name)
        try:
            with _ClientLock(slug):
                outcome = _process(req, spool, projects, pending[slug], runner, now)
        except (ValueError, KeyError, OSError) as e:
            outcome = {"request_id": rid, "classification": "refused_request",
                       "detail": str(e)}
            _write_result(rid, spool, "refused_request", "refused", 2, str(e), now)
        outcomes.append(outcome)
        _discard(path)
    return outcomes


def _process(req, spool, projects, pending_count, runner, now):
    """One locked request. Refuses before any side effect that could reach Google."""
    rid, slug, cid = req["request_id"], req["client"], req["changeset"]

    if C.seen_contains(slug, rid):
        detail = "request_id %s has already been accepted — replay refused" % rid
        _write_result(rid, spool, "refused_replay", "refused", 2, detail, now)
        return {"request_id": rid, "classification": "refused_replay", "detail": detail}

    rec = vault_lib.resolve(slug)                       # unknown slug raises -> refusal
    quotas = C.read_spool_quotas(projects, rec["project"])
    decision = classify(req, quotas, pending_count, _accepted_today(slug, now), now)
    if not decision.accept:
        _write_result(rid, spool, decision.classification, "refused", 2,
                      decision.detail, now)
        return {"request_id": rid, "classification": decision.classification,
                "detail": decision.detail}

    # Accepted. Burn the id BEFORE acting: if the process dies here the request is
    # refused as a replay, which costs a re-request. The opposite ordering costs a
    # duplicate account change.
    C.append_seen(slug, rid, now)
    return _execute(req, spool, runner, now)
```

- [ ] **Step 6: Stub `_execute` so the refusal tests can run**

Append (Task 6 replaces the body):

```python
def _run_subprocess(argv):
    raise NotImplementedError("Task 6")


def _execute(req, spool, runner, now):
    raise NotImplementedError("Task 6")
```

- [ ] **Step 7: Run the refusal tests**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py -k Refusal -v; python3 bin/hermes-broker.test.py -k NoInterpolation -v; python3 bin/hermes-broker.test.py -k GlobalCeiling -v`
Expected: every `refused_*` test PASSES. `test_control_a_valid_request_DOES_execute` and the two `TestNoInterpolation` tests still FAIL with `NotImplementedError` — that is correct at this step and is what Task 6 fixes.

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/hermes-broker.py infra/hermes-agent/bin/hermes-broker.test.py \
        infra/hermes-agent/bin/governance_lib.py infra/hermes-agent/bin/governance_lib.test.py
git commit -m "feat(hermes): broker validation, quotas and replay refusal — no execution path yet"
```

---

### Task 6: broker — reservation, execution, and exit-code mapping

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-broker.py` (replace the two Task-5 stubs)
- Modify: `infra/hermes-agent/bin/hermes-broker.test.py`

**Interfaces:**
- Consumes: `changeset_lib.reserve_approval`, `changeset_lib.record_outcome` (Task 4).
- Produces, for Task 7: `_run_subprocess(argv) -> (int, str)`, `_execute(req, spool, runner, now) -> dict`, `CLASSIFICATION_BY_RC: dict`.

> **A Plan-1 fact that removes work here:** `run-ads-mutate.sh` already calls `bin/persist-run-record.py` itself, so the broker does **not** persist `result.json` / `timeline.md` — spec §6.5 assigned that to the broker, but Plan 1 put it in the wrapper. The broker's only artefact is the spool result. **This is also precisely where parked residual (a) becomes reachable**: the broker runs that persist step as the governance store's owner. Task 8 closes it, and Task 8 must land before Task 13's live gate.

- [ ] **Step 1: Write the failing tests**

Append to `infra/hermes-agent/bin/hermes-broker.test.py`, above the trailing `unittest.main()`:

```python
class TestExecution(Base):
    def test_reservation_is_written_before_the_runner_is_called(self):
        # The ordering property from spec §7, asserted DIRECTLY: the runner inspects
        # the approval record at the moment it is invoked. If reservation happened
        # after execution, reserved_at would be absent here.
        seen = {}

        def runner(argv):
            p = governance_lib.approval_path(SLUG, CID)
            with open(p) as f:
                seen["rec"] = json.load(f)
            return 0, ""

        self.file_request()
        self.drain(runner)
        self.assertIn("reserved_at", seen["rec"])

    def test_a_failing_executor_still_leaves_the_approval_unusable(self):
        # The crash case. An interrupted apply is not a reusable approval.
        self.file_request()
        self.drain(RecordingRunner(rc=3))
        with self.assertRaises(ValueError):
            C.verify_approval(SLUG, CID, DIGEST, NOW)

    def test_exit_codes_are_not_collapsed(self):
        cases = {0: ("accepted_applied", "applied"),
                 1: ("refused_usage", "refused"),
                 2: ("refused_preflight", "refused"),
                 3: ("failed_after_mutation", "failed")}
        for rc, (classification, status) in cases.items():
            C.write_approval(SLUG, CID, DIGEST, "operator", NOW, 24)
            rid = self.file_request()
            self.drain(RecordingRunner(rc=rc))
            got = self.result_for(rid)
            self.assertEqual(got["classification"], classification, "rc=%d" % rc)
            self.assertEqual(got["status"], status, "rc=%d" % rc)
            self.assertEqual(got["exit_code"], rc)

    def test_an_unknown_exit_code_is_treated_as_failure_not_success(self):
        rid = self.file_request()
        self.drain(RecordingRunner(rc=42))
        got = self.result_for(rid)
        self.assertEqual(got["status"], "failed")
        self.assertNotEqual(got["classification"], "accepted_applied")

    def test_executor_output_never_reaches_the_spool_result(self):
        # §17.3: per-action resource names must not reach Hermes. The spool result is
        # Hermes-readable, so the executor's stdout must not be copied into it.
        marker = "CAMPAIGN-RESOURCE-NAME-MARKER-9f8e7d"
        rid = self.file_request()
        self.drain(RecordingRunner(rc=0, stdout="applied 3 actions %s" % marker))
        blob = json.dumps(self.result_for(rid))
        self.assertNotIn(marker, blob)

    def test_a_missing_approval_refuses_without_calling_the_runner(self):
        os.unlink(governance_lib.approval_path(SLUG, CID))
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_approval")

    def test_an_already_reserved_approval_refuses_without_calling_the_runner(self):
        C.reserve_approval(SLUG, CID, "1111aaaa-2222-4bbb-8ccc-3333dddd4444", NOW)
        rid = self.file_request()
        r = RecordingRunner()
        self.drain(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result_for(rid)["classification"], "refused_approval")

    def test_the_outcome_is_recorded_on_the_approval(self):
        self.file_request()
        self.drain(RecordingRunner(rc=0))
        with open(governance_lib.approval_path(SLUG, CID)) as f:
            self.assertEqual(json.load(f)["outcome"], "accepted_applied")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py -k Execution`
Expected: FAIL with `NotImplementedError: Task 6`.

- [ ] **Step 3: Replace the two stubs**

In `infra/hermes-agent/bin/hermes-broker.py`, replace the Task-5 stubs with:

```python
# Exit semantics are load-bearing and must not be collapsed (spec §12):
#   0 success · 1 usage · 2 pre-flight refusal (NOTHING was mutated) · 3 failure after
#   at least one live mutation landed.
# An unrecognised code is treated as a FAILURE, never as a success: the only safe
# reading of "the executor did something we do not understand" is that it may have
# touched the account.
CLASSIFICATION_BY_RC = {
    0: ("accepted_applied", "applied"),
    1: ("refused_usage", "refused"),
    2: ("refused_preflight", "refused"),
    3: ("failed_after_mutation", "failed"),
}
UNKNOWN_RC = ("failed_unknown_exit", "failed")

# Fixed, non-identifying detail strings. The executor's stdout is DELIBERATELY not
# copied into the spool result: the spool is Hermes-readable, and per-action resource
# names are exactly what §17.3 keeps out of Hermes's reach. The full executor output
# goes to the broker's own stderr, which is host-side and lands in the journal.
DETAIL_BY_CLASSIFICATION = {
    "accepted_applied": "the change-set was applied",
    "refused_usage": "the executor refused with a usage error; nothing was mutated",
    "refused_preflight": "a guard refused before any mutation; nothing was mutated",
    "failed_after_mutation": "the apply failed AFTER at least one live mutation landed "
                             "— an operator must reconcile this run",
    "failed_unknown_exit": "the executor exited with an unrecognised status; treat the "
                           "account as possibly modified",
}


def _run_subprocess(argv):
    """Run the mutation wrapper. argv is a LIST — there is no shell here, and no
    request field is ever part of the program name or an option name."""
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=RUNNER_TIMEOUT_SECONDS)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _execute(req, spool, runner, now):
    rid, slug, cid = req["request_id"], req["client"], req["changeset"]

    # RESERVE FIRST. Not after success — a crash between the mutations landing and the
    # mark being written would otherwise leave the approval live and the same
    # change-set applicable a second time (spec §7).
    try:
        C.reserve_approval(slug, cid, rid, now)
    except (ValueError, OSError) as e:
        detail = "approval unavailable: %s" % e
        _write_result(rid, spool, "refused_approval", "refused", 2, detail, now)
        return {"request_id": rid, "classification": "refused_approval", "detail": detail}

    argv = [MUTATE_SH, "--client", slug, "--changeset", cid]
    try:
        rc, output = runner(argv)
    except subprocess.TimeoutExpired:
        # A timeout may have left mutations in flight. It is not a refusal.
        rc, output = 3, "executor exceeded %ds" % RUNNER_TIMEOUT_SECONDS

    classification, status = CLASSIFICATION_BY_RC.get(rc, UNKNOWN_RC)
    # Host-side only. Never into the spool.
    print("broker: request %s client %s changeset %s rc=%d\n%s"
          % (rid, slug, cid, rc, output), file=sys.stderr)
    try:
        C.record_outcome(slug, cid, classification, now)
    except (ValueError, OSError) as e:
        print("broker: could not record outcome for %s: %s" % (cid, e), file=sys.stderr)

    _write_result(rid, spool, classification, status, rc,
                  DETAIL_BY_CLASSIFICATION[classification], now)
    return {"request_id": rid, "classification": classification, "exit_code": rc}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py`
Expected: `OK`, `Ran 23 tests` — including the previously-failing control `test_control_a_valid_request_DOES_execute`.

- [ ] **Step 5: Mutation proof**

| Edit `hermes-broker.py` | Test that must turn RED |
|---|---|
| Move the `C.reserve_approval(...)` block to *after* `runner(argv)` | `test_reservation_is_written_before_the_runner_is_called` |
| `CLASSIFICATION_BY_RC.get(rc, UNKNOWN_RC)` → `.get(rc, ("accepted_applied", "applied"))` | `test_an_unknown_exit_code_is_treated_as_failure_not_success` |
| Add `"output": output` to the `_write_result` payload | `test_executor_output_never_reaches_the_spool_result` |
| `CLASSIFICATION_BY_RC[2]` → `("accepted_applied", "applied")` | `test_exit_codes_are_not_collapsed` |
| Delete the `C.append_seen(slug, rid, now)` call in `_process` | `test_replayed_request_id_refuses_without_spawning` |

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/hermes-broker.py infra/hermes-agent/bin/hermes-broker.test.py
git commit -m "feat(hermes): broker execution path with pre-execution reservation and uncollapsed exit codes"
```

---

### Task 7: broker CLI, watch loop, and a real end-to-end drain

Everything so far ran against a fake runner. This task proves the broker can drive a **real** executable and that the wiring — spool paths, registry resolution, governance root — is correct outside the unit tests.

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-broker.py` (add `main`, `watch`)
- Modify: `infra/hermes-agent/bin/hermes-broker.test.py`

**Interfaces:**
- Produces, for Tasks 11 and 13: CLI `hermes-broker.py --once` and `hermes-broker.py --watch [--interval SECONDS]`.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/hermes-broker.test.py`, above `unittest.main()`:

```python
class TestRealSubprocess(Base):
    """The fake runner proves the logic. This proves the WIRING — that the broker can
    actually start a program and read its status back."""

    def _fake_mutate(self, exit_code, body="echo ran"):
        p = os.path.join(self.regdir, "fake-mutate.sh")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n%s\nexit %d\n" % (body, exit_code))
        os.chmod(p, 0o755)
        return p

    def test_a_real_subprocess_exit_code_reaches_the_result(self):
        script = self._fake_mutate(2)
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            rid = self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
            got = self.result_for(rid)
        finally:
            B.MUTATE_SH = orig
        self.assertEqual(got["exit_code"], 2)
        self.assertEqual(got["classification"], "refused_preflight")

    def test_control_a_real_subprocess_success_also_reaches_the_result(self):
        # The must-SUCCEED control: without it, "exit 2 arrives" could be produced by a
        # broker that reports 2 for everything.
        script = self._fake_mutate(0)
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            rid = self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
            got = self.result_for(rid)
        finally:
            B.MUTATE_SH = orig
        self.assertEqual(got["exit_code"], 0)
        self.assertEqual(got["classification"], "accepted_applied")

    def test_the_wrapper_is_invoked_with_exactly_four_argv_elements(self):
        script = os.path.join(self.regdir, "echo-argv.sh")
        with open(script, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$#" > "$ARGC_OUT"\nexit 0\n')
        os.chmod(script, 0o755)
        argc_out = os.path.join(self.regdir, "argc.txt")
        os.environ["ARGC_OUT"] = argc_out
        orig, B.MUTATE_SH = B.MUTATE_SH, script
        try:
            self.file_request()
            B.drain(spool=self.spool, projects=self.registry, now=NOW)
        finally:
            B.MUTATE_SH = orig
            os.environ.pop("ARGC_OUT", None)
        with open(argc_out) as f:
            self.assertEqual(f.read().strip(), "4")   # --client X --changeset Y


class TestCli(Base):
    def test_once_returns_zero_on_an_empty_spool(self):
        self.assertEqual(B.main(["--once", "--spool", self.spool,
                                 "--projects", self.registry]), 0)

    def test_watch_and_once_are_mutually_exclusive(self):
        self.assertNotEqual(B.main(["--once", "--watch", "--spool", self.spool,
                                    "--projects", self.registry]), 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py -k "RealSubprocess or Cli"`
Expected: FAIL — `AttributeError: module 'hermes_broker' has no attribute 'main'`.

- [ ] **Step 3: Add the CLI and the watch loop**

Append to `infra/hermes-agent/bin/hermes-broker.py`:

```python
def watch(spool, projects, interval):
    """Poll the spool forever. Deliberately a poll rather than inotify: one dependency
    fewer, portable to macOS for local testing, and a few seconds of latency on a path
    whose slowest step is a human approval is not worth a platform-specific watcher.

    A single exception must never kill the broker — a dead broker is a silently
    unprocessed queue, which looks exactly like an idle one.
    """
    while True:
        try:
            drain(spool=spool, projects=projects)
        except Exception as e:                       # noqa: BLE001 — see docstring
            print("broker: drain failed: %s" % e, file=sys.stderr)
        time.sleep(interval)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hermes-broker",
        description="Drain the mutation request spool. Host-side; holds the write "
                    "credential's directory but never its value.")
    ap.add_argument("--once", action="store_true", help="one drain pass, then exit")
    ap.add_argument("--watch", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--spool")
    ap.add_argument("--projects")
    args = ap.parse_args(argv)

    if args.once == args.watch:
        print("hermes-broker: pass exactly one of --once or --watch", file=sys.stderr)
        return 1

    spool = args.spool or S.spool_root()
    projects = args.projects or C.registry_projects_path()
    if args.watch:
        watch(spool, projects, args.interval)
        return 0
    for outcome in drain(spool=spool, projects=projects):
        print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Add `json` to the module's import line: `import argparse, collections, datetime, errno, fcntl, json, os, subprocess, sys, time`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py`
Expected: `OK`, `Ran 28 tests`.

- [ ] **Step 5: Run both full suites and confirm the counts**

Run:
```bash
cd /Users/ericksicard/Projects/claude_code
node scripts/run-all-tests.js
infra/hermes-agent/bin/run-bin-tests.sh
```
Expected: `21/21` node; `hermes bin: 23/23 suites passed` — **23** suites (20 baseline + `spool_lib` + `hermes-syscall` + `hermes-broker`). If it says 22, one new suite is not being discovered; find it before continuing.

- [ ] **Step 6: Mutation proof**

| Edit | Test that must turn RED |
|---|---|
| In `main`, `if args.once == args.watch:` → `if False:` | `test_watch_and_once_are_mutually_exclusive` |
| In `_execute`, `argv = [MUTATE_SH, "--client", slug, "--changeset", cid]` → append `"--undo"` | `test_the_wrapper_is_invoked_with_exactly_four_argv_elements` and `test_the_runner_receives_an_argv_list_of_validated_identifiers_only` |

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/hermes-broker.py infra/hermes-agent/bin/hermes-broker.test.py
git commit -m "feat(hermes): broker CLI with --once and --watch, verified against a real subprocess"
```

---

### Task 8: parked residuals (a), (b), (c) — the host-side writer, now that the broker owns the store

Ledger ruling **R20**. All three live in `persist_run_record_shim.py`, the host-side step that writes into `data/vaults` — the one tree Hermes can write. They were parked as unreachable. **Plan 2 makes (a) reachable**: the broker runs `run-ads-mutate.sh`, which runs this persist step, as the user that owns the governance store. This is the same seam that produced Plan 1's CRITICAL — a host-side writer meeting a host-owned store — so it is closed before the live gate, not after.

**Files:**
- Modify: `infra/hermes-agent/bin/persist_run_record_shim.py`
- Modify: `infra/hermes-agent/bin/persist-run-record.test.py`

**Interfaces:**
- Produces: `_open_regular(path, flags, dir_fd=None)` gains a `dir_fd` parameter; `_resolve_vault` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

Append to `infra/hermes-agent/bin/persist-run-record.test.py`, above the trailing `unittest.main()`:

```python
class TestParkedResiduals(unittest.TestCase):
    """R20 (a) hardlinks, (b) directory-component TOCTOU, (c) makedirs before check."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "pilot-1")
        os.makedirs(os.path.join(self.vault, "changes"), exist_ok=True)
        self.result = {"changeset_id": "20260824-101500-abcdef01",
                       "status": "applied", "applied": 1,
                       "finished_at": "2026-08-24T10:15:00Z"}

    def test_control_a_normal_persist_still_works(self):
        # The must-SUCCEED control. Three refusals are about to be added; if any of
        # them over-reaches, this is the test that catches it.
        p = PR.persist(self.vault, self.result, root=self.root)
        self.assertTrue(os.path.isfile(p))

    # --- (a) hardlinks -------------------------------------------------------------
    def test_a_hardlinked_timeline_is_refused(self):
        # O_NOFOLLOW does not see a hardlink and S_ISREG accepts one, so both existing
        # barriers pass it. With the broker running this step as the governance store's
        # OWNER, a hardlink from the vault to a store file is a write primitive.
        outside = os.path.join(self.root, "outside.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        os.link(outside, os.path.join(self.vault, "timeline.md"))
        with self.assertRaises(PR.PersistRefused) as cm:
            PR.persist(self.vault, self.result, root=self.root)
        self.assertIn("hard link", str(cm.exception).lower())
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")   # untouched

    def test_a_hardlinked_result_file_is_refused(self):
        outside = os.path.join(self.root, "outside2.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        dest = os.path.join(self.vault, "changes",
                            "20260824-101500-abcdef01.result.json")
        os.link(outside, dest)
        with self.assertRaises(PR.PersistRefused):
            PR.persist(self.vault, self.result, root=self.root)
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")

    def test_control_a_single_linked_file_is_accepted(self):
        # Proves the nlink check refuses hardlinks specifically and not ordinary
        # pre-existing files.
        with open(os.path.join(self.vault, "timeline.md"), "w") as f:
            f.write("- earlier\n")
        self.assertTrue(os.path.isfile(PR.persist(self.vault, self.result,
                                                  root=self.root)))

    # --- (b) directory-component TOCTOU --------------------------------------------
    def test_the_changes_directory_is_opened_by_descriptor_not_by_path(self):
        # The structural fix for the TOCTOU: after the containment check, every open
        # must be relative to an already-open directory fd, so swapping the directory
        # by path afterwards cannot redirect the write.
        import inspect
        src = inspect.getsource(PR)
        self.assertIn("dir_fd", src)
        self.assertIn("O_DIRECTORY", src)

    def test_a_symlinked_changes_directory_is_still_refused(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere, exist_ok=True)
        changes = os.path.join(self.vault, "changes")
        os.rmdir(changes)
        os.symlink(elsewhere, changes)
        with self.assertRaises(PR.PersistRefused):
            PR.persist(self.vault, self.result, root=self.root)

    # --- (c) makedirs before the containment check ---------------------------------
    def test_an_out_of_root_vault_is_refused_without_being_created(self):
        outside = os.path.join(tempfile.mkdtemp(), "not-in-the-root")
        with self.assertRaises(PR.PersistRefused):
            PR.persist(outside, self.result, root=self.root)
        # The mkdir belongs BELOW the check: refusing after creating the directory
        # leaves an attacker-chosen path on disk.
        self.assertFalse(os.path.exists(outside))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra/hermes-agent && python3 bin/persist-run-record.test.py -k ParkedResiduals`
Expected: FAIL — the hardlink tests pass the current barriers and persist succeeds; the out-of-root test finds the directory created.

- [ ] **Step 3: Fix (c) — move `makedirs` below the containment check**

In `persist_run_record_shim.py`, replace the body of `_resolve_vault` with:

```python
def _resolve_vault(vault, root=None):
    """Resolve the client vault and prove it lies under the configured vault root.

    Refuses a symlinked vault outright even when it resolves back inside the root.

    R20(c): the containment check now precedes the mkdir. Creating the directory first
    and refusing afterwards leaves an attacker-chosen path on disk — a refusal that
    still performed the side effect it was refusing.
    """
    root_real = os.path.realpath(root or vault_lib.vault_root())
    if os.path.islink(vault):
        raise PersistRefused("vault path is a symlink, refusing: %s" % vault)
    # Prove containment of the path we are ABOUT to create, using the resolved parent.
    candidate = os.path.join(os.path.realpath(os.path.dirname(vault)),
                             os.path.basename(vault))
    if not _contained(candidate, root_real):
        raise PersistRefused(
            "vault %s resolves to %s, which is outside the vault root %s — refusing"
            % (vault, candidate, root_real))
    if not os.path.exists(vault):
        os.makedirs(vault, exist_ok=True)
    if not os.path.isdir(vault):
        raise PersistRefused("vault path is not a directory, refusing: %s" % vault)
    vault_real = os.path.realpath(vault)
    # Re-check after creation: the pre-check proved the intent, this proves the result.
    if not _contained(vault_real, root_real):
        raise PersistRefused(
            "vault %s resolves to %s, which is outside the vault root %s — refusing"
            % (vault, vault_real, root_real))
    return vault_real
```

- [ ] **Step 4: Fix (a) and (b) — nlink check plus an openat dirfd chain**

Replace `_open_regular` and add `_open_dir`:

```python
def _open_dir(name, dir_fd=None):
    """Open a directory component with O_NOFOLLOW, relative to an already-open
    directory when one is supplied.

    R20(b): resolving a path with realpath and then opening it by path leaves a window
    in which any DIRECTORY component can be swapped. Opening each component relative to
    the previous component's descriptor removes the window structurally — there is no
    second path resolution to race.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags) if dir_fd is None else os.open(name, flags, dir_fd=dir_fd)
    except OSError as e:
        raise PersistRefused("%s cannot be opened as a directory (%s)" % (name, e))


def _open_regular(path, flags, dir_fd=None):
    """os.open with O_NOFOLLOW plus regular-file AND single-link assertions on the fd.

    O_NOFOLLOW refuses a symlink at the final component and the fstat refuses a
    directory, fifo, device or socket in that position — but NEITHER sees a HARD LINK
    (R20(a)). A hardlink planted in the vault, pointing at a file in the governance
    store, passes both and turns this step into a write primitive against the store the
    broker owns. st_nlink > 1 is the check that closes it.

    Everything is asserted on the FD, never the path, so nothing can be swapped between
    the test and the write.
    """
    fd = (os.open(path, flags | os.O_NOFOLLOW, 0o600) if dir_fd is None
          else os.open(path, flags | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PersistRefused("%s is not a regular file, refusing" % path)
        if st.st_nlink > 1:
            raise PersistRefused(
                "%s has %d hard links, refusing: a hard link to a file outside the "
                "vault passes both O_NOFOLLOW and the regular-file test, and this step "
                "runs as the owner of the governance store" % (path, st.st_nlink))
    except BaseException:
        os.close(fd)
        raise
    return fd
```

Then rewrite `persist` to route every open through the dirfd chain:

```python
def persist(vault, result, root=None):
    """Write <vault>/changes/<cid>.result.json and append <vault>/timeline.md.

    Every destination is proven to lie inside the vault, then opened RELATIVE TO an
    already-open directory descriptor, with O_NOFOLLOW, a regular-file assertion and a
    single-link assertion. Anything unprovable raises PersistRefused (a ValueError)
    rather than being skipped.
    """
    vault_real = _resolve_vault(vault, root)
    changes_name = os.path.basename(C.changes_dir(vault_real))
    _resolve_subdir(vault_real, changes_name, vault_real)

    vfd = _open_dir(vault_real)
    try:
        cfd = _open_dir(changes_name, dir_fd=vfd)
        try:
            base = os.path.basename(C.result_path(vault_real, result["changeset_id"]))
            tmp_base = base + ".tmp"
            path = os.path.join(vault_real, changes_name, base)
            _check_dest(path, vault_real)
            _check_dest(path + ".tmp", vault_real)

            fd = _open_regular(tmp_base, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, dir_fd=cfd)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            # os.RENAME, not os.replace: os.replace is NOT in os.supports_dir_fd on
            # darwin (measured 2026-08-24), while os.rename IS. On POSIX the two are
            # the same call — rename(2) already overwrites atomically; replace only
            # differs on Windows, which this tier does not target.
            os.rename(tmp_base, base, src_dir_fd=cfd, dst_dir_fd=cfd)
        finally:
            os.close(cfd)

        timeline = os.path.join(vault_real, "timeline.md")
        _check_dest(timeline, vault_real)
        fd = _open_regular("timeline.md", os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                           dir_fd=vfd)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                    % (result.get("finished_at", ""), result["changeset_id"],
                       result.get("status", "?"), result.get("applied", "?")))
    finally:
        os.close(vfd)
    return path
```

> **Platform note, measured not assumed (2026-08-24, darwin):** `os.open`, `os.rename`, `os.unlink` and `os.mkdir` are all in `os.supports_dir_fd`, but **`os.replace` is NOT** — so the atomic swap uses `os.rename` with `src_dir_fd`/`dst_dir_fd`. On POSIX that is the same `rename(2)` and overwrites atomically; `os.replace` differs only on Windows. Add an explicit guard at import time so an unsupported platform refuses loudly rather than silently falling back to path-based opens:
> ```python
> if os.open not in os.supports_dir_fd or os.rename not in os.supports_dir_fd:
>     raise RuntimeError("persist_run_record_shim requires openat/renameat support "
>                        "(os.supports_dir_fd); refusing to fall back to path-based "
>                        "opens, which reintroduces the directory-component TOCTOU")
> ```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd infra/hermes-agent && python3 bin/persist-run-record.test.py`
Expected: `OK`, `Ran 25 tests` (18 + 7).

- [ ] **Step 6: Mutation proof**

| Edit `persist_run_record_shim.py` | Test that must turn RED |
|---|---|
| Delete the `st.st_nlink > 1` check | `test_a_hardlinked_timeline_is_refused` |
| Move `os.makedirs(vault, ...)` back above the `candidate` containment check | `test_an_out_of_root_vault_is_refused_without_being_created` |
| Replace the `dir_fd=cfd` opens with path-based `os.open(path, ...)` | `test_the_changes_directory_is_opened_by_descriptor_not_by_path` |
| Delete the `_resolve_subdir` symlink check | `test_a_symlinked_changes_directory_is_still_refused` |

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/persist_run_record_shim.py infra/hermes-agent/bin/persist-run-record.test.py
git commit -m "fix(hermes): close R20 residuals — hardlinks, directory TOCTOU, and mkdir-before-check"
```

---

### Task 9: parked residual (d) — bind the review→approve window

Spec §7, corrected: the snapshot closes **approve → apply** structurally but **not** review → approve, and `--expect-sha256` was opt-in, so the residual window stayed procedural. Make the binding the default path.

**Files:**
- Modify: `infra/hermes-agent/bin/approve-changeset.py`
- Modify: `infra/hermes-agent/bin/approve-changeset.test.py`

> **What this does and does not buy, stated honestly.** It converts a reading task into a mechanical confirmation: the operator must transcribe a digest that names the exact bytes. It does **not** make the window structurally closed — an operator who pastes the digest without reading the summary has confirmed nothing. The real reason the window is empty in v1 remains §17.1: no model authors a change-set at all. This task removes the *silent* default, not the human.

- [ ] **Step 1: Write the failing test**

Append to `infra/hermes-agent/bin/approve-changeset.test.py`, above the trailing `unittest.main()`:

```python
class TestExpectShaIsRequired(unittest.TestCase):
    def test_approving_without_expect_sha256_refuses_and_prints_the_digest(self):
        rc, out, err = self._run_cli(["--client", self.SLUG, "--changeset", self.CID,
                                      "--operator", "operator"])
        self.assertEqual(rc, 2)
        text = out + err
        self.assertIn("--expect-sha256", text)
        self.assertIn(self.expected_digest, text)      # paste-ready
        self.assertIn("action(s)", text)               # and the summary to read

    def test_no_approval_record_is_written_by_the_refusing_call(self):
        self._run_cli(["--client", self.SLUG, "--changeset", self.CID,
                       "--operator", "operator"])
        self.assertFalse(os.path.isfile(governance_lib.approval_path(self.SLUG, self.CID)))

    def test_control_supplying_the_digest_approves(self):
        # The must-SUCCEED control: the new refusal must not have broken approval.
        rc, _, _ = self._run_cli(["--client", self.SLUG, "--changeset", self.CID,
                                  "--operator", "operator",
                                  "--expect-sha256", self.expected_digest])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(governance_lib.approval_path(self.SLUG, self.CID)))

    def test_a_wrong_digest_still_refuses(self):
        rc, _, err = self._run_cli(["--client", self.SLUG, "--changeset", self.CID,
                                    "--operator", "operator",
                                    "--expect-sha256", "b" * 64])
        self.assertEqual(rc, 2)
        self.assertIn("mismatch", err)
```

> Reuse whatever fixture helper `approve-changeset.test.py` already has for building a client + change-set and running the CLI; name it `_run_cli` / `expected_digest` only if those names already exist there, otherwise adopt the file's existing convention rather than adding a second one.

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/approve-changeset.test.py -k ExpectSha`
Expected: FAIL — approval currently succeeds with no `--expect-sha256`.

- [ ] **Step 3: Implement**

In `approve-changeset.py`, change `approve()` so that a `None` `expect_sha256` becomes a refusal that first prints what the operator needs. Replace the `if expect_sha256 is not None:` block with:

```python
    import hashlib
    actual = hashlib.sha256(data).hexdigest()
    if expect_sha256 is None:
        # The review -> approve window is not closed by the snapshot (spec §7). Making
        # --expect-sha256 the DEFAULT path turns the operator's confirmation into a
        # refusal rather than a reading task. It does not remove the human: an operator
        # who pastes without reading has confirmed nothing. What it removes is the
        # silent default, where the command bound whatever happened to be on disk.
        raise ExpectShaRequired(actual, cs["actions"], changeset_id)
    if not C.SHA256_RE.fullmatch(expect_sha256.strip().lower()):
        raise ValueError(f"invalid --expect-sha256: {expect_sha256!r}")
    if actual != expect_sha256.strip().lower():
        raise ValueError(
            f"--expect-sha256 mismatch: the change-set on disk hashes to {actual}, "
            f"not {expect_sha256.strip().lower()} — these are not the bytes you "
            "reviewed; re-read it before approving")
```

Add near the top of the file:

```python
class ExpectShaRequired(Exception):
    """Not an error in the change-set — the operator has not yet confirmed the bytes.

    Carries everything needed to print a paste-ready next command, so the refusal is a
    step in the workflow rather than an obstacle to route around. A refusal an operator
    learns to bypass is worse than no refusal.
    """

    def __init__(self, digest, actions, changeset_id):
        super().__init__("confirmation required")
        self.digest, self.actions, self.changeset_id = digest, actions, changeset_id
```

And in `main`, handle it **before** the generic handler:

```python
    except ExpectShaRequired as e:
        print("change-set %s binds these %d action(s):" % (e.changeset_id, len(e.actions)))
        for i, a in enumerate(e.actions, 1):
            print("    %d. %s  campaign %s  %s  %r"
                  % (i, a["type"], a["campaign_id"], a["match_type"], a["keyword"]))
        print("\n  sha256 %s" % e.digest)
        print("\nRead the actions above. If they are what you reviewed, re-run with:\n"
              "  --expect-sha256 %s" % e.digest, file=sys.stderr)
        return 2
```

- [ ] **Step 4: Run the tests**

Run: `cd infra/hermes-agent && python3 bin/approve-changeset.test.py`
Expected: `OK`, `Ran 25 tests` (21 + 4).

- [ ] **Step 5: Mutation proof**

| Edit | Test that must turn RED |
|---|---|
| `if expect_sha256 is None: raise ...` → `if False:` | `test_approving_without_expect_sha256_refuses_and_prints_the_digest` |
| Move `write_snapshot_bytes` / `write_approval` above the `ExpectShaRequired` raise | `test_no_approval_record_is_written_by_the_refusing_call` |

- [ ] **Step 6: Update every caller and doc that shows the old two-argument form**

Run: `grep -rn "approve" --include='*.md' --include='*.sh' infra/hermes-agent/ docs/ | grep -v '\.test\.'`

> Search for `approve`, **not** `approve-changeset` — the wrapper is invoked as
> `./changeset.sh approve ...`, which the narrower pattern misses. Verified 2026-08-24: the
> narrow pattern returns only two prose mentions and **zero** call sites, which would have read
> as "nothing to update".

Expected hits to fix: `changeset.sh:5` (the header example, currently omits the flag) and
`changeset.sh:26` (the usage line, currently shows it as optional `[--expect-sha256 <hex>]` —
it is now required). Re-run `./changeset.sh approve` with no flag and confirm the usage text
and the refusal agree. **A documented sequence that now refuses is a documentation bug**, and Plan 1 shipped exactly that class of defect once already.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/approve-changeset.py infra/hermes-agent/bin/approve-changeset.test.py \
        infra/hermes-agent/changeset.sh
git commit -m "fix(hermes): require --expect-sha256 so approval binds the reviewed bytes by default"
```

---

# PHASE B — the socket proxy and the VPS posture

> **Gate:** Phase A is complete and testable on its own, and is acceptable on a single-user development machine where the broker talks to the Docker socket directly. **Phase B must land before any VPS deploy**, because on a VPS the broker's Docker access is equivalent to host root. Do not describe Phase A as "deployed" without Phase B.

---

### Task 10: `docker-create-proxy.py` — a body-inspecting Docker API allow-list

Spec §6.4 asks for a proxy restricted to `create`/`start` on one image. **Deviation D1 applies**: `docker compose run` needs more of the Engine API than two endpoints, and the "one image" constraint lives in the JSON *body* of `POST /containers/create`, which an endpoint-level ACL cannot see. So the allow-list is derived by measurement and the create call is pinned by body inspection.

**Files:**
- Create: `infra/hermes-agent/bin/docker-create-proxy.py`
- Create: `infra/hermes-agent/bin/docker-create-proxy.test.py`

**Interfaces:**
- Produces, for Task 11: CLI `docker-create-proxy.py --listen PATH --upstream /var/run/docker.sock --image IMAGE`; and the pure decision function `decide(method, path, body) -> (bool, str)`.

- [ ] **Step 1: MEASURE the endpoint set — do not guess it**

Write a temporary logging pass-through (allow everything, print `METHOD PATH`), point Compose at it, and run one real invocation.

```bash
cd infra/hermes-agent
python3 bin/docker-create-proxy.py --listen /tmp/dsock.sock \
    --upstream /var/run/docker.sock --image hermes-agent-claude --log-only \
    > /tmp/docker-endpoints.txt 2>&1 &
PROXY=$!
DOCKER_HOST=unix:///tmp/dsock.sock docker compose -f docker-compose.yml \
    run --rm --no-deps -T ads-mutator --help >/dev/null 2>&1 || true
kill $PROXY
sort -u /tmp/docker-endpoints.txt
```

Expected: a short list — version/ping negotiation, an image inspect, container create/start/attach/wait/delete, and possibly a network inspect. **Record the exact list in the file's docstring** as the measured basis for the allow-list, with the date. Do not add an endpoint the measurement did not show; if a later Compose version needs more, that is a deliberate re-measurement, not a guess.

> The `--log-only` mode exists only for this step and must be removed, or made refuse-by-default, before Task 11 installs the unit. A proxy with a bypass flag is not a proxy.

- [ ] **Step 2: Write the failing test**

Create `infra/hermes-agent/bin/docker-create-proxy.test.py`:

```python
import importlib.util, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load("docker_create_proxy", "docker-create-proxy.py")
IMAGE = "hermes-agent-claude"


def body(**over):
    b = {"Image": IMAGE, "Cmd": ["--client", "pilot-1"],
         "HostConfig": {"AutoRemove": True, "Binds": []}}
    b.update(over)
    return json.dumps(b).encode()


class TestAllowed(unittest.TestCase):
    def setUp(self):
        P.PINNED_IMAGE = IMAGE

    def test_control_a_normal_create_is_allowed(self):
        # THE POSITIVE CONTROL. Every refusal below is meaningless unless the proxy
        # lets the legitimate call through — a proxy that denies everything "passes"
        # every negative test and breaks the rail.
        ok, why = P.decide("POST", "/v1.45/containers/create?name=x", body())
        self.assertTrue(ok, why)

    def test_control_container_start_is_allowed(self):
        ok, _ = P.decide("POST", "/v1.45/containers/abc123/start", b"")
        self.assertTrue(ok)

    def test_control_version_negotiation_is_allowed(self):
        self.assertTrue(P.decide("GET", "/_ping", b"")[0])
        self.assertTrue(P.decide("GET", "/v1.45/version", b"")[0])


class TestDenied(unittest.TestCase):
    def setUp(self):
        P.PINNED_IMAGE = IMAGE

    def test_a_different_image_is_refused(self):
        ok, why = P.decide("POST", "/v1.45/containers/create", body(Image="alpine"))
        self.assertFalse(ok)
        self.assertIn("image", why.lower())

    def test_privileged_is_refused(self):
        ok, _ = P.decide("POST", "/v1.45/containers/create",
                         body(HostConfig={"Privileged": True}))
        self.assertFalse(ok)

    def test_host_pid_namespace_is_refused(self):
        ok, _ = P.decide("POST", "/v1.45/containers/create",
                         body(HostConfig={"PidMode": "host"}))
        self.assertFalse(ok)

    def test_binding_the_docker_socket_back_in_is_refused(self):
        ok, _ = P.decide("POST", "/v1.45/containers/create",
                         body(HostConfig={"Binds": ["/var/run/docker.sock:/var/run/docker.sock"]}))
        self.assertFalse(ok)

    def test_added_capabilities_are_refused(self):
        ok, _ = P.decide("POST", "/v1.45/containers/create",
                         body(HostConfig={"CapAdd": ["SYS_ADMIN"]}))
        self.assertFalse(ok)

    def test_exec_is_refused(self):
        # exec into a running container is a shell. The whole point of the one-shot
        # executor is that Hermes has no shell in it.
        self.assertFalse(P.decide("POST", "/v1.45/containers/abc/exec", b"")[0])

    def test_image_build_and_pull_are_refused(self):
        self.assertFalse(P.decide("POST", "/v1.45/build", b"")[0])
        self.assertFalse(P.decide("POST", "/v1.45/images/create?fromImage=alpine", b"")[0])

    def test_unlisted_endpoints_are_refused_by_default(self):
        for method, path in (("GET", "/v1.45/containers/json"),
                             ("POST", "/v1.45/volumes/create"),
                             ("GET", "/v1.45/secrets"),
                             ("POST", "/v1.45/swarm/init"),
                             ("DELETE", "/v1.45/images/hermes-agent-claude")):
            self.assertFalse(P.decide(method, path, b"")[0], "%s %s" % (method, path))

    def test_malformed_create_body_is_refused_not_forwarded(self):
        self.assertFalse(P.decide("POST", "/v1.45/containers/create", b"{not json")[0])

    def test_path_traversal_in_the_url_does_not_reach_an_allowed_pattern(self):
        self.assertFalse(
            P.decide("POST", "/v1.45/containers/create/../../../build", b"")[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd infra/hermes-agent && python3 bin/docker-create-proxy.test.py`
Expected: FAIL — file not found.

- [ ] **Step 4: Implement the decision function and the socket plumbing**

Create `infra/hermes-agent/bin/docker-create-proxy.py`. The security-critical half:

```python
#!/usr/bin/env python3
"""A body-inspecting Docker Engine API allow-list for the mutation broker. Stdlib-only.

WHY OUR OWN, rather than an off-the-shelf socket proxy: the constraint that matters is
"create ONLY this image", and the image name lives in the JSON BODY of
POST /containers/create. A proxy that filters by method and path cannot see it, so it
would satisfy the letter of spec §6.4 and none of its intent. This file is also small
enough to audit in one sitting, which is the right property for the one component whose
compromise is worst.

THE ALLOW-LIST BELOW WAS MEASURED, NOT GUESSED (spec deviation D1). `docker compose run
--rm --no-deps` needs more than create+start: it negotiates a version, inspects the
image, creates, attaches, starts, waits, and deletes. The exact set was captured on
<DATE> by running one real invocation through this proxy in --log-only mode; that list
is reproduced here. Adding an endpoint is a re-measurement, never a guess.

    <PASTE THE MEASURED `sort -u` OUTPUT FROM STEP 1 HERE>

DENY BY DEFAULT. Anything not matched below is refused.
"""
import argparse, json, os, re, socket, socketserver, sys, threading

PINNED_IMAGE = None          # set from --image at startup

_V = r"(?:/v[0-9]+\.[0-9]+)?"          # optional API version prefix
_ID = r"[A-Za-z0-9_.-]+"

# (method, compiled path pattern). Fullmatch only — a prefix match would let
# /containers/create/../../build through.
ALLOWED = [
    ("GET",    re.compile(r"/_ping")),
    ("HEAD",   re.compile(r"/_ping")),
    ("GET",    re.compile(_V + r"/version")),
    ("GET",    re.compile(_V + r"/images/" + _ID + r"/json")),
    ("POST",   re.compile(_V + r"/containers/create")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/start")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/attach")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/wait")),
    ("GET",    re.compile(_V + r"/containers/" + _ID + r"/json")),
    ("DELETE", re.compile(_V + r"/containers/" + _ID)),
]

# HostConfig keys that hand back what the proxy exists to withhold.
FORBIDDEN_HOSTCONFIG = (
    "Privileged", "CapAdd", "Devices", "DeviceCgroupRules", "SecurityOpt",
    "Sysctls", "UsernsMode", "CgroupParent", "Runtime", "PidMode", "IpcMode",
    "UTSMode", "CgroupnsMode", "Init", "Mounts",
)


def _path_only(path):
    """Strip the query string and reject any traversal before matching."""
    p = path.split("?", 1)[0]
    if ".." in p or "//" in p:
        return None
    return p


def decide(method, path, body):
    """Pure allow/deny. Returns (allowed, reason). No I/O — this is the whole policy,
    and it is a function so it can be tested exhaustively without a socket."""
    p = _path_only(path)
    if p is None:
        return False, "path %r contains a traversal component" % path
    if not any(m == method and pat.fullmatch(p) for m, pat in ALLOWED):
        return False, "%s %s is not on the allow-list" % (method, p)

    if method == "POST" and re.fullmatch(_V + r"/containers/create", p):
        try:
            spec = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return False, "unparseable create body: %s" % e
        if not isinstance(spec, dict):
            return False, "create body is not an object"
        if spec.get("Image") != PINNED_IMAGE:
            return False, ("create refused: image %r is not the pinned image %r"
                           % (spec.get("Image"), PINNED_IMAGE))
        hc = spec.get("HostConfig") or {}
        if not isinstance(hc, dict):
            return False, "HostConfig is not an object"
        for k in FORBIDDEN_HOSTCONFIG:
            if hc.get(k):
                return False, "create refused: HostConfig.%s is not permitted" % k
        for mode_key in ("NetworkMode", "PidMode", "IpcMode"):
            if str(hc.get(mode_key, "")).startswith("host"):
                return False, "create refused: HostConfig.%s=host" % mode_key
        for bind in hc.get("Binds") or []:
            src = str(bind).split(":", 1)[0]
            if src.rstrip("/").endswith("docker.sock") or src in ("/", "/etc", "/root"):
                return False, "create refused: bind %r is not permitted" % bind
    return True, "allowed"
```

The plumbing half — a `socketserver.ThreadingUnixStreamServer` that reads the request line and headers, reads exactly `Content-Length` bytes of body, calls `decide`, and either splices to the upstream socket or returns `403 Forbidden` with a JSON `{"message": reason}` body. Requirements:

- Refuse a request with no `Content-Length` on `POST /containers/create` — a chunked body cannot be inspected before forwarding, and forwarding an uninspected create is the one thing this file exists to prevent.
- Cap the buffered body at 1 MiB; refuse above it.
- Log every decision (allow and deny) with method, path, and reason to stderr.
- The listening socket is created with mode `0600` and owned by the broker's user.

- [ ] **Step 5: Run the tests**

Run: `cd infra/hermes-agent && python3 bin/docker-create-proxy.test.py`
Expected: `OK`, `Ran 15 tests`.

- [ ] **Step 6: End-to-end proof, with both a refusal and a success**

```bash
cd infra/hermes-agent
python3 bin/docker-create-proxy.py --listen /tmp/dsock.sock \
    --upstream /var/run/docker.sock --image hermes-agent-claude &
PROXY=$!
# MUST FAIL: a different image
DOCKER_HOST=unix:///tmp/dsock.sock docker run --rm alpine true; echo "alpine rc=$?"
# MUST SUCCEED: the pinned image through the real wrapper
DOCKER_HOST=unix:///tmp/dsock.sock ./run-ads-mutate.sh --client <slug-1> \
    --changeset <id> --dry-run; echo "wrapper rc=$?"
kill $PROXY
```
Expected: the `alpine` run fails with a 403 from the proxy; the wrapper reaches `apply-changeset.py` and refuses at guard 1 (kill switch absent) with exit 2 — **not** a proxy error. A pipeline takes its status from the last command, so read each `rc=` line rather than piping either command into anything.

- [ ] **Step 7: Mutation proof**

| Edit | Test that must turn RED |
|---|---|
| `spec.get("Image") != PINNED_IMAGE` → `if False:` | `test_a_different_image_is_refused` |
| `pat.fullmatch(p)` → `pat.match(p)` | `test_path_traversal_in_the_url_does_not_reach_an_allowed_pattern` |
| Delete the `FORBIDDEN_HOSTCONFIG` loop | `test_privileged_is_refused`, `test_added_capabilities_are_refused` |
| Add `("POST", re.compile(_V + r"/containers/" + _ID + r"/exec"))` to `ALLOWED` | `test_exec_is_refused` |

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/docker-create-proxy.py infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "feat(hermes): body-inspecting Docker socket proxy pinned to the executor image"
```

---

### Task 11: systemd units and the VPS deploy sequence

**Files:**
- Create: `infra/hermes-agent/deploy/hermes-docker-proxy.service`
- Create: `infra/hermes-agent/deploy/hermes-broker.service`
- Modify: `infra/hermes-agent/README.md`

- [ ] **Step 1: Write the proxy unit**

`infra/hermes-agent/deploy/hermes-docker-proxy.service`:

```ini
[Unit]
Description=Hermes Docker API allow-list proxy (pins container creation to one image)
After=docker.service
Requires=docker.service

[Service]
Type=simple
# This unit is the ONLY component in the group that touches the real Docker socket.
# It runs as a user in the docker group; the broker deliberately is not.
User=hermes-docker-proxy
SupplementaryGroups=docker
RuntimeDirectory=hermes
RuntimeDirectoryMode=0750
ExecStart=/opt/hermes-agent/bin/docker-create-proxy.py \
    --listen /run/hermes/docker-proxy.sock \
    --upstream /var/run/docker.sock \
    --image hermes-agent-claude
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX
MemoryMax=128M

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write the broker unit**

`infra/hermes-agent/deploy/hermes-broker.service`:

```ini
[Unit]
Description=Hermes mutation request broker (drains the spool, invokes the governed rail)
After=hermes-docker-proxy.service
Requires=hermes-docker-proxy.service

[Service]
Type=simple
# Its own user. .env.gaw and the governance store are readable ONLY by this user, so
# even the deploy user's shell cannot read the write credential — an isolation the
# local machine cannot practically provide (spec §16.2).
User=hermes-broker
Group=hermes-broker
WorkingDirectory=/opt/hermes-agent
# NOT in the docker group. Docker access is exclusively through the proxy socket.
Environment=DOCKER_HOST=unix:///run/hermes/docker-proxy.sock
Environment=HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance
Environment=HERMES_GOVERNANCE_ROOT=/var/lib/hermes/governance
Environment=HERMES_SPOOL_ROOT=/opt/hermes-agent/data/spool
ExecStartPre=/usr/bin/python3 /opt/hermes-agent/bin/preflight-governance-access.py \
    --root /var/lib/hermes/governance
ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-broker.py --watch --interval 5
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/hermes/governance /opt/hermes-agent/data/spool
RestrictAddressFamilies=AF_UNIX
MemoryMax=256M

[Install]
WantedBy=multi-user.target
```

> **`ExecStartPre` runs the pre-flight**, so a governance store the executor cannot read refuses at *boot* rather than mid-apply. **This is why Task 2 of the session brief — the pre-flight's file-level blind spot — must land before the first VPS apply.** Note it here and cross-reference it in the README; do not let it be discovered by an exit-3.

- [ ] **Step 3: Assert the units stay consistent with the code**

Append to `infra/hermes-agent/bin/hermes-broker.test.py`, above `unittest.main()`:

```python
class TestDeployUnits(unittest.TestCase):
    DEPLOY = os.path.join(os.path.dirname(HERE), "deploy")

    def _unit(self, name):
        with open(os.path.join(self.DEPLOY, name)) as f:
            return f.read()

    def test_the_broker_is_not_in_the_docker_group(self):
        # The entire point of the proxy. A broker in the docker group has host root and
        # the proxy is decoration.
        self.assertNotIn("docker", self._unit("hermes-broker.service").split("User=")[1]
                         .split("\n")[0])
        self.assertNotIn("SupplementaryGroups=docker", self._unit("hermes-broker.service"))

    def test_the_broker_talks_to_the_proxy_socket_not_the_real_one(self):
        u = self._unit("hermes-broker.service")
        self.assertIn("DOCKER_HOST=unix:///run/hermes/docker-proxy.sock", u)
        self.assertNotIn("unix:///var/run/docker.sock", u)

    def test_the_preflight_runs_before_the_broker_starts(self):
        self.assertIn("ExecStartPre", self._unit("hermes-broker.service"))
        self.assertIn("preflight-governance-access.py",
                      self._unit("hermes-broker.service"))

    def test_control_the_proxy_unit_DOES_have_docker_access(self):
        # The positive control for the two assertions above: something must reach the
        # socket, or nothing works and the tests above would pass trivially.
        self.assertIn("SupplementaryGroups=docker",
                      self._unit("hermes-docker-proxy.service"))
```

- [ ] **Step 4: Run and commit**

Run: `cd infra/hermes-agent && python3 bin/hermes-broker.test.py`
Expected: `OK`, `Ran 32 tests`.

```bash
git add infra/hermes-agent/deploy infra/hermes-agent/bin/hermes-broker.test.py
git commit -m "feat(hermes): systemd units — broker outside the docker group, proxy in front of the socket"
```

---

# PHASE C — review and the live gate

---

### Task 12: the cross-task security review (budgeted, not optional)

Plan 1's CRITICAL was invisible to **eleven per-task reviews** because it lived in a *seam*: a host-side writer (task 7) met a host-owned store (tasks 2/5) and followed symlinks. **Plan 2 has the same shape** — a broker writing into agent-adjacent space. This task exists because per-task review is structurally incapable of finding that class of defect.

This is a **review task with no code of its own**. Dispatch it to a reviewer who did not implement Tasks 1–11, and give them the seam list rather than the file list.

- [ ] **Step 1: Walk each seam explicitly and write a finding or an explicit "clean" for each**

| # | Seam | The question to answer with a probe, not an argument |
|---|---|---|
| S1 | Broker (T6) → `persist_run_record_shim` (T8) | The broker runs `run-ads-mutate.sh` as the governance store's owner, and that wrapper persists into `data/vaults`, which Hermes writes. Plant a hardlink, a symlink, and a fifo at `timeline.md` and at the `.tmp` result path, then run a real drain. Confirm the kill switch is **still absent** and the audit log's byte count is **unchanged** afterwards. |
| S2 | Spool (T1) → broker (T5) | Can Hermes make the broker read anything outside `requests/`? Try a symlink, a `..` in the filename, a hardlink to the audit log, a 1 GB file, a fifo, a file that grows during the read. |
| S3 | Seen-set (T4) → quotas (T3/T5) | Delete `governance/seen/<slug>.jsonl` from the host between drains. Does a used `request_id` become replayable? Does the daily quota reset? Both must be host-only surfaces, and Hermes must reach neither. |
| S4 | Reservation (T4) → executor guard 5 (Plan 1) | Kill the broker between `reserve_approval` and the subprocess (`kill -9` from a runner that sleeps). Confirm the approval is dead afterwards and the change-set cannot be applied without a fresh approval. |
| S5 | Proxy (T10) → wrapper (Plan 1) | With `DOCKER_HOST` pointed at the proxy, can any Compose invocation reach an endpoint or an image outside the allow-list? Try `docker run alpine`, `docker exec`, `docker build`, and a create with `Binds` including the socket. |
| S6 | `hermes-syscall` (T2) → broker (T5) | Do the client and the broker agree on the schema in *both* directions? Have the client write a request and the broker's validator read it; then hand-craft each field's boundary value. |
| S7 | Result file (T6) → Hermes | Does anything client-identifying reach the spool result — resource names, campaign ids, customer ids, credential fragments? Grep the result of a real dry-run apply for the digits of the resolved customer id and for the credential's sha12. **Pair with a control**: grep for a string you know IS present, so an empty grep is evidence. |
| S8 | Compose (Plan 1 masks) → spool | `data/` is mounted read-write and now contains the spool. Confirm the mask on `infra/hermes-agent` still holds and that no new path under `data/` exposes a credential or the governance store. Re-run the Plan-1 credential-readability probe: **5 → 0 readable, with a normal repo file readable as the control.** |

- [ ] **Step 2: Re-run the Plan-1 guarantee probes, not just the new ones**

Every Plan 1 guarantee was measured against the pre-Plan-2 tree. Prove each still holds:

```bash
cd infra/hermes-agent
./audit-credential-access.sh --all --customer <digits>   # exit 0 = both roles as declared
```
Then the in-container probe: every `.env.*` unreadable, **with a known-readable control file proving the probe works**, and the governance store unreachable **with a control path that is reachable**.

- [ ] **Step 3: Confirm the test totals**

Run:
```bash
cd /Users/ericksicard/Projects/claude_code
node scripts/run-all-tests.js
infra/hermes-agent/bin/run-bin-tests.sh
```
Expected: `21/21` node; `hermes bin: 24/24 suites passed`. Sum the per-suite `Ran N tests` and record the total in the ledger. It must be **materially above 302** — a suite count that rose while the test count did not is a suite that is not running.

- [ ] **Step 4: Record every finding in the SDD ledger before any fix**

Findings that are fixed, findings that are parked, and the reason for each. Plan 1's parked residuals only survived because they were written down.

---

### Task 13: the live verification gate (operator-run, dormant pilot only)

Spec §13. **Do not start this until Tasks 1–12 are merged.** Zero spend: the dormant pilot client only, resolved via `vault_lib.resolve('<slug>')`, never the live one, never a hardcoded id.

> **Precondition P1 is satisfied by Plan 1** (credential files masked: 5 → 0 readable). Re-verify it in step 2 rather than assuming it — the syscall's central claim is conditional on it, and a locked front door beside an open window is not a security property.

- [ ] **Step 1: Credential roles unchanged** — `./audit-credential-access.sh --all --customer <digits>` → exit 0, before and after the whole gate. Do not re-derive credential facts by hand; this tool measures them.
- [ ] **Step 2: P1 by probe** — from inside the gateway container, every credential file unreadable, **with a known-readable control file** proving the probe works.
- [ ] **Step 3: Governance store unreachable from the gateway container**, with a control path that *is* reachable. Add: the **spool** *is* reachable and writable (that is the design), and the **seen-set is not**.
- [ ] **Step 3b: F7 closed for the write path** — during a live apply, poll `/proc/*/environ` from the gateway container for the write credential's fingerprint and find nothing, **with the F7 marker probe re-run as a positive control** proving the polling technique still works. Compare by sha12 only; never print a credential value.
- [ ] **Step 4: Kill switch absent** → `hermes-syscall.py apply` → refusal at guard 1; the result file **exists**; `exit_code` 2; `hermes-syscall.py result` exits 2 and does not read as retryable.
- [ ] **Step 5: Kill switch enabled** → request naming an **unapproved** change-set → refused at the approval check, subprocess reached, guard 5 refuses, exit 2.
- [ ] **Step 6: Forged approval** written into the **old vault location** → **not honoured** (proves the executor reads the governance store, not the writable copy).
- [ ] **Step 7: Kill switch created from inside the container** at the old path → **no effect**.
- [ ] **Step 8: Replay** — re-file the same `request_id` → `refused_replay`. Then **delete the whole spool from inside the container** and re-file it → still `refused_replay`.
- [ ] **Step 9: Quotas** — file `max_pending_requests + 3` requests → the excess is `refused_quota` and **no subprocess ran for them** (check the broker's journal, not just the result files).
- [ ] **Step 10: Full happy path** on the dormant client via the syscall, then `run-ads-mutate.sh --undo` **host-side**, then confirm the account is byte-identical.
- [ ] **Step 11: Consumed approval** — re-request the same change-set → refused as consumed (`refused_approval`).
- [ ] **Step 12: Undo is unreachable** — confirm there is no syscall path to `--undo`: `python3 bin/hermes-syscall.py undo ...` exits non-zero, and a hand-written spool request with `"op": "undo"` is `refused_request`.
- [ ] **Step 13: Kill switch removed. Confirm absent.**

```bash
test -e ~/.hermes/governance/control/mutation-enabled && echo "STILL ENABLED — fix" || echo "absent (correct)"
```
Use a **file test**, not `ls | grep -c`: `ls` on a missing directory prints an error line that `grep -c` counts as a match, and `grep -c` prints `0` while exiting 1.

- [ ] **Step 14: Record the measured results in the ledger**, each with the control that made it meaningful.

---

### Task 14: documentation and the spec amendment

**Files:**
- Modify: `infra/hermes-agent/README.md`
- Modify: `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md`

- [ ] **Step 1: README** — add a "Mutation syscall" section covering: the spool layout; `hermes-syscall.py apply` / `result` and every exit code including **4 = pending, not refused**; the broker's `--once` / `--watch`; the two new quotas and where they live; the socket proxy and why the broker is not in the docker group; and the deploy sequence with the pre-flight cross-reference. State plainly that **`undo` is operator-only and unreachable from the syscall**.
- [ ] **Step 2: Correct any claim the implementation changed.** Specifically, §6.5's "the broker persists `result.json` and `timeline.md`" is false — `run-ads-mutate.sh` already does it. Grep the README and the spec for that claim and fix both. This capsule has now shipped three false guarantees of the form "verified about one surface, asserted about another"; do not add a fourth.
- [ ] **Step 3: Amend the spec with deviation D1** — record in §6.4 that the proxy's allow-list is wider than `create`/`start`, that the list was **measured** on the date it was measured, and that the pinning is by body inspection. Keep the original text and mark the correction, the way §7 was corrected — the way this design has been wrong is part of the record.
- [ ] **Step 4: Capture the decision in the brain**

```bash
node scripts/brain/brain-capture.js --type decision --message "Plan 2 shipped the governed mutation syscall: spool + hermes-syscall + host broker + body-inspecting Docker socket proxy. <fill in the measured results>"
```

- [ ] **Step 5: Open the PR** (`main` is protected in both repos)

```bash
git push -u origin feat/hermes-governed-syscall
gh pr create --base main --title "feat(hermes): the governed mutation syscall Hermes can call" --body "<summary + measured results + parked findings from Task 12>"
```

The PR body must carry **every parked finding from Task 12**. The Plan-1 ledger notes that its parked findings existed nowhere but the ledger until they reached the PR body — that is the only reason R19–R21 survived into this plan.

---

## Self-review

**Spec coverage.** §6.2 spool → T1. §6.3 `hermes-syscall` → T2. §6.4 broker → T5/T6/T7; socket proxy → T10. §6.5 executor → unchanged from Plan 1; the run-record split is corrected in T14 §2. §7 snapshot + reservation → T4 (reservation), T9 (review→approve). §8 closed schema → T1; seen-set → T4; hostile input → T1; quotas → T3/T5. §9 guards → unchanged, verified by T13 steps 4–7. §12 failure semantics → T6 (uncollapsed exit codes), T2 (pending ≠ refused). §13 verification gate → T13. §14 testing → the mutation proof in every task plus T12 step 3. §16 VPS → T11. §17.1/§17.2 → enforced by T1 (`OPS`) and T2 (no `undo` subcommand), tested in both. R19 → **not in this plan**; it is the session's Task 2 and must land before T13. R20(a)(b)(c) → T8. Residual (d) → T9.

**Known gaps, stated rather than hidden.**
- §16.4 (staging exercisable with a dummy `.env.gaw`, failing closed at guard 8) has **no task**. It is a VPS-time acceptance test and belongs with the first deploy, not here. Flagged so it is not silently dropped.
- §17.3's consequence — Hermes cannot see remaining cap headroom and discovers caps as refusals — is unchanged and untested, because there is nothing to test: it is the absence of a mount.
- The `_accepted_today` implementation counts seen-set lines by substring-matching the date. That is fragile if the record format changes. T5's tests cover the behaviour, not the parsing strategy; a reviewer should consider whether to parse the JSON per line instead. **Raised as a known weakness rather than left for discovery.**

**Type consistency.** `Decision` / `classify` / `drain` / `_process` / `_execute` / `_write_result` are used with the same signatures in T5, T6, T7. `spool_lib.write_result(request_id, payload, root)` matches every call site. `changeset_lib.reserve_approval(slug, cid, request_id, now)` and `record_outcome(slug, cid, outcome, now)` match T6's calls. `governance_lib.lock_path(slug, root=None)` matches `_ClientLock`. `_open_regular(path, flags, dir_fd=None)` in T8 is backward compatible with its existing two-argument call sites.

**Sequencing constraints.**
1. T1 → T2, T5. T3, T4 → T5, T6. T5 → T6 → T7.
2. **T8 must precede T13.** The broker running `persist` as the store's owner is what makes residual (a) reachable.
3. **The session's Task 2 (pre-flight file-level blind spot, R19) must precede T13** and any VPS apply — T11's `ExecStartPre` depends on that check being honest.
4. T12 after T11, before T13. T14 last.
