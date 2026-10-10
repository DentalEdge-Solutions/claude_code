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

### A configuration keyword in double quotes

Measured 2026-10-10 in a throwaway `ubuntu:24.04` container (`openssh-server`, `OpenSSH_9.6p1`), a user `u` made,
`sshd -T` run with and without `-C user=u,host=h,addr=127.0.0.1`. File `q.conf` has the keywords in double quotes
(`"Port" 2200`, `"Match" User u`, then `  X11Forwarding yes`); file `c.conf` is the same without the quotes
(control). A third file held `"Include" /tmp/inc.conf`, and `inc.conf` held `Port 2300`.

```
OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
== q
syntax rc: 0
port 2200
x11forwarding no
--- as user u:
x11forwarding yes
== c
syntax rc: 0
port 2200
x11forwarding no
--- as user u:
x11forwarding yes
(third run, the quoted Include)  port 2300
```

What it shows: `sshd` 9.6p1 reads a keyword
written in double quotes exactly as it reads it bare, `"Match"` opens a block and `"Include"` brings the file in, so
the D1.7 line reader counts such a line.

## 4 · What is not measured

- 35 real days of journal: the rehearsal shows the setting in force and the deletion mechanism at 3 minutes, not a
  35-day run.
- The box's own restart of the journal service (Task 13 is the first).
- `hermes-broker` and `hermes-docker-proxy` logging after the restart (only the audit broker has a safe trigger);
  the rehearsal's long-running stand-in is the `ticker` unit.
