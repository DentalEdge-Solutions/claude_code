# Handoff — 2026-09-30: Google Ads audits live on the box; security review #5 PASS

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. The spec, plan and reviews
named below carry the detail. Client names are written as `<client>`, and no customer ids or id fingerprints appear
in this repo (it is public; BRING-UP step 5 explains why).

## Where things stand

- **The box runs client Google Ads trend audits with one command:** `sudo run-client-audit <client>` (or
  `--dry-run` first).
  - Collectors and readers run in one-shot containers (`ads-collector`, `ads-reader`). The READ credential is passed
    per run as `-e NAME` and never mounted.
  - A host metrics snapshot and `vault-write` both run as uid 10000. The Opus trend draft runs in the gateway.
  - The draft lands in the client's vault at `/opt/hermes-agent/data/vaults/<client>/audits/<ts>-audit.md`.
  - Exit codes: 0 draft written, 1 a step failed, 2 a pre-check refused, 3 another audit is running.
- **The first real audit** (a spending client): about 3 minutes and $0.51. The operator judged it **deliverable**
  against a laptop draft.
- **Secrets on the box:**
  - The Google Ads READ credential at `/etc/hermes/.env.ga`, `root:root 0400`, the same token as the laptop's
    `.env.ga` (the account is READ_ONLY on the manager).
  - A real Anthropic key in the gateway `.env`, from the Console workspace `hermes-box` (monthly limit $20). The
    legacy key is deleted.
  - **No write credential anywhere.** The read-only posture (D3.2) is unchanged.
- **Security review #5: PASS 26/26, checklist v1.10** (`docs/security-reviews/2026-09-30-review-5.md`). It binds to
  box fingerprint `2dad4553…` and access digest `0f0bdb9e…`. The box is on `main` at the review's code. **Any change
  under `infra/hermes-agent/{bin,deploy,registry}`, `docker-compose.yml` or `Dockerfile` breaks that binding and
  needs a new review.** `deploy/` includes BRING-UP.md and CHECKLIST.md: docs there count too.
- **Registry:** 3 clients: 2 active (one is the only dormant pilot, the mutation-tier test target) and 1 retired
  (`rehearsal`, whose vault was removed).

## What landed (PRs, in order)

| PR | What |
|---|---|
| #75 | Ads audits on the box: spec, plan, orchestrator, one-shot containers, package (collectors + scrubbed SOP docs, id guard), checklist v1.8, BRING-UP |
| #76 | BRING-UP step 5: guarded client registration (after the registry incident, below) |
| #77 | Orchestrator passes compose the symlink-resolved path (`/opt/hermes-agent` is a symlink) |
| #78 | Orchestrator ensures `data/reports` belongs to uid 10000; fails closed on a missing `data/` |
| #79 | Security review #4: PASS 26/26 (v1.8) |
| #80 | A customer-id fingerprint removed from BRING-UP; rule: fingerprints never go into the repo |
| #81 | `bin/register-client.py` (never installs a broken registry); D7.1 covers `data/reports` + `audit-logs`; `pwd -P` in 9 host scripts; checklist v1.9 |
| #82 | Checklist v1.10: `audit-logs/<client>` is root `0711` by design (v1.9 wrongly required `0700`) |
| #83 | Security review #5: PASS 26/26 (v1.10) |

The ads repo (`claude-google-ads`, private) merged its PR #4: the SOP docs scrubbed of a real client's ids, name and
location hints. The Hermes package pins its commit `81103e1`.

## Lessons from this rollout (all recorded in the brain)

- **Never put an interactive prompt inside a multi-line paste.** A hidden `read` got an empty line from the paste,
  and the next line installed an EMPTY registry over the real one. The store refused, correctly, and the registry
  was rebuilt the same day. Prompts go in their own one-line paste, reading from `/dev/tty`. Governed files are
  replaced only by a script that parses the current file, validates the new one and swaps atomically (now
  `register-client.py`).
- **`docker compose -f /opt/hermes-agent/...` resolves relative binds through the symlink** and mounted the wrong
  dirs (`/claude-google-ads`, and `/` for `../..`). Always resolve the real path (PR #77, `pwd -P` in #81).
- **Docker creates a missing bind source as root:root 0755**, which the uid-10000 containers can't write. Pre-create
  bind sources with the right owner (PR #78).
- **Customer-id sha1 prefixes are not redaction** (10 digits → brute-forceable). Compare them in the terminal
  only; never commit them.
- **With `sudo` and globs:** a `*` under a root-only directory must be expanded by root (`sudo sh -c '… *'`).
- **Operator evidence files** live in `infra/hermes-agent/security-reviews/`, which is **gitignored**. They may
  hold client names and fingerprints; review REPORTS are committed and must hold neither.

## Next work, in priority order

1. **Option B: Hermes chat triggers and shows audits** (the stated end goal). It needs its own spec → plan → review.
   Design these in from the start:
   - Hermes needs an OpenRouter key for its own reasoning (a new secret).
   - Per-client isolation: the gateway owns `data/`, so a reasoning Hermes could read EVERY client's vault.
   - A probe proving only the collect step holds the Google credential.
   - Egress limits for the Opus draft step (it reads client-controlled ad data).
   - Keyed hashes instead of sha12 for the review tooling's `cid:` fingerprints.
   - Allow Hermes to call exactly one command: `run-client-audit`.
2. **Review-collector follow-ups** (from review #5):
   - report file modes inside `audit-logs/<client>/` without names;
   - classify Docker `nsfs` handles in `memory_sweep`;
   - have each evidence file carry the last PASS's proxy `execstart_sha256`.
3. **Brain upkeep:** decision and lesson candidates from 2026-09-29/30 await review with
   `node scripts/brain/brain-promote.js` (`--approve` for canon).

## Operational reference

- The first audit on a new client:
  1. Register it (BRING-UP "Ads audits on the box" step 5: a one-line id prompt, then `register-client.py`).
  2. Create its vault dir (the same step).
  3. `sudo run-client-audit <client> --dry-run`, then the real run.
- **Copy a draft off the box** (vault drafts are uid-10000 only):
  1. Box: `sudo install -o hermesops -g hermesops -m 0600 <vault draft> ~/x.md`.
  2. Laptop: `scp -i ~/.ssh/vps-hermes hermesops@<host>:~/x.md ~/Desktop/`.
  3. Box: `shred -u ~/x.md`.
- **Step logs:** `/var/lib/hermes/audit-logs/<client>/` (root 0600). Read them masked:
  `sudo sed -E 's/[0-9]{6,}/<num>/g' <log> | tail -40`.
- **A security review:**
  1. Box: `git pull`, then `sudo python3 infra/hermes-agent/bin/collect-review-evidence.py > ~/bundle-box.json`.
  2. Copy it to the laptop's `security-reviews/`, and delete it from the box.
  3. Laptop: `bin/collect-review-evidence-laptop.py --customer <dormant pilot id> --package-*` (ads repo checked
     out at the pin, with `.claude/settings.json` stashed).
  4. Launch a fresh reviewer with only REVIEWER-BRIEF, CHECKLIST, REPORT-TEMPLATE, both bundles, the findings doc
     and the operator evidence file.
- **Key files:**
  - `docs/superpowers/specs/2026-09-29-ads-audits-on-the-box-design.md`
  - `docs/superpowers/plans/2026-09-29-ads-audits-on-the-box.md`
  - `infra/hermes-agent/bin/run-client-audit.py`, `bin/client_audit_lib.py`, `bin/register-client.py`
  - `infra/hermes-agent/deploy/BRING-UP.md` ("Ads audits on the box")
  - `infra/hermes-agent/deploy/security-review/CHECKLIST.md` (v1.10)
