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
| Image source `hermes_cli/dashboard_auth/routes.py` (section 2.1) | primary | The password-login throttle: 10 attempts per 60 s per client IP, in memory. |
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

Measured 2026-10-08 on the laptop, against a throwaway Compose project (`step7e-rehearsal`). Nothing on the box
was touched. Test values only: user `hermesadmin`, passwords `OldTestPassword000000000000`,
`NewTestPassword111111111111` and (second run) `ThirdTestPassword2222222222`.

### 2.1 Sources and what each verified (accessed 2026-10-08)

| Source | Authority | Verified there |
|---|---|---|
| Image source in `hermes-eval-derived:v0.21.5`, `hermes_cli/dashboard_auth/routes.py` lines 335 to 358 | primary | The password login is throttled by a process-local sliding window per client IP: `_PW_RATE_MAX_ATTEMPTS = 10` per `_PW_RATE_WINDOW_SEC = 60.0`; an attempt is recorded only when allowed; a refused one answers 429. The comment says it "resets on restart". |
| This rehearsal (2.2 to 2.6) | measurement | The results below. |

### 2.2 Set-up

The throwaway project is the brief's: one service `hermes-agent` (image `hermes-eval-derived:v0.21.5`, command
`gateway run`, `env_file: gateway.env`, `./data:/opt/data`, port `127.0.0.1:29119:9119`). The env file held
`HERMES_DASHBOARD=1`, the username, a line `KEEP_ME=unchanged # a line that must survive byte for byte`, and (as
step 7d leaves the box) a scrypt hash of the old password and a signing secret, both written with
`install-env-secret.py`. The gateway started without a `config.yaml`: **the `config.yaml.example` copy was not
needed.** Set-up output: `install-env-secret: ...PASSWORD_HASH set ... (mode 0600)`,
`install-env-secret: ...SECRET generated ... (mode 0600)`, `hermes-agent running`.

The blocks were run as `bash b0.sh` .. `bash b3.sh` (each a file holding the block as adapted below). **Input:**
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

The exact text as run is kept in the working notes (`task-2-blocks-as-run.txt`, git-ignored) for comparison with
the runbook.

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
| Session after (the cookie jar from the old sign-in) | `401` | `session after 401` | yes |
| `KEEP_ME` line byte for byte | `1` | `1` | yes |
| Names in the env file | each once | `HERMES_DASHBOARD`, `..._PASSWORD_HASH`, `..._SECRET`, `..._USERNAME`, `KEEP_ME`: 1 each | yes |
| File mode | not in the brief | `600` | extra |

A refused attempt did not touch the file: a copy taken before each refusal compared identical afterwards.

### 2.4 Lock-out after repeated failures (measured)

Fifteen wrong passwords in a row, then the right one, straight after block 3 (which had made three attempts on the
same gateway process):

`401 401 401 401 401 401 401 429 429 429 429 429 429 429 429`, then the right one: `429`.

So the dashboard does refuse the right password for a while after failures. The count fits the source (2.1): ten
attempts are allowed in a 60-second sliding window per IP, and the three of block 3 plus the first seven here made
ten; the eighth was the first refused. **Duration, measured:** polled once a minute; the first poll, 68 seconds
after the burst (13:20:53Z to 13:22:01Z), already gave `200`. So the lock lasts under about a minute, and it ends
without the operator doing anything. Refused attempts are not recorded, so repeating them does not extend it. The
window is in the process's memory: a gateway restart also clears it (stated in the source comment; the restart
case was not run).

**What the runbook should say:** the step makes at most three login attempts (block 3), under the limit of ten; if
a mistyped attempt is followed by `429`, wait one minute and run block 3 again. Behind the box's tunnel the address
the dashboard sees may be the same for every client, so the Desktop app and a browser share the budget (reasoned
from the source comment about proxies, not measured).

### 2.5 The second full run

With `ThirdTestPassword2222222222` (27 characters), after a sign-in with the second password. All of: block 0 (three
names); block 1 (three `install-env-secret:` lines as above); block 2 (`STOP_EXIT=0`, `UP_EXIT=0`,
`hermes-agent running Up 25 seconds`, `hash: file == container (len 86)`, `secret: in the container (len 44)`,
`plaintext: not in the container`); block 3 with the second password as "old" and the third as "new"
(`401`, `401`, `200`); the session taken before block 1 answered `200` before and `401` after; `KEEP_ME` still `1`,
each name once, mode `600`. **Same results as the first run: the step is repeatable.**

### 2.6 Bugs found in the blocks

None. Every measured value matched the plan; no block was changed to make it pass.

### Not measured

- The Desktop app's own behaviour when its saved password stops working.
- The listener-check lines of block 2 (`systemctl`, `show-listener-check`, the timer): the laptop has no systemd.
- The real box: `sudo`, `--owner-uid 0 --owner-gid 0`, file ownership, and the box's own port 9119.
- A restart clearing the throttle, and several clients sharing one address (both from the source, not run).
