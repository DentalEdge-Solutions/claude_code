# Design 2026-10-13: a second chat-triggered job (`ads-report`), a job template that is a template, and the follow-ups of review #10

Status: written for the operator's review on 2026-10-13, after five sections agreed in conversation. Nothing
is built, pushed or changed on the box. Client names are written as `<client>`. This file carries no customer
id, hostname, address, fingerprint or credential value.

## Goal

One box change, judged by security review #11:

1. A second job, `ads-report`: the three Google Ads reports of the audit, as figures only, with no AI model.
2. The chat-trigger machinery stops knowing the audit by name, so a third job is a description file and a
   runbook chapter, not a code change.
3. The security review covers every job the box declares, not one job written into the collector.
4. The follow-ups of review #10 are closed, F59 first.

Done means: review #11 passes on checklist v1.20 with both jobs; the audit behaves as it does today; a
report run opens no AI credential and starts no AI container.

## In plain language

Hermes can today be asked in chat to run one job, the audit, which collects a client's Google Ads figures and
has an AI model write a draft. This change adds a second job that stops before the AI step and stores the
figures. It costs no AI fees. It has its own account on the server, its own inbox, its own daily limits and
its own off switch. Hermes still sees only the outcome (done, refused, failed, busy), never the content; the
operator reads a report on the server with `sudo show-report <client>`.

Adding it shows where the audit is still written into parts meant to be shared. Those parts are fixed, and
the security review is taught to check every job.

## Decisions made by the operator (2026-10-12 and 2026-10-13)

- The second job is the Google Ads report job; its deliverable is **figures only**.
- Scope: the job, plus **Group A** of the review #10 handoff, plus small Group B items only where the same
  code is already being changed.
- Build approach: **a true second job that reuses the audit's steps**, not a mode of the audit job.
- A report run reuses the audit's working folders, so it clears the previous run's step logs, as every audit
  already does. **Accepted**, and the runbook says so.
- Two internal labels keep their names (`vault_path`, `audits`) for both jobs.
- The report gets the audit's guard against a result that names another client.
- The change stays one change with one review; the follow-ups are built first so they can ship alone.

## What was read before this design (code at `main`, 2026-10-13)

- `bin/app_lib.py`: the manifest's key set is closed (`app, user, command, ops, tools, wait_seconds`);
  `_run_result` accepts only `/var/lib/hermes/vaults/<client>/audits/<ts>-audit.md`; `STEP_CLASSES` is the
  audit's list; `result_in_whitelist` takes no job.
- `bin/hermes-app-mcp.py`: the three tool descriptions are constants and describe an audit.
- `bin/run-client-audit.py`: `plan()` builds collect ×4, snapshot, read ×3, proxy, draft, vault-write; the
  run refuses unless the Anthropic key file holds a real key; `_run` resets `audit-data`, `reports`,
  `draft-out` and `audit-logs` for the client; `step_name()` calls every unrecognised step `vault-write`;
  the "collection worked" check is tied to the snapshot step; `STEP_CLASSES` is restated here.
- `docker-compose.yml`: the drafter mounts the client's whole vault and the `reports` working folder
  read-only; the gateway mounts `./registry` and `./skills/ads-audits`.
- `bin/collect-review-evidence.py`: one constant `APP = "ads-audit"` feeds D2.4, D4.6, D10.3, D10.4, D10.7
  and D10.8; D4.1 has a fixed list of paths; D2.3 and D10.7 read the journal with `-o cat` (message text
  only) and hold the whole text in memory; the customer-id count is a plain substring match.
- `bin/summarize-review-bundle.py`: the audit's broker is named in `SERVICES`.
- `deploy/BRING-UP.md`: "Chat-triggered audits, part 2" sets the job up by hand and by name; step 8
  (offboarding) lists the client's folders; the collection step redirects the bundle into a file the shell
  creates.
- `deploy/hermes-app-broker@.service`, `hermes-app-runner@.service`, `.path`, `bin/host_layout.py`
  (`app_layout`), `bin/hermes-app-broker.py`, `bin/hermes-app-runner.py`: already generic.
- The earlier decision of 2026-10-10 (design `2026-10-09-review-10-box-change-design.md`): the journal is
  read in **one call**, not in several.

## Part 1: the `ads-report` job

### What the operator sees

- Chat commands: `ads_report_run(client)`, `ads_report_status(request_id)`, `ads_report_list(client)`.
- Limits: one run per client per day, five per box per day, 60 lists per box per day; counted in the job's
  own ledger, separately from the audit's.
- Time limit of a run: 5,400 s. Worst case of the step limits: 4 × 900 + 3 × 300 + 120 = 4,620 s (77 min).
- An audit and a report never run at once: both take the existing lock, and the second gets `busy`.
- Off switch: `/var/lib/hermes/app-state/ads-report/DISABLED`.
- Reading: `sudo show-report <client> [--latest | --ts <ts> | --list]`.
- By hand: `sudo run-client-audit <client> --figures` (no separate run command is installed).

### The description file

`registry/apps/ads-report.json`: `app: ads-report`, `user: hermes-app-ads-report`, `command:
/usr/local/sbin/run-client-audit`, `run` with `args: ["--figures", "--json"]`, `timeout: 5400`,
`quota: {per_client_day: 1, per_box_day: 5}`; `list` with `args: ["--figures", "--list", "--json"]`,
`timeout: 60`, `quota: {per_box_day: 60}`; `wait_seconds: {run: 300, list: 60}`; plus the two new keys of
part 2.

### The figures mode of `run-client-audit.py`

- Client check: unchanged (`eligible_client`: registered, active, ten-digit customer id).
- Pre-checks: the Google credential file and the package pin, as today. The Anthropic key file is **not
  opened and not checked**; the vault is not checked.
- Steps: collect ×4, read ×3, store. No snapshot (its only consumer is the audit's history in the vault), no
  proxy, no draft, no vault-write.
- The check after collection (collector error files, or no data) is kept and no longer hangs on the snapshot
  step.
- Working folders: the audit's (`audit-data`, `reports`, `draft-out`, `audit-logs` under
  `/var/lib/hermes`), reset at the start of the run as today.
- `--list` in figures mode lists the report store, newest 24, and takes no lock.
- `--dry-run` works in figures mode and prints the plan.
- The JSON line keeps its six keys; `vault_path` holds the stored report's path.

### The store step

- A small program of its own, run as a step by root with a 120 s limit and its own step log.
- It reads the reader's output in `/var/lib/hermes/reports/<client>/`, a folder a container writes: every
  name is opened below the folder without following links, must be a regular file and is size-capped. It
  copies bytes and parses nothing. It expects exactly one file per reader, in the order of `READERS`.
- It joins them into one document with a heading per report.
- Before anything is written, the joined text is checked with `others_named`; a hit ends the run as
  `failed/isolation` and nothing is stored.
- It writes `/var/lib/hermes/report-archive/<client>/<ts>-report.md`, mode `0600`, root, atomically.
- The run reports `ok` only after the stored file is confirmed to be a regular file.

### The report store

- `/var/lib/hermes/report-archive`: `root:root 0700`, created once by the runbook. One folder per client,
  `root:root 0700`, created by the store step.
- No container mounts it, the gateway cannot see it, the drafter never reads it. That is why the reports are
  not kept in the client's vault: the drafter mounts the whole vault, and reports there would reach the AI
  step of later audits.
- Offboarding (BRING-UP step 8) removes `/var/lib/hermes/report-archive/<client>` with the other folders.

### `show-report`

`bin/show-report.py` and `deploy/show-report`, the twins of `show-audit`: root only, the same three options,
names opened below the store without following links, and control characters stripped from what is printed
(a report quotes search terms, which an outsider controls).

### The chat side

- `skills/ads-reports/SKILL.md`, the twin of the audit's: how to call the three tools, what to say for each
  status, never to retry a refusal, never to read report content.
- `docker-compose.yml`: one mount line for that folder in the gateway.
- `config.yaml.example`: a second server `ads_report` under `mcp_servers`, with the three tools, `env: {}`
  and `timeout: 360`.
- At rollout the gateway container is re-created once. Review #11 states it.

## Part 2: the template stops knowing the audit

### Two new keys in every description file

The manifest's key set stays closed and becomes eight keys. Both files change with the code, in one commit.

- `result`: where a run's result may live, as three closed fields: `root` (a name from a fixed table in the
  code: `vaults` or `report-archive`), `subdir` (`audits` or empty) and `suffix` (`-audit.md` or
  `-report.md`), each validated by a tight pattern. The manifest carries no free pattern and no path.
- `descriptions`: one line per tool (`run`, `list`, `status`), printable ASCII, length-capped. The MCP
  server reads them from the manifest; its constants go.

The audit's file gets values that reproduce today's rule exactly.

### The result checker

- `_run_result`, `map_done` and `result_in_whitelist` take the job's manifest and build the allowed path
  from `result`. The client in the path must still be the request's client and the timestamp the result's.
- `STEP_CLASSES` gains `store`. The list stays closed. It exists in `app_lib.py` and in
  `run-client-audit.py`; both change and a test holds them equal.
- `step_name()` names the store step explicitly; the fall-through to `vault-write` goes.

### Kept on purpose

- The result keys `vault_path` and `audits` keep their names for both jobs. Renaming them changes the live
  audit's answers and the stored results for no functional gain. The report's skill file says what they
  mean.
- The broker, the runner, the units, the spool, the ledger and the off switch are not changed.

### The runbook

"Chat-triggered audits, part 2" becomes "Add a chat-triggered job", with the job's name as a blank: the
account, the layout, the units, the chat settings, the tools check, the off switch, the first run and the
guarded live refusal blocks. It is rehearsed for both jobs in the stand-in before it reaches the box. A job
is added with its off switch on.

### Tests

- Every suite that loads `ads-audit.json` finds the manifests in `registry/apps/` itself.
- Results the audit produces today pass the new checker unchanged; a report result under the audit's rule,
  and an audit result under the report's, are refused.
- The end-to-end stand-in test runs both jobs.

## Part 3: the security review covers every job (checklist v1.20, 38 items)

No item is added. Each change extends an existing item.

- **The collector finds the jobs.** It reads `registry/apps/*.json` in the box's checkout and lists the
  installed `hermes-app-broker@*` and `hermes-app-runner@*` units. A job running without a description
  file, or a description file without its units, is a FAIL (D10.3).
- **Per job:** D10.3 (units, account, groups, sudo rules), D10.4 (layout), D10.7 (journal counts and leak
  counts) and D10.8 (results, checked with that job's manifest). The evidence carries one entry per job.
- **D2.4** reads every job's two journals. **D4.6** lists every job's broker.
- **A job installed since the last PASS.** Its journal is days old. v1.20 says: such a job is judged from
  its first journal entry, the report states its install date from the rollout record, and the three live
  refusals and the one `ok` run are still required.
- **D4.1:** `/var/lib/hermes/report-archive` joins the paths the gateway must not see.
- **D7.1:** the report store's parent is `root:root 0700`; each client folder is `root:root 0700`, of an
  active client, files `0600`; no running container mounts the store or a folder above it.
- **D10.1:** the probe also reports `figures_services`, the containers a figures plan would start, read
  from the same `plan()`. Expected: `ads-collector` and `ads-reader` only.
- **D10.6:** the title becomes "exactly six tools"; the pinned hash of the committed block is recomputed.
  The comparison itself already covers the whole block.
- **D10.7 and D10.8 expected sets** gain `failed/store`.
- **The summary tool, the board and REPORT-TEMPLATE** follow the per-job shape.
  `check-checklist-version.py` moves to v1.20.

Cost to the operator before each review: per job, the three live refusals (off switch, second run the same
day, malformed request) and one real run that returned `ok`, within 7 days of the collection.

The private helper that compares one review's bundle with the previous one (`review-10/tools/`, not in the
repository) needs a small adjustment for the new shape before review #11.

## Part 4: the follow-ups of review #10

### F59: the leak search reads every stored field

- D2.3 (whole journal) and D10.7 (each job's journals) read with `journalctl -o json --all`: every field,
  long fields included. A field that is not text arrives as a list of bytes and is decoded with
  replacement.
- **One call, consumed entry by entry.** This keeps the 2026-10-10 decision (one call, not several) and
  keeps memory flat whatever the size.
- Credential patterns and known secret values are searched in every field.
- The customer-id count (D10.7) skips a fixed list of the journal's own clock, counter and address fields
  (`__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP`, `__SEQNUM`, `_SOURCE_REALTIME_TIMESTAMP`,
  `_SOURCE_MONOTONIC_TIMESTAMP`; the plan fixes the list from the box's field names). A ten-digit id can
  match a long number there by chance. The checklist names the list; those fields are still searched for
  credentials.
- Counts only, as today, plus the number of entries and fields read. D10.7 also reports
  `undecodable_characters`, as D2.3 already does.
- The time limits are set from measurement M1 below.
- A hit is a finding. A credential is replaced before review #11. A customer id: the cause is fixed and the
  finding is decided on its own.

### The bundle is owner-only

When its standard output is a regular file, the collector sets that file to `0600` before it writes. The
shell still creates the file and the operator's account still owns it, so the copy to the laptop works as
today and the step cannot be forgotten. The laptop collector does the same. The runbook removes the box's
copy with `shred -u` (best effort on a virtual disk, as elsewhere in the runbook).

### The leftover journal directory

One block searches every directory under `/var/log/journal` other than the machine's own with the
all-fields search and prints counts only, never the directory's name. With zero hits and the expected
number of directories and files, a second block removes it, on the operator's word; all or nothing, as the
laptop deletion was. A hit stops the step and is a finding. This needs F59's code on the box first. After
it, D2.4's `other_directories` is 0 and the operator's statement about it is no longer asked.

### D4.6 reports the journal service

`started_at` and `started_after_last_pass` gain `systemd-journald`. No file check is made for it. An
automatic system update can restart it; the report then explains the restart in one line, as for any other.

### The runbook on `--last-pass-execstart`

The full value is in the last PASS's private box bundle, not in the public report, which shows it
abbreviated. The helper that reads it moves into the repository with tests
(`bin/last-pass-execstart.py`): it writes the one value to standard output for the clipboard, and nothing
else. The runbook pipes it to the clipboard; it is never shown on screen.

### Left deferred

The other items of the handoff's "Deferred from the build" list, and the other private helper scripts.

## Measurements on the box before the plan is written (read-only, by the operator, counts only)

- **M1:** the size in bytes and the seconds of one `journalctl -o json --all` read of the whole journal, and
  the days the journal holds. The box holds about 8 days today, not 35: the limit is the measured seconds
  scaled to 35 days, times ten, and never under 300 s.
- **M2:** the journal's field names (names only), to fix the skip list.
- **M3:** the number of other directories under `/var/log/journal` and of files in them.

## Testing

- Tests first, in `infra/hermes-agent/bin/run-bin-tests.sh` and the CI integration suites.
- A figures plan holds no drafter, no proxy, no vault-write and no Anthropic variable; the key file is never
  opened (a test that fails if it is).
- The store step: a planted link, a non-regular file, an oversized file, a missing report, another client's
  name; nothing is stored in each case.
- The all-fields search: a planted secret in `_CMDLINE`, in a long field and in a byte-list field is
  counted; a customer id inside a clock field is not; the 35-day size passes through the real runner.
- The bundle's mode: a redirected file ends `0600`; a pipe is untouched.
- An independent reviewer per task and one for the whole branch.

## Rollout and review #11

**Before the box:** M1 to M3; the plan; the build; the rehearsal of "Add a chat-triggered job" for both
jobs; the operator's word before a push; the operator merges.

**On the box, by the operator, block by block, each on the operator's word:**

1. Pull.
2. Restart what holds old code: the audit's broker, and any service a trial collection's D4.6 names.
   `sudo run-client-audit <client> --dry-run` shows the audit's plan unchanged.
3. Add the report job with its off switch on: account, layout, units, the report store, the chat settings
   (backup first), the gateway re-created, `show-report`. `hermes mcp list` shows two servers, six tools.
4. One chat audit returns `ok`.
5. The first report: `--dry-run`, then by hand, then the switch off and one by chat; read with
   `show-report`.
6. The live refusals for both jobs.
7. The leftover journal directory: search, then removal.

No new app package is built: the report uses the installed one, at the same pin.

**Undo:** each job's off switch; disable the report's units; restore the chat settings backup and re-create
the gateway; check out the previous commit and restart the audit's broker. Stored reports stay until the
operator says otherwise.

**Review #11:** checklist v1.20, 38 items, both jobs; F59 fixed, not accepted. The journal reaches 30 days
about 2026-11-04; a review before that passes D2.4 on the operator's stated date, as review #10 did. The
findings document's "Open items" list is brought up to date first.

## Out of scope

The write tier; packs for other platforms; a shared brain across projects; renaming `vault_path` and
`audits`; how long results and reports are kept; the rest of the deferred build items; the other private
helper scripts.

## Risks

| Risk | Answer |
|---|---|
| The shared checker changes under the live audit | Today's audit results pass the new checker in a test; rollout step 4; the undo |
| The description files and the code disagree during the pull | They change in one commit; the broker is restarted in step 2; the off switch |
| A report reaches the AI step of a later audit | The store is outside every mount; D7.1 and D4.1 measure it |
| Root reads files a container wrote | No link followed, regular files only, size cap, bytes copied and not parsed |
| A report run erases a failed audit's step logs | Accepted by the operator; the runbook says to read the logs first |
| The all-fields search is slow | M1 sets the limit; one call consumed entry by entry |
| The all-fields search gives a false customer-id hit | The skip list of clock and counter fields, named in the checklist |
| The all-fields search finds something real | A finding, handled before review #11 |
| The new job's journal is too young for the 30-day rule | v1.20's rule for a job installed since the last PASS |
| The first use of "Add a chat-triggered job" on the box | Rehearsed for both jobs; the job starts switched off |
| The change is large for one review | The follow-ups are built first and can ship alone |
| A retired client's reports stay on the box | Offboarding removes the folder; D7.1 fails on a retired row |
| The evidence shape changes between two reviews | The summary tool and the board follow; the private comparison helper is adjusted |
