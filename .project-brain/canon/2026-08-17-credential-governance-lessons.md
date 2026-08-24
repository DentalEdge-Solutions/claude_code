---
type: decision
title: Credential governance — three rules earned from the mutation tier (rule 1 amended 2026-08-19 and 2026-08-24)
description: Durable rules for any project that holds credentials to a client's external system, each derived from a measured failure. Rule 1 has been amended twice — on 2026-08-19 after its prescription was disproven by a revocation that caused collateral damage, and on 2026-08-24 after a deliberate experiment measured the Cloud-project boundary the first amendment had explicitly left untested. Every prior claim is preserved alongside its correction. Carry into the project replacing the current Ads integration.
tags: [credentials, security, governance, hermes, architecture, lessons]
timestamp: 2026-08-17T00:00:00
amended_at: 2026-08-24
sources: [.superpowers/sdd/2026-08-12-hermes-mutation-tier/progress.md, decisions/candidates/2026-08-16-hermes-credential-locus-vs-project-autonomy.md, lessons/memories/2026-08-19-corrects-canon-oauth-revocation-isolates-by-account-not-by-c.md]
status: canon
promoted_at: 2026-08-24
---

Three rules, each paid for by a real failure during the mutation-tier increment. They are
about **credentials to a client's external system**, so they outlive whichever project
holds them and apply directly to the system replacing the current Ads integration.

> **Rule 1 has been amended twice.** On **2026-08-19** its original prescription — "own OAuth
> client, not merely own account" — was acted on, and then disproven by measurement. On
> **2026-08-24** the Cloud-project boundary that the first amendment had explicitly refused to
> recommend was measured directly, and it isolated. Every version is kept below, because the
> way this rule has been wrong is more instructive than the rule itself.

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

### The Cloud-project boundary, measured 2026-08-24

The 2026-08-19 amendment ended by refusing to recommend separate Cloud projects, on the
grounds that every client id involved had sat in a single project and no credential in a
different project existed to try. That gap has now been closed by a deliberate experiment
rather than by reasoning.

**Design.** The test required no Google Ads permissions at all — revocation isolation is a
pure OAuth property — so it used a throwaway account with no client access and could not
touch production. Two new Cloud projects, one Desktop-app OAuth client in each, and two
adwords-scoped refresh tokens minted from **the same Google account**, one per client.

**Setup control.** The Cloud project number is the prefix of every OAuth client id, so the
two projects were verified distinct **mechanically rather than assumed** — the two client ids
carried different numeric prefixes, confirmed before either token was minted. (The values
themselves are not recorded here; they identify throwaway test projects and the durable fact
is that they differed.) This is the check that was available and unrun in the incident that
produced the first amendment.

**Result.** The token issued by the client in the first project was revoked and **proven dead**
by an attempted refresh grant returning `invalid_grant` — not inferred from the revoke
endpoint's HTTP 200. The token issued by the client in the second project was then probed
**after** that revocation and returned a successful refresh grant: **it survived**.

| | account | Cloud project | outcome |
|---|---|---|---|
| T1 | A | P1 | revoked — intended |
| T2 | A | P2 | **survived** |

**What this establishes:** in this measurement, the **Cloud project boundary isolated
revocation** for two clients granted by the same account. Account and project appear to be
two independent isolation axes.

**What it does NOT establish, and must not be written up as though it did:**

- It is **one** measurement — one account, two projects, one platform, one moment. Google does
  not document revocation as project-scoped, so this is observed behaviour, not a contract.
- It does **not** demote the account rule. That finding was earned by an actual credential
  loss; this one adds a second axis that appears to isolate, and replaces nothing.
- It is **not yet a recommended mitigation.** Recommending separate projects would need repeat
  measurement and ideally a statement from the platform. Writing an untested prescription into
  this rule is exactly how its first version came to overstate its own guarantee, and the
  temptation to do it again is stronger now that a result points the right way.

**Two confounds that had to be excluded, and how.** A survivor probed *before* the revocation
proves nothing about survival — the probe was run after. And an OAuth app in Testing
publishing status issues refresh tokens that expire in seven days, so a *dead* survivor would
have been ambiguous between revocation and expiry; that confound does not arise here, because
the survivor came back alive, which expiry cannot produce.

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
- **Design the experiment so it cannot touch production.** Added 2026-08-24. The
  project-boundary question had gone unanswered because the obvious way to answer it — revoke
  something real and see what dies — is how the 2026-08-19 outage happened. Asking what the
  property actually depends on showed it needed no Google Ads permissions at all, which made a
  throwaway account sufficient and the blast radius zero. When a measurement looks too
  dangerous to run, check whether you are measuring more than the question requires.
- **Control the setup, not just the result.** Added 2026-08-24. Both projects were verified
  distinct by their project numbers before minting, because the project number is the prefix
  of every OAuth client id. Had they silently shared a project, the experiment would have
  produced a confident, wrong, and unfalsifiable answer.
- **Fingerprint with one convention.** `grep | cut | shasum` includes a trailing newline;
  `printf '%s' | shasum` does not. The same secret hashes two ways, and that discrepancy
  has twice read as a security incident when it was a measurement artifact. This capsule
  uses the bare form.
- **Revocation is reversible; exposure is not.** Revoking a refresh token removes no
  account permissions — a new one can always be minted. That asymmetry should bias toward
  acting.
