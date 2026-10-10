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
| `man/journald.conf.xml` | primary | The settings, their defaults and units: `MaxRetentionSec=` defaults to 0 (off) and takes `day`; `SystemMaxFiles=` defaults to 100; drop-in directories under `/etc/systemd`, `/run/systemd`, `/usr/lib/systemd`. | 2026-10-09 |
| `man/systemd-analyze.xml` | primary | `cat-config` copies a config file and its drop-ins to standard output "using the usual systemd set of directories and rules for precedence". | 2026-10-10 |
| `man/journalctl.xml` | primary | `--lines=`: with a `+` prefix "the oldest journal events are used instead". `--output-fields=`: for the json mode, `__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP` and `_BOOT_ID` are always printed. (R5 measured that `__SEQNUM` and `__SEQNUM_ID` are printed too.) | 2026-10-10 |
| `src/libsystemd/sd-journal/journal-vacuum.c` | primary | An archived file is deleted when the time in its name is older than the retention; the file and size limits are counted in one directory. | 2026-10-10 |
| `src/shared/pretty-print.c` | primary | `cat-config` prints a `# <path>` header, with an empty line before every file but the first. | 2026-10-10 |
| `src/basic/time-util.c` | primary | The time units (`day`, `min`). | 2026-10-10 |
| The rehearsal (section 3) | measurement | R1 to R6. | 2026-10-10 |

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

Not yet run when this record was written; its output is added here when the operator has run it.

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
- The `whole` timestamp (1791654206417845 microseconds, 2026-10-10T17:43:26 UTC) is the same instant as the FIRST
  line of the plain journal (the brief said "last line"; the command prints the first, and `-n +1` is the oldest).
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

## 4 · What is not measured

- 35 real days of journal: the rehearsal shows the setting in force and the deletion mechanism at 3 minutes, not a
  35-day run.
- The box's own restart of the journal service (Task 13 is the first).
- `hermes-broker` and `hermes-docker-proxy` logging after the restart (only the audit broker has a safe trigger);
  the rehearsal's long-running stand-in is the `ticker` unit.
