# Review #10 box change: 35 days of journal, and what a review can see of it — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> One change, one fingerprint change, one security review (#10). Build order: this plan, an implementer, an
> independent review, then ask the operator before pushing. Tasks 0, 13 and 14 are the operator's, block by
> block; the build runs nothing on the box.
>
> **Operator blocks in this file are drafts.** The blocks to run on the box are ONLY those in
> `infra/hermes-agent/deploy/BRING-UP.md` once Task 11 has rehearsed them. (The review #9 plan's drafts were
> replaced after rehearsal; do not paste from a plan.)
>
> **The code in Tasks 4 to 9 was tried before this plan was shown** (2026-10-10, on a scratch copy of `bin/`,
> on the laptop): the collector's suite ran 304 tests with every new test passing and one older test needing
> the change Task 4 names; the summary tool's 9 tests pass. That is a check of the plan, not the build: the
> implementer still writes each test first and watches it fail. What the laptop cannot show (systemd's real
> output) is measured in Tasks 0, 1, 2 and 7.

**Goal:** Close finding F58 (the box kept 7 days of journal while the checklist assumed 30) and review #9's
follow-ups in one box change, so that security review #10 can judge it on checklist v1.19.

**Architecture:** One settings file of our own for the journal service (a drop-in; the server's file is not
touched). One new probe in the box collector (`d2_4`) that reports the journal's reach, the settings and the
file that sets each, whether the running service has read them, and how near the journal is to its limits.
Three existing probes report more (`d1_7`, `d2_3`, `d10_7`). One new read-only tool prints a safe summary of
a bundle. The runbook gains the journal step, the guarded live refusal checks and a laptop keychain check.

**Tech Stack:** Python 3 stdlib only (`unittest`, `json`, `re`, `os`), bash runbook blocks, systemd 255
(`journald.conf` drop-ins, `journalctl`, `systemd-analyze cat-config`), Docker on the laptop for two
rehearsals.

**Spec:** `docs/superpowers/specs/2026-10-09-review-10-box-change-design.md` (approved 2026-10-10, amended the
same day; the amendments are marked "2026-10-10" in it).

## Global Constraints

- Python stdlib only. No value of any secret is ever printed, logged or written: names, labels, ports, counts,
  times and fixed words only. What cannot be measured is `could-not-check`, never a healthy-looking value.
- No client name, customer id, hostname, non-loopback address, machine id, full fingerprint or credential
  value in any file, commit message or conversation. Client names are written `<client>`.
- The server's own `/etc/systemd/journald.conf` is never edited. Our file is
  `infra/hermes-agent/deploy/journald-hermes-retention.conf`, installed as
  `/etc/systemd/journald.conf.d/50-hermes-retention.conf`, `root:root`, mode `0644`, and sets exactly
  `MaxRetentionSec=35day` and `SystemMaxFiles=500` under `[Journal]`. The 1G size cap stays.
- D2.3 reads the whole journal in ONE call (operator's decision, 2026-10-10). No piece-by-piece reading, no
  new call on the collector's `Host`.
- `CHECKLIST.md` goes to `version: 1.19` (38 items, 31 box probes); every bullet of an item stays one line;
  `python3 infra/hermes-agent/bin/check-checklist-version.py --base main` exits 0.
- The D10.6 pinned `mcp_servers` canonical sha256 must not change.
- The agent never reads a `.env` file and never runs a shell command that names one (the project's
  secret-read guard).
- The agent cannot reach the box (`ssh hermes-box` asks for a passphrase): every box block is the operator's.
  The box runs fail2ban: nothing may retry a login that fails.
- Before every commit that touches `infra/hermes-agent/`: `infra/hermes-agent/bin/run-bin-tests.sh`,
  `python3 infra/hermes-agent/deploy/units.test.py`, `python3 infra/hermes-agent/deploy/provision.test.py` and
  `node scripts/run-all-tests.js` pass.
- Commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Branch `feat/review-10-box-change`
  (exists; it holds the design and this plan). No push, no PR, without the operator's word; the operator
  merges. Before every commit: the hidden-name search of the 2026-10-09 handoff's appendix is the operator's;
  the agent reads `git diff --cached` as its own step and commits only after reading it.
- Operator blocks: one block per paste, labelled VPS or LAPTOP; `sudo -v` alone first; a block that prompts
  is pasted alone. Ask for output "starting after the prompt line". Every block states what to expect and
  when to stop.
- Sources and measurements go in `docs/evaluations/2026-10-10-journal-retention-35-days.md`.

## Review Focus

Conditions the spec implies and a person will meet. Each has a test or a measured step in the named task.

1. **A settings file is installed and the journal service is never restarted:** the files say 35 days, the
   running service still applies 7. D2.4 must say so, not show a healthy setting. Task 7,
   `test_a_settings_file_newer_than_the_service_start_is_reported`.
2. **A journal with no entry for a unit, or none at all** (a new unit, a fresh box): `null`, never a crash and
   never a made-up time. Task 6, `test_no_entry_is_none_and_a_failure_is_could_not_check`.
3. **A settings value the collector cannot convert** (`MaxRetentionSec=1 fortnight`, an empty assignment, a
   setting written outside `[Journal]`, `Key = value` with spaces): `could-not-check` or ignored exactly as
   systemd would, never a guess. Task 6, `test_spans_sizes_and_what_cannot_be_converted` and
   `test_only_journal_section_lines_count_and_the_last_file_wins`.
4. **Our file is missing, differs from the repository's, or has a neighbour in its directory:** each is
   visible in `drop_in`. Task 7, `test_a_missing_a_different_and_a_neighbouring_file_are_each_visible`.
5. **The summary tool is given something that is not a bundle** (empty input because the collector refused,
   a bundle whose item has no `data`, a value of the wrong type): one plain line and exit 2, or the item's
   status alone; never a traceback, never a value it does not know. Task 9,
   `test_not_a_bundle_is_one_line_and_exit_2` and `test_a_secret_planted_in_every_field_is_never_printed`.

---

### Task 0: One read-only look at the box (operator)

Nothing changes on the box. It settles three things the build depends on: where the journal file dated
2026-09-05 is, that the box's `journalctl` gives the oldest entry in one call, and the exact form of the
settings printout.

- [ ] **Step 1 (VPS, after `sudo -v` alone):** give the operator this block. Its output holds no host name,
  no directory name and no journal line.

```bash
sudo sh -c 'M=$(cat /etc/machine-id); for d in /var/log/journal/*/; do n=$(basename "$d"); echo "journal dir: own=$([ "$n" = "$M" ] && echo yes || echo no) files=$(ls "$d" | wc -l) dates=$(ls -l --time-style=+%F "$d" | awk "NR>1{print \$6}" | sort | sed -n "1p;\$p" | tr "\n" " ")"; done
echo "oldest, whole: $(journalctl -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1 | grep -oE "\"__REALTIME_TIMESTAMP\":\"[0-9]+\"")"
echo "oldest, broker 30d: $(journalctl -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1 -u hermes-app-broker@ads-audit --since -30d | grep -oE "\"__REALTIME_TIMESTAMP\":\"[0-9]+\"")"
echo "oldest, no such unit: [$(journalctl -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1 -u hermes-no-such-unit; echo rc=$?)]"
systemd-analyze cat-config systemd/journald.conf | grep -nE "^# /|^\[|^[A-Za-z]+[[:space:]]*="
echo "journal service started: $(systemctl show systemd-journald -p ActiveEnterTimestamp --value)"'; date -u
```

Expected: one or two `journal dir:` lines (one `own=yes` with about 21 files; possibly one `own=no` with one
file dated `2026-09-05`); two lines each holding `"__REALTIME_TIMESTAMP":"<16 digits>"`; `[rc=0]` or
`[rc=1]` with nothing before `rc`; the settings printout's file headers (`# /etc/systemd/journald.conf`,
`# /usr/lib/systemd/journald.conf.d/syslog.conf`), `[Journal]` and the `Name=value` lines; a start time
ending `UTC`; the date.

- [ ] **Step 2:** record the output in `docs/evaluations/2026-10-10-journal-retention-35-days.md` (created in
  Task 1), section "The box, read-only". Then apply these rules:
  - A `journal dir: own=no` line: the 2026-09-05 file is in another machine's directory. Ask the operator,
    with a recommendation: leave it and state it in review #10's evidence (recommended: it predates every
    credential on the box, and deleting it is one more change to explain), or delete it in Task 13.
  - No `own=no` line, and `own=yes` shows a date of `2026-09-05`: the old file is in the machine's own
    directory. Record it; D2.4's `usage.files` then counts it, which is correct (the service counts it too).
  - Either `oldest` line empty, or an error: **stop.** Task 6's command does not work on the box as the
    manual says. Report it to the operator before Task 6; do not build around it.
  - A header line that is not `# ` followed by a path under `/etc/systemd`, `/run/systemd`,
    `/usr/lib/systemd` or `/usr/local/lib/systemd`: **stop** and report it (Task 6's parser reads that form).

---

### Task 1: Rehearse the journal step in a throwaway container

**Files:**
- Create: `docs/evaluations/2026-10-10-journal-retention-35-days.md`
- Scratch only (not committed): `$SCRATCH/journald-rehearsal/Dockerfile`

**Interfaces:**
- Produces: the image `journald-rehearsal` and the running container `jr`, used again in Tasks 7 and 11. The
  measured answers R1 to R6, which Tasks 6, 7 and 11 quote.

`$SCRATCH` is the session's scratchpad directory, `$REPO` the repository root.

- [ ] **Step 1: Build and start a container that runs systemd and its journal service.**

```bash
mkdir -p "$SCRATCH/journald-rehearsal" && cd "$SCRATCH/journald-rehearsal" && cat > Dockerfile <<'EOF'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv python3 bsdutils && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /var/log/journal && printf '[Journal]\nStorage=persistent\nSystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n' > /etc/systemd/journald.conf
RUN printf '[Unit]\nDescription=ticker\n[Service]\nExecStart=/bin/sh -c "while :; do echo tick; sleep 1; done"\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/ticker.service && systemctl enable ticker.service
CMD ["/sbin/init"]
EOF
docker build -q -t journald-rehearsal . && docker run -d --name jr --privileged --cgroupns=host --tmpfs /run --tmpfs /run/lock -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$REPO":/opt/projects/claude_code:ro journald-rehearsal
sleep 8; docker exec jr sh -c 'systemctl --version | head -1; systemctl is-active systemd-journald ticker'
```

Expected: `systemd 255 (…)`, `active`, `active`. **If the container does not reach that state** (Docker on
this Mac refuses a privileged systemd): try once more without `--cgroupns=host`. If it still fails, the
rehearsal is the fallback the design names: write in the evaluation record "no container: the manual pages
plus block 2 of the runbook step on the box", skip Steps 2 to 5, and tell the operator before Task 11.

- [ ] **Step 2: R1, R2 — the settings printout before anything is installed.**

```bash
docker exec jr systemd-analyze cat-config systemd/journald.conf
```

Record the whole output. Expected first line `# /etc/systemd/journald.conf`, then the file; any further file
after an empty line and its own `# /path` line.

- [ ] **Step 3: R3, R4 — install our file, read the settings, restart, compare.** (Run after Task 3 has
  created the file; until then use `printf '[Journal]\nMaxRetentionSec=35day\nSystemMaxFiles=500\n'` in its
  place and say so in the record.)

```bash
docker exec jr sh -c '
install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d
install -o root -g root -m 0644 /opt/projects/claude_code/infra/hermes-agent/deploy/journald-hermes-retention.conf /etc/systemd/journald.conf.d/50-hermes-retention.conf
systemd-analyze cat-config systemd/journald.conf | grep -nE "^# /|^(MaxRetentionSec|SystemMaxFiles)[[:space:]]*="
B=$(journalctl -q --no-pager -o short-iso --no-hostname -n +1 | cut -c1-24); N=$(journalctl -q -u ticker -o cat --no-pager | wc -l)
systemctl restart systemd-journald; sleep 5
A=$(journalctl -q --no-pager -o short-iso --no-hostname -n +1 | cut -c1-24)
echo "service: $(systemctl is-active systemd-journald) | oldest before: $B | after: $A | ticker lines before: $N | after: $(journalctl -q -u ticker -o cat --no-pager | wc -l) | ticker: $(systemctl is-active ticker)"'
```

Expected: the last `MaxRetentionSec=` line is `35day` and stands under
`# /etc/systemd/journald.conf.d/50-hermes-retention.conf`; `service: active`; the two oldest times equal;
more ticker lines after than before; `ticker: active` (a long-running service keeps logging through the
restart). Record every line. Anything else: record it and stop; the runbook step is not safe as designed.

- [ ] **Step 4: R5 — the collector's three `journalctl` forms.**

```bash
docker exec jr sh -c 'O="-q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1"
echo "whole: $(journalctl $O)"; echo "unit, 30d: $(journalctl $O -u ticker --since -30d)"; echo "no such unit: [$(journalctl $O -u no-such-unit)] rc=$?"
journalctl -q --no-pager -o short-iso --no-hostname | head -1 | cut -c1-24'
```

Expected: two one-line JSON objects holding only `__CURSOR`, `__REALTIME_TIMESTAMP`,
`__MONOTONIC_TIMESTAMP` and `_BOOT_ID` (no message, no host name); `[]` for the unit that does not exist; and
the `whole` timestamp is the same instant as the last line's time. Record the output with the cursor and boot
id cut out. **If `-n +1` with `-u … --since` does not give the oldest entry inside the window:** in Task 8
D10.7's two calls drop `--since -30d` (the unit's oldest entry, whatever its age), and D10.7's checklist text
says "the oldest entry of that journal" instead of "inside the 30 days read". Record which form was used.

- [ ] **Step 5: R6 — the override is in force, with a control.** Two fresh containers from the same image,
  each with the server's retention set to 3 minutes so that the effect can be seen in minutes:

```bash
for c in control treated; do docker run -d --name jr-$c --privileged --cgroupns=host --tmpfs /run --tmpfs /run/lock -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$REPO":/opt/projects/claude_code:ro journald-rehearsal; done; sleep 8
docker exec jr-treated sh -c 'install -d /etc/systemd/journald.conf.d && install -m 0644 /opt/projects/claude_code/infra/hermes-agent/deploy/journald-hermes-retention.conf /etc/systemd/journald.conf.d/50-hermes-retention.conf'
for c in control treated; do docker exec jr-$c sh -c 'sed -i "s/^MaxRetentionSec=.*/MaxRetentionSec=3min/" /etc/systemd/journald.conf && systemctl restart systemd-journald && sleep 2 && logger REHEARSAL-MARK && journalctl --rotate'; done
for i in 1 2 3 4 5 6; do sleep 60; for c in control treated; do docker exec jr-$c journalctl --rotate; done; done
for c in control treated; do echo "$c: marks left $(docker exec jr-$c sh -c 'journalctl -q --no-pager -o cat | grep -c REHEARSAL-MARK')"; done
docker rm -f jr-control jr-treated >/dev/null
```

Expected: `control: marks left 0` (the server's 3 minutes applied: the mark's file was deleted) and
`treated: marks left 1` (our file's 35 days overrode it). Record both. If `control` is not `0`, the
experiment proves nothing: record that, and say in the record that the override rests on Step 3's printout
and the manual alone.

- [ ] **Step 6: Write the evaluation record.** `docs/evaluations/2026-10-10-journal-retention-35-days.md`,
  in the form of `docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`:
  a header (date, what was asked, method), then:
  1. **Sources** (a table: source, authority, what it verified, date read). Rows: systemd v255
     `man/journald.conf.xml` (the settings, their defaults, the units; read 2026-10-09);
     `man/systemd-analyze.xml` (`cat-config` and its precedence sentence; 2026-10-10); `man/journalctl.xml`
     (`--lines=+N`, `--output-fields=`; 2026-10-10); `src/libsystemd/sd-journal/journal-vacuum.c` (a file is
     deleted when the time in its name is older than the retention; the file and size limits are counted in
     one directory; 2026-10-10); `src/shared/pretty-print.c` (the `# <path>` header, an empty line before
     every file but the first; 2026-10-10); `src/basic/time-util.c` (the time units; 2026-10-10). Each with
     its URL at tag `v255` on github.com/systemd/systemd.
  2. **The box, read-only:** the design's 2026-10-09 values, M1 to M3 (2026-10-10 12:43 UTC), Task 0's output.
  3. **The rehearsal:** R1 to R6 with their outputs, or the fallback sentence.
  4. **What is not measured:** 35 real days; the box's own restart of the journal service (Task 13 is the
     first); `hermes-broker` and `hermes-docker-proxy` logging after the restart (only the audit broker has a
     safe trigger).

- [ ] **Step 7: Commit.**

```bash
git add docs/evaluations/2026-10-10-journal-retention-35-days.md
git commit -m "docs(evaluations): 35 days of journal, sources and the rehearsal of the restart"
```

---

### Task 2: Measure the two key-line cases against a real sshd

D1.7's reader counts two kinds of line as unreadable that `sshd` is believed to accept. The belief comes from
reading `sshd`'s source during the review #9 build; it was never measured. Measure before touching the parser.

**Files:**
- Modify: `docs/evaluations/2026-10-10-journal-retention-35-days.md` (a section "The key reader's two cases")

**Interfaces:**
- Produces: for each of four lines, `accepted` or `refused`. Task 5 repairs only an `accepted` case.

- [ ] **Step 1: A throwaway server with the box's OpenSSH release** (`OpenSSH_9.6p1`, as `ubuntu:24.04`
  ships; confirmed for the box on 2026-10-08).

```bash
cd "$SCRATCH" && mkdir -p sshd-cases && cd sshd-cases && for k in a b c d; do ssh-keygen -q -t ed25519 -N '' -C '' -f k$k; done
docker run -d --name sshd-cases -p 127.0.0.1:2222:22 ubuntu:24.04 sh -c 'apt-get update -qq && apt-get install -y -qq openssh-server >/dev/null 2>&1 && mkdir -p /run/sshd /home/u/.ssh && useradd -d /home/u -s /bin/bash u && sleep infinity'
until docker exec sshd-cases test -x /usr/sbin/sshd; do sleep 3; done
B() { cut -d' ' -f2 "k$1.pub"; }
{ printf 'ssh-ed25519 %s com"ment\n' "$(B a)"; printf 'no-pty ssh-ed25519 %s com"ment\n' "$(B b)"; printf 'ssh-ed25519 %s\r\n' "$(B c)"; printf 'ssh-ed25519 %s plain\n' "$(B d)"; } > authorized_keys
docker cp authorized_keys sshd-cases:/home/u/.ssh/authorized_keys
docker exec sshd-cases sh -c 'chown -R u:u /home/u && chmod 700 /home/u/.ssh && chmod 600 /home/u/.ssh/authorized_keys && ssh -V 2>&1 | cut -d, -f1 && /usr/sbin/sshd'
for k in a b c d; do ssh -i k$k -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p 2222 u@127.0.0.1 true 2>/dev/null && echo "$k: accepted" || echo "$k: refused"; done
ssh-keygen -q -t ed25519 -N '' -C '' -f kx && ssh -i kx -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p 2222 u@127.0.0.1 true 2>/dev/null && echo "x: accepted" || echo "x: refused"
docker rm -f sshd-cases >/dev/null
```

Cases: `a` a key first, its comment holding one double quote; `b` an option first, the same comment; `c` a
key with no comment and a carriage return before the line break; `d` a plain line (control: must be
`accepted`); `x` a key that is not in the file (control: must be `refused`).

- [ ] **Step 2: Record** the five lines and the server's version line in the evaluation record. If `d` is
  not `accepted` or `x` is not `refused`, the measurement is void: fix the set-up, do not go on.

- [ ] **Step 3: Commit.**

```bash
git add docs/evaluations/2026-10-10-journal-retention-35-days.md
git commit -m "docs(evaluations): the key reader's two false-alarm cases, measured against sshd 9.6p1"
```

---

### Task 3: The settings file

**Files:**
- Create: `infra/hermes-agent/deploy/journald-hermes-retention.conf`
- Test: `infra/hermes-agent/deploy/units.test.py`

**Interfaces:**
- Produces: the file Task 7's `JOURNALD_DROP_IN_REPO` names and Task 11's runbook installs.

- [ ] **Step 1: Write the failing test.** In `units.test.py`, above the `if __name__ == "__main__":` line:

```python
class TestJournalRetentionDropIn(unittest.TestCase):
    """The file says what the design says. That systemd applies it is measured, not tested here:
    docs/evaluations/2026-10-10-journal-retention-35-days.md."""

    def test_it_sets_exactly_two_values_under_journal(self):
        self.assertEqual(live_lines(unit("journald-hermes-retention.conf")),
                         ["[Journal]", "MaxRetentionSec=35day", "SystemMaxFiles=500"])
```

- [ ] **Step 2: Run it.** `python3 infra/hermes-agent/deploy/units.test.py TestJournalRetentionDropIn -v`
  Expected: an error, `No such file or directory`.

- [ ] **Step 3: Create the file.**

```ini
# Hermes: the box keeps 35 days of journal (finding F58). Security review item D2.4 compares the
# installed file with this one, byte for byte.
# Installed as /etc/systemd/journald.conf.d/50-hermes-retention.conf (root:root 0644) by
# deploy/BRING-UP.md, "The journal's retention". The server's own /etc/systemd/journald.conf is
# left as it is: a file in this directory is read after it and overrides it.
# SystemMaxFiles: the box writes up to 4 journal files a day (measured 2026-10-10); systemd's
# default limit of 100 files would trim the journal before 35 days. 3 x 4 x 35 = 420, so 500.
[Journal]
MaxRetentionSec=35day
SystemMaxFiles=500
```

- [ ] **Step 4: Run it again.** Expected: `OK`.

- [ ] **Step 5: Commit.**

```bash
git add infra/hermes-agent/deploy/journald-hermes-retention.conf infra/hermes-agent/deploy/units.test.py
git commit -m "feat(hermes): a journal settings file of our own, 35 days and 500 files (F58)"
```

---

### Task 4: D1.7 counts the `Match` lines; the checklist goes to v1.19

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`d1_7`, and a new `_sshd_match_lines` above it)
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md` (the version line, the header paragraph, D1.7)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (`TestD17AcceptedKeys`),
  `infra/hermes-agent/bin/security-review-checklist.test.py`

**Interfaces:**
- Consumes: `_split_unquoted(text, seps) -> (parts, unbalanced)`, `R.COULD_NOT_CHECK`, `AUTHORIZED_KEYS_READ_LIMIT`.
- Produces: `d1_7(...)["match_lines"]` and `["include_elsewhere"]`, each an `int` or `"could-not-check"`.
  Task 9's summary tool prints both.

- [ ] **Step 1: Write the failing tests.** In `TestD17AcceptedKeys`:

```python
    def _sshd_config(self, main, **drop_ins):
        self._w("/etc/ssh/sshd_config", main)
        for name, body in drop_ins.items():
            self._w("/etc/ssh/sshd_config.d/" + name.replace("_", "."), body)

    def test_match_lines_are_counted_in_the_main_file_and_the_conf_files(self):
        self._two()
        self._sshd_config("Include /etc/ssh/sshd_config.d/*.conf\nPort 22\n# Match User x\n"
                          "Match User a\n  X11Forwarding no\n\tmatch=Group b\n",
                          a_conf="MATCH all\nPermitRootLogin no\n", b_txt="Match User ignored\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (3, 0))

    def test_no_match_line_is_zero_not_could_not_check(self):
        self._two()
        self._sshd_config("Include /etc/ssh/sshd_config.d/*.conf\nPermitRootLogin no\nMatchmaker yes\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 0))

    def test_an_include_that_reaches_elsewhere_is_counted_per_line(self):
        self._two()
        self._sshd_config('Include /etc/ssh/sshd_config.d/*.conf\ninclude /etc/ssh/extra/*.conf "/opt/x y.conf"\n'
                          "Include sshd_config.d/*.conf\nInclude other.conf\n")
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (0, 2))

    def test_a_configuration_that_cannot_be_read_is_could_not_check_and_the_keys_are_still_listed(self):
        self._two()                                             # no /etc/ssh/sshd_config in the fake root
        d = CE.d1_7(self.host(), {})
        self.assertEqual((d["match_lines"], d["include_elsewhere"]), (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))
        self.assertEqual(len(d["files"][0]["keys"]), 2)
```

In the same class, the existing `test_the_result_has_exactly_these_top_level_fields` lists the item's
fields: change its expected list to
`["accounts_checked", "files", "include_elsewhere", "match_lines", "sshd", "unprivileged_port_start"]`.

In `security-review-checklist.test.py`, rename `test_the_version_is_1_18` to `test_the_version_is_1_19` and
change its pattern to `r"(?m)^version: 1\.19$"`.

- [ ] **Step 2: Run them.**
  `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD17AcceptedKeys -v` — expected: the four
  new tests fail with `KeyError: 'match_lines'`.
  `python3 infra/hermes-agent/bin/security-review-checklist.test.py -v` — expected: the version test fails.

- [ ] **Step 3: Implement.** Above `def d1_7`:

```python
SSHD_CONFIG = "/etc/ssh/sshd_config"
SSHD_CONFIG_DIR = "/etc/ssh/sshd_config.d"
# A keyword and its arguments, as sshd_config(5) allows them: blanks, or blanks around one `=`.
_SSHD_LINE_RE = re.compile(r"[ \t]*([A-Za-z]+)(?:[ \t]*=[ \t]*|[ \t]+|$)(.*)")


def _sshd_match_lines(host):
    """(match_lines, include_elsewhere): the `Match` lines in the two places this collector reads
    (the main file and sshd_config.d/*.conf), and the `Include` lines there that name anything
    else. A `Match` block's settings are not read: its presence is what a reviewer must hear of.
    A file brought in from elsewhere is not read either, which is why it is counted. A place
    that cannot be read makes both could-not-check: a count of 0 must mean 0 was found."""
    try:
        names = sorted(n for n in os.listdir(host.path(SSHD_CONFIG_DIR)) if n.endswith(".conf"))
    except FileNotFoundError:
        names = []
    except OSError:
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
    matches = elsewhere = 0
    for p in [SSHD_CONFIG] + [SSHD_CONFIG_DIR + "/" + n for n in names]:
        try:
            with open(host.path(p), "rb") as f:
                data = f.read(AUTHORIZED_KEYS_READ_LIMIT + 1)
        except OSError:
            return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
        if len(data) > AUTHORIZED_KEYS_READ_LIMIT:
            return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
        for line in data.decode("utf-8", errors="replace").split("\n"):
            m = _SSHD_LINE_RE.match(line)
            if not m:
                continue
            keyword = m.group(1).lower()
            if keyword == "match":
                matches += 1
            elif keyword == "include":
                args = [a.strip('"') for a in _split_unquoted(m.group(2).strip(" \t\r"), " \t")[0]]
                full = [os.path.normpath(a if a.startswith("/") else "/etc/ssh/" + a) for a in args]
                elsewhere += any(a != SSHD_CONFIG_DIR + "/*.conf" for a in full) or not full
    return matches, elsewhere
```

In `d1_7`, before the `return`, add `match_lines, include_elsewhere = _sshd_match_lines(host)`, and add
`"match_lines": match_lines, "include_elsewhere": include_elsewhere,` to the returned dict after
`"unprivileged_port_start"`. In `d1_7`'s docstring replace "a `Match` block is not read here (the
fingerprint's entry_points component carries the whole of `sshd -T`)" by "a `Match` block's settings are not
read here, only counted (`match_lines`); the fingerprint's entry_points component carries the whole of
`sshd -T`".

- [ ] **Step 4: The checklist.** In `CHECKLIST.md`:
  - `version: 1.18` becomes `version: 1.19`.
  - At the end of the header paragraph's last line (after the `(v1.18: …)` sentence), on the same line, add:
    ` (v1.19: review #9's follow-ups. New D2.4: how far back the journal reaches, the retention settings and the file that sets each, whether the running service has read them, and how near the journal is to its limits (F58: the box kept 7 days while the leak checks assumed 30). D2.3 and D10.7 report the oldest entry they read, and D2.3 the size of the text it searched. D1.7 counts the `Match` lines and the `Include` lines that reach outside the two places it reads; the operator's pasted count is no longer needed.)`
  - D1.7 `expected`: replace `(a `Match` block is not read; the fingerprint's `entry_points` component carries the whole of `sshd -T`)` by `(a `Match` block's settings are not read, only counted: `match_lines` is the number of `Match` lines in `/etc/ssh/sshd_config` and `/etc/ssh/sshd_config.d/*.conf`, and `include_elsewhere` the number of `Include` lines in those files that name anything other than `/etc/ssh/sshd_config.d/*.conf`; both `0`; the fingerprint's `entry_points` component carries the whole of `sshd -T`)`.
  - D1.7 `pass rule`: replace the whole of part (4), from `(4) **What this evidence cannot see:**` up to and including `without the count this item is CANNOT-VERIFY.`, by: `(4) **`Match` blocks:** `sshd` holds the global settings, and a `Match` block could give one account another `AuthorizedKeysFile`, a key command or a CA. `match_lines` and `include_elsewhere` must both be `0`. `could-not-check` is CANNOT-VERIFY. Another number needs the operator's statement of what each block sets, or what each file brought in from elsewhere holds (a `Match` line there is not counted); unexplained, it is a FAIL.`

- [ ] **Step 5: Run everything.** `infra/hermes-agent/bin/run-bin-tests.sh` — expected: every suite passes
  (the checklist suite's `test_d1_7_and_d4_6_name_every_field_the_collector_reports` now finds the two new
  names). `python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo rc=$?` — `rc=0`.

- [ ] **Step 6: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/security-review-checklist.test.py infra/hermes-agent/deploy/security-review/CHECKLIST.md
git commit -m "feat(hermes): D1.7 counts the sshd Match lines and outside Includes; checklist v1.19"
```

---

### Task 5: Repair the key reader's false alarms that Task 2 confirmed

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`_key_row`, and a new `_key_fields` above it)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (`TestD17AcceptedKeys`)

**Interfaces:**
- Consumes: Task 2's four results. `_KEY_TYPE_RE`, `_KEY_BODY_RE`, `_split_unquoted`, `_shown_option`, `PK.sha256_bytes`.
- Produces: `_key_row(line) -> {"type", "options", "sha12"} | None`, unchanged in form. For every line the
  old reader accepted, the row is the same.

**Decision rule.** Repair the quote case only if Task 2's `a` AND `b` were `accepted`; repair the carriage
return only if `c` was `accepted`. A case `sshd` refused is not a false alarm: leave the reader as it is for
that case, and write the test below with the opposite expectation (`unparsed_lines` 1, no key), so that the
measured behaviour is pinned either way. If no case was accepted, this task is the tests alone.

- [ ] **Step 1: Write the failing tests** (as written here they expect both repairs):

```python
    def test_a_quote_in_a_keys_comment_does_not_hide_the_key(self):
        self._keys("/home/hermesops", f'ssh-ed25519 {_keybody(1)} com"ment\n'
                                      f'no-pty ssh-ed25519 {_keybody(2)} com"ment\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual(([k["options"] for k in row["keys"]], row["unparsed_lines"]), ([[], ["no-pty"]], 0))
        self.assertNotIn("ment", json.dumps(row))

    def test_a_carriage_return_after_the_key_body_does_not_hide_the_key(self):
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\r\n{TUNNEL_OPTS} ssh-ed25519 {_keybody(2)}\r\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (2, 0))
        self.assertEqual(row["keys"][0]["sha12"], hashlib.sha256(base64.b64decode(_keybody(1))).hexdigest()[:12])

    def test_an_unclosed_quote_in_the_options_is_still_not_a_key(self):
        self._keys("/home/hermesops", f'command="unbalanced ssh-ed25519 {_keybody(1)}\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["keys"], row["unparsed_lines"]), ([], 1))

    def test_the_rows_of_ordinary_lines_are_what_they_were(self):
        self._two()
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual([k["options"] for k in row["keys"]],
                         [[], ['command="/bin/false"', 'permitlisten="127.0.0.1:1"',
                               'permitopen="127.0.0.1:9119"', "port-forwarding", "restrict"]])
```

- [ ] **Step 2: Run them.** `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD17AcceptedKeys -v`
  Expected: the first two fail (`unparsed_lines` is 2, then 1 or 2); the last two pass.

- [ ] **Step 3: Implement.** Replace `_key_row` by:

```python
# What sshd's base64 reader skips inside a key body besides the space and tab that end it
# (measured against sshd 9.6p1: docs/evaluations/2026-10-10-journal-retention-35-days.md).
_KEY_BODY_SKIPPED = str.maketrans("", "", "\r\n\x0b\x0c")


def _key_fields(text):
    """(type, body bytes) when `text` starts with a key type and a key body, as sshd's key reader
    takes them: two fields, each ended by a space or a tab. Whatever follows is the comment; it
    is never looked at (a quote in it means nothing to sshd). None otherwise."""
    parts = re.split(r"[ \t]+", text, maxsplit=2)
    if len(parts) < 2 or not _KEY_TYPE_RE.fullmatch(parts[0]):
        return None
    body = parts[1].translate(_KEY_BODY_SKIPPED)
    if not _KEY_BODY_RE.fullmatch(body):
        return None
    try:
        return parts[0], base64.b64decode(body, validate=True)
    except ValueError:
        return None


def _key_row(line):
    """One authorized_keys line as its key type, its options and a short fingerprint of the key
    body, or None when it is not a key line. Read as sshd reads it: a key first, or the options
    (up to the first space or tab outside double quotes) and then a key. The body and the comment
    are never returned."""
    text = line.strip(" \t")
    got, options = _key_fields(text), []
    if got is None:
        i, quoted = 0, False
        while i < len(text) and (quoted or text[i] not in " \t"):
            if text[i] == "\\" and text[i + 1:i + 2] == '"':
                i += 1                                  # sshd skips both characters
            elif text[i] == '"':
                quoted = not quoted
            i += 1
        if quoted:                                      # the options never end: sshd finds no key
            return None
        got = _key_fields(text[i:].lstrip(" \t"))
        if got is None:
            return None
        options = _split_unquoted(text[:i], ",")[0]
    return {"type": got[0], "options": sorted(_shown_option(o) for o in options),
            "sha12": PK.sha256_bytes(got[1])[:12]}
```

Whatever Task 2 showed, also change the blank-line test in `_authorized_keys_row` from
`if not line.strip(" \t") or …` to `if not line.strip(" \t\r") or …`: in a file with CR LF line endings an
empty line arrives as a lone carriage return, which can never be a key and must not count as unreadable. Its
test:

```python
    def test_an_empty_line_in_a_file_with_cr_lf_endings_is_blank(self):
        self._keys("/home/hermesops", f"# two keys\r\n\r\nssh-ed25519 {_keybody(1)} one\r\n   \r\n")
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (1, 0))
```

If Task 2's `c` was `refused`, leave out the `.translate(_KEY_BODY_SKIPPED)` and the constant. If `a` or `b`
was `refused`, keep the old `_key_row` and add only what the carriage-return repair needs (the translate, on
`tokens[i + 1]`).

- [ ] **Step 4: Run the whole suite.** `infra/hermes-agent/bin/run-bin-tests.sh` — expected: every suite
  passes, among them every older `TestD17AcceptedKeys` test unchanged.

- [ ] **Step 5: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "fix(hermes): D1.7 reads a key line as sshd does (a quote in the comment, a CR line ending)"
```

---

### Task 6: Reading the journal's settings and its oldest entry (helpers)

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (new helpers at the end of the D2 section, after `d2_3`; `_ok` gains a `timeout` parameter)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class `TestJournalHelpers`)

**Interfaces:**
- Consumes: `Host.run(argv, timeout=60) -> (rc, out, err)`, `_iso(epoch) -> "YYYY-MM-DDTHH:MM:SSZ"`,
  `CouldNotCheck`, `R.COULD_NOT_CHECK`.
- Produces (Tasks 7 and 8 use these exact names):
  - `_ok(host, argv, timeout=60) -> str`
  - `JOURNALD_SETTINGS = ("MaxRetentionSec", "SystemMaxUse", "SystemMaxFiles", "MaxFileSec")`
  - `_span_seconds(value: str) -> int | "could-not-check"`
  - `_size_bytes(value: str) -> int | "could-not-check"`
  - `_journald_settings(text: str) -> (dict, list)`: `{name: {"value": str | None, "file": str | None}}`
    and the files printed, in order. Raises `CouldNotCheck` when a file is printed twice.
  - `OLDEST_ENTRY_ARGS` (a list) and `_oldest_entry(host, selector=()) -> str | None | "could-not-check"`

- [ ] **Step 1: Write the failing tests.** A new class after `TestD17AcceptedKeys`:

```python
CAT_CONFIG = ("# /etc/systemd/journald.conf\n#  This file is part of systemd.\n\n# See journald.conf(5) for details.\n\n"
              "[Journal]\n#Storage=auto\nSystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n\n"
              "# /etc/systemd/journald.conf.d/50-hermes-retention.conf\n# Hermes: 35 days\n[Journal]\n"
              "MaxRetentionSec=35day\nSystemMaxFiles=500\n\n"
              "# /usr/lib/systemd/journald.conf.d/syslog.conf\n[Journal]\nForwardToSyslog=yes\n")
OURS = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"


def _oldest_key(*selector):
    return tuple(["journalctl", *CE.OLDEST_ENTRY_ARGS, *selector])


def _entry(epoch):
    return json.dumps({"__CURSOR": "s=abc", "__REALTIME_TIMESTAMP": str(epoch * 1000000 + 123456),
                       "__MONOTONIC_TIMESTAMP": "1", "_BOOT_ID": "0" * 32}) + "\n"


class TestJournalHelpers(Base):
    def test_the_last_file_that_sets_a_value_is_the_one_reported(self):
        got, files = CE._journald_settings(CAT_CONFIG)
        self.assertEqual(files, ["/etc/systemd/journald.conf", OURS, "/usr/lib/systemd/journald.conf.d/syslog.conf"])
        self.assertEqual(got["MaxRetentionSec"], {"value": "35day", "file": OURS})
        self.assertEqual(got["SystemMaxFiles"], {"value": "500", "file": OURS})
        self.assertEqual(got["SystemMaxUse"], {"value": "1G", "file": "/etc/systemd/journald.conf"})
        self.assertEqual(got["MaxFileSec"], {"value": "1day", "file": "/etc/systemd/journald.conf"})

    def test_only_journal_section_lines_count_and_the_last_file_wins(self):
        text = ("# /etc/systemd/journald.conf\n[Other]\nMaxRetentionSec=99day\n[Journal]\n  MaxRetentionSec = 7day  \n"
                ";MaxRetentionSec=1day\n#MaxRetentionSec=2day\nSystemMaxUse=\n"
                "# /etc/systemd/journald.conf.d/x.conf\nMaxRetentionSec=40day\n")
        got, files = CE._journald_settings(text)
        # the second `# /` line does not follow an empty line: it is a comment, not a file
        self.assertEqual(files, ["/etc/systemd/journald.conf"])
        self.assertEqual(got["MaxRetentionSec"], {"value": "40day", "file": "/etc/systemd/journald.conf"})
        self.assertEqual(got["SystemMaxUse"], {"value": "", "file": "/etc/systemd/journald.conf"})
        self.assertEqual(got["SystemMaxFiles"], {"value": None, "file": None})

    def test_a_comment_that_looks_like_a_header_of_a_file_already_printed_is_could_not_check(self):
        with self.assertRaises(CE.CouldNotCheck):
            CE._journald_settings(CAT_CONFIG + "\n# /etc/systemd/journald.conf\n[Journal]\nMaxRetentionSec=1day\n")

    def test_spans_sizes_and_what_cannot_be_converted(self):
        for text, want in (("35day", 3024000), ("7day", 604800), ("1month", 2629800), ("2h 30min", 9000),
                           ("1w", 604800), ("90", 90), ("1.5h", 5400), ("0", 0), ("1y", 31557600),
                           ("1 fortnight", R.COULD_NOT_CHECK), ("", R.COULD_NOT_CHECK),
                           ("infinity", R.COULD_NOT_CHECK), ("day", R.COULD_NOT_CHECK), ("-1day", R.COULD_NOT_CHECK)):
            self.assertEqual(CE._span_seconds(text), want, text)
        for text, want in (("1G", 1 << 30), ("500M", 500 << 20), ("4096", 4096), ("8K", 8192), ("2T", 2 << 40),
                           ("1.5G", R.COULD_NOT_CHECK), ("", R.COULD_NOT_CHECK), ("big", R.COULD_NOT_CHECK)):
            self.assertEqual(CE._size_bytes(text), want, text)

    def test_the_oldest_entry_is_a_utc_time_and_the_selector_comes_last(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[_oldest_key()] = (0, _entry(1759000000), "")
        host = self.host()
        self.assertEqual(CE._oldest_entry(host), "2025-09-27T19:06:40Z")
        self.assertEqual(CE._oldest_entry(host, ("-u", "hermes-app-broker@ads-audit", "--since", "-30d")),
                         "2025-10-09T08:53:20Z")
        self.assertEqual(host.calls[-1][-4:], ["-u", "hermes-app-broker@ads-audit", "--since", "-30d"])
        self.assertEqual(host.calls[0][:2], ["journalctl", "-q"])     # never the leak checks' own prefixes

    def test_no_entry_is_none_and_a_failure_is_could_not_check(self):
        self.outputs[_oldest_key()] = (0, "", "")
        self.assertIsNone(CE._oldest_entry(self.host()))
        for bad in ((1, "", "boom"), (0, "not json\n", ""), (0, "{}\n", ""), (0, '{"__REALTIME_TIMESTAMP": "x"}\n', ""),
                    (0, "[1]\n", ""), (0, '{"__REALTIME_TIMESTAMP": "9" }\n' * 2, "")):
            self.outputs[_oldest_key()] = bad
            self.assertEqual(CE._oldest_entry(self.host()), R.COULD_NOT_CHECK, bad)

    def test_ok_passes_its_time_limit_to_the_host(self):
        seen = []
        host = CE.Host(self.root, lambda argv, timeout=60: seen.append(timeout) or (0, "x", ""))
        CE._ok(host, ["true"])
        CE._ok(host, ["true"], timeout=300)
        self.assertEqual(seen, [60, 300])
```

(Check the two expected times before running: `python3 -c "import datetime as d; print(d.datetime.fromtimestamp(1759000000, d.timezone.utc), d.datetime.fromtimestamp(1760000000, d.timezone.utc))"`;
if they differ from the strings above, the strings are wrong, not the code: correct them.)

- [ ] **Step 2: Run them.** `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestJournalHelpers -v`
  Expected: every test errors with `AttributeError` (`OLDEST_ENTRY_ARGS`, `_journald_settings`, …) and the
  last with `TypeError` (`_ok` takes no `timeout`).

- [ ] **Step 3: Implement.** Change `_ok`:

```python
def _ok(host, argv, timeout=60):
    rc, out, err = host.run(argv, timeout)
    if rc != 0:
        raise CouldNotCheck(f"{argv[0]} exited {rc}: {(err or out).strip()[:200]}")
    return out
```

After `d2_3`:

```python
# D2.4: the journal service's settings, as `systemd-analyze cat-config systemd/journald.conf`
# prints the files (systemd 255: `# <path>` before each file, an empty line before every file
# but the first; the last file to set a value is the one that counts).
JOURNALD_SETTINGS = ("MaxRetentionSec", "SystemMaxUse", "SystemMaxFiles", "MaxFileSec")
_JOURNALD_FILE_RE = re.compile(r"# (/(?:etc|run|usr/lib|usr/local/lib)/systemd/journald\.conf"
                               r"(?:\.d/[A-Za-z0-9._@-]+\.conf)?)")
# systemd.time(7), as src/basic/time-util.c reads a time span at tag v255. A bare number is seconds.
_SPAN_UNITS = {"": 1, "usec": 1e-6, "us": 1e-6, "μs": 1e-6, "µs": 1e-6, "msec": 1e-3, "ms": 1e-3,
               "seconds": 1, "second": 1, "sec": 1, "s": 1, "minutes": 60, "minute": 60, "min": 60, "m": 60,
               "hours": 3600, "hour": 3600, "hr": 3600, "h": 3600, "days": 86400, "day": 86400, "d": 86400,
               "weeks": 604800, "week": 604800, "w": 604800, "months": 2629800, "month": 2629800, "M": 2629800,
               "years": 31557600, "year": 31557600, "y": 31557600}
_SPAN_PART_RE = re.compile(r"[ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*([A-Za-zμµ]*)")
_SIZE_UNITS = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40, "P": 1 << 50, "E": 1 << 60}
# The oldest entry journalctl would show: its time and nothing else (no message, no host name).
# The selector (a unit, a window) goes AFTER these, so the call never starts as a leak check's does.
OLDEST_ENTRY_ARGS = ["-q", "--no-pager", "-o", "json", "--output-fields=__REALTIME_TIMESTAMP", "-n", "+1"]


def _span_seconds(value):
    """A systemd time span as whole seconds, or could-not-check: a value this collector cannot
    convert is never guessed at (`infinity`, a unit it does not know, an empty value)."""
    text, pos, total = value.strip(" \t"), 0, 0.0
    if not text:
        return R.COULD_NOT_CHECK
    while pos < len(text):
        m = _SPAN_PART_RE.match(text, pos)
        if not m or m.group(2) not in _SPAN_UNITS:
            return R.COULD_NOT_CHECK
        total += float(m.group(1)) * _SPAN_UNITS[m.group(2)]
        pos = m.end()
    return int(total)


def _size_bytes(value):
    """A size as journald.conf writes it (a whole number and K, M, G, T, P or E, powers of 1024)."""
    m = re.fullmatch(r"([0-9]+)([KMGTPE]?)", value.strip(" \t"))
    return int(m.group(1)) * _SIZE_UNITS[m.group(2)] if m else R.COULD_NOT_CHECK


def _journald_settings(text):
    """(settings, files): for each name in JOURNALD_SETTINGS the value written LAST under
    [Journal] and the file it stands in (both None when no file sets it), and the files printed,
    in order. A file starts at a `# /path` line that is the first line or follows an empty one
    and names a journald settings file; every other line starting with # or ; is a comment. A
    file printed twice is could-not-check: cat-config prints each once, so a second header is a
    comment made to look like one, and the file of a value below it cannot be told."""
    lines = text.split("\n")
    last = {k: {"value": None, "file": None} for k in JOURNALD_SETTINGS}
    files, current, section = [], None, None
    for i, line in enumerate(lines):
        m = _JOURNALD_FILE_RE.fullmatch(line)
        if m and (i == 0 or lines[i - 1] == ""):
            if m.group(1) in files:
                raise CouldNotCheck("cat-config shows one settings file twice")
            current, section = m.group(1), None
            files.append(current)
            continue
        s = line.strip(" \t")
        if not s or s[0] in "#;":
            continue
        if s[0] == "[" and s[-1] == "]":
            section = s[1:-1]
            continue
        name, eq, val = s.partition("=")
        if eq and current and section == "Journal" and name.strip(" \t") in last:
            last[name.strip(" \t")] = {"value": val.strip(" \t"), "file": current}
    return last, files


def _oldest_entry(host, selector=()):
    """The UTC time of the oldest entry journalctl shows for `selector`: None when it shows no
    entry, could-not-check when the answer is not exactly one entry with a time."""
    rc, out, _ = host.run(["journalctl", *OLDEST_ENTRY_ARGS, *selector])
    if rc != 0:
        return R.COULD_NOT_CHECK
    lines = [l for l in out.split("\n") if l.strip()]
    if not lines:
        return None
    try:
        if len(lines) != 1:
            raise ValueError("more than one entry")
        return _iso(int(json.loads(lines[0])["__REALTIME_TIMESTAMP"]) // 1000000)
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        return R.COULD_NOT_CHECK
```

Note for the implementer: in the second test the settings text has `MaxRetentionSec=40day` under a `# /…`
line that does not follow an empty line, so it stays in the first file and in `[Journal]`: the value is
`40day` from `/etc/systemd/journald.conf`. That is what the test expects.

- [ ] **Step 4: Run.** `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestJournalHelpers -v`
  — expected `OK`. Then `infra/hermes-agent/bin/run-bin-tests.sh` — every suite passes.

- [ ] **Step 5: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): read the journal service's settings and the journal's oldest entry"
```

---

### Task 7: The new probe `d2_4`, registered, with its checklist item

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`d2_4` and three helpers after Task 6's; `PROBES`)
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md` (new item D2.4 after D2.3)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class `TestD24Journal`),
  `infra/hermes-agent/bin/security-review-checklist.test.py`

**Interfaces:**
- Consumes: Task 6's helpers; `_unit_started_at(host, unit)`, `_epoch(iso)`, `_same_file(host, a, b)`,
  `_stat(host, p)`, `WITHHELD`, `CHECKOUT`, `APP`; Task 3's file.
- Produces: `d2_4(host, ctx) -> dict` with the keys `oldest_entry` (`journal`, `broker`, `runner`),
  `reach_days`, `settings` (per name: `value`, `file`, `number`), `config_files`, `drop_in` (`equals_repo`,
  `owner`, `group`, `mode`, `other_files`), `service` (`started_at`, `config_changed_after_start`), `usage`
  (`bytes`, `files`, `bytes_percent_of_max_use`, `files_percent_of_max_files`, `free_bytes`, `free_percent`,
  `other_directories`). `JOURNALD_DROP_IN`, `JOURNAL_UNITS`. `PROBES["D2.4"]`. Task 9 reads these names.

- [ ] **Step 1: Write the failing tests.**

```python
class TestD24Journal(Base):
    MID = "0123456789abcdef0123456789abcdef"
    REPO_FILE = CE.CHECKOUT + "/infra/hermes-agent/deploy/journald-hermes-retention.conf"
    BODY = "[Journal]\nMaxRetentionSec=35day\nSystemMaxFiles=500\n"
    STARTED = "Sat 2026-10-10 12:00:00 UTC\n"

    def setUp(self):
        super().setUp()
        self._w("/etc/machine-id", self.MID + "\n")
        for name in ("system.journal", "user-1000.journal", "system@a-1-2.journal", "user-1000@b-1-2.journal~"):
            self._w(f"/var/log/journal/{self.MID}/{name}", "x" * 8192)
        self._w(f"/var/log/journal/{self.MID}/not-a-journal.txt", "x")
        self._w(self.REPO_FILE, self.BODY)
        self.conf_paths = [self._w("/etc/systemd/journald.conf", "[Journal]\nMaxRetentionSec=7day\n"),
                           self._w(OURS, self.BODY),
                           self._w("/usr/lib/systemd/journald.conf.d/syslog.conf", "[Journal]\nForwardToSyslog=yes\n")]
        os.chmod(self.conf_paths[1], 0o644)
        self._all_older_than_the_start()
        self.outputs[("systemd-analyze", "cat-config", "systemd/journald.conf")] = (0, CAT_CONFIG, "")
        self.outputs[("systemctl", "show", "systemd-journald")] = (0, self.STARTED, "")
        now = int(time.time())
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(now - 3 * 86400), "")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, "", "")
        self.outputs[_oldest_key()] = (0, _entry(now - 31 * 86400 - 60), "")

    def _all_older_than_the_start(self):
        old = CE._epoch("2026-10-10T11:00:00Z")
        for p in self.conf_paths:
            os.utime(p, (old, old))

    def test_a_healthy_box(self):
        with mock.patch.object(CE, "_changed_at", lambda host, p: os.stat(host.path(p)).st_mtime):
            d = CE.d2_4(self.host(), {})
        self.assertEqual(d["reach_days"], 31)
        self.assertRegex(d["oldest_entry"]["journal"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(d["oldest_entry"]["broker"], r"Z$")
        self.assertIsNone(d["oldest_entry"]["runner"])
        self.assertEqual(d["settings"]["MaxRetentionSec"], {"value": "35day", "file": OURS, "number": 3024000})
        self.assertEqual(d["settings"]["SystemMaxFiles"], {"value": "500", "file": OURS, "number": 500})
        self.assertEqual(d["settings"]["SystemMaxUse"]["number"], 1 << 30)
        self.assertEqual(d["settings"]["MaxFileSec"]["number"], 86400)
        self.assertEqual(d["config_files"], ["/etc/systemd/journald.conf", OURS,
                                             "/usr/lib/systemd/journald.conf.d/syslog.conf"])
        self.assertEqual((d["drop_in"]["equals_repo"], d["drop_in"]["mode"], d["drop_in"]["other_files"]),
                         (True, "0o644", []))
        self.assertEqual(d["service"], {"started_at": "2026-10-10T12:00:00Z", "config_changed_after_start": False})
        own = os.path.join(self.root, "var/log/journal", self.MID)
        blocks = sum(os.lstat(os.path.join(own, n)).st_blocks for n in os.listdir(own) if ".journal" in n)
        self.assertEqual((d["usage"]["files"], d["usage"]["bytes"], d["usage"]["other_directories"]),
                         (4, blocks * 512, 0))
        self.assertEqual(d["usage"]["files_percent_of_max_files"], 0.8)
        self.assertIsInstance(d["usage"]["bytes_percent_of_max_use"], float)
        self.assertIsInstance(d["usage"]["free_bytes"], int)
        self.assertTrue(0 <= d["usage"]["free_percent"] <= 100)

    def test_a_settings_file_newer_than_the_service_start_is_reported(self):
        later = CE._epoch("2026-10-10T12:00:01Z")
        os.utime(self.conf_paths[1], (later, later))
        with mock.patch.object(CE, "_changed_at", lambda host, p: os.stat(host.path(p)).st_mtime):
            d = CE.d2_4(self.host(), {})
        self.assertIs(d["service"]["config_changed_after_start"], True)

    def test_a_file_just_written_is_newer_than_an_old_start_without_any_patching(self):
        # the real clock: every file of this test was created just now, the service started long ago
        self.outputs[("systemctl", "show", "systemd-journald")] = (0, "Thu 2020-01-02 00:00:00 UTC\n", "")
        self.assertIs(CE.d2_4(self.host(), {})["service"]["config_changed_after_start"], True)

    def test_a_start_time_that_cannot_be_read_is_could_not_check_never_false(self):
        self.outputs[("systemctl", "show", "systemd-journald")] = (0, "\n", "")
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["service"], {"started_at": R.COULD_NOT_CHECK,
                                        "config_changed_after_start": R.COULD_NOT_CHECK})

    def test_a_missing_a_different_and_a_neighbouring_file_are_each_visible(self):
        self._w("/etc/systemd/journald.conf.d/99-other.conf", "[Journal]\n")
        self._w("/etc/systemd/journald.conf.d/odd name;.conf", "")
        self._w(OURS, self.BODY.replace("35day", "36day"))
        d = CE.d2_4(self.host(), {})["drop_in"]
        self.assertEqual((d["equals_repo"], d["other_files"]), (False, ["99-other.conf", CE.WITHHELD]))
        shutil.rmtree(os.path.join(self.root, "etc/systemd/journald.conf.d"))
        d = CE.d2_4(self.host(), {})["drop_in"]
        self.assertEqual(d, {"equals_repo": False, "owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK,
                             "mode": R.COULD_NOT_CHECK, "other_files": []})

    def test_no_setting_by_any_file_uses_systemds_default_file_limit(self):
        self.outputs[("systemd-analyze", "cat-config", "systemd/journald.conf")] = \
            (0, "# /etc/systemd/journald.conf\n[Journal]\nMaxRetentionSec=1 fortnight\n", "")
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["settings"]["MaxRetentionSec"]["number"], R.COULD_NOT_CHECK)
        self.assertEqual(d["settings"]["SystemMaxFiles"], {"value": None, "file": None, "number": None})
        self.assertEqual(d["usage"]["files_percent_of_max_files"], 4.0)        # 4 files of the default 100
        self.assertEqual(d["usage"]["bytes_percent_of_max_use"], R.COULD_NOT_CHECK)

    def test_what_cannot_be_read_is_could_not_check_part_by_part(self):
        self.outputs[("systemd-analyze", "cat-config", "systemd/journald.conf")] = (1, "", "boom")
        self.outputs[_oldest_key()] = (1, "", "boom")
        os.remove(os.path.join(self.root, "etc/machine-id"))
        d = CE.d2_4(self.host(), {})
        self.assertEqual(d["oldest_entry"]["journal"], R.COULD_NOT_CHECK)
        self.assertEqual(d["reach_days"], R.COULD_NOT_CHECK)
        self.assertEqual(d["settings"], R.COULD_NOT_CHECK)
        self.assertEqual(d["config_files"], R.COULD_NOT_CHECK)
        self.assertEqual(set(d["usage"].values()), {R.COULD_NOT_CHECK})
        self.assertIs(d["drop_in"]["equals_repo"], True)                # the other parts are still read

    def test_another_machines_directory_is_counted_not_measured(self):
        self._w("/var/log/journal/ffffffffffffffffffffffffffffffff/system.journal", "y" * 4096)
        d = CE.d2_4(self.host(), {})["usage"]
        self.assertEqual((d["files"], d["other_directories"]), (4, 1))

    def test_no_machine_id_no_path_outside_the_settings_and_no_journal_text_in_the_item(self):
        out = json.dumps(CE.d2_4(self.host(), {}))
        self.assertNotIn(self.MID, out)
        self.assertNotIn("s=abc", out)
        self.assertNotIn(self.root, out)

    def test_it_is_in_the_bundle(self):
        self.assertEqual(CE.collect(self.host(), self.KEY)["items"]["D2.4"]["status"], R.OBSERVED)
```

In `security-review-checklist.test.py`, after `test_d1_7_and_d4_6_name_every_field_the_collector_reports`:

```python
    def test_d2_4_names_every_field_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D2.4"]
        import tempfile
        cat = "# /etc/systemd/journald.conf\n[Journal]\nMaxRetentionSec=7day\n"
        host = ce.Host(tempfile.mkdtemp(), lambda argv, timeout=60: (0, cat if argv[0] == "systemd-analyze" else "", ""))
        d = ce.d2_4(host, {})
        fields = [*d, *d["oldest_entry"], *d["settings"], *d["settings"]["MaxRetentionSec"], *d["drop_in"],
                  *d["service"], *d["usage"]]
        for field in fields:
            self.assertIn(f"`{field}`", block, field)
        self.assertIn("`/etc/systemd/journald.conf.d/50-hermes-retention.conf`", block)
        self.assertIn("`2592000`", block)
```

- [ ] **Step 2: Run them.** Expected: `TestD24Journal` errors with `AttributeError: … 'd2_4'`; the checklist
  test fails with `KeyError: 'D2.4'`.

- [ ] **Step 3: Implement.** After Task 6's helpers:

```python
JOURNAL_DIR = "/var/log/journal"
JOURNALD_DROP_IN_DIR = "/etc/systemd/journald.conf.d"
JOURNALD_DROP_IN = JOURNALD_DROP_IN_DIR + "/50-hermes-retention.conf"
JOURNALD_DROP_IN_REPO = CHECKOUT + "/infra/hermes-agent/deploy/journald-hermes-retention.conf"
JOURNALD_DEFAULT_MAX_FILES = 100                # journald.conf(5), systemd 255: SystemMaxFiles= defaults to 100
JOURNAL_UNITS = {"broker": "hermes-app-broker@" + APP, "runner": "hermes-app-runner@" + APP}
_SETTING_NUMBER = {"MaxRetentionSec": _span_seconds, "MaxFileSec": _span_seconds, "SystemMaxUse": _size_bytes,
                   "SystemMaxFiles": lambda v: int(v) if re.fullmatch(r"[0-9]+", v) else R.COULD_NOT_CHECK}


def _percent(part, whole):
    ok = all(isinstance(x, int) and not isinstance(x, bool) for x in (part, whole)) and whole > 0
    return round(100 * part / whole, 1) if ok else R.COULD_NOT_CHECK


def _changed_at(host, p):
    """When a settings file last changed: the later of its content time and its inode time (a
    copy that keeps the old content time still shows here)."""
    st = os.stat(host.path(p))
    return max(st.st_mtime, st.st_ctime)


def _journald_service(host, files):
    """When the journal service started, and whether a settings file changed after that: the
    service reads its settings when it starts, so a newer file is not yet in force."""
    started = _unit_started_at(host, "systemd-journald")
    changed = R.COULD_NOT_CHECK
    if started != R.COULD_NOT_CHECK and isinstance(files, list) and files:
        try:
            changed = any(_changed_at(host, p) > _epoch(started) for p in files)
        except OSError:
            pass
    return {"started_at": started, "config_changed_after_start": changed}


def _journal_usage(host, settings):
    """As the service counts it (journal-vacuum.c): the files of the machine's OWN directory,
    512 bytes times each file's blocks. Other directories under /var/log/journal are counted,
    not measured: the service does not trim them and journalctl does not read them."""
    keys = ("bytes", "files", "bytes_percent_of_max_use", "files_percent_of_max_files", "free_bytes",
            "free_percent", "other_directories")
    try:
        with open(host.path("/etc/machine-id")) as f:
            mid = f.read(64).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", mid):
            raise ValueError("machine-id")
        base = host.path(JOURNAL_DIR)
        own = os.path.join(base, mid)
        names = [n for n in os.listdir(own) if n.endswith((".journal", ".journal~"))]
        used = sum(os.lstat(os.path.join(own, n)).st_blocks * 512 for n in names)
        others = sum(1 for n in os.listdir(base) if n != mid and os.path.isdir(os.path.join(base, n)))
        vfs = os.statvfs(own)
    except (OSError, ValueError):
        return {k: R.COULD_NOT_CHECK for k in keys}
    max_use = max_files = R.COULD_NOT_CHECK
    if isinstance(settings, dict):
        max_use = settings["SystemMaxUse"]["number"]
        max_files = (JOURNALD_DEFAULT_MAX_FILES if settings["SystemMaxFiles"]["value"] is None
                     else settings["SystemMaxFiles"]["number"])
    return {"bytes": used, "files": len(names), "bytes_percent_of_max_use": _percent(used, max_use),
            "files_percent_of_max_files": _percent(len(names), max_files),
            "free_bytes": vfs.f_bavail * vfs.f_frsize, "free_percent": _percent(vfs.f_bavail, vfs.f_blocks),
            "other_directories": others}


def _journald_drop_in(host):
    try:
        st = _stat(host, JOURNALD_DROP_IN)
        row = {"owner": st["owner"], "group": st["group"], "mode": st["mode"]}
    except OSError:
        row = {"owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK, "mode": R.COULD_NOT_CHECK}
    try:
        others = sorted(n for n in os.listdir(host.path(JOURNALD_DROP_IN_DIR))
                        if n != os.path.basename(JOURNALD_DROP_IN))
        others = [n if re.fullmatch(r"[A-Za-z0-9._@-]+", n) else WITHHELD for n in others]
    except FileNotFoundError:
        others = []
    except OSError:
        others = R.COULD_NOT_CHECK
    return {"equals_repo": _same_file(host, JOURNALD_DROP_IN, JOURNALD_DROP_IN_REPO), **row, "other_files": others}


def d2_4(host, ctx):
    """How far back the journal reaches and what decides it (F58: the box kept 7 days while the
    leak checks assumed 30). Times, numbers, setting names and settings-file paths only: no
    journal line, no machine id. Each part that cannot be read is could-not-check on its own."""
    oldest = {"journal": _oldest_entry(host)}
    for label, unit in JOURNAL_UNITS.items():
        oldest[label] = _oldest_entry(host, ("-u", unit))
    reach = R.COULD_NOT_CHECK
    if oldest["journal"] is None:
        reach = None
    elif oldest["journal"] != R.COULD_NOT_CHECK:
        reach = max(0, int(time.time()) - _epoch(oldest["journal"])) // 86400
    settings = files = R.COULD_NOT_CHECK
    rc, out, _ = host.run(["systemd-analyze", "cat-config", "systemd/journald.conf"])
    if rc == 0:
        try:
            got, files = _journald_settings(out)
            settings = {k: {**v, "number": None if v["value"] is None else _SETTING_NUMBER[k](v["value"])}
                        for k, v in got.items()}
        except CouldNotCheck:
            settings = files = R.COULD_NOT_CHECK
    return {"oldest_entry": oldest, "reach_days": reach, "settings": settings, "config_files": files,
            "drop_in": _journald_drop_in(host), "service": _journald_service(host, files),
            "usage": _journal_usage(host, settings)}
```

Add `"D2.4": d2_4` to `PROBES`, after `"D2.3": d2_3`.

Two notes for the implementer. (a) `test_a_healthy_box` and the next test patch `_changed_at` to the content
time alone, because a test cannot set a file's inode time; the third test runs the real function. (b) In
`test_what_cannot_be_read…`, `settings` is the string `could-not-check`, so `_journal_usage` must not index
it: the `isinstance(settings, dict)` guard above is what the machine-id removal does not reach in that test
(the usage is could-not-check there for the missing machine id); keep the guard.

- [ ] **Step 4: The checklist item.** In `CHECKLIST.md`, after D2.3's last bullet and its empty line, before
  `## D3 Credential access, as Google sees it`, add (each bullet ONE line):

```markdown
### D2.4 — The journal reaches as far back as the leak checks assume
- **source:** box
- **claim:** the box keeps at least 30 days of journal, by a setting of ours that the running journal service has read, and nothing trims it sooner (F58: review #9 found 7 days kept while D2.3 and D10.7 assumed 30).
- **expected:** `oldest_entry` holds the UTC time of the oldest entry of the whole journal (`journal`) and of the two unit journals D10.7 reads (`broker`, `runner`; `null` when a journal holds no entry), and `reach_days` the whole days between `journal` and the collection. `settings` has one entry each for `MaxRetentionSec`, `SystemMaxUse`, `SystemMaxFiles` and `MaxFileSec`, read from `systemd-analyze cat-config systemd/journald.conf`: `value` (the text as written; `null` when no file sets it), `file` (the file that sets it last, which is the one that counts) and `number` (seconds for the two times, bytes for `SystemMaxUse`, a count for `SystemMaxFiles`; `could-not-check` when the collector cannot convert the text, never a guess). `config_files` lists the files that command printed, in order. On this box `MaxRetentionSec` is `35day` (`number` `3024000`) and `SystemMaxFiles` is `500`, both from `/etc/systemd/journald.conf.d/50-hermes-retention.conf`; `SystemMaxUse` is `1G` (`1073741824`) and `MaxFileSec` is `1day` (`86400`), both from the server's own `/etc/systemd/journald.conf`. `drop_in` describes our file: `equals_repo` is `true` (it is byte for byte the checkout's `deploy/journald-hermes-retention.conf`), `owner` and `group` are `root`, `mode` is `0o644`, and `other_files` (every other name in `/etc/systemd/journald.conf.d/`) is `[]`. `service` holds `started_at` (when `systemd-journald` last started) and `config_changed_after_start`, which is `true` when any file in `config_files` changed after that start (the service reads its settings when it starts, so such a file is not yet in force); `false`. `usage` is counted as the service counts it, in the machine's own directory under `/var/log/journal`: `bytes` (512 times the blocks of each journal file), `files`, `bytes_percent_of_max_use`, `files_percent_of_max_files` (against `SystemMaxFiles`, or systemd's default of 100 when no file sets it), `free_bytes` and `free_percent` of that file system, and `other_directories` (directories there other than the machine's own; the service does not trim them and `journalctl`, so D2.3, does not read them).
- **pass rule:** judged in this order. (1) **Not read:** a value of `could-not-check` is CANNOT-VERIFY for its part, and `oldest_entry.journal` of `null` or `could-not-check` is CANNOT-VERIFY for the item. (2) **The setting:** the `number` of `MaxRetentionSec` is at least `2592000` (30 days), its `file` is `/etc/systemd/journald.conf.d/50-hermes-retention.conf`, `drop_in.equals_repo` is `true` and `drop_in.other_files` is `[]`; anything else is a FAIL, and so is an `owner` or `group` other than `root` or a `mode` other than `0o644`. (3) **In force:** `service.config_changed_after_start` of `true` is CANNOT-VERIFY: the running service has not read the files shown (BRING-UP "The journal's retention" restarts it; collect again afterwards). (4) **The reach:** `reach_days` is at least `30`. When it is less, the operator's evidence states the UTC date the retention was raised on the box, and `oldest_entry.journal` must be at least 5 days before that date (until then the box kept 6 to 8 days: a journal file is deleted at the daily trim once its first entry is 7 days old); a journal shorter than that, or no stated date, is CANNOT-VERIFY. (5) **The limits:** `bytes_percent_of_max_use` or `files_percent_of_max_files` of `90` or more, or `free_percent` under `20` (the service keeps 15% of the file system free by default), is CANNOT-VERIFY unless the operator explains it: at a limit the journal is trimmed by size before it is trimmed by age. (6) **Other directories:** `other_directories` above `0` needs the operator's statement of what each is (a server image can leave the journal of the machine it was built on); unexplained, it is CANNOT-VERIFY. **What this item cannot show:** `oldest_entry` is where the journal begins, not proof that it is unbroken; (2), (3) and (5) are what show that nothing is trimming it.
```

- [ ] **Step 5: Run.** `infra/hermes-agent/bin/run-bin-tests.sh` — every suite passes (the checklist suite's
  `test_box_items_equal_the_box_collector` now sees D2.4 on both sides; if Task 1 changed D10.7's form, see
  Task 8).

- [ ] **Step 6: Run the probe against a real journal service.** In Task 1's container `jr` (skip, and say so
  in the record, if the rehearsal fell back):

```bash
docker exec jr python3 -c '
import importlib.util, json
s = importlib.util.spec_from_file_location("ce", "/opt/projects/claude_code/infra/hermes-agent/bin/collect-review-evidence.py")
ce = importlib.util.module_from_spec(s); s.loader.exec_module(ce)
print(json.dumps(ce.d2_4(ce.Host(), {}), indent=1))'
```

Expected: a time for `oldest_entry.journal` and `null` for the two units; `MaxRetentionSec` `35day` from our
file with `number` `3024000`; `SystemMaxUse` `1G`; `drop_in.equals_repo` `true`, `root`, `root`, `0o644`,
`other_files` `[]`; `service.started_at` a time and `config_changed_after_start` `false` (Task 1 restarted
the service after installing the file); `usage` all numbers, `other_directories` `0`. Then
`docker exec jr touch /etc/systemd/journald.conf` and run it again: `config_changed_after_start` must now be
`true`. Record both outputs in the evaluation record (section "The rehearsal", R7). Anything else is a defect:
fix it with a test before going on.

- [ ] **Step 7: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/security-review-checklist.test.py infra/hermes-agent/deploy/security-review/CHECKLIST.md docs/evaluations/2026-10-10-journal-retention-35-days.md
git commit -m "feat(hermes): new review item D2.4, how far back the journal reaches and what decides it (F58)"
```

---

### Task 8: D2.3 and D10.7 say what they covered; D2.3 gets its longer limit

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`d2_3`, `d10_7`)
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md` (D2.3, D10.7)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class `TestJournalReach`; `TestRunReal`),
  `infra/hermes-agent/bin/security-review-checklist.test.py`

**Interfaces:**
- Consumes: `_ok(host, argv, timeout)`, `_oldest_entry(host, selector)`, `JOURNAL_UNITS`.
- Produces: `d2_3(...)` returns `journal` (unchanged), `scanned_characters` (int) and `oldest_entry_read`;
  `d10_7(...)` gains `oldest_entry_read` with the keys `broker` and `runner`. `JOURNAL_SCAN_TIMEOUT = 300`.

- [ ] **Step 1: Write the failing tests.**

```python
class TestJournalReach(Base):
    SECRET = "sk-or-v1-" + "0123456789abcdef" * 4
    M2_BYTES = 4630823                                  # the whole journal on the box, 2026-10-10 (7 days)

    def test_d2_3_reports_the_size_searched_and_the_oldest_entry_read_after_the_search(self):
        self.outputs[("journalctl", "-o")] = (0, "Started.\n" * 3, "")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        host = self.host()
        d = CE.d2_3(host, {"secrets": []})
        self.assertEqual(d, {"journal": {"pattern_hits": 0, "known_secret_hits": 0},
                             "scanned_characters": 27, "oldest_entry_read": "2025-10-09T08:53:20Z"})
        self.assertEqual([c[1] for c in host.calls], ["-o", "-q"])      # the search first, then the oldest entry

    def test_d2_3_gives_the_journal_300_seconds(self):
        seen = {}
        def run(argv, timeout=60):
            seen[tuple(argv[:2])] = timeout
            return (0, "", "")
        CE.d2_3(CE.Host(self.root, run), {"secrets": []})
        self.assertEqual(seen[("journalctl", "-o")], 300)

    def test_d2_3_finds_a_secret_and_a_pattern_at_the_far_end_of_35_days_of_journal(self):
        line = "hermes-app-broker[ads-audit]: request=0 op=run client=x status=ok reason=-\n"
        filler = line * (5 * self.M2_BYTES // len(line))
        text = f"leak {self.SECRET}\n" + filler + f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
        self.assertGreaterEqual(len(text), 5 * self.M2_BYTES - len(line))
        self.outputs[("journalctl", "-o")] = (0, text, "")
        t0 = time.monotonic()
        d = CE.d2_3(self.host(), {"secrets": [self.SECRET]})
        took = time.monotonic() - t0
        self.assertEqual(d["journal"], {"pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(d["scanned_characters"], len(text))
        self.assertLess(took, 60, "the search of a 35-day journal must end far inside the 300 s limit")

    def test_d10_7_reports_the_oldest_entry_read_for_each_unit_inside_its_30_days(self):
        self.outputs[_oldest_key("-u", "hermes-app-broker@ads-audit")] = (0, _entry(1760000000), "")
        self.outputs[_oldest_key("-u", "hermes-app-runner@ads-audit")] = (0, "", "")
        self.outputs[("journalctl", "-u")] = (0, "", "")
        host = self.host()
        d = CE.d10_7(host, CE.context(host, self.KEY))
        self.assertEqual(d["oldest_entry_read"], {"broker": "2025-10-09T08:53:20Z", "runner": None})
        oldest = [c for c in host.calls if c[1] == "-q"]
        self.assertTrue(all(c[-2:] == ["--since", "-30d"] for c in oldest), oldest)
```

In `TestRunReal`:

```python
    def test_a_35_day_journal_passes_through_the_real_runner_whole(self):
        n = 5 * 4630823
        rc, out, err = CE._run_real([sys.executable, "-c", f"import sys; sys.stdout.write('x' * {n})"], timeout=120)
        self.assertEqual((rc, len(out), err), (0, n, ""))
```

In `security-review-checklist.test.py`:

```python
    def test_d2_3_and_d10_7_name_the_reach_fields(self):
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        for field in ("journal", "scanned_characters", "oldest_entry_read"):
            self.assertIn(f"`{field}`", blocks["D2.3"], field)
        for field in ("oldest_entry_read", "broker", "runner"):
            self.assertIn(f"`{field}`", blocks["D10.7"], field)
```

(`"Started.\n" * 3` is 27 characters; `TOKEN` is the fake refresh token at the top of the test file, which
the credential pattern matches once in that line; measured on the laptop, the pattern search of 23 MB takes
about a third of a second. If Task 1, Step 4 found that `-n +1` with `--since` does not give the
oldest entry of the window, the last assertion of the D10.7 test becomes
`self.assertTrue(all("--since" not in c for c in oldest), oldest)` and the code below drops the two
arguments.)

- [ ] **Step 2: Run them.** Expected: `TestJournalReach` fails (`d2_3` returns one key; no
  `oldest_entry_read`); the `TestRunReal` test passes already (it pins what Option 1 rests on); the checklist
  test fails.

- [ ] **Step 3: Implement.** Replace `d2_3`:

```python
# The whole journal in one call: 4.6 MB of text in 2 s on the box at 7 days (2026-10-10), so about
# 23 MB and 10 s at 35. Ten times that, times five for growth, is 100 s; never under 300.
JOURNAL_SCAN_TIMEOUT = 300


def d2_3(host, ctx):
    """The whole journal, as far back as it reaches (D2.4 judges how far). The oldest entry is
    read AFTER the search: entries only ever leave, so the search reached at least that far."""
    text = _ok(host, ["journalctl", "-o", "cat", "--no-pager"], timeout=JOURNAL_SCAN_TIMEOUT)
    return {"journal": _count_cred_text(text, ctx.get("secrets", [])), "scanned_characters": len(text),
            "oldest_entry_read": _oldest_entry(host)}
```

In `d10_7`, after the `runner = _journal(...)` line add:

```python
    oldest = {label: _oldest_entry(host, ("-u", unit, "--since", "-30d")) for label, unit in JOURNAL_UNITS.items()}
```

and add `"oldest_entry_read": oldest,` to its returned dict after `"known_secrets_checked"`. `JOURNAL_UNITS`
is defined above `d10_7` (Task 7 put it in the D2 section).

- [ ] **Step 4: The checklist.** Replace D2.3's three bullets after `source` by:

```markdown
- **claim:** as D2.2, for the whole journal, as far back as it reaches (D2.4 judges how far).
- **expected:** `journal` holds both counts, `0`. `scanned_characters` is the size of the text searched (about 4.6 million at 7 days on this box, 2026-10-10; it grows with the retention to about 23 million) and `oldest_entry_read` the UTC time of the journal's oldest entry, read just after the search: entries only ever leave the journal, so the search reached at least that far back.
- **pass rule:** any non-zero count is a FAIL. `oldest_entry_read` of `null` or `could-not-check`, or `scanned_characters` of `0`, is CANNOT-VERIFY: what the search covered is unknown.
```

In D10.7's `expected`, at its end (same line), add:
` `oldest_entry_read` holds, for `broker` and `runner`, the UTC time of the oldest entry inside the 30 days read (`null` when that journal holds no entry in them).`
In D10.7's `pass rule`, after its first sentence, add:
` An `oldest_entry_read` of `could-not-check` for either journal, or of `null` for `broker`, is CANNOT-VERIFY (D2.4 judges whether the journal itself reaches 30 days).`

- [ ] **Step 5: Run.** `infra/hermes-agent/bin/run-bin-tests.sh` — every suite passes. Older tests compare
  `["D2.3"]["data"]["journal"]`, which is unchanged; `test_d10_7_reads_both_units_over_the_same_window`
  filters on `["journalctl", "-u"]`, which the new calls (`journalctl -q …`) do not match.

- [ ] **Step 6: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/security-review-checklist.test.py infra/hermes-agent/deploy/security-review/CHECKLIST.md
git commit -m "feat(hermes): D2.3 and D10.7 report the oldest entry read; D2.3 gets 300 s for a 35-day journal"
```

---

### Task 9: The summary tool

**Files:**
- Create: `infra/hermes-agent/bin/summarize-review-bundle.py`
- Test: `infra/hermes-agent/bin/summarize-review-bundle.test.py`

**Interfaces:**
- Consumes: a box bundle as the collector prints it (`{"kind": "box", "items": {id: {"status", "data" | "reason"}}, "fingerprint": {"complete"}, "collected_at", "credentials"}`), and the field names of Tasks 4, 7 and 8.
- Produces: `main(argv=None, stdin=None, out=None) -> int` (0 printed, 2 not a box bundle);
  `summary(bundle) -> list[str]`. Used by the runbook as
  `… collect-review-evidence.py --fp-key-tty | python3 infra/hermes-agent/bin/summarize-review-bundle.py; echo "collector_rc=${PIPESTATUS[0]}"`.

What it may print, and nothing else: an item id; a status; `true`, `false`, `null`; a number; a UTC time; a
**word** (at most 32 characters of letters, digits and `_ @ . + -`, optionally `/` and a second short part,
and holding no run of 8 or more hexadecimal characters). Every other string prints as `<withheld>`: a path, a
fingerprint, an option value, free text. It reads only the fields named in `FIELDS`; an item it does not know
prints its status alone.

- [ ] **Step 1: Write the failing tests.**

```python
#!/usr/bin/env python3
import importlib.util, io, json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("summarize_review_bundle", os.path.join(HERE, "summarize-review-bundle.py"))
SB = importlib.util.module_from_spec(spec); spec.loader.exec_module(SB)

OURS = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
PLANT = "sk-or-v1-" + "0123456789abcdef" * 4


def bundle():
    setting = lambda v, f, n: {"value": v, "file": f, "number": n}
    return {"schema": 1, "kind": "box", "collected_at": "2026-10-20T14:00:00Z",
            "fingerprint": {"complete": True, "sha256": "ab" * 32},
            "credentials": [{"role": "read", "refresh_token_sha12": "0123456789ab"},
                            {"label": "openrouter-key", "sha12": "ba9876543210"}],
            "items": {
                "D1.1": {"status": "observed", "data": {"listeners": ["tcp 0.0.0.0:22", "tcp 127.0.0.1:9119"]}},
                "D1.7": {"status": "observed", "data": {
                    "accounts_checked": 34, "unprivileged_port_start": 1024, "match_lines": 0, "include_elsewhere": 0,
                    "sshd": {"gatewayports": "no", "authorizedkeysfile": ".ssh/authorized_keys .ssh/authorized_keys2"},
                    "files": [{"path": "/home/hermesops/.ssh/authorized_keys", "users": ["hermesops"], "kind": "file",
                               "owner": "hermesops", "group": "hermesops", "mode": "0o600", "unparsed_lines": 0,
                               "keys": [{"type": "ssh-ed25519", "options": [], "sha12": "aaaaaaaaaaaa"},
                                        {"type": "ssh-ed25519", "sha12": "bbbbbbbbbbbb",
                                         "options": ['command="/bin/false"', 'permitlisten="127.0.0.1:1"',
                                                     'permitopen="127.0.0.1:9119"', "port-forwarding", "restrict"]}]}]}},
                "D2.3": {"status": "observed", "data": {"journal": {"pattern_hits": 0, "known_secret_hits": 0},
                                                        "scanned_characters": 23000000,
                                                        "oldest_entry_read": "2026-09-18T15:11:34Z"}},
                "D2.4": {"status": "observed", "data": {
                    "oldest_entry": {"journal": "2026-09-18T15:11:34Z", "broker": "2026-10-05T18:35:47Z", "runner": None},
                    "reach_days": 31,
                    "settings": {"MaxRetentionSec": setting("35day", OURS, 3024000),
                                 "SystemMaxFiles": setting("500", OURS, 500),
                                 "SystemMaxUse": setting("1G", "/etc/systemd/journald.conf", 1 << 30),
                                 "MaxFileSec": setting("1day", "/etc/systemd/journald.conf", 86400)},
                    "config_files": ["/etc/systemd/journald.conf", OURS],
                    "drop_in": {"equals_repo": True, "owner": "root", "group": "root", "mode": "0o644", "other_files": []},
                    "service": {"started_at": "2026-10-14T16:00:00Z", "config_changed_after_start": False},
                    "usage": {"bytes": 400000000, "files": 110, "bytes_percent_of_max_use": 37.3,
                              "files_percent_of_max_files": 22.0, "free_bytes": 80000000000, "free_percent": 86.5,
                              "other_directories": 0}}},
                "D4.2": {"status": "observed", "data": {"active": "active", "matches_last_pass": True,
                                                        "drop_in_paths": [], "execstart_sha256": "cd" * 32}},
                "D4.6": {"status": "observed", "data": {
                    "last_pass_collected_at": "2026-10-09T14:01:23Z", "started_at": {"hermes-broker": "2026-10-07T06:45:46Z"},
                    "started_after_last_pass": {"hermes-broker": False},
                    "files_newer_than_start": {"hermes-broker": []}, "files_checked": {"hermes-broker": 9}}},
                "D10.7": {"status": "observed", "data": {
                    "journal_counts": {"refused/disabled": 1, "refused/quota": 1, "refused/bad_request": 2, "ok/-": 3},
                    "note_counts": {}, "other_lines": 4, "known_secrets_checked": 7,
                    "broker_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "runner_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "oldest_entry_read": {"broker": "2026-10-05T18:35:47Z", "runner": None}}},
                "D10.8": {"status": "observed", "data": {"out_of_whitelist": 0, "results": [
                    {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
                    {"op": "run", "status": "refused", "reason": "quota", "keys_ok": True, "values_ok": True}]}},
                "D5.3": {"status": "could-not-check", "reason": "OSError: /var/lib/hermes/x: denied"},
                "D99.9": {"status": "observed", "data": {"anything": PLANT}}}}


def planted(value):
    """The same structure with every string leaf (and every dict key that is not an item id or a
    top-level bundle key) replaced by a secret-shaped value."""
    if isinstance(value, str):
        return PLANT
    if isinstance(value, list):
        return [planted(v) for v in value] or [PLANT]
    if isinstance(value, dict):
        return {k: planted(v) for k, v in value.items()}
    return value


def run(text):
    out = io.StringIO()
    rc = SB.main([], stdin=io.StringIO(text), out=out)
    return rc, out.getvalue()


class TestSummary(unittest.TestCase):
    def test_every_item_is_listed_with_its_status_known_to_the_tool_or_not(self):
        rc, text = run(json.dumps(bundle()))
        self.assertEqual(rc, 0)
        for iid in bundle()["items"]:
            self.assertRegex(text, rf"(?m)^{iid} +(observed|could-not-check)\b")
        self.assertRegex(text, r"(?m)^items 10 \| not observed: D5\.3$")
        self.assertNotIn("anything", text)                       # an unknown item: its status alone
        self.assertNotIn("denied", text)                         # a reason is free text

    def test_counts_booleans_words_and_times_are_printed(self):
        text = run(json.dumps(bundle()))[1]
        for want in ("match_lines: 0", "reach_days: 31", "scanned_characters: 23000000",
                     "oldest_entry_read: 2026-09-18T15:11:34Z", "MaxRetentionSec: {file: <withheld>, number: 3024000, value: 35day}",
                     "refused/bad_request: 2", "matches_last_pass: true", "run/ok results: 1",
                     "keys: 2 (ssh-ed25519 options=0, ssh-ed25519 options=5 limited_to_the_forward=true)"):
            self.assertIn(want, text)

    def test_no_path_no_fingerprint_and_no_option_value_is_printed(self):
        text = run(json.dumps(bundle()))[1]
        for gone in ("/etc/", "/home/", "/bin/false", "0123456789ab", "aaaaaaaaaaaa", "abab", "cdcd", "127.0.0.1", "0.0.0.0"):
            self.assertNotIn(gone, text, gone)

    def test_a_secret_planted_in_every_field_is_never_printed(self):
        b = bundle()
        b["items"] = {iid: planted(item) for iid, item in b["items"].items()}
        b["credentials"], b["fingerprint"], b["collected_at"] = planted(b["credentials"]), planted(b["fingerprint"]), PLANT
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertNotIn("sk-or", text)
        self.assertNotIn("0123456789abcdef", text)

    def test_the_closing_list_says_what_to_look_at_before_the_real_collection(self):
        text = run(json.dumps(bundle()))[1]
        closing = text[text.index("Before the real collection"):]
        self.assertIn("LOOK  every item observed (not observed: D5.3)", closing)
        for ok in ("the three live refusals are in the journal", "at least one run/ok result",
                   "retention at least 30 days, set by our file", "the journal reaches 30 days",
                   "the running journal service has read its settings", "the proxy matches the last PASS",
                   "no service runs older code", "fingerprint complete"):
            self.assertRegex(closing, rf"(?m)^ok    {ok}")
        self.assertIn("Reminders, not verdicts", closing)

    def test_each_closing_line_turns_to_look(self):
        def closing(change):
            b = bundle()
            change(b["items"])
            text = run(json.dumps(b))[1]
            return text[text.index("Before the real collection"):]
        cases = (
            (lambda it: it["D10.7"]["data"]["journal_counts"].pop("refused/quota"), "the three live refusals"),
            (lambda it: it["D10.8"]["data"]["results"].pop(0), "at least one run/ok result"),
            (lambda it: it["D2.4"]["data"]["settings"]["MaxRetentionSec"].update(file="/etc/systemd/journald.conf"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["drop_in"].update(other_files=["99-x.conf"]), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"].update(reach_days=12), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"]["service"].update(config_changed_after_start=True), "the running journal service"),
            (lambda it: it["D4.2"]["data"].update(matches_last_pass=False), "the proxy matches the last PASS"),
            (lambda it: it["D4.6"]["data"]["files_newer_than_start"].update({"hermes-broker": ["app_lib.py"]}), "no service runs older code"),
            (lambda it: it.pop("D2.4"), "the journal reaches 30 days"),
        )
        for change, line in cases:
            self.assertRegex(closing(change), rf"(?m)^LOOK  {line}", line)
        self.assertIn("reach is 12 days: the evidence needs the date the retention was raised",
                      closing(lambda it: it["D2.4"]["data"].update(reach_days=12)))

    def test_not_a_bundle_is_one_line_and_exit_2(self):
        for text in ("", "collect-review-evidence: refused\n", "[]", '{"kind": "laptop", "items": {}}',
                     '{"kind": "box"}', '{"kind": "box", "items": []}'):
            rc, out = run(text)
            self.assertEqual((rc, out.count("\n")), (2, 1), text)
            self.assertTrue(out.startswith("summarize-review-bundle: not a box bundle"), out)

    def test_odd_shapes_never_raise(self):
        b = bundle()
        b["items"]["D1.7"] = {"status": "observed"}                                  # no data
        b["items"]["D2.4"] = {"status": "observed", "data": {"settings": "could-not-check", "usage": 7}}
        b["items"]["D10.8"] = {"status": "observed", "data": {"results": "x"}}
        b["items"]["D10.7"] = {"status": "observed", "data": []}
        b["items"]["D4.6"] = "observed"
        b["fingerprint"] = None
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertIn("D4.6", text)

    def test_it_reads_a_file_named_on_the_command_line(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bundle(), f)
        out = io.StringIO()
        try:
            self.assertEqual(SB.main([f.name], out=out), 0)
        finally:
            os.unlink(f.name)
        self.assertIn("reach_days: 31", out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it.** `python3 infra/hermes-agent/bin/summarize-review-bundle.test.py -v`
  Expected: an error at import, `No such file or directory: …summarize-review-bundle.py`.

- [ ] **Step 3: Implement.** `infra/hermes-agent/bin/summarize-review-bundle.py`, mode 0755:

```python
#!/usr/bin/env python3
"""Print a summary of a box review bundle that is safe to paste: every item with its status,
and, for the items this tool knows, counts, booleans, times and short words only.

    sudo python3 collect-review-evidence.py --fp-key-tty | python3 summarize-review-bundle.py
    python3 summarize-review-bundle.py bundle-box.json

It is for the TRIAL collection (a throwaway key): it shows whether every item was observed and
what to look at before the real collection. It judges nothing: the reviewer does. Anything that
is not a number, a boolean, a UTC time or a short word prints as <withheld>: a path, a
fingerprint, an option value, free text. An item this tool does not know prints its status alone.
"""
import json
import re
import sys

WITHHELD = "<withheld>"
MAX_ENTRIES = 40
OUR_FILE = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
THIRTY_DAYS = 30 * 86400
LIMITED_OPTIONS = ['command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                   "port-forwarding", "restrict"]
REFUSALS = ("refused/disabled", "refused/quota", "refused/bad_request")
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_WORD_RE = re.compile(r"[A-Za-z0-9?-][A-Za-z0-9_@.+-]{0,31}(/[A-Za-z0-9_?.-]{1,24})?")
_HEX_RUN_RE = re.compile(r"[0-9A-Fa-f]{8,}")

# The fields printed for each item this tool knows, by their names in the item's data.
FIELDS = {
    "D1.7": ("accounts_checked", "unprivileged_port_start", "match_lines", "include_elsewhere", "sshd"),
    "D2.3": ("journal", "scanned_characters", "oldest_entry_read"),
    "D2.4": ("oldest_entry", "reach_days", "settings", "drop_in", "service", "usage"),
    "D4.1": ("listeners", "docker_dns_listeners", "secret_env"),
    "D4.2": ("active", "matches_last_pass"),
    "D4.5": ("timer_active", "timer_enabled", "installed_equal_repo", "last_age_seconds", "alert_present",
             "history_counts", "alert_log"),
    "D4.6": ("last_pass_collected_at", "started_at", "started_after_last_pass", "files_newer_than_start",
             "files_checked"),
    "D7.1": ("records",),
    "D10.7": ("journal_counts", "note_counts", "other_lines", "broker_journal", "runner_journal",
              "known_secrets_checked", "oldest_entry_read"),
    "D10.8": ("out_of_whitelist",),
}


def word(text):
    if not isinstance(text, str):
        return WITHHELD
    if _TIME_RE.fullmatch(text):
        return text
    return text if _WORD_RE.fullmatch(text) and not _HEX_RUN_RE.search(text) else WITHHELD


def show(value, depth=0):
    """A value as text, by the rule in the module's first lines."""
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return word(value)
    if depth >= 4 or not isinstance(value, (list, dict)):
        return WITHHELD
    if len(value) > MAX_ENTRIES:
        return f"<{len(value)} entries>"
    if isinstance(value, list):
        return "[" + ", ".join(show(v, depth + 1) for v in value) + "]"
    pairs = sorted(((word(k), v) for k, v in value.items()), key=lambda kv: kv[0])
    return "{" + ", ".join(f"{k}: {show(v, depth + 1)}" for k, v in pairs) + "}"


def _data(items, iid):
    item = items.get(iid)
    data = item.get("data") if isinstance(item, dict) else None
    return data if isinstance(data, dict) else {}


def _get(value, *path):
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _keys_line(data):
    lines = []
    for row in data.get("files") if isinstance(data.get("files"), list) else []:
        if not isinstance(row, dict):
            continue
        head = "  file: " + ", ".join(f"{k}: {show(row.get(k))}" for k in ("users", "kind", "owner", "group", "mode", "unparsed_lines"))
        keys = row.get("keys")
        if not isinstance(keys, list):
            lines += [head, f"  keys: {show(keys)}"]
            continue
        parts = []
        for key in keys:
            opts = key.get("options") if isinstance(key, dict) else None
            n = len(opts) if isinstance(opts, list) else "?"
            limited = " limited_to_the_forward=true" if opts == LIMITED_OPTIONS else ""
            parts.append(f"{show(key.get('type') if isinstance(key, dict) else None)} options={n}{limited}")
        lines += [head, f"  keys: {len(keys)} ({', '.join(parts)})"]
    return lines


def _run_ok(data):
    rows = data.get("results")
    if not isinstance(rows, list):
        return None
    return sum(1 for r in rows if isinstance(r, dict) and r.get("op") == "run" and r.get("status") == "ok")


def _checks(bundle, items, not_observed):
    """(ok, text) pairs: what to look at before the real collection. Reminders, not verdicts."""
    d24, d107 = _data(items, "D2.4"), _data(items, "D10.7")
    counts = d107.get("journal_counts") if isinstance(d107.get("journal_counts"), dict) else {}
    missing = [k for k in REFUSALS if not (isinstance(counts.get(k), int) and counts.get(k) > 0)]
    run_ok = _run_ok(_data(items, "D10.8"))
    retention = _get(d24, "settings", "MaxRetentionSec")
    retention = retention if isinstance(retention, dict) else {}
    number = retention.get("number")
    setting_ok = (isinstance(number, int) and not isinstance(number, bool) and number >= THIRTY_DAYS
                  and retention.get("file") == OUR_FILE and _get(d24, "drop_in", "equals_repo") is True
                  and _get(d24, "drop_in", "other_files") == [])
    reach = d24.get("reach_days")
    reach_ok = isinstance(reach, int) and not isinstance(reach, bool) and reach >= 30
    reach_note = ""
    if not reach_ok:
        reach_note = (f" (reach is {reach} days: the evidence needs the date the retention was raised)"
                      if isinstance(reach, int) and not isinstance(reach, bool) else " (not read)")
    newer = _get(_data(items, "D4.6"), "files_newer_than_start")
    code_ok = isinstance(newer, dict) and bool(newer) and all(v == [] for v in newer.values())
    return [
        (not not_observed, "every item observed" + (f" (not observed: {', '.join(not_observed)})" if not_observed else "")),
        (not missing, "the three live refusals are in the journal" + (f" (missing: {', '.join(missing)})" if missing else "")),
        (isinstance(run_ok, int) and run_ok > 0, "at least one run/ok result"),
        (setting_ok, "retention at least 30 days, set by our file, the file equal to the repository's, no other file"),
        (reach_ok, "the journal reaches 30 days" + reach_note),
        (_get(d24, "service", "config_changed_after_start") is False, "the running journal service has read its settings"),
        (_get(_data(items, "D4.2"), "matches_last_pass") is True, "the proxy matches the last PASS"),
        (code_ok, "no service runs older code than the box holds"),
        (_get(bundle, "fingerprint", "complete") is True, "fingerprint complete"),
    ]


def summary(bundle):
    items = bundle["items"]
    ids = sorted(items, key=lambda i: [int(n) if n.isdigit() else n for n in re.findall(r"[0-9]+|[^0-9]+", str(i))])
    status = {i: word(items[i].get("status")) if isinstance(items[i], dict) else WITHHELD for i in ids}
    not_observed = [word(i) for i in ids if status[i] != "observed"]
    lines = [f"collected_at {show(bundle.get('collected_at'))}",
             f"items {len(ids)} | not observed: {', '.join(not_observed) or 'none'}", ""]
    for iid in ids:
        lines.append(f"{word(iid)}  {status[iid]}")
        data = _data(items, iid)
        for field in FIELDS.get(iid, ()):
            if field in data:
                lines.append(f"  {field}: {show(data[field])}")
        if iid == "D1.7":
            lines += _keys_line(data)
        if iid == "D10.8":
            lines.append(f"  run/ok results: {show(_run_ok(data))}")
    creds = bundle.get("credentials")
    lines += ["", f"credentials: {len(creds) if isinstance(creds, list) else show(creds)}", "",
              "Before the real collection (ok = as expected, LOOK = look at it first):"]
    lines += [f"{'ok  ' if ok else 'LOOK'}  {text}" for ok, text in _checks(bundle, items, not_observed)]
    lines.append("Reminders, not verdicts: the reviewer judges the real bundle against the checklist.")
    return lines


def main(argv=None, stdin=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    out = out or sys.stdout
    try:
        if argv:
            with open(argv[0], encoding="utf-8") as f:
                bundle = json.load(f)
        else:
            bundle = json.load(stdin or sys.stdin)
        if not (isinstance(bundle, dict) and bundle.get("kind") == "box" and isinstance(bundle.get("items"), dict)):
            raise ValueError("not a box bundle")
    except (OSError, ValueError):
        print("summarize-review-bundle: not a box bundle (did the collector stop? read its own message and its rc)", file=out)
        return 2
    print("\n".join(summary(bundle)), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Notes for the implementer. (a) The planted-secret test replaces every string, so `status` becomes the plant
and prints as `<withheld>`; that is intended. (b) `show` sorts a dict by its PRINTED keys, so two withheld
keys cannot reveal their order. (c) If a test expectation and this code disagree on spacing, the test's text
is the specification: make the code print it.

- [ ] **Step 4: Run.** `python3 infra/hermes-agent/bin/summarize-review-bundle.test.py -v` — expected `OK`.
  Then a real bundle, read from the private directory, printing to the terminal only:
  `python3 infra/hermes-agent/bin/summarize-review-bundle.py infra/hermes-agent/security-reviews/review-9/bundle-box.json`
  Expected: 30 items, all `observed`; `D2.4` absent (review #9 predates it), so the closing list shows `LOOK`
  for the three D2.4 lines and `ok` for the others. **Read the whole output before going on**: it must hold
  no path, no hexadecimal run and nothing that names a client or a host. If it does, that is a defect: add
  the case to the tests and fix it. Do not paste the output anywhere.

- [ ] **Step 5: Run every suite, then commit.**

```bash
infra/hermes-agent/bin/run-bin-tests.sh
chmod 0755 infra/hermes-agent/bin/summarize-review-bundle.py
git add infra/hermes-agent/bin/summarize-review-bundle.py infra/hermes-agent/bin/summarize-review-bundle.test.py
git commit -m "feat(hermes): a summary tool for a trial collection that lists every item and prints no value"
```

---

### Task 10: The report template and the reviewer's brief

**Files:**
- Modify: `infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md`
- Modify: `infra/hermes-agent/deploy/security-review/REVIEWER-BRIEF.md`

- [ ] **Step 1: The template.** After the line `- **Accepted SSH keys (D1.7):** …` add:

```markdown
- **sshd `Match` lines (D1.7):** `match_lines` `<number>`, `include_elsewhere` `<number>`
- **Journal (D2.4):** `oldest_entry.journal` `<UTC time>`, `reach_days` `<number>`; `MaxRetentionSec` `<value>` set by `<file>`; `usage` `<bytes_percent_of_max_use>`% of the size limit, `<files_percent_of_max_files>`% of the file limit
- **Proxy (D4.2):** `execstart_sha256` `<sha256>`, `execstart_argv_sha256` `<sha256>` (the next review gives the first to the collector as `--last-pass-execstart`)
- **Listener check (D4.5):** `alert_log` `<as the bundle shows it>`
```

In the sign-off, after the `- **D4.6 restarts:**` line, add:

```markdown
- **D2.4 journal:** (only when `reach_days` is under 30: the UTC date the retention was raised; any limit or other directory explained)
```

- [ ] **Step 2: The brief.** In item 5, after `D1.7's statement of whose each key is,` add
  ` D2.4's date the journal's retention was raised and its statement of the journal service's restart (when `reach_days` is under 30), the laptop keychain check (BRING-UP "A security review"),`.
  In item 7, replace the parenthesis
  `(the fingerprint and its components, the box bundle's collection time, the authorised credential set, the accepted SSH keys' short fingerprints, D4.2's `execstart_sha256`, D4.5's `alert_log`, D7.1's `records`)`
  by
  `(the fingerprint and its components, the box bundle's collection time, the authorised credential set, the accepted SSH keys' short fingerprints, D1.7's `match_lines`, D2.4's oldest entry and retention, D4.2's `execstart_sha256` and `execstart_argv_sha256`, D4.5's `alert_log`, D7.1's `records`)`.

- [ ] **Step 3: Check and commit.** Before writing the D4.2 line, confirm the two field names in the collector:
  `grep -n 'execstart_sha256\|execstart_argv_sha256\|alert_log' infra/hermes-agent/bin/collect-review-evidence.py | head`
  (if a name differs, the collector's name is the right one: use it in the template and the brief).

```bash
git add infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md infra/hermes-agent/deploy/security-review/REVIEWER-BRIEF.md
git commit -m "docs(hermes): the report header carries the baselines review #9's reviewer added by hand"
```

---

### Task 11: The runbook and the README

**Files:**
- Modify: `infra/hermes-agent/deploy/BRING-UP.md`
- Modify: `infra/hermes-agent/README.md`
- Modify: `docs/evaluations/2026-10-10-journal-retention-35-days.md` (the rehearsal of each block)

Every block below is rehearsed before it is committed: the VPS blocks in Task 1's container `jr` (as root,
so drop `sudo`; say so in the record), the LAPTOP block on this Mac with a throwaway key, as section 1.10 of
`docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md` did. A block whose
rehearsal differs from its expected text is corrected, and the corrected block is the one committed. What
could not be rehearsed is marked "first run on the box" in the runbook, with the reason.

- [ ] **Step 1: A new section, "The journal's retention (finding F58)",** placed after the section
  "The listener check (finding F50)" and its closing `---`, before "Replace the OpenRouter key". Text:

````markdown
## The journal's retention (finding F58)

The server came with a journal that keeps 7 days. The security review's leak checks read the journal, and
the review needs the live refusal checks of part 2 step 11 to be in it, so the box keeps 35 days (review
item D2.4 needs 30; a journal file is deleted whole, up to a day early). The setting lives in a file of our
own; the server's `/etc/systemd/journald.conf` is not edited. Do it once, after a pull that brings
`deploy/journald-hermes-retention.conf`, and before the first review on a new box. Measured beforehand:
`docs/evaluations/2026-10-10-journal-retention-35-days.md`. Run `sudo -v` alone first. Each block is one
paste; report its output starting after the prompt line.

**VPS 1, look (read-only):**

```bash
sudo sh -c 'systemd-analyze cat-config systemd/journald.conf | grep -E "^# /|^(MaxRetentionSec|SystemMaxUse|SystemMaxFiles|MaxFileSec|SystemKeepFree|Storage)[[:space:]]*="; echo "oldest entry: $(journalctl -q --no-pager -o short-iso --no-hostname -n +1 | cut -c1-24)"; echo "journal files: $(ls /var/log/journal/$(cat /etc/machine-id) | wc -l) | disk used: $(df --output=pcent /var/log/journal | tail -1 | tr -d " ")"; echo "docker logging: $(docker info --format "{{.LoggingDriver}}")"; journalctl -u hermes-app-broker@ads-audit --since -30d -o cat --no-pager | grep -oE "status=refused reason=(disabled|quota|bad_request)" | sort | uniq -c'; date -u
```

Expected on this box: `# /etc/systemd/journald.conf` with `SystemMaxUse=1G`, `MaxRetentionSec=7day`,
`MaxFileSec=1day`; `# /usr/lib/systemd/journald.conf.d/syslog.conf` with nothing under it; an oldest entry
6 to 8 days back; about 20 files; `docker logging: json-file`; up to three refusal lines. **Stop** if
`docker logging:` is `journald` (the containers then log through the service block 3 restarts: report it,
do nothing), or if a file other than those two is listed.

**VPS 2, install the file and read the settings again.** The journal service is told nothing yet.

```bash
sudo install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d
sudo install -o root -g root -m 0644 /opt/projects/claude_code/infra/hermes-agent/deploy/journald-hermes-retention.conf /etc/systemd/journald.conf.d/50-hermes-retention.conf
systemd-analyze cat-config systemd/journald.conf | grep -E "^# /|^(MaxRetentionSec|SystemMaxFiles)[[:space:]]*="; echo "files in the directory: $(ls /etc/systemd/journald.conf.d | wc -l)"
```

Expected, in this order: `# /etc/systemd/journald.conf`, `MaxRetentionSec=7day`,
`# /etc/systemd/journald.conf.d/50-hermes-retention.conf`, `MaxRetentionSec=35day`, `SystemMaxFiles=500`,
`# /usr/lib/systemd/journald.conf.d/syslog.conf`, then `files in the directory: 1`. The LAST
`MaxRetentionSec=` line is the one that counts. **Stop** unless it is `35day` and stands under our file's
line: remove the file (`sudo rm /etc/systemd/journald.conf.d/50-hermes-retention.conf`) and report the
output. Nothing has changed for the running service at this point.

**VPS 3, apply.**

```bash
B=$(sudo journalctl -q --no-pager -o short-iso --no-hostname -n +1 | cut -c1-24); sudo systemctl restart systemd-journald; sleep 5
A=$(sudo journalctl -q --no-pager -o short-iso --no-hostname -n +1 | cut -c1-24); echo "journal service: $(systemctl is-active systemd-journald) | started: $(systemctl show systemd-journald -p ActiveEnterTimestamp --value)"; echo "oldest entry before: $B | after: $A | same: $([ "$B" = "$A" ] && echo yes || echo NO)"
for u in hermes-broker hermes-docker-proxy hermes-app-broker@ads-audit; do echo "$u: $(systemctl is-active $u)"; done
sudo systemctl start hermes-listener-check.service; echo "listener_check_rc=$?"; sudo journalctl -u hermes-listener-check --since -1min -o cat --no-pager | tail -1
```

Expected: `journal service: active` with a start time of this minute; `same: yes` (nothing was lost); three
`active` lines; `listener_check_rc=0` and a line starting `hermes-listener-check: status=ok` (a service
started after the restart writes to the journal). Then run live check c of part 2 step 11 (the malformed
request): its `c: status=refused reason=bad_request` shows that the audit broker, which was running through
the restart, still writes to the journal. `hermes-broker` and `hermes-docker-proxy` have no harmless request
to make them write; the rehearsal showed a long-running service logging through the restart. **Stop** and
go to VPS 4 if the journal service is not `active`, or `same:` is `NO`.

Write the date and time of this block (UTC) in the next review's evidence: D2.4 asks for the date the
retention was raised until the journal is 30 days long, and the restart of the journal service is not among
the starts D4.6 reports.

**VPS 4, undo (only if needed):**

```bash
sudo rm /etc/systemd/journald.conf.d/50-hermes-retention.conf && sudo systemctl restart systemd-journald; sleep 5; systemctl is-active systemd-journald
```

Then VPS 1 again: the settings are the server's own. The box is back to 7 days, and at the next daily trim
everything older leaves the journal.

Reading it later: review item D2.4 reports the reach, the settings and the file that sets each, whether the
running service has read them, and how near the journal is to its size and file limits. If D2.4 shows
`config_changed_after_start: true` (a settings file changed after the service started, for example after a
system update), run VPS 3 again and collect again.

---
````

- [ ] **Step 2: Part 2 step 11, the guarded live refusal checks.** Replace the body of step 11 (from
  `11. Live refusal checks` up to the line before `12. Rollback`) by the blocks of the appendix of
  `docs/superpowers/handoffs/2026-10-09-review-9-pass.md` ("VPS, the client at a hidden prompt", "live check
  a", "live check b", "live check c", "VPS, afterwards"), copied byte for byte, each as its own fenced block
  with its expected line, under this introduction:

```markdown
11. Live refusal checks (review D10.7 needs one each of `refused/disabled`, `refused/quota` and
    `refused/bad_request` in the broker journal, 30 days back; with "The journal's retention" applied they
    stay 35 days). They place a request file in the spool the way the gateway's MCP tool does and read the
    journal line the broker writes for it (it polls every 2 s). None runs an audit. Each block is one paste
    and prints only `status=… reason=…`, never the client; the client is typed once, at a hidden prompt.
    These are the blocks used on the box on 2026-10-09. Check b needs a real chat audit for that client on
    the same UTC day (step 10) and places its request only when the broker's own counter says exactly 1.
    Every block cleans up after itself: if the broker does not answer, the test request is deleted, and in
    check a the kill switch is LEFT ON; say so and stop.
```

  Keep step 11's three explanations that the blocks rest on, as one sentence each after the block it belongs
  to: (a) a request still in `requests/` is decided afresh once the switch is gone, and could start a real
  audit; (b) the quota is counted only while a `run` for that client is held today; (c) a badly named file
  is only `dropped/bad_request`, which does not count. Keep the last sentence about `results/` and D10.8.
  Then check that nothing was lost: `git diff -U0 -- infra/hermes-agent/deploy/BRING-UP.md | grep '^-' | grep -c 'sudo'`
  and read every removed command: each must be inside one of the new blocks.

- [ ] **Step 3: "A security review".** In that section:
  - First paragraph, after `(D1.7) and each service's start time (D4.6)` add `; since v1.19 it reads the journal's reach and settings (D2.4), which needs "The journal's retention" applied`. Replace `must have been run within the last 30 days (D10.7)` by `must be in the journal, at most 30 days back (D10.7; read the three counts with the last line of step 11 before collecting, never assume them)`.
  - Step 2: delete the three sentences from `Then count the `Match` blocks in the sshd configuration (D1.7):` up to and including `on the box it runs for the first time).` and put in their place: `The collector counts the sshd `Match` lines itself since v1.19 (D1.7 `match_lines` and `include_elsewhere`).`
  - Step 2, the trial collection: replace the parenthesis that starts `(the collector run once with a throwaway key` so that it ends with: `… typed or pasted at the collector's key prompt and discarded afterwards; pipe it into the summary tool, ALONE: `cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --fp-key-tty | python3 infra/hermes-agent/bin/summarize-review-bundle.py; echo "collector_rc=${PIPESTATUS[0]}"`. It lists every item with its status and ends with a list headed "Before the real collection": every line there should read `ok`, and a `LOOK` line says what to settle first. It prints counts, times and short words only, so its output can be pasted in full)`.
  - After step 3's `Once the key is pasted, clear the laptop's clipboard: `pbcopy < /dev/null`.` add: `A value that is pasted at a prompt on the box is copied in a SECOND laptop window, after the block is pasted and its prompt is waiting: copying the block itself replaces what the clipboard held.`
  - Step 6: replace `D1.7's statement of whose each accepted key is (and the `Match` count of step 2)` by `D1.7's statement of whose each accepted key is, D2.4's date the journal's retention was raised (while `reach_days` is under 30) with the time the journal service was restarted, the laptop keychain check below`. At the end of step 6 add: `Every console screen and every pasted output is read in full before it goes into the evidence file: twice a paste turned out to be the day before's, and once a screen showed more than the statement said.`
  - After step 6, a new step 7:

````markdown
7. Laptop, for the evidence file: is the administrative key's passphrase still out of the keychain (step 7f
   took it out)? One function and its call; it prints counts only. The first two lines only read. The third
   part asks the keychain to load what it holds, which is the only way to see what it would supply: if it
   supplies the administrative key, the block takes the key out of the agent again and says so.

```bash
kc() {
  local FP K="$HOME/.ssh/vps-hermes"
  echo "UseKeychain lines left in the file: $(grep -ciE '^[[:space:]]*usekeychain([[:space:]=]|$)' "$HOME/.ssh/config" 2>/dev/null)"
  echo "ssh on the new alias: $(pgrep -f '19119:127\.0\.0\.1:9119 hermes-box-tunnel$' | wc -l | tr -d ' '); ssh on the old alias: $(pgrep -f '19119:127\.0\.0\.1:9119 hermes-box$' | wc -l | tr -d ' ')"
  FP=$(ssh-keygen -lf "$K.pub" 2>/dev/null | awk '{print $2}')
  [ -n "$FP" ] || { echo "STOPPED: could not read the key's public file"; return; }
  if [ "$(ssh-add -l 2>/dev/null | grep -cF "$FP")" != 0 ]; then echo "STOPPED: the key is in the agent already (a work session): run this again after 'ssh-add -d ~/.ssh/vps-hermes'"; return; fi
  ssh-add --apple-load-keychain >/dev/null 2>&1; echo "keychain load rc=$?"
  if [ "$(ssh-add -l 2>/dev/null | grep -cF "$FP")" = 0 ]; then echo "supplied by the keychain: 0"; else ssh-add -d "$K" >/dev/null 2>&1; echo "supplied by the keychain: 1 -- the passphrase is in the keychain again; the key was taken out of the agent; stop and report"; fi
}; kc; unset -f kc
```

   Expected: `UseKeychain lines left in the file: 0`; `ssh on the new alias: 1; ssh on the old alias: 0`;
   `keychain load rc=0`; `supplied by the keychain: 0`. Paste the four lines into the evidence file. Any
   other output: stop and report it; do not run step 7f's removal again without asking.
````

- [ ] **Step 4: The corrections from the rollout of 2026-10-08.** Each replaces a mark by what the box and
  this laptop showed that day (the operator's outputs, handoff `2026-10-08-rollout-done-review-9-next.md`).
  Find each with `grep -n 'not rehearsed\|Not rehearsed\|First run on this laptop' infra/hermes-agent/deploy/BRING-UP.md`.
  - LAPTOP 3b, the sentence `macOS's own `nc`, `curl` and `ssh` against a real server were not rehearsed: pasted into zsh on this Mac the block ran only with `ssh`, `scp` and `curl` replaced by stand-ins.` becomes: `Run for real on this Mac against the box on 2026-10-08: gate `rc=1`, T1 `302`, T4 `0 bytes, link up`, T5a `refused`, T5b `refused`, T6 `0 bytes, link up`, T7 `rc=255`.`
  - LAPTOP 4b, `**First run on this laptop, not rehearsed**: the rehearsal replaced `launchctl` by a stand-in, so only the block's own check and its order were run.` becomes: `Run for real on this Mac on 2026-10-08: `RELOADED: bootstrap rc=0`.`
  - LAPTOP 4c, `**First run on this laptop, not rehearsed for real**: its `launchctl print` ran only as a stand-in, and the other two lines ran with another port number against a scratch page and stand-in processes.` becomes: `Run for real on this Mac on 2026-10-08: `state = running` together with two `state = active` lines, `302`, `ssh on the new alias: 1; ssh on the old alias: 0`.` And in its expected text, `Expected: `state = running`;` becomes `Expected: one `state = running` line (this macOS also prints two `state = active` lines, from nested sections of `launchctl print`: they are not a fault; what matters is that `state = running` is there);`. In the first bullet under it, `No `state = ` line, or another state;` becomes `No `state = running` line;`.
  - LAPTOP 5c, in the expected text, after `Expected: `Identity added: …`, `in the agent before: 1`, `Identity removed: …`,` add the sentence (after the list ends): `The first and third lines carry the key's path and its comment: do not paste those two lines, report the other four.` And in the bullet on `keychain load rc=`, the sentence that starts `Not measured: what the real `ssh-add --apple-load-keychain` ends with` and ends `it is still the right thing to report.)` becomes: `Measured on 2026-10-08 with the real key: `keychain load rc=0` and `supplied by the keychain: 0`.)`
  - LAPTOP 6a, `Not rehearsed: the same on macOS, where the keychain could answer.` becomes: `On this Mac, 2026-10-08: `ssh hermes-box` asked for the passphrase and got in; the keychain did not answer.`
  - Leave every other mark as it is (the login item's stop command, `ssh-add -d` after a login, a `generate` that fails in step 7e): none of those ran.

- [ ] **Step 5: The README.** In "Security review and app packages", after the sentence that ends
  `and the operator's sign-off.` add: `A trial collection is read through `bin/summarize-review-bundle.py`, which lists every item with its status and prints counts, times and short words only. The box keeps 35 days of journal by a settings file of its own (`deploy/journald-hermes-retention.conf`, finding F58; `deploy/BRING-UP.md`, "The journal's retention"); review item D2.4 reports how far back the journal reaches.`

- [ ] **Step 6: Rehearse, record, test, commit.** Rehearse VPS 1 to 4 in `jr` (VPS 1's Docker and broker
  lines have nothing to read there: expected empty, say so; VPS 3's listener check and unit lines likewise)
  and `kc` on this Mac with a throwaway key in the place of `vps-hermes` (set `K` to it for the rehearsal
  only). Add the outputs to the evaluation record under "The runbook blocks, as written". Then:

```bash
infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/deploy/provision.test.py && node scripts/run-all-tests.js
git add infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md docs/evaluations/2026-10-10-journal-retention-35-days.md
git commit -m "docs(hermes): the journal step, the guarded live refusal checks, the keychain check, the rollout's corrections"
```

---

### Task 12: The independent review of the build, then the operator's word

- [ ] **Step 1: Everything green.** `infra/hermes-agent/bin/run-bin-tests.sh`,
  `python3 infra/hermes-agent/deploy/units.test.py`, `python3 infra/hermes-agent/deploy/provision.test.py`,
  `node scripts/run-all-tests.js`, `python3 infra/hermes-agent/bin/check-checklist-version.py --base main`.
  Paste the last line of each into the request for review.

- [ ] **Step 2: A reviewer that did not build it** (the operator's word is needed to start an agent). It
  receives the design, this plan, the evaluation record and `git diff main...HEAD`, and is asked for, in this
  order:
  1. Anything in `d2_4`, `d2_3`, `d10_7` or `d1_7` that could show a healthy value for something not
     measured, or put a journal line, a machine id, a host name or a key body into a bundle.
  2. Any line `sshd` accepts as a key that the new `_key_row` hides or shows with other options (the reverse,
     a line shown that `sshd` refuses, is acceptable and must be said).
  3. Anything the summary tool can print that is not a number, a boolean, a time or a short word.
  4. Every checklist sentence against the code: a field named that the collector does not report, a rule
     that a healthy box as measured on 2026-10-10 would fail, a rule a 7-day journal would pass.
  5. Every runbook block: what happens when it is pasted twice, when a line fails half-way, and whether its
     expected text matches the rehearsal's output in the record.
- [ ] **Step 3:** Fix what the review finds, each with a test or a re-run rehearsal; record a finding that is
  not fixed with its reason. Re-run Step 1.
- [ ] **Step 4:** Tell the operator, in plain language: what was built, what the review found, what was
  rehearsed and what will run on the box for the first time. Ask for the word to push and open the pull
  request. The operator merges.

---

### Task 13: The rollout on the box (operator, block by block)

Deadline that matters: the live refusals of 2026-10-09 leave the journal between 2026-10-15 and 2026-10-16,
about 15:00 UTC. If the journal step is applied before then, they stay 35 days. If not, nothing is lost but
time: step 11 is run again before review #10.

- [ ] **Step 1 (VPS):** `cd /opt/projects/claude_code && sudo git pull --ff-only && git log --oneline -1`.
  Expected: the merge commit of this change.
- [ ] **Step 2 (VPS, ALONE, with a throwaway key):** the trial collection through the summary tool
  (BRING-UP "A security review", step 2). Expected: 31 items; `LOOK` for the D2.4 lines (the file is not
  installed yet) and `ok` for the rest; D4.6 `files_newer_than_start` empty for every service (the changed
  files are the collector, the summary tool and the settings file, which no running service loads). If a
  service is named: restart it, as in the review #9 rollout, and say so in the evidence.
- [ ] **Step 3 (VPS):** "The journal's retention", VPS 1, then VPS 2, then VPS 3, each on its own, each
  output reported before the next. Write down the UTC time of VPS 3.
- [ ] **Step 4 (VPS):** live check c of step 11 (the malformed request; it needs no client and no prompt).
  Expected `c: status=refused reason=bad_request`.
- [ ] **Step 5 (VPS, ALONE):** the trial collection again. Expected: every closing line `ok` except
  `the journal reaches 30 days`, which reads `LOOK … reach is N days: the evidence needs the date the
  retention was raised` until the journal is 30 days long. That line is expected, and Step 3's time answers it.
- [ ] **Step 6:** if Task 0 found a journal directory of another machine and the operator chose to delete it:
  one block, written then, that prints the directory's file count, removes that one directory by its
  `own=no` test (never by a typed name) and prints the count of directories left. Otherwise nothing.
- [ ] **Step 7 (agent):** `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`, F58's "Now"
  cell becomes: `**fixed on the box <date of Step 3>** (checklist v1.19): the box keeps 35 days by a settings
  file of its own (`deploy/journald-hermes-retention.conf`); review item D2.4 reports the reach, the settings,
  whether the running service has read them and how near the journal is to its limits; D2.3 and D10.7 report
  the oldest entry they read. Until the journal is 30 days long (<date of Step 3 plus 30 days>), D2.4 passes
  on the operator's statement of the date the retention was raised.` Add the box's values before and after
  to the evaluation record. Commit on a new branch; push only with the operator's word.

---

### Task 14: Security review #10

As the handoff `2026-10-09-review-9-pass.md` describes a review, with what this change adds:

- [ ] One chat audit first (D10.8: the `run`/`ok` result of 2026-10-09 leaves the box on 2026-10-16 13:39 UTC).
- [ ] Read the three refusal counts (last line of step 11). Missing: run step 11's checks, on the audit's UTC day.
- [ ] The trial collection through the summary tool; every `LOOK` line settled or explained before the real one.
- [ ] The real collection with `--last-pass-execstart` and `--last-pass-collected-at 2026-10-09T14:01:23Z`
  (both are in review #9's report header); the laptop bundle; both on the sign-off's UTC day.
- [ ] The evidence file, every statement marked `[CONFIRM]` until the operator confirms it: the manual items;
  the date and time the retention was raised and the journal service restarted (D2.4); anything Task 0 found
  about another journal directory; the keychain check's four lines; D4.6's restarts; D1.7's keys. No pasted
  `Match` count: the bundle carries it.
- [ ] `review-10/previous-pass-header.md` from review #9's report (header and sign-off only).
- [ ] A fresh reviewer with only what `REVIEWER-BRIEF.md` lists. The operator signs. The report is committed
  and pushed with the operator's word; the operator merges.
- [ ] Afterwards: the handoff for the next session, and the brain entry through `brain-capture` (the operator
  promotes).
