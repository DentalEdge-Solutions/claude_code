# Hermes security review — checklist

version: 1.8

Spec: `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`. Every report
cites this version, so every change to this file must raise it (CI enforces this:
`bin/check-checklist-version.py`). Any change also changes the box fingerprint: its `code`
component hashes the git tree of `deploy/`, which contains this file, and flags uncommitted
edits. The `checklist` component records the version. Either way, the review is
re-triggered (§5). (v1.6: this paragraph only. The v1.5 header named the wrong fingerprint
component, and the version-bump rule is new. No item changed.) (v1.7: D2.1 `kind`s and
`memory_sweep`, D2.2 coverage, D6.1 `.env` rule, bundle `collected_at` — review #3's residuals.) (v1.8: ads audits on the box: the box's read credential, the real Anthropic key, D4.1 probe, D7.1 `audit_data`.)

**How to read an item.** `source` says where the evidence comes from: `box` (the box
bundle, item id as key), `laptop` (the laptop bundle), or `manual` (the operator states it
in the report). `expected` is what a healthy box shows. The reviewer marks each item
`PASS`, `FAIL` or `CANNOT-VERIFY`, quoting the evidence. An item whose evidence is
`could-not-check` is `CANNOT-VERIFY` — never `PASS`. Each bundle carries `collected_at` (UTC):
the box bundle must postdate the last change to the box the report relies on, and the laptop
bundle must be from the same day as the sign-off.

## D1 Host exposure

### D1.1 — Only SSH listens publicly
- **source:** box
- **claim:** the only non-loopback listener, TCP or UDP, is SSH.
- **expected:** `listeners` contains `tcp 0.0.0.0:22` and/or `tcp [::]:22`; every other entry starts with `127.` or `[::1]` (e.g. the dashboard's `tcp 127.0.0.1:9119`); no non-loopback UDP listener unless the operator explains it.
- **pass rule:** no other non-loopback address, TCP or UDP.

### D1.2 — The firewall agrees
- **source:** box
- **claim:** `ufw` is active, default-deny inbound, and allows only 22/tcp.
- **expected:** `Status: active`, `Default: deny (incoming)`, a single `22/tcp ALLOW IN` rule (v4 and v6).
- **pass rule:** no other ALLOW IN rule.

### D1.3 — SSH is key-only, no root login
- **source:** box
- **claim:** `sshd -T` refuses passwords and root.
- **expected:** `permitrootlogin no`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`.
- **pass rule:** all four exactly.

### D1.4 — Brute-force and patch hygiene are on
- **source:** box
- **claim:** fail2ban and unattended-upgrades run.
- **expected:** both `active`.
- **pass rule:** both `active`.

### D1.5 — Only expected accounts can log in or sudo
- **source:** box
- **claim:** login shells and sudo membership are exactly the operator's.
- **expected:** login shells: `root` and `hermesops` only; sudo group: `hermesops` only; `sudoers_d` holds only files the operator recognises.
- **pass rule:** any unexplained account is a FAIL.

### D1.6 — No human or deploy account is in the docker group
- **source:** box
- **claim:** `docker` group membership is root-equivalent, so no login account may hold it.
- **expected:** `docker_group_members` is exactly `["hermes-docker-proxy"]` — the proxy service account, which must reach the Docker socket to broker every container create (by design, BRING-UP Phase 6). Neither `hermesops` nor any other login account appears. (v1.4: the 2026-09-29 review failed v1.3's "empty" expectation on this designed member.)
- **pass rule:** any member other than `hermes-docker-proxy` is a FAIL.

## D2 Credential inventory

### D2.1 — The credential sweep finds exactly the authorised set
- **source:** box
- **claim:** a system-wide sweep (not known paths — F24) finds only authorised credentials, each `hermes-broker:hermes-broker 0600` (write, if one is ever held) or, for the read credential, `root:root 0400` as the README table says. Under the read-only posture (D3.2, v1.5) the authorised set holds **no** write credential, so any `.env.gaw` other than `.env.gaw.example` is a FAIL. Since v1.8 the authorised set on the box is exactly one **read** credential at `/etc/hermes/.env.ga`, `root:root 0400`, `kind: credential`, `role: read`, whose `refresh_token_sha12` equals the laptop's `.env.ga` (D3.1).
- **expected:** every row has a `kind`. The authorised set on the box is exactly ONE `credential` row: path `/etc/hermes/.env.ga`, `role: read`, `owner root`, `group root`, `mode 0o400`, and a `refresh_token_sha12` equal to the laptop's `.env.ga` row (D3.1). Any other `credential` row is a FAIL; under the read-only posture no write credential exists. `example` rows are templates. `empty` rows are 0 bytes. `authorised-other` rows carry a `label` naming the README's non-Google secret (`gateway-env`: the gateway `.env`, `root:root 0600`). No row is `unlisted`, `unparsed` or `unreadable`. `not_swept`: `/boot`, `/boot/efi` (kernel and bootloader), `/dev` (device nodes) and `/run/lock` (lock files) are pre-explained; the writable in-memory mounts are covered by `memory_sweep`, whose `name_hits`, `content_hits` and `unreadable` are all empty; any other entry must be explained by the operator. If `memory_sweep` is `could-not-check`, the operator attaches BRING-UP's manual "Sweep the in-memory mounts" output instead. The operator states in the report that the gateway `.env`'s `ANTHROPIC_API_KEY` is real (workspace `hermes-box`, monthly spend limit stated); missing that statement is CANNOT-VERIFY.
- **pass rule:** an unexpected credential, a mode wider than `0600` for any future write credential, the authorised read row with any owner, group or mode other than `root`, `root`, `0o400`, an `unlisted`/`unparsed`/`unreadable` row not explained, any `memory_sweep` hit, or an unexplained `not_swept` entry, is a FAIL.

### D2.2 — No credential text in shell histories
- **source:** box
- **claim:** no value-shaped credential or known secret sits in any history file — shell, REPL and database clients (`.bash_history`, `.zsh_history`, `.python_history`, `.psql_history`, …) — in `/root`, every `/home/*` and every home `/etc/passwd` names, service accounts included.
- **expected:** every `pattern_hits` and `known_secret_hits` is `0`.
- **pass rule:** any non-zero is a FAIL until explained and cleaned.

### D2.3 — No credential text in the journal
- **source:** box
- **claim:** as D2.2, for `journalctl`.
- **expected:** both counts `0`.
- **pass rule:** any non-zero is a FAIL.

## D3 Credential access, as Google sees it

### D3.1 — Every credential measures as declared
- **source:** laptop
- **claim:** `audit-credential-access.sh --all --customer` measures each role as declared, with the audit's own exit code.
- **expected:** `rc 0`; `.env.ga` `READ_ONLY`; `.env.gaw` `MUTATE_CAPABLE` — or, under the read-only posture (D3.2, v1.5), **no `.env.gaw` row at all**; every `mismatch false`; the fingerprints equal the authorised set. The box credential's `refresh_token_sha12` (box bundle `credentials`) equals the laptop `.env.ga` row's. The retired write token's sha12 (`b5aa4baf3310`) appears nowhere in either bundle.
- **pass rule:** any mismatch or non-zero `rc` is a FAIL. A `.env.gaw` row under the read-only posture is a FAIL, and so is the retired sha12 appearing anywhere.

### D3.2 — The ADMIN decision is made and recorded
- **source:** manual
- **claim:** the operator has decided whether the ADMIN operator account stays the write credential, is replaced by a dedicated STANDARD-access account (spec decision 7), or no write credential is held (the read-only posture; v1.5).
- **expected:** the report states the decision and the reason; the `projects.yaml` comment matches it. Under the read-only posture the report also records what happened to the retired write token: revoked and proved dead (D8.2), or not revoked with every copy destroyed, as an accepted risk with its reason.
- **pass rule:** no recorded decision is CANNOT-VERIFY.

## D4 Isolation boundaries

### D4.1 — The gateway cannot read credentials or the governance store
- **source:** box
- **claim:** from inside the gateway container, the governance store is absent and credential files are absent, unreadable or empty masks; the control path is readable.
- **expected:** `/opt/governance` and `/var/lib/hermes/governance` `absent`; `/projects/claude_google_ads/.env` `readable 0` (the empty mask) or `absent`; both `/opt/hermes-agent/.env.ga*` `absent`; `/etc/hermes/.env.ga` `absent`; `/opt/registry/projects.yaml` `readable <n>` (the control); `google_ads_env_names` empty.
- **pass rule:** a readable credential, or a failed control, is a FAIL; `could-not-check` is CANNOT-VERIFY.

### D4.2 — The Docker proxy is live
- **source:** box
- **claim:** `hermes-docker-proxy` is active with its reviewed ExecStart.
- **expected:** `active`; `execstart_sha256` equal to the previous PASS report's (first review: recorded).
- **pass rule:** inactive is a FAIL.

### D4.3 — Installed units equal the repo
- **source:** box
- **claim:** each installed unit file is byte-identical to `deploy/`.
- **expected:** `installed == repo` for both units.
- **pass rule:** any difference is a FAIL.

### D4.4 — The broker's layout check passes
- **source:** box
- **claim:** `init-host-layout.py --check` as `hermes-broker` passes.
- **expected:** `rc 0`.
- **pass rule:** non-zero is a FAIL.

## D5 Governance store

### D5.1 — The pre-flight passes
- **source:** box
- **claim:** `preflight-governance-access.py` as `hermes-broker` passes.
- **expected:** `rc 0`.
- **pass rule:** non-zero is a FAIL.

### D5.2 — Every registered log is sealed
- **source:** box
- **claim:** every `log/*.jsonl` carries the append-only flag (§6B).
- **expected:** `sealed == logs`.
- **pass rule:** any unsealed log is a FAIL.

### D5.3 — The kill switch is absent
- **source:** box
- **claim:** mutation is disabled during the review.
- **expected:** `kill_switch_present false`. Under the read-only posture this holds permanently, not only during the review.
- **pass rule:** present is a FAIL.

### D5.4 — The registry is as expected
- **source:** box
- **claim:** client counts match the operator's own list.
- **expected:** the operator confirms the counts by status; `dormant_pilots` is `0` or `1` — and exactly `1` before any live gate (`vault_lib.resolve_dormant_pilot` refuses more than one).
- **pass rule:** unexplained clients, or `dormant_pilots` greater than `1`, are a FAIL.

## D6 App packages

### D6.1 — The installed package is the pinned package
- **source:** box
- **claim:** each app directory holds exactly the pinned package.
- **expected:** `installed_sha256 == pin.sha256`; `commit == pin.commit`; `mismatched` and `extra` empty; `placeholder false`; `git_dir false`; `env_file.size` `0`. (The app's `.env` is masked from the executor and exempt from `extra` only while it is empty; a non-empty one appears in `extra`.)
- **pass rule:** any deviation is a FAIL.

### D6.2 — No git or GitHub credential on the box
- **source:** box
- **claim:** no private SSH key, `.git-credentials` or `gh` token in any home.
- **expected:** `git_or_ssh_private_credentials` empty (SSH *authorized_keys* are not listed and are fine).
- **pass rule:** anything listed is a FAIL until explained.

### D6.3 — The pin is a package built from the verified commit
- **source:** laptop
- **claim:** rebuilding from the operator-verified commit gives the pinned hash.
- **expected:** laptop `D6.3.sha256` == box `D6.1.pin.sha256`, same `commit`.
- **pass rule:** any difference is a FAIL.

## D7 Client data on the box

### D7.1 — Client data is where it should be, readable only by its owners
- **source:** box
- **claim:** vaults, run records and backups are the expected ones, none world-readable, none inside a package.
- **expected:** vault directories `0700` owned by uid 10000; `root_backups` explained by the operator (e.g. `live-gate-*`). `audit_data`: every row `status: active`, `owner` the container uid (10000 or its name), `mode 0o700`. No `retired` or `unregistered` row: offboarding removes them.
- **pass rule:** a world-readable client path is a FAIL.

## D8 Stop and recover

### D8.1 — Mutation can be disabled in one step
- **source:** manual
- **claim:** the operator can remove the kill switch and stop both units in one documented block.
- **expected:** the report cites the BRING-UP block.
- **pass rule:** no documented block is CANNOT-VERIFY.

### D8.2 — Revocation is written and proves death
- **source:** manual
- **claim:** the revocation procedure exists and ends by using the token and observing the refusal (canon, credential governance).
- **expected:** the report cites the procedure.
- **pass rule:** a procedure that trusts HTTP 200 is a FAIL.

## D9 Open findings

### D9.1 — Every open finding is decided
- **source:** manual
- **claim:** each open item is `accepted (reason)` or `blocking`.
- **expected:** a line each for F3, F8, F16, F17, F20, the `audit_data` data layer, repo visibility, `main` branch protection, and the SDK logger printing raw account ids — plus any finding opened since.
- **pass rule:** an undecided item is CANNOT-VERIFY.
