# Rollout plan 2026-10-14: the review #11 box change

Status: written for the operator's review. Nothing here has been run. Every step on the box is done by
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

Runbook: "Add a chat-triggered job", step 0, plus the checks below. Each settles something the
build could not measure. Record every result in the operator evidence file.

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
3. The real collection, both bundles the same UTC day, within 7 days of each job's `ok` run.
4. The evidence file: every restart since the last PASS (the audit's broker, the report's broker, the
   gateway, and the journal service if it restarted); the install date of `ads-report`; the leftover
   directory's search counts and removal line; the stage 0 measurements; each standing acceptance
   repeated with its reason.
5. A fresh reviewer with only what the reviewer brief lists; the report; the operator's sign-off.
6. On PASS: the report job's off switch off. On anything else: it stays on.

## What is still decided by the operator, outside this plan

- Whether the audit's own check for another client's name and `show-audit` get the two hardenings the
  report job has (recommended: yes, as a small follow-up change, judged by review #12).
- Whether to accept the stated limits of that check (a name without its hyphen or with a space is not
  matched; a single-word name can refuse a report).
- Whether reports should keep their step logs in a folder of their own.

## Dates

- The journal reaches 30 days about 2026-11-04; a review before then passes D2.4 on the operator's
  stated date, as review #10 did.
- A job's `ok` result leaves the box 7 days after it was written: collect within 7 days of stage 2's
  and stage 5's runs.
- `dentaledge-bot-pat` expires on 2026-10-23 (the operator's decision; the box holds no GitHub
  credential).
