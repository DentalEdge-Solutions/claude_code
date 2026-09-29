# Handoff — security review #1 (NOT PASS) and the path to the live gate (2026-09-29)

Start here in the next session. Read, in order: this file; the review report
`docs/security-reviews/2026-09-29-review.md`; the spec
`docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`; BRING-UP
"Before creating the kill switch" and the three sections after it.

**Hard rules that carry over.** Never print or paste a credential value (fingerprints only —
sha1 of the bare value, first 12 hex). Client slugs stay on the box: write `<client>` in anything
pasted into chat, a PR, or a doc (F21). This repo is public: no IP address, slug or customer id in
any committed file. Stage by explicit path (the working tree carries unrelated `.project-brain/`,
`evals/` and an untracked `infra/hermes-agent/CLAUDE.md`). Raw evidence bundles live only in the
gitignored `infra/hermes-agent/security-reviews/` and the operator's private storage. The operator
runs every box command and pastes the output; the assistant has no box access.

## Update — later on 2026-09-29: steps A and B done

- **A (box), done.** A1: the box checkout is at `dc295d8`. A2: the in-memory mount sweep printed only
  the two `done` lines (D2.1 cleared). A3: both vault directories are now `700`, owned by uid 10000,
  group `hermes`; the operator still has to confirm `getent group hermes` shows gid 10000 with no
  members. A4: the gateway `.env` holds two secrets, both real: `ANTHROPIC_API_KEY` (used only by the
  box, with a workspace spend limit) and the dashboard password (kept only in the password manager and
  this file). The other names are flags or paths. No Google Ads variables.
- **B (D3.2), decided: read-only posture.** No write credential. The operator won't create another
  Google account (the ADMIN account is shared with another project), and `hermes@` must stay
  READ_ONLY. **F25:** `hermes@` had drifted to STANDARD; the operator put it back, and it is measured
  READ_ONLY again. Changes to client accounts belong to the apps that join the AI OS. The old ADMIN
  token `b5aa4baf3310` is **not revoked** (revoking could hit the other project, canon rule 1); every
  copy is destroyed instead, as an accepted risk. See README "Why there is no write credential".
- **Checklist v1.5** covers the read-only posture (D2.1, D3.1, D3.2, D5.3).
- **Step E is parked.** No live gate until a write role comes back, which needs a dedicated
  STANDARD account and a new review.
- Operator evidence for review #2 is in the gitignored
  `infra/hermes-agent/security-reviews/2026-09-29-operator-evidence-step-A.md`.

## Where things stand

| | State |
|---|---|
| Code | `main` has the security-review tooling + app packages (PR #69) and this handoff's PR |
| Box checkout | `f74db3c` (pull again after this handoff's PR merges) |
| Ads code on the box | app package installed: `claude_google_ads` at `5826212d7f7c`, manifest sha256 `839b9d68b431…`, 11 files, `root:root` read-only; gateway recreated and running |
| WRITE credential | **off the box** (shredded 2026-09-27; a stray copy found and shredded — F24). Laptop copy still exists, sha12 `b5aa4baf3310`, on the operator's ADMIN account |
| Kill switch | **absent** |
| Pilot | the dormant pilot is registered, log sealed (F21: name stays on the box) |
| Fingerprint | stable on the box (two runs 5 min apart identical, `complete: true`); post-install box fingerprint `3cf9e456…` |
| Review #1 | **NOT PASS** — 19 PASS / 3 FAIL / 4 manual |

## What review #1 found, and what this PR already fixed

| Item | Finding | Status |
|---|---|---|
| D1.6 | `hermes-docker-proxy` in the `docker` group | **Fixed in the checklist (v1.4):** by design; the item now fails only on a login account |
| D2.1 | unexplained `not_swept` mounts | **Partly fixed:** v1.4 pre-explains `/boot`, `/boot/efi`, `/dev`, `/run/lock`; the in-memory mounts need the operator's sweep — **step A2** |
| D7.1 | two vault dirs `0755` (parent `data/vaults` is `700`, so not reachable) | **Box step A3** |
| D8.1 | no one-step disable block | **Fixed:** BRING-UP "Stop everything in one step" |
| D8.2 | no written revocation procedure that proves death | **Fixed:** BRING-UP "Revoke the write credential and prove it dead" |
| Not on checklist #1 | README claimed revocation is surgical via a separate OAuth client — contradicts canon rule 1 | **Fixed:** three README passages corrected |
| Not on checklist #2 | the gateway `.env` holds non-Ads secrets the review does not cover | **Box step A4** (names only) |
| D3.2 | ADMIN operator account as the write role | **Operator decision — step B.** Reviewer recommends a dedicated STANDARD-access account |
| D9.1 | open findings undecided | **Operator decision — step C** |

## Next steps, in order

### A. On the box (after this PR merges)

A1. `cd /opt/projects/claude_code && sudo git pull --ff-only && sudo git -C /opt/projects/claude_code log --oneline -1`

A2. D2.1 — run BRING-UP "Sweep the in-memory mounts". Expected: only `name sweep done` and
`content sweep done`. Any path printed: stop, measure exposure (canon rule 3) before touching it.

A3. D7.1 — tighten the vault directories (the gateway, uid 10000, is the owner and keeps access):
```bash
sudo find /opt/hermes-agent/data/vaults -mindepth 1 -maxdepth 1 -type d -exec chmod 700 {} +
sudo find /opt/hermes-agent/data/vaults -mindepth 1 -maxdepth 1 -type d -printf '%u:%g %m\n'   # 10000:10000 700 on every line (names not printed)
```

A4. The gateway `.env` — variable NAMES only, then the operator states for each whether its value
is real or a dummy:
```bash
sudo grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/hermes-agent/.env | tr -d '='
```

### B. Operator decision — D3.2: keep ADMIN, or move the write role to a dedicated STANDARD account

The reviewer recommends moving it: ADMIN carries user management, billing and account linking;
the token already leaked onto the box once (F24); and per canon rule 1 only a separate account
makes revocation surgical. If the operator decides to move it (README "Provisioning a credential
for a new project or role"):
1. Create the dedicated Google account; invite it on the manager at **STANDARD**.
2. Create its own OAuth client (consider a separate Cloud project — canon 2026-08-24).
3. Mint the refresh token **in a terminal that is not an assistant session**, into a new laptop `.env.gaw`.
4. Laptop audit: `./audit-credential-access.sh --cred .env.gaw` → `MUTATE_CAPABLE`, `mismatch false`,
   and `manager_level_admin.admin` **false**. Record the new sha12.
5. Only then retire the old token by BRING-UP "Revoke the write credential and prove it dead"
   (the replacement exists first — canon's ordering rule), including the collateral check.
6. Update the README credential table's `write` row and the `projects.yaml` comment; findings entry; brain.

If the operator keeps ADMIN, the report records the decision and the reason.

### C. Operator decision — D9.1: each open finding accepted (reason) or blocking

From the checklist and the findings doc: F3 (usable-sudo `--check`), F8 (`data/skills` ownership),
F16 (container-path defaults in other host tools), F17 (`unreadable` vs `mismatch` wording), F20
(forged audit-log appends), the `audit_data` data layer (five local readers find no data on the box),
repo visibility (make `claude_code` private?), `main` branch protection, the Google Ads SDK logging
raw account ids to stderr during the audit (the laptop collector discards it). Plus the deferred
minors from the build — see the PR #69 description and review history.

### D. Collect again and run review #2

1. Box: `sudo python3 bin/collect-review-evidence.py > ~/bundle-box.json; echo rc=$?`, copy it to the
   laptop's `infra/hermes-agent/security-reviews/`, delete it from the box.
2. Laptop: `CUST` from the local pilot vault's `index.md`; stash `.claude/settings.json` in the ads
   repo, run `bin/collect-review-evidence-laptop.py --customer "$CUST" --package-project claude_google_ads
   --package-repo ~/Projects/claude-google-ads --package-commit 5826212d7f7c27ebbb51b7bb108558356286a505
   > security-reviews/bundle-laptop.json`, then `stash pop`. If step B changed the credential, the
   laptop `.env.gaw` is the new one.
3. Launch a fresh reviewer agent (most capable model) with ONLY: REVIEWER-BRIEF.md, CHECKLIST.md
   (v1.5), REPORT-TEMPLATE.md, both bundles, the findings doc. It writes
   `docs/security-reviews/<date>-review.md`. Give it the A2 sweep output and the A4 answers as the
   operator's stated evidence for D2.1 / "not on the checklist" #2.
4. Operator sign-off in the report (final verdict, D3.2, D8, D9 lines). Land it by PR; brain decision.

### E. Only after a PASS

1. Reinstall the WRITE credential the #64 way (audit on the laptop first; fingerprint matched on the
   box; `hermes-broker:hermes-broker 0600`).
2. The three checks against the PASS report (BRING-UP): `--fingerprint-only` equals its box
   fingerprint (`complete: true`); `--credentials-only` equals its authorised set (exit 0);
   laptop `--access-digest` equals its digest. Plus `MUTATOR_OK`.
3. Live gate from a **fresh** change-set (the 2026-09-26 attempt-1 block in BRING-UP, steps B–F:
   kill switch on and off in one block; undo host-side as root; consumed-approval check; kill
   switch absent at the end).

## Pointers

- Tooling: `infra/hermes-agent/bin/{collect-review-evidence.py,collect-review-evidence-laptop.py,build-app-package.py,install-app-package.py,review_lib.py,package_lib.py}`
- Checklist, brief, template: `infra/hermes-agent/deploy/security-review/`
- Plan (executed): `docs/superpowers/plans/2026-09-28-hermes-security-review.md`
- Canon: `canon/2026-08-17-credential-governance-lessons.md` (rule 1: the account is the isolation boundary; prove death; mint before revoking)
- Findings: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (F23, F24)
