# Hermes ads-analyst — Google Ads audit pilot (P6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec authority:** `docs/superpowers/specs/2026-08-05-hermes-ads-analyst-pilot-design.md` governs. Where this plan and the spec disagree, the spec wins — stop and reconcile.

**Goal:** A repeatable, read-only pipeline that produces one client-grade Google Ads audit **draft** (exec summary + top-5 + "do NOT change yet" + evidence appendix) for `claude_google_ads`, validating the fixed-fee audit as a product.

**Architecture:** Host-side read-only collection (`audit_discovery.py` under the read-only cred, refreshing `audit_data/`) → Inc-3 read-execute readers produce scrubbed reports → a single `claude-code-ads-analyst` skill synthesizes the deliverable via read-only `claude -p` (Read/Grep/Glob), output redirected to `/opt/data/audits/`. Nothing mutates the account; Hermes stays `:ro`.

**Tech Stack:** POSIX sh (host wrappers); Docker (`docker compose exec`); the ads project's own `.venv` + `google-ads` SDK (collection, on host); Inc-3's `run-ads-report.py`/`/opt/ads-venv` (readers); `claude -p` (analyst).

**Nature of this increment:** it wires already-proven pieces (Inc-3 read-execute) together and adds a prose domain skill. There is little unit-testable logic, so tasks verify via **dry-run, `sh -n`, parse-safety checks, the Task-1 empirical gate, and the Task-5 live e2e + benchmark** rather than red-green unit tests. That is the appropriate rigor for shell wrappers + a skill + config.

## Global Constraints

- **Read-only end-to-end.** Read-only credential is the backstop; readers/allow-list only; collection is SELECT-only (`audit_discovery.py`) under the read-only cred; the analyst is read-only `claude` (Read/Grep/Glob, plan mode). The ad account is **never** mutated at any stage.
- **Hermes never writes the client tree.** The only host-side write is `audit_data/` by the project's **own unmodified** collector, run on the host (not in-container). The `:ro` mount is never written. All Hermes outputs go under `/opt/data`.
- **No changes to the `claude-google-ads` repo.** Collection *invokes* its collector; the analyst *reads* its SOP docs.
- **Credentials never** reach the analyst, the deliverable, logs, memory, or telemetry. The analyst reads Inc-3-scrubbed reports only; `.env.ga` is parsed (never sourced) and injected only into the collector process.
- **Client-private data governance (hard rule).** The reports and the audit draft contain real client business data (ad spend, performance). They live ONLY under `/opt/data` (gitignored) and on the host — NEVER committed to git, NEVER written to the brain/memory/telemetry. The Task-5 brain-capture records ONLY the meta outcome (pipeline worked, benchmark verdict, go/no-go) — never client data.
- **The deliverable is a DRAFT** with a mandatory human-review gate; it carries a DRAFT banner + data-provenance line and is never auto-sent.
- **Reader/collector sets are finalized by the Task-1 gate.** The candidate set used below is: collector `audit_discovery.py`; readers `account_overview`, `audit_search_terms`, `audit_analyze`, `negatives_audit`, `negatives_coverage`. If the gate drops/adds any, the finalized set governs Tasks 2–4.
- `.env.ga` (read-only credential) is already provisioned + gitignored from Increment 3.

---

## File Structure

- `infra/hermes-agent/collect-audit-data.sh` — **create.** Host-side read-only collection wrapper.
- `infra/hermes-agent/run-audit-bundle.sh` — **create.** Host loop producing the report set via the Inc-3 wrapper.
- `infra/hermes-agent/run-ads-audit.sh` — **create.** Host wrapper: `claude -p` analyst → persist draft to `/opt/data/audits`.
- `infra/hermes-agent/registry/projects.yaml` — **modify.** Broaden `claude_google_ads` `read_execute.allow`.
- `infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md` — **create.** The domain-specialist analyst skill.
- `infra/hermes-agent/docker-compose.yml` — **modify.** Mount the analyst skill `:ro` where `claude -p` can read it.
- `infra/hermes-agent/README.md` — **modify.** Document the audit-pilot pipeline.

---

## Task 1: Verification gate (controller-run, empirical — decision point)

> **Controller-run, not TDD.** This is spec §7 (G1–G5). It refreshes `audit_data/` on the host (an expected, read-only side effect) and finalizes the collector + reader sets. NO code is committed here. If a gate item fails, STOP and escalate. Record every result in the ledger.

**Files:** none created; produces evidence + a finalized set recorded in the ledger.

- [ ] **Step 1: G1 — collection runs read-only and refreshes `audit_data/`.** With the read-only credential injected, run the collector on the host from the project dir:

```sh
GA=/Users/ericksicard/Projects/claude-google-ads          # host project dir (compose mount source)
set -a; while IFS= read -r l; do case "$l" in GOOGLE_ADS_*=*) export "$l";; esac; done < /Users/ericksicard/Projects/claude_code/infra/hermes-agent/.env.ga; set +a
( cd "$GA" && .venv/bin/python code/audit_discovery.py )   # SELECT-only; read-only user cannot mutate
ls -lt "$GA/audit_data" | head -3                           # confirm fresh files
```
Expected: completes exit 0; `audit_data/*.json` timestamps are now current. Record the collection time. **Discriminator:** if it errors, confirm it's a data/quota error, NOT a permission error on a SELECT (a SELECT permission-denied would mean the read-only user lacks read access — escalate).

- [ ] **Step 2: G1b — confirm which collector(s) are needed.** Note whether `audit_discovery.py` alone produces every `audit_data/*.json` the chosen local readers consume, or whether a sibling collector (e.g. `assess_supplemental.py`, `audit_assets_rsa.py`) is also required. Record the minimal collector set.

- [ ] **Step 3: G2/G3 — reader taxonomy + local readers consume fresh data.** For each candidate reader, run it in-container under the Inc-3 venv and record API-vs-local + usable output:

```sh
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent
set -a; . ./.env.ga; set +a   # (gate only; the shipped wrapper parses, not sources)
for r in account_overview audit_search_terms audit_analyze negatives_audit negatives_coverage; do
  echo "== $r =="
  docker compose exec -e GOOGLE_ADS_DEVELOPER_TOKEN -e GOOGLE_ADS_CLIENT_ID -e GOOGLE_ADS_CLIENT_SECRET \
    -e GOOGLE_ADS_REFRESH_TOKEN -e GOOGLE_ADS_LOGIN_CUSTOMER_ID -e GOOGLE_ADS_CUSTOMER_ID -T hermes-agent \
    /opt/ads-venv/bin/python3 /projects/claude_google_ads/code/$r.py 2>&1 | tail -3
done
```
Expected: each finalized reader exits 0 with non-empty, plausible output; local readers reflect the new collection date. Drop any reader that needs an unavailable arg or produces nothing. **Record the finalized reader set.**

- [ ] **Step 4: G5 — confinement + scan.** Snapshot the target's tracked-file state EXCLUDING `audit_data/` (which collection legitimately changed), run the readers again, and confirm nothing ELSE changed; scan the container logs for the six credential values (0 secrets):

```sh
GA=/Users/ericksicard/Projects/claude-google-ads
( cd "$GA" && git status --porcelain -- . ':(exclude)audit_data' | tee /tmp/ga_before )
# (re-run a reader here) then:
( cd "$GA" && git status --porcelain -- . ':(exclude)audit_data' | diff - /tmp/ga_before && echo "PROOF: only audit_data changed" )
```
Expected: no non-`audit_data` change; credential scan clean.

- [ ] **Step 5: Record the gate outcome** in the ledger: GATE PASSED/FAILED with the finalized **collector set** and **reader set**, the collection timestamp, and the per-reader API/local classification. Only a full pass authorizes Task 2. **The finalized sets govern Tasks 2–4** (replace the candidate lists there if they differ).

---

## Task 2: Host-side read-only collection wrapper

**Files:**
- Create: `infra/hermes-agent/collect-audit-data.sh`

**Interfaces:**
- Produces: a repeatable command that refreshes `audit_data/` under the read-only credential and prints an ISO-8601 collection timestamp (the deliverable's provenance).

- [ ] **Step 1: Write `collect-audit-data.sh`**

```sh
#!/bin/sh
# Host-side READ-ONLY collection: refresh audit_data/ by running the ads project's
# own collector(s) (SELECT-only) under the READ-ONLY credential from .env.ga. Runs on
# the HOST (must write the project tree); Hermes stays :ro. Parses .env.ga (never
# sources it). No mutation possible: read-only cred + SELECT-only collector.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
project_dir="${ADS_PROJECT_DIR:-$(cd "$here/../../../claude-google-ads" 2>/dev/null && pwd || true)}"
env_file="$here/.env.ga"
# Finalized collector set (Task-1 gate): audit_discovery.py (main dump) +
# negatives_audit.py (writes shared-negative coverage into audit_data/). Both are
# SELECT-only and verified working on the host under the read-only credential.
COLLECTORS="audit_discovery.py negatives_audit.py"

[ -n "$project_dir" ] && [ -d "$project_dir" ] || { echo "collect-audit-data: project dir not found (set ADS_PROJECT_DIR)" >&2; exit 1; }
[ -f "$env_file" ] || { echo "collect-audit-data: $env_file not found — provision the read-only credential (Inc-3)" >&2; exit 1; }
py="$project_dir/.venv/bin/python"
[ -x "$py" ] || { echo "collect-audit-data: $py not found — the ads project's .venv must exist on the host" >&2; exit 1; }

# Parse .env.ga as DATA (not shell code): assign the complete read-only set literally.
while IFS= read -r _l || [ -n "$_l" ]; do
  case "$_l" in ''|'#'*) continue ;; GOOGLE_ADS_*=*) : ;; *) continue ;; esac
  _k=${_l%%=*}; _v=${_l#*=}
  case "$_v" in \"*\") _v=${_v#\"}; _v=${_v%\"} ;; \'*\') _v=${_v#\'}; _v=${_v%\'} ;; esac
  export "$_k=$_v"
done < "$env_file"

if [ "${1:-}" = "--dry-run" ]; then
  for c in $COLLECTORS; do echo "would run (read-only cred): (cd $project_dir && .venv/bin/python code/$c)"; done
  exit 0
fi

for c in $COLLECTORS; do
  [ -f "$project_dir/code/$c" ] || { echo "collect-audit-data: collector not found: code/$c" >&2; exit 1; }
  echo "collect-audit-data: running code/$c under the read-only credential…" >&2
  ( cd "$project_dir" && .venv/bin/python "code/$c" )
done
date -u +%Y-%m-%dT%H:%M:%SZ    # collection timestamp = deliverable provenance
```

- [ ] **Step 2: Make executable + syntax check**

Run: `chmod +x infra/hermes-agent/collect-audit-data.sh && sh -n infra/hermes-agent/collect-audit-data.sh && echo OK`
Expected: `OK`.

- [ ] **Step 3: Dry-run (no collection, no creds needed to hit the API)**

Run: `cd infra/hermes-agent && ./collect-audit-data.sh --dry-run`
Expected: prints `would run (read-only cred): (cd <project> && .venv/bin/python code/audit_discovery.py)` and exits 0 (proves path resolution + arg handling without touching the API).

- [ ] **Step 4: Parse-safety check (metachar in a value must NOT execute)**

Run this against a crafted temp env to prove the parser treats values as inert data:

```sh
T=$(mktemp -d); printf 'GOOGLE_ADS_REFRESH_TOKEN=a$(touch %s/PWNED)b\n' "$T" > "$T/.env.ga"
sh -c 'while IFS= read -r _l || [ -n "$_l" ]; do case "$_l" in ""|"#"*) continue;; GOOGLE_ADS_*=*) :;; *) continue;; esac; _k=${_l%%=*}; _v=${_l#*=}; export "$_k=$_v"; done < "'"$T"'/.env.ga"; printf "%s\n" "$GOOGLE_ADS_REFRESH_TOKEN"'
[ -f "$T/PWNED" ] && echo "FAIL: executed" || echo "OK: inert"; rm -rf "$T"
```
Expected: prints the literal `a$(touch …)b` then `OK: inert`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/collect-audit-data.sh
git commit -m "feat(hermes): host-side read-only audit_data collection wrapper (P6 Task 2)"
```

---

## Task 3: Broaden the read-execute allow-list + bundle runner

**Files:**
- Modify: `infra/hermes-agent/registry/projects.yaml`
- Create: `infra/hermes-agent/run-audit-bundle.sh`

**Interfaces:**
- Consumes: Inc-3's `run-ads-report.sh` + the broadened allow-list.
- Produces: a full scrubbed report set under `/opt/data/reports/claude_google_ads/`.

- [ ] **Step 1: Broaden the allow-list** in `infra/hermes-agent/registry/projects.yaml` — replace the `claude_google_ads` `read_execute.allow` list with the finalized reader set (readers only; mutators still absent):

```yaml
      allow:                       # EXACT basenames; fail-closed; READERS ONLY
        - account_overview
        - audit_search_terms
        - audit_analyze
```
(Task-1 gate finalized this set: `negatives_audit` is a *collector* — it writes
`audit_data/` and the `:ro` mount refuses it in-container — so it lives in
`collect-audit-data.sh`, NOT here; `negatives_coverage` was dropped (input-doc bug).)

- [ ] **Step 2: Verify the runner resolves each new reader (offline dry-run)**

Run: `cd infra/hermes-agent/bin && for r in account_overview audit_search_terms audit_analyze; do python3 run-ads-report.py --project claude_google_ads --report "$r" --dry-run >/dev/null && echo "$r OK" || echo "$r FAIL"; done`
Expected: each prints `OK` (the Inc-3 parser + allow-list accept them). Also confirm a mutator AND a now-non-listed script are refused: `for r in apply_negatives negatives_audit negatives_coverage; do python3 run-ads-report.py --project claude_google_ads --report "$r" --dry-run >/dev/null 2>&1 && echo "$r NOT-REFUSED(bad)" || echo "$r refused OK"; done` → all `refused OK`.

- [ ] **Step 3: Confirm the Inc-3 offline suite still passes** (the registry change must not break it)

Run: `cd infra/hermes-agent/bin && python3 run-ads-report.test.py 2>&1 | grep -E "Ran |OK|FAILED"`
Expected: `OK`.

- [ ] **Step 4: Write `run-audit-bundle.sh`**

```sh
#!/bin/sh
# Produce the full READ-ONLY report set the ads-analyst consumes, by running each
# allow-listed reader via the Inc-3 wrapper (run-ads-report.sh). Read-only; each
# reader is allow-list-enforced by run-ads-report.py. The reader set MATCHES the
# registry read_execute.allow (finalized in the Task-1 gate).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-claude_google_ads}"
READERS="account_overview audit_search_terms audit_analyze"   # Task-1 finalized (matches read_execute.allow)
echo "run-audit-bundle: producing report set for $PROJECT" >&2
for r in $READERS; do
  echo "  -> $r" >&2
  "$here/run-ads-report.sh" --project "$PROJECT" --report "$r"   # prints each report path
done
echo "run-audit-bundle: done" >&2
```

- [ ] **Step 5: Executable + syntax check**

Run: `chmod +x infra/hermes-agent/run-audit-bundle.sh && sh -n infra/hermes-agent/run-audit-bundle.sh && echo OK`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/registry/projects.yaml infra/hermes-agent/run-audit-bundle.sh
git commit -m "feat(hermes): broaden read-execute allow-list + audit bundle runner (P6 Task 3)"
```

---

## Task 4: The `ads-analyst` skill + analyst wrapper

**Files:**
- Create: `infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md`
- Modify: `infra/hermes-agent/docker-compose.yml`
- Create: `infra/hermes-agent/run-ads-audit.sh`

**Interfaces:**
- Consumes: the scrubbed reports (`/opt/data/reports/<project>/`) + the SOP docs (`:ro` mount).
- Produces: the audit DRAFT at `/opt/data/audits/<project>/<ts>-audit.md`.

- [ ] **Step 1: Write the analyst skill** `infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md`

````markdown
---
name: claude-code-ads-analyst
description: >
  Produce a client-grade Google Ads audit DRAFT for a dental practice from
  read-only Hermes reports. Use when asked to audit, analyze, or summarize a
  registered Google Ads account's performance. READ-ONLY: reads reports + SOP
  docs and EMITS the deliverable; never runs scripts, never proposes applying
  changes to the account.
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [Google-Ads, Audit, Read-Only, AIOS, Monetization]
---

# Ads Analyst — read-only Google Ads audit synthesis

You produce a **client-grade audit DRAFT** from already-collected, credential-
scrubbed reports. You are READ-ONLY: you may Read/Grep/Glob the reports and the
project's SOP/benchmark docs; you MUST NOT run scripts, take Bash, or recommend
*applying* changes. Output ONLY the deliverable markdown — no preamble.

## Inputs
- Scrubbed reports: `/opt/data/reports/<project>/*.md` (newest per report type).
- SOP / benchmark docs in the project mount `/projects/<project>/`:
  `dental-benchmarks.md`, `dental-sefl-blueprint.md`, `ad-assets-best-practices.md`,
  `anatomy-of-a-good-ad.md`, and any `*negative*` / `campaigns.md` reference.

## Rules
- **Ground every quantitative claim** in a specific report; if the reports do not
  support a claim, do not make it. Never invent numbers.
- **Cite the SOP principle** a recommendation follows (by doc + section).
- Recommendations are **advisory**; the account is not changed by this pilot.
- Disclose data provenance (report timestamps + the `audit_data/` collection date
  if present in the reports) and mark the document a DRAFT for human review.

## Output contract (exact order)
1. A first line banner: `> DRAFT FOR HUMAN REVIEW — not final, not client-sent.`
   then a **provenance** line: report date(s) + collection date + account name.
2. `## Overall account condition` — one grounded paragraph.
3. `## Largest source of wasted spend` — with the numbers + which report shows it.
4. `## Largest growth opportunity`.
5. `## Most urgent tracking / configuration problem`.
6. `## Top 5 recommended actions` — prioritized; each: action, rationale, the
   report evidence, and the SOP principle it follows. Advisory only.
7. `## Changes that should NOT be made yet` — mandatory; guard against premature action.
8. `## Evidence appendix` — list the report file paths used.

## Never
- Run a script, take Bash, or use Write/Edit — you only Read/Grep/Glob and emit text.
- Recommend *executing* a mutation; "apply the changes" is out of scope.
- State the draft is final or client-ready.
````

- [ ] **Step 2: Mount the skill read-only where `claude -p` can read it** — in `infra/hermes-agent/docker-compose.yml`, add to the `hermes-agent` service `volumes:` (next to the other skill mounts):

```yaml
      - ./skills/claude-code-ads-analyst:/opt/data/skills/claude-code-ads-analyst:ro  # ads-analyst skill (read-only)
```

- [ ] **Step 3: Recreate the container so the mount takes effect, and verify it's readable**

Run: `cd infra/hermes-agent && docker compose up -d hermes-agent && docker compose exec -T hermes-agent sh -lc 'head -1 /opt/data/skills/claude-code-ads-analyst/SKILL.md'`
Expected: prints the `---` frontmatter opener (skill is mounted + readable in-container).

- [ ] **Step 4: Write `run-ads-audit.sh`** (analyst invocation + persist)

```sh
#!/bin/sh
# Produce the ads-analyst audit DRAFT (READ-ONLY). Runs `claude -p` inside the
# container over the scrubbed reports (/opt/data/reports) + SOP docs (:ro mount),
# following the ads-analyst skill, and persists the draft to /opt/data/audits via a
# shell redirect. claude itself only Reads/Greps/Globs (plan mode); the redirect
# writes to /opt/data (writable state volume), never the :ro project mount.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-claude_google_ads}"
SKILL="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
exec docker compose -f "$here/docker-compose.yml" exec -T hermes-agent sh -lc '
  set -eu
  proj="'"$PROJECT"'"
  skill="'"$SKILL"'"
  ls /opt/data/reports/"$proj"/*.md >/dev/null 2>&1 || { echo "run-ads-audit: no reports in /opt/data/reports/$proj — run ./run-audit-bundle.sh first" >&2; exit 1; }
  mkdir -p /opt/data/audits/"$proj"
  out=/opt/data/audits/"$proj"/$(date -u +%Y-%m-%d_%H-%M-%S)-audit.md
  claude -p "Read and follow $skill EXACTLY. Produce the Google Ads audit DRAFT for project $proj using the scrubbed reports in /opt/data/reports/$proj/ and the SOP/benchmark docs in /projects/$proj/. Output ONLY the deliverable markdown, no preamble." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'
```

- [ ] **Step 5: Executable + syntax check**

Run: `chmod +x infra/hermes-agent/run-ads-audit.sh && sh -n infra/hermes-agent/run-ads-audit.sh && echo OK`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md infra/hermes-agent/docker-compose.yml infra/hermes-agent/run-ads-audit.sh
git commit -m "feat(hermes): ads-analyst skill + read-only analyst wrapper (P6 Task 4)"
```

---

## Task 5: End-to-end pilot + benchmark + human-review gate + proofs

**Files:**
- Modify: `infra/hermes-agent/README.md`

- [ ] **Step 1: Collect fresh data (host, read-only)**

Run: `cd infra/hermes-agent && ./collect-audit-data.sh` → record the printed collection timestamp.
Expected: `audit_data/` refreshed; exit 0.

- [ ] **Step 2: Produce the report set**

Run: `cd infra/hermes-agent && ./run-audit-bundle.sh claude_google_ads`
Expected: prints a report path per reader under `/opt/data/reports/claude_google_ads/`.

- [ ] **Step 3: Produce the audit draft**

Run: `cd infra/hermes-agent && ./run-ads-audit.sh claude_google_ads`
Expected: prints `/opt/data/audits/claude_google_ads/<ts>-audit.md`.

- [ ] **Step 4: Prove read-only + no leak (confinement + scan)**

- **Account untouched:** the whole pipeline used SELECT-only collection under a read-only credential + read-only readers + a read-only analyst — assert no mutator ran and the read-only cred backstops it.
- **`:ro` mount untouched by Hermes:** `cd /Users/ericksicard/Projects/claude-google-ads && git status --porcelain -- . ':(exclude)audit_data'` is unchanged from before the Hermes steps (only host-side `audit_data/` changed, in Step 1).
- **Credential scan clean:** none of the six `GOOGLE_ADS_*` values appear in the draft, the reports, or `docker compose logs hermes-agent`.
- **Draft is read-only-authored:** the draft file was written by the shell redirect to `/opt/data`, not by `claude` (which ran `--permission-mode plan --allowedTools 'Read,Grep,Glob'`).

- [ ] **Step 5: Benchmark against the existing hand-made audit (the quality bar)**

Compare the draft's four judgments (overall condition, largest wasted spend, largest growth opportunity, most urgent tracking problem) against `/Users/ericksicard/Projects/claude-google-ads/google-ads-executive-summary.md` for the same account. Record: do they match, or are divergences **defensible from the report data**? Note any invented/unsupported numbers (there must be none).

- [ ] **Step 6: HUMAN-REVIEW GATE**

Present the draft to the operator for validation against the raw reports BEFORE any client use. This is a required gate, not optional — the deliverable is a draft. Record the operator's verdict (ship-after-edits / needs-work + what).

- [ ] **Step 7: Document in the README** — add a "Google Ads audit pilot (P6)" section to `infra/hermes-agent/README.md`: the read-only-collection prerequisite (`collect-audit-data.sh`, host, read-only cred), the `run-audit-bundle.sh` → `run-ads-audit.sh` flow, the allow-list (readers only), the safety model (read-only end-to-end + human-review gate + `:ro` + scrub), data-provenance disclosure, and that the output is a DRAFT.

- [ ] **Step 8: Capture the pilot outcome to the brain**

Run `brain-capture` (or write a decision candidate under `.project-brain/decisions/candidates/`) recording ONLY the META outcome: whether the pipeline worked, the benchmark verdict, and the go/no-go recommendation on the fixed-fee-audit product. **NEVER** write client business data (spend, performance, the audit content) into the brain — that is a hard-rule violation. Promotable to canon only via `brain-promote --approve` — never write `canon/` directly.

- [ ] **Step 9: Commit**

```bash
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): document the Google Ads audit pilot + record P6 outcome (P6 Task 5)"
```

---

## Final whole-branch review

After Task 5, dispatch the final whole-branch review (superpowers:requesting-code-review) on a capable model over the increment's commit range. Focus: that the pipeline is genuinely read-only end-to-end (collection SELECT-only under the read-only cred; readers allow-list-enforced; analyst plan-mode Read/Grep/Glob; the draft written by redirect to `/opt/data`, not the `:ro` mount); that no credential can reach the draft/logs; that the wrappers parse (not source) `.env.ga`; that the skill forbids mutation recommendations; and that the human-review gate + DRAFT framing are enforced. Confirm the account is never mutated at any stage.

---

## Self-Review (completed during planning)

- **Spec coverage:** collection §5.1 (Task 2 + Task 1 G1); allow-list §5.2 + bundle §5.3 (Task 3); analyst skill §5.4 + output §5.5 (Task 4); deliverable contract §8 (skill Step 1); gate §7 (Task 1); safety §6 + human gate (Task 5 Steps 4/6); benchmark §9 (Task 5 Step 5); governance §10 (Task 5 Step 8). All covered.
- **Placeholder scan:** none — every wrapper, the skill, and the registry block are complete. The reader/collector sets are explicitly gate-finalized (Task 1 Step 5 governs Tasks 2–4) — a deliberate empirical dependency, not a placeholder.
- **Consistency:** the reader set is identical across the registry (Task 3 Step 1), the bundle (`run-audit-bundle.sh`), and the gate (Task 1 Step 3); `.env.ga` is parsed (not sourced) in `collect-audit-data.sh` matching the Inc-3 wrapper; the analyst is read-only (plan mode + Read/Grep/Glob) everywhere it's described; outputs go only under `/opt/data`.
