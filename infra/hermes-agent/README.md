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

## Security

- Keys live in `.env` (gitignored); the executor's key is projected into the
  gitignored `data/` volume by the init sidecar. **No secret is ever committed** —
  `.env`, `data/` are gitignored; only `*.example` templates are tracked.
- Dashboard/API bind to loopback only. Project mount is read-only until write
  access is explicitly granted (plan P5).
- Rotate any key that has been exposed (logs, transcripts, screen shares), then
  recreate the container.
