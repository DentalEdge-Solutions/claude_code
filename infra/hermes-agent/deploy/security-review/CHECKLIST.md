# Hermes security review — checklist

version: 1.11

Spec: `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`. Every report
cites this version, so every change to this file must raise it (CI enforces this:
`bin/check-checklist-version.py`). Any change also changes the box fingerprint: its `code`
component hashes the git tree of `deploy/`, which contains this file, and flags uncommitted
edits. The `checklist` component records the version. Either way, the review is
re-triggered (§5). (v1.6: this paragraph only. The v1.5 header named the wrong fingerprint
component, and the version-bump rule is new. No item changed.) (v1.7: D2.1 `kind`s and
`memory_sweep`, D2.2 coverage, D6.1 `.env` rule, bundle `collected_at` — review #3's residuals.) (v1.8: ads audits on the box: the box's read credential, the real Anthropic key, D4.1 probe, D7.1 `audit_data`, vault `status` and `audit-logs`.) (v1.9: D7.1 also checks `reports` and `audit_logs` — hardening after review #4.) (v1.10: D7.1 `audit_logs.rows` mode is `0o711`, as the tool creates it; v1.9 wrongly required `0o700`.) (v1.11: Option B — D2.1 Anthropic key file + OpenRouter in the gateway env; D4.1 moved client data, no gateway Anthropic key; D4.2 last-PASS baseline carried in the bundle; D7.1 new paths, per-file audit-log modes; new D10 chat-triggered apps; memory_sweep nsfs handles classified.)

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
- **claim:** a system-wide sweep (not known paths — F24) finds only authorised credentials, each at its stated owner and mode. Under the read-only posture (D3.2, v1.5) the authorised set holds **no** write credential, so any `.env.gaw` other than `.env.gaw.example` is a FAIL. Since v1.8 the authorised Google credential on the box is exactly one **read** credential at `/etc/hermes/.env.ga`, `root:root 0400`, `kind: credential`, `role: read`, whose `refresh_token_sha12` equals the laptop's `.env.ga` (D3.1). Since v1.11 (Option B) the authorised set also holds the **Anthropic key** at `/etc/hermes/.env.anthropic` (used only by the `ads-drafter`, per run) and the **OpenRouter key** in the gateway `.env` (Hermes's own reasoning); the gateway `.env` holds no Anthropic key.
- **expected:** every row has a `kind`. The authorised set on the box is exactly: (1) ONE `credential` row: path `/etc/hermes/.env.ga`, `role: read`, `owner root`, `group root`, `mode 0o400`, and a `refresh_token_sha12` equal to the laptop's `.env.ga` row (D3.1); any other `credential` row is a FAIL; (2) the Anthropic key: path `/etc/hermes/.env.anthropic`, `kind: authorised-other`, `label: anthropic-key`, `owner root`, `group root`, `mode 0o400`, `anthropic_key_state: real` (`dummy` and `missing` mean the audit cannot draft and are a FAIL); (3) the gateway `.env`: `kind: authorised-other`, `label: gateway-env`, `owner root`, `group root`, `mode 0o600`, holding the OpenRouter key (the file's content is not read; D4.1's `openrouter_env_names` shows the key reached the gateway). `example` rows are templates. `empty` rows are 0 bytes. No row is `unlisted`, `unparsed` or `unreadable`. A leftover rollback backup such as `/opt/hermes-agent/.env.pre-optb2` is an `unlisted` row and a FAIL until it is shredded (BRING-UP part 2 step 5 creates it and `/root/config.yaml.pre-optb2`, which the sweep does not see; step 10 shreds both before evidence collection, and the operator attaches its `ls` output showing both gone). `not_swept`: `/boot`, `/boot/efi` (kernel and bootloader), `/dev` (device nodes) and `/run/lock` (lock files) are pre-explained; the writable in-memory mounts are covered by `memory_sweep`, whose `name_hits`, `content_hits` and `unreadable` are all empty; any other `not_swept` entry must be explained by the operator. `memory_sweep.namespace_handles` lists Docker `nsfs` namespace handles (under `/run`, bind-mounted network and mount namespaces): they are classified and never read, so a non-empty list is explained and never a FAIL. If `memory_sweep` is `could-not-check`, the operator attaches BRING-UP's manual "Sweep the in-memory mounts" output instead. The operator states in the report that the `/etc/hermes/.env.anthropic` key is real (workspace `hermes-box`, monthly spend limit stated); missing that statement is CANNOT-VERIFY. The OpenRouter key's limit is D10.5's statement.
- **pass rule:** an unexpected credential, a mode wider than `0600` for any future write credential, the authorised read row with any owner, group or mode other than `root`, `root`, `0o400`, the `anthropic-key` row with any owner, group or mode other than `root`, `root`, `0o400` or with an `anthropic_key_state` other than `real`, the `gateway-env` row with any owner, group or mode other than `root`, `root`, `0o600`, an `unlisted`/`unparsed`/`unreadable` row not explained (a rollback backup is never explained: it is shredded), any `memory_sweep` `name_hits`, `content_hits` or `unreadable` entry, or an unexplained `not_swept` entry, is a FAIL. A missing `anthropic-key` or `gateway-env` row is a FAIL.

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

### D4.1 — The gateway cannot read credentials, client data or the governance store
- **source:** box
- **claim:** from inside the gateway container, the governance store, every moved client-data path, the app-state tree and every credential file are absent (or an unreadable or empty mask); no Anthropic or Google Ads variable is in its environment; the control path is readable.
- **expected:** in `paths`, every one of these is `absent`: `/opt/governance`, `/var/lib/hermes/governance`, `/opt/hermes-agent/.env.gaw`, `/opt/hermes-agent/.env.ga`, `/etc/hermes/.env.ga`, `/etc/hermes/.env.anthropic`, `/var/lib/hermes/vaults`, `/var/lib/hermes/reports`, `/var/lib/hermes/draft-out`, `/var/lib/hermes/audit-data`, `/var/lib/hermes/app-state`, `/opt/data/vaults`, `/opt/data/reports` and `/opt/data/home/.claude/settings.json`. `/projects/claude_google_ads/.env` is `readable 0` (the empty mask) or `absent`. `/opt/registry/projects.yaml` is `readable <n>` (the control). `anthropic_env_names` is `[]` and `google_ads_env_names` is `[]` (the gateway holds no Anthropic key: it lives only in `/etc/hermes/.env.anthropic`, D2.1). `openrouter_env_names` is exactly `["OPENROUTER_API_KEY"]`. (The gateway's side of D10.1's declared credential map is measured here, not by the probe.)
- **pass rule:** a path that is readable (other than the control and the empty `.env` mask), any Anthropic or Google Ads variable name, an `openrouter_env_names` other than `["OPENROUTER_API_KEY"]`, or a failed control, is a FAIL; `could-not-check` is CANNOT-VERIFY.

### D4.2 — The Docker proxy is live
- **source:** box
- **claim:** `hermes-docker-proxy` is active with its reviewed ExecStart.
- **expected:** `active` is `active`; `execstart_sha256` equals `last_pass_execstart_sha256`, which the collector was given with `--last-pass-execstart` (the previous PASS report's value, carried in the bundle), so `matches_last_pass` is `true`. `matches_last_pass: null` means the flag was not given: the operator then states the baseline (the first review that carries it, #6; the previous PASS report's `execstart_sha256` is the baseline and the reviewer compares by hand).
- **pass rule:** inactive, or `matches_last_pass` `false`, is a FAIL. `null` without the operator's stated baseline is CANNOT-VERIFY.

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
- **claim:** vaults, reports, draft output, audit data, step logs and backups are the expected ones, none world-readable, none inside a package, none at the retired `data/` paths.
- **expected:** `parents` (`vaults`, `reports`, `draft-out` under `/var/lib/hermes/`): each a dict `owner root`, `group root`, `mode 0o711` (traversable by uid 10000, listable by root only). `vaults`, `reports_rows` and `draft_out_rows`: one row per client directory, every row `status: active`, `owner` 10000 (or its name), `mode 0o700`. `old_data` (`data/vaults` and `data/reports` under `/opt/hermes-agent`): both `absent`. `audit_data`: every row `status: active`, `owner` 10000 (or its name), `mode 0o700`. `root_backups` explained by the operator (e.g. `live-gate-*`). No `retired` or `unregistered` row in `vaults`, `reports_rows`, `draft_out_rows`, `audit_data` or `audit_logs.rows`: offboarding removes them. `audit_logs` (`/var/lib/hermes/audit-logs/<client>/` holds each run's step logs, never mounted): `audit_logs.root` carries `owner`, `group` and `mode` and is `root:root` `0o711`; `audit_logs.rows` has one row per child, each `status: active`, `owner` root, `mode` `0o711`, and a `files` object counting the entries in that directory by `"<owner> <group> <mode>"` (never names). Every `files` key ends in ` 0o600`. The step logs and `proxy.log` are `root root 0o600`; `snapshot.stdout` is handed to uid and gid 10000 for vault-write (`fchown`, mode unchanged) and so is `10000 <10000 or hermes> 0o600` (gid 10000 is the group `hermes` on the box). So `files` holds `root root 0o600` and at most one `10000 … 0o600` (a fresh run resets its client's directory first). A `parents` value, an `old_data` value or an `audit_logs.root` of `symlink` or `not-a-directory` is reported instead of the dict and never followed; `absent` is reported the same way.
- **pass rule:** a world-readable client path is a FAIL. A `parents` value other than `root`, `root`, `0o711` (`absent`, `symlink` and `not-a-directory` included) is a FAIL. A `vaults`, `reports_rows`, `draft_out_rows` or `audit_data` row whose `status` is `retired` or `unregistered`, whose `owner` is not 10000 (or its name), or whose `mode` is not `0o700`, is a FAIL. An `old_data` value other than `absent` is a FAIL. An `audit_logs.rows` row that is `retired` or `unregistered`, whose `owner` is not root, or whose `mode` is not `0o711` (root-owned; uid 10000 may traverse it to reach the one handed-over `snapshot.stdout` but cannot list it), is a FAIL; so is an `audit_logs.root` other than `root:root` `0o711`. The mode at the end of each `audit_logs.rows[*].files` key must be `0o600`: any file with another mode (`0o644` and any group- or world-readable mode included) is a FAIL. An owner other than root or 10000 in a `files` key is a FAIL too. An empty `files` object for a client whose directory exists is explained by the operator (no run since the directory was created) and is not a FAIL.

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

## D10 Chat-triggered apps

Spec: `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` (§6, §8.1). The chain is gateway MCP client → broker (`hermes-app-broker@ads-audit`, unprivileged) → runner (`hermes-app-runner@ads-audit`, root) → `run-client-audit`. **Declared credential map:** `ads-collector` and `ads-reader` hold `GOOGLE_ADS_*` only; `ads-drafter` holds `ANTHROPIC_API_KEY` only; `egress-proxy` holds none; the gateway holds `OPENROUTER_API_KEY` and no `ANTHROPIC_*` or `GOOGLE_ADS_*`; the broker and the runner hold none. D10.1 measures the four containers; D4.1 measures the gateway; D10.3 measures the broker's and runner's unit environments.

### D10.1 — The credential-placement probe matches the declared map
- **source:** box
- **claim:** `run-client-audit --probe-env` (root only, sentinel values and throwaway empty directories: no real credential or client data is read) starts each audit container as a real run would and reports which credential-shaped variable names it holds, which variables' values hold the sentinel whatever they are called, and whether any mounted file holds it.
- **expected:** `rc 0` and `probe.matches_declared: true`. In `probe.services` exactly four entries, each with `rc 0` and `sentinel_in_files: false`: `ads-collector` and `ads-reader` have `env_names` and `sentinel_env_names` both non-empty, every name starting `GOOGLE_ADS_`; `ads-drafter` has both exactly `["ANTHROPIC_API_KEY"]`; `egress-proxy` has both `[]`. The probe takes the audit lock: `rc 3` with no output (the item is `could-not-check`) means an audit was running; the operator waits for it to end and re-collects. The collector gives each probe 600 s; `--probe-env` can take about 8 minutes, so a slow run is not a hang.
- **pass rule:** `matches_declared` `false`, `rc` 1, any `sentinel_in_files: true`, a name outside a service's declared prefix, or a service missing or added, is a FAIL. `could-not-check` (exit 3, 124, no JSON object) is CANNOT-VERIFY.

### D10.2 — The drafter reaches only the egress proxy, and the proxy only Anthropic
- **source:** box
- **claim:** `run-client-audit --probe-egress` (same lock and rules as D10.1) runs from inside an `ads-drafter` container: a direct connection to the internet fails, the proxy refuses a non-Anthropic host and allows `api.anthropic.com`, only the three `/work` mount points exist, and the host's `/var/lib/hermes` is not visible.
- **expected:** `rc 0` and `probe.matches_expected: true`: `direct: "blocked"`, `non_allowed` ends ` 403` (the proxy's refusal line), `anthropic` ends ` 200`, `work_entries` is exactly `["out", "reports", "vault"]`, `host_visible: false`. The probe mounts throwaway empty directories, so it shows the drafter has exactly one vault mount point, not which client's vault a real run mounts. `could-not-check` as D10.1.
- **pass rule:** `matches_expected` `false`, `direct` other than `blocked`, a `non_allowed` that is not a refusal, an `anthropic` that is not `200`, any other `work_entries` or `host_visible: true`, is a FAIL.

### D10.3 — The broker is sandboxed, unprivileged and has no credential; the runner units are the repo's
- **source:** box
- **claim:** the broker unit carries spec §6's hardening, the three app units installed equal the repo's, the broker user has no sudo rights, is in no docker or sudo group, and neither the broker's nor the runner's unit environment holds anything.
- **expected:** `broker_unit`: `User: "hermes-app-ads-audit"`, `NoNewPrivileges: "yes"`, `CapabilityBoundingSet: ""` (empty), `PrivateNetwork: "yes"`, `PrivateTmp: "yes"`, `ProtectSystem: "strict"`, `ProtectHome: "yes"`, `ReadWritePaths` exactly `/var/lib/hermes/spool/apps/ads-audit /var/lib/hermes/app-state/ads-audit`, `UMask: "0077"`, `ActiveState: "active"`, and `Environment: []` and `EnvironmentFiles: []` (variable names only; no value reaches the bundle). `runner_unit`: `Environment: []` and `EnvironmentFiles: []`. `installed_equal_repo`: `true` for each of `hermes-app-broker@.service`, `hermes-app-runner@.service` and `hermes-app-runner@.path`; that equality is what proves the runner's reviewed values (`User=root`, `StartLimitIntervalSec=0`, `KillMode=control-group`, `TimeoutStartSec=12h`, the broker's `RestrictAddressFamilies=AF_UNIX` and `MemoryMax=128M`), which the collector does not print one by one. `broker_user_groups` is exactly `["hermes-app-ads-audit", "hermes"]` (no `docker`, no `sudo`). `sudo_rules` is `{"not_allowed": true, "command_lines": 0}` (`sudo -l -U` says the user may not run sudo; `rc` is recorded, not judged). `runner_path_active` is `active`.
- **pass rule:** any `broker_unit` value other than above, a non-empty `Environment` or `EnvironmentFiles` on either unit, any `installed_equal_repo` `false`, any other `broker_user_groups`, `not_allowed` `false` or `command_lines` above `0`, or `runner_path_active` other than `active`, is a FAIL. A `could-not-check` value is CANNOT-VERIFY.

### D10.4 — The spool and app-state layout is as designed, and no container mounts the app state
- **source:** box
- **claim:** the layout table's rules (`host_layout.check_app`, the rules `init-host-layout.py --app ads-audit --check` applies) hold for `/var/lib/hermes/spool/apps/ads-audit/` and `/var/lib/hermes/app-state/ads-audit/` (`jobs/`, `done/`, `running/`, `state/`: owners, groups and modes), and no running container has a bind or volume whose host side is the app-state tree, a path inside it, or a directory above it.
- **expected:** `layout_problems: []`, `containers_mounting_app_state: 0`, `containers_not_inspected: 0` (`containers` is the number of running containers, for scale).
- **pass rule:** a non-empty `layout_problems` or a non-zero `containers_mounting_app_state` is a FAIL. A non-zero `containers_not_inspected` (a container whose mounts could not be read) is CANNOT-VERIFY for those containers: the operator re-collects once, or inspects them by hand.

### D10.5 — The OpenRouter key is limited and privacy routing is stated
- **source:** manual
- **claim:** the OpenRouter key Hermes uses for its own reasoning is dedicated and limited, and the control plane's data is not collected or retained by the model host.
- **expected:** the report states (spec §6, §13): the key's credit limit (the dedicated key, $10, monthly reset) and that the OpenRouter ACCOUNT's privacy settings deny data-collecting providers and set Zero Data Retention. Hermes has no `zdr` key: what `config.yaml` enforces is `provider_routing.data_collection: "deny"`, which Hermes sends as `provider.data_collection`; true zero data retention is an account setting (optionally with `provider_routing.only` pinned to ZDR-listed providers). The operator states which of config and account enforces what, and attaches the console's limit and privacy-settings screens (no key value).
- **pass rule:** no stated limit, or no statement of how privacy routing is enforced, is CANNOT-VERIFY. A statement that ZDR is enforced by a `zdr` config key is a FAIL (no such key exists).

### D10.6 — Hermes may call exactly three tools
- **source:** box
- **claim:** the gateway's `mcp_servers:` block registers one server whose `tools.include` is exactly the three audit tools, with an empty `env`; the tool list the gateway itself reports is recorded as information, not as a boundary.
- **expected:** `mcp_block` holds the committed block: `mcp_servers:`, one server `ads_audit` (`command: "python3"`, `args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]`, `env: {}`), and `include: [ads_audit_run, ads_audit_status, ads_audit_list]`, with `resources: false` and `prompts: false`. No `env:` or `headers:` entry beyond `{}`; a value there shows as `<withheld>` and is a FAIL. `gateway_mcp_list` is recorded as information (the `hermes mcp list` text; `gateway_mcp_list_rc` is its exit code, `null` when no gateway container ran; an empty list with a non-zero code is noted, not judged).
- **pass rule:** an `include` other than exactly those three tools, any other server, a non-empty `env` or `headers`, or a missing `mcp_block`, is a FAIL.

### D10.7 — The broker's journal shows the live checks and holds no credential or customer id
- **source:** box
- **claim:** the live refusals were exercised on the box and the broker and runner journals (30 days) hold no credential text, no registered customer id and no installed secret value.
- **expected:** `journal_counts` (broker lines by `status/reason`, never a line) holds at least one each of `refused/disabled` (the kill switch), `refused/quota` (a second same-day run) and `refused/bad_request` (a malformed request) from the live checks. Other keys are expected and are not a FAIL: `queued/-`, `ok/-`, `dropped/duplicate`, `dropped/bad_request`, `dropped/expired`, `busy/busy`, `failed/<step class>`; `note_counts` (`warning`, `error`: the broker's fixed-text lines) and `other_lines` (systemd's own lines) are recorded; the operator explains a non-zero `error` count. An unknown status or reason shows as `?`. After 1000 refusals in one UTC day the broker (`REFUSAL_CAP_PER_DAY`) writes no result and no ledger line for a further refusal: the caller sees `pending`, and the journal shows a `warning` in `note_counts` (the cap line; one other fixed-text warning shares that key) and no `refused/*` count for those requests. That cap is intended, not a FAIL; the operator explains a day with that many refusals. `broker_journal` and `runner_journal` (`runner_journal` is where `run-client-audit`'s own output lands) each carry `credential_text_lines`, `customer_id_lines`, `pattern_hits` and `known_secret_hits`, all `0`. `known_secrets_checked` is greater than `0`: with none loaded, `known_secret_hits` is `0` by construction and proves nothing.
- **pass rule:** a missing `refused/disabled`, `refused/quota` or `refused/bad_request` count (the live check did not happen, or fell outside the 30 days) or any leak count above `0` in either journal is a FAIL. `known_secrets_checked` of `0` is CANNOT-VERIFY (the leak counts prove nothing). The OpenRouter key is not among the known secrets (D2.3 has the same limit): the operator states it was never typed into a chat or a log.

### D10.8 — The results hold only whitelisted fields, and one real audit returned `ok`
- **source:** box
- **claim:** every file in `results/` is exactly a result the broker could have written (keys and values checked independently of the broker), and a real audit has returned `ok`; the journal's lack of credential text or customer id is D10.7's leak counts.
- **expected:** `out_of_whitelist: 0`; every row has `keys_ok: true` and `values_ok: true`. At least one `results` row has `op: "run"` and `status: "ok"` (reason `-`). Rows may legitimately carry `status: "busy"` with `reason: "busy"`, `failed` with a step class (`collect`, `snapshot`, `read`, `proxy`, `draft`, `isolation`, `vault-write`) or `internal`, `refused` with `precheck` or a broker reason, and `op: "list"` rows. Values outside the closed sets show as `?` and are out of whitelist. A result's origin is not in the evidence: the operator states that the `ok` run was triggered from chat (BRING-UP part 2 step 10).
- **pass rule:** any `out_of_whitelist` above `0`, or no `run`/`ok` row, is a FAIL. A single unexplained row that shows only `keys_ok: false, values_ok: false` (no `op`, `status` or `reason`) can be the broker's in-flight temporary file or a file that expired mid-listing: the operator re-collects once before judging it, and a row that persists is a FAIL.
