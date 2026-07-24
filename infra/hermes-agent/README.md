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

## Security

- Keys live in `.env` (gitignored); the executor's key is projected into the
  gitignored `data/` volume by the init sidecar. **No secret is ever committed** —
  `.env`, `data/` are gitignored; only `*.example` templates are tracked.
- Dashboard/API bind to loopback only. Project mount is read-only until write
  access is explicitly granted (plan P5).
- Rotate any key that has been exposed (logs, transcripts, screen shares), then
  recreate the container.
