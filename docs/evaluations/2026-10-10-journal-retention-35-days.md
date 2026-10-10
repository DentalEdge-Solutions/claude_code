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

## 3 · The rehearsal

The image is `ubuntu:24.04` with `systemd`, `systemd-sysv`, `python3`, `bsdutils`; its `/etc/systemd/journald.conf`
is `Storage=persistent`, `SystemMaxUse=1G`, `MaxRetentionSec=7day`, `MaxFileSec=1day` (the box's values), and a unit
`ticker.service` echoes a line every second (a stand-in for a long-running service). Containers were started with
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

**Run 1, as found (healthy).** (This run predates `Storage`, `service.active`, `newest_entry_on_disk` and
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
probe's own lines, the two other settings left out):

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
lines):

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

The fixed probe (re-run the same way in `jr4`; the probe's own lines):

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
second. The checklist's limit is 600: a journal that left the disk less than ten minutes before the collection
still passes that rule, which the checklist says.

## 3b · The key reader's two cases

Measured 2026-10-10 on the laptop (macOS, shell zsh; Docker 29, linux/aarch64 container, `ubuntu:24.04`), against a
throwaway `sshd` on 127.0.0.1 port 2222, with five throwaway ed25519 keys (no key body is kept here): four in the
server's `authorized_keys` (`a` to `d`) and a fifth, `x`, that is NOT in the file. Server version line:
`OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`; the box's release is 9.6p1 as the plan states, confirmed on the box on
2026-10-08 (not re-checked here).

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
  that faulty run, showed the key of `d` accepted. The options were then written out literally, as in the plan, and
  the result above is from that run. The four lines in the file were never changed.
- After that final run, a separate check: with the account `u` locked (`!` password, as it was made) `d` was accepted;
  with the password set to `*`, all five lines gave the results above. (An earlier `usermod -p '*'` and a restart of
  `sshd` were made while looking for the fault, before the final run; the account is unlocked in the final run.)
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
- A `/var` the journal service could not open, or a flush that failed: R13 produced the state with
  `journalctl --relinquish-var` only.
- What `systemd-analyze cat-config` prints for a settings directory linked to an absolute path or to a place
  outside `/etc/systemd` (R12 measured a relative link beside it).
- `d2_4` on the box itself: R7 is the container. The start-time command and its `us+utc` form are measured on
  systemd 255 only.
- `hermes-broker` and `hermes-docker-proxy` logging after the restart (only the audit broker has a safe trigger);
  the rehearsal's long-running stand-in is the `ticker` unit.
