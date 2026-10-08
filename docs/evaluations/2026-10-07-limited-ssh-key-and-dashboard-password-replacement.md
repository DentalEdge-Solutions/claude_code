# Evaluation — the limited SSH key for the dashboard tunnel, and replacing the dashboard password

> **Date:** 2026-10-07 (measured 2026-10-08) · **Asked:** can a second SSH key on the box be limited to carry one
> local port-forward to `127.0.0.1:9119` and do nothing else? · **Method:** the candidate `authorized_keys`
> option string was run against a throwaway OpenSSH server in Docker on the laptop, with a fixed set of tests and
> a control key. Nothing on the box was touched. This document has two sections: section 1 is this measurement;
> section 2 (step 7e, rehearsed) is added later.

## 1 · The limited key, measured against a throwaway server

### 1.1 Sources, authority and what each verified (accessed 2026-10-07)

| Source | Authority | Verified there |
|---|---|---|
| Local `man sshd`, section "AUTHORIZED_KEYS FILE FORMAT" (laptop OpenSSH 10.3p1) | primary | `restrict` disables port, agent and X11 forwarding, PTY allocation and `~/.ssh/rc`; its list does not include command execution, so a `command=` is needed to stop commands. `port-forwarding` re-enables forwarding in both directions ("Enable port forwarding previously disabled by the `restrict` option"). `permitopen="host:port"` limits `-L`; `permitlisten="[host:]port"` limits `-R`. `permitlisten` has no "none" form, so a port that cannot be bound stands in for it. |
| Local `man ssh-add` (`--apple-use-keychain`) | primary | With `-d`, `--apple-use-keychain` removes the passphrase from the keychain as well. |
| The box's OpenSSH version | **not yet known** | The operator was asked and has not answered. Until then the rehearsal used `ubuntu:24.04`, which ships the version in 1.2. **The box's version is still to be confirmed against it.** |
| This rehearsal (1.2 to 1.5) | measurement | The results below. |

### 1.2 The throwaway server

`docker build` of `ubuntu:24.04` plus `openssh-server` and `python3`; account `hermesops` (unprivileged, bash);
`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`, `LogLevel VERBOSE`;
three listeners as that account: HTTP on 9119 (the permitted target), HTTP on 9120 (a forbidden target), and a
unix socket at `/tmp/t.sock` that answers `UNIX-REACHED` once. Published on `127.0.0.1:2222` only.

Measured version line: `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19, OpenSSL 3.0.13 30 Jan 2024`

Key file, as used (test keys, bodies not kept):

```
<admin key line, no options>
restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false" ssh-ed25519 <test key>
```

Every client call used `-F none`, `IdentityAgent=none`, `IdentitiesOnly=yes`, `BatchMode=yes`, a scratch
known-hosts file and scratch keys, so none of the laptop's own keys, agent or config took part.

### 1.3 The six tests with the limited key (measured 2026-10-08)

Run as written in the plan, with one change: `kill %1` became `kill $!` (a script has no job table).

| Test | Expected | Measured | Match |
|---|---|---|---|
| T1 forward to 9119 | `200` | `200` | yes |
| T2 command `echo MARK` | `[]` and `rc=1` | `[] rc=1` (sshd log: `forced-command (key-option) '/bin/false'`) | yes |
| T3 terminal (`-tt`) | `PTY allocation request failed`, no prompt | `PTY allocation request failed on channel 0` | yes |
| T4 forward to 9120 | `000` | `000` (log: `request to connect to host 127.0.0.1 port 9120, but the request was denied`) | yes |
| T5a remote forward, port 29123 | `rc=255` | `rc=255` (log: `request to remote forward to host 127.0.0.1 port 29123, but the request was denied`) | yes |
| T5b remote forward, the permitted port 1 | `rc=255` | **first run: no exit; `ssh` was still running 8 s later** (the forward was established). **Corrected run: `rc=255`** | **differs, then matches (see 1.4)** |
| T6 forward to a unix socket | `[]` | `[]` (log: `request to connect to path /tmp/t.sock, but the request was denied`) | yes |
| T7 sftp | not `rc=0` | `rc=1` | yes |

T1 to T7 were run twice: once in the container as first built, and once in a container recreated with the
setting described in 1.4. Apart from T5b, both runs gave the values above.

### 1.4 T5b: the test depended on the container, not the key

The plan expects an unprivileged account to be unable to bind port 1. In the container as first built it could:
Docker sets `net.ipv4.ip_unprivileged_port_start` to `0` inside containers, and `hermesops` bound
`127.0.0.1:1` directly with Python (`hermesops bound port 1 OK`). So the remote forward on port 1 was
**established**, and `ssh -N` ran on instead of exiting `255`. The original T5b therefore did not hold, and
that is recorded as measured. It says nothing against the key line: `permitlisten="127.0.0.1:1"` is an allowance,
and what makes it harmless is that the account cannot bind a port below 1024.

The corrected test: the same image, the container recreated with
`--sysctl net.ipv4.ip_unprivileged_port_start=1024` (the Linux and Ubuntu default), same key, same command.
Result: `rc=255`, and the sshd log says `bind [127.0.0.1]:1: Permission denied`. A direct bind as `hermesops`
failed with `[Errno 13] Permission denied`. So the refusal is for the stated reason.

**What this means for the box:** the key line is only as tight as the box's `net.ipv4.ip_unprivileged_port_start`.
If the box (or any container it runs this in) has it at `0`, the key can open a listener on `127.0.0.1:1` on the
box. That is a loopback listener for another local process, not a path to a shell, but it is a gap. The box's
value is **not measured**; the runbook should read it (`cat /proc/sys/net/ipv4/ip_unprivileged_port_start`) and
the checklist should expect `1024` or higher.

### 1.5 The control and the box block's refusals

The control (admin key, no options; the unix listener had not been used, so no restart was needed):

| Test | Expected | Measured | Match |
|---|---|---|---|
| C-T2 command | `[MARK] rc=0` | `[MARK] rc=0` | yes |
| C-T4 forward to 9120 | `200` | `200` | yes |
| C-T6 unix socket | `[UNIX-REACHED]` | `[UNIX-REACHED]` | yes |

So the refusals above are the key's options, not a broken test.

The `tunnel_key_add` function from the box block, run as `hermesops` in the container. The function and each
line were fed on standard input (`docker exec -i -u hermesops tunnel-rehearsal bash -s` with the function, then
one call followed by the line it reads), because there was no terminal for `-it`.

One change to the plan's input: the container's file already held the limited key (it was baked in at build), so
the "right line" in the calls below is a **second, fresh test key** with the same option string; with the first
key the answer can only be `already present`, which was also tried.

| Call | Expected | Measured | Match |
|---|---|---|---|
| line cut after `ssh-ed25519` | `REFUSED`, file unchanged | `REFUSED: not the expected line -- nothing written`; 2 lines before, 2 after; no backup file made | yes |
| bare public key, no options | `REFUSED`, file unchanged | `REFUSED: not the expected line -- nothing written`; 2 lines before, 2 after | yes |
| right line, fresh key | `ADDED` | `ADDED: 3 key line(s), mode 600`; 3 lines; backup holds the 2 earlier lines | yes |
| the same line again | `already present` | `already present`; still 3 lines | yes |
| the first limited key's line (already in the file) | not planned | `already present`; still 3 lines | extra |

The cut line was refused by the first check (it lacks `AAAA`), not by the length check. The right line was 181
characters; the length floor in the function is 180, so the floor has very little room and is a second line of
defence, not the main one.

### Not measured

- The box's real OpenSSH version and its `net.ipv4.ip_unprivileged_port_start` (1.1, 1.4).
- A key with `restrict` and **no** `command=`: every test ran with `command="/bin/false"`, so "`restrict` alone does
  not stop commands" rests on the manual, not on a run.
- IPv6 (`::1`) forwards, and `-R` with a bind address other than `127.0.0.1`.
- `-D` (dynamic) forwards and agent forwarding; neither was run, though `restrict` without `agent-forwarding`
  disables the latter.
- A client older or newer than the laptop's OpenSSH 10.3p1 (LibreSSL); the server was 9.6p1.
- That the same refusals hold when the key is the one actually used by the Desktop app's tunnel.

## 2 · Step 7e, rehearsed

To be added by the step 7e rehearsal.
