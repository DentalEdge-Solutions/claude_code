# The `ads-report` job, the job template and the review of every job (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second chat-triggered job, `ads-report` (the audit's three Google Ads reports, figures only, no AI model), make the chat-trigger machinery stop knowing the audit by name, and make the security review cover every job the box declares.

**Architecture:** A job's description file (`registry/apps/<app>.json`) gains two keys: where its results may live and the text of its chat tools. The shared result checker and the chat-side server read them instead of audit-only constants. `run-client-audit.py` gains a `--figures` mode whose steps are collect ×4, read ×3 and a new root-run `store` step that joins the three reports into one document in `/var/lib/hermes/report-archive/<client>/`, a store no container mounts. The review collector discovers the jobs from the description files and the installed units, and runs its per-job checks once per job.

**Tech Stack:** Python 3 standard library only; `unittest`; systemd template units (unchanged); Docker Compose (one mount line); the Hermes gateway's `mcp_servers` config.

**Spec:** `docs/superpowers/specs/2026-10-13-ads-report-job-design.md` (Parts 1, 2, 3; "Testing"; "Rollout and review #11").

## Global Constraints

- Standard library only in `infra/hermes-agent/bin/`.
- Run `infra/hermes-agent/bin/run-bin-tests.sh` after every change under `infra/hermes-agent/bin/`; it must report every suite passed before a commit.
- No client name, customer id, host name, machine id, address or credential value in any output, error reason, test name, commit message or document. Test fixtures use the existing fake values (`acme-dental`, `1234567890`).
- Job names: `ads-audit` (unchanged) and `ads-report`. Account `hermes-app-ads-report`. Tools `ads_report_run`, `ads_report_status`, `ads_report_list`. MCP server key `ads_report`.
- The report store is `/var/lib/hermes/report-archive`: `root:root 0700`; one folder per client, `root:root 0700`; files `0600`, named `<ts>-report.md` with `<ts>` as `YYYY-MM-DD_HH-MM-SS`. No container mounts it.
- The manifest's key set is closed and is exactly: `app, user, command, ops, tools, wait_seconds, result, descriptions`.
- Result roots are a fixed table in the code: `vaults` → `/var/lib/hermes/vaults`, `report-archive` → `/var/lib/hermes/report-archive`. A manifest carries no path and no pattern.
- The result keys `vault_path` and `audits` keep their names for both jobs.
- `ads-report` limits: `run` timeout 5400, `per_client_day` 1, `per_box_day` 5; `list` timeout 60, `per_box_day` 60; `wait_seconds` `{run: 300, list: 60}`.
- Step classes, closed: `collect, snapshot, read, proxy, draft, isolation, vault-write, store`. Step limit for `store`: 120 s.
- A figures run never opens the Anthropic key file, never checks the vault, and starts neither `ads-drafter` nor `egress-proxy`.
- The audit's behaviour, result shape and stored results do not change: every existing audit test must pass with at most the changes this plan names.
- The broker, the runner, the three unit files, the spool, the ledger and the off switch are not changed.
- The checklist goes from `version: 1.20` to `version: 1.21` once, in Task 8. Item count stays 38.
- If an existing test fails for a reason this plan does not name: STOP and report it; do not edit that test.
- Never commit anything under `evals/`. `git add` named paths only. Never push; the operator gives the word.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work on branch `feat/ads-report-job`, created from `docs/plan-b-ads-report-job`.

## Review Focus

1. A report result presented under the audit's rule, or an audit result under the report's: refused by the checker (Task 1).
2. The reader's output folder holding a symlink, a FIFO, an oversized file, two files for one report, or none: nothing is stored and the run fails as `store` (Task 2).
3. A figures run on a box whose Anthropic key file is missing or unreadable: it still runs; a test fails if the file is opened (Task 3).
4. A job running on the box without a description file, or a description file without its units: D10.3 says so (Task 5).
5. A job installed since the last PASS, whose journal is days old: judged from its first entry, never `could-not-check` for being young (Task 5).

## File Structure

| File | Change |
|---|---|
| `bin/app_lib.py` (+ test) | manifest keys `result`, `descriptions`; checker takes the manifest; `store` step |
| `registry/apps/ads-audit.json` | the two new keys, reproducing today's rule and texts |
| `registry/apps/ads-report.json` | new |
| `bin/hermes-app-mcp.py` (+ test) | tool descriptions from the manifest |
| `bin/report_lib.py` (+ test) | new: read the reader's output safely, join, store, list |
| `bin/report-store.py` (+ test) | new: the `store` step |
| `bin/show-report.py` (+ test), `deploy/show-report` | new: the operator reads a report |
| `bin/run-client-audit.py` (+ test) | `--figures` mode; `step_name`; the probe reports `figures_services` |
| `skills/ads-reports/SKILL.md`, `docker-compose.yml`, `config.yaml.example`, `bin/gateway-config.test.py`, `bin/mcp_config.test.py` | the chat side |
| `bin/collect-review-evidence.py` (+ test) | jobs discovered; per-job D2.4, D4.6, D10.3, D10.4, D10.7, D10.8; D4.1; D7.1 |
| `bin/summarize-review-bundle.py` (+ test) | the per-job shape |
| `deploy/security-review/CHECKLIST.md`, `REPORT-TEMPLATE.md`, `REVIEWER-BRIEF.md`, `bin/security-review-checklist.test.py` | v1.21 |
| `deploy/BRING-UP.md`, `README.md` | "Add a chat-triggered job"; the report store; offboarding |

All paths are under `infra/hermes-agent/`.

---

## Phase 1: the template and the job

### Task 1: a job's description file says where its results live and what its tools say

**Files:**
- Modify: `bin/app_lib.py`, `bin/app_lib.test.py`
- Modify: `registry/apps/ads-audit.json`; Create: `registry/apps/ads-report.json`
- Modify: `bin/hermes-app-mcp.py`, `bin/hermes-app-mcp.test.py`
- Modify: `bin/collect-review-evidence.py` (`d10_8` only), `bin/run-client-audit.test.py` (one test)

**Interfaces:**
- Produces:
  - `app_lib.RESULT_ROOTS = {"vaults": "/var/lib/hermes/vaults", "report-archive": "/var/lib/hermes/report-archive"}`
  - `app_lib.Manifest` fields: `app user command ops tools wait_seconds result descriptions`
  - `app_lib.result_path_re(manifest, client) -> re.Pattern` (group 1 is the timestamp)
  - `app_lib.result_in_whitelist(r, manifest)` (the manifest is now required)
  - `app_lib.STEP_CLASSES` ends with `"store"`
  - `app_lib.load_manifests(manifest_dir) -> {app: Manifest}` for every `*.json` in the directory

- [ ] **Step 1: Write the failing tests** (in `bin/app_lib.test.py`; `m()` there returns the audit's manifest and `MANIFEST` is its path)

```python
REPORT_MANIFEST = os.path.join(os.path.dirname(HERE), "registry", "apps", "ads-report.json")


def mr():
    return A.load_manifest(REPORT_MANIFEST, "ads-report")


class TestManifestResultAndDescriptions(unittest.TestCase):
    def _load(self, change):
        raw = json.load(open(MANIFEST))
        change(raw)
        d = tempfile.mkdtemp()
        json.dump(raw, open(os.path.join(d, "ads-audit.json"), "w"))
        return A.load_manifest(os.path.join(d, "ads-audit.json"), "ads-audit")

    def test_both_committed_manifests_load_with_exactly_eight_keys(self):
        self.assertEqual(m().result, {"root": "vaults", "subdir": "audits", "suffix": "-audit.md"})
        self.assertEqual(mr().result, {"root": "report-archive", "subdir": "", "suffix": "-report.md"})
        for man in (m(), mr()):
            self.assertEqual(set(man.descriptions), set(man.tools))
        self.assertEqual(set(json.load(open(REPORT_MANIFEST))),
                         {"app", "user", "command", "ops", "tools", "wait_seconds", "result", "descriptions"})

    def test_the_report_manifest_is_the_design_s(self):
        r = mr()
        self.assertEqual((r.user, r.command), ("hermes-app-ads-report", "/usr/local/sbin/run-client-audit"))
        self.assertEqual(r.ops["run"], {"args": ["--figures", "--json"], "timeout": 5400,
                                        "quota": {"per_client_day": 1, "per_box_day": 5}})
        self.assertEqual(r.ops["list"], {"args": ["--figures", "--list", "--json"], "timeout": 60,
                                         "quota": {"per_box_day": 60}})
        self.assertEqual(r.tools, {"run": "ads_report_run", "status": "ads_report_status", "list": "ads_report_list"})
        self.assertEqual(r.wait_seconds, {"run": 300, "list": 60})

    def test_a_manifest_without_the_new_keys_or_with_a_bad_one_is_refused(self):
        bad = [lambda d: d.pop("result"), lambda d: d.pop("descriptions"),
               lambda d: d["result"].update(root="/var/lib/hermes/vaults"),      # a path, not a root's name
               lambda d: d["result"].update(root="governance"),
               lambda d: d["result"].update(subdir="../x"), lambda d: d["result"].update(subdir="a/b"),
               lambda d: d["result"].update(suffix="audit.md"), lambda d: d["result"].update(suffix="-a.txt"),
               lambda d: d["result"].update(suffix="-(.*)\\.md"), lambda d: d["result"].update(extra=1),
               lambda d: d["descriptions"].pop("status"), lambda d: d["descriptions"].update(other="x"),
               lambda d: d["descriptions"].update(run=""), lambda d: d["descriptions"].update(run="x" * 301),
               lambda d: d["descriptions"].update(run="line\nbreak"), lambda d: d["descriptions"].update(run="café"),
               lambda d: d["descriptions"].update(run=7)]
        for i, change in enumerate(bad):
            with self.subTest(i=i), self.assertRaises(ValueError):
                self._load(change)

    def test_load_manifests_finds_every_job_and_refuses_a_stray_file(self):
        d = os.path.dirname(MANIFEST)
        self.assertEqual(sorted(A.load_manifests(d)), ["ads-audit", "ads-report"])
        t = tempfile.mkdtemp()
        shutil.copy(MANIFEST, t)
        open(os.path.join(t, "Bad Name.json"), "w").write("{}")
        with self.assertRaises(ValueError):
            A.load_manifests(t)


class TestResultPathPerJob(unittest.TestCase):
    TS = "2026-10-01_12-00-00"

    def _ok(self, path):
        return {"status": "ok", "reason": None, "exit_code": 0, "ts": self.TS,
                "steps": [{"name": "collect", "rc": 0, "seconds": 1.0}, {"name": "store", "rc": 0, "seconds": 0.1}],
                "vault_path": path}

    AUDIT = "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"
    REPORT = "/var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md"

    def test_each_job_accepts_its_own_location_and_refuses_the_other_s(self):
        req = {"request_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "op": "run", "client": "acme-dental"}
        for man, good, bad in ((m(), self.AUDIT, self.REPORT), (mr(), self.REPORT, self.AUDIT)):
            done = lambda p: {"job_id": "x", "rc": 0, "stdout": json.dumps(self._ok(p)), "timed_out": False, "interrupted": False}
            self.assertEqual(A.map_done(req, done(good), man)["vault_path"], good)
            r = A.map_done(req, done(bad), man)
            self.assertEqual((r["status"], r["reason"], r["vault_path"]), ("failed", "internal", None))

    def test_another_client_s_path_another_timestamp_and_a_deeper_path_are_refused(self):
        req = {"request_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "op": "run", "client": "acme-dental"}
        for p in (self.REPORT.replace("acme-dental", "other-dental"), self.REPORT.replace("12-00-00", "12-00-01"),
                  self.REPORT.replace("/acme-dental/", "/acme-dental/audits/"), self.REPORT + "x", "/tmp" + self.REPORT):
            done = {"job_id": "x", "rc": 0, "stdout": json.dumps(self._ok(p)), "timed_out": False, "interrupted": False}
            self.assertEqual(A.map_done(req, done, mr())["reason"], "internal", p)

    def test_the_whitelist_re_check_needs_the_job_s_manifest(self):
        req = {"request_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "op": "run", "client": "acme-dental"}
        done = {"job_id": "x", "rc": 0, "stdout": json.dumps(self._ok(self.REPORT)), "timed_out": False, "interrupted": False}
        r = json.loads(json.dumps(A.map_done(req, done, mr())))
        self.assertEqual(A.result_in_whitelist(r, mr()), (True, True))
        self.assertEqual(A.result_in_whitelist(r, m()), (True, False))

    def test_store_is_a_step_class_and_the_list_is_closed(self):
        self.assertEqual(A.STEP_CLASSES, ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write", "store"))
        self.assertIn("store", A.STATUS_REASONS["failed"])
```

(add `shutil, tempfile` to that file's imports if missing.) In `bin/hermes-app-mcp.test.py` add:

```python
    def test_each_job_s_tools_carry_its_own_descriptions(self):
        for app, word in (("ads-audit", "audit"), ("ads-report", "report")):
            man = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps", app + ".json"), app)
            tools = {t["name"]: t["description"] for t in MCP.Server(man, "/nonexistent")._tools()}
            self.assertEqual(set(tools), set(man.tools.values()))
            self.assertEqual(tools[man.tools["run"]], man.descriptions["run"])
            self.assertIn(word, tools[man.tools["run"]].lower())
        self.assertFalse(hasattr(MCP, "DESCRIPTIONS"))
```

(`MCP` stands for however that file names the loaded server module.)

Run: `python3 infra/hermes-agent/bin/app_lib.test.py 2>&1 | tail -4` → ERROR (`ads-report.json` missing; `Manifest` has no `result`).

- [ ] **Step 2: The two description files**

`registry/apps/ads-audit.json`: add after `"wait_seconds"`:

```json
  "result": {"root": "vaults", "subdir": "audits", "suffix": "-audit.md"},
  "descriptions": {
    "run": "Run a Google Ads trend audit for one registered client. Takes minutes. Returns a result with status ok|refused|failed|busy, or pending with a request_id. A refused or failed result is FINAL: do not call this tool again for that client today.",
    "list": "List the timestamps of a client's past audits. Returns timestamps only.",
    "status": "Check the result of an earlier request by its request_id. Files nothing."
  }
```

Create `registry/apps/ads-report.json`:

```json
{
  "app": "ads-report",
  "user": "hermes-app-ads-report",
  "command": "/usr/local/sbin/run-client-audit",
  "ops": {
    "run": {"args": ["--figures", "--json"], "timeout": 5400, "quota": {"per_client_day": 1, "per_box_day": 5}},
    "list": {"args": ["--figures", "--list", "--json"], "timeout": 60, "quota": {"per_box_day": 60}}
  },
  "tools": {"run": "ads_report_run", "status": "ads_report_status", "list": "ads_report_list"},
  "wait_seconds": {"run": 300, "list": 60},
  "result": {"root": "report-archive", "subdir": "", "suffix": "-report.md"},
  "descriptions": {
    "run": "Produce the Google Ads figures report for one registered client: the account's three read-only reports, with no AI analysis. Takes minutes. Returns a result with status ok|refused|failed|busy, or pending with a request_id. A refused or failed result is FINAL: do not call this tool again for that client today.",
    "list": "List the timestamps of a client's past figures reports. Returns timestamps only.",
    "status": "Check the result of an earlier report request by its request_id. Files nothing."
  }
}
```

- [ ] **Step 3: `app_lib.py`**

```python
STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write", "store")
# Where a job's results may live: the manifest names a root from this table, never a path.
RESULT_ROOTS = {"vaults": "/var/lib/hermes/vaults", "report-archive": "/var/lib/hermes/report-archive"}
_SUBDIR_RE = re.compile(r"^(?:[a-z][a-z0-9-]{0,31})?$")
_SUFFIX_RE = re.compile(r"^-[a-z][a-z0-9-]{0,31}\.md$")
_DESCRIPTION_RE = re.compile(r"^[\x20-\x7e]{1,300}$")
MANIFEST_KEYS = frozenset({"app", "user", "command", "ops", "tools", "wait_seconds", "result", "descriptions"})

Manifest = collections.namedtuple("Manifest", "app user command ops tools wait_seconds result descriptions")
```

In `load_manifest`: `if set(d) != MANIFEST_KEYS:`; before the `return`, add:

```python
    res = d["result"]
    if not isinstance(res, dict) or set(res) != {"root", "subdir", "suffix"} \
            or not isinstance(res["root"], str) or res["root"] not in RESULT_ROOTS \
            or not isinstance(res["subdir"], str) or not _SUBDIR_RE.fullmatch(res["subdir"]) \
            or not isinstance(res["suffix"], str) or not _SUFFIX_RE.fullmatch(res["suffix"]):
        raise ValueError("manifest result")
    desc = d["descriptions"]
    if not isinstance(desc, dict) or set(desc) != set(tools) \
            or not all(isinstance(v, str) and _DESCRIPTION_RE.fullmatch(v) for v in desc.values()):
        raise ValueError("manifest descriptions")
    return Manifest(d["app"], d["user"], d["command"], ops, tools, ws, dict(res), dict(desc))
```

Add:

```python
def load_manifests(manifest_dir):
    """Every job the directory declares: {app: Manifest}. A file that is not `<app>.json` with a
    valid app name, or whose manifest does not load, is a ValueError: a directory that cannot be
    read whole declares nothing."""
    out = {}
    for name in sorted(os.listdir(manifest_dir)):
        if not name.endswith(".json") or not APP_RE.fullmatch(name[:-5]):
            raise ValueError("an entry that is not a job's manifest")
        out[name[:-5]] = load_manifest(os.path.join(manifest_dir, name), name[:-5])
    return out


def result_path_re(manifest, client):
    """The one place a run's result may be for this job and this client; group 1 is the timestamp."""
    res = manifest.result
    sub = "/" + res["subdir"] if res["subdir"] else ""
    return re.compile(re.escape(RESULT_ROOTS[res["root"]] + "/" + client + sub) + "/(" + _TS_BODY + ")"
                      + re.escape(res["suffix"]))
```

`_run_result(req, rc, p, manifest)`: replace the hard-coded `want = re.compile(...)` with `want = result_path_re(manifest, req["client"])`. `map_done`: pass `manifest` to `_run_result`. `_broker_could_write(r, is_list, manifest)` and `result_in_whitelist(r, manifest)`: pass the manifest down to `_run_result`. Update the module docstring's "the four file schemas" sentence to mention that the result location is the manifest's.

- [ ] **Step 4: the callers**

- `bin/hermes-app-mcp.py`: delete `DESCRIPTIONS`; in `_tools`, `"description": self.m.descriptions[op]`.
- `bin/collect-review-evidence.py`, `d10_8`: load the job's manifest once and pass it (Task 5 makes this per job):

```python
    manifest = A.load_manifest(host.path(AGENT_DIR + "/registry/apps/" + APP + ".json"), APP)
```

  at the top of `d10_8` inside a `try` that raises `CouldNotCheck("the job's manifest could not be loaded")` on `OSError` or `ValueError`, then `A.result_in_whitelist(obj, manifest)`. In `collect-review-evidence.test.py`, the fixture that builds the fake box for D10.8 must hold the manifest: copy `registry/apps/ads-audit.json` from the repository into `<root>/opt/hermes-agent/registry/apps/ads-audit.json` in that class's `setUp` (find it by `def _result(self, obj, name=None)`).
- `bin/app_lib.test.py`: every existing call `A.result_in_whitelist(x)` becomes `A.result_in_whitelist(x, m())`. Existing tests that assert the exact `STEP_CLASSES` length or the manifest's exact key set are updated to the new values; list each in the report.
- `bin/run-client-audit.test.py`, `test_the_app_runner_manifest_offers_no_probe`: run the same two assertions for both manifests.
- `git grep -n "result_in_whitelist\|_run_result\|Manifest(" infra/hermes-agent/bin` must show no caller with the old arity.

- [ ] **Step 5: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes, `rc=0`.

```bash
git add infra/hermes-agent/bin/app_lib.py infra/hermes-agent/bin/app_lib.test.py infra/hermes-agent/bin/hermes-app-mcp.py infra/hermes-agent/bin/hermes-app-mcp.test.py infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/run-client-audit.test.py infra/hermes-agent/registry/apps
git commit -m "apps: a job's manifest states where its results live and what its tools say; ads-report declared"
```

---

### Task 2: the report store (read the reader's output safely, join, store, list, show)

**Files:**
- Create: `bin/report_lib.py`, `bin/report_lib.test.py`, `bin/report-store.py`, `bin/report-store.test.py`, `bin/show-report.py`, `bin/show-report.test.py`, `deploy/show-report`

**Interfaces:**
- Consumes: `client_audit_lib` (`open_dir_below`, `UnsafePathError`, `TS_RE`, `others_named`), `vault_lib` (`load_registry`, `validate_slug`).
- Produces (`report_lib`):
  - `ARCHIVE = "/var/lib/hermes/report-archive"`, `MAX_REPORT_BYTES = 5 * 1024 * 1024`, `ISOLATION_RC = 4`
  - `class ReportError(Exception)`
  - `read_reports(reports_base, slug, readers) -> str` (the joined document)
  - `store(archive_base, slug, ts, text, owner_uid=0) -> str` (the stored file's path below `archive_base`)
  - `list_report_ts(dir_fd) -> [ts]`, `is_stored(archive_base, slug, ts) -> bool`
- `report-store.py --client S --ts T --reports-dir D --archive A --registry R --reader N [--reader N ...]`: exit 0 stored, 1 failed, `ISOLATION_RC` when the document names another client (nothing stored).
- `show-report <client> [--latest | --ts T | --list]`, as `show-audit`.

- [ ] **Step 1: Write the failing tests** (`bin/report_lib.test.py`)

```python
#!/usr/bin/env python3
import os, stat, sys, tempfile, shutil, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import report_lib as RL

READERS = ("account_overview", "audit_search_terms", "audit_analyze")
TS = "2026-10-01_12-00-00"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.root, True)
        self.reports = os.path.join(self.root, "reports"); self.archive = os.path.join(self.root, "report-archive")
        self.cdir = os.path.join(self.reports, "acme-dental"); os.makedirs(self.cdir)
        os.mkdir(self.archive, 0o700)
        for r in READERS:
            self.w(f"2026-10-01_11-59-0{READERS.index(r)}-{r}.md", f"figures of {r}\n")

    def w(self, name, text):
        with open(os.path.join(self.cdir, name), "w") as f:
            f.write(text)

    def read(self):
        return RL.read_reports(self.reports, "acme-dental", READERS)


class TestRead(Base):
    def test_the_three_reports_are_joined_in_the_readers_order_with_a_heading_each(self):
        text = self.read()
        marks = [text.index(f"## {r}\n") for r in READERS]
        self.assertEqual(marks, sorted(marks))
        for r in READERS:
            self.assertIn(f"figures of {r}", text)

    def test_a_missing_report_or_two_for_one_reader_is_refused(self):
        os.unlink(os.path.join(self.cdir, "2026-10-01_11-59-00-account_overview.md"))
        with self.assertRaises(RL.ReportError):
            self.read()
        self.w("2026-10-01_11-59-00-account_overview.md", "a"); self.w("2026-10-01_11-59-09-account_overview.md", "b")
        with self.assertRaises(RL.ReportError):
            self.read()

    def test_a_link_a_fifo_an_oversized_file_and_a_stray_entry_are_refused(self):
        name = "2026-10-01_11-59-00-account_overview.md"
        target = os.path.join(self.root, "secret"); open(target, "w").write("SECRET")
        for make in (lambda p: os.symlink(target, p), lambda p: os.mkfifo(p), lambda p: os.mkdir(p),
                     lambda p: open(p, "w").write("x" * (RL.MAX_REPORT_BYTES + 1))):
            with self.subTest(make=make):
                p = os.path.join(self.cdir, name)
                os.path.isdir(p) and not os.path.islink(p) and os.rmdir(p)
                os.path.lexists(p) and os.unlink(p)
                make(p)
                with self.assertRaises((RL.ReportError, OSError)) as cm:
                    self.read()
                self.assertNotIn("SECRET", str(cm.exception))
                os.path.isdir(p) and not os.path.islink(p) and os.rmdir(p)
                os.path.lexists(p) and os.unlink(p)
                self.w(name, "ok")
        self.w("notes.txt", "x")
        with self.assertRaises(RL.ReportError):
            self.read()

    def test_a_linked_client_folder_is_refused(self):
        shutil.rmtree(self.cdir); os.symlink(self.root, self.cdir)
        with self.assertRaises(OSError):
            self.read()

    def test_bytes_that_are_not_text_are_replaced_not_fatal(self):
        with open(os.path.join(self.cdir, "2026-10-01_11-59-00-account_overview.md"), "wb") as f:
            f.write(b"a\xffb")
        self.assertIn("a�b", self.read())


class TestStore(Base):
    def store(self, text="DOC", ts=TS):
        return RL.store(self.archive, "acme-dental", ts, text, owner_uid=os.geteuid())

    def test_the_document_lands_owner_only_under_the_client_s_folder(self):
        rel = self.store()
        self.assertEqual(rel, f"acme-dental/{TS}-report.md")
        p = os.path.join(self.archive, rel)
        self.assertEqual(open(p).read(), "DOC")
        self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.dirname(p)).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [f"{TS}-report.md"])     # no temporary file left
        self.assertTrue(RL.is_stored(self.archive, "acme-dental", TS))

    def test_an_existing_report_is_never_overwritten(self):
        self.store("first")
        with self.assertRaises((RL.ReportError, OSError)):
            self.store("second")
        self.assertEqual(open(os.path.join(self.archive, "acme-dental", f"{TS}-report.md")).read(), "first")

    def test_a_loose_or_linked_store_and_a_linked_client_folder_are_refused(self):
        os.chmod(self.archive, 0o755)
        with self.assertRaises(RL.ReportError):
            self.store()
        os.chmod(self.archive, 0o700)
        os.symlink(self.root, os.path.join(self.archive, "acme-dental"))
        with self.assertRaises(OSError):
            self.store()
        self.assertFalse(os.path.exists(os.path.join(self.root, f"{TS}-report.md")))

    def test_a_bad_timestamp_or_client_name_is_refused(self):
        for slug, ts in (("acme-dental", "2026-10-01"), ("acme-dental", "../x"), ("../x", TS), ("a/b", TS)):
            with self.subTest(slug=slug, ts=ts), self.assertRaises((RL.ReportError, ValueError, OSError)):
                RL.store(self.archive, slug, ts, "DOC", owner_uid=os.geteuid())

    def test_the_list_is_sorted_and_holds_regular_report_files_only(self):
        for ts in ("2026-10-02_00-00-00", TS):
            self.store(ts=ts)
        d = os.path.join(self.archive, "acme-dental")
        os.symlink("x", os.path.join(d, "2026-10-03_00-00-00-report.md")); open(os.path.join(d, "x.md"), "w").close()
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(RL.list_report_ts(fd), [TS, "2026-10-02_00-00-00"])
        finally:
            os.close(fd)
        self.assertFalse(RL.is_stored(self.archive, "acme-dental", "2026-10-03_00-00-00"))


if __name__ == "__main__":
    unittest.main()
```

Run it → ERROR (`No module named 'report_lib'`).

- [ ] **Step 2: `bin/report_lib.py`**

```python
#!/usr/bin/env python3
"""The figures-report store (design 2026-10-13, Part 1). Stdlib only.

A figures run's three reader reports are written by a container (uid 10000) into
/var/lib/hermes/reports/<client>/. Root joins them into ONE document and stores it in
/var/lib/hermes/report-archive/<client>/<ts>-report.md: a store no container mounts, so a report
never reaches the drafter of a later audit. Everything read here was written by a container: each
name is opened below its folder without following a link, must be a regular file, is size-capped,
and is copied, never parsed."""
import os, re, stat

import client_audit_lib as L
import governance_lib

ARCHIVE = "/var/lib/hermes/report-archive"
MAX_REPORT_BYTES = 5 * 1024 * 1024
ISOLATION_RC = 4          # report-store.py: the document names another client; nothing was stored
_READER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SLUG_RE = governance_lib.SLUG_RE          # the registry's own rule for a client's short name, never restated
_READER_FILE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}-([a-z][a-z0-9_]{0,63})\.md$")
_REPORT_NAME_RE = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})-report\.md$")


class ReportError(Exception):
    pass


def _read_one(dir_fd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReportError("a report is not a regular file")
        if st.st_size > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        data = os.read(fd, MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        return data.decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def read_reports(reports_base, slug, readers):
    """The joined document: one `## <reader>` section per reader, in `readers`' order. Exactly one
    file per reader, and nothing else in the folder, or ReportError. Reasons never hold a name."""
    if not _SLUG_RE.fullmatch(slug) or not readers or not all(_READER_RE.fullmatch(r) for r in readers):
        raise ReportError("invalid client or reader name")
    fd = L.open_dir_below(reports_base, (slug,))
    if fd is None:
        raise ReportError("the reports folder is missing")
    try:
        found = {}
        for name in sorted(os.listdir(fd)):
            m = _READER_FILE_RE.fullmatch(name)
            if m is None or m.group(1) not in readers:
                raise ReportError("an entry that is not one of this run's reports")
            if m.group(1) in found:
                raise ReportError("two reports for one reader")
            found[m.group(1)] = name
        if set(found) != set(readers):
            raise ReportError("a report is missing")
        return "".join(f"## {r}\n\n{_read_one(fd, found[r]).rstrip()}\n\n" for r in readers)
    finally:
        os.close(fd)


def _archive_fd(archive_base, owner_uid):
    st = os.lstat(archive_base)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) \
            or st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
        raise ReportError("the report store must be a real directory, owner-only")
    return os.open(archive_base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def store(archive_base, slug, ts, text, owner_uid=0):
    """Write the document as <archive>/<slug>/<ts>-report.md, 0600, never over an existing file.
    Returns the path below the archive. The client folder is created 0700 when missing."""
    if not _SLUG_RE.fullmatch(slug) or not L.TS_RE.fullmatch(ts):
        raise ReportError("invalid client name or timestamp")
    base = _archive_fd(archive_base, owner_uid)
    try:
        try:
            os.mkdir(slug, 0o700, dir_fd=base)
        except FileExistsError:
            pass
        cfd = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
    finally:
        os.close(base)
    try:
        st = os.fstat(cfd)
        if st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
            raise ReportError("the client's report folder must be owner-only")
        name, tmp = f"{ts}-report.md", f".{ts}-report.tmp"
        try:
            os.stat(name, dir_fd=cfd, follow_symlinks=False)
            raise ReportError("a report with this timestamp exists")
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=cfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.link(tmp, name, src_dir_fd=cfd, dst_dir_fd=cfd)      # link, not rename: never replaces a file
        finally:
            try:
                os.unlink(tmp, dir_fd=cfd)
            except FileNotFoundError:
                pass
        return f"{slug}/{name}"
    finally:
        os.close(cfd)


def list_report_ts(dir_fd):
    out = []
    for name in os.listdir(dir_fd):
        m = _REPORT_NAME_RE.fullmatch(name)
        if m and stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
            out.append(m.group(1))
    return sorted(out)


def is_stored(archive_base, slug, ts):
    try:
        fd = L.open_dir_below(archive_base, (slug,))
    except OSError:
        return False
    if fd is None:
        return False
    try:
        return stat.S_ISREG(os.stat(f"{ts}-report.md", dir_fd=fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)
```

Run: `python3 infra/hermes-agent/bin/report_lib.test.py 2>&1 | tail -3` → `OK`. (If `os.link` with `dir_fd` is unavailable on the test machine, `os.link in os.supports_dir_fd` is False: then use `os.open(name, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o600, dir_fd=cfd)` directly for the final name and drop the temporary file; say which form you used.)

- [ ] **Step 3: `bin/report-store.py` and its test**

```python
#!/usr/bin/env python3
"""The `store` step of a figures run (run by root; design 2026-10-13, Part 1). Stdlib only.

  report-store.py --client S --ts T --reports-dir D --archive A --registry R --reader N [--reader N ...]

Joins this run's reader reports and stores them as one document. Before anything is written the
document is checked for another client's name: a hit stores nothing and exits ISOLATION_RC.
Exit 0 stored, 1 failed. Human lines on stderr, in fixed words: never a report's text."""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import report_lib as RL
import vault_lib as V

OWNER_UID = 0          # tests override


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    for name in ("--client", "--ts", "--reports-dir", "--archive", "--registry"):
        ap.add_argument(name, required=True)
    ap.add_argument("--reader", action="append", required=True)
    a = ap.parse_args(argv)
    try:
        text = RL.read_reports(a.reports_dir, a.client, tuple(a.reader))
        named = L.others_named(text, a.client, list(V.load_registry(a.registry)))
        if named:
            print(f"report-store: ASSERTION FAIL: the reports name {len(named)} other client(s); nothing stored",
                  file=sys.stderr)
            return RL.ISOLATION_RC
        rel = RL.store(a.archive, a.client, a.ts, text, owner_uid=OWNER_UID)
    except RL.ReportError as e:
        print(f"report-store: refused: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"report-store: failed: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"report-store: stored {os.path.basename(rel)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`bin/report-store.test.py`: load the module with `importlib` (as `RS`), set `RS.OWNER_UID = os.geteuid()`, build the same tree as `report_lib.test.py`'s `Base` plus a registry file `{"clients": {"acme-dental": {...}, "other-dental": {...}}}` in the shape `vault_lib.load_registry` reads (copy the shape from `run-client-audit.test.py`'s `Base.setUp`). Tests:
- a clean run returns 0, the file exists `0600`, and stdout is empty;
- a report whose text holds `other-dental` returns `RL.ISOLATION_RC`, the client's archive folder holds no file, and stderr holds neither `other-dental` nor a line of the report;
- a missing report returns 1 and stores nothing;
- an unreadable registry returns 1 and stores nothing;
- `--reader` given twice for the same name, and an abbreviated option, are usage errors (exit 2).

- [ ] **Step 4: `bin/show-report.py`, its test, `deploy/show-report`**

`bin/show-report.py`: copy `bin/show-audit.py` and change exactly: the docstring (`Print one client's figures report to the operator`), `VAULTS` → `ARCHIVE = RL.ARCHIVE`, the folder `L.open_dir_below(root + ARCHIVE, (a.client,))`, the listing `RL.list_report_ts(fd)`, the file name `f"{ts}-report.md"`, the messages' prefix `show-report:` and words `report(s)`. Keep `safe_text` (a report quotes search terms, which an outsider controls) and every refusal as it is.

`deploy/show-report` (mode 755):

```sh
#!/bin/sh
# Installed as /usr/local/sbin/show-report (symlink, BRING-UP "Add a chat-triggered job").
# Root only: the report store is root's, 0700.
[ "$(id -u)" = 0 ] || { echo "show-report: run with sudo" >&2; exit 2; }
exec python3 /opt/hermes-agent/bin/show-report.py "$@"
```

`bin/show-report.test.py`: mirror `show-audit`'s tests if a `show-audit.test.py` exists (same cases, the report's names); otherwise write: `--latest`, `--ts`, `--list`; a control character in the report is stripped; a symlinked client folder and an invalid `--ts` are refused with exit 2; no report gives exit 1.

- [ ] **Step 5: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes (three more suites), `rc=0`.

```bash
git add infra/hermes-agent/bin/report_lib.py infra/hermes-agent/bin/report_lib.test.py infra/hermes-agent/bin/report-store.py infra/hermes-agent/bin/report-store.test.py infra/hermes-agent/bin/show-report.py infra/hermes-agent/bin/show-report.test.py infra/hermes-agent/deploy/show-report
git commit -m "reports: a root-only store for figures reports, the store step and show-report"
```

---

### Task 3: the figures mode of `run-client-audit.py`

**Files:**
- Modify: `bin/run-client-audit.py`, `bin/run-client-audit.test.py`

**Interfaces:**
- Consumes: `report_lib` (Task 2), `app_lib.STEP_CLASSES` (Task 1).
- Produces: `--figures`; `plan(rec, ts, root, cred_values=None, anthropic_key=None, figures=False)`; `step_name` returning `store` for the store step and raising `ValueError` for an argv it does not know; `TIMEOUTS["store"] == 120`; `probe_env`'s result gains `figures_services`.

- [ ] **Step 1: Write the failing tests** (in `bin/run-client-audit.test.py`)

Extend `FakeRunner.__call__`: when `"ads-reader" in argv`, write `f"2026-10-01_11-59-00-{report}.md"` (the name after `--report`) with text `f"figures {report}\n"` into `self.root + "/var/lib/hermes/reports/acme-dental"`; when `name == "store"`, run the real step: `RS.main(argv[1:])` where `RS` is `report-store.py` loaded with `importlib` and `RS.OWNER_UID = os.geteuid()`, and return its exit code. In `Base.setUp` create `/var/lib/hermes/report-archive` under the root with mode `0700`.

```python
class TestFigures(Base):
    ARCHIVED = "/var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md"

    def test_the_steps_are_collect_read_store_and_the_report_lands_in_the_archive(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r, "--figures")
        self.assertEqual(rc, 0, text)
        names = [RCA.step_name(c["argv"]) for c in r.calls]
        self.assertEqual(names, [f"collect:{c}" for c in RCA.COLLECTORS] + [f"read:{x}" for x in RCA.READERS] + ["store"])
        doc = open(self.root + self.ARCHIVED).read()
        for x in RCA.READERS:
            self.assertIn(f"figures {x}", doc)
        self.assertIn(self.ARCHIVED, text)
        self.assertEqual(self.proxy_stops, [])                       # the proxy is neither started nor stopped
        self.assertFalse(os.path.exists(self.root + "/var/lib/hermes/vaults/acme-dental/audits"))

    def test_json_names_the_archive_path_and_only_the_three_step_classes(self):
        rc, text = self.run_main(FakeRunner(self.root), "--figures", "--json")
        j = json.loads(text.splitlines()[0])
        self.assertEqual((j["status"], j["vault_path"]), ("ok", self.ARCHIVED))
        self.assertEqual([s["name"] for s in j["steps"]], ["collect", "read", "store"])

    def test_no_anthropic_key_no_drafter_no_proxy_no_vault(self):
        os.unlink(self.root + "/etc/hermes/.env.anthropic")
        shutil.rmtree(self.root + "/var/lib/hermes/vaults/acme-dental")
        r = FakeRunner(self.root)
        with mock.patch.object(RCA.L, "load_env_value", side_effect=AssertionError("the AI key file was opened")), \
                mock.patch.object(RCA.L, "anthropic_key_state", side_effect=AssertionError("the AI key file was read")):
            rc, text = self.run_main(r, "--figures")
        self.assertEqual(rc, 0, text)
        for c in r.calls:
            self.assertNotIn("ads-drafter", c["argv"]); self.assertNotIn("egress-proxy", c["argv"])
            self.assertNotIn("ANTHROPIC_API_KEY", c["env"]); self.assertNotIn("HERMES_VAULT_DIR", c["env"])

    def test_the_audit_still_refuses_without_the_key_and_still_runs_its_ten_steps(self):
        rc, _ = self.run_main(FakeRunner(self.root))
        self.assertEqual(rc, 0)
        os.unlink(self.root + "/etc/hermes/.env.anthropic")
        self.assertEqual(self.run_main(FakeRunner(self.root))[0], 2)

    def test_a_collector_error_or_no_data_fails_as_collect_before_any_reader(self):
        for kw in ({"error_file": "x.ERROR.txt"}, {"collector_json": False}):
            with self.subTest(kw=kw):
                r = FakeRunner(self.root, **kw)
                rc, text = self.run_main(r, "--figures", "--json")
                j = json.loads(text.splitlines()[0])
                self.assertEqual((rc, j["reason"]), (1, "collect"))
                self.assertFalse(any("ads-reader" in c["argv"] for c in r.calls))

    def test_reports_that_name_another_client_fail_as_isolation_and_store_nothing(self):
        r = FakeRunner(self.root)
        orig = r.__call__
        def call(argv, env, timeout, out, err):
            rc = orig(argv, env, timeout, out, err)
            if "ads-reader" in argv and argv[argv.index("--report") + 1] == RCA.READERS[0]:
                open(self.root + f"/var/lib/hermes/reports/acme-dental/2026-10-01_11-59-00-{RCA.READERS[0]}.md", "a").write("see other-dental\n")
            return rc
        rc, text = self.run_main(call, "--figures", "--json")
        j = json.loads(text.splitlines()[0])
        self.assertEqual((rc, j["status"], j["reason"], j["vault_path"]), (1, "failed", "isolation", None))
        self.assertEqual([s["name"] for s in j["steps"]][-1], "isolation")
        self.assertFalse(os.path.exists(self.root + self.ARCHIVED))

    def test_a_failed_store_step_fails_as_store(self):
        os.chmod(self.root + "/var/lib/hermes/report-archive", 0o755)        # the store refuses a loose archive
        rc, text = self.run_main(FakeRunner(self.root), "--figures", "--json")
        self.assertEqual(rc, 2)                                              # caught by the pre-check, before any step
        os.chmod(self.root + "/var/lib/hermes/report-archive", 0o700)
        rc, text = self.run_main(FakeRunner(self.root, fail_on="store"), "--figures", "--json")
        self.assertEqual(json.loads(text.splitlines()[0])["reason"], "store")

    def test_list_shows_the_archive_and_takes_no_lock(self):
        self.run_main(FakeRunner(self.root), "--figures")
        rc, text = self.run_main(FakeRunner(self.root), "--figures", "--list", "--json")
        self.assertEqual((rc, json.loads(text.splitlines()[0])), (0, {"status": "ok", "audits": ["2026-10-01_12-00-00"]}))
        rc, text = self.run_main(FakeRunner(self.root), "--list", "--json")      # the audit's list is its own
        self.assertEqual(json.loads(text.splitlines()[0]), {"status": "ok", "audits": []})

    def test_dry_run_prints_the_figures_plan_and_runs_nothing(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r, "--figures", "--dry-run")
        self.assertEqual((rc, r.calls), (0, []))
        self.assertIn("[store]", text); self.assertNotIn("[draft]", text); self.assertNotIn("[proxy]", text)

    def test_a_busy_lock_is_busy_for_a_figures_run_too(self):
        with RCA.L.AuditLock(self.root + RCA.LOCK):
            rc, text = self.run_main(FakeRunner(self.root), "--figures", "--json")
        self.assertEqual((rc, json.loads(text.splitlines()[0])["status"]), (3, "busy"))

    def test_figures_does_not_mix_with_the_probes(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            RCA.main(["--probe-env", "--figures"], root=self.root)


class TestStepNames(unittest.TestCase):
    def test_the_two_lists_of_step_classes_are_one(self):
        import app_lib as A
        self.assertEqual(RCA.STEP_CLASSES, A.STEP_CLASSES)
        self.assertEqual(set(RCA.TIMEOUTS), set(A.STEP_CLASSES) - {"isolation"})
        self.assertEqual(RCA.TIMEOUTS["store"], 120)

    def test_an_unknown_step_has_no_name(self):
        with self.assertRaises(ValueError):
            RCA.step_name(["true"])
```

Add to `class TestProbes` (it has `fake_probe_runner` and the module-level `ENV_OK` answers):

```python
    def test_the_probe_reports_which_services_a_figures_run_would_start(self):
        run, _ = self.fake_probe_runner(ENV_OK)
        j = RCA.probe_env(self.root, run)
        self.assertEqual(j["figures_services"], ["ads-collector", "ads-reader"])
        self.assertTrue(j["matches_declared"], j)
        with mock.patch.object(RCA, "_figures_services", return_value=["ads-collector", "ads-drafter", "ads-reader"]):
            run, _ = self.fake_probe_runner(ENV_OK)
            self.assertFalse(RCA.probe_env(self.root, run)["matches_declared"])

    def test_the_figures_plan_is_built_without_opening_a_credential_file(self):
        with mock.patch.object(RCA.L, "load_cred_env", side_effect=AssertionError("the Google credential file was opened")), \
                mock.patch.object(RCA.L, "load_env_value", side_effect=AssertionError("the AI key file was opened")):
            self.assertEqual(RCA._figures_services(self.root), ["ads-collector", "ads-reader"])
```

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py TestFigures TestStepNames 2>&1 | tail -4` → FAIL/ERROR (`unrecognized arguments: --figures`).

- [ ] **Step 2: Write the implementation** (`bin/run-client-audit.py`)

Imports: add `import report_lib as RL` beside the other local imports. Constants:

```python
REPORT_ARCHIVE = RL.ARCHIVE     # root-only, 0700; no container mounts it (design 2026-10-13)
TIMEOUTS = {"collect": 900, "snapshot": 120, "read": 300, "proxy": 60, "draft": 1200, "vault-write": 120, "store": 120}
STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write", "store")
```

`step_name`: replace the last line with

```python
    for script, name in (("ads-metrics-snapshot.py", "snapshot"), ("vault-write.py", "vault-write"),
                         ("report-store.py", "store")):
        if any(a.endswith(script) for a in argv):
            return name
    raise ValueError("an argv that is no step of this program")
```

`plan(..., figures=False)`: keep the collect steps; then

```python
    if figures:
        # Figures only (design 2026-10-13): no snapshot (its one consumer is the vault's history), no
        # proxy, no draft, no vault-write; the Anthropic key file is not opened. The store step runs
        # as root: it reads what a container wrote, without following a link, and copies bytes.
        steps += [("read", run(f"read-{r}") + ["ads-reader", "--report", r, "--project", PROJECT], cred)
                  for r in READERS]
        steps.append(("store", ["python3", root + AGENT_DIR + "/bin/report-store.py", "--client", slug, "--ts", ts,
                                "--reports-dir", root + REPORTS, "--archive", root + REPORT_ARCHIVE,
                                "--registry", root + REGISTRY] + [x for r in READERS for x in ("--reader", r)], base))
        return steps
```

placed before `steps.append(("snapshot", ...))`. (The existing code after it is the audit's and is unchanged.)

`main`: `ap.add_argument("--figures", action="store_true")`; in the probe check, `if probe and (a.client is not None or a.dry_run or a.figures): ap.error(...)`. In the `--list` branch:

```python
            base, parts = (root + REPORT_ARCHIVE, (rec["slug"],)) if a.figures else (root + VAULTS, (rec["slug"], "audits"))
            fd = L.open_dir_below(base, parts)
            ...
                    audits = (RL.list_report_ts(fd) if a.figures else L.list_audit_ts(fd))[-LIST_LIMIT:]
```

The pre-checks become two branches inside the same `try`:

```python
        L.check_secret_file(root + CRED, uid=OWNER_UID, mode=0o400)
        if a.figures:
            L.check_host_parent(root + REPORTS, uid=OWNER_UID)
            L.check_host_parent(root + REPORT_ARCHIVE, uid=OWNER_UID, mode=0o700)
        else:
            <the existing Anthropic, HOST_PARENTS and vault checks, unchanged>
        pin = ...
        L.package_matches(root + APP_DIR, pin)
        steps = plan(rec, ts, root, figures=a.figures)
```

`_run(steps, rec, ts, root, runner, say, state, figures=False)` (pass `figures=a.figures` from `main`):

- The collection check moves from `if key == "snapshot":` to the first step that is not a collector: keep a local `collected = False`; at the top of the loop, `if key != "collect" and not collected:` run the two existing checks, then `collected = True`.
- After `rc = runner(...)` and `results.append(...)`: 

```python
            if key == "store" and rc == RL.ISOLATION_RC:        # the reports name another client: nothing was stored
                results[-1] = ("isolation", 1, results[-1][2])
                state["reason"] = "isolation"
                say("run-client-audit: ASSERTION FAIL — the reports name another client; not stored")
                return _summary(results, 1, say)
```

  before the generic `if rc != 0:`.
- After the loop:

```python
        if figures:
            stored = f"{REPORT_ARCHIVE}/{slug}/{ts}-report.md"
            if not RL.is_stored(root + REPORT_ARCHIVE, slug, ts):
                state["reason"] = "store"
                say("run-client-audit: the store step reported success but the report is missing")
                return _summary(results, 1, say)
            state["vault_path"] = stored
            say(f"run-client-audit: report -> {stored}  (data collected {ts} UTC)")
            return _summary(results, 0, say)
```

- In the `finally`: wrap the existing `remove_transient` / `stop_proxy` block in `if not figures:` (a figures run starts no proxy and writes no transient draft); keep the signal-mask handling around it.

The probe:

```python
def _figures_services(root):
    """Which audit services a figures run would start: read off plan() itself."""
    rec = {"slug": PROBE_SLUG, "customer_id": "0000000000"}
    steps = plan(rec, "2000-01-01_00-00-00", root, cred_values={n: SENTINEL for n in CRED_NAMES}, figures=True)
    return sorted({s for _, argv, _ in steps for s in DECLARED if s in argv})
```

In `probe_env`: `figures = _figures_services(root)`; `ok = ... and figures == ["ads-collector", "ads-reader"]`; return `{"services": services, "figures_services": figures, "matches_declared": ok}`.

Update the module docstring's usage block with the three `--figures` forms.

- [ ] **Step 3: Existing tests this changes**

- Any test that asserts `probe_env`'s exact dict gains `figures_services`.
- Any test that calls `RCA.step_name` with an argv that is no step and expects `vault-write` now expects `ValueError`.
- Any test pinning `RCA.TIMEOUTS` or `RCA.STEP_CLASSES` gains `store`.

List each in the report with old and new. Any other failure: STOP and report.

- [ ] **Step 4: The end-to-end stand-in test runs both jobs**

`bin/app-e2e.test.py` drives request → broker → runner → result with a fake command, for the audit's manifest only. Make its end-to-end case run once per manifest found in `registry/apps/` (`A.load_manifests`): for each job the fake command prints a result that is valid for THAT job (build the stored path from `A.RESULT_ROOTS[man.result["root"]]`, the client, `man.result["subdir"]` and `man.result["suffix"]`; the step list of a figures run is `collect`, `read`, `store`), and the test asserts the result file the broker writes carries that path and that each job's ledger and spool are its own (a run of one job leaves the other job's `requests/`, `results/` and ledger untouched). Read the file first and keep its structure; change `git add` below to include it.

- [ ] **Step 5: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes.

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py infra/hermes-agent/bin/app-e2e.test.py
git commit -m "run-client-audit: a figures mode (collect, read, store) that opens no AI key and starts no AI step"
```

---

### Task 4: the chat side of the report job

**Files:**
- Create: `skills/ads-reports/SKILL.md`
- Modify: `docker-compose.yml`, `config.yaml.example`, `bin/gateway-config.test.py`, `bin/mcp_config.test.py`, `README.md`

- [ ] **Step 1: Write the failing tests**

`bin/gateway-config.test.py` (it reads the three files as text; follow its helpers): the gateway mounts `./skills/ads-reports:/opt/data/skills/ads-reports:ro`; `config.yaml.example` holds `args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-report"]` and `include: [ads_report_run, ads_report_status, ads_report_list]`; `skills/ads-reports/SKILL.md` names the three tools and `show-report` and does NOT name `ads_audit_run`. Add one test that ties the config to the manifests:

```python
    def test_every_job_s_manifest_has_its_server_and_exactly_its_tools_in_the_template(self):
        import app_lib as A, mcp_config
        block, why = mcp_config.block_value(read("config.yaml.example"))
        self.assertIsNotNone(block, why)
        mans = A.load_manifests(os.path.join(ROOT, "registry/apps"))     # ROOT: this file's name for infra/hermes-agent
        self.assertEqual(sorted(block), sorted(a.replace("-", "_") for a in mans))
        for app, man in mans.items():
            server = block[app.replace("-", "_")]
            self.assertEqual(server["args"], ["/opt/cc-bin/hermes-app-mcp.py", "--app", app])
            self.assertEqual(sorted(server["tools"]["include"]), sorted(man.tools.values()))
            self.assertEqual((server["env"], server["tools"]["resources"], server["tools"]["prompts"]), ({}, False, False))
```

`bin/mcp_config.test.py`: its `EXPECTED` value (the committed block) gains the `ads_report` server with the same shape; the test that pins the committed block's hash is updated to the new hash (compute it with the module, as that test does).

Run both → FAIL.

- [ ] **Step 2: The files**

`config.yaml.example`, under `mcp_servers:`, after the `ads_audit` server (same indentation):

```yaml
  ads_report:
    command: "python3"
    args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-report"]
    env: {}
    timeout: 360
    tools:
      include: [ads_report_run, ads_report_status, ads_report_list]
      resources: false
      prompts: false
```

`docker-compose.yml`, the gateway's volumes, directly under the `./skills/ads-audits` line:

```yaml
      - ./skills/ads-reports:/opt/data/skills/ads-reports:ro  # how Hermes calls the figures-report tools
```

`skills/ads-reports/SKILL.md`: copy `skills/ads-audits/SKILL.md` and change: `name: ads-reports`; the description (`Use when the operator asks to run, check, or list a client's Google Ads figures report. Calls the ads_report_run, ads_report_status and ads_report_list tools. Never reads or summarizes report content; the operator reads reports on the host.`); every `ads_audit_*` → `ads_report_*`; "audit" → "figures report" where it names the product; `sudo show-audit <client>` → `sudo show-report <client>`; the manual command → `sudo run-client-audit <client> --figures`; the `quota` words → `one report per client per day`; `disabled` → `reports are switched off`; the failed-step examples → `collect`, `read`, `store`, `timeout`, `interrupted`. Add under "Reporting a result": `The result's `vault_path` is where the report was stored and a list's `audits` holds the reports' timestamps: the two labels are shared with the audit tools.` Add under "Never": `- Start an audit when a figures report was asked for, or the reverse. If the operator's request could mean either, ask.` Add the same last line to `skills/ads-audits/SKILL.md`.

`README.md`: where it describes the chat-triggered audit (search `ads_audit_run`), add a short paragraph: the second job `ads-report`, its three tools, figures only, the report store `/var/lib/hermes/report-archive` that no container mounts, `sudo show-report`, and that a job is a description file in `registry/apps/` plus the runbook chapter "Add a chat-triggered job".

- [ ] **Step 3: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes. (The collector's D10.6 test and the checklist's D10.6 test may pin the old block or its hash: update the pinned hash in the collector TEST only; the checklist text and its test change in Task 8. If the checklist test fails here, mark it `@unittest.expectedFailure` with a comment naming Task 8, and Task 8 removes that mark.)

```bash
git add infra/hermes-agent/skills infra/hermes-agent/docker-compose.yml infra/hermes-agent/config.yaml.example infra/hermes-agent/bin/gateway-config.test.py infra/hermes-agent/bin/mcp_config.test.py infra/hermes-agent/README.md
git commit -m "ads-report: the chat side (skill, gateway mount, mcp server in the config template)"
```

---

## Phase 2: the security review covers every job

### Task 5: the collector finds the jobs and checks each one

**Files:**
- Modify: `bin/collect-review-evidence.py`, `bin/collect-review-evidence.test.py`

**Interfaces:**
- Consumes: `app_lib.load_manifests`, `result_in_whitelist(r, manifest)`, `_unit_search` (Plan A).
- Produces (bundle shapes; `<app>` is a job's name):
  - `_declared_apps(host) -> {app: Manifest}` from `AGENT_DIR/registry/apps`; `_installed_apps(host) -> sorted [app]` from the units systemd knows.
  - D10.3 `data`: `declared_apps` (sorted names), `installed_apps` (sorted names), `installed_equal_repo` (the three template files, as today), `apps: {<app>: {broker_unit, runner_unit, drop_in_paths, broker_user_groups, sudo_rules, runner_path_active}}` for every app in the union of the two lists.
  - D10.4 `data`: `apps: {<app>: {"layout_problems": [...]}}`, and `containers`, `containers_mounting_app_state`, `containers_not_inspected` as today.
  - D10.7 `data`: `apps: {<app>: {journal_counts, note_counts, other_lines, broker_journal, runner_journal, journal_read, oldest_entry_read, first_entry, installed_since_last_pass}}`, and `known_secrets_checked`.
  - D10.8 `data`: `apps: {<app>: {"results": [...], "out_of_whitelist": n}}`.
  - D2.4 `oldest_entry`: `{"journal": t, "apps": {<app>: {"broker": t, "runner": t}}}`.
  - D4.6: `started_at`, `started_after_last_pass`, `files_newer_than_start`, `files_checked` carry one key `hermes-app-broker@<app>` per declared app.
- The module constants `APP`, `APP_USER`, `APP_RESULTS`, `_BROKER_LINE`, `JOURNAL_UNITS` and the app key in `SERVICE_FILES` are removed; nothing names a job.

- [ ] **Step 1: The fake box holds two jobs**

In the test file's shared fixture (`Base.setUp`), copy BOTH manifests from the repository into `<root>/opt/hermes-agent/registry/apps/`, and give the fake `systemctl list-units` this answer by default:

```python
            ("systemctl", "list-units"): (0, "".join(f"hermes-app-{k}@{a}.{s} loaded active running x\n"
                                                     for a in ("ads-audit", "ads-report")
                                                     for k, s in (("broker", "service"), ("runner", "path"))), ""),
```

The helper `_journal(self, broker=None, runner=None)` gains `app="ads-audit"` and builds its key from it. `_result(self, obj, name=None)` gains `app="ads-audit"` and writes under that app's `results/`.

- [ ] **Step 2: Write the failing tests**

```python
class TestEveryJob(Base):
    APPS = ["ads-audit", "ads-report"]

    def test_the_jobs_are_read_from_the_description_files_and_from_systemd(self):
        d = self._item("D10.3")["data"]
        self.assertEqual((d["declared_apps"], d["installed_apps"], sorted(d["apps"])), (self.APPS, self.APPS, self.APPS))
        for app in self.APPS:
            self.assertEqual(set(d["apps"][app]), {"broker_unit", "runner_unit", "drop_in_paths", "broker_user_groups",
                                                   "sudo_rules", "runner_path_active"})
        self.assertEqual(sorted(d["installed_equal_repo"]), sorted(CE.APP_UNITS))

    def test_a_job_installed_without_a_description_file_and_the_reverse_are_both_shown(self):
        os.unlink(os.path.join(self.root, "opt/hermes-agent/registry/apps/ads-report.json"))
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@ads-audit.service loaded active running x\n"
                                                        "hermes-app-broker@ghost.service loaded active running x\n", "")
        d = self._item("D10.3")["data"]
        self.assertEqual((d["declared_apps"], d["installed_apps"]), (["ads-audit"], ["ads-audit", "ghost"]))
        self.assertEqual(sorted(d["apps"]), ["ads-audit", "ghost"])            # the undeclared one is still measured

    def test_a_description_file_that_does_not_load_makes_the_job_items_could_not_check(self):
        open(os.path.join(self.root, "opt/hermes-agent/registry/apps/ads-report.json"), "w").write("{}")
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertEqual(self._item(iid)["status"], R.COULD_NOT_CHECK, iid)

    def test_a_unit_name_that_is_not_a_job_s_is_not_an_app(self):
        self.outputs[("systemctl", "list-units")] = (0, "hermes-app-broker@Bad..Name.service loaded active running x\n"
                                                        "hermes-app-runner@ads-audit.path loaded active waiting x\n", "")
        self.assertEqual(self._item("D10.3")["data"]["installed_apps"], ["ads-audit"])

    def test_each_job_s_journal_is_searched_and_counted_on_its_own(self):
        self._journal(app="ads-report", broker="hermes-app-broker[ads-report]: request=1 op=run client=x status=ok reason=-\n",
                      runner=_e(MESSAGE="done", _CMDLINE="tool --customer 1234567890"))
        d = self._item("D10.7")["data"]
        self.assertEqual(sorted(d["apps"]), self.APPS)
        self.assertEqual(d["apps"]["ads-report"]["journal_counts"], {"ok/-": 1})
        self.assertEqual(d["apps"]["ads-report"]["runner_journal"]["customer_id_lines"], 1)
        self.assertEqual(d["apps"]["ads-audit"]["runner_journal"]["customer_id_lines"], 0)
        self.assertNotIn("1234567890", json.dumps(d))

    def test_a_broker_line_of_another_job_in_a_job_s_journal_is_not_its_count(self):
        self._journal(app="ads-report", broker="hermes-app-broker[ads-audit]: request=1 op=run client=x status=ok reason=-\n")
        a = self._item("D10.7")["data"]["apps"]["ads-report"]
        self.assertEqual((a["journal_counts"], a["other_lines"]), ({}, 1))

    def test_a_job_whose_first_entry_is_after_the_last_pass_is_marked_installed_since(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-report")] = (0, _entry(1760500000), "")
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1759000000), "")
        with mock.patch.object(CE, "LAST_PASS_COLLECTED_AT", "2025-10-10T00:00:00Z"):
            d = self._item("D10.7")["data"]["apps"]
        self.assertEqual((d["ads-report"]["installed_since_last_pass"], d["ads-audit"]["installed_since_last_pass"]), (True, False))
        self.assertRegex(d["ads-report"]["first_entry"], r"^2025-10-1\dT")
        self.assertIsNone(self._item("D10.7")["data"]["apps"]["ads-report"]["installed_since_last_pass"])   # no flag given

    def test_each_job_s_results_are_judged_by_its_own_rule(self):
        report_ok = {"request_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "op": "run", "client": "acme-dental",
                     "status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00",
                     "steps": [{"name": "store", "rc": 0, "seconds": 0.1}],
                     "vault_path": "/var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md"}
        self._result(report_ok, app="ads-report")
        self._result(report_ok, app="ads-audit")                      # the same file in the audit's results is out of ITS rule
        d = self._item("D10.8")["data"]["apps"]
        self.assertEqual(d["ads-report"]["out_of_whitelist"], 0)
        self.assertGreaterEqual(d["ads-audit"]["out_of_whitelist"], 1)

    def test_the_layout_is_checked_per_job(self):
        d = self._item("D10.4")["data"]
        self.assertEqual(sorted(d["apps"]), self.APPS)
        self.assertIn("containers_mounting_app_state", d)

    def test_the_journal_reach_and_the_restart_items_name_every_job(self):
        b = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(sorted(b["D2.4"]["data"]["oldest_entry"]["apps"]), self.APPS)
        self.assertEqual(set(b["D2.4"]["data"]["oldest_entry"]["apps"]["ads-report"]), {"broker", "runner"})
        for key in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
            for app in self.APPS:
                self.assertIn(f"hermes-app-broker@{app}", b["D4.6"]["data"][key], key)

    def test_no_constant_names_a_job(self):
        src = open(os.path.join(HERE, "collect-review-evidence.py")).read()
        code = "\n".join(l.split("#", 1)[0] for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')))
        self.assertNotRegex(code, r'"ads-(audit|report)"')
        for name in ("APP", "APP_USER", "APP_RESULTS", "JOURNAL_UNITS", "_BROKER_LINE"):
            self.assertFalse(hasattr(CE, name), name)
```

Run → FAIL.

- [ ] **Step 3: Write the implementation**

```python
APPS_DIR = AGENT_DIR + "/registry/apps"
_APP_UNIT_RE = re.compile(r"hermes-app-(?:broker|runner)@([a-z][a-z0-9-]{0,31})\.(?:service|path)")


def _declared_apps(host):
    """{app: Manifest} for every job the box's checkout declares. A directory that cannot be read
    whole declares nothing this collector trusts: could-not-check."""
    try:
        return A.load_manifests(host.path(APPS_DIR))
    except (OSError, ValueError):
        raise CouldNotCheck("the jobs' description files could not all be loaded")


def _installed_apps(host):
    """The jobs systemd knows a broker or runner unit for, loaded or not: names only."""
    out = _ok(host, ["systemctl", "list-units", "--all", "--plain", "--no-legend", "--no-pager",
                     "hermes-app-broker@*", "hermes-app-runner@*"])
    found = set()
    for line in out.splitlines():
        m = _APP_UNIT_RE.fullmatch(line.split()[0]) if line.split() else None
        if m:
            found.add(m.group(1))
    return sorted(found)


def _app_names(host):
    return sorted(set(_declared_apps(host)) | set(_installed_apps(host)))
```

Then, item by item, with the shapes of "Interfaces":
- `d10_3`: the per-app dict is today's body with `APP` replaced by the loop variable and `"hermes-app-" + app` for the user; `installed_equal_repo` stays at the top level.
- `d10_4`: `check_app` per app (a `LayoutError` for one app is that app's `layout_problems: could-not-check`, not the whole item's); the container loop is unchanged.
- `d10_7`: a helper `_app_journal(host, ctx, app, secrets)` holding today's body with the unit names and the line prefix `"hermes-app-broker[" + app + "]: "` built from `app`; plus `first_entry = _oldest_entry_or_unknown(host, ("-u", "hermes-app-broker@" + app))` and `installed_since_last_pass`: `None` when `LAST_PASS_COLLECTED_AT` is `None`, could-not-check when `first_entry` is could-not-check, `True` when `first_entry` is `None` (the job never logged) or later than the last PASS, else `False`.
- `d10_8`: per app, with `A.result_in_whitelist(obj, manifests[app])`; an installed app with no description file gets `{"results": could-not-check, "out_of_whitelist": could-not-check}`.
- `d2_4`: `oldest_entry` as specified.
- `d4_6`: `services = {**SERVICE_FILES, **{"hermes-app-broker@" + a: ("hermes-app-broker@.service", "hermes-app-broker.py") for a in _declared_apps(host)}}` and use `services` where `SERVICE_FILES` was used; `SERVICE_FILES` keeps the two fixed services.
- Delete the five constants; `git grep -n '\bAPP\b\|APP_USER\|APP_RESULTS\|JOURNAL_UNITS\|_BROKER_LINE' infra/hermes-agent/bin/collect-review-evidence.py` prints nothing.

- [ ] **Step 4: Existing tests**

Every existing assertion on D10.3, D10.4, D10.7 or D10.8 data moves one level down, to `["apps"]["ads-audit"]`, and D2.4's `oldest_entry["broker"]`/`["runner"]` to `oldest_entry["apps"]["ads-audit"][...]`. Tests that count `journalctl -u` calls now see four (two jobs). The summary tool's tests that tie its constants to `CE.JOURNAL_UNITS` or `CE.SERVICE_FILES` are updated in Task 7: until then mark exactly those `@unittest.expectedFailure` with a comment naming Task 7. A failure that is not one of these mechanical moves: STOP and report.

- [ ] **Step 5: Run and commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/summarize-review-bundle.test.py
git commit -m "review: the collector finds the jobs itself and checks each one (D2.4, D4.6, D10.3, D10.4, D10.7, D10.8)"
```

---

### Task 6: the report store in the review (D4.1, D7.1) and the probe's figures line (D10.1)

**Files:**
- Modify: `bin/collect-review-evidence.py`, `bin/collect-review-evidence.test.py`

**Interfaces:**
- Produces: `GATEWAY_PROBE_PATHS` holds `/var/lib/hermes/report-archive`; D7.1 `data` gains `report_archive: {"parent": <dir row>, "rows": [{"status", "owner", "mode", "files": {"<owner> <group> <mode>": n}}], "containers_mounting": n, "containers_not_inspected": n}`; D10.1's `probe` carries `figures_services` (passed through from the probe's JSON).

- [ ] **Step 1: Write the failing tests**

- D4.1: the path list given to the gateway's `sh -c` holds `/var/lib/hermes/report-archive`.
- D7.1, with a fake tree `var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md`: `parent` is the directory's row; `rows` has one row with `status: active` and a `files` count keyed by owner, group and mode, and holds no client name; a second folder for a client the registry does not know shows `status: unregistered`.
- D7.1, mounts: with a fake `docker inspect` answer whose `Source` is `/var/lib/hermes/report-archive/acme-dental`, `/var/lib/hermes/report-archive` or `/var/lib/hermes`, `containers_mounting` is 1 each time; with `/var/lib/hermes/reports` it is 0; an inspect that fails counts in `containers_not_inspected`.
- D10.1: a probe JSON holding `figures_services` reaches the item's `probe` unchanged.

- [ ] **Step 2: Write the implementation**

- Add the path to `GATEWAY_PROBE_PATHS`.
- Generalise `_exposes_app_state(source)` into `_exposes(source, tree)` (the same three-way test for any tree) and keep `_exposes_app_state` as a one-line call of it; move D10.4's container loop into `_containers_mounting(host, tree) -> (containers, mounting, not_inspected)` and use it in D10.4 and D7.1.
- D7.1: `report_archive` built with `_dir_row`, `_client_rows` and the existing per-directory file-mode counter (the one `audit_logs.rows` uses).
- D10.1 already returns the probe's JSON; confirm with the test and change nothing if it passes.

- [ ] **Step 3: Run and commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "review: the report store is measured (D4.1 unseen by the gateway, D7.1 owner-only and unmounted)"
```

---

### Task 7: the summary tool follows the per-job shape

**Files:**
- Modify: `bin/summarize-review-bundle.py`, `bin/summarize-review-bundle.test.py`; `bin/make-review-board.py` and its test only if they read a changed key (search them for `D10.`, `broker`, `oldest_entry`).

**Interfaces:**
- Consumes: Task 5's and Task 6's shapes.
- Produces: the same closing list of lines, each now true only when it holds for EVERY job; one line added: `every job is declared and installed`.

- [ ] **Step 1: Write the failing tests**

Update `bundle()` to the new shapes with two jobs, then:
- the item lines print each job's values under its name (`ads-audit:` / `ads-report:`), and a job name that does not match `^[a-z][a-z0-9-]{0,31}$` prints as withheld;
- `every job is declared and installed` reads `ok` when the two lists are equal and non-empty, `LOOK` otherwise;
- the three refusals line, the no-leaks line, the one-`ok`-run line and the no-older-code line each read `LOOK` when ONE job fails them while the other passes, and name how many jobs (never which values);
- a job with `installed_since_last_pass: true` adds `(1 job installed since the last PASS: judged from its first entry)` to the journal-reach line;
- `report_archive` and `figures_services` are printed and are not counted as unknown keys;
- a bundle in the OLD shape (review #10's: no `apps` level) still prints without a traceback, its job items shown as `(older shape)`.

- [ ] **Step 2: Write the implementation**

A helper `per_app(fmt)` that formats `{app: value}` with app names checked by the pattern; `SERVICES` becomes the two fixed services and the start/file keys accept `hermes-app-broker@<app>` for any valid app name; `JOURNAL_LABELS` becomes `{"journal"}` plus the per-app level; the closing checks iterate `d["apps"].values()`. Remove the `@unittest.expectedFailure` marks Task 5 added.

- [ ] **Step 3: Run and commit**

```bash
git add infra/hermes-agent/bin/summarize-review-bundle.py infra/hermes-agent/bin/summarize-review-bundle.test.py
git commit -m "review: the summary tool judges every job"
```

---

### Task 8: checklist v1.21, the report template and the reviewer brief

**Files:**
- Modify: `deploy/security-review/CHECKLIST.md`, `REPORT-TEMPLATE.md`, `REVIEWER-BRIEF.md`, `bin/security-review-checklist.test.py`

- [ ] **Step 1: Write the failing tests** (`bin/security-review-checklist.test.py`)

- `test_the_version_is_1_20` → `test_the_version_is_1_21`.
- The D10.6 test states the committed block: two servers, six tools, the new hash (computed in the test with `mcp_config`, as it does today), and the title "exactly six tools". Remove the `expectedFailure` mark Task 4 may have added.
- A new test: the D10 area's text names no single job as "the" job: the D10.3, D10.4, D10.7 and D10.8 blocks each hold the words `each job` and `declared_apps` appears in D10.3.
- A new test: every key the collector emits for D10.3, D10.4, D10.7, D10.8 (per app, taken from a collection on the fake box, as the existing "names every field" tests do), for D7.1's `report_archive` and for D10.1's `figures_services` is named in its item.
- A new test: the D10.7 and D10.8 expected sets name `failed/store`.
- A new test: D10.7 holds the words `installed since the last PASS` and `first_entry`.
- The item count is still 38.

- [ ] **Step 2: The checklist**

- `version: 1.21`. Header note: `(v1.21: the review covers every chat-triggered job the box declares: D10.3, D10.4, D10.7 and D10.8 run once per job, D2.4 and D4.6 name every job's units, and D10.3 compares the jobs declared with the jobs installed. A second job, `ads-report` (figures only). The report store joins D4.1 and D7.1. D10.1 reports the services a figures run would start. D10.6: six tools.)`
- The D10 area's lead paragraph: the chain is described for a job `<app>` (gateway MCP client → broker `hermes-app-broker@<app>` → runner `hermes-app-runner@<app>` → the job's command); the declared credential map gains: `a figures run (`ads-report`) starts `ads-collector` and `ads-reader` only and opens no Anthropic credential`.
- D10.1 **expected**: `probe.figures_services` is exactly `["ads-collector", "ads-reader"]`; **pass rule**: any other list is a FAIL.
- D10.3: **claim** and **expected** rewritten for each job: `declared_apps` (the description files in the box's checkout) and `installed_apps` (the broker and runner units systemd knows) are equal and are the jobs the operator states; a job in one list only is a FAIL; under `apps.<app>` the values listed today, with `User: "hermes-app-<app>"` and `ReadWritePaths` exactly `/var/lib/hermes/spool/apps/<app> /var/lib/hermes/app-state/<app>`.
- D10.4, D10.8: "for each job" with the values under `apps.<app>`; D10.8: each job's results are judged by that job's own rule (its description file's `result`), and each job needs one `run`/`ok` row within 7 days; the expected step classes gain `store`.
- D10.7: per job; the three live refusals are needed for each job; the expected keys gain `failed/store`; the new-job rule: `A job whose `installed_since_last_pass` is `true` (its first journal entry is later than the last PASS's collection, or it never logged) is judged from `first_entry`: the report states the job's install date from the rollout record, the 30-day reach is not asked of it, and the three live refusals and the one `ok` run are still required. `null` (no `--last-pass-collected-at`) is CANNOT-VERIFY for that job's reach.`
- D2.4: `oldest_entry.apps.<app>` for every declared job. D4.6: one `hermes-app-broker@<app>` per declared job.
- D4.1: the paths list gains `/var/lib/hermes/report-archive` (expected `absent`).
- D7.1: `report_archive`: `parent` is `root`, `root`, `0o700`; every row `status: active`, `owner` root, `mode` `0o700`, every `files` key ending ` 0o600`; `containers_mounting` `0`; a `containers_not_inspected` above `0` is CANNOT-VERIFY; a `retired` or `unregistered` row is a FAIL (offboarding removes the folder).
- D10.6: title `Hermes may call exactly six tools`; the committed block is two servers; the hash is the new one.

- [ ] **Step 3: The template and the brief**

`REPORT-TEMPLATE.md`: the "Unit journals (D10.7)" line becomes one line per job; add `- **Jobs (D10.3):** `declared_apps` `<list>`, `installed_apps` `<list>`; installed since the last PASS: `<job, install date>` or none`. `REVIEWER-BRIEF.md`: where it lists what the reviewer receives for D10.6, say the committed block now holds two servers; where it lists the baselines, add the jobs line.

- [ ] **Step 4: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes. After the commit: `python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo rc=$?` → `rc=0` (1.20 → 1.21).

```bash
git add infra/hermes-agent/deploy/security-review infra/hermes-agent/bin/security-review-checklist.test.py
git commit -m "review: checklist v1.21, every job is reviewed; the report store; six tools"
```

---

### Task 9: the runbook

**Files:**
- Modify: `deploy/BRING-UP.md`, `README.md`

- [ ] **Step 1: "Add a chat-triggered job"**

Rename the section "Chat-triggered audits — part 2: the chat trigger" to `## Add a chat-triggered job (spec 2026-09-30 §3, §6; design 2026-10-13)`. Its lead says: every step is written for a job named `<job>`; set it once per window with `JOB=<job>` and the blocks use `$JOB`; the jobs are `ads-audit` and `ads-report`; a job is added with its off switch ON. Then rewrite each numbered step so that every `ads-audit` in a command becomes `$JOB` (`hermes-app-$JOB`, `hermes-app-broker@$JOB`, `/var/lib/hermes/app-state/$JOB/DISABLED`, `init-host-layout.py --app $JOB`, the guarded live-refusal blocks of step 11), keeping every expected output and stop condition. Each block that uses `$JOB` starts by refusing an empty or malformed value: `case "$JOB" in ads-audit|ads-report) ;; *) echo "STOP: set JOB first"; exit 1;; esac` (inside the block's subshell or `sh -c`, so the operator's shell is not closed).

Add these steps where they belong in the chapter's order:
- before the units are enabled: `sudo touch /var/lib/hermes/app-state/$JOB/DISABLED` and its check;
- for `ads-report` only, once: `sudo install -d -o root -g root -m 0700 /var/lib/hermes/report-archive && sudo stat -c '%U:%G %a' /var/lib/hermes/report-archive` → `root:root 700`; `sudo ln -s /opt/hermes-agent/deploy/show-report /usr/local/sbin/show-report` and its check;
- the chat settings step: the template now holds every job's server; after it, `hermes mcp list` shows one server per job with three tools each (two servers, six tools);
- after a pull that changes a description file or `bin/app_lib.py`: restart EVERY job's broker (`for j in ads-audit ads-report; do sudo systemctl restart hermes-app-broker@$j; done`) and re-create the gateway, because both hold the description files in memory;
- the first run of `ads-report`: `sudo run-client-audit <client> --figures --dry-run` (the plan shows `[store]` and no `[draft]`), then by hand without `--dry-run`, then the off switch off and one run by chat, then `sudo show-report <client> --latest`; state that a by-hand run does not count against the chat limits and that a figures run resets the client's working folders, so the step logs of a failed audit must be read first.

- [ ] **Step 2: The other places**

- Step 8 "Offboarding": both commands gain `/var/lib/hermes/report-archive/<client>`.
- The security review's step 2 pre-read loop: `for u in docker systemd-journald hermes-docker-proxy hermes-broker hermes-app-broker@ads-audit hermes-app-broker@ads-report; do`; "five lines" → "six lines".
- The review's steps that describe the trial's closing list: add the line `every job is declared and installed` and say that the refusal, leak, `ok`-run and older-code lines now need every job.
- Before each review: the three live refusals and one `ok` run are needed per job; the report's `ok` run costs no AI fee.
- "The leftover journal directory": add `Run the four blocks in one sitting. If anything else was done on the box between VPS 1 and VPS 3, start again at VPS 1: the removal checks the directory's counts and size, not that its content is what was searched.`
- `README.md`: the runbook pointer to the renamed chapter.

- [ ] **Step 3: Check the commands**

Every fenced block and inline command that changed is run through `sh -n` (syntax only) with `JOB=ads-report` set, from a scratch file. No command is run for real. `git grep -n 'ads-audit' infra/hermes-agent/deploy/BRING-UP.md` shows only: the list of job names, the pre-read loop, history notes, and the sections that are about the audit itself ("Ads audits on the box", "Chat-triggered audits — part 1"); list what remains in the report.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "runbook: add a chat-triggered job (one chapter for every job); the report store; offboarding"
```

---

## After the last task

- `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → every suite passes; `node scripts/run-all-tests.js` → all suites pass.
- `python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo rc=$?` → `rc=0`.
- No `@unittest.expectedFailure` added by this plan remains: `git grep -n "expectedFailure" infra/hermes-agent/bin | grep -i "task"` prints nothing.
- A scan of the diff for a ten-digit number, a 32-character hex string, an address or a key-shaped string outside test fixtures: none.
- No push. The operator gives the word.

## Not in this plan (the rollout's, on the operator's word)

The rehearsal of "Add a chat-triggered job" for both jobs in the stand-in; the trial collection through the `umask 077` subshell; `-q` on a unit that never logged; the leftover directory's search and removal; the adjustment of the private review-to-review comparison helper to the per-job shape.
