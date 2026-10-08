# Evaluation — the limited SSH key for the dashboard tunnel, and replacing the dashboard password

> **Date:** 2026-10-07 (measured 2026-10-08) · **Asked:** can a second SSH key on the box be limited to carry one
> local port-forward to `127.0.0.1:9119` and do nothing else? · **Method:** the candidate `authorized_keys`
> option string was run against a throwaway OpenSSH server in Docker on the laptop, with a fixed set of tests and
> a control key. Nothing on the box was touched. This document has three sections: section 1 is this measurement
> (1.7 and appendix 1.B were added when the runbook blocks were rehearsed as written); section 2 (step 7e, rehearsed)
> is the rehearsal of the dashboard password replacement, measured 2026-10-08 (2.8 and appendix 2.B added at the same
> time); section 3 holds the two rehearsals of the same round that belong to neither: the `awk` that edits the laptop's
> SSH config, and the `Match` count of the security review. A second fix round, after a review of the runbook, added 1.8
> and appendix 1.C (step 7f's sequence redesigned and rehearsed block by block), 2.9 and 3.3; where an earlier subsection
> describes a block that 1.8 replaces, a sentence there says so. A final edit (2026-10-08) added the read-only look at the
> box to 1.1, subsection 1.10 and appendix 1.D, and dated notes ("Confirmed 2026-10-08", "Note 2026-10-08") after the
> sentences they bring up to date; no earlier measurement was rewritten.

## 1 · The limited key, measured against a throwaway server

### 1.1 Sources, authority and what each verified (accessed 2026-10-07)

| Source | Authority | Verified there |
|---|---|---|
| Local `man sshd`, section "AUTHORIZED_KEYS FILE FORMAT" (laptop OpenSSH 10.3p1) | primary | `restrict` disables port, agent and X11 forwarding, PTY allocation and `~/.ssh/rc`; its list does not include command execution, so a `command=` is needed to stop commands. `port-forwarding` re-enables forwarding in both directions ("Enable port forwarding previously disabled by the `restrict` option"). `permitopen="host:port"` limits `-L`; `permitlisten="[host:]port"` limits `-R`. `permitlisten` has no "none" form, so a port that cannot be bound stands in for it. |
| Local `man ssh-add` (`--apple-use-keychain`) | primary | With `-d`, `--apple-use-keychain` removes the passphrase from the keychain as well. |
| Image source `hermes_cli/dashboard_auth/routes.py` (section 2.1) | primary | The password-login throttle: 10 attempts per 60 s per client IP, in memory. |
| The box's OpenSSH version | **not yet known** | The operator was asked and has not answered. Until then the rehearsal used `ubuntu:24.04`, which ships the version in 1.2. **The box's version is still to be confirmed against it.** **Confirmed 2026-10-08:** the box prints `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`, the release the rehearsals used (the table "The read-only look at the box" below). |
| This rehearsal (1.2 to 1.6, appendix 1.A) | measurement | The results below. |
| Local `man ssh-add` and `man ssh-agent` (laptop OpenSSH 10.3p1; accessed 2026-10-08, for 1.8) | primary | `--apple-load-keychain`: "Add identities to the agent using any passphrase stored in the user's keychain." `ssh-agent` creates its socket under `$HOME/.ssh/agent` unless `-T` puts it in the temporary directory. |
| The rehearsals of 1.8 (appendix 1.C) | measurement | Step 7f's sequence as it stands in the runbook after the review. |
| The read-only look at the box, by the operator (2026-10-08) | measurement on the box itself | The table below. Values only were reported; no hostname and no address is recorded anywhere. |
| The rehearsals of 1.10 (appendix 1.D), 2026-10-08 | measurement | The `VPS look` and `VPS root key` blocks on a stand-in server; the keychain lines of LAPTOP 5c and 6b on this Mac's login keychain with a throwaway key. |

**The read-only look at the box (2026-10-08).** Added in the final edit. The operator ran the read-only blocks on the
box and reported what they printed. Nothing was changed there.

| Read on the box | Value |
|---|---|
| `ssh -V` | `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19` (the release of 1.2) |
| `sshd -T`, the eight settings the `VPS look` block of BRING-UP step 7f filters | `gatewayports no`, `allowtcpforwarding yes`, `allowstreamlocalforwarding yes`, `trustedusercakeys none`, `authorizedprincipalsfile none`, `authorizedkeyscommand none`, `authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`, `permittunnel no` |
| Key files, by account (the second half of the same block) | `root authorized_keys`: 1 line, 1 `ssh-ed25519`, 0 lines with options. `hermesops authorized_keys`: 1 line, 1 `ssh-ed25519`, 0 lines with options. No other account has one. |
| `/proc/sys/net/ipv4/ip_unprivileged_port_start` | `1024` |
| `systemctl show docker -p ActiveEnterTimestamp --value` | a line of the form `Mon 2026-09-21 16:49:31 UTC` |

What the look does not show: the box's `Match` blocks (the `Match` count of 3.2 has not been run there), its fail2ban
jail, and everything that needs a login with the new key (LAPTOP 3a and 3b).

### 1.2 The throwaway server

`docker build` of `ubuntu:24.04` plus `openssh-server`, `python3` and (second run only) `iproute2`; account
`hermesops` (unprivileged, bash); `PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
`PermitRootLogin no`, `LogLevel VERBOSE`; three listeners as that account: HTTP on 9119 (the permitted target),
HTTP on 9120 (a forbidden target), and a unix socket at `/tmp/t.sock` that answers `UNIX-REACHED` once. Published
on `127.0.0.1:2222` only. The full recipe is in the appendix (1.A).

Measured version line: `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19, OpenSSL 3.0.13 30 Jan 2024`

Key file, as used (test keys, bodies not kept):

```
<admin key line, no options>
restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false" ssh-ed25519 <test key>
```

Every client call used `-F none`, `IdentityAgent=none`, `IdentitiesOnly=yes`, `BatchMode=yes`, a scratch
known-hosts file and scratch keys, so none of the laptop's own keys, agent or config took part.

**Two runs, and what differed between them.** The measurement was made twice. The first run (2026-10-08, earlier)
used a container as first built, then a second container recreated with a sysctl; the keys, the image and the
known-hosts file were scratch ones, and the scratch known-hosts file was removed before the second container
because the new container has a new host key. The second run (fix round 1, same day) rebuilt the image with
`iproute2` added and fresh keys, and is the source of the values below unless a row says otherwise. Deviations
from the plan, all of them:

- `kill %1` became `kill $!` (a script has no job table).
- T5b in the first run was **bounded at 8 seconds** (`ssh` still running at 8 s) because an earlier unbounded
  attempt in the same container ran until the 120 s tool timeout: two separate attempts, not one.
- T7 as written in the plan, `sftp $SSHO ...`, was a defect: `$SSHO` holds `-p 2222`, and `sftp` takes its port
  with `-P`, so that command was a usage error that exits 1 whatever the key allows. The first run's "T7 `rc=1`"
  therefore **proved nothing** and is withdrawn; the sshd log of that run showed no sftp connection. T7 was
  re-measured with `-P` (1.5).

### 1.3 The tests with the limited key

Second run, in the container started with `--sysctl net.ipv4.ip_unprivileged_port_start=1024` (see 1.4 for why),
all values measured. The sshd log lines are the server's own words.

| Test | Expected | Measured | Match |
|---|---|---|---|
| T1 forward to 9119 | `200` | `200` | yes |
| T2 command `echo MARK` | `[]` and `rc=1` | `[] rc=1` (log: `Starting session: forced-command (key-option) '/bin/false'`) | yes |
| T3 terminal (`-tt`) | `PTY allocation request failed`, no prompt | `PTY allocation request failed on channel 0` | yes |
| T4 forward to 9120 | `000` | `000` (log: `request to connect to host 127.0.0.1 port 9120, but the request was denied`) | yes |
| T5a remote forward, port 29123 | `rc=255` | `rc=255` (log: `request to remote forward to host 127.0.0.1 port 29123, but the request was denied`) | yes |
| T5b remote forward, the permitted port 1 | `rc=255` | **plain container (ip_unprivileged_port_start 0): `rc=255` was NOT reached; the forward was established and a listener on `127.0.0.1:1` was observed (1.4).** Container with the sysctl at 1024: `rc=255`, log `bind [127.0.0.1]:1: Permission denied` | **DIFFERS in the plain container (the finding, see 1.4); matches only with the sysctl at 1024** |
| T6 forward to a unix socket | `[]` | `[]` (log: `request to connect to path /tmp/t.sock, but the request was denied`) | yes |
| T7 file transfer | refused | see 1.5; the plan's `sftp` command was a defect | see 1.5 |
| T8 (added) `-L` whose target is the NAME `localhost`, port 9119 | not planned | `000` (log: `request to connect to host localhost port 9119, but the request was denied`); admin key control: `200` | extra |

T8 is a finding about the option string: `permitopen="127.0.0.1:9119"` compares the text the client sends, so a
forward written with `localhost` instead of `127.0.0.1` is refused. The Desktop app's tunnel and the alias must
use `127.0.0.1:9119` literally (measured: refused with `localhost`).

### 1.4 T5b: what was observed in the plain container, and with the sysctl

Docker sets `net.ipv4.ip_unprivileged_port_start` to `0` inside a plain container (measured:
`net.ipv4.ip_unprivileged_port_start = 0`). Then:

- **Plain container, observed.** While `ssh -N -R 127.0.0.1:1:127.0.0.1:22` (limited key, `ExitOnForwardFailure=yes`)
  was running (still alive after 4 s), `docker exec ... ss -ltn` listed `LISTEN 0 128 127.0.0.1:1`, absent from
  the listing taken before; `/proc/net/tcp` held a LISTEN row `0100007F:0001` (state `0A`) owned by uid 1001, the
  `hermesops` account; after the `ssh` process was killed the listener was gone. sshd's log for that connection
  held only `Accepted publickey` and `User child is on pid ...` (no refusal line). A direct bind of
  `127.0.0.1:1` as `hermesops` printed `bound port 1 OK`.
- **Container with `--sysctl net.ipv4.ip_unprivileged_port_start=1024`, observed.** `ssh` exited `rc=255` at once
  (client: `Error: remote port forwarding failed for listen port 1`); `ss -ltn` and `/proc/net/tcp` held **no**
  row for port 1 during the attempt; sshd's log held `bind [127.0.0.1]:1: Permission denied` and
  `channel_setup_fwd_listener_tcpip: cannot listen to port: 1`; a direct bind as `hermesops` failed with
  `[Errno 13] Permission denied`.

So what stops port 1 is the **kernel setting**, not the key line: `permitlisten="127.0.0.1:1"` allowed the
forward, and the bind succeeded or failed according to `ip_unprivileged_port_start`. The earlier run's wording
("established", "harmless because the account cannot bind below 1024") is replaced: the establishment is now
observed directly (above), and the "cannot bind" part holds only where the setting is 1024 or higher.

**Reasoned, not measured:** if the box (or any container it runs this in) has the setting at `0`, the key could
open a loopback-only listener on its port 1, for another local process to connect to; that is a gap rather than
a path to a shell or a file. The box's value is **not measured**; the runbook should read it
(`cat /proc/sys/net/ipv4/ip_unprivileged_port_start`) and the checklist should expect `1024` or higher.
**Confirmed 2026-10-08:** read on the box by the operator: `1024` (1.1).

### 1.5 T7 re-measured: file transfer (the limited key and the control)

Port given as `-P 2222` for `sftp` and `scp`, with every other option unchanged. Each row's sshd log lines were
captured from `docker logs` for that connection only. Plain container (setting 0; irrelevant to transfers).

| Command | Key | Measured | Server log of that connection |
|---|---|---|---|
| `sftp` (`ls`) | limited | `Connection closed`, `rc=255` | `Accepted publickey ...`, `Starting session: forced-command (key-option) '/bin/false'` |
| `scp` file TO the server (default protocol, SFTP) | limited | `scp: Connection closed`, `rc=255`; **no file on the server** | same `forced-command ... '/bin/false'` line |
| `scp` file FROM the server (default) | limited | `scp: Connection closed`, `rc=255`; **no file on the laptop** | same |
| `scp -O` TO the server (legacy protocol) | limited | `lost connection`, `rc=1`; **no file on the server** | same |
| `scp -O` FROM the server (legacy) | limited | `rc=1`; **no file on the laptop** | same |
| `sftp` (`ls`) | admin (control) | listing printed, `rc=0` | `Starting session: subsystem 'sftp'` |
| `scp` TO / FROM (default) | admin (control) | both `rc=0`; file present on the other side each time | `Starting session: subsystem 'sftp'` |
| `scp -O` TO / FROM (legacy) | admin (control) | both `rc=0`; file present each time | `Starting session: command` |

So the limited key cannot transfer a file by SFTP, by `scp` over SFTP, or by legacy `scp`: in every case sshd
accepted the key and then ran the forced command `/bin/false` instead of the file-transfer program, and the
connection arrived (a log entry exists for each). The control shows the same commands work with the admin key,
so the refusals are the key's options and not a broken test. T7 now **matches** the expectation, for the right
reason.

### 1.6 The control and the box block's refusals

The control for T2, T4, T6 and T8 (admin key, no options, second run): `C-T2 [MARK] rc=0`, `C-T4 200`,
`C-T6 [UNIX-REACHED]`, `C-T8 200`; all as expected. (A first attempt of the control, typed into `zsh`, failed at
word-splitting with `rc=255` and was discarded; the rerun under `bash` is the one recorded.) The first run's
controls gave the same values.

The `tunnel_key_add` function from the box block, run as `hermesops` in the container; its exact text is in the
appendix. It was fed on standard input (`docker exec -i -u hermesops tunnel-rehearsal bash -s`, the function, then
one call followed by the line it reads), because there was no terminal for `-it`. First run, against the file
that already held the limited key (so a "right line" had to be a second, fresh test key):

| Call | Expected | Measured | Match |
|---|---|---|---|
| line cut after `ssh-ed25519` | `REFUSED`, file unchanged | `REFUSED: not the expected line -- nothing written`; 2 lines before, 2 after; no backup file made | yes |
| bare public key, no options | `REFUSED`, file unchanged | `REFUSED: not the expected line -- nothing written`; 2 lines before, 2 after | yes |
| right line, fresh key | `ADDED` | `ADDED: 3 key line(s), mode 600`; 3 lines; backup holds the 2 earlier lines | yes |
| the same line again | `already present` | `already present`; still 3 lines | yes |
| the first limited key's line (already in the file) | not planned | `already present`; still 3 lines | extra |

How the function decides, **measured in the second run** (each call on a copy of the file holding the admin line
only, so "already present" could not interfere; the two refusals have different messages, which tells the checks
apart):

| Line given | Measured |
|---|---|
| right options + `ssh-ed25519 AAAA...`, 3 words, 133 characters | `REFUSED: the line is cut or has extra words` (passes the pattern check, fails the length check) |
| same, 178 characters | same refusal |
| same, 179 characters | same refusal |
| same, 180 characters | `ADDED: 2 key line(s), mode 600` |
| the full line, 181 characters | `ADDED: 2 key line(s), mode 600` |
| the full line plus a fourth word (`extra`) | `REFUSED: the line is cut or has extra words`; file unchanged |
| the full line plus a comment word (`admin@x`) | same refusal; file unchanged |
| line cut after `ssh-ed25519` (first run) | `REFUSED: not the expected line`: the pattern check, not the length check |

So the floor of 180 is **measured**: 179 is refused and 180 is accepted. The right line is 181 characters, so
the floor leaves one character of room and is a second line of defence, not the main one. (The function described in
this subsection was replaced after the review of the runbook, because a body cut by one character passed that floor:
the function now in the runbook, and its rehearsal, are in 1.8.)

### 1.7 The runbook's own LAPTOP 2 and LAPTOP 3 blocks, run verbatim under zsh

Measured 2026-10-08, in the fix round that followed the first writing of BRING-UP step 7f. The rule of that round:
a block that enters the runbook has been run, as written, somewhere safe first. Sections 1.3 to 1.6 ran the tests as
a script under `bash` against `127.0.0.1:2222`; the operator pastes LAPTOP 2 and LAPTOP 3 into macOS's `zsh`, so this
subsection runs the blocks as they stand in the runbook, from a "laptop" container to a "server" container (how to
rebuild both: appendix 1.B).

**Set-up.**

- **Server** (`rehearsal-server`): the Dockerfile of appendix 1.A (Ubuntu 24.04, OpenSSH 9.6p1 as in 1.2), started with
  `--sysctl net.ipv4.ip_unprivileged_port_start=1024` (measured inside: `1024`), on a Docker network of its own; an HTTP
  listener on `127.0.0.1:9119`; and, so that T6 cannot pass for want of a socket, a root-run unix listener at
  `/run/dbus/system_bus_socket` (mode 666, answers `UNIX-REACHED` and a line break to any connection). Its
  `authorized_keys` held one line, the throwaway administrative key.
- **Laptop** (`rehearsal-laptop`): `ubuntu:24.04` with `openssh-client` (`OpenSSH_9.6p1`), `zsh` (5.9), `curl` (8.5.0),
  `netcat-openbsd`; a non-root user `laptop` whose shell is zsh; `~/.ssh/config` held only
  `Host hermes-box` (`HostName` the server container's name on the network, `User hermesops`,
  `IdentityFile ~/.ssh/vps-hermes`, `AddKeysToAgent yes`; `UseKeychain` left out, which Linux `ssh` rejects); a throwaway
  administrative key at `~/.ssh/vps-hermes`. The host key was accepted once beforehand by a login with the
  administrative key (`StrictHostKeyChecking=accept-new`); both aliases use the same `HostName`, so the one entry in
  `known_hosts` covers both.
- **`pbcopy`** does not exist on Linux: LAPTOP 1 ran verbatim with a stand-in `pbcopy` (a two-line script that writes
  its input to `~/clipboard`). Its result: `KEY MADE, line on the clipboard`, and the stand-in held a line of 181
  characters (182 bytes with the line break) with two spaces in it, the length that `tunnel_key_add` of appendix 1.A
  expects. (LAPTOP 1 was since split into LAPTOP 1 and LAPTOP 1b, and LAPTOP 1b was run with the real `pbcopy`: 1.8.)
- **VPS 0 and VPS 1** ran verbatim as `hermesops` in the server container: `docker exec -u hermesops rehearsal-server
  bash -c "<the block>"`, and for VPS 1 the pasted line was fed on standard input (`docker exec -i ... < clipboard line`),
  as `read` would get it from a terminal; `read -p` prints no prompt when its input is not a terminal.
- **How the blocks were fed.** LAPTOP 2 and LAPTOP 3 were fed to an **interactive `zsh -i`** running on a pseudo-terminal
  (`script -qec "stty cols 600; zsh -i" /dev/null`, run through `docker exec -i -u laptop` with the block on standard
  input, followed by an `exit` line). Why `zsh -i` on a pseudo-terminal, not `zsh -c`: the block uses job control
  (`&`, `kill %1`, `$!`, `wait`) and an interactive zsh keeps a job table and prints the job notices an operator will
  see; the pseudo-terminal, not a pipe, is what makes `ssh` behave as it does when it is pasted into a terminal. The
  lines were typed in one after the other (no bracketed-paste markers). The transcript's zsh prompt padding and escape
  codes are removed in the tables below; nothing else is.

**LAPTOP 2.** The block, verbatim:

| Run | Expected | Measured | Match |
|---|---|---|---|
| First (config held `Host hermes-box` only) | `3` | `3`; `~/.ssh/config` then held the `hermes-box-tunnel` block with the server container's name as `HostName`, the address copied from the existing alias | yes |
| Second (same block again) | `alias exists`, then `3` | `alias exists`, `3`; the config unchanged | yes |

Measured on that configuration only. **Reasoned, not measured:** the `3` counts the `identityfile .../hermes-box-tunnel`,
`identitiesonly yes` and `identityagent none` lines that `ssh -G` prints; a `Host *` block on the real laptop that sets
`IdentityAgent` or `IdentitiesOnly`, or that adds `IdentityFile` lines ending in `/hermes-box-tunnel`, would change the
count, because options from the first matching setting win and an earlier `Host *` block could set them before the alias does.
The runbook says what to do when the number is not `3`.

**LAPTOP 3, first run: the block as the runbook then had it (T2 written `ssh -o BatchMode=yes hermes-box-tunnel
'echo MARK'`). It MISBEHAVED.** T1 printed `200` and T2 printed `T2 command -> [] rc=1`, and then **nothing more ran**:
T4 to T7 never printed, and zsh was still at its prompt 40 seconds later (stopped by hand). What happened: `ssh`
without `-n` reads its standard input, here the terminal, and with the forced command `/bin/false` it sent the lines
pasted after T2, and the final `exit`, to the command, which discarded them. The raw transcript is kept. **Correction:**
`ssh -n -o BatchMode=yes hermes-box-tunnel 'echo MARK'` (`-n` redirects `ssh`'s input from `/dev/null`). Whether the
operator's own terminal, which normally pastes with bracketed-paste markers and hands zsh the whole paste as one
command, would hit this was not measured; the fix is harmless either way, and the line with `-n` is the one that was
rehearsed next and is in the runbook.

**LAPTOP 3, second run, with `-n` in T2, limited key** (the block exactly as in the runbook at that time, typed into
`zsh -i`; this block was replaced after the review of the runbook by LAPTOP 3a and LAPTOP 3b, rehearsed in 1.8):

| Test | Expected | Measured | Match |
|---|---|---|---|
| T1 forward to the dashboard | `200` here (the stand-in page; `302` on the real dashboard) | `T1 forward to the dashboard -> 200` | yes |
| T2 command | `[] rc=1` | `T2 command -> [] rc=1` | yes |
| T4 forward to another port | `0 bytes` | `T4 forward to another port -> 0 bytes` | yes |
| T5a remote forward, another port | `refused` | `T5a remote forward, another port -> refused` (zsh: `[1]  + exit 255 ssh ...`) | yes |
| T5b remote forward, port 1 | `refused` | `T5b remote forward, port 1 -> refused` (zsh: `[1]  + exit 255 ssh ...`) | yes |
| T6 unix socket | `0 bytes` | `T6 unix socket -> 0 bytes` | yes |
| T7 file copy | `rc=255` | `T7 file copy -> rc=255`; no file in the server's `/tmp` afterwards | yes |

zsh's own notices were printed between the results and are **not results**: `[1] 203` (a background `ssh` started),
`[1]  + done ssh -o BatchMode=yes ... ` (a background `ssh` ended after `kill %1`), and `[1]  + exit 255 ssh ...`
(T5a and T5b: the background `ssh` had already exited with 255 when `kill -0` ran). The runbook's "Expected" text tells
the operator so. The server's log for the run held, for the refused requests, the same words as in 1.3 (a denied remote
forward to 29123, a denied connect to port 22, a denied connect to `/run/dbus/system_bus_socket`, `bind [127.0.0.1]:1:
Permission denied`), and five `Starting session: forced-command (key-option) '/bin/false'` lines in all, counted
over both runs of LAPTOP 3 together (they were not attributed one by one to a test).

**The control: the same LAPTOP 3 lines with the alias argument replaced by `hermes-box` (the administrative key).**
Done with `sed -E 's/hermes-box-tunnel([ :])/hermes-box\1/g'`, which leaves the `~/.ssh/hermes-box-tunnel.pub` file
name of T7 alone.

| Test | Expected with the administrative key | Measured | Match |
|---|---|---|---|
| T1 | `200` | `200` | yes |
| T2 | `MARK`, `rc=0` | `T2 command -> [MARK] rc=0` | yes |
| T4 | more than 0 bytes | `20 bytes` (the banner of the server's `sshd`, cut at 20) | yes |
| T5a | `OPENED` | `OPENED (stop: this must be refused)` | yes |
| T5b | still refused (the sysctl stops it) | `refused` | yes |
| T6 | more than 0 bytes | `13 bytes` | yes |
| T7 | `rc=0` | `rc=0`; the file arrived (removed afterwards) | yes |

So each test can tell "allowed" from "refused": with the administrative key T2, T4, T5a, T6 and T7 all went through, and
T5b stays refused with it because the kernel setting stops the bind, which is T5b's point (1.4).

**Other statements the runbook makes, and what supports them.**

- *After VPS 1: `ADDED: 2 key line(s), mode 600`.* Measured here with an `authorized_keys` of exactly one key before
  (`ADDED: 2 key line(s), mode 600`; running the block again with the same line: `already present`). The 2 therefore
  assumes the file held exactly one key; on the box that is what the read-only look of the first trial collection showed.
  Another count is not an error by itself, but it must equal what that look showed plus one. The runbook says so.
  **Note 2026-10-08:** no trial collection had been made when that sentence was written. The look was made on
  2026-10-08 with the `VPS look` block (1.10): `lines=1` for `hermesops`, so the expected count is 2.
- *LAPTOP 4 on a second run, or with the login item not loaded.* `launchctl bootout` prints an error when the login item
  is not loaded, and (read from the commands) `launchctl bootstrap` prints one when it already is; the runbook says that
  such a message is not a failure by itself. **LAPTOP 4 was NOT rehearsed**: it edits and reloads the real login item of
  this laptop. (LAPTOP 4 was replaced by LAPTOP 4a, 4b and 4c; what of them was run, and how, is in 1.8.)

**What this subsection does NOT show.**

- macOS's own `nc`, `curl` and `ssh` (the stand-in had netcat-openbsd, curl 8.5.0 and OpenSSH 9.6p1 on Linux; the
  laptop that ran the rehearsal has OpenSSH 10.3p1, section 1.1).
- `pbcopy` (a stand-in script was used) and the macOS clipboard.
- LAPTOP 4 (`plutil`, `launchctl`): not run.
- LAPTOP 5's `ssh-add --apple-use-keychain -d` and the keychain: not run; only its `awk` program was (3.1).
- LAPTOP 6 (the one attempt with the administrative key, from a new terminal window): not run.
- Whether the operator's terminal swallows pasted lines in T2 without the fix (the fix is in; the behaviour without it
  was seen on a pseudo-terminal fed line by line).
- The box itself: its OpenSSH version, its `sshd_config`, its kernel setting and the dashboard's `302`.
  **Note 2026-10-08:** the version, eight global `sshd -T` settings and the kernel setting are now measured (1.1); the
  `Match` blocks, the dashboard's `302` through the new key and the box's fail2ban jail are not.
- VPS 0 and VPS 1 on the box (they ran as `hermesops` in a container on this laptop).

### 1.8 Step 7f's sequence after the review of the runbook

Measured 2026-10-08, in the second fix round. A review of the runbook as committed found that step 7f's laptop sequence
was not safe to hand to the operator. This subsection records what the review found, the sequence that replaced it, and
every rehearsal of the round. The drafts of the new blocks came from the controller, written from the findings and never
run; each was rehearsed, and where a draft misbehaved or a defect was seen it was corrected and the corrected text
rehearsed. Both are recorded. How to rebuild the set-up: appendix 1.C.

**What the review found (its own measurements, not repeated here unless a row below says so).**

- *Seven logins in one paste.* The old LAPTOP 3, pasted as one bracketed paste into macOS zsh with `ssh` and `scp`
  replaced by stand-ins that print "Permission denied" and end with 255, made 7 calls in 27 seconds and printed
  `T1 -> 000`, `T2 -> [] rc=255`, then `T4 -> 0 bytes`, `T5a -> refused`, `T5b -> refused`, `T6 -> 0 bytes`,
  `T7 -> rc=255`: the last five are exactly the expected lines. The text's "every one of these logs in successfully" was
  the thing under test, not a fact. A key line whose body was cut by one character was accepted by `tunnel_key_add`
  (`ADDED: 2 key line(s)`), and the clipboard order made a refusal the likely first outcome: copying the VPS 1 block
  replaces the key line that LAPTOP 1 put on the clipboard.
- *The login item switched or not, the same output.* `plutil -replace ProgramArguments.9` INSERTED on this macOS (a scratch
  plist with the README's ten arguments: the count went 10 to 11). With one extra `-o` pair in the file the old guard
  failed silently, nothing was replaced, the reload ran regardless, and the block still printed `state = running` and
  `-> 302`.
- *The keychain emptied before the passphrase was proven.* LAPTOP 5 removed the passphrase from the keychain before the
  operator had typed it anywhere, and `ssh-add -l | grep -c vps-hermes` could not fail: `ssh-add -l` prints a key's
  comment, not its file name (`0` while the key was loaded, `0` after its removal).
- *The config edit.* A second run overwrote the backup with the edited file; under zsh's `noclobber` the redirect failed
  and the next line still removed the key; the `awk` missed `HOST` and `MATCH` in capitals and kept `UseKeychain=yes`.
- LAPTOP 2's stop text told the operator to read `ssh -G hermes-box-tunnel`, which prints the address.

**The sequence now in the runbook.** VPS 0 (unchanged) · LAPTOP 1 (the key only) · VPS 1 pasted first and left waiting,
LAPTOP 1b (the line to the clipboard), the paste at the waiting prompt · LAPTOP 2 (unchanged) · **LAPTOP 3a, one login
alone, the gate** · LAPTOP 3b (the other tests, one function that stops by itself after T1) · LAPTOP 4a (the login
item's file) · LAPTOP 4b (reload) · LAPTOP 4c (checks) · LAPTOP 5a (the passphrase, proven locally before anything is
removed) · LAPTOP 5b (the config edit) · LAPTOP 5c (the agent and the keychain) · LAPTOP 6 (the interactive login) ·
LAPTOP 6b (did that login put the key back) · only then the first session is closed and the backups removed. The old
LAPTOP 6 (a deliberate failed login) is dropped: it cost an attempt and, with `UseKeychain` gone from the alias, proved
nothing about the keychain.

**How blocks were fed in this round.** Every block was pasted by a small terminal stand-in (a Python script that runs
the shell on a pseudo-terminal 500 columns wide): when the shell has switched bracketed paste on, as zsh and bash do at
their prompt, the block goes in between the paste markers in one piece and a Return follows; otherwise the text goes in
raw with each line break as a carriage return, which is what happens at a `read` prompt. The record says which for each
paste, with the first 16 characters of the SHA-256 of the pasted text; the same file is what the runbook's block was
built from. Three places:

- **the stand-in server** (`rehearsal-server`, Ubuntu 24.04, OpenSSH 9.6p1, sysctl `1024`, as in 1.7), now also with
  `rsyslog`, Ubuntu's own `fail2ban` 1.0.2 with its default `sshd` jail reading `/var/log/auth.log`, and a page on
  `127.0.0.1:9119` that answers `302` to `/login?next=%2F` as the dashboard does: an interactive `bash` as `hermesops`;
- **the stand-in laptop** (`rehearsal-laptop`, as in 1.7, without the `pbcopy` stand-in): an interactive `zsh` 5.9 as
  the user `laptop`;
- **this Mac** (macOS 27.0.1, zsh 5.9, BSD awk 20200816, OpenSSH 10.3p1): an interactive `/bin/zsh` with a clean
  environment, `HOME` pointed at a scratch directory so that `~` in a block is the scratch directory, and `ZDOTDIR` at a
  scratch directory whose `.zshrc` sets the prompt and, where a row says so, defines stand-in functions. Nothing under
  the real `~/.ssh`, the real agent, the login keychain or the real login item was read or written.

#### VPS 1: `tunnel_key_add`

The draft checked the line by exact comparison (`the options, "ssh-ed25519", one more word`), an exact length (181) and
a base64-only body. Rehearsed as written, then corrected in two places and rehearsed again. Each case started from a file
holding the administrative key only, except where the row says otherwise; "unchanged" means byte for byte (`cmp`).

| Case | Expected | Draft, measured | Corrected block, measured |
|---|---|---|---|
| a. the right line | `ADDED`, 2 lines | `ADDED: 2 key line(s), mode 600`; `ssh-keygen` reads 2 keys; backup = the file before | the same |
| h. the same line again | `already present` | `already present: nothing to do` | the same |
| l. after that, a DIFFERENT valid line (a second test key) | not in the draft's list | `ADDED: 3 …`, and **the backup was overwritten** (it then held 2 lines, so the restore command would have left the first limited key in place) | `ADDED: 3 …`; the backup still the original file |
| b. body cut by ONE character (180) | `REFUSED` | `REFUSED: not the expected line …`; unchanged, no backup | the same |
| c. one character of the body replaced by `*` | `REFUSED` | `REFUSED: the key holds a character that is not base64 …`; unchanged | the same |
| d. a bare key | `REFUSED` | `REFUSED: not the expected line …`; unchanged | the same |
| e. a fourth word | `REFUSED` | the same refusal; unchanged | the same |
| k. a trailing space | `ADDED` | `ADDED: 2 …`, last line 181 characters | the same |
| m. other options (port 9120), same length | `REFUSED` | `REFUSED: not the expected line …`; unchanged | the same |
| g. the block's own text pasted at the prompt | `REFUSED`, nothing written | `REFUSED: not the expected line …`, then **the block's other eleven lines ran as commands at the shell's prompt**: `local: can only be used in a function`, a second `Paste the line:` prompt that swallowed one line, a second `REFUSED` line, two syntax errors, `return: can only return from a function` twice, and `cp`, `tail`, `grep` and a redirect each failing on an empty file name. Nothing was written, because the file name lives in a variable that is empty outside the function | `REFUSED: more than one line was pasted -- nothing written`, and nothing else: no line ran as a command |
| i. a file with no final line break | `ADDED`, 2 lines | `ADDED: 2 …`; 2 lines, the first equal to the original | the same |
| j. the file missing | `REFUSED` | `REFUSED: /home/hermesops/.ssh/authorized_keys is missing …`; nothing created | the same |
| f. the line followed by a carriage return | `ADDED`, no carriage return in the file | fed on standard input (`docker exec -i … bash -c "<the block>" < line`): `ADDED: 2 …`, 0 carriage returns in the file. Through the terminal the carriage return arrives as a second line break | the same on standard input; through the terminal `ADDED: 2 …` (the empty extra line is not counted as a second line) |

**The two corrections, and why.** (1) After `read`, the function now reads on for one second
(`while read -r -t 1 X; do [ -z "$X" ] || N=1; done`) and refuses when anything but empty lines followed: case g, which
the review saw happen. (2) `[ -e "$F.before-tunnel-key" ] || cp -p …`: the first backup is kept (case l). A refused key
is then removable with the runbook's restore command whatever was added in between. Every case ran in an interactive
bash on a pseudo-terminal: the block as one bracketed paste and a Return, then the line raw with its line break, as the
clipboard gives it.

#### LAPTOP 1 and LAPTOP 1b

| Block, where | Case | Expected | Measured | Match |
|---|---|---|---|---|
| LAPTOP 1, stand-in laptop | first run | `KEY MADE` | `KEY MADE`; both key files present | yes |
| LAPTOP 1, stand-in laptop | second run | `EXISTS …` | `EXISTS: not overwritten (fine if you made it a moment ago)` | yes |
| LAPTOP 1b, this Mac, scratch key, the real `pbcopy` and `pbpaste` | the key present | `182 characters` | `line on the clipboard: 182 characters`; `pbpaste` gave 182 bytes, one line break at the end, three words, the first the option string, the third 68 characters | yes |
| the hand-over | that clipboard content pasted at VPS 1's waiting prompt on the stand-in server (VPS 1 had been pasted first) | `ADDED` | `ADDED: 3 key line(s), mode 600` (the file already held the administrative key and the stand-in laptop's limited key); `ssh-keygen` read 3 keys | yes |
| LAPTOP 1b, this Mac | the `.pub` file missing | another number | `cut: … No such file or directory`, then `line on the clipboard: 102 characters` | yes |
| `pbcopy < /dev/null`, this Mac | | clipboard empty | `pbpaste | wc -c`: `0` | yes |

This replaced the operator's clipboard twice and then emptied it. `pbcopy` and the hand-over are therefore measured on
this Mac, with the paste into the server done by the terminal stand-in, not by Terminal.app.

#### LAPTOP 2, LAPTOP 3a and LAPTOP 3b on the stand-in laptop, with the server's log

The server's log (`/var/log/auth.log`, sshd at `LogLevel VERBOSE` unless the row says otherwise) was read after each
paste, with fail2ban's counters (`fail2ban-client status sshd`). The jail's `maxretry` was raised to 100 for the round so
that no ban could interfere; nothing else in fail2ban's stock configuration was changed (`mode = normal`).

| Step | Expected | Measured (laptop) | The server's log for that paste | fail2ban total failed |
|---|---|---|---|---|
| VPS 0 | `1024` | `1024` | | |
| VPS 1, the line at the waiting prompt | `ADDED: 2 …` | `ADDED: 2 key line(s), mode 600` | | 0 |
| LAPTOP 2 | `3` | `3` | no login | 0 |
| LAPTOP 2 again | `alias exists`, `3` | `alias exists`, `3` | no login | 0 |
| **LAPTOP 3a, key in place** | `gate rc=1` | `gate rc=1` | 1 `Accepted publickey`, 1 `Starting session: forced-command (key-option) '/bin/false'` | 0 |
| **LAPTOP 3b, key in place** | the six lines | `T1 … -> 302`; `T4 … -> 0 bytes, link up`; `T5a … -> refused`; `T5b … -> refused`; `T6 … -> 0 bytes, link up`; `T7 … -> rc=255`; 24 seconds; nothing in the server's `/tmp` | 6 `Accepted publickey`, 0 refused; a denied connect to port 22, a denied remote forward, `bind [127.0.0.1]:1: Permission denied`, a denied connect to `/run/dbus/system_bus_socket`, one forced-command session | 0 |
| CONTROL: 3a with the alias argument replaced by `hermes-box` | `MARK`, `gate rc=0` | `MARK`, `gate rc=0` | `Starting session: command` | 0 |
| CONTROL: 3b the same way | everything allowed but T5b | `302`; `20 bytes, link up`; `OPENED`; `refused` (the sysctl); `13 bytes, link up`; `rc=0`, the file arrived | 6 `Accepted publickey`; `Starting session: subsystem 'sftp'` | 0 |
| **REFUSED: 3a alone, the limited key's line taken off the server** (with the runbook's restore command) | `gate rc=255`, ONE refused login | `gate rc=255` | exactly 1 `Failed publickey for hermesops` and 1 `Connection closed by authenticating user hermesops … [preauth]` (one login), 0 accepted | 0 |
| REFUSED: 3b pasted although the gate failed | it stops after one login | `T1 … -> 000`, `STOPPED after T1: the other tests were NOT run` | 1 `Failed publickey`, 1 `Connection closed by authenticating user` | 0 |
| REFUSED: 3a alone, sshd at `LogLevel INFO` (the default, which the box's `provision.sh` does not change) | `gate rc=255` | `gate rc=255` | 1 `Connection closed by authenticating user hermesops … [preauth]`, no `Failed publickey` line | 0 |
| **UNRESTRICTED: 3a alone, the same key on the server WITHOUT its options** | `MARK`, `gate rc=0` | `MARK`, `gate rc=0` | `Starting session: command` | 0 |
| 3a after the line was added again with VPS 1 | `gate rc=1` | `ADDED: 2 …` (the first backup still the original), then `gate rc=1` | forced-command session | 0 |
| 3a with the server taken off the Docker network | `gate rc=255` | `gate rc=255` within 2 seconds (the name did not resolve; a silent address with the 10-second timeout was not run) | none | |
| positive control for fail2ban's counter (not a runbook block): a login as a user that does not exist | counted | `rc=255` | `Connection closed by invalid user nosuchuser … [preauth]` | **1** |

**What the fail2ban column shows, and what it does not.** With Ubuntu 24.04's `fail2ban` 1.0.2 as packaged, a refused
public key for an existing user did not raise the count (three such logins: `0`), and a login as a user that does not
exist did (`1`): the counter was working. That is a measurement on a stand-in with the packaged defaults. The box's own
fail2ban version, jail settings and log source have **not** been read, so the runbook treats
every refused login as counted. "ONE refused login" above is counted in sshd's own log.

**zsh's notices.** In a function the background `ssh` is job 2, not job 1 (`[2] 186`, `[2]  + done ssh …`,
`[2]  + exit 255 ssh …`; on this Mac's zsh a killed stand-in showed `[2]  + terminated ssh …`). The old block's
`kill %1` would have addressed the wrong job inside a function; the new block uses `$!`.

**The draft of LAPTOP 3b** was "T1, T4, T5a, T5b, T6, T7 as now", the committed lines without T2. Run as written with
the key in place it gave the six expected values (`302`, `0 bytes`, `refused`, `refused`, `0 bytes`, `rc=255`; 6 accepted
logins). It was replaced, not because that run misbehaved, but for what it prints when something is wrong:

| Defect of the draft | The block now in the runbook |
|---|---|
| Six logins whatever the first one did (the review's measurement; with the gate before it, a refusal is unlikely but each one would count) | one function; after T1 it stops unless T1 printed `302` (measured above: ONE login, `STOPPED after T1`) |
| T4 and T6 print `0 bytes` also when their `ssh` was not running | each prints `link up` or `link DOWN` (`kill -0 $!` at the time of the test), and their `ssh` now has `ExitOnForwardFailure=yes`, so `link up` also means the local port was bound |
| `kill %1` assumes no other job, and prints `kill: %1: no such job` when the `ssh` had ended; `wait` with no argument waits for every job of the terminal | `kill $! 2>/dev/null; wait $! 2>/dev/null` |
| T1's `ssh` printed its errors, which hold the address | `2>/dev/null` on T1's `ssh` too |

**On this Mac** LAPTOP 3a and 3b were also pasted into zsh 5.9 as one bracketed paste with `ssh`, `scp` and `curl`
replaced by stand-in functions (no login leaves the Mac; `nc` is the real one), to see how macOS zsh runs the blocks'
own logic and how many logins one paste makes:

| Stand-ins behave as | LAPTOP 3a | LAPTOP 3b | `ssh`/`scp` calls from the one paste of 3b |
|---|---|---|---|
| a refused login (every call ends with 255) | `gate rc=255` | `T1 … -> 000`, `STOPPED after T1 …` | **1** (the old block: 7, the review's measurement) |
| the limited key (`-L` stays up, `-R` ends with 255, a command ends with 1, `scp` 255) | `gate rc=1` | the six expected lines, `link up` twice | 6 |
| an unlimited key (everything stays up, the command prints `MARK`) | `MARK`, `gate rc=0` | `302`, `0 bytes, link up` (nothing listens behind a stand-in), `OPENED`, `OPENED`, `0 bytes, link up`, `rc=0` | 6 |

#### LAPTOP 4a, 4b and 4c on this Mac

Scratch plists built from the README's ten arguments (`Label`, `ProgramArguments`, `RunAtLoad`, `KeepAlive`,
`ThrottleInterval` 120), at `<scratch home>/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist`. The real file
was not read. The state afterwards was read with `PlistBuddy`, `plutil -lint` and Python's `plistlib`.

| Case | Draft, measured | Block now in the runbook, measured |
|---|---|---|
| 1. the good file | `SWITCHED IN THE FILE`, `… uses: hermes-box-tunnel`; 10 arguments before and after, the tenth changed, every other value equal. `PlistBuddy` wrote the keys back in another order (`KeepAlive` moved): the text differs in more than one line, the data in one value. The backup was written next to the login item, in `LaunchAgents`. `P` and `B` stayed set in the shell | the same two lines; the same data result; the backup at `~/hermes-box-tunnel.plist.before-tunnel-key`; no variable left set |
| 2. the block again | `NOT SWITCHED: the file is not as expected -- stop` over `… uses: hermes-box-tunnel`: a correct state reported as a stop | `ALREADY SWITCHED: nothing changed`, `… uses: hermes-box-tunnel`; the file unchanged |
| 3. one extra `-o` pair (12 arguments) | `NOT SWITCHED …`, `… uses: -L`; the file unchanged | the same |
| 4. no file | `NOT SWITCHED …`, `PlistBuddy`'s own error, and `… uses: File Doesn't Exist, Will Create: <path>`; nothing created | `NOT SWITCHED …` and the same last line; nothing created |
| 5. the file and its folder not writable | (the draft's backup could not be written there, so its `Set` never ran: `cp: … Permission denied`, `… uses: hermes-box`) | see below |
| 6. an older backup already there and `cp` aliased to `cp -i` | not run | `SWITCHED IN THE FILE`, no question asked |

**Case 5 found a defect in the first corrected form.** With the backup moved to the home directory the `Set` ran on a file
it could not write: `PlistBuddy` printed `Error Opening Destination: … [Permission denied]` and **ended with status 0**,
so the block printed `SWITCHED IN THE FILE` over `the alias the login item uses: hermes-box`. The message now comes from
reading the file back, not from the tool's status: second form, case 5: `NOT SWITCHED: the change did not reach the file
-- stop`, `… uses: hermes-box`. A second defect came from case 6 on that second form: with `cp` aliased to `cp -i` and a
backup already present, zsh stopped at `overwrite …? (y/n [n])`; answered `n`, the block printed `NOT SWITCHED: the change
did not reach the file`. The third form writes `command cp -p`, which is the one in the runbook; all six cases were run
again on it.

**LAPTOP 4b and 4c were NOT run for real**: they would unload and reload the real login item. They ran with `launchctl`
replaced by a stand-in function that records its arguments and touches nothing:

| Block | Case | Measured | Calls the stand-in received |
|---|---|---|---|
| 4b | the scratch file names `hermes-box-tunnel` | `RELOADED: bootstrap rc=0` | `bootout gui/501/com.dentaledge.hermes-box-tunnel`, then `bootstrap gui/501 <the scratch plist>` |
| 4b | the same, the stand-in's `bootstrap` ends with 5 | `RELOADED: bootstrap rc=5` | the same two |
| 4b | the file still names `hermes-box`; a file with an extra `-o` pair; no file | `NOT RELOADED: the file does not name hermes-box-tunnel -- stop` (each) | none |
| 4c, port `19119` written `39119` | stand-in `state = running`, a scratch page answering `302` on 39119, one stand-in process whose command line ends in `hermes-box-tunnel` | `state = running`; `dashboard through the link -> 302`; `ssh on the new alias: 1; ssh on the old alias: 0` | `print …` |
| 4c | plus a stand-in process ending in `hermes-box` | `… new alias: 1; ssh on the old alias: 1` | |
| 4c | the stand-in says "not loaded", nothing listens, only the old process | no `state =` line; `-> 000`; `new alias: 0; … old alias: 1` | |
| 4c | nothing at all | no `state =` line; `-> 000`; `0`; `0` | |

So the `pgrep` patterns tell the two aliases apart (the first ends in `hermes-box-tunnel$`, the second in `hermes-box$`),
measured on stand-in processes (a script named `ssh` started with the README's arguments and the other port). 4c's text
was changed in one place for the run, `19119` to `39119`, because on this Mac `127.0.0.1:19119` is the real forward to the
box. What this does not show: `launchctl bootout`, `bootstrap` and `print` themselves, their messages, and how long the
login item takes to start its `ssh`.

#### LAPTOP 5a on this Mac

A scratch key with the passphrase `test-passphrase-0000` at `<scratch home>/.ssh/vps-hermes`; the prompt was answered
through the pseudo-terminal (not `SSH_ASKPASS`).

| Case | Expected | Measured | Match |
|---|---|---|---|
| the right passphrase | `PASSPHRASE OK` | prompt `Enter passphrase for "<path>":`, then `PASSPHRASE OK` | yes |
| a wrong one | `NOT OK …` | `Load key "<path>": incorrect passphrase supplied to decrypt private key`, `NOT OK: stop, nothing was changed`; it asked once | yes |
| Return alone | `NOT OK …` | the same two lines | yes |
| Ctrl+C at the prompt | not planned | neither line printed | extra |
| a key with NO passphrase in its place | not planned | **`PASSPHRASE OK` without asking** | extra: the runbook says the check counts only when it asked |
| no key file | not planned | `… No such file or directory`, `NOT OK …` | extra |

#### LAPTOP 5b on this Mac

Scratch configs at `<scratch home>/.ssh/config`; `ssh` in the block's second line was a function that calls the real
`ssh` with `-F <the scratch config>` added, so the real configuration was never read. Config A: the `hermes-box` block
with both settings, then `HOST upper` and `MATCH host y.example` in capitals, an unrelated block, an indented
`Host other-indented`, `Match host x.example`, `Host hermes-box-tunnel` and `Host hermes-box other`, each with both
settings. B: `UseKeychain=yes` and `AddKeysToAgent = yes` in the block, then a block written `Host=eq-form` with both.
C: the block and one unrelated block. D: the block and a `Host *` block with both.

| Case | Draft, measured | Block now in the runbook, measured |
|---|---|---|
| 1. config A | `EDITED: 2 line(s) removed`; `diff`: lines 5 and 6 deleted, nothing added; config mode 600; backup = the input | the same edit; then `addkeystoagent true` (the `hermes-box other` block also applies) and `UseKeychain lines left in the file: 6` |
| 2. the block again | `A BACKUP EXISTS …`; config and backup unchanged | the same |
| 3. config A under `setopt noclobber` | `EDITED: 2 …`, the same `diff` | the same |
| 4. config B | **`EDITED: 4 line(s) removed`**: the two under `Host=eq-form` went too | `EDITED: 2 …`: lines 3 and 4 only; `addkeystoagent false`; `UseKeychain lines left in the file: 1` |
| 5. config C | `EDITED: 2 …`; `addkeystoagent false` | the same, and `UseKeychain lines left in the file: 0` |
| 6. config D | `EDITED: 2 …`; `addkeystoagent true` | the same, and `… left in the file: 1` |
| 7. config C, `cp`, `mv` and `rm` aliased to `-i` | zsh stopped at `overwrite <config>? (y/n [n])`; answered `n`, **it printed `EDITED: 0 line(s) removed`** with the config untouched and a `config.new` left behind | `EDITED: 2 …`, no question (`mv -f`) |
| 8. a made failure (`config.new` is a directory) | `zsh: is a directory`, **no message from the block**, the config byte-identical, and a backup left behind, so a second run says `A BACKUP EXISTS` | `NOT EDITED: a command failed -- stop`; the config byte-identical; no backup |
| 9. the config is a link to another file | `EDITED: 2 …`: **the link was replaced by a plain file**, the file it pointed to unchanged | `NOT EDITED: ~/.ssh/config is missing or is a link -- stop`; the link and its target unchanged |
| 10. no config | `cp: … No such file or directory`, nothing else | `NOT EDITED: ~/.ssh/config is missing or is a link -- stop` |

**A finding about the check line.** The draft's second line printed `ssh -G hermes-box` filtered for `usekeychain` and
`addkeystoagent`. On this Mac `ssh -G` printed `addkeystoagent true` or `false` and **no `usekeychain` line in any case**,
with the setting present or absent. So that line cannot show whether `UseKeychain` still applies. The block now prints
the `addkeystoagent` line and, separately, the number of `UseKeychain` lines left anywhere in the file, and LAPTOP 6b
tests after the login whether the keychain supplies the key again. Other changes to the draft: the edit is made from
the config itself and the backup is taken only when the edited text exists (case 8); the `awk` takes the keyword up to
an `=` (case 4); `mv -f` (case 7); a refusal for a link or a missing file (cases 9 and 10).

The restore command in the runbook's text was first written `cp -pf …`. With `cp` aliased to `cp -i` it **still asked**
(`overwrite …? (y/n [n])`), the next pasted command was taken as the answer (`not overwritten`), and the config was not
restored. It is now `command cp -p …`: run with the same aliases, no question, the config equal to the backup. The
clean-up `rm -f …` ran with `rm` aliased to `rm -i`, twice, without a question.

#### LAPTOP 5c and LAPTOP 6b on this Mac, with a stand-in for `ssh-add`

**Not run against the login keychain or the real agent.** `ssh-add` in the blocks was a function that calls the real
`ssh-add` WITHOUT the two `--apple-…` options, against a scratch agent (`ssh-agent -s -T`, killed afterwards); for
`--apple-load-keychain` it does nothing, or, when told to play a keychain that still holds the passphrase, adds the
scratch key to the scratch agent. The scratch key has a passphrase, typed through the pseudo-terminal.

| Case | Draft (four lines), measured | Block now in the runbook (one function), measured |
|---|---|---|
| 1. the login item's scratch file switched, the key not in the agent | `Identity added`, `in the agent before: 1`, `Identity removed`, `in the agent after: 0`, `supplied by the keychain: 0` | the same |
| 2. the stand-in keychain still supplies the key | `1`, `0`, then `supplied by the keychain: 1` | the same |
| 3. the login item's file still names `hermes-box` | **it ran all the same**: `1`, `0`, `0` | `STOPPED: the login item's file does not name hermes-box-tunnel -- nothing removed`; the stand-in received no call |
| 4. `vps-hermes.pub` missing, one OTHER key in the agent | `ssh-keygen: … No such file or directory`, then **`in the agent before: 2`, `after: 1`, `supplied by the keychain: 1`**: with an empty fingerprint every key is counted | `STOPPED: could not read <path>/vps-hermes.pub -- nothing removed`; no call |
| 6b 1. nothing in the agent, the stand-in keychain supplies nothing | | `in the agent after the login: 0`, `supplied by the keychain after the login: 0` |
| 6b 2. the stand-in keychain supplies the key | | `0`, then `1` |
| 6b 3. the key is in the agent | | `1`, `1` |

So counting by fingerprint can fail and can pass (the review's finding was that the old count could do neither), and the
two refusals work. What this does not show: `--apple-use-keychain`, `--apple-use-keychain -d` and `--apple-load-keychain`
themselves, that is, whether the passphrase leaves the keychain and whether the last line would show it if it had not.
Those lines run for the first time on the operator's laptop. The operator has been asked whether a throwaway key may be
put into the login keychain and taken out again to rehearse them; that would be a later round. **Note 2026-10-08:** the
operator allowed it; the rehearsal is in 1.10.

#### LAPTOP 6 on the stand-in laptop

The throwaway administrative key was given the passphrase `test-passphrase-0000` (`ssh-keygen -p`), then `ssh hermes-box`
on the pseudo-terminal:

| Case | Measured (laptop) | The server's log | fail2ban total failed |
|---|---|---|---|
| the right passphrase | `Enter passphrase for key '/home/laptop/.ssh/vps-hermes':`, then the server's prompt; `whoami`: `hermesops`; `exit` | 1 `Accepted publickey`, `Starting session: shell on pts/0` | unchanged |
| a wrong passphrase at each of the three prompts | three prompts, then `hermesops@rehearsal-server: Permission denied (publickey).` | ONE `Connection closed by authenticating user hermesops … [preauth]` for the three | unchanged |
| Ctrl+C at the prompt | back at the laptop's prompt | one such line | unchanged |

On the real laptop the last message prints the box's address in place of the stand-in's name, which is why the runbook
says to describe it and not paste it.

#### The single commands in the runbook's text

| Command, where | Measured |
|---|---|
| `ssh -G hermes-box-tunnel \| grep -E '^(identityfile\|identitiesonly\|identityagent) '`, stand-in laptop, and this Mac through the `-F` stand-in | `identitiesonly yes`, `identityagent none`, `identityfile ~/.ssh/hermes-box-tunnel`; no `hostname` line |
| `cp -p ~/.ssh/authorized_keys.before-tunnel-key ~/.ssh/authorized_keys`, stand-in server | 1 key line afterwards; the next gate printed `gate rc=255` |
| `rm -f /tmp/t7-must-not-arrive`, then `rm -f ~/.ssh/authorized_keys.before-tunnel-key` (twice), stand-in server | the file and the backup gone; 2 key lines left; no message the second time |
| `command cp -p ~/.ssh/config.before-tunnel-key ~/.ssh/config`, this Mac, scratch home, `cp` aliased to `cp -i` | no question; the config equal to the backup |
| `rm -f ~/.ssh/config.before-tunnel-key ~/hermes-box-tunnel.plist.before-tunnel-key` (twice), the same | both gone; no question, no message |
| `pbcopy < /dev/null`, this Mac | clipboard `0` characters |

**Mechanical comparison.** Every fenced block of step 7f in the runbook was compared, by a script, with the file that
the terminal stand-in pasted in the last rehearsal of that block (exact string equality, and the SHA-256 prefix written in
the record at the paste): all `same`. For LAPTOP 4c the comparison is against the pasted text with `39119` written back
to `19119`.

**What this subsection does NOT show.**

- **LAPTOP 4b and 4c for real:** `launchctl bootout`, `bootstrap` and `print`, the real login item, and the real forward
  on port 19119. Stand-ins only.
- **LAPTOP 5c and 6b for real:** the login keychain, the real agent, the three `--apple-…` forms of `ssh-add`, and the
  two single commands `ssh-add --apple-use-keychain ~/.ssh/vps-hermes` and `ssh-add -d ~/.ssh/vps-hermes` of the text.
  **Note 2026-10-08:** the three `--apple-…` forms were run against the login keychain with a throwaway key and a private
  agent (1.10). Still not shown: the same with the administrative key, the agent macOS provides, and plain `ssh-add -d`.
- **LAPTOP 6 on macOS**, where the keychain could answer the prompt; and LAPTOP 5a with the real key, for the same reason.
- **macOS's own `nc`, `curl` and `ssh` against a real server:** on this Mac 3a and 3b ran with stand-ins for `ssh`, `scp`
  and `curl`; the real logins were made from Linux (OpenSSH 9.6p1, netcat-openbsd, curl 8.5.0).
- **Terminal.app itself:** every paste was made by the terminal stand-in, which sends what a terminal sends.
- **The box:** its OpenSSH version, its sshd configuration and log level, its kernel setting, the dashboard's own `302`,
  and its fail2ban (version, jail settings, journal back end). The fail2ban column is a stand-in's.
  **Note 2026-10-08:** the version, eight global `sshd -T` settings and the kernel setting are now measured (1.1). Its
  log level, its `Match` blocks, the dashboard's own `302` and its fail2ban are not.
- The gate against an address that does not answer (the 10-second `ConnectTimeout`): only a name that does not resolve.
- The operator's real `~/.ssh/config`, real login item file and real keys: none was read. Whether the real config has
  a `Host *` block, a link, or `UseKeychain` lines elsewhere is first seen when LAPTOP 5b runs.
- Whether macOS reads a second file left in `~/Library/LaunchAgents`: not measured; the backup is kept out of that folder.
- In VPS 1, a multi-line paste whose last line has no line break: the last piece then stays at the shell's prompt, unrun
  (reasoned from how the terminal hands over lines; not run).

### 1.9 Round 3: the points of the re-review

Measured 2026-10-08, in the third fix round. A re-review of 1.8's sequence found every earlier finding addressed and a
short list of new points in the round-2 text. This subsection records what changed for each and every rehearsal of the
round. Nothing of 1.8 was run again except where a row says so, and no earlier measurement is restated differently here.
Four blocks changed (LAPTOP 2, 4a, 5c, 6b); one one-line block is new and was **not run** (the stop command after
LAPTOP 4c); every other block of step 7f, and the four blocks of step 7e, are byte for byte those of round 2.

**Set-up.** As in 1.8 and appendix 1.C, rebuilt for the round: the stand-in server and the stand-in laptop from the
Dockerfiles of 1.C, the same terminal stand-in, and this Mac's `/bin/zsh -i` with a clean environment, `HOME` and
`ZDOTDIR` in a scratch directory, no `SSH_AUTH_SOCK` except the scratch agent's where a row says so. Differences from 1.C:

- the stand-in for `ssh-add` ends its `--apple-load-keychain` branch with `return ${STANDIN_LOAD_RC:-0}` where 1.C's has
  `return 0`, so that a failed load can be played;
- a third scratch plist, the good one with its tenth argument written `hermesops@box.example` (a test value);
- LAPTOP 5c was pasted with `19119` written `39119` (the only change to its text), for the reason 4c was in 1.8: on this
  Mac a process with `19119` in its command line could be the real forward. The stand-in processes are 1.C's (a script
  named `ssh` that sleeps, started with the README's arguments and the port `39119`);
- the fail2ban `maxretry` change of 1.C was not made, and no login was made in this round: nothing here connects to the
  server's sshd.

Nothing under the real `~/.ssh`, the real agent, the login keychain, or the real login item (its file or its launchd
job) was read, listed or written. `launchctl` was not run at all in this round, not even as a stand-in.

#### LAPTOP 2 refuses an alias it cannot read (stand-in laptop, zsh 5.9, OpenSSH 9.6p1)

The re-review's point: when `ssh -G hermes-box` fails or prints no `hostname` line, the address variable is empty and
the alias is written with an empty `HostName`, "while the count still prints `3`"; and `ssh -G` of a name with no block
prints a `hostname` line equal to the name. First what `ssh -G hermes-box` prints, for seven configs (run with
`ssh -F <file> -G hermes-box`, not through the block):

| Config | Status | `hostname` line |
|---|---|---|
| the `hermes-box` block only | 0 | `hostname rehearsal-server` |
| no `hermes-box` block | 0 | `hostname hermes-box` |
| an unknown option in the `hermes-box` block, or in another block | 255 | none (`Bad configuration option`) |
| `HostName %Z` in the `hermes-box` block | 255 | none (`unknown key %Z`); the same file asked for another name: status 0 |
| `HostName` with no value | 255 | none |
| a `Match host hermes-box exec` whose command fails | 0 | `hostname hermes-box` |

Then the block of round 2 and the block now in the runbook, each pasted into an interactive zsh as one bracketed paste,
on seven configs. "Unchanged" means byte for byte (`cmp` against a copy taken before the paste).

| Case | Block of round 2, measured | Block now in the runbook: expected | Measured | Match |
|---|---|---|---|---|
| a. the `hermes-box` block only | `3`; alias written, `HostName rehearsal-server` | alias written, `3` | `3`; one `Host hermes-box-tunnel` block, `HostName rehearsal-server`, config mode 600 | yes |
| b. the block again | `alias exists`, `3` | `alias exists`, `3` | `alias exists`, `3`; still one block | yes |
| c. **no `hermes-box` block** | **`3`, and an alias written with `HostName hermes-box`**: a pass over an alias that points at a word | a refusal, nothing written | `STOPPED: the hermes-box alias has no HostName of its own -- nothing written`, `0`; unchanged | yes |
| d. a config `ssh` cannot read (unknown option in an unrelated block) | `ssh`'s two error lines, an alias written with an EMPTY `HostName`, then `ssh`'s errors again and **`0`** | a refusal, nothing written | `ssh`'s two error lines, `STOPPED: could not read the hermes-box alias -- nothing written`, the two error lines again, `0`; unchanged | yes |
| e. `HostName %Z` in the `hermes-box` block, the rest readable | the expand error, an alias written with an EMPTY `HostName`, `no argument after keyword "hostname"`, **`0`** | a refusal, nothing written | the expand error, `STOPPED: could not read the hermes-box alias -- nothing written`, `0`; unchanged | yes |
| f. no config file | `grep: … No such file or directory`, **`3`**, and a config CREATED (mode 644) with `HostName hermes-box` | a refusal, nothing written | the `grep` line, `STOPPED: the hermes-box alias has no HostName of its own -- nothing written`, `0`; no file created | yes |
| g. a `hermes-box` block with no `HostName` line | `3`, `HostName hermes-box` | a refusal, nothing written | the same `STOPPED … no HostName of its own …`, `0`; unchanged | yes |

**What the measurement corrects in the finding.** With an EMPTY address the old block did write a broken alias, but its
count printed `0`, not `3` (cases d and e): the empty `HostName` line is itself a config error, so the second `ssh -G`
fails. The case that printed `3` over a wrong alias is the other one, no `hermes-box` block (cases c, f, g).

**The decision for a config with no `hermes-box` block.** The block refuses, with a message of its own, when the
address it read is the word `hermes-box`. Reason: `ssh -G` returns the name it was given when no block supplies a
`HostName`, so that value means "there is no address here"; an alias written from it would point at a name that
resolves to nothing, or to something else, and would pass the count. The box's real `HostName` is an address, so the
refusal cannot hit a correct config. The block never prints the value it read. No variable stays set (checked after each
paste).

**The same block on this Mac's own `ssh`** (OpenSSH 10.3p1; zsh with the scratch home; `ssh` a function that adds
`-F <the scratch config>`, 1.C's stand-in for LAPTOP 5b, so the real configuration is not read; the test address is the
name `box.example`): case a `3`, the alias written with `HostName box.example`; b `alias exists`, `3`; c and g
`STOPPED: the hermes-box alias has no HostName of its own -- nothing written`, `0`; d and e `ssh`'s error,
`STOPPED: could not read the hermes-box alias -- nothing written`, `0`; the scratch config byte for byte unchanged in c,
d, e and g. So macOS's `ssh -G` also answers with the name itself for a name it has no block for. Case f (no config
file) was not run on the Mac.

#### LAPTOP 4a's second line says which of three things (this Mac)

The second line printed the tenth argument verbatim. It now prints `hermes-box-tunnel`, `hermes-box`, or
`something else (not shown)`. The six cases of 1.8 were run again on the changed block, plus one.

| Case | Expected second line | Measured (both lines) | Match |
|---|---|---|---|
| 1. the good file | `… uses: hermes-box-tunnel` | `SWITCHED IN THE FILE`, `the alias the login item uses: hermes-box-tunnel`; 10 arguments before and after, only the tenth changed (`plistlib`), `plutil -lint` OK | yes |
| 2. the block again | `… hermes-box-tunnel` | `ALREADY SWITCHED: nothing changed`, `… uses: hermes-box-tunnel`; file unchanged | yes |
| 3. one extra `-o` pair (the tenth argument is `-L`) | `… something else (not shown)` | `NOT SWITCHED: the file is not as expected -- stop`, `… uses: something else (not shown)`; file unchanged | yes |
| 4. no file | `… something else (not shown)` | the same two lines; nothing created. (In 1.8 this line printed `File Doesn't Exist, Will Create: <path>`.) | yes |
| 5. the file and its folder not writable | `… hermes-box` | `NOT SWITCHED: the change did not reach the file -- stop`, `… uses: hermes-box` | yes |
| 7. the tenth argument written `hermesops@box.example` | `… something else (not shown)` | `NOT SWITCHED: the file is not as expected -- stop`, `… uses: something else (not shown)`; the value is nowhere in the output; file unchanged | yes |
| 6. an older backup present, `cp` aliased to `cp -i` | `… hermes-box-tunnel` | `SWITCHED IN THE FILE`, `… uses: hermes-box-tunnel`, no question | yes |

No variable stays set after any case.

#### LAPTOP 5c: a count of running `ssh` on the old alias; the keychain load's status (this Mac, stand-ins)

**Not run against the login keychain or the real agent**, as in 1.8. Two changes. (1) The guard read the login item's
FILE; launchd runs the definition it LOADED. The function now also counts running processes whose command line ends in
`19119:127.0.0.1:9119 hermes-box` (LAPTOP 4c's pattern) and stops when the count is not `0`. (2)
`ssh-add --apple-load-keychain >/dev/null 2>&1` discarded its status, so `supplied by the keychain: 0` was printed also
when the load had failed; the status is now printed (`keychain load rc=N`). `pgrep` (outside the block) confirmed the
stand-in processes before each paste.

| Case | Expected | Measured | Calls the `ssh-add` stand-in received | Match |
|---|---|---|---|---|
| 1. the scratch file switched, no stand-in process | the six lines | `Identity added`, `in the agent before: 1`, `Identity removed`, `in the agent after: 0`, `keychain load rc=0`, `supplied by the keychain: 0` | six | yes |
| 2. the stand-in keychain still supplies the key | last line `1` | …, `keychain load rc=0`, `supplied by the keychain: 1` | six | yes |
| 3. the stand-in's load ends with status 1 | `rc=1` shown | …, `keychain load rc=1`, `supplied by the keychain: 0` | six | yes |
| 4. the file still names `hermes-box` | the first refusal | `STOPPED: the login item's file does not name hermes-box-tunnel -- nothing removed` | none | yes |
| 5. **the file names `hermes-box-tunnel`, one stand-in process on the OLD alias** | the new refusal | `STOPPED: an ssh on the old alias (hermes-box) is still running -- nothing removed` | none | yes |
| 6. the same, and a process on the new alias too | the new refusal | the same line | none | yes |
| 7. only a process on the NEW alias (the state 4c expects) | it runs | the six lines of case 1 | six | yes |
| 8. `vps-hermes.pub` missing, one other key in the agent | the third refusal | `STOPPED: could not read <path>/vps-hermes.pub -- nothing removed` | none | yes |

In round 2's block, case 5 would have run to the end: its guard read the file only (not run again here; the old guard
has no line that looks at processes).

**What the new guard prints when `pgrep` itself cannot run:** nothing, and the function goes on: a failed `pgrep` gives
a count of `0` (reasoned from the pipeline; not produced). The runbook says so at the block and names what covers it:
LAPTOP 4c, run just before, prints `ssh on the new alias: 1` only when `pgrep` works.

#### LAPTOP 6b: the same status line (this Mac, stand-ins)

| Case | Expected | Measured | Match |
|---|---|---|---|
| 1. nothing in the agent, the stand-in keychain supplies nothing | `0`, `rc=0`, `0` | `in the agent after the login: 0`, `keychain load rc=0`, `supplied by the keychain after the login: 0` | yes |
| 2. the stand-in keychain supplies the key | `0`, `rc=0`, `1` | `0`, `keychain load rc=0`, `1` | yes |
| 3. the stand-in's load ends with status 1 | `0`, `rc=1`, `0` | `0`, `keychain load rc=1`, `0` | yes |
| 4. the key is in the agent | `1`, `rc=0`, `1` | `1`, `keychain load rc=0`, `1` | yes |

**Not measured, and it matters for the expected line:** what the real `ssh-add --apple-load-keychain` ends with when the
keychain holds no passphrase at all. The runbook expects `rc=0` and tells the operator to stop and report on any other
number; if macOS ends that command with another status in the clean state, that stop is a false alarm. It could not be
found out without reading the login keychain. The stand-in's `0` was written for the rehearsal; it is not a record of
what `ssh-add` does. **Note 2026-10-08:** measured in 1.10 with a throwaway key: `rc=0`, with the throwaway key's passphrase
absent from the keychain and one other key still supplied by it. A keychain holding no SSH passphrase at all is still
not measured.

#### VPS 1: leaving the waiting prompt (stand-in server, interactive bash)

When LAPTOP 1b prints another number there is nothing to paste, and VPS 1 is waiting. The block is unchanged; the case
"Return alone" was not among 1.8's.

| Case | Expected | Measured | Match |
|---|---|---|---|
| the block pasted, then Return alone at `Paste the line:` | `REFUSED: not the expected line …`, nothing written | an empty line, then `REFUSED: not the expected line (other options, a cut key, or extra words) -- nothing written`, the shell's prompt 1.9 seconds after the Return (the function reads on for one second); `authorized_keys` byte for byte the original, no backup, the function no longer defined, the next command ran normally | yes |
| the same, Return twice quickly | the same | the same refusal; file unchanged, no backup | yes |

#### The single command of the way back

LAPTOP 4c's stop text gives two commands to go back to the state before the laptop part. The first was run; the second
was not.

| Command, where | Measured |
|---|---|
| `command cp -p ~/hermes-box-tunnel.plist.before-tunnel-key ~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist`, this Mac, scratch home, after LAPTOP 4a had switched a scratch file, `cp` aliased to `cp -i` | no question; the file byte for byte the one from before the switch; its tenth argument `hermes-box` |
| `launchctl bootout gui/$(id -u)/com.dentaledge.hermes-box-tunnel` (the new fenced block) | **not run** |
| `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist` | **not run** |

Both `launchctl` commands are the ones the README gives for stopping and starting the login item. What they print, and
that the item stops retrying after `bootout`, has not been seen in any rehearsal; the runbook says so at the block and
asks for LAPTOP 4c afterwards (both counts `0`, no `state = running` line).

#### Text only (nothing run)

- *Step 7e, block 2.* The runbook now says, where the operator reads the bullets, that they are reasoned and that none of
  those outputs was produced (2.9 already said it), and has two more: `secret: in the container (len N)` with N other
  than `44`, and no `secret:` line together with `HASH DIFFERS` (the `docker compose exec` itself failed). Both are
  reasoned from the block's text; neither was produced.
- *LAPTOP 4b.* `RELOADED: bootstrap rc=5` is not a success, only `rc=0` is; and "nothing is retrying" holds only when the
  item is not loaded: if `bootout` failed, the old definition is still loaded and keeps running on the administrative
  key. 1.8 measured the block printing `RELOADED: bootstrap rc=5` with a stand-in; the two states behind it are reasoned.
- *LAPTOP 4c.* After the one retry: stop the login item first, then report; what that leaves; the way back.
- *The fail2ban sentence.* It now says the stand-in's `maxretry` was raised to 100 (1.8) and that the real box's jail was
  not measured.
- *"A security review", step 2.* A unit name with nothing after it means the unit never became active since boot; the
  lines show when each unit last started, not that it runs now. This is the re-review's statement of what
  `ActiveEnterTimestamp` holds; it was not run here (the stand-in has no systemd), and the loop itself is still not
  rehearsed (3.3).
- *The closing paragraph.* The clean-up on the box uses the first administrative session, after LAPTOP 6b's expected
  lines, and that session is closed last.

**Mechanical comparison.** A script compared every fenced block of steps 7e and 7f with the runbook as committed after
round 2 and with the files pasted: the four changed blocks equal the files this round pasted (SHA-256 prefix at the paste
line of each record; for LAPTOP 5c the text with `39119`), the thirteen others equal both the committed block and round
2's pasted file, the new one-line block equals the README's command and is reported as not rehearsed. Outside steps 7e
and 7f the runbook differs from the committed one in one line (the sentence of "A security review"). All `same`.

**What this subsection does NOT show** (1.8's list stands unchanged; these are added or sharpened):

- `launchctl bootout` and `launchctl bootstrap` as the stop and the way back: not run, not even with a stand-in.
- The real `ssh-add --apple-load-keychain`'s status, with a keychain that holds the passphrase and with one that does
  not; `rc=0` as the expected value is an assumption.
  **Note 2026-10-08:** measured for a throwaway key in both states (`rc=0` each time, 1.10); a keychain with no SSH
  passphrase at all is not.
- LAPTOP 5c's new guard against real processes and the real port `19119`: stand-in processes and `39119` only. And a
  `pgrep` that cannot run (reasoned).
- LAPTOP 2 against the operator's real `~/.ssh/config`: scratch configs only, on Linux (9.6p1) and on this Mac (10.3p1,
  through the `-F` stand-in). The real config was not read, so what the block prints for it is first seen on the laptop.
- LAPTOP 4a against the real login item's file: scratch files only, as in 1.8.
- VPS 1's Return case on the box; step 7e's two new bullets; the two states behind `bootstrap rc` other than `0`.

### 1.10 The final edit: the look and root-key blocks, and the keychain lines run for real

Measured 2026-10-08, after the operator's read-only look at the box (1.1) and with the operator's permission for one
rehearsal against this Mac's login keychain. Nothing of 1.8 or 1.9 was run again, and no block that was in step 7f
before this edit changed. Four fenced blocks are new in the runbook (`VPS look`, `VPS root key` parts (a) and (b), and
the way back for part (b)), with three single commands in its text. How to rebuild the set-up: appendix 1.D.

**How blocks were fed.** The terminal stand-in of 1.8 (appendix 1.C), unchanged. On the stand-in server: an
interactive `bash` as `hermesops`, each case in a new shell that first received `sudo -v` alone (the test password
typed at its prompt), then the block as one bracketed paste and a Return. On this Mac: an interactive `/bin/zsh` with a
clean environment, described under "The keychain lines" below.

#### `VPS look` (stand-in server)

The block is the one the operator ran on the box on 2026-10-08, character for character (compared by script with the
text the operator was given). On the box it printed the eight settings and the two key-file values of 1.1. It was run
again here because it is cheap, and to see what it prints in states the box is not in.

| Case | Expected | Measured | Match |
|---|---|---|---|
| L1. as built: `root` and `hermesops` each hold one `ssh-ed25519` key, no options | the eight settings, two key-file lines | `gatewayports no`, `allowtcpforwarding yes`, `allowstreamlocalforwarding yes`, `trustedusercakeys none`, `authorizedprincipalsfile none`, `authorizedkeyscommand none`, `authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`, `permittunnel no`, then `root authorized_keys lines=1 types= 1 ssh-ed25519; options=0` and `hermesops authorized_keys lines=1 types= 1 ssh-ed25519; options=0` | yes |
| L2. a second account holds an `ssh-ed25519` key in `authorized_keys` and an ECDSA key in `authorized_keys2` | two more lines, one per file | the ten lines of L1, then `otheracct authorized_keys lines=1 types= 1 ssh-ed25519; options=0` and `otheracct authorized_keys2 lines=1 types= 1 ecdsa-sha2-nistp256; 1 ecdsa-test; options=0` | yes, **with a finding** (below) |
| L3. the limited key's line present in the `hermesops` file | `lines=2`, `options=1` | `hermesops authorized_keys lines=2 types= 2 ssh-ed25519; options=1`; the other nine lines as in L1 | yes |
| L4. a comment line, an empty line and a second plain key in the `hermesops` file | `lines=2`, `options=0` | `hermesops authorized_keys lines=2 types= 2 ssh-ed25519; options=0` | yes |
| L5. no key file on any account | the eight settings and nothing else | the eight settings and nothing else | yes |

So the eight settings of the stand-in server (Ubuntu 24.04's packaged defaults) are the eight the box gave, in the order
the operator reported them; the two key-file lines of L1 carry the box's values (1 line, 1 `ssh-ed25519`, 0 with options,
for each account) in the form the block prints them. The exact text of the box's own ten lines was not handed over, only
the values.

**Finding (L2): `types=` can show a word of a key's comment.** The block finds key types with the pattern
`(ssh|ecdsa|sk)-[a-z0-9@.-]+`, which also matches a word of that shape in a comment: the test key's comment
`ecdsa-test` was printed as ` 1 ecdsa-test;`. A comment is free text and could hold a name. On the box the block printed
one `ssh-ed25519` per file and nothing else, so nothing of that kind was shown there. The block was not changed (it is
the one proven on the box); the runbook tells the operator not to paste such a line.

What it prints when something is broken: a setting that differs shows as a different line among the first eight (not
produced: the stand-in's settings were not changed); a key file on another account shows as a line (L2); no key file
shows as no line (L5). Not produced: a failing `sshd -T` and an account whose home directory cannot be read.

#### `VPS root key`, part (a): same key or not (stand-in server)

Written for this edit. It reads the two files and prints one line. "Unchanged" means the first twelve characters of each
file's SHA-256, owner and mode, read before and after the paste.

| Case | Expected | Measured | Match |
|---|---|---|---|
| A1. root holds the same key as `hermesops` | `same` | `root key vs the first hermesops key: same`; both files unchanged | yes |
| A4. the block again in the same shell | `same` | the same line; both files unchanged | yes |
| A2. root holds another key | `different` | `root key vs the first hermesops key: different` | yes |
| A3. root has no `authorized_keys` | its own line | `root key: root has no authorized_keys file` | yes |
| A5. root holds two keys | a refusal | `root key: NOT COMPARED: root holds 2 key(s), or the hermesops file holds none -- stop` | yes |
| A10. root's file is there and empty | a refusal | `root key: NOT COMPARED: root holds 0 key(s), or the hermesops file holds none -- stop` | yes |
| A6. `hermesops` holds the administrative key, then the limited key; root holds the administrative key | `same` | `… same` | yes |
| A7. root holds the administrative key written with options (one of them with a space inside quotes), under a comment line | `same` | `… same` | yes |
| A9. root holds the limited key with its five options | `different` | `… different` | yes |
| A8. the `hermesops` file is missing | a refusal | `root key: NOT COMPARED: the hermesops file is missing -- stop` | yes |
| A11. the `hermesops` file holds only a comment line | a refusal | `root key: NOT COMPARED: root holds 1 key(s), or the hermesops file holds none -- stop` | yes |

No record of these runs holds a key body (searched for `AAAA`: none). What the block compares is the word after the key
type on each line; it does not compare options or comments. Not run: a root line whose forced command itself contains
the text of a key type followed by a space (the block would then take the wrong word, and say `different` or `same`
about that word).

#### `VPS root key`, part (b): the file moved aside, the way back, the clean-up line (stand-in server)

Written for this edit. Part (b) moves `/root/.ssh/authorized_keys` to
`/root/.ssh/authorized_keys.removed-by-step-7f` and then says, for each of the two names sshd reads, whether root still
has a file there.

| Case | Expected | Measured | Match |
|---|---|---|---|
| B1. root holds one key file | moved; two `no file` lines | `MOVED: /root/.ssh/authorized_keys -> /root/.ssh/authorized_keys.removed-by-step-7f`, `root authorized_keys: no file`, `root authorized_keys2: no file`, `kept aside: /root/.ssh/authorized_keys.removed-by-step-7f`. The moved file: same SHA-256 prefix, owner `root`, mode 600, as the file before (read in B6) | yes |
| then `VPS look` | no `root` line | the eight settings and the `hermesops` line only | yes |
| B2. part (b) again | nothing changed | `NOT MOVED: … is already there (this block ran before) -- nothing changed now`, the two `no file` lines, `kept aside: …` | yes |
| B3. the way back | the file back | `PUT BACK: /root/.ssh/authorized_keys, lines=1, mode 600`; then `VPS look` printed the `root` line of L1 again | yes |
| the way back a second time | a refusal | `NOT PUT BACK: /root/.ssh/authorized_keys is there -- nothing changed` | yes |
| B4. root has no `authorized_keys` | a refusal | `NOT MOVED: … is missing or is a link -- nothing changed`, two `no file` lines, `kept aside: nothing` | yes |
| B5. root's `authorized_keys` is a link | a refusal | the same `NOT MOVED` line, then `root authorized_keys: STILL THERE, lines=1`, `root authorized_keys2: no file`, `kept aside: nothing` | yes |
| B6. root also has an `authorized_keys2` | moved, and the other file reported | `MOVED: …`, `root authorized_keys: no file`, `root authorized_keys2: STILL THERE, lines=1`, `kept aside: …` | yes |
| B7. a moved file is there and a new `authorized_keys` too | nothing changed, the new file reported | `NOT MOVED: … is already there …`, `root authorized_keys: STILL THERE, lines=1`, `root authorized_keys2: no file`, `kept aside: …` | yes |
| B8. **a made failure**: a second container of the same image, `/root/.ssh` made unchangeable (`chattr +i`) | the failure said, nothing moved | `mv: cannot move … Operation not permitted`, `NOT MOVED: the move failed -- stop`, `root authorized_keys: STILL THERE, lines=1`, `root authorized_keys2: no file`, `kept aside: nothing` | yes |
| C1. after a move, the clean-up line of the runbook's text | the moved file gone | `the moved file is gone`; run again: the same line; then the way back: `NOT PUT BACK: … is missing -- nothing changed` | yes |

The clean-up line prints `the moved file is gone` also when there never was such a file (second run of C1): it shows
that the file is not there, not that it was deleted just now. The runbook says so.

**Does sshd really ignore the moved file?** Measured in the same container, with `sshd` started for the test and root
login allowed there (the image's packaged default, `permitrootlogin without-password`; on the box it is `no`). A login
as `root` with the key of that file, from inside the container to `127.0.0.1`: with the file in place `IN`, `rc=0`;
after the move `rc=255`; after moving it back `IN`, `rc=0`. `sshd -T` there printed
`authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`, the box's value. On the box this cannot be shown by a
login, because root login is off; there the proof is the two `no file` lines and `VPS look`.

#### Two single commands of the text (stand-in server)

| Command, where it stands | Case | Expected | Measured | Match |
|---|---|---|---|---|
| VPS 1 (the block is unchanged), then `chmod 600 ~/.ssh/authorized_keys; stat -c %a ~/.ssh/authorized_keys`, after VPS 1 | the `hermesops` file made mode 644 before VPS 1 | `ADDED: … mode 644`, then `600` | `ADDED: 2 key line(s), mode 644`, then `600`; the file mode 600 afterwards | yes |
| the same command | a file that is already 600 | `600` | `600` | yes |
| `K=$(openssl rand -hex 32); echo "throwaway key: $K"`, "A security review" step 2 | | the key shown | `throwaway key: ` and 64 hexadecimal characters | yes |

#### The keychain lines of LAPTOP 5c and LAPTOP 6b, on this Mac's login keychain

**What ran, and within which limits.** macOS 27.0.1 (build 26A434), `/usr/bin/ssh-add` and `/usr/bin/ssh-agent` of
OpenSSH 10.3p1 (LibreSSL 3.3.6), zsh 5.9. A throwaway ed25519 key with the passphrase `test-passphrase-0000`, made at a
scratch path. A private agent started for the test (`ssh-agent -D -a a.sock`, its socket a relative path inside the
scratch directory because the absolute scratch path is too long for a socket; its own `HOME` a scratch directory) and
killed right after the last count. The shell was an interactive `/bin/zsh` on a pseudo-terminal with an environment
built from nothing: `PATH`, `TERM`, `LANG`, `USER`, `LOGNAME`, `SHELL`, the real `HOME` (so that the login keychain is
the one a Terminal window uses), `ZDOTDIR` at a scratch directory whose `.zshrc` only sets the prompt, and
`SSH_AUTH_SOCK=a.sock`. The `SSH_AUTH_SOCK` this session inherited was never read, and the agent macOS provides was
never contacted. The passphrase prompt was answered **through the pseudo-terminal**, as a person types it (no
`SSH_ASKPASS`). From the agent only counts were taken: `ssh-add -l | grep -cF "$FP"` for the throwaway key (its
fingerprint read from its public file into a shell variable and never printed) and the number of lines of `ssh-add -l` that hold a
fingerprint for a total (a `grep -c` for the word `SHA256` and a colon; the pattern is written out in words so that this
document holds no string shaped like a fingerprint). Every wait had a time limit of 25 seconds and nothing was to be retried. No network connection was made. Nothing
under the real `~/.ssh` was read, listed or written by any command of the rehearsal, with one disclosed exception that
is inherent to the line under test: `ssh-add --apple-load-keychain` loads every key whose passphrase the keychain holds
(row 2b and steps 4 and 5).

Each line is the runbook's, with the key path substituted, and with the status and a total echoed after it (the
runbook's lines do not print them). "Total" is the number of identities in the private agent.

| Step | Line (paths left out) | Expected | Measured |
|---|---|---|---|
| 0. before anything | `ssh-add -l` | an empty agent | status 1, total 0, throwaway key 0 |
| 1. LAPTOP 5c's first line | `ssh-add --apple-use-keychain "$K"; echo "in the agent before: $(ssh-add -l \| grep -cF "$FP")"` | it asks for the passphrase; count 1 | it asked once (`Enter passphrase for <path>:`), then `Identity added: <path> (<comment>)`; status 0; `in the agent before: 1`; total 1 |
| 2b. **added to the six steps: a positive control for the last line** | `ssh-add -D`, then LAPTOP 5c's third line: `ssh-add --apple-load-keychain >/dev/null 2>&1; echo "keychain load rc=$?"; echo "supplied by the keychain: $(ssh-add -l \| grep -cF "$FP")"`, then `ssh-add -D` | the keychain holds the passphrase, so count 1 | total before 0; `keychain load rc=0`; `supplied by the keychain: 1`; total after **2**; after `ssh-add -D`: 0 |
| 2. the first line again on the emptied agent, no passphrase supplied | as step 1 | silent, count 1 | it did **not** ask; `Identity added: …`; status 0; `in the agent before: 1`; total 1 |
| 3. LAPTOP 5c's second line | `ssh-add --apple-use-keychain -d "$K"; echo "in the agent after: $(ssh-add -l \| grep -cF "$FP")"` | count 0 | `Identity removed: <path> ED25519 (<comment>)`; status 0; `in the agent after: 0`; total 0 |
| 4. LAPTOP 5c's third line | the load line of 2b, then `ssh-add -D` | `rc`, count 0, the total | total before 0; `keychain load rc=0`; `supplied by the keychain: 0`; total after **1**; after `ssh-add -D`: 0 |
| 5a. clean state (the key neither in the agent nor in the keychain) | `ssh-add --apple-use-keychain -d "$K"` | to be recorded | `Could not remove identity "<path>": agent refused operation`; status 1; throwaway key 0, total 0 |
| 5b. clean state, the load line as LAPTOP 6b has it | the load line, then `ssh-add -D` | `rc` to be recorded, count 0 | total before 0; `keychain load rc=0`; `supplied by the keychain: 0`; total after **1**; after `ssh-add -D`: 0. Then the private agent was killed |
| 6. is the keychain item gone? | `security find-generic-password -a <the throwaway key's path> -s SSH`, status only | not found | status 44 (not found). **This proves nothing by itself: see below** |

**No command blocked.** Each one came back to the prompt within its time limit, so no permission dialog held any of
them up (the screen itself was not looked at). No step asked for a passphrase other than step 1.

**What the measurement shows.**

- `ssh-add --apple-use-keychain <key>` asks once and stores the passphrase: the same line on an emptied agent then adds
  the key without asking (step 2), and `--apple-load-keychain` supplies it (2b: count 1).
- `ssh-add --apple-use-keychain -d <key>` takes the key out of the agent and the passphrase out of the keychain: after
  it the load line supplies the key no longer (step 4 and 5b: count 0), where before it did (2b: count 1). So the last
  line of LAPTOP 5c and of LAPTOP 6b **can print `1` and can print `0`**, measured against the real keychain.
- `keychain load rc=0` in all three runs of the load line: with the throwaway key's passphrase in the keychain (2b) and
  without it (4, 5b).
- **The disclosed side effect, as a count.** Each run of `--apple-load-keychain` put **one** identity that is not the
  throwaway key into the private agent (totals 2, 1, 1 with the throwaway key counted 1, 0, 0). So this Mac's keychain
  holds the passphrase of one other SSH key. That identity was removed from the private agent with `ssh-add -D` after
  each count; the agent was killed after 5b; no connection was made with it. Nothing about it was printed or recorded
  but the number.

**Differences from what the runbook assumed, and what changed.**

1. *`keychain load rc=0` in the clean state* was an assumption (1.9). Measured: `rc=0` with the throwaway key's
   passphrase absent. **But the keychain was not empty of SSH passphrases in any run** (one other key, above), so the
   state "no SSH passphrase at all", which is this laptop's state after LAPTOP 5c if the administrative key's is the only
   one stored, is **still not measured**. No block changed. The runbook's text at LAPTOP 5c and 6b now says what was
   measured and keeps the sentence about a possible false alarm for the unmeasured state.
2. *"From the manual; not measured"* for the other keys the last line loads: now measured as a count; the text says so.
3. *`security find-generic-password` cannot see the item.* The query of step 6 ended with status 44 **also while the
   item existed** (straight after step 1), with `-s SSH`, with `-s OpenSSH` and with the account alone; it ended with 44
   before step 1 and after step 3 as well. On this macOS that tool does not see what `ssh-add` stores, so "not found"
   at the end is no proof. No wider query was tried: every query named the throwaway key's path as its account, and
   none asked for a secret. The proof that the throwaway item is gone is the load line: count 1 while it was stored
   (2b), count 0 after the removal (4, 5b). The runbook does not use `security`, so nothing changed there.
4. *`ssh-add -l | grep -c .` is not a total.* With an empty agent `ssh-add -l` prints the sentence `The agent has no
   identities.` on standard output and ends with status 1, so that count would be 1. The totals above count the lines
   that hold a fingerprint. The runbook's counts use `grep -cF "$FP"` and are not affected.
5. *`--apple-use-keychain -d` on a key that is not in the agent* (5a): `agent refused operation`, status 1, as the
   reviewer had measured for a plain `-d`. LAPTOP 5c never runs it in that state: its first line loads the key first.

**What was rehearsed, and what was not.** Rehearsed for real: the three `--apple-…` forms of `ssh-add` against the
login keychain, each followed by its count, with a throwaway key and a private agent; and with them the single command
`ssh-add --apple-use-keychain <key>` that LAPTOP 6's text gives for putting a passphrase back. **Not rehearsed:** the
same lines with the administrative key and with the agent macOS itself provides; LAPTOP 5c and 6b as whole functions
against the keychain (their refusals and their order ran with stand-ins, 1.8 and 1.9); the load line's status with no
SSH passphrase at all in the keychain; LAPTOP 6's login on macOS and LAPTOP 6b after a real login; a passphrase that
`ssh` itself stored through `UseKeychain` (the item here was stored by `ssh-add`); plain `ssh-add -d` and
`ssh-add -t 1h` of the text; a locked keychain, and a keychain that answers with a permission dialog.

**Clean-up, checked.** The throwaway key's passphrase is out of the keychain (load line: count 0, twice). The private
agent is killed (its exit status was read; no such process and no socket file left). The throwaway key files were
deleted. Besides that keychain item, created and removed, nothing outside the scratch directory was changed on this Mac.

#### Mechanical comparison

A script (a file, run by path) compared every fenced block of the runbook with the runbook at commit `1cbf032`:
80 blocks there, all 80 found identical and in the same order now; 84 blocks now, the four new ones all in step 7f
(21 blocks of steps 7e and 7f before, 25 now). Each new block equals, character for character, the file the terminal
stand-in pasted, and that file's SHA-256 prefix stands at a paste line of the records; `VPS look` equals the block the
operator was given; the three single commands of the text are the rehearsed strings. `README.md` is unchanged.

#### What this subsection does NOT show

- **The new blocks on the box**, except `VPS look`, which the operator ran there. `VPS root key` (a), (b), the way back
  and the clean-up line have run only on the stand-in server; whether root's key on the box is the administrative key
  is not known until part (a) runs there.
- `sudo` on the box for these blocks (the stand-in asked for a test password at `sudo -v`; the box's `sudo` settings were
  not read).
- The box's `Match` blocks, its fail2ban jail, and everything that needs a login with the new key.
- The keychain items listed as not rehearsed above; Terminal.app itself (the terminal stand-in pasted every block).
- `VPS look` with a setting that differs, with a failing `sshd -T`, or with accounts that are not in `/etc/passwd`
  (`getent passwd` lists what the system's name services give; the stand-in had local accounts only).

### Not measured

- The box's real OpenSSH version, its own `sshd_config` (a global `AllowTcpForwarding`, any `Match` block that
  could override the key's options) and its `net.ipv4.ip_unprivileged_port_start` (1.1, 1.4).
  **Confirmed 2026-10-08:** the box's OpenSSH version, its global `sshd -T` settings (`allowtcpforwarding yes` among the
  eight of 1.1) and its `ip_unprivileged_port_start` (`1024`) are now measured. Still not measured: its `Match` blocks,
  its fail2ban jail, and everything that needs a login with the new key.
- A real host, as opposed to Docker's network: every connection came from the Docker bridge address.
- A key with `restrict` and **no** `command=`: every test ran with `command="/bin/false"`, so "`restrict` alone does
  not stop commands" rests on the manual, not on a run.
- IPv6 (`::1`) forwards, and `-R` with a bind address other than `127.0.0.1`.
- `-D` (dynamic) forwards and agent forwarding; neither was run, though `restrict` without `agent-forwarding`
  disables the latter.
- A client older or newer than the laptop's OpenSSH 10.3p1 (LibreSSL); the server was 9.6p1.
- That the same refusals hold when the key is the one actually used by the Desktop app's tunnel.
- Anything stated as "reasoned" above (the consequence of a listener on port 1).

### 1.A Appendix: how to reproduce section 1

All of this ran on the laptop; every connection went to `127.0.0.1:2222`. Test keys only. `$S` is a scratch
directory.

**Keys and key file**

```bash
ssh-keygen -q -t ed25519 -N "" -C admin  -f "$S/admin"
ssh-keygen -q -t ed25519 -N "" -C tunnel -f "$S/tunnel"
TUNNEL_OPTS='restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'
{ cat "$S/admin.pub"; printf '%s %s\n' "$TUNNEL_OPTS" "$(cut -d' ' -f1,2 "$S/tunnel.pub")"; } > "$S/authorized_keys"
```

**Dockerfile** (`$S/Dockerfile`; the first run had no `iproute2`)

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server python3 iproute2 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /bin/bash hermesops && install -d -m 700 -o hermesops -g hermesops /home/hermesops/.ssh && mkdir -p /run/sshd \
 && printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nLogLevel VERBOSE\n' > /etc/ssh/sshd_config.d/10-test.conf
COPY --chown=hermesops:hermesops --chmod=600 authorized_keys /home/hermesops/.ssh/authorized_keys
CMD ["sh", "-c", "runuser -u hermesops -- python3 -m http.server 9119 --bind 127.0.0.1 >/dev/null 2>&1 & runuser -u hermesops -- python3 -m http.server 9120 --bind 127.0.0.1 >/dev/null 2>&1 & runuser -u hermesops -- python3 -c \"import socket,os; s=socket.socket(socket.AF_UNIX); s.bind('/tmp/t.sock'); s.listen(); c,_=s.accept(); c.send(b'UNIX-REACHED'); c.close()\" & exec /usr/sbin/sshd -D -e"]
```

**The two containers** (one at a time; remove `$S/kh` between them, the host key is new)

```bash
docker build -q -t tunnel-rehearsal "$S"
# plain: net.ipv4.ip_unprivileged_port_start is 0 inside
docker run -d --rm --name tunnel-rehearsal -p 127.0.0.1:2222:22 tunnel-rehearsal
# with the sysctl
docker run -d --rm --name tunnel-rehearsal --sysctl net.ipv4.ip_unprivileged_port_start=1024 -p 127.0.0.1:2222:22 tunnel-rehearsal
docker exec tunnel-rehearsal sshd -V 2>&1 | head -1
docker exec tunnel-rehearsal sysctl net.ipv4.ip_unprivileged_port_start
```

**Client options** (run under `bash`, not `zsh`, which does not split `$SSHO`)

```bash
SSHO="-F none -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o UserKnownHostsFile=$S/kh -o StrictHostKeyChecking=accept-new"
SFTPO="-F none -P 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o UserKnownHostsFile=$S/kh -o StrictHostKeyChecking=accept-new"
K="-i $S/tunnel"        # the control uses K="-i $S/admin"
```

**T1 to T8 with the limited key** (T5b is bounded at 10 s; `rc=124` would mean the forward is up)

```bash
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -L 29119:127.0.0.1:9119 hermesops@127.0.0.1 & sleep 3
echo "T1 forward to 9119 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29119/)"; kill $!; wait
echo "T2 command -> [$(ssh $SSHO $K hermesops@127.0.0.1 'echo MARK' 2>/dev/null)] rc=$?"
echo "T3 terminal -> [$(ssh $SSHO $K -tt hermesops@127.0.0.1 2>&1 </dev/null | tr -d '\r' | head -2 | tr '\n' '|')]"
ssh $SSHO $K -N -L 29120:127.0.0.1:9120 hermesops@127.0.0.1 2>/dev/null & sleep 3
echo "T4 forward to 9120 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29120/)"; kill $!; wait
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -R 127.0.0.1:29123:127.0.0.1:22 hermesops@127.0.0.1 2>/dev/null; echo "T5a -> rc=$?"
timeout 10 ssh $SSHO $K -o ExitOnForwardFailure=yes -N -R 127.0.0.1:1:127.0.0.1:22 hermesops@127.0.0.1 2>/dev/null; echo "T5b -> rc=$?"
ssh $SSHO $K -N -L 29124:/tmp/t.sock hermesops@127.0.0.1 2>/dev/null & sleep 3
echo "T6 unix socket -> [$(nc -w 3 127.0.0.1 29124 </dev/null)]"; kill $!; wait
echo "T7 sftp (-P 2222) -> $(echo ls | sftp $SFTPO $K hermesops@127.0.0.1 >/dev/null 2>&1; echo rc=$?)"
ssh $SSHO $K -N -L 29125:localhost:9119 hermesops@127.0.0.1 2>/dev/null & sleep 3
echo "T8 -L to the NAME localhost -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29125/)"; kill $!; wait
```

**Control** (`K="-i $S/admin"`): `C-T2`, `C-T4`, `C-T6` and `C-T8` are the T2, T4, T6 and T8 commands above with
`K` switched; the first run's control used T2, T4 and T6 only.

**T5b with the listener shown** (run in each container; `M` is the log line count taken before)

```bash
M=$(docker logs tunnel-rehearsal 2>&1 | wc -l)
docker exec tunnel-rehearsal ss -ltn                                  # before
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -R 127.0.0.1:1:127.0.0.1:22 hermesops@127.0.0.1 2>"$S/t5b.err" &
P=$!; sleep 4; kill -0 $P && echo "still running" || { wait $P; echo "exited rc=$?"; }
docker exec tunnel-rehearsal ss -ltn                                  # while it runs
docker exec tunnel-rehearsal sh -c "awk '\$4==\"0A\"' /proc/net/tcp"  # LISTEN rows; port 1 is 0100007F:0001
cat "$S/t5b.err"; docker logs tunnel-rehearsal 2>&1 | tail -n +$((M+1))
kill $P; wait $P
docker exec -u hermesops tunnel-rehearsal python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',1));print('bound port 1 OK')"
```

**T7 file transfer** (for each of `KEY=tunnel` and `KEY=admin`; the log is read the same way with `M`)

```bash
echo "local-payload" > "$S/up.txt"
docker exec tunnel-rehearsal sh -c 'echo remote-payload > /home/hermesops/down.txt; chown hermesops /home/hermesops/down.txt'
echo ls | sftp $SFTPO -i "$S/$KEY" hermesops@127.0.0.1
scp    $SFTPO -i "$S/$KEY" "$S/up.txt" hermesops@127.0.0.1:/home/hermesops/up.txt
docker exec tunnel-rehearsal ls /home/hermesops/up.txt          # is the file there?
scp    $SFTPO -i "$S/$KEY" hermesops@127.0.0.1:/home/hermesops/down.txt "$S/down.txt"; ls "$S/down.txt"
# remove up.txt and down.txt, then the same two scp calls with -O
scp -O $SFTPO -i "$S/$KEY" "$S/up.txt" hermesops@127.0.0.1:/home/hermesops/up.txt
scp -O $SFTPO -i "$S/$KEY" hermesops@127.0.0.1:/home/hermesops/down.txt "$S/down.txt"
```

**`tunnel_key_add`, as tested** (the "VPS 1" function of the box block)

```bash
tunnel_key_add() {
  local L F="$HOME/.ssh/authorized_keys"
  read -r -p "Paste the line: " L
  case "$L" in
    'restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false" ssh-ed25519 AAAA'*) ;;
    *) echo "REFUSED: not the expected line -- nothing written"; return;;
  esac
  [ "$(printf '%s' "$L" | wc -w)" -eq 3 ] && [ ${#L} -ge 180 ] || { echo "REFUSED: the line is cut or has extra words -- nothing written"; return; }
  grep -qxF "$L" "$F" && { echo "already present"; return; }
  cp -p "$F" "$F.before-tunnel-key" || return
  [ -z "$(tail -c1 "$F")" ] || echo >> "$F"
  printf '%s\n' "$L" >> "$F" && echo "ADDED: $(grep -cvE '^\s*(#|$)' "$F") key line(s), mode $(stat -c %a "$F")"
}
```

**The stdin script** (`docker exec -i -u hermesops tunnel-rehearsal bash -s < script`; for each line under test,
`tunnel_key_add` is followed on the next line by the line to paste; `mk N` below builds the options string,
`ssh-ed25519` and the first N characters of the test key body, so N = 66 gives 179 characters and 67 gives 180)

```bash
<the function above>
export HOME=$(mktemp -d); mkdir -p $HOME/.ssh; chmod 700 $HOME/.ssh
head -1 /home/hermesops/.ssh/authorized_keys > $HOME/.ssh/authorized_keys; chmod 600 $HOME/.ssh/authorized_keys
echo "--- line of 179 characters"
tunnel_key_add
<the 179-character line>
echo "lines now: $(wc -l < $HOME/.ssh/authorized_keys)"
# ... repeated for the 133, 178, 180 and 181 (full) characters lines, the full line + " extra",
#     and the full line + " admin@x"
```

**Teardown**

```bash
docker rm -f tunnel-rehearsal; docker rmi tunnel-rehearsal; rm -rf "$S"
```

### 1.B Appendix: how to rebuild the two containers of 1.7

`$X` is a scratch directory with `server/` and `laptop/` inside. The server differs from appendix 1.A's Dockerfile in
three ways: `/run/dbus` is created, there is no 9120 listener and no `/tmp/t.sock`, and a root-run unix listener
(`server_unix.py`) is started. `authorized_keys` holds the throwaway administrative key's public line.

`$X/server/server_unix.py`

```python
import socket, os
p = '/run/dbus/system_bus_socket'
try:
    os.unlink(p)
except FileNotFoundError:
    pass
s = socket.socket(socket.AF_UNIX)
s.bind(p)
os.chmod(p, 0o666)
s.listen()
while True:
    c, _ = s.accept()
    c.send(b'UNIX-REACHED\n')
    c.close()
```

`$X/server/Dockerfile`

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server python3 iproute2 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /bin/bash hermesops && install -d -m 700 -o hermesops -g hermesops /home/hermesops/.ssh && mkdir -p /run/sshd /run/dbus \
 && printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nLogLevel VERBOSE\n' > /etc/ssh/sshd_config.d/10-test.conf
COPY --chown=hermesops:hermesops --chmod=600 authorized_keys /home/hermesops/.ssh/authorized_keys
COPY server_unix.py /root/server_unix.py
CMD ["sh", "-c", "python3 /root/server_unix.py & runuser -u hermesops -- python3 -m http.server 9119 --bind 127.0.0.1 >/dev/null 2>&1 & exec /usr/sbin/sshd -D -e"]
```

`$X/laptop/Dockerfile`

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client zsh curl netcat-openbsd ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /usr/bin/zsh laptop && install -d -m 700 -o laptop -g laptop /home/laptop/.ssh && touch /home/laptop/.zshrc && chown laptop:laptop /home/laptop/.zshrc \
 && printf '#!/bin/sh\ncat > "$HOME/clipboard"\n' > /usr/local/bin/pbcopy && chmod 755 /usr/local/bin/pbcopy
CMD ["sleep", "infinity"]
```

**Bring-up** (the administrative key is made in the laptop container first, because the server image needs its public
half)

```bash
docker network create rehearsal-net
docker build -q -t rehearsal-laptop "$X/laptop"
docker run -d --rm --name rehearsal-laptop --network rehearsal-net rehearsal-laptop
docker exec -u laptop rehearsal-laptop ssh-keygen -q -t ed25519 -N "" -C admin-test -f /home/laptop/.ssh/vps-hermes
docker cp rehearsal-laptop:/home/laptop/.ssh/vps-hermes.pub "$X/server/authorized_keys"
docker build -q -t rehearsal-sshd "$X/server"
docker run -d --rm --name rehearsal-server --network rehearsal-net --sysctl net.ipv4.ip_unprivileged_port_start=1024 rehearsal-sshd
printf 'Host hermes-box\n  HostName rehearsal-server\n  User hermesops\n  IdentityFile ~/.ssh/vps-hermes\n  AddKeysToAgent yes\n' \
  | docker exec -i -u laptop rehearsal-laptop sh -c 'cat > /home/laptop/.ssh/config; chmod 600 /home/laptop/.ssh/config'
docker exec -u laptop rehearsal-laptop ssh -o StrictHostKeyChecking=accept-new hermes-box 'echo admin-login-ok'
```

**LAPTOP 1** ran as `docker exec -u laptop rehearsal-laptop zsh -c "$(cat laptop1.txt)"` (a file holding the runbook's
block). **VPS 0 and VPS 1:** `docker exec -u hermesops rehearsal-server bash -c "$(cat vps0.txt)"`, and
`docker exec -i -u hermesops rehearsal-server bash -c "$(cat vps1.txt)" < clipboard.line`, the line having been copied
out with `docker cp rehearsal-laptop:/home/laptop/clipboard clipboard.line`.

**LAPTOP 2 and 3** (`zrun2.sh BLOCKFILE RAWOUT`; the block file holds the runbook's block, nothing added):

```bash
{ cat "$1"; echo "exit"; } | docker exec -i -u laptop -e PS1='Z> ' rehearsal-laptop script -qec "stty cols 600; zsh -i" /dev/null > "$2" 2>&1
```

The control's block file is the LAPTOP 3 block through `sed -E 's/hermes-box-tunnel([ :])/hermes-box\1/g'`.

**Teardown**

```bash
docker rm -f rehearsal-server rehearsal-laptop; docker network rm rehearsal-net; docker rmi rehearsal-sshd rehearsal-laptop
```

### 1.C Appendix: how to rebuild the set-up of 1.8

`$X` is a scratch directory. The two containers and the network are the ones of appendix 1.B, with these differences.

**Server** (`$X/server/`): `server_unix.py` as in 1.B, plus a page that answers as the dashboard does, a start script, and
`rsyslog` and `fail2ban` in the image.

`$X/server/page302.py`

```python
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(302); self.send_header('Location', '/login?next=%2F'); self.end_headers()
        else:
            self.send_response(200); self.end_headers(); self.wfile.write(b'stand-in sign-in page\n')
    def log_message(self, *a):
        pass
HTTPServer(('127.0.0.1', 9119), H).serve_forever()
```

`$X/server/start.sh` (the container of this round was started with `touch /var/log/auth.log` in the fourth line, which
left the file owned by root so that `rsyslogd` could not write it; it was corrected in the running container with
`chown syslog:adm /var/log/auth.log` and a restart of `rsyslogd`. The line below is the corrected one and has not been
run as a start-up.)

```bash
#!/bin/sh
# LOGLEVEL comes from the container's environment (VERBOSE or INFO)
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nLogLevel %s\n' "${LOGLEVEL:-VERBOSE}" > /etc/ssh/sshd_config.d/10-test.conf
install -o syslog -g adm -m 640 /dev/null /var/log/auth.log
rsyslogd
python3 /opt/rehearsal/server_unix.py &
runuser -u hermesops -- python3 /opt/rehearsal/page302.py &
fail2ban-server -b >/dev/null 2>&1
exec /usr/sbin/sshd -D
```

`$X/server/Dockerfile`

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server python3 iproute2 rsyslog fail2ban && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /bin/bash hermesops && install -d -m 700 -o hermesops -g hermesops /home/hermesops/.ssh && mkdir -p /run/sshd /run/dbus /run/fail2ban \
 && printf '[sshd]\nenabled = true\nbackend = polling\nlogpath = /var/log/auth.log\n' > /etc/fail2ban/jail.d/zz-rehearsal.local
COPY --chown=hermesops:hermesops --chmod=600 authorized_keys /home/hermesops/.ssh/authorized_keys
COPY server_unix.py page302.py start.sh /opt/rehearsal/
CMD ["sh", "/opt/rehearsal/start.sh"]
```

**Laptop** (`$X/laptop/Dockerfile`): as in 1.B without the `pbcopy` stand-in, and with the prompt set in `.zshrc`.

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client zsh curl netcat-openbsd ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /usr/bin/zsh laptop && install -d -m 700 -o laptop -g laptop /home/laptop/.ssh && printf "PS1='Z> '\n" > /home/laptop/.zshrc && chown laptop:laptop /home/laptop/.zshrc
CMD ["sleep", "infinity"]
```

**Bring-up**: as in 1.B, with `-e LOGLEVEL=VERBOSE` added to the server's `docker run`, then
`docker exec rehearsal-server fail2ban-client set sshd maxretry 100`. The log level was switched in the running container
with `sed -i 's/^LogLevel .*/LogLevel INFO/' /etc/ssh/sshd_config.d/10-test.conf; kill -HUP 1` and back the same way. The
unreachable case: `docker network disconnect rehearsal-net rehearsal-server`, the gate, `docker network connect …`.

**The terminal stand-in** (Python, standard library): `pty.fork()` and `exec` of the shell; a window 500 columns wide
(`TIOCSWINSZ`); output read until the prompt (`Z> ` for zsh, `B$ ` for bash) is the last thing printed and nothing more
has arrived for 0.6 seconds. A paste is sent as `ESC [ 200 ~`, the text, `ESC [ 201 ~` when the last of `ESC [ ? 2004 h`
and `ESC [ ? 2004 l` in the shell's output is the `h`; otherwise as the raw text with each line break as a carriage
return. Return is a carriage return. The shells:

```bash
docker exec -it -u laptop -e TERM=xterm-256color rehearsal-laptop zsh -i
docker exec -it -u hermesops -e TERM=xterm-256color -e 'PS1=B$ ' rehearsal-server bash --norc -i
env -i HOME="$X/mac/home" ZDOTDIR="$X/mac/<one of the directories below>" PATH=/usr/bin:/bin:/usr/sbin:/sbin TERM=xterm-256color LANG=en_US.UTF-8 /bin/zsh -i
```

The third line is written as a command for the reader; the stand-in started `/bin/zsh -i` itself with exactly that
environment plus `USER`, `LOGNAME`, `SHELL=/bin/zsh` and `TMPDIR` (and, for LAPTOP 5c and 6b, `SSH_AUTH_SOCK` set to the
scratch agent's socket; for the stand-ins, the variable that selects their behaviour).

**The stand-ins on this Mac** (each a `.zshrc` in its own `ZDOTDIR`; all start with `PS1='Z> '`).

For LAPTOP 5b and the single commands (the real `ssh`, made to read the scratch config; two more directories add
`setopt noclobber`, or `alias mv='mv -i' cp='cp -i' rm='rm -i'`):

```zsh
ssh() { command ssh -F "$HOME/.ssh/config" "$@" }
```

For LAPTOP 4b and 4c (nothing reaches launchd):

```zsh
launchctl() {
  echo "$*" >> "$HOME/launchctl.calls"
  case "$1" in
    print) if [ "$STANDIN_PRINT" = running ]; then printf 'gui/501/com.dentaledge.hermes-box-tunnel = {\n\tactive count = 1\n\tpath = (stand-in)\n\ttype = LaunchAgent\n\tstate = running\n\n\tprogram = /usr/bin/ssh\n}\n'; else echo 'Bad request.' >&2; echo 'Could not find service "com.dentaledge.hermes-box-tunnel" in domain for user gui: 501' >&2; return 113; fi;;
    bootstrap) echo "[stand-in for launchctl] bootstrap called"; return ${STANDIN_BOOTSTRAP_RC:-0};;
    bootout) echo "[stand-in for launchctl] bootout called"; return ${STANDIN_BOOTOUT_RC:-0};;
  esac
}
```

The words this stand-in prints for `print` were written for the rehearsal; they are not a record of what `launchctl`
prints. The stand-in processes for 4c were a two-line script named `ssh` (`sleep 90`) started as
`$X/mac/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -L 39119:127.0.0.1:9119 hermes-box-tunnel` (and with
`hermes-box`), and the scratch page was `page302.py` with the port `39119`.

For LAPTOP 5c and 6b (the login keychain is never touched; `SSH_AUTH_SOCK` is the scratch agent's socket):

```zsh
ssh-add() {
  echo "$*" | sed "s#$HOME#~#g" >> "$HOME/ssh-add.calls"
  local a keep; keep=()
  for a in "$@"; do
    case "$a" in
      --apple-load-keychain) [ -n "$STANDIN_KEYCHAIN_SUPPLIES" ] && command ssh-add -q "$HOME/.ssh/vps-hermes"; return 0;;
      --apple-use-keychain) ;;
      *) keep+=("$a");;
    esac
  done
  [ ${#keep} -gt 0 ] || return 0
  command ssh-add "${keep[@]}"
}
```

The scratch agent was started with `env -i PATH=/usr/bin:/bin HOME="$X/mac/home" TMPDIR="$TMPDIR" /usr/bin/ssh-agent -s -T`
(`-T`: its socket in the temporary directory; without it OpenSSH 10.3 puts the socket under `$HOME/.ssh/agent`, and the
scratch path was too long for a socket) and killed at the end.

For LAPTOP 3a and 3b on this Mac (no login leaves the Mac):

```zsh
ssh() {
  echo "ssh $*" >> "$HOME/calls"
  case "$STANDIN" in
    refused) return 255;;
    limited) case "$*" in *MARK*) return 1;; *' -R '*) return 255;; *) exec sleep 60;; esac;;
    open) case "$*" in *MARK*) echo MARK; return 0;; *) exec sleep 60;; esac;;
  esac
}
scp() { echo "scp $*" >> "$HOME/calls"; [ "$STANDIN" = open ] && return 0; return 255 }
curl() { echo "curl" >> "$HOME/calls.other"; [ "$STANDIN" = refused ] && printf 000 || printf 302 }
```

**The scratch plist** (`good.plist`; the variant with an extra pair has `-o`, `ServerAliveInterval=30` before `-L`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.dentaledge.hermes-box-tunnel</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/ssh</string>
		<string>-N</string>
		<string>-T</string>
		<string>-o</string>
		<string>BatchMode=yes</string>
		<string>-o</string>
		<string>ExitOnForwardFailure=yes</string>
		<string>-L</string>
		<string>19119:127.0.0.1:9119</string>
		<string>hermes-box</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ThrottleInterval</key>
	<integer>120</integer>
</dict>
</plist>
```

**The blocks that were replaced in this round, as they were run** (the blocks now in the runbook are in the runbook).

The draft of VPS 1:

```bash
tunnel_key_add() {
  local L F="$HOME/.ssh/authorized_keys" O='restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'
  read -r -p "Paste the line: " L
  L=${L%$'\r'}
  [ -f "$F" ] || { echo "REFUSED: $F is missing -- nothing written"; return; }
  [ "$L" = "$O ssh-ed25519 ${L##* }" ] && [ ${#L} -eq $(( ${#O} + 81 )) ] || { echo "REFUSED: not the expected line (other options, a cut key, or extra words) -- nothing written"; return; }
  case "${L##* }" in *[!A-Za-z0-9+/]*) echo "REFUSED: the key holds a character that is not base64 -- nothing written"; return;; esac
  grep -qxF "$L" "$F" && { echo "already present: nothing to do"; return; }
  cp -p "$F" "$F.before-tunnel-key" || return
  [ -z "$(tail -c1 "$F")" ] || echo >> "$F"
  printf '%s\n' "$L" >> "$F" && echo "ADDED: $(grep -cvE '^\s*(#|$)' "$F") key line(s), mode $(stat -c %a "$F")"
}; tunnel_key_add; unset -f tunnel_key_add
```

The draft of LAPTOP 4a:

```bash
P=~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist; B=/usr/libexec/PlistBuddy
if [ "$($B -c 'Print :ProgramArguments:9' "$P" 2>/dev/null)" = "hermes-box" ] && [ "$($B -c 'Print :ProgramArguments' "$P" | grep -c .)" -eq 12 ]; then cp -p "$P" "$P.before-tunnel-key" && $B -c 'Set :ProgramArguments:9 hermes-box-tunnel' "$P" && echo "SWITCHED IN THE FILE"; else echo "NOT SWITCHED: the file is not as expected -- stop"; fi
echo "the alias the login item uses: $($B -c 'Print :ProgramArguments:9' "$P")"
```

The first corrected form of LAPTOP 4a differed from the block in the runbook in its third line only:
`… then cp -p "$P" "$K" && $B -c 'Set :ProgramArguments:9 hermes-box-tunnel' "$P" && echo "SWITCHED IN THE FILE"; elif …`;
the second form had the runbook's third line with `cp -p` in place of `command cp -p`.

The draft of LAPTOP 5b:

```bash
C=~/.ssh/config
if [ -e "$C.before-tunnel-key" ]; then echo "A BACKUP EXISTS: this block was run before -- stop and read the text below"; else cp -p "$C" "$C.before-tunnel-key" && awk 'tolower($1)=="host"||tolower($1)=="match"{inblk=(tolower($1)=="host" && $2=="hermes-box" && NF==2)} !(inblk && tolower($1) ~ /^(usekeychain|addkeystoagent)(=|$)/)' "$C.before-tunnel-key" >| "$C.new" && chmod 600 "$C.new" && mv "$C.new" "$C" && echo "EDITED: $(( $(grep -c '' "$C.before-tunnel-key") - $(grep -c '' "$C") )) line(s) removed"; fi
ssh -G hermes-box | grep -iE '^(usekeychain|addkeystoagent) '
```

The draft of LAPTOP 5c:

```bash
FP=$(ssh-keygen -lf ~/.ssh/vps-hermes.pub | awk '{print $2}')
ssh-add --apple-use-keychain ~/.ssh/vps-hermes; echo "in the agent before: $(ssh-add -l | grep -cF "$FP")"
ssh-add --apple-use-keychain -d ~/.ssh/vps-hermes; echo "in the agent after: $(ssh-add -l | grep -cF "$FP")"
ssh-add --apple-load-keychain >/dev/null 2>&1; echo "supplied by the keychain: $(ssh-add -l | grep -cF "$FP")"; unset FP
```

The draft of LAPTOP 3b was the LAPTOP 3 block of 1.7 without its T2 line. LAPTOP 1, LAPTOP 1b, LAPTOP 3a and
LAPTOP 5a entered the runbook as drafted.

**Teardown**

```bash
docker rm -f rehearsal-server rehearsal-laptop; docker network rm rehearsal-net; docker rmi rehearsal-sshd rehearsal-laptop ubuntu:24.04
pbcopy < /dev/null
```

### 1.D Appendix: how to rebuild the set-up of 1.10

`$X` is a scratch directory. Test values only.

**The stand-in server** (`$X/server/Dockerfile`): Ubuntu 24.04 with `openssh-server`, `sudo` and `openssl`; `hermesops`
in the `sudo` group with a test password; a second account for case L2; test keys kept in `/opt/keys` to build the
cases from; `root` and `hermesops` each start with the same one key. No network, no published port.

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server sudo openssl && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /bin/bash hermesops && usermod -aG sudo hermesops && echo 'hermesops:test-password-0000' | chpasswd \
 && useradd -m -s /bin/bash otheracct \
 && install -d -m 700 -o hermesops -g hermesops /home/hermesops/.ssh && install -d -m 700 /root/.ssh /opt/keys && mkdir -p /run/sshd \
 && for k in admin second tunnel; do ssh-keygen -q -t ed25519 -N "" -C "$k-test" -f /opt/keys/$k; done \
 && ssh-keygen -q -t ecdsa -N "" -C ecdsa-test -f /opt/keys/ec \
 && cp /opt/keys/admin.pub /home/hermesops/.ssh/authorized_keys && chown hermesops:hermesops /home/hermesops/.ssh/authorized_keys && chmod 600 /home/hermesops/.ssh/authorized_keys \
 && cp /opt/keys/admin.pub /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
CMD ["sleep", "infinity"]
```

```bash
docker build -q -t rehearsal-fe-server "$X/server"
docker run -d --rm --name rehearsal-fe-server --network none --hostname rehearsalbox --add-host rehearsalbox:127.0.0.1 --sysctl net.ipv4.ip_unprivileged_port_start=1024 rehearsal-fe-server
# for the made failure B8 only: a second container of the same image, and `chattr +i /root/.ssh` in it before the paste
docker run -d --rm --name rehearsal-fe-server-ro --network none --hostname rehearsalbox --add-host rehearsalbox:127.0.0.1 --cap-add LINUX_IMMUTABLE rehearsal-fe-server
```

(`--hostname` and `--add-host` only stop `sudo` from complaining that it cannot resolve the container's name; the first
start, without them, printed that complaint.) Measured inside: `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`, Ubuntu 24.04.5,
`sudo` 1.9.15p5, `awk` is `mawk`, GNU `grep` 3.11, the kernel setting `1024`.

**The shell and the cases.** The terminal stand-in of 1.C started
`docker exec -it -u hermesops -e TERM=xterm-256color -e 'PS1=B$ ' rehearsal-fe-server bash --norc -i`, pasted `sudo -v`
alone and typed the test password, then pasted the block. Before each case the state was reset as `root`
(`docker exec -u root`): root's and `hermesops`'s files back to the one administrative test key, mode 600; then the
case's own change, for example `cp /opt/keys/second.pub /root/.ssh/authorized_keys` (A2), `ln -s` (B5), or the limited
line built as LAPTOP 1b builds it and appended to the `hermesops` file (L3, A6). File states were read the same way
(owner, mode, the first twelve characters of the SHA-256).

**The login as `root` of 1.10** (inside the container, as `root`; `T` was run with the file in place, moved, and back):

```bash
/usr/sbin/sshd
T() { ssh -n -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/kh -o IdentitiesOnly=yes -o IdentityAgent=none -i /opt/keys/admin root@127.0.0.1 "echo IN" 2>/dev/null; echo "rc=$?"; }
```

**The keychain lines on this Mac.** `$C` is a scratch directory, the working directory of everything below. The driver
is a Python script built on the terminal stand-in; it starts each process with the environment written here and
nothing else, so the `SSH_AUTH_SOCK` of the session that runs it is never read.

```bash
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$C/home" /usr/bin/ssh-keygen -q -t ed25519 -N 'test-passphrase-0000' -C rehearsal-throwaway -f "$C/throwaway-key"
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$C/home" /usr/bin/ssh-agent -D -a a.sock     # a child of the driver, killed by it
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin TERM=xterm-256color LANG=en_US.UTF-8 USER="$USER" LOGNAME="$USER" SHELL=/bin/zsh HOME="$HOME" ZDOTDIR="$C/zd" SSH_AUTH_SOCK=a.sock /bin/zsh -i
```

These three lines are written as commands for the reader; the driver started the three programs itself with exactly
these arguments and environments. `$C/zd/.zshrc` holds `PS1='Z> '` and nothing else. In that zsh, first
`K=<the throwaway key's path>; FP=$(ssh-keygen -lf "$K.pub" 2>/dev/null | awk '{print $2}')`, then the lines of 1.10's
table, each pasted as one bracketed paste. The total was `ssh-add -l 2>/dev/null` piped into a `grep -c` for the word `SHA256` and a colon; the `security`
queries were `security find-generic-password -a "$K" -s SSH >/dev/null 2>&1; echo rc=$?`, the same with `-s OpenSSH`, and
the same without `-s`. At a passphrase prompt the driver typed the test passphrase when the step expected a prompt
(step 1 only) and would otherwise have pressed Ctrl+C and noted that it asked; on a wait longer than 25 seconds it
would have pressed Ctrl+C once, stopped, and killed the agent. Neither happened.

**Teardown**

```bash
docker rm -f rehearsal-fe-server rehearsal-fe-server-ro; docker rmi rehearsal-fe-server ubuntu:24.04
rm -f "$C/throwaway-key" "$C/throwaway-key.pub" "$C/a.sock"
```

## 2 · Step 7e, rehearsed

Measured 2026-10-08 on the laptop, against a throwaway Compose project (`step7e-rehearsal`). Nothing on the box
was touched. Test values only: user `hermesadmin`, passwords `OldTestPassword000000000000`,
`NewTestPassword111111111111` and (second run) `ThirdTestPassword2222222222`.

### 2.1 Sources and what each verified (accessed 2026-10-08)

| Source | Authority | Verified there |
|---|---|---|
| Image source in `hermes-eval-derived:v0.21.5`, `hermes_cli/dashboard_auth/routes.py` lines 335 to 358 | primary | The password login is throttled by a process-local sliding window per client IP: `_PW_RATE_MAX_ATTEMPTS = 10` per `_PW_RATE_WINDOW_SEC = 60.0`; an attempt is recorded only when allowed; a refused one answers 429. The comment says it "resets on restart". |
| `docs/evaluations/2026-10-07-dashboard-password-hash-and-session-secret.md` | earlier measurement | A session survived a restart and a recreate with a signing secret set, and did not without one. |
| This rehearsal (2.2 to 2.8, appendix 2.A) | measurement | The results below. |

### 2.2 Set-up

The throwaway project is the brief's: one service `hermes-agent` (image `hermes-eval-derived:v0.21.5`, command
`gateway run`, `env_file: gateway.env`, `./data:/opt/data`, port `127.0.0.1:29119:9119`). The env file held
`HERMES_DASHBOARD=1`, the username, a line `KEEP_ME=unchanged # a line that must survive byte for byte`, and (as
step 7d leaves the box) a scrypt hash of the old password and a signing secret, both written with
`install-env-secret.py`. The gateway started without a `config.yaml`: **the `config.yaml.example` copy was not
needed.** Set-up output: `install-env-secret: ...PASSWORD_HASH set ... (mode 0600)`,
`install-env-secret: ...SECRET generated ... (mode 0600)`, `hermes-agent running`.

The blocks were run as `bash b0.sh` .. `bash b3.sh` (each a file holding the block as run, in appendix 2.A). **Input:**
the answers to the `read -rs` prompts were supplied on the script's standard input (`printf 'pw\npw\n' | bash b1.sh`),
one line per prompt. This is safe in block 1 because `docker compose exec -T` reads the pipe fed by the inner
`printf`, not the script's standard input, and `read` has already consumed its two lines by then; block 3's `curl`
reads its body from its own pipe. With no terminal, `read -p` does not print its prompt text, so prompts are absent
from the transcript; on the box they appear.

**Substitutions made to the blocks** (all of them; nothing else was changed):

- `sudo ` removed everywhere (including `sudo -v`); `docker compose` run directly.
- `.env` became `gateway.env`: block 0's `grep ... .env`, block 1's `E=/opt/hermes-agent/.env` (now `E="$S/gateway.env"`),
  block 2's `open(".env")` (now `open("gateway.env")`).
- `cd /opt/hermes-agent` became `cd "$S"` (blocks 0, 1, 2), `S` being the scratch directory.
- `bin/install-env-secret.py` became `"$BIN/install-env-secret.py"`; in block 2's one-line Python,
  `sys.path.insert(0, "bin")` became `sys.path.insert(0, "'"$BIN"'")` (the shell closes and reopens the single quotes
  around the path); `BIN` is the repo's `infra/hermes-agent/bin`.
- `--owner-uid 0 --owner-gid 0` removed from the `set` and `generate` calls.
- Port `9119` became `29119` in block 3 (the `Origin` header and the URL).
- Block 2: the two `systemctl start hermes-listener-check.service` lines with their `echo`, the
  `show-listener-check` line and the `systemctl list-timers` line removed (no systemd on the laptop).

The exact text as run is in appendix 2.A, for comparison with the runbook.

### 2.3 The session with the old password, and the four blocks

| Step | Expected | Measured | Match |
|---|---|---|---|
| Sign in with the old password | `login 200` | `login 200` | yes |
| Session before | `200` | `session before 200` | yes |
| Block 0 | the three names only | `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`, `..._SECRET`, `..._USERNAME` | yes |
| Block 1, two different entries (`...111` and `...222`) | `REFUSED`; file unchanged | `REFUSED: ... nothing written`; `cmp` silent (`cmp: identical` printed by an added `&& echo`) | yes |
| Block 1, 23-character entry, twice | same | same | yes |
| Block 1, entry with a `$` (27 characters), twice | same | same | yes |
| Block 1, the real run | hash `set`, secret `removed` (1 line), secret `generated` | `...PASSWORD_HASH set ... (mode 0600)`; `...SECRET removed ... (1 line(s))`; `...SECRET generated ... (mode 0600)` | yes |
| Block 2: stop, recreate | `STOP_EXIT=0`, `UP_EXIT=0`, `hermes-agent running Up ...` | `STOP_EXIT=0`, `UP_EXIT=0`, `hermes-agent running Up 25 seconds` | yes |
| Block 2: hash | `hash: file == container (len 86)` | `hash: file == container (len 86)` | yes |
| Block 2: secret | `secret: in the container (len 44)` | `secret: in the container (len 44)` | yes |
| Block 2: plaintext | `plaintext: not in the container` | `plaintext: not in the container` | yes |
| Block 3 | `401`, `401`, `200` | `old password -> 401`, `wrong password -> 401`, `new password -> 200` | yes |
| Session after (the cookie jar from the old sign-in) | `401` | `session after 401` (what ended it is separated in 2.4) | yes |
| `KEEP_ME` line byte for byte | `1` | `1` | yes |
| Names in the env file | each once | `HERMES_DASHBOARD`, `..._PASSWORD_HASH`, `..._SECRET`, `..._USERNAME`, `KEEP_ME`: 1 each | yes |
| File mode | not in the brief | `600` | extra |

A refused attempt did not touch the file: a copy taken before each refusal compared identical afterwards.

### 2.4 What ended the old session: three controls

Step 7e both replaces the signing secret and recreates the container, so the `401` of 2.3 does not say which of
the two ended the old session. Three controls, each in one fresh throwaway project (set up as in 2.2, the old
password, a signing secret), one change at a time. Sessions were read on `/api/auth/me`. To show a secret changed
or not, only whether the SHA-256 of the container's value was equal before and after was printed.

| Control | What changed in `gateway.env`, then a recreate | Secret in the container | The old session answered |
|---|---|---|---|
| Before any change | nothing | n/a | `200` (sign-in `200`, `/api/auth/me` `200`) |
| A | nothing at all | same | **`200`** |
| B | the secret only (`strip` then `generate`); password unchanged | different | **`401`** |
| B, positive control | the same password, signed in again on the new process | n/a | a fresh session answered **`200`** |
| C | the password hash only (a new password); secret unchanged | same | **`200`** for two sessions taken with the old password (one of them taken after B's recreate, on the then-current secret) |

After C's recreate, signing in with the old password answered `401` and with the new one `200`, and that new session
answered `200`.

What this shows, and no more:

- **A recreate alone does not end a session** (A: `200`, same secret). This agrees with the earlier measurement.
- **Replacing the signing secret ends the sessions signed with the old one** (B: `401`), and a session can be valid on
  the new process (B's fresh sign-in: `200`), so the `401` is not a dead gateway or a failure to read the cookie.
- **Replacing the password alone does not end an old session** (C: `200` while the old password was already refused
  at the sign-in). So the secret replacement in step 7e is not optional: without it, a session taken with the old
  password stays valid after the password change. This is the reason block 1 replaces the secret.
- The `401` after step 7e in 2.3 is therefore caused by the secret replacement (B), not by the recreate (A) and not
  by the new password (C). These controls were each run once, on one process each; the lifetime limit of a session
  (12 hours by default, per the earlier document) was not tested.

### 2.5 Lock-out after repeated failures (measured)

**The first measurement:** fifteen wrong passwords in a row, then the right one, straight after block 3 (which had
made three attempts on the same gateway process):

`401 401 401 401 401 401 401 429 429 429 429 429 429 429 429`, then the right one: `429`.

**How the codes add up.** The source (2.1) allows ten attempts in a sliding 60-second window per client IP.
Every attempt that is allowed counts, successful ones included. Block 3's three attempts (`401`, `401`, `200`) plus
the first seven wrong ones made ten; the eighth was the first `429`. In the controls below, on a fresh process, the
fifteen wrong passwords in one second gave ten `401` and then five `429`: more than ten attempts within 60 seconds
from one address are refused. A mistyped password is answered `401`, not `429`.

**Duration, measured (fresh process, 15 wrong in about one second, then the right password):**

| Time after the start of the burst | Right password every 10 seconds | Wrong password every 5 seconds (a separate run) |
|---|---|---|
| +0 s | `429` | |
| +6 to +56 s | `429` at +10, +20, +30, +40, +50 | `429` at each of +6, +11, +16, +21, +26, +31, +36, +41, +46, +51, +56 |
| +60 or +61 s | **`200`** at +60 | **`401`** at +61 (the lock had ended) |
| +66 to +92 s | | `401` at each of +66, +71, +77, +82, +87, +92; then the right password at +92: `200` |

So the lock ended 56 to 61 seconds after the burst, that is when the ten recorded attempts left the 60-second
window, and it ended without the operator doing anything. The first measurement ("had ended by 68 seconds", one poll)
is consistent with this. **Refused attempts did not extend it, measured:** eleven refused wrong attempts spread
over the lock, and in the first run six refused polls of the right password, did not move the end past about 60
seconds. The poll that got `200` was itself an allowed attempt, and so counted toward the next window.

**Does a recreate empty the count? Yes, measured.** On a fresh process, a burst of fifteen wrong passwords, the right
password `429`; then `docker compose up -d --force-recreate hermes-agent`; the right password, tried as soon as the
new process answered, 10 seconds after the burst began (well inside the 60 seconds), gave **`200`**. The
window lives in the process's memory, so recreating the container clears it. (A plain restart was not run; the
source comment says it resets on restart.)

**What the operator should be told** (follows from the measurements above; the Desktop app and shared-address points
are reasoned, as marked):

- A mistyped password in block 3 shows as `401`, never `429`.
- `429` means the limiter, not a wrong password: more than ten sign-in attempts within 60 seconds from one address,
  successful ones included.
- Block 3 makes three attempts, so it can be run three times within a minute before the fourth run meets a `429`.
- The Desktop app retrying a saved password after step 7e uses the same budget (reasoned from the source: one
  window per client IP; not measured). Behind the box's tunnel the address the dashboard sees may be the same for
  every client, so the Desktop app and a browser may share it (reasoned from the source comment about proxies, not
  measured).
- If block 3 prints `429` on any line: wait two minutes and run block 3 again. The lock ended within 61 seconds in
  every run; two minutes is a margin. Nothing needs to be redone: the password and secret are already replaced.
- Recreating the container empties the count, so block 2 followed at once by block 3 starts from zero.

### 2.6 The second full run

With `ThirdTestPassword2222222222` (27 characters), after a sign-in with the second password. All of: block 0 (three
names); block 1 (three `install-env-secret:` lines as above); block 2 (`STOP_EXIT=0`, `UP_EXIT=0`,
`hermes-agent running Up 25 seconds`, `hash: file == container (len 86)`, `secret: in the container (len 44)`,
`plaintext: not in the container`); block 3 with the second password as "old" and the third as "new"
(`401`, `401`, `200`); the session taken before block 1 answered `200` before and `401` after; `KEEP_ME` still `1`,
each name once, mode `600`. **Same results as the first run: the step is repeatable.**

### 2.7 Bugs found in the blocks

None. Every measured value matched the plan; no block was changed to make it pass.

### 2.8 Block 1 changed form after the first rehearsal

Measured 2026-10-08, in the fix round that followed the first writing of the runbook. **Why.** The repository's test
`infra/hermes-agent/bin/install-env-secret.test.py::test_every_command_in_bring_up_runs` takes every
`bin/install-env-secret.py set|generate|strip ...` command out of the runbook (up to the next line break, `|`, `;` or
backtick), requires `--file` to be followed by a literal absolute path, and runs it. Block 1 as rehearsed in 2.2 and 2.3
wrote `--file "$E"` (the path in a shell variable) and continued its lines with `\` and `&&`; three sub-tests of that
test failed on it (an unterminated escape, and `--file` not an absolute path). That is a limit of the test, which was
left alone; the block changed instead. **Because the block changed, it was rehearsed again; the result of 2.3 does not
carry over by argument.**

**What changed in block 1, all of it:** the variable `E` is gone (`local P Q`), each of the three installer commands
carries the literal path `--file /opt/hermes-agent/.env`, and the chain `... | set ... && strip ... && generate ...`
became three nested `if` statements, so each command ends its line or ends at `;` (the `set` command ends with `; then`).
Blocks 0, 2 and 3 are unchanged (checked by text against appendix 2.A).

**Set-up** as in 2.2: the same throwaway project (`step7e-rehearsal`, image `hermes-eval-derived:v0.21.5`, env file
`gateway.env`, port `127.0.0.1:29119`, `KEEP_ME` line, old password hash and signing secret as step 7d leaves them),
and the same substitutions and no others, now with `--file /opt/hermes-agent/.env` becoming `--file "$S/gateway.env"`. The
as-run files were produced from the runbook text by a script (so the rehearsed text is the runbook's text with those
substitutions), and blocks 0, 2 and 3 as produced were identical to the as-run text in appendix 2.A. **Input:** the
answers to the `read -rs` prompts were fed on standard input (`printf 'pw\npw\n' | bash b1.sh`); `docker compose exec
-T` reads the pipe fed by the block's own `printf`, so it cannot swallow the answers, and the three refusals and the
real run below show the answers arriving. A session was taken with the old password before (`login 200`,
`session before 200`).

| Step | Expected | Measured | Match |
|---|---|---|---|
| Block 1, two different entries | `REFUSED`; file unchanged | `REFUSED: ... nothing written`; `cmp` identical | yes |
| Block 1, 23-character entry, twice | same | same | yes |
| Block 1, entry with a `$`, twice | same | same | yes |
| **Block 1 with the `strip` made to fail** (below) | the failure printed; no `generated` line; secret line untouched | see below | yes |
| Block 0 | the three names only | the three names | yes |
| Block 1, the real run | hash `set`, secret `removed` (1 line), secret `generated` | the three `install-env-secret:` lines | yes |
| Block 2 | `STOP_EXIT=0`, `UP_EXIT=0`, `hermes-agent running Up 25 seconds`, `hash: file == container (len 86)`, `secret: in the container (len 44)`, `plaintext: not in the container` | all six, as expected | yes |
| Block 3 | `401`, `401`, `200` | `old password -> 401`, `wrong password -> 401`, `new password -> 200` | yes |
| Session after (cookie jar of the old sign-in) | `401` | `session after 401` | yes |
| `KEEP_ME` line byte for byte; each name once; mode | `1`; each once; `600` | `1`; each once (`HERMES_DASHBOARD`, the hash, the secret, the username, `KEEP_ME`); `600` | yes |

**The case the nested form handles differently: the removal fails.** The as-run copy of block 1 differed from the
real one in one line: its `strip` command named a directory in the scratch directory (`--file "$S/adir"`) instead of the
env file, so that `strip` would fail while `set` before it succeeded (a made failure; no read-only trick was needed).
Fed two equal 24-character passwords:

- `set` ran: `install-env-secret: HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH set in ... (mode 0600)`, and the hash line
  in the file differed afterwards (a new hash for the new test password).
- `strip` printed one line, `install-env-secret: <the directory> is a symlink or not a regular file`, and failed.
- **`generate` did not run:** no `generated` line was printed; the signing-secret line in the file was byte for byte
  what it was before (`cmp` silent); every other line of the file was identical to the copy taken before the call.
- **The block's own exit status was `0`.** The nested form ends without an error status when the removal fails, so a
  failure shows as a missing third `install-env-secret:` line and the printed failure, not as an exit code. The runbook
  says so ("fewer than three `install-env-secret:` lines: stop"). (Reasoned, not run: the old `&&` chain would also have
  stopped at the failed `strip`, but with a non-zero status for the block.)
- The running gateway was untouched (the step recreates it only in block 2). The real run that followed set the hash again
  and replaced the secret, as in the table.

This also shows the recovery the runbook gives for a failed block 1 ("run it again") on the state this leaves: the hash
already replaced, the secret still the old one; the second run set the hash again, removed the secret and generated a
new one.

**After the change:** `install-env-secret.test.py` passes (26 tests, including `test_every_command_in_bring_up_runs`).
Hash and secret values are described here, never shown.

### 2.9 Text added around blocks 1, 2 and 3 after the review of the runbook

Second fix round, 2026-10-08. **No block of step 7e changed, and nothing of section 2 was run again.** The review found
outputs of these blocks that the runbook gave no instruction for; the text now has one for each. What supports each
sentence:

- *Block 1, the state after a partial run.* From 2.8's made failure: the hash's `set` line, the removal's failure
  message, no `generated` line; the file then holds the new hash and the old secret, and the next run completed. The
  other partial state (the removal works, `generate` fails, no secret left in the file) was **not** rehearsed; the runbook
  says so and points at block 2's `secret:` line.
- *Block 2.* A stop instruction for `STOP_EXIT` or `UP_EXIT` not `0`, `check_while_stopped_rc=0`, a missing `secret:`
  line, `PLAINTEXT STILL SET`, `check_after_rc` not `0` and a missing timer line. None of these outputs was produced
  in a rehearsal: every run of block 2 printed the expected lines (2.3, 2.6, 2.8), and the four listener-check lines have
  not run at all. The instructions are **reasoned from the block's text**: for example, the `secret:` line comes from an
  `awk` that prints once per line it is given, so no line means the container returned none.
- *Block 2, what the laptop rehearsal changed.* The runbook's sentence now names every substitution of 2.2, not only
  the four listener-check lines.
- *Block 3.* `old password -> 401` is also what a mistyped old password prints (the wrong-password line of every run:
  `401`); the runbook now says that the proof is block 2's `hash: file == container` line, and that `old password -> 200`
  can also mean block 2 did not recreate the gateway (reasoned: 2.8 found the running gateway untouched by block 1, so
  until a recreate it still holds the old hash). It also says to clear the clipboard after the last paste
  (`pbcopy < /dev/null`: run on this Mac in 1.8, the clipboard then held `0` characters).

### Not measured

- The Desktop app's own behaviour when its saved password stops working.
- The listener-check lines of block 2 (`systemctl`, `show-listener-check`, the timer): the laptop has no systemd.
- The real box: `sudo` (including `sudo` inside the pipes of blocks 1 and 2), `--owner-uid 0 --owner-gid 0`, root
  ownership of the real file, and the box's own port 9119.
- The box's own image and env-file wiring, as opposed to `hermes-eval-derived:v0.21.5` and `gateway.env`.
- A real terminal's behaviour for the hidden `read -rs` prompts: all input was piped.
- The three refusals of block 1 (two different entries, 23 characters, an entry with a `$`) were each run once.
- A plain restart clearing the limiter (a recreate was measured), and several clients sharing one address (from the
  source, not run).
- The 12-hour lifetime of a session, and the controls of 2.4 beyond one run each.

### 2.A Appendix: the four blocks as run

Each ran as a script file (`bash b0.sh` .. `bash b3.sh`), the first line setting the laptop's two shell variables
(`S` the scratch directory, `BIN` the repo's `infra/hermes-agent/bin`). They hold no secret.

```bash
##### BLOCK 0, exactly as run (first line = the two shell variables set for the laptop: S = scratch dir, BIN = the repo's infra/hermes-agent/bin)
S=<scratch>/step7e-rehearsal; BIN=<repo>/infra/hermes-agent/bin
cd "$S" && grep -oE '^HERMES_DASHBOARD_BASIC_AUTH[A-Z_]*' gateway.env | sort

##### BLOCK 1, exactly as run (first line = the two shell variables set for the laptop: S = scratch dir, BIN = the repo's infra/hermes-agent/bin)
S=<scratch>/step7e-rehearsal; BIN=<repo>/infra/hermes-agent/bin
step7e_set() {
  local P Q E="$S/gateway.env"
  cd "$S" || return
  read -rs -p "NEW dashboard password: " P; echo
  read -rs -p "The same again: " Q; echo
  if [ "$P" = "$Q" ] && [ ${#P} -ge 24 ] && case "$P" in *[!A-Za-z0-9]*) false;; *) true;; esac; then
    printf '%s' "$P" | docker compose exec -T -w /opt/hermes hermes-agent python3 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
      | python3 "$BIN/install-env-secret.py" set --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --stdin \
      && python3 "$BIN/install-env-secret.py" strip --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET \
      && python3 "$BIN/install-env-secret.py" generate --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600
  else
    echo "REFUSED: the two entries differ, or it is under 24 characters, or it holds something other than letters and digits -- nothing written"
  fi
}; step7e_set; unset -f step7e_set

##### BLOCK 2, exactly as run (first line = the two shell variables set for the laptop: S = scratch dir, BIN = the repo's infra/hermes-agent/bin)
S=<scratch>/step7e-rehearsal; BIN=<repo>/infra/hermes-agent/bin
cd "$S"
docker compose stop hermes-agent; echo "STOP_EXIT=$?"
docker compose up -d --force-recreate hermes-agent; echo "UP_EXIT=$?"
sleep 25; docker compose ps -a hermes-agent --format '{{.Service}} {{.State}} {{.Status}}'
F=$(python3 -c 'import sys; sys.path.insert(0, "'"$BIN"'"); import client_audit_lib as C; print((C.env_values(open("gateway.env").read(), "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH") or [""])[0])')
C=$(docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)
[ ${#C} -eq 86 ] && [ "$F" = "$C" ] && echo "hash: file == container (len ${#C})" || echo "HASH DIFFERS (file ${#F}, container ${#C}): STOP"; unset F C
docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_SECRET | awk '{print "secret: in the container (len " length($0) ")"}'
docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD >/dev/null && echo "PLAINTEXT STILL SET" || echo "plaintext: not in the container"

##### BLOCK 3, exactly as run (first line = the two shell variables set for the laptop: S = scratch dir, BIN = the repo's infra/hermes-agent/bin)
S=<scratch>/step7e-rehearsal; BIN=<repo>/infra/hermes-agent/bin
step7e_login() {
  local OLD NEW
  read -rs -p "OLD dashboard password: " OLD; echo
  read -rs -p "NEW dashboard password: " NEW; echo
  login() { printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' "$1" | curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:29119' --data @- http://127.0.0.1:29119/auth/password-login; }
  echo "old password -> $(login "$OLD")"
  echo "wrong password -> $(login "not-the-password-0000")"
  echo "new password -> $(login "$NEW")"
  unset -f login
}; step7e_login; unset -f step7e_login
```

### 2.B Appendix: block 1 as run after it changed form (2.8)

Block 1 only; blocks 0, 2 and 3 are as in 2.A. The file started with the same first line as in 2.A (`S` and `BIN` set for
the laptop). It holds no secret.

```bash
step7e_set() {
  local P Q
  cd "$S" || return
  read -rs -p "NEW dashboard password: " P; echo
  read -rs -p "The same again: " Q; echo
  if [ "$P" = "$Q" ] && [ ${#P} -ge 24 ] && case "$P" in *[!A-Za-z0-9]*) false;; *) true;; esac; then
    if printf '%s' "$P" | docker compose exec -T -w /opt/hermes hermes-agent python3 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
      | python3 "$BIN/install-env-secret.py" set --file "$S/gateway.env" --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --stdin; then
      if python3 "$BIN/install-env-secret.py" strip --file "$S/gateway.env" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET; then
        python3 "$BIN/install-env-secret.py" generate --file "$S/gateway.env" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600
      fi
    fi
  else
    echo "REFUSED: the two entries differ, or it is under 24 characters, or it holds something other than letters and digits -- nothing written"
  fi
}; step7e_set; unset -f step7e_set
```

The made failure of 2.8 used this text with one line changed: the `strip` line named `--file "$S/adir"` (a directory) in
place of `--file "$S/gateway.env"`.

## 3 · The config edit and the `Match` count, rehearsed

Measured 2026-10-08, in the same fix round. Nothing on the box was touched, and nothing on this laptop's own SSH
configuration: the `awk` ran on scratch files only.

### 3.1 LAPTOP 5's `awk`, with this laptop's own `awk`

**Why.** The `awk` of step 7f that removes `UseKeychain` and `AddKeysToAgent` from the `hermes-box` block, as first
written, tracked only `Host ` lines that start in column 0 and did not end the block at a `Match` line, so an indented
`Host` line or a `Match` block after `hermes-box` would have lost the two settings too (found by reading; shown below on
the same input). **The program now in the runbook:**

```
/^[[:space:]]*([Hh]ost|[Mm]atch)[[:space:]]/{inblk=(tolower($1)=="host" && $2=="hermes-box" && NF==2)} !(inblk && tolower($1) ~ /^(usekeychain|addkeystoagent)$/)
```

**Run** with this laptop's `awk` (BSD awk, `awk version 20200816`: the one the operator has), on a scratch input, with the
program taken out of the runbook text by a script and passed as `awk "$(cat prog.awk)" cfg.in > cfg.out`. The input held
the `hermes-box` block with the two settings and an `IdentityFile`, then an indented `Host other-indented` line with
the two settings, a `Match host x` block with the two settings, a `Host hermes-box-tunnel` block with the two, a
`Host hermes-box other` block with the two, and a final `Host *` block with the two. Result:

```
awk rc=0
4,5d3
<   UseKeychain yes
<   AddKeysToAgent yes
```

`diff` showed exactly two deletions (lines 4 and 5, inside the `hermes-box` block) and no addition; every other line,
including the two settings in each of the four other places, survived byte for byte. Run again on its own output, the
program changed nothing (`cmp` silent). BSD awk accepted the program on the first try (no correction was needed).
(This program and the line around it were replaced after the review of the runbook: LAPTOP 5b and its rehearsal are
in 1.8.)

For the record, the **previous program** on the same input deleted six lines: the two in the `hermes-box` block and, in
addition, the two after the indented `Host other-indented` line (lines 8 and 9) and the two in the `Match host x` block
(lines 12 and 13). That is the defect the new program removes.

**Not measured:** `gawk` or `mawk` (the operator's `awk` is the one tested); the whole LAPTOP 5 first line (the `cp -p`,
the redirection into `~/.ssh/config` and the `chmod`), which was not run; a `Host hermes-box # comment` line (it has more
than two fields, so the block is not recognised and the settings stay: a safe failure); `Host=hermes-box` written with an
equals sign; the real configuration (never read); `ssh-add --apple-use-keychain -d` and the keychain. **Note 2026-10-08:**
`ssh-add --apple-use-keychain -d` was run against the login keychain with a throwaway key (1.10).

### 3.2 The `Match` count of the security review (checklist item D1.7)

BRING-UP's "A security review", step 2, now counts the `Match` lines of the sshd configuration:

```bash
sudo sh -c 'cat /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -ciE "^[[:space:]]*match[[:space:]]"'
```

Rehearsed in the throwaway server container of 1.7 (Ubuntu 24.04, OpenSSH 9.6p1), as `root` (`docker exec -u root`),
with the command taken out of the runbook text by a script and without the `sudo ` (the container has no `sudo`):

| State of the container's sshd configuration | Expected | Measured |
|---|---|---|
| As built (the stock file, whose one `Match` mention is a comment, plus the test drop-in) | `0` | `0` |
| A `Match User nobody` block (with one option under it) appended to the drop-in | `1` | `1` |
| Plus an indented, lower-case `  match all` line, for the case the `[[:space:]]*` and `-i` are there for | `2` | `2` |

The stock file's commented `#Match` line is not counted, as intended (a `grep -ci match` on the file gave `1`; the
command printed `0`). **Not measured:** the box's own configuration (it is read at the next review, where D1.7 cannot
pass without the number); `sudo` on the box; an `Include` of a path other than `sshd_config.d/*.conf` (not read by the
command: reasoned, which is why another number needs a statement of what each block sets, and `0` is a floor for the
files it reads, not a proof about files it does not).

### 3.3 The start-time lines of the security review (checklist item D4.6): not rehearsed

BRING-UP's "A security review", step 2, starts with a loop that prints each service's start time
(`systemctl show <unit> -p ActiveEnterTimestamp --value` for four units), then `uptime -s`, then the last six
`Start-Date` and `Commandline` lines of `/var/log/apt/history.log`. They were added in the first writing of the runbook
and appeared nowhere in this document. Second fix round, 2026-10-08: run as written (no `sudo` in them) as `root` in the
stand-in server of 1.8, which has **no systemd**: the loop printed `systemctl: command not found` four times and each
unit's name with nothing after it; `uptime -s` printed the container's start time; the `grep` printed six lines of the
image's own update log. So only the last two commands are rehearsed, and the loop is **not**: it runs for the first time
on the box. The lines only read. The runbook says so at the block and describes a healthy output (four names each
followed by a date and time, the boot time, up to six log lines); that description is **reasoned** from the commands, not
measured.

In 3.2, the runbook's text now also says what the `Match` count does not cover: it reads two fixed places, prints `0` when
neither can be read, and does not count a `Match` in a file brought in by an `Include` of another directory (3.2's "Not
measured" already says the last; for the second, the same command with two paths that do not exist was run in the
stand-in server and printed `0`).

### Not measured (section 3)

- Everything listed under 3.1 and 3.2 as "Not measured".
- The `Match` count's command inside the review's own flow (`collect-review-evidence.py`, D1.7): only the command was run.
