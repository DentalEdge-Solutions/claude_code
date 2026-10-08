# Evaluation — the limited SSH key for the dashboard tunnel, and replacing the dashboard password

> **Date:** 2026-10-07 (measured 2026-10-08) · **Asked:** can a second SSH key on the box be limited to carry one
> local port-forward to `127.0.0.1:9119` and do nothing else? · **Method:** the candidate `authorized_keys`
> option string was run against a throwaway OpenSSH server in Docker on the laptop, with a fixed set of tests and
> a control key. Nothing on the box was touched. This document has three sections: section 1 is this measurement
> (1.7 and appendix 1.B were added when the runbook blocks were rehearsed as written); section 2 (step 7e, rehearsed)
> is the rehearsal of the dashboard password replacement, measured 2026-10-08 (2.8 and appendix 2.B added at the same
> time); section 3 holds the two rehearsals of the same round that belong to neither: the `awk` that edits the laptop's
> SSH config, and the `Match` count of the security review.

## 1 · The limited key, measured against a throwaway server

### 1.1 Sources, authority and what each verified (accessed 2026-10-07)

| Source | Authority | Verified there |
|---|---|---|
| Local `man sshd`, section "AUTHORIZED_KEYS FILE FORMAT" (laptop OpenSSH 10.3p1) | primary | `restrict` disables port, agent and X11 forwarding, PTY allocation and `~/.ssh/rc`; its list does not include command execution, so a `command=` is needed to stop commands. `port-forwarding` re-enables forwarding in both directions ("Enable port forwarding previously disabled by the `restrict` option"). `permitopen="host:port"` limits `-L`; `permitlisten="[host:]port"` limits `-R`. `permitlisten` has no "none" form, so a port that cannot be bound stands in for it. |
| Local `man ssh-add` (`--apple-use-keychain`) | primary | With `-d`, `--apple-use-keychain` removes the passphrase from the keychain as well. |
| Image source `hermes_cli/dashboard_auth/routes.py` (section 2.1) | primary | The password-login throttle: 10 attempts per 60 s per client IP, in memory. |
| The box's OpenSSH version | **not yet known** | The operator was asked and has not answered. Until then the rehearsal used `ubuntu:24.04`, which ships the version in 1.2. **The box's version is still to be confirmed against it.** |
| This rehearsal (1.2 to 1.6, appendix 1.A) | measurement | The results below. |

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
the floor leaves one character of room and is a second line of defence, not the main one.

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
  expects.
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

**LAPTOP 3, second run, with `-n` in T2, limited key** (the block exactly as in the runbook, typed into `zsh -i`):

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
- *LAPTOP 4 on a second run, or with the login item not loaded.* `launchctl bootout` prints an error when the login item
  is not loaded, and (read from the commands) `launchctl bootstrap` prints one when it already is; the runbook says that
  such a message is not a failure by itself. **LAPTOP 4 was NOT rehearsed**: it edits and reloads the real login item of
  this laptop.

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
- VPS 0 and VPS 1 on the box (they ran as `hermesops` in a container on this laptop).

### Not measured

- The box's real OpenSSH version, its own `sshd_config` (a global `AllowTcpForwarding`, any `Match` block that
  could override the key's options) and its `net.ipv4.ip_unprivileged_port_start` (1.1, 1.4).
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
S=/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/d39c558e-d127-4fdd-9112-e44fbb972f9d/scratchpad/step7e-rehearsal; BIN=/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cd "$S" && grep -oE '^HERMES_DASHBOARD_BASIC_AUTH[A-Z_]*' gateway.env | sort

##### BLOCK 1, exactly as run (first line = the two shell variables set for the laptop: S = scratch dir, BIN = the repo's infra/hermes-agent/bin)
S=/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/d39c558e-d127-4fdd-9112-e44fbb972f9d/scratchpad/step7e-rehearsal; BIN=/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
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
S=/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/d39c558e-d127-4fdd-9112-e44fbb972f9d/scratchpad/step7e-rehearsal; BIN=/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
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
S=/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/d39c558e-d127-4fdd-9112-e44fbb972f9d/scratchpad/step7e-rehearsal; BIN=/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
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

For the record, the **previous program** on the same input deleted six lines: the two in the `hermes-box` block and, in
addition, the two after the indented `Host other-indented` line (lines 8 and 9) and the two in the `Match host x` block
(lines 12 and 13). That is the defect the new program removes.

**Not measured:** `gawk` or `mawk` (the operator's `awk` is the one tested); the whole LAPTOP 5 first line (the `cp -p`,
the redirection into `~/.ssh/config` and the `chmod`), which was not run; a `Host hermes-box # comment` line (it has more
than two fields, so the block is not recognised and the settings stay: a safe failure); `Host=hermes-box` written with an
equals sign; the real configuration (never read); `ssh-add --apple-use-keychain -d` and the keychain.

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

### Not measured (section 3)

- Everything listed under 3.1 and 3.2 as "Not measured".
- The `Match` count's command inside the review's own flow (`collect-review-evidence.py`, D1.7): only the command was run.
