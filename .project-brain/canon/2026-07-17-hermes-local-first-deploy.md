---
type: decision
status: canon
title: "Hermes is built local-first (Docker), deployed to Hostinger — the VPS is a deploy target, not the dev workshop"
description: "Develop the Hermes runtime locally, containerized from day one for dev/prod parity; provision the Hostinger VPS early in parallel for staging deploys with dummy credentials; introduce real client credentials only after hardening + security review. The git repo is the source of truth; the VPS runs deployments and spawned projects."
tags: [hermes, deployment, docker, hostinger, vps, runtime, workflow, security]
timestamp: 2026-07-17
reviewed_at: 2026-10-27
sources:
  - .project-brain/canon/2026-07-17-ai-os-charter.md
  - .project-brain/decisions/superseded/vercel-eve-fs-architecture-adoption.md (was in decisions/active/)
  - docs/superpowers/specs/2026-07-17-domain-packs-design.md
  - "Session discussion 2026-07-17 (Claude Opus 4.8): local-first vs VPS-first for Hermes"
promoted_at: 2026-10-27
originally_promoted_at: 2026-08-05
---

# Decision — Hermes local-first, deploy to Hostinger

> **Status: canon** (first promoted 2026-08-05; re-promoted 2026-10-05 and 2026-10-27).
>
> **Reviewed 2026-10-27 (weekly review):** the principle stands: develop locally in containers, deploy to the box,
> the git repository is the source of truth. Since then the box was provisioned and runs Hermes (canon: Phase 6
> passed on the box, 2026-09-22; security review #11, 2026-10-14). Steps 1–2 below describe designing a custom
> runtime and a "discovery loader"; that framing is superseded by the adoption of the Nous Hermes Agent and the
> memory corrections D-1 and D-2. Step 4 happened once (a real write credential was installed on the box on
> 2026-09-25 after an audit) and was reversed by D3.2 (canon, 2026-09-29): Hermes now holds no write credential for
> the Google Ads accounts, and any future write role needs a dedicated STANDARD account and a new security review.
> The Eve decision named in the sources is superseded (kept as a design influence, D-2).

## Decision
Build the Hermes runtime **locally, containerized (Docker/compose) from day one**. Treat the Hostinger
VPS (Ubuntu/Docker) as a **deploy target, not the development workshop**. Provision and harden the VPS
**early, in parallel**, and run continuous **staging deploys with dummy credentials**. Introduce real,
money-spending / client-facing credentials on the VPS **only after** the credential vault and HITL loop
are hardened and security-reviewed.

## Why
- **Iteration speed:** a runtime (vault, HITL pause/resume, discovery loader, tool execution, staging
  enforcement) is heavy trial-and-error; the local loop is minutes vs. an SSH round-trip.
- **Dev/prod parity for free:** developing in Docker makes "deploy" = "run the same containers on the
  VPS," which neutralizes the main reason to start on the server (parity / "works on my machine").
- **Repo is the source of truth:** the project is filesystem-as-registry + git; `install.sh` already
  embodies the factory-here / deploy-there model. VPS = where Hermes runs deployments and spawned projects.
- **Security (weighted heavily):** Hermes holds live credentials for money-spending, client-facing
  systems (Google Ads, Meta, WordPress). A half-built, secret-holding runtime must not sit on an
  internet-exposed box. Harden locally with dummy creds; deploy a known-good artifact to a secured host.

## Consequences / path
1. Design Hermes (spec) — discovery loader, credential vault, HITL loop, staging enforcement, budget-cap
   checks, pack mounting.
2. Build locally in Docker against the proven declarative pack contract.
3. Provision + harden the VPS in parallel (non-root deploy user, firewall, SSH-keys-only, fail2ban);
   wire staging deploys with dummy credentials.
4. Harden vault/HITL, security-review, then introduce real credentials on the VPS.
5. Cut over; "spawn new project" = `install.sh` + Hermes registration on the box.

## Alternative rejected
**VPS-first (develop on Hostinger).** Rejected: trades the fast local feedback loop and a safe place to
get credential handling right for a parity benefit that containers already provide, while widening the
security exposure window.
