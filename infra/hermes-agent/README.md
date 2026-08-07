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

**Usage** (operator-invoked; the wrapper sources `.env.pr` and passes the PAT via
`docker compose exec -e` — it never enters the gateway env):

```bash
./infra/hermes-agent/open-proposal-pr.sh --project claude_code --proposal latest
# prints the draft PR URL; add --dry-run to preview without any git/network.
```

**90-day PAT rotation:** mint a new bot PAT → replace the value in `.env.pr`. No
container recreate needed (the PAT isn't in the gateway env).

**Safety model:** bot ≠ owner; `:ro` mount never written (ephemeral clone only);
draft-only (a human marks ready + merges); `main` unwritable by the bot (pre-push
hook + server-side ruleset); and the PAT is kept **out of the gateway env** so no
agent-launched process can read it — necessary because **Hermes does NOT scrub the
`CLAUDE_CODE_PR_PAT` name** (it only scrubs known-provider names).

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
the gateway/agent environment. `run-ads-report.sh` sources it on the host and
injects the six values **per-invocation** via `docker compose exec -e`, so
they reach only the one exec'd reader process — the same pattern as the
Increment-2 PAT in `.env.pr`.

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
  data ("Palmetto Dental Studio") with the customer id scrubbed to `***`.
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

The **client roster is itself client-private**, so it lives in the vault tier, not
git: `data/vaults/_registry/clients.json` (gitignored). `registry/projects.yaml`
stays project-level and client-agnostic. Shape:

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

## Security

- Keys live in `.env` (gitignored); the executor's key is projected into the
  gitignored `data/` volume by the init sidecar. **No secret is ever committed** —
  `.env`, `data/` are gitignored; only `*.example` templates are tracked.
- Dashboard/API bind to loopback only. Project mount is read-only until write
  access is explicitly granted (plan P5).
- Rotate any key that has been exposed (logs, transcripts, screen shares), then
  recreate the container.
