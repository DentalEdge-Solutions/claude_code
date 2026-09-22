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
| 5 Bind paths | **mismatch, open** (F9) — measured, not widened |
| 6 Units | **parked** — README step 1 done and verified; the store/spool layout (F10) is fixed in PR #<N>; step 2+ still waits on F9 |
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

### F9: the bind paths do not match the proxy allow-list, and no layout matches both

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
**Open:** a design fix in the repo. The candidates are pinning the allow-list to the canonical
paths, or giving compose absolute paths. The fix must keep `proxy-policy-sync.test.py` meaningful.

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

**Fixed** in PR #<N> (design: `docs/superpowers/specs/2026-09-21-f10-governance-store-and-spool-layout-design.md`).
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

### F12: approvals and run records are written by host-side tools that cannot reach `data/vaults` (recorded, not fixed)

Found while designing F10. `approve-changeset.py` reads the change-set from `data/vaults/`
(uid 10000, `700`) and writes `approvals/<slug>/` plus a `0600` lock file that the broker later
reopens. Run as root, it leaves root-owned `0600` locks, and `reserve_approval` fails on the
first apply. Run as `hermes-broker`, it cannot read `data/vaults`. Approval and snapshot files
are written with plain `open()`, so they are group-readable only because of the umask; the
2026-09-17 handoff's §6 `UMask=0077` would make every approval unreadable to the executor.

Second case: `run-ads-mutate.sh` runs as `hermes-broker` inside the broker's sandbox, and after
every apply it calls `persist-run-record.py`, which writes into `data/vaults/<slug>/`. `data/` is
`700` uid 10000, and `data/vaults` is not in `ReadWritePaths`, so the write fails. The failure
shows as the "RUN RECORD NOT PERSISTED" banner, with the executor's exit status kept.

**Gates creating the kill switch, not Phase 6.** Installing the units approves nothing.
F10's `approvals/` ownership (`hermes-broker:hermes 2750`) is compatible with any F12 fix.

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

1. F9: the allow-list and compose path design. This unblocks Phase 6.
2. F3: a `--check` for usable sudo, with a firing control.
3. F8: `data/skills` ownership; the `docker_config_migrate.py` warning.
4. F6: a deploy-key clone of the ads repo, after the security review.
5. F12: host-side approval and run-record writes vs data/vaults. Gates the kill switch.
