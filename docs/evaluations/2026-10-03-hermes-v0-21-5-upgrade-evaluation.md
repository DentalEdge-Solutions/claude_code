# Upgrade evaluation — Hermes Agent v0.19.0 → v0.21.5

> **Date:** 2026-10-03 · **Asked:** should the box move from the pinned v0.19.0 to v0.21.5 before security
> review #7? · **Answer:** yes, in the same batch as the PR #96 pull: one fingerprint change, one review.
> **Method:** official sources read on 2026-10-03, community sources only as corroboration, and every
> compatibility claim measured on the laptop against both images (local-first canon). Nothing in the repo
> or on the box was changed by this evaluation.

## 1 · Sources, authority and what each verified (accessed 2026-10-03)

| Source | Authority | Verified there |
|---|---|---|
| [Release notes](https://github.com/NousResearch/hermes-agent/releases) | primary | Latest release v0.21.5 (`v2026.9.24`, 2026-09-24). v0.21.0 (`v2026.8.31`, "Pantheon"): no breaking changes, migrations or deprecations listed ([notes](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31)). v0.21.2: state database fixes (concurrent writers cancelling each other's locks; healthy databases reported as corrupt), agent instruction files always require write approval, wider secret redaction, `.env` handling in multi-profile isolation. v0.21.3: long-lived processes no longer leak duplicate `state.db` writer handles; remote dashboard sessions stable across refresh bursts. |
| [Repository](https://github.com/nousresearch/hermes-agent) and its [security advisories](https://github.com/NousResearch/hermes-agent/security/advisories) | primary | No published GitHub security advisories. |
| [Docs: security](https://hermes-agent.nousresearch.com/docs/user-guide/security) | primary | Secrets belong in `~/.hermes/.env` (`$HERMES_HOME/.env`, `/opt/data/.env` in the image); MCP stdio servers get only a safe environment baseline plus their configured `env`; protected write paths include `.env`. |
| [Docs: MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) | primary | Config keys `command`, `args`, `env`, `timeout`, `connect_timeout`, `tools.include` / `exclude` / `resources` / `prompts`, `enabled`. |
| [Docs: configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) | primary | Precedence: CLI arguments, `config.yaml`, `.env`, defaults. `hermes config set` routes UPPER_SNAKE names to `.env`. |
| [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) | primary (experimental) | Phase 1 (skills) only; human review on every change. Not adopted. |
| CVE databases ([SentinelOne CVE-2026-14625](https://www.sentinelone.com/vulnerability-database/cve-2026-14625/), [GitLab advisories](https://advisories.gitlab.com/pypi/hermes-agent/CVE-2026-9353/), [GCVE CVE-2026-9367](https://db.gcve.eu/vuln/cve-2026-9367), [releasealert CVE-2026-14617](https://releasealert.dev/cve/CVE-2026-14617), [CVE-2026-17432](https://releasealert.dev/cve/CVE-2026-17432)) | secondary | Every hermes-agent CVE found affects versions up to 0.15.2, 0.12.0, 2026.4.x or 2026.6.5 builds, or the SimpleX adapter. None affects v0.19.0 (2026.7.20) as recorded. CVE-2026-14617 (low) was declined by the maintainers. **No CVE forces the upgrade.** |
| [hermes-optimization-guide](https://github.com/OnlyTerp/hermes-optimization-guide/tree/main) | community | Verified against v0.21.4; says versions below v0.21.2 should update for `state.db` safety (corroborated by the release notes above). |
| [Hermes Bible](https://www.hermesbible.com/) | unofficial index | A fan-made index of the official docs; no deployment or security content. Not used for any conclusion. |
| Docker Hub `nousresearch/hermes-agent` | primary | Tag `v2026.9.24` → index digest `sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7` (multi-arch: linux/amd64 and arm64). The current pin is also an index digest. |

## 2 · Measurements (laptop, arm64, Docker 29.7.2)

| Check | v0.19.0 (current pin) | v0.21.5 | Matters because |
|---|---|---|---|
| `hermes --version` | v0.19.0 (2026.7.20) | v0.21.5 (2026.9.24) | identity |
| Runtime user | `hermes`, uid 10000 | `hermes`, uid 10000 | F7 / layout contract |
| `HERMES_HOME`, `HERMES_WRITE_SAFE_ROOT` | `/opt/data`, `/opt/data` | same | mounts unchanged |
| Entrypoint | `/init` + `main-wrapper.sh` | `entrypoint-dispatch.sh`, which `exec`s `/init` + `main-wrapper.sh` when PID 1 (always under Compose) | gateway supervision unchanged; our audit services set their own `entrypoint:` |
| s6 services | dashboard, main-hermes, user, user2 | same | dashboard unchanged |
| `printenv` in the image | present | present | D4.1 `secret_env` |
| Node | 22 | 26 | our Dockerfile installs the Claude CLI with npm |
| Our derived image (Dockerfile on the new base) | builds | builds: uid 10000, Claude CLI 2.1.288, `ads-venv OK` | the image the box runs |
| Gateway rewrite of `config.yaml` (template seeded, gateway run 75 s) | adds `_config_version`, `agent`, `display`, `plugins` (96 changed lines) | adds `_config_version` only (1 line) | D10.6 |
| Collector's `mcp_config.compare(box, repo)` after the rewrite | `equals_repo: true`, reason `-` | `equals_repo: true`, reason `-` | D10.6 pass rule |
| `hermes mcp list` without a TTY | rc 0, `ads_audit … 3 selected … enabled` | same | D10.6 listing |
| Our app MCP server (`hermes mcp test ads_audit`, bin and registry mounted as in compose) | connected, 3 tools | connected, 3 tools | chat-triggered audits |
| `docker exec … printenv OPENROUTER_API_KEY` | equals the key | equals the key | D4.1 `secret_env` |
| MCP keepalive | stdio servers pinged every 180 s | `_DEFAULT_KEEPALIVE_INTERVAL = 180`, but "stdio only opts in explicitly" | the PR #92 ping handling stays correct either way; the measured "pings every 180 s" fact no longer holds for stdio |
| Dashboard basic auth | plaintext password variable | also `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` | a hash can replace the plaintext password in the gateway `.env` (dashboard work) |
| Auxiliary models | provider `auto` | provider `auto` = inherit the main model; the auto-chain's OpenRouter fallback model defaults to a PAID model (`auxiliary.openrouter_model`, `free_only`) | cost and data routing: check `provider_routing.data_collection: deny` still applies, or pin the auxiliary model |

Logged by v0.21.5 at start and expected on the box: warnings that the Nous Portal is not configured (we use OpenRouter). The laptop-only warning about SQLite on a cross-VM filesystem (Docker Desktop bind mounts) does not apply to the Linux box.

## 3 · Not measured here (box trial)

- the amd64 image on the box, a real chat-triggered audit end to end, and the review probes (D10.1, D10.2) against the rebuilt audit images;
- whether auxiliary calls honour `provider_routing.data_collection: deny` (D10.5);
- that no `/opt/data/.env` exists on the box (Hermes would load secrets from it without them being in the container environment that D4.1 `secret_env` reads; D2.1's sweep would report it as `unlisted`).

## 4 · Decision

Upgrade the pin to `sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7` (v0.21.5) and re-run the image security audit (`SECURITY-AUDIT.md`), batched with the PR #96 pull. Then one trial collection and review #7 against checklist v1.15. If the trial finds a regression, stay on v0.19.0 and run review #7 on the current pin. Revisit the pin at the next minor release, re-reading these sources first.
