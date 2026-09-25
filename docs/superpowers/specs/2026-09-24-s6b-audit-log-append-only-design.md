# §6 part B — Audit logs are append-only (design)

**Status:** approved in sections 2026-09-24; spec awaiting operator review.
**Gate:** §6 part B, the last kill-switch gate (`docs/superpowers/handoffs/2026-09-17-phase-b-rereview-and-pr.md`
~:112; brief in `docs/superpowers/handoffs/2026-09-24-post-f19-state-and-next-steps.md`).
**Origin:** the "Truncation" residual S3-b left open deliberately
(`docs/superpowers/specs/2026-09-04-s3b-audit-log-integrity-design.md` §2, ~:56-71).
**Scope:** how per-client audit logs are created (sealed) and verified (pre-flight). Nothing that
writes or reads a log's contents changes.

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing here creates it.**

## 1. Problem

`log/<slug>.jsonl` is `0660 root:hermes` in a `2750 root:hermes` directory. S3-b closed unlink
(directory write) but not truncation: write on the FILE includes truncate and overwrite. Two
consequences:

1. **The reversibility record is erasable** by the parties it audits, and `--undo` reads it.
2. **The daily caps reset.** `day_counts` (`changeset_lib.py:1119`, called in `apply-changeset.py`
   step 6, ~:155) counts records in the same log, so an emptied log reads as zero applies today.

The file still exists afterwards, so `iter_log_records`, the pre-flight and `bootstrap_logs` all
call the store healthy.

## 2. Assessment — measured, not inferred

### 2.1 Who legitimately writes and reads the log (code, 2026-09-24)

- **One runtime writer:** `changeset_lib.append_log` (`:732`) — `open(p, "a")` (O_APPEND), one
  line, fsync file then directory. Sole caller: `apply-changeset.py:362`, inside the `ads-mutator`
  container, the only service that mounts `log/` (`docker-compose.yml:118`).
- **Two host-side creators, neither rewrites:** `bootstrap_logs` (`migrate_governance_shim.py:124`;
  `O_CREAT|O_EXCL`, skips existing) and `migrate()` (`:262-320`; one-time, only when the
  destination is absent; copy to tmp, count, `os.replace`).
- **The broker never touches the log.** No reference to `log_path` / `append_log` /
  `iter_log_records` in `hermes-broker.py` or `hermes-syscall.py`.
- **No rotation, rewrite, backup or truncating open** of `log/` anywhere in shipped code.
- **One parser, read-only:** `iter_log_records` (`:1066`), feeding `day_counts` (caps) and
  `_undo_targets` (`apply-changeset.py:210-240`). Host-side checks stat only (`isfile`, `exists`).
- **Nothing edits a record after the fact.** An undo APPENDS a `status: "undone"` record
  (`apply-changeset.py:358`); `_undo_targets` subtracts them. The design is already append-only.

### 2.2 Who can write the file (box `srv1997271`, 2026-09-24, metadata only)

| Principal | Write on `log/<slug>.jsonl` | Why |
|---|---|---|
| root (`hermesops` via sudo) | yes | owner / root |
| `hermes-broker` (uid 997) | **yes** | the ONLY host account in group `hermes` (10000), via the unit's `SupplementaryGroups`; `ReadWritePaths` covers the store |
| executor (container uid 10000, gid 10000) | yes | group |
| `hermes-docker-proxy` | indirectly | in `docker` (root-equivalent; already assumed everywhere) |
| everyone else | no | no host account has uid 10000 or primary gid `hermes` |

The box has **0 registered clients** (`clients.json` → `0`), so **no real logs exist yet**.

### 2.3 Truncation, before and after `chattr +a` (box, scratch file only)

Filesystem: `/var/lib/hermes/governance/log` is on `/` = `/dev/sda1`, **ext4**
(`rw,relatime,discard,errors=remount-ro,commit=30`). Scratch file `log/s6b-probe.scratch`,
`-rw-rw---- 660 root:hermes`; the broker probed via `systemd-run` with the unit's identity and
sandboxing; the executor via the real `hermes-agent-claude` image (`sha256:d72e8543…`) with the
real bind mount. Scratch removed afterwards; `init-host-layout --check` and the pre-flight both
`rc=0`; kill switch ABSENT.

| | append | overwrite @0 | `O_TRUNC` open (`: >`) | `truncate(2)` | rename / unlink |
|---|---|---|---|---|---|
| **before** — broker | OK | **OK** | **OK** | **OK** | EACCES |
| **before** — executor | OK | **OK** | **OK** | **OK** | EACCES |
| **after `+a`** — broker | OK | EPERM | EPERM | EPERM | EACCES |
| **after `+a`** — executor (through the bind mount) | OK | EPERM | EPERM | EPERM | EACCES |
| **after `+a`** — root | OK | EPERM | EPERM | EPERM | **EPERM** |

The broker half of the gap was only inferred in the brief; it is now measured. Root's EPERM on
rename/unlink (it bypasses the directory check) shows the flag, not the mode, is what refuses.

## 3. Decisions

- **D1 — `chattr +a` on each `log/<slug>.jsonl`**, set when the log is created. Fits every
  legitimate writer and reader (§2.1). Kernel-enforced for every principal, including root.
- **D2 — a log without the flag refuses** (the pre-flight fails; the broker does not start; a
  mutation run does not start). The rail being down is the safe failure; a warning-only guard would
  be the one fail-open check in the store.
- **D3 — never sealed automatically after creation.** No tool adds `+a` to a log that already
  exists. A log that was ever flagless may have been emptied; a person inspects it, then runs
  `sudo chattr +a` by hand. Same rule as `init-host-layout`'s "never repair".
- **D4 — stdlib `fcntl.ioctl`, not the `chattr`/`lsattr` binaries.** No subprocess, no text
  parsing, no `e2fsprogs` dependency on the security path. The kernel constants are the risky
  part and are proven on Linux CI (§6).
- **D5 — the check lives in the pre-flight**, not `init-host-layout --check`. The pre-flight runs
  at broker start (`hermes-broker.service` second `ExecStartPre`) **and** before every mutation run
  (`run-ads-mutate.sh:38`), so a flag cleared after start is still caught before the next apply;
  it already walks the registered logs; it is already a no-op off Linux.
- **D6 — messages carry counts, never slugs.** Client slugs are client-private and the pre-flight's
  stderr lands in the journal (existing rule, `_check_registered_logs` docstring).

## 4. Components

### 4.1 `governance_lib.py` — the only code that talks to the kernel

- `LOG_APPEND_ONLY_FL = 0x00000020` (`FS_APPEND_FL`), `_FS_IOC_GETFLAGS = 0x80086601`,
  `_FS_IOC_SETFLAGS = 0x40086602` (`_IOR/_IOW('f', 1|2, long)` on 64-bit Linux), each with a
  comment naming `linux/fs.h`. The kernel reads and writes an **int** through these requests
  despite the `long` in the macro: use a 4-byte buffer. **§6 Tier 2 is the proof these are right.**
- `is_append_only(path) -> bool`
  - `os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)`; `fstat` must be a regular file, else raise.
  - `FS_IOC_GETFLAGS`; return `bool(flags & LOG_APPEND_ONLY_FL)`.
  - **Raises on every failure** (unsupported filesystem → `ENOTTY`/`EOPNOTSUPP`, open failure,
    non-regular file). Never returns False on an error.
  - Needs no root; the broker can call it (group read).
- `set_append_only(path) -> None`
  - Same open and regular-file check; GET flags; SET `flags | LOG_APPEND_ONLY_FL`; then
    `is_append_only(path)` must be True, else raise.
  - Only root succeeds (`CAP_LINUX_IMMUTABLE`).
- Off Linux both raise a "not supported on <platform>" error; callers decide what that means.

### 4.2 `migrate_governance_shim.py`

- **`bootstrap_logs`**: after the existing create → chmod → mode/gid verification, call
  `set_append_only(dst)` **inside the existing `try`**, so a sealing failure takes the existing
  cleanup (remove the file THIS call created; the flag did not take, so root can) and re-raises.
  Existing logs are still skipped and never sealed (D3). Dry run: unchanged — it reports the slugs
  it would create; it never touches flags.
- **`migrate()`**: after `os.replace(tmp_log, dst_log)`, call `set_append_only(dst_log)`. It must
  come after the rename: Linux refuses to rename an append-only file (measured: EPERM for root,
  §2.3). On failure remove `dst_log` (a copy made by this call; the vault original is untouched)
  and re-raise, so a retry reproduces the same result.

### 4.3 `preflight-governance-access.py`

A new `_check_registered_logs_sealed(root)`, called from `check()` next to
`_check_registered_logs`, walking the **same** registered-slug list derived from `clients.json`
(never a listing of `log/`), with the same registry handling (missing/unreadable → `[]`,
unparseable → already reported by `_check_registered_logs`; not reported twice).

For each registered slug whose log exists (a missing log stays `_check_registered_logs`' job):

| `is_append_only` | Bucket |
|---|---|
| True | sealed — fine |
| False | **not sealed** — refuse |
| raises | **cannot verify** — refuse (fail closed) |

At most one message per non-zero bucket, **counts only**:
- not sealed: `"<root>/log: N registered client log(s) are not append-only, so their records and
  the daily caps can be erased by truncation. Inspect with: sudo lsattr <root>/log/*.jsonl — then,
  for each log you have checked, run: sudo chattr +a <root>/log/<slug>.jsonl"`.
- cannot verify: `"<root>/log: N registered client log(s) could not be checked for the
  append-only flag (<sorted distinct errno names, e.g. ENOTTY>) — refusing, because an
  unverifiable log is not a sealed one"`. Errno names only — never a path or slug.

**Double-count rule (R19b / Ruling 9 lineage):** a log whose mode is wrong can also be unopenable
by the checking process. The plan must determine, against the existing exact-count tests, whether
"cannot verify" must skip a file the existing file-level check already reported, and pin the
chosen behaviour with a test. One fault must read as one problem.

### 4.4 Untouched

`append_log`, `iter_log_records`, `day_counts`, `--undo`, `init-host-layout.py`, `host_layout.py`,
the broker, both unit files, `docker-compose.yml` (except a comment, §8). No unit change → the
rollout needs no unit re-`cp` and no `daemon-reload`.

## 5. Flows and failures

- **New client log** (`sudo migrate-governance.py --bootstrap-logs --apply`): create (O_EXCL) →
  0660 → verify mode/gid → **seal → verify seal**. Any failure: remove the just-created empty file,
  refuse with the cause. Result: either a sealed log or no log; never a flagless one left behind.
- **Vault carry-over** (`migrate()`): copy → count → replace → **seal**. Failure: remove the copy,
  refuse; the vault original is untouched.
- **Pre-flight**: sealed / not sealed / cannot verify, as §4.3.
- **Unchanged by sealing:** `append_log` (O_APPEND — measured OK under `+a`), `--undo` (appends),
  readers (read).
- **Now needs root to clear the flag first:** deleting a client's log, restoring one from backup
  (a copy does not carry the flag). Neither exists in code; both are deliberate operator steps and
  the README says so.

## 6. Testing and proof

**Tier 1 — unit, any platform** (injected fake helper; no kernel):
- `bootstrap_logs`: seals each created log; never seals an existing one; sealing failure removes
  the created file and refuses; dry run never seals.
- `migrate()`: seals after the replace; sealing failure removes the copy, keeps the vault original.
- Pre-flight: the three buckets; counts only — a test registers a distinctive slug and asserts it
  appears in **no** message; a missing log is not counted twice; the §4.3 double-count rule pinned;
  off Linux the check does not run.

**Tier 2 — `deploy/layout-integration.test.py`, root, Linux CI, real ids, real ext4 file:**
1. Helper vs real kernel: `set_append_only` → `is_append_only` True **and `lsattr` shows `a`**
   (cross-checks the ioctl numbers and the 4-byte buffer against the tool used on the box); a
   plain file → False; a symlink → refused.
2. The property: `bootstrap_logs` for a registered fixture client (in the test's own store), then
   as **`GATEWAY`** (uid 10000) **and `BROKER`**: append OK; overwrite, `O_TRUNC` open and
   `truncate(2)` → **EPERM**; line count unchanged. **The security assertion first**, on the errno,
   not "some error was raised".
3. Pre-flight on real flags, as `BROKER`: `rc=0` on the sealed store; after `chattr -a` on the
   fixture log, it refuses with the not-sealed message.
4. Filesystem guard: if the runner's filesystem cannot hold the flag, that is a **failure** under
   `HERMES_REQUIRE_LINUX_INTEGRATION=1`, never a skip.

**RED first:** Tier 2 lands first on a draft PR, before any implementation. The expected RED is the
**truncation assertion failing because truncation succeeded** — read the failing assertion before
counting it (canon lesson "check why a RED is red").

**Firing controls** (in memory or on temp copies; never by editing a tracked file), each recording
which mutation turned which test red:
- drop the `set_append_only` call from `bootstrap_logs` → Tier 2 (2) red;
- wrong flag constant → Tier 2 (1)'s `lsattr` cross-check red;
- `is_append_only` returning True unconditionally → Tier 2 (3) red.

**Not in CI:** the Docker bind-mount path. Measured on the box (§2.3) and re-measured at rollout
(§7). A container probe in `bind-agreement` would re-prove the same inode flag at the cost of a
slower job.

**CI counts:** read `executed N, skipped 0` for `layout-integration` and `bind-agreement` on the PR
and on the merge commit.

## 7. Box rollout

The box has 0 registered clients, so the pre-flight's new check is **vacuous** on the real store:
`rc=0` after the pull proves nothing. The proof uses a **scratch store** on the same ext4 disk,
through the real code paths. The real store, the real registry and the kill switch are never
touched.

1. **Before the pull** (current code): build a scratch store (`init-host-layout --apply` with
   scratch store and spool roots under `/var/lib`), register one fake client in the scratch
   registry, `--bootstrap-logs --apply` against it. Expected: `lsattr` shows **no** `a`; truncation
   as the broker **works**; the pre-flight on the scratch store **`rc=0`**.
2. **Pull**; restart the proxy only (the broker restarts with it). No unit files change.
3. **After:** tear down and rebuild the scratch store the same way. Expected: `lsattr` shows
   **`a`**; truncation as the broker **and** as the executor (real image, bind mount of the scratch
   `log/`) → **EPERM**, append OK; pre-flight **`rc=0`**; then `chattr -a` on the scratch log → the
   pre-flight **refuses** with the not-sealed count (the box firing control).
4. Clean up (`chattr -a`, `rm -rf` the scratch roots). Real store: `init-host-layout --check` and
   the pre-flight both `rc=0`; both units `active`; kill switch **ABSENT**.

The operator runs every command; exact commands with the expected result per line; stop at the
first mismatch.

**Later, first real client:** `sudo … --bootstrap-logs --apply` seals the log; the checklist adds
`sudo lsattr` on it, expecting `a`.

## 8. Records

- This spec (with §2's measurements).
- **Findings record: F20 — forged appends** (below), a named, deliberate deferral.
- **README:** logs are append-only; deleting or restoring one needs `sudo chattr -a` first; the
  bootstrap checklist gains the `lsattr` line.
- **BRING-UP:** "After pulling §6B" with a `RESULT` block, filled only from real output.
- **Comments now wrong:** `docker-compose.yml`'s "It is NOT append-only, though …" (~:111-116) and
  the S3-a/S3-b block in `changeset_lib.py` (~:756-767) — comment-only edits. The S3-b spec gets a
  one-line forward pointer to this spec (history is not rewritten).
- **Brain:** a `[decision]` entry once landed and applied.

## 9. Explicitly not this wave

- **F20 — forged appends.** `+a` stops erasing, not adding. Whoever can append (the executor —
  including the ads-repo mutator subprocess running as uid 10000 in the same container — and the
  broker via group `hermes`) can append a fabricated `"undone"` record for a real resource;
  `_undo_targets` then drops it, losing reversibility as surely as truncation. Fabricated
  `"applied"` records only exhaust the caps (fail-safe). No mode can deny the executor, which must
  append. The real fix is a host-side writer or signed records — new code on the security path,
  its own design. Recorded as a decision, not an oversight.
- **Removing the broker's unused write** (ACL or group change). Modes alone cannot, since the
  executor needs group write through the same gid; `+a` covers truncation for both.
- **Auto-sealing existing logs** (D3).
- **A Docker probe in CI** (§6).
- **Creating the kill switch.** After §6B the remaining gate is the rehearsal gate (`.env.gaw` with
  the WRITE credential on the box) — an operator security decision.
