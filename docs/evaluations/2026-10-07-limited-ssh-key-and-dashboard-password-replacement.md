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
