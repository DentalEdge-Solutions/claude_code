# Hermes ads-analyst — Google Ads audit pilot (P6 monetization pilot) — Design Spec

> **Status:** DRAFT for review. Implements P6 (monetization pilot) from the roadmap
> `docs/superpowers/plans/steady-discovering-hartmanis.md`, pulled AHEAD of P4 (VPS)
> by decision (validate value before scaling infrastructure — charter principle
> "measure before scaling"). Builds directly on Increment 3 (read-execute). No
> implementation begins until this spec is reviewed.

## 0. One-paragraph summary

Prove Hermes can produce a **client-grade Google Ads audit deliverable** — an
executive summary + top-5 prioritized actions + a "do NOT change yet" section,
backed by an evidence appendix — for a dental practice's account, entirely
**read-only**, via a **repeatable pipeline**. The pipeline is: Increment-3
read-execute readers (broadened allow-list) produce raw, credential-scrubbed
reports → a single hand-authored **`ads-analyst`** skill synthesizes them into
the deliverable (read-only `claude -p`) → the output is a **draft for human
review**, never auto-sent. This validates a **fixed-fee one-off audit** as a
monetizable product (canon D-5) against the bar set by the existing hand-made
Palmetto Dental Studio audit — with no VPS and no account mutation.

## 1. Goal & non-goals

**Goal.** A repeatable, read-only pipeline that produces one client-grade audit
draft for `claude_google_ads` (the DentalEdge/Palmetto account), good enough that
a human operator would refine and send it — validating the audit as a product.

**Non-goals (this pilot):**
- **No mutation.** The ad account is never changed; mutator scripts stay off the
  allow-list. "Apply the changes" is a later, separately-gated capability.
- **No auto-send.** Output is a draft; a human validates before any client use.
- **No VPS / no automation.** On-demand, local. Recurring delivery is P4+.
- **No multi-agent team.** A single `ads-analyst` skill; the specialist-team
  version (Inc-1 pattern) is the documented scale-up, not this pilot.
- **No in-container writes to the client tree.** Fresh `audit_data/` is produced by
  a HOST-side read-only collection step (§5.1) so Hermes itself stays `:ro`.
  Collection is IN scope (added by decision) but never mutates the account (SELECT-only).
- **No changes to the `claude-google-ads` repo.** All Hermes artifacts are
  Hermes-side; collection *invokes* the project's own collector, unmodified.

## 2. Decisions locked (this session)

1. **Revenue path:** fixed-fee one-off, read-only audit; repeatable pipeline is
   the product; foot-in-the-door for a later retainer/managed tier.
2. **Synthesis architecture:** a single `ads-analyst` skill (not a team).
3. **Deliverable scope:** executive summary + top-5 prioritized actions + "do NOT
   change yet", with the raw reports attached as an evidence appendix.

## 3. Context — reader taxonomy, `audit_data/`, and the quality bar

**The deliverables already exist** as bespoke one-offs for Palmetto Dental Studio
(e.g. `google-ads-executive-summary.md`: *overall condition → largest wasted spend
→ growth opportunity → most urgent tracking problem → top-5 actions → what NOT to
change yet*; plus a ~37 KB full audit, negative-keyword and RSA/asset audits). They
set the quality bar. The product is the pipeline that reproduces them cheaply.

**Two kinds of reader (critical):**
- **API readers** (need the read-only credential): `account_overview`,
  `negatives_audit` ("SELECT statements only"). Live snapshots.
- **Local-analysis readers** (NO API, NO credential): `audit_search_terms`,
  `audit_analyze`, `negatives_coverage` — "pure local computation over
  `audit_data/*.json`." They read pre-collected data from the `:ro` mount.

**`audit_data/` freshness — solved by a host-side collection step (§5.1).** The
local-analysis readers reflect whenever `audit_data/` was last collected, and the
`:ro` mount means Hermes cannot (and must not) refresh it in-container. So the
pilot begins with a **host-side, read-only collection step** that runs the ads
project's own collector (`audit_discovery.py` — "SELECT queries only… writes raw
JSON to `audit_data/`") under the **read-only credential**, refreshing `audit_data/`
in the project tree; the `:ro` bind mount then reflects the fresh data. Hermes
stays 100% `:ro`; the account is never mutated (SELECT-only + read-only cred). The
deliverable still discloses the collection date as provenance.

**SOP grounding.** The analyst cites the project's own SOP/benchmark docs (all in
the `:ro` mount): `dental-benchmarks.md`, `dental-sefl-blueprint.md`,
`ad-assets-best-practices.md`, `anatomy-of-a-good-ad.md`, and the universal-negative
principles the existing audit references — so recommendations are grounded, not invented.

## 4. Architecture — read-only pipeline

```
collect-audit-data.sh (HOST, read-only cred)           [step 0 — refresh audit_data/]
   └─ ads project's own audit_discovery.py (SELECT-only) → writes host audit_data/*.json
        (the :ro bind mount then reflects the fresh data; Hermes never writes it)

run-audit-bundle.sh (host)                              [thin loop over Inc-3 wrapper]
   ├─ API readers      → run-ads-report.sh (read-only cred) → /opt/data/reports/…  (scrubbed)
   └─ local readers    → run-ads-report.sh (cred harmless)  → /opt/data/reports/…  (over :ro audit_data/)
        → ads-analyst skill  (claude -p, --permission-mode plan, Read/Grep/Glob ONLY)
             reads: the scrubbed reports + the SOP/benchmark docs (:ro)
             writes: /opt/data/audits/claude_google_ads/<ts>-audit.md
                     — exec summary + top-5 + do-not-change-yet + evidence appendix
                     — DRAFT-FOR-REVIEW banner + data-provenance line
        → HUMAN REVIEW gate (operator validates against the raw reports)
```

The analyst is **read-only synthesis**: `claude -p` with `Read/Grep/Glob`, no
Bash, no writes to the account, and it **never sees credentials** (reports are
already scrubbed by Inc-3, and the SOP docs carry none).

## 5. Components

### 5.1 Host-side collection (read-only) — `collect-audit-data.sh`
A host script (NOT run in-container, because it must write the project tree) that:
- Parses `.env.ga` for the **read-only** credential (same file/pattern as
  `run-ads-report.sh`; never sourced — parsed, like the Inc-3 minor fix).
- Runs the ads project's own collector `audit_discovery.py` (and any sibling
  collector the Task-1 gate shows is needed) via the **project's host `.venv`**
  (`<project-dir>/.venv/bin/python`), with the read-only credentials injected so
  collection is provably read-only (SELECT-only; the read-only user cannot mutate).
- Refreshes `<project-dir>/audit_data/*.json` on the host; the `:ro` mount reflects it.
- Prints the collection timestamp (used as the deliverable's data provenance).
The host project dir is resolved from the compose mount source (or an explicit
`--project-dir` / env). Hermes proper is untouched and stays `:ro`. This script
*invokes* the project's unmodified collector — it does not reimplement collection.

### 5.2 Broaden the `read_execute` allow-list (the "3b follow-on")
Add the audit readers to `registry/projects.yaml` `read_execute.allow`, readers
only, mutators still absent: `account_overview` (present), `audit_search_terms`,
`audit_analyze`, `negatives_audit`, `negatives_coverage`. The exact final set is
confirmed by the Task-1 gate (each must run standalone and produce usable output).

### 5.3 Bundle runner — `run-audit-bundle.sh`
A thin host script that runs each allow-listed reader via the Inc-3 wrapper
(`run-ads-report.sh`) and collects the report paths, so a full report set is
produced in one command. No new execution capability — it loops the proven Inc-3
path. Reuses Inc-3's credential injection (harmless for local-analysis readers).

### 5.4 The `ads-analyst` skill
Hand-authored domain-specialist skill at
`infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md`, mounted `:ro` like
the other Hermes skills. It:
- Reads the scrubbed reports under `/opt/data/reports/claude_google_ads/` + the SOP
  docs in the project mount (Read/Grep/Glob only).
- Produces the deliverable in the **structure defined in §8**,
  grounding every claim in the report numbers and citing the SOP where relevant.
- Is strictly READ-ONLY: refuses to run scripts, take Bash, or propose *applying*
  changes; recommendations are advisory, and the "do NOT change yet" section is
  mandatory.
- Emits a DRAFT-FOR-REVIEW banner and a data-provenance line (report dates +
  `audit_data/` collection date).

### 5.5 Output
Deliverable persisted to `/opt/data/audits/claude_google_ads/<UTC-ts>-audit.md`
(new `audits/` tree under the writable state volume; never the `:ro` mount).

## 6. Safety model (inherits Inc-3; adds a human gate)

- **Read-only credential** — mutation impossible server-side (Inc-3 gate proved it).
- **Allow-list, readers only** — mutators never listed; fail-closed (Inc-3).
- **Analyst is read-only claude** — Read/Grep/Glob, no Bash, no account writes.
- **Credentials never reach the analyst** — it reads Inc-3-scrubbed reports.
- **`:ro` mount** — nothing under the project is written; outputs go to `/opt/data`.
- **Human-review gate (new)** — the deliverable is a DRAFT; an operator validates
  it against the raw reports before any client use. An LLM audit with a wrong
  number could harm a real client relationship, so this gate is part of the
  product, not optional.

## 7. Task-1 verification gate (controller-run, before building the analyst)

Mirrors the Inc-3 discipline — verify the premise before building:
- **G1 — collection runs read-only and refreshes `audit_data/`.** `audit_discovery.py`
  (+ any needed sibling) runs on the host under the read-only credential, completes
  via SELECT-only, and writes fresh `audit_data/*.json`; confirm no mutate is
  attempted/possible (read-only cred backstops it). Record which collector(s) are
  needed to produce the inputs the chosen local readers consume.
- **G2 — reader taxonomy confirmed.** Each candidate reader runs standalone under
  `/opt/ads-venv` via the wrapper; record which need the API (credential) vs. which
  are local over the freshly-collected `audit_data/`. Finalize the allow-list to
  those that produce usable output.
- **G3 — local readers consume the fresh data.** After collection, the local-analysis
  readers produce non-empty output reflecting the new collection date.
- **G4 — API readers under the read-only credential** produce real snapshots (reads only).
- **G5 — confinement holds.** `git status --porcelain` on the target is byte-identical
  before/after the *Hermes* steps (collection legitimately changes `audit_data/` on the
  host — assert that is the ONLY change, and that the bundle/analyst change nothing);
  credential scan of the reports + deliverable clean (Inc-3 guarantees).

Only a clean gate authorizes building the bundle runner + analyst.

## 8. Deliverable specification (the output contract)

The audit draft MUST contain, in this order:
1. **DRAFT-FOR-REVIEW banner** + **data-provenance line** (report timestamps +
   `audit_data/` collection date; account name).
2. **Overall account condition** (1 paragraph, grounded).
3. **Largest source of wasted spend** (with the numbers + the evidence report).
4. **Largest growth opportunity.**
5. **Most urgent tracking/configuration problem.**
6. **Top-5 recommended actions** — prioritized, each with rationale + the report
   evidence + the SOP principle it follows; advisory only.
7. **Changes that should NOT be made yet** (mandatory — guards against premature action).
8. **Evidence appendix** — the raw reports (or references to their paths).

## 9. Success criteria / benchmark

- The draft is produced end-to-end by the pipeline (bundle → analyst → file),
  read-only, with the target account and repo provably untouched.
- **Benchmark:** on the four judgments it makes (condition, wasted spend, growth,
  tracking problem), the draft **matches or defensibly approaches** the existing
  hand-made Palmetto exec summary over the same account — assessed by the operator.
  Divergences must be *defensible from the data*, not errors.
- Every quantitative claim is traceable to a report in the appendix (no invented
  numbers) — the human-review gate spot-checks this.
- Outcome (validated / needs-work + what) is captured as a brain decision candidate.

## 10. Governance

The `ads-analyst` skill is **internally authored** (not sourced from a reference
repo), so the scout→audit→adapt hard rule does not apply; but it SHOULD get a
`skill-eval` pass for trigger/fit hygiene before it is considered production. The
pilot's real gate is deliverable quality vs. the bar (§9). The pilot outcome and
the go/no-go on the fixed-fee-audit product are captured via `brain-capture` →
candidate (promotable to canon only via `brain-promote --approve`).

## 11. Scope boundary & follow-ons

- **This pilot:** host-side read-only collection step + allow-list broadening +
  bundle runner + `ads-analyst` skill + one Palmetto audit draft + human-review
  gate + benchmark.
- **Follow-ons (not now):** the multi-specialist team (Inc-1 pattern); a polished
  client-facing render (HTML/Artifact); recurring/automated collection+delivery
  (needs P4/VPS); the managed/mutation tier (separately gated).

## 12. Global constraints (bind every task)

- Read-only end-to-end: read-only credential is the backstop; allow-list readers
  only; analyst is read-only `claude`; **collection is SELECT-only under the
  read-only credential**; the ad account is never mutated at any stage.
- No changes to the `claude-google-ads` repo (collection invokes its *unmodified*
  collector). Hermes never writes the client tree — the only host-side write is
  `audit_data/` by the project's own collector, run on the host, not in-container;
  the `:ro` mount is never written; Hermes outputs go only under `/opt/data`.
- Credentials never in the analyst's inputs, logs, the deliverable, memory, or
  telemetry (Inc-3 scrub + the analyst reads scrubbed reports only).
- The deliverable is a DRAFT with a review gate; never represented as final or
  auto-sent; data provenance/date always disclosed.
- Delivered via subagent-driven-development: Task-1 gate first (controller-run),
  then the build tasks, then a final whole-branch review.
