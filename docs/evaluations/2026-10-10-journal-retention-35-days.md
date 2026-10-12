# Evaluation — 35 days of journal on the box, and the rehearsal of the journal service's restart

> **Date:** 2026-10-10 · **Asked:** does a drop-in `journald.conf.d/50-hermes-retention.conf` (`MaxRetentionSec=35day`,
> `SystemMaxFiles=500`) override the server's own `/etc/systemd/journald.conf` (`MaxRetentionSec=7day`), and is
> restarting `systemd-journald` safe for a long-running service? **Method:** the real file from the repository
> (`infra/hermes-agent/deploy/journald-hermes-retention.conf`) was installed into throwaway Ubuntu 24.04 containers
> that run systemd 255 (Docker 29 on the laptop, linux/aarch64), set up with the box's journal settings. Nothing on
> the box was touched by this rehearsal. Container ids, machine ids, boot ids and journal cursors are cut (`<cut>`).

## 1 · Sources, authority and what each verified

All at tag `v255` on github.com/systemd/systemd (`https://github.com/systemd/systemd/blob/v255/<path>`).

| Source | Authority | Verified there | Read |
|---|---|---|---|
| `man/journald.conf.xml` | primary | The settings, their defaults and units: `MaxRetentionSec=` defaults to 0 (off) and takes the units year, month, week, day, h and m (the man page; `min` is from `time-util.c`); `SystemMaxFiles=` defaults to 100; drop-in directories under `/etc/systemd`, `/run/systemd`, `/usr/lib/systemd`. | 2026-10-09 |
| `man/systemd-analyze.xml` | primary | `cat-config` copies a config file and its drop-ins to standard output "using the usual systemd set of directories and rules for precedence". | 2026-10-10 |
| `man/journalctl.xml` | primary | `--lines=`: with a `+` prefix "the oldest journal events are used instead". `--output-fields=`: for the json mode, `__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP` and `_BOOT_ID` are always printed. (R5 measured that `__SEQNUM` and `__SEQNUM_ID` are printed too.) | 2026-10-10 |
| `src/libsystemd/sd-journal/journal-vacuum.c` | primary | An archived file is deleted when the time in its name is older than the retention; `patch_realtime()` lowers that time to the earliest of the file's own times (ctime, atime, mtime), and also the file's creation time where the file system gives one (`fd_getcrtime_at`), when one of them is earlier; the file and size limits are counted in one directory. | 2026-10-10 |
| `src/shared/pretty-print.c` | primary | `cat-config` prints a `# <path>` header, with an empty line before every file but the first. | 2026-10-10 |
| `src/basic/time-util.c` | primary | The time units (`day`, `min`); `min` is here, not in the man page's list. | 2026-10-10 |
| The rehearsal (section 3) | measurement | R1 to R6. | 2026-10-10 |
| The key-case measurement (section 3b) | measurement | What `sshd` 9.6p1 does with four key lines. | 2026-10-10 |
| The operator's read-only look at the box (section 2) | measurement on the box | The box's OpenSSH release and package revision, how its sshd is started, the journal's on-disk flag, no linked settings path. | 2026-10-11 |
| The runbook blocks (section 5) | measurement | Each block of the runbook as written, in the stand-in; the laptop block against a private agent. | 2026-10-11 |

## 2 · The box, read-only

- **2026-10-09** (`systemd-analyze cat-config systemd/journald.conf`): `SystemMaxUse=1G`, `MaxRetentionSec=7day` and
  `MaxFileSec=1day` are set in `/etc/systemd/journald.conf`; `/etc/systemd/journald.conf.d/` does not exist; the only
  drop-in is the distribution's `/usr/lib/systemd/journald.conf.d/syslog.conf`. 7 days of journal took 85.4M (read
  with `sudo`); the disk was 13% used. At about 13:35 UTC the oldest entry of the whole journal was 2026-10-02 15:11
  UTC, about 6 days 22 hours old.
- **2026-10-10 12:43 UTC (M1 to M3, by the operator):** M1: 22 journal files, at most 4 with the same date, 14
  `system` and 8 `user-1000`; one file is dated 2026-09-05 (the day the server image was made), older than the
  retention allows. M2: the whole journal is 4,630,823 bytes of text, read in 2 s; the broker's journal is 16 lines
  and the runner's 38. M3: Docker's logging driver is `json-file`, for the default and for the one container;
  systemd 255; 7940 MB of memory, 6589 MB available. The three live refusals were in the journal.

### Task 0 (the operator's read-only look)

Task 0, run by the operator on the box, 2026-10-10 17:41:47 UTC (pasted starting after the prompt line):

```
journal dir: own=no files=1 dates=2026-09-05 2026-09-05 
journal dir: own=yes files=22 dates=2026-10-05 2026-10-10 
oldest, whole: __REALTIME_TIMESTAMP":"1791126754096580
oldest, broker 30d: __REALTIME_TIMESTAMP":"1791225347188639
oldest, no such unit: [rc=0]
1:# /etc/systemd/journald.conf
2:[Journal]
3:SystemMaxUse=1G
4:SystemMaxFileSize=100M
5:MaxRetentionSec=7day
6:MaxFileSec=1day
7:Compress=yes
9:# /usr/lib/systemd/journald.conf.d/syslog.conf
13:[Journal]
14:ForwardToSyslog=yes
journal service started: Wed 2026-09-30 06:23:38 UTC
Sat Oct 10 17:41:47 UTC 2026
```

What it shows:
- The file dated 2026-09-05 is in a directory of ANOTHER machine id (own=no, 1 file). The service does not trim it and journalctl does not read it. D2.4 will report `other_directories: 1`.
- Oldest entry of the whole journal: 1791126754 s = 2026-10-04 15:12:34 UTC, 6.1 days before the block's date: inside the expected 6 to 8 days, no gap.
- Oldest broker entry in 30 days: 2026-10-05 18:35:47 UTC.
- A unit with no entry: no output, rc 0 (so `_oldest_entry` returns None there).
- The settings printout has the form Task 6's parser reads: `# <path>` headers, the second after an empty line (line 8). Also set in the server's file and not known before: `SystemMaxFileSize=100M`, `Compress=yes`.
- The journal service started 2026-09-30 06:23:38 UTC.
- Timing settled: at 17:41 on 2026-10-10 the oldest entry was 2026-10-04 15:12, so the daily trim (about 15:12 UTC) had already deleted the file that began 2026-10-03 15:12, at 7.0 days. The file holding the 2026-10-09 refusals began 2026-10-08 about 15:12 and so leaves at the trim of 2026-10-15, about 15:12 UTC.
- The operator's decision (2026-10-10): the other machine's directory is left as it is and stated in review #10's evidence.

### The sshd and journal look (the operator's read-only block, 2026-10-11)

Run by the operator on the box, 2026-10-11 01:31:04 UTC (pasted starting after the prompt line; account names inside
process titles were replaced by the block's own `sed`):

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
ssh.socket: active | ssh.service: active
root     sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
root     sshd: <account> [priv]
hermeso+ sshd: hermesops
root     sshd: <account> [priv]
hermeso+ sshd: <account>@<terminal>
ExecStart=/usr/sbin/sshd -D $SSHD_OPTS
SSHD_OPTS=
journal on disk flag: yes
settings paths that are links: 0
Sun Oct 11 01:31:04 UTC 2026
```

What it shows:
- The box runs OpenSSH_9.6p1 Ubuntu-3ubuntu13.19, the same release and package revision the key-line and configuration measurements were made on (section 3b). This replaces "no record of that reading was found".
- sshd is socket-activated (`ssh.socket` active) and `ssh.service` is active; the unit starts `/usr/sbin/sshd -D $SSHD_OPTS` and `SSHD_OPTS` is empty.
- The process list has ONE listener line, in exactly the form measured in the container (`sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups`), with no `-f` and no `-o`: D1.7 `daemon_options` will read `{"listeners": 1, "config_file_options": 0, "setting_options": 0}`.
- The other lines are session children in forms the collector's closed set knows: `sshd: NAME [priv]`, `sshd: NAME@terminal`, and a bare `sshd: hermesops`, which is ignored because `hermesops` is an account in `/etc/passwd`.
- `/run/systemd/journal/flushed` exists: the journal is on disk (D2.4 `usage.flushed_to_disk` will be `true`).
- None of the fourteen path parts D2.4 walks is a symbolic link.

### The rollout on the box (2026-10-12, the operator, block by block)

Each block is the runbook's (`deploy/BRING-UP.md`, "The journal's retention"), pasted by the operator; the
outputs below are as reported, with nothing cut.

- **Pull** (before the first trial collection): the checkout moved from `df58e10` to `634c190` (the merge of PR #114), fast-forward;
  `git status --short` printed 0 lines.
- **Trial collection before the step** (`collected_at 2026-10-12T15:08:35Z`, through the summary tool): 31 items,
  all observed, `collector_rc=0`. D2.4: `MaxRetentionSec` `7day` (604800, not set by our file), `SystemMaxUse` `1G`,
  `MaxFileSec` `1day`, `Storage` and `SystemMaxFiles` set by no file; `reach_days` 6; `drop_in` not equal to the
  repository's, owner, group and mode `could-not-check` (the file was not installed); service active, started
  2026-09-30T06:23:38Z, `config_changed_after_start` false; 24 files, 101593088 bytes (9.5% of the size limit),
  87.7% of the disk free, 1 other directory, `flushed_to_disk` true. Five closing lines read `LOOK`, the five the
  runbook names. One difference from the runbook: the first of them read `(4 places)`, not 3. The fourth is the
  KEY `could-not-check` in D4.5's `history_counts` (`{could-not-check: 1, ok: 472}`), a count of past runs of the
  listener check, which the summary tool counted as a place; review #9's report shows the same single run and
  CHECKLIST D4.5 calls it a count of runs. The tool no longer counts that key (it prints
  `(not counted: N past listener-check runs in D4.5's history)`), changed after the rollout.
- **VPS 1** (15:15:45 UTC): the server's own file with `SystemMaxUse=1G`, `MaxRetentionSec=7day`, `MaxFileSec=1day`;
  the `syslog.conf` drop-in with nothing under it; oldest entry 2026-10-05T16:53:19+00:00; 25 journal files, disk
  13% used; journal on disk yes; 0 settings paths that are links; `sshd release: OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`
  (the first time the server program itself was asked on the box); 1 listener, 0 words starting `-f` or `-o`;
  `docker logging: json-file`; one refusal each of `bad_request`, `disabled`, `quota`.
- **VPS 2**: our file listed third, `MaxRetentionSec=35day`, `SystemMaxFiles=500`; 1 file in the directory.
- **VPS 3**: `journal service: active | started: Mon 2026-10-12 16:06:05 UTC | journal on disk: yes`; oldest entry
  before and after 2026-10-05T16:53:19+00:00, `same: yes`; `hermes-broker`, `hermes-docker-proxy` and
  `hermes-app-broker@ads-audit` active; `listener_check_rc=0` and
  `hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[] docker_dns_listeners=1`; the block ended
  Mon Oct 12 16:06:11 UTC 2026. **The retention was raised on 2026-10-12 at 16:06:05 UTC.**
- **Live check c**: `c: status=refused reason=bad_request` (the audit broker, running since 2026-10-08, writes to
  the journal after the restart).
- **Trial collection after the step** (`collected_at 2026-10-12T16:10:39Z`): 31 items, all observed,
  `collector_rc=0`. D2.4: `MaxRetentionSec` `35day` (3024000) and `SystemMaxFiles` 500, both set by our file;
  `drop_in` equal to the repository's, root, root, `0o644`, 0 other files; service active, started
  2026-10-12T16:06:05Z, `config_changed_after_start` false; 25 files (5.0% of the file limit), 106614784 bytes
  (9.9%), `on_disk_age_seconds` 19, `flushed_to_disk` true; `reach_days` 6. D2.3: 4718282 characters, 0
  undecodable, oldest entry read 2026-10-05T16:53:19Z, no hit. D10.7: refusals `bad_request` 2, `disabled` 1,
  `quota` 1. Four closing lines read `LOOK`: could-not-check `(1 places)` (the history key above), the reach (6
  days), the other directory (1), and the proxy (a trial is given no last-PASS reference). The retention line, the
  service line and the on-disk line read `ok`.
- Nothing was undone and nothing was deleted: the other journal directory stays, as the operator decided on
  2026-10-10.

## 3 · The rehearsal

The image is `ubuntu:24.04` with `systemd`, `systemd-sysv`, `python3`, `bsdutils`; its `/etc/systemd/journald.conf`
is `Storage=persistent`, `SystemMaxUse=1G`, `MaxRetentionSec=7day`, `MaxFileSec=1day` (the box's values), and a unit
`ticker.service` echoes a line every second (a stand-in for a long-running service). Stand-ins used for the
runbook's blocks (section 5): the container itself for the server; in the second round a unit named
`hermes-listener-check.service` and a script in the place of the audit broker; for the laptop block a private ssh
agent, a throwaway key and, for one run, a shell function in the place of the keychain load. Section 5 says for
each output which of these it rests on. Containers were started with
`--privileged --cgroupns=host`, `/run` and `/run/lock` as tmpfs, and the host's `/sys/fs/cgroup` mounted; the
first attempt worked, so the fallback (no container) was not needed.

**Start (Step 1).** `systemctl --version | head -1`: `systemd 255 (255.4-1ubuntu8.17)`; `systemctl is-active
systemd-journald ticker`: `active`, `active`. As expected.

### R1, R2 — the settings before anything is installed (Step 2)

`docker exec jr systemd-analyze cat-config systemd/journald.conf` printed:

```
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day

# /usr/lib/systemd/journald.conf.d/syslog.conf
# Undo upstream commit 46b131574fdd7d77 for now. For details see
#  http://lists.freedesktop.org/archives/systemd-devel/2014-November/025550.html

[Journal]
ForwardToSyslog=yes
```

R1: the main file comes first, with the `# /etc/systemd/journald.conf` header. R2: the only other file is the
distribution's `syslog.conf`, after an empty line and its own `# <path>` header. Matched the expectation, and the
same shape as the box's 2026-10-09 reading.

### R3, R4 — install our file, read the settings, restart, compare (Step 3)

The file installed (`root:root`, `0644`) is the repository's real file (`MaxRetentionSec=35day`,
`SystemMaxFiles=500`). The grep of `cat-config` printed (line numbers are grep's):

```
1:# /etc/systemd/journald.conf
5:MaxRetentionSec=7day
8:# /etc/systemd/journald.conf.d/50-hermes-retention.conf
17:MaxRetentionSec=35day
18:SystemMaxFiles=500
20:# /usr/lib/systemd/journald.conf.d/syslog.conf
```

The restart line:

```
service: active | oldest before: 2026-10-10T17:43:26+00:0 | after: 2026-10-10T17:43:26+00:0 | ticker lines before: 13 | after: 18 | ticker: active
```

R3: the last `MaxRetentionSec=` is `35day`, under the `50-hermes-retention.conf` header; the drop-in is printed
after the main file. R4: after `systemctl restart systemd-journald` the service is active, the oldest entry is the
same (the 24-character cut of the time ends `+00:0`; that is the brief's own `cut -c1-24`), the ticker has more
lines after (13 to 18) and is active. Matched.

### R5 — the collector's three `journalctl` forms (Step 4)

Options: `-q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1`. Output, cursor, boot id and sequence id
cut:

```
whole: {"__SEQNUM":"627","__MONOTONIC_TIMESTAMP":"112046410","__REALTIME_TIMESTAMP":"1791654206417845","__SEQNUM_ID":"<cut>","_BOOT_ID":"<cut>","__CURSOR":"<cut>"}
unit, 30d: {"__SEQNUM_ID":"<cut>","__CURSOR":"<cut>","__REALTIME_TIMESTAMP":"1791654206462246","__MONOTONIC_TIMESTAMP":"112090812","_BOOT_ID":"<cut>","__SEQNUM":"1285"}
no such unit: [] rc=0
2026-10-10T17:43:26+00:0
```

- Each call gives one one-line JSON object with no message and no host name, but with **six** fields, not four:
  `__SEQNUM` and `__SEQNUM_ID` are printed as well (the manual lists four). Differed from the brief, harmlessly.
- The JSON prints `"__REALTIME_TIMESTAMP":"…"` **without** spaces around the colon, with the value as a quoted
  string of microseconds, and the field order varies from call to call (parse JSON, do not match by position).
- The unit that does not exist gives an empty output (`[]` around nothing) and exit status 0.
- The `whole` timestamp (1791654206417845 microseconds, 2026-10-10T17:43:26 UTC) is the same second as the FIRST
  line of the plain journal (the plain output was cut to the second; the brief said "last line"; the command prints the first, and `-n +1` is the oldest).
- Does `-n +1` with `-u … --since -30d` give the oldest entry of the window? **Yes.** Checked a second way: the
  first line of `journalctl -o json --output-fields=__REALTIME_TIMESTAMP -u ticker --since -30d` (no `-n`) and the
  `-n +1` call both gave `"__REALTIME_TIMESTAMP":"1791654206462246"`; the whole journal's first line and its
  `-n +1` both gave `1791654206417845`. So Task 8's fallback (dropping `--since -30d`) is NOT needed.
  (Exit status of `-u no-such-unit -n +1` was re-checked on its own: 0.)

### R6 — the override is in force, with a control (Step 5)

Two fresh containers from the same image, `jr-control` and `jr-treated`; only `jr-treated` got our file. In both,
`MaxRetentionSec` in `/etc/systemd/journald.conf` was set to `3min`, the journal service restarted, a line
`REHEARSAL-MARK` logged and the journal rotated; then six rounds of 60 s, each followed by `journalctl --rotate` in
both. Result:

```
control: marks left 0
treated: marks left 1
```

The `cat-config` of each at the end: control shows `MaxRetentionSec=3min` from `/etc/systemd/journald.conf` only;
treated shows `MaxRetentionSec=3min` from the main file and then `MaxRetentionSec=35day` under
`# /etc/systemd/journald.conf.d/50-hermes-retention.conf`. Matched: the control lost the mark's file (the server's
3 minutes applied), the treated container kept it (our file's 35 days overrode it), so the experiment is valid.
Both containers were removed afterwards.

### R7 · the probe `d2_4` against a real journal service

Measured 2026-10-10 in the running systemd 255 container `jr` (our file installed and the service restarted in R3;
the repository mounted read-only). The probe was called as the brief gives it, from a script at
`<scratchpad>/probe.sh`:

```
docker exec jr python3 -c '
import importlib.util, json
s = importlib.util.spec_from_file_location("ce", "/opt/projects/claude_code/infra/hermes-agent/bin/collect-review-evidence.py")
ce = importlib.util.module_from_spec(s); s.loader.exec_module(ce)
print(json.dumps(ce.d2_4(ce.Host(), {}), indent=1))'
```

**Before the first run: how the start time must be read.** Read-only, in `jr`:

```
$ systemctl show systemd-journald -p ExecMainStartTimestamp -p InactiveExitTimestamp -p ActiveEnterTimestamp
ExecMainStartTimestamp=Sat 2026-10-10 17:43:38 UTC
InactiveExitTimestamp=Sat 2026-10-10 17:43:38 UTC
ActiveEnterTimestamp=Sat 2026-10-10 17:43:38 UTC
$ systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p InactiveExitTimestamp -p ActiveEnterTimestamp
ExecMainStartTimestamp=Sat 2026-10-10 17:43:38.112198 UTC
InactiveExitTimestamp=Sat 2026-10-10 17:43:38.112275 UTC
ActiveEnterTimestamp=Sat 2026-10-10 17:43:38.123219 UTC
$ stat -c "%n %y | %z" /etc/systemd/journald.conf.d /etc/systemd/journald.conf.d/50-hermes-retention.conf
/etc/systemd/journald.conf.d 2026-10-10 17:43:38.089807001 +0000 | 2026-10-10 17:43:38.089807001 +0000
/etc/systemd/journald.conf.d/50-hermes-retention.conf 2026-10-10 17:43:38.090807001 +0000 | 2026-10-10 17:43:38.090807001 +0000
```

`--timestamp=unix` printed `@1791654218` (seconds only); a unit that does not exist printed an empty line, rc 0.
Our file was written 21 ms before the service's process started, inside the same second. So the plan's comparison
(a file's time against `ActiveEnterTimestamp` at second precision, `17:43:38.090 > 17:43:38`) would have reported
`config_changed_after_start: true` for this healthy container, and would do so on the box whenever BRING-UP's install
and restart fall in one second. The probe therefore asks for `ExecMainStartTimestamp` with `--timestamp=us+utc` (the
moment the process was started, which is before it can read anything; `ActiveEnterTimestamp` is 11 ms later, when
the service has reported ready, and whether it has read its settings by then was not measured) and compares to the
microsecond. A change stamped less than 10 ms before the start counts as after
it: a file's time comes from the kernel's coarse clock, which can be one tick behind (10 ms is the longest tick Linux
is built with; the tick length of this kernel was not measured, and no such case was produced here).

**Run 1, as found (healthy).** (This run predates `Storage`, `service.active`, `flushed_to_disk`, `newest_entry_on_disk` and
`on_disk_age_seconds`, which later fixes added: R10, R11, R13 show them.) As expected: a time for the journal and `null` for the two units, `35day` from our
file, `1G`, the file equal to the repository's, `config_changed_after_start` `false`, the usage in numbers.

```
{
 "oldest_entry": {
  "journal": "2026-10-10T17:43:26Z",
  "broker": null,
  "runner": null
 },
 "reach_days": 0,
 "settings": {
  "MaxRetentionSec": {
   "value": "35day",
   "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
   "number": 3024000
  },
  "SystemMaxUse": {
   "value": "1G",
   "file": "/etc/systemd/journald.conf",
   "number": 1073741824
  },
  "SystemMaxFiles": {
   "value": "500",
   "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
   "number": 500
  },
  "MaxFileSec": {
   "value": "1day",
   "file": "/etc/systemd/journald.conf",
   "number": 86400
  }
 },
 "config_files": [
  "/etc/systemd/journald.conf",
  "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
  "/usr/lib/systemd/journald.conf.d/syslog.conf"
 ],
 "drop_in": {
  "equals_repo": true,
  "owner": "root",
  "group": "root",
  "mode": "0o644",
  "other_files": []
 },
 "service": {
  "started_at": "2026-10-10T17:43:38Z",
  "config_changed_after_start": false
 },
 "usage": {
  "bytes": 8392704,
  "files": 1,
  "bytes_percent_of_max_use": 0.8,
  "files_percent_of_max_files": 0.2,
  "free_bytes": 915426824192,
  "free_percent": 93.6,
  "other_directories": 0
 }
}
```

**Run 2, after `docker exec jr touch /etc/systemd/journald.conf`.** The output differs from run 1 in two lines only
(the second is the free space moving by 4096 bytes):

```
  "config_changed_after_start": true
  "free_bytes": 915426820096,
```

**Run 3, a broken drop-in** (`printf '[Broken\n[Journal]\nCompress=yes\n' > /etc/systemd/journald.conf.d/10-x.conf`;
the journal service was NOT restarted). `settings` and `config_files` are `could-not-check`, and with them the two
percentages and `config_changed_after_start`; the neighbour is named in `other_files`:

```
{
 "oldest_entry": {
  "journal": "2026-10-10T17:43:26Z",
  "broker": null,
  "runner": null
 },
 "reach_days": 0,
 "settings": "could-not-check",
 "config_files": "could-not-check",
 "drop_in": {
  "equals_repo": true,
  "owner": "root",
  "group": "root",
  "mode": "0o644",
  "other_files": [
   "10-x.conf"
  ]
 },
 "service": {
  "started_at": "2026-10-10T17:43:38Z",
  "config_changed_after_start": "could-not-check"
 },
 "usage": {
  "bytes": 8392704,
  "files": 1,
  "bytes_percent_of_max_use": "could-not-check",
  "files_percent_of_max_files": "could-not-check",
  "free_bytes": 915426816000,
  "free_percent": 93.6,
  "other_directories": 0
 }
}
```

**Run 4, after `rm /etc/systemd/journald.conf.d/10-x.conf`.** Identical to run 2, byte for byte: the settings, the
three files and `other_files: []` are back. `config_changed_after_start` stays `true`, as it must: the main file was
touched in run 2, and the directory `/etc/systemd/journald.conf.d` changed when the file was added and removed (its
time is now `19:45:15`, after the start), which is what would show a drop-in the service read and that was deleted
since.

**How `jr` was left.** Our file installed and equal to the repository's, no other file in the directory, the service
active and never restarted (`ExecMainStartTimestamp` still `17:43:38.112198`). One thing differs from how it was
found and cannot be undone without a restart: the main file's and the directory's times are after the service's
start, so `d2_4` reports `config_changed_after_start: true` in `jr` until `systemctl restart systemd-journald` is
run there.

### R8 · the settings printout with `--tldr`

Measured 2026-10-10 in the running systemd 255 container `jr` (read-only), `systemd-analyze cat-config --tldr systemd/journald.conf | cat -A`:

```
# /etc/systemd/journald.conf$
[Journal]$
Storage=persistent$
SystemMaxUse=1G$
MaxRetentionSec=7day$
MaxFileSec=1day$
$
# /etc/systemd/journald.conf.d/50-hermes-retention.conf$
[Journal]$
MaxRetentionSec=35day$
SystemMaxFiles=500$
$
# /usr/lib/systemd/journald.conf.d/syslog.conf$
[Journal]$
ForwardToSyslog=yes$
```

The same command without `--tldr` additionally prints every comment line of the file contents (the three-line
Hermes header of our file, the upstream comment of `syslog.conf`) and an empty line inside a file's content. With
`--tldr` one empty line separates the files and the comment lines of the contents are gone. It is NOT a guarantee that a
line starting with `#` is a header the tool printed (R9: a file name holding newlines prints as several lines), and
it prints the section lines and assignments of the contents as they are, including lines systemd rejects (R9). Read
as a list of which files systemd lists, and in what order; not as proof of what systemd parses.

### R9 · what the `--tldr` printout does not show

Measured 2026-10-10 in a fresh systemd 255 container `jr2` (image `journald-rehearsal`; removed afterwards), our real
file installed as in R3.

N1, a broken line in an earlier drop-in. `/etc/systemd/journald.conf.d/10-x.conf` holding `[Broken`, `[Journal]`,
`Compress=yes`. `cat-config --tldr` printed it unchanged (`[Broken$`, `[Journal]$`, `Compress=yes$` under the
`# .../10-x.conf$` header, before our file). A file holding only `[Broken` printed `[Broken$`; a file holding
`[Journal]`, `X=1`, `[Broken`, `[Journal]`, `MaxRetentionSec=35day` printed all five lines. After
`systemctl restart systemd-journald` the journal said:

```
/etc/systemd/journald.conf.d/10-x.conf:1: Invalid section header '[Broken'
/etc/systemd/journald.conf.d/10-x.conf:1: Failed to parse file: Bad message
```

Which value applied: main file set to `MaxRetentionSec=3min`, our file (35day) present after the broken one; a mark
logged and the journal rotated every 60 s. Marks left: 1 at start, 1 after round 1, 1 after round 2, 0 after rounds 3 to 6.
The mark was deleted although our 35-day file was present: journald stopped reading at the broken file and kept the
main file's 3 minutes (the same control as R6: with our file read, the mark would have stayed). What this measured:
journald stops at the broken header and does not apply our value. The printout did NOT hide it: it printed
`[Broken` as it stands in the file, and the collector's printout reader refuses that line. No printout that withholds
a section line was observed.

N2, a header forged through a file name. Our file moved aside; a file named
`50-hermes-retention.conf\n[Journal]\nMaxRetentionSec=35day\nX=.conf` (newlines in the name) holding `[Journal]`,
`Compress=yes`. `cat-config --tldr` printed:

```
# /etc/systemd/journald.conf.d/50-hermes-retention.conf$
[Journal]$
MaxRetentionSec=35day$
X=.conf$
[Journal]$
Compress=yes$
```

The tool lists that file and prints the raw name, so it shows our header and `MaxRetentionSec=35day` while no
file with our name exists. Looking the listed path up on disk (it does not exist) catches it.

Why the collector reads the files as well as the printout. Two reasons, and N1 is not one of them: (i) N2, measured
above: a file whose name holds newlines is listed with lines that stand in no file, so the collector also lists the
four drop-in directories and refuses any `.conf` name outside `[A-Za-z0-9._@-]+\.conf`; (ii) the printout is produced
by `systemd-analyze`, a different program than `systemd-journald`, which is the one that applies the settings, so the
collector parses each listed file by the closed grammar itself (opened without following a link) and requires the
two readings to agree. Reason (ii) is a design choice, not a measurement.

### R10 · `Storage=`

Measured 2026-10-10 in a fresh systemd 255 container `jr3` (image `journald-rehearsal`, started as `jr` was, the
repository mounted read-only; removed afterwards; `jr` was not used). The image's main file sets
`Storage=persistent`; `90-s.conf` sorts after it and after our file. Commands and output as they ran (`sh -x`; the
machine id cut):

```
+ systemctl is-active systemd-journald
active
+ install -D -o root -g root -m 0644 /opt/projects/claude_code/infra/hermes-agent/deploy/journald-hermes-retention.conf /etc/systemd/journald.conf.d/50-hermes-retention.conf
+ systemctl restart systemd-journald
+ sleep 2
+ logger mark-persist
+ journalctl --flush
+ journalctl -q -o cat
+ grep -c mark-persist
1
+ ls /var/log/journal/<cut>/
system.journal
+ ls /run/log/journal/*/
+ sed s/[0-9a-f]\{32\}/<cut>/g
ls: cannot access '/run/log/journal/*/': No such file or directory
+ printf [Journal]\nStorage=volatile\n
+ systemd-analyze cat-config --tldr systemd/journald.conf
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day

# /etc/systemd/journald.conf.d/50-hermes-retention.conf
[Journal]
MaxRetentionSec=35day
SystemMaxFiles=500

# /etc/systemd/journald.conf.d/90-s.conf
[Journal]
Storage=volatile

# /usr/lib/systemd/journald.conf.d/syslog.conf
[Journal]
ForwardToSyslog=yes
+ systemctl restart systemd-journald
+ sleep 2
+ logger mark-vol
+ journalctl --flush
+ echo flush rc=0
+ sleep 1
flush rc=0
+ + sed s/[0-9a-f]\{32\}/<cut>/g
ls -la /var/log/journal/<cut>/
total 8208
drwxr-sr-x+ 2 root systemd-journal    4096 Oct 10 19:57 .
drwxr-sr-x+ 1 root systemd-journal    4096 Oct 10 19:57 ..
-rw-r-----+ 1 root systemd-journal 8388608 Oct 10 19:58 system.journal
+ ls -la /run/log/journal/<cut>/
+ sed s/[0-9a-f]\{32\}/<cut>/g
total 8192
drwxr-s--- 2 root systemd-journal      60 Oct 10 19:58 .
drwxr-sr-x 3 root systemd-journal      60 Oct 10 19:58 ..
-rw-r----- 1 root systemd-journal 8388608 Oct 10 19:58 system.journal
+ journalctl -q -o cat
+ grep -c mark-vol
1
+ cat /etc/machine-id
+ grep -c mark-vol
+ journalctl -D /var/log/journal/<cut> -q -o cat
0
+ + cat /etc/machine-id
grep -c mark-vol
+ journalctl -D /run/log/journal/<cut> -q -o cat
1
+ journalctl -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1
+ sed s/"__CURSOR":"[^"]*"/"__CURSOR":"<cut>"/; s/[0-9a-f]\{32\}/<cut>/g
{"__SEQNUM_ID":"<cut>","__SEQNUM":"1007","__CURSOR":"<cut>","__MONOTONIC_TIMESTAMP":"8180457716","__REALTIME_TIMESTAMP":"1791662274871373","_BOOT_ID":"<cut>"}
+ cat /etc/machine-id
+ cut -c1-25
+ journalctl -D /var/log/journal/<cut> -q --no-pager -o short-iso -n 1
2026-10-10T19:58:05+00:00
+ date -u
Sat Oct 10 19:58:09 UTC 2026
```

What it shows: with `Storage=volatile` in force, `mark-vol` is in `/run/log/journal` only (1) and not in
`/var/log/journal` (0), whose file stops at `19:58:05`, the moment before the restart; `journalctl` without `-D`
reads both places, so its oldest entry and its count look as before; `journalctl --flush` exits 0 and moves nothing.
The probe as committed in Task 7 (before this fix), run in that state:

```
{
 "oldest_entry": {
  "journal": "2026-10-10T19:57:54Z",
  "broker": null,
  "runner": null
 },
 "reach_days": 0,
 "settings": {
  "MaxRetentionSec": {
   "value": "35day",
   "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
   "number": 3024000
  },
  "SystemMaxUse": {
   "value": "1G",
   "file": "/etc/systemd/journald.conf",
   "number": 1073741824
  },
  "SystemMaxFiles": {
   "value": "500",
   "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
   "number": 500
  },
  "MaxFileSec": {
   "value": "1day",
   "file": "/etc/systemd/journald.conf",
   "number": 86400
  }
 },
 "config_files": [
  "/etc/systemd/journald.conf",
  "/etc/systemd/journald.conf.d/50-hermes-retention.conf",
  "/etc/systemd/journald.conf.d/90-s.conf",
  "/usr/lib/systemd/journald.conf.d/syslog.conf"
 ],
 "drop_in": {
  "equals_repo": true,
  "owner": "root",
  "group": "root",
  "mode": "0o644",
  "other_files": [
   "90-s.conf"
  ]
 },
 "service": {
  "started_at": "2026-10-10T19:58:06Z",
  "config_changed_after_start": false
 },
 "usage": {
  "bytes": 8392704,
  "files": 1,
  "bytes_percent_of_max_use": 0.8,
  "files_percent_of_max_files": 0.2,
  "free_bytes": 915417976832,
  "free_percent": 93.6,
  "other_directories": 0
 }
}
```

Every value is the healthy one except `other_files` (this rehearsal put the setting in a drop-in of its own; in the
server's own main file there would be no sign at all): `35day` from our file, `usage` from the stale file on disk.
After the fixes, the probe in the same state (re-run in the container `jr4` of R13, 12 s after the restart; the
probe's own lines, the two other settings left out). The commands that set the state for this re-run were not kept:
the implementer's report of that task gives its result only ("volatile → `Storage` `volatile`, age 12"):

```
"settings": {"MaxRetentionSec": {"value": "35day", "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "number": 3024000}, "Storage": {"value": "volatile", "file": "/etc/systemd/journald.conf.d/90-s.conf", "number": null}, ...}
"config_files": ["/etc/systemd/journald.conf", "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "/etc/systemd/journald.conf.d/90-s.conf", "/usr/lib/systemd/journald.conf.d/syslog.conf"]
"drop_in": {"equals_repo": true, "owner": "root", "group": "root", "mode": "0o644", "other_files": ["90-s.conf"]}
"service": {"active": true, "started_at": "2026-10-10T20:16:45Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417972736, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:16:45Z", "on_disk_age_seconds": 12}
```

The checklist's rule (2) fails `volatile`. `on_disk_age_seconds` is 12: the seconds since the restart, and growing.
Not measured: `Storage=none`, and `Storage=auto` or no `Storage=` with `/var/log/journal` missing.

### R11 · a stopped journal service

Measured 2026-10-10 in `jr3`, after `90-s.conf` was removed and the service restarted. Commands and output as they ran:

```
+ rm /etc/systemd/journald.conf.d/90-s.conf
+ systemctl restart systemd-journald
+ sleep 2
+ systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p SubState -p MainPID -p ExecMainExitTimestamp
MainPID=190
ExecMainStartTimestamp=Sat 2026-10-10 19:58:25.588933 UTC
ExecMainExitTimestamp=
ActiveState=active
SubState=running
+ systemctl stop systemd-journald.socket systemd-journald-dev-log.socket systemd-journald
+ echo stop rc=0
+ sleep 2
stop rc=0
+ systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p SubState -p MainPID -p ExecMainExitTimestamp
MainPID=0
ExecMainStartTimestamp=Sat 2026-10-10 19:58:25.588933 UTC
ExecMainExitTimestamp=Sat 2026-10-10 19:58:27.643146 UTC
ActiveState=inactive
SubState=dead
+ systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p MainPID --value
+ cat -A
0$
Sat 2026-10-10 19:58:25.588933 UTC$
inactive$
+ systemctl is-active systemd-journald systemd-journald.socket systemd-journald-dev-log.socket
inactive
inactive
inactive
+ date -u
Sat Oct 10 19:58:29 UTC 2026
```

The finding holds: a stopped service keeps `ExecMainStartTimestamp`, with `MainPID=0` and `ActiveState=inactive`.
Stopping it did not break the container. Also seen: with `--value` and several `-p`, systemd prints the values in
its own order (`MainPID`, the time, `ActiveState`), not the order asked for, so the probe reads `Name=value` lines by
name. The probe as committed in Task 7, run while the service was stopped, said (the other parts as in R7):

```
"service": {"started_at": "2026-10-10T19:58:25Z", "config_changed_after_start": false}
```

Then the service was started again; a unit that does not exist is shown for comparison:

```
+ systemctl start systemd-journald
+ sleep 2
+ systemctl show systemd-journald --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p SubState -p MainPID
MainPID=224
ExecMainStartTimestamp=Sat 2026-10-10 19:58:29.903740 UTC
ActiveState=active
SubState=running
+ systemctl is-active systemd-journald systemd-journald.socket systemd-journald-dev-log.socket
active
active
active
+ systemctl show no-such-unit-x --timestamp=us+utc -p ExecMainStartTimestamp -p ActiveState -p MainPID
MainPID=0
ExecMainStartTimestamp=
ActiveState=inactive
```

After the fixes, the probe with the service stopped (re-run in `jr4`, one second after the stop; the probe's own
lines). The commands that set the state for this re-run were not kept: the implementer's report gives its result
only ("stopped → `active: false`, age 1"):

```
"settings": {"MaxRetentionSec": {"value": "35day", "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "number": 3024000}, "Storage": {"value": "persistent", "file": "/etc/systemd/journald.conf", "number": null}, ...}
"config_files": ["/etc/systemd/journald.conf", "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "/usr/lib/systemd/journald.conf.d/syslog.conf"]
"drop_in": {"equals_repo": true, "owner": "root", "group": "root", "mode": "0o644", "other_files": []}
"service": {"active": false, "started_at": "could-not-check", "config_changed_after_start": "could-not-check"}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417976832, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:16:59Z", "on_disk_age_seconds": 1}
```

### R12 · a settings directory that is a symbolic link

Measured 2026-10-10 in `jr3`, with the fixed probe. `/etc/systemd/journald.conf.d` moved to `/etc/systemd/real.d` and
replaced by a link to it; a second file `99-short.conf` (`MaxRetentionSec=7day`) written there, the service
restarted, the file removed:

```
+ mv /etc/systemd/journald.conf.d /etc/systemd/real.d
+ ln -s real.d /etc/systemd/journald.conf.d
+ printf [Journal]\nMaxRetentionSec=7day\n
+ systemctl restart systemd-journald
+ sleep 2
+ rm /etc/systemd/real.d/99-short.conf
+ ls -la /etc/systemd/
+ grep -i journald
-rw-r--r-- 1 root root   82 Oct 10 17:43 journald.conf
lrwxrwxrwx 1 root root    6 Oct 10 20:01 journald.conf.d -> real.d
+ systemd-analyze cat-config --tldr systemd/journald.conf
+ grep -n ^#\|MaxRetention
1:# /etc/systemd/journald.conf
5:MaxRetentionSec=7day
8:# /etc/systemd/real.d/50-hermes-retention.conf
10:MaxRetentionSec=35day
13:# /usr/lib/systemd/journald.conf.d/syslog.conf
```

The fixed probe (re-run the same way in `jr4`; the probe's own lines). The commands that set the state for this
re-run were not kept: the implementer's report gives its result only ("linked directory → as in round 1, age 2"):

```
"settings": "could-not-check"
"config_files": "could-not-check"
"drop_in": {"equals_repo": true, "owner": "root", "group": "root", "mode": "0o644", "other_files": []}
"service": {"active": true, "started_at": "could-not-check", "config_changed_after_start": "could-not-check"}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": "could-not-check", "files_percent_of_max_files": "could-not-check", "free_bytes": 915417976832, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:17:03Z", "on_disk_age_seconds": 2}
```

`drop_in` still reads our path through the link. One thing differs from the
review's description of this case: systemd 255 printed the header with the link's TARGET
(`/etc/systemd/real.d/…`), which the printout reader does not accept as a settings file, so with this link the
Task 7 code would also have answered `could-not-check`. The review's result (`false`, `35day`) needs a printout
that names the link's own path; whether systemd prints that for another kind of link (an absolute target, a
target outside `/etc/systemd`) was not measured. The probe now refuses the link itself, whatever the printout
says. With the directory restored and the service restarted the healthy output was back
(`config_changed_after_start: false`). `jr3` was then removed.

### R13 · an on-disk journal that is not being written

Measured 2026-10-10 in a fresh systemd 255 container `jr4` (as `jr3`; our file installed, the service restarted;
removed afterwards; `jr` was not used). Commands and output as they ran (`sh -x`; machine id, boot id, cursor cut):

```
+ cat /etc/machine-id
+ M=<cut>
+ journalctl --flush
+ logger mark-before
+ sleep 1
+ ls /run/systemd/journal/flushed
/run/systemd/journal/flushed
+ journalctl -D /var/log/journal/<cut> -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n 1
{"__REALTIME_TIMESTAMP":"1791663254486776","__MONOTONIC_TIMESTAMP":"9160068110","__SEQNUM_ID":"<cut>","_BOOT_ID":"<cut>","__CURSOR":"<cut>","__SEQNUM":"2152"}
+ echo rc=0
+ journalctl -D /var/log/journal/<cut> -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1
rc=0
{"__CURSOR":"<cut>","__REALTIME_TIMESTAMP":"1791663242354127","__SEQNUM_ID":"<cut>","__MONOTONIC_TIMESTAMP":"9147935677","_BOOT_ID":"<cut>","__SEQNUM":"1040"}
+ echo rc=0
+ date -u +%s
rc=0
1791663254
+ journalctl --relinquish-var
+ echo relinquish rc=0
+ logger mark-relq
relinquish rc=0
+ sleep 1
+ journalctl -D /var/log/journal/<cut> -q -o cat
+ grep -c mark-relq
0
+ journalctl -D /run/log/journal/<cut> -q -o cat
+ grep -c mark-relq
1
+ journalctl -q -o cat
+ grep -c mark-relq
1
+ ls /run/systemd/journal/flushed
ls: cannot access '/run/systemd/journal/flushed': No such file or directory
+ systemctl show systemd-journald -p ActiveState -p MainPID
MainPID=113
ActiveState=active
+ ls -la /var/log/journal/<cut>/ /run/log/journal/<cut>/
/run/log/journal/<cut>/:
total 8192
drwxr-s--- 2 root systemd-journal      60 Oct 10 20:14 .
drwxr-sr-x 3 root systemd-journal      60 Oct 10 20:14 ..
-rw-r----- 1 root systemd-journal 8388608 Oct 10 20:14 system.journal

/var/log/journal/<cut>/:
total 8208
drwxr-sr-x+ 2 root systemd-journal    4096 Oct 10 20:14 .
drwxr-sr-x+ 1 root systemd-journal    4096 Oct 10 20:14 ..
-rw-r-----+ 1 root systemd-journal 8388608 Oct 10 20:14 system.journal
```

The probe as it was before this fix, run in that state, said (its own lines, from the saved output):

```
"service": {"active": true, "started_at": "2026-10-10T20:14:11Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417980928, "free_percent": 93.6, "other_directories": 0}
```

with `Storage` `persistent`, `35day` from our file and `oldest_entry.journal` `2026-10-10T20:14:02Z`: all healthy.
Then the restart:

```
+ cat /etc/machine-id
+ M=<cut>
+ journalctl -D /var/log/journal/<cut> -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n 1
{"__MONOTONIC_TIMESTAMP":"9160068110","__SEQNUM":"2152","__SEQNUM_ID":"<cut>","__REALTIME_TIMESTAMP":"1791663254486776","__CURSOR":"<cut>","_BOOT_ID":"<cut>"}
+ echo rc=0
+ date -u +%s
rc=0
1791663265
+ systemctl restart systemd-journald
+ sleep 3
+ logger mark-after-restart
+ sleep 1
+ journalctl -D /var/log/journal/<cut> -q -o cat
+ grep -c mark-after-restart
0
+ journalctl -D /run/log/journal/<cut> -q -o cat
+ grep -c mark-after-restart
1
+ ls /run/systemd/journal/flushed
ls: cannot access '/run/systemd/journal/flushed': No such file or directory
+ systemctl show systemd-journald -p ActiveState -p MainPID
MainPID=177
ActiveState=active
+ sleep 20
+ journalctl -D /var/log/journal/<cut> -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n 1
{"__CURSOR":"<cut>","__SEQNUM":"2152","__SEQNUM_ID":"<cut>","_BOOT_ID":"<cut>","__REALTIME_TIMESTAMP":"1791663254486776","__MONOTONIC_TIMESTAMP":"9160068110"}
+ echo rc=0
+ date -u +%s
rc=0
1791663289
+ journalctl -D /nonexistent-dir -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n 1
Failed to open /nonexistent-dir: No such file or directory
+ echo rc=1
+ mkdir /tmp/empty-j
rc=1
+ journalctl -D /tmp/empty-j -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n 1
+ echo rc=0
rc=0
```

and the old probe again: `"service": {"active": true, "started_at": "2026-10-10T20:14:25Z",
"config_changed_after_start": false}`, the same `usage`.

What it shows. The reading of the source holds: after `journalctl --relinquish-var` (rc 0) the flag
`/run/systemd/journal/flushed` is gone, the service stays `active`, and a new entry is in `/run/log/journal` (1) and
not in `/var/log/journal` (0); after `systemctl restart systemd-journald` the flag is still absent and the next entry
again goes to `/run` only (0 on disk, 1 in `/run`). `journalctl` without `-D` reads both. With `-D` on the on-disk
directory, `-n 1` prints one object with rc 0, as `-n +1` does, and its time stays where it was
(`1791663254486776` before the relinquish, 11 s after it, and 35 s after it); a directory without an entry prints
nothing with rc 0; a missing directory gives rc 1.

The probe with the fix, in the relinquished state, 150 s after the last entry reached the disk (its own lines):

```
"settings": {"MaxRetentionSec": {"value": "35day", "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "number": 3024000}, "Storage": {"value": "persistent", "file": "/etc/systemd/journald.conf", "number": null}, ...}
"config_files": ["/etc/systemd/journald.conf", "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "/usr/lib/systemd/journald.conf.d/syslog.conf"]
"drop_in": {"equals_repo": true, "owner": "root", "group": "root", "mode": "0o644", "other_files": []}
"service": {"active": true, "started_at": "2026-10-10T20:14:25Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417976832, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:14:14Z", "on_disk_age_seconds": 150}
```

Then `journalctl --flush`:

```
+ cat /etc/machine-id
+ M=<cut>
+ journalctl --flush
flush rc=0
+ echo flush rc=0
+ logger mark-flushed
+ sleep 1
+ ls /run/systemd/journal/flushed
/run/systemd/journal/flushed
+ journalctl -D /var/log/journal/<cut> -q -o cat
+ grep -c mark-flushed
1
+ journalctl -D /var/log/journal/<cut> -q -o cat
+ grep -c mark-relq
1
+ journalctl -D /var/log/journal/<cut> -q -o cat
+ grep -c mark-after-restart
1
```

The flag is back, the new entry is on disk, and so are the two entries written while relinquished (the flush
copies what `/run` held). The probe after it:

```
"settings": {"MaxRetentionSec": {"value": "35day", "file": "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "number": 3024000}, "Storage": {"value": "persistent", "file": "/etc/systemd/journald.conf", "number": null}, ...}
"config_files": ["/etc/systemd/journald.conf", "/etc/systemd/journald.conf.d/50-hermes-retention.conf", "/usr/lib/systemd/journald.conf.d/syslog.conf"]
"drop_in": {"equals_repo": true, "owner": "root", "group": "root", "mode": "0o644", "other_files": []}
"service": {"active": true, "started_at": "2026-10-10T20:14:25Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417976832, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:16:44Z", "on_disk_age_seconds": 1}
```

So `on_disk_age_seconds` was 1 in the healthy state and 150 in the relinquished state, where it grows by one a
second. The checklist's limit for the age is 600, so the age alone would not have shown this state for its first
ten minutes. The flag `/run/systemd/journal/flushed`, measured above (there, gone after `--relinquish-var`, still
gone after the restart, back after `--flush`), shows it at once, and the probe now reads it as
`usage.flushed_to_disk`. (The probe lines quoted earlier in R10 to R13 were taken before that key existed.)

The probe with that key, in a further fresh container `jr5` (our file installed, the service restarted,
`journalctl --flush`; removed afterwards), in three states; its own lines.

Flushed (`ls /run/systemd/journal/flushed`: there):

```
"service": {"active": true, "started_at": "2026-10-10T20:21:20Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417980928, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:21:23Z", "on_disk_age_seconds": 0, "flushed_to_disk": true}
```

After `journalctl --relinquish-var` (rc 0; `ls`: `No such file or directory`), two seconds later:

```
"service": {"active": true, "started_at": "2026-10-10T20:21:20Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417980928, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:21:23Z", "on_disk_age_seconds": 2, "flushed_to_disk": false}
```

After `journalctl --flush` again (rc 0; `ls`: there):

```
"service": {"active": true, "started_at": "2026-10-10T20:21:20Z", "config_changed_after_start": false}
"usage": {"bytes": 8392704, "files": 1, "bytes_percent_of_max_use": 0.8, "files_percent_of_max_files": 0.2, "free_bytes": 915417980928, "free_percent": 93.6, "other_directories": 0, "newest_entry_on_disk": "2026-10-10T20:21:25Z", "on_disk_age_seconds": 1, "flushed_to_disk": true}
```

## 3b · The key reader's two cases

Measured 2026-10-10 on the laptop (macOS, shell zsh; Docker 29, linux/aarch64 container, `ubuntu:24.04`), against a
throwaway `sshd` on 127.0.0.1 port 2222, with five throwaway ed25519 keys (no key body is kept here): four in the
server's `authorized_keys` (`a` to `d`) and a fifth, `x`, that is NOT in the file. Server version line:
`OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`. The box's release was read on the box on 2026-10-11 (section 2, "The sshd and
journal look"): `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`, the same release and package revision. (An earlier wording here
said "as the plan states, confirmed on the box on 2026-10-08"; no record of a reading on that day was found.) The
runbook's VPS 1 block reads it again at the rollout.

How each line was tested: one real `ssh` public-key login per key to 127.0.0.1 port 2222 as user `u`, offering that
key only (`IdentitiesOnly=yes`, `IdentityAgent=none`, `BatchMode=yes`), running `true`. Exit status 0 is "accepted",
anything else "refused".

The file had four lines: `a` a key first, its comment holding one double quote; `b` an option (`no-pty`) first, the
same comment; `c` a key with no comment and a carriage return before the line break; `d` a plain line with a
comment (control, must be accepted). `x` is the control that must be refused.

Result lines, exactly as printed:

```
a: accepted
b: accepted
c: accepted
d: accepted
x: refused
```

Both controls held (`d` accepted, `x` refused), so the measurement is valid.

- The server really received line `c` ending in carriage return plus line feed: the last three bytes of that line, read
  inside the container with `od -c`, are `n \r \n`; the file has 4 lines, with 3, 4, 2 and 3 whitespace-separated
  fields (so `c` has only the type and the key).
- One change to the measuring loop, none to the server or the file. The first run printed `refused` for all five
  lines, control `d` included, which is how the fault was seen. The ssh options had been held in one shell variable,
  which zsh passes as a single word, so every login failed before reaching the key. The server's debug log, read after
  that faulty run, showed the key of `d` accepted (as the implementer observed; no excerpt kept). The options were then written out literally, as in the plan, and
  the result above is from that run. The four lines in the file were never changed.
- The account's state, said outright. The account `u` was made by `useradd`, so its password field was `!` (locked).
  While the fault was looked for, `usermod -p '*'` was run and `sshd` restarted, both BEFORE the final run: the five
  results above were taken with the password field `*`, not in the locked state. The lock checks came AFTER that final
  run: with the account locked again (`!`), `d` was accepted; with `*` again, all five lines gave the results above
  (which of the two was tried first is not recorded). This is what the implementer's report of that task records ("tested the account locked
  ('!') vs '*': d accepted both ways"; "the locked vs `*` check was made after the final run, with an earlier
  usermod/sshd restart before it"); it keeps no command and no output of the lock checks, and for the locked state it
  names `d` only.
- What it means for the reader: `sshd` 9.6p1 accepts the quote-in-comment line, the option-first line with that
  comment, and the carriage-return line, so the D1.7 reader counts as unreadable lines (a, b and c) that the server
  accepts. The next task decides what to do with it.

### A configuration keyword in double quotes, a leading `=`, a carriage return

Measured 2026-10-10 in a throwaway `ubuntu:24.04` container with `openssh-server` (`OpenSSH_9.6p1`); accounts `u`
and `other` made by the script. Command as run (the script is under the scratchpad of this session, written `<scratchpad>`
in every command of this record; its text follows):

```
docker run --rm -v <scratchpad>/measure2.sh:/measure.sh:ro ubuntu:24.04 sh /measure.sh
```

```sh
#!/bin/sh
# runs inside ubuntu:24.04; u and other are made here
apt-get update -qq && apt-get install -y -qq openssh-server >/dev/null 2>&1
mkdir -p /run/sshd /tmp/sub; useradd u; useradd other
ssh -V 2>&1 | cut -d, -f1
x() { /usr/sbin/sshd -T -f /tmp/f.conf -C "user=$1,host=h,addr=127.0.0.1" 2>&1 | grep -i '^x11forwarding ' | cut -d' ' -f2; }
m() { # label, printf format of the line(s) before "  X11Forwarding yes"
  printf "$2  X11Forwarding yes\n" > /tmp/f.conf
  rc=$(/usr/sbin/sshd -t -f /tmp/f.conf >/dev/null 2>&1; echo $?)
  printf "MATCH   [%s] rc=%s as_u=%s as_other=%s\n" "$1" "$rc" "$(x u)" "$(x other)"
}
printf 'X11Forwarding yes\n' > /tmp/inc.conf
i() {
  printf "$2\n" > /tmp/f.conf
  rc=$(/usr/sbin/sshd -t -f /tmp/f.conf >/dev/null 2>&1; echo $?)
  v=$(/usr/sbin/sshd -T -f /tmp/f.conf 2>&1 | grep -i '^x11forwarding ' | cut -d' ' -f2)
  printf "INCLUDE [%s] rc=%s global=%s\n" "$1" "$rc" "${v:-<none>}"
}
m 'control Match User u' 'Match User u\n'
printf 'Port 22\n' > /tmp/f.conf; rc=$(/usr/sbin/sshd -t -f /tmp/f.conf >/dev/null 2>&1; echo $?)
printf "MATCH   [control no Match line (Port 22)] rc=%s as_u=%s as_other=%s\n" "$rc" "$(x u)" "$(x other)"
m '"Match" User u' '"Match" User u\n'
m 'Ma"tch" User u' 'Ma"tch" User u\n'
m 'Match"" User u' 'Match"" User u\n'
m '""Match User u' '""Match User u\n'
m '"" "Match" User u' '"" "Match" User u\n'
m '"Match"User u' '"Match"User u\n'
m '"Match User" u' '"Match User" u\n'
m 'Match\rUser u' 'Match\rUser u\n'
m '\rMatch User u' '\rMatch User u\n'
m 'Match=User u' 'Match=User u\n'
m '"Match"=User u' '"Match"=User u\n'
m 'Match\tUser u' 'Match\tUser u\n'
m '=Match User u' '=Match User u\n'
m '= Match User u' '= Match User u\n'
m '="Match" User u' '="Match" User u\n'
m '==Match User u' '==Match User u\n'
m '""=Match User u' '""=Match User u\n'
m '"" ""Match User u' '"" ""Match User u\n'
m 'Matchmaker yes' 'Matchmaker yes\n'
m 'NUL: Ma<NUL>\ntch User u' 'Ma\000\ntch User u\n'
i 'control Include /tmp/inc.conf' 'Include /tmp/inc.conf'
i '"Include" /tmp/inc.conf' '"Include" /tmp/inc.conf'
i 'In"clude" /tmp/inc.conf' 'In"clude" /tmp/inc.conf'
i 'Include\r/tmp/inc.conf' 'Include\r/tmp/inc.conf'
i 'Include "/tmp/inc.conf"' 'Include "/tmp/inc.conf"'
i 'Include=/tmp/inc.conf' 'Include=/tmp/inc.conf'
i '=Include /tmp/inc.conf' '=Include /tmp/inc.conf'
i '""Include /tmp/inc.conf' '""Include /tmp/inc.conf'
i '"Include"/tmp/inc.conf' '"Include"/tmp/inc.conf'
i 'Include\t/tmp/inc.conf' 'Include\t/tmp/inc.conf'
i 'Include /tmp/inc.conf # c' 'Include /tmp/inc.conf # c'
i 'Include /tmp/sub/../inc.conf' 'Include /tmp/sub/../inc.conf'
i 'Include "/tmp/inc.conf (unterminated)' 'Include "/tmp/inc.conf'
```

Each Match form is one line followed by `  X11Forwarding yes`, read as `u` and as `other`
(`sshd -T -f FILE -C user=...,host=h,addr=127.0.0.1`): `yes` / `no` means the line opened a Match block for `u`;
`yes` / `yes` means the line was ignored (no block). Each Include form is one line, with `/tmp/inc.conf` holding
`X11Forwarding yes`, read with `sshd -T -f FILE` (global). Output, unedited (`\r`, `\t` in the labels are the
escapes written in the script):

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
MATCH   [control Match User u] rc=0 as_u=yes as_other=no
MATCH   [control no Match line (Port 22)] rc=0 as_u=no as_other=no
MATCH   ["Match" User u] rc=0 as_u=yes as_other=no
MATCH   [Ma"tch" User u] rc=0 as_u=yes as_other=no
MATCH   [Match"" User u] rc=0 as_u=yes as_other=no
MATCH   [""Match User u] rc=0 as_u=yes as_other=no
MATCH   ["" "Match" User u] rc=0 as_u=yes as_other=no
MATCH   ["Match"User u] rc=0 as_u=yes as_other=no
MATCH   ["Match User" u] rc=255 as_u= as_other=
MATCH   [Match\rUser u] rc=0 as_u=yes as_other=no
MATCH   [\rMatch User u] rc=0 as_u=yes as_other=no
MATCH   [Match=User u] rc=0 as_u=yes as_other=no
MATCH   ["Match"=User u] rc=255 as_u= as_other=
MATCH   [Match\tUser u] rc=0 as_u=yes as_other=no
MATCH   [=Match User u] rc=0 as_u=yes as_other=no
MATCH   [= Match User u] rc=0 as_u=yes as_other=no
MATCH   [="Match" User u] rc=0 as_u=yes as_other=no
MATCH   [==Match User u] rc=0 as_u=yes as_other=yes
MATCH   [""=Match User u] rc=0 as_u=yes as_other=yes
MATCH   ["" ""Match User u] rc=0 as_u=yes as_other=yes
MATCH   [Matchmaker yes] rc=255 as_u= as_other=
MATCH   [NUL: Ma<NUL>\ntch User u] rc=0 as_u=yes as_other=no
INCLUDE [control Include /tmp/inc.conf] rc=0 global=yes
INCLUDE ["Include" /tmp/inc.conf] rc=0 global=yes
INCLUDE [In"clude" /tmp/inc.conf] rc=0 global=yes
INCLUDE [Include\r/tmp/inc.conf] rc=0 global=yes
INCLUDE [Include "/tmp/inc.conf"] rc=0 global=yes
INCLUDE [Include=/tmp/inc.conf] rc=0 global=yes
INCLUDE [=Include /tmp/inc.conf] rc=0 global=yes
INCLUDE [""Include /tmp/inc.conf] rc=0 global=yes
INCLUDE ["Include"/tmp/inc.conf] rc=0 global=yes
INCLUDE [Include\t/tmp/inc.conf] rc=0 global=yes
INCLUDE [Include /tmp/inc.conf # c] rc=0 global=yes
INCLUDE [Include /tmp/sub/../inc.conf] rc=0 global=yes
INCLUDE [Include "/tmp/inc.conf (unterminated)] rc=255 global=<none>
```

Match forms ("counted" is the collector's rule, checked by its tests, not by this run):

| form | `sshd -t` rc | as `u` | as `other` | counted by the collector |
|---|---|---|---|---|
| `control Match User u` | 0 | yes | no | n/a (control) |
| `control no Match line (Port 22)` | 0 | no | no | no (control, no Match line) |
| `"Match" User u` | 0 | yes | no | yes |
| `Ma"tch" User u` | 0 | yes | no | yes |
| `Match"" User u` | 0 | yes | no | yes |
| `""Match User u` | 0 | yes | no | yes |
| `"" "Match" User u` | 0 | yes | no | yes |
| `"Match"User u` | 0 | yes | no | yes |
| `"Match User" u` | 255 | (none printed) | (none printed) | yes |
| `Match\rUser u` | 0 | yes | no | yes |
| `\rMatch User u` | 0 | yes | no | yes |
| `Match=User u` | 0 | yes | no | yes |
| `"Match"=User u` | 255 | (none printed) | (none printed) | yes |
| `Match\tUser u` | 0 | yes | no | yes |
| `=Match User u` | 0 | yes | no | yes |
| `= Match User u` | 0 | yes | no | yes |
| `="Match" User u` | 0 | yes | no | yes |
| `==Match User u` | 0 | yes | yes | yes |
| `""=Match User u` | 0 | yes | yes | yes |
| `"" ""Match User u` | 0 | yes | yes | yes |
| `Matchmaker yes` | 255 | (none printed) | (none printed) | yes |
| `NUL: Ma<NUL>\ntch User u` | 0 | yes | no | yes (file has a NUL: could-not-check) |

Include forms:

| form | `sshd -t` rc | global `x11forwarding` | counted by the collector |
|---|---|---|---|
| `control Include /tmp/inc.conf` | 0 | yes | n/a (control) |
| `"Include" /tmp/inc.conf` | 0 | yes | yes (outside path) |
| `In"clude" /tmp/inc.conf` | 0 | yes | yes (outside path) |
| `Include\r/tmp/inc.conf` | 0 | yes | yes (outside path) |
| `Include "/tmp/inc.conf"` | 0 | yes | yes (outside path) |
| `Include=/tmp/inc.conf` | 0 | yes | yes (outside path) |
| `=Include /tmp/inc.conf` | 0 | yes | yes (outside path) |
| `""Include /tmp/inc.conf` | 0 | yes | yes (outside path) |
| `"Include"/tmp/inc.conf` | 0 | yes | yes (outside path) |
| `Include\t/tmp/inc.conf` | 0 | yes | yes (outside path) |
| `Include /tmp/inc.conf # c` | 0 | yes | yes (outside path) |
| `Include /tmp/sub/../inc.conf` | 0 | yes | yes (outside path) |
| `Include "/tmp/inc.conf (unterminated)` | 255 | <none> | yes (outside path) |

What it shows, only from the output: the two controls gave yes / no and no / no. Opened a block for `u` only (yes / no):
all the forms of the first round and `=Match`, `= Match`, `="Match"`. Ignored without error (yes / yes, rc 0):
`==Match User u`, `""=Match User u`, `"" ""Match User u`. Refused (rc 255): `"Match User" u`, `"Match"=User u`,
`Matchmaker yes`, and `Include "/tmp/inc.conf` with an unterminated quote. A file holding a NUL byte between `Ma`
and a newline, then `tch User u`, opened a block for `u`. Every `Include` form run except the unterminated quote (rc 255), among them a trailing
` # c` and `/tmp/sub/../inc.conf`, brought the file in. Not run: other characters between or after the letters of
the keyword, a `Match` or `Include` in a drop-in file, and any other sshd version. The collector counts a line as a
Match or Include line from the first letters it finds once it has skipped every blank or control character, double
quote and `=`, which includes all the honoured forms above and over-counts the ignored and refused ones.

#### The standard glob with something around it

Same set-up (`ubuntu:24.04`, `OpenSSH_9.6p1`), 2026-10-10, with `/etc/ssh/sshd_config.d/a.conf` holding `Port 22` so the
glob matches a file. `GLOB` is `/etc/ssh/sshd_config.d/*.conf`. Command as run:

```
docker run --rm -v <scratchpad>/measure3.sh:/measure.sh:ro ubuntu:24.04 sh /measure.sh
```

```sh
#!/bin/sh
apt-get update -qq && apt-get install -y -qq openssh-server >/dev/null 2>&1
mkdir -p /run/sshd /etc/ssh/sshd_config.d
printf 'Port 22\n' > /etc/ssh/sshd_config.d/a.conf
ssh -V 2>&1 | cut -d, -f1
G=/etc/ssh/sshd_config.d/*.conf
i() { # label, printf format of the whole line
  printf "$2\n" > /tmp/f.conf
  rc=$(/usr/sbin/sshd -t -f /tmp/f.conf >/dev/null 2>&1; echo $?)
  printf 'INCLUDE [%s] rc=%s\n' "$1" "$rc"
  /usr/sbin/sshd -T -ddd -f /tmp/f.conf 2>&1 | grep -a 'new include' | cat -v | sed 's/^/    /'
}
i 'control: Include GLOB' "Include $G"
i 'control: Include "GLOB"' "Include \"$G\""
i 'Include = = GLOB' "Include = = $G"
i 'Include "=" GLOB' "Include \"=\" $G"
i 'Include " " GLOB' "Include \" \" $G"
i 'Include ==GLOB' "Include ==$G"
i 'Include \x01GLOB' "Include \001$G"
i 'Include GLOB\x01' "Include $G\001"
i 'Include GLOB\x0b' "Include $G\013"
i 'Include GLOB\x7f' "Include $G\177"
i 'Include GLOB\x0c' "Include $G\014"
```

Output, unedited except that `cat -v` shows non-printing bytes escaped (`^M` is the carriage return that
`sshd -ddd` itself prints at the end of each debug line; `\001`, `\013`, `\177` are bytes of the path):

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
INCLUDE [control: Include GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [control: Include "GLOB"] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include = = GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/=^M
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include "=" GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/=^M
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include " " GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/ ^M
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include ==GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/=/etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include \x01GLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/\001/etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include GLOB\x01] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf\001^M
INCLUDE [Include GLOB\x0b] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf\013^M
INCLUDE [Include GLOB\x7f] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf\177^M
INCLUDE [Include GLOB\x0c] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
```

What it shows: with `= =`, a quoted `=`, a quoted blank, `==`, or a control byte before or after the glob, `sshd`
9.6p1 includes another path or a pattern with the byte in it as well as, or instead of, the glob; a form feed after
it was dropped. That is why the collector recognises the standard glob only in a closed set of spellings (bare or in
one pair of quotes, after the bare keyword, absolute or `sshd_config.d/*.conf`) and counts every other spelling as
reaching elsewhere.

The accepted spellings, measured one by one (same set-up, 2026-10-10, `ubuntu:24.04`, `OpenSSH_9.6p1`; `GLOB` as above;
`\r` is a carriage return, `\t` a tab). Each is a whole-line spelling the collector does NOT count as reaching elsewhere;
the question was whether `sshd` reads exactly the standard glob and nothing else. Command as run:

```
docker run --rm --name t5b4 -v <scratchpad>/measure7.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
apt-get update -qq && apt-get install -y -qq openssh-server >/dev/null 2>&1
mkdir -p /run/sshd /etc/ssh/sshd_config.d
printf 'Port 22\n' > /etc/ssh/sshd_config.d/a.conf
ssh -V 2>&1 | cut -d, -f1
G=/etc/ssh/sshd_config.d/*.conf
i() { # label, printf format of the whole line
  printf "$2\n" > /tmp/f.conf
  rc=$(/usr/sbin/sshd -t -f /tmp/f.conf >/dev/null 2>&1; echo $?)
  printf 'INCLUDE [%s] rc=%s\n' "$1" "$rc"
  /usr/sbin/sshd -T -ddd -f /tmp/f.conf 2>&1 | grep -a 'new include' | cat -v | sed 's/^/    /'
}
i 'Include GLOB\r' "Include $G\r"
i 'Include GLOB \r' "Include $G \r"
i '\tinclude\tGLOB' "\tinclude\t$G"
i ' iNcLuDe  "GLOB" \r' " iNcLuDe  \"$G\" \r"
i 'Include sshd_config.d/*.conf' "Include sshd_config.d/*.conf"
i 'Include "sshd_config.d/*.conf"' "Include \"sshd_config.d/*.conf\""
```

Output, unedited (`^M` is the carriage return `sshd -ddd` itself prints at the end of each debug line):

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
INCLUDE [Include GLOB\r] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include GLOB \r] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [\tinclude\tGLOB] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [ iNcLuDe  "GLOB" \r] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include sshd_config.d/*.conf] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
INCLUDE [Include "sshd_config.d/*.conf"] rc=0
    debug2: /tmp/f.conf line 1: new include /etc/ssh/sshd_config.d/*.conf^M
```

What it shows: each of the six accepted spellings gave one `new include /etc/ssh/sshd_config.d/*.conf` and no other path
(the relative ones are read against `/etc/ssh/`), `sshd -t` rc 0. Not run: any other spelling of the keyword's letters
or any other sshd version.

### How the running sshd was started

Measured 2026-10-10 in a throwaway `ubuntu:24.04` container with `openssh-server` and `procps` (`OpenSSH_9.6p1`),
account `u` and a throwaway ed25519 key made by the script; the container was removed afterwards (`--rm`). Command as run
(the script is under the scratchpad of this session, written `<scratchpad>` below; its text follows):

```
docker run --rm --name t5b -v <scratchpad>/measure4.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
# runs inside ubuntu:24.04
apt-get update -qq && apt-get install -y -qq openssh-server procps >/dev/null 2>&1
mkdir -p /run/sshd
ssh -V 2>&1 | cut -d, -f1
useradd -m -s /bin/bash u; passwd -u u >/dev/null 2>&1; usermod -p '*' u
ssh-keygen -q -t ed25519 -N '' -f /root/k
mkdir -p /home/u/.ssh; cp /root/k.pub /home/u/.ssh/authorized_keys; chown -R u:u /home/u/.ssh; chmod 700 /home/u/.ssh; chmod 600 /home/u/.ssh/authorized_keys
cp /etc/ssh/sshd_config /tmp/alt.conf
SSH() { ssh -p 22 -i /root/k -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR u@127.0.0.1 "$@"; }
show() { # label
  echo "--- $1"
  echo "ps -C sshd -o args=:"
  ps -C sshd -o args= | cat -v | sed 's/^/    /'
  echo "/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:"
  for p in $(pgrep -x sshd); do printf '    <cut> %s\n' "$(tr '\0' '|' < /proc/$p/cmdline | cat -v)"; done
  echo "(count of pgrep -x sshd: $(pgrep -x sshd | wc -l))"
}
stop() { pkill -x sshd; sleep 1; }
echo "=== state 5 (before any start): no sshd"
show "no sshd"; echo "ps rc: $(ps -C sshd -o args= >/dev/null; echo $?)"
echo "=== state 1: /usr/sbin/sshd"
/usr/sbin/sshd; sleep 1; show "plain"; stop
echo "=== state 2: /usr/sbin/sshd -D &"
/usr/sbin/sshd -D & sleep 1; show "-D"; stop
echo "=== state 3a: -f /tmp/alt.conf -o X11Forwarding=yes"
/usr/sbin/sshd -f /tmp/alt.conf -o X11Forwarding=yes; sleep 1; show "-f -o split"; stop
echo "=== state 3b: -f/tmp/alt.conf -oX11Forwarding=yes"
/usr/sbin/sshd -f/tmp/alt.conf -oX11Forwarding=yes; sleep 1; show "-f -o joined"; stop
echo "=== state 3c: -D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22 &"
/usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22 & sleep 1; show "-D with options"; stop
echo "=== state 4: -D & with one login session (sleep 20) and one half-open connection"
/usr/sbin/sshd -D & sleep 1
SSH sleep 20 & sleep 3
exec 3<>/dev/tcp/127.0.0.1/22; sleep 1
show "listener + session children + pre-auth connection"
exec 3>&-; wait %2 2>/dev/null; stop
echo "=== state 4b: same, listener started with -f and -o"
/usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes & sleep 1
SSH sleep 20 & sleep 3
show "listener with options + session children"
stop
echo "=== state 4c: account named -f / -o (hand-made passwd line), session open"
printf -- '-f:x:1500:1500::/home/u:/bin/bash\n-o:x:1501:1501::/home/u:/bin/bash\n' >> /etc/passwd
printf -- '-f:x:1500:\n-o:x:1501:\n' >> /etc/group
/usr/sbin/sshd -D & sleep 1
for n in -f -o; do ssh -p 22 -i /root/k -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -- "$n@127.0.0.1" true; echo "login as $n rc=$?"; done
ssh -p 22 -i /root/k -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -l -f 127.0.0.1 sleep 20 &
sleep 3; show "session of an account named -f"
stop
```

Output, unedited except that no process id appears in it (the script prints `<cut>` for it); in the `/proc` lines a NUL
byte is shown as `|`. The last block (an account named `-f`) did not reach the daemon: the `ssh` client refused the
user name before connecting (`remote username contains invalid characters`), so the listener there is the only process:

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
=== state 5 (before any start): no sshd
--- no sshd
ps -C sshd -o args=:
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
(count of pgrep -x sshd: 0)
ps rc: 1
=== state 1: /usr/sbin/sshd
--- plain
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
=== state 2: /usr/sbin/sshd -D &
--- -D
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
=== state 3a: -f /tmp/alt.conf -o X11Forwarding=yes
--- -f -o split
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -f /tmp/alt.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -f /tmp/alt.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
=== state 3b: -f/tmp/alt.conf -oX11Forwarding=yes
--- -f -o joined
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -f/tmp/alt.conf -oX11Forwarding=yes [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -f/tmp/alt.conf -oX11Forwarding=yes [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
=== state 3c: -D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22 &
--- -D with options
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22 [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes -o Port=22 [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
=== state 4: -D & with one login session (sleep 20) and one half-open connection
--- listener + session children + pre-auth connection
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D [listener] 1 of 10-100 startups
    sshd: u [priv]
    sshd: u@notty
    sshd: [accepted]
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -D [listener] 1 of 10-100 startups|
    <cut> sshd: u [priv]|||||||
    <cut> sshd: u@notty||||||||
    <cut> sshd: [accepted]|||||
(count of pgrep -x sshd: 4)
Connection to 127.0.0.1 closed by remote host.
=== state 4b: same, listener started with -f and -o
--- listener with options + session children
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups
    sshd: u [priv]
    sshd: u@notty
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups|
    <cut> sshd: u [priv]|||||||||||||||||||||||||||||||||||||||||||||
    <cut> sshd: u@notty||||||||||||||||||||||||||||||||||||||||||||||
(count of pgrep -x sshd: 3)
Connection to 127.0.0.1 closed by remote host.
=== state 4c: account named -f / -o (hand-made passwd line), session open
remote username contains invalid characters
login as -f rc=255
remote username contains invalid characters
login as -o rc=255
remote username contains invalid characters
--- session of an account named -f
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
/proc/PID/cmdline of each pgrep -x sshd (NUL shown as |), PID cut:
    <cut> sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups|
(count of pgrep -x sshd: 1)
```

A second script, for what `ps` returns when nothing matches and when it fails:

```
docker run --rm --name t5b2 -v <scratchpad>/measure5.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
apt-get update -qq && apt-get install -y -qq procps >/dev/null 2>&1
ps -C sshd -o args= >/tmp/o 2>/tmp/e; echo "no sshd: rc=$? stdout_bytes=$(wc -c </tmp/o) stderr_bytes=$(wc -c </tmp/e)"
ps -C sshd -o nosuchcol= >/tmp/o 2>/tmp/e; echo "bad column: rc=$? stdout_bytes=$(wc -c </tmp/o) stderr_first_line=$(head -1 /tmp/e)"
```

```
no sshd: rc=1 stdout_bytes=0 stderr_bytes=0
bad column: rc=1 stdout_bytes=0 stderr_first_line=error: unknown user-defined format specifier "nosuchcol"
```

What it shows, only from the output: the listener's title is `sshd: ` then the original command line (program path and
every option, in the split and the joined form) then `[listener] N of M-K startups`; `ps -C sshd -o args=` and
`/proc/PID/cmdline` give the same text (the `/proc` one padded with NULs for the children), so `ps` is enough. Every
child (`sshd: u [priv]`, `sshd: u@notty`, `sshd: [accepted]`) lacks the `[listener]` mark and shows the user name, never
the options; the listener count read from the mark was 1 in every state with a daemon and 0 with none (`ps` rc 1, no output,
no error text), and `ps` failing on a bad column also gave rc 1 but with an error text.

Values with a blank, and option clusters (a review note asked whether the original argument vector survives). Same
container recipe, script `measure6.sh`:

```
docker run --rm --name t5b3 -v <scratchpad>/measure6.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
# runs inside ubuntu:24.04
apt-get update -qq && apt-get install -y -qq openssh-server procps >/dev/null 2>&1
mkdir -p /run/sshd
ssh -V 2>&1 | cut -d, -f1
cp /etc/ssh/sshd_config "/tmp/a b.conf"; cp /etc/ssh/sshd_config /tmp/alt.conf
run() { # label, then the sshd arguments (sshd -D stays in the foreground, so each is started with &)
  l="$1"; shift
  /usr/sbin/sshd "$@" >/dev/null 2>&1 &
  sleep 1
  echo "--- $l"
  echo "ps -C sshd -o args=:"
  ps -C sshd -o args= | cat -v | sed 's/^/    /'
  for p in $(pgrep -x sshd); do printf '    /proc <cut> %s\n' "$(tr '\0' '|' < /proc/$p/cmdline | cat -v)"; done
  echo "    processes named sshd: $(pgrep -x sshd | wc -l)"
  pkill -x sshd; sleep 1
}
run '-D -o "AllowUsers u v" -o X11Forwarding=yes' -D -o "AllowUsers u v" -o X11Forwarding=yes
run '-D -f "/tmp/a b.conf" -o X11Forwarding=yes' -D -f "/tmp/a b.conf" -o X11Forwarding=yes
run '-D -e -f /tmp/alt.conf' -D -e -f /tmp/alt.conf
run '-De -f /tmp/alt.conf' -De -f /tmp/alt.conf
run '-Def/tmp/alt.conf' -Def/tmp/alt.conf
run '-Def /tmp/alt.conf' -Def /tmp/alt.conf
run '-Deo X11Forwarding=yes' -Deo X11Forwarding=yes
run '-D -f /tmp/alt.conf -f /tmp/alt.conf' -D -f /tmp/alt.conf -f /tmp/alt.conf
```

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
--- -D -o "AllowUsers u v" -o X11Forwarding=yes
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -o AllowUsers u v -o X11Forwarding=yes [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -D -o AllowUsers u v -o X11Forwarding=yes [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -D -f "/tmp/a b.conf" -o X11Forwarding=yes
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -f /tmp/a b.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -D -f /tmp/a b.conf -o X11Forwarding=yes [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -D -e -f /tmp/alt.conf
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -e -f /tmp/alt.conf [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -D -e -f /tmp/alt.conf [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -De -f /tmp/alt.conf
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -De -f /tmp/alt.conf [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -De -f /tmp/alt.conf [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -Def/tmp/alt.conf
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -Def/tmp/alt.conf [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -Def/tmp/alt.conf [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -Def /tmp/alt.conf
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -Def /tmp/alt.conf [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -Def /tmp/alt.conf [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -Deo X11Forwarding=yes
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -Deo X11Forwarding=yes [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -Deo X11Forwarding=yes [listener] 0 of 10-100 startups|
    processes named sshd: 1
--- -D -f /tmp/alt.conf -f /tmp/alt.conf
ps -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -f /tmp/alt.conf [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -f /tmp/alt.conf [listener] 0 of 10-100 startups|
    processes named sshd: 1
```

What it shows: `/proc/PID/cmdline` of the listener is the rewritten title as ONE string (a single NUL at its end), not the
original NUL-separated vector, so a value with a blank (`-o "AllowUsers u v"`, `-f "/tmp/a b.conf"`) cannot be told from
extra words in either source; the clusters `-De -f`, `-Def/path`, `-Def path` and `-Deo X=Y` appear as typed. The collector
therefore reads every word starting with `-` as an option cluster and skips (never stops at) a word that does not.
(`-o "Banner /tmp/a b"` is refused by sshd itself, so `AllowUsers` stands in for a blank-holding value. Re-run, script
`measure10.sh`: `/usr/sbin/sshd -t -o "Banner /tmp/a b"`, output below.)

```
docker run --rm --name t5b7 -v <scratchpad>/measure10.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
apt-get update -qq && apt-get install -y -qq openssh-server >/dev/null 2>&1
mkdir -p /run/sshd
/usr/sbin/sshd -t -o "Banner /tmp/a b"; echo "rc=$?"
```

```
command-line line 0: keyword Banner extra arguments at end of line
rc=1
```

#### Fix round 1: a title that is cut, a process never retitled, the full list of child titles

A review found that dropping any line that is not a listener would let a second daemon with options read as healthy.
Three more scripts, same container recipe (`ubuntu:24.04`, `openssh-server`, `procps`, `OpenSSH_9.6p1`), 2026-10-10.
`measure8.sh` covers (a) `COLUMNS=60` with and without `-ww` against a long `-f` path, (b) a daemon started under
`env -i` beside a plain one, and (c) a sampler running `ps -ww -C sshd -o args=` every 20 ms across successful logins
(plain and `ssh -tt`), a refused user, a refused password and a bare TCP connection; the unique lines it saw are counted.
(The "Permission denied" lines are the refused logins.)

```
docker run --rm --name t5b5 -v <scratchpad>/measure8.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
# runs inside ubuntu:24.04
apt-get update -qq && apt-get install -y -qq openssh-server procps >/dev/null 2>&1
mkdir -p /run/sshd
ssh -V 2>&1 | cut -d, -f1
useradd -m -s /bin/bash u; usermod -p '*' u
ssh-keygen -q -t ed25519 -N '' -f /root/k
mkdir -p /home/u/.ssh; cp /root/k.pub /home/u/.ssh/authorized_keys; chown -R u:u /home/u/.ssh; chmod 700 /home/u/.ssh; chmod 600 /home/u/.ssh/authorized_keys
mkdir -p /tmp/a-rather-long-directory-name-for-the-alternative-configuration; cp /etc/ssh/sshd_config /tmp/a-rather-long-directory-name-for-the-alternative-configuration/sshd_config_alt.conf
L=/tmp/a-rather-long-directory-name-for-the-alternative-configuration/sshd_config_alt.conf
cp /etc/ssh/sshd_config /tmp/alt.conf
proc() { for p in $(pgrep -x sshd); do printf '    /proc <cut> %s\n' "$(tr '\0' '|' < /proc/$p/cmdline | cat -v)"; done; }
echo "=== (a) long -f path, listener started normally (-D -f LONG -o Port=22)"
/usr/sbin/sshd -D -f $L -o Port=22 >/dev/null 2>&1 & sleep 1
echo "COLUMNS=60 ps -C sshd -o args= | cat:"; COLUMNS=60 ps -C sshd -o args= | cat -v | sed 's/^/    /'
echo "COLUMNS=60 ps -ww -C sshd -o args= | cat:"; COLUMNS=60 ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
echo "ps -C sshd -o args= | cat (no COLUMNS):"; ps -C sshd -o args= | cat -v | sed 's/^/    /'
proc; pkill -x sshd; sleep 1
echo "=== (b) env -i listener with options next to a plain listener (second one on port 2222)"
/usr/sbin/sshd -D >/dev/null 2>&1 & sleep 1
env -i /usr/sbin/sshd -D -f /tmp/alt.conf -o Port=2222 -o AuthorizedKeysFile=/x >/dev/null 2>&1 & sleep 1
echo "ps -ww -C sshd -o args=:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
proc; pkill -x sshd; sleep 1
echo "=== (b2) env -i with a short -f, alone"
env -i /usr/sbin/sshd -D -f /tmp/alt.conf -o Port=22 >/dev/null 2>&1 & sleep 1
echo "ps -ww -C sshd -o args=:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
proc; pkill -x sshd; sleep 1
echo "=== (c) child titles: sampler every 20 ms while logins run; unique lines seen"
/usr/sbin/sshd -D >/dev/null 2>&1 & sleep 1
( while :; do ps -ww -C sshd -o args= ; sleep 0.02; done ) > /tmp/samples 2>/dev/null &
SP=$!
O="-p 22 -i /root/k -o IdentitiesOnly=yes -o IdentityAgent=none -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
for n in 1 2 3; do
  ssh $O u@127.0.0.1 sleep 1
  ssh -tt $O u@127.0.0.1 sleep 1 </dev/null >/dev/null
  ssh $O nosuchuser@127.0.0.1 true
  ssh -p 22 -o PreferredAuthentications=password -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR u@127.0.0.1 true
  (exec 3<>/dev/tcp/127.0.0.1/22; sleep 0.5)
done
ssh $O u@127.0.0.1 sleep 3 & SS=$!; sleep 1.5
echo "during an open session:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
wait $SS
sleep 0.5; kill $SP
echo "unique lines sampled:"; sort /tmp/samples | uniq -c | sed 's/^/    /'
echo "after all sessions closed:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
pkill -x sshd
```

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
=== (a) long -f path, listener started normally (-D -f LONG -o Port=22)
COLUMNS=60 ps -C sshd -o args= | cat:
    sshd: /usr/sbin/sshd -D -f /tmp/a-rather-long-directory-name
COLUMNS=60 ps -ww -C sshd -o args= | cat:
    sshd: /usr/sbin/sshd -D -f /tmp/a-rather-long-directory-name-for-the-alternative-configuration/sshd_config_alt.conf -o Port=22 [listener] 0 of 10-100 startups
ps -C sshd -o args= | cat (no COLUMNS):
    sshd: /usr/sbin/sshd -D -f /tmp/a-rather-long-directory-name-for-the-alternative-configuration/sshd_config_alt.conf -o Port=22 [listener] 0 of 10-100 startups
    /proc <cut> sshd: /usr/sbin/sshd -D -f /tmp/a-rather-long-directory-name-for-the-alternative-configuration/sshd_config_alt.conf -o Port=22 [listener] 0 of 10-100 startups|
=== (b) env -i listener with options next to a plain listener (second one on port 2222)
ps -ww -C sshd -o args=:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
    sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o Port=2222 -o AuthorizedKey x
    /proc <cut> sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups|
    /proc <cut> sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o Port=2222 -o AuthorizedKey|x|
=== (b2) env -i with a short -f, alone
ps -ww -C sshd -o args=:
    sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o 2
    /proc <cut> sshd: /usr/sbin/sshd -D -f /tmp/alt.conf -o|2|
=== (c) child titles: sampler every 20 ms while logins run; unique lines seen
nosuchuser@127.0.0.1: Permission denied (publickey,password).
u@127.0.0.1: Permission denied (publickey,password).
nosuchuser@127.0.0.1: Permission denied (publickey,password).
u@127.0.0.1: Permission denied (publickey,password).
nosuchuser@127.0.0.1: Permission denied (publickey,password).
u@127.0.0.1: Permission denied (publickey,password).
during an open session:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
    sshd: u [priv]
    sshd: u@notty
unique lines sampled:
          1 /usr/sbin/sshd -D -R
          2 [sshd]
          2 [sshd] <defunct>
        352 sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
        113 sshd: /usr/sbin/sshd -D [listener] 1 of 10-100 startups
        103 sshd: [accepted]
         50 sshd: [net]
          1 sshd: [rexeced]
         11 sshd: u
          6 sshd: u [net]
        335 sshd: u [priv]
        209 sshd: u@notty
        105 sshd: u@pts/0
          1 sshd: unknown [net]
          2 sshd: unknown [priv]
after all sessions closed:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
```

`measure9.sh` shows the exact bytes of `ps -ww` and its result with no sshd:

```bash
#!/bin/bash
apt-get update -qq && apt-get install -y -qq openssh-server procps >/dev/null 2>&1
mkdir -p /run/sshd
ps -ww -C sshd -o args= >/tmp/o 2>/tmp/e; echo "no sshd, -ww: rc=$? stdout_bytes=$(wc -c </tmp/o) stderr_bytes=$(wc -c </tmp/e)"
/usr/sbin/sshd -D >/dev/null 2>&1 & sleep 1
echo "bytes of ps -ww -C sshd -o args= with one listener:"; ps -ww -C sshd -o args= | od -c | sed 's/^/    /'
pkill -x sshd
```

```
no sshd, -ww: rc=1 stdout_bytes=0 stderr_bytes=0
bytes of ps -ww -C sshd -o args= with one listener:
    0000000   s   s   h   d   :       /   u   s   r   /   s   b   i   n   /
    0000020   s   s   h   d       -   D       [   l   i   s   t   e   n   e
    0000040   r   ]       0       o   f       1   0   -   1   0   0       s
    0000060   t   a   r   t   u   p   s  \n
    0000070
```

What it shows, only from the output: (a) without `-ww`, `COLUMNS=60` cut the listener's title at 60 characters, with
`-ww` it did not; (b) a daemon started under `env -i` (empty environment) had its title cut and mangled
(`... -o Port=2222 -o AuthorizedKey x`, with no `[listener]` mark; in /proc a NUL replaced the cut) while the plain one
kept its full title, so a cut title is a real state, not a theory; with no sshd, `ps -ww` gave rc 1 and no output, and the
listener line ends in a single line feed with no trailing blank. The title forms seen across logins: `sshd: [accepted]`,
`sshd: [net]`, `sshd: [rexeced]`, `sshd: u`, `sshd: u [net]`, `sshd: u [priv]`, `sshd: u@notty`, `sshd: u@pts/0`,
`sshd: unknown [net]`, `sshd: unknown [priv]`, and, as processes of the name `sshd` before or after retitling,
`/usr/sbin/sshd -D -R`, `[sshd]` and `[sshd] <defunct>`. The collector accepts exactly these as children; any other line
(a cut title, an untitled process, trailing blanks, a form not seen such as `[pam]`, which did not appear) makes
`daemon_options` `could-not-check`.

#### Fix round 2: can a daemon's own cut title look like a child?

A review derived from the two `env -i` lines that a daemon started with an empty environment and the arguments `s -rfx`
could be cut to `sshd: x`, the bare child form. Measured with `python3 -c 'import os; os.execve("/usr/sbin/sshd",
["s","-rfx"], {})'` (a real execve with an empty environment; `python3` installed in the container), from a directory
holding a file `x` with `Port 2222`, beside a plain `-D` listener, and then the same with `argv[0]` = `sshd`:

```
docker run --rm --name t5b8 -v <scratchpad>/measure11.sh:/measure.sh:ro ubuntu:24.04 bash /measure.sh
```

```bash
#!/bin/bash
# runs inside ubuntu:24.04; python3 is installed to get a real execve with argv ["s","-rfx"] and an empty environment
apt-get update -qq && apt-get install -y -qq openssh-server procps python3 >/dev/null 2>&1
mkdir -p /run/sshd /tmp/d && cd /tmp/d
ssh -V 2>&1 | cut -d, -f1
printf 'Port 2222\n' > x
/usr/sbin/sshd -D >/dev/null 2>&1 & sleep 1
python3 -c 'import os; os.execve("/usr/sbin/sshd", ["s","-rfx"], {})' >/tmp/err 2>&1 &
sleep 1
echo "ps -ww -C sshd -o args= | od -c:"; ps -ww -C sshd -o args= | od -c | sed 's/^/    /'
echo "ps -ww -C sshd -o args= | cat -v:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
for p in $(pgrep -x sshd); do echo "  /proc <cut> cmdline bytes:"; od -c < /proc/$p/cmdline | sed 's/^/    /'; done
echo "processes named sshd: $(pgrep -x sshd | wc -l); output of the second start: $(cat /tmp/err)"
echo "listening on 2222: $( (ss -ltn 2>/dev/null || true) | grep -c ':2222 ')"
pkill -x sshd; sleep 1
echo "=== the same with argv[0] = sshd"
/usr/sbin/sshd -D >/dev/null 2>&1 & sleep 1
python3 -c 'import os; os.execve("/usr/sbin/sshd", ["sshd","-rfx"], {})' >/tmp/err 2>&1 &
sleep 1
echo "ps -ww -C sshd -o args= | od -c:"; ps -ww -C sshd -o args= | od -c | sed 's/^/    /'
echo "ps -ww -C sshd -o args= | cat -v:"; ps -ww -C sshd -o args= | cat -v | sed 's/^/    /'
for p in $(pgrep -x sshd); do echo "  /proc <cut> cmdline bytes:"; od -c < /proc/$p/cmdline | sed 's/^/    /'; done
pkill -x sshd
```

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
ps -ww -C sshd -o args= | od -c:
    0000000   s   s   h   d   :       /   u   s   r   /   s   b   i   n   /
    0000020   s   s   h   d       -   D       [   l   i   s   t   e   n   e
    0000040   r   ]       0       o   f       1   0   -   1   0   0       s
    0000060   t   a   r   t   u   p   s  \n   s   :       s       x  \n
    0000077
ps -ww -C sshd -o args= | cat -v:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
    s: s x
  /proc <cut> cmdline bytes:
    0000000   s   s   h   d   :       /   u   s   r   /   s   b   i   n   /
    0000020   s   s   h   d       -   D       [   l   i   s   t   e   n   e
    0000040   r   ]       0       o   f       1   0   -   1   0   0       s
    0000060   t   a   r   t   u   p   s  \0
    0000070
  /proc <cut> cmdline bytes:
    0000000   s   :       s  \0   x  \0
    0000007
processes named sshd: 2; output of the second start: 
listening on 2222: 0
=== the same with argv[0] = sshd
ps -ww -C sshd -o args= | od -c:
    0000000   s   s   h   d   :       /   u   s   r   /   s   b   i   n   /
    0000020   s   s   h   d       -   D       [   l   i   s   t   e   n   e
    0000040   r   ]       0       o   f       1   0   -   1   0   0       s
    0000060   t   a   r   t   u   p   s  \n   s   s   h   d   :       s    
    0000100   x  \n
    0000102
ps -ww -C sshd -o args= | cat -v:
    sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
    sshd: s x
  /proc <cut> cmdline bytes:
    0000000   s   s   h   d   :       /   u   s   r   /   s   b   i   n   /
    0000020   s   s   h   d       -   D       [   l   i   s   t   e   n   e
    0000040   r   ]       0       o   f       1   0   -   1   0   0       s
    0000060   t   a   r   t   u   p   s  \0
    0000070
  /proc <cut> cmdline bytes:
    0000000   s   s   h   d   :       s  \0   x  \0
    0000012
```

What it shows: the process started that way is a process named `sshd` with a title of `s: s x` (argv[0] `s`) or
`sshd: s x` (argv[0] `sshd`), in `/proc` `s: s|x|` / `sshd: s|x|`: two words, not the bare `sshd: x`, so the reviewer's
exact form was not reproduced here; whether it listened on 2222 was not checked (the `ss` count printed 0, but whether `ss` exists in the image was not
checked, so that 0 is not a measurement). The bare form can still not be excluded for another
argument layout, so the collector accepts a bare `sshd: NAME` only when NAME is an account in `/etc/passwd`; the suffixed
forms (`[priv]`, `[net]`, `@notty`, `@pts/N`) are accepted for any name, as a daemon's title cannot end in them. Only
`unknown [net]` and `unknown [priv]` were seen, never a bare `sshd: unknown`, which therefore counts as unrecognised.

Not measured: the box's own unit (a socket-activated start, `sshd.socket`, which would show another title or none), a
user name containing the text `[listener]` (the client refuses odd names; `useradd` refuses blanks), a child title not
in the list above (for example `[pam]`), the title of a re-executed child of a daemon started with options (`-R` with the
other options), any other sshd version, and a `ps` other than procps 4. Not seen by the method: `ps -C sshd` lists
processes by command name, so an OpenSSH daemon run from a binary with another name is not listed (the listening-port
items would show it); any local account can add a line that looks like a listener or an unrecognised one, which makes the
item CANNOT-VERIFY, never a pass.

## 4 · What is not measured

- 35 real days of journal: the rehearsal shows the setting in force and the deletion mechanism at 3 minutes, not a
  35-day run.
- The box's own restart of the journal service (Task 13 is the first).
- How systemd reads `SystemMaxFiles=` with a leading zero (as octal, or as decimal), a hexadecimal form or more
  than nine digits: `d2_4` gives `number` `could-not-check` for all of them instead of a count.
- The length of the kernel's clock tick on the box, and a settings file changed within one tick of the journal
  service's start: `d2_4` counts a change stamped less than 10 ms before the start as after it (R7).
- `Storage=none`; `Storage=auto` or no `Storage=` on a machine without `/var/log/journal` (R10 measured `volatile`).
- `Storage` unset with `/var/log/journal` present on a real boot: the rehearsal image sets `persistent`, the real
  server sets none. R13 (relinquish, restart, flush) was measured with `persistent` only.
- `MaxLevelStore=`: it thins what is stored; D2.4 does not read it.
- A `/var` the journal service could not open, or a flush unit that failed: R13 produced the state with
  `journalctl --relinquish-var` only, so what `/run/systemd/journal/flushed` reads in those two cases is not known
  (the age of the newest on-disk entry is what covers them, once it passes 600 seconds).
- The flag `/run/systemd/journal/flushed` on the real server: the operator's trial collection shows it.
- What `systemd-analyze cat-config` prints for a settings directory linked to an absolute path or to a place
  outside `/etc/systemd` (R12 measured a relative link beside it).
- `d2_4` on the box itself: R7 is the container. The start-time command and its `us+utc` form are measured on
  systemd 255 only.
- `hermes-broker` and `hermes-docker-proxy` logging after the restart (only the audit broker has a safe trigger);
  the rehearsal's long-running stand-in is the `ticker` unit.
## R14 · what the journal search can miss

Measured 2026-10-10 in a fresh container `jr6` (image `journald-rehearsal`), removed afterwards. The scripts ran in the order: items 1, 2, 4, 5, 6 (first try), 3 (it damages the journal, so it ran last of that script); item 4's strict-decode check and item 6's unit-file form were run afterwards. Output is unedited except that the machine id is cut (`<machine id>`) and the scratch path is `<scratchpad>`.

### The script (scratch file \`<scratchpad>/m.sh\`), and its output

```
echo '--- 1a'; journalctl -o cat --no-pager >/dev/null; echo rc=$?
echo '--- 1b'; journalctl -u ticker --since -30d -o cat --no-pager >/dev/null; echo rc=$?
echo '--- 2'; runuser -u nobody -- journalctl -o cat --no-pager | wc -c; echo rc=${PIPESTATUS[0]}
echo '--- 4'
printf 'bad \377 byte MARK-AFTER-BYTE\n' | systemd-cat -t t8; sleep 1
echo '[plain]'; journalctl -t t8 -o cat --no-pager | od -c | tail -5
echo '[--all]'; journalctl -t t8 -o cat --no-pager --all | od -c | tail -5
echo '[strict decode, plain]'; journalctl -o cat --no-pager | python3 -c "import sys; sys.stdin.read(); print('decoded ok')"; echo rc=${PIPESTATUS[1]}
echo '--- 5'
python3 -c "print('x'*100000+'MARK-AT-END')" | systemd-cat -t t8long; sleep 1
echo -n 'plain: '; journalctl -t t8long -o cat --no-pager | grep -c MARK-AT-END
echo -n 'all: '; journalctl -t t8long -o cat --no-pager --all | grep -c MARK-AT-END
echo -n 'plain chars: '; journalctl -t t8long -o cat --no-pager | wc -c
echo -n 'all chars: '; journalctl -t t8long -o cat --no-pager --all | wc -c
echo '--- 6'
systemd-run --unit t8cmd --wait /bin/sh -c 'echo hello-from-t8cmd' TOKEN-IN-ARGV-123 2>&1 | tail -2; sleep 1
echo -n 'cat: '; journalctl -u t8cmd -o cat --no-pager | grep -c TOKEN-IN-ARGV-123
echo -n 'json: '; journalctl -u t8cmd -o json --no-pager | grep -c TOKEN-IN-ARGV-123
journalctl -u t8cmd -o json --no-pager | grep -o '"_CMDLINE":"[^"]*"' | head -2
echo '--- 3'
journalctl --rotate; f=$(ls /var/log/journal/$(cat /etc/machine-id)/system@*.journal | head -1); truncate -s 4096 "$f"
journalctl -o cat --no-pager >/dev/null; echo rc=$?
echo '[oldest]'; journalctl -q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP -n +1; echo rc=$?
echo '[wc after]'; journalctl -o cat --no-pager 2>/dev/null | wc -c
```

```
--- 1a
rc=0
--- 1b
rc=0
--- 2
No journal files were opened due to insufficient permissions.
0
rc=1
--- 4
[plain]
0000000   b   a   d     377       b   y   t   e       M   A   R   K   -
0000020   A   F   T   E   R   -   B   Y   T   E  \n
0000033
[--all]
0000000   b   a   d     377       b   y   t   e       M   A   R   K   -
0000020   A   F   T   E   R   -   B   Y   T   E  \n
0000033
[strict decode, plain]
decoded ok
rc=0
--- 5
plain: 1
all: 1
plain chars: 100014
all chars: 100014
--- 6
Failed to connect to bus: No such file or directory
cat: 0
json: 0
--- 3
Journal file /var/log/journal/<machine id>/system@<machine id>-0000000000000440-00065d8277b0fc05.journal is truncated, ignoring file.
rc=0
[oldest]
Journal file /var/log/journal/<machine id>/system@<machine id>-0000000000000440-00065d8277b0fc05.journal is truncated, ignoring file.
{"__REALTIME_TIMESTAMP":"1791664815876897","__SEQNUM":"2257","__MONOTONIC_TIMESTAMP":"10721451533","__SEQNUM_ID":"<machine id>","__CURSOR":"s=<machine id>;i=8d1;b=<machine id>;m=27f0c5e0d;t=65d8278e82b21;x=27538f0207472e85","_BOOT_ID":"<machine id>"}
rc=0
[wc after]
255
```

### Item 4, strict decode (the collector reads with \`text=True\`, i.e. a strict UTF-8 decode)

```
printf 'bad \377 byte MARK-AFTER-BYTE\n' | systemd-cat -t t8b; sleep 1
journalctl -t t8b -o cat --no-pager > /tmp/t8b.out; wc -c < /tmp/t8b.out
python3 -c "import sys; d=open('/tmp/t8b.out','rb').read().decode('utf-8'); print('decoded', len(d))"; echo rc=$?
---
54
Traceback (most recent call last):
  File "<string>", line 1, in <module>
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 4: invalid start byte
rc=1
```

### Item 6, in a unit file (\`systemd-run\` failed above: no bus in the container)

```
echo '--- 6'
cat > /etc/systemd/system/t8cmd.service <<'U'
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo hello-from-t8cmd; sleep 3' TOKEN-IN-ARGV-123
U
systemctl daemon-reload; systemctl start t8cmd; echo start-rc=$?; sleep 1
echo -n 'cat: '; journalctl -u t8cmd -o cat --no-pager | grep -c TOKEN-IN-ARGV-123
echo -n 'json: '; journalctl -u t8cmd -o json --no-pager | grep -c TOKEN-IN-ARGV-123
journalctl -u t8cmd -o json --no-pager | grep -o '"_CMDLINE":"[^"]*"' | sort -u
journalctl -u t8cmd -o cat --no-pager
---
--- 6
start-rc=0
cat: 0
json: 2
"_CMDLINE":"/bin/sh -c \"
"_CMDLINE":"/sbin/init"
Starting t8cmd.service...
hello-from-t8cmd
t8cmd.service: Deactivated successfully.
Finished t8cmd.service.
Starting t8cmd.service...
hello-from-t8cmd
t8cmd.service: Deactivated successfully.
Finished t8cmd.service.
Starting t8cmd.service...
hello-from-t8cmd
t8cmd.service: Deactivated successfully.
Finished t8cmd.service.
Starting t8cmd.service...
hello-from-t8cmd
t8cmd.service: Deactivated successfully.
Finished t8cmd.service.
```

The unit was started again each time the script was repeated while preparing this record, so the message repeats; the `json` count is the number of lines holding the token.

### What it showed

1. A healthy root run: rc 0 and nothing on stderr, for the whole journal and for the D10.7 form (`-u ticker --since -30d`).
2. No rights (`nobody`): rc **1**, 0 characters, and `No journal files were opened due to insufficient permissions.` on stderr. A caller with a journal of its own but no right to the system journal (journalctl's "Hint: You are currently not seeing messages from other users and the system" case) was not produced in this item; item 7 measures it: rc 0, nothing on stderr, only that user's own entries.
3. A truncated archived file: **rc 0**, stdout continues, and stderr says `Journal file …/system@….journal is truncated, ignoring file.`, for the search and for the oldest-entry call alike. The oldest-entry call still printed an entry (of the files that remained). The text searched shrank to 255 characters (from the 100 kB of the earlier item 5 plus the rest of the journal: the before-count was not taken, so the drop is inferred).
4. A message with a byte that is not UTF-8: plain `-o cat` prints it whole (the byte as `377`, `MARK-AFTER-BYTE` after it); `--all` prints the same. No placeholder. But a strict UTF-8 decode of that output raises `UnicodeDecodeError`, and the collector reads with `text=True`: the probe ends `could-not-check` (it fails safe, and stays so while such a message is in the journal).
5. A message of 100011 characters: plain `-o cat` and `--all` both print it whole (`MARK-AT-END` found once in each, 100014 characters).
6. A token in a command line: stored in `_CMDLINE` of the `-o json` output (count above 0), absent from `-o cat` (count 0). D2.3 does not search it. (A line logged by a process that had already exited carried no `_CMDLINE` at all.)

### What was decided for measurements 4 and 6
Measurement 6 (a token in a command line, stored in `_CMDLINE` and not searched): not changed. D2.3 has always searched the message text only; widening it is the operator's decision and its own change. The checklist says so under "What this item cannot show". Measurement 4 (one message with a byte that is not UTF-8 ended the strict decode, so D2.3 was `could-not-check` for as long as the message stayed in the journal, now up to 35 days): fixed. The journal reads decode with replacement (`Host.run_lossy`, the same single command and limit), D2.3 reports `undecodable_characters` (the count of U+FFFD in the text searched), and a credential is ASCII, so it is still found beside a replaced byte. What can be lost is a credential with an invalid byte inside it, which is not that credential. D10.7 decodes the same way but does not report the count: adding it changes the pinned shape of three tests, so it was left alone.

### Notes on this record
- Item 4 printed `decoded ok rc=0` in the first script because that reader (`sys.stdin.read()`) was not strict in this container (Python's C-locale handling escapes such bytes instead of failing). The later run, which decodes the bytes with `decode('utf-8')`, is the valid one.
- The empty stderr of item 1 is this container's. The operator's trial collection shows the box's.

### Item 7, a user who is not root (fresh container `jr7`, removed afterwards)

```
useradd -m u2; echo useradd-rc=$?
runuser -u u2 -- logger from-u2; echo logger-rc=$?; sleep 1
runuser -u u2 -- journalctl -o cat --no-pager >/dev/null; echo rc=$?
runuser -u u2 -- journalctl -o cat --no-pager | wc -c
runuser -u u2 -- journalctl -o cat --no-pager 2>&1 | head -5
echo '[root, same journal]'; journalctl -o cat --no-pager | wc -c
ls -la /var/log/journal/*/ | head
---
useradd-rc=0
logger-rc=0
rc=0
8
from-u2
[root, same journal]
61505
total 16400
drwxr-sr-x+ 2 root systemd-journal    4096 Oct 10 20:53 .
drwxr-sr-x+ 1 root systemd-journal    4096 Oct 10 20:53 ..
-rw-r-----+ 1 root systemd-journal 8388608 Oct 10 20:53 system.journal
-rw-r-----+ 1 root systemd-journal 8388608 Oct 10 20:53 user-1001.journal
```

A user with a journal of its own reads **rc 0, nothing on stderr**, and sees only its own entries (8 characters here, against 61505 as root): a partial read that nothing announces. So the collector refuses to read the journal unless it runs as root (`the journal is read as root only`).

### Item 8, the standard error of the single-entry reads on a healthy service

Measured 2026-10-11 (UTC) in `jr`, as root, the journal service healthy and restarted a moment before. The script
(scratch file `<scratchpad>/e4.sh`, piped to `docker exec -i jr bash`) and its output:

```
F="-q --no-pager -o json --output-fields=__REALTIME_TIMESTAMP"
echo '--- whole';        journalctl $F -n +1 2>&1 >/dev/null | od -c | head -3; echo rc=$?
echo '--- unit, 30d';    journalctl $F -u ticker --since -30d -n +1 2>&1 >/dev/null | od -c | head -3; echo rc=$?
echo '--- no such unit'; journalctl $F -u no-such-unit -n +1 2>&1 >/dev/null | od -c | head -3; echo rc=$?
echo '--- on disk, -D';  journalctl -D /var/log/journal/$(cat /etc/machine-id) $F -n 1 2>&1 >/dev/null | od -c | head -3; echo rc=$?
echo '--- the four exit statuses and stdout sizes'
journalctl $F -n +1 2>/dev/null | wc -c; echo rc=${PIPESTATUS[0]}
journalctl $F -u ticker --since -30d -n +1 2>/dev/null | wc -c; echo rc=${PIPESTATUS[0]}
journalctl $F -u no-such-unit -n +1 2>/dev/null | wc -c; echo rc=${PIPESTATUS[0]}
journalctl -D /var/log/journal/$(cat /etc/machine-id) $F -n 1 2>/dev/null | wc -c; echo rc=${PIPESTATUS[0]}
```

```
--- whole
0000000
rc=0
--- unit, 30d
0000000
rc=0
--- no such unit
0000000
rc=0
--- on disk, -D
0000000
rc=0
--- the four exit statuses and stdout sizes
326
rc=0
327
rc=0
0
rc=0
333
rc=0
```

`od -c` prints only its closing offset `0000000`: **no byte on standard error** for any of the four forms (the whole
journal, `-u ticker --since -30d`, a unit that does not exist, and the on-disk read with `-D`). Each exits 0; the
unit that does not exist prints nothing on standard output either. (The `rc=` after each `od` line is the pipe's, so
the second half reads each command's own status.) The addendum's literal form
(`docker exec jr sh -c '… -n +1 2>&1 >/dev/null | od -c | head -3; echo rc=$?'`) printed the same `0000000`, `rc=0`.
So the collector's rule "anything on stderr is could-not-check" does not fire on a healthy service here. This is the
container's; the operator's trial collection shows the box's.

## 5 · The runbook blocks, as written

Rehearsed 2026-10-11 (UTC; 2026-10-10 local). Every block that `infra/hermes-agent/deploy/BRING-UP.md` tells the
operator to paste in "The journal's retention (finding F58)" and the new block of "A security review" was taken OUT
OF THE RUNBOOK FILE by a script (the text between its code fences), not retyped, and run as below. Several blocks
were changed after the review of this task: "After the review" below holds the rehearsal of the blocks as they now
stand, and its outputs replace the ones before it for the changed blocks. What is a stand-in is said there.

**How.** The VPS blocks ran in the container `jr`, where the caller is root and there is no `sudo`: the only change
to each block is that the word `sudo ` is removed (`sed 's/sudo //g'`). Each was piped to `docker exec -i jr bash`,
so what ran is bash reading the pasted text. `jr` was first brought to the state of a box before the step: our file
and its directory removed, the journal service restarted. Order in `jr`: VPS 1, VPS 2, VPS 2 again, VPS 3, VPS 3
again, the flush line, VPS 4, VPS 4 again, VPS 1, VPS 2, VPS 3. `jr` is left running with our file installed and
the service restarted after it. Two more containers from the same image were started for this section and
removed afterwards: `jr11` (with `openssh-server` and `procps` installed, an sshd started through `ssh.socket`, and
an empty client list `{"clients": {}}` so that the collector runs) and `jr12` (without the repository, for the
failure paths).

### The VPS blocks in `jr`

```
===== vps1 (before anything)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
ssh release: sh: 1: ssh: not found
sshd listeners: 0 | words starting -f or -o: 0
sh: 1: docker: not found
docker logging: 
Sun Oct 11 01:29:47 UTC 2026
[exit status of the paste: 0]
===== vps2 (first)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
[exit status of the paste: 0]
===== vps2 (pasted again)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
[exit status of the paste: 0]
===== vps3 (first)
journal service: active | started: Sun 2026-10-11 01:29:47 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
Failed to start hermes-listener-check.service: Unit hermes-listener-check.service not found.
listener_check_rc=5
Sun Oct 11 01:29:52 UTC 2026
[exit status of the paste: 0]
===== vps3 (pasted again)
journal service: active | started: Sun 2026-10-11 01:29:52 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
Failed to start hermes-listener-check.service: Unit hermes-listener-check.service not found.
listener_check_rc=5
Sun Oct 11 01:29:57 UTC 2026
[exit status of the paste: 0]
===== flush (the one line)
journal on disk: yes
[exit status of the paste: 0]
===== vps4 (undo)
journal service: active | our file still there: no
[exit status of the paste: 0]
===== vps4 (pasted again)
journal service: active | our file still there: no
[exit status of the paste: 0]
===== vps1 (after the undo)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
ssh release: sh: 1: ssh: not found
sshd listeners: 0 | words starting -f or -o: 0
sh: 1: docker: not found
docker logging: 
Sun Oct 11 01:30:07 UTC 2026
[exit status of the paste: 0]
===== vps2 (second install)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
[exit status of the paste: 0]
===== vps3 (second apply)
journal service: active | started: Sun 2026-10-11 01:30:08 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
Failed to start hermes-listener-check.service: Unit hermes-listener-check.service not found.
listener_check_rc=5
Sun Oct 11 01:30:13 UTC 2026
[exit status of the paste: 0]
```

Readings, block by block:

- **VPS 1.** The settings lines, the oldest entry, the file count, the disk use, `journal on disk: yes` and
  `settings paths that are links: 0` printed as the runbook expects, with the stand-in's stated differences
  (`Storage=persistent` is set in its own file; 1 journal file; 2% used). `jr` has no ssh client, no sshd, no Docker
  and no broker: `ssh release:` holds the shell's `ssh: not found`, the sshd counts are `0` and `0`, `docker
  logging:` is empty after `docker: not found`, and no refusal line is printed. Expected text changed after the
  rehearsal: the brief's `cut -c1-24` cut the time to `…+00:0`; the block now cuts at 25 and prints `…+00:00`.
- **VPS 2.** The six lines in the runbook's order, then `files in the directory: 1`. Pasted again: the same output.
- **VPS 3.** `journal service: active`, a start time 5 seconds before the block's last line, `journal on disk: yes`,
  `same: yes`. The three Hermes services print `inactive` and the listener check `not found` with
  `listener_check_rc=5`: none of them exists in `jr`. Pasted again: the same, with a new start time.
- **The flush line.** `journal on disk: yes`.
- **VPS 4.** `journal service: active | our file still there: no`; pasted again: the same. VPS 1 after it shows the
  server's own settings only, as before the step.

### VPS 1 with a real sshd, and VPS 2, VPS 3 once more (`jr11`)

```
===== vps1 in jr11 (a real sshd of the same release, started by its socket unit)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-11T00:57:37+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
ssh release: OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
sshd listeners: 1 | words starting -f or -o: 0
sh: 1: docker: not found
docker logging: 
Sun Oct 11 01:30:34 UTC 2026
===== vps2 in jr11
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== vps3 in jr11
journal service: active | started: Sun 2026-10-11 01:31:08 UTC | journal on disk: yes
oldest entry before: 2026-10-11T00:57:37+00:00 | after: 2026-10-11T00:57:37+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
Failed to start hermes-listener-check.service: Unit hermes-listener-check.service not found.
listener_check_rc=5
Sun Oct 11 01:31:13 UTC 2026
```

`ssh release:` and the two sshd counts print as the runbook expects. The box's own values were read by the operator
on 2026-10-11 (section 2) and are the same.

**Do the block's two counts agree with the collector?** The script below ran in `jr11` (scratch file
`<scratchpad>/sshd-state.sh`); `counts` prints the block's two numbers and then `_sshd_daemon_options` of the
collector in the checkout. The connection in state 2 is a plain TCP connection made by bash, not an ssh client.

```
counts() { echo "block: listeners $(ps -ww -C sshd -o args= | grep -c "\[listener\]") | words starting -f or -o: $(ps -ww -C sshd -o args= | grep "\[listener\]" | tr " " "\n" | grep -cE "^-[A-Za-z]*[fo]")"
  python3 -c '
import importlib.util,sys
sys.dont_write_bytecode=True
sp=importlib.util.spec_from_file_location("ce","/opt/projects/claude_code/infra/hermes-agent/bin/collect-review-evidence.py"); ce=importlib.util.module_from_spec(sp); sp.loader.exec_module(ce)
print("collector:", ce._sshd_daemon_options(ce.Host("/")))'; }
echo "=== 1 socket unit started, nothing connected yet"; systemctl start ssh.socket; sleep 1; echo "ssh.socket $(systemctl is-active ssh.socket) | ssh.service $(systemctl is-active ssh)"; ps -ww -C sshd -o args=; counts
echo "=== 2 after one TCP connection to port 22 (bash /dev/tcp, no ssh client)"; (exec 3<>/dev/tcp/127.0.0.1/22; head -c 8 <&3 >/dev/null; exec 3<&-) 2>&1; sleep 2; echo "ssh.service $(systemctl is-active ssh)"; ps -ww -C sshd -o args=; counts
echo "=== 3 a second daemon with -o and -E (a value word that holds f and o)"; mkdir -p /run/sshd; /usr/sbin/sshd -p 2022 -oLogLevel=INFO -E/tmp/logfile; sleep 1; ps -ww -C sshd -o args=; counts; pkill -f 'sshd -p 2022'; sleep 1
echo "=== 4 back to one"; ps -ww -C sshd -o args=; counts
```

```
=== 1 socket unit started, nothing connected yet
ssh.socket active | ssh.service inactive
block: listeners 0 | words starting -f or -o: 0
collector: {'listeners': 0, 'config_file_options': 0, 'setting_options': 0}
=== 2 after one TCP connection to port 22 (bash /dev/tcp, no ssh client)
ssh.service active
sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
block: listeners 1 | words starting -f or -o: 0
collector: {'listeners': 1, 'config_file_options': 0, 'setting_options': 0}
=== 3 a second daemon with -o and -E (a value word that holds f and o)
sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
sshd: /usr/sbin/sshd -p 2022 -oLogLevel=INFO -E/tmp/logfile [listener] 0 of 10-100 startups
block: listeners 2 | words starting -f or -o: 1
collector: {'listeners': 2, 'config_file_options': 0, 'setting_options': 1}
=== 4 back to one
sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups
block: listeners 1 | words starting -f or -o: 0
collector: {'listeners': 1, 'config_file_options': 0, 'setting_options': 0}
```

- They agreed in all four states. A daemon started through `ssh.socket` has the ordinary listener title once the
  first connection has started it; before that there is no sshd process and both read 0 listeners (on the box an
  operator who is logged in over SSH has already started it).
- Where they can differ, by reading the two (not produced here): the block gives ONE number for `-f` and `-o`
  together, and counts every word that starts with `-` and has an `f` or `o` among its leading letters, while the
  collector stops at the first letter of a word that takes a value (`-Elogfile` counts in the block and not in the
  collector). So the block's number is never lower than the collector's two together and can be higher. The block
  counts any line holding `[listener]`; the collector wants the whole line in the measured form and answers
  `could-not-check` for a cut or unknown line. The runbook's stop text says both.

### Failure paths (`jr12`, no repository mounted)

```
===== vps2 in jr12 (no checkout there: the install line fails)
install: cannot stat '/opt/projects/claude_code/infra/hermes-agent/deploy/journald-hermes-retention.conf': No such file or directory
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 0
===== the stop instruction's line, then the directory
rc=0
3
===== vps4 in jr12 with no file of ours installed (the directory is empty)
journal service: active | our file still there: no
ls: cannot access '/etc/systemd/journald.conf.d': No such file or directory
===== journal taken back to memory (journalctl --relinquish-var), then vps1 line and the flush line
relinquish rc=0
journal on disk: no
journal on disk: yes
```

- VPS 2 without the repository file: `install: cannot stat …`, no line for our file, `files in the directory: 0`.
  The runbook's stop rule covers it (the last `MaxRetentionSec=` is not `35day`). The stop instruction's `rm -f`
  exits 0 with nothing to remove. The directory made by the first `install` line stays, empty (the `3` is `ls -la`'s
  three lines for an empty directory).
- VPS 4 with nothing of ours installed: it removes the empty directory, restarts, and prints the expected line.
- After `journalctl --relinquish-var` the flag line reads `no`; the runbook's flush line then prints `yes`.

### The trial collection piped into the summary tool

The runbook's line, without `sudo`, run under a pseudo-terminal (`script -qc "bash /tmp/trial.sh" /dev/null`, the
throwaway key written to it after 3 seconds) because the collector asks for the key on the terminal.

In `jr` (no client list there, so the collector stops; this is the "collector stopped" path):

```
review fingerprint key (hidden, from `pbcopy < ~/.config/hermes-review/fp.key`): 
collect-review-evidence: cannot load the redaction list: FileNotFoundError — refusing to print anything I cannot redact
summarize-review-bundle: not a box bundle (did the collector stop? read its own message and its rc)
collector_rc=2
```

In `jr11` (empty client list): 95 lines. The first four, the items the journal step concerns, and the closing list:

```
review fingerprint key (hidden, from `pbcopy < ~/.config/hermes-review/fp.key`): 
collected_at 2026-10-11T01:31:16Z
items 31 | not observed: D1.1, D1.2, D4.1, D5.2, D10.1, D10.2, D10.4, D10.6, D10.8
other items: 0
…
D1.7  observed
  accounts_checked: 22
  unprivileged_port_start: 0
  match_lines: 0
  include_elsewhere: 0
  daemon_options: {listeners: 1, config_file_options: 0, setting_options: 0}
  sshd_settings: 8
  files: 0
…
D2.3  observed
  journal: {pattern_hits: 0, known_secret_hits: 0}
  scanned_characters: 67030
  undecodable_characters: 0
  oldest_entry_read: 2026-10-11T00:57:37Z
D2.4  observed
  oldest_entry: {broker: null, journal: 2026-10-11T00:57:37Z, runner: null}
  reach_days: 0
  settings: {MaxFileSec: {number: 86400, set_by: other, value: 1day}, MaxRetentionSec: {number: 3024000, set_by: ours, value: 35day}, Storage: {number: null, set_by: other, value: persistent}, SystemMaxFiles: {number: 500, set_by: ours, value: 500}, SystemMaxUse: {number: 1073741824, set_by: other, value: 1G}}
  drop_in: {equals_repo: true, owner_is_root: true, group_is_root: true, mode: 0o644, other_files: 0}
  service: {active: true, started_at: 2026-10-11T01:31:08Z, config_changed_after_start: false}
  usage: {bytes: 8392704, files: 1, bytes_percent_of_max_use: 0.8, files_percent_of_max_files: 0.2, free_bytes: 915297001472, free_percent: 93.6, other_directories: 0, newest_entry_on_disk: 2026-10-11T01:31:16Z, on_disk_age_seconds: 0, flushed_to_disk: true}
…
Before the real collection (ok = as expected, LOOK = look at it first):
LOOK  every item observed (31 items) (not observed: D1.1, D1.2, D4.1, D5.2, D10.1, D10.2, D10.4, D10.6, D10.8)
LOOK  nothing in the bundle is could-not-check (28 places)
ok    sshd runs with its default settings file and no Match line
LOOK  the three live refusals are in the journal (missing: refused/disabled, refused/quota, refused/bad_request)
LOOK  at least one run/ok result
ok    retention at least 30 days, set by our file, the file equal to the repository's, no other file
LOOK  the journal reaches 30 days (reach is 0 days: the evidence needs the date the retention was raised)
ok    the journal search read everything it was given
ok    the running journal service has read its settings
ok    the journal is being written to disk
LOOK  the proxy matches the last PASS
LOOK  no service runs older code than the box holds
LOOK  fingerprint complete
Reminders, not verdicts: the reviewer judges the real bundle against the checklist.
collector_rc=0
```

The closing list has thirteen lines, in the wording the runbook lists. `the proxy matches the last PASS` reads `LOOK`
because the trial line names no last PASS (`matches_last_pass` is `null`), which the runbook says. The other `LOOK`
lines are the stand-in's: it has no Hermes services, no broker and no audit.

### The laptop block `kc` (zsh on this Mac, a private agent, a throwaway key)

The block was sourced by `zsh -f` from the text taken out of the runbook, with ONE change for the rehearsal only:
`K="$HOME/.ssh/vps-hermes"` became the path of a throwaway ed25519 key made under `<scratchpad>/t11/k` (deleted
afterwards). The shell first ran `eval "$(ssh-agent -s)"`, so `SSH_AUTH_SOCK` pointed at a private agent for that
shell only; the operator's own agent was not touched, no real key or comment was read or printed, and no `ssh` was
run. The agent was emptied and stopped at the end (`ssh-agent -k`). The first two lines of the block read this
laptop's real `~/.ssh/config` and process list, as counts.

```
lines of the block that set K: 1
===== run 1: the block, K set to the throwaway key
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 0
===== run 2: pasted again
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 0
===== run 3: the throwaway key put in the agent first
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
STOPPED: the key is in the agent already (a work session): run this again after 'ssh-add -d ~/.ssh/vps-hermes'
throwaway key still in the agent: 1
===== run 4: no public file
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
STOPPED: could not read the key's public file
===== run 5: a stand-in ssh-add whose keychain load supplies the throwaway key
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 1 -- the passphrase is in the keychain again; the key was taken out of the agent; stop and report
throwaway key in the agent afterwards: 0
function kc left defined: no
private agent stopped
```

- Runs 1 and 2 (the block, and pasted again): the four lines the runbook expects. The real
  `ssh-add --apple-load-keychain` ran against the private agent and ended with `rc=0`; afterwards that agent held
  **0** keys (`ssh-add -l` exit status 1, counted separately; no name was listed). So on this Mac, today, the
  keychain supplies no SSH key at all, and the load still ends with 0: the state LAPTOP 5c had marked "not
  measured" before the rollout.
- Run 3 (the key already in the agent): the first `STOPPED` line; the key was left in the agent, as the text says.
- Run 4 (no public file): the second `STOPPED` line.
- Run 5, with a STAND-IN: a shell function `ssh-add` that, for `--apple-load-keychain` only, adds the throwaway key
  (every other call goes to the real `ssh-add`). The block printed `supplied by the keychain: 1 -- …` and the key was
  out of the agent afterwards. The real keychain was not made to hold the throwaway key's passphrase: that would
  write to the operator's keychain.
- The function is not left defined after the paste.

### After the review: the blocks as changed, rehearsed again (2026-10-11 UTC)

The review of this task changed these blocks: VPS 1 (the server program's own release line `sshd -V`; the error
texts of `docker info` and of the journal directory's `ls` are no longer printed), VPS 3 (the listener check's own
line is picked out with `grep`), live check a of step 11 (one guard added around the handoff's lines), `kc` (it
counts the key again after taking it out); and added two: "take the file out again" after a stop in VPS 2, and a
label for the flush block. VPS 2, VPS 4, the flush line, and checks b, c, the prompt and "afterwards" are unchanged.
Every block was again taken out of the runbook file by script and run exactly as written, `sudo ` removed (and
`sudo -u hermes-app-ads-audit ` for step 11); after the last edit the blocks in the file were compared once more
with the ones run: equal. **The outputs below replace those above for the changed blocks.**

**Stand-ins in this round, and only these.** (1) A unit `hermes-listener-check.service` in `jr`, `Type=oneshot`,
first with `ExecStart=/bin/true` (it writes no line of its own), then with an `echo` of a line in the real check's
form. (2) A unit `hermes-app-broker@.service` in `jr` running the script below, which answers a request file with a
journal line of the broker's shape. (3) For `kc` run 5, the shell function described above. (4) `jr` is root without
`sudo`, and the request files are written by root, not by the app's user. The real listener check, the real broker
and its ledger were not run. All stand-in units, the script and `/var/lib/hermes` were removed from `jr` afterwards.

#### The journal blocks in `jr`

`jr` was first brought back to the state before the step. Order: VPS 1, VPS 2, the take-out block, the take-out
block again, VPS 2, VPS 3 (silent stand-in), VPS 3 (speaking stand-in), the flush block, VPS 4, VPS 4, VPS 1,
VPS 2, VPS 3.

```
===== vps1 (before anything)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
sshd release: sh: 1: sshd: not found
sshd listeners: 0 | words starting -f or -o: 0
docker logging: 
Sun Oct 11 01:48:05 UTC 2026
===== vps2 (first)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== takeout (after a stop in VPS 2)
our file still there: no | directory still there: no
===== takeout (pasted again, nothing there)
rmdir: failed to remove '/etc/systemd/journald.conf.d': No such file or directory
our file still there: no | directory still there: no
===== vps2 (again)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== vps3 (the listener stand-in writes NO line of its own)
journal service: active | started: Sun 2026-10-11 01:48:06 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
listener_check_rc=0
Sun Oct 11 01:48:11 UTC 2026
===== (stand-in changed: the listener check now writes a status=ok line)
===== vps3 (pasted again; the stand-in writes its line)
journal service: active | started: Sun 2026-10-11 01:48:11 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
listener_check_rc=0
hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[] docker_dns_listeners=1
Sun Oct 11 01:48:16 UTC 2026
===== what the journal holds for that unit, for comparison (the brief's tail -1 would have printed its last line)
Starting hermes-listener-check.service...
hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[] docker_dns_listeners=1
hermes-listener-check.service: Deactivated successfully.
Finished hermes-listener-check.service.
===== flush (the flush block)
journal on disk: yes
===== vps4 (undo)
journal service: active | our file still there: no
===== vps4 (pasted again)
journal service: active | our file still there: no
===== vps1 (after the undo)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
sshd release: sh: 1: sshd: not found
sshd listeners: 0 | words starting -f or -o: 0
docker logging: 
Sun Oct 11 01:48:26 UTC 2026
===== vps2 (second install)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== vps3 (second apply)
journal service: active | started: Sun 2026-10-11 01:48:26 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
listener_check_rc=0
hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[] docker_dns_listeners=1
Sun Oct 11 01:48:31 UTC 2026
```

- **VPS 1:** `sshd release:` holds the shell's `sshd: not found` (no sshd in `jr`; `jr11` below has one). `docker
  logging:` has nothing after it and no error line is printed any more.
- **The take-out block:** removes the file and the directory; pasted again, `rmdir` says `No such file or
  directory` and the line is the same.
- **VPS 3, the listener line.** With the silent stand-in: `listener_check_rc=0` and NO line after it, which the
  runbook names as a stop. With the speaking stand-in: the check's own line. The four lines the journal holds for
  the unit are printed after it for comparison: the last is systemd's `Finished hermes-listener-check.service.`,
  which is what the block's earlier `tail -1` would have shown.
- VPS 2, the flush block and VPS 4 printed what they printed before.

The third line of VPS 2 pasted alone (the runbook's "Reading it later" asks for it) printed the same six lines and
`files in the directory: 1`.

#### VPS 1 with a real sshd, and the take-out block with another file present (`jr11`, started again, removed)

`sshd -V` in that container printed `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19, OpenSSL 3.0.13 30 Jan 2024` with exit
status 0, so the block reads the server program, not the client.

```
===== vps1 in jr11 (a real sshd, started through ssh.socket)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-11T01:46:04+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
sshd release: OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
sshd listeners: 1 | words starting -f or -o: 0
docker logging: 
Sun Oct 11 01:49:22 UTC 2026
===== vps2 in jr11, then another file put in the directory, then the take-out block
files in the directory: 1
rmdir: failed to remove '/etc/systemd/journald.conf.d': Directory not empty
our file still there: no | directory still there: yes
```

#### Step 11 in `jr`, against the stand-in broker

The stand-in broker (`/usr/local/bin/standin-broker`):

```bash
#!/bin/bash
# STAND-IN for the audit broker, for the rehearsal only: it answers a request file with a journal line of the broker's shape.
D=/var/lib/hermes/spool/apps/ads-audit/requests; SW=/var/lib/hermes/app-state/ads-audit/DISABLED
while sleep 1; do for f in "$D"/*.json; do [ -e "$f" ] || continue; r=$(basename "$f" .json)
  if ! grep -q '"op"' "$f"; then echo "hermes-app-broker[ads-audit]: request=$r op=- client=- status=refused reason=bad_request"
  elif [ -e "$SW" ]; then echo "hermes-app-broker[ads-audit]: request=$r op=run client=standin status=refused reason=disabled"
  else echo "hermes-app-broker[ads-audit]: request=$r op=run client=standin status=queued reason=-"; fi
  rm -f "$f"; done; done
```

The driver (each block is evaluated as text in one shell, as pastes into one login are):

```bash
# Each block is evaluated as text in ONE shell, as pastes into one login are. STAND-INS: no sudo (root), the broker is /usr/local/bin/standin-broker.
P() { echo "===== $1"; }
P "the hidden prompt (the word typed is 'standin', 7 characters)"; eval "$(cat /tmp/s11-prompt)" <<< "standin"
P "check a, state 1: the switch's directory does not exist, so touch fails"; eval "$(cat /tmp/s11-a)"
echo "requests directory exists: $([ -d /var/lib/hermes/spool/apps/ads-audit/requests ] && echo yes || echo no) | switch: $([ -e /var/lib/hermes/app-state/ads-audit/DISABLED ] && echo present || echo absent)"
mkdir -p /var/lib/hermes/app-state/ads-audit /var/lib/hermes/spool/apps/ads-audit/requests
chattr +i /var/lib/hermes/app-state/ads-audit 2>/dev/null && { P "check a, state 2: the directory exists but cannot be written (immutable), so touch fails"; eval "$(cat /tmp/s11-a)"; echo "requests waiting: $(ls /var/lib/hermes/spool/apps/ads-audit/requests | wc -l)"; chattr -i /var/lib/hermes/app-state/ads-audit; } || echo "(chattr not available: state 2 not run)"
P "check a, state 3: the switch can be set, the stand-in broker is STOPPED (no answer)"; eval "$(cat /tmp/s11-a)"
echo "requests waiting: $(ls /var/lib/hermes/spool/apps/ads-audit/requests | wc -l) | switch: $([ -e /var/lib/hermes/app-state/ads-audit/DISABLED ] && echo present || echo absent)"
rm -f /var/lib/hermes/app-state/ads-audit/DISABLED; systemctl start hermes-app-broker@ads-audit; sleep 1; echo "(switch removed by hand; stand-in broker: $(systemctl is-active hermes-app-broker@ads-audit))"
P "check a, state 4: the stand-in broker running"; eval "$(cat /tmp/s11-a)"
P "check a, pasted again"; eval "$(cat /tmp/s11-a)"
P "check b (no ledger and no /opt/hermes-agent in the stand-in: the counter cannot be read)"; eval "$(cat /tmp/s11-b)"
P "check c"; eval "$(cat /tmp/s11-c)"
P "afterwards"; eval "$(cat /tmp/s11-after)"; echo "C after the block: [${C-unset}]"
```

```
===== the hidden prompt (the word typed is 'standin', 7 characters)

length 7
===== check a, state 1: the switch's directory does not exist, so touch fails
touch: cannot touch '/var/lib/hermes/app-state/ads-audit/DISABLED': No such file or directory
a: STOPPED, the switch is not set | nothing was placed
requests directory exists: no | switch: absent
===== check a, state 2: the directory exists but cannot be written (immutable), so touch fails
touch: cannot touch '/var/lib/hermes/app-state/ads-audit/DISABLED': Operation not permitted
a: STOPPED, the switch is not set | nothing was placed
requests waiting: 0
===== check a, state 3: the switch can be set, the stand-in broker is STOPPED (no answer)
a: UNEXPECTED [] | test request deleted | switch LEFT ON: stop
requests waiting: 0 | switch: present
(switch removed by hand; stand-in broker: active)
===== check a, state 4: the stand-in broker running
a: status=refused reason=disabled | switch off again: yes
===== check a, pasted again
a: status=refused reason=disabled | switch off again: yes
===== check b (no ledger and no /opt/hermes-agent in the stand-in: the counter cannot be read)
Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'app_lib'
HELD_RUNS=
b: SKIPPED, nothing was placed
===== check c
c: status=refused reason=bad_request
===== afterwards
      1 status=refused reason=bad_request
      2 status=refused reason=disabled
switch present: no | requests waiting: 0
C after the block: [unset]
```

- **Check a, the guard.** With the switch's directory missing, and with it present but unwritable, `touch` fails and
  the block prints `a: STOPPED, the switch is not set | nothing was placed`; no request file was written (in state 1
  the requests directory did not even exist; in state 2 it held 0 files). With the switch settable and no broker:
  `a: UNEXPECTED [] | test request deleted | switch LEFT ON: stop`, 0 requests waiting, the switch present. With the
  stand-in broker: the expected line, twice.
- **The inner lines are the handoff's.** `diff` of lines 2 to 4 of the handoff's block against lines 3 to 5 of the
  runbook's: no output, exit status 0; `cmp`: identical, 764 bytes.
- **Check b** printed `HELD_RUNS=` and `b: SKIPPED, nothing was placed` after a Python error: the stand-in has no
  `app_lib` and no ledger, so only the "counter not read" path ran. Its placing branch was not run.
- **Check c** and **afterwards** printed their expected forms (two `disabled` lines because check a ran twice; no
  `quota` line because check b placed nothing). The client variable is unset afterwards.
- Not produced: an admitted request (`status=queued reason=-`) in check a or b. The stand-in would write that line
  with the switch off, but the guarded block never places a request then.

#### `kc` again (zsh, private agent, throwaway key; the same five runs)

```
lines of the block that set K: 1
===== run 1: the block, K set to the throwaway key
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 0
===== run 2: pasted again
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 0
===== run 3: the throwaway key put in the agent first
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
STOPPED: the key is in the agent already (a work session): run this again after 'ssh-add -d ~/.ssh/vps-hermes'
throwaway key still in the agent: 1
===== run 4: no public file
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
STOPPED: could not read the key's public file
===== run 5: a stand-in ssh-add whose keychain load supplies the throwaway key
UseKeychain lines left in the file: 0
ssh on the new alias: 1; ssh on the old alias: 0
keychain load rc=0
supplied by the keychain: 1 -- the passphrase is in the keychain again; still in the agent: 0 (0 expected); stop and report
throwaway key in the agent afterwards: 0
function kc left defined: no
private agent stopped
```

Run 5 (the stand-in keychain load) now ends `still in the agent: 0 (0 expected)`: the count is taken after the
removal instead of being asserted.

#### How the runbook's rendering was checked

Step 11's fences are at column 0, which ends the numbered item, so its paragraphs after the first fence now have
no indent (indented by four they rendered as code). Checked two ways: by count (in step 11, 5 fenced blocks and 0
lines indented by four or more outside the fences after the first fence), and by rendering the three edited
sections with `marked` 12.0.2 (`npx`): step 11 with its neighbours 5 `<pre>` for 5 fences, the journal section 6
for 6, "A security review" 1 for 1.

#### Second round after review (2026-10-11 UTC): VPS 1 after the step, VPS 4's extra line, cut pastes of check a

One block changed: VPS 4 now prints `directory still there: another file is in it` when the settings directory was
not empty (its `rmdir` error stays hidden). The other eleven blocks are as in the round before (compared by
script). All ran in `jr` as before (`sudo ` removed). Stand-ins: for the cut pastes, the switch and spool directories
were made by hand, no broker ran and the client was the letter `x`; they were removed afterwards. The two refusal
lines VPS 1 now prints in `jr` are the stand-in broker's lines of the round before, still in its journal (shell
line-number prefixes of two error lines are cut).

```
===== vps1 (as jr stands: our file installed, the service restarted after it)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
sshd release: sh: 1: sshd: not found
sshd listeners: 0 | words starting -f or -o: 0
docker logging: 
      1 status=refused reason=bad_request
      2 status=refused reason=disabled
Sun Oct 11 01:58:11 UTC 2026
===== vps4 (undo; the directory is empty)
journal service: active | our file still there: no
===== vps2 (install again)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== (another file, other.conf, put in the directory)
===== vps4 (undo; another file is in the directory)
journal service: active | our file still there: no
directory still there: another file is in it
===== (the other file and the directory removed by hand)
===== vps2 (install)
# /etc/systemd/journald.conf
MaxRetentionSec=7day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
files in the directory: 1
===== vps3 (apply (no stand-in unit this round))
journal service: active | started: Sun 2026-10-11 01:58:22 UTC | journal on disk: yes
oldest entry before: 2026-10-10T17:43:26+00:00 | after: 2026-10-10T17:43:26+00:00 | same: yes
hermes-broker: inactive
hermes-docker-proxy: inactive
hermes-app-broker@ads-audit: inactive
Failed to start hermes-listener-check.service: Unit hermes-listener-check.service not found.
listener_check_rc=5
Sun Oct 11 01:58:27 UTC 2026
===== vps1 (after the step, once more)
# /etc/systemd/journald.conf
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=7day
MaxFileSec=1day
# /etc/systemd/journald.conf.d/50-hermes-retention.conf
MaxRetentionSec=35day
SystemMaxFiles=500
# /usr/lib/systemd/journald.conf.d/syslog.conf
oldest entry: 2026-10-10T17:43:26+00:00
journal files: 1 | disk used: 2%
journal on disk: yes
settings paths that are links: 0
sshd release: sh: 1: sshd: not found
sshd listeners: 0 | words starting -f or -o: 0
docker logging: 
      1 status=refused reason=bad_request
      2 status=refused reason=disabled
Sun Oct 11 01:58:27 UTC 2026
===== check a, cut pastes (no broker; the switch and spool directories made by hand; 'x' as the client)
--- the last line lost (piped, so bash reports the end of input where a terminal shows a > prompt)
syntax error: unexpected end of file
switch: ON | requests waiting: 0
--- the first two lines lost
syntax error near unexpected token `else'
`else echo "a: STOPPED, the switch is not set | nothing was placed"; fi'
a: UNEXPECTED [] | test request deleted | switch LEFT ON: stop
switch: off | requests waiting: 0
```

- **VPS 1 after the step** (never run in that state before): between the server's own lines and the distribution's
  `syslog.conf` line it prints `# /etc/systemd/journald.conf.d/50-hermes-retention.conf`, `MaxRetentionSec=35day`,
  `SystemMaxFiles=500`. The runbook's "Reading it later" said VPS 1 does not show our file's lines: that was wrong
  and is corrected to this order; VPS 1's stop rule now says that our file is the expected third file after the
  step and a fourth is the reason to stop.
- **VPS 4:** with an empty directory, the one expected line; with another file in the directory, the second line.
- **Check a, the last line lost:** piped, bash reports the end of input (at a terminal it waits at a `>` prompt and
  prints nothing); the switch is ON and no request was placed.
- **Check a, the first two lines lost:** the inner lines ran without the guard (here: no broker, so `a: UNEXPECTED []
  … switch LEFT ON`) and bash reports a syntax error at `else`; the switch was in fact OFF, so the printed text is
  not true, as the runbook now says. (At a terminal the error comes after that text; here the two streams arrived
  in the other order.)
- VPS 2 and VPS 3 were run again to leave `jr` with our file installed and the service restarted after it (VPS 3's
  listener lines are the `not found` ones: no stand-in unit this round).
- Rendering checked again as before: step 11 5 `<pre>` for 5 fences, the journal section 6 for 6.

### Pasted twice, and stopped half-way: what was checked

| Block | Pasted twice | A middle line fails |
|---|---|---|
| VPS 1 | Read-only. Run three times here. | Read-only: a failing part leaves its line empty or with the error; the stop rules cover every line. |
| VPS 2 | Run twice: `install` writes the same directory and file again. Pasted after VPS 3 it rewrites the file, so D2.4 reads `config_changed_after_start: true` until VPS 3 runs again (the runbook says so; by reading, not run through the collector here). | Run in `jr12`: the second `install` failed, the last line shows no file of ours and `0`; the runbook says stop. What is left is an empty directory (its time is newer than the service's start, so D2.4 would show `config_changed_after_start: true` until the next restart; VPS 3 or VPS 4 restarts). |
| VPS 3 | Run twice: a second restart; the oldest entry stayed the same; the start time is the second one, so the runbook says to give the first time. | If the restart fails the next line shows the state and `same:`; the runbook sends the operator to VPS 4. Changed from the brief: `same:` now reads `NO` when the first read printed nothing (two empty reads compared equal before). A restart that fails was not produced. |
| The flush line | `journalctl --flush` again is harmless (run after a healthy flush and after a relinquish). | Its second part only reads. |
| VPS 4 | Run twice, once with nothing installed, and once with another file in the directory (it then says the directory is still there). | Changed from the brief, which had `rm … && restart`: had the restart been interrupted after the file was removed, a second paste would have stopped at `rm` (no such file) and never restarted, leaving the service running on settings whose file is gone. The block now uses `rm -f` and always restarts, and prints whether the file is gone. |
| The trial line | Read-only for what a review looks at (the collector's own note on its two probes stands). | The collector stopping is shown by `collector_rc` and the summary tool's own line (run in `jr`). |
| The take-out block (new) | Run twice, and with another file present: the second time and the non-empty directory each give a harmless `rmdir` error. | Its last part only reads and says what is left. |
| `kc` | Run twice. | Each part prints its own line; the two `STOPPED` paths return before the keychain is asked. |
| Step 11's five blocks | Check a run twice against the stand-in broker. Read for b and c: a second paste places one more test request that is refused, and one more journal line. | Check a as the handoff had it: if the first line (`sudo touch …`) failed, the second still placed a `run` request with the switch off. Changed after review (the controller's decision): the block now places the request only when it has seen the switch, and says `a: STOPPED …` otherwise (run in two failing states). A paste that misses the block's first two lines is not protected; the runbook says to paste it whole. |

### What could not be rehearsed

- **Step 11's five blocks against the real broker** (the hidden prompt, live checks a, b, c, afterwards): the
  broker, its spool and its ledger exist on the box only; "After the review" ran them against a stand-in. Four are
  the blocks that ran on the box on 2026-10-09, byte for byte from the appendix of
  `docs/superpowers/handoffs/2026-10-09-review-9-pass.md` (compared by script); check a is that block's lines 2 to 4,
  unchanged, inside one added guard.
- **VPS 1:** `docker info` and the broker's refusal counts (neither exists in the stand-ins). The operator read the
  logging driver on the box on 2026-10-10 (`json-file`, section 2).
- **VPS 3:** the three Hermes services and the real listener check (a stand-in unit of its name was used); and the restart of the box's own journal service
  with its real load (section 4).
- **The server's real sshd:** the stand-in's sshd is the same release and package revision, started the same way
  (through `ssh.socket`); the box's own process list was read by the operator on 2026-10-11 (section 2).
- **A successful real collection through the summary tool:** the stand-in cannot observe most items.
- **`kc` with the real administrative key and a keychain that holds its passphrase:** run 5 is a stand-in.
- **A journal service that does not come back after the restart**, and VPS 4 after such a failure.

In the runbook, the lines of VPS 1 and VPS 3 that the stand-in could not run, and the trial line, are marked "first
run on the box", each with what to do when the output differs (stop and report); step 11 says that its blocks could
not be rehearsed off the box.
