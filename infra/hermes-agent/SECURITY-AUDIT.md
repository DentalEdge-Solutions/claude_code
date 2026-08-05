# Hermes Agent — Security Audit (P0 gate record)

**Date:** 2026-07-21 · **Scope:** adopting Nous Research Hermes Agent (official Docker image) as a
control plane that runs `claude -p` in mounted project dirs — local now, hardened VPS later.
**Method:** read-only review of the upstream `Dockerfile`, `docker-compose.yml`, `docker/stage2-hook.sh`,
`install.sh`, `docs/user-guide/{docker,security,features/api-server}.md`, the bundled
`skills/autonomous-ai-agents/claude-code/SKILL.md`, `.github/workflows/docker.yml`, and Docker Hub
tag/digest data — compared against `infra/hermes-agent/`.

## Verdict: GO for local dev (with the current safe defaults)

Conditions (all already met by our config): project mount **read-only**, API server **off**, dashboard
**loopback-only** (no `network_mode: host`), **no** Docker socket mounted, image **pinned** (below).

## Findings

| Sev | Issue | Status / mitigation |
|---|---|---|
| HIGH | Bundled `claude-code` skill uses `--dangerously-skip-permissions` (auto-approves all `claude` file/bash ops; Hermes's own approval layer can't see inside the subprocess). | **Neutralized now** by the read-only mount (no write can land). Becomes live if the mount goes read-write → gated: avoid the flag, scope `--allowedTools`, or use an isolated sandbox mount. |
| HIGH | `:latest` is retagged on every push to `main` (moving target, no rollback anchor). | **Fixed** — pinned to a digest (below). |
| MED | `docker-cli` baked in + `stage2-hook.sh` adds `hermes` to the docker-socket group if the socket is present → host-root-equivalent if `/var/run/docker.sock` is ever mounted. | **Do not mount the Docker socket.** Our compose does not; keep it that way. |
| MED | Official compose uses `network_mode: host` (exposes all bound ports on the host). | Our compose avoids it (explicit `127.0.0.1:9119` bridge) — safer. |
| MED | `install.sh` fetches third-party installers (uv, Node) outside Hermes's checksum pinning. | N/A — we build FROM the published image (whose build pins base images + s6 by SHA), not `install.sh`. |
| LOW | API server one edit away from public exposure (`API_SERVER_HOST=0.0.0.0`, CORS `*` in docs). | Keep API server **off** locally; never bind non-loopback without a strong `API_SERVER_KEY` + narrow CORS + TLS. |
| LOW | Secrets stored plaintext under `/opt/data` (`.env`, `auth.json`, oauth, mcp-tokens). | `chmod 600` host-side; dedicated low-priv host UID; don't widen the container's filesystem reach. |
| INFO | Upstream image: base pinned by digest, tarballs SHA-verified, `/opt/hermes` immutable root-owned, state confined to `/opt/data`, runtime user non-root `hermes` UID 10000. | Positive — our derived `USER hermes` is correct. |

## Pinned image

```
FROM nousresearch/hermes-agent@sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a
```
= `v2026.7.20` (Hermes Agent v0.19.0 "Quicksilver", published 2026-07-20). More soak-tested alt:
`v2026.7.7.2` (v0.18.2). **Re-pin + re-run this audit on every upgrade.**

## VPS hardening checklist (P4 — before any real key / public exposure)

1. Pin base by tag **and** digest; re-verify on each rebuild.
2. **Never** mount the Docker socket.
3. **No** `network_mode: host`; explicit `127.0.0.1:PORT` + SSH/Tailscale tunnel (no public bind).
4. API server: off unless needed; if remote, mandatory `API_SERVER_KEY` (`openssl rand -hex 32`) +
   narrow CORS + TLS reverse proxy. *(Docs note an unauthenticated public dashboard/API was the entry
   point for the June 2026 attack that planted an SSH-key backdoor.)*
5. Dashboard: require an auth provider before any non-loopback bind (fails closed since June 2026);
   put behind VPN/Tailscale.
6. `claude -p` on the VPS: avoid `--dangerously-skip-permissions`; scope `--allowedTools`; write only
   to narrow, purpose-specific mounts (or an isolated sandbox backend).
7. Secrets: `chmod 600` `~/.hermes/.env`; dedicated non-priv host user; rotate keys on any exposure.
8. Keep `approvals.mode: smart` (not `off`).
9. Track `HERMES_GIT_SHA` (baked into image) for incident triage.
10. Re-run this audit on every version bump.
