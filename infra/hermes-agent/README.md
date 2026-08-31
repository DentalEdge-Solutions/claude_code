# Hermes Agent — control plane over Claude Code projects

Local Docker deployment of **Nous Research's Hermes Agent** as an always-on
control plane that operates Claude Code projects by driving `claude -p` in
mounted project directories. You talk to Hermes; Hermes reaches into a project
and runs Claude Code there.

## Architecture (two model roles)

| Role | Runs on | Billed via | Notes |
|------|---------|-----------|-------|
| **Control plane** (Hermes's own reasoning / tool-orchestration) | cheap OSS model via **OpenRouter** (`deepseek/deepseek-v3.2`) | OpenRouter credits | swap freely — it's one config line |
| **Executor** (`claude -p`, the real work) | **Claude**, direct Anthropic API | `ANTHROPIC_API_KEY` | model pinned per task via `--model` (haiku/sonnet/opus) |

Why the split: OpenRouter's endpoint is OpenAI-compatible only, and Claude Code
is a Claude-native agent (it carries each project's skills/agents/`CLAUDE.md`).
So OpenRouter centralizes everything that is a plain model call (the control
plane), while `claude -p` stays direct on Anthropic for reliable agentic
execution. See the project plan for the full rationale.

## Files

- `Dockerfile` — derived image: official `nousresearch/hermes-agent` base + the `claude` CLI.
- `docker-compose.yml` — loopback-only, read-only project mount, `env_file: .env`.
- `.env.example` — copy to `.env` (gitignored) and fill in keys.
- `config.yaml.example` — version-controlled template for the live `./data/config.yaml` (gitignored).
- `bootstrap-claude-auth.sh` — init-sidecar script; projects the executor key from `.env` into claude's config.
- `registry/projects.yaml` — project registry (which projects Hermes may operate, workdir, scope, model).
- `skills/claude-code-operator/` — the operator skill (registry-aware, read-only, model-tiered).
- `bin/monitor-runs.py` — read-only monitor over cron job/run history.
- `SECURITY-AUDIT.md` — P0 audit of the base image / posture.
- `data/` — Hermes state (HERMES_HOME ↔ `/opt/data`), **gitignored**.

## First run

```bash
cp .env.example .env          # then edit: set OPENROUTER_API_KEY + ANTHROPIC_API_KEY
cp config.yaml.example data/config.yaml
docker compose up -d --build
docker compose exec hermes-agent hermes gateway status   # -> running
docker compose exec hermes-agent claude --version        # -> Claude reachable
```

## Control-plane model config

The live config is `./data/config.yaml` (gitignored). Apply the template, or set
it non-interactively (`hermes model` needs a TTY, so prefer `config set`):

```bash
docker compose exec hermes-agent hermes config set model.provider openrouter
docker compose exec hermes-agent hermes config set model.default deepseek/deepseek-v3.2
docker compose up -d --force-recreate   # reload env + config
```

To try a different control-plane model, change `model.default` to any OpenRouter
slug (e.g. `nousresearch/hermes-4-70b`, `z-ai/glm-4.6`) and recreate.

## Smoke test (control plane orchestrates the executor)

```bash
docker compose exec hermes-agent hermes --accept-hooks -z \
  "In /projects/claude_code, use your terminal tool to run: \
   claude -p 'In one sentence, how do you run the tests here?' --model claude-haiku-4-5 \
   --allowedTools 'Read,Grep,Glob' --permission-mode plan (workdir /projects/claude_code). \
   Return only Claude's answer."
```

A grounded, repo-correct answer confirms the full chain (OpenRouter control
plane → `claude -p` → Anthropic).

## How the executor gets its key (important, non-obvious)

Hermes **scrubs secrets from the environment** of the shell commands it runs
(verified: `printenv ANTHROPIC_API_KEY` inside the terminal tool returns empty).
So a **Hermes-launched `claude -p` never sees `$ANTHROPIC_API_KEY`** — it reads
its key from Claude Code's own config, `$HOME/.claude/settings.json`, and Hermes
runs those subprocesses with `HOME=/opt/data/home`.

`bootstrap-claude-auth.sh` materializes that file from the container env at
startup (wired as the `claude-auth-init` sidecar in `docker-compose.yml`, which
`hermes-agent` waits on). Net effect:

- **`.env` stays the single human-facing source of truth** for keys.
- `data/home/.claude/settings.json` is a **generated** artifact (gitignored,
  0600) — never hand-edited, never committed, never stale after a rotation.
- Rotating a key = edit `.env`, then `docker compose up -d --force-recreate`.

## P2 — operating projects (registry, scheduling, monitoring)

The management layer that lets you drive projects by talking to Hermes.

**Registry** (`registry/projects.yaml`, mounted read-only at `/opt/registry`) —
the source of truth for which projects Hermes may operate: `workdir`, `scope`
(`read` | `write`), `default_model`, description. Add a project by adding an
entry (and, until P5, keep `scope: read`).

**Operator skill** (`skills/claude-code-operator`, mounted into `SKILLS_DIR`) —
resolves a project NAME → workdir from the registry, enforces the read-only
guardrail (`--permission-mode plan --allowedTools 'Read,Grep,Glob'`), picks the
cheap model tier, and delegates the `claude -p` mechanics to the bundled
`claude-code` skill. Just ask naturally:

```bash
docker compose exec hermes-agent hermes --accept-hooks -z \
  "In the claude_code project, what are the five metrics skill-eval computes?"
```

Write requests are refused (scope gated to P5); unregistered projects are
rejected with the available list.

**Scheduling** (native `hermes cron`) — register unattended workflows:

```bash
docker compose exec hermes-agent hermes cron create '0 9 * * *' \
  --name cc-testing-digest --deliver local \
  --workdir /projects/claude_code --skill claude-code-operator \
  "In the claude_code project (read-only), summarize how tests are run."
# trigger once:  hermes cron run <name> && hermes cron tick
# pause/resume:  hermes cron pause|resume <name>
```

**Monitoring** — durable run history + reports:

```bash
docker compose exec hermes-agent python3 /opt/cc-bin/monitor-runs.py        # digest
docker compose exec hermes-agent python3 /opt/cc-bin/monitor-runs.py --json # machine-readable
```

Run reports are written to `data/cron/output/<job_id>/<timestamp>.md`.

## Improvement proposals (Track A)

The `claude-code-proposer` skill (`skills/claude-code-proposer`) reviews a
registered project **read-only** and writes a structured improvement proposal
— never a code change in the project itself. Ask Hermes directly:

```bash
docker compose exec hermes-agent hermes --accept-hooks -z \
  "Use the claude-code-proposer skill. Review the claude_google_ads project \
   and propose improvements. Then tell me the summary and the saved path."
```

Proposals are saved via `bin/save-proposal.py` to
`/opt/data/proposals/<project>/<timestamp>.md` (each with a `## Summary`, a
prioritized `## Items` list — `[P1]`/`[P2]`/`[P3]` — and `## Sources
consulted`), and are listable/filterable with `bin/proposals-index.py`:

```bash
docker compose exec hermes-agent python3 /opt/cc-bin/proposals-index.py --project claude_google_ads
docker compose exec hermes-agent python3 /opt/cc-bin/proposals-index.py --json
```

End-to-end verified: the project's git working tree stays clean
(`git status --porcelain` unchanged) before and after a proposal run —
the mount's read-only guardrail holds even for this analysis-and-write-elsewhere flow.

## Web dashboard (P3 — the browser UI)

An s6-supervised web dashboard is the **unified browser surface**: a **Chat** tab
that embeds the full Hermes TUI (via xterm.js — real conversations in the
browser), plus Config, API Keys, Sessions, Logs, Analytics, Cron, Skills, MCP,
Channels, System — and the bundled **Kanban** board.

Enable it in `.env` (see `.env.example`): `HERMES_DASHBOARD=1` plus
`HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD`. It is **off by default**,
and per the June-2026 hardening its `0.0.0.0` bind (required by the container
port-map) **requires basic auth** (`--insecure` no longer bypasses it). Then:

```bash
docker compose up -d          # s6 auto-starts + supervises the dashboard
open http://127.0.0.1:9119    # log in with the basic-auth credentials
```

Published to **loopback only** (`127.0.0.1:9119`), reachable only from this
machine, and it **auto-restarts with the container**. Read your password with
`grep HERMES_DASHBOARD_BASIC_AUTH_PASSWORD .env`.

## Kanban review pipeline (first multi-agent orchestration — C2)

The first AIOS multi-agent use-case: a fixed-template, **read-only** review pipeline
where three provably-confined specialists analyze a project in parallel
(architecture / tests / risks) and a synthesizer fuses their handoffs into one
prioritized improvement proposal — the single-agent proposer (Track A), elevated to
a team on Hermes's durable Kanban runtime.

```bash
cd infra/hermes-agent
# 1) one-time: create the four confined worker profiles (idempotent)
docker compose exec -T hermes-agent sh /opt/cc-bin/setup-review-team.sh
# 2) build the fixed 4-task board for a registered project
docker compose exec -T hermes-agent python3 /opt/cc-bin/make-review-board.py --project claude_code
# 3) run the confined workers (native dispatcher; or `hermes kanban dispatch --max 2` per pass)
docker compose exec -d hermes-agent hermes kanban daemon --interval 15 --max 2
# watch on the dashboard Kanban board, or: hermes kanban list
# 4) when `synthesize` is done, persist the proposal + list it
docker compose exec -T hermes-agent python3 /opt/cc-bin/persist-review-proposal.py --project claude_code
docker compose exec -T hermes-agent python3 /opt/cc-bin/proposals-index.py --project claude_code
```

**Board shape:** `analyze-architecture→architect`, `analyze-tests→test-analyst`,
`analyze-risks→risk-analyst` (parallel), then `synthesize→synthesizer` created with
`--parent` on all three, so the native Kanban fan-in auto-promotes it to `ready`
only when every analysis is `done` — no LLM orchestrator, no polling.

**Worker confinement (hardened group-level "Branch B" — a custom hand-picked toolset
is not achievable without forking Hermes):**
- **OS `:ro` project mounts = the hard guarantee** — workers physically cannot write
  any project (kernel-enforced; verified byte-identical git tree before/after a run).
- Each profile's `config.yaml` pins an **allow-list** `platform_toolsets.cli: [file,
  skills]` + a **deny-list** `agent.disabled_toolsets` stripping every dangerous
  group (`terminal`, `code_execution`, `browser`, `web`, `delegation`, `computer_use`,
  …). Workers analyze **directly** (no `claude -p`, which needs the terminal tool).
- **Documented residuals:** `write_file`/`patch` ride the `file` group but are
  `:ro`-contained to `/opt/data`+scratch; kanban fan-out tools are present but their
  use is asserted-against (a post-run check requires zero worker-authored cards).

Each worker runs under its own profile `HERMES_HOME`, so the reviewer skill is
symlinked into each profile's `skills/` dir by `setup-review-team.sh` (workers
resolve `--skill` from the profile dir, not the global mount). Design + plan:
`docs/superpowers/{specs,plans}/2026-07-24-hermes-kanban-review-pipeline*`.

## Improvement proposals as draft PRs (Increment 2 — first write capability)

Deliver a persisted proposal (from the Track-A proposer or the Kanban review pipeline)
to GitHub as a **draft PR** that adds one machine-authored brain-candidate file — the
project's `:ro` mount is never touched (the write happens in a fresh ephemeral clone).

**One-time human setup:** a dedicated machine account (`dentaledge-bot`) added as an
org collaborator with **write** (not admin); a **fine-grained** bot PAT (Contents +
Pull-requests write, single repo, 90-day expiry) — note fine-grained PATs only grant
write to **org-owned** repos for collaborators, so `claude_code` lives under the
`DentalEdge-Solutions` org; the PAT goes in gitignored `infra/hermes-agent/.env.pr`
(**not** `.env`); a `main` **ruleset** requiring a PR with bypass = repo admin only
(bot **not** on the bypass list).

**Usage** (operator-invoked; the wrapper parses `.env.pr` **as data, never sourcing
it** and passes the PAT via `docker compose exec -e` — it never enters the gateway
`env_file`):

```bash
./infra/hermes-agent/open-proposal-pr.sh --project claude_code --proposal latest
# prints the draft PR URL; add --dry-run to preview without any git/network.
```

**90-day PAT rotation:** mint a new bot PAT → replace the value in `.env.pr`. No
container recreate needed (the PAT isn't in the gateway env).

**Safety model:** bot ≠ owner; `:ro` mount never written (ephemeral clone only);
draft-only (a human marks ready + merges); `main` unwritable by the bot (pre-push
hook + server-side ruleset); and the PAT is kept **out of the gateway `env_file`** —
necessary because **Hermes does NOT scrub the `CLAUDE_CODE_PR_PAT` name** (it only
scrubs known-provider names).

**What that does not mean.** An earlier version of this section said the PAT is out of
the gateway env "so no agent-launched process can read it." That claim is **false**,
for the same `/proc/<pid>/environ` reason documented for the Ads write credential
below. Keeping the PAT out of `env_file` removes the **resting** exposure — it is not
in the environment of every process, all the time. It does not remove the **timing
window**: `open-proposal-pr.sh` still `exec -e`s into the *gateway* container, and
during that run any same-UID process there (everything runs as `hermes`, uid 10000)
can read the value out of `/proc`. The Ads write credential's fix was to move its
consumer into a one-shot container Hermes has no shell in; the same move has **not**
been applied to this path yet. The PAT carries org-repo Contents + Pull-requests
write, so treat the window as real and rotate on suspicion.

**Tests:** `python3 infra/hermes-agent/bin/open-proposal-pr.test.py` (the hermes
`bin/` tests aren't auto-discovered by `run-all-tests.js`; run them directly).

## Read-execute — Google Ads reporting (Increment 3)

A second, narrower write-adjacent capability alongside the draft-PR path
(Increment 2): a new `scope: read-execute` registry tier lets Hermes run
**allow-listed reporting scripts** against the live Google Ads API — not via
`claude -p` (which gets no Bash for this at all), but via a host wrapper that
shells straight into a pinned Python venv. `claude` is only ever allowed to
*read* the persisted report afterward.

**Prerequisite — a READ-ONLY Google Ads credential (spec §9).** The entire
safety model rests on the refresh token belonging to a Google account whose
access to the MCC/client is READ-ONLY at the platform level, so any mutate
call — however it got triggered — is refused **server-side** by Google, not
just by this code. This is the backstop underneath everything else. Mint it
by adding a **Viewer**-only user (not Standard/Admin) to the Google Ads MCC
and generating a refresh token for that user; the developer token is the same
MCC-scoped token already used by the project's own `.env`. Task 2's gate
proved this holds: a `validate_only` mutate was refused with
`authorization_error: ACTION_NOT_PERMITTED` (positive control: a plain read
succeeded first, ruling out a token/scope misconfiguration as the cause).

**`.env.ga` setup** — copy the template and fill in the six credential values:

```bash
cd infra/hermes-agent
cp .env.ga.example .env.ga   # gitignored — never commit this file
$EDITOR .env.ga              # GOOGLE_ADS_DEVELOPER_TOKEN / CLIENT_ID / CLIENT_SECRET /
                              # REFRESH_TOKEN / LOGIN_CUSTOMER_ID / CUSTOMER_ID (no dashes)
```

`.env.ga` is **not** `docker-compose.yml`'s `env_file` and is never loaded into
the gateway/agent environment. `run-ads-report.sh` reads it on the host and
injects the six values **per-invocation** via `docker compose exec -e` — the same
pattern as the Increment-2 PAT in `.env.pr`.

**Delivery is not visibility.** This section used to say the values "reach only the one
exec'd reader process." That is true of *delivery* and **false of visibility**:
`/proc/<pid>/environ` is readable by any same-UID process, and everything in the
gateway container runs as `hermes` (uid 10000), so during a report run an
agent-launched process can read the injected credential out of `/proc`. Per-invocation
injection removes the *resting* exposure, not the *timing window*. The read path is
deliberately left on this footing for now because it keeps its platform-level backstop
— the credential is measured `READ_ONLY` and Google refuses its mutate calls
server-side — whereas the write path, which has no such backstop, was moved into a
one-shot container Hermes has no shell in (see "Credential separation" below).
`run-ads-report.sh` and `bin/run-ads-report.py` are **frozen** (Increment 3), so
closing this the same way is a later increment, not an edit here.

**Usage:**

```bash
./run-ads-report.sh --project claude_google_ads --report account_overview
# -> prints /opt/data/reports/claude_google_ads/<ts>-account_overview.md ; exit 0
```

The report is a scrubbed markdown file under `/opt/data/reports/<project>/`.
`claude -p` may then be pointed at it read-only (`--permission-mode plan
--allowedTools 'Read,Grep,Glob'`) to summarize or answer questions about it.

**Allow-list** — each project's `read_execute` block in `registry/projects.yaml`
pins `runner` (the venv interpreter), `script_dir`, and an `allow` list of exact
script basenames. `run-ads-report.py` resolves `--report` against that list and
refuses (fail-closed, before any subprocess or API call) anything not on it.
The list is **readers only** — no mutating script is ever added to it, in this
project or any future one.

**Safety model (defense in depth, each layer independent of the others):**

- **Platform read-only backstop** — the credential itself cannot mutate (see
  Prerequisite above); this holds even if every other layer below failed.
- **Allow-list, fail-closed** — unknown/mutator report names are rejected
  before exec; path separators / traversal in `--report` are rejected too.
- **No shell for `claude`** — the reader always runs via the wrapper +
  `run-ads-report.py`, never through a `claude -p` Bash tool call; the operator
  skill's `read-execute` branch enforces this (§2 above).
- **Credential scrub** — `_scrub()` replaces all six credential values with
  `***` in both captured stdout and stderr before anything is persisted or
  printed; verified clean against the report file, `docker compose logs
  hermes-agent`, and `data/logs`.
- **`:ro` project mount** — the reader subprocess runs with a scratch cwd and a
  restricted child env (the six credentials + a minimal runtime whitelist,
  excluding `ANTHROPIC_API_KEY`/OpenRouter keys); the project mount stays
  read-only regardless, so nothing under it can be written even if a reader
  script tried.

**Pinned venv** — the reader runs under `/opt/ads-venv/bin/python3`, a
build-time virtualenv baked into the image (Task 1), not the base
interpreter. If the target project's `google-ads`/dependency pins change,
rebuild the image (`docker compose up -d --build`) to resync the venv —
a stale venv is a correctness issue, not a security one, since the allow-list
and credential scope are enforced independently of it.

**Proofs (this session, live):**

- `account_overview` produced a real report —
  `data/reports/claude_google_ads/2026-08-03_20-22-41-account_overview.md`
  (host path; `/opt/data/reports/...` in-container) — containing real account
  data (a dental practice's account name) with the customer id scrubbed to `***`.
- Credential scan clean: none of the six `GOOGLE_ADS_*` values appear in the
  report or in `docker compose logs`.
- Allow-list fail-closed, live: `./run-ads-report.sh --project
  claude_google_ads --report apply_negatives` exits non-zero with `report
  'apply_negatives' not in read_execute allow-list ['test_connection',
  'account_overview'] — readers only; mutators are never allow-listed` — a
  pre-exec rejection, so no credential is ever used for this call.
- Confinement: the `/projects/claude_google_ads` mount is `ro` in the running
  container, and the target's git working tree was byte-identical
  before/after a run — read-execute never wrote the `:ro` mount.

**Tests:** `python3 infra/hermes-agent/bin/run-ads-report.test.py` (like the other
hermes `bin/` tests, run directly — not auto-discovered by `run-all-tests.js`).

## Google Ads audit pilot (P6 — monetization)

Builds on read-execute to produce a **client-grade Google Ads audit DRAFT** (executive
summary + top-5 prioritized actions + "do NOT change yet" + evidence appendix) for a
dental practice — the first monetization pilot (fixed-fee one-off audit). **Read-only
end-to-end; the ad account is never mutated; Hermes never writes the client tree.**

Three host commands, run in order:

```bash
cd infra/hermes-agent
./collect-audit-data.sh                                 # 1. refresh audit_data/ (host, read-only cred)
./run-audit-bundle.sh claude_google_ads                 # 2. produce the scrubbed report set
./run-ads-audit.sh   claude_google_ads                  # 3. opus analyst -> DRAFT in /opt/data/audits/
```

- **Collection (`collect-audit-data.sh`)** runs the ads project's OWN collectors
  (`audit_discovery.py`, `negatives_audit.py` — SELECT-only) on the **host** under the
  read-only credential from `.env.ga`, refreshing `<project>/audit_data/`. It runs on the
  host (not in-container) because it must WRITE the project tree; Hermes itself stays `:ro`.
  It parses `.env.ga` (never sources it) and rejects unknown args (the `--dry-run` gate
  can't be bypassed by a typo). Prints an ISO-8601 collection timestamp = the deliverable's
  data provenance.
- **Bundle (`run-audit-bundle.sh`)** loops the allow-listed audit readers
  (`account_overview`, `audit_search_terms`, `audit_analyze`) through the Inc-3 wrapper,
  producing credential-scrubbed reports under `/opt/data/reports/<project>/`.
- **Analyst (`run-ads-audit.sh`)** runs `claude -p` (`--permission-mode plan
  --allowedTools 'Read,Grep,Glob'`, model `claude-opus-4-8`) over the scrubbed reports +
  the project's SOP/benchmark docs, following the `claude-code-ads-analyst` skill, and
  emits the DRAFT. `claude` never writes — a shell redirect persists the output to
  `/opt/data/audits/<project>/` (writable), never the `:ro` mount. The project arg is
  charset-validated (rejects path/shell metacharacters) and passed via `docker exec -e`.

**Safety model (defense in depth, each layer independent):** read-only Google Ads
credential (mutation refused server-side) · allow-list readers only, fail-closed ·
collection SELECT-only · analyst is read-only `claude` (no Bash/Write) · `_scrub` removes
credential values from every report · `:ro` project mount · **human-review gate** (the
output is a DRAFT; an operator validates it against the raw reports before any client use).
Note: report *content* (search terms are whatever the public typed into Google) is
untrusted input to the analyst — well-contained here (the analyst has no Bash/Write and no
credential, and the draft is human-reviewed), so the worst case is a misleading line a
reviewer catches, never mutation or exfiltration. Treat the draft's claims as a starting
point to verify, not gospel.

**Client-private data governance (hard rule):** the reports and the audit draft contain
real client business data. They live ONLY under `/opt/data` (gitignored) — NEVER committed
to git, NEVER written to the brain/memory/telemetry. Only the meta pilot outcome is captured.

**Allow-list:** the audit readers are in `registry/projects.yaml` under the
`claude_google_ads` `read_execute.allow` block; mutators are never listed. The reader deps
run in the pinned `/opt/ads-venv`. When the ads project's collectors/readers change, re-run
the Task-1-style verification before trusting the pipeline.

## Two-tier memory / per-client vaults

Hermes keeps two separate memory tiers so client-private data never reaches the
shared, git-versioned project brain:

- **Shared project brain** (`.project-brain/`, git) — META only: how the pipeline
  operates, methodology, what "good" looks like. No client data, ever.
- **Per-client vaults** (gitignored, Obsidian-flavored markdown) — one client's
  audits, metrics history, timeline, and opportunities. They live only under
  `/opt/data/vaults/<slug>/` (host `data/vaults/<slug>/`, which opens directly in
  Obsidian), never in git.

The **client roster is itself client-private** and, since it gates every mutation
guard, it lives outside the gateway container entirely: in the host-owned governance
store (see "Governance store" below) at `$HERMES_GOVERNANCE_DIR/registry/clients.json`.
The gateway container does not mount it at all; only the one-shot executor Hermes has
no shell in reads it, read-only. `registry/projects.yaml` stays project-level and
client-agnostic, still version-controlled and mounted read-only into the gateway as
before. Shape:

```json
{ "clients": {
    "<slug>": { "project": "<project>", "customer_id": "<digits>",
                "currency": "USD", "timezone": "America/New_York",
                "status": "active" }
} }
```

**Vault layout** (`data/vaults/<slug>/`):

```
index.md               # client profile
timeline.md            # one line per run (the analyst reads this first)
audits/<ts>-audit.md   # audit DRAFTs over time
metrics/<ts>.json      # deterministic KPI snapshot per run (enables trend deltas)
```

**Trend audit** — the operator entry point re-collects fresh data (read-only
credential, this client's account), produces the scrubbed report set, runs the opus
analyst in plan mode over the fresh reports **plus this client's prior `metrics/` +
`audits/`** (so the draft references change-over-time; a first run establishes a
baseline), and persists the new draft + snapshot into the vault via `bin/vault-write.py`
(the sole vault writer):

```bash
cd infra/hermes-agent
./run-trend-audit.sh --client <slug>
```

**Offboarding / retention** — export-then-hard-purge a client's vault, with a
deletion audit log and a registry status flip. Export always precedes deletion; a
distinct **exit 3** signals a failure that occurred *after* the irreversible delete
(vs exit 2 for a pre-flight refusal):

```bash
python3 bin/vault-purge.py --client <slug> --export-to <dir> --confirm
```

**Safety model:** read-only end-to-end — the trend audit never mutates the ad
account (platform mutation is a separate, future increment); `claude` runs plan-mode
`Read,Grep,Glob` only and writes the draft via a redirect to `/opt/data`, never a
`:ro` mount. Soft cross-client isolation now (one `VAULT_DIR` per run + a fail-closed
assertion that the draft names no other client), with hard per-client container
isolation deferred. The deliverable is a DRAFT behind a human-review gate. No client
name, account id, metric, or draft is ever committed to git, the brain, or telemetry.

**Tests** (run directly — not auto-discovered by `run-all-tests.js`):

```bash
python3 infra/hermes-agent/bin/vault_lib.test.py
python3 infra/hermes-agent/bin/ads-metrics-snapshot.test.py
python3 infra/hermes-agent/bin/vault-write.test.py
python3 infra/hermes-agent/bin/vault-purge.test.py
```

## Mutation tier — applying approved changes (Task 2)

The first Hermes path that can **change** a client's Google Ads account. Everything
else in this README is read-only, and that guarantee has always rested on a
**read-only credential**: Google refuses every mutate call server-side, whatever the
code does. This tier deliberately removes that backstop for one narrow action, so
**the guardrails are the safety model** — there is no platform-level layer beneath them.

Scope is one typed action: **add a campaign-level negative keyword**. Never budgets,
bids, or campaign status. Undo removes exactly the criteria this rail created, by
resource name.

**Three commands, deliberately not chainable, with sharply different privilege:**

```bash
cd infra/hermes-agent
./changeset.sh propose --client <slug> --from actions.json               # no credential
./changeset.sh approve --client <slug> --changeset <id> --operator <name> \
    --expect-sha256 <hex>
./run-ads-mutate.sh --client <slug> --changeset <id>                      # write credential
./run-ads-mutate.sh --client <slug> --undo <id>
```

**Run them through the wrappers, not the scripts directly.** `bin/propose-changeset.py`
and `bin/approve-changeset.py` default to the **container** paths
(`/opt/governance/registry/clients.json`, `/opt/data/vaults`), which on the host fail
with *"client registry not found"*. `changeset.sh` sets the two host-side roots — and
resolves `HERMES_GOVERNANCE_DIR` the same way `run-ads-mutate.sh` does: from the
environment if set, otherwise parsed **as data** out of `.env`, which Docker Compose
reads for interpolation but never exports to your shell. The equivalent by hand, if you
prefer to invoke the scripts directly, is:

```bash
export HERMES_GOVERNANCE_ROOT="$HERMES_GOVERNANCE_DIR"   # ...itself exported first
export VAULT_ROOT="$PWD/data/vaults"
python3 bin/propose-changeset.py --client <slug> --from actions.json
```

`approve` prints the **sha256 it binds** and **one line per action**. Read them: that
printout is the only place the operator can confirm that what is being approved is what
was reviewed (see "What the snapshot does and does not close" below).

`--expect-sha256 <hex>` is the **default path, not an option** (2026-08-24): omit it and
`approve` refuses — printing the digest and the per-action summary first, so the refusal
is a step in the workflow (read the summary, paste the digest back) rather than a bare
rejection. Supply a digest that does not match and `approve` refuses with the same exit
code, naming the mismatch:

```bash
./changeset.sh approve --client <slug> --changeset <id> --operator <name>
# refuses: prints the digest + actions and tells you to re-run with --expect-sha256 <hex>

./changeset.sh approve --client <slug> --changeset <id> --operator <name> \
  --expect-sha256 <hex>        # succeeds only if the bytes on disk hash to <hex>
```

Be honest about what this buys: it converts a reading task into a mechanical
confirmation, not more. An operator who pastes the digest back without reading the
printed summary above it has confirmed nothing. It does not make **review → approve**
structurally closed — see below.

`propose` and `approve` hold **no credential and perform no network I/O** — they are
structurally incapable of touching the account. Only `apply` can reach Google.

The operator's `actions.json` contains **only** an `actions` array; `propose` fills in
client, project, customer id, change-set id, and timestamp from the client resolver.
An operator therefore cannot typo a customer id into a change-set, and the apply-time
identity check becomes a genuine tamper check.

**Approval binds bytes.** `approve` records the sha256 of the exact change-set file the
operator reviewed, plus an expiry, and copies those bytes into the host-owned
governance store. `apply` executes from **that copy**. Editing the vault copy afterwards
has no effect on what runs; editing the snapshot invalidates the approval, because
`apply` recomputes and compares.

**What the snapshot does and does not close.** It closes **approve → apply**
completely: after `approve` returns, the executed artefact lives somewhere Hermes
cannot write, so nothing can change what runs. It does **not** close
**review → approve**: the snapshot is taken *at approve time*, from the vault copy, so
whatever is there when the operator types the command is what gets bound — including
bytes written after a human read the change-set. The precise claim this rail supports
is *"a model can never author both a change and its approval"*; it is **not** *"a model
can never author the change"*. The residual window is covered by procedure and by
`approve`'s printed digest + per-action summary, not by a mechanism.
`--expect-sha256` being the default path removes the *silent* default — where the
command bound whatever happened to be on disk with no confirmation step at all — but it
does not remove the human, and does not close the window structurally: an operator who
pastes the digest without reading the summary above it has confirmed nothing. The real
reason this window stays empty in v1 is a separate rule (§17.1: no model authors a
change-set), not this flag.

**Guard order at apply** (fail-closed; the credential is touched last, so every refusal
happens before Google is reachable):

1. kill switch present and readable
2. client slug resolves and is `active`
3. change-set loads from the approved SNAPSHOT in the governance store — never the
   vault copy Hermes can write — schema-validates, within the per-change-set action cap
4. change-set identity matches the resolved client
5. approval hash matches and has not expired
6. daily caps satisfied, counted from the audit log
7. the injected credential belongs to **this** client
8. mutator resolves in `mutate_execute.allow`; the read and mutate allow-lists are disjoint
9. full credential set present and `GOOGLE_ADS_CREDENTIAL_ROLE=write`
10. **`validate_only` dry run over every action, all-or-nothing** — any failure aborts
    the whole change-set with nothing applied
11. live apply, one action at a time, each logged and fsynced **before the next begins**

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | usage error |
| 2 | pre-flight refusal — **guaranteed nothing was mutated** |
| 3 | failure *after* at least one live mutation landed; the audit log holds what applied, and `--undo` reverses it |

Exit 2 is a promise about the account, not merely about the process. The test suite
asserts the stronger property directly: for every refusal, the mutator subprocess is
never spawned at all.

**Caps** live in `registry/projects.yaml` under `mutate_execute.caps`, so tuning them is
a config edit rather than a code change. Missing or malformed caps **refuse** — an
unreadable limit must never become an unlimited one. Defaults: 25 actions per
change-set, 100 actions and 5 applies per client per day, 24-hour approval expiry.

**The kill switch** is a marker file in the host-owned governance store (see
"Governance store" below), at `$HERMES_GOVERNANCE_DIR/control/mutation-enabled` on the
host. The gateway container does not mount that tree at all, so nothing running inside
it — including a compromised Hermes session — can create, see, or remove that file.
Absent, unreadable, or a directory in its place all mean *disabled* — the safe state is
the default state, and one `rm` on the host disables all mutation across every client.

**Undo bypasses only the kill switch and the daily caps.** Guards constrain *creating*
change, never *reversing* it: a tripped kill switch that also blocked cleanup would be a
guardrail that makes a bad situation worse. Every other guard still applies.

An undo cannot reach another client's account, and *two independent checks* enforce that:
the injected credential must belong to the resolved client (guard 7), and every
`resource_name` read out of the audit log is shape-validated and prefix-checked against
that client's customer id before it can become a command-line argument. The second check
lives in `apply-changeset.py` deliberately. The mutator carries an equivalent one, but a
pre-flight guarantee that exists only in a separate repository is one Hermes neither owns
nor version-pins — and for a while that was the only copy, which a whole-branch review
caught.

**`--dry-run` runs the guards, not the account.** `./run-ads-mutate.sh --client <slug>
--changeset <id> --dry-run` runs every pre-flight guard and prints the resolved runner,
script, mode, and action count — then stops. It does **not** perform the `validate_only`
pass, and it never spawns the mutator, so it proves the change-set would be *admitted*,
not that Google would accept it. The `validate_only` dry run happens inside a real apply.

**One client per credential file.** Guard 7 requires the injected
`GOOGLE_ADS_CUSTOMER_ID` to equal the resolved client's customer id, and `.env.gaw` pins
exactly one. Operating a second client means pointing that file at that client — by
construction, not by convention. This is a deliberate safety property, but it surfaces as
a refusal rather than a prompt, so it is worth knowing before the second client rather
than during it.

**Credential separation.** The write credential lives **only** in the gitignored
`.env.gaw` (copy `.env.gaw.example`), is parsed as data rather than sourced, and is
injected per-invocation into the one-shot `ads-mutator` container via
`docker compose run -e` — a container Hermes has no shell in. It never enters the
gateway container at all.

An earlier version of this doc claimed the credential "reaches only this exec'd
process." That was true of *delivery* and false of *visibility*: `/proc/<pid>/environ`
is readable by any same-UID process, and everything running in the gateway container
runs as the same user, so a same-container boundary was never real isolation — any
process in that container could have read it. The one-shot, no-shell `ads-mutator`
container is what actually makes the credential inaccessible to Hermes, because Hermes
has no process running there to read `/proc/<pid>/environ` from.

The credential is never in `.env`, never in `.env.ga`, and never in the gateway
environment. `.env.ga` stays read-only so every other path keeps its backstop —
**never copy a token between the two files**. The mutator in the ads project reads
credentials strictly from the injected environment and never loads a local `.env`,
which would otherwise pick up that project's full-access token.

**Vault artifacts** (gitignored, per client, under `data/vaults/<slug>/changes/`):
the proposed change-set and a per-run result file. The **approval record and the
byte-exact snapshot `apply` executes from** do not live here — they live in the
host-owned governance store (see "Governance store" below), so Hermes can write the
vault copy of a change-set but cannot reach or tamper with what `apply` actually reads.
The **append-only audit log** (`log.jsonl`, one per client) that feeds the daily caps
and undo also lives in the governance store, not the vault. Each apply still appends a
line to the vault's `timeline.md`, so the next trend audit sees that a change was made.

**Tests.** These suites are stdlib-only and are not discoverable by
`scripts/run-all-tests.js`, which is node-only by design. Run all of them with:

```bash
infra/hermes-agent/bin/run-bin-tests.sh
```

It discovers every `*.test.py` in that directory rather than listing them, runs all of
them even after one fails, and exits non-zero if any did. Individual suites still run
directly (`python3 infra/hermes-agent/bin/apply-changeset.test.py`) — note `python3`,
never `python`.

## Governed mutation syscall — how Hermes asks for a change (Plan 2, Phase A)

The mutation tier above is host-side: an operator runs `run-ads-mutate.sh`. The syscall is how
**Hermes itself** asks for an approved change-set to be applied, without ever holding the write
credential, reaching the governance store, or getting a shell on the host.

It is a **spool**, not an API. Hermes writes a request file; a host-side broker picks it up. There
is no listener, no socket, and no network path between the two — the only channel is a directory
the agent can write and the broker can read.

### Spool layout

`data/spool/` (inside the container, `/opt/data/spool`), overridable with `HERMES_SPOOL_ROOT`:

```
data/spool/
  requests/<request_id>.json    # Hermes writes; the broker reads and deletes
  results/<request_id>.json     # the broker writes; Hermes reads
```

`<request_id>` is a uuid, and the filename must match the `request_id` inside the file. The broker
treats every byte here as hostile: closed schema, size cap, regular-files-only, no symlinks, no
directories, and a quarantine for entries it cannot parse.

### Client — `hermes-syscall`, in-container

Identifier-only. It passes a client slug and a change-set id, never a customer id, never a
credential, never a file path.

```bash
python3 /opt/cc-bin/hermes-syscall.py apply  --client <slug> --changeset <id>
python3 /opt/cc-bin/hermes-syscall.py result --request <request_id>
```

| Exit | Meaning |
|---|---|
| 0 | applied |
| 1 | usage error (bad arguments) |
| 2 | **refused** — a guard said no; nothing was mutated |
| 3 | failed *after* at least one live mutation landed — an operator must reconcile |
| 4 | **pending — NOT refused** |

**Exit 4 is the one that gets misread.** It means the broker has not written a result yet. The
request is still queued and may still succeed. Treat it as "ask again later", never as a refusal,
and never re-file the request — a second request for the same change-set is refused as a replay,
and the original is still in flight.

### Broker — host-side

```bash
python3 bin/hermes-broker.py --once                  # one drain pass, then exit
python3 bin/hermes-broker.py --watch --interval 5    # poll forever
```

`--once` is what a timer or a smoke test should call; `--watch` is for the long-running unit. Exactly
one of the two is required. The broker is single-threaded with one advisory lock per client slug, so
two drains cannot process the same client concurrently.

### The two quotas

Both live in the client registry, both **fail closed** — an unreadable or missing limit is a refusal,
never "unlimited":

| Key | Refusal | What it bounds |
|---|---|---|
| `max_pending_requests` | `refused_quota` | Unread requests per client at drain time |
| `accepted_requests_per_client_day` | `refused_quota` | Requests accepted per client per UTC day |

A client already over `max_pending_requests` has **every** request refused that drain, not merely the
surplus — the count is computed once per pass. That is deliberate: a flooding client gets nothing
until it drains.

### Spool overflow (R6) — a flood stalls the client until an operator clears it

Above `MAX_SPOOL_FILES` (256) matching request files, the broker **refuses the entire drain**:

- it writes **no per-request result files** — so `hermes-syscall result` reports *pending* (exit 4),
  which is honest: no decision was made about any individual request;
- it **does not delete the flooding files**. Attributing them to a client would require parsing
  them, which is the very work the cap exists to avoid;
- it logs loudly to stderr, so the condition is visible in the journal.

The consequence is deliberate and worth stating plainly: **a flooded spool stalls that client until
an operator clears it.** This is a documented departure from "a result on every outcome" (spec §12) —
overflow is a broker-level event, not a per-request outcome. There is no automatic pruning of
quarantined entries either; both are operator tasks today.

### Deploy sequence

Order matters — the pre-flight exists to stop a half-configured store becoming an exit-3 *after* a
live mutation:

1. **Governance store in place** — `approvals/`, `control/`, `registry/`, `log/`, `seen/` all present.
   `seen/` is host-only and must **not** be mounted into the executor.
2. **Pre-flight passes** — `python3 bin/preflight-governance-access.py --root "$HERMES_GOVERNANCE_DIR"`
   exits 0. It is a deliberate **no-op off Linux**, so a clean run on macOS proves nothing.
3. **Mutation disabled at rest** — no kill-switch file. Absence means disabled; that is the safe default.
4. **Broker started** (`--watch`) as its own user, never as root.
5. **Approve per action** — `approve-changeset.py` with `--expect-sha256`, which binds the approval to
   the exact reviewed bytes.

> **Not deployable to the VPS as of 2026-08-31.** Phase B (the body-inspecting Docker socket proxy
> and the systemd units) is not built, and without it the broker's Docker access on a VPS is host
> root. See `docs/evaluations/2026-08-30-hermes-phase-a-deployment-readiness.md`.

## Governance store

Every piece of state a mutation guard *trusts* — as opposed to state Hermes merely
produces, like a proposed change-set or a report — lives outside the container
entirely, in a host-owned directory tree the gateway container does not mount:

```
$HERMES_GOVERNANCE_DIR/
  control/    mutation-enabled            # the kill switch
  registry/   clients.json                # the client roster
  approvals/  <slug>/<cid>.approval.json  # approval record: hash + expiry
              <slug>/<cid>.changeset.json # byte-exact snapshot apply executes from
  log/        <slug>.jsonl                # append-only audit log; feeds caps + undo
  seen/       <slug>.jsonl                # replay-protection state (Plan 2)
```

Path contract in `bin/governance_lib.py`; every other module reaches these paths
through it rather than composing them independently.

**`HERMES_GOVERNANCE_DIR`** (in `.env`, gitignored) is the absolute host path to this
tree. It must be **outside this repo** (the repo is bind-mounted into the gateway
container) and **outside `./data`** (the one read-write mount the gateway does have).
Create it mode `700` before first use; Compose does not expand `~`, so write the path
in full (`/Users/you/.hermes/governance`, not `~/.hermes/governance`). See
`.env.example` for the annotated template.

**Who mounts what:**

| Container | approvals/ control/ registry/ | log/ | seen/ |
|---|---|---|---|
| `hermes-agent` (the gateway — where Hermes runs) | not mounted at all | not mounted | not mounted |
| `ads-mutator` (one-shot executor, no shell) | `:ro` | read-write | **not mounted** |
| `ads-credential-audit` (one-shot, no shell) | not mounted | not mounted | not mounted |

`seen/` is not mounted anywhere. The seen-set is replay-protection state written and
read entirely host-side by the broker; nothing under the executor's entrypoint touches
it. It used to be mounted read-write into `ads-mutator` on the strength of a comment
rather than a measurement, which handed the governed party delete access to the state
it is governed by (S3-a). `log/` must stay writable there — `append_log` is fsync'd per
action and is the reversibility record `--undo` reads.

The gateway **does not mount any part of the store** — no path in it is readable or
writable from the container Hermes runs in. Verify at any time:

```bash
docker compose exec -T hermes-agent sh -c '[ -e /opt/governance ] && echo REACHABLE-BAD || echo unreachable-good'
```

The store's host **path** is no longer in the gateway's environment either. It used to
be: `HERMES_GOVERNANCE_DIR` lives in `.env`, which is the gateway's `env_file`, and
`env_file` injects every key it holds. The variable cannot simply be removed from
`.env` — Compose interpolates `${HERMES_GOVERNANCE_DIR}` from that same file when
rendering `ads-mutator`'s mounts, and `hostenv.sh` parses it as data for the host-side
rail — so the gateway service masks it with an empty `environment` entry instead, the
same idiom as `masks/empty` for the ads repo's `.env`. Interpolation is unaffected: it
happens at render time, from the file, before any container exists. Verify:

```bash
docker compose exec -T hermes-agent sh -c 'echo "[$HERMES_GOVERNANCE_DIR]"'   # => []
```

Knowing a host path grants nothing on its own — the tree is not mounted and the
container has no way to reach the host filesystem, which is why this was graded on the
policy axis rather than as a disclosure. It is worth withholding anyway, because
anything host-side that writes into `data/` on Hermes's behalf writes to a target an
attacker would otherwise know; that is exactly the shape of the 2026-08-19 symlink
finding against the run-record persist step, and why `bin/persist_run_record_shim.py`
resolves and contains every destination it opens.

### Ownership on a Linux host

The store is documented as mode `700` owned by the deploy/broker user — and the
one-shot `ads-mutator` executor runs as **uid 10000** (`Dockerfile`: `USER hermes`). On
Linux those are the same UID namespace, so a `700` store owned by anyone else is simply
**unreadable to the executor**: the kill switch reads as absent, client resolution
raises, and `append_log` fails *mid-apply* — exit 3 after a live account change has
landed. macOS hides this entirely, because Docker Desktop remaps ownership, so the
local gate passes and the VPS is where it breaks.

Give the store an ownership the executor's UID can use — either group access:

```bash
sudo chgrp -R 10000 "$HERMES_GOVERNANCE_DIR"
sudo chmod -R g+rX "$HERMES_GOVERNANCE_DIR"
sudo chmod -R g+w  "$HERMES_GOVERNANCE_DIR"/log
```

`log/` only — `seen/` is not mounted into the executor and needs no access for uid
10000. Widening it would hand the governed party the replay-protection state again.

or outright ownership:

```bash
sudo chown -R 10000:10000 "$HERMES_GOVERNANCE_DIR" && sudo chmod -R 700 "$HERMES_GOVERNANCE_DIR"
```

**Never `chmod 777`.** The store is the one tree Hermes cannot reach; making it
world-writable hands it to every process on the host and deletes the isolation the
whole tier rests on.

`run-ads-mutate.sh` pre-flights this before it does anything else
(`bin/preflight-governance-access.py`), so the condition surfaces as a refusal with the
remedy printed, rather than as an exit-3 failure halfway through an apply. The check is
a no-op on non-Linux, where a stat-based prediction would be false.

**Migration** copies the pre-governance-store artifacts (client registry, audit log)
from the vault tier into the store. Dry run by default; `--apply` performs the copy.
Originals are left in place as a rollback path — the migration copies, it does not move:

```bash
python3 infra/hermes-agent/bin/migrate-governance.py \
  --vault-root infra/hermes-agent/data/vaults \
  --governance-root "$HERMES_GOVERNANCE_DIR"        # dry run; add --apply to execute
```

## Mount masking — keeping credential files out of the container view

The project mounts are `:ro`, which stops Hermes *writing* them. It never stopped
Hermes *reading* them, and on 2026-08-19 a probe found **five readable non-empty
credential files** inside the gateway container: the Ads read credential, the Ads write
credential, Hermes's own `.env`, and the draft-PR bot PAT — all through the repo mount,
plus the ads project's own `.env`. None of that exposure was intended, and nothing
in-container consumed any of it. Masking closes it.

**Declared in `registry/projects.yaml`, enforced in `docker-compose.yml`.** Each project
declares `mask_paths:` — workdir-relative paths that must not be visible in the
container:

```yaml
  claude_code:
    mask_paths:
      - infra/hermes-agent        # the whole directory: every .env.* lives here
  claude_google_ads:
    mask_paths:
      - .env                      # one file
```

**Two mask kinds, chosen by what is being hidden:**

| Kind | Compose form | Use when |
|---|---|---|
| **Directory tmpfs** | `- type: tmpfs` / `target: <path>` / `read_only: true` | hiding a whole directory. An empty in-memory filesystem is laid over it; it never touches the host, and `read_only: true` keeps it consistent with the read-only-project-mount default. |
| **Empty-file bind** | `- ./masks/empty:<path>:ro` | hiding one file while its directory must stay visible. The path still exists and reads as 0 bytes, so anything that merely tests for presence is undisturbed. |

**The declaration and the mount are paired by a test, not by discipline.**
`bin/registry-invariants.test.py` asserts that every declared `mask_paths` entry has a
**real mount targeting it inside the `hermes-agent` service's own `volumes:` list** — a
declared mask that Compose does not implement reads as protection while providing none.
The test is anchored to actual mount syntax and scoped to that one service, so a path
mentioned only in a comment, or mounted on `ads-mutator` while the gateway stays
unmasked, does **not** satisfy it; controls in the same suite assert both of those
failure modes are caught. `read_mask_paths` refuses a duplicate `mask_paths:` key
rather than silently choosing which paths stay exposed.

**Verify after any change** (the control is what makes the result meaningful — an
unreadable file proves nothing if the probe itself is broken):

```bash
# every credential file must be absent or empty ...
docker compose exec -T hermes-agent sh -c 'for f in /projects/claude_code/infra/hermes-agent/.env*; do [ -s "$f" ] && echo "READABLE-BAD $f"; done; echo done'
# ... while a known-readable control file still reads normally
docker compose exec -T hermes-agent sh -c 'head -1 /projects/claude_code/CLAUDE.md >/dev/null && echo control-ok'
```

Masking a mount can break the reader path, which would be worse than the exposure, so
re-run a report and a collection afterwards and confirm both still exit 0.

## Credential access levels — measure, never assert

Every access-level guarantee here used to be a sentence in prose: "`.env.ga` is
read-only", "`.env.gaw` is Standard-access". Twice those sentences were wrong, and
both times the discrepancy surfaced by luck rather than by design. Prose cannot be
checked, so the guarantee is now measurable:

```bash
cd infra/hermes-agent
./audit-credential-access.sh --cred .env.ga  --customer <digits>
./audit-credential-access.sh --cred .env.gaw --customer <digits>
./audit-credential-access.sh --all
```

It is **credential-scoped, not project-scoped** — it asks Google what a given
credential can do, so it works unchanged for whatever project replaces
`claude-google-ads` and for every project registered after it.

**Structurally non-mutating.** The mutate probe hardcodes `validate_only=True`
with no flag to disable it; every other probe is a `SELECT`. It cannot change an
account.

| Probe | Answers |
|---|---|
| `read` | Can it read the target account? Positive control for the rest — without a successful read, a refusal below proves nothing about access level |
| `scope` | How many accounts are reachable under the login customer — the blast radius, and the number that matters once Hermes holds credentials for several projects |
| `mutate` | `validate_only` against a **SEARCH** campaign. Three-valued: PERMITTED / DENIED / INCONCLUSIVE |
| `roles` | The `customer_user_access` role table for the manager and the target account — Google's own record of who holds what |

**Verdicts:** `UNUSABLE` · `READ_ONLY` · `MUTATE_CAPABLE` · `INCONCLUSIVE`.
Exit `0` agree · `2` unusable · `3` **mismatch** · `4` inconclusive.

Two rules this encodes, both learned from getting them wrong:

- **A context refusal is not an authorization refusal.** Campaign-level negative
  keywords are invalid on some channel types; that refusal says nothing about
  access level. Conflating the two reports a mutate-capable credential as
  read-only. Hence the SEARCH-campaign requirement and the three-valued result.
- **"Could not tell" must never round to "safely read-only."** An inconclusive
  probe stays `INCONCLUSIVE` and exits 4.

| `manager_admin` | Is it ADMIN at the **manager** level? `validate_only` update of the manager account's own name, set to the value it already holds. Touches no client ad account |

**How the admin probe was arrived at, because two earlier attempts were wrong and
both failed confidently.** First, reading `customer_user_access` was treated as
proof of ADMIN — it is not a discriminator at all, since a READ_ONLY credential
reads it fine, and the tool reported ADMIN for a credential whose mutate was
refused in the *same run*. Then this doc claimed admin was simply not measurable,
reasoning that `MutateCustomerUserAccessRequest` has no `validate_only`. True, but
the wrong service: `MutateCustomerRequest` **has** `validate_only`, and updating the
manager account is admin-gated.

The current probe is verified **discriminating** against a known-READ_ONLY control
(`hermes@` is refused with `ACTION_NOT_PERMITTED`; a manager ADMIN is accepted).
That control is the check both earlier versions lacked — a probe never shown to
refuse something it *should* refuse proves nothing when it accepts.

This is also how a credential's identity gets pinned down without a `whoami`
endpoint, which Google Ads does not offer: combine the measured manager-level
result with the `customer_user_access` role table. A credential that is refused at
manager level cannot belong to any manager ADMIN, which is often the exclusion you
actually need.

**Tests:** `bin/audit-credential-access.test.py` covers the classification logic
(the part where both historical bugs lived). The probes need a live account and
belong to operator-run verification.

## Provisioning a credential for a new project or role

The model, stated once so the next project does not have to rediscover it:

**One OAuth client per credential-holding component, and one Google *account* per
role.** These are different axes and conflating them is what made an earlier
revocation collateral rather than surgical — revocation is per *(user, client)*
pair, so a shared client means killing one grant kills them all.

| Role | Account | Access level | Credential file | Why |
|---|---|---|---|---|
| read | `hermes@…` | **READ_ONLY** on the manager | `.env.ga` | The platform backstop. Google refuses every mutate server-side, so a read path stays safe even if every allow-list, cap and kill switch failed. **Never upgrade this account.** |
| write | the operator's own Google account | **ADMIN** on the manager | `.env.gaw` | Operator decision, 2026-08-18: reuse the existing account rather than provision a dedicated `hermes-write@`. |

**The write row is a deliberate, recorded tradeoff, not the ideal shape.** A
purpose-made `hermes-write@` at STANDARD would be better on three counts, and it is
worth knowing which ones were traded away:

- **Privilege.** The operator account is ADMIN at the manager level, so the write
  credential carries user management, billing and account linking — far more than
  the one typed action (`add_campaign_negative`) the mutation tier actually uses.
  A STANDARD service account would be mutate-capable and nothing more.
- **Attribution.** Google's change history will record Hermes's mutations under a
  human's identity. Nothing on the platform side distinguishes "the operator did
  this" from "Hermes did this while the operator was asleep". The vault audit log
  (`data/vaults/<slug>/changes/log.jsonl`) is the only place that distinction
  exists, so it carries more weight than it otherwise would.
- **Assurance.** With a purpose-made account the access level is known by
  construction. With a human account it is inherited from whatever that person
  needs for their own work, and it can change without anyone touching Hermes —
  which is exactly the drift pattern this capsule has been bitten by twice.
  Compensate by running the access audit after any change to the operator's own
  Google Ads permissions, not just after Hermes changes.

**What is NOT lost:** revocation stays surgical. OAuth revocation is per
*(user, client)* pair, and Hermes has its own OAuth client as of 2026-08-17, so
revoking the Hermes write grant does not disturb the operator's other grants for
the same account. That property came from separating the client, not the account —
which is why the two axes are worth keeping distinct even when one is reused.

Never point both files at the same account, and never copy a token between them.
The read guarantee is only real while the read account genuinely cannot mutate.

**Steps.** Console work is the operator's; verification is mechanical.

1. Google Ads → the manager account → Admin → Access and security → invite the new
   user at the minimum role for its job (`STANDARD` for write; `READ_ONLY` for read).
   Accept the invitation from that account.

   *Skip this step when reusing an existing account* — which is the current shape of
   the write role. Reuse changes nothing below: step 2 still creates a **separate
   OAuth client**, and that is what keeps revocation surgical. Never reuse another
   component's client just because you are reusing its account.
2. Cloud Console → Credentials → Create OAuth client ID → **Desktop app**, named for
   the component. One client per component; do not reuse another component's.
3. Mint the refresh token **signed in as the matching account**, in a terminal that is
   not an assistant session — the token must never reach a transcript. Set the new
   client id/secret first: the ads project's `get_refresh_token.py` calls
   `load_dotenv()`, and `load_dotenv` does not override already-set variables, so a
   bare run mints against whatever client that project's `.env` names. The failure
   then looks like a bad token rather than a wrong client.
4. Write the value into the gitignored `.env.<x>` (mode 600). Never into a tracked
   `*.example`, never into git, never into a report or the brain.
5. **Verify rather than assert:**

```bash
./audit-credential-access.sh --cred .env.gaw --customer <digits>
# expect: measured_verdict MUTATE_CAPABLE, mismatch false, exit 0
./audit-credential-access.sh --cred .env.ga  --customer <digits>
# expect: measured_verdict READ_ONLY,      mismatch false, exit 0
```

   Check `probes.scope.reachable_accounts` — that is the blast radius. An MCC-level
   grant reaches every account under the manager; if a credential should only touch
   one client, grant it on that client account rather than on the manager.

   Then match `probes.roles` against the account you just minted from. The tool
   reports the role table but deliberately does not guess which row is *this*
   credential — see the note above on why ADMIN is not measurable non-destructively.

**Drift detection.** Access levels have silently changed before. Re-run the audit
after any access change, and periodically:

```bash
./audit-credential-access.sh --all --customer <digits>   # exit 3 = a credential is not what it claims
```

## Security

- Keys live in `.env` (gitignored); the executor's key is projected into the
  gitignored `data/` volume by the init sidecar. **No secret is ever committed** —
  `.env`, `data/` are gitignored; only `*.example` templates are tracked.
- Dashboard/API bind to loopback only. Project mount is read-only until write
  access is explicitly granted (plan P5).
- Rotate any key that has been exposed (logs, transcripts, screen shares), then
  recreate the container.
