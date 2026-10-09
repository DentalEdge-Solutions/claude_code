# Handoff 2026-10-09: security review #9 passed; the next box change (F58) and review #10 are next

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written
as `<client>`. This file carries no customer id, hostname, address, fingerprint or credential value. Where it
differs from `2026-10-08-rollout-done-review-9-next.md`, this one is later. The working detail of how to run
a review is still in `2026-10-07-next-session-open-items.md` ("Running a review", "Working with this
operator", "Rules that apply"); the corrections this round taught are below.

## Where things stand

- **Security review #9: PASS 37/37, checklist v1.18, signed 2026-10-09**
  (`docs/security-reviews/2026-10-09-review-9.md`, merged in PR #108).
- **`main` is at `792451f`** (merge of PR #108). **The box is at checkout `df58e10`**; `main` is ahead of it
  by documentation only, which the box fingerprint does not cover. Nothing is owed on the box.
- Box fingerprint at review #9: `660599e0…bb8a`. The report's header carries the baselines for review #10
  (the components, the box bundle's collection time `2026-10-09T14:01:23Z`, the credential set, both SSH
  keys' short fingerprints, D4.2's two hashes, D4.5's `alert_log`, D7.1 `records`).
- Findings document: F56 fixed on the box (2026-10-08), F57 reduced with its three residuals accepted,
  **F58 open** (below).
- Private evidence, git-ignored, on the laptop: `infra/hermes-agent/security-reviews/review-9/` (today's two
  bundles, the replaced pair as `bundle-*-2026-10-08.json`, six console screens, `previous-pass-header.md`)
  and `infra/hermes-agent/security-reviews/2026-10-09-operator-evidence-review9.md`.

## How review #9 went

- **2026-10-08:** both bundles collected, evidence confirmed, reviewer: 36 PASS, 1 FAIL (D10.7). The broker's
  journal no longer held the three live refusals of 2026-10-02.
- **Cause (F58):** the box's journal keeps 7 days (`MaxRetentionSec=7day`, `MaxFileSec=1day`,
  `SystemMaxUse=1G`). The setting is not in this repository and the operator did not set it. The collector's
  `--since -30d` (D2.3, D10.7) therefore reads about a week.
- **2026-10-09:** one chat audit (13:39 UTC, `ok`), the three live refusal checks of BRING-UP part 2 step 11
  (about 13:45 to 13:57 UTC), both bundles collected again (box 14:01:23Z, laptop 14:20:05Z), the same
  reviewer judged all 37 items again: PASS. Signed 15:06 UTC.

## Open work

### 1. The next box change, then review #10 (one change, one review)

Build work: plan in `docs/superpowers/plans/`, measure on the laptop first, implementer, independent review,
ask before pushing. Nothing is planned or built yet. **The operator agreed this scope on 2026-10-09, all six
items:**

| Item | Source | Notes |
|---|---|---|
| **Keep at least 30 days of journal** | F58 | A reviewed box change. Read on the box on 2026-10-09 (`systemd-analyze cat-config systemd/journald.conf`): `SystemMaxUse=1G`, `MaxRetentionSec=7day` and `MaxFileSec=1day` are all set in the main file `/etc/systemd/journald.conf`; `/etc/systemd/journald.conf.d/` does not exist; the only drop-in is the distribution's `/usr/lib/systemd/journald.conf.d/syslog.conf`. So a drop-in of our own under `/etc/systemd/journald.conf.d/` can raise the retention and leave the server's file untouched (a drop-in is read after the main file: measure that on the laptop or a stand-in before the box). Size: 7 days took 85.4M (read with `sudo`; without it `journalctl --disk-usage` shows only the user's own 28.8M), so 30 days is roughly 370M, under the 1G cap, with the disk 13% used. The cap can still trim before 30 days if the log grows, which is why the next item matters. |
| **The collector reports the journal window it read** | F58; review #9, entry 1 | The oldest entry's time for each journal D2.3 and D10.7 read, so a short window is visible in the bundle and the checklist can judge it. |
| **The collector counts the sshd `Match` lines** | review #9, entry 5 | Today the count is the operator's paste and is in no bundle. |
| **`REPORT-TEMPLATE.md`: lines for D4.2's hashes and D4.5's `alert_log`** | review #9, entry 9 | The reviewer added both to the header by hand. |
| **BRING-UP corrections from the rollout** | handoff 2026-10-08, "Follow-ups" | LAPTOP 4c's expected text, LAPTOP 5c's lines not to paste, the "not rehearsed" marks, D1.7's two false-FAIL cases. |
| **A read-only laptop check that the passphrase is out of the keychain** | review #9, entry 6 | For the next evidence file. |

### 2. Until F58 is fixed

The three live refusal checks must be repeated within 7 days before every box collection. They need a real
chat audit on the same UTC day (the quota check). Blocks that print only `status=… reason=…`, take the client
at a hidden prompt, and leave the kill switch on if the broker does not answer were written and used on
2026-10-09; they are in that session's conversation, not in BRING-UP. Put them in BRING-UP step 11 with the
next box change.

### 3. The operator's housekeeping

- Three key-shaped strings of unknown origin on the laptop (four files in the code editor's local edit
  history, one downloaded automation template). None is the box's key and none is a live key of the box's
  OpenRouter account. Identify or delete them.
- As in the 2026-10-07 handoff, item 3 (brain candidates, untracked handoffs including this one and
  2026-10-08's, merged local branches, the two modified `evals/` files).
- `.superpowers/sdd/2026-10-07-review-9-box-change/` can be deleted now that review #9 is signed.
- No brain entry records review #9's PASS yet (`brain-capture`, then the weekly review).

## What this round taught about running a review

1. **Check the journal's reach before collecting:** `sudo journalctl --disk-usage`, the oldest entry, and
   `sudo journalctl -u hermes-app-broker@ads-audit --since -30d -o cat --no-pager | grep -oE 'status=refused reason=(disabled|quota|bad_request)' | sort | uniq -c`
   (three lines, or the live checks come first). The trial summary should print D10.7 `journal_counts`:
   the one used on 2026-10-08 did not, and the FAIL was found by the reviewer a day late.
2. **The clipboard:** the operator copies each block from the conversation, which replaces whatever the agent
   put on the clipboard. For a value pasted at a prompt on the box: paste the block first, leave the prompt
   waiting, run the `pbcopy` line in a second laptop window, then paste. Clear with `pbcopy < /dev/null`.
3. **The agent cannot log in to the box** (the key asks for its passphrase): every box block and the `scp`
   are the operator's.
4. **The session's guard refuses the agent a credential search and a script that runs `git stash` and
   `checkout`** even on the laptop: give those blocks to the operator.
5. **Look at every screen and every paste.** This round: a screenshot saved with a leading space in its name,
   a key fragment left uncovered and then covered by a hand-drawn stroke (not a rectangle), a search first
   reported as "no file names" that named twelve, and a start-time paste that was the previous day's output
   (its last line gave the date). Each was caught by reading the thing itself.
6. **The laptop search** for OpenRouter-shaped keys now covers the whole home directory
   (`grep -rIl -E 'sk-or-v1-[A-Za-z0-9]{32,}' ~`); each hit is fingerprinted with `review_lib.sha12` (sha1,
   12 hex) and compared with the bundle's `openrouter-key` row, printing only equal or not.
7. **A re-judgement** goes to the same reviewer with the new bundles and evidence; the replaced bundles are
   renamed with their date and the reviewer is told not to read them. The report is named for the sign-off
   day.
8. **Without the trial collection and the hand-run probes** the second collection went straight through
   (the checkout had not changed since a clean collection the day before). Keep the trial after any pull.

9. **Before a file that was never committed goes into a public commit, read it in full, and stop on any scan
   match.** After the review, a brain pull request (#110) moved old notes into
   `decisions/superseded/`, twelve of which had never been committed; they were moved on their titles. One held a client's short name. A scan before the
   commit reported the match, but the command went on to commit and push. The name was replaced and the branch
   force-pushed within minutes, before the merge; it never reached `main`. GitHub Support was asked on
   2026-10-09 to expunge the replaced commit (`10f45a9`). A scan belongs in its own step whose result is read
   before the commit, and it only finds the names it is given: the operator searched `main` for other names.

## Dates that matter

- **2026-10-12:** the `run`/`ok` result of 2026-10-05 expires on the box.
- **2026-10-16:** the `run`/`ok` result and the three live refusals of 2026-10-09 leave the box's results and
  its 7-day journal. A box bundle collected after that needs a fresh chat audit (D10.8) and the three live
  checks (D10.7) first.
- **2027-10-06:** the OpenRouter key is due for replacement.
