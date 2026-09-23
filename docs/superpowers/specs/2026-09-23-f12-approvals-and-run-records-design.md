# F12 — Approvals and run records vs `data/vaults` (design)

> **Status:** design approved in brainstorming, 2026-09-23; amended during execution
> (R1: §2.4's per-client directory mode is `0o2750`, not `0750` — see the correction there).
> Plan: `docs/superpowers/plans/2026-09-23-f12-approvals-and-run-records.md`.
> **Finding:** F12 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`
> **Predecessors:** F10 (`2026-09-21-f10-governance-store-and-spool-layout-design.md`) laid the
> store this design extends; F9 (`2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md`)
> pinned the executor's binds, which this design must not disturb.
> **Constraints carried forward:** mutation stays disabled (no kill switch); the proxy, its
> `--allow-bind` set and the seven `ads-mutator` binds are untouched; the spool stays out of
> `data/` and off the allow-list; every new check has a firing control; Linux ownership is
> proven on the Linux CI runner or stated as unproven; never read or print `.env`; never
> `docker compose config`.

## 1. Problem

Two host-side tools on the mutation rail reach into `data/vaults`, which belongs to the gateway
(uid 10000, `data/` is `700`). Neither can.

- **Approvals.** `approve-changeset.py` reads the proposed change-set from the vault, then writes
  a snapshot and an approval record into the governance store, plus a lock sidecar
  (`_approval_lock`, `changeset_lib.py:741-777`) that the broker reopens at reserve time. Run as
  root it leaves that sidecar root-owned `0600`, and `reserve_approval` fails on the first apply.
  Run as `hermes-broker` it cannot read the vault at all. The approval and snapshot are written
  with plain `open()` (`_atomic_write_json`, `write_snapshot_bytes`), so their group readability
  is a umask accident — and the planned `UMask=0077` hardening would make every approval
  unreadable to the executor that must verify it.
- **Run records.** `run-ads-mutate.sh` runs as `hermes-broker` inside the broker's sandbox and
  calls `persist-run-record.py`, which writes `changes/<cid>.result.json` and appends
  `timeline.md` **inside the vault**. Two independent walls stop it: `data/` is `700` uid 10000,
  and `data/vaults` is not in the unit's `ReadWritePaths=`
  (`hermes-broker.service:53` lists only the store and the spool). The failure surfaces as the
  "RUN RECORD NOT PERSISTED" banner, with the executor's exit status preserved.

**F12 gates the kill switch and the rehearsal**, not Phase 6: installing the units approves
nothing. Without it no approval can be written at all, so no request can ever be approved.

### 1.1 Why "let the executor write the vault" is not an option

`ads-mutator` has **no vault mount**. Its seven binds are the four governance directories, the
ads repo, `registry` and `cc-bin` (F9 §3.2). Giving the executor vault access would mean adding
an eighth bind and widening the proxy's pinned set — forbidden. So on the mutation path the vault
is unreachable from both the broker (permissions) and the executor (no mount). Moving the records
is the only fix that leaves the security gate alone.

## 2. Decisions

### 2.1 Run records move to the governance store

`persist_run_record_shim.persist()` writes into `<store>/records/<slug>/` instead of the vault:
`<cid>.result.json`, and an appended `timeline.md`. `persist-run-record.py` resolves the store
root (the broker unit already exports `HERMES_GOVERNANCE_ROOT`) rather than
`vault_lib.resolve(...)["vault_path"]`, and still refuses an unknown slug.

The existing containment hardening carries over **unchanged**: every destination proven inside the
records directory, opened relative to an already-open directory fd, `O_NOFOLLOW`, a regular-file
assertion and a single-link assertion; anything unprovable raises `PersistRefused` rather than
being skipped (`persist_run_record_shim.py:360-420`). `run-ads-mutate.sh`'s unmissable banner and
the rule that the executor's exit status wins are unchanged.

Files are written `0640` **explicitly**, never by umask, so `UMask=0077` cannot make them
unreadable later.

`ReadWritePaths=` needs no change: `/var/lib/hermes/governance` is already there.

**Accepted loss (operator decision, 2026-09-22).** Applied changes stop appearing in the vault's
`timeline.md`, which `run-trend-audit.sh` feeds the analyst as "THIS client's prior history". The
audit path keeps writing that file from inside the container (`vault-write.py`); only the
mutation path stops. Governance is unaffected — `apply-changeset.py:363` already calls
`result.json` and `timeline.md` "convenience artifacts", the authoritative record being the
governance audit log, fsynced per action. If the analyst is later shown to need applied-change
history, that is its own design, not a vault writer resurrected on the mutation path.

### 2.2 Approvals get deterministic ownership and modes

A helper in `changeset_lib` sets owner and mode on an **open file descriptor** (`os.fchown` /
`os.fchmod`), never by path, so no symlink swap between create and chmod can redirect it. It is
applied by `_atomic_write_json`, `write_snapshot_bytes` and `_approval_lock`:

| Artifact | Mode | Owner when run as root |
|---|---|---|
| approval record | `0640` | `hermes-broker:hermes` |
| change-set snapshot | `0640` | `hermes-broker:hermes` |
| approval lock sidecar | `0660` | `hermes-broker:hermes` |

Ownership and mode are set on the **temp file before `os.replace`**, so the file that lands is
never briefly wrong. Groups are resolved **by name** (`hermes`, `hermes-broker`); a missing group
is a refusal, never a guessed gid. When not running as root, mode is still set explicitly and
ownership is left alone (see §2.3).

This closes both recorded defects: the root-owned `0600` sidecar that breaks `reserve_approval`,
and the umask dependence that `UMask=0077` would turn fatal.

### 2.3 `approve-changeset.py` requires root on Linux

Reading the proposal needs root anyway (`data/` is `700` uid 10000), and a non-root writer leaves
artifacts the broker cannot reserve — a failure that would otherwise surface hours later, at apply
time, as a governance-looking refusal. So on Linux the tool refuses unless `os.geteuid() == 0`,
with a message naming `sudo ./changeset.sh approve …`. On darwin it behaves as today: there is no
uid separation to honour, and the dev flow must keep working.

### 2.4 The store gains one layout row

Following F10's table exactly (`bin/host_layout.py:35-46`):

```python
Entry("store", "records", DIR, "hermes-broker", "hermes", 0o2750, None)
```

Per-client directories `records/<slug>/` are created by the writer at **`0o2750`** — the same
mode as `records/` itself, setgid included. `init-host-layout.py` creates and verifies the row
like every other entry, and never repairs.

**CORRECTION (R1, 2026-09-23, found in Task 2's review).** This section originally said `0750`,
which is wrong and self-defeating on Linux: `records/` is setgid, so `os.mkdir` gives the new
directory group `hermes` AND an inherited `S_ISGID`, and a subsequent `fchmod(0o750)` strips that
bit. Files created afterwards then take the writer's egid — `hermes-broker`, since the broker runs
`Group=hermes-broker` with `hermes` only supplementary — so the records land
`hermes-broker:hermes-broker` and an operator in group `hermes` cannot read them, which is the
exact outcome this row's setgid bit exists to prevent and what §3.2's Tier 2 assertion checks.
Darwin inherits groups from the parent directory regardless, so a green darwin suite proves
nothing here. Keep the setgid bit: `0o2750`.

### 2.5 The pre-flight deliberately does not change

`preflight-governance-access.py` declares what the **executor inside the container** needs.
`records/` is host-side only and has no mount. Adding it there would make the pre-flight demand
access to something that does not exist in the container and false-refuse every run — the mirror
of the coupling F10 hit when it dropped the `seen/` mount. A test asserts `records` is **absent**
from the executor's declared read-write directories, so a future well-meaning addition fails
loudly.

### 2.6 Untouched

The proxy and its allow-list; the seven `ads-mutator` binds; `docker-compose.yml`; the spool; the
governance audit log and the approval's hash-binding semantics; `ReadWritePaths=`; the units. No
kill switch is created by anything in this design.

## 3. How it is proven

### 3.1 Tier 1 — every platform, discovered by `run-bin-tests.sh`

- **Records destination:** `persist-run-record.test.py` re-pointed at `records/<slug>/`. Its
  containment cases (a `timeline.md` symlinked out of the tree, a hardlinked result file, a
  non-regular destination) must still raise `PersistRefused` — those are the firing controls, and
  they already exist; they guard a new root.
- **Wrapper behaviour unchanged:** `run-ads-mutate.test.py` still proves the persist banner is
  unmissable and that the executor's exit status wins over a persist failure.
- **Hostile umask (the control for §2.2):** with `umask 0077`, the approval and snapshot are still
  `0640` and the sidecar `0660`. This test FAILS against today's code — umask dependence is the
  defect.
- **Root requirement:** the Linux refusal fires without root and names `sudo`; control — it does
  not fire on darwin.
- **Pre-flight negative:** `records` is absent from the executor's declared read-write dirs.
- **Layout row:** `host_layout.test.py` covers `records` with owner, group and mode; the suite's
  existing wrong-mode control already proves the checker can fail.

### 3.2 Tier 2 — root on Linux CI, real uids and gids (`layout-integration.test.py`)

- **The centrepiece — reproduce F12, then show it fixed.** As **root**, approve a change-set; as
  **`hermes-broker`**, reserve that approval. Today this fails on the root-owned `0600` sidecar,
  which is exactly what the finding records; after the fix it succeeds.
  **Firing control:** force the old shape (root-owned `0600` sidecar) and assert
  `reserve_approval` still fails, so the test is watching the right thing.
- **Records round trip:** as `hermes-broker`, persist into `records/<slug>/`; assert `0640`, that
  the **gateway (uid 10000) cannot write** there, and that a member of group `hermes` can read.
  **Firing controls:** a `records/` without setgid loses group inheritance; a `0770` `records/`
  lets the gateway write.
- **Executor readability:** an approval written by root is readable by uid 10000. Control: `0600`
  makes it unreadable.

No CI wiring changes: `layout-integration.test.py` is already its own step, and the
`bind-agreement` job is untouched.

## 4. Operator impact

**On the box, after the merge** — no downtime, no unit change, no restart:

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
cd /opt/hermes-agent
python3 bin/init-host-layout.py                                   # dry run: "create records"
sudo python3 bin/init-host-layout.py --apply
sudo -u hermes-broker python3 bin/init-host-layout.py --check     # must exit 0
```

**Nothing to migrate:** the kill switch has never existed, so no apply has ever run, so no run
records exist anywhere.

**Changed command:** approvals are now `sudo ./changeset.sh approve …` on Linux.

**Docs:** README's change-set section (the root requirement and where records live), the note at
README:533 about container-path defaults extended to the records root, and BRING-UP's rehearsal
gate — F12 moves from blocking to landed, leaving `.env.gaw` with the WRITE credential as the
remaining prerequisite.

## 5. Order of work

1. Records destination in the persist shim, containment tests re-pointed.
2. The `records` layout row, `init-host-layout` coverage, the pre-flight negative test.
3. The fd-based owner/mode helper applied to approval, snapshot and sidecar, with the umask
   control.
4. `approve-changeset.py`'s root requirement and message.
5. Tier 2: the root-approves → broker-reserves round trip and the records round trip, with every
   firing control.
6. Docs (README, BRING-UP) and F12 marked fixed in the findings record.
7. Brain note (unstaged); final whole-branch review; redaction scan over added lines with a live
   control; PR; CI read on the PR **and** on the merge commit; then the box step in §4.

## 6. Accepted risks and what stays unproven

- **Ownership only means something under root with real identities**, so Tier 1 asserts modes and
  Tier 2 carries the ownership half — which is where F15 proved the gaps hide.
- **The first real apply still cannot be exercised**: it needs the kill switch, which stays absent.
  The rehearsal after F12 exercises broker → proxy → container → `refused_preflight`.
- **`UMask=0077` is not applied by this design.** F12 makes the artifacts umask-independent so
  that the §6 hardening can land later without breaking approvals; landing it is that wave's work.
- **F14 is unchanged and still open**: a Compose failure is reported as "nothing was mutated",
  which could be false mid-run. It gates the kill switch alongside this.
