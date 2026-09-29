# Hermes security review — definition, evidence, and app packages (design)

**Status:** approved in sections 2026-09-27/28; spec awaiting operator review.
**Origin:** F23 (`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`). Two gates defer
to "the security review", and neither says what it is:
- BRING-UP Phase 3: real money-spending credentials are "gated behind a security review that is
  downstream of this runbook".
- F6: a clone of the private ads repo "after the security review".

The roadmap candidate (2026-07-21) and the post-P6 backlog (2026-08-05) name it too. Nothing
defines what it checks, who performs it, what passes, or where the result lives.

**Scope:** what the review checks, how evidence is collected, who judges it, and how a verdict is
bound to a box state and re-triggered. Also how application code reaches the box (**app
packages**), because the review must be able to vouch for it.

**Mutation stays disabled throughout. The kill switch is ABSENT, and the WRITE credential is OFF
the box (removed 2026-09-27). Nothing here creates either.**

## 1. Problem

1. **An undefined gate is not a gate.** The real WRITE credential went onto the box on 2026-09-25
   (#64) with no review on record. F23's live gate attempt then reached a placeholder ads repo,
   because nothing had ever defined what "reviewed and ready" covers.
2. **The credential is ADMIN on the manager account** (README credential table: an operator
   decision on 2026-08-18). The kill switch governs Hermes's rail, not theft of the file. A stolen
   copy carries user management, billing and account linking for every reachable account.
3. **The obvious F6 route puts client data on the box.** A full clone carries account-level audit
   reports, `google-ads-recommendations.csv`, `campaigns.md`, `runlogs/` and the full history. It
   also puts a GitHub key that can read all of it on the box.
4. **Guard 7 checks that the mutator exists, not which version it is** (F23, second gap).
5. **F24 (measured 2026-09-27):** a stray copy of the WRITE credential sat at
   `/home/hermesops/.env.gaw`, from a session that was cut off. It was `hermesops:hermesops 600` in
   a `750` home, with the same refresh-token fingerprint as the audited credential (`b5aa4baf3310`),
   so there was no wider exposure; it was shredded. No runbook step would have found it. Only a
   system-wide `find` did.

## 2. Decisions (operator, 2026-09-27/28)

| # | Decision | Chosen | Rejected, and why |
|---|---|---|---|
| 1 | Who performs the review | **An independent reviewer session plus operator sign-off** | The operator alone (no second eyes). Codex (its eval layer is built for skills and agents, not host security). |
| 2 | When it runs | **Once now, then on triggers** (§5) | Once only (a September PASS would silently vouch for a changed box). On a schedule (a routine a single operator will not sustain). |
| 3 | How ads code reaches the box | **App package**: the allow-listed code at a verified commit, plus a manifest hash (§6) | A full clone with a deploy key (client data and a GitHub key on the box). A sparse clone (still a key, and history still leaks names). |
| 4 | The WRITE credential until PASS | **Removed from the box**; reinstalled only after PASS, and only if it matches the authorised fingerprint | Leave it dormant (the kill switch does not stop theft; canon rule 3: exposure is irreversible). |
| 5 | Review structure | **Checklist + evidence bundle + independent verdict** | Live walk-through (not repeatable). Script-decided verdict (loses independent judgment). |
| 6 | Raw evidence | **Out of git.** Only the report is committed | Commit the bundles (`claude_code` is public; a bundle is a map of the box). |
| 7 | D3, the ADMIN credential | **The reviewer may recommend** a dedicated STANDARD-access account; **the operator decides**, and the report records the choice and the reason | — |
| 8 | Repo visibility | **Deferred.** Recorded as a D9 open item ("make `claude_code` private; the box receives it as an app package") | — |

**Why app packages fit the AI-OS charter** (`canon/2026-07-17-ai-os-charter.md`). The registry
already treats each project as an app: a name, a scope, and an exact allow-list of functions. A
package installs exactly those functions at a vetted commit (principle 1, governance-first). It
keeps an app's code separate from client data, which lives in the vault and governance layers
(principle 5). It gives every future pack (Meta, WordPress, GTM, GoHighLevel) the same install
route, with no per-repo deploy keys (principle 3). And it leaves room for automation later — CI
builds the package, Hermes proposes installing it, the operator approves — without changing shape.

## 3. What the review checks

Each area expands into checklist items with IDs (`D2.1`, …). Each item states the claim, the
read-only command that tests it, the expected output, and the pass rule.

| Area | What it proves |
|---|---|
| **D1 Host exposure** | Only `:22` listens, and the firewall agrees. SSH is key-only, with no root login. fail2ban and unattended-upgrades are active. Only the expected accounts have login shells or sudo. The deploy user is not in the `docker` group. |
| **D2 Credential inventory** | A **system-wide sweep** — not a check of known paths — finds exactly the authorised credential set (§5.2), each with the expected owner and mode, and each matching its authorised fingerprint. No credential-shaped strings in shell histories or the journal. Covers `.env*`, `*.ga`/`*.gaw`, token and key files, gcloud config, git credentials. (F24's lesson.) |
| **D3 Credential access, as Google sees it** | The laptop audit (`audit-credential-access.sh --all --customer`) measures every role as declared, **with its own exit code visible** (not hidden by a pipe). Decision 7 is recorded here, and the stale "Standard-access" comment in `projects.yaml` is corrected to match. |
| **D4 Isolation boundaries** | From inside the gateway container, credential files and the governance store are unreadable — each probe paired with a control path that *is* readable. The proxy's policy is live. The installed unit files equal the repo's. The broker's `init-host-layout.py --check` passes. |
| **D5 Governance store** | The layout check passes; every registered log is sealed (`a` flag); the kill switch is absent; registry counts are as expected. Counts only, never slugs. |
| **D6 App packages** | Each installed package's manifest hash = the hash in the registry = a package built from the laptop-verified commit. No client data in any package. No git or GitHub credential on the box. |
| **D7 Client data on the box** | What client data exists (vaults, run records, log backups such as `/root/live-gate-*`), where it is, who can read it, and that none of it is inside a package. |
| **D8 Stop and recover** | Mutation can be disabled in one step (remove the kill switch, stop the units). The credential-revocation procedure is written and follows canon: prove death by using the token and observing the refusal. |
| **D9 Open findings** | Every open finding is explicitly **accepted, with a reason** or **blocking**. Known at the time of writing: F3, F8, F16, F17, F20 (forged audit-log appends), the `audit_data` data layer (§6.5), repo visibility (decision 8), `main` having no branch protection, and the Google Ads SDK's logger printing raw account ids during the audit (found 2026-09-26, step A of the live gate). |

**Out of scope:** line-by-line review of application code. The per-task and cross-task reviews
(Task 12) own that. A changed code tree hash (§5) is what re-triggers this review.

## 4. How a review runs

1. **The checklist**, `infra/hermes-agent/deploy/security-review/CHECKLIST.md`. It is versioned
   (`version:` at the top), and every report cites the version it used.
2. **The box collector**, `infra/hermes-agent/bin/collect-review-evidence.py`. Stdlib only,
   read-only, run with `sudo`. It runs every box-side item and prints one bundle to stdout (the
   operator redirects it to a file). Rules, each enforced in code and tests:
   - **Never prints** a credential value (sha12 fingerprints only, the same convention as
     `audit-credential-access.py`), a client slug (`<client>`), or a customer id (sha12).
   - **An item it cannot run is `could-not-check`, never a pass.** An unreadable path is not
     healthy (F17's lesson).
   - `--fingerprint-only` prints only the box-state fingerprint (§5).
3. **The laptop collector**, `infra/hermes-agent/bin/collect-review-evidence-laptop.py`. It runs the
   D3 audit with its exit code captured and computes the D6 package hash from the verified commit.
4. **Evidence storage.** Raw bundles go to a gitignored directory on the laptop
   (`infra/hermes-agent/security-reviews/`, added to `.gitignore`) and to the operator's own
   private storage. They are never committed.
5. **The independent reviewer.** A fresh session that did not build the box. It receives **only**
   the checklist, the two bundles, and the findings doc — not this conversation. It writes the
   report, `docs/security-reviews/YYYY-MM-DD-review.md`:
   - a verdict per item — `PASS`, `FAIL` or `CANNOT-VERIFY` — each with a short quoted excerpt from
     the evidence;
   - a section for anything alarming that the checklist does not cover;
   - the box-state fingerprint and the authorised credential set (§5.2).
   Any `FAIL` or `CANNOT-VERIFY` makes the overall verdict **not PASS**. The reviewer is told to
   ask for more evidence rather than pass by default.
6. **Operator sign-off**, in the same report: the final verdict, decision 7, and the D9 decisions.
7. **Record.** The report lands by PR. A brain decision records the verdict with its fingerprint
   and goes through `brain-promote --approve`.

## 5. Box-state fingerprint and triggers

### 5.1 The fingerprint

Hashes only, so it is safe to commit in the report. It has **three parts, each checked on its
own**, because they are measured in different places and at different times:

- **The box fingerprint:** every component in the table below. The box collector computes it
  alone (`--fingerprint-only`).
- **The authorised credential set** (§5.2): each credential as {role, refresh-token sha12,
  client-id sha12}. It is compared as a set against what is installed, not hashed into the box
  fingerprint, because the installed set is empty during the review and full afterwards.
- **The measured-access digest:** a hash of the D3 audit's verdicts and access levels, from the
  laptop collector. It re-triggers on access-level drift (canon: human accounts drift).

The box fingerprint's components:

| Component | Hash of | Re-trigger it represents |
|---|---|---|
| Clients | `registry/clients.json` (whole-file sha256; no slugs printed) | a new client or a status change |
| App packages | per app: manifest sha256 and source commit | a new package |
| Security-relevant code | git tree hashes of `infra/hermes-agent/bin/`, `deploy/`, `registry/`, and the blob hashes of `docker-compose.yml` and `Dockerfile`, at the box's checkout | a new action type, a guard change, a unit or image change |
| Entry points | listening sockets, firewall rules, effective `sshd -T` settings | new exposure |
| Checklist | the checklist version | the checklist itself changed |

Changes elsewhere in `claude_code` — docs, brain, skills — do **not** re-trigger. That is why the
code component uses tree hashes of the relevant paths rather than the repo commit.

### 5.2 The authorised credential set (the credential/PASS ordering)

A PASS approves an **authorised credential set**: each credential by role and fingerprint, as
measured on the laptop in D3. It does not approve "whatever is on the box". The fingerprint's
credential component compares the **installed** set against the authorised set:

- **During the review:** the installed set is empty (decision 4), which is allowed.
- **After PASS:** the reinstalled file must match its authorised fingerprint exactly, or the
  pre-kill-switch check fails.

This resolves the conflict that would otherwise arise: reinstalling the credential after PASS
would change the fingerprint and void the PASS.

### 5.3 Enforcement

BRING-UP "Before creating the kill switch" gains three checks against the **latest PASS report**.
All three must hold:

1. **Box:** `collect-review-evidence.py --fingerprint-only` equals the report's box fingerprint.
2. **Box:** `collect-review-evidence.py --credentials-only` prints the installed credential set
   (roles and sha12s), which must equal the report's authorised set.
3. **Laptop:** `collect-review-evidence-laptop.py --access-digest` equals the report's
   measured-access digest. This runs the same audit the credential reinstall already requires.

Any trigger means the PASS no longer applies: no PASS for the current state, no kill switch. A re-run is the full collector; the reviewer is told
which components changed and focuses there, but judges every item.

## 6. App packages

### 6.1 Contents — derived from the registry, not chosen by hand

- `code/<name>.py` for every name on the app's allow-lists (`read_execute.allow` and
  `mutate_execute.allow`);
- plus the static inputs the registry declares in `package.include` — for `claude_google_ads`,
  `universal-negative-keywords.md` (read by `negatives_coverage`; methodology, no client data).

Nothing else: no history, no reports, no `audit_data/`, no `.env`. Measured 2026-09-27: every
allow-listed file imports only the stdlib, `google-ads` and `dotenv`, all already in the image.

### 6.2 Build (laptop)

`bin/build-app-package.py --project <name> --repo <path> --commit <sha>`

- Refuses unless `<sha>` is the checked-out HEAD and the working tree is clean.
- Writes a **reproducible** tarball: entries sorted, mtime/uid/gid/uname/gname fixed, no
  directories other than the implied parents. Same commit → same bytes.
- Writes `manifest.json`: `{project, source_repo, commit, files: [{path, sha256, size}]}`, with
  canonical key order. **Package hash = sha256 of `manifest.json`.**

### 6.3 Record (registry)

`registry/projects.yaml`, per app: `package: {commit: <sha>, sha256: <manifest hash>, include: [...]}`.
It lands by PR like any other registry change, and it is part of the "security-relevant code" tree
hash, so changing it re-triggers the review.

### 6.4 Install (box)

`sudo bin/install-app-package.py --project <name> --package <tar> --manifest <json>`

- Refuses unless the manifest's sha256 equals the registry's `package.sha256`, and every tar
  member's sha256 equals its manifest entry.
- Refuses symlinks, hard links, `..` or absolute paths, device files, and any member not in the
  manifest.
- Replaces the target (`/opt/projects/claude-google-ads`) atomically: extract to a sibling
  temporary directory, then rename. Files `root:root 0444`, directories `0555`. Keeps the empty
  `.env` mask file (`docker-compose.yml:70` binds onto it). Writes the manifest next to the files
  as `.hermes-package.json`.
- Removes the F6 `PLACEHOLDER` marker by replacement (it is not in the manifest).

### 6.5 Run-time enforcement (guard 7)

`apply-changeset.py` guard 7 today (`:193`) refuses only if the mutator file is missing. It gains a
check: the mutator file's sha256 must equal its entry in `.hermes-package.json`, and that manifest's
sha256 must equal the registry's `package.sha256`. A missing or unparseable manifest refuses
(fail-closed). A package swapped or edited on the box is then refused at the point of use, not only
caught at the next review. The same check applies on the `--undo` path (undo runs the same mutator).

**Out of scope, recorded as a D9 item:** a home for `audit_data/`. It is client data, so it belongs
in the box's data layer, and it needs new mounts and a proxy-policy change (F9's bind agreement).
The mutator and the three API readers do not need it. Until then, the five local-compute readers
find no data on the box.

## 7. Order of operations

1. **Build the tools**, by PR with tests: the checklist, both collectors, the package build and
   install, the guard 7 hash check, the registry `package` field, `.gitignore` for evidence, and
   the BRING-UP changes (§5.3, and the pre-kill-switch list pointing here).
2. **Package the ads app:** build on the laptop at the verified commit, record the hash in the
   registry by PR, install on the box. The credential is absent and the kill switch is absent.
3. **Collect:** the box bundle and the laptop bundle. Both stay out of git.
4. **Review:** the independent reviewer writes the report. The operator signs off (decision 7, D9).
5. **If PASS:** reinstall the WRITE credential the #64 way (audit on the laptop first, match the
   fingerprint on the box). It must equal the authorised set. Then the pre-kill-switch check
   (fingerprint = PASS, `MUTATOR_OK`), then re-run the live gate from a **fresh** change-set.
6. **If FAIL or CANNOT-VERIFY:** fix through normal PRs, collect again, review again. Each review is
   a new report; earlier reports are kept.

## 8. Testing

Stdlib suites, discovered by `run-bin-tests.sh`. **Confirm the test count changed**, not merely
that the suite reports OK (spec 2026-08-19 §14). Every negative test pairs with a positive control.

- **Collector redaction.** Fixtures plant a slug and a fake token. The output must contain
  `<client>` and a sha12, never the raw values. Firing control: with redaction disabled in memory,
  the test fails.
- **Collector honesty.** An unreadable path yields `could-not-check`, never a pass; its control, a
  readable path, yields a real result. Determinism: the same fixture state gives the same
  fingerprint twice, and a one-byte change in any component changes it.
- **Checklist ↔ collector sync.** Every checklist ID has a probe, or is marked `laptop` or
  `manual`; every probe maps to a checklist ID. The same pattern as `proxy-policy-sync.test.py`.
- **Package build.** The same commit builds byte-identical packages twice. It refuses a dirty tree
  and a non-HEAD commit. Contents are exactly allow-lists ∪ `include` — asserted against the
  registry, not a hardcoded list.
- **Package install.** It refuses a manifest-hash mismatch, a member-hash mismatch, a symlink, a
  hard link, `..`, an absolute path, and an extra member; the valid package installs with the
  stated modes. Interruption leaves the previous tree intact (the atomic rename).
- **Guard 7.** An edited mutator is refused; the untouched one proceeds to guard 8; a missing
  manifest is refused; a manifest whose hash differs from the registry is refused. The same
  checks on the `--undo` path.

## 9. Residual risks, stated

- **The reviewer sees only what the collector prints.** A check nobody wrote is not run. The
  "not on the checklist" section, and a reviewer instructed to ask for more evidence rather than
  pass by default, are the mitigations — not a guarantee.
- **The ADMIN credential is a standing risk until decision 7 says otherwise.** Removing it while
  under review shortens the window of exposure; it does not change what a stolen copy could do.
- **Already-published material stays published.** Keeping bundles out of git protects future
  evidence only (decision 8 covers the rest).
- **A package pins code, not library versions.** The `google-ads` SDK comes from the image build
  (`/opt/ads-venv`). The `Dockerfile` hash re-triggers the review when the build recipe changes,
  but an unpinned dependency can change on a rebuild without the recipe changing.
