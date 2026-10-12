# Design 2026-10-09: the review #10 box change (35 days of journal, and what a review can see of it)

Status: approved by the operator on 2026-10-10; amended the same day with the box measurements (M1 to M3),
the operator's choice on D2.3 and four corrections found while the plan was written (each marked
"2026-10-10"). Plan: `docs/superpowers/plans/2026-10-10-review-10-box-change.md`. Nothing is built. Client names are written as
`<client>`. This file carries no customer id, hostname, address, fingerprint or credential value.

## Goal

Close finding F58 and the follow-ups of security review #9 in one box change, judged by security review #10:

1. The box keeps at least 30 days of journal, and every review bundle says how far back the journal it read
   went.
2. The collector counts the sshd `Match` lines itself.
3. The report template carries the baselines the reviewer had to add by hand.
4. The runbook holds the corrected steps and the guarded live refusal checks.
5. The evidence file can show that the administrative key's passphrase is out of the macOS keychain.
6. A trial collection can no longer hide an item: a summary tool lists every item of a bundle.

Done means: review #10 passes on checklist v1.19, and a short journal can never again go unnoticed.

## Decisions made by the operator (2026-10-09)

- Scope: the six items of the handoff `2026-10-09-review-9-pass.md`, plus the summary tool (part 5).
- Retention: **35 days**. The 1G size cap stays.
- A journal shorter than 30 days at a review: **it needs the operator's explanation, and the checklist says
  which one counts** (part 2, pass rule). Not an automatic FAIL, not report-only.
- The server's own `/etc/systemd/journald.conf` is left untouched; our setting goes in a file of its own.
- **2026-10-10, D2.3:** the journal is NOT read in pieces. M2 measured the whole journal at 4.6 MB of text,
  read in 2 s; 35 days is about 23 MB on a box with 7.9 GB of memory. D2.3 keeps reading it in one call,
  with a longer limit, a test at the 35-day size and the size of the text reported. Reading in pieces
  would change how the leak check talks to the box for a problem this box does not have.

## What was measured or read before this design

- On the box, 2026-10-09 (`systemd-analyze cat-config systemd/journald.conf`): `SystemMaxUse=1G`,
  `MaxRetentionSec=7day` and `MaxFileSec=1day` are set in `/etc/systemd/journald.conf`;
  `/etc/systemd/journald.conf.d/` does not exist; the only drop-in is the distribution's
  `/usr/lib/systemd/journald.conf.d/syslog.conf`. 7 days of journal took 85.4M (read with `sudo`); the disk
  was 13% used.
- On the box, 2026-10-09 at about 13:35 UTC: the oldest entry of the whole journal was 2026-10-02 15:11 UTC,
  about 6 days 22 hours old. So entries leave up to a day BEFORE they are 7 days old: the journal is deleted
  a file at a time, and the files are a day long. One observation; the cause is reasoned, not measured.
- systemd v255 manual, `journald.conf` (source `man/journald.conf.xml` at tag v255, read 2026-10-09):
  `MaxRetentionSec=` defaults to 0 (off) and takes `day` as a unit; **`SystemMaxFiles=` defaults to 100**;
  `SplitMode=` defaults to `uid` (one set of files per user); `SystemMaxFileSize=` defaults to an eighth of
  `SystemMaxUse=`, capped at 128M; drop-in directories exist under `/etc/systemd`, `/run/systemd` and
  `/usr/lib/systemd`. The page does not state that a drop-in overrides the main file: that is measured
  (part 1, block 2).
- **On the box, 2026-10-10 12:43 UTC (M1 to M3, by the operator):** M1: 22 journal files, at most 4 with
  the same date, 14 `system` and 8 `user-1000`; one file is dated 2026-09-05 (the day the server image was
  made), older than the retention allows. M2: the whole journal is 4,630,823 bytes of text, read in 2 s;
  the broker's journal is 16 lines and the runner's 38. M3: Docker's logging driver is `json-file`, for
  the default and for the one container. systemd 255; 7940 MB of memory, 6589 MB available. The three
  live refusals were in the journal.
- **systemd v255 sources, read 2026-10-10:** `journal-vacuum.c` deletes an archived file when the time in
  its NAME (its first entry) is older than the retention, so an entry leaves up to one file-length (a day
  here) before it reaches the retention: this replaces "reasoned, not measured" above. The same function
  counts `SystemMaxFiles` and `SystemMaxUse` (512 bytes times the blocks of each file) over ONE directory,
  the machine's own. `journalctl` without `--merge` reads that directory only. So a file left in another
  directory (the likely place of the 2026-09-05 file: a server image keeps the journal of the machine it
  was built on) is neither trimmed nor read by the leak check; the plan's first task looks.
  `man/systemd-analyze.xml`: `cat-config` prints the file and its drop-ins "using the usual systemd set
  of directories and rules for precedence", so the precedence IS documented (the bullet above said it was
  not); it is still measured. `man/journalctl.xml`: `--lines=+N` shows the OLDEST N entries, which gives
  the oldest entry's time in one cheap call.
- In the collector: D2.3 reads the WHOLE journal in one call (`journalctl -o cat --no-pager`), holds it in
  memory, and the call has the default limit of 60 seconds. D10.7 reads two units' journals with
  `--since -30d`. Neither records how far back it read.

## Part 1: 35 days of journal on the box

### The file

A drop-in of our own, in the repository as `infra/hermes-agent/deploy/journald-hermes-retention.conf`,
installed as `/etc/systemd/journald.conf.d/50-hermes-retention.conf`, `root:root`, mode `0644`. It sets two
values in `[Journal]`:

- `MaxRetentionSec=35day`
- `SystemMaxFiles=<n>`

Why two: the box starts a new file every day and keeps a set of files per user, so 35 days needs more than
the default 100 files; at the default the journal would be trimmed before 35 days with nothing to say so.
`<n>` is not guessed. Measurement M1 (below) counts the files the box writes per day; `<n>` is three times
that count times 35, rounded up to the next hundred. **2026-10-10: M1 gave 4, so `<n>` is 500**
(3 x 4 x 35 = 420).

Considered and not chosen: editing the server's file (a provider or image update could overwrite it, and the
undo needs the old text); sending the journal off the box (far more than the problem needs).

### Two measurements on the box before the plan is written (read-only, by the operator)

- **M1:** the number of journal files, and the number written per day (a listing of `/var/log/journal`,
  counts only).
- **M2:** how long reading the whole journal takes and how many bytes it is
  (`journalctl -o cat --no-pager | wc -c`, timed), and the same two numbers for the two unit journals D10.7
  reads. Part 2 sizes D2.3's limit from it, and gives D10.7's calls the same treatment if they are not small.
- **M3:** Docker's logging driver (`docker info --format '{{.LoggingDriver}}'`). The repository sets none, so
  Docker's default (`json-file`) is expected. If it is `journald`, the containers log THROUGH the service this
  change restarts: stop, and settle that in the design before any plan.

### The runbook step (BRING-UP, new), four blocks

1. **Look** (read-only): the settings in force and the file each comes from; the oldest entry of the whole
   journal; the file count and the disk use; Docker's logging driver (as M3: not `journald`); the three live
   refusal counts in the broker's journal.
2. **Install and check on paper:** install the file, then `systemd-analyze cat-config` again. The journal
   service has not been told anything yet. STOP unless the output shows `MaxRetentionSec=35day` and our
   `SystemMaxFiles`, each set last by our file.
3. **Apply:** `systemctl restart systemd-journald`. Then: the service is active; the oldest entry equals
   block 1's (nothing was lost); a fresh entry from each Hermes service unit can be read (they still log);
   the listener check's next run records `ok`.
4. **Undo** (written out, used only if needed): remove the file, restart the service, repeat block 1.

On a fresh server the step sits after the units are installed and before the first review.

### Rehearsal

The laptop is a Mac and the stand-in server of earlier rehearsals has no systemd. The rehearsal is a
throwaway Linux container on the laptop that runs `systemd-journald`: the drop-in installed, `cat-config`
read, the service restarted, an entry written before the restart read after it. If such a container cannot be
made to run on this laptop, the fallback is the manual above plus block 2, which is a measurement on the box
taken before anything is applied. The evaluation record (part 4) says which of the two it was.

## Part 2: the collector and the checklist (v1.19, 38 items, 31 box probes)

### New item D2.4 — the journal reaches as far back as the leak checks assume

The collector reports, with no journal line and no name:

- `oldest_entry`: the time of the oldest entry of the whole journal, and of each unit whose journal D10.7
  reads (`hermes-app-broker@ads-audit`, `hermes-app-runner@ads-audit`);
- `settings`: `MaxRetentionSec`, `SystemMaxUse`, `SystemMaxFiles` and `MaxFileSec` as
  `systemd-analyze cat-config` gives them, each with the file that sets it last;
- `drop_in`: whether `/etc/systemd/journald.conf.d/50-hermes-retention.conf` equals the repository's file
  (one sha256 for both), and the names of every other file in that directory;
- `usage`: the bytes the journal uses, the number of its files, and the free space of the file system it is
  on (bytes and per cent). 2026-10-10: counted in the machine's own directory, as the service counts; the
  number of OTHER directories under `/var/log/journal` is reported beside it;
- `service` (added 2026-10-10): when `systemd-journald` started, and whether any settings file is newer
  than that start. `cat-config` reads the FILES; the running service read them when it started. Without
  this, a file installed and never applied would look "in force";
- `reach_days` (added 2026-10-10): whole days between the oldest entry and the collection.

The time settings are converted to seconds (the manual's units: `year`, `month`, `week`, `day`, `h`, `m`, and
a bare number of seconds); a value that cannot be converted is `could-not-check`, never a guess.

**Pass rule.**

- `MaxRetentionSec` in force is at least 30 days, is set last by our file, the file equals the repository's,
  and the directory holds no other file.
- `oldest_entry` of the whole journal is at least 30 days before the bundle's `collected_at`. If it is not,
  the operator states the date the retention was raised, and the oldest entry must be at least 5 days before
  that date (the box held 6 to 7 days at the time). Any other short journal is CANNOT-VERIFY.
- `usage` at 90% or more of `SystemMaxUse`, a file count at 90% or more of `SystemMaxFiles`, or free space
  under 20% of the file system (the service keeps 15% free by default, `SystemKeepFree=`), is CANNOT-VERIFY
  unless the operator explains it: at a limit, the journal is being trimmed.
- A value the collector could not read is `could-not-check`, as everywhere.
- 2026-10-10: a settings file newer than the service's start is CANNOT-VERIFY (the service runs older
  settings than the files show). A directory other than the machine's own under `/var/log/journal` needs
  the operator's statement of what it is. The checklist states one limit plainly: the oldest entry shows
  how far back the journal BEGINS, not that it is unbroken; the settings, the service's start and the three
  limits are what show nothing is being trimmed.

### D2.3 and D10.7 say what they covered

Each adds `oldest_entry_read`: the time of the oldest entry in the text it scanned. No pass rule of its own;
D2.4 judges the reach.

### D2.3 must finish on a journal five times longer

As decided on 2026-10-10 (the piece-by-piece reading of the first draft is dropped):

- The call gets a limit sized from M2: ten times the measured seconds times five (100 s), and never under
  300 s. So 300 s.
- D2.3 reports `scanned_characters`, the size of the text it searched, so growth is seen review by review.
- Tests: a simulated journal of the 35-day size (five times M2's bytes) with a planted secret and a planted
  credential pattern at its far end; both are counted, and the search itself ends well inside the limit.
  One test passes that much text through the collector's real command runner.
- The counts D2.3 reports keep their names and meaning.

### D1.7 counts the `Match` lines

- `match_lines`: the count of `Match` lines in `/etc/ssh/sshd_config` and `/etc/ssh/sshd_config.d/*.conf`
  (the two places the operator's command read).
- `include_elsewhere`: the count of `Include` lines in those files that name a path outside
  `/etc/ssh/sshd_config.d/` (a `Match` there would not be counted).
- Pass rule: both `0`; another number needs the operator's statement of what each block or file sets.
- The reader's two known false alarms are repaired, each with a test: an unbalanced double quote in a key's
  comment, and a CR line ending. Both fail on the safe side today. 2026-10-10: neither was ever measured
  against a real `sshd` (they come from a reading of its source), so the plan measures each first and
  repairs only a line `sshd` really accepts.

### Unchanged

D10.7's rule that the three live refusals are in the journal within 30 days. D10.8's rule that one `run`/`ok`
result is on the box: the broker deletes a result 7 days after writing it, so each review still starts with
one chat audit.

## Part 3: documents and the laptop check

- **`REPORT-TEMPLATE.md`:** header lines for D4.2's `execstart_sha256` and `execstart_argv_sha256`, D4.5's
  `alert_log`, D2.4's `oldest_entry` and retention in force, and D1.7's `match_lines`.
- **`REVIEWER-BRIEF.md`:** the evidence file also holds the date the retention was raised (when D2.4 needs
  it) and the laptop keychain check; item 7's list of baselines gains the new header lines.
- **`BRING-UP.md`:**
  - the new journal step (part 1);
  - part 2 step 11: the guarded live refusal blocks used on 2026-10-09 (the client at a hidden prompt, only
    `status=… reason=…` printed, the kill switch left ON when the broker does not answer, the quota request
    placed only when the broker's counter says exactly 1), and the closing check;
  - "running a review": the journal's reach is read before collecting; a value pasted at a prompt on the box
    is copied in a second laptop window AFTER the block is pasted; every screen and every paste is read
    before it becomes evidence; the trial collection goes through the summary tool (part 5);
  - the rollout's corrections: LAPTOP 4c also prints two `state = active` lines on this macOS; LAPTOP 5c's
    first and third lines carry the key's path and are not pasted; the "first run on this laptop / not
    rehearsed" marks give way to what was measured on the box on 2026-10-08.
- **The laptop keychain check,** one block for the evidence file, made of step 7f's own commands as measured
  on this Mac, printing counts only:
  - the `UseKeychain` lines left in `~/.ssh/config` (expected `0`), read-only;
  - which alias the login item's `ssh` runs on (new alias `1`, old alias `0`), read-only;
  - `ssh-add --apple-load-keychain`, then whether the administrative key is in the agent (expected `0`).
    This one is an active test, not a read: if it ever printed `1` it would itself have loaded the key, so
    the block then removes it from the agent and tells the operator to stop.
- **Findings document:** F58 with its fix, once the step has run on the box.

## Part 4: the record of sources

`docs/evaluations/2026-10-10-journal-retention-35-days.md`: each manual page used, the date read and what it
confirmed; M1 and M2; the rehearsal (container, or the fallback) with its output; the box's values before
and after the step.

## Part 5: the summary tool (added to the scope by the operator on 2026-10-09)

`infra/hermes-agent/bin/summarize-review-bundle.py`: reads a box bundle on stdin or from a path and prints:

- **every item of the bundle with its status**, known to the tool or not;
- for each item the tool knows, only fields on a fixed list: counts, booleans, labels and times. Never a
  fingerprint, a path or free text. An unknown item gets its status and nothing else;
- a closing list, "before the real collection": every item observed; D10.7's three refusal counts present;
  D10.8 holds at least one `run`/`ok`; D2.4's reach and settings as part 2 expects; D4.2 matches the last
  PASS; D4.6 names no file newer than a service's start. Reminders, not verdicts.

Tests: a bundle with a secret-shaped value planted in every field prints none of it; a bundle with an item
the tool does not know still lists that item; a bundle missing a refusal count says so in the closing list.

The tool is a new file under `bin/`, so it is on the box and in the fingerprint. It replaces the script
pasted from the handoff of 2026-10-07.

## Rollout and review #10

**Before the box:** M1 and M2; the plan; the build with tests first; the rehearsal; an independent review by
an agent that did not build it; the operator's word before a push; the operator merges.

**On the box, by the operator, block by block:**

1. Pull.
2. A trial collection through the summary tool. D4.6 says whether a running service loads a changed file.
   None is expected: the changed files are the collector, the summary tool and the drop-in, which no running
   service loads. If one is named, restart that service, as in the review #9 rollout.
3. The journal step: look, install and check on paper, apply, verify.

The restart of `systemd-journald` is not among the starts D4.6 reports, so the operator states it in the
evidence.

**Review #10:** one chat audit; the trial collection through the summary tool; the real collection; the
laptop bundle; the console screens (a filled rectangle on the keys list); the evidence file with the date the
retention was raised and the keychain check; a fresh reviewer; both bundles and the sign-off on the same UTC
day. `review-10/previous-pass-header.md` is made from review #9's report, whose header carries the baselines.

**Timing.** The live refusals of 2026-10-09 (13:45 to 13:57 UTC) are in a journal file that leaves the box
at the daily trim on its seventh or its eighth day: between **2026-10-15 and 2026-10-16, about 15:00
UTC** (the file list of 2026-10-10 does not settle which; plan for the 15th). If the journal step is applied before then, they stay for 35 days and need not be repeated for
review #10; block 1 reads the three counts so this is seen, not assumed. If they are gone, step 11 is run
again first. The handoff's "2026-10-16" is corrected with this design.

## Out of scope

The "confirm this canon entry is still true" action for the brain; raising the 1G cap; sending the journal
off the box; a notification when the listener check alerts (F54); excluding the proxy and the mutation broker
from automatic restarts (F55); how long the broker keeps a result; the `brain-weekly-review` skill writing
`reviewed_at`.

## Risks

| Risk | Answer |
|---|---|
| The drop-in does not override the server's file | Block 2 reads the settings in force before the service is told anything, and stops |
| Restarting the journal service loses entries or disturbs a service | Rehearsed first; block 3 compares the oldest entry and reads a fresh entry from each Hermes unit; the undo is one file |
| The size cap, the file limit or the free-space reserve trims the journal before 35 days | `SystemMaxFiles` set from M1; D2.4 reports use against all three and cannot pass at a limit |
| The containers log through the journal service and lose their logging when it restarts | M3 and block 1 read Docker's logging driver first; `journald` there stops the step |
| D2.3 runs out of time or memory on a longer journal | Its limit is sized from M2 (300 s); 35 days is about 23 MB of text; tested at that size; `scanned_characters` shows growth |
| The settings files say 35 days and the running service still applies 7 | D2.4 `service`: the service's start is compared with every settings file's time |
| An old file outside the machine's own journal directory is neither trimmed nor searched | The plan's first task looks; D2.4 reports the count of other directories |
| The rehearsal container cannot run the journal service on this laptop | The manual plus block 2 on the box; the evaluation record says which it was |
| Client short names stay in the journal for 35 days instead of 7 | Permitted by the policy on the box's journal (F21); stated here so it is a choice |
| The summary tool prints something it should not | A fixed list of fields per item; the planted-secret test |
| An entry leaves up to a day early (file granularity) | 35 days leaves 34 whole days for a 30-day rule |
