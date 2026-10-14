# Rollout plan 2026-10-14: the review #11 box change

Status: approved by the operator on 2026-10-14, after a check against the runbook. **Done 2026-10-14: stages 0 to 6 run, security review #11 PASS 38/38, signed (`docs/security-reviews/2026-10-14-review-11.md`).** Every step on the box is done by
the operator, one block per paste, each on the operator's word. The blocks themselves are in
`infra/hermes-agent/deploy/BRING-UP.md` (the runbook); this plan gives the order, what each stage
proves, and when to stop. Client names are written as `<client>`. This file carries no customer id,
hostname, address, fingerprint or credential value.

## What is being rolled out

`main` at the merge of pull request #121, which holds Plan A (#120) and Plan B (#121):

- the leak search reads every stored field of the journal (finding F59);
- the evidence file is created owner-only; D4.6 reports the journal service's start;
- the leftover journal directory can be searched and removed;
- a second job, `ads-report` (figures only), with its report store;
- the security review covers every job (checklist v1.21, twenty closing lines).

The box is at the commit of review #10's PASS. Rolling back is "check out that commit again", plus
the undo of each stage below.

## Rules for the day

- One block per paste, labelled VPS or LAPTOP. `sudo -v` alone first. Paste output starting after the
  prompt line.
- A block that reads `STOP` or shows something not listed as expected: stop and report it; do not
  retry, do not improvise.
- Do not collect for a real review between stage 2 and the end of stage 4: until the chat settings
  hold both jobs' servers, D10.6 fails and no closing line says so.
- The two jobs never run at once; a report run clears that client's step logs, a failed audit's
  included. Read a failed audit's logs before running a report for that client.

## Stage 0: measurements before anything changes (read-only)

Runbook: "Add a chat-triggered job", step 0, holds the blocks for 0.1 to 0.3; step 10 holds the
block for 0.4. **The runbook has no block for 0.5, 0.6 and 0.7**: each is a new read-only block that
prints counts, sizes or modes only, written by the assistant on the day, checked with `sh -n`, and
given to the operator one at a time. 0.8 is on the laptop. Each settles something the build could
not measure. Record every result in the operator evidence file.

| # | What is measured | Why |
|---|---|---|
| 0.1 | The output shape of the job-units listing (columns UNIT LOAD ACTIVE SUB) | The collector reads the LOAD column to decide which jobs are installed |
| 0.2 | What the box answers for a job that is not installed, and for a unit that never logged (exit codes and byte counts only) | The rollout-window reading of D10.3 and D10.7 rests on it |
| 0.3 | The job-units listing again, after 0.2 | Whether a query alone leaves a job counted as installed |
| 0.4 | The registry: a count of records whose customer id is a placeholder or unreadable (runbook step 10's count block) | A placeholder would make reports refuse by accident; an unreadable id refuses every report |
| 0.5 | The size of the reader's three files after the last audit, per client (bytes only) | Each must be under the 5 MiB limit of the store step |
| 0.6 | The number of client short names with no hyphen (a count) | A single ordinary word as a name can refuse a report that quotes it as a search term |
| 0.7 | No symlink in the path of the job state folder (`namei -l`, modes and owners only) | The mount checks compare written paths |
| 0.8 | LAPTOP: the last PASS's proxy value copied with `bin/last-pass-execstart.py` (length 64, never shown) | Needed for the collection in stage 6 |

Stop condition for the stage: any result that is not what the runbook lists as expected is reported
before stage 1. Stage 0 changes nothing, so there is no undo.

## Stage 1: take the new version (runbook step 1)

1. Set the audit's off switch (step 1's first block). No job may be running.
2. Pull.
3. Check the description files are ordinary files (`regular file` twice). **STOP if not: restart
   nothing.**
4. Restart the audit's broker and re-create the gateway (step 7a, two blocks).
5. Take the audit's switch off again (step 1's last block).

Undo: check out the previous commit, repeat 7a.

## Stage 2: prove the audit still works (runbook step 1a)

1. The audit's dry run for the client the chat audit will be asked for: eleven plan lines, costs
   nothing.
2. One chat audit: `ok`. This costs an AI fee and is that client's audit of the day.
3. The three live refusals for the audit (step 11 with `JOB=ads-audit`).

This is evidence produced by the code now running; review #11 judges the audit on it.

## Stage 3: the follow-ups of review #10

1. A trial collection through the summary tool, started with the owner-only command of the review's
   step 3. Read the twenty closing lines. In this window three read `LOOK` for the report job (it is
   declared and not installed, and its store is not there): expected. **STOP if the leak line reads
   `LOOK`:** the wider search found something; it is a finding to decide before going on.
2. The leftover journal directory (runbook "The leftover journal directory", four blocks, in one
   sitting): search, dry run, removal on the operator's word, verify.

Undo for 3.2: none (the removal cannot be undone); that is why the search and the dry run come first.

## Stage 4: add the report job (runbook steps 2 to 8, with `JOB=ads-report`)

In the runbook's order: the account; the layout; the off switch ON (3a); the report store and
`show-report` (3b); the units, comparing and not copying the unit files, noting the proxy line's hash
before and after (4); the chat settings, count block first (6); the gateway (7); two servers and six
tools visible (8).

Record: whether the proxy hash changed at step 4 (it decides whether D4.2 needs the operator's
statement), and the date and time the job was installed (D10.7 asks for it).

Undo: the runbook's step 12 for the job; the chat settings restored from the backup taken at step 6.

## Stage 5: the report job's first runs (runbook steps 10 and 11)

1. Whether a failed audit's logs are still there for the client (`yes`/`no`); read them first if so.
2. The figures dry run: `[store]`, no `[draft]`, no `[proxy]`.
3. One run by hand. Minutes of silence; no Ctrl-C. Then the stored-report count with `show-report`.
4. The off switch off; one run by chat: `ok`.
5. The three live refusals for `ads-report`, in one sitting, not within an hour of 00:00 UTC.
6. The off switch back ON (step 11's last block): the job is not in use until the review that covers
   it passes.

If a report is refused for naming another client: nothing is stored; read the two counts with the
runbook's counts block; report it; do not run again.

## Stage 6: security review #11 (runbook "A security review")

1. Before it: the private review-to-review comparison helper adjusted to the per-job shape; the
   findings document's open-items list brought up to date.
2. The trial collection: twenty lines. Expected `LOOK` lines are only those the runbook explains for
   this box (the journal's reach until about 2026-11-04; the proxy line if stage 4 changed it).
3. The real collection on the box (review step 3, alone: it prompts for the review key), then the
   laptop collection (step 4), both the same UTC day, within 7 days of each job's `ok` run; the box
   bundle copied to the laptop, the copy made owner-only, and the box's copy removed with `shred`
   (step 5); both bundles show the same key id.
4. The evidence file: every restart since the last PASS (the audit's broker, the report's broker, the
   gateway, and the journal service if it restarted); the install date of `ads-report`; the leftover
   directory's search counts and removal line; the stage 0 measurements; each standing acceptance
   repeated with its reason.
5. LAPTOP: the check that the administrative key's passphrase is out of the keychain (step 7).
   A fresh reviewer with only what the reviewer brief lists; the report; the operator's sign-off.
6. On PASS: the report job's off switch off. On anything else: it stays on.

## What is still decided by the operator, outside this plan

- Whether the audit's own check for another client's name and `show-audit` get the two hardenings the
  report job has (recommended: yes, as a small follow-up change, judged by review #12).
- Whether to accept the stated limits of that check (a name without its hyphen or with a space is not
  matched; a single-word name can refuse a report). Decided 2026-10-14: accepted (reports stay on
  the box and are read before they go anywhere).
- Whether reports should keep their step logs in a folder of their own.

## Dates

- The journal reaches 30 days about 2026-11-04; a review before then passes D2.4 on the operator's
  stated date, as review #10 did.
- A job's `ok` result leaves the box 7 days after it was written: collect within 7 days of stage 2's
  and stage 5's runs.
- `dentaledge-bot-pat` expires on 2026-10-23 (the operator's decision; the box holds no GitHub
  credential).

## To resume in a fresh conversation

State on 2026-10-14, end of the day: **the rollout is complete.** Stages 0 to 6 are done. Security
review #11 PASSED 38/38 on checklist v1.22 and is signed and dated 2026-10-14
(`docs/security-reviews/2026-10-14-review-11.md`, pull request #126). The box is at `20a2e7c` (the
pull since `a2c243e` changed two documents only). Both jobs are in use: the off switches of
`ads-audit` and `ads-report` are both off (17:43:57 UTC). Finding F62 (OpenRouter's new retention
choice for the box's chat model, found set to "Safety retention allowed") was fixed in the console the
same day ("Zero retention only"); it is in the findings document. The private evidence file
(`infra/hermes-agent/security-reviews/2026-10-14-operator-evidence-review11.md`, git-ignored) holds
every result, with a dated corrections section after the reviewer's reading; the bundles and console
screens are in `infra/hermes-agent/security-reviews/review-11/`, owner-only.

Standing rule accepted at the sign-off: before a report is run for a client whose last audit failed,
read that audit's step logs first (the report run clears them).

Read first, in this order, for the next piece of work:

1. `docs/security-reviews/2026-10-14-review-11.md`: its "Not on the checklist" entries and the
   operator sign-off (the follow-ups below come from there).
2. `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`: F61, F62 and the open items
   21 and 22.
3. The brain's daily log of 2026-10-14 (`.project-brain/sessions/daily/2026-10-14.md`).

Open with the operator, none blocking:

- An API-key guardrail limiting the OpenRouter key to the box's model (closes the Google residual of
  F46; shown in review #12's screens). A console change only.
- For review #12 (a box change): the collector reads a named volume's options (F61) and
  `provider_routing` from the box's `data/config.yaml`; D10.5 names each Zero Data Retention row's
  retention choice (item 22); the next evidence file quotes the time of D4.5's one `could-not-check`
  run; review #12 reads `ads-report`'s D10.7 counts with particular care.
- Whether reports keep their step logs in a folder of their own; whether the audit's own check for
  another client's name and `show-audit` get the report job's two hardenings; removing the retired
  `rehearsal` record at the next registry change.
- The runbook fixes noted during the rollout (a block that takes one job's off switch off; the
  `git log` line run without `sudo`; the `wc` read of `sudoers.d/README` through an unprivileged
  redirection). They change a file the box's fingerprint covers, so review #12 judges them.
- Compiling and promoting the brain entries (`brain-compile`, then the operator's `/brain-promote`).

Dates: `dentaledge-bot-pat` expires 2026-10-23; the journal reaches 30 days about 2026-11-04;
`ads-audit`'s `ok` result of 2026-10-09 leaves the box 2026-10-16, both jobs' results of 2026-10-14
on 2026-10-21 (a review collected after that needs a new chat run of each job first).

Standing rules of the operator (unchanged):

- Plain language for a non-coder; one block at a time; nothing changes on the box and nothing is
  pushed without the operator's word; the operator merges.
- The assistant cannot reach the box: every VPS block is pasted by the operator, ALONE, labelled, with
  what to expect and the stop condition; `sudo -v` alone first; output pasted starting after the
  prompt line; never retry a login that fails.
- Never a client name, customer id, host name, address, fingerprint or credential value in the
  repository, the brain or the conversation; blocks print counts, states and fixed words only.
- The private files under `infra/hermes-agent/security-reviews/` are never committed, printed whole
  or pasted; the assistant does not read `.env` files.
- Never commit anything under `evals/`.
