---
type: decision
title: Where credentials live — Hermes as credential holder vs. projects executing their own function
description: The charter says projects perform their full function; the shipped mutation tier has Hermes hold client credentials and invoke project scripts directly. Records the tension, why v1 chose the current shape, what the alternative would require, and the ungoverned mutation path that exists today either way.
tags: [hermes, architecture, credentials, mutation-tier, blast-radius, governance]
timestamp: 2026-08-16T21:00:00
sources: [docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md, canon/2026-07-17-ai-os-charter.md, canon/2026-08-05-p6-ads-audit-pilot-validated.md]
status: candidate
---

## The question

Raised by the operator, 2026-08-16: if Hermes is a control plane that asks registered
projects to perform actions and report results, **why does Hermes hold Google Ads
credentials at all**, and why was a dedicated read-only Google Ads user necessary?

The operator's model: Hermes asks `claude-google-ads` to audit an account; the project
audits and reports; Hermes asks it to apply changes; the project decides what it can
apply, applies it, and reports results. Under that model the project holds its own
credential and Hermes holds none.

## What is actually implemented (as of the mutation-tier increment)

`claude-google-ads` is **not** an agent receiving requests. It is a library of scripts
that Hermes executes directly via `docker compose exec`, with a credential Hermes
supplies per-invocation. There is no Claude Code session inside that project performing
the work. The registry does define an agentic `scope: read` mode (`claude -p`), but the
Ads work uses the mechanical `read_execute` / `mutate_execute` tiers instead.

**Spec §4.2 justifies siting the mutator in the ads repo as "the project performs its own
function." It does not.** The file lives there; the execution, the credential, the
approval binding, the caps, and the kill switch are all Hermes's. That is target-model
conformance in filesystem layout only, and the tension should be recorded rather than
papered over.

## Why v1 is shaped this way (the load-bearing reasons)

1. **The injected credential exists to OVERRIDE the project's own.** `claude-google-ads`
   already holds an in-tree `.env` with a **full-access** token, and 14 of its scripts
   call `load_dotenv()`. Because `load_dotenv()` does not overwrite already-set
   environment variables, Hermes's injected value wins. All credential scoping —
   read-only for reads, narrow write for mutations — is enforceable *only because Hermes
   supplies the credential*. If the project used its own, the guardrails would be
   advisory.
2. **No model in the mutation path (spec §3).** "In v1 no model output can become a
   mutation, even in principle." The operator's step 3 — the project *determines which
   changes can be applied* — is a model deciding mutations, which v1 explicitly rules
   out. Note the read pipeline already honours this: the analyst is a read-only `claude`
   that reads collected data and holds no credential.
3. **Approval binds bytes.** The sha256 is taken over the change-set file in Hermes's
   vault. If the project decided what to execute, the human's approval would not bind
   what actually ran.
4. **`:ro` mounts.** Hermes cannot hand a project a credential file at runtime without
   writing to its tree.

## Why a dedicated read-only user was necessary

It was the layer **beneath** the code guards: even with every allow-list, cap, and
approval check failed, Google refuses the mutate server-side. That is what made every
read-only claim true rather than merely asserted.

It is not theoretical. Credential **drift** was found during the mutation-tier gate:
`.env.ga` had at some point been re-minted from an admin-capable account, so the backstop
was absent for an unknown period while every document asserted it was present. Nobody
noticed until the gate's positive control failed in the dangerous direction. Creating a
genuine read-only *service* user (distinct from the two client-owned logins on the MCC)
restored it.

## The real argument for the operator's model

**Hermes is currently a single point of credential aggregation.** It holds credentials
for every registered client. Compromise Hermes and the blast radius is every client
account. Per-project scoped credentials would reduce that to one client per compromise.
That is a genuine security improvement and the strongest case for the alternative.

## What the alternative would require

- A scoped credential store **per project**, not one — N read-only users and N write
  users, each provisioned and rotated.
- The governance rail (approval binding, caps, kill switch, allow-list, audit log)
  either duplicated per project, or replaced by the project **verifying a signed
  approval** issued by Hermes.
- A decision on whether "determine which changes can be applied" is model judgment
  (which v1 forbids) or a typed, mechanical filter.
- Rotation and revocation become an N-place problem instead of a 1-place problem —
  a cost, and the direction that argues *for* the current design.

## Recorded finding: an ungoverned mutation path exists today, under EITHER architecture

Measured 2026-08-16. Four scripts in `claude-google-ads` mutate and call `load_dotenv()`:
`add_campaign_negative.py`, `add_competitor_negatives.py`, `apply_negatives.py`,
`attach_audience.py`. Run directly, they use the in-tree **full-access** token and are
subject to **no** approval, caps, kill switch, allow-list, audit log, or undo — none of
the mutation tier's guarantees apply, because none of them are in that path.

**That project's own `.env` targets the LIVE client account, not the dormant pilot one.**
So "make a change" performed through the project's own tooling lands on the live account
by default.

This is not a defect introduced by the mutation tier; it predates it. But it means the
tier's safety model governs one path while a wider, older, unguarded path sits beside it.
Revoking the in-tree full-access token would close it, at the cost of manual/standalone
use of that repo's scripts. Nothing in the Hermes pipeline depends on that token —
`run-ads-report.sh`, `run-ads-mutate.sh`, and `collect-audit-data.sh` all inject
credentials that win over `load_dotenv()`.

## Recommended direction (operator framing, 2026-08-16)

The operator's sharper framing: Hermes should communicate intent to projects, let them
operate at full capacity, and then display and analyse the results — which also scales as
more projects are registered. **The answer differs by direction, and that split is the
core of this decision.**

### Measured capability loss (reads)

12 of 20 scripts in `claude-google-ads` are unreachable by Hermes, and **8 of those are
analysis, not mutation**: `find_negatives`, `negatives_coverage`, `simulate_negatives`,
`rsa_rubric_check`, `audit_assets_rsa`, `assess_supplemental`, `build_dashboard_data`,
`discover_accounts`.

For reads this restriction buys **no safety** — a read-only credential already bounds the
worst case to "produces a bad report", which is the failure mode a human reviewer is best
at catching. Allow-listing 4 of 12 readers is not a guardrail; it is an artefact of what
was wired up first, and it is costing real capability.

### Why writes are not symmetric

The mutation tier's entire claim is: *a human approved these exact bytes, and a
deliberately dumb program executed exactly those bytes.* The hash binding, the caps, and
the exact undo by resource name all follow from that. If a project "operates at full
capacity" and decides what to apply, a model decides what changes a client's live account
and the approval no longer binds what ran. That is the load-bearing property, not a detail.

### The decisive observation

**Half of the proposed architecture is already in production, ungoverned.** The four
`load_dotenv()` mutators ARE "the project operating at full capacity with its own
credential" — and they are unguarded and default to the live client account. The question
is therefore not whether to adopt this model, but what would make the half that already
exists safe.

### Caveat on "more reliable"

More **comprehensive** — demonstrably. More **reliable** — not automatically. Counter-
evidence from this increment: `account_overview` broke on an API version change and
printed "(none)" rather than failing. A mechanical rail surfaces that as a visibly wrong
report; a full-capacity agent is likelier to route around it and return a plausible,
confident, incomplete audit. Capability and predictability trade off; adopting the former
requires stronger output verification to hold the latter.

### What the scaling argument actually implies

The problem that does not scale is that **Hermes knows each project's internals** — script
names, runner path, cap values, credential shape — regardless of who holds the credential.
The fix is to **standardise the contract**: projects declare what they can do and what they
need; Hermes issues a scoped, short-lived credential plus a signed authorisation; the
project executes and returns structured results. Registering project eleven then means
adding a manifest, not extending an allow-list inside Hermes.

### Sequenced recommendation

1. **Open the read path.** Low risk, high value, and the argument for it is unanswerable.
   Reads move toward the operator's model now.
2. **Close the ungoverned write path.** ✅ **DONE 2026-08-17** — and closed at the
   *scripts* rather than at the credential, which turned out to be the better lever.

   Revoking the shared OAuth grant was rejected once measured: the admin account has
   other consumers, and revocation is per *(user, client)* pair, so it would have been
   collateral rather than surgical. It was also unnecessary for protecting `.env.ga` —
   that is a **different Google user** (`hermes@…`), so it survives an admin-side
   revocation regardless. Note for the record: `hermes@` is a separate *account* but
   **not** a separate OAuth *client* — all three credential files share one client id and
   secret.

   Instead the four mutators (`add_campaign_negative`, `add_competitor_negatives`,
   `apply_negatives`, `attach_audience`) now route through a new
   `code/injected_credentials.py`: no `.env` is read, the complete credential set must be
   injected or the script refuses with exit 2 before touching the network,
   `login_customer_id` is refuse-then-strip, and the API surface is pinned. Verified with
   a complete `.env` present in the working directory — all four refuse.

   This was safe to do because a search with a positive control confirmed **no automated
   consumer** existed for any of them: every reference was a test asserting they must be
   refused, documentation naming them as excluded, a historical analysis artifact, or the
   change-set *action-type string* (not the script). Manual execution only.

   The orphaned admin-capable refresh token is **✅ REVOKED (2026-08-17)**, and how that
   was reached is the transferable part. Publishing status is "In production", so it would
   never have expired. It was assumed nobody possessed its value — until 262 session
   transcripts were scanned, which found it in one of them. **The exposure that made it
   dangerous is what made it cheaply fixable**: with the value recoverable, revocation
   became surgical (one token, by value) instead of collateral (the whole user-to-app
   grant). Death was proven by an attempted refresh grant returning `invalid_grant`, not
   inferred from the revoke endpoint's HTTP 200. Both live credentials were verified
   unaffected, and both were confirmed absent from every transcript.

   Lesson worth carrying into the replacement project: **scan for exposure before choosing
   a remediation**, because the cheapest fix may only exist if the credential leaked.
3. **Keep writes typed and approval-bound** until a project can verify a signed
   authorisation issued by Hermes. At that point "full capacity" becomes safe for writes
   too, rather than merely faster.

Do not re-architect now: the mutation tier is at a verified resting point. Step 2 is a live
exposure and should be resolved sooner than the rest; steps 1 and 3 are the next
increment's scoping decision.
