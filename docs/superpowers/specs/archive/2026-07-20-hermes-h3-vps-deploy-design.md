# Hermes H3 — VPS Deploy + Real Credentials (design spec)

> **⚠ SPLIT by the definitive roadmap.** The VPS provision/deploy mechanics are the **kernel phase K3**
> (dummy creds, `ANTHROPIC_API_KEY` only); real credentials + staged rollout + the security-review gate
> are the deferred **Operate track**. See `~/.claude/plans/iterative-squishing-church.md` and
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`.

> **Date:** 2026-07-20 · **Status:** design (planning only) · **Depends on:** H1, H2 (and H0.5 for scheduled runs)
> **Master:** `specs/2026-07-20-hermes-master-architecture.md`

The final phase: take the locally-built, security-hardened Hermes and run it on the Hostinger VPS
with **real, money-spending, client-facing credentials** — but only after a security-review gate.
This is the phase the local-first decision was designed to make safe: *"a half-built, secret-holding
runtime must not sit on an internet-exposed box. Harden locally with dummy creds; deploy a
known-good artifact to a secured host"* (`decisions/candidates/2026-07-17-hermes-local-first-deploy.md`).

## Goal

1. **Provision + harden the VPS** — Ubuntu box with a non-root deploy user, SSH-keys-only, UFW
   firewall, fail2ban, unattended security upgrades, Docker.
2. **Deploy Hermes** — git pull + `docker compose build` on the box (master **D8**); the daemon runs
   as a restart-on-failure service.
3. **Provision the vault master key** out of band (never in git); real credentials are added to the
   vault on the box.
4. **Pass a security-review gate** before any real credential is introduced.
5. **First real run** — a read-only pack against a real API, then a HITL money action end to end,
   then a staging-autonomous write — each verified against the H1/H2 guarantees on the real host.

## Non-goals

New runtime features (H3 ships what H0–H2 built). Multi-VPS/HA, blue-green deploys, a public HTTP
channel (later, if a measured need appears — master D9 spirit). No production-promotion flow for
WordPress (out of scope per that pack).

## Design decisions

- **D8 Deploy:** the git repo is the source of truth. Deploy = `git pull` on the VPS + `docker
  compose build && up -d`. No registry in v1 (single box, simplest). A tagged release commit marks
  each deploy.
- **Vault key handling:** `HERMES_VAULT_KEY` is provided to the container via a **root-owned env
  file** referenced by the compose/systemd unit (`env_file`, mode `0600`), generated once and stored
  only on the box + in the operator's password manager. It is never committed and never printed to
  logs.
- **Secrets on the box:** real credentials are added with `hermes vault set` **on the VPS** (value
  read from stdin), after the security review. Local/dev keeps using dummy creds.
- **Network posture:** inbound = SSH only (key auth), via UFW; all Hermes triggering is the local
  daemon/scheduler + `hermes enqueue` over SSH. No inbound app port is opened in v1.

## Architecture / deliverables

```
deploy/
├── provision.sh          # [new] idempotent VPS hardening (run once, as root, via ssh)
├── deploy.sh             # [new] run on the box: git pull + compose build + up -d (+ health check)
├── hermes.service        # [new] systemd unit (optional; or `docker compose up -d` + restart policy)
├── env.example           # [new] documents required env (ANTHROPIC_API_KEY, HERMES_VAULT_KEY) — NO values
└── SECURITY-REVIEW.md    # [new] the gate checklist (must be signed off before real creds)
```

The runtime image and compose file already exist (H0/H0.5). H3 adds only the provisioning, deploy,
and review artifacts — no changes to the run core.

## The security-review gate (hard gate — real creds blocked until green)

A checklist that must be fully satisfied and human-signed before `hermes vault set` is run with any
real credential:

1. VPS hardened: non-root deploy user; SSH password auth disabled; root SSH disabled; UFW default-deny
   inbound except SSH; fail2ban active; unattended-upgrades enabled.
2. `HERMES_VAULT_KEY` generated with a CSPRNG, stored `0600` root-only + in a password manager; never
   in git (`git log -p | grep` clean); never in container logs.
3. `hermes/state/` (vault + db) is on the box only, backed up encrypted, never committed
   (`git check-ignore` confirms).
4. All H1/H2 guarantees pass on the box with **dummy** creds: wrong key fails closed; write-tier
   denied without approval; over-cap denied; staging-only writes; no secret in any artifact.
5. `npx ecc-agentshield` / `project-audit` run against the deployed `.claude/` config — clean (run
   only on explicit request; it may incur cost).
6. Least-privilege real credentials obtained (read-scoped where possible; Google Ads on a test/low-cap
   account first; WordPress pointed at a real staging site).
7. Rollback plan documented (previous release commit + `deploy.sh` re-run).

Only after all seven are signed does the operator add real credentials and enable the corresponding
pack tiers in `hermes.config.json` on the box.

## Rollout sequence (defense in depth, smallest blast radius first)

1. Deploy with **dummy creds**; run the full test suite on the box; verify daemon + scheduler.
2. Add **one read-only** real credential (e.g. Google Analytics); run the read-only pack; verify
   output + no secret leakage.
3. Add the **WordPress staging** binding (real staging site, real creds); run a staging-autonomous
   write; verify it hits staging and a production-target write is refused.
4. Add **Google Ads** on a **low-cap test account**; run a HITL money action end to end (propose →
   approve → execute → ledger); verify the cap denies an over-budget attempt.
5. Only then widen to real client accounts, one at a time.

## Error handling / operations

- **Failed deploy:** `deploy.sh` health-check fails → it does not switch the running service; operator
  re-runs against the previous release commit (documented rollback).
- **Daemon crash:** `restart: unless-stopped` (compose) / systemd `Restart=on-failure`; stale
  `running` rows reaped on restart (H0.5); pending approvals survive (SQLite on a mounted volume).
- **Key loss:** vault is unrecoverable by design; documented that the key must be backed up in a
  password manager; losing it means re-adding secrets.
- **Backups:** `hermes/state/` (encrypted vault + db) backed up on a schedule to encrypted storage;
  restore procedure documented.

## Security (whole-box posture)

- Attack surface: SSH-only inbound, key auth, fail2ban, UFW default-deny.
- Secrets: encrypted at rest (H1 vault); key root-only, out of band; never in git or logs; decrypted
  only into a single run's child env; scrubbed after.
- Blast radius: real money creds arrive last, on capped/test accounts first; every money action still
  passes HITL + budget cap; staging packs can't touch production.
- Auditability: every run/approval/spend is in SQLite with git SHA; the deploy is a tagged commit.

## Testing / verification strategy

H3 is mostly infrastructure, so verification is command-based rather than unit-tested:

- `provision.sh` is idempotent — running twice yields the same hardened state (verified by re-run +
  `sshd_config`/`ufw status`/`fail2ban-client status` checks).
- Post-deploy: `node scripts/run-all-tests.js` **on the box** is green with dummy creds.
- The security-review checklist is fully green and signed.
- Each rollout step (2–5) has an explicit verify command + expected observation before the next.
- A deliberate negative test on the box: attempt a production-target WordPress write and an
  over-cap Google Ads change — both must be refused.

## Definition of done (H3 = Hermes v1 complete)

- [ ] VPS hardened and idempotently reprovisionable; SSH-key-only; UFW + fail2ban + auto-upgrades on.
- [ ] Hermes deploys via `deploy.sh` (git pull + compose) and runs as a restart-on-failure daemon.
- [ ] Full test suite green on the box with dummy creds.
- [ ] Security-review checklist signed before any real credential.
- [ ] Real read-only, staging-autonomous, and HITL money paths each verified end to end on the box,
      smallest blast radius first, with the negative tests refused.
- [ ] Rollback + backup procedures documented and tested once.

## Out of scope / future (per master D9)

Retrieval upgrade (LangChain), multi-session coordination (CrewAI), a public HTTP/Slack channel,
multi-VPS/HA — all revisited only on a measured need, via `scout → audit → adapt → eval`.
