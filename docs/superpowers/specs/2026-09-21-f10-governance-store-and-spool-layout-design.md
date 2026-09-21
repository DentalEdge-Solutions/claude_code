# F10 — Governance store and spool layout for a fresh Linux host (design)

> **Status:** design approved in brainstorming, 2026-09-21. Implementation plan follows via
> `superpowers:writing-plans`.
> **Handoff:** `docs/superpowers/handoffs/2026-09-21-f10-governance-store-and-spool-layout.md`
> **Finding:** F10 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`
> **Constraints carried from the handoff:** mutation stays disabled (no kill switch); nothing
> widened to make something pass; F9 not folded in; every new check has a firing control; Linux
> ownership proven on the Linux CI runner or stated as unproven; the VPS is not touched.

## 1. Problem

Phase 6 of the bring-up (installing the systemd units) assumes a governance store and a request
spool that nothing creates on a fresh host. Reading the code to settle the handoff's five
questions found that the gap is larger than a missing `mkdir`:

- **F10 (as filed).** Only `migrate()` creates any of `approvals/`, `control/`, `registry/`,
  `log/`, `seen/`, `registry/clients.json`, and only by copying from local vaults the VPS does
  not have. The store owner is unspecified. `data/spool/` must exist for the broker unit's
  `ReadWritePaths=`, but `data/` is `700` uid 10000 and the spool's Linux permissions are
  undocumented.
- **F10a — the spool cannot work on Linux in either direction.** Nothing in `spool_lib.py`,
  `hermes-syscall.py` or `hermes-broker.py` sets a file mode. Both sides write via
  `tempfile.mkstemp`, which always creates `0600`. A request written by the gateway (uid 10000)
  cannot be opened by `hermes-broker`, so `load_request` raises `SpoolRefused` and every request
  is refused and discarded. A result written by the broker cannot be read by uid 10000, so
  `hermes-syscall fetch` reports `result_unreadable` for every request. Invisible on darwin,
  where both sides are the same user.
- **F10b — a spool under `data/` is a redirect into the governance store.** `data/` is owned by
  uid 10000, which is the gateway. The gateway can therefore rename `data/spool` (or
  `requests/`, `results/`) and put a symlink in its place. The broker resolves
  `/opt/hermes-agent/data/spool` host-side and follows it. Under `ProtectSystem=strict` the
  broker's only writable paths are the governance store and the spool, so the redirect lands
  exactly in the tree the tier exists to protect: results written into it, uuid-named `.json`
  files unlinked in it, gateway-built directories moved into it via quarantine. The same shape
  exists one level down: `_discard` does `makedirs(requests/.quarantine, exist_ok=True)`, which
  accepts a `.quarantine` symlink the gateway planted first, and `os.replace` then moves the
  entry through it.

## 2. Decisions

| # | Question (handoff) | Decision |
|---|---|---|
| Scope | — | F10a and F10b are folded into F10: a layout cannot be proven correct while the code writes `0600` and follows a gateway-controllable path. |
| 1 | Store owner | Per-directory ownership, §3.2. `control/` is root-owned so only root can create the kill switch. The README's "outright ownership" recipe (`chown -R 10000`) is removed. |
| 2 | Spool ownership and modes | Setgid + sticky `requests/` owned by the broker; pre-created broker-owned `.quarantine/`; group-read-only `results/`; `0640` files set by fd. §3.3. |
| 3 | Who creates the skeleton | New governed operator CLI `init-host-layout.py` over one layout table. Refuses any existing mismatch; never repairs. §4.1–4.2. |
| 4 | Pre-flight: missing vs unreadable | Yes. An unenterable or missing root collapses to one root-cause line; a missing subdirectory says "missing". §4.5. |
| 5 | `data/` as a whole | The spool moves out of `data/` to `/var/lib/hermes/spool`, bind-mounted into the gateway at the unchanged `/opt/data/spool`. `data/` is not widened. §3.1. |
| C | `approve-changeset.py` host identity | Out of scope. Recorded as **F12**, which gates creating the kill switch, not Phase 6. §7. |

## 3. Layout

### 3.1 Spool location

- Host path: **`/var/lib/hermes/spool`**, beside `/var/lib/hermes/governance`.
- In-container path: unchanged, `/opt/data/spool`. `spool_lib.DEFAULT_SPOOL_ROOT` and
  `hermes-syscall` need no path change.
- `docker-compose.yml`, gateway service: add
  `- ${HERMES_SPOOL_DIR:?HERMES_SPOOL_DIR must be set — see README "Spool layout"}:/opt/data/spool`
  after the `./data:/opt/data` mount. The `:?` form is deliberate: an unset variable must fail
  compose, never fall back to a path under the gateway-owned `data/` (that fallback is F10b).
  Consequence, stated: a local darwin `.env` without `HERMES_SPOOL_DIR` stops `docker compose up`
  with that message until it is set (locally, `./data/spool` is acceptable — darwin has no uid
  separation to protect).
- `.env.example`: `HERMES_SPOOL_DIR=/var/lib/hermes/spool`, beside `HERMES_GOVERNANCE_DIR`.
- `deploy/hermes-broker.service`: `HERMES_SPOOL_ROOT=/var/lib/hermes/spool`;
  `ReadWritePaths=/var/lib/hermes/governance /var/lib/hermes/spool`.
- Inside the container, `/opt/data/spool` is a mount point: the gateway cannot rename or
  replace it (`EBUSY`). On the host, no component of `/var/lib/hermes/spool` is writable by
  uid 10000.

### 3.2 Governance store (`/var/lib/hermes/governance`)

| Path | Owner:group | Mode | Rationale |
|---|---|---|---|
| (root) | `root:hermes` | `0750` | broker and executor traverse; only root renames children |
| `approvals/` | `hermes-broker:hermes` | `2750` | broker reserves and records outcomes; executor reads via group; setgid keeps group `hermes` on broker-created slug dirs and files |
| `control/` | `root:hermes` | `2750` | only root can create `mutation-enabled`; the broker cannot enable mutation |
| `control/.locks/` | `hermes-broker:hermes-broker` | `0700` | broker's per-client flocks; not listable by the executor through its `:ro` mount |
| `registry/` | `root:hermes` | `2750` | operator-edited |
| `registry/clients.json` | `root:hermes` | `0640` | created as `{}` **only if absent**; content never checked or rewritten by the tool |
| `log/` | `root:hermes` | `2750` | unchanged S3-b rule (`governance_lib.LOG_DIR_MODE`) |
| `seen/` | `hermes-broker:hermes-broker` | `0700` | broker-only replay state |

`log/<slug>.jsonl` files are not in the table: they remain `--bootstrap-logs`'s job
(`root:hermes 0660`).

**Accepted residual, documented:** `hermes-broker` is in gid 10000 (`SupplementaryGroups=hermes`)
so it can read `clients.json`. It therefore has group write on `log/*.jsonl`: it can truncate an
audit log, though it cannot unlink one (no write on `log/`). Closing this needs a second
executor-only group; not justified now. The broker already owns `approvals/` and `seen/`, so a
compromised broker is already past this.

### 3.3 Spool (`/var/lib/hermes/spool`)

| Path | Owner:group | Mode | Rationale |
|---|---|---|---|
| (root) | `root:hermes` | `0750` | nobody but root can rename `requests/` or `results/` |
| `requests/` | `hermes-broker:hermes` | `3770` | gateway creates entries (group rwx). Sticky: the broker, as directory owner, may unlink the gateway's files; the gateway may not unlink or rename broker-owned entries. Setgid: new files carry group `hermes` |
| `requests/.quarantine/` | `hermes-broker:hermes-broker` | `0700` | pre-created so the gateway can never claim the name first |
| `results/` | `hermes-broker:hermes` | `2750` | gateway reads via group, cannot write — it can no longer forge a result |
| request files | `10000:hermes` | `0640` | set by `hermes-syscall` (§4.3) |
| result files | `hermes-broker:hermes` | `0640` | set by `spool_lib.write_result` (§4.3) |

The gateway can still delete its own pending requests. That is harmless: every request is its own.

### 3.4 The existing VPS store

The bring-up left `/var/lib/hermes/governance` empty at `700 root:root`. The tool treats it as a
mismatch and refuses, like any other. The documented step is `sudo rmdir` (which only succeeds
on an empty directory) followed by `--apply`. The tool has no adopt-if-empty special case.

## 4. Components

### 4.1 `infra/hermes-agent/bin/host_layout.py` (new, stdlib-only)

The single layout table (§3.2 + §3.3) and the logic over it. Imports `governance_lib` only.

- **Table:** entries of `(root_key, relpath, kind, owner_name, group_name, mode, initial_content)`,
  ordered parent-first. `root_key` ∈ {`store`, `spool`}.
- **Resolver:** names resolve to ids via `pwd`/`grp` at run time, injectable for tests. Refuses
  if `hermes` does not resolve to `governance_lib.EXECUTOR_GID` (10000).
- **`check(store_root, spool_root, resolver=…) -> list[str]`**: `lstat` only — a symlink is
  always a problem, never followed. Per entry: missing (reported as *missing*) / wrong kind /
  wrong uid / wrong gid / mode not exactly equal (so a missing setgid or sticky bit is caught).
  Plus every ancestor of both roots up to `/`: must be root-owned and not group- or
  world-writable.
- **`plan(...)`**: per entry, `create` / `ok` / `mismatch: <reason>`. The dry-run output.
- **`apply(...)`**: refuses unless `euid == 0`. Runs `check` first; if **any existing** entry
  mismatches, or any ancestor fails, refuses before creating anything. Then, parent-first, for
  each **missing** entry only:
  - directory: `mkdir`, `open(O_DIRECTORY|O_NOFOLLOW)`, `fchown`, `fchmod` on that fd;
  - file: `open(O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW)`, write `initial_content`, `fchown`,
    `fchmod`, `fsync`;
  - re-`lstat` and verify; on mismatch remove what this call created and raise.

  It never chowns or chmods an entry it did not create.

### 4.2 `infra/hermes-agent/bin/init-host-layout.py` (new CLI)

`--store-root` (default `/var/lib/hermes/governance`), `--spool-root` (default
`/var/lib/hermes/spool`). No mode flag: dry run (prints the plan). `--apply`: create. `--check`:
verify only. Exit `0` ok · `1` usage · `2` refusal or drift. Same governed-operator-CLI pattern as
`migrate-governance.py --bootstrap-logs` (ruling R23): the pre-flight's refusal names a command
the operator can run.

### 4.3 File modes on the spool (fixes F10a)

- `hermes-syscall.submit`: `os.fchmod(fd, 0o640)` on the `mkstemp` fd before writing.
- `spool_lib.write_result`: the same.

Set on the fd, so the umask cannot defeat it.

### 4.4 Broker quarantine verification (fixes the `.quarantine` half of F10b)

In `hermes-broker._discard`, replace `os.makedirs(qdir, exist_ok=True)` with: `mkdir(qdir, 0o700)`
if absent, then `lstat(qdir)`, which must be a real directory (not a symlink), `st_uid ==
os.geteuid()`, and no group/other write. Otherwise print the reason to stderr, leave the entry in
place and return — the existing "could not remove or quarantine" path. `_discard` still never
raises; the drain survives.

### 4.5 Pre-flight (`preflight-governance-access.py`)

- If the root cannot be `stat`ed or entered, report exactly one line and return: `ENOENT` →
  "missing — run `init-host-layout.py --apply`"; `EACCES` → "uid N cannot enter". No per-child
  cascade.
- A missing child directory reports "missing", distinct from "cannot stat".
- `REMEDY`: drop the `chown -R <uid>:<gid>` alternative; point at `init-host-layout.py` (dry run,
  `--apply`, `--check`) and `migrate-governance.py --bootstrap-logs --apply`.
- Existing checks and their firing controls unchanged.

### 4.6 Broker unit

- `ExecStartPre`: `init-host-layout.py --check` first, then the existing pre-flight. Both run as
  `hermes-broker`, which can `lstat` every table entry: it traverses both roots via group
  `hermes`, and owns `seen/`, `control/.locks/` and `requests/.quarantine/`.
- `HERMES_SPOOL_ROOT` and `ReadWritePaths` per §3.1.
- The comment "the governance store [is] readable ONLY by this user" is corrected: the executor
  reads it via gid 10000.
- `deploy/units.test.py` updated to assert the new `ExecStartPre` order and paths.

## 5. Testing

Every check has a firing control: a test running it against a bad layout and showing it fails.

### 5.1 Tier 1 — unprivileged, darwin and CI (`bin/*.test.py`)

- `host_layout.check`, resolver mapped to the test process's own uid/gid. Firing controls:
  missing entry; wrong mode, including a missing setgid bit and a missing sticky bit; wrong owner
  (resolver maps the name to another uid); wrong group; symlink in place of a directory;
  group-writable ancestor; world-writable ancestor. The correct layout returns `[]`.
- `apply`: refuses when not root. With one existing mismatched entry, refuses and creates
  nothing (tree snapshot before/after). Dry run creates nothing.
- File modes: `submit` and `write_result` produce `0640` under umask `0000` and `0077`. The plan
  records a mutation check: removing the `fchmod` turns the test red.
- `_discard`: a planted symlink `.quarantine` and a group-writable `.quarantine` are refused; the
  entry stays; the drain continues and processes the other entries.
- Pre-flight: missing root yields exactly one "missing" line; `chmod 000` root (non-root process)
  yields exactly one "cannot enter" line. The existing suite passes unchanged.

### 5.2 Tier 2 — Linux integration with real ids (new CI step under `sudo`)

`infra/hermes-agent/deploy/layout-integration.test.py`, run as root on `ubuntu-latest`:

- **Setup:** create `hermes` (gid 10000), `hermes-broker`, `hermes-rail` as README step 1 does.
  Roots under a fresh root-owned directory in `/var/lib`. Running the tool against a root under
  `/tmp` must refuse (the ancestor check's firing control: `/tmp` is world-writable).
- **Round trip, real identities** (`setpriv` with the real supplementary groups):
  uid 10000 → `hermes-syscall apply` for an unregistered client; `hermes-broker` →
  `hermes-broker.py --once`; uid 10000 → `hermes-syscall result` must return a refusal
  classification. `result_unreadable` fails the test. This test fails on the pre-fix code
  (F10a), which proves the fix.
- **Attack probes as uid 10000**, each against the correct layout and a deliberately wrong one:
  delete or rename `requests/.quarantine`; rename `requests/`; create a file in `results/`. On
  the correct layout each fails with `EPERM`/`EACCES`. On the wrong layouts (no sticky bit,
  `results/` group-writable, `.quarantine` not pre-created) the attack **succeeds** and
  `init-host-layout.py --check` reports the fault.
- **Quarantine ownership:** a `.quarantine` created by uid 10000 is refused by the broker.
- **Gates as `hermes-broker`:** `init-host-layout.py --check` and the pre-flight both exit `0` on
  a fresh store with `{}` — the state the bring-up never reached. The pre-flight against a
  missing root prints one "missing" line.
- **Mount-point probe (F10b's premise):** a `busybox` container as `--user 10000`, the spool
  bind-mounted inside a bind-mounted `data/`: `mv /opt/data/spool …` must fail. Firing control:
  the spool as a plain directory under `data/`, where the same `mv` succeeds.

**Proof it ran:** CI sets `HERMES_REQUIRE_LINUX_INTEGRATION=1`. With it set, the suite exits
non-zero instead of skipping if it is not root on Linux or Docker is unavailable, and it prints
the number of tests executed. That count is read in the CI log on the PR and on the merge
commit.

### 5.3 Unproven until the VPS (stated, not hidden)

- The systemd sandbox: `ProtectSystem=strict` with the new `ReadWritePaths`.
- The real gateway process identity inside the hermes-agent image.
- The compose `:?` interpolation against the real `.env` — cannot be exercised here without
  `docker compose config`, which is banned (it prints secrets).

## 6. Documentation

- **README "Ownership on a Linux host":** rewritten around the §3.2 table and
  `init-host-layout.py` (dry run → `--apply` → `--check`). The group-access `chgrp`/`chmod`
  recipe and the "outright ownership" recipe are both removed. The S3-b reasoning for `log/`
  stays, as does `--bootstrap-logs`, plus a paragraph on the §3.2 residual.
- **README "Spool layout":** host path, §3.3 table, and why the spool is not under `data/`
  (F10b). Fix `result --request` to `result --request-id` (the CLI flag).
- **README "VPS deploy sequence" step 2:** `sudo rmdir` the empty store; set `HERMES_SPOOL_DIR`
  in `.env`; `init-host-layout.py` dry run → `sudo … --apply` → `--check` as `hermes-broker`;
  `--bootstrap-logs` (a no-op with zero clients); pre-flight as `hermes-broker` must exit `0`.
  Later steps renumbered only if the insertion requires it.
- **`deploy/BRING-UP.md` Phase 6:** the banner stays, narrowed to "Blocked on F9 (bind paths vs
  the proxy allow-list). The store/spool layout (F10) is landed — see README step 2." The layout
  bullets are replaced by that pointer. The on-box layout table (`:200`) gets the new spool path.
- **Findings record:** F10 marked fixed, pointing to the PR, with F10a, F10b and the pre-flight
  collapse as sub-items. F12 added (§7). The effect on F9 is written down (§8). The open-items
  list loses F10 and gains F12.

## 7. F12 — recorded, not fixed here

`approve-changeset.py` reads the change-set from `data/vaults/` (uid 10000, `700`) and writes
`approvals/<slug>/` plus a `0600` lock file beside each approval, which the broker later reopens.
Run as root, it leaves root-owned `0600` lock files and `reserve_approval` fails on the first
apply. Run as `hermes-broker`, it cannot read `data/vaults`. Separately, approval and snapshot
files are written with plain `open()`, so they are group-readable only because of the umask. The
handoff's §6 `UMask=0077` gate would make every approval unreadable to the executor.

**F12 gates creating the kill switch.** It does not gate Phase 6: installing the units and
running the pre-flight approves nothing, and mutation stays disabled. F10's `approvals/`
ownership (`hermes-broker:hermes 2750`) is compatible with any F12 fix.

## 8. Effect on F9

- The spool is not mounted into `ads-mutator` and does not appear in `docker-create-proxy.py`,
  so F10 adds nothing to the proxy allow-list.
- The store's host path is unchanged, so F9's governance bind paths are unchanged.
- F9's design must not move the spool back under `data/`.

## 9. Landing

- Branch `fix/f10-store-and-spool-layout`. Stage by explicit path only; never `.project-brain/`
  or `evals/`.
- Redaction scan over **added lines only**, with a live control that must fire.
- All suites green: hermes bin, node, units, provision, and the Tier 2 integration step on CI.
- One PR. CI checked on the PR **and on the merge commit**, including the Tier 2 executed-test
  count on both.
- Nothing is applied to the VPS in this session. Mutation stays disabled; the kill switch is not
  created.

## 10. Out of scope

F9 (bind paths vs proxy allow-list); F12 (§7); F3, F6, F8 from the findings record; any change to
`data/` ownership; the Tailscale proposal (PR #31).
