# Hermes chat triggers client audits (Option B) — design (2026-09-30)

**Status:** approved in conversation, section by section, 2026-09-30; this document awaits operator review.
**Scope:** the stated end goal of the ads-audits work (handoff 2026-09-30, "Next work" item 1), built so it
becomes the reusable pattern for every future app on the Hermes AI OS. Ends with security review #6.
**Builds on:** `2026-09-29-ads-audits-on-the-box-design.md` (the entry command and its steps), the mutation
syscall's spool pattern (`2026-08-19-hermes-mutation-syscall-design.md`), credential canon
(`canon/2026-08-17-credential-governance-lessons.md`) and D3.2 (read-only, no write credential).

## 1. Goal and intent

The operator asks Hermes in chat to audit a client. Hermes files the request, the box runs the existing
audit command, and Hermes reports the outcome. The operator reads the draft on the host.

- **Chat surface, now:** `hermes chat` inside the gateway container, over SSH. It adds no inbound listener.
- **Chat surface, later:** the dashboard over Tailscale (spec 2026-09-19). Nothing in this design depends on
  the front end.
- **Out of scope:** messaging platforms (Telegram, Slack…), scheduled audits, pushing drafts off the box,
  any mutation (D3.2), and egress limits for the collector and reader (a follow-up, §5.4).

### Principles

1. **The broker is the boundary, not Hermes's config.** Upstream research (§12) shows the terminal toolset
   cannot be reliably removed and toolset deny-lists fail silently in several documented ways. Nothing here
   relies on Hermes config to limit what Hermes can do. Config narrowing is ergonomics, and the review
   records it as information only.
2. **Code visible, data sealed.** An app's code may be mounted read-only into the gateway. An app's client
   data never is.
3. **Hermes never sees client content.** Results carry enums, numbers, timestamps and paths only. Report
   text, metrics, search terms and ids never enter Hermes's context, and so never reach OpenRouter.
4. **Root never reads what Hermes wrote.** Hostile input is parsed by a sandboxed, unprivileged broker.
   The root runner reads only files the broker wrote.
5. **One app, one declared entry.** Everything specific to audits lives in a single manifest, so app #2 is a
   new manifest plus new unit instances, not a redesign. No general multi-app engine is built now.

### Success criteria

1. A chat-triggered audit on a spending client is judged deliverable by the operator.
2. Security review #6 (checklist v1.11): PASS.
3. No customer id, credential value or report text in chat, results or the journal.
4. The cost per chat-triggered audit (Anthropic draft plus OpenRouter chat turns) is recorded.

## 2. Architecture

```
 operator ──SSH──▶ hermes chat (gateway container, uid 10000; reasoning = DeepSeek via OpenRouter)
                     │ MCP stdio server hermes-app-mcp: ads_audit_run | ads_audit_status | ads_audit_list
                     ▼
   /var/lib/hermes/spool/apps/ads-audit/{requests,results}/        (under the existing spool mount)
                     ▼
   hermes-app-broker@ads-audit.service   user hermes-app-ads-audit · NoNewPrivileges · no capabilities
     reads registry/apps/ads-audit.json · validates · quota (host-only state) · kill switch
     writes a job file ──▶ /var/lib/hermes/app-state/ads-audit/jobs/
                     ▼  systemd .path activation
   hermes-app-runner@ads-audit.service   root, oneshot
     re-validates the job · runs /usr/local/sbin/run-client-audit <slug> --json | --list --json
     writes output ──▶ app-state/ads-audit/done/   ──▶ broker maps it to a result
                     ▼
   run-client-audit: pre-checks → collect → snapshot → read → DRAFT (ads-drafter, egress: Anthropic only)
                     → isolation check → vault-write → /var/lib/hermes/vaults/<client>/
```

### Components

| Component | What it is | Trust |
|---|---|---|
| `registry/apps/ads-audit.json` | the app manifest: ops, fixed argv per op, quotas, run-as user, result fields, runner timeout | repo, reviewed |
| `bin/hermes-app-mcp.py` | stdlib MCP stdio server in the gateway, three tools, slug-format check only, no policy | untrusted (Hermes's domain) |
| `bin/hermes-app-broker.py` + `deploy/hermes-app-broker@.service` | per-app drain: validation, quota, kill switch, job write, result write | unprivileged, sandboxed |
| `bin/hermes-app-runner.py` + `deploy/hermes-app-runner@.{path,service}` | root oneshot: re-validate job, exec fixed argv, write output | root, minimal |
| `bin/run-client-audit.py` (modified) | `--json`, `--list`, `--probe-env`; draft step moves to `ads-drafter`; new data paths | root, reviewed in #5, re-reviewed in #6 |
| `bin/egress-proxy.py` | stdlib CONNECT proxy; allow-list `api.anthropic.com:443` | per run |
| `bin/show-audit.py` → `/usr/local/sbin/show-audit` | host command: print a client's latest or named draft | operator only |
| `skills/ads-audits/` | Hermes skill: how to call the tools and report outcomes; mounted read-only | repo, reviewed |
| compose services `ads-drafter`, `egress-proxy` | one-shot containers, `tools` profile | §5 |

The instance name of each unit (`ads-audit`) comes from the operator's `systemctl enable`, never from the
spool.

**Unchanged:** the mutation broker and the parked mutation rail; the laptop's `run-trend-audit.sh`; the
`claude_code` repo mount, the ads app package mount and the skills mounts in the gateway.

## 3. Request flow

### 3.1 The Hermes interface

`hermes-app-mcp` is a stdlib implementation of the MCP stdio protocol (initialize, `tools/list`,
`tools/call`). It adds no SDK, so the pinned image is unchanged. It's configured in the gateway's
`config.yaml`:

```yaml
mcp_servers:
  ads_audit:
    command: "python3"
    args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]
    env: {}
    timeout: 360
    tools:
      include: [ads_audit_run, ads_audit_status, ads_audit_list]
      resources: false
      prompts: false
```

| Tool | Does | Returns |
|---|---|---|
| `ads_audit_run(client)` | writes a `run` request, then polls for its result for up to 5 min | the result, or `{status: pending, request_id}` |
| `ads_audit_status(request_id)` | reads the result file; files nothing | the result, or `pending` |
| `ads_audit_list(client)` | writes a `list` request and waits up to 60 s | audit timestamps only |

It validates only the slug format (`governance_lib.SLUG_RE`, the one shared definition) and the request-id format (`governance_lib.REQUEST_ID_RE`). A refusal is
returned as final and never rendered as a retryable error (the syscall rule, mutation spec §12).

### 3.2 Request and result files

A request is `{request_id (uuid4), app, op, client}`, written atomically (mkstemp then rename, mode `0640`,
as `spool_lib`) to `spool/apps/ads-audit/requests/<request_id>.json`. The MCP server validates its own
output with the broker's validator before writing.

A result is written by the broker to `results/<request_id>.json`, and every field is from a closed set:

```json
{"request_id": "…", "op": "run", "client": "<slug>", "status": "ok|refused|failed|busy",
 "reason": "<enum|null>", "exit_code": 0, "ts": "YYYY-MM-DD_HH-MM-SS|null",
 "steps": [{"name": "collect|snapshot|read|proxy|draft|isolation|vault-write", "rc": 0, "seconds": 0}],
 "vault_path": "/var/lib/hermes/vaults/<slug>/audits/<ts>-audit.md|null",
 "audits": ["<ts>", "…"]}
```

`audits` is present only for `list`. `reason` enums: `bad_request`, `duplicate`, `inactive_client`,
`quota`, `disabled`, `precheck`, `busy`, `timeout`, `interrupted`, `internal`, and for `failed` the step name.

### 3.3 Broker drain

The broker has the same drain model as `hermes-broker`: single-threaded and serial. Per request:

1. **Hostile-input checks:** the filename pattern, `lstat` regular file, a size cap (1 KiB), at most 64 files
   per pass, and requests older than 1 hour deleted unread. JSON parse, then a closed schema: exact keys,
   `app` equals the unit instance, `op` in the manifest.
2. **Replay:** a `request_id` already in the seen-set (`app-state/ads-audit/seen/`) gives `refused: duplicate`.
3. **Kill switch:** if `app-state/ads-audit/DISABLED` exists, the result is `refused: disabled`.
4. **Client:** registered and `status: active` in the governance registry. Otherwise `refused: inactive_client`.
   The broker user gets read-only access to the registry file through a group. The plan measures the exact
   grant against the store's current modes. `run-client-audit` re-checks as root regardless.
5. **Quota, reserved before the job:** per UTC day, `run` is capped at 1 per client and 5 per box; `list` at
   60 per box. A reservation counts whatever the run's outcome, so a failing loop can't retry through the
   budget. A `busy` outcome releases its reservation.
6. **Job:** `{job_id = request_id, op, client}` written atomically to `app-state/ads-audit/jobs/`.
7. **Result:** when `done/<job_id>.json` appears, the broker validates it against the whitelist in §3.2 and
   writes the result. Anything unparseable or outside the whitelist gives `failed: internal`, and no text
   passes through. The request, job and done files are then removed.

The seen-set and quota ledger are append-only JSONL under `app-state/`, which no container mounts.

### 3.4 Runner

`hermes-app-runner@ads-audit.path` watches `jobs/` (`DirectoryNotEmpty=`). The service is a root oneshot
that processes jobs oldest first:

- It first turns anything left in `running/` into an `interrupted` done file: `running/` only ever holds a job whose
  run was cut off (a crash or reboot), and it is never re-run.
- It `lstat`s and size-caps the job, parses a three-key schema (`job_id`, `op`, `client`) with the same
  `SLUG_RE`, and renames it into `running/` before executing.
- It maps `op` to the manifest's fixed argv: `run` gives `/usr/local/sbin/run-client-audit <slug> --json`,
  and `list` gives `… <slug> --list --json`. No shell; the slug is one argv element.
- It runs with the manifest timeout (30 min for `run`, 60 s for `list`), killing the process group on expiry
  and writing `{…, "status": "failed", "reason": "timeout"}`.
- It writes stdout (at most 64 KiB) and the rc to `done/<job_id>.json` atomically, as `root:hermes-app-ads-audit 0640`,
  then removes the job. `done/` is owned by the broker user (`0700`), so the broker can read and unlink
  what root wrote.

Layout of `app-state/ads-audit/`: the directory itself is `root:hermes-app-ads-audit 0750`, so only root can
create or remove `DISABLED` in it; `state/`, `jobs/` and `done/` are the broker user's (`0700`); `running/`
is `root:hermes-app-ads-audit 0750`, so the broker can see a job in flight and never mistakes it for an
interrupted one. The runner is serial, so a `list` filed during an audit waits behind it (the MCP tool
returns `pending`).

The runner is the only root code this design adds. It reads only files written by the broker user, into a
directory only that user can write (`jobs/`: `0700` `hermes-app-ads-audit`). Root can read it regardless of
mode.

### 3.5 Exit mapping (`run-client-audit --json`)

| rc | Result |
|---|---|
| 0 | `ok` |
| 1 | `failed`, `reason` = the failed step |
| 2 | `refused: precheck` |
| 3 (lock held, e.g. a manual run) | `busy`; the quota reservation is released |
| timeout | `failed: timeout` |

## 4. Isolation: client data leaves the gateway

| Data | Today | After | Owner / mode |
|---|---|---|---|
| Vaults (drafts, metrics, timeline) | `data/vaults/<client>/` | `/var/lib/hermes/vaults/<client>/` | uid 10000, `0700` |
| Scrubbed reports | `data/reports/<project>/` (shared by all clients) | `/var/lib/hermes/reports/<client>/` | uid 10000, `0700` |
| Transient draft | under `data/` | `/var/lib/hermes/draft-out/<client>/`, emptied each run | uid 10000, `0700` |
| Raw audit data | `/var/lib/hermes/audit-data/<client>/` | unchanged | unchanged |

- `vault_lib` gains a single `VAULT_ROOT`. On the box it's `/var/lib/hermes/vaults`; on the laptop it defaults
  to `data/vaults` (darwin has no uid separation to protect).
- `ads-reader` mounts `reports/<client>` read-write at `/opt/data/reports/claude_google_ads` (where
  `run-ads-report.py` writes), instead of the shared `data/reports`.
- `vault-write` (host, uid 10000) writes the new vault root.
- The parent `/var/lib/hermes/{vaults,reports,draft-out}` directories are root `0711`, and each
  `<client>/` below is pre-created with the right owner (the lesson behind PR #78).
- **The gateway keeps:** the `claude_code` repo, the ads app package (code and scrubbed docs, 21 files,
  id-guarded) and the skills, all read-only.
- **The gateway loses:** every client data tree.
- **Accepted side effect:** the parked mutation rail's `propose` step wrote under `vaults/<slug>/changes/`
  from inside the gateway and no longer can. Un-parking it needs its own design regardless (D3.2).

**Migration** (`bin/migrate-client-data.py`, a BRING-UP step):
1. Stop the gateway.
2. Copy the vaults with owners, modes and mtimes preserved. Reports are not migrated: they are per run and
   rebuilt by the next audit, so `data/reports` is only removed.
3. Verify per-file size and sha256 against the source.
4. Only then remove `data/vaults` and `data/reports`.

Any mismatch stops with the source intact. Rollback moves the trees back.

## 5. The drafter and egress

### 5.1 `ads-drafter`

A one-shot container per run and per client (image `hermes-agent-claude`, `tools` profile):

- **Mounts, read-only:** `vaults/<client>`, `reports/<client>`, the ads app package (with the `.env` mask),
  and `skills/claude-code-ads-analyst`.
- **Mount, read-write:** only `draft-out/<client>`.
- **Hardening:** `user: 10000:10000`, `read_only: true`, tmpfs `HOME` and `/tmp`, `cap_drop: [ALL]`,
  `no-new-privileges`, memory and PID limits.
- **No `env_file`.** `ANTHROPIC_API_KEY` arrives per run as `-e NAME`, read by `run-client-audit` from
  `/etc/hermes/.env.anthropic`. No Google credential, ever. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
- The same `claude -p` prompt, `Read,Grep,Glob` plan mode, Opus model and in-container timeout as today,
  with paths rewritten to the new mounts.

### 5.2 `egress-proxy`

- The drafter is on its own network `hermes-drafter-net` with `internal: true`, which has no route out. The
  proxy is on that network and the default bridge.
- `bin/egress-proxy.py` is a stdlib HTTP CONNECT proxy:
  - it allows exactly `api.anthropic.com:443`;
  - it refuses IP literals, other ports, other hosts and any non-CONNECT method;
  - it doesn't terminate TLS;
  - it logs host, decision and byte counts only.
- The drafter uses `HTTPS_PROXY=http://egress-proxy:3128`.
- A hostname allow-list at a proxy is used rather than IP firewall rules because Anthropic's addresses
  change.
- `run-client-audit` starts the proxy for the draft step and stops it in its `finally`. **No proxy means no
  draft.**

### 5.3 The drafter's output

The isolation check (the draft names no other registered client) and `vault-write` run on the host exactly
as today, reading the draft from `draft-out/<client>/`.

### 5.4 Follow-up, out of scope

The same proxy pattern for the collector and reader, with a Google-APIs allow-list.

## 6. Secrets and privileges

| Secret | Where | Owner / mode | Used by |
|---|---|---|---|
| Google Ads READ credential | `/etc/hermes/.env.ga` (unchanged) | `root:root 0400` | the collector and reader containers only, per run `-e` |
| Anthropic key (workspace `hermes-box`, $20 a month) | **moved** to `/etc/hermes/.env.anthropic` | `root:root 0400` | the `ads-drafter` only, per run `-e` |
| OpenRouter key (**new**, dedicated) | gateway `.env` | `root:root 0600` | Hermes's own reasoning |

- **The gateway holds no Anthropic key.** Today `claude-auth-init` writes it to
  `/opt/data/home/.claude/settings.json`, readable by anything Hermes runs; Hermes's scrubbing covers the
  environment, not files. The sidecar is retired, the key leaves the gateway `.env`, and any existing
  `settings.json` is removed. Hermes answers read-only project questions with its own file tools.
- **OpenRouter key:**
  - a per-key credit limit of **$10, monthly reset**;
  - the account is set to deny providers that collect data, with Zero Data Retention (ZDR) where available.
    OpenRouter supports `provider.data_collection: "deny"` and `provider.zdr: true`.
  - **Unverified:** Hermes's docs show no config key for OpenRouter provider preferences. Plan step 1 checks
    the pinned image. If none exists, the account-level setting is what's in force, and the review records
    which one is.
  - If ZDR routing leaves no DeepSeek V3.2 endpoint, pick from the existing alternatives
    (`config.yaml.example`).
- **No sudo.** The broker user has no sudoers entry and isn't in the docker group. Its only root path is the
  job file (§3.4).
- **Broker unit hardening:**
  - `User=hermes-app-ads-audit`, `NoNewPrivileges=yes`, `CapabilityBoundingSet=` (empty);
  - `ProtectSystem=strict`, `ReadWritePaths=` limited to its spool subtree and `app-state/ads-audit`;
  - `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateNetwork=yes`, `UMask=0077`.

### 6.1 What each outside company sees

| Company | Sees | Never sees |
|---|---|---|
| Anthropic | as today: scrubbed reports, the vault history, docs (drafting) | the Google credential |
| OpenRouter / the model host | the operator's chat, **client short names** (accepted), result labels, timestamps, vault paths | report text, metrics, search terms, customer ids, any credential |
| Google | as today: API calls with the READ credential | anything else |

## 7. Failure handling

- **Every outcome is one of four classes** (§3.2), and every `reason` is from a closed set.
- **Nothing reruns on its own.** On start, the broker writes `failed: interrupted` for any reservation with
  no result, and removes its job if the runner hasn't taken it.
- **Timeouts:** the runner kills the process group; `run-client-audit`'s `finally` still removes the drafter
  (`--rm`), stops the proxy and clears the transient draft.
- **Spend caps:**
  - Anthropic refusing gives `failed: draft`.
  - OpenRouter exhausted means Hermes stops answering. The box is unaffected, and the manual
    `sudo run-client-audit` path always works.
- **Broker down:** requests wait and Hermes reports `pending`. `Restart=on-failure` with a burst limit.
- **Kill switch:**
  - `app-state/ads-audit/DISABLED` (root-created) gives `refused: disabled`, instantly and with no restart;
  - `systemctl stop hermes-app-broker@ads-audit` stops the app.
- **Skill behaviour:**
  - `refused`: state the reason and stop;
  - `busy` or `pending`: say so, and check status once when asked;
  - `failed`: name the step and give the manual command;
  - never re-request unprompted.
- **Journal:** one line per request (request id, op, client slug, class, reason). Never customer ids,
  credentials or report text. F21 governs pasting it anywhere.

## 8. Review tooling

- **Keyed `cid:` fingerprints.** `review_lib` replaces `sha12` for customer ids with HMAC-SHA256.
  - The key lives only on the laptop (`~/.config/hermes-review/fp.key`, `0600`). The box collector reads it
    from the tty for one run (`--fp-key-tty`, a hidden one-line paste), never from disk or argv.
  - Refresh-token and client-id fingerprints stay `sha12`: those values are high-entropy, and existing
    records (canon, decisions) compare against them.
- **Credential-placement probe:** `run-client-audit --probe-env`, root only.
  - It isn't reachable through the runner, whose manifest ops are `run` and `list`.
  - It starts each step's container with its real mounts and env wiring, **sentinel values** instead of
    secrets, and a no-op entrypoint that reports which variable names exist and whether any sentinel appears
    in any environment or mounted file.
  - Declared map: Google READ in the collector and reader only; Anthropic in the drafter only; OpenRouter in
    the gateway only; nothing in the proxy, broker or runner environments. The long-running gateway and
    broker are checked by name directly.
  - This corrects the handoff's "only the collect step": the reader holds the credential by design (spec
    2026-09-29 §2 step 4).
- **Review-#5 follow-ups, included:**
  - report file modes inside `audit-logs/<client>/` without names;
  - classify Docker `nsfs` handles in `memory_sweep`;
  - each evidence file carries the last PASS's proxy `execstart_sha256`.

### 8.1 Checklist v1.11

| Check | Proves |
|---|---|
| D2.1 (edit) | the authorised set is Google READ, Anthropic (`/etc/hermes/.env.anthropic`) and OpenRouter (gateway `.env`), each at its stated owner and mode |
| D4.1 (edit) | from inside the gateway: no vaults, reports, draft output, audit data, `app-state` or `/etc/hermes` secret; no Anthropic key in its environment or `settings.json` |
| D7.1 (edit) | client data at the new paths (`0700`, uid 10000); `data/vaults` and `data/reports` absent; no retired client has data |
| D10.1 | the credential-placement probe matches the declared map |
| D10.2 | drafter egress: direct connections fail, the proxy refuses a non-Anthropic host and allows `api.anthropic.com`; exactly one client's vault mounted |
| D10.3 | broker unit hardening as §6; runner units equal the repo; no sudoers entry for the broker user; the broker user isn't in the docker group |
| D10.4 | spool `apps/ads-audit/` and `app-state/ads-audit/` (`jobs/`, `done/`, `seen/`) owners and modes; `app-state` mounted into no container |
| D10.5 | the OpenRouter key limit is stated; privacy routing is in force, recorded as config or account |
| D10.6 | Hermes MCP config `tools.include` is exactly the three tools; the measured tool list is recorded as information, not a boundary |
| D10.7 | live: the kill switch gives `refused: disabled`; a second same-day run gives `refused: quota`; a malformed request gives `refused: bad_request` |
| D10.8 | one chat-triggered real audit returned `ok`; its result holds only whitelisted fields; the journal holds no credential text or customer id |

The review process is unchanged from #4 and #5. It binds to a new box fingerprint and access digest.

## 9. Testing

Test-first. Stdlib `bin/*.test.py`, run by `run-bin-tests.sh`.

- **`hermes-app-mcp`:**
  - the MCP handshake; `tools/list` returns exactly three tools;
  - `run` writes a request the broker's validator accepts; bad slugs are rejected;
  - `pending`, `refused` and `failed` are rendered as final.
- **Broker:**
  - schema, size, flood and age caps; `duplicate`; app mismatch;
  - quota reserved before the job; `busy` releases it;
  - `interrupted` on restart; the kill switch; the done-file whitelist; `internal` on bad output.
- **Runner:**
  - job re-validation; fixed argv per op; no shell;
  - the timeout kills the process group; `done/` is written atomically; output is capped.
- **`run-client-audit`:**
  - `--json` and `--list`; the drafter step argv and mounts; the new data paths;
  - the proxy is started and always stopped; `--probe-env`;
  - the existing redaction and step tests are still green.
- **`egress-proxy`:** the allow-list, IP-literal and port refusal, non-CONNECT refusal, the log format.
- **Others:**
  - `review_lib` HMAC fingerprints;
  - the manifest loader (unknown keys refused);
  - `migrate-client-data.py` (verify-then-remove; a mismatch refuses with the source intact);
  - `units.test.py` for the new units.
- **Linux CI**, extending the real-Docker mount job, with no Google or Anthropic calls:
  - the gateway sees no client data;
  - drafter egress (direct fails, `example.com` refused, CONNECT to `api.anthropic.com` succeeds at the
    TCP/TLS level);
  - the sentinel probe matches the declared map;
  - broker, runner and a stub `run-client-audit` end to end.

## 10. Build order and rollout

**Three PRs, each green before the next. The box gets nothing until all three are merged.**

1. **Isolation and egress:** data paths and migration script, `ads-drafter`, `egress-proxy`, Anthropic key
   moved to `/etc/hermes`, `run-client-audit --json/--list`, `show-audit`. Works with manual
   `sudo run-client-audit`.
2. **The chat trigger:** the manifest, `hermes-app-mcp`, broker, runner, units, the `ads-audits` skill and
   the OpenRouter wiring. `claude-auth-init` is retired.
3. **Review tooling:** HMAC fingerprints, `--probe-env`, the review-#5 follow-ups, checklist v1.11.

**Box rollout** (BRING-UP steps; every prompt goes in its own one-line paste, reading from `/dev/tty`;
governed files are replaced only by validating scripts):

1. Pull; install `run-client-audit`, `show-audit` and the units; create the broker user and `app-state`.
2. **Secrets:**
   - move the Anthropic key to `/etc/hermes/.env.anthropic` and strip it from the gateway `.env`;
   - install the OpenRouter key;
   - in the OpenRouter console: the $10 monthly key limit and privacy/ZDR routing.
3. Migrate the vaults and reports (§4).
4. Manual audit: `sudo run-client-audit <client> --dry-run`, then a real run. This proves the drafter path.
5. **Chat:** one chat-triggered audit; the live D10.7 checks.
6. **Review:** bundles, a fresh reviewer, review #6, operator sign-off, a brain decision.

## 11. Decisions resolved in design

| Decision | Choice | Why |
|---|---|---|
| Chat surface | `hermes chat` over SSH now; dashboard over Tailscale later | no new inbound surface for review #6 |
| Isolation | by construction: client data out of the gateway, a per-client drafter | policy isolation is a guardrail on a path, not a boundary (canon rule 2) |
| Gate on a chat run | quotas only (1 per client, 5 per box, per UTC day), reserved before execution | the $20 cap bounds the worst case; a confirmation step would defeat the point |
| What Hermes sees | metadata only | keeps client data at one vendor and keeps injectable text away from the model that can file requests |
| Trigger channel | per-app broker plus root runner (hand-off tray) | the sandbox stays intact; sudo would need `NoNewPrivileges` off; the pattern is reusable per app |
| Hermes interface | stdlib MCP server with `tools.include` | typed actions for a cheap model; no SDK in the pinned image |
| Gateway Anthropic key | none; `claude-auth-init` retired | the file-based key was readable by anything Hermes runs |
| OpenRouter | dedicated key, $10 a month, privacy/ZDR routing | same cap pattern as Anthropic |
| Client names to OpenRouter | accepted, real short names | code names would cost usability for little gain under ZDR |
| Ads package in the gateway | kept, read-only | code and scrubbed docs, not client data |
| Credential probe scope | Google in collector **and reader** | the reader holds it by existing design |

## 12. Upstream research (2026-09-30)

- The Hermes terminal toolset is part of the irreducible minimum, even in Blank Slate mode.
- Only `agent.disabled_toolsets` with exact toolset names works. `HERMES_DISABLED_TOOLSETS`, root-level
  `disabled_toolsets:` and unknown names fail silently (issue #97111, open).
- The deny-list isn't applied to desktop-app sessions (#88857) or the multiplexed API server (#91415).
  This bears on the dashboard phase: it confirms Principle 1.
- MCP stdio servers support a `tools.include` allow-list and receive only a minimal environment plus the
  declared `env`.
- Hermes self-evolution runs offline and proposes skill changes as PRs for human review. That's compatible
  with the read-only skill mount and the skill-eval pipeline.
- OpenRouter: per-key `limit` with `limit_reset: monthly`; provider routing `data_collection: "deny"` and
  `zdr: true`. The Hermes configuration docs show no OpenRouter provider-preference key.

**Sources:**
- Hermes docs: user-guide/features/tools, features/mcp, user-guide/security, reference/cli-commands,
  user-guide/configuration
- NousResearch/hermes-agent issues #97111, #88857, #91415
- NousResearch/hermes-agent-self-evolution README
- OpenRouter docs: provider selection, provider logging, API key creation

## 13. Measurements (part 2, Task 1 — 2026-10-01)

Measured against the pinned image `nousresearch/hermes-agent@sha256:f7b3…` as built into local `hermes-agent-claude` (Hermes code at `/opt/hermes`).

| Question | Result | Consequence |
|---|---|---|
| Hermes provider-routing key | `provider_routing.data_collection` (string, e.g. `deny`) is read from `config.yaml` (`gateway/run.py:5405-5413` loader; `gateway/run.py:14793` and `:20321` pass `provider_data_collection=pr.get("data_collection")`; `cli.py:4001-4007`) and emitted as `provider.data_collection` in the OpenRouter request (`agent/chat_completion_helpers.py:186-187`, built by `_provider_preferences_for_agent`, injected as `extra_body["provider"]` at `:2050-2054`). Sibling keys read: `only`, `ignore`, `order`, `sort`, `require_parameters`. No `zdr` key exists anywhere in Hermes. Cron path also reads it (`cron/scheduler.py:3146`). | `config.yaml.example` sets `provider_routing.data_collection: deny`. There is no per-request ZDR switch in Hermes, so true zero-data-retention must come from the account-level OpenRouter setting plus (optionally) `provider_routing.only` pinned to ZDR providers; D10.5 records the account setting. |
| ZDR endpoint for the control-plane model (`deepseek/deepseek-v3.2`) | The per-model `/models/<id>/endpoints` listing has NO retention/ZDR/data-policy field (endpoint keys: context_length, latency_last_30m, max_completion_tokens, max_prompt_tokens, model_id, model_name, name, native_tools, pricing, provider_name, quantization, status, supported_parameters, supports_*, tag, throughput_last_30m, uptime_*). It lists 13 providers: GMICloud, SiliconFlow, DeepInfra, AtlasCloud, Venice, Baidu, DigitalOcean, Alibaba, Friendli, Google, Phala, Mara, SambaNova. The separate public `GET /api/v1/endpoints/zdr` list (923 endpoints) contains deepseek-v3.2 for 8 providers: DeepInfra, DigitalOcean, Google, Mara, Phala, SambaNova, SiliconFlow, Venice. Not ZDR-listed: GMICloud, AtlasCloud, Baidu, Alibaba, Friendli. | Model kept: ZDR-capable endpoints exist. Pin with `provider_routing.only` to a subset of the 8 above if strict ZDR is wanted (the ZDR list is the source; the models listing does not show it). Alternates, by the same list: `qwen/qwen3-235b-a22b-2507` has ZDR endpoints (Nebius, Venice, Google, Novita, DeepInfra, Parasail); `z-ai/glm-4.6` has (Venice, Novita, Z.AI, DeepInfra); `nousresearch/hermes-4-70b` has none (and `/models/.../endpoints` returned no endpoint list for it). |
| MCP `tools.include` | yes: `/opt/hermes/tools/mcp_tool.py:5045` (`include_set = _normalize_name_filter(tools_filter.get("include"), "mcp_servers.<name>.tools.include")`), enforced by `_should_register` at `:5050-5054` (include is a whitelist, takes precedence over `exclude`; non-listed tools are never registered). Code read only; no behavioural run. | `tools.include` is used in `config.yaml.example` as defence in depth alongside the server exposing only its three tools. |
