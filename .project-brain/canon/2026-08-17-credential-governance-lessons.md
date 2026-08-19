---
type: decision
title: Credential governance — three rules earned from the mutation tier (rule 1 amended 2026-08-19)
description: Durable rules for any project that holds credentials to a client's external system, each derived from a measured failure. Rule 1 was AMENDED on 2026-08-19 after its prescription was disproven by a revocation that caused collateral damage — the original claim is preserved alongside the correction. Carry into the project replacing the current Ads integration.
tags: [credentials, security, governance, hermes, architecture, lessons]
timestamp: 2026-08-17T00:00:00
amended_at: 2026-08-19
sources: [.superpowers/sdd/2026-08-12-hermes-mutation-tier/progress.md, decisions/candidates/2026-08-16-hermes-credential-locus-vs-project-autonomy.md, lessons/memories/2026-08-19-corrects-canon-oauth-revocation-isolates-by-account-not-by-c.md]
status: canon
promoted_at: 2026-08-19
---

Three rules, each paid for by a real failure during the mutation-tier increment. They are
about **credentials to a client's external system**, so they outlive whichever project
holds them and apply directly to the system replacing the current Ads integration.

> **Rule 1 was amended on 2026-08-19.** Its original prescription — "own OAuth client, not
> merely own account" — was acted on, and then disproven by measurement. Both the original
> claim and the correction are kept below, because the way this rule was wrong is more
> instructive than the rule itself.

## 1. The isolation boundary is the ACCOUNT — a separate OAuth client is not enough

**The incident that produced the original rule (2026-08-17).** A dedicated read-only *user*
was created and its credential minted, which correctly restored the read-only guarantee. But
it was minted through the **same OAuth client** as the write credential and the project's own
full-access credential. Killing a stray grant therefore meant killing every grant that user
held for that app — collateral, not surgery. The stray token was only removable because its
value happened to be recoverable; had it not been, the choice was "break working credentials"
or "leave it live".

**What was concluded, and acted on:** *each credential-holding component gets its own OAuth
client, not merely its own account.* A separate OAuth client was duly provisioned for the
control plane, and both of its credentials re-minted against it.

**What measurement showed (2026-08-19).** Revoking a third credential — same account as the
write credential, but a **different client id** — killed the write credential too. A third
credential on the **same client id** as the casualty survived, because it belonged to a
different account. The separation that had been provisioned bought nothing; the separation
that saved the survivor was the one the original rule dismissed as "not merely".

| | account | client id | outcome |
|---|---|---|---|
| read credential | A | X | **survived** |
| write credential | B | X | revoked — collateral |
| revocation target | B | Y | revoked — intended |

**Corrected rule:** the isolation boundary is the **ACCOUNT**. Give each *role* its own
account — that is what makes revocation surgical, and it is the part that was already right.
A separate OAuth client id, on its own, provides no revocation isolation and must not be
relied on for it.

**What is NOT established.** Every client id involved sat in a single Cloud project — checkable,
since the project number is the prefix of every OAuth client id — which plausibly explains why
the platform treated them as one app boundary. It is **untested**: no credential in a different
Cloud project existed to try. Do not recommend separate Cloud projects as a mitigation until
someone measures it. Writing an untested mitigation into this rule is precisely how its first
version came to overstate its own guarantee.

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
- **Order irreversible operations so a wrong assumption costs nothing.** Added 2026-08-19,
  the same day rule 1 was amended and for the same reason: mint the replacement *before*
  revoking the old. The revocation that disproved rule 1 was performed on a pre-flight
  assertion that it could not affect a working credential — an untested hypothesis treated
  as a check. Had the replacement been minted first, being wrong would have cost nothing.
- **Fingerprint with one convention.** `grep | cut | shasum` includes a trailing newline;
  `printf '%s' | shasum` does not. The same secret hashes two ways, and that discrepancy
  has twice read as a security incident when it was a measurement artifact. This capsule
  uses the bare form.
- **Revocation is reversible; exposure is not.** Revoking a refresh token removes no
  account permissions — a new one can always be minted. That asymmetry should bias toward
  acting.
