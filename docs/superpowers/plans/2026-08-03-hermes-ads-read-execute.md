# Hermes read-execute for `claude-google-ads` — Implementation Plan (Increment 3 / P5 Track B.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec authority:** `docs/superpowers/specs/2026-08-03-hermes-ads-read-execute-design.md` governs. Where this plan and the spec disagree, the spec wins — stop and reconcile.

**Goal:** Give Hermes a `read-execute` capability that runs allow-listed Google Ads *reporting* scripts under a read-only credential, producing a credential-scrubbed report on disk, with the live account and the `:ro` target both provably unmutated.

**Architecture:** A tested stdlib runner (`run-ads-report.py`) resolves a per-project allow-list from the registry and executes only listed reader scripts under a pinned build-time venv (`/opt/ads-venv`); `claude` never gets a shell. Credentials are read-only (platform backstop) and injected per-invocation via a host wrapper + `docker compose exec -e` (never in the gateway env). Output is scrubbed and persisted under `/opt/data`.

**Tech Stack:** Python 3 stdlib (runner + tests); POSIX sh (wrapper); Docker (build-time venv layer); the target's `google-ads`/`python-dotenv` SDK (in the venv only).

## Global Constraints

- **Stdlib-only** in `run-ads-report.py` — no third-party imports in the runner itself (it *invokes* the venv python for readers).
- **No changes to the `claude-google-ads` repo** — every artifact is Hermes-side.
- **Read-only credential is the mutation backstop; the allow-list is the second layer.** Mutators (`apply_negatives`, `add_campaign_negative`, `add_competitor_negatives`, `attach_audience`) are never on the allow-list.
- **`claude` never receives Bash/Edit/Write** in this flow; execution is the runner's.
- **Credentials never** in the gateway env, `env_file`, git, logs, reports, telemetry, or memory/brain. `.env.ga` is gitignored; `_scrub()` runs on all captured output; the runner **refuses** if any of the six `GOOGLE_ADS_*` vars is missing (so nothing falls through to the in-tree `.env`).
- **The credential guarantee** is the complete injected set + `load_dotenv(override=False)` — not the scratch cwd (which is defense-in-depth).
- **`:ro` project mount never written**; the runner writes only under `/opt/data`.
- Reader deps live in the pinned `/opt/ads-venv` from a **vendored** `ads-requirements.txt`; resync + rebuild deliberately on target dep churn.
- The six credential var names: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `GOOGLE_ADS_CUSTOMER_ID`.
- Pinned reader slice this increment: `test_connection`, `account_overview` (readers only).

---

## File Structure

- `infra/hermes-agent/ads-requirements.txt` — **create.** Vendored pinned reader deps.
- `infra/hermes-agent/Dockerfile` — **modify.** Add the `/opt/ads-venv` build layer (root, before `USER hermes`).
- `infra/hermes-agent/registry/projects.yaml` — **modify.** `claude_google_ads`: `scope: read-execute` + `read_execute` block.
- `infra/hermes-agent/bin/run-ads-report.py` — **create.** The runner (offline core in Task 3, execution in Task 4).
- `infra/hermes-agent/bin/run-ads-report.test.py` — **create.** Offline unit tests.
- `infra/hermes-agent/run-ads-report.sh` — **create.** Host wrapper (sources `.env.ga`, `exec -e` passthrough).
- `infra/hermes-agent/.env.ga.example` — **create.** Read-only credential template.
- `.gitignore` — **modify.** Add `infra/hermes-agent/.env.ga`.
- `infra/hermes-agent/skills/claude-code-operator/SKILL.md` — **modify.** Add the `read-execute` scope branch.
- `infra/hermes-agent/README.md` — **modify.** Read-execute section (setup, credential, usage, safety).

---

## Task 1: Build-time venv + vendored requirements

**Files:**
- Create: `infra/hermes-agent/ads-requirements.txt`
- Modify: `infra/hermes-agent/Dockerfile`

**Interfaces:**
- Produces: a `/opt/ads-venv/bin/python3` interpreter in the `hermes-agent-claude` image with `google.ads.googleads` and `dotenv` importable. Later tasks reference `/opt/ads-venv/bin/python3` as the registry `runner`.

- [ ] **Step 1: Vendor the pinned requirements**

Create `infra/hermes-agent/ads-requirements.txt`:

```
# Vendored + pinned from claude-google-ads/requirements.txt.
# This is OUR pin point (like the allow-list): resync DELIBERATELY when the
# target's deps change, then rebuild the image. Do not auto-track the target.
google-ads==31.1.0
google-auth-oauthlib==1.3.1
python-dotenv==1.2.1
```

- [ ] **Step 2: Add the venv build layer to the Dockerfile**

In `infra/hermes-agent/Dockerfile`, insert BEFORE the final `USER hermes` line (while still `USER root`):

```dockerfile
# Read-execute (Increment 3): a pinned, isolated venv carrying the target's Google
# Ads reader deps, so run-ads-report.py can execute reader scripts without pip or
# runtime network. Deps pinned from a vendored copy of the target's requirements
# (resync + rebuild on target churn). Built as root; world-readable so the hermes
# UID (10000) can execute it. Isolated from the Hermes base python.
COPY ads-requirements.txt /opt/ads-requirements.txt
RUN python3 -m venv /opt/ads-venv \
 && /opt/ads-venv/bin/pip install --no-cache-dir -r /opt/ads-requirements.txt \
 && /opt/ads-venv/bin/python3 -c "import google.ads.googleads, dotenv; print('ads-venv OK')"
```

- [ ] **Step 3: Build the image**

Run: `cd infra/hermes-agent && docker compose build hermes-agent`
Expected: build succeeds; the final `RUN` prints `ads-venv OK`.

- [ ] **Step 4: Verify the venv in a container**

Run: `cd infra/hermes-agent && docker compose run --rm --no-deps hermes-agent /opt/ads-venv/bin/python3 -c "import google.ads.googleads, dotenv; print('OK', google.ads.googleads.__name__)"`
Expected: prints `OK google.ads.googleads` (exit 0). Confirms the hermes UID can execute the venv interpreter and import the deps.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/ads-requirements.txt infra/hermes-agent/Dockerfile
git commit -m "feat(hermes): pinned build-time venv for Google Ads readers (Inc 3 Task 1)"
```

---

## Task 2: Verification gate (controller-run, empirical — decision point)

> **This task is controller-run, not TDD.** It is the empirical gate from spec §7. It requires the operator to have provisioned the read-only credential (spec §9) into `infra/hermes-agent/.env.ga` first. NO runner code is written here — probe with the venv python + `docker compose exec -e` directly. Record every result in the ledger. If a gate item fails, STOP and escalate; do not proceed to Task 3.

**Files:** none created; produces evidence recorded in the ledger.

- [ ] **Step 1: Confirm the prerequisite is in place**

Confirm `infra/hermes-agent/.env.ga` exists with all six vars, the refresh token belongs to a **read-only** Google Ads user, and `.env.ga` is gitignored (Task 3 adds the ignore rule; until then, DO NOT `git add` it — verify with `git status --porcelain infra/hermes-agent/.env.ga` returning nothing staged).

- [ ] **Step 2: G4 positive control — a reader runs read-only end-to-end**

Inject the credential and run the simplest reader via the venv python:

```bash
cd infra/hermes-agent
set -a; . ./.env.ga; set +a
docker compose exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -T hermes-agent /opt/ads-venv/bin/python3 /projects/claude_google_ads/code/test_connection.py
```
Expected: real campaign rows / a successful connection message (exit 0). This is the **positive control** — the credential can READ.

- [ ] **Step 3: G1 — a mutate is refused SERVER-SIDE (permission, not config)**

Run a minimal `validate_only` mutate under the same credential (a one-off inline probe — a campaign-budget update with `validate_only=True`, or the smallest available mutate). Capture the exact error.
Expected: `USER_PERMISSION_DENIED` / "not permitted"-class authorization error — proving the READ-ONLY user cannot mutate. **Discriminator (Inc-2 lesson):** it must be a *permission/authorization* error, NOT `AuthenticationError`, a missing-field/config error, or a network error. If it is a config/auth error, the gate is INCONCLUSIVE — fix the probe, do not record a pass. Because Step 2 already proved the same credential can read, a permission-class refusal here is unambiguous.

- [ ] **Step 4: G3 — injection dominates the in-tree `.env`**

Inject a customer id that DIFFERS from the in-tree `.env` value and run a one-liner under the venv that mimics the readers' loader:

```bash
docker compose exec -e GOOGLE_ADS_CUSTOMER_ID=1234567890 -T hermes-agent \
  /opt/ads-venv/bin/python3 -c \
  "import os; from dotenv import load_dotenv; os.chdir('/projects/claude_google_ads/code'); load_dotenv(); print(os.getenv('GOOGLE_ADS_CUSTOMER_ID'))"
```
Expected: prints `1234567890` (the injected value), NOT the in-tree `.env` value — proving `override=False` keeps our injected value even when `find_dotenv()` locates the in-tree file. (Use a throwaway id; this makes no API call.)

- [ ] **Step 5: G2 — map the `.env` exposure residual**

Record whether the in-tree `.env` is readable inside the container:
`docker compose exec -T hermes-agent sh -lc 'test -r /projects/claude_google_ads/.env && echo READABLE || echo not-readable'`
Note the result in the ledger against spec §10 (the decision on the residual comes at the final review).

- [ ] **Step 6: G5 — credential scan is clean**

Grep the six credential VALUES across `docker compose logs hermes-agent` and `infra/hermes-agent/data/logs` (if present). Expected: no value appears. Record clean.

- [ ] **Step 7: Record the gate outcome in the ledger**

Append a GATE PASSED/FAILED line with each of G1–G5 and the exact evidence (the mutate error class for G1, the injected-value echo for G3, the `.env` readability for G2). Only a full pass authorizes Task 3.

---

## Task 3: Registry `read-execute` config + runner offline core + wrapper + templates

**Files:**
- Modify: `infra/hermes-agent/registry/projects.yaml`
- Create: `infra/hermes-agent/bin/run-ads-report.py`
- Create: `infra/hermes-agent/bin/run-ads-report.test.py`
- Create: `infra/hermes-agent/run-ads-report.sh`
- Create: `infra/hermes-agent/.env.ga.example`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the registry `read_execute` block (this task defines it).
- Produces: `read_workdir(path, project) -> str`; `read_read_execute(path, project) -> {"runner","script_dir","allow":[...]}`; `resolve_report(cfg, report) -> report`; `build_plan(project, report) -> {"workdir","runner","script","report","project"}`; `_scrub(text, secrets) -> str`. `run_report` is added in Task 4 (referenced by `main`, guarded so `--dry-run` never calls it).

- [ ] **Step 1: Add the `read-execute` config to the registry**

In `infra/hermes-agent/registry/projects.yaml`, replace the `claude_google_ads` `scope: read` line and append the block so the entry reads:

```yaml
  claude_google_ads:
    workdir: /projects/claude_google_ads
    scope: read-execute            # NEW tier: run allow-listed reader scripts only (Inc 3)
    default_model: claude-haiku-4-5
    description: >
      Google Ads API integration for the DentalEdge Solutions MCC (Python,
      google-ads SDK). read-execute: Hermes may run ALLOW-LISTED reporting
      scripts under a READ-ONLY credential; mutation is refused server-side.
      Credentials are injected per-invocation (never mounted, never in the
      gateway env). READERS ONLY — mutators are absent from the allow-list.
    read_execute:
      runner: /opt/ads-venv/bin/python3   # pinned build-time venv (Task 1), NOT base python
      script_dir: code             # relative to workdir
      allow:                       # EXACT basenames; fail-closed; READERS ONLY
        - test_connection
        - account_overview
```

- [ ] **Step 2: Write the failing offline tests**

Create `infra/hermes-agent/bin/run-ads-report.test.py`:

```python
import os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "run-ads-report.py")
mod = {}
with open(SCRIPT) as f:
    exec(compile(f.read(), SCRIPT, "exec"), mod)  # import functions without running main

REG = ("version: 1\nprojects:\n"
       "  claude_google_ads:\n"
       "    workdir: /projects/claude_google_ads\n"
       "    scope: read-execute\n"
       "    read_execute:\n"
       "      runner: /opt/ads-venv/bin/python3\n"
       "      script_dir: code\n"
       "      allow:\n"
       "        - test_connection\n"
       "        - account_overview\n"
       "  other:\n"
       "    workdir: /projects/other\n"
       "    scope: read\n")


def _reg(text=REG):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    f.write(text); f.close(); return f.name


class TestParse(unittest.TestCase):
    def test_read_workdir(self):
        p = _reg()
        self.assertEqual(mod["read_workdir"](p, "claude_google_ads"), "/projects/claude_google_ads")
        os.unlink(p)

    def test_read_read_execute(self):
        p = _reg()
        cfg = mod["read_read_execute"](p, "claude_google_ads")
        self.assertEqual(cfg["runner"], "/opt/ads-venv/bin/python3")
        self.assertEqual(cfg["script_dir"], "code")
        self.assertEqual(cfg["allow"], ["test_connection", "account_overview"])
        os.unlink(p)

    def test_missing_read_execute_rejected(self):
        p = _reg()
        with self.assertRaises(SystemExit):
            mod["read_read_execute"](p, "other")
        os.unlink(p)

    def test_sibling_after_allow_does_not_bleed(self):
        # A sibling scalar after the read_execute block must not be swallowed as allow items.
        text = REG + "    default_model: claude-haiku-4-5\n"
        p = _reg(text)
        cfg = mod["read_read_execute"](p, "claude_google_ads")
        self.assertEqual(cfg["allow"], ["test_connection", "account_overview"])
        self.assertNotIn("claude-haiku-4-5", cfg["allow"])
        os.unlink(p)


class TestAllowList(unittest.TestCase):
    CFG = {"runner": "/opt/ads-venv/bin/python3", "script_dir": "code",
           "allow": ["test_connection", "account_overview"]}

    def test_allowed(self):
        self.assertEqual(mod["resolve_report"](self.CFG, "account_overview"), "account_overview")

    def test_not_in_allowlist_rejected(self):
        with self.assertRaises(SystemExit):
            mod["resolve_report"](self.CFG, "apply_negatives")   # a mutator — must be refused

    def test_path_separator_rejected(self):
        with self.assertRaises(SystemExit):
            mod["resolve_report"](self.CFG, "../account_overview")


class TestScrub(unittest.TestCase):
    def test_scrub_replaces_all_secrets(self):
        out = mod["_scrub"]("token=SEKRET id=999 refresh=RRR", ["SEKRET", "RRR", ""])
        self.assertNotIn("SEKRET", out)
        self.assertNotIn("RRR", out)
        self.assertIn("id=999", out)


class TestDryRun(unittest.TestCase):
    def test_dry_run_no_exec_no_creds(self):
        p = _reg()
        env = {**os.environ, "ADS_REGISTRY": p, "REPORTS_DIR": "/tmp/r"}
        for v in mod["CRED_VARS"]:
            env.pop(v, None)                       # dry-run must not need creds
        r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_google_ads",
                            "--report", "account_overview", "--dry-run"],
                           capture_output=True, text=True, env=env)
        os.unlink(p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/opt/ads-venv/bin/python3", r.stdout)
        self.assertIn("code/account_overview.py", r.stdout)
        self.assertIn("/tmp/r/claude_google_ads/", r.stdout)

    def test_dry_run_rejects_disallowed_report(self):
        p = _reg()
        env = {**os.environ, "ADS_REGISTRY": p}
        r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_google_ads",
                            "--report", "apply_negatives", "--dry-run"],
                           capture_output=True, text=True, env=env)
        os.unlink(p)
        self.assertNotEqual(r.returncode, 0)       # mutator refused even in dry-run


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd infra/hermes-agent/bin && python3 run-ads-report.test.py`
Expected: FAIL (module `run-ads-report.py` does not exist yet).

- [ ] **Step 4: Write the offline core**

Create `infra/hermes-agent/bin/run-ads-report.py`:

```python
#!/usr/bin/env python3
"""Run an allow-listed READ-ONLY Google Ads reporting script for a registered project.

Operator-invoked (credentials injected per-invocation by run-ads-report.sh via
`docker compose exec -e`). Executes ONLY scripts named in the project's
read_execute allow-list, under the pinned /opt/ads-venv interpreter, and scrubs
all six GOOGLE_ADS_* credential values from captured output before persisting.
STDLIB ONLY. Never writes the :ro project mount; writes only under /opt/data.
See docs/superpowers/specs/2026-08-03-hermes-ads-read-execute-design.md
"""
import argparse, datetime, os, shutil, subprocess, sys, tempfile

DEFAULT_REGISTRY = "/opt/registry/projects.yaml"
DEFAULT_REPORTS = "/opt/data/reports"
CRED_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
             "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")


def registry_path():
    return os.environ.get("ADS_REGISTRY") or (
        DEFAULT_REGISTRY if os.path.exists(DEFAULT_REGISTRY)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registry", "projects.yaml"))


def reports_dir():
    return os.environ.get("REPORTS_DIR", DEFAULT_REPORTS)


def read_workdir(path, project):
    """Stdlib line-parser for projects.<project>.workdir."""
    cur = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if indent == 2 and stripped.endswith(":"):
                cur = stripped[:-1]
            elif indent == 4 and cur == project and stripped.startswith("workdir:"):
                return stripped.split(":", 1)[1].strip()
    raise SystemExit(f"run-ads-report: no workdir for project {project!r}")


def read_read_execute(path, project):
    """Stdlib line-parser for projects.<project>.read_execute {runner, script_dir, allow[]}.

    Scope discipline mirrors the Inc-2 review fix: ANY sibling/shallower line closes
    the read_execute scope, so a later sibling key cannot bleed into `allow`.
    """
    cur = None
    in_re = False
    in_allow = False
    got = {"allow": []}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if indent == 2 and stripped.endswith(":"):        # a project name
                cur = stripped[:-1]; in_re = False; in_allow = False
            elif indent == 4 and cur == project and stripped == "read_execute:":
                in_re = True; in_allow = False
            elif indent <= 4:                                  # any sibling/shallower closes scope
                in_re = False; in_allow = False
            elif indent == 6 and in_re and cur == project:
                if stripped == "allow:":
                    in_allow = True
                else:
                    in_allow = False
                    k, _, v = stripped.partition(":")
                    got[k.strip()] = v.strip()
            elif indent == 8 and in_allow and in_re and cur == project and stripped.startswith("- "):
                got["allow"].append(stripped[2:].strip())
    if not got.get("runner") or not got.get("script_dir") or not got["allow"]:
        raise SystemExit(f"run-ads-report: no read_execute(runner,script_dir,allow) for project {project!r}")
    return {"runner": got["runner"], "script_dir": got["script_dir"], "allow": got["allow"]}


def resolve_report(cfg, report):
    if os.path.basename(report) != report:                    # reject path separators / traversal
        raise SystemExit(f"run-ads-report: --report must be a bare name, got {report!r}")
    if report not in cfg["allow"]:
        raise SystemExit(f"run-ads-report: report {report!r} not in read_execute allow-list "
                         f"{cfg['allow']} — readers only; mutators are never allow-listed")
    return report


def _scrub(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def build_plan(project, report):
    workdir = read_workdir(registry_path(), project)
    cfg = read_read_execute(registry_path(), project)
    resolve_report(cfg, report)
    script = os.path.join(workdir, cfg["script_dir"], report + ".py")
    return {"workdir": workdir, "runner": cfg["runner"], "script": script,
            "report": report, "project": project}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    plan = build_plan(args.project, args.report)
    if args.dry_run:
        print(f"project: {plan['project']}")
        print(f"runner:  {plan['runner']}")
        print(f"script:  {plan['script']}")
        print(f"report:  {plan['report']}")
        print(f"writes:  {os.path.join(reports_dir(), plan['project'])}/<ts>-{plan['report']}.md")
        return 0
    return run_report(plan, datetime.datetime.now(datetime.timezone.utc))  # noqa: F821 (Task 4)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd infra/hermes-agent/bin && python3 run-ads-report.test.py`
Expected: PASS (all TestParse/TestAllowList/TestScrub/TestDryRun cases). `run_report` is undefined but `--dry-run` returns before calling it, so dry-run tests pass.

- [ ] **Step 6: Create the host wrapper**

Create `infra/hermes-agent/run-ads-report.sh`:

```sh
#!/bin/sh
# Host-side wrapper: inject the READ-ONLY Google Ads credential per-invocation and
# run the report inside the container. The credential lives in the gitignored
# .env.ga (NOT loaded by docker-compose env_file, NOT in the gateway env) — sourced
# here and passed via `docker compose exec -e`, so it reaches ONLY this exec'd
# process, never the gateway/agent env. Mirrors open-proposal-pr.sh (Increment 2).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env.ga" ]; then
  echo "run-ads-report: $here/.env.ga not found — copy .env.ga.example and fill in the READ-ONLY credential" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; . "$here/.env.ga"; set +a
exec docker compose -f "$here/docker-compose.yml" exec \
  -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
  -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID \
  -T hermes-agent python3 /opt/cc-bin/run-ads-report.py "$@"
```

Run: `chmod +x infra/hermes-agent/run-ads-report.sh && sh -n infra/hermes-agent/run-ads-report.sh`
Expected: no output (syntax OK).

- [ ] **Step 7: Create the credential template**

Create `infra/hermes-agent/.env.ga.example`:

```
# READ-ONLY Google Ads credential for Hermes read-execute (Increment 3).
# Copy to .env.ga and fill in. GITIGNORED. NOT loaded by docker-compose env_file —
# it is sourced by run-ads-report.sh and injected per-invocation via `exec -e`, so
# it never enters the gateway/agent env. Customer IDs WITHOUT dashes.
#
# CRITICAL: the refresh token MUST belong to a Google account with READ-ONLY access
# to the MCC/client, so Google refuses every mutate server-side (spec §9). The
# developer token is the same MCC-scoped token as the project's .env.
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
GOOGLE_ADS_LOGIN_CUSTOMER_ID=
GOOGLE_ADS_CUSTOMER_ID=
```

- [ ] **Step 8: Gitignore the real credential file**

In `.gitignore`, add under the existing Hermes ignores:

```
infra/hermes-agent/.env.ga
```

Run: `git check-ignore infra/hermes-agent/.env.ga`
Expected: prints the path (confirms it is ignored). Also confirm `.env.ga.example` is NOT ignored: `git check-ignore infra/hermes-agent/.env.ga.example || echo "example tracked OK"`.

- [ ] **Step 9: Commit**

```bash
git add infra/hermes-agent/registry/projects.yaml infra/hermes-agent/bin/run-ads-report.py \
        infra/hermes-agent/bin/run-ads-report.test.py infra/hermes-agent/run-ads-report.sh \
        infra/hermes-agent/.env.ga.example .gitignore
git commit -m "feat(hermes): read-execute registry config + runner offline core + wrapper (Inc 3 Task 3)"
```

---

## Task 4: Execution engine (`run_report`) + fake-reader tests

**Files:**
- Modify: `infra/hermes-agent/bin/run-ads-report.py` (add `run_report`)
- Modify: `infra/hermes-agent/bin/run-ads-report.test.py` (add execution tests)

**Interfaces:**
- Consumes: `build_plan` output; `CRED_VARS`; `_scrub`; `reports_dir()`.
- Produces: `run_report(plan, now) -> int` (0 on success), printing the persisted report path; refuses on any missing credential var; scrubs all six values from captured stdout/stderr before persist.

- [ ] **Step 1: Write the failing execution tests**

Append to `infra/hermes-agent/bin/run-ads-report.test.py` (before the `if __name__` line):

```python
import datetime


class TestRunReport(unittest.TestCase):
    def _workdir_with_fake_reader(self, d, body):
        code = os.path.join(d, "code"); os.makedirs(code)
        with open(os.path.join(code, "fake_reader.py"), "w") as f:
            f.write(body)
        return d

    def _env_with_creds(self, extra):
        env = {**os.environ, **extra}
        for i, v in enumerate(mod["CRED_VARS"]):
            env[v] = env.get(v) or f"SECRET{i}"
        return env

    def test_run_report_scrubs_and_persists(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            # fake reader echoes the injected developer token (a "secret") + a benign line
            self._workdir_with_fake_reader(
                d, "import os\nprint('token=' + os.environ['GOOGLE_ADS_DEVELOPER_TOKEN'])\nprint('campaigns=3')\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = self._env_with_creds({"GOOGLE_ADS_DEVELOPER_TOKEN": "TOPSECRETTOKEN",
                                        "REPORTS_DIR": out})
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                rc = mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)
            self.assertEqual(rc, 0)
            report_dir = os.path.join(out, "claude_google_ads")
            files = os.listdir(report_dir)
            self.assertEqual(len(files), 1)
            content = open(os.path.join(report_dir, files[0])).read()
            self.assertNotIn("TOPSECRETTOKEN", content)     # secret scrubbed
            self.assertIn("***", content)
            self.assertIn("campaigns=3", content)           # benign output preserved

    def test_run_report_refuses_missing_cred(self):
        with tempfile.TemporaryDirectory() as d:
            self._workdir_with_fake_reader(d, "print('hi')\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = {k: v for k, v in os.environ.items() if k not in mod["CRED_VARS"]}
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                with self.assertRaises(SystemExit):
                    mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)

    def test_run_report_nonzero_reader_raises(self):
        with tempfile.TemporaryDirectory() as d:
            self._workdir_with_fake_reader(d, "import sys\nsys.exit(2)\n")
            plan = {"workdir": d, "runner": sys.executable,
                    "script": os.path.join(d, "code", "fake_reader.py"),
                    "report": "fake_reader", "project": "claude_google_ads"}
            env = self._env_with_creds({})
            old = dict(os.environ); os.environ.clear(); os.environ.update(env)
            try:
                with self.assertRaises(SystemExit):
                    mod["run_report"](plan, datetime.datetime(2026, 8, 3, 12, 0, 0))
            finally:
                os.environ.clear(); os.environ.update(old)
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd infra/hermes-agent/bin && python3 run-ads-report.test.py`
Expected: FAIL on `TestRunReport` (`run_report` is not defined / `KeyError`).

- [ ] **Step 3: Implement `run_report`**

In `infra/hermes-agent/bin/run-ads-report.py`, add ABOVE `def main`:

```python
def run_report(plan, now):
    missing = [v for v in CRED_VARS if not os.environ.get(v)]
    if missing:
        raise SystemExit("run-ads-report: missing injected credential vars: "
                         f"{', '.join(missing)} (operator-invoked via run-ads-report.sh only). "
                         "The complete set is required so nothing falls through to the in-tree .env.")
    secrets = [os.environ[v] for v in CRED_VARS]
    if not os.path.isfile(plan["runner"]):
        raise SystemExit(f"run-ads-report: runner interpreter not found: {plan['runner']} "
                         "(build the /opt/ads-venv image layer — Task 1)")
    if not os.path.isfile(plan["script"]):
        raise SystemExit(f"run-ads-report: reader not found: {plan['script']}")
    scratch = tempfile.mkdtemp(prefix="ads-report-")   # defense-in-depth cwd; guarantee is override=False
    try:
        proc = subprocess.run([plan["runner"], plan["script"]],
                              cwd=scratch, env=dict(os.environ),
                              capture_output=True, text=True)
        out = _scrub(proc.stdout, secrets)
        err = _scrub(proc.stderr, secrets)
        if proc.returncode != 0:
            raise SystemExit(f"run-ads-report: reader {plan['report']} failed "
                             f"(exit {proc.returncode}):\n{err}")
        dest_dir = os.path.join(reports_dir(), plan["project"])
        os.makedirs(dest_dir, exist_ok=True)
        ts = now.strftime("%Y-%m-%d_%H-%M-%S")
        dest = os.path.join(dest_dir, f"{ts}-{plan['report']}.md")
        header = (f"# Google Ads read report — {plan['project']} — {plan['report']}\n\n"
                  f"_Generated {ts} UTC by Hermes read-execute (read-only credential). "
                  f"Credential values scrubbed._\n\n")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(header + "```\n" + out + "\n```\n")
        print(dest)
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)   # cleanup on success AND failure
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 run-ads-report.test.py`
Expected: PASS (all Task-3 + Task-4 cases). Also confirm no third-party import crept in: `python3 -c "import ast; t=ast.parse(open('run-ads-report.py').read()); print('stdlib-only OK')"` and eyeball the import line.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/run-ads-report.py infra/hermes-agent/bin/run-ads-report.test.py
git commit -m "feat(hermes): run_report execution engine — scrub + persist + fail-closed creds (Inc 3 Task 4)"
```

---

## Task 5: Operator `read-execute` branch + README + live e2e + proofs

**Files:**
- Modify: `infra/hermes-agent/skills/claude-code-operator/SKILL.md`
- Modify: `infra/hermes-agent/README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–4 + the passed Task-2 gate.

- [ ] **Step 1: Add the `read-execute` scope branch to the operator skill**

In `infra/hermes-agent/skills/claude-code-operator/SKILL.md`, in the "Enforce scope" section, add after the `scope: read` bullet and before `scope: write`:

```markdown
- `scope: read-execute` → the project may run ALLOW-LISTED reporting scripts via
  the runner, NOT via `claude`. You (the operator) do **not** get Bash for this:
  invoke the host wrapper `run-ads-report.sh --project <name> --report <name>`,
  which runs `run-ads-report.py` against the registry `read_execute` allow-list
  under a READ-ONLY credential. Never run a script that is not on the allow-list;
  never pass write tools to `claude`. `claude` may only READ the persisted report
  afterward (`--permission-mode plan --allowedTools 'Read,Grep,Glob'`). If asked to
  change the account or run a mutator, REFUSE — mutation is not a capability here.
```

- [ ] **Step 2: Deploy the operator skill change to the container path**

The skill is mounted `:ro` from source, so no redeploy is needed beyond the file edit; confirm the container sees it:
Run: `cd infra/hermes-agent && docker compose exec -T hermes-agent sh -lc 'grep -c read-execute /opt/data/skills/claude-code-operator/SKILL.md'`
Expected: `1` (or greater).

- [ ] **Step 3: Live end-to-end — produce a real report**

With `.env.ga` in place (Task 2 prerequisite), run:
`cd infra/hermes-agent && ./run-ads-report.sh --project claude_google_ads --report account_overview`
Expected: prints a path like `/opt/data/reports/claude_google_ads/<ts>-account_overview.md`; exit 0.

- [ ] **Step 4: Prove the report + confinement**

- Report content: `docker compose exec -T hermes-agent sh -lc 'cat <printed path>'` — real Ads data, readable.
- **Credential scan clean:** grep each of the six credential VALUES across the report, `docker compose logs hermes-agent`, and `infra/hermes-agent/data/logs` — none appear.
- **`:ro` mount unchanged:** `cd /Users/ericksicard/Projects/claude-google-ads && git status --porcelain` — byte-identical (empty or unchanged from before).
- **Allow-list fail-closed (live):** `./run-ads-report.sh --project claude_google_ads --report apply_negatives` → non-zero, "not in read_execute allow-list". (No credential is even used for the API — the refusal is pre-exec.)
- **No writes outside `/opt/data`:** the only new file is under `/opt/data/reports/`.

- [ ] **Step 5: Document in the README**

In `infra/hermes-agent/README.md`, add a "Read-execute — Google Ads reporting (Increment 3)" section covering: the read-only-credential prerequisite (§9) and how to mint it; `.env.ga` setup (copy from `.env.ga.example`, gitignored, never in the gateway env); the `run-ads-report.sh --project … --report …` usage; the allow-list location (registry `read_execute`) and readers-only rule; the safety model (platform read-only backstop + allow-list + no shell for `claude` + scrub + `:ro`); and the resync-the-venv note when the target's deps change.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/skills/claude-code-operator/SKILL.md infra/hermes-agent/README.md
git commit -m "feat(hermes): operator read-execute branch + README + live e2e proofs (Inc 3 Task 5)"
```

---

## Final whole-branch review

After Task 5, dispatch the final whole-branch review (superpowers:requesting-code-review) on a capable model over the increment's commit range. Focus: the runner's allow-list fail-closed logic and `read_read_execute` scope discipline; the credential path (never in gateway env; `_scrub` covers stdout AND stderr; missing-var refusal enforces the complete-set guarantee); the wrapper's `exec -e` passthrough; the Dockerfile venv isolation; the `:ro` and no-mutation proofs. Resolve the spec §10 `.env`-exposure residual decision here (accept / exclude-from-mount / push target to move `.env` out of tree), and confirm the mutators are absent from every allow-list.

---

## Self-Review (completed during planning)

- **Spec coverage:** venv/exec env (Task 1 + spec §5.6); verification gate G1–G5 (Task 2 + §7); `read-execute` scope + allow-list + runner offline core + wrapper + `.env.ga` + gitignore (Task 3 + §5.1–5.3); `run_report` scrub/persist/fail-closed (Task 4 + §5.2); operator branch + README + live proofs + acceptance (Task 5 + §8). Prerequisite (§9) gated into Task 2. Residual (§10) routed to the final review.
- **Placeholder scan:** none — every code/step is concrete. The one artifact (the `if False` ternary in the dry-run `script:` print) is called out with the plain replacement immediately below it; implementer uses `print(f"script:  {plan['script']}")`.
- **Type consistency:** `build_plan` returns `{workdir,runner,script,report,project}`; `run_report(plan, now)` consumes exactly those keys; `CRED_VARS`, `_scrub(text, secrets)`, `reports_dir()`, `read_read_execute` shape `{runner,script_dir,allow}` are used identically across Tasks 3–4 and the tests.
