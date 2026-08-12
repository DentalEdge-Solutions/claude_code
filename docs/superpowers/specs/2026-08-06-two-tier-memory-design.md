# Two-Tier Memory Model — Design Spec

> **Date:** 2026-08-06 · **Increment:** keystone (unblocks target-model requirements 3, 4.1, 5)
> **Status:** design (awaiting plan) · **Method:** brainstorming → spec → writing-plans → SDD
> **Client-agnostic by rule:** this file is committed to the org repo, so it contains **no client
> names, no account IDs, no client business data**. Real identities live only in the gitignored
> `clients.yaml` on the Hermes volume (see §2).

## 1 · Problem & goal

Hermes execution results must feed a "second brain" — but private/financial **client** data cannot
live in the shared, git-versioned project brain (`.project-brain/`, pushed to
`DentalEdge-Solutions/*`). We split memory into two tiers:

- **Shared project brain** (git, `canon/`/`decisions/`): **META only** — how projects operate,
  lessons, what "good" looks like. No client data, ever.
- **Per-client vaults** (Obsidian-flavored markdown, gitignored, access-controlled, **not** in the
  shared repo): that client's audits, metrics history, timeline, opportunities, profile.

This keystone increment stands up the boundary and proves it **end-to-end on two real pilot clients**
under the DentalEdge MCC, with a schema that generalizes to N clients.

**Success criterion (the loop this slice must prove):**
run audit → write to vault → a *later* run reads the client's prior audits + **structured metrics
history** → produces a **trend-aware** audit ("since last audit, CPL worsened 18%"). One pilot client
has a prior audit (a real delta is shown); the other establishes a cold-start baseline.

## 2 · The git/vault boundary (load-bearing decision)

The dividing question for anything new: *is this about how projects operate (→ git brain) or about a
specific client (→ vault)?*

- `infra/hermes-agent/registry/projects.yaml` (git, **unchanged**) stays **project-level** and
  client-agnostic.
- **New — the client registry is itself client-private, so it lives in the vault tier, not git:**
  `/opt/data/vaults/_registry/clients.yaml` (gitignored) maps
  `client-slug → { project, mcc_id, customer_id, currency, timezone, status: active|offboarded }`.
- The **code** that reads it (resolver + wrappers in `infra/hermes-agent/`, git) is meta —
  **mechanism in git, client data on the volume.**

Rationale: a roster of "who the clients are + their account IDs" is client-relationship data;
committing it to the org repo would violate the no-client-data-in-git hard rule.

## 3 · Vault layout & schema (per client)

Host `infra/hermes-agent/data/vaults/<client-slug>/` (opens in Obsidian) ↔ container
`/opt/data/vaults/<client-slug>/`:

```
<client-slug>/
  index.md              # profile: mcc/customer id, tz, currency, engagement notes
  timeline.md           # rolling one-line-per-run log (analyst reads FIRST for orientation)
  audits/<ts>-audit.md  # DRAFT deliverables (P6 8-section contract)
  metrics/<ts>.json     # DETERMINISTIC KPI snapshot per run (enables trend deltas)
  opportunities.md      # open recommendations + status, carried across runs
```

`metrics/<ts>.json` is **deterministic** (derived from structured reader/`audit_data` output, **never**
from model prose — trend deltas must be reliable):

```json
{
  "collected_at": "<ISO-8601>",
  "customer_id": "<digits>",
  "spend": 0.0, "conversions": 0.0, "cost_per_conv": 0.0,
  "ctr": 0.0, "conv_rate": 0.0, "impression_share": 0.0,
  "campaign_count": 0
}
```

Field set may extend, but every field is machine-extracted from the readers, not the analyst.

## 4 · Two-tier taxonomy (what goes where)

| Shared project brain (git, meta) | Per-client vault (`/opt/data`, gitignored) |
|---|---|
| Audit methodology, benchmark rubrics, SOP | That client's audit drafts over time |
| "What good looks like" for an ads audit | That client's metrics snapshots + deltas |
| Lessons about how the pipeline operates | Timeline / history of runs |
| Pipeline/skill/agent improvements | Open opportunities + outcomes |
| — never | Client profile, account IDs, the client roster |

## 5 · Components

### 5.1 `clients.yaml` resolver (`bin/vault-lib.py`, git)
Reads the gitignored `/opt/data/vaults/_registry/clients.yaml`; resolves `client-slug →
{customer_id, vault_path, status, ...}`. **Charset-validates** the slug (rejects `/`, `..`, quotes,
`;`, whitespace, any non-`[A-Za-z0-9_-]`) before it touches a path — the P6/Inc-3 injection lesson
applied to vault paths. Stdlib-only. Fail-closed on unknown slug.

### 5.2 `vault-write` (`bin/vault-write.py`, git)
Post-audit writer; writes **only** under `/opt/data/vaults/<slug>/`, never the `:ro` project mount.
1. Save audit draft → `audits/<ts>-audit.md`.
2. Write deterministic `metrics/<ts>.json` (extracted for that client's `customer_id`).
3. Append one line to `timeline.md`.
Path derived only via the §5.1 resolver (validated slug). Idempotent per timestamp.

### 5.3 Trend mode in `claude-code-ads-analyst` skill (git)
**Extend the existing skill** (not a second skill — keeps the 8-section contract in one place):
add a "trend mode" that, when a `VAULT_DIR` with prior `metrics/` + `audits/` is present, reads the
most-recent prior snapshot(s), computes deltas, and references change-over-time. Cold-start
(no prior snapshot) → explicitly states "establishing baseline." Read-only throughout
(plan mode, `Read,Grep,Glob`; no Bash/Write/network; no credential).

### 5.4 `run-trend-audit.sh` (host wrapper, git)
Operator entry point. `--client <slug>`:
1. Resolve client (§5.1) → `customer_id`, `vault_path`.
2. **Live re-collect** fresh data under the **read-only** cred: `CUSTOMER_ID` set per-client for the
   host-side collectors (`collect-audit-data.sh`) and injected via `docker compose exec -e` for the
   in-container readers (`run-audit-bundle.sh`) — never the gateway env → scrubbed reports
   (Inc-3/P6 pipeline).
3. Take a fresh deterministic metrics snapshot.
4. Run the analyst (`claude -p`, plan-mode, opus) pointed at **the fresh reports + `VAULT_DIR`
   (prior `audits/` + `metrics/` + `timeline.md`)**, following the §5.3 trend mode.
5. `vault-write` (§5.2) persists the new audit + snapshot.
6. Run post-run assertions (§7).
`$CLIENT` charset-validated and passed via `docker exec -e` (never source-spliced) — the P6 Critical
fix pattern.

### 5.5 `vault-purge.py` (`bin/`, git) — retention/offboarding
`--client <slug> --confirm`:
1. **Export** vault (tar to operator-specified path) — never delete without export first.
2. **Hard-delete** the vault dir + any `/opt/data/reports|audits` for that client.
3. Append deletion record `{slug, ts, operator, bytes_exported}` to
   `/opt/data/vaults/_governance/deletions.log` (gitignored).
4. Flip `clients.yaml` status → `offboarded`.
Guards: charset-validated slug; refuses an `active` client without `--force`. Time-based retention
caps are **deferred** (indefinite-while-active chosen); the export+purge+audit-log mechanism is built now.

### 5.6 Minimal `audit_data` governance fix (in `claude-google-ads` repo, this increment)
This increment actively refreshes the ads repo's **git-tracked** `audit_data/` per client, widening a
client-data-in-git hole. Close it, minimally:
- Add `audit_data/` (+ report output paths) to `claude-google-ads/.gitignore`.
- `git rm --cached` the currently-tracked files so they stop being committed.
Scope stays minimal — gitignore + untrack only, no broader cleanup. The **vault** becomes the
sanctioned durable store; the repo copy is transient working data.

## 6 · Isolation & access control (soft now, hard deferred)

- Resolve a single `VAULT_DIR=/opt/data/vaults/<client>`; the analyst is directed to read only there +
  the fresh reports.
- The analyst is already confined: plan mode, `Read,Grep,Glob`, no Bash/Write/network, no credential.
- **Hard isolation** — an ephemeral per-client container with *only* that client's vault bind-mounted
  — is **designed-for and deferred to P4/VPS**; its payoff (untrusted multi-tenant / shared host) does
  not arrive until then. Proportionate now: single-operator, loopback, local-first.

## 7 · Post-run assertions (every trend-audit run)

1. **Write confinement:** `vault-write` touched only `/opt/data/vaults/<slug>/` (no other client dir).
2. **Cross-client bleed:** no *other* client's slug appears in the produced draft.
3. **Credential scan:** zero of the six `GOOGLE_ADS_*` values in draft + reports + logs.
4. **`:ro` integrity:** project mounts byte-identical before == after (git tree hash).
5. **No client data committed:** `/opt/data` gitignored; `git status` in both repos clean of client data.

## 8 · Meta feedback seam (target-model requirement 4.2)

After runs, **only meta** flows to the git brain via existing `brain-capture` (meta-only) — lessons
about how the pipeline operates / methodology, never client data. This slice preserves the rule and
captures one meta lesson about the two-tier model itself. Full self-improvement automation is a later
increment.

## 9 · Verification gate (Task-1 style, controller-run)

- Pilot-client reachability under the read-only cred — **already proven** this session (two ads
  accounts reachable through the MCC via `discover_accounts.py`; read-only refresh token distinct from
  the project's full-access token).
- `clients.yaml` seeded (gitignored) for the two pilot clients.
- One end-to-end run per client: cold-start baseline (no prior snapshot) and a delta run (prior
  snapshot present) both produce a valid draft + snapshot; all §7 assertions pass.

## 10 · Testing

- `vault-lib` / `vault-write` / `vault-purge` unit tests (stdlib-only, like the other `bin/` suites,
  run directly — not auto-discovered by `run-all-tests.js`): slug injection/traversal rejected;
  snapshot determinism; trend-mode reads the prior snapshot; cross-client isolation assertion fails
  closed; purge exports-then-deletes and writes the audit log; refuses active client without `--force`.
- Live e2e proofs per §7 + §9.

## 11 · Explicitly deferred (YAGNI)

Encryption-at-rest; hard container isolation; cross-vault retrieval/index; SQLite/graph store;
time-based retention caps; N>2 provisioning tooling (schema already generalizes); per-client
context-pack injection (the non-chosen approach). Add only when a measurable need appears
(charter principle: measure before scaling infrastructure).

## 12 · Guarantees preserved (must hold at whole-branch review)

`:ro` project mounts; credentials in gitignored `.env.<x>` injected per-invocation (never gateway
env); read-only end-to-end (no mutation — that is Task 2, a separate increment); no
secrets/client-private data in git/brain/memory/telemetry; charset-validated args passed via
`docker exec -e` (never source-spliced); DRAFT + human-review gate on any deliverable.
