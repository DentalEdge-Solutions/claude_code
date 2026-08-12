# Mutation Tier — Design Spec

> **Date:** 2026-08-12 · **Increment:** Task 2 (highest-risk; separately gated)
> **Status:** design (awaiting plan) · **Method:** brainstorming → spec → writing-plans → SDD
> **Client-agnostic by rule:** this file is committed to the org repo, so it contains **no client
> names, no account IDs, no campaign IDs, no client business data**. Real identities live only in the
> gitignored client registry on the Hermes volume (two-tier design §2).

## 1 · Problem & goal

Everything shipped so far is read-only by design. The platform-level backstop is a **read-only Google
Ads credential**: any mutate call, however triggered, is refused server-side by Google (Inc-3 proved
this live — a `validate_only` mutate returned `authorization_error: ACTION_NOT_PERMITTED`, with a
plain read succeeding first as a positive control).

Target-model requirement #2 is that each project performs its **full** function, including applying
approved changes to the client's **external** system. For `claude_google_ads` that means mutating the
client's Google Ads account. This mutates the external account, **not** the project's own code, so it
does not conflict with requirement #1 (`:ro` project mounts) — different layers.

Delivering it means **removing the read-only-credential backstop** for one narrow path. Therefore:

> **The guardrails are the safety model.** There is no longer a platform-level layer underneath them.

**Goal of this increment:** one typed, human-approved, reversible, capped mutation path — add a
campaign-level negative keyword — proven end-to-end on a real but **paused** account, with the
account left byte-identical afterwards.

## 2 · Scope

**In scope:** a `mutate-execute` tier parallel to Inc-3's `read-execute`; a typed change-set with
operator authorship, hash-bound approval, and expiry; `validate_only` dry-run; four caps; an exact
undo path; a per-client audit log in the vault; a separate Standard-access write credential; a live
verification gate.

**Out of scope (deferred, YAGNI):** additional action types (bids, budgets, campaign status, shared
negative lists); model-authored proposals; dashboard/Kanban approval UI; ephemeral per-apply
containers; scheduled or unattended application. The typed allow-list is the seam each extends
through.

## 3 · Decisions taken in brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Gate target | A real but **paused** pilot account | Real API semantics, real structure, real error modes; a Google Ads API test account needs a separate test manager, its own refresh token, and synthetic structure, and still proves less. Campaigns are PAUSED and negatives count is 0, so a negative keyword has zero serving and zero spend impact. |
| Approval surface | Change-set file + `approve` command, hash-bound | Durable, tamper-evident, works headless, separates approval in time from execution. |
| Action scope | Campaign-level negative criterion | Narrowest blast radius; undo is exact by resource name. |
| Provenance | **Operator-authored; no model in the mutation path** | In v1 no model output can become a mutation, even in principle. |
| Mutator location | `claude-google-ads/code/` (separate repo), committed and pushed | Target-model #2: the project performs its own function. Hermes keeps the entire safety rail. |
| Caps | All four (per-change-set, per-client daily, kill switch, expiry) | The backstop is gone; layered limits replace it. |
| Rail shape | New `mutate_execute` tier parallel to `read_execute` | Keeps Inc-3's "readers only; mutators are never allow-listed" invariant literally true. |

**Recorded deviation from the Task-2 handoff.** The handoff said "prove it on a TEST / low-stakes
account FIRST (do not mutate a live client account in the gate)." The operator elected to use a real
but paused pilot account instead, for better fidelity. The deviation is made defensible by four
conditions, all binding on the gate (§8): live re-verification of PAUSED status; a synthetic,
obviously-fake keyword; undo proven in the same gate; and the client-data hard rule unchanged.

## 4 · Components

### 4.1 In `infra/hermes-agent/` (git — mechanism)

| Component | Credential | Purpose |
|---|---|---|
| `bin/changeset_lib.py` | none | Stdlib-only shared library: typed schema + validation, canonical serialization + sha256, approval records, caps accounting. The `vault_lib.py` of this increment. |
| `bin/propose-changeset.py` | none | Validates an operator-authored change-set; writes it into the client vault. |
| `bin/approve-changeset.py` | none | Writes the approval record (operator, timestamp, `expires_at`, sha256). |
| `bin/apply-changeset.py` | **write** | The only credentialed entry point. Runs all guards, `validate_only` first, then applies. Also carries `--undo`. |
| `run-ads-mutate.sh` | **write** | Host wrapper: parses gitignored `.env.gaw` as data (never sources it), injects per-invocation via `docker compose exec -e`, charset-validates args. Mirrors `run-ads-report.sh`. |
| `registry/projects.yaml` | — | New `mutate_execute` block: `runner`, `script_dir`, `allow` — exactly one entry. |

`propose` and `approve` hold no credential and cannot reach Google at all. Only `apply` can.

### 4.2 In `claude-google-ads/code/` (separate repo — execution)

`mutate_campaign_negative.py` — a deliberately dumb typed executor with two modes: `--action <json>`
adds exactly one negative campaign criterion and prints the created resource name as structured JSON;
`--undo <resource_name>` removes exactly one criterion by identity (§7.1). Both modes support
`--validate-only`. Named distinctly from the existing hardcoded
`add_campaign_negative.py`, which stays untouched and stays off every allow-list.

**No `load_dotenv()`.** Credentials come strictly from the injected environment; the script refuses if
the set is incomplete. Every other mutator in that repo calls `load_dotenv()` and would otherwise pick
up the project's in-tree **full-access** token — the exact credential this design must never use.
Inc-3 defends against this with a scratch cwd plus an all-or-nothing credential check; for a mutator
that defense becomes load-bearing, so it is also asserted inside the mutator itself.

### 4.3 Where each command runs

Following the pattern the shipped code already uses — uncredentialed vault work on the host,
credentialed work inside the container:

| Command | Runs | `VAULT_ROOT` |
|---|---|---|
| `propose-changeset.py` | host | `<here>/data/vaults` (as `run-trend-audit.sh` does) |
| `approve-changeset.py` | host | `<here>/data/vaults` |
| `apply-changeset.py` | **in-container**, via `run-ads-mutate.sh` → `docker compose exec -e … python3 /opt/cc-bin/apply-changeset.py` | `/opt/data/vaults` |

Apply runs in-container because it needs both the writable vault bind mount and the pinned
`/opt/ads-venv` interpreter — exactly the `run-ads-report.py` arrangement. `changeset_lib.py` resolves
the vault through `VAULT_ROOT` (as `vault_lib.py` does), so it is agnostic to which side it runs on.

### 4.4 Two invariants enforced in code, not comments

1. **Allow-list disjointness** — `apply-changeset.py` refuses if any script name appears in both
   `read_execute.allow` and `mutate_execute.allow`.
2. **Credential separation** — the write credential lives only in `.env.gaw`, reaches only the one
   exec'd apply process, and is never in `.env.ga`, never in `.env`, never in the gateway environment.

## 5 · Artifacts (per client, in the gitignored vault)

```
<client-slug>/
  index.md · timeline.md · audits/ · metrics/        # existing (two-tier)
  changes/
    <ts>-<changeset-id>.json            # the proposed change-set
    <ts>-<changeset-id>.approval.json   # approval: operator, ts, expires_at, sha256
    <ts>-<changeset-id>.result.json     # what actually happened, per action
    log.jsonl                           # append-only reversibility record
```

**Change-set** (operator-authored; exactly one action type in v1):

```json
{ "changeset_id": "<ts>-<rand>", "client": "<slug>", "project": "<project>",
  "customer_id": "<digits>", "created_at": "<ISO-8601>",
  "actions": [ { "type": "add_campaign_negative", "campaign_id": "<digits>",
                 "keyword": "<text>", "match_type": "EXACT|PHRASE|BROAD" } ] }
```

Validation is fail-closed on every field: `type` must be in the typed registry; `campaign_id` and
`customer_id` digits-only via `re.fullmatch` (the two-tier carry-forward correction); `match_type`
from the enum; `keyword` capped at Google's 80 characters with control characters rejected. The
keyword is free text — it is whatever the public typed into Google — so it travels as JSON to the
mutator and is **never** spliced into a shell command.

**Approval** stores sha256 over canonical JSON (sorted keys, no whitespace) of the change-set bytes,
plus operator, timestamp, and `expires_at` (+24h). Apply recomputes and compares: any edit after
approval, including whitespace, invalidates it. Approval binds the exact bytes that were reviewed.

**`log.jsonl`** is the reversibility record and the source of truth for daily caps. One line per
action, written **immediately after that action returns** — never batched. If the process dies after
action 3 of 5, resource names for 1–3 are already durable and undoable. (The vault-purge
post-destruction lesson: never let an irreversible side effect outrun its record.)

```json
{"ts":"<ISO-8601>","changeset_id":"...","action_index":0,"type":"add_campaign_negative",
 "resource_name":"customers/<cid>/campaignCriteria/<cid>~<crit>","status":"applied","operator":"<name>"}
```

`resource_name` makes undo exact rather than reconstructed: the rail removes precisely the criterion
it created, by identity, never by re-matching keyword text.

**Field provenance.** `changeset_id` is generated by `propose` (the operator never invents one).
`operator` is supplied at `approve` via `--operator`; `apply` copies it from the approval record
rather than accepting it again, so the log records who *approved*, not who ran the command. The kill
switch is created once by the operator, out of band, as a deliberate enabling act.

## 6 · Operator flow

Three separate commands, deliberately not chainable into one:

```
python3 bin/propose-changeset.py  --client <slug> --from <file>            # no credential
python3 bin/approve-changeset.py  --client <slug> --changeset <id> --operator <name>
./run-ads-mutate.sh --client <slug> --changeset <id>                       # write credential
./run-ads-mutate.sh --client <slug> --undo <id>
```

Apply also appends one line to `timeline.md`, which the ads-analyst reads first for orientation. The
next trend audit therefore **sees** that a change was applied and can attribute movement to it —
closing requirement 3 into 4.1 using the loop already shipped and proven, with no new machinery.

## 7 · Guards, ordering, and failure semantics

**Enforcement order at apply** — cheapest and safest checks first; the credential is touched last, so
every refusal happens before Google is reachable:

1. Kill switch `/opt/data/vaults/_governance/mutation-enabled` present and readable — else refuse
2. Slug validated and resolved via `vault_lib`; client status must be `active`
3. Change-set loads, schema-validates, ≤ 10 actions
4. `changeset.client` == `--client` **and** `changeset.customer_id` == the resolved customer id
   (cross-client bleed guard, mirroring two-tier §7)
5. Approval exists, hash matches, not expired
6. Daily caps satisfied, counted from `log.jsonl`: ≤ 3 applies and ≤ 25 actions per client per UTC day
7. Mutator resolves in `mutate_execute.allow`; allow-lists disjoint
8. All write-credential vars present — else refuse, so nothing falls through to the in-tree `.env`
9. **`validate_only` pass over every action.** Any failure aborts the entire change-set, nothing applied
10. Live apply, action by action, each logged immediately
11. Write `result.json`, append `timeline.md`

Step 9 is all-or-nothing: a change-set is validated as a unit before any part of it executes.

**Exit codes** (reusing the reviewed vault-purge convention):

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | usage error |
| 2 | pre-flight refusal — **guaranteed nothing was mutated** |
| 3 | failure *after* at least one live mutation — partial state; the audit log holds what landed; undo available |

The 2-versus-3 split is the point: exit 2 is a promise about the world, not merely about the process.

### 7.1 Undo

Undo is **not** a new action type and does not widen the allow-list. The same allow-listed
`mutate_campaign_negative.py` carries a second mode, `--undo <resource_name>`, which removes one
criterion by identity. Keeping it in the one script means the allow-list stays at exactly one entry
and undo cannot exist without the add path it reverses.

Guards that **do** apply to undo: slug validation and resolution; a matching `log.jsonl` entry with
status `applied`; **`resource_name` prefix-validated against the resolved `customer_id`** (so an undo
can never reach another account); allow-list resolution; the full credential set; and `validate_only`
before the live removal. Each undo appends its own `log.jsonl` line with status `undone`.

Guards that **do not** apply: the kill switch and the daily caps. They constrain *creating* change,
never *reversing* it — a tripped kill switch that also blocked cleanup would be a guardrail that makes
a bad situation worse. Undo therefore has no pre-flight state that can refuse a cleanup the operator
needs.

## 8 · Verification gate (controller-run, live)

Binding conditions from §3 apply throughout. In order:

1. Re-read campaign status live — abort unless still PAUSED
2. Prove the read-only credential still refuses a mutate (Inc-3 positive control, preserved)
3. Prove the write refresh token is distinct from the read-only one
4. Prove the read path still cannot reach the mutator — allow-list disjointness, live
5. `validate_only` on a synthetic, obviously-fake negative keyword — succeeds where the read-only
   credential was refused
6. Apply it; verify present via a read
7. **Undo; verify absent** — the account ends as found
8. Two-tier §7 assertions: write confinement to the one vault; zero cross-client mention; credential
   scan clean; `:ro` mounts byte-identical; `git status` clean of client data in both repos

Step 5 is the moment the increment becomes real: the same call Inc-3 proved returns
`ACTION_NOT_PERMITTED` now returns a valid dry-run, because the credential changed and nothing else did.

## 9 · Testing

Stdlib-only, run directly (not auto-discovered by `run-all-tests.js`), like the other `bin/` suites.

- **`changeset_lib.test.py`** — schema rejection (unknown type, bad match type, non-digit ids, oversize
  keyword, control characters, > 10 actions); hash determinism and invalidation on any byte edit;
  expiry; caps accounting from a synthetic log; kill-switch fail-closed; allow-list disjointness.
- **`apply-changeset.test.py`** — for every pre-flight refusal, assert the mutator subprocess is
  **never spawned** (stub records invocation) — stronger than asserting an exit code; a `validate_only`
  failure produces zero live calls; per-action log writes precede the next action; post-mutation
  failure yields exit 3.
- **Undo tests** — a `resource_name` belonging to another `customer_id` is refused; undo succeeds with
  the kill switch absent and with daily caps already exhausted; an undo without a matching `applied`
  log entry is refused; a successful undo appends an `undone` line.
- **Ads-repo mutator test** — argument handling, both modes, `--validate-only` wiring, refusal on
  incomplete credentials, and absence of `load_dotenv`.
- **Live** — the §8 gate.

## 10 · Guarantees preserved (must hold at whole-branch review)

`:ro` project mounts · credentials in gitignored `.env.<x>` injected per-invocation, never the gateway
env, never source-spliced · charset-validated args passed via `docker exec -e` · no client names, IDs,
metrics, or drafts in git, the brain, specs, plans, tests, or telemetry · a human gate on anything
reaching a client system · Inc-3's read path and its read-only credential unchanged and re-proven.

## 11 · Known context carried in from the two-tier increment

- The mutator lands in a **separate repo** with 2 unpushed commits and uncommitted WIP; that repo's
  changes sit outside this branch's whole-branch review and need their own review pass.
- Pre-existing, not introduced here: a real client name appears in tracked files
  (`docs/superpowers/specs/2026-08-05-hermes-ads-analyst-pilot-design.md`, and one canon record).
  It contradicts the two-tier hard rule; the canon edit is human-gated via `brain-promote --approve`.
  Flagged for a separate remediation decision, not folded into this increment.
- `infra/hermes-agent/bin/__pycache__/` is untracked and ungitignored.
