---
type: decision
title: Credential governance — three rules earned from the mutation tier
description: Durable rules for any project that holds credentials to a client's external system, each derived from a measured failure during the first mutation-capable increment. Carry into the project replacing the current Ads integration.
tags: [credentials, security, governance, hermes, architecture, lessons]
timestamp: 2026-08-17T00:00:00
sources: [.superpowers/sdd/2026-08-12-hermes-mutation-tier/progress.md, decisions/candidates/2026-08-16-hermes-credential-locus-vs-project-autonomy.md]
status: canon
promoted_at: 2026-08-17
---

Three rules, each paid for by a real failure during the mutation-tier increment. They are
about **credentials to a client's external system**, so they outlive whichever project
holds them and apply directly to the system replacing the current Ads integration.

## 1. A separate account is not a separate OAuth client — and the difference decides whether you can ever revoke cleanly

A dedicated read-only *user* was created and its credential minted, which correctly
restored the read-only guarantee. But it was minted through the **same OAuth client** as
the write credential and the project's own full-access credential.

Consequence: OAuth revocation is per *(user, client)* pair. With one shared client, killing
a stray grant meant killing every grant that user held for that app — collateral, not
surgery. The stray token in this case was only removable because its value happened to be
recoverable; had it not been, the choice was "break working credentials" or "leave it live".

**Rule:** each credential-holding component gets its **own OAuth client**, not merely its
own account. Provision revocability at design time; you cannot add it during an incident.

## 2. Guard at the executing script, not only at the governed rail

The mutation rail was built carefully: per-action human approval bound to bytes by sha256,
a dry run, a typed one-entry allow-list, four caps, a kill switch, an exact undo, and a
separate credential injected per invocation. All of it verified live.

Beside it sat four scripts in the same project that mutated the same client accounts using
an in-tree full-access credential, with **no** approval, caps, kill switch, audit log, or
undo — and defaulting to the *live* client rather than the dormant pilot one. The rail's
guarantees were true and also nearly irrelevant, because nothing forced traffic through it.

**Rule:** a guardrail secures a path, never a capability. Enumerate every path that can
reach the external system and close or guard each one. The measure of a safety model is its
weakest reachable path, not its best-designed one.

## 3. Measure exposure before choosing a remediation — the cheapest fix may exist only if the credential leaked

A stray admin-capable token was believed unexposed, since it was in no file and no git
history. On that assumption the only remedy was the blunt one, and it was nearly deferred
indefinitely as too disruptive.

Scanning session transcripts found the value in one of them. That made the token *more*
dangerous than assumed — and simultaneously made the fix trivial: with a value in hand,
revocation became surgical, with zero collateral. The same scan also proved both live
credentials clean, which no amount of reasoning would have established.

**Rule:** before deciding how to remediate, **measure** where the secret actually is. And
never print a credential in an assistant session — transcripts persist, sync, and get
backed up long after the terminal closes.

## Corollaries worth keeping

- **Prove death, never infer it.** A revoke endpoint returning HTTP 200 means "request
  accepted". Confirm by attempting to *use* the credential and observing the refusal.
- **Fingerprint with one convention.** `grep | cut | shasum` includes a trailing newline;
  `printf '%s' | shasum` does not. The same secret hashes two ways, and that discrepancy
  has twice read as a security incident when it was a measurement artifact. This capsule
  uses the bare form.
- **Revocation is reversible; exposure is not.** Revoking a refresh token removes no
  account permissions — a new one can always be minted. That asymmetry should bias toward
  acting.
