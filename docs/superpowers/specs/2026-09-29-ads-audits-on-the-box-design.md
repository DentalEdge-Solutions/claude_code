# Ads audits on the box — design (2026-09-29)

**Status:** approved in conversation, section by section, 2026-09-29; this document awaits operator review.
**Scope:** step 3 of the post-review-#3 batch (with PR #73 and PR #74). Ends with security review #4.

## 1. Goal and intent

The box can produce a client's Google Ads trend audit DRAFT, from start to finish, on one operator
command. Today only the laptop can. The box holds no Google Ads credential and a dummy Anthropic key,
and the collectors are not in its app package.

- **Now (Option 1):** the operator runs `sudo run-client-audit <client>` over SSH and copies the draft off.
- **Final goal (Option 3):** Hermes triggers the same command on request. That comes later and is
  **out of scope here**. It needs an OpenRouter key for Hermes's own reasoning and its own review. This
  design keeps one entry command, so Option 3 becomes "allow Hermes to call that command" and nothing more.

Also out of scope: scheduled audits, pushing drafts off the box, and any mutation (the write tier stays
parked, D3.2).

### Success criteria

1. One real audit on a **spending** client, produced on the box, judged deliverable by the operator
   against a laptop-produced draft for the same period.
2. Security review #4 (checklist v1.8): PASS.
3. No customer id and no credential value in the journal or on the operator's screen.
4. Runtime and Anthropic cost per audit recorded, as the baseline for Option 3 and for scheduling.

## 2. Flow

Build on the existing laptop pipeline, `infra/hermes-agent/run-trend-audit.sh`, rather than a new one.
It already does, in order: resolve the client, collect fresh data, take a deterministic metrics
snapshot, clear stale reports, run the reader bundle, run the trend-aware Opus draft (reading this
client's vault history), write through `vault-write.py` (the sole vault writer), and assert that the
draft names no other client. A box mode keeps every one of those steps and changes only what the box needs.

**Entry:** `sudo run-client-audit <client>`, a thin root wrapper, and the only thing Option 3 will ever
allow Hermes to call. `--dry-run` prints the planned steps, mounts and paths (never a secret value) and
exits.

1. **Pre-checks.** Any failure exits non-zero before anything is created or queried.
   - The client is registered in the governance registry (`clients.json`, resolved by `vault_lib`, the
     same registry D5.4 counts), with `status: active`. A retired or unregistered client is refused. The
     `mutation_target` flag is irrelevant: this path is read-only.
   - The installed app package matches its pin (the D6.1 check).
   - `/etc/hermes/.env.ga` exists, `root:root 0400`. The gateway `.env` holds a non-dummy
     `ANTHROPIC_API_KEY` (checked by prefix, never printed).
   - The box-wide audit lock is free.
2. **Collect.** A one-shot container from the existing Hermes image (the pinned Google Ads SDK is in
   `/opt/ads-venv`) runs the four collectors: `audit_discovery.py`, `negatives_audit.py`,
   `audit_assets_rsa.py` and `assess_supplemental.py`. The read credential and the client's customer id
   are passed as `-e` for this run only, never mounted as a file.
   `/var/lib/hermes/audit-data/<client>/` is mounted **read-write** at the app's
   `/projects/claude_google_ads/audit_data`, in this container only. The rest of the app directory is
   mounted read-only. `audit-data/<client>/` is emptied first, so a run never mixes old and new data.
3. **Snapshot.** `ads-metrics-snapshot.py` over that directory (unchanged).
4. **Reports.** Clear `/opt/data/reports/<project>/`, then run the allow-listed readers
   (`account_overview`, `audit_search_terms`, `audit_analyze`) through the existing enforcer
   `run-ads-report.py`, in a **one-shot `ads-reader` container** (tools profile, the `ads-credential-audit`
   pattern). The reader gets the same per-run credential, `audit-data/<client>` mounted **read-only**, and
   the reports directory read-write. It does not run by `exec` in the gateway, because the long-running
   gateway's mounts are fixed and cannot carry one client's data read-only per run.
5. **Draft.** `claude -p` (Opus, plan mode, `Read,Grep,Glob` only), in trend mode, exactly as
   `run-trend-audit.sh` does today. It reads the scrubbed reports, this client's vault history and the
   packaged SOP/benchmark docs. It gets the Anthropic key via the existing `claude-auth-init` path and
   never sees the Ads credential.
6. **Vault write and isolation check.** `vault-write.py` ingests the draft, metrics and timeline into
   `data/vaults/<client>/`. The existing check that the draft names no other client runs against the
   governance registry.
7. **Summary.** The vault path of the draft, the data collection timestamp, and the rc and duration of
   each step. The operator copies the draft off with `scp`.

## 3. Secrets and placement

| Item | Where | Owner / mode | Seen by |
|---|---|---|---|
| Ads read credential (same token as the laptop's `.env.ga`, `hermes@` READ_ONLY) | `/etc/hermes/.env.ga` (outside the repo checkout, so no container mount can reach it) | `root:root 0400` | the collector and reader runs only, as per-run `-e` |
| Anthropic key (new, dedicated) | gateway `.env`, replacing the dummy | `root:root 0600` | `claude -p` in the gateway |
| Collectors + SOP/benchmark docs | app package, re-pinned in `projects.yaml` | as installed today | collector container (collectors); analyst (docs) |
| Raw client data | `/var/lib/hermes/audit-data/<client>/` | `0700`, uid 10000 | collector (rw), readers (ro) |
| Drafts, metrics, timeline | `data/vaults/<client>/` (existing) | `0700`, uid 10000 (D7.1) | vault-write (w), analyst (r) |

**Anthropic key:** a new key in its own Console workspace (e.g. `hermes-box`) with a monthly spend limit,
used only by the box. Delete the unused legacy key `…9wAA`.

**Package:** add the four collectors and the SOP/benchmark docs the analyst reads to the
`claude_google_ads` package `include` list. Build from a verified ads-repo commit and re-pin the commit
and sha256. D6.1 and D6.3 then cover them.

## 4. Failure handling

- **Stop at the first failure.** Each step's rc is recorded; the summary always prints.
- **Collector errors block the draft.** Any `*.ERROR.txt` in `audit-data/<client>/` stops the run
  before the draft, printing collector names only, never content.
- **One audit at a time.** A box-wide lock (`flock`) keeps spend and API quota predictable.
- **Timeouts** on every step. A hung Google or Anthropic call fails cleanly.
- **Customer ids stay out of logs.** The Google Ads SDK prints raw customer ids to stderr. Collector
  and reader stderr goes to `audit-data/<client>/logs/<step>.stderr` (`0600`, inside the client's private
  directory). The terminal and the journal get line counts only, so D2.3 keeps holding.
- **Spend limit.** A refusal from the Anthropic workspace limit is an ordinary failed step.

## 5. Retention

- **Raw data** (`audit-data/<client>/`): the latest run only, replaced on each run.
- **Scrubbed reports:** the latest run only (cleared at step 4).
- **Drafts, metrics, timeline** (the vault): kept, because trend mode compares against them. No
  automatic expiry.
- **Offboarding:** a new BRING-UP step deletes a retired client's `audit-data/<client>/` and vault. A
  review check confirms no retired client still has either.

## 6. First spending client

The first real audit runs on a client with real spend. It is registered on the box with the existing
BRING-UP procedure (the 2026-09-26 one: registry entry, log created and sealed append-only), plus its
vault. The slug and customer id stay off the repo (F21). Registering it puts that client's data on the
box, and review #4 covers it.

## 7. Testing

Test-first, as in steps 1 and 2.

- **Unit tests** (stdlib, `bin/*.test.py`, run by `run-bin-tests.sh`) for the entry command and box mode,
  on a faked box. They check that it:
  - refuses a retired or unregistered client, a package that differs from its pin, and a secret file
    with the wrong owner or mode;
  - stops at the first failed step;
  - produces no draft on any `*.ERROR.txt`;
  - empties stale data before a run;
  - respects the lock;
  - never prints a customer id or credential value (redaction assertions, like the collector's);
  - enforces each step's timeout.
- **Linux CI mount test**, extending the root, real-Docker "Bind agreement" job with stub collectors.
  It checks that `audit-data` is writable in the collect run and **not** writable in the reader and
  draft runs, and that `/etc/hermes/.env.ga` is invisible inside the gateway container.
- **Nothing in CI calls Google or Anthropic.** Real calls happen only on the box.

## 8. Rollout and review #4

1. Merge. On the box: pull (this brings #73, #74 and this work), install the re-pinned package, install
   `/etc/hermes/.env.ga` and the Anthropic key, and register the spending client (all as BRING-UP
   steps).
2. Laptop: `audit-credential-access.sh`. The box credential's fingerprint must equal `.env.ga`'s
   (`fd18a3b7d0f4`), and the access digest must be unchanged. Declare `GOOGLE_ADS_CREDENTIAL_ROLE=read`
   in `.env.ga` first.
3. **First real audit on the spending client**, before the review, so review #4 sees the system as it
   is actually used.
4. Collect both bundles; a fresh reviewer runs checklist **v1.8**, which adds:
   - the authorised set holds one **read** credential on the box, `/etc/hermes/.env.ga`,
     `root:root 0400`, with a fingerprint equal to the laptop's;
   - the gateway `.env`'s `ANTHROPIC_API_KEY` is real, recorded as such, with the workspace spend limit
     stated;
   - D4.1 also probes `/etc/hermes/.env.ga` from inside the gateway (expected `absent`);
   - `audit-data/<client>/` and the vaults are `0700`, uid 10000; no retired client has either;
   - the new package pin covers the collectors and docs;
   - the journal holds no credential text after a real run (D2.3).
5. Operator sign-off, then land by PR and record a brain decision.

## 9. Decisions resolved before planning

- **Credential file name: `/etc/hermes/.env.ga`, not `ads-read.env`.** The review's system-wide sweep matches
  `.env*`, `*.ga` and `*.gaw`, and would never have seen `ads-read.env`. The new name is swept, and
  `review_lib.ROLE_BY_NAME` classifies it as the `read` role. The file also declares
  `GOOGLE_ADS_CREDENTIAL_ROLE=read`.
- **Readers run in a one-shot `ads-reader` container** (§2 step 4), not by `exec` in the gateway.

- **Package docs:** `dental-benchmarks.md`, `dental-sefl-blueprint.md`, `ad-assets-best-practices.md`,
  `anatomy-of-a-good-ad.md`, `campaigns.md` and `find-and-add-negatives.md` (the docs the
  `claude-code-ads-analyst` skill names), plus the already-packaged `universal-negative-keywords.md`. All are
  tracked at the pin and generic. **Every `google-ads-*.md` is excluded:** at least one
  (`google-ads-negative-keyword-audit.md`) is a past client deliverable carrying a client name and account ids,
  and the skill's "any `*negative*` doc" wording would otherwise sweep it in. The package build gains a guard
  that refuses any packaged doc containing a customer-id-shaped number (`\d{3}-?\d{3}-?\d{4}`).
- **Analyst skill on the box:** already present. `docker-compose.yml` mounts
  `skills/claude-code-ads-analyst` read-only from the checkout.
- **Where box mode lives:** a sibling Python script, `bin/run-client-audit.py`, reusing `vault_lib`,
  `ads-metrics-snapshot.py`, `vault-write.py` and the reader wrapper; `sudo run-client-audit` is its thin
  wrapper. It is testable on a faked box, like the collectors. The laptop's `run-trend-audit.sh` is unchanged.
- **Follow-up, out of scope:** on the laptop, the skill's `*negative*` wording can read that client
  deliverable during another client's audit. Narrow the skill's doc list in its own change.
