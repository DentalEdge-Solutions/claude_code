# Ads audits on the box — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sudo run-client-audit <client>` produces a client's Google Ads trend-audit DRAFT on the box, from start to finish, written into that client's vault.

**Architecture:** A Python orchestrator, `bin/run-client-audit.py`, does the pre-checks, then drives the laptop pipeline's steps in box form:
- the collectors run in a one-shot `ads-collector` container, and the readers in a one-shot `ads-reader` container. Both come from the existing image. The read credential is passed per run with `-e` (never mounted), and the client's `audit-data` is mounted rw for collection and ro for the readers;
- the host runs the metrics snapshot;
- the Opus draft runs by `exec` in the gateway, exactly as `run-trend-audit.sh` does;
- `vault-write.py` writes the vault, and a cross-client check runs last.

Small, pure helpers live in `bin/client_audit_lib.py`, so both files stay testable on a faked box.

**Tech Stack:** Python 3 stdlib only (like every `bin/` tool), POSIX sh for the wrapper, Docker Compose (the `tools` profile), GitHub Actions (the existing root "Bind agreement" job).

**Spec:** `docs/superpowers/specs/2026-09-29-ads-audits-on-the-box-design.md`

## Global Constraints

- Python stdlib only in `infra/hermes-agent/bin/`; tests are `bin/<name>.test.py` (unittest), discovered by `bin/run-bin-tests.sh`. Run it after every task: `infra/hermes-agent/bin/run-bin-tests.sh` must end `N/N suites passed`.
- Credential path: `/etc/hermes/.env.ga`, `root:root 0400`, declaring `GOOGLE_ADS_CREDENTIAL_ROLE=read`. It is never mounted into any container; values reach containers only as `-e NAME` (value from the process env, never in argv).
- Raw data: `/var/lib/hermes/audit-data/<client>/`, `0700`, uid 10000, emptied at the start of every run.
- Box paths: `AGENT_DIR=/opt/hermes-agent` (a symlink to the checkout's `infra/hermes-agent`), `GOV=/var/lib/hermes/governance`, registry `GOV/registry/clients.json`, app dir `/opt/projects/claude-google-ads`, gateway `.env` `/opt/hermes-agent/.env`.
- Eligible client: registered, and `status == "active"`. `mutation_target` is ignored (read-only path).
- Never print, log or commit a customer id or a credential value. Anything shown on screen goes through `review_lib.Redactor`. Step stderr and stdout go to `audit-data/<client>/logs/<step>.{stdout,stderr}` (`0600`).
- Stop at the first failed step. Any `*.ERROR.txt` in `audit-data/<client>/` blocks the draft.
- One audit at a time: `fcntl.flock` on `/run/lock/hermes-client-audit.lock`.
- Timeouts (seconds): collect 900 per collector, snapshot 120, reader 300 per reader, draft 1200, vault-write 120.
- The analyst prompt and model (`claude-opus-4-8`, `--permission-mode plan`, `--allowedTools "Read,Grep,Glob"`) are copied verbatim from `run-trend-audit.sh`.
- Any change to `CHECKLIST.md` raises its `version:` (CI enforces it). This plan takes it to 1.8.
- The laptop's `run-trend-audit.sh`, `collect-audit-data.sh` and `run-audit-bundle.sh` are **not** modified.

## Review Focus

1. **A malicious or typo'd slug** (`../x`, `A B`, empty) must be refused before any path is built. `vault_lib.validate_slug` does this; Task 3 pins it with a test.
2. **A customer id stored dashed in the registry** (`123-456-7890`) must reach the containers as digits only, and be redacted in both forms. Task 3 has the test.
3. **A credential file with CRLF endings, quoted values or an `export ` prefix** must parse like the shell parser in `run-ads-report.sh`. Task 3 has the test.
4. **A second `run-client-audit` while one is running** must refuse at once (rc 3, "another audit is running") without touching the first run's data. Task 3 (lock) and Task 4 (entry) have tests.
5. **Collectors that exit 0 but write no JSON** (an account with nothing to report, or a silently broken collector) must not produce a draft. Task 4 blocks when `audit-data` holds no `*.json` after collection.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/registry/projects.yaml` | modify | `claude_google_ads.package.include` gains the 4 collectors + 6 SOP docs; the pin is re-set |
| `infra/hermes-agent/bin/package_lib.py` | modify | `refuse_client_ids(files)`: no packaged `.md` may hold a customer-id-shaped number |
| `infra/hermes-agent/bin/build-app-package.py` | modify | calls `refuse_client_ids` before writing |
| `infra/hermes-agent/docker-compose.yml` | modify | new `ads-collector` and `ads-reader` services (`tools` profile) |
| `infra/hermes-agent/deploy/audit-mounts-integration.test.py` | create | root/Linux CI test of the two services' mounts and env |
| `.github/workflows/ci.yml` | modify | runs the new integration test in the "Bind agreement" job |
| `infra/hermes-agent/bin/client_audit_lib.py` | create | pure helpers: credential parsing, pre-checks, lock, dir reset, error scan, isolation check |
| `infra/hermes-agent/bin/run-client-audit.py` | create | the orchestrator: pre-checks → steps → summary; `--dry-run` |
| `infra/hermes-agent/deploy/run-client-audit` | create | the `sudo` wrapper (installed as `/usr/local/sbin/run-client-audit`) |
| `infra/hermes-agent/bin/collect-review-evidence.py` | modify | D4.1 probes the credential path; D7.1 reports `audit-data` dirs |
| `infra/hermes-agent/deploy/security-review/CHECKLIST.md` | modify | v1.8 |
| `infra/hermes-agent/deploy/BRING-UP.md`, `infra/hermes-agent/README.md` | modify | install, first run, offboarding; credential table |

---

### Task 1: Package the collectors and SOP docs, and refuse client data in the package

**Files:**
- Modify: `infra/hermes-agent/bin/package_lib.py` (add after `build_manifest`)
- Modify: `infra/hermes-agent/bin/build-app-package.py:35-37`
- Modify: `infra/hermes-agent/registry/projects.yaml` (the `claude_google_ads.package` block)
- Test: `infra/hermes-agent/bin/build-app-package.test.py`

**Interfaces:**
- Produces: `package_lib.refuse_client_ids(files: dict[str, bytes]) -> None`, which raises `ValueError` naming the file (never the match).

- [ ] **Step 1: Write the failing test** (append to `build-app-package.test.py`)

```python
class TestRefuseClientIds(unittest.TestCase):
    def test_doc_with_customer_id_is_refused(self):
        import package_lib as PK
        with self.assertRaises(ValueError) as cm:
            PK.refuse_client_ids({"campaigns.md": b"ok", "google-ads-audit.md": b"Account 676-497-7319"})
        self.assertIn("google-ads-audit.md", str(cm.exception))
        self.assertNotIn("676", str(cm.exception))

    def test_undashed_id_is_refused(self):
        import package_lib as PK
        with self.assertRaises(ValueError):
            PK.refuse_client_ids({"x.md": b"cid 6764977319 here"})

    def test_code_files_are_not_scanned_and_clean_docs_pass(self):
        import package_lib as PK
        PK.refuse_client_ids({"code/a.py": b"MCC = 4518110176", "dental-benchmarks.md": b"CPL $120-$250"})
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 infra/hermes-agent/bin/build-app-package.test.py TestRefuseClientIds -v`
Expected: 3 errors, `AttributeError: module 'package_lib' has no attribute 'refuse_client_ids'`

- [ ] **Step 3: Implement** (in `package_lib.py`, after `build_manifest`)

```python
_CLIENT_ID_RE = re.compile(rb"(?<!\d)\d{3}-?\d{3}-?\d{4}(?!\d)")


def refuse_client_ids(files):
    """A packaged DOC must never carry a customer-id-shaped number: the package is built from
    the ads repo, where past client deliverables sit beside the generic SOPs (spec 2026-09-29
    ads-audits-on-the-box §9). Code is exempt (it may hold the MCC id in a constant).
    Raises ValueError naming the file, never the match."""
    bad = sorted(p for p, b in files.items() if p.endswith(".md") and _CLIENT_ID_RE.search(b))
    if bad:
        raise ValueError(f"refusing to package docs holding a customer-id-shaped number: {bad}")
```

Add `import re` to `package_lib.py`'s imports if it's missing. In `build-app-package.py`, after `files = {...}` (line 36), add:

```python
    PK.refuse_client_ids(files)
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `python3 infra/hermes-agent/bin/build-app-package.test.py -v`
Expected: all tests pass, including the 3 new ones.

- [ ] **Step 5: Extend the package include list** (`registry/projects.yaml`, `claude_google_ads.package.include`)

```yaml
      include:
        - universal-negative-keywords.md
        # Collectors (run in the one-shot ads-collector container; spec 2026-09-29 §2):
        - code/audit_discovery.py
        - code/negatives_audit.py
        - code/audit_assets_rsa.py
        - code/assess_supplemental.py
        # SOP/benchmark docs the claude-code-ads-analyst skill reads. NEVER google-ads-*.md:
        # those are past client deliverables (package_lib.refuse_client_ids enforces it).
        - dental-benchmarks.md
        - dental-sefl-blueprint.md
        - ad-assets-best-practices.md
        - anatomy-of-a-good-ad.md
        - campaigns.md
        - find-and-add-negatives.md
```

- [ ] **Step 6: Build the new package from the pinned ads commit and re-pin.** The ads repo has a local change to `.claude/settings.json`, and the build refuses modified tracked files, so stash it around the build:

```bash
cd ~/Projects/claude-google-ads && git stash push -q -m repin -- .claude/settings.json
cd ~/Projects/claude_code/infra/hermes-agent && python3 bin/build-app-package.py --project claude_google_ads \
  --repo ~/Projects/claude-google-ads --commit 5826212d7f7c27ebbb51b7bb108558356286a505 --out-dir security-reviews/pkg3; echo rc=$?
cd ~/Projects/claude-google-ads && git stash pop -q && git stash list | wc -l      # 0
```

Expected: rc 0 and `files: 21` (today's 11 + 4 collectors + 6 docs). If the guard refuses a doc, remove that doc from `include` and say so in the PR (don't weaken the guard). Put the printed `sha256` into `claude_google_ads.package.sha256`. `commit` is unchanged.

- [ ] **Step 7: Run all suites and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh` → `N/N suites passed`.

```bash
git add infra/hermes-agent/bin/package_lib.py infra/hermes-agent/bin/build-app-package.py \
        infra/hermes-agent/bin/build-app-package.test.py infra/hermes-agent/registry/projects.yaml
git commit -m "feat(hermes): package the audit collectors + SOP docs; refuse client ids in packaged docs"
```

---

### Task 2: One-shot `ads-collector` and `ads-reader` services, proven on Linux CI

**Files:**
- Modify: `infra/hermes-agent/bin/install-app-package.py` (`install()`: create the `audit_data/` mount point)
- Test: `infra/hermes-agent/bin/install-app-package.test.py`
- Modify: `infra/hermes-agent/docker-compose.yml` (after the `ads-credential-audit` service)
- Create: `infra/hermes-agent/deploy/audit-mounts-integration.test.py`
- Modify: `.github/workflows/ci.yml` ("Bind agreement" job: one more step)

**Interfaces:**
- Produces: the compose services `ads-collector` (entrypoint `/opt/ads-venv/bin/python3`, working dir `/projects/claude_google_ads`, command `code/<collector>.py`) and `ads-reader` (entrypoint `python3 /opt/cc-bin/run-ads-report.py`, args are the reader's arguments). Both read `HERMES_AUDIT_DATA_DIR` from the caller's environment.

- [ ] **Step 0: The installer creates the `audit_data/` mount point.** The app dir is installed read-only
(`0555`, root) and bind-mounted `:ro`. Docker can only bind `audit-data/<client>` onto
`/projects/claude_google_ads/audit_data` if that directory already exists in it. Otherwise it tries to
create it inside the read-only mount and fails. The installer already does the same for the `.env` mask
file. Write the failing test first (append to `install-app-package.test.py`, reusing that file's
existing install fixture; read its first test for the fixture names):

```python
    def test_install_creates_empty_audit_data_mount_point(self):
        # after a successful install into `target` (as the file's existing happy-path test does):
        p = os.path.join(target, "audit_data")
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(os.listdir(p), [])
```

Run it: FAIL (`AssertionError: False is not true`). Then in `install()`, right after the line that writes
the empty `.env` (`_write_new(os.path.join(new, ".env"), b"", 0o600)`), add:

```python
        # Mount point for the per-client audit-data bind (spec 2026-09-29 ads-audits-on-the-box §2):
        # it must pre-exist, because the app dir is bound read-only. Empty; D6.1 lists files only.
        os.mkdir(os.path.join(new, "audit_data"), 0o755)
```

The existing post-walk `chmod 0555` and chown then apply to it. Run the test: PASS. Run
`infra/hermes-agent/bin/run-bin-tests.sh` → `N/N suites passed`.

- [ ] **Step 1: Write the failing integration test** (`deploy/audit-mounts-integration.test.py`)

```python
#!/usr/bin/env python3
"""Spec 2026-09-29 ads-audits-on-the-box §2/§7: the one-shot audit containers' REAL mounts.
Runs only as root on Linux with Docker (CI "Bind agreement" job, HERMES_REQUIRE_LINUX_INTEGRATION=1);
elsewhere prints SKIPPED and exits 0 unless that variable is set, in which case a skip FAILS.
Uses a stand-in image tagged hermes-agent-claude (python:3.12-slim + uid 10000 + /opt/ads-venv)."""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
REQUIRE = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
CAN = sys.platform.startswith("linux") and os.geteuid() == 0 and shutil.which("docker")
STANDIN = """FROM python:3.12-slim
RUN useradd -u 10000 -m hermes && mkdir -p /opt/ads-venv/bin && ln -s /usr/local/bin/python3 /opt/ads-venv/bin/python3
USER hermes
"""


def sh(*a, env=None, check=True):
    return subprocess.run(list(a), capture_output=True, text=True, env=env, check=check)


@unittest.skipUnless(CAN, "needs root + Linux + docker")
class TestAuditMounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        # Layout mirrors the box: <root>/claude_code/infra/hermes-agent and <root>/claude-google-ads,
        # so the compose file's ../../../claude-google-ads resolves as it does on the box.
        cls.agent = os.path.join(cls.tmp, "claude_code/infra/hermes-agent")
        shutil.copytree(AGENT, cls.agent, ignore=shutil.ignore_patterns("data", "security-reviews", ".env*"))
        app = os.path.join(cls.tmp, "claude-google-ads/code")
        os.makedirs(app)
        os.makedirs(os.path.join(cls.tmp, "claude-google-ads/audit_data"))   # as install-app-package creates it
        open(os.path.join(cls.tmp, "claude-google-ads/.env"), "w").close()    # as install-app-package creates it
        with open(os.path.join(app, "stub_write.py"), "w") as f:
            f.write("open('/projects/claude_google_ads/audit_data/out.json','w').write('{}')\n")
        os.chmod(os.path.join(cls.tmp, "claude-google-ads"), 0o755)
        cls.data = os.path.join(cls.tmp, "audit-data/acme")
        os.makedirs(cls.data)
        os.chown(cls.data, 10000, 10000); os.chmod(cls.data, 0o700)
        d = os.path.join(cls.tmp, "img"); os.makedirs(d)
        open(os.path.join(d, "Dockerfile"), "w").write(STANDIN)
        sh("docker", "build", "-q", "-t", "hermes-agent-claude", d)
        cls.env = dict(os.environ, HERMES_AUDIT_DATA_DIR=cls.data, HERMES_SPOOL_DIR=cls.tmp,
                       HERMES_AGENT_DIR=cls.agent, HERMES_ADS_REPO_DIR=os.path.join(cls.tmp, "claude-google-ads"))
        cls.compose = ["docker", "compose", "--env-file", "/dev/null", "-f",
                       os.path.join(cls.agent, "docker-compose.yml"), "--profile", "tools"]

    def run_svc(self, *args):
        return sh(*self.compose, "run", "--rm", "--no-deps", "-T", *args, env=self.env, check=False)

    def test_collector_can_write_audit_data(self):
        r = self.run_svc("ads-collector", "code/stub_write.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.data, "out.json")))

    def test_reader_cannot_write_audit_data(self):
        r = self.run_svc("--entrypoint", "python3", "ads-reader", "-c",
                         "open('/projects/claude_google_ads/audit_data/x','w')")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Read-only file system", r.stderr)

    def test_collector_cannot_write_the_app_code(self):
        r = self.run_svc("ads-collector", "-c", "open('/projects/claude_google_ads/code/y','w')")
        self.assertNotEqual(r.returncode, 0)

    def test_no_audit_service_gets_env_file_or_mounts_etc_hermes(self):
        cfg = json.loads(sh(*self.compose, "config", "--format", "json", env=self.env).stdout)
        for name in ("ads-collector", "ads-reader"):
            svc = cfg["services"][name]
            self.assertNotIn("env_file", svc)
            self.assertNotIn("ANTHROPIC_API_KEY", json.dumps(svc.get("environment", {})))
            for v in svc.get("volumes", []):
                self.assertFalse(str(v.get("source", "")).startswith("/etc/hermes"), v)

    def test_unset_audit_data_dir_fails_closed(self):
        env = {k: v for k, v in self.env.items() if k != "HERMES_AUDIT_DATA_DIR"}
        r = sh(*self.compose, "run", "--rm", "--no-deps", "-T", "ads-collector", "code/stub_write.py",
               env=env, check=False)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    if not CAN:
        print("SKIPPED: audit-mounts integration needs root + Linux + docker")
        sys.exit(1 if REQUIRE else 0)
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails** (on a Linux host with Docker, as root; on macOS it prints SKIPPED)

Run: `sudo env HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/audit-mounts-integration.test.py -v`
Expected: errors, `no such service: ads-collector`. (If no Linux host is available locally, push the branch and read the CI result instead.)

- [ ] **Step 3: Add the services** (`docker-compose.yml`, after `ads-credential-audit`)

```yaml
  # ---- One-shot audit containers (spec 2026-09-29 ads-audits-on-the-box §2). Driven ONLY by
  # bin/run-client-audit.py, which sets HERMES_AUDIT_DATA_DIR per client and passes the READ
  # credential as `-e NAME` (value from its env, never argv, never a mounted file). No env_file:
  # these containers never see the gateway .env (it holds ANTHROPIC_API_KEY).
  # HERMES_AUDIT_DATA_DIR defaults to /dev/null, so a run without it fails closed (a char device
  # cannot be bind-mounted onto a directory) and the gateway's `up` never needs it set.
  ads-collector:
    image: hermes-agent-claude
    profiles: ["tools"]
    entrypoint: ["/opt/ads-venv/bin/python3"]
    working_dir: /projects/claude_google_ads
    volumes:
      - ../../../claude-google-ads:/projects/claude_google_ads:ro
      - ./masks/empty:/projects/claude_google_ads/.env:ro
      - ${HERMES_AUDIT_DATA_DIR:-/dev/null}:/projects/claude_google_ads/audit_data
  ads-reader:
    image: hermes-agent-claude
    profiles: ["tools"]
    entrypoint: ["python3", "/opt/cc-bin/run-ads-report.py"]
    volumes:
      - ../../../claude-google-ads:/projects/claude_google_ads:ro
      - ./masks/empty:/projects/claude_google_ads/.env:ro
      - ${HERMES_AUDIT_DATA_DIR:-/dev/null}:/projects/claude_google_ads/audit_data:ro
      - ./registry:/opt/registry:ro
      - ./bin:/opt/cc-bin:ro
      - ./data/reports:/opt/data/reports
```

- [ ] **Step 4: Wire it into CI** (`.github/workflows/ci.yml`, "Bind agreement" job, after the existing step)

```yaml
      - name: Audit containers' mounts (root, Linux, real Docker)
        run: sudo env HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/audit-mounts-integration.test.py -v
```

- [ ] **Step 5: Confirm it passes.** Run the Step 2 command on Linux, or push and read the CI job log. Expected: `Ran 5 tests ... OK`. Also check that the gateway is unaffected: `docker compose -f infra/hermes-agent/docker-compose.yml config --services` lists `hermes-agent` with `HERMES_AUDIT_DATA_DIR` unset.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/install-app-package.py infra/hermes-agent/bin/install-app-package.test.py \
        infra/hermes-agent/docker-compose.yml infra/hermes-agent/deploy/audit-mounts-integration.test.py .github/workflows/ci.yml
git commit -m "feat(hermes): one-shot ads-collector/ads-reader services; Linux CI proves their mounts"
```

---

### Task 3: `client_audit_lib` — pre-checks and pure helpers

**Files:**
- Create: `infra/hermes-agent/bin/client_audit_lib.py`
- Test: `infra/hermes-agent/bin/client_audit_lib.test.py`

**Interfaces:**
- Consumes: `vault_lib.validate_slug`, `vault_lib.load_registry(path)`, `package_lib.MANIFEST_NAME`, `package_lib.sha256_bytes`, `package_lib.sha256_file`, `package_lib.load_manifest`.
- Produces:
  - `class PrecheckError(Exception)`
  - `load_cred_env(path) -> dict[str, str]`: `GOOGLE_ADS_*` keys only
  - `check_secret_file(path, uid=0, mode=0o400) -> None` (raises `PrecheckError`)
  - `anthropic_key_state(env_path) -> str`, one of `"real" | "dummy" | "missing"`
  - `eligible_client(slug, registry_path) -> dict`: the record plus `slug`, with `customer_id` as digits (raises `PrecheckError`)
  - `package_matches(app_dir, pin_sha256) -> None` (raises `PrecheckError`)
  - `reset_dir(path, uid=10000, gid=10000) -> None`: empties and recreates the directory `0700`
  - `error_files(path) -> list[str]`: sorted basenames of `*.ERROR.txt`
  - `json_count(path) -> int`: the number of `*.json` directly in `path`
  - `others_named(text, me, slugs) -> list[str]`
  - `class AuditLock(path)`: a context manager that raises `PrecheckError("another audit is running")` if the lock is held

- [ ] **Step 1: Write the failing tests** (`bin/client_audit_lib.test.py`)

```python
#!/usr/bin/env python3
import json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client_audit_lib as L
import package_lib as PK


def w(path, body, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    if mode is not None:
        os.chmod(path, mode)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.reg = w(os.path.join(self.d, "clients.json"), json.dumps({"clients": {
            "acme-dental": {"customer_id": "123-456-7890", "status": "active", "project": "claude_google_ads"},
            "old-dental": {"customer_id": "1112223333", "status": "retired", "project": "claude_google_ads"},
            "pilot": {"customer_id": "4445556666", "status": "active", "mutation_target": "dormant_pilot",
                      "project": "claude_google_ads"}}}))


class TestCredEnv(Base):
    def test_parses_like_the_shell_parser(self):
        p = w(os.path.join(self.d, "c"), 'GOOGLE_ADS_REFRESH_TOKEN="1//abc"\r\n'
                                         "export GOOGLE_ADS_CLIENT_ID='cid'\n# c\nOTHER=x\n"
                                         "GOOGLE_ADS_CREDENTIAL_ROLE=read\n")
        self.assertEqual(L.load_cred_env(p), {"GOOGLE_ADS_REFRESH_TOKEN": "1//abc",
                                               "GOOGLE_ADS_CLIENT_ID": "cid",
                                               "GOOGLE_ADS_CREDENTIAL_ROLE": "read"})


class TestSecretFile(Base):
    def test_wrong_mode_refused(self):
        p = w(os.path.join(self.d, "c"), "x", 0o644)
        with self.assertRaises(L.PrecheckError):
            L.check_secret_file(p, uid=os.geteuid(), mode=0o400)

    def test_right_owner_and_mode_pass(self):
        p = w(os.path.join(self.d, "c"), "x", 0o400)
        L.check_secret_file(p, uid=os.geteuid(), mode=0o400)

    def test_missing_refused(self):
        with self.assertRaises(L.PrecheckError):
            L.check_secret_file(os.path.join(self.d, "nope"), uid=os.geteuid())


class TestAnthropicKey(Base):
    def test_states(self):
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "a"), "ANTHROPIC_API_KEY=sk-ant-api03-x\n")), "real")
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "b"), "ANTHROPIC_API_KEY=dummy-key-this-wave\n")), "dummy")
        self.assertEqual(L.anthropic_key_state(w(os.path.join(self.d, "c"), "OTHER=1\n")), "missing")
        self.assertEqual(L.anthropic_key_state(os.path.join(self.d, "none")), "missing")


class TestEligibleClient(Base):
    def test_active_client_resolves_with_digit_id(self):
        rec = L.eligible_client("acme-dental", self.reg)
        self.assertEqual((rec["slug"], rec["customer_id"]), ("acme-dental", "1234567890"))

    def test_dormant_pilot_is_allowed(self):
        self.assertEqual(L.eligible_client("pilot", self.reg)["slug"], "pilot")

    def test_retired_unknown_and_malformed_refused(self):
        for slug in ("old-dental", "nobody", "../x", "A B", ""):
            with self.assertRaises(L.PrecheckError, msg=slug):
                L.eligible_client(slug, self.reg)

    def test_refusal_message_never_carries_a_customer_id(self):
        with self.assertRaises(L.PrecheckError) as cm:
            L.eligible_client("old-dental", self.reg)
        self.assertNotIn("1112223333", str(cm.exception))


class TestPackage(Base):
    def _install(self, app, files):
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, files)
        for p, b in files.items():
            w(os.path.join(app, p), b.decode())
        with open(os.path.join(app, PK.MANIFEST_NAME), "wb") as f:
            f.write(PK.manifest_bytes(m))
        return PK.manifest_hash(m)

    def test_matching_package_passes_and_tampered_file_refused(self):
        app = os.path.join(self.d, "app")
        pin = self._install(app, {"code/a.py": b"print(1)\n"})
        L.package_matches(app, pin)
        w(os.path.join(app, "code/a.py"), "print(2)\n")
        with self.assertRaises(L.PrecheckError):
            L.package_matches(app, pin)

    def test_wrong_pin_refused(self):
        app = os.path.join(self.d, "app")
        self._install(app, {"code/a.py": b"x"})
        with self.assertRaises(L.PrecheckError):
            L.package_matches(app, "0" * 64)


class TestDirsAndScans(Base):
    def test_reset_dir_empties_and_is_0700(self):
        p = os.path.join(self.d, "audit-data/acme")
        w(os.path.join(p, "old.json"), "{}")
        L.reset_dir(p, uid=os.geteuid(), gid=os.getegid())
        self.assertEqual(os.listdir(p), [])
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o700)

    def test_error_files_and_json_count(self):
        p = os.path.join(self.d, "ad")
        w(os.path.join(p, "a.json"), "{}"); w(os.path.join(p, "b.ERROR.txt"), "boom")
        self.assertEqual(L.error_files(p), ["b.ERROR.txt"])
        self.assertEqual(L.json_count(p), 1)

    def test_others_named(self):
        self.assertEqual(L.others_named("Report for Old-Dental ...", "acme-dental", ["acme-dental", "old-dental"]),
                         ["old-dental"])
        self.assertEqual(L.others_named("acme-dental only", "acme-dental", ["acme-dental", "old-dental"]), [])


class TestLock(Base):
    def test_second_holder_refused(self):
        p = os.path.join(self.d, "lock")
        with L.AuditLock(p):
            with self.assertRaises(L.PrecheckError) as cm:
                with L.AuditLock(p):
                    pass
            self.assertIn("another audit is running", str(cm.exception))
        with L.AuditLock(p):                               # released after the first exits
            pass


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py`
Expected: `ModuleNotFoundError: No module named 'client_audit_lib'`

- [ ] **Step 3: Implement** (`bin/client_audit_lib.py`)

```python
#!/usr/bin/env python3
"""Pure helpers for run-client-audit.py (spec 2026-09-29 ads-audits-on-the-box). Stdlib only.
Nothing here prints; refusals raise PrecheckError with messages that never carry a customer id
or a credential value."""
import errno, fcntl, glob, os, re, shutil, stat
import package_lib as PK
import vault_lib as V


class PrecheckError(Exception):
    pass


def load_cred_env(path):
    """GOOGLE_ADS_* assignments, parsed as DATA (never sourced), matching run-ads-report.sh:
    split on the first '=', strip one layer of matching quotes, tolerate CRLF and `export `."""
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if not line.startswith("GOOGLE_ADS_") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k] = v
    return env


def check_secret_file(path, uid=0, mode=0o400):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing")
    if st.st_uid != uid or stat.S_IMODE(st.st_mode) != mode:
        raise PrecheckError(f"{path} must be owner uid {uid}, mode {oct(mode)}; "
                            f"is uid {st.st_uid}, mode {oct(stat.S_IMODE(st.st_mode))}")


def anthropic_key_state(env_path):
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip("\"'")
                    if not v:
                        return "missing"
                    return "real" if v.startswith("sk-ant-") else "dummy"
    except FileNotFoundError:
        pass
    return "missing"


def eligible_client(slug, registry_path):
    try:
        V.validate_slug(slug)
    except ValueError:
        raise PrecheckError("invalid client slug")
    clients = V.load_registry(registry_path)
    if slug not in clients:
        raise PrecheckError(f"client {slug!r} is not registered")
    rec = dict(clients[slug])
    if rec.get("status") != "active":
        raise PrecheckError(f"client {slug!r} is {rec.get('status', 'unknown')}, not active")
    cid = re.sub(r"\D", "", str(rec.get("customer_id", "")))
    if len(cid) != 10:
        raise PrecheckError(f"client {slug!r} has no valid customer id in the registry")
    rec.update(slug=slug, customer_id=cid)
    return rec


def package_matches(app_dir, pin_sha256):
    mpath = os.path.join(app_dir, PK.MANIFEST_NAME)
    try:
        with open(mpath, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise PrecheckError("no installed app package")
    if PK.sha256_bytes(raw) != pin_sha256:
        raise PrecheckError("installed app package does not match its pin")
    for e in PK.load_manifest(raw)["files"]:
        p = os.path.join(app_dir, e["path"])
        if not os.path.isfile(p) or PK.sha256_file(p) != e["sha256"]:
            raise PrecheckError(f"installed file differs from the package: {e['path']}")


def reset_dir(path, uid=10000, gid=10000):
    if os.path.lexists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    os.chown(path, uid, gid)
    os.chmod(path, 0o700)


def error_files(path):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(path, "*.ERROR.txt")))


def json_count(path):
    return len(glob.glob(os.path.join(path, "*.json")))


def others_named(text, me, slugs):
    low = text.lower()
    return sorted(s for s in slugs if s != me and re.search(r"(?<![\w-])" + re.escape(s.lower()) + r"(?![\w-])", low))


class AuditLock:
    def __init__(self, path):
        self.path, self.fd = path, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self.fd)
            if e.errno in (errno.EAGAIN, errno.EACCES):
                raise PrecheckError("another audit is running")
            raise
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py -v`
Expected: all 15 tests pass. Then run `infra/hermes-agent/bin/run-bin-tests.sh` → `N/N suites passed`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/client_audit_lib.py infra/hermes-agent/bin/client_audit_lib.test.py
git commit -m "feat(hermes): client_audit_lib — pre-checks, credential parsing, lock, isolation helpers"
```

---

### Task 4: `run-client-audit.py` — the orchestrator

**Files:**
- Create: `infra/hermes-agent/bin/run-client-audit.py`
- Test: `infra/hermes-agent/bin/run-client-audit.test.py`

**Interfaces:**
- Consumes: everything `client_audit_lib` produces (Task 3); `review_lib.Redactor`; `package_lib`; the compose services `ads-collector` and `ads-reader` (Task 2); `ads-metrics-snapshot.py --audit-data D --customer C --collected-at TS` (prints JSON); `vault-write.py --client S --audit-file F --metrics-file M --ts TS --registry R`.
- Produces:
  - `main(argv, runner=None, root="/", now=None) -> int`. rc 0 = draft written; 1 = a step failed; 2 = a pre-check refused; 3 = the lock was held.
  - `COLLECTORS`, `READERS`, `TIMEOUTS` constants.
  - A runner is `callable(argv, env, timeout, out_path, err_path) -> int` (the rc; stdout and stderr go to the files).

- [ ] **Step 1: Write the failing tests** (`bin/run-client-audit.test.py`)

```python
#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import package_lib as PK
spec = importlib.util.spec_from_file_location("rca", os.path.join(HERE, "run-client-audit.py"))
RCA = importlib.util.module_from_spec(spec); spec.loader.exec_module(RCA)

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"
CID = "1234567890"


class FakeRunner:
    """Records every step; simulates collectors writing JSON and the analyst writing a draft."""
    def __init__(self, root, fail_on=None, collector_json=True, error_file=None, draft_text="DRAFT acme"):
        self.root, self.calls, self.fail_on = root, [], fail_on
        self.collector_json, self.error_file, self.draft_text = collector_json, error_file, draft_text

    def __call__(self, argv, env, timeout, out_path, err_path):
        self.calls.append({"argv": argv, "env": dict(env or {}), "timeout": timeout})
        open(out_path, "w").write(f"stdout with {CID}\n"); open(err_path, "w").write(f"stderr {CID}\n")
        name = RCA.step_name(argv)
        if self.fail_on and self.fail_on in name:
            return 1
        ad = self.root + "/var/lib/hermes/audit-data/acme-dental"
        if "ads-collector" in argv and self.collector_json:
            open(os.path.join(ad, argv[-1].split("/")[-1] + ".json"), "w").write("{}")
            if self.error_file:
                open(os.path.join(ad, self.error_file), "w").write("boom")
        if name == "snapshot":
            open(out_path, "w").write('{"customer": "x"}')
        if name == "draft":
            d = self.root + "/opt/hermes-agent/data/audits/claude_google_ads"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, env["TS"] + "-audit.md"), "w").write(self.draft_text)
        if name == "vault-write":
            v = self.root + "/opt/hermes-agent/data/vaults/acme-dental/audits"
            os.makedirs(v, exist_ok=True)
            open(os.path.join(v, env["TS"] + "-audit.md"), "w").write(self.draft_text)
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        R = lambda p: self.root + p
        def w(p, body, mode=None):
            os.makedirs(os.path.dirname(R(p)), exist_ok=True); open(R(p), "w").write(body)
            if mode: os.chmod(R(p), mode)
        w("/var/lib/hermes/governance/registry/clients.json", json.dumps({"clients": {
            "acme-dental": {"customer_id": CID, "status": "active", "project": "claude_google_ads"},
            "other-dental": {"customer_id": "9998887777", "status": "active", "project": "claude_google_ads"}}}))
        w("/etc/hermes/.env" + ".ga", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\nGOOGLE_ADS_CREDENTIAL_ROLE=read\n", 0o400)
        w("/opt/hermes-agent/.env", "ANTHROPIC_API_KEY=sk-ant-api03-x\n")
        app = "/opt/projects/claude-google-ads"
        files = {"code/a.py": b"x"}
        w(app + "/code/a.py", "x")
        m = PK.build_manifest("claude_google_ads", "r", "a" * 40, files)
        open(R(app + "/" + PK.MANIFEST_NAME), "wb").write(PK.manifest_bytes(m))
        self.pin = PK.manifest_hash(m)
        os.makedirs(R("/run/lock"), exist_ok=True)
        RCA.PIN_OVERRIDE = self.pin          # tests bypass projects.yaml; main() reads the pin otherwise
        RCA.OWNER_UID = os.geteuid()         # tests are not root
        RCA.DATA_UID = RCA.DATA_GID = None   # skip chown to 10000 in tests
        RCA.RUN_AS_DATA_UID = []              # no setpriv in tests

    def run_main(self, runner, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RCA.main(["acme-dental", *extra], runner=runner, root=self.root, now="2026-10-01_12-00-00")
        return rc, out.getvalue() + err.getvalue()


class TestHappyPath(Base):
    def test_all_steps_run_in_order_and_draft_lands_in_vault(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 0, text)
        names = [RCA.step_name(c["argv"]) for c in r.calls]
        self.assertEqual(names, [f"collect:{c}" for c in RCA.COLLECTORS] + ["snapshot"]
                         + [f"read:{x}" for x in RCA.READERS] + ["draft", "vault-write"])
        self.assertIn("data/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md", text)

    def test_credential_only_as_env_names_and_never_on_screen(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        for c in r.calls:
            self.assertNotIn(TOKEN, " ".join(c["argv"]))
        coll = r.calls[0]
        self.assertIn("GOOGLE_ADS_REFRESH_TOKEN", coll["argv"])           # passed as -e NAME
        self.assertEqual(coll["env"]["GOOGLE_ADS_REFRESH_TOKEN"], TOKEN)   # value only in env
        self.assertEqual(coll["env"]["GOOGLE_ADS_CUSTOMER_ID"], CID)
        self.assertEqual(coll["env"]["HERMES_AUDIT_DATA_DIR"], "/var/lib/hermes/audit-data/acme-dental")
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(CID, text)

    def test_draft_step_never_gets_the_ads_credential(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        draft = [c for c in r.calls if RCA.step_name(c["argv"]) == "draft"][0]
        self.assertFalse(any(k.startswith("GOOGLE_ADS_") for k in draft["env"]))

    def test_stderr_goes_to_0600_log_files(self):
        self.run_main(FakeRunner(self.root))
        logs = self.root + "/var/lib/hermes/audit-data/acme-dental/logs"
        f = os.path.join(logs, "snapshot.stderr")
        self.assertTrue(os.path.exists(f))
        self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)

    def test_timeouts_applied(self):
        r = FakeRunner(self.root)
        self.run_main(r)
        by = {RCA.step_name(c["argv"]): c["timeout"] for c in r.calls}
        self.assertEqual(by["draft"], RCA.TIMEOUTS["draft"])
        self.assertEqual(by[f"collect:{RCA.COLLECTORS[0]}"], RCA.TIMEOUTS["collect"])

    def test_vault_write_runs_as_the_container_uid(self):
        RCA.RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]
        import client_audit_lib as L
        rec = L.eligible_client("acme-dental", self.root + RCA.REGISTRY)
        vw = [a for k, a, e in RCA.plan(rec, "t", self.root) if k == "vault-write"][0]
        self.assertEqual(vw[:4], ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"])

    def test_transient_draft_is_removed_after_vault_write(self):
        self.run_main(FakeRunner(self.root))
        d = self.root + "/opt/hermes-agent/data/audits/claude_google_ads"
        self.assertEqual(os.listdir(d), [])


class TestFailClosed(Base):
    def test_stops_at_first_failed_step(self):
        r = FakeRunner(self.root, fail_on="snapshot")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertNotIn("draft", [RCA.step_name(c["argv"]) for c in r.calls])
        self.assertIn("snapshot", text)

    def test_collector_error_file_blocks_draft(self):
        r = FakeRunner(self.root, error_file="negatives_audit.ERROR.txt")
        rc, text = self.run_main(r)
        self.assertEqual(rc, 1)
        self.assertIn("negatives_audit.ERROR.txt", text)
        self.assertNotIn("snapshot", [RCA.step_name(c["argv"]) for c in r.calls])

    def test_no_json_after_collection_blocks(self):
        rc, text = self.run_main(FakeRunner(self.root, collector_json=False))
        self.assertEqual(rc, 1)
        self.assertIn("no data", text)

    def test_stale_data_is_cleared_before_collecting(self):
        ad = self.root + "/var/lib/hermes/audit-data/acme-dental"
        os.makedirs(ad); open(ad + "/stale.json", "w").write("{}")
        self.run_main(FakeRunner(self.root))
        self.assertFalse(os.path.exists(ad + "/stale.json"))

    def test_draft_naming_another_client_fails(self):
        rc, text = self.run_main(FakeRunner(self.root, draft_text="compare with other-dental"))
        self.assertEqual(rc, 1)
        self.assertIn("other-dental", text)


class TestPrechecks(Base):
    def test_retired_or_unknown_client_refused_before_any_step(self):
        r = FakeRunner(self.root)
        out = io.StringIO()
        with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
            rc = RCA.main(["nobody"], runner=r, root=self.root, now="t")
        self.assertEqual(rc, 2); self.assertEqual(r.calls, [])

    def test_dummy_anthropic_key_refused(self):
        open(self.root + "/opt/hermes-agent/.env", "w").write("ANTHROPIC_API_KEY=dummy-key-this-wave\n")
        r = FakeRunner(self.root)
        rc, text = self.run_main(r)
        self.assertEqual(rc, 2); self.assertEqual(r.calls, []); self.assertIn("Anthropic", text)

    def test_package_mismatch_refused(self):
        open(self.root + "/opt/projects/claude-google-ads/code/a.py", "w").write("tampered")
        r = FakeRunner(self.root)
        self.assertEqual(self.run_main(r)[0], 2); self.assertEqual(r.calls, [])

    def test_lock_held_refused_with_rc_3(self):
        import client_audit_lib as L
        with L.AuditLock(self.root + "/run/lock/hermes-client-audit.lock"):
            r = FakeRunner(self.root)
            rc, text = self.run_main(r)
        self.assertEqual(rc, 3); self.assertEqual(r.calls, []); self.assertIn("another audit is running", text)

    def test_dry_run_prints_plan_runs_nothing_and_shows_no_secret(self):
        r = FakeRunner(self.root)
        rc, text = self.run_main(r, "--dry-run")
        self.assertEqual(rc, 0); self.assertEqual(r.calls, [])
        self.assertIn("ads-collector", text)
        self.assertNotIn(TOKEN, text); self.assertNotIn(CID, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py`
Expected: `FileNotFoundError` for `run-client-audit.py`.

- [ ] **Step 3: Implement** (`bin/run-client-audit.py`)

```python
#!/usr/bin/env python3
"""One client's Google Ads trend-audit DRAFT on the box (spec 2026-09-29 ads-audits-on-the-box).

  sudo run-client-audit <client> [--dry-run]

Pre-checks, then: collect (one-shot ads-collector) -> snapshot (host) -> readers (one-shot
ads-reader) -> draft (claude -p in the gateway, as run-trend-audit.sh) -> vault-write -> the
check that the draft names no other client. Stops at the first failure. Exit: 0 draft
written, 1 a step failed, 2 a pre-check refused, 3 another audit is running.
Nothing shown carries a customer id or credential value; each step's stdout and stderr go to
<audit-data>/logs/<step>.{stdout,stderr} (0600)."""
import argparse, datetime, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import changeset_lib as C
import client_audit_lib as L
import review_lib as R

AGENT_DIR = "/opt/hermes-agent"
GOV = "/var/lib/hermes/governance"
REGISTRY = GOV + "/registry/clients.json"
CRED = "/etc/hermes/.env" + ".ga"
APP_DIR = "/opt/projects/claude-google-ads"
AUDIT_DATA = "/var/lib/hermes/audit-data"
LOCK = "/run/lock/hermes-client-audit.lock"
PROJECT = "claude_google_ads"
COLLECTORS = ("audit_discovery", "negatives_audit", "audit_assets_rsa", "assess_supplemental")
READERS = ("account_overview", "audit_search_terms", "audit_analyze")
TIMEOUTS = {"collect": 900, "snapshot": 120, "read": 300, "draft": 1200, "vault-write": 120}
CRED_NAMES = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
              "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")
OWNER_UID = 0                 # the credential file's owner; tests override
DATA_UID = DATA_GID = 10000   # the containers' uid; tests set None to skip chown
PIN_OVERRIDE = None           # tests only
# vault-write runs on the HOST but writes files the gateway (uid 10000) must read next month
# (trend mode): run it AS that uid, or the vault fills with root-owned files. Tests set [].
RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]

# Verbatim from run-trend-audit.sh (spec §2 step 5): the analyst, its model and its limits.
DRAFT_SCRIPT = r'''
  set -eu
  skill="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
  vault="/opt/data/vaults/$CLIENT"; reports="/opt/data/reports/$PROJECT"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  mkdir -p "/opt/data/audits/$PROJECT"
  out="/opt/data/audits/$PROJECT/$TS-audit.md"
  claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Do NOT attempt ExitPlanMode and do NOT narrate your tools or environment; BEGIN your response with the DRAFT banner and output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'''


def step_name(argv):
    if "ads-collector" in argv:
        return "collect:" + os.path.basename(argv[-1])[:-3]
    if "ads-reader" in argv:
        return "read:" + argv[argv.index("ads-reader") + 1]
    if "exec" in argv:
        return "draft"
    return "snapshot" if any(a.endswith("ads-metrics-snapshot.py") for a in argv) else "vault-write"
    # (a vault-write argv may start with RUN_AS_DATA_UID; the fallback still names it)


def real_runner(argv, env, timeout, out_path, err_path):
    with open(out_path, "w") as out, open(err_path, "w") as err:
        try:
            return subprocess.run(argv, env=env, stdout=out, stderr=err, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            err.write(f"\n[run-client-audit] timed out after {timeout}s\n")
            return 124


def _compose(root):
    return ["docker", "compose", "-f", root + AGENT_DIR + "/docker-compose.yml", "--profile", "tools"]


def plan(rec, ts, root):
    """[(timeout_key, argv, env)] — env holds only what the step needs, plus PATH."""
    slug, cid = rec["slug"], rec["customer_id"]
    data = AUDIT_DATA + "/" + slug
    base = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")}
    cred = {**base, **{k: v for k, v in L.load_cred_env(root + CRED).items() if k in CRED_NAMES},
            "GOOGLE_ADS_CUSTOMER_ID": cid, "HERMES_AUDIT_DATA_DIR": data}
    eflags = [x for n in CRED_NAMES for x in ("-e", n)]
    run = _compose(root) + ["run", "--rm", "--no-deps", "-T"] + eflags
    steps = [("collect", run + ["ads-collector", f"code/{c}.py"], cred) for c in COLLECTORS]
    steps.append(("snapshot", ["python3", root + AGENT_DIR + "/bin/ads-metrics-snapshot.py",
                               "--audit-data", root + data, "--customer", cid, "--collected-at", ts], base))
    steps += [("read", run + ["ads-reader", r, "--project", PROJECT], cred) for r in READERS]
    steps.append(("draft", _compose(root) + ["exec", "-e", "PROJECT", "-e", "CLIENT", "-e", "TS", "-T",
                                             "hermes-agent", "sh", "-lc", DRAFT_SCRIPT],
                  {**base, "PROJECT": PROJECT, "CLIENT": slug, "TS": ts}))
    steps.append(("vault-write", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/vault-write.py", "--client", slug,
                                  "--audit-file", root + f"{AGENT_DIR}/data/audits/{PROJECT}/{ts}-audit.md",
                                  "--metrics-file", root + data + "/logs/snapshot.stdout", "--ts", ts,
                                  "--registry", root + REGISTRY],
                  {**base, "VAULT_ROOT": root + AGENT_DIR + "/data/vaults", "TS": ts}))
    return steps


def main(argv=None, runner=None, root="/", now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    root = root.rstrip("/")
    runner = runner or real_runner
    ts = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    try:
        rec = L.eligible_client(a.client, root + REGISTRY)
    except (L.PrecheckError, ValueError, OSError) as e:
        print(f"run-client-audit: refused: {e}", file=sys.stderr); return 2
    red = R.Redactor([], [rec["customer_id"]])
    say = lambda s: print(red.text(s))
    try:
        L.check_secret_file(root + CRED, uid=OWNER_UID, mode=0o400)
        if L.anthropic_key_state(root + AGENT_DIR + "/.env") != "real":
            raise L.PrecheckError("the gateway .env has no real Anthropic key")
        pin = PIN_OVERRIDE or C.read_package(root + AGENT_DIR + "/registry/projects.yaml", PROJECT)["sha256"]
        L.package_matches(root + APP_DIR, pin)
    except (L.PrecheckError, ValueError, OSError) as e:
        print(red.text(f"run-client-audit: refused: {e}"), file=sys.stderr); return 2
    steps = plan(rec, ts, root)
    if a.dry_run:
        for key, argv_, env in steps:
            say(f"would run [{step_name(argv_)}] timeout={TIMEOUTS[key]}s: {' '.join(argv_[:12])} …"
                f" env={sorted(k for k in env if k != 'PATH')}")
        return 0
    try:
        with L.AuditLock(root + LOCK):
            return _run(steps, rec, ts, root, runner, say)
    except L.PrecheckError as e:
        print(f"run-client-audit: {e}", file=sys.stderr); return 3


def _run(steps, rec, ts, root, runner, say):
    slug = rec["slug"]
    data = root + AUDIT_DATA + "/" + slug
    kw = ({"uid": os.geteuid(), "gid": os.getegid()} if DATA_UID is None
          else {"uid": DATA_UID, "gid": DATA_GID})
    L.reset_dir(data, **kw)
    logs = os.path.join(data, "logs"); os.makedirs(logs, mode=0o700)
    os.chown(logs, kw["uid"], kw["gid"])
    reports = root + f"{AGENT_DIR}/data/reports/{PROJECT}"
    results = []
    for i, (key, argv_, env) in enumerate(steps):
        name = step_name(argv_)
        if key == "snapshot":                                   # collection just finished
            bad = L.error_files(data)
            if bad:
                say(f"run-client-audit: collector errors, no draft: {bad}"); return _summary(results, 1, say)
            if L.json_count(data) == 0:
                say("run-client-audit: collectors wrote no data, no draft"); return _summary(results, 1, say)
        if key == "read" and name.endswith(READERS[0]) and os.path.isdir(reports):
            for f in os.listdir(reports):
                if f.endswith(".md"):
                    os.remove(os.path.join(reports, f))
        stem = os.path.join(logs, name.replace(":", "-"))
        t0 = time.monotonic()
        rc = runner(argv_, env, TIMEOUTS[key], stem + ".stdout", stem + ".stderr")
        for p in (stem + ".stdout", stem + ".stderr"):
            if os.path.exists(p):
                os.chmod(p, 0o600)
                if DATA_UID is not None:              # vault-write (as 10000) reads snapshot.stdout
                    os.chown(p, DATA_UID, DATA_GID)
        results.append((name, rc, round(time.monotonic() - t0, 1)))
        if rc != 0:
            say(f"run-client-audit: step {name} failed (rc {rc}); see {stem}.stderr")
            return _summary(results, 1, say)
    vault_draft = root + f"{AGENT_DIR}/data/vaults/{slug}/audits/{ts}-audit.md"
    with open(vault_draft, encoding="utf-8", errors="replace") as f:
        named = L.others_named(f.read(), slug, list(L.V.load_registry(root + REGISTRY)))
    if named:
        say(f"run-client-audit: ASSERTION FAIL — the draft names other clients: {named}")
        return _summary(results, 1, say)
    transient = root + f"{AGENT_DIR}/data/audits/{PROJECT}/{ts}-audit.md"
    if os.path.exists(transient):
        os.remove(transient)
    say(f"run-client-audit: draft -> {vault_draft[len(root):]}  (data collected {ts} UTC)")
    return _summary(results, 0, say)


def _summary(results, rc, say):
    for name, r, secs in results:
        say(f"  {name:<28} rc={r:<4} {secs}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run it and confirm it passes; fix only what the tests show**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -v`
Expected: all 18 tests pass. Note the snapshot's stdout is its JSON, which vault-write reads as `--metrics-file` from `logs/snapshot.stdout`. If `ads-metrics-snapshot.py` also prints to stdout on success (check its `main`), adjust the fake and the plan so vault-write gets pure JSON. Then run `infra/hermes-agent/bin/run-bin-tests.sh` → `N/N suites passed`.

- [ ] **Step 5: Check the reader arguments against `run-ads-report.py`**

Run: `grep -n "add_argument" infra/hermes-agent/bin/run-ads-report.py`
Expected: the reader name is positional and `--project` exists. If the flags differ, change the `read` steps in `plan()` to match, and update `test_all_steps_run_in_order...` only if the step names change.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py
git commit -m "feat(hermes): run-client-audit — one-command, fail-closed client audit on the box"
```

---

### Task 5: The `sudo` wrapper, BRING-UP and README

**Files:**
- Create: `infra/hermes-agent/deploy/run-client-audit`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (new section "Ads audits on the box", after "Sweep the in-memory mounts")
- Modify: `infra/hermes-agent/README.md` (credential table `read` row; the gateway-`.env` paragraph)

- [ ] **Step 1: The wrapper** (`deploy/run-client-audit`, mode `0755` in git)

```sh
#!/bin/sh
# Installed as /usr/local/sbin/run-client-audit (symlink, BRING-UP "Ads audits on the box").
# Root only: it reads /etc/hermes's 0400 credential and drives Docker directly.
[ "$(id -u)" = 0 ] || { echo "run-client-audit: run with sudo" >&2; exit 2; }
exec python3 /opt/hermes-agent/bin/run-client-audit.py "$@"
```

Run: `chmod 0755 infra/hermes-agent/deploy/run-client-audit && sh -n infra/hermes-agent/deploy/run-client-audit && echo ok` → `ok`.

- [ ] **Step 2: BRING-UP section "Ads audits on the box (spec 2026-09-29)"**, with these subsections, each a paste-as-one-block command with the expected output as a trailing comment, in the file's existing style:
  1. **Install the re-pinned package**: `bin/install-app-package.py` exactly as the current package-install section does, with the new pin. Expected: D6.1-style `installed_sha256 == pin`.
  2. **Install the read credential** (operator, from the laptop): `scp` the laptop's `.env.ga` to `~/env.ga.incoming`, then:
     `sudo install -d -m 0755 /etc/hermes && sudo install -o root -g root -m 0400 ~/env.ga.incoming /etc/hermes/.env.ga && shred -u ~/env.ga.incoming`
     `sudo stat -c '%U:%G %a' /etc/hermes/.env.ga` → `root:root 400`;
     `sudo python3 /opt/hermes-agent/bin/collect-review-evidence.py --credentials-only` → one row, role `read`, sha12 `fd18a3b7d0f4`;
     `ls ~/env.ga.incoming 2>&1` → `No such file or directory` (the F24 lesson: no stray copy).
  3. **Install the Anthropic key** (operator; the key never enters an assistant session):
     - Console: create workspace `hermes-box`, set a monthly spend limit, create a key there, save it in the password manager.
     - Delete the legacy `…9wAA` key.
     - On the box, `sudoedit /opt/hermes-agent/.env` and replace the dummy value.
     - Check: `sudo sed -nE 's/^ANTHROPIC_API_KEY=//p' /opt/hermes-agent/.env | awk '{print substr($0,1,10), "len="length($0)}'` → `sk-ant-api len=…`.
     - Recreate the gateway, so `claude-auth-init` rewrites the executor's settings: `cd /opt/hermes-agent && sudo docker compose up -d --force-recreate`.
  4. **Create the audit-data root**: `sudo install -d -o root -g root -m 0711 /var/lib/hermes/audit-data` (per-client dirs are created `10000:10000 0700` by the tool).
  5. **Register the spending client**: follow the existing "first real client" procedure (the 2026-09-26 block: registry entry with `status: active`, no `mutation_target`; its log created and sealed append-only; the vault directory `10000:hermes 0700`). The slug and id stay off the repo (F21).
  6. **Install the command**: `sudo ln -sf /opt/hermes-agent/deploy/run-client-audit /usr/local/sbin/run-client-audit`.
  7. **Dry run, then the first audit**: `sudo run-client-audit <client> --dry-run` (shows no secret or id), then `sudo run-client-audit <client>`. Expected: every step `rc=0`, `draft -> /opt/hermes-agent/data/vaults/<client>/audits/<ts>-audit.md`. Copy it off with `scp`, and record the runtime (the summary) and the cost (the Console's `hermes-box` usage).
  8. **Offboarding**: when a client is retired, `sudo rm -rf /var/lib/hermes/audit-data/<client> /opt/hermes-agent/data/vaults/<client>` after its status is set to `retired`. The review's D7.1 checks no retired client has either.

- [ ] **Step 3: README.** In the credential table's `read` row, replace "on the laptop only (the box holds no Google Ads credential; security review #3)" with "on the laptop, and on the box at `/etc/hermes/.env.ga` (`root:root 0400`, same token; passed per run to the audit containers, never mounted)". In the gateway-`.env` paragraph, change "a **dummy** `ANTHROPIC_API_KEY`" to "a **real** `ANTHROPIC_API_KEY` (workspace `hermes-box`, monthly spend limit; used only by the audit analyst)".

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/deploy/run-client-audit infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): BRING-UP for ads audits on the box; run-client-audit wrapper; README credential table"
```

---

### Task 6: Review tooling and checklist v1.8

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`GATEWAY_PROBE_PATHS`; `d7_1`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`

**Interfaces:**
- Produces: the `D7.1` data key `audit_data: [{"status": "active"|"retired"|"unregistered", "owner": str, "mode": str}]` (redacted: never the slug). `GATEWAY_PROBE_PATHS` gains `/etc/hermes/.env.ga`.

- [ ] **Step 1: Write the failing tests** (append to `TestTighteningAfterReview3`, or a new class `TestAuditsOnTheBox(Base)`)

```python
class TestAuditsOnTheBox(Base):
    def test_gateway_probe_includes_the_box_credential_path(self):
        self.assertIn("/etc/hermes/.env" + ".ga", CE.GATEWAY_PROBE_PATHS)

    def test_d7_1_reports_audit_data_dirs_by_status_without_slugs(self):
        os.makedirs(os.path.join(self.root, "var/lib/hermes/audit-data/acme-dental"))
        os.makedirs(os.path.join(self.root, "var/lib/hermes/audit-data/ghost-client"))
        os.makedirs(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "data/vaults"), exist_ok=True)
        out = CE.collect(self.host())
        rows = out["items"]["D7.1"]["data"]["audit_data"]
        self.assertEqual(sorted(r["status"] for r in rows), ["active", "unregistered"])
        self.assertNotIn("ghost-client", json.dumps(out))
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestAuditsOnTheBox -v`
Expected: 2 failures (`AssertionError` / `KeyError: 'audit_data'`).

- [ ] **Step 3: Implement.** Add `"/etc/hermes/.env" + ".ga"` to the `GATEWAY_PROBE_PATHS` tuple. In `d7_1`, before its `return`, add (and include `"audit_data": audit` in the returned dict):

```python
    audit = []
    ad_root = host.path("/var/lib/hermes/audit-data")
    if os.path.isdir(ad_root):
        with open(host.path(GOV + "/registry/clients.json")) as f:
            reg = json.load(f).get("clients", {})
        for name in sorted(os.listdir(ad_root)):
            st = os.lstat(os.path.join(ad_root, name))
            audit.append({"status": reg.get(name, {}).get("status", "unregistered"),
                          "owner": _owner(st.st_uid), "mode": oct(stat.S_IMODE(st.st_mode))})
```

- [ ] **Step 4: Run them and confirm they pass.** Run the Step 2 command, then `infra/hermes-agent/bin/run-bin-tests.sh` → `N/N suites passed`.

- [ ] **Step 5: Checklist v1.8.** Set `version: 1.8`. In the header's version notes, append: "(v1.8: ads audits on the box: the box's read credential, the real Anthropic key, D4.1 probe, D7.1 `audit_data`.)" Then change these items (text to paste):
  - **D2.1 claim**, append: "Since v1.8 the authorised set on the box is exactly one **read** credential at `/etc/hermes/.env.ga`, `root:root 0400`, `kind: credential`, `role: read`, whose `refresh_token_sha12` equals the laptop's `.env.ga` (D3.1)."
  - **D3.1 expected**, append: "The box credential's `refresh_token_sha12` (box bundle `credentials`) equals the laptop `.env.ga` row's."
  - **D4.1 expected**: add "`/etc/hermes/.env.ga` `absent`" to the list of paths.
  - **D7.1 expected**, append: "`audit_data`: every row `status: active`, `owner` the container uid (10000 or its name), `mode 0o700`. No `retired` or `unregistered` row: offboarding removes them."
  - **New manual line under "Not on the checklist" guidance, or D2.1 expected**: "The gateway `.env`'s `ANTHROPIC_API_KEY` is real (workspace `hermes-box`, spend limit stated by the operator)."

Run: `python3 infra/hermes-agent/bin/check-checklist-version.py --base origin/main` after committing → `changed, version raised 1.7 -> 1.8`.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py \
        infra/hermes-agent/deploy/security-review/CHECKLIST.md
git commit -m "feat(hermes): review tooling for audits on the box; checklist v1.8"
```

---

### Task 7: Rollout, first audit, review #4 (operational: operator and assistant, no new code)

Not a coding task. Each step says who does it. Do nothing on the box before the PR is merged.

- [ ] **Step 1 (assistant):** open the PR; CI green (including the new mounts test, whose log must show `Ran 5 tests`, not SKIPPED). Operator merges.
- [ ] **Step 2 (operator, laptop):** declare the role in `.env.ga` (the command from the step-2 summary; prints `1`).
- [ ] **Step 3 (operator, box):** `cd /opt/projects/claude_code && sudo git pull --ff-only`, then BRING-UP "Ads audits on the box" subsections 1–6, pasting each block's output.
- [ ] **Step 4 (assistant, laptop):** `collect-review-evidence-laptop.py --access-digest` shows the digest unchanged (`0f0bdb9e…1319`), and the box's `--credentials-only` sha12 equals `fd18a3b7d0f4`.
- [ ] **Step 5 (operator, box):** subsection 7: dry run, then the first audit on the spending client. Copy the draft off, compare it with a laptop draft for the same period, and state "deliverable" or not. Record runtime and cost.
- [ ] **Step 6 (operator + assistant):** collect both bundles (as in review #3) and run a fresh reviewer against checklist v1.8 with the operator evidence. Then sign-off, a PR for the report and a brain decision.
