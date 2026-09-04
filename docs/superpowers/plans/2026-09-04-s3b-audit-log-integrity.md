# S3-b Audit-Log Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `ads-mutator` executor able to append to its audit log but not delete it, and make a missing log fail closed instead of reading as "no usage yet".

**Architecture:** Four coupled changes. The host owns `log/` at `2750` (setgid, no group write, so no `unlink` and no create); each registered client gets a pre-created `0660` log from a new `--bootstrap-logs` mode on `migrate-governance.py`; the pre-flight stops demanding write on the *directory* and starts demanding a log per *registered client*; and `iter_log_records` raises on a missing log. Landing fewer than four breaks the rail — see the spec's §2.

**Tech Stack:** Python 3 stdlib only (no third-party imports anywhere under `infra/hermes-agent/bin/`), `unittest`, POSIX permission semantics, Docker for the layout probe.

**Spec:** `docs/superpowers/specs/2026-09-04-s3b-audit-log-integrity-design.md`

## Global Constraints

- **Python 3 stdlib only** under `infra/hermes-agent/bin/`. No new dependencies.
- **Exactly one trailing `unittest.main()`** per test file.
- **Fail closed** — an unreadable or missing limit must never read as permissive.
- **No client names, customer ids, campaign ids, or credential values** in code, tests, docs, or refusal text. The established invented fixtures are `acme-dental` / `acme` / `other-clinic` and `"1234567890"`; see Task 6 for why a naive scan hits them.
- **Never print a credential value or a sha12 into a tracked file.** `.env.*.example` are tracked.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in cleartext.
- **Leave the kill switch OFF.** It is the *file* `~/.hermes/governance/control/mutation-enabled`, currently absent. `control/` itself exists and holds `.locks/`, so `ls control/` returns 0 and proves nothing.
- **Stage by explicit path only.** `evals/` is only partially gitignored (`.gitignore:14` covers `evals/codex-runs/` alone) and the tree carries 5 tracked + 43 untracked pre-existing changes. Never `git add -A`, `git add .project-brain/`, or `git add evals/`.
- **Branch:** `s3b-audit-log-integrity` (already created; the design doc is committed on it at `182c285`). `main` is protected — land via PR.
- **`cmd | tail` takes its exit status from `tail`.** Capture into a variable or use `PIPESTATUS`. This has misreported an exit code twice in this project.
- **Bash working directory persists between tool calls.** Start each command block with an explicit `cd`, or use absolute paths.
- **Baselines before starting:** `infra/hermes-agent/bin/run-bin-tests.sh` → 25/25 (exit 0); `node scripts/run-all-tests.js` → 22/22 (exit 0). Per-file test counts: `preflight-governance-access.test.py` 30, `migrate-governance.test.py` 11, `changeset_lib.test.py` 109, `apply-changeset.test.py` 46.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `infra/hermes-agent/bin/preflight-governance-access.py` | The startup gate. Loses its directory-write demand on `log/`; gains a registry-driven log-existence check; its `REMEDY` text becomes the setgid layout. | 1, 3 |
| `infra/hermes-agent/bin/preflight-governance-access.test.py` | Fixtures move to the new documented layout; two tests are each replaced by a pair (net +2); six new tests for the existence check. | 1, 3 |
| `infra/hermes-agent/bin/governance_lib.py` | Gains `EXECUTOR_UID`/`EXECUTOR_GID` and the log modes as the single definition, following `6645879`'s `REQUEST_ID_RE` precedent. | 2 |
| `infra/hermes-agent/bin/migrate_governance_shim.py` | Gains `bootstrap_logs()`. `migrate()`'s `_ensure_dir` call learns the new `log/` mode. | 2 |
| `infra/hermes-agent/bin/migrate-governance.py` | Gains `--bootstrap-logs`, sharing the dry-run-by-default contract. | 2 |
| `infra/hermes-agent/bin/migrate-governance.test.py` | Nine new tests for the bootstrap and its CLI. | 2 |
| `infra/hermes-agent/bin/changeset_lib.py` | `iter_log_records` raises on a missing log; two stale comment blocks corrected. | 4 |
| `infra/hermes-agent/README.md` | The deploy layout, kept verbatim-identical to `REMEDY`. | 1 |
| `infra/hermes-agent/docker-compose.yml` | Comment only — records why the mount stays `rw` while the host mode changes. | 1 |
| `docs/evaluations/2026-09-04-s3b-layout-probe.md` | The container probe's recorded evidence. | 5 |

---

## Task 1: Deploy layout and pre-flight inversion

Changes (1) and (3) from the spec. They are one change seen from two sides: the layout becomes `2750`/`0660`, and the gate stops refusing it. Splitting them would land a commit in which the pre-flight refuses the documented layout — R24(a)'s exact failure.

**Files:**
- Modify: `infra/hermes-agent/bin/preflight-governance-access.test.py:40-45` (`_restore_modes`), `:74-81`, `:84-93`, `:121-129` (`_configure_group_readable_dirs`)
- Modify: `infra/hermes-agent/bin/preflight-governance-access.py:258-261`, `:286-289` (`REMEDY`)
- Modify: `infra/hermes-agent/README.md:894-901`
- Modify: `infra/hermes-agent/docker-compose.yml:92-97`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the layout constants every later task assumes — `log/` mode `0o2750`, per-client log files `0o660`. `PF.check(root, uid, gid, platform=...)` keeps its signature and its `list[str]` return.

- [ ] **Step 1: Move the test fixtures to the new documented layout — this is the failing-test step**

In `preflight-governance-access.test.py`, `_configure_group_readable_dirs` (`:121`) currently reads:

```python
    def _configure_group_readable_dirs(self):
        """The documented remedy layout: root and read-only dirs at 0750, log/
        additionally group-writable at 0770. Mirrors
        test_group_readable_store_with_a_matching_gid_passes above."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o770)
```

Replace it with:

```python
    def _configure_group_readable_dirs(self):
        """The documented remedy layout (S3-b): root and read-only dirs at 0750, and
        log/ at 2750 — group read+traverse but NOT group write, because directory write
        is what grants unlink, and setgid so host-created log files inherit the
        executor's group. append_log fsyncs the log/ directory fd, so r-x is required
        and traverse alone would not do. Mirrors
        test_group_readable_store_with_a_matching_gid_passes above."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)
```

And in `_restore_modes` (`:40`), change the same line so cleanup mirrors the layout under test:

```python
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)
```

`_restore_modes` exists so `shutil.rmtree` can run; the tests own these directories and owner bits are `rwx` in `2750`, so cleanup is unaffected.

- [ ] **Step 2: Run the suite to verify it fails, and record which tests fail**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out"; echo "exit: $rc"
```

Expected: FAIL. Every test built on `_configure_full_correct_store` reds, because `check()` still demands write on `log/` and `2750` does not grant it. Each failure message contains `log: mode 2750 ... the executor needs read+write+traverse`. **This is R24(a) reproduced inside the suite** rather than asserted.

Record the sorted list of failing test names; Step 8 compares against it.

- [ ] **Step 3: Invert the directory requirement**

In `preflight-governance-access.py`, `check()` at `:258-261` currently reads:

```python
    for name in READ_WRITE_DIRS:
        p = _check_dir(os.path.join(root, name), uid, gid, need_write=True)
        if p:
            problems.append(p)
```

Replace with:

```python
    # S3-b: read+traverse on the DIRECTORY, never write. Directory write is what grants
    # unlink, so a log/ the executor can write is a log/ it can delete — and both the
    # undo path and the caps path read through iter_log_records, so a deleted log costs
    # REVERSIBILITY, not merely quota. What the executor actually needs here is r-x:
    # append_log opens log/<slug>.jsonl with mode "a" (the FILE-level check below covers
    # that) and then fsyncs the log/ DIRECTORY fd via os.open(dirname, O_RDONLY), which
    # is why read is required and traverse alone would not be enough.
    for name in READ_WRITE_DIRS:
        p = _check_dir(os.path.join(root, name), uid, gid, need_write=False)
        if p:
            problems.append(p)
```

- [ ] **Step 4: Run the suite; expect the Step 2 failures gone and exactly one new one**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out"; echo "exit: $rc"
```

Expected: every Step 2 failure is gone, and exactly one test now fails —
`test_read_only_store_flags_only_the_writable_directories`. Its premise ("the executor must WRITE the audit log", so `0o755` throughout must produce exactly `len(READ_WRITE_DIRS)` problems) is precisely what this task inverts. Do **not** delete it; Step 5 moves its intent to the axis that now carries it.

- [ ] **Step 5: Rewrite that test onto the file-level axis**

Replace `test_read_only_store_flags_only_the_writable_directories` (`:84-93`) with:

```python
    def test_world_readable_store_passes_the_dirs_but_flags_an_unwritable_log_file(self):
        """S3-b moved the write requirement from the DIRECTORY to the FILE. 0o755
        throughout is now a correct layout for log/ itself — r-x is all append_log needs
        from the directory — so the directory pass here is not a weakened check, it is
        the check landing on the right object. The requirement did not go away: an
        existing log/<slug>.jsonl the executor cannot append to is still exactly the
        mid-apply exit-3 this script exists to prevent, and is still reported."""
        self._chmod_all(0o755)
        log_file = os.path.join(self.root, "log", "acme.jsonl")
        with open(log_file, "w") as f:
            f.write("{}\n")
        os.chmod(log_file, 0o644)          # readable, NOT writable by group or other
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("acme.jsonl", problems[0])
        for name in PF.READ_ONLY_DIRS:
            self.assertFalse(any("%s:" % name in p for p in problems), name)

    def test_control_the_same_store_with_an_appendable_log_file_is_healthy(self):
        """POSITIVE CONTROL for the test above. Without it, that assertion would also
        pass against an implementation that reported every log file as a problem."""
        self._chmod_all(0o755)
        log_file = os.path.join(self.root, "log", "acme.jsonl")
        with open(log_file, "w") as f:
            f.write("{}\n")
        os.chmod(log_file, 0o666)
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.other_gid, platform="linux"), [])
```

- [ ] **Step 6: Update the test that documents the old remedy, and record the honest negative**

`test_group_readable_store_with_a_matching_gid_passes` (`:74`) sets `log/` to `0o770` inline and still passes (group `rwx` includes `r-x`), so it is green but documents a layout the project no longer recommends. Replace it with two tests:

```python
    def test_group_readable_store_with_a_matching_gid_passes(self):
        """The documented remedy: keep the store off `other`, grant the executor's
        group. log/ is 2750 — group read+traverse, NO group write (write on the
        directory is what grants unlink), setgid so host-created log files inherit
        gid 10000."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_group_writable_log_dir_still_passes_because_it_over_grants(self):
        """HONEST NEGATIVE RESULT, recorded rather than hidden. This gate checks that
        the executor CAN work, not that it is minimally privileged, so the old 0770
        layout still returns zero problems — the pre-flight is NOT what stops an
        operator re-widening log/. The deploy documentation and REMEDY text are, and
        Task 5's container probe is what measures the difference. Asserting a refusal
        here would be asserting a guarantee this script does not make."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o770)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])
```

- [ ] **Step 7: Run the suite to verify it passes**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

Expected: PASS (`OK`), **32** tests — 30 before, and two replacements that each turn one test into two (Step 5 and Step 6), so net +2.

- [ ] **Step 8: Mutation proof — revert the inversion and confirm it reds**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cp preflight-governance-access.py /tmp/pf.orig
python3 - <<'PY'
import io
p = "preflight-governance-access.py"
s = io.open(p).read()
old = "        p = _check_dir(os.path.join(root, name), uid, gid, need_write=False)"
assert s.count(old) == 1, "expected exactly one inverted call, found %d" % s.count(old)
io.open(p, "w").write(s.replace(old, old.replace("need_write=False", "need_write=True")))
PY
python3 -c "import ast; ast.parse(open('preflight-governance-access.py').read())" && echo "mutant parses"
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | sort
echo "mutant exit: $rc"
cp /tmp/pf.orig preflight-governance-access.py && rm /tmp/pf.orig
```

Expected: the mutant parses, exits non-zero, and reds the positive control plus the `TestFileLevelChecks` exact-count tests. Report the sorted failing-set difference. **If this mutation reds nothing, stop** — that is a coverage claim, not a pass, and it means Step 1's fixture change did not take.

- [ ] **Step 9: Update `REMEDY` so the gate stops teaching the vulnerability**

`preflight-governance-access.py:288-289` currently reads:

```python
    sudo chgrp -R %(gid)d %(root)s
    sudo chmod -R g+rX %(root)s && sudo chmod -R g+w %(root)s/log
```

`chmod -R g+w .../log` adds group write to the *directory*, which is exactly the `unlink` grant this wave removes — and the pre-flight prints this text when it refuses, so leaving it teaches every operator to rebuild the hole. Replace those two lines with:

```python
    sudo chgrp -R %(gid)d %(root)s
    sudo chmod -R g+rX %(root)s
    sudo chmod g+s %(root)s/log
    sudo find %(root)s/log -type f -name '*.jsonl' -exec chmod 0660 {} +

log/ gets NO group write: write on a directory is what grants unlink, and a deleted
audit log costs reversibility (both --undo and the daily caps read through it), not
merely quota. The executor appends to a PRE-CREATED per-client file instead, and setgid
on log/ is what makes host-created files inherit gid %(gid)d — without it, 0660 grants
the wrong group and uid %(uid)d falls through to `other`. Create missing per-client logs
with:

    migrate-governance.py --bootstrap-logs --apply
```

- [ ] **Step 10: Update the README to the identical layout**

`infra/hermes-agent/README.md:896-898` currently reads:

```bash
sudo chgrp -R 10000 "$HERMES_GOVERNANCE_DIR"
sudo chmod -R g+rX "$HERMES_GOVERNANCE_DIR"
sudo chmod -R g+w  "$HERMES_GOVERNANCE_DIR"/log
```

Replace with:

```bash
sudo chgrp -R 10000 "$HERMES_GOVERNANCE_DIR"
sudo chmod -R g+rX "$HERMES_GOVERNANCE_DIR"
sudo chmod g+s "$HERMES_GOVERNANCE_DIR"/log
sudo find "$HERMES_GOVERNANCE_DIR"/log -type f -name '*.jsonl' -exec chmod 0660 {} +
```

Immediately below it, replace the paragraph beginning "`log/` only — `seen/` is not mounted" with:

    `log/` gets **no group write**. Write on a directory is what grants `unlink`, and
    both the undo path and the daily caps read through `iter_log_records`, so an
    executor that can delete `log/<slug>.jsonl` destroys the reversibility record — not
    merely a quota. It appends to a **pre-created** per-client file instead; `setgid` on
    `log/` is what makes those files inherit gid 10000, without which `0660` grants the
    operator's own group and uid 10000 falls through to `other`.

    Create the per-client logs — required for every registered client, and idempotent:

        infra/hermes-agent/bin/migrate-governance.py --bootstrap-logs            # dry run
        infra/hermes-agent/bin/migrate-governance.py --bootstrap-logs --apply

    `seen/` is not mounted into the executor at all and needs no access for uid 10000.
    Widening it would hand the governed party the replay-protection state again.

(Render the indented block above as normal Markdown prose and a fenced `bash` block; the indentation here only keeps it out of this plan's own code fences.)

- [ ] **Step 11: Record why the compose mount is unchanged**

At `infra/hermes-agent/docker-compose.yml:97` the mount stays read-write. Extend the comment block immediately above it (`:92-96`) with:

```yaml
      # S3-b: this mount stays rw and that is CORRECT — what changed is the HOST mode.
      # log/ is 2750 host-owned, so the container's rw mount grants append to the
      # pre-created 0660 per-client file and nothing else: no create, no unlink. Do not
      # "fix" this to :ro — append_log would fail mid-apply, which is exit 3 after a
      # live account change.
```

- [ ] **Step 12: Run both full suites**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -5; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "node exit: $rc"
```

Expected: 25/25 exit 0, and 22/22 exit 0.

- [ ] **Step 13: Commit**

```bash
cd /Users/ericksicard/Projects/claude_code
git add infra/hermes-agent/bin/preflight-governance-access.py \
        infra/hermes-agent/bin/preflight-governance-access.test.py \
        infra/hermes-agent/README.md \
        infra/hermes-agent/docker-compose.yml
git commit -m "$(cat <<'MSG'
fix(hermes): require read+traverse on log/, not write (S3-b 1 of 4)

Directory write is what grants unlink, so a log/ the executor can write is a
log/ it can delete — and both the undo path and the caps path read through
iter_log_records, so that costs reversibility, not merely quota.

check() now asks _check_dir for read+traverse on log/. The file-level check
added by R19 already requires write on log/<slug>.jsonl, which is where the
requirement actually belongs: append_log opens the FILE with mode "a" and then
fsyncs the DIRECTORY fd via os.open(dirname, O_RDONLY), so r-x is exactly
right and traverse alone would not be enough.

The fixtures move to 2750 first, which reds the positive control against the
un-inverted gate — R24(a) reproduced inside the suite rather than asserted.
test_read_only_store_flags_only_the_writable_directories is rewritten rather
than deleted: its intent moves to the file-level axis that now carries it,
with a positive control. A second test records the honest negative that a 0770
log/ still passes, because this gate checks that the executor CAN work, not
that it is minimally privileged.

REMEDY and the README drop `chmod -R g+w log` for setgid + per-file 0660 and
stay verbatim-identical, because the pre-flight PRINTS the remedy when it
refuses — a remedy out of step with the docs teaches operators to rebuild the
hole.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 2: Registration bootstrap

Change (2). There is no programmatic client-registration hook — `clients.json` is hand-edited — so per R23 the bootstrap rides the existing `migrate-governance.py`, as a separate mode (spec D3).

**Files:**
- Modify: `infra/hermes-agent/bin/governance_lib.py:20` (add the executor identity constants)
- Modify: `infra/hermes-agent/bin/preflight-governance-access.py:27-28` (alias them)
- Modify: `infra/hermes-agent/bin/migrate_governance_shim.py:27` (imports), new `bootstrap_logs`, `:133`
- Modify: `infra/hermes-agent/bin/migrate-governance.py:10-26`
- Modify: `infra/hermes-agent/bin/migrate-governance.test.py:1-3` (imports), new test class

**Interfaces:**
- Consumes: the `0o2750` / `0o660` layout established in Task 1.
- Produces:
  - `governance_lib.EXECUTOR_UID = 10000`, `governance_lib.EXECUTOR_GID = 10000`, `governance_lib.LOG_DIR_MODE = 0o2750`, `governance_lib.LOG_FILE_MODE = 0o660`
  - `migrate_governance_shim.bootstrap_logs(governance_root, dry_run=False, expected_gid=None) -> {"created": [str], "skipped": [str]}`, raising `RuntimeError` on a missing `log/`, an unparseable registry, a non-conforming slug, or a file that lands with the wrong gid or mode
  - CLI: `migrate-governance.py --bootstrap-logs [--apply] [--governance-root PATH]`

- [ ] **Step 1: Write the failing tests for `bootstrap_logs`**

First extend the imports at `migrate-governance.test.py:1-3` to:

```python
import importlib.util, json, os, shutil, stat, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migrate_governance_shim as M  # see Step 3 note on the module name


def _load_cli():
    """migrate-governance.py has a hyphen in its name, so it cannot be imported —
    the same loader idiom preflight-governance-access.test.py uses."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "migrate_governance_cli", os.path.join(here, "migrate-governance.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

Then append this class **above** the trailing `unittest.main()`:

```python
class TestBootstrapLogs(unittest.TestCase):
    """S3-b: every REGISTERED client must be guaranteed a pre-created log, or a missing
    log stays ambiguous between 'never used' and 'deleted'."""

    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.makedirs(os.path.join(self.gov, "registry"))
        os.makedirs(os.path.join(self.gov, "log"), mode=0o2750)
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            json.dump({"clients": {
                "acme-dental": {"customer_id": "1234567890", "status": "active"},
                "other-clinic": {"customer_id": "9998887776", "status": "dormant_pilot"},
            }}, f)

    def _log(self, slug):
        return os.path.join(self.gov, "log", "%s.jsonl" % slug)

    def test_dry_run_creates_nothing(self):
        res = M.bootstrap_logs(self.gov, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])
        self.assertFalse(os.path.exists(self._log("acme-dental")))
        self.assertFalse(os.path.exists(self._log("other-clinic")))

    def test_apply_creates_one_empty_log_per_registered_client_at_0660(self):
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])
        for slug in ("acme-dental", "other-clinic"):
            st = os.stat(self._log(slug))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o660, slug)
            self.assertEqual(st.st_size, 0, slug)

    def test_an_existing_log_is_skipped_and_left_byte_identical(self):
        """THE load-bearing idempotency test. A bootstrap that opened the file with mode
        'w' would truncate exactly the reversibility record this wave exists to protect,
        and an existence-only assertion would call that a pass."""
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        with open(self._log("acme-dental"), "w") as f:
            f.write('{"status": "applied", "ts": "2026-09-04T00:00:00Z", '
                    '"changeset_id": "20260904-000000-abcd1234"}\n')
        with open(self._log("acme-dental"), "rb") as f:
            before = f.read()
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["skipped"]), ["acme-dental", "other-clinic"])
        self.assertEqual(res["created"], [])
        with open(self._log("acme-dental"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_a_missing_log_directory_refuses_rather_than_creating_it(self):
        """Creating log/ here would lay it down at the wrong mode and produce exactly
        the unusable store the pre-flight exists to catch."""
        shutil.rmtree(os.path.join(self.gov, "log"))
        with self.assertRaises(RuntimeError) as cm:
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertIn("log", str(cm.exception))

    def test_a_file_landing_with_the_wrong_group_refuses(self):
        """THE D4 HAZARD as an executable test. log/ without setgid gives new files the
        creating user's primary group; 0660 then grants the WRONG group and uid 10000
        falls through to `other` — a layout that passes a delete probe and fails the
        append control. A bootstrap that only created the file would report success on a
        log the executor cannot use. Forced here by asking for a gid this process cannot
        produce, which needs no root."""
        with self.assertRaises(RuntimeError) as cm:
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid() + 4242)
        self.assertIn("group", str(cm.exception))
        self.assertFalse(os.path.exists(self._log("acme-dental")),
                         "a file that failed verification must not be left behind")

    def test_control_the_same_call_with_the_real_gid_succeeds(self):
        """POSITIVE CONTROL for the test above — without it, that refusal would also
        pass against a bootstrap that refused everything."""
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])

    def test_an_unparseable_registry_refuses(self):
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            f.write("{not json")
        with self.assertRaises(RuntimeError):
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())

    def test_cli_dry_run_then_apply(self):
        import governance_lib
        CLI = _load_cli()
        real = governance_lib.EXECUTOR_GID
        governance_lib.EXECUTOR_GID = os.getgid()
        self.addCleanup(setattr, governance_lib, "EXECUTOR_GID", real)
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov]), 0)
        self.assertFalse(os.path.exists(self._log("acme-dental")))
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov, "--apply"]), 0)
        self.assertTrue(os.path.isfile(self._log("acme-dental")))

    def test_cli_returns_2_on_a_missing_log_directory(self):
        CLI = _load_cli()
        shutil.rmtree(os.path.join(self.gov, "log"))
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov, "--apply"]), 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 migrate-governance.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -25; echo "exit: $rc"
```

Expected: FAIL, nine errors, each `AttributeError: module 'migrate_governance_shim' has no attribute 'bootstrap_logs'` (the two CLI tests fail on the missing `--bootstrap-logs` argument instead).

- [ ] **Step 3: Add the executor identity constants to `governance_lib.py`**

`preflight-governance-access.py:27-28` defines `EXECUTOR_UID`/`EXECUTOR_GID` and the shim now needs them too. Following `6645879` — which unified `REQUEST_ID_RE` into `governance_lib` for exactly this reason — put one definition there. After `CHANGESET_ID_RE` at `governance_lib.py:20`, add:

```python
# The one-shot executor's identity and the audit-log layout it requires. ONE definition,
# shared, so preflight-governance-access.py and migrate_governance_shim.py cannot drift —
# the rule 6645879 applied to REQUEST_ID_RE, for the same reason.
EXECUTOR_UID = 10000            # Dockerfile: USER hermes
EXECUTOR_GID = 10000
# log/ is setgid and NOT group-writable: directory write is what grants unlink, and
# setgid is what makes host-created log files inherit EXECUTOR_GID.
LOG_DIR_MODE = 0o2750
LOG_FILE_MODE = 0o660
```

Then in `preflight-governance-access.py`, replace `:27-28` with:

```python
EXECUTOR_UID = governance_lib.EXECUTOR_UID
EXECUTOR_GID = governance_lib.EXECUTOR_GID
```

Confirm `governance_lib` is imported above that point before editing:

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
grep -n '^import\|^from\|governance_lib' preflight-governance-access.py | head
```

If the import sits below line 28, move the two assignments below the import rather than moving the import above the module docstring.

- [ ] **Step 4: Implement `bootstrap_logs`**

Extend `migrate_governance_shim.py`'s imports at `:27` to:

```python
import json, os, shutil, stat, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib
```

Then add this function after `_atomic_copy` and before `migrate`:

```python
def bootstrap_logs(governance_root, dry_run=False, expected_gid=None):
    """Guarantee every REGISTERED client a pre-created audit log.

    S3-b's second half. Under the append-but-not-unlink layout the executor cannot
    CREATE log/<slug>.jsonl — log/ is host-owned 2750 — so a missing log is no longer a
    normal resting state for a registered client, and iter_log_records fails closed on
    it. That is only safe once every registered client is guaranteed a log, and there is
    no programmatic registration hook: clients.json is hand-edited, and migrate() only
    carries logs that ALREADY exist in a vault. Hence this rides the same operator CLI
    (ruling R23), as a separate mode rather than folded into migrate(): migration is a
    one-time vault->store move, registration is continuous, and the pre-flight's refusal
    has to name a command an operator can run right after editing the registry.

    Three properties this must have, each earned:

    1. It REFUSES a missing log/ rather than creating one. _ensure_dir would lay it down
       at 0700, producing exactly the unusable store the pre-flight exists to catch.
    2. Creation is O_CREAT|O_EXCL, never open(p, "w"). Truncation would destroy the
       reversibility record this whole wave protects, and an existence-only idempotency
       check would call that a pass.
    3. It VERIFIES what it created and refuses on a mismatch. log/ without its setgid
       bit gives a new file the creating user's primary group; 0660 then grants the
       wrong group and uid 10000 falls through to `other`, so the executor can neither
       append nor unlink. That layout passes a delete probe and fails an append control
       — it looks like a fix. Creating the file is not evidence; stat'ing it is.
    """
    if expected_gid is None:
        expected_gid = governance_lib.EXECUTOR_GID
    log_dir = os.path.join(governance_root, "log")
    if not os.path.isdir(log_dir):
        raise RuntimeError(
            "no log directory at %s — refusing to create it, because a log/ laid down "
            "here would get the wrong mode and produce a store the executor cannot use. "
            "Create it host-side at mode %04o (see the README's ownership section) and "
            "re-run." % (log_dir, governance_lib.LOG_DIR_MODE))

    reg = os.path.join(governance_root, "registry", "clients.json")
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(
            "cannot read the client registry at %s (%s) — refusing, because a registry "
            "that will not parse resolves no client, and reading it as 'zero registered "
            "clients' would report success over a store that cannot work" % (reg, e))
    # WITH the default, matching vault_lib.load_registry:49 — an absent "clients" key is
    # zero registered clients, not a malformed registry.
    clients = data.get("clients", {}) if isinstance(data, dict) else None
    if not isinstance(clients, dict):
        raise RuntimeError("registry 'clients' must be a JSON object: %s" % reg)

    result = {"created": [], "skipped": []}
    for slug in sorted(clients):
        if not isinstance(slug, str) or not governance_lib.SLUG_RE.fullmatch(slug):
            raise RuntimeError(
                "registry contains a slug that is not resolvable (%r) — refusing rather "
                "than skipping it, because a skipped registration is exactly the "
                "ambiguity this function exists to remove" % (slug,))
        dst = os.path.join(log_dir, "%s.jsonl" % slug)
        if os.path.exists(dst):
            result["skipped"].append(slug)
            continue
        if dry_run:
            result["created"].append(slug)
            continue
        fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     governance_lib.LOG_FILE_MODE)
        os.close(fd)
        try:
            os.chmod(dst, governance_lib.LOG_FILE_MODE)   # defeat the umask
            st = os.stat(dst)
            mode = stat.S_IMODE(st.st_mode)
            if mode != governance_lib.LOG_FILE_MODE:
                raise RuntimeError(
                    "%s landed at mode %04o, not %04o — refusing"
                    % (dst, mode, governance_lib.LOG_FILE_MODE))
            if st.st_gid != expected_gid:
                raise RuntimeError(
                    "%s landed with group %d, not the executor's group %d — refusing. "
                    "log/ is almost certainly missing its setgid bit, without which a "
                    "new file inherits the creating user's primary group and mode %04o "
                    "grants the WRONG group: uid %d then falls through to `other` and "
                    "can neither append nor unlink. Run `chmod g+s %s` and re-run."
                    % (dst, st.st_gid, expected_gid, governance_lib.LOG_FILE_MODE,
                       governance_lib.EXECUTOR_UID, log_dir))
        except Exception:
            os.remove(dst)      # created by THIS call; never remove a pre-existing log
            raise
        result["created"].append(slug)
    return result
```

- [ ] **Step 5: Correct `migrate()`'s log directory mode**

`migrate_governance_shim.py:133` calls `_ensure_dir(dst_log_dir)`, which creates `log/` at `0700` — wrong for this layout, so a fresh migration would lay down a store the executor cannot use. Change it to:

```python
        _ensure_dir(dst_log_dir, mode=governance_lib.LOG_DIR_MODE)
```

`_ensure_dir` leaves a pre-existing directory alone by design (its docstring explains the retry tests depend on that), so this affects only stores where `migrate()` creates `log/` itself.

- [ ] **Step 6: Add the CLI mode**

Replace the body of `main` in `migrate-governance.py`:

```python
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-root", default=None)
    ap.add_argument("--governance-root", default=None)
    ap.add_argument("--bootstrap-logs", action="store_true",
                    help="pre-create a log for every REGISTERED client instead of "
                         "migrating; idempotent, and required after any hand-edit to "
                         "clients.json")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it this is a dry run")
    args = ap.parse_args(argv)
    gov = args.governance_root or governance_lib.governance_root()
    try:
        if args.bootstrap_logs:
            res = M.bootstrap_logs(gov, dry_run=not args.apply)
        else:
            res = M.migrate(args.vault_root or vault_lib.vault_root(), gov,
                            dry_run=not args.apply)
    except (OSError, RuntimeError) as e:
        print("migrate-governance: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0
```

`--bootstrap-logs` ignores `--vault-root` deliberately: the registry it reads lives in the governance store, and resolving a vault root it does not need would refuse for an irrelevant reason.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 migrate-governance.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

Expected: PASS (`OK`), 20 tests — 11 before, 9 added.

- [ ] **Step 8: Mutation proofs**

Two mutants, run and reverted one at a time:

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cp migrate_governance_shim.py /tmp/shim.orig

# --- Mutant A: drop the gid verification ---
python3 - <<'PY'
import io
p = "migrate_governance_shim.py"
s = io.open(p).read()
old = "            if st.st_gid != expected_gid:"
assert s.count(old) == 1, "gid check not found exactly once"
io.open(p, "w").write(s.replace(old, "            if False:"))
PY
python3 -c "import ast; ast.parse(open('migrate_governance_shim.py').read())" && echo "mutant A parses"
out=$(python3 migrate-governance.test.py 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | sort; echo "mutant A exit: $rc"
cp /tmp/shim.orig migrate_governance_shim.py

# --- Mutant B: truncating create instead of O_EXCL ---
python3 - <<'PY'
import io
p = "migrate_governance_shim.py"
s = io.open(p).read()
old = ("        fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY,\n"
       "                     governance_lib.LOG_FILE_MODE)\n        os.close(fd)")
assert s.count(old) == 1, "create call not found exactly once"
io.open(p, "w").write(s.replace(old, "        open(dst, 'w').close()"))
PY
python3 -c "import ast; ast.parse(open('migrate_governance_shim.py').read())" && echo "mutant B parses"
out=$(python3 migrate-governance.test.py 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | sort; echo "mutant B exit: $rc"
cp /tmp/shim.orig migrate_governance_shim.py && rm /tmp/shim.orig
```

Expected: mutant A reds `test_a_file_landing_with_the_wrong_group_refuses`. Mutant B is the subtle one — `open(dst,'w')` is only reached when the file does not already exist, so it reds via the umask path (`0644` instead of `0660`) in `test_apply_creates_one_empty_log_per_registered_client_at_0660`. Report both sorted failing-set differences. **If either mutant reds nothing, chase it** — an inert mutation is a coverage claim, not a pass. In particular, if mutant B is inert, the `assert` guards above did not match and the mutation never applied.

- [ ] **Step 9: Run both full suites and commit**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -5; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "node exit: $rc"
git add infra/hermes-agent/bin/governance_lib.py \
        infra/hermes-agent/bin/preflight-governance-access.py \
        infra/hermes-agent/bin/migrate_governance_shim.py \
        infra/hermes-agent/bin/migrate-governance.py \
        infra/hermes-agent/bin/migrate-governance.test.py
git commit -m "$(cat <<'MSG'
feat(hermes): pre-create a log for every registered client (S3-b 2 of 4)

Under the append-but-not-unlink layout the executor cannot CREATE
log/<slug>.jsonl, so a missing log stops being a normal resting state for a
registered client — which is what lets iter_log_records fail closed on it in
the next commit. There is no programmatic registration hook (clients.json is
hand-edited, and migrate() only carries logs that already exist in a vault),
so per R23 this rides migrate-governance.py, as a separate --bootstrap-logs
mode: migration is a one-time vault->store move, registration is continuous,
and the pre-flight's refusal must name a command an operator can run right
after editing the registry.

Three properties, each earned rather than assumed:
  * refuses a missing log/ instead of creating it — _ensure_dir would lay it
    down at 0700, the unusable store the pre-flight exists to catch;
  * O_CREAT|O_EXCL, never open(p,"w") — truncation would destroy the record
    this wave protects, and an existence-only idempotency check would pass it;
  * stats what it created and refuses on a wrong gid or mode. log/ without
    setgid gives a new file the creating user's primary group; 0660 then
    grants the wrong group and uid 10000 falls through to `other`, so the
    executor can neither append nor unlink — a layout that passes a delete
    probe and fails an append control. Creating the file is not evidence.

EXECUTOR_UID/GID and the log modes move to governance_lib as one definition,
the rule 6645879 applied to REQUEST_ID_RE. migrate()'s own _ensure_dir call
learns the new log/ mode so a fresh migration cannot lay down the old one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 3: Pre-flight refuses a registered client with no log

Spec D2. `iter_log_records` alone catches this **mid-apply**; R19 exists so a store the executor cannot use is caught at startup instead, before a live account change can land.

**Files:**
- Modify: `infra/hermes-agent/bin/preflight-governance-access.py` (new `_check_registered_logs`, called from `check()`)
- Modify: `infra/hermes-agent/bin/preflight-governance-access.test.py` (new test class)

**Interfaces:**
- Consumes: `governance_lib.SLUG_RE`, `governance_lib.clients_registry_path(root)`, `governance_lib.LOG_DIR_MODE` (Task 2), and the `--bootstrap-logs` CLI (named in the refusal text).
- Produces: no new public names; `check()` keeps its signature and its `list[str]` return.

- [ ] **Step 1: Write the failing tests**

Append to `preflight-governance-access.test.py`, above the trailing `unittest.main()`:

```python
class TestRegisteredClientLogs(Base):
    """S3-b/D2. Under the append-but-not-unlink layout the executor cannot CREATE
    log/<slug>.jsonl, so a registered client with no log is a store it cannot use —
    R19's own class of finding, and R19 exists so that surfaces at startup rather than
    mid-apply as exit 3 after a live account change."""

    def _write_registry(self, text):
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        with open(reg, "w") as f:
            f.write(text)
        os.chmod(reg, 0o640)

    def _healthy_dirs(self):
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)

    def test_a_registered_client_without_a_log_is_refused(self):
        self._healthy_dirs()
        self._write_registry('{"clients": {"acme-dental": {"status": "active"}}}')
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("--bootstrap-logs", problems[0])

    def test_control_the_same_registry_with_the_log_present_is_healthy(self):
        """POSITIVE CONTROL. Without it the refusal above would also pass against a
        check that refused every store with a non-empty registry."""
        self._healthy_dirs()
        self._write_registry('{"clients": {"acme-dental": {"status": "active"}}}')
        p = os.path.join(self.root, "log", "acme-dental.jsonl")
        with open(p, "w"):
            pass
        os.chmod(p, 0o660)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_the_refusal_names_a_count_not_the_slugs(self):
        """Client slugs are client-private and this text reaches stderr, which the
        systemd journal captures under Phase B. vault_lib.resolve_dormant_pilot makes
        the same choice for the same reason."""
        self._healthy_dirs()
        self._write_registry(
            '{"clients": {"acme-dental": {"status": "active"}, '
            '"other-clinic": {"status": "dormant_pilot"}}}')
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("2", problems[0])
        self.assertNotIn("acme-dental", problems[0])
        self.assertNotIn("other-clinic", problems[0])

    def test_an_unparseable_registry_is_refused(self):
        self._healthy_dirs()
        self._write_registry("{not json")
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertTrue(any("registry" in p for p in problems))

    def test_an_absent_registry_is_not_a_fault(self):
        """Absence stays absence. _check_file already treats a missing registry as the
        normal resting state of a fresh store, and this check must not change that —
        turning a fresh store into a refusal is R19b's cry-wolf failure."""
        self._healthy_dirs()
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_an_empty_registry_requires_nothing(self):
        self._healthy_dirs()
        self._write_registry('{"clients": {}}')
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -25; echo "exit: $rc"
```

Expected: FAIL on exactly three — `test_a_registered_client_without_a_log_is_refused`, `test_the_refusal_names_a_count_not_the_slugs`, and `test_an_unparseable_registry_is_refused` — each getting `[]` and asserting against it. The three "not a fault" tests already pass; they are the guard rails and must **stay** green through Step 3.

- [ ] **Step 3: Implement the check**

Add to `preflight-governance-access.py`, immediately before `check()`:

```python
def _check_registered_logs(root):
    """Every REGISTERED client must have a pre-created audit log (S3-b).

    log/ is host-owned 2750, so the executor cannot create log/<slug>.jsonl — append_log
    opens it with mode "a", which creates, and that now fails with EACCES. Catching it
    only in iter_log_records surfaces it MID-APPLY, and R19 exists precisely so a store
    the executor cannot use is refused at startup instead: mid-apply is exit 3 after a
    live account change, while a startup refusal costs one idempotent command.

    This is NOT R19b's over-checking. Every false refusal in that lineage — the
    .approval.lock sidecar, a rotated log, an operator's backup — was this gate demanding
    access to a file the executor never opens, from a requirement list written from
    memory. This requirement is the inverse: log/<slug>.jsonl for a registered slug is
    the one file the executor certainly opens, and it is DERIVED from the same
    clients.json vault_lib.resolve already gates on, never from a listing of log/. Files
    in log/ that no registered slug names stay ignored, exactly as before.

    A MISSING registry is not a fault — _check_file already treats it as the normal
    resting state of a fresh store, and turning that into a refusal is the cry-wolf
    failure. An UNPARSEABLE one is: no client resolves through it, so "zero registered
    clients" would be a silent pass over a store that cannot work at all.

    The message carries a COUNT, never the slugs. Client slugs are client-private, this
    text goes to stderr, and the systemd journal captures stderr under Phase B —
    vault_lib.resolve_dormant_pilot refuses to name candidates for the same reason.
    """
    reg = governance_lib.clients_registry_path(root)
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        return ["%s: unreadable or malformed client registry (%s) — refusing, because a "
                "registry that will not parse resolves no client, and reading it as "
                "'zero registered clients' would pass a store that cannot work" % (reg, e)]
    # data.get("clients", {}) — WITH the default, matching vault_lib.load_registry:49
    # exactly. An ABSENT "clients" key means zero registered clients, which is how
    # load_registry already reads it; only a PRESENT but non-object "clients" is a fault.
    # Dropping the default here would return None for a registry of "{}" and refuse it —
    # reding the very controls this check is supposed to leave untouched, since
    # _configure_full_correct_store writes exactly that.
    clients = data.get("clients", {}) if isinstance(data, dict) else None
    if not isinstance(clients, dict):
        return ["%s: registry 'clients' must be a JSON object" % reg]

    missing = 0
    for slug in clients:
        if not isinstance(slug, str) or not governance_lib.SLUG_RE.fullmatch(slug):
            continue        # vault_lib.resolve would refuse it; not this gate's call
        if not os.path.isfile(os.path.join(root, "log", "%s.jsonl" % slug)):
            missing += 1
    if not missing:
        return []
    return ["%s/log: %d registered client(s) have no pre-created audit log. The executor "
            "cannot create one (log/ is host-owned %04o by design), so this surfaces "
            "mid-apply as exit 3 after a live account change. Fix with: "
            "migrate-governance.py --bootstrap-logs --apply"
            % (root, missing, governance_lib.LOG_DIR_MODE)]
```

Call it from `check()`, immediately before the final `return problems`:

```python
    problems.extend(_check_approvals(root, uid, gid))
    problems.extend(_check_registered_logs(root))

    return problems
```

Confirm `json` and `governance_lib` are both imported in this module, and add `json` to the import line if it is absent:

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
grep -n '^import\|^from\|governance_lib' preflight-governance-access.py | head
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

Expected: PASS (`OK`), **38** tests — 32 from Task 1, plus 6.

- [ ] **Step 5: Confirm the pre-existing controls did not move**

The spec's central claim is that this check costs the existing suite nothing, because `_configure_full_correct_store` writes the registry as the literal `"{}"` (`:143`) and `load_registry` therefore sees zero clients. Verify rather than assume:

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 preflight-governance-access.test.py -v 2>&1); rc=$?
printf '%s\n' "$out" | grep -E 'fresh_store_with_correct_dirs|fully_correct_store'
echo "exit: $rc"
```

Expected: `test_fresh_store_with_correct_dirs_and_no_files_is_healthy ... ok` and `test_control_fully_correct_store_including_files_is_healthy ... ok`. **If either reds, the spec's claim was wrong — stop and report it** rather than adjusting the fixture to fit the check.

- [ ] **Step 6: Mutation proof**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cp preflight-governance-access.py /tmp/pf.orig
python3 - <<'PY'
import io
p = "preflight-governance-access.py"
s = io.open(p).read()
old = "    problems.extend(_check_registered_logs(root))\n"
assert s.count(old) == 1, "call site not found exactly once"
io.open(p, "w").write(s.replace(old, ""))
PY
python3 -c "import ast; ast.parse(open('preflight-governance-access.py').read())" && echo "mutant parses"
out=$(python3 preflight-governance-access.test.py 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | sort; echo "mutant exit: $rc"
cp /tmp/pf.orig preflight-governance-access.py && rm /tmp/pf.orig
```

Expected: reds exactly `test_a_registered_client_without_a_log_is_refused`, `test_the_refusal_names_a_count_not_the_slugs`, and `test_an_unparseable_registry_is_refused`, leaving the three "not a fault" tests green. Report the sorted failing-set difference.

- [ ] **Step 7: Run both full suites and commit**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -5; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "node exit: $rc"
git add infra/hermes-agent/bin/preflight-governance-access.py \
        infra/hermes-agent/bin/preflight-governance-access.test.py
git commit -m "$(cat <<'MSG'
fix(hermes): refuse at startup when a registered client has no log (S3-b 3 of 4)

log/ is host-owned 2750, so the executor cannot create log/<slug>.jsonl.
Catching that only in iter_log_records surfaces it mid-apply — exit 3 after a
live account change — and R19 exists precisely so a store the executor cannot
use is refused at startup instead, where the cost is one idempotent command.

Not R19b's over-checking. Every false refusal in that lineage was this gate
demanding access to a file the executor never opens, from a requirement list
written from memory. This one is derived from the same clients.json that
vault_lib.resolve already gates on, and log/ is still never listed, so an
unknown file there stays ignored.

A missing registry stays not-a-fault; an unparseable one is refused, because
"zero registered clients" would otherwise silently pass a store where nothing
resolves. The message carries a COUNT, never slugs — this text reaches stderr
and the journal captures it under Phase B.

Costs the existing suite nothing, verified rather than assumed: the fixture
writes the registry as "{}", so zero clients are registered and both the
fresh-store and fully-correct-store controls stay green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 4: A missing log fails closed

Change (4) — the point of the other three. Measured blast radius from R24(b): ~30 tests, including the plain happy path.

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py:604-611` (stale comment), `:889-942` (`iter_log_records`)
- Modify: whichever tests rely on an absent log — found by running, not guessed

**Interfaces:**
- Consumes: `bootstrap_logs` from Task 2 (used to build fixtures through the real path).
- Produces: `iter_log_records(slug)` raises `ValueError` on a missing log. Both production callers already catch `ValueError` and `_refuse` (`apply-changeset.py:147`, `:214`), so no caller changes.

- [ ] **Step 1: Make the change and let the suite tell you the blast radius**

In `changeset_lib.py`, `iter_log_records`'s body at `:940-942` currently reads:

```python
    p = log_path(slug)
    if not os.path.exists(p):
        return                              # NOT fail-closed — see the docstring above
```

Replace with:

```python
    p = log_path(slug)
    if not os.path.exists(p):
        raise ValueError(
            f"missing audit log at {p} — fail-closed. Every registered client is "
            f"guaranteed a pre-created log by `migrate-governance.py --bootstrap-logs "
            f"--apply`, so an absent one is either an unbootstrapped registration or a "
            f"DELETED reversibility record. Neither may read as 'no usage yet': that "
            f"would take the daily caps from exhausted back to zero and the undo list "
            f"from populated to empty.")
```

**Careful:** `changeset_lib.py` has *two* lines reading `return  # NOT fail-closed` — `:680` in `iter_seen_records` and `:942` here. Change only `:942`. `:680` is deliberately left open (see Step 6) and is out of scope.

- [ ] **Step 2: Run every suite and capture the full failing set**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?
printf '%s\n' "$out"; echo "exit: $rc"
```

Expected: FAIL. R24(b) measured ~30 tests red across `changeset_lib.test.py` and `apply-changeset.test.py`, including the plain happy path. Record the exact sorted list — it is the input to Step 3 and the evidence that this half genuinely needed the other three.

- [ ] **Step 3: Regenerate the affected fixtures through the real code path**

For each failing test, the fix is to give the client a log **before** the code under test reads one. Do **not** hand-write the file.

- Where the test needs an *empty* log (a client that has never applied), create it the way the deploy does:

```python
        import migrate_governance_shim as M
        M.bootstrap_logs(GOV_ROOT, dry_run=False, expected_gid=os.getgid())
```

where `GOV_ROOT` is whatever that suite already calls its governance root — `self.tmp` in
`apply-changeset.test.py` (set as `HERMES_GOVERNANCE_ROOT` in `setUp`), `self.gov` or
`self.root` in `changeset_lib.test.py` depending on the class. Do not introduce a new
name for it.

- Where the test needs a *populated* log, append through the production writer:

```python
        C.append_log("acme-dental", {"status": "applied",
                                     "ts": "2026-09-04T00:00:00Z",
                                     "changeset_id": "20260904-000000-abcd1234"})
```

**This is not a style preference.** A hand-written fixture whose format is subtly wrong makes the guard refuse *for the wrong reason*; every "a refusal happened" assertion still passes, and the suite proves nothing while green.

Where a test's whole point is that no log exists, invert its assertion to expect the refusal rather than papering over it, and say so in its docstring.

- [ ] **Step 4: Run the suites to verify they pass**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

Expected: PASS, 25/25, exit 0.

- [ ] **Step 5: Prove the refusal reaches BOTH callers as a refusal, not a traceback**

Spec D6 claims both call sites already handle this. Assert it rather than trusting it, on
each path separately — `day_counts` (`apply-changeset.py:147`) and `_undo_targets`
(`:214`) are different branches, and a fix that covered only one would leave the other
raising.

`apply-changeset.test.py` already has the harness: `self._applied(n=1)` runs a change-set
through to an applied state (which creates the log via `append_log`), `self.tmp` is the
governance root, the slug is the literal `"acme-dental"`, and `self._assert_refused(cs_id,
because=...)` asserts `SystemExit` with code **2**, that no live call was made, and that
the named guard is the one that refused. Exit 2 is the governed refusal; an uncaught
`ValueError` would be exit 1 with a traceback, so `_assert_refused` *is* the "clean
refusal, not a traceback" assertion. Do not introduce a new harness.

Add both tests to the class that owns `_applied`:

```python
    def test_a_missing_log_refuses_cleanly_on_the_caps_path(self):
        """S3-b/D6, guard 6. iter_log_records now raises ValueError on a missing log,
        and day_counts' call site already wraps it in `except ValueError -> _refuse`.
        Asserted rather than trusted: an uncaught ValueError would be exit 1 with a
        traceback instead of a governed exit-2 refusal, which is a materially different
        failure for the broker to read."""
        self._applied()                                   # creates the log via append_log
        os.remove(C.log_path("acme-dental"))
        nxt = self._approved()
        self._assert_refused(nxt["changeset_id"], because="missing audit log")

    def test_a_missing_log_refuses_cleanly_on_the_undo_path(self):
        """The other call site. _undo_targets reads through the same generator, and
        _assert_refused cannot drive the undo path (it takes no undo argument), so this
        makes the same assertions inline."""
        cs = self._applied()
        os.remove(C.log_path("acme-dental"))
        err = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(err):
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("missing audit log", err.getvalue())
        self.assertEqual(self._calls(), [])
```

`io` and `contextlib` are already imported at `apply-changeset.test.py:1`.

- [ ] **Step 6: Correct the two stale comment blocks**

These are load-bearing, not tidying: R19 recorded a stale docstring as the root cause of its own defect, and an independent automated commit security review already flagged `78db7e9` on exactly this state.

In `iter_log_records`'s docstring, delete the paragraph beginning `A MISSING LOG IS THE ONE EXCEPTION, AND IT IS NOT COVERED (S3-b, ruling R22).` through `...migrate-governance.py only carries logs that ALREADY exist in a vault.`, and the closing sentence `Until both land together, treat a missing log as UNVERIFIED rather than as zero.` Replace all of it with:

```
    CLOSED BY S3-b. A missing log now RAISES, like every other failure mode here. That
    is only safe because log/ is host-owned 2750 — the executor appends to its
    pre-created file but can neither create nor unlink one — and because
    `migrate-governance.py --bootstrap-logs` guarantees every REGISTERED client a log.
    Both halves were required: the raise alone breaks the first apply for every client
    (R24(b)), and the permission change alone was refused by
    preflight-governance-access.py (R24(a)).
```

At `:604-611`, the comment currently ends `...so an executor that could write log/ could always delete log/<slug>.jsonl outright. It still can — see iter_log_records' docstring for what that costs and why closing it is a two-part change parked for its own wave.` Replace that final sentence with:

```
# delete log/<slug>.jsonl outright. It no longer can: S3-b moved log/ to host-owned
# 2750, so the executor holds append on a pre-created 0660 file and has neither create
# nor unlink on the directory. Per R22 that is measured on Linux and UNMEASURED on the
# VPS — Phase B owns the bind-mount semantics there.
```

Leave `iter_seen_records`' docstring at `:664-677` **unchanged**. Its fail-open is deliberate and its reasoning still holds.

- [ ] **Step 7: Mutation proof**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cp changeset_lib.py /tmp/cl.orig
python3 - <<'PY'
import io, re
p = "changeset_lib.py"
s = io.open(p).read()
new, n = re.subn(
    r"    p = log_path\(slug\)\n    if not os\.path\.exists\(p\):\n        raise ValueError\(\n(?:            .*\n)+?        \)\n",
    "    p = log_path(slug)\n    if not os.path.exists(p):\n        return\n",
    s, count=1)
assert n == 1, "MUTATION DID NOT APPLY — a silent miss would read as an inert mutation"
io.open(p, "w").write(new)
PY
python3 -c "import ast; ast.parse(open('changeset_lib.py').read())" && echo "mutant parses"
grep -n 'if not os.path.exists(p):' -A1 changeset_lib.py
out=$(./run-bin-tests.sh 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '  FAIL'; echo "mutant exit: $rc"
cp /tmp/cl.orig changeset_lib.py && rm /tmp/cl.orig
```

Expected: the `assert` confirms the mutation applied (a silent regex miss would otherwise look like an inert mutation), the mutant parses, the `grep` shows the raise really became a `return`, and the run reds `changeset_lib.test.py` and `apply-changeset.test.py`. Report the sorted failing-set difference.

- [ ] **Step 8: Run both full suites and commit**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -5; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "node exit: $rc"
git add infra/hermes-agent/bin/changeset_lib.py \
        infra/hermes-agent/bin/changeset_lib.test.py \
        infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "$(cat <<'MSG'
fix(hermes): a missing audit log fails closed (S3-b 4 of 4)

iter_log_records returned nothing for a missing log, so a deleted log read as
"under the cap" to day_counts and as "nothing to undo" to _undo_targets — the
exact fail-open its own docstring condemned two paragraphs earlier. It now
raises ValueError like every other failure mode there.

Safe only because of the other three commits: log/ is host-owned 2750 so the
executor can append to its pre-created file but cannot create or unlink one,
and --bootstrap-logs guarantees every registered client a log. Landing this
alone breaks the first apply for every client (R24(b), measured at ~30 tests
including the plain happy path).

No caller changes: both sites already wrap it in `except ValueError ->
_refuse`. A test now asserts that rather than trusting it, because an uncaught
ValueError would be exit 1 with a traceback instead of a governed refusal.

Fixtures were regenerated through bootstrap_logs and append_log, never
hand-written: a subtly wrong fixture makes the guard refuse for the wrong
reason while every "a refusal happened" assertion still passes.

Both stale comment blocks are corrected — R19 recorded a stale docstring as
the root cause of its own defect, and an independent commit security review
already flagged 78db7e9 on this state. iter_seen_records' matching fail-open
is deliberately left: S3-a removed the executor's seen/ mount, so the governed
party cannot reach it. R22's caveat travels with this: measured on Linux,
UNMEASURED on the VPS.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 5: Container probe — the only evidence for the layout

`preflight-governance-access.py` is a deliberate no-op off Linux (`applies()` returns False unless `sys.platform` startswith `linux`). A clean run on macOS **proves nothing** — that exact mistake was made in this project and had to be corrected. The unit tests pass `platform="linux"` explicitly, which covers the *logic*; nothing on darwin covers the *POSIX layout*.

**Files:**
- Create: `docs/evaluations/2026-09-04-s3b-layout-probe.md`

**Interfaces:**
- Consumes: the layout constants from Task 2 and the CLI from Task 2.
- Produces: recorded evidence referenced by the PR body. No code.

- [ ] **Step 1: Confirm the image exists and is the executor's real identity**

```bash
docker images --format '{{.Repository}}:{{.Tag}}' | grep hermes-agent-claude
docker run --rm --entrypoint sh hermes-agent-claude:latest -c 'id hermes; python3 -VV; uname -s'
```

Expected: `hermes-agent-claude:latest` exists; `hermes` is uid 10000; Python 3.13; `Linux`. **`ads-mutator` is the compose service name, not an image** — `docker run` takes the image tag.

- [ ] **Step 2: Run the three-row matrix, each row with both probes**

```bash
cd /Users/ericksicard/Projects/claude_code
docker run --rm --user 0:0 --entrypoint sh hermes-agent-claude:latest -c '
set -u
probe() {
  mode="$1"; gid="$2"; label="$3"
  root=$(mktemp -d)
  mkdir -p "$root/log"
  chmod 0755 "$root"                      # ancestors MUST be traversable, or append
                                          # fails for an irrelevant reason
  chgrp "$gid" "$root/log"
  chmod "$mode" "$root/log"
  : > "$root/log/slug-1.jsonl"
  chgrp "$gid" "$root/log/slug-1.jsonl"
  chmod 0660 "$root/log/slug-1.jsonl"
  if su hermes -s /bin/sh -c "printf x >> $root/log/slug-1.jsonl" 2>/dev/null; then
    append=OK; else append=DENIED; fi
  su hermes -s /bin/sh -c "rm -f $root/log/slug-1.jsonl" 2>/dev/null
  if [ -e "$root/log/slug-1.jsonl" ]; then delete=DENIED; else delete=DELETED; fi
  printf "%-34s append=%-7s delete=%s\n" "$label" "$append" "$delete"
  rm -rf "$root"
}
probe 0770 10000 "0770 (the finding)"
probe 2750 10000 "2750 + gid 10000 (the fix)"
probe 2750 0     "2750 + WRONG gid (D4 hazard)"
'
```

Expected:

| row | append | delete |
|---|---|---|
| `0770` | `OK` | `DELETED` — reproduces the finding |
| `2750`, file gid 10000 | **`OK`** | `DENIED` — the fix |
| `2750`, file gid 0 | `DENIED` | `DENIED` — proves the append control discriminates |

**Row 2's `append=OK` is the load-bearing cell.** A layout where uid 10000 can neither append nor delete looks like a fix and is a broken fixture — row 3 exists to show the control *can* fail, so row 2's success means something.

- [ ] **Step 3: Run the real pre-flight and the real bootstrap inside the container**

```bash
cd /Users/ericksicard/Projects/claude_code
docker run --rm --user 0:0 -v "$PWD/infra/hermes-agent/bin":/bin-ro:ro \
  --entrypoint sh hermes-agent-claude:latest -c '
set -u
build() {
  root=$(mktemp -d); mkdir -p "$root/log" "$root/approvals" "$root/control" "$root/registry"
  chmod 0750 "$root"; chgrp -R 10000 "$root"
  for d in approvals control registry; do chmod 0750 "$root/$d"; done
  chmod "$1" "$root/log"
  printf "{\"clients\": {}}" > "$root/registry/clients.json"
  chmod 0640 "$root/registry/clients.json"
  echo "$root"
}
for mode in 0770 2750; do
  root=$(build "$mode")
  out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
  printf "empty registry, log/ %s -> exit %s\n" "$mode" "$rc"
  printf %s "$out" | head -3
  rm -rf "$root"
done

# The D2 refusal, and then the positive control that the guard still ADMITS.
root=$(build 2750)
printf "{\"clients\": {\"slug-1\": {\"status\": \"active\"}}}" > "$root/registry/clients.json"
chmod 0640 "$root/registry/clients.json"
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "registered, no log -> exit %s (names bootstrap-logs: %s)\n" \
  "$rc" "$(printf %s "$out" | grep -c bootstrap-logs)"
python3 /bin-ro/migrate-governance.py --bootstrap-logs --governance-root "$root" --apply
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "after bootstrap -> exit %s\n" "$rc"
ls -ln "$root/log"
rm -rf "$root"
'
```

Expected, **after** Tasks 1–3: both empty-registry rows exit 0 (`2750` because it is now supported, `0770` because it over-grants — Task 1 Step 6 records that honest negative). Then `registered, no log -> exit 2` with the refusal naming `--bootstrap-logs`, the bootstrap creating `slug-1.jsonl`, `after bootstrap -> exit 0`, and `ls -ln` showing `-rw-rw----` group `10000`.

**The last three lines are the end-to-end positive control** — the guard admits the legitimate case, not merely refuses the illegitimate one. Task 12's seam S4 blessed a seam nobody could get through because it never asked this.

If you run this *before* Task 1, the `2750` row exits 2 with the `read+write+traverse` problem. That is R24(a); record it as the finding rather than adjusting anything.

- [ ] **Step 4: Record the evidence**

Write `docs/evaluations/2026-09-04-s3b-layout-probe.md` containing the image id, the `docker run` commands verbatim, the raw output of Steps 1–3, the three-row matrix as measured, and this closing section:

    ## What this does and does not establish

    Establishes: append-but-not-unlink holds at the OS level for uid 10000 on Linux at
    `2750`/`0660`; the pre-flight admits that layout; the bootstrap produces a file the
    executor can actually append to; and the refuse → bootstrap → admit cycle works end
    to end. The wrong-gid row proves the append control discriminates, so the fix row's
    success is evidence rather than a broken fixture.

    Does NOT establish anything about the VPS. This ran under Docker Desktop, which
    remaps bind-mount ownership. Per R22 no darwin-hosted measurement may be read as
    covering the VPS, whose bind-mount semantics Phase B owns. Nothing here licenses
    describing Phase A as deployed or deployable.

Report any row that came out differently from the table as a **finding**, not as a fixture to adjust. An honest negative beats a contrived positive — twice in this project, an implementer reporting "my proof failed and here is why" produced the session's best findings.

- [ ] **Step 5: Commit**

```bash
cd /Users/ericksicard/Projects/claude_code
git add docs/evaluations/2026-09-04-s3b-layout-probe.md
git commit -m "$(cat <<'MSG'
docs(hermes): record the S3-b layout probe (container-measured)

preflight-governance-access.py is a deliberate no-op off Linux, so a clean
darwin run proves nothing — a mistake made in this project once already. This
ran in hermes-agent-claude:latest as uid 10000, the real executor identity.

Three rows, each with an append control: 0770 reproduces the finding (append
OK, delete DELETED), 2750 with gid 10000 is the fix (append OK, delete
DENIED), and 2750 with a wrong gid fails BOTH, which is what proves the append
control discriminates rather than a layout where nothing works looking like
success.

Also runs the real pre-flight and the real bootstrap end to end inside the
container: refusal naming --bootstrap-logs, then the bootstrap, then exit 0
with the file at 0660 group 10000. That positive control is the half Task 12's
seam S4 omitted when it blessed a seam nobody could pass.

Per R22 this is Linux-under-Docker-Desktop and says nothing about the VPS.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 6: Verification and PR

**Files:** none modified — this task produces the PR.

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: a PR against `main`.

- [ ] **Step 1: Full suites, exit status captured**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?
printf '%s\n' "$out" | tail -4; echo "node exit: $rc"
```

Expected: 25/25 exit 0 and 22/22 exit 0. `cmd | tail` would take its status from `tail` — that has misreported an exit code twice here.

- [ ] **Step 2: Redaction scan, scoped to the diff, paired with a live control**

```bash
cd /Users/ericksicard/Projects/claude_code
git diff main...HEAD > /tmp/s3b.diff
echo "=== scan ==="
grep -nE '[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10}|customers/[0-9]+' /tmp/s3b.diff || echo "no hits"
echo "=== CONTROL (must fire) ==="
printf 'customer 123-456-7890 and 1234567890\n' \
  | grep -nE '[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10}' \
  && echo "CONTROL FIRED — the scan is live" || echo "CONTROL DID NOT FIRE — scan invalid"
```

**Expect hits, and expect them to be fine.** `acme-dental`, `acme`, `other-clinic`, `"1234567890"`, `"9998887776"` and `"9999999999"` are this project's established invented fixtures — 142 and 45 occurrences across 16 tracked suites before this branch. They are not client data. Confirm every hit is one of those and that none is a value taken from a real store; if a hit is anything else, stop.

A scan whose control does not fire proves nothing — that is why the control line is not optional.

- [ ] **Step 3: Confirm the working tree is exactly the pre-existing dirt**

```bash
cd /Users/ericksicard/Projects/claude_code
git status --porcelain | grep -v '^??'
echo "--- tracked-dirty count (expect 5) ---"
git status --porcelain | grep -v '^??' | wc -l
echo "--- untracked count (expect 43) ---"
git status --porcelain | grep '^??' | wc -l
```

Expected: the same 5 tracked and 43 untracked entries the branch started with — `.project-brain/log.md`, two deleted `.project-brain` candidates, two `evals/*.json`, plus `.obsidian/` and the `.project-brain/reports/` set. Nothing from this wave is left unstaged. If a file you do not recognise appears, **inspect it before doing anything with it**: a leftover after an interrupted run is either real work or an unreverted mutation, and committing the latter commits a deliberate bug.

- [ ] **Step 4: Confirm the kill switch is still off**

```bash
test -f ~/.hermes/governance/control/mutation-enabled \
  && echo "PRESENT — MUTATION ENABLED, turn it off" \
  || echo "ABSENT — mutation disabled at rest"
```

Expected: ABSENT. Test the **file**; `control/` itself exists and holds `.locks/`, so `ls control/` returns 0 and proves nothing.

- [ ] **Step 5: Open the PR**

```bash
cd /Users/ericksicard/Projects/claude_code
git push -u origin s3b-audit-log-integrity
gh pr create --base main --head s3b-audit-log-integrity \
  --title "S3-b: make the audit log append-but-not-unlink for the executor" \
  --body "$(cat <<'BODY'
Closes S3-b (ruling R23 TIER 2; its PARTIAL was accepted as R24). Four coupled
changes — landing fewer breaks the rail.

## The finding

The executor could delete its own audit log. `log/` is mounted rw into the one-shot
container — it must be, `append_log` is fsync'd per action — and **directory write is
what grants `unlink`**. Both the undo path and the daily caps read through
`iter_log_records`, so this cost **reversibility**, not merely quota: Task 13's `--undo`
step had to be read as unproven against a hostile executor.

## What landed

1. **Pre-flight inversion** — `log/` needs read+traverse on the directory and write on
   the file. `append_log` fsyncs the directory fd, so `r-x` is exactly right.
2. **Registration bootstrap** — `migrate-governance.py --bootstrap-logs`, dry-run by
   default. No programmatic registration hook exists, so per R23 it rides the existing
   operator CLI, as a separate mode because registration is continuous while migration
   is one-time.
3. **Deploy permissions** — `log/` `2750` host-owned, files `0660`. `REMEDY` and the
   README move together and stay verbatim-identical, because the pre-flight *prints* the
   remedy when it refuses.
4. **Fail-closed** — `iter_log_records` raises on a missing log.

## A hazard the brief did not name

`log/` at `0750` without setgid gives bootstrapped files the operator's primary group;
`0660` then grants the wrong group and uid 10000 falls through to `other`. That layout
**passes a delete probe and fails the append control** — it looks fixed. Hence `2750`,
and the bootstrap stats every file it creates and refuses on a wrong gid or mode, so the
requirement is self-enforcing rather than a README line a future deploy drops.

## Evidence

- `docs/evaluations/2026-09-04-s3b-layout-probe.md` — measured in
  `hermes-agent-claude:latest` as uid 10000: three rows each with an append control,
  plus the end-to-end refuse → bootstrap → admit positive control.
- Mutation proofs on every guard, with sorted failing-set differences, in the task
  commits.
- `run-bin-tests.sh` 25/25, `node scripts/run-all-tests.js` 22/22.

## Still open

- **Phase B** (Tasks 10–11: body-inspecting Docker socket proxy, systemd units) is the
  real precondition for any VPS deploy — the broker's Docker access is host root there.
  **Phase A must not be described as deployed or deployable without it.**
- **Per R22 the VPS behaviour of this layout is UNMEASURED.** The probe ran under Docker
  Desktop, which remaps bind-mount ownership. Nothing here covers the VPS.
- **P6** — `vault-purge.py:42` calls `getpass.getuser()` after the vault is deleted; a
  systemd `DynamicUser` hazard. Separate, smaller.
- **`iter_seen_records`' missing-file `return`** (`changeset_lib.py:680`) keeps the same
  fail-open shape, deliberately: S3-a removed the executor's `seen/` mount, so the
  governed party cannot reach it. **Anything re-mounting `seen/` must fix that first.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
BODY
)"
```
