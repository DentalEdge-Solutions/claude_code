# S3-b — audit-log integrity: design

> **Written 2026-09-04.** Brainstormed from
> `docs/superpowers/specs/2026-09-03-s3b-audit-log-integrity-brief.md`.
> Every fact below is measured against the tree at `9645d1b` unless it says otherwise.
> Where this document and the code disagree, the code wins.

## 1. The finding

The one-shot `ads-mutator` executor can delete its own audit log. `docker-compose.yml:97`
mounts `${HERMES_GOVERNANCE_DIR}/log` read-write into the container — it must, because
`append_log` (`changeset_lib.py:579`, called at `apply-changeset.py:351`) is fsync'd per
action and is the reversibility record. **Write access to a directory is what grants
`unlink`.**

The cost is **reversibility**, not merely quota. `iter_log_records` (`changeset_lib.py:889`)
is the single parser feeding two consumers — `day_counts` (daily caps) and
`apply-changeset._undo_targets` (the undo path, `:213`). It returns empty for a missing log
(`:942`), so a deleted log reads as *under the cap* and as *nothing to undo*. Task 13's
`--undo` step must therefore be read as unproven against a hostile executor (ruling R24).

Per R22, the exploit is **darwin-measured and VPS-UNMEASURED**: Docker Desktop remaps
bind-mount ownership. Nothing in this wave may be claimed of the VPS; Phase B owns that.

## 2. Scope

Four changes, landed together. R23 TIER 2 defines the wave; the fourth item is the point of
the other three, and was confirmed in brainstorming.

1. **Pre-flight inversion** — `log/` requires read+traverse on the *directory* and write on
   the *file*, not write on the directory.
2. **Registration bootstrap** — a `--bootstrap-logs` mode on the existing
   `migrate-governance.py`, guaranteeing every registered client a pre-created log.
3. **Deploy permissions** — `log/` `2750` host-owned, per-client files `0660`.
4. **Fail-closed** — `iter_log_records` raises on a missing log instead of returning empty.

Applying (3) without (1) reproduces R19's over-checking failure a fourth time and blocks
broker startup (measured in R24(a): 1 problem, exit 2). Applying (4) without (2) breaks the
first apply for every client (measured in R24(b): 30 suite tests red, including the plain
happy path).

### Explicitly not this wave

- **Phase B** — the body-inspecting Docker socket proxy and the systemd units. The real
  precondition for any VPS deploy; on a VPS the broker's Docker access is host root.
- **P6** — `vault-purge.py:42` calls `getpass.getuser()` after an irreversible delete.
- **S5-M1** — `_check_approvals` never checks the `approvals/<slug>/` directory's own
  traverse bits. A parked minor on an adjacent path; not reopened here.
- **`iter_seen_records`'s missing-file `return`** (`changeset_lib.py:680`) — the *same*
  fail-open shape as the one this wave closes, and left open deliberately. Its docstring
  already states the reasoning: every seen-set caller is host-side, and S3-a removed the
  executor's `seen/` mount, so the governed party cannot reach the file. That is an argument
  about who can write the store, not about the function. Named here so its survival reads as a
  decision rather than an oversight — **and so that anything re-mounting `seen/` into a
  container fixes this `return` first.**
- **Truncation.** This wave closes `unlink` on `log/<slug>.jsonl` (directory write, not
  file mode, is what grants it) but does nothing about the executor rewriting the
  file's own contents — `0660` grants the owner/group write on the FILE, and write
  includes truncate. Measured on the shipped layout (container, uid 10000, log/ at
  2750 host-owned, file at 0660 host-owned): `rm -f log/acme.jsonl` → `Permission
  denied`, file still present (unlink closed). Then `: > log/acme.jsonl` on the same
  file → exit 0, record count 1 → 0 (truncation open). Because the file still exists
  afterward, `iter_log_records` reads it cleanly — a store the pre-flight and
  `bootstrap_logs` both call healthy can still have its audit trail emptied by the
  party it audits, at the same reversibility cost as the deletion this wave stops
  (the daily-cap and `--undo` reads through `iter_log_records` see zero records
  either way). Closing this needs append-only semantics the mode system alone cannot
  express — `chattr +a` (Linux-specific, and the bind-mount's underlying filesystem
  would need to support it) or moving the write off the executor entirely (a
  host-side writer the container talks to instead of opening the file itself). Both
  are a real design change, not a mode tweak, and are left for a separate wave.

## 3. Design decisions

### D1 — the raise in `iter_log_records` is unconditional; no registry lookup

R23 phrases the requirement as "a missing log for a **REGISTERED** client". Measured: both
production call sites pass `rec["slug"]`, where `rec = vault_lib.resolve(client, registry)`
at `apply-changeset.py:99`, and `resolve` raises `KeyError` on an unknown slug. **Registration
is already guaranteed upstream by construction.** So the raise needs no registry read, and the
hot audit path stays uncoupled from registry parsing and its failure modes.

### D2 — the pre-flight refuses at startup as well, deriving the requirement from the registry

`iter_log_records` alone catches a missing log **mid-apply**. R19 exists precisely to prevent
that: a pre-flight blind to a condition "would have let the broker start against a store the
executor cannot use, and the failure would then surface mid-apply as exit 3 after a live
account change" (`progress.md:740`). `main()` states the same in the code. Under the new
layout a registered client with no log **is** a store the executor cannot use — `append_log`
opens with mode `"a"`, which creates, and `log/` at `2750` host-owned denies creation to
uid 10000.

The harms are asymmetric: a mid-apply failure lands *after* a live account change may already
have gone through; a startup failure is recoverable by one idempotent command.

**Why this is not R19b's over-checking.** Every false-refusal in that lineage —
`.approval.lock`, rotated logs, operator backups (S5-M2) — was the gate demanding access to
files *the executor never opens*, from requirement lists "written from memory rather than
measured" (`progress.md:1052`). This is the inverse: `log/<slug>.jsonl` for a registered slug
is the one file the executor certainly opens, and the requirement is derived from the same
`clients.json` that `vault_lib.resolve` already gates on. Derived, not invented.

Four constraints keep it honest:

- **Derive from the registry, never from a listing of `log/`.** Allowlist discipline per
  R19b — unknown files in `log/` stay ignored.
- **Do not touch `_check_file`.** "Absence is not a fault" stays true for the kill switch,
  approvals, and every other path. This is an added check, not a changed one.
- **The refusal names the exact idempotent bootstrap command.** R19b's real harm was
  refusals with no legitimate fix — "operators disable checks that cry wolf".
- **Fail closed on an unparseable registry**, with a message distinct from the permission
  problems. If `clients.json` will not parse, `resolve` fails for every client anyway.

**Measured suite cost: near zero.** `_configure_full_correct_store` writes the registry as the
literal `"{}"` (`preflight-governance-access.test.py:143`), so `load_registry` returns `{}` via
`data.get("clients", {})` — zero registered clients. A registry-driven existence check requires
nothing in the existing fixtures, so both the positive control and
`test_fresh_store_with_correct_dirs_and_no_files_is_healthy` stay green. R19's earlier
red-cascade came from making `_check_file`'s *generic* absence a fault; this does not.

### D3 — the bootstrap is a separate mode on `migrate-governance.py`, not folded into `migrate()`

R23 requires the bootstrap to ride the existing script, because there is no programmatic
client-registration hook — `clients.json` is hand-edited. It rides it as a **separate
`--bootstrap-logs` flag** backed by a new shim function, sharing the dry-run-by-default
contract.

Folding it into `migrate()` couples two different lifetimes. Migration is a one-time
vault→store move; registration is continuous — a registry entry added next month needs a log.
D2's third constraint requires the pre-flight's refusal to name an exact idempotent command,
and "re-run the vault migration" is the wrong instruction for an operator who has just edited
the registry. Keeping it separate also leaves `migrate()`'s count-verification as its single
concern.

### D4 — `log/` is setgid (`2750`), and the bootstrap verifies its own result

**A hazard the brief does not name.** `log/` at `0750` owned `root:10000` has no setgid bit,
so a file the operator creates inside inherits *the operator's primary group*, not `10000`.
`chmod 0660` then grants rw to the wrong group and uid 10000 falls through to the "other"
class — `0`. The executor can then neither append nor unlink: it **passes a delete probe and
fails the append control**. That is the brief's own broken-fixture warning, baked into the
deploy layout rather than the test.

Setgid makes new files inherit the directory's group regardless of who runs the bootstrap, and
covers `migrate()`'s `_atomic_copy` path and any future host-side writer for free. The
alternative — an explicit `chown` in the bootstrap — needs root and fixes only that one path.

Creating the file is not enough. **The bootstrap stats each file it creates and refuses if the
resulting gid is not the executor gid or the mode is not `0660`.** That makes the setgid
requirement self-enforcing rather than a README line a future deploy silently drops, and it
makes the bootstrap's own output the control: it cannot report success on a file the executor
cannot use.

### D5 — the bootstrap refuses a missing `log/`; it does not create it

`_ensure_dir(path, mode=0o700)` (`migrate_governance_shim.py:62`) creates at `0700` and
deliberately leaves an existing directory alone. A bootstrap that helpfully created `log/`
would produce exactly the unusable store the pre-flight exists to catch. It refuses instead,
naming the deploy step. `migrate()`'s own `_ensure_dir(dst_log_dir)` (`:133`) call is corrected to pass
the new mode, so a fresh migration does not lay down the wrong layout either.

### D6 — no changes needed in `apply-changeset.py`

Measured: both call sites already handle it. `:147` wraps `day_counts` in
`except ValueError → _refuse(str(e))`, and `:214` does the same around
`list(C.iter_log_records(slug))`. A `ValueError` raised on a missing log surfaces as a clean
refusal today — not a traceback, not an exit 1. The raise is one edit, not a propagation
exercise.

## 4. The layout

| Path | Owner | Mode | Why |
|---|---|---|---|
| `<root>/` | host | `0750` | unchanged; executor traverses by group |
| `<root>/log/` | host | **`2750`** | was `0770`. No group write ⇒ no `unlink`, no create. Setgid ⇒ new files inherit gid 10000 (D4) |
| `<root>/log/<slug>.jsonl` | host:10000 | **`0660`** | pre-created by the bootstrap; the executor appends and cannot remove |
| `<root>/approvals/`, `control/`, `registry/` | host | `0750` | unchanged |

`append_log` fsyncs the directory fd (`changeset_lib.py:591`, `os.open(dirname, O_RDONLY)`),
so `log/` needs **read** as well as traverse — `r-x`, which is what `_check_dir(need_write=False)`
already requires. The pre-flight inversion is therefore exactly correct for the real call, not
merely weaker.

## 5. Change spec

### 5.1 `preflight-governance-access.py`

- `check()` `:259` — `_check_dir(log, need_write=True)` → `need_write=False`. The file-level
  check at `:269–272` already requires write on `<slug>.jsonl` (R19's fix) and is unchanged.
- New check, run after the existing ones and only inside the `applies()` guard: read the
  registry via `governance_lib.clients_registry_path()`, and for each registered slug require
  `log/<slug>.jsonl` to exist. ~~Missing ⇒ one problem per slug, naming the bootstrap
  command.~~ **CORRECTED to match the shipped code**: missing logs are reported as one
  AGGREGATE problem naming a count (never the slugs — see the count-not-list rule two
  bullets below, which this must also follow), not one problem per slug.
  Unparseable registry ⇒ one problem, distinct message.
- `REMEDY` `:288–289` — replace `chmod -R g+w %(root)s/log`, which rebuilds the vulnerability,
  with the setgid form. The pre-flight prints this text when it refuses, so a remedy that is
  out of step with the README teaches operators the wrong layout.
- Slug handling: validate through `governance_lib.SLUG_RE` before building a path, and do not
  print slugs — they are client-private. Report a **count** and the bootstrap command, not a
  list of identifiers. (`vault_lib.resolve_dormant_pilot` makes the same choice for the same
  reason, `vault_lib.py:97`.)

### 5.2 `migrate_governance_shim.py`

- New `bootstrap_logs(governance_root, dry_run=False)`:
  - refuse if `log/` is absent (D5), naming the deploy step;
  - read the registry, iterate slugs in sorted order;
  - for each slug with no `log/<slug>.jsonl`: create it empty, `chmod 0660`, then `os.stat`
    and refuse unless `st_gid == EXECUTOR_GID` and `S_IMODE == 0o660` (D4);
  - return the same result shape as `migrate()` — `{"created": [...], "skipped": [...]}`,
    slugs included. `migrate()`'s result already names slugs, this JSON is printed to the
    terminal of an operator who hand-edits `clients.json`, and it is not written anywhere
    tracked. The count-not-list rule in 5.1 applies to the **pre-flight's refusal**, which
    goes to stderr and can be captured by the systemd journal under Phase B — a different
    destination, hence a different rule.
  - Idempotent: an existing log is `skipped`, never truncated. **Truncation would destroy the
    record the wave exists to protect** — the create must be exclusive (`O_CREAT|O_EXCL`), not
    `open(p, "w")`.
- `migrate()` `:133` — `_ensure_dir(dst_log_dir)` passes the new `log/` mode.

### 5.3 `migrate-governance.py`

- `--bootstrap-logs` flag; dry-run by default, `--apply` to act, mirroring the existing
  contract. Same `--governance-root` resolution. Exit 2 on refusal, JSON result on success.

### 5.4 `changeset_lib.py`

- `iter_log_records` `:942` — `return` on a missing file becomes
  `raise ValueError("missing audit log at {p} — fail-closed ...")`, naming the bootstrap.
- The docstring's "A MISSING LOG IS THE ONE EXCEPTION, AND IT IS NOT COVERED (S3-b, ruling
  R22)" carve-out is removed, and the `:604–611` comment block's "It still can" is corrected.
  **These are load-bearing, not tidying**: an independent automated commit security review
  already flagged `78db7e9` on this exact state, and a stale docstring here is what R19
  recorded as the root cause of its own defect.

### 5.5 `README.md` and `docker-compose.yml`

- `README.md:896–898` — the setgid remedy, kept verbatim-identical to `REMEDY`.
- `docker-compose.yml:97` — the `log/` mount stays read-write. The container mount is not what
  changes; the host-side mode is. Its comment gains the reason, so a future reader does not
  "fix" the asymmetry back.

## 6. Test plan

### 6.1 Unit — `preflight-governance-access.test.py`

The existing suite passes `platform="linux"` explicitly, so these exercise the real code path
on darwin despite `applies()`.

- `_configure_group_readable_dirs` `:128–129` moves `log/` from `0770` to `2750`. This is the
  deploy change entering the tests, and it makes
  `test_control_the_same_store_at_the_documented_mode_is_still_healthy` a regression guard for
  the new mode. `_restore_modes` follows.
- New positive control: a registry listing one slug **with** its log ⇒ 0 problems.
- New negative: the same registry **without** the log ⇒ exactly 1 problem.
- New negative: an unparseable registry ⇒ exactly 1 problem, distinct text.
- Retained: `test_fresh_store_with_correct_dirs_and_no_files_is_healthy` must stay green with
  an empty registry — the proof that absence is still not a fault where nothing is registered.

### 6.2 Unit — `migrate-governance.test.py`

- dry-run creates nothing;
- `--apply` creates missing logs at `0660`, leaves existing ones **byte-identical** (assert
  content, not just mtime — an idempotency test that only checks existence would pass a
  truncation);
- refusal when `log/` is absent;
- refusal when the created file lands with the wrong gid — ~~forced by clearing setgid on
  the fixture directory~~ **CORRECTED to match the shipped test**: forced by passing an
  `expected_gid` this process cannot produce (`os.getgid() + 4242`), needing no root —
  the D4 hazard as an executable test rather than a note.

### 6.3 Unit — `changeset_lib.test.py` / `apply-changeset.test.py`

- `day_counts` and `_undo_targets` refuse on a missing log;
- and the refusal reaches the caller as `_refuse`, not a traceback (D6's claim, asserted
  rather than trusted);
- **every fixture that previously relied on an absent log is regenerated through the real
  path** — `bootstrap_logs` for the empty case, `append_log` for the populated one. Per the
  brief: hand-written fixtures pass vacuously; if a fixture's format is subtly wrong the guard
  refuses for the wrong reason and every "a refusal happened" assertion still passes.

### 6.4 Container probe — the only evidence that counts for the layout

`preflight-governance-access.py` is a deliberate no-op off Linux, and a clean darwin run
proves nothing. Probe in `hermes-agent-claude:latest` (Linux, Python 3.13, uid 10000 — the
real executor identity), building the store as root and acting as the executor via
`su hermes -s /bin/sh -c`:

```
docker run --rm --user 0:0 -v "$PWD":/work:ro --entrypoint sh hermes-agent-claude:latest -c '...'
```

Matrix, each row with **both** probes — a layout where uid 10000 can neither append nor delete
looks like a fix and is a broken fixture:

| `log/` mode | append (control) | delete | expected |
|---|---|---|---|
| `0770` | must succeed | succeeds | reproduces the finding |
| `2750`, file `0660` gid 10000 | **must succeed** | must be denied | the fix |
| `2750`, file `0660` **wrong gid** | must fail | denied | D4's hazard, proving the control discriminates |

Ancestor directories must be traversable or append fails for an irrelevant reason — that
invalidated two of three probe attempts last time, and only the append control caught it.

This probe is **operator-run and recorded**, not added to `run-bin-tests.sh`: that suite is
stdlib-only and must pass on hosts without Docker.

### 6.5 Mutation proofs

Green→red on a named test, with the sorted failing-set difference reported, and `ast.parse`
the mutant before believing a silent result:

| Mutation | Must red |
|---|---|
| revert `:259` to `need_write=True` | the positive control, once `log/` is `2750` |
| drop the registry-driven existence check | the new missing-log negative |
| `iter_log_records` returns instead of raising | the `day_counts` and `_undo_targets` refusals |
| `bootstrap_logs` skips the gid/mode verification | the wrong-gid refusal test |
| `bootstrap_logs` uses `open(p,"w")` instead of `O_EXCL` | ~~the byte-identical idempotency test~~ ~~the `0660` mode test~~ the TOCTOU test — **CORRECTED TWICE, see below** |

**An inert mutation is itself a finding** — if one reds nothing, that is a coverage claim to
chase, not a result to accept.

> **CORRECTED 2026-09-04, while writing the plan.** The struck expectation is wrong, and
> would have produced exactly the inert mutation the line above warns about. A truncating
> `open(p,"w")` cannot red the idempotency test: `bootstrap_logs` takes the `skipped` branch
> on an existing file and **never reaches the create**, so there is nothing there to
> truncate. That mutant reds through the umask instead — `open(p,"w")` yields `0644` rather
> than `0660` — killing `test_apply_creates_one_empty_log_per_registered_client_at_0660`.
>
> `O_EXCL` stays, but the honest reason is narrower than the original row implied: it is
> defense in depth against a raced or later-removed `os.path.exists` guard, not the thing
> that protects the existing record. **What protects the existing record is the `skipped`
> branch**, and the byte-identical test is that branch's proof — which is why the test
> stays exactly as specified even though this row no longer points at it.
>
> **CORRECTED AGAIN 2026-09-04, during execution — the umask claim above was also wrong.**
> The implementer ran the mutant, got exit 0 and zero failures, and chased it instead of
> accepting a green result. `bootstrap_logs` calls `os.chmod(dst, LOG_FILE_MODE)`
> immediately after creating the file, which defeats the umask regardless of how the file
> was created — so the `0644` red predicted above cannot happen either. **Nothing in the
> suite killed this mutation.** Two successive predictions about this one row were wrong,
> which is itself the argument for running mutations rather than reasoning about them.
>
> Closed by adding the test the row always needed: a TOCTOU test that forces
> `os.path.exists` to miss exactly once for the target path while the file genuinely exists
> on disk, then asserts BOTH that the call refuses AND that the pre-existing bytes are
> unchanged — the second assertion being the difference between "it errored" and "it did
> not destroy the audit log". It carries its own control (`assertTrue(lied["done"])`)
> proving the race was actually simulated. Mutant B reds it. **The row now reads: `O_EXCL`
> replaced by `open(p,"w")` -> the TOCTOU test.**

### 6.6 Baselines

`infra/hermes-agent/bin/run-bin-tests.sh` → 25/25 (re-measured 2026-09-04, exit 0).
`node scripts/run-all-tests.js` → 22/22 (re-measured 2026-09-04, exit 0). Capture exit status
into a variable or use `PIPESTATUS`; `cmd | tail` takes its status from `tail` and has
misreported an exit code twice in this project.

## 7. Operator impact

A registry entry added by hand without a bootstrap run blocks broker startup until
`migrate-governance.py --bootstrap-logs --apply` is run. That is deliberate (D2) and the
refusal names the command.

**Cost if wrong:** a store whose registry lists a client that will never be mutated blocks the
rail until one idempotent command is run — recoverable, and caught before any live change.
Against the alternative's cost: an exit 3 mid-apply, after a live account change may already
have landed.

## 8. What stays unmeasured

Per R22, the VPS behaviour of the deployed layout remains unmeasured until Phase B, and
nothing measured on darwin — including the container probe in 6.4, which runs under Docker
Desktop — may be claimed of the VPS. The probe establishes that append-but-not-unlink holds at
the OS level for uid 10000 on Linux. It does not establish how a VPS bind mount maps
ownership.

## 9. Constraints carried

- Python 3 **stdlib only** under `infra/hermes-agent/bin/`; exactly one trailing
  `unittest.main()` per test file.
- **Fail closed** — an unreadable or missing limit must never read as permissive.
- No client names, customer ids, campaign ids, or credential values in code, tests, docs, or
  refusal text. Invented slugs only. Re-run the redaction scan before the PR **and pair it
  with a live control** — a scan whose control does not fire proves nothing.
- Leave the kill switch OFF. It is the **file** `control/mutation-enabled`, currently absent;
  `control/` itself exists and holds `.locks/`, so `ls control/` returns 0 and proves nothing.
- Stage by explicit path only — `evals/` is only partially gitignored (`.gitignore:14` covers
  `evals/codex-runs/` alone), and the tree carries 5 tracked and 43 untracked pre-existing
  changes. Never `git add -A`.
- `main` is protected — land via PR.

## 10. Evidence

- `docs/superpowers/specs/2026-09-03-s3b-audit-log-integrity-brief.md` — P2/P3 measurements
- `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md` — R19/R19b (`:728`),
  the S3 decomposition (`:1055`), R22 (`:1069`), R23 TIER 2 (`:1085`),
  R24 (`:1128`)
- `.superpowers/sdd/2026-09-02-hermes-syscall-approval-handoff/HANDOFF.md` — the CRITICAL
  fix's rulings. **Stale on its item 8**: the `REQUEST_ID_RE` divergence was fixed in
  `6645879` and is on `main`.
- `docs/evaluations/2026-08-30-hermes-phase-a-deployment-readiness.md` — P1–P6
- `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` — binding spec; §7/§9
  corrected 2026-09-03, §6.4 carries D1

### Line references corrected while writing this

The brief cites `apply-changeset.py:194` for the undo/caps coupling (now `:208` docstring,
`:213` call) and `apply-changeset.py:301` for `append_log` (now `:351`; `:237` is a comment).
Both drifted with PR #21 and #22. The brief's prose also says "the `ads-mutator` image" —
`ads-mutator` is the **compose service**; `hermes-agent-claude:latest` is the only image that
exists, and it is what `docker run` takes.
