# Broker sweep of stray entries in `jobs/`: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stray entry in `app-state/<app>/jobs/` can no longer keep the root runner re-starting: the broker
removes it within one pass.

**Architecture:**
- The runner's path unit fires on `DirectoryNotEmpty=/var/lib/hermes/app-state/%i/jobs`. The runner
  (`bin/hermes-app-runner.py`, `_oldest`) only picks up names matching `app_lib.FILENAME_RE` and exits 0, so any
  other entry stays, the directory stays non-empty, and the path unit fires again. `StartLimitIntervalSec=0`
  means nothing throttles it.
- The broker owns `jobs/` (`0700`, the app user). It writes each job's temp file in `state/` and renames it into
  `jobs/` under its `<request id>.json` name, so nothing legitimate in `jobs/` ever has a non-matching name.
- The fix is a new `sweep_jobs(ctx)` in `bin/hermes-app-broker.py`, called from `step()` on every pass. It
  removes every entry in `jobs/` whose name does not fully match `FILENAME_RE`. Matching names are jobs and are
  never touched: they are the runner's.

**Tech Stack:** Python 3 stdlib only.

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` §3 (request flow: broker →
job → runner) and §7 (failure handling). The defect is follow-up 1 in
`docs/superpowers/handoffs/2026-10-01-option-b-part-3-merged-next-box-rollout.md`.

## Global Constraints

- Python stdlib only; tests are `bin/<name>.test.py`. `infra/hermes-agent/bin/run-bin-tests.sh` must end
  `N/N suites passed`.
- The broker never executes anything and never reads a job's content here: the sweep decides by NAME only.
- A journal line never carries a file name, a slug, or an exception message. New lines go through `_note`
  (fixed text) and start `warning: ` so the review collector's `_NOTE_RE` counts them as notes.
- No change to `deploy/security-review/CHECKLIST.md` (any change there needs a version bump above 1.11), to the
  units under `deploy/`, to `bin/hermes-app-runner.py`, or to `bin/app_lib.py`.
- One entry must never stop a pass: no filesystem error leaves `sweep_jobs`. (A logger that raises is outside
  it, as for every other journal line the broker writes.)

## Review Focus

1. **A queued job is removed by the sweep.** A real job (name matches `FILENAME_RE`) must survive any number of
   passes untouched. Test: `test_a_queued_job_survives_the_sweep`.
2. **A fresh dot-named temp file in `jobs/`.** It used to be kept for an hour (older brokers wrote temp files
   there); for that hour the runner spun. It is now removed at once, and the broker's own write must still land
   outside `jobs/`. Tests: `test_every_kind_of_stray_entry_is_removed_in_one_pass` and the existing
   `test_job_temp_file_is_written_outside_jobs`.
3. **A non-empty directory in `jobs/`.** It cannot be removed with `rmdir`. The pass must not raise, the journal
   must get one fixed line per process (not one per pass), and other stray entries must still be removed. Test:
   `test_a_non_empty_directory_is_left_with_one_note`.
4. **A name that only looks like a job.** `<uuid>.json\n` matches a `$`-anchored `.match` but not `fullmatch`;
   the runner ignores it, so the sweep must remove it. Test: `test_a_trailing_newline_name_is_stray`.
5. **An entry that vanishes between the listing and the `lstat`.** It must cost nothing: no note, no exception.
   Test: `test_a_vanishing_entry_costs_nothing`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/hermes-app-broker.py` | modify | `Ctx.stray_noted`; new `sweep_jobs(ctx)`; `step()` calls it; `collect_once` stops sweeping dot-files in `jobs/` |
| `infra/hermes-agent/bin/hermes-app-broker.test.py` | modify | new `TestStrayJobs`; the one existing test that expected a fresh dot-file in `jobs/` to be kept |

---

### Task 1: `sweep_jobs` in the broker

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-app-broker.py` (`Ctx.__init__`, new `sweep_jobs`, `collect_once`, `step`)
- Test: `infra/hermes-agent/bin/hermes-app-broker.test.py`

**Interfaces:**
- Consumes: `A.FILENAME_RE` (`^[0-9a-f-]{36}\.json$`), `_note(ctx, text)`, `Ctx.d(name)`.
- Produces: `sweep_jobs(ctx) -> None`; `Ctx.stray_noted: bool`; two fixed journal texts:
  - `warning: stray entries in jobs/ were removed` (at most once per pass);
  - `warning: a stray entry in jobs/ cannot be removed (left in place)` (at most once per process).

- [ ] **Step 1: Write the failing tests** (append to `hermes-app-broker.test.py`, before the `if __name__` block)

```python
class TestStrayJobs(Base):
    """jobs/ holds only <request id>.json files. Anything else keeps the runner's path unit
    (DirectoryNotEmpty=jobs) re-triggering a runner that ignores it."""
    RID = "0f8e2c1a-1111-4222-8333-444455556666"

    def jp(self, name):
        return os.path.join(self.state, "jobs", name)

    def touch(self, name):
        with open(self.jp(name), "w") as f:
            f.write("{}")

    def notes(self, text):
        return [l for l in self.logs if l.endswith(text)]

    def test_every_kind_of_stray_entry_is_removed_in_one_pass(self):
        self.touch("leftover")
        self.touch(".y.json.new.tmp")                      # a FRESH dot-file: no age test in jobs/
        self.touch("0f8e2c1a.json")                        # .json, but not a request id
        os.symlink("/etc/hostname", self.jp("link"))
        os.mkfifo(self.jp("fifo"))
        os.mkdir(self.jp("emptydir"))
        B.step(self.ctx, 1)                                # 1: not a recover() pass; the sweep runs anyway
        self.assertEqual(self.jobs(), [])
        self.assertEqual(len(self.notes("warning: stray entries in jobs/ were removed")), 1)
        for name in ("leftover", ".y.json.new.tmp", "0f8e2c1a", "link", "fifo", "emptydir"):
            self.assertFalse(any(name in l for l in self.logs), name)

    def test_a_queued_job_survives_the_sweep(self):
        rid = self.file()
        B.drain_once(self.ctx)
        self.assertEqual(self.jobs(), [rid + ".json"])
        with open(self.jp(rid + ".json"), "rb") as f:
            before = f.read()
        for n in (1, 2, 3):
            B.sweep_jobs(self.ctx)
        self.assertEqual(self.jobs(), [rid + ".json"])
        with open(self.jp(rid + ".json"), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.notes("were removed"), [])

    def test_a_clean_jobs_dir_logs_nothing(self):
        B.sweep_jobs(self.ctx)
        self.assertEqual(self.logs, [])

    def test_a_trailing_newline_name_is_stray(self):
        self.touch(self.RID + ".json\n")
        B.sweep_jobs(self.ctx)
        self.assertEqual(self.jobs(), [])

    def test_a_non_empty_directory_is_left_with_one_note(self):
        os.mkdir(self.jp("full"))
        with open(os.path.join(self.jp("full"), "x"), "w") as f:
            f.write("x")
        self.touch("leftover")
        for n in (1, 2, 3):
            B.step(self.ctx, n)                            # never raises
        self.assertEqual(self.jobs(), ["full"])            # the removable one is gone
        self.assertEqual(len(self.notes("warning: a stray entry in jobs/ cannot be removed (left in place)")), 1)
        self.assertFalse(any("full" in l for l in self.logs))

    def test_a_vanishing_entry_costs_nothing(self):
        self.touch("leftover")
        real = os.lstat
        def gone(p, *a, **k):
            if os.path.basename(str(p)) == "leftover":
                raise FileNotFoundError(p)
            return real(p, *a, **k)
        os.lstat = gone
        self.addCleanup(setattr, os, "lstat", real)
        B.sweep_jobs(self.ctx)
        self.assertEqual(self.logs, [])

    def test_an_unlistable_jobs_dir_costs_nothing(self):
        os.rmdir(os.path.join(self.state, "jobs"))
        B.sweep_jobs(self.ctx)                             # never raises
        self.assertEqual(self.logs, [])

    def test_state_temp_files_keep_the_age_test(self):
        st = os.path.join(self.state, "state")
        old, new = os.path.join(st, ".x.json.old.tmp"), os.path.join(st, ".y.json.new.tmp")
        for p in (old, new):
            with open(p, "w") as f:
                f.write("{}")
        t = time.time() - B.REQUEST_MAX_AGE - 10
        os.utime(old, (t, t))
        B.step(self.ctx, 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))               # the broker's own in-flight write
```

   Replace the existing `TestFinalFix.test_stale_temp_files_in_jobs_are_swept_fresh_ones_kept` (it asserts that a
   fresh dot-file in `jobs/` is KEPT, which is the spin) with:

```python
    def test_temp_files_in_jobs_are_removed_whatever_their_age(self):
        jobs = os.path.join(self.state, "jobs")
        old, new = os.path.join(jobs, ".x.json.old.tmp"), os.path.join(jobs, ".y.json.new.tmp")
        for p in (old, new):
            with open(p, "w") as f:
                f.write("{}")
        t = time.time() - B.REQUEST_MAX_AGE - 10
        os.utime(old, (t, t))
        B.step(self.ctx, 1)
        self.assertEqual(self.jobs(), [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/hermes-app-broker.test.py TestStrayJobs TestFinalFix -v`
Expected: FAIL. `AttributeError: … has no attribute 'sweep_jobs'` in the tests that call it, and assertion
failures on `self.jobs()` in the tests that call `B.step` (`['.y.json.new.tmp', '0f8e2c1a.json', …] != []`).
`test_state_temp_files_keep_the_age_test` passes already: it pins behaviour that must not change.

- [ ] **Step 3: Implement** (in `hermes-app-broker.py`)

   In `Ctx.__init__`, after `self.dir_noted = False`:

```python
        self.stray_noted = False
```

   Add after `_sweep_stale_dotfile`:

```python
def sweep_jobs(ctx):
    """jobs/ holds only <request id>.json files, renamed in by this broker (the temp file lives
    in state/). Anything else is stray, and one stray entry keeps the runner's path unit
    (DirectoryNotEmpty=jobs) re-triggering a runner that ignores it: remove it, every pass, by
    name alone. A matching name is a job and is the runner's: never touched here."""
    jobs = ctx.d("jobs")
    try:
        names = os.listdir(jobs)
    except OSError:
        return
    removed = False
    for n in names:
        if A.FILENAME_RE.fullmatch(n):                     # fullmatch: `$` alone admits "…json\n"
            continue
        p = os.path.join(jobs, n)
        try:
            if stat.S_ISDIR(os.lstat(p).st_mode):          # lstat: a symlink is unlinked, never followed
                os.rmdir(p)
            else:
                os.unlink(p)
            removed = True
        except FileNotFoundError:
            pass
        except OSError:
            # A non-empty directory (only this user or root can make one here). Say so once per
            # process and never let it stop a pass.
            if not ctx.stray_noted:
                _note(ctx, "warning: a stray entry in jobs/ cannot be removed (left in place)")
                ctx.stray_noted = True
    if removed:
        _note(ctx, "warning: stray entries in jobs/ were removed")
```

   In `collect_once`, the dot-file sweep no longer covers `jobs/` (`sweep_jobs` removes everything stray there,
   whatever its age). Replace:

```python
    # Stale temp files in jobs/ (older brokers wrote them there; a crash strands them) and in
    # state/: a leftover in jobs/ keeps the runner's path unit re-triggering on nothing.
    for d in ("jobs", "state"):
        for n in os.listdir(ctx.d(d)):
            if n.startswith(".") and n.endswith(".tmp"):
                _sweep_stale_dotfile(ctx, os.path.join(ctx.d(d), n), now)
```

   with:

```python
    # Stale temp files in state/ (a crash strands them). jobs/ is sweep_jobs's: anything stray
    # there goes at once, whatever its age.
    for n in os.listdir(ctx.d("state")):
        if n.startswith(".") and n.endswith(".tmp"):
            _sweep_stale_dotfile(ctx, os.path.join(ctx.d("state"), n), now)
```

   In `step`, call the sweep first on every pass:

```python
    sweep_jobs(ctx)
    if n % RECOVER_EVERY == 0:
        recover(ctx)
    drain_once(ctx)
    collect_once(ctx)
    expire_results(ctx)
```

   and extend `step`'s docstring with one sentence: `sweep_jobs() runs on every pass: a stray entry in jobs/
   must not outlive one interval.`

- [ ] **Step 4: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/hermes-app-broker.test.py -v`
Expected: all PASS, no warnings.

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: ends `53/53 suites passed` (`app-e2e.test.py` drives the broker and runner together and must stay
green).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-app-broker.py infra/hermes-agent/bin/hermes-app-broker.test.py
git commit -m "fix(hermes): broker sweeps stray entries out of jobs/ every pass (runner restart spin)"
```

---

## Self-review notes (done while writing)

- **Coverage:** the handoff's fix ("a broker-side sweep of names that don't match") is Task 1. Each Review Focus
  line has its test in Task 1.
- **What this does not fix:** an entry the broker cannot remove (a non-empty directory, which only the app user
  or root can create in `jobs/`) still leaves the directory non-empty. It gets one journal line. The same is
  true of a matching-name entry the runner cannot remove. Both need the app user or root to plant them.
  The sweep also works only while the broker is running: with the broker stopped or failed, a stray entry
  planted by root or the app user still spins the root runner.
- **No checklist change:** the two new journal lines start `warning: `, which the collector's `_NOTE_RE` already
  counts under `note_counts`; checklist D10.7 already says fixed-text lines are expected.
- **Fingerprint:** `bin/` is in the box fingerprint, so this must be on `main` before the box rollout.
