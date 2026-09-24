# VPS first bring-up — findings (2026-09-21)

First time anything in `infra/hermes-agent/deploy/` ran on a Linux host. Session driven from
`docs/superpowers/handoffs/2026-09-21-vps-deployment-and-local-access.md`, following
`deploy/BRING-UP.md` at `bbe5dd3`. The assistant had no access to the box. The operator ran
every command and pasted the output back, and the observations below come from that output.

**Mutation stayed disabled throughout. The kill switch was never created. The only credentials
on the box are a dummy `ANTHROPIC_API_KEY`, the operator's deploy key, a sudo password and the
dashboard basic-auth password. None of them appears in this document or in git.**

## Outcome

| Phase | Status |
|---|---|
| 0 Buy / key | done — needed a root key-authorization step the runbook lacked (F1) |
| 1 Harden | done — `--check` **17/17, exit 0**; root login refused from outside; **sudo unusable as provisioned** (F3) |
| 2 Layout | done — runbook `mkdir`-then-`ln -s` bug avoided (F5); ads repo is a **placeholder** (F6) |
| 3 `.env` | done — dummy key, `600 root:root`, checkout clean |
| 4 Start | done — binds measured **before** `up` (F7); `data/` ownership fixed (F8); gateway running, `claude 2.1.278` |
| 5 Bind paths | **fixed and CONFIRMED ON THE BOX** (F9, PR #38; BRING-UP Phase 6 run 2026-09-22) |
| 6 Units | **installed and running on the box** (2026-09-22) — after F15; F10 applied to the box the same day |
| 7 Dashboard | done — form login enforced, reachable only through an SSH tunnel |

Host: Hostinger KVM 2, Ubuntu 24.04.4 LTS, x86_64, kernel 6.8.0. Docker 29.8.1, compose plugin
5.5.1, containerd 2.3.5. fail2ban 1.0.2.

## Findings

Each finding has a **Fix** line, which says whether it is fixed in this PR's runbook or
still open.

### F1: nothing authorized the key for root. Batch mode then hid the real error

Phase 0 generated a key and Phase 1 `scp`'d as root with it, but no step installed it for root.
After it was installed, the test command (`-o BatchMode=yes`) still returned
`Permission denied (publickey,password)`. The server-side fingerprint was present, and the
test then succeeded without batch mode (`KEY_LOGIN_OK`). The key has a passphrase, and batch
mode cannot prompt for it, so ssh gave up. That looks identical to a key the server rejected.
**Fix:** runbook Phase 0 step 4 (in this PR).

### F2: the apt lock was held by unattended-upgrades on first boot

`Waiting for cache lock ... held by process 3904 (unattended-upgr)`, nine lines, and then apt
continued. Harmless. **Fix:** noted in runbook 1b (in this PR).

### F3: the deploy user cannot use sudo, and `--check` passes anyway

`provision.sh:153` runs `adduser --disabled-password`. `:159` adds the user to `sudo`. Nothing
sets a password or a `NOPASSWD` rule. Measured:
`sudo: a password is required`, `SUDO_EXIT=1`. After `passwd hermesops`: `SUDO_OK`. The check
"hermesops is in the sudo group" passed, and **none of the 56 tests notices the difference
between membership and usability.** The runbook's own step 1d ("`sudo -v` should exit cleanly")
could never have passed. The handoff predicts exactly this: the defect is in the code that
*verifies*.
**Fix:** runbook step 1b-2 (in this PR). **Open:** a `--check` that asserts a usable password
(`passwd -S` state `P`), and a test that shows it reporting DRIFT on a
`--disabled-password` account. That second test is the control that proves the check can fail.

### F4: the uid in the runbook example was guessed

The runbook said `uid=1002`. Measured `uid=1000(hermesops) gid=1000(hermesops)`. **Fix:** in this
PR.

### F5: `mkdir /opt/hermes-agent` followed by `ln -s ... /opt/hermes-agent` builds the wrong layout

When the link path already exists as a directory, `ln -s` puts the link inside it. This was
caught before running and skipped. Measured result:
`/opt/hermes-agent -> /opt/projects/claude_code/infra/hermes-agent`. **Fix:** in this PR.

### F6: the ads repo is private and holds client-adjacent material

`claude_code` is public, so an HTTPS clone needs no credential. `claude-google-ads` is private,
and its tracked files include account-level audit reports. The operator chose an **empty
placeholder** until after the security review. It contains a `PLACEHOLDER` marker and an
**empty `.env`**, because `docker-compose.yml:70` binds a mask file onto that path inside a
`:ro` mount. That the start would fail without the `.env` is *predicted, not observed*: the file
was created before `up`. **Fix:** runbook Phase 2 (in this PR). Deploy-key clone is deferred.

### F7: the runbook started the stack before measuring its binds

Phase 4 (`up`) came before Phase 5 (bind measurement). Reading the compose file suggested that if
compose resolved paths from `/opt/hermes-agent` lexically, the gateway's `../..` mount would be
`/`, i.e. the host root inside the gateway. Measured with `create` + `inspect` and no start. The
output was identical from the symlink and from the physical path. **Compose resolves the
symlink**, so the source is `/opt/projects/claude_code`. The hazard is not real, but the order was
still wrong: it relied on luck. **Fix:** runbook Phase 4 now measures first (in this PR).

### F8: `data/` and `data/skills` are root-owned on Linux

`data/` is gitignored, so it does not exist on a fresh clone. Docker creates missing bind
sources as root **at start**. `create` did not create it, as measured: after `create`/`down`,
`data` still did not exist. The container runs as uid 10000. The fix was applied before `up`:
`install -d -o 10000 -g 10000 -m 700 data`. `data/skills` was still measured `755 root:root`
afterwards, because compose mounts four skills inside it. The gateway logs
`Permission denied: '/opt/data/skills/github'` and `.../software-development` while seeding
bundled skills, and also `docker_config_migrate.py failed; continuing`. Docker Desktop hides
all of this on macOS. **Fix:** `data/` in the runbook (in this PR). **Open:** `data/skills`
ownership, and the migrate warning.

### F9: the bind paths do not match the proxy allow-list — fixed (PR #38)

Measured binds of the `hermes-agent` service (identical from both directories):

```
/opt/projects/claude_code/infra/hermes-agent/bin:/opt/cc-bin:ro
/opt/projects/claude_code:/projects/claude_code:ro
/opt/projects/claude_code/infra/hermes-agent/masks/empty:/projects/claude_google_ads/.env:ro
/opt/projects/claude_code/infra/hermes-agent/data:/opt/data:rw
/opt/projects/claude-google-ads:/projects/claude_google_ads:ro
/opt/projects/claude_code/infra/hermes-agent/registry:/opt/registry:ro
/opt/projects/claude_code/infra/hermes-agent/skills/claude-code-operator:/opt/data/skills/claude-code-operator:ro
/opt/projects/claude_code/infra/hermes-agent/skills/claude-code-proposer:/opt/data/skills/claude-code-proposer:ro
/opt/projects/claude_code/infra/hermes-agent/skills/claude-code-reviewer:/opt/data/skills/claude-code-reviewer:ro
/opt/projects/claude_code/infra/hermes-agent/skills/claude-code-ads-analyst:/opt/data/skills/claude-code-ads-analyst:ro
```

`hermes-docker-proxy.service:37-38` allow-lists `/opt/hermes-agent/registry` and
`/opt/hermes-agent/bin`. The proxy requires the bind set to equal the pinned set exactly
(`docker-create-proxy.py:231-232`), so `ads-mutator` creation would be refused. A real directory
at `/opt/hermes-agent` would fix those two, but it would send `../../../claude-google-ads` to
`/claude-google-ads`. **This is an inference for `ads-mutator`, which uses the same relative
forms.** It was deliberately not created, because doing so before README step 2 would have made
Docker lay the governance subdirectories down as root. Nothing was widened.
**Was open:** a design fix in the repo. The candidates are pinning the allow-list to the canonical
paths, or giving compose absolute paths. The fix must keep `proxy-policy-sync.test.py` meaningful.

**Correction (2026-09-22, measured on Linux CI).** The measurement above was partly caused by how
it was taken. `sudo docker compose` run from the working directory has no `PWD`, so Compose
takes the resolved path as its project directory. The broker's real path
(`run-ads-mutate.sh`, `-f /opt/hermes-agent/docker-compose.yml`) sends `/opt/hermes-agent/bin`
and `/opt/hermes-agent/registry`, which match the pins, and `/claude-google-ads`, which does not.
No invocation matched all seven. The root cause was the relative sources. See spec
`2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md` §2, M1 and M6.

**Fix (PR #38).** Every `ads-mutator` source is an absolute `:?`-guarded variable, set by the
broker unit and equal to the proxy's pins. The allow-list and the proxy are unchanged.
`proxy-policy-sync.test.py` compares the strings on every platform, and the CI job
`bind-agreement` drives the broker's path through the real proxy on Linux.

**Second defect on the same path, fixed in the same PR.** `hermes-broker` cannot read `.env`
(`600 root:root`), and Compose aborts on an unreadable `.env` even when every variable is
exported (M4). `run-ads-mutate.sh` now passes `--env-file /dev/null`, and the broker unit
supplies the variables. The handoff's first half was wrong: `hostenv.sh` never read `.env` as
the broker, because the unit already sets `HERMES_GOVERNANCE_DIR`.

**Remaining:** the box confirmation (BRING-UP Phase 6) on the box's own Compose and real image.

### F10: Phase 6 assumes a governance store and spool that nothing creates on a fresh box

README step 1 ran. Measured result: `hermes:x:10000:hermes-broker`, `docker:x:988:hermes-docker-proxy`,
and `hermes-broker` is not in `docker`. The pre-flight, run as `hermes-broker` against the empty
`700 root:root` store, refused with exit 2. It reported every subdirectory as `Permission denied`,
because it cannot tell "missing" from "unreadable" when the root cannot be entered. Its
suggested fix `chmod`s a `log/` that does not exist. Gaps:

- `approvals/`, `control/`, `registry/`, `log/`, `seen/` and `registry/clients.json`: only
  `migrate()` from local vaults creates any of these, and the VPS has no vaults.
  `--bootstrap-logs` refuses a missing `log/` by design.
- The store owner. The broker writes `seen/` (`hermes-broker.py:403`), `approvals/`
  (`:495`, `:520`) and `control/.locks/`, but README:894 says only "deploy/broker user".
- `data/spool/` must exist for the broker unit's `ReadWritePaths=`. uid 10000 writes it, and
  `hermes-broker` reads, deletes and quarantines in it. But `data/` is `700` uid 10000, and the
  spool's Linux permissions are undocumented. It is the only channel between agent and broker,
  so this is a security design decision.

**Fixed** in PR #35 (design: `docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md`).
Reading the code to design the layout found three more faults, fixed in the same PR:

- **F10a — the spool could not work on Linux in either direction.** Both sides wrote `0600`
  (`mkstemp`), so the broker could not read requests and the gateway could not read results.
  Spool files are now `0640`, set on the fd.
- **F10b — a spool under `data/` redirects the broker into the store.** The gateway owns `data/`,
  so it could swap the spool, or a pre-planted `.quarantine`, for a symlink. The spool moved to
  `/var/lib/hermes/spool` as its own bind mount, and the broker verifies `.quarantine` before use.
- **The pre-flight cascade.** A missing or unenterable root is now one line naming
  `init-host-layout.py`. A missing child says "missing".

Stated residual: a non-empty directory the gateway plants in `requests/` stays in place and is
logged on every drain (R1). Unproven until the VPS: the systemd sandbox with the new
`ReadWritePaths`, the gateway's real identity in the image, and compose's `:?` against the real
`.env`.

**Effect on F9.** The spool is not mounted into `ads-mutator` and is not in the proxy allow-list,
so F10 adds nothing there. The store's host path is unchanged. F9's design must not move the spool
back under `data/`.

### F11: the dashboard login is a form, `/api/status` needs no credentials, and a length guard warned without stopping

- `/` returns `302 -> /login?next=%2F` ("Sign in — Hermes Agent"). `/api/config`,
  `/api/sessions` and `/api/logs` return `401`. `/api/status` returns `auth_required = True`,
  `auth_providers = ['basic']`. The step had been written expecting `401` from `/`.
  **Fix:** in this PR.
- `/api/status` returns `200` without credentials. Field names: `active_agents`,
  `active_sessions`, `auth_providers`, `auth_required`, `can_update_hermes`, `config_version`,
  `gateway_*` (state, mode, platforms, busy, drainable, exit reason, updated_at),
  `latest_config_version`, `nous_session_valid`, `profiles`, `release_date`,
  `restart_drain_timeout`, `version`. These are operational fields, with no credentials and no client data.
  **Accepted** while it is loopback-only. Revisit if the dashboard is ever exposed any other way.
- The first password write used a length check that only *printed* `TOO SHORT`. The next line
  ran anyway and wrote a 13-character value, while the password manager held 22. This was found
  by comparing lengths only: file = container = 13, manager = 22. **Fix:** Phase 7a is now a
  single `if` (in this PR).
- The browser controls were run after the fix. A wrong password was refused, and the correct
  one signed in.

### F12: approvals and run records vs data/vaults — fixed (PR #42)

**Was open:** found while designing F10. `approve-changeset.py` reads the change-set from
`data/vaults/` (uid 10000, `700`) and writes `approvals/<slug>/` plus a `0600` lock file that the
broker later reopens. Run as root, it leaves root-owned `0600` locks, and `reserve_approval`
fails on the first apply. Run as `hermes-broker`, it cannot read `data/vaults`. Approval and
snapshot files are written with plain `open()`, so they are group-readable only because of the
umask; the 2026-09-17 handoff's §6 `UMask=0077` would make every approval unreadable to the
executor.

Second case: `run-ads-mutate.sh` runs as `hermes-broker` inside the broker's sandbox, and after
every apply it calls `persist-run-record.py`, which writes into `data/vaults/<slug>/`. `data/` is
`700` uid 10000, and `data/vaults` is not in `ReadWritePaths`, so the write fails. The failure
shows as the "RUN RECORD NOT PERSISTED" banner, with the executor's exit status kept.

**Gates creating the kill switch, not Phase 6.** Installing the units approves nothing.
F10's `approvals/` ownership (`hermes-broker:hermes 2750`) is compatible with any F12 fix.

**Fix (PR #42).** Run records move to `<store>/records/<slug>/` — `hermes-broker:hermes 0o2750`
(setgid preserved: R1 — `0750` would have stripped it and left records unreadable to group
`hermes` on Linux), files `0640` — so the mutation path never writes the vault. The writer
refuses outright if `records/` itself is missing, naming `init-host-layout.py --apply`: the
layout is a hard prerequisite, not something created ad hoc. The executor could not have
written the vault either: `ads-mutator` has no vault mount, and giving it one would widen the
proxy's pinned set (F9). Approval artifacts get explicit modes and ownership set on the open fd,
before the rename: approval and snapshot `0640`, lock sidecar `0660`, owner
`hermes-broker:hermes` when root — killing both the root-owned `0600` sidecar that broke
`reserve_approval` and the umask dependence that `UMask=0077` would have made fatal. The
per-client APPROVALS directory gets the same ownership and mode (R2, traced during review):
without it, the broker still could not create its temp file or lock sidecar inside a root-owned
`02755` directory — F12's symptom reappearing at a different file, so fixing the sidecar's mode
alone was necessary but not sufficient. `approve-changeset.py` now refuses non-root on Linux
with a message naming `sudo`.

**How it is proven (executed on Linux CI — see the result below):** Tier 2 reproduces the recorded
failure and shows it fixed — root approves, the broker reserves — with a firing control that forces
the old root-owned `0600` sidecar, and a second that forces a root-owned `02755` approvals
directory, each failing at a different site (the original defect and R2's). A second round trip
shows the broker writing a run record that a member of group `hermes` reads back, the gateway
(uid 10000) refused with `Permission denied`, and a `0770` group-writable control proving that
refusal comes from the mode. These ran with real uids and gids; darwin cannot exercise setgid
group inheritance at all (BSD vs System V), which is the mechanism the records design rests on.
**CI RESULT (PR #42, run 35890456609, 2026-09-23): `layout-integration: executed 30, skipped 0, failures 0, errors 0`** — 22 before F12, so all eight new Tier 2 tests ran and passed with real uids and gids. `bind-agreement: executed 6, skipped 0` stayed green alongside them.

**Deliberate loss:** applied changes no longer appear in the vault's `timeline.md`, which
`run-trend-audit.sh` feeds the analyst as client history. The audit path still writes that file;
governance is unaffected (the fsynced audit log is the authoritative record). Revisit as its own
design if the analyst is shown to need it.

**Still open:** audit-log truncation (§6 part B). F18 is
fixed (PR #50). The
framing hardening and `UMask=0077` (§6 part A) are in PR #48. F14 (a Compose failure reported as
"nothing was mutated") is fixed (PR #46).

**§6 part A merged and applied to the box, 2026-09-23.** Merge commit `e1110bb`: CI run
35927728502, `bind-agreement: executed 6, skipped 0`, `layout-integration: executed 30, skipped
0`. The box pulled `4074295..e1110bb`, re-copied both units and ran `daemon-reload`; after the
restart, `systemctl show -p UMask` gave `UMask=0077` for both units, the socket was still
`hermes-docker-proxy:hermes-rail 660`, both units `active`, `NRestarts=0`. **Real traffic through
the stricter parser, on the box:** BRING-UP Phase 6's create gave `rc=2` (`mutation is disabled`)
and the proxy logged `ALLOW POST /v1.55/containers/create?name=hermes-agent-ads-mutator-run-…`,
with no `malformed` refusal — which also discharges the end-to-end check the 2026-09-17 handoff §5
owed for `65df9b1`. Kill switch: absent (checked with `sudo test`).

**Applied to the box, 2026-09-23.** Pulled `da2a0ae..9df03d4` (fast-forward, no mode conflict).
Firing control first: `sudo -u hermes-broker init-host-layout.py --check` exited **2**, naming
only `/var/lib/hermes/governance/records: missing, expected dir hermes-broker:hermes 2750`.
Then `--apply` printed `created /var/lib/hermes/governance/records` and `layout OK`; the same
`--check` exited **0**; `stat` showed `hermes-broker:hermes 2750`; both units `active`,
`NRestarts=0` on the broker; a `sudo` dry run showed all 13 rows `ok`. **Still unexercised on the
box:** an approval written by the new code, and a run record — both wait for the rehearsal gate.

### F14: a Compose failure is reported as "refused, nothing was mutated" — fixed (PR #46)

`docker compose run` exits 1 on any Compose-level failure. Two such failures were measured on
Linux CI (2026-09-22): a proxy refusal at create, and an unreadable `.env`. The broker maps
exit 1 to `refused_usage`, whose detail says "nothing was mutated" (`hermes-broker.py`,
`CLASSIFICATION_BY_RC` / `DETAIL_BY_CLASSIFICATION`). For a refusal at create, that is true.
If Compose loses the proxy connection **after** the container started, it may also return 1
while the executor is mid-apply, and the broker would promise "nothing was mutated" about a run
that may have changed the account. That goes around the exit-2 guarantee in
`apply-changeset.py`. **Inferred, not measured.** It gates the kill switch, not the rehearsal:
the kill switch is absent there, so nothing can be mutated. ~~Open: a distinct wrapper exit
code for "Compose failed before the container started", designed in its own PR (F9 spec §3.7,
§5).~~ Superseded by the fix below: instead of a distinct code for that one case, the wrapper
now verifies EVERY exit and falls back to exit 4 whenever it cannot, which covers this case
along with any other unattested Compose failure.

**Fix (PR #46, spec `2026-09-23-f14-attested-executor-exit-design.md`).** The executor prints
`HERMES-EXIT <nonce> <rc>` for the exits it chose, bound to a per-run nonce the wrapper
generates; `run-ads-mutate.sh` passes 0–3 through only on exactly one exact match and
otherwise exits **4**, which the broker records as `failed_unverified_exit` ("possibly
modified") and the Hermes client returns as `EXIT_FAILED_AFTER_MUTATION`. Pre-start Compose
failures are now false alarms by decision. **Measured on Linux CI** (run 35905446915): the proxy
refusing the create gives wrapper status 4 with `compose rc=1`; the broker path's real refusal
is attested (`bind-agreement: executed 6, skipped 0`). **Still unmeasured:** an actual
connection loss after the container started — the fix does not depend on it.

**Merged and applied to the box, 2026-09-23.** Merge commit `4074295`: CI run 35908282335,
`bind-agreement: executed 6, skipped 0`, `layout-integration: executed 30, skipped 0`. The box
pulled `9df03d4..4074295` (fast-forward), `init-host-layout.py --check` as `hermes-broker`
exited 0, and `hermes-broker` was restarted (`ActiveEnterTimestamp` 19:41:36 UTC, `NRestarts=0`,
the unit's `ExecStartPre` logged `layout OK`); both units `active`. On disk:
`run-ads-mutate.sh` carries `set +eu  # F14`, `hermes-broker.py` the `failed_unverified_exit`
mapping. **Still unexercised on the box:** a real run through the new path — it waits for the
rehearsal gate (`.env.gaw` with the WRITE credential). Kill switch: absent.

### F15: the proxy unit execs a script that is not executable in git — fixed (PR #40)

**Measured on the VPS, 2026-09-22**, installing the units for the first time (BRING-UP Phase 5).
`hermes-docker-proxy.service` runs `ExecStart=/opt/hermes-agent/bin/docker-create-proxy.py …`
directly, but the file shipped `100644`. systemd could not exec it:
`Active: failed (Result: exit-code)`, `status=203/EXEC`, `Duration: 32ms`. The broker then
failed behind it with "Dependency failed", because it `Requires=` the proxy. The units were
otherwise correct: both `ExecStartPre` checks exited 0, and `id hermes-broker` showed
`hermes-broker, hermes-rail, hermes` with no `docker`.

**Why nothing caught it.** `bind-agreement-integration.test.py` starts the proxy as
`python3 <script>`, so it never needs the bit; `units.test.py` asserted what the unit files
SAY. Neither runs systemd. The same class as F9's own lesson: a check that never exercises
the real invocation proves nothing about it.

**Fix (PR #40).** `bin/docker-create-proxy.py` is `100755` in git, and
`units.test.py::TestExecStartProgramsAreExecutable` now asserts that every `Exec*` program
that is a repo file (i.e. run directly, not via `/usr/bin/python3`) is `100755` in the git
INDEX — the working tree's mode is a local accident. It has two controls: one proving the
mode lookup distinguishes `100755` from `100644` and an untracked path, and one proving the
parser actually finds a directly-executed program (otherwise the assertion would pass
vacuously). It failed against the pre-fix tree with `'100644' != '100755'`.

**Operator note:** the 2026-09-22 box was unblocked by hand with
`sudo chmod 0755 /opt/projects/claude_code/infra/hermes-agent/bin/docker-create-proxy.py`.
After pulling PR #40 the working tree and git agree; no conflict.

### F16: README step 3 omits `--governance-root`, so it targets the container path (recorded)

`migrate-governance.py` resolves its root from `HERMES_GOVERNANCE_ROOT`, defaulting to the
CONTAINER path `/opt/governance` (`governance_lib.governance_root`). README "VPS deploy
sequence" step 3 and the step near README:992 both invoke `--bootstrap-logs` with no
`--governance-root` and no env prefix, so on the host they do not address
`/var/lib/hermes/governance`. Corrected in the README by PR #40; recorded here because the
same omission pattern (host tool, container default) is worth checking in the other
host-side tools.

### F17: an unreadable path is reported as `mismatch` (recorded, not fixed)

**Measured on the VPS, 2026-09-23.** The post-F12 dry run (`python3 bin/init-host-layout.py`, as
BRING-UP then wrote it — no `sudo`) run as `hermesops` printed `mismatch … cannot lstat ([Errno
13] Permission denied …)` for all 11 rows below the two roots, and exited 2. Nothing was wrong:
the store is `root:hermes 2750` and `hermesops` is by design only in `sudo` and `users`
(BRING-UP Phase 1). With `sudo`, every row was `ok`. Two parts:

- **Docs (fixed in this PR).** BRING-UP's post-F12 block, the F12 spec §4 and the post-F12
  handoff now run the dry run with `sudo`. README step 2's first-install dry run is correct
  without it — the store does not exist yet.
- **Tool (open, low priority).** `host_layout.py`'s state probe maps any `OSError` from `lstat` other than `ENOENT`
  to `mismatch`. It fails closed, so it is safe, but it reads as "the layout is wrong" when it
  means "could not look". A distinct `unreadable` action (still non-zero) would say so. Does not
  gate anything.

### F18: the proxy's attach pass-through skips inspection for the rest of the connection — fixed (PR #50)

**Found in the whole-branch review of PR #48.** `docker-create-proxy.py`'s `_handle`: after
`decide()` allows a request, `if "/attach" in path:` — a substring test over the WHOLE target,
query string included — switches the connection to raw two-way pumping. Nothing after that
passes `_parse_head` or `decide()` again. Three routes reach it: (a) any allowed request with
`/attach` in its query, e.g. `GET /_ping?x=/attach`; (b) an allowed path whose container id is
literally `attach` (`_ID` accepts it), e.g. `DELETE /v1.55/containers/attach`; (c) a real
`POST /containers/<id>/attach` that dockerd answers with an error (e.g. 404) instead of
hijacking — dockerd keeps the connection, so the next bytes are parsed as a fresh request.

**Measured 2026-09-23** on a scratch copy with a keep-alive fake upstream (whole-branch review
of PR #48): after `GET /_ping?x=/attach`, and after an attach answered 404, a following
privileged `POST /containers/create` reached the upstream with no ALLOW/DENY logged. Not
measured against a real dockerd.

Pre-existing (predates PR #48); not caused by the framing hardening. Reachable by anything that
can connect to the proxy socket (hermes-rail, i.e. the broker) — the adversary the proxy exists
to contain. At the time: gates the kill switch. Not the rehearsal (the kill switch is absent,
nothing can mutate).

**Open: its own spec.** Pump only for `POST` whose `_path_only(path)` fullmatches the attach
allow-list pattern AND whose upstream response is `101 Switching Protocols` (Compose sends
`Upgrade: tcp`); otherwise relay normally and keep inspecting; forward any already-read client
bytes (`buf`) explicitly. Tests need a keep-alive fake upstream (TestPlumbing's closes after
each reply, so this was never exercised).

**Fix (PR #50, spec `2026-09-23-f18-attach-pass-through-design.md`).** Attach is defined once
(`_ATTACH_RE`, used by both the allow-list and `_is_attach`: POST, query string stripped,
fullmatch). `_handle` now reads dockerd's response head before deciding: only an attach answered
exactly `101` is passed through (forwarding the 101 head, any stream bytes read with it, and any
client bytes already read past the request); any other answer to an attach is relayed and the
connection closed; non-attach requests are unchanged. Tested with a keep-alive fake upstream (all
three routes let a smuggled create through before the fix and not after). **Measured on Linux CI**
(run 35999764190): the real Compose attach is logged `UPGRADE POST …/attach… (101)`.

**Merged and applied to the box, 2026-09-24.** Merge commit `5acee36`: CI run 36004506122,
`bind-agreement: executed 6, skipped 0`, `layout-integration: executed 30, skipped 0`. The box
pulled `e1110bb..5acee36` and restarted `hermes-docker-proxy` only (no unit changes); both units
`active`, `NRestarts=0`. BRING-UP Phase 6 on the box gave `rc=2` (`mutation is disabled`) and the
proxy logged `ALLOW POST /v1.55/containers/create?name=hermes-agent-ads-mutator-run-…` followed by
`UPGRADE POST /v1.55/containers/<id>/attach?stderr=1&stdin=1&stdout=1&stream=1 (101)`, with no
`DENY-FOLLOWUP` and no `malformed` refusal — the first real-dockerd measurement of the fixed attach
path on the box. Kill switch: absent (checked with `sudo test`).

### F19: container-scoped calls accept any container id — fixed (PR #53)

**Found 2026-09-23/24 (F18 design + F18 whole-branch review).** The allow-list's container-scoped
entries — inspect (`GET /containers/<id>/json`), start, wait, delete, and attach — all match any
container id (`_ID = [A-Za-z0-9_.-]+`), so the broker — the adversary the proxy exists to
contain — can direct any of them at **any** container, not just an ads-mutator run. This is the
whole id-scoped family, not just attach:

- **inspect returns another container's config, including its environment.** The Hermes gateway
  is started with `env_file: .env` (`docker-compose.yml`, gateway service), which holds the
  Anthropic/provider API keys — so a compromised broker could read them through the proxy.
- **attach can read another container's output** (and its log history with `logs=1`), **and write
  its stdin** with `stdin=1` if the target keeps stdin open. **Measured on the box, 2026-09-24:**
  the legitimate rail's own attach carries `stdin=1` (Compose sends
  `attach?stderr=1&stdin=1&stdout=1&stream=1` even under `run -T`), so an F19 fix cannot simply
  refuse `stdin=1` — it has to restrict *which container* an attach may target.
- **start/wait/delete act on any container** — e.g. stop the gateway by deleting it with `force`
  in the query string; the query string is never inspected on these entries.

Unlike F18 this is not a parsing or pass-through defect; it is a policy gap in `decide()`.
Recorded, not fixed. **Not measured.** Closing it needs the proxy to know which ids are
ads-mutator runs. **Whether it gates the kill switch is assessed in its own cycle; it is listed
as a gate until then.**

**Assessed 2026-09-24: a real gap; it gated the kill switch.** Two allowed calls reached the
gateway's environment: `GET /containers/json` for its id, then `GET /containers/<id>/json`.

**Fixed (PR #53, spec `2026-09-24-f19-container-scope-design.md`).** Container-scoped entries take
only a full 64-hex id — measured as the only form the rail sends (box journal, 2026-09-24:
`3 GET /json`, `2 POST /attach`, `1 POST /start`, `1 POST /wait`, all 64 hex). Before forwarding,
the proxy inspects the target on its own connection and allows only the pinned image **and** the
pinned entrypoint. An earlier RED attempt (run 36019974966) failed for the wrong reason — the
probe pinned `/v1.55` and CI's dockerd 28.0.4 caps at API 1.48 — and was discarded once the probe
was changed to unversioned paths. CI: RED on today's proxy (run 36020681939: the decoy's sentinel
was read), then `bind-agreement: executed 7, skipped 0` on the PR (run 36024366720) and the merge
commit (merge-commit run: pending). **Residual, accepted:** the list call still enumerates
containers (names, labels, image, mounts — no environment); every id it reveals is now refused.

## Final state of the box (end of session)

- Stack running: `hermes-agent` up. `claude-auth-init` exited 0. The dashboard is enabled,
  with basic auth.
- Public listeners: `:22` only (`ss -tlnH`). `127.0.0.1:9119` is loopback.
- `provision.sh --check`: 17/17 after the stack came up.
- Users and groups from README step 1 exist. **No units are installed.** The governance store is
  empty, `700 root:root`.
- `/opt/projects/claude-google-ads` is a placeholder.
- Kill switch: absent.

## Open items, in order

1. F6: a deploy-key clone of the ads repo, after the security review (the box's ads repo is still a placeholder).
2. F3: a `--check` for usable sudo, with a firing control.
3. F8: `data/skills` ownership; the `docker_config_migrate.py` warning.
4. F14: Compose failures reported as "nothing was mutated" — fixed (PR #46); no longer gates
   the kill switch. The rehearsal gate no longer needs F12 (fixed, PR #42) — its remaining
   prerequisite is `.env.gaw` carrying the WRITE Google Ads credential, plus Phase 6 passed.
5. F16: audit the other host-side tools for container-path defaults (F16's pattern).
6. F17: report an unreadable path as `unreadable`, not `mismatch`. Wording only; does not gate.
7. F18: the attach pass-through bypass — fixed (PR #50).
8. F19: container-scoped calls accept any container id — fixed (PR #53).
