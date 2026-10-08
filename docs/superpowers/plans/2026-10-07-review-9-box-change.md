# Review #9 box change: a new dashboard password, a limited key for the laptop link, service start times, findings F55 to F57 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> One change, one fingerprint change, one security review (#9). Build order: this plan, an implementer, an
> independent review, then ask the operator before pushing. Tasks 0, 9 and 10 are the operator's, block by
> block; the build runs nothing on the box.

> **SUPERSEDED BLOCKS — do not paste from this file.** The command blocks in Tasks 1, 2 and 6 below are the first drafts. Rehearsal and review found several of them unsafe (seven logins in one paste with no gate; a login-item edit that inserts instead of replacing; a keychain removal before the passphrase is proven) and replaced them. The blocks to run are ONLY those in `infra/hermes-agent/deploy/BRING-UP.md`, steps 7e and 7f; what was measured is in `docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`. The checklist text in Task 5 was also revised: `CHECKLIST.md` is the text that counts.

**Goal:** Close review #8's open entries on the box (a dashboard password that was once plaintext, an always-on
link that uses the administrative key, restarts a review cannot see) and let review #9 judge the result.

**Architecture:** Two new probes in the existing box collector (`d1_7`, `d4_6`), each a function in
`bin/collect-review-evidence.py` registered in `PROBES`, each matched by a checklist item. Two new runbook
procedures in `BRING-UP.md` (step 7e and the limited key), each rehearsed on the laptop first and recorded in
`docs/evaluations/`. No other program changes.

**Tech Stack:** Python 3 stdlib only (`unittest`, `ast`, `base64`, `calendar`), bash runbook blocks, OpenSSH
`authorized_keys` options, Docker on the laptop for the two rehearsals.

**Spec:** `docs/superpowers/specs/2026-10-07-review-9-box-change-design.md`

## Global Constraints

- Python stdlib only. No value of any secret is ever printed, logged or written: names, labels, ports, counts,
  timestamps, key types, 12-character fingerprints and fixed words only. What cannot be measured is
  `could-not-check`, never a healthy-looking value.
- No client name, customer id, hostname, non-loopback address, full fingerprint or credential value in any
  file, commit message or conversation. A public key BODY and a key COMMENT never enter a bundle.
- `CHECKLIST.md` goes to `version: 1.18`; every bullet of an item stays one line;
  `python3 infra/hermes-agent/bin/check-checklist-version.py --base main` exits 0.
- The D10.6 pinned `mcp_servers` canonical sha256 must not change.
- The agent never reads a `.env` file and never runs a shell command that names one (the project's
  secret-read guard). Rehearsal env files are named `gateway.env`.
- The limited key's option string, used verbatim wherever this plan says `TUNNEL_OPTS`:
  `restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"`.
  Task 1 measures it. If Task 1 changes it, change it in: Task 3's tests, Task 5's D1.7 text, Task 6's two
  blocks, and this line.
- Before every commit that touches `infra/hermes-agent/`: `infra/hermes-agent/bin/run-bin-tests.sh`,
  `python3 infra/hermes-agent/deploy/units.test.py`, `python3 infra/hermes-agent/deploy/provision.test.py` and
  `node scripts/run-all-tests.js` pass.
- Commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Branch `feat/review-9-box-change`.
  No push, no PR, without the operator's word; the operator merges.
- Operator blocks: one block per paste, labelled VPS or LAPTOP; a block that prompts is one function followed
  by its call, pasted alone, after `sudo -v` alone. Ask for output "starting after the prompt line".

## Review Focus

Conditions the spec implies and a person will meet. Each has a test or a measured step in the named task.

1. **An `authorized_keys` option whose quoted value holds a space or a comma** (`command="/bin/echo a,b c"`):
   it is one option, not three. Task 3, `test_a_quoted_value_with_a_space_and_a_comma_is_one_option`.
2. **An option value that holds an address** (`from="203.0.113.7"`): the bundle shows `from=<withheld>`, never
   the address. Task 3, `test_an_address_or_an_odd_command_is_withheld`.
3. **A start time that is empty (the unit is not running) or not in UTC:** `could-not-check`, never a `false`
   that reads as "not restarted". Task 4, `test_a_time_that_is_empty_or_not_utc_is_could_not_check`.
4. **A module a service imports inside a function, or through another module:** it is in the file list.
   Task 4, `test_an_import_inside_a_function_and_a_transitive_import_are_followed`.
5. **The operator pastes a cut or wrong key line on the box, or types the old password as the new one:** the
   key block refuses and writes nothing (Task 1 rehearses the refusal; Task 6 block); step 7e's block 3 shows
   `old password -> 200`, the stated stop condition (Task 2 measures it).

---

### Task 0: Two read-only looks at the box (operator)

Nothing changes on the box. The answers fix Task 1's image and Task 5's wording.

- [ ] **Step 1 (VPS):** the SSH version. Give the operator this block; the output holds no address.

```bash
ssh -V 2>&1 | cut -d, -f1
```

Expected: one line such as `OpenSSH_9.6p1 Ubuntu-3ubuntu13.x`. Record the version.

- [ ] **Step 2 (VPS, after `sudo -v` alone):** counts and key types only, for every account.

```bash
sudo sh -c 'sshd -T | grep -E "^(authorizedkeysfile|authorizedkeyscommand|trustedusercakeys|authorizedprincipalsfile|allowtcpforwarding|allowstreamlocalforwarding|gatewayports|permittunnel) "; getent passwd | while IFS=: read -r u _ _ _ _ h _; do for f in "$h/.ssh/authorized_keys" "$h/.ssh/authorized_keys2"; do [ -e "$f" ] && echo "$u $(basename "$f") lines=$(grep -cvE "^\s*(#|$)" "$f") types=$(grep -vE "^\s*(#|$)" "$f" | grep -oE "(ssh|ecdsa|sk)-[a-z0-9@.-]+" | sort | uniq -c | tr -s " " | tr "\n" ";") options=$(grep -vE "^\s*(#|$)" "$f" | grep -cvE "^(ssh|ecdsa|sk)-")"; done; done'
```

Expected: the eight `sshd` settings, then one line per file that exists. Record: which accounts hold a file,
how many keys each, and whether any line carries options (`options=` above 0).

- [ ] **Step 3:** if `root` (or any account other than `hermesops`) holds a key, ask the operator, with a
  recommendation: remove it in Task 9 (recommended: root login is off, so the key does nothing and only adds
  a line the reviewer must have explained), or keep it and state why in review #9's evidence.

---

### Task 1: Rehearse the limited key on the laptop

**Files:**
- Create: `docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`
- Scratch only (never committed): `$S` = the session scratchpad directory, subdirectory `tunnel-rehearsal/`

**Interfaces:**
- Produces: the measured `TUNNEL_OPTS` string (Global Constraints) and section 1 of the evaluation document.

- [ ] **Step 1: Build a throwaway SSH server of the box's version.** `ubuntu:24.04` ships OpenSSH 9.6p1. If
  Task 0 step 1 shows another version, use the Ubuntu release that ships it and say so in the document.

```bash
S=<scratchpad>/tunnel-rehearsal; mkdir -p "$S" && cd "$S"
ssh-keygen -q -t ed25519 -N "" -C admin -f "$S/admin"
ssh-keygen -q -t ed25519 -N "" -C tunnel -f "$S/tunnel"
TUNNEL_OPTS='restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'
{ cat "$S/admin.pub"; printf '%s %s\n' "$TUNNEL_OPTS" "$(cut -d' ' -f1,2 "$S/tunnel.pub")"; } > "$S/authorized_keys"
cat > "$S/Dockerfile" <<'EOF'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server python3 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -s /bin/bash hermesops && install -d -m 700 -o hermesops -g hermesops /home/hermesops/.ssh && mkdir -p /run/sshd \
 && printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nLogLevel VERBOSE\n' > /etc/ssh/sshd_config.d/10-test.conf
COPY --chown=hermesops:hermesops --chmod=600 authorized_keys /home/hermesops/.ssh/authorized_keys
CMD ["sh", "-c", "runuser -u hermesops -- python3 -m http.server 9119 --bind 127.0.0.1 >/dev/null 2>&1 & runuser -u hermesops -- python3 -m http.server 9120 --bind 127.0.0.1 >/dev/null 2>&1 & runuser -u hermesops -- python3 -c \"import socket,os; s=socket.socket(socket.AF_UNIX); s.bind('/tmp/t.sock'); s.listen(); c,_=s.accept(); c.send(b'UNIX-REACHED'); c.close()\" & exec /usr/sbin/sshd -D -e"]
EOF
docker build -q -t tunnel-rehearsal "$S" && docker run -d --rm --name tunnel-rehearsal -p 127.0.0.1:2222:22 tunnel-rehearsal
docker exec tunnel-rehearsal sshd -V 2>&1 | head -1
```

Expected: an image id, a container id, and the server's version line.

- [ ] **Step 2: The six tests, with the limited key.** `SSHO` keeps the laptop's own keys, agent and config out.

```bash
cd "$S"; SSHO="-F none -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o UserKnownHostsFile=$S/kh -o StrictHostKeyChecking=accept-new"
K="-i $S/tunnel"
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -L 29119:127.0.0.1:9119 hermesops@127.0.0.1 & sleep 3
echo "T1 forward to 9119 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29119/)"; kill %1; wait
echo "T2 command -> [$(ssh $SSHO $K hermesops@127.0.0.1 'echo MARK' 2>/dev/null)] rc=$?"
echo "T3 terminal -> [$(ssh $SSHO $K -tt hermesops@127.0.0.1 2>&1 </dev/null | tr -d '\r' | head -2 | tr '\n' '|')]"
ssh $SSHO $K -N -L 29120:127.0.0.1:9120 hermesops@127.0.0.1 2>/dev/null & sleep 3
echo "T4 forward to 9120 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29120/)"; kill %1; wait
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -R 127.0.0.1:29123:127.0.0.1:22 hermesops@127.0.0.1 2>/dev/null; echo "T5a remote forward, high port -> rc=$?"
ssh $SSHO $K -o ExitOnForwardFailure=yes -N -R 127.0.0.1:1:127.0.0.1:22 hermesops@127.0.0.1 2>/dev/null; echo "T5b remote forward, the permitted port 1 -> rc=$?"
ssh $SSHO $K -N -L 29124:/tmp/t.sock hermesops@127.0.0.1 2>/dev/null & sleep 3
echo "T6 unix socket -> [$(nc -w 3 127.0.0.1 29124 </dev/null)]"; kill %1; wait
echo "T7 sftp -> $(echo ls | sftp $SSHO $K hermesops@127.0.0.1 >/dev/null 2>&1; echo rc=$?)"
```

Expected, and what each proves:

| Test | Expected | Meaning |
|---|---|---|
| T1 | `200` | the link works |
| T2 | `[]` and `rc=1` | no command runs (`/bin/false` ran instead) |
| T3 | holds `PTY allocation request failed` and no shell prompt | no terminal |
| T4 | `000` | a forward to another port is refused |
| T5a | `rc=255` | a remote forward to an unlisted port is refused |
| T5b | `rc=255` | the one listed port cannot be bound by a non-root account |
| T6 | `[]` | a forward to a unix socket is refused |
| T7 | not `rc=0` | no file transfer |

- [ ] **Step 3: The control.** Run T2, T4 and T6 again with `K="-i $S/admin"`. Expected: `[MARK] rc=0`,
  `200`, `[UNIX-REACHED]`. Without this, a refusal above could be a broken test. (The container's unix
  listener answers once; restart the container before the control if T6 printed anything.)

- [ ] **Step 4: Rehearse the box block's refusals.** Paste Task 6's `tunnel_key_add` function into a shell
  inside the container as `hermesops` (`docker exec -it -u hermesops tunnel-rehearsal bash`), and call it
  three times: with a line cut after `ssh-ed25519`, with the bare public key (no options), and with the
  right line twice. Expected: `REFUSED` twice with the file unchanged (`wc -l` before and after), `ADDED`
  once, then `already present`.

- [ ] **Step 5: If any expected result differs, STOP.** Do not adjust the option string and carry on. Report
  what differed to the operator with options (for T5b: another unbindable port; for T6: accept and record as
  a finding, or drop `port-forwarding` in favour of a different design). The operator decides.

- [ ] **Step 6: Tear down and write section 1 of the evaluation document.**

```bash
docker rm -f tunnel-rehearsal; docker rmi tunnel-rehearsal; rm -rf "$S"
```

The document follows `docs/evaluations/2026-10-07-dashboard-password-hash-and-session-secret.md`: a sources
table (the local `man sshd` "AUTHORIZED_KEYS FILE FORMAT" and `man ssh-add`, read 2026-10-07, what each
verified: `restrict` does not disable command execution; `port-forwarding` re-enables both directions;
`permitlisten` has no "none" form; `--apple-use-keychain -d` removes the passphrase; and the box's OpenSSH
version from Task 0), the tests table above with the measured results, the control, and "Not measured".
Test values only: no real key, no address.

- [ ] **Step 7: Commit.**

```bash
git add docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md
git commit -m "docs(evaluations): the limited SSH key, measured against a throwaway server"
```

---

### Task 2: Rehearse step 7e on the laptop

**Files:**
- Modify: `docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md` (section 2)
- Scratch only: `$S` = `<scratchpad>/step7e-rehearsal/`

**Interfaces:**
- Consumes: Task 6's four step 7e blocks (write them into the runbook draft first, or rehearse from this
  plan's text and copy what was rehearsed).
- Produces: section 2 of the evaluation document; the lock-out answer that Task 6's text states.

- [ ] **Step 1: A throwaway Compose project.** Test values only: user `hermesadmin`, old password
  `OldTestPassword000000000000`, new password `NewTestPassword111111111111`.

```bash
S=<scratchpad>/step7e-rehearsal; mkdir -p "$S/data" && cd "$S"
cat > compose.yaml <<'EOF'
name: step7e-rehearsal
services:
  hermes-agent:
    image: hermes-eval-derived:v0.21.5
    command: ["gateway", "run"]
    env_file: gateway.env
    volumes: ["./data:/opt/data"]
    ports: ["127.0.0.1:29119:9119"]
EOF
printf 'HERMES_DASHBOARD=1\nHERMES_DASHBOARD_BASIC_AUTH_USERNAME=hermesadmin\nKEEP_ME=unchanged # a line that must survive byte for byte\n' > gateway.env
BIN=<repo>/infra/hermes-agent/bin
printf '%s' 'OldTestPassword000000000000' | docker run --rm -i -w /opt/hermes --entrypoint python3 hermes-eval-derived:v0.21.5 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
  | python3 "$BIN/install-env-secret.py" set --file "$S/gateway.env" --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --stdin
python3 "$BIN/install-env-secret.py" generate --file "$S/gateway.env" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600
docker compose up -d; sleep 25; docker compose ps -a --format '{{.Service}} {{.State}}'
```

Expected: two `install-env-secret:` lines and `hermes-agent running`. If the gateway exits for want of a
config file, copy `infra/hermes-agent/config.yaml.example` to `$S/data/config.yaml` and `up -d` again; say so
in the document. This is the state step 7d leaves on the box.

- [ ] **Step 2: Take a session with the old password** (decision 2 is that it must die).

```bash
cd "$S"; printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' 'OldTestPassword000000000000' | curl -s -c "$S/jar" -o /dev/null -w 'login %{http_code}\n' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:29119' --data @- http://127.0.0.1:29119/auth/password-login
curl -s -b "$S/jar" -o /dev/null -w 'session before %{http_code}\n' http://127.0.0.1:29119/api/auth/me
```

Expected: `login 200`, `session before 200`.

- [ ] **Step 3: Run step 7e's blocks 1 to 3,** unchanged except: no `sudo`, `cd "$S"`, `--file "$S/gateway.env"`,
  `python3 "$BIN/install-env-secret.py"`, port `29119`, no `--owner-uid`/`--owner-gid`, and the two
  `systemctl`/`show-listener-check` lines of block 2 left out (the laptop has no systemd). Type the test
  passwords at the prompts. Run block 1 three more times first, to see each refusal: two different entries;
  a 23-character entry; an entry with a `$`. Expected for each: `REFUSED` and
  `cmp gateway.env gateway.env.copy` silent (take the copy before).

Expected for the real run: the hash line `set`, the secret `removed` (1 line) and `generated`;
`hash: file == container (len 86)`; `secret: in the container (len 44)`; `plaintext: not in the container`;
then `old password -> 401`, `wrong password -> 401`, `new password -> 200`.

- [ ] **Step 4: The old session is dead, and nothing else moved.**

```bash
cd "$S"; curl -s -b "$S/jar" -o /dev/null -w 'session after %{http_code}\n' http://127.0.0.1:29119/api/auth/me
grep -c '^KEEP_ME=unchanged # a line that must survive byte for byte$' gateway.env
grep -oE '^[A-Z_]+' gateway.env | sort | uniq -c
```

Expected: `session after 401`; `1`; each name exactly once.

- [ ] **Step 5: Does the dashboard lock out after repeated failures?**

```bash
cd "$S"; login() { printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' "$1" | curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:29119' --data @- http://127.0.0.1:29119/auth/password-login; }
for i in $(seq 1 15); do printf '%s ' "$(login wrong-$i)"; done; echo; echo "then the right one -> $(login 'NewTestPassword111111111111')"
```

Record the fifteen codes and the last one. If the last is not `200`, repeat it every 60 seconds until it is,
and record how long the lock lasts: Task 6's text then says so, and tells the operator to wait that long
after a mistyped attempt.

- [ ] **Step 6: Run the whole of step 7e a second time** with a third test password. Expected: the same
  results (the step is repeatable, which is its recovery path).

- [ ] **Step 7: Tear down, write section 2, commit.**

```bash
cd "$S" && docker compose down -v; rm -rf "$S"
git add docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md
git commit -m "docs(evaluations): step 7e rehearsed on a throwaway Compose project"
```

Section 2 holds: the set-up, a table of every block's result (the three refusals included), the session
before and after, the lock-out measurement, the second run, and "Not measured: the Desktop app's own
behaviour when its saved password stops working; the listener-check lines of block 2 (no systemd)".

---

### Task 3: The collector reads the accepted SSH keys (`d1_7`)

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (imports on line 21; new code after `d1_6`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class at the end, before `if __name__`)

**Interfaces:**
- Produces: `d1_7(host, ctx) -> {"sshd": {setting: value}, "accounts_checked": int, "files": [row]}`; a row is
  `{"path", "users", "kind", "owner", "group", "mode", "keys", "unparsed_lines"}`; a key is
  `{"type", "options", "sha12"}`. NOT yet in `PROBES` (Task 5 registers it with the checklist item, so every
  commit keeps `security-review-checklist.test.py` green).

- [ ] **Step 1: Write the failing tests.** Append to `collect-review-evidence.test.py`:

```python
import base64

TUNNEL_OPTS = 'restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'


def _keybody(seed):
    """A well-formed ed25519 public key body (test value: 32 equal bytes)."""
    return base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 " + bytes([seed]) * 32).decode()


class TestD17AcceptedKeys(Base):
    SSHD = ("authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\nauthorizedkeyscommand none\n"
            "authorizedprincipalsfile none\ntrustedusercakeys none\nallowtcpforwarding yes\n"
            "allowstreamlocalforwarding yes\ngatewayports no\npermittunnel no\npermitrootlogin no\n")
    PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
              "hermesops:x:1000:1000::/home/hermesops:/bin/bash\n"
              "hermes-broker:x:997:997::/var/lib/hermes-broker:/usr/sbin/nologin\n"
              "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
              "bin:x:2:2:bin:/usr/sbin:/usr/sbin/nologin\n")

    def setUp(self):
        super().setUp()
        self._w("/etc/passwd", self.PASSWD)
        self.outputs[("sshd", "-T")] = (0, self.SSHD, "")

    def _keys(self, home, body):
        p = self._w(home + "/.ssh/authorized_keys", body)
        os.chmod(p, 0o600)
        return p

    def _two(self):
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)} operator@laptop.example\n"
                                      f"{TUNNEL_OPTS} ssh-ed25519 {_keybody(2)} hermes-box-tunnel\n")

    def test_two_keys_one_bare_one_limited(self):
        self._two()
        d = CE.d1_7(self.host(), {})
        self.assertEqual(d["accounts_checked"], 5)
        self.assertEqual(len(d["files"]), 1)
        row = d["files"][0]
        self.assertEqual((row["path"], row["users"], row["kind"], row["mode"], row["unparsed_lines"]),
                         ("/home/hermesops/.ssh/authorized_keys", ["hermesops"], "file", "0o600", 0))
        self.assertEqual(row["keys"][0], {"type": "ssh-ed25519", "options": [],
                                          "sha12": hashlib.sha256(base64.b64decode(_keybody(1))).hexdigest()[:12]})
        self.assertEqual(row["keys"][1]["options"],
                         ['command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                          "port-forwarding", "restrict"])
        self.assertNotEqual(row["keys"][0]["sha12"], row["keys"][1]["sha12"])

    def test_no_key_body_and_no_comment_leave_the_collector(self):
        self._two()
        out = json.dumps(CE.d1_7(self.host(), {}))
        for gone in (_keybody(1), _keybody(2), "laptop.example", "operator@", "hermes-box-tunnel"):
            self.assertNotIn(gone, out)

    def test_the_sshd_settings_that_accept_keys_or_forwards_are_reported(self):
        d = CE.d1_7(self.host(), {})
        self.assertEqual(d["sshd"], {"authorizedkeysfile": ".ssh/authorized_keys .ssh/authorized_keys2",
                                     "authorizedkeyscommand": "none", "authorizedprincipalsfile": "none",
                                     "trustedusercakeys": "none", "allowtcpforwarding": "yes",
                                     "allowstreamlocalforwarding": "yes", "gatewayports": "no", "permittunnel": "no"})
        self.assertEqual(d["files"], [])

    def test_a_setting_sshd_did_not_print_is_could_not_check(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace("trustedusercakeys none\n", ""), "")
        self.assertEqual(CE.d1_7(self.host(), {})["sshd"]["trustedusercakeys"], R.COULD_NOT_CHECK)

    def test_sshd_failing_or_naming_no_key_file_is_could_not_check(self):
        for result in ((1, "", "boom"), (0, "port 22\n", "")):
            self.outputs[("sshd", "-T")] = result
            with self.assertRaises(CE.CouldNotCheck):
                CE.d1_7(self.host(), {})

    def test_an_account_without_a_login_shell_is_read_too(self):
        self._keys("/var/lib/hermes-broker", f"ssh-ed25519 {_keybody(3)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([(r["users"], len(r["keys"])) for r in rows], [(["hermes-broker"], 1)])

    def test_accounts_that_share_a_home_give_one_row_naming_both(self):
        self._keys("/usr/sbin", f"ssh-ed25519 {_keybody(4)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([r["users"] for r in rows], [["bin", "daemon"]])

    def test_the_second_file_name_is_read(self):
        self._w("/root/.ssh/authorized_keys2", f"ssh-ed25519 {_keybody(5)}\n")
        rows = CE.d1_7(self.host(), {})["files"]
        self.assertEqual([r["path"] for r in rows], ["/root/.ssh/authorized_keys2"])

    def test_percent_tokens_and_an_absolute_pattern_are_expanded(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace(".ssh/authorized_keys .ssh/authorized_keys2",
                                                              "%h/.ssh/authorized_keys /etc/ssh/keys/%u"), "")
        self._keys("/home/hermesops", f"ssh-ed25519 {_keybody(1)}\n")
        self._w("/etc/ssh/keys/root", f"ssh-ed25519 {_keybody(6)}\n")
        self.assertEqual(sorted(r["path"] for r in CE.d1_7(self.host(), {})["files"]),
                         ["/etc/ssh/keys/root", "/home/hermesops/.ssh/authorized_keys"])

    def test_a_token_the_collector_does_not_expand_is_could_not_check(self):
        self.outputs[("sshd", "-T")] = (0, self.SSHD.replace(".ssh/authorized_keys .ssh/authorized_keys2",
                                                              "/etc/ssh/keys/%U"), "")
        with self.assertRaises(CE.CouldNotCheck):
            CE.d1_7(self.host(), {})

    def test_comments_and_blank_lines_are_skipped_and_other_lines_are_counted(self):
        self._keys("/home/hermesops", f"# a comment\n\nssh-ed25519 {_keybody(1)}\nnot a key line\n"
                                      f"ssh-ed25519 not*base64\nssh-ed25519\n"
                                      f'command="unbalanced ssh-ed25519 {_keybody(2)}\n')
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((len(row["keys"]), row["unparsed_lines"]), (1, 4))

    def test_a_quoted_value_with_a_space_and_a_comma_is_one_option(self):
        self._keys("/home/hermesops", f'command="/bin/echo a,b c",no-pty ssh-ed25519 {_keybody(1)}\n')
        key = CE.d1_7(self.host(), {})["files"][0]["keys"][0]
        self.assertEqual(key["options"], ["command=<withheld>", "no-pty"])

    def test_an_address_or_an_odd_command_is_withheld(self):
        self._keys("/home/hermesops",
                   f'from="203.0.113.7",permitopen="203.0.113.9:443",command="/usr/bin/x --token=abc",'
                   f'permitopen="127.0.0.1:9119",environment="A=b" ssh-ed25519 {_keybody(1)}\n')
        out = CE.d1_7(self.host(), {})["files"][0]["keys"][0]["options"]
        self.assertEqual(out, ["command=<withheld>", "environment=<withheld>", "from=<withheld>",
                               'permitopen="127.0.0.1:9119"', "permitopen=<withheld>"])
        self.assertNotIn("203.0.113", json.dumps(out))

    def test_a_symlink_in_place_of_the_file_is_never_read_as_empty(self):
        os.makedirs(os.path.join(self.root, "home/hermesops/.ssh"))
        os.symlink("/etc/passwd", os.path.join(self.root, "home/hermesops/.ssh/authorized_keys"))
        row = CE.d1_7(self.host(), {})["files"][0]
        self.assertEqual((row["kind"], row["keys"], row["unparsed_lines"]),
                         ("symlink", R.COULD_NOT_CHECK, R.COULD_NOT_CHECK))

    def test_a_certificate_authority_line_is_a_key_with_that_option(self):
        self._keys("/home/hermesops", f"cert-authority ssh-ed25519 {_keybody(7)}\n")
        self.assertEqual(CE.d1_7(self.host(), {})["files"][0]["keys"][0]["options"], ["cert-authority"])
```

- [ ] **Step 2: Run them and see them fail.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD17AcceptedKeys 2>&1 | tail -5`
Expected: every test errors with `AttributeError: module 'collect_review_evidence' has no attribute 'd1_7'`.

- [ ] **Step 3: Implement.** In `collect-review-evidence.py`, add `base64` to the import line (line 21:
  `import argparse, base64, fnmatch, …`). After `d1_6` (and before the `# --- D2` section), add:

```python
# D1.7: the sshd settings that say where a key, a certificate or a forward may come from.
SSHD_KEY_SOURCES = ("authorizedkeysfile", "authorizedkeyscommand", "authorizedprincipalsfile",
                    "trustedusercakeys", "allowtcpforwarding", "allowstreamlocalforwarding",
                    "gatewayports", "permittunnel")
_KEY_TYPE_RE = re.compile(r"(ssh-(rsa|dss|ed25519)|ecdsa-sha2-nistp(256|384|521)"
                          r"|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)(-cert-v01@openssh\.com)?")
_KEY_BODY_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,3}")
_OPTION_NAME_RE = re.compile(r"[A-Za-z0-9-]+")
# The only option VALUES printed: a plain program path, and a loopback target. Any other value
# (an address in from=, a command line with arguments, an environment assignment) is withheld.
_SHOWN_OPTION_RES = {"command": re.compile(r"[A-Za-z0-9_./-]+"),
                     "permitopen": re.compile(r"(127\.0\.0\.1|localhost|\[::1\]):(\d{1,5}|\*)"),
                     "permitlisten": re.compile(r"((127\.0\.0\.1|localhost|\[::1\]):)?(\d{1,5}|\*)")}


def _split_unquoted(text, seps):
    """(parts, unbalanced): `text` split on any character of `seps` outside double quotes. Inside
    quotes a backslash keeps the next character, as sshd reads an option value. Empty parts are
    dropped. `unbalanced` is True when a quote is never closed."""
    parts, cur, quoted, i = [], [], False, 0
    while i < len(text):
        c = text[i]
        if quoted and c == "\\" and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        if c in seps and not quoted:
            if cur:
                parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur))
    return parts, quoted


def _shown_option(opt):
    name, eq, value = opt.partition("=")
    if not _OPTION_NAME_RE.fullmatch(name):
        return WITHHELD
    if not eq:
        return name
    inner = value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
    rx = _SHOWN_OPTION_RES.get(name.lower())
    return opt if rx and rx.fullmatch(inner) else f"{name}={WITHHELD}"


def _key_row(line):
    """One authorized_keys line as its key type, its options and a short fingerprint of the key
    body, or None when it is not a key line. The body and the comment are never returned."""
    tokens, unbalanced = _split_unquoted(line.strip(), " \t")
    if unbalanced:
        return None
    for i in (0, 1):                                    # the key type is first, or second after the options
        if len(tokens) > i + 1 and _KEY_TYPE_RE.fullmatch(tokens[i]) and _KEY_BODY_RE.fullmatch(tokens[i + 1]):
            try:
                body = base64.b64decode(tokens[i + 1], validate=True)
            except ValueError:
                return None
            options = _split_unquoted(tokens[0], ",")[0] if i == 1 else []
            return {"type": tokens[i], "options": sorted(_shown_option(o) for o in options),
                    "sha12": PK.sha256_bytes(body)[:12]}
    return None


def _authorized_keys_paths(pattern, user, home):
    """The files sshd reads for one account, from its AuthorizedKeysFile value: `%h`, `%u` and `%%`
    expanded, a relative name taken under the home directory. Another token is could-not-check:
    a file this collector cannot name is a file it did not read."""
    out = []
    for pat in pattern.split():
        if pat == "none":
            continue
        p = pat.replace("%%", "\0").replace("%h", home).replace("%u", user)
        if "%" in p:
            raise CouldNotCheck("authorizedkeysfile holds a token this collector does not expand")
        p = p.replace("\0", "%")
        out.append(os.path.normpath(p if p.startswith("/") else os.path.join(home, p)))
    return out


def _authorized_keys_row(host, p, users):
    st = os.lstat(host.path(p))
    row = {"path": p, "users": sorted(users), "owner": _owner(st.st_uid), "group": _group(st.st_gid),
           "mode": oct(stat.S_IMODE(st.st_mode)),
           "kind": "file" if stat.S_ISREG(st.st_mode) else "symlink" if stat.S_ISLNK(st.st_mode) else "not-a-file"}
    unread = {**row, "keys": R.COULD_NOT_CHECK, "unparsed_lines": R.COULD_NOT_CHECK}
    if row["kind"] != "file":
        return unread
    try:
        with open(host.path(p), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return unread
    keys, unparsed = [], 0
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key = _key_row(line)
        if key is None:
            unparsed += 1
        else:
            keys.append(key)
    return {**row, "keys": keys, "unparsed_lines": unparsed}


def d1_7(host, ctx):
    """Every SSH key the box accepts, for EVERY account in /etc/passwd: an account with no login
    shell can still be used for a forward. Key types, options and short fingerprints only. The
    sshd settings are the global ones (`sshd -T`): a `Match` block is not read here (the
    fingerprint's entry_points component carries the whole of `sshd -T`)."""
    got = {}
    for line in _ok(host, ["sshd", "-T"]).splitlines():
        k, _, v = line.partition(" ")
        if k in SSHD_KEY_SOURCES:
            got[k] = v.strip()
    if "authorizedkeysfile" not in got:
        raise CouldNotCheck("sshd -T printed no authorizedkeysfile")
    users_of, accounts = {}, 0
    with open(host.path("/etc/passwd")) as f:
        for line in f:
            parts = line.rstrip("\n").split(":")
            if len(parts) != 7:
                continue
            accounts += 1
            for p in _authorized_keys_paths(got["authorizedkeysfile"], parts[0], parts[5] or "/"):
                if os.path.lexists(host.path(p)):
                    users_of.setdefault(p, set()).add(parts[0])
    return {"sshd": {k: got.get(k, R.COULD_NOT_CHECK) for k in SSHD_KEY_SOURCES},
            "accounts_checked": accounts,
            "files": [_authorized_keys_row(host, p, users_of[p]) for p in sorted(users_of)]}
```

- [ ] **Step 4: Run the tests and see them pass.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD17AcceptedKeys 2>&1 | tail -3`
Expected: `Ran 15 tests` … `OK`. Then `infra/hermes-agent/bin/run-bin-tests.sh` exits 0.

- [ ] **Step 5: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): the review collector reads the accepted SSH keys (d1_7)"
```

---

### Task 4: The collector reports each service's start time (`d4_6`)

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (imports; new code after `d4_5`; `main`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class at the end)

**Interfaces:**
- Produces: `LAST_PASS_COLLECTED_AT` (module global, `None` by default); `SERVICE_FILES` (unit name →
  `(unit file, script)`); `_iso(epoch) -> str`, `_epoch(iso) -> int`;
  `d4_6(host, ctx) -> {"last_pass_collected_at", "started_at", "started_after_last_pass",
  "files_newer_than_start", "files_checked"}`; the flag `--last-pass-collected-at`. NOT yet in `PROBES`.
- Refinement of the spec: the file list is computed from the scripts on the box at collection time (their
  import statements, followed to any depth), not kept as a constant with a test. It cannot fall behind.

- [ ] **Step 1: Write the failing tests.** Append to `collect-review-evidence.test.py`:

```python
class TestD46StartTimes(Base):
    START = "Wed 2026-10-07 06:45:46 UTC"      # as `systemctl show -p ActiveEnterTimestamp --value` prints it
    START_ISO = "2026-10-07T06:45:46Z"
    BOOT = 1758448800                          # /proc/stat btime, seconds since the epoch

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, CE, "LAST_PASS_COLLECTED_AT", None)
        CE.LAST_PASS_COLLECTED_AT = None
        for unit in ("docker", *CE.SERVICE_FILES):
            self._start(unit, self.START)
        self.outputs[("docker", "ps")] = (0, "a" * 64 + "\n", "")
        self.outputs[("docker", "inspect", "--format", "{{.State.StartedAt}}")] = (0, "2026-10-07T15:39:12.123456789Z\n", "")
        self._w("/proc/stat", f"cpu  1 2 3\nbtime {self.BOOT}\nprocesses 5\n")
        self.t0 = CE._epoch(self.START_ISO)
        for unit_file, script in CE.SERVICE_FILES.values():
            self._file("/etc/systemd/system/" + unit_file, "[Unit]\n")
            self._file(CE.AGENT_DIR + "/bin/" + script, "import os\n")

    def _start(self, unit, text):
        self.outputs[("systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value")] = (0, text + "\n", "")

    def _file(self, rel, body, age=-3600):
        """A file whose modification time is `age` seconds after the services' start."""
        p = self._w(rel, body)
        os.utime(p, (self.t0 + age, self.t0 + age))
        return p

    APP = "hermes-app-broker@ads-audit"

    def test_every_start_is_reported_in_utc(self):
        d = CE.d4_6(self.host(), {})
        self.assertEqual(sorted(d["started_at"]), sorted(["boot", "docker", "gateway-container", "hermes-broker",
                                                          "hermes-docker-proxy", self.APP]))
        for unit in ("docker", "hermes-broker", "hermes-docker-proxy", self.APP):
            self.assertEqual(d["started_at"][unit], self.START_ISO)
        self.assertEqual(d["started_at"]["gateway-container"], "2026-10-07T15:39:12Z")
        self.assertEqual(d["started_at"]["boot"], CE._iso(self.BOOT))
        self.assertRegex(d["started_at"]["boot"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_without_a_baseline_nothing_is_compared(self):
        d = CE.d4_6(self.host(), {})
        self.assertIsNone(d["last_pass_collected_at"])
        self.assertEqual(set(d["started_after_last_pass"].values()), {None})

    def test_a_start_after_the_last_pass_is_marked(self):
        CE.LAST_PASS_COLLECTED_AT = "2026-10-07T10:00:00Z"
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["last_pass_collected_at"], "2026-10-07T10:00:00Z")
        self.assertEqual(d["started_after_last_pass"],
                         {"boot": False, "docker": False, "hermes-broker": False, "hermes-docker-proxy": False,
                          self.APP: False, "gateway-container": True})
        CE.LAST_PASS_COLLECTED_AT = self.START_ISO          # the same second is not "after"
        self.assertFalse(CE.d4_6(self.host(), {})["started_after_last_pass"]["hermes-broker"])

    def test_a_time_that_is_empty_or_not_utc_is_could_not_check(self):
        CE.LAST_PASS_COLLECTED_AT = "2026-10-07T10:00:00Z"
        for text in ("", "n/a", "Wed 2026-10-07 08:45:46 CEST", "2026-10-07 06:45:46", "Wed 2026-10-07 06:45:46 UTC extra"):
            self._start("hermes-broker", text)
            d = CE.d4_6(self.host(), {})
            self.assertEqual(d["started_at"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["started_after_last_pass"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["files_newer_than_start"]["hermes-broker"], R.COULD_NOT_CHECK, text)
            self.assertEqual(d["started_at"]["hermes-docker-proxy"], self.START_ISO)   # control: the others stand

    def test_systemctl_failing_is_could_not_check(self):
        self.outputs[("systemctl", "show", "docker", "-p", "ActiveEnterTimestamp", "--value")] = (1, self.START, "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["docker"], R.COULD_NOT_CHECK)

    def test_no_gateway_or_an_odd_container_time_is_could_not_check(self):
        self.outputs[("docker", "inspect", "--format", "{{.State.StartedAt}}")] = (0, "0001-01-01T00:00:00+02:00\n", "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["gateway-container"], R.COULD_NOT_CHECK)
        self.outputs[("docker", "ps")] = (0, "", "")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["gateway-container"], R.COULD_NOT_CHECK)

    def test_no_boot_time_is_could_not_check(self):
        self._w("/proc/stat", "cpu  1 2 3\n")
        self.assertEqual(CE.d4_6(self.host(), {})["started_at"]["boot"], R.COULD_NOT_CHECK)

    def test_files_older_than_the_start_are_not_listed(self):
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"], {"hermes-broker": [], "hermes-docker-proxy": [], self.APP: []})
        self.assertEqual(d["files_checked"], {"hermes-broker": 2, "hermes-docker-proxy": 2, self.APP: 2})

    def test_a_script_or_a_unit_file_changed_after_the_start_is_listed(self):
        self._file(CE.AGENT_DIR + "/bin/hermes-broker.py", "import os\n", age=60)
        self._file("/etc/systemd/system/hermes-app-broker@.service", "[Unit]\n", age=60)
        d = CE.d4_6(self.host(), {})["files_newer_than_start"]
        self.assertEqual(d, {"hermes-broker": ["hermes-broker.py"], "hermes-docker-proxy": [], self.APP: ["unit"]})

    def test_a_file_changed_in_the_same_second_as_the_start_is_not_listed(self):
        self._file(CE.AGENT_DIR + "/bin/hermes-broker.py", "import os\n", age=0)
        self.assertEqual(CE.d4_6(self.host(), {})["files_newer_than_start"]["hermes-broker"], [])

    def test_an_import_inside_a_function_and_a_transitive_import_are_followed(self):
        b = CE.AGENT_DIR + "/bin/"
        self._file(b + "hermes-app-broker.py", "import os, app_lib as A\n\ndef f():\n    from lazy_lib import x\n")
        self._file(b + "app_lib.py", "import vault_lib\n")
        self._file(b + "vault_lib.py", "import json\n", age=60)
        self._file(b + "lazy_lib.py", "x = 1\n", age=60)
        self._file(b + "unrelated_lib.py", "y = 1\n", age=60)
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"][self.APP], ["lazy_lib.py", "vault_lib.py"])
        self.assertEqual(d["files_checked"][self.APP], 5)       # the unit, the script and three modules

    def test_a_file_loaded_by_its_name_is_followed(self):
        b = CE.AGENT_DIR + "/bin/"
        self._file(b + "hermes-broker.py", 'import os\nP = os.path.join(HERE, "side-loaded.py")\n')
        self._file(b + "side-loaded.py", "z = 1\n", age=60)
        self.assertEqual(CE.d4_6(self.host(), {})["files_newer_than_start"]["hermes-broker"], ["side-loaded.py"])

    def test_a_missing_or_unparsable_script_costs_that_service_only(self):
        os.remove(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "bin/hermes-broker.py"))
        self._file(CE.AGENT_DIR + "/bin/docker-create-proxy.py", "def broken(:\n")
        d = CE.d4_6(self.host(), {})
        self.assertEqual(d["files_newer_than_start"], {"hermes-broker": R.COULD_NOT_CHECK,
                                                       "hermes-docker-proxy": R.COULD_NOT_CHECK, self.APP: []})
        self.assertEqual(d["files_checked"]["hermes-broker"], R.COULD_NOT_CHECK)

    def test_each_service_is_paired_with_the_script_its_unit_runs(self):
        deploy = os.path.join(os.path.dirname(HERE), "deploy")
        for unit_file, script in CE.SERVICE_FILES.values():
            with open(os.path.join(deploy, unit_file)) as f:
                self.assertRegex(f.read(), r"(?m)^ExecStart=.*/opt/hermes-agent/bin/" + script.replace(".", r"\."), unit_file)

    def test_the_repos_own_app_broker_loads_what_review_8_named(self):
        loaded = CE._loaded_files(HERE, "hermes-app-broker.py")
        for name in ("hermes-app-broker.py", "app_lib.py", "vault_lib.py", "governance_lib.py", "client_audit_lib.py"):
            self.assertIn(name, loaded)
        self.assertNotIn("collect-review-evidence.py", loaded)

    def test_main_refuses_an_invalid_last_pass_collected_at(self):
        for bad in ("2026-10-07", "2026-10-07T16:21:22", "2026-10-07T16:21:22+00:00", "2026-13-40T00:00:00Z",
                    "2026-10-07T16:21:22Z\n", ""):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = CE.main(["--fp-key-tty", "--last-pass-collected-at", bad], host=self.host(),
                             read_key=lambda: "11" * 32)
            self.assertEqual((rc, out.getvalue()), (2, ""), repr(bad))
            self.assertIn("--last-pass-collected-at", err.getvalue())
            self.assertIsNone(CE.LAST_PASS_COLLECTED_AT)
```

- [ ] **Step 2: Run them and see them fail.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD46StartTimes 2>&1 | tail -5`
Expected: errors with `AttributeError: … has no attribute 'SERVICE_FILES'` (from `setUp`).

- [ ] **Step 3: Implement the probe.** Add `ast, calendar, datetime, time` to the import line. After `d4_5`
  (before the `# --- D5` section), add:

```python
# D4.6: when each service started, and whether it runs older code than the box holds.
LAST_PASS_COLLECTED_AT = None   # the last passing review's box-bundle collected_at, set by main()
# Each long-running Hermes service: its unit file and the script its ExecStart runs (tested
# against the repo's unit files). The files it loads are read from the script itself.
SERVICE_FILES = {"hermes-docker-proxy": ("hermes-docker-proxy.service", "docker-create-proxy.py"),
                 "hermes-broker": ("hermes-broker.service", "hermes-broker.py"),
                 "hermes-app-broker@" + APP: ("hermes-app-broker@.service", "hermes-app-broker.py")}
_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_ISO_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
_SYSTEMD_TS_RE = re.compile(r"[A-Z][a-z]{2} (\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) UTC")
_DOCKER_TS_RE = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z")
_PY_NAME_RE = re.compile(r"[A-Za-z0-9_-]+\.py")


def _iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime(_ISO_FORMAT)


def _epoch(iso):
    return calendar.timegm(time.strptime(iso, _ISO_FORMAT))


def _unit_started_at(host, unit):
    """The unit's ActiveEnterTimestamp as UTC, second precision. Empty (the unit never became
    active), another time zone, or any other form is could-not-check: a time this collector
    cannot place is never compared."""
    rc, out, _ = host.run(["systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value"])
    m = _SYSTEMD_TS_RE.fullmatch(out.strip()) if rc == 0 else None
    return f"{m.group(1)}T{m.group(2)}Z" if m else R.COULD_NOT_CHECK


def _gateway_started_at(host):
    rc, gw, _ = host.run(["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER])
    if rc != 0 or len(gw.strip()) != 64:
        return R.COULD_NOT_CHECK
    rc, out, _ = host.run(["docker", "inspect", "--format", "{{.State.StartedAt}}", gw.strip()])
    m = _DOCKER_TS_RE.fullmatch(out.strip()) if rc == 0 else None
    return m.group(1) + "Z" if m else R.COULD_NOT_CHECK


def _boot_at(host):
    try:
        with open(host.path("/proc/stat")) as f:
            for line in f:
                if line.startswith("btime "):
                    return _iso(int(line.split()[1]))
    except (OSError, ValueError, IndexError):
        pass
    return R.COULD_NOT_CHECK


def _loaded_files(bin_dir, script):
    """The bin/ files `script` loads: itself, every bin module it imports at any depth (an
    import inside a function included), and any bin file it names in a string ending `.py`
    (loaded by path, as the collector loads the listener check). Read from the files as they
    are now, so the list cannot fall behind the code. A module imported only on a rare path is
    listed too: that errs towards a restart, never away from one."""
    seen, todo = set(), [script]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        with open(os.path.join(bin_dir, name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] + ".py" for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0] + ".py"]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _PY_NAME_RE.fullmatch(node.value):
                names = [node.value]
            todo.extend(n for n in names if os.path.isfile(os.path.join(bin_dir, n)))
    return sorted(seen)


def _files_newer_than_start(host, unit, started_at):
    """(names, count): the loaded files whose modification time is later than the service's
    start, and how many files were looked at. `unit` stands for the unit file. The start has
    second precision, so a file changed in that same second is not listed."""
    if started_at == R.COULD_NOT_CHECK:
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
    unit_file, script = SERVICE_FILES[unit]
    bin_dir = host.path(AGENT_DIR + "/bin")
    try:
        paths = {"unit": host.path("/etc/systemd/system/" + unit_file)}
        paths.update({n: os.path.join(bin_dir, n) for n in _loaded_files(bin_dir, script)})
        start = _epoch(started_at)
        return sorted(n for n, p in paths.items() if int(os.stat(p).st_mtime) > start), len(paths)
    except (OSError, SyntaxError, ValueError):
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK


def d4_6(host, ctx):
    """When the host, Docker, the three long-running Hermes services and the gateway container
    last started, each compared with the last PASS's collection time (given with
    --last-pass-collected-at), and which files each service loads that changed after it
    started. D4.2's hash is the same string after any daemon-reload, so it cannot show a
    restart (review #8); this item can. Timestamps, unit names and file names only."""
    starts = {"boot": _boot_at(host), "docker": _unit_started_at(host, "docker"),
              **{u: _unit_started_at(host, u) for u in SERVICE_FILES},
              "gateway-container": _gateway_started_at(host)}
    base = LAST_PASS_COLLECTED_AT

    def after(ts):
        if ts == R.COULD_NOT_CHECK:
            return R.COULD_NOT_CHECK
        return None if base is None else ts > base       # one fixed-width UTC format: text order is time order

    files = {u: _files_newer_than_start(host, u, starts[u]) for u in SERVICE_FILES}
    return {"last_pass_collected_at": base, "started_at": starts,
            "started_after_last_pass": {k: after(v) for k, v in starts.items()},
            "files_newer_than_start": {u: f[0] for u, f in files.items()},
            "files_checked": {u: f[1] for u, f in files.items()}}
```

- [ ] **Step 4: Implement the flag.** Replace `main` (keep `_main` as it is) with:

```python
def _valid_collected_at(value):
    if not _ISO_RE.fullmatch(value):
        return False
    try:
        _epoch(value)
    except ValueError:
        return False
    return True


def main(argv=None, host=None, read_key=_tty_key):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fingerprint-only", action="store_true")
    g.add_argument("--credentials-only", action="store_true")
    ap.add_argument("--fp-key-tty", action="store_true")
    ap.add_argument("--last-pass-execstart")
    ap.add_argument("--last-pass-collected-at")
    a = ap.parse_args(argv)
    if a.last_pass_execstart is not None and not re.fullmatch(r"[0-9a-f]{64}", a.last_pass_execstart):
        print("collect-review-evidence: --last-pass-execstart must be 64 lowercase hex characters",
              file=sys.stderr)
        return 2
    if a.last_pass_collected_at is not None and not _valid_collected_at(a.last_pass_collected_at):
        print("collect-review-evidence: --last-pass-collected-at must be the last PASS bundle's collected_at, "
              "a UTC time such as 2026-10-07T16:21:22Z", file=sys.stderr)
        return 2
    global LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT
    prior = LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT
    if a.last_pass_execstart is not None:
        LAST_PASS_EXECSTART = a.last_pass_execstart
    if a.last_pass_collected_at is not None:
        LAST_PASS_COLLECTED_AT = a.last_pass_collected_at
    try:
        return _main(a, host, read_key)
    finally:
        LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT = prior   # never leaks into a later call without the flag
```

Add the flag to the module docstring's usage lines:
`  sudo python3 bin/collect-review-evidence.py --fp-key-tty --last-pass-execstart <64 hex> --last-pass-collected-at <UTC time>`.

- [ ] **Step 5: Run the tests and see them pass.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD46StartTimes TestReview5FollowUps 2>&1 | tail -3`
Expected: `OK` (the second class holds the existing `--last-pass-execstart` tests, which must still pass).
Then `infra/hermes-agent/bin/run-bin-tests.sh` exits 0.

- [ ] **Step 6: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): the review collector reports each service's start time (d4_6)"
```

---

### Task 5: Checklist v1.18, the two probes registered, the report template and the brief

**Files:**
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`
- Modify: `infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md`
- Modify: `infra/hermes-agent/deploy/security-review/REVIEWER-BRIEF.md`
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`PROBES`)
- Test: `infra/hermes-agent/bin/security-review-checklist.test.py`, `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Consumes: `d1_7`, `d4_6`, `LAST_PASS_COLLECTED_AT` (Tasks 3 and 4).
- Produces: bundle items `D1.7` and `D4.6`; checklist `version: 1.18`.

- [ ] **Step 1: Write the failing tests.** In `security-review-checklist.test.py`, after
  `test_d4_5_names_every_field_the_collector_reports`:

```python
    def test_d1_7_and_d4_6_name_every_field_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        import tempfile
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "etc"))
        with open(os.path.join(root, "etc/passwd"), "w") as f:
            f.write("root:x:0:0:root:/root:/bin/bash\n")
        os.makedirs(os.path.join(root, "root/.ssh"))
        with open(os.path.join(root, "root/.ssh/authorized_keys"), "w") as f:
            f.write("ssh-ed25519 " + "A" * 68 + "\n")
        host = ce.Host(root, lambda argv, timeout=60: (0, "authorizedkeysfile .ssh/authorized_keys\n", ""))
        d1_7 = ce.d1_7(host, {})
        for field in [*d1_7, *d1_7["sshd"], *d1_7["files"][0], *d1_7["files"][0]["keys"][0]]:
            self.assertIn(f"`{field}`", blocks["D1.7"], field)
        d4_6 = ce.d4_6(host, {})
        for field in [*d4_6, *d4_6["started_at"]]:
            self.assertIn(f"`{field}`", blocks["D4.6"], field)

    def test_d1_7_states_the_limited_keys_exact_options(self):
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        for opt in ('command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                    "port-forwarding", "restrict"):
            self.assertIn(f"`{opt}`", blocks["D1.7"], opt)

    def test_the_version_is_1_18(self):
        self.assertRegex(items()[0], r"(?m)^version: 1\.18$")
```

In `collect-review-evidence.test.py`, at the end of `TestD46StartTimes`:

```python
    def test_main_passes_a_valid_last_pass_collected_at_and_does_not_leak_it(self):
        def run(*extra):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = CE.main(["--fp-key-tty", *extra], host=self.host(), read_key=lambda: "11" * 32)
            return rc, json.loads(out.getvalue())["items"]
        rc, items = run("--last-pass-collected-at", "2026-10-07T10:00:00Z")
        self.assertEqual(items["D4.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D4.6"]["data"]["last_pass_collected_at"], "2026-10-07T10:00:00Z")
        self.assertTrue(items["D4.6"]["data"]["started_after_last_pass"]["gateway-container"])
        self.assertIsNone(CE.LAST_PASS_COLLECTED_AT)
        _, items = run()
        self.assertIsNone(items["D4.6"]["data"]["last_pass_collected_at"])

    def test_the_bundle_carries_both_new_items(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertEqual(items["D4.6"]["status"], R.OBSERVED)
        self.assertEqual(items["D1.7"]["status"], R.COULD_NOT_CHECK)      # no sshd in this fake host
```

- [ ] **Step 2: Run them and see them fail.**

Run: `python3 infra/hermes-agent/bin/security-review-checklist.test.py 2>&1 | tail -4; python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD46StartTimes 2>&1 | tail -4`
Expected: `KeyError: 'D1.7'`, the version assertion, and `KeyError: 'D4.6'`.

- [ ] **Step 3: Register the probes.** In `PROBES`: add `"D1.7": d1_7` after `"D1.6": d1_6`, and
  `"D4.6": d4_6` after `"D4.5": d4_5`.

- [ ] **Step 4: The checklist.** In `CHECKLIST.md`:

  (a) `version: 1.18`.

  (b) Append to the header paragraph, after the `(v1.17: …)` note:
  ` (v1.18: review #8's follow-ups. New D1.7: every SSH key the box accepts, by type, options and short fingerprint, and the sshd settings that could accept a key or a forward from elsewhere; the laptop's always-on forward now has a key of its own. New D4.6: when each service started, compared with the last PASS's collection time, and the files a service loads that changed after it started. D4.2: an equal hash does not show "not restarted". D9.1 names F55 to F57.)`

  (c) After D1.6's block, this item (each bullet is ONE line in the file):

```markdown
### D1.7 — The accepted SSH keys are the expected ones
- **source:** box
- **claim:** the box accepts exactly the keys the operator names: one administrative key, and one key limited to the laptop's forward to the dashboard (review #8, F57). No other account holds a key, and no sshd setting accepts a key or a certificate from elsewhere.
- **expected:** `sshd` holds the global `sshd -T` values (a `Match` block is not read; the fingerprint's `entry_points` component carries the whole of `sshd -T`): `authorizedkeysfile` is `.ssh/authorized_keys .ssh/authorized_keys2`; `authorizedkeyscommand`, `authorizedprincipalsfile` and `trustedusercakeys` are `none`; `gatewayports` is `no`; `permittunnel` is `no`; `allowtcpforwarding` is `yes` (the forward needs it) and `allowstreamlocalforwarding` is whatever the box shows (the limited key's options are what refuse it, measured in `docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`). `accounts_checked` is the number of `/etc/passwd` lines read: every account, because one with no login shell can still be used for a forward. `files` has one row per key file that exists, each with `path`, `users` (the accounts whose key file it is), `kind`, `owner`, `group`, `mode`, `keys` and `unparsed_lines` (lines that are neither a key, a comment nor blank). A key is its `type`, its `options` (sorted; a value is printed only for a plain program path in `command` and a loopback target in `permitopen` or `permitlisten`, and is `<withheld>` otherwise) and `sha12` (the first 12 hex characters of the sha256 of the key body); the key body and its comment are never in the bundle. On this box: exactly one row, `path` `/home/hermesops/.ssh/authorized_keys`, `users` `["hermesops"]`, `kind` `file`, `owner` and `group` `hermesops`, `mode` `0o600`, `unparsed_lines` `0`, and exactly two `keys`: one with `options` `[]` (the administrative key) and one whose `options` are exactly `command="/bin/false"`, `permitlisten="127.0.0.1:1"`, `permitopen="127.0.0.1:9119"`, `port-forwarding`, `restrict` (the forward's key: no terminal, no command, a local forward to the dashboard's port only, and a remote forward only to a port an unprivileged account cannot bind). The report header carries each key's `sha12`, and from review #10 on the reviewer compares them with the previous header's.
- **pass rule:** a row on any other account, a third key, a key whose `options` are neither of the two sets above (a `<withheld>` value included), `unparsed_lines` above `0`, a `kind` other than `file`, a `mode` other than `0o600`, or an owner other than the account, is a FAIL unless the operator states whose key it is and why it stays (a key on `root` that login cannot use is such a case: `permitrootlogin no`, D1.3). `authorizedkeyscommand`, `authorizedprincipalsfile` or `trustedusercakeys` other than `none`, `gatewayports` other than `no`, or an `authorizedkeysfile` other than the one above, is a FAIL. A `keys` or `unparsed_lines` of `could-not-check`, or a `sshd` value of `could-not-check`, is CANNOT-VERIFY. A `sha12` that differs from the previous report's header needs the operator's statement of which key was replaced and when; unexplained, it is a FAIL.
```

  If Task 0 found a key on another account and the operator chose to keep it, the reviewer handles it under
  the pass rule's "unless the operator states"; the text above does not change.

  (d) In D4.2's `claim`, append: ` An equal hash does not show that the proxy was not restarted: after any `daemon-reload` the line is the same string whatever happened to the process (review #8). D4.6 reports the start times.`

  (e) After D4.5's block:

```markdown
### D4.6 — Every restart since the last PASS is explained, and no service runs older code than the box holds
- **source:** box
- **claim:** the reviewer can see when the host, Docker, the three long-running Hermes services and the gateway container last started, and whether a service has been running since before a file it loads was changed (review #8, entries 2 and 8; F55).
- **expected:** `last_pass_collected_at` is the previous PASS report's box-bundle collection time, given to the collector with `--last-pass-collected-at` (`null` when the flag was not given). `started_at` holds one UTC time (second precision) for each of `boot` (the host, from `/proc/stat`), `docker`, `hermes-docker-proxy`, `hermes-broker`, `hermes-app-broker@ads-audit` (each unit's `ActiveEnterTimestamp`) and `gateway-container` (the container's `StartedAt`). `started_after_last_pass` says for each of those whether it started later than `last_pass_collected_at` (`true`, `false`, or `null` without the flag). `files_newer_than_start` lists, for each of the three Hermes services, the files it loads whose modification time is later than its start: `unit` stands for its unit file in `/etc/systemd/system`, and the other names are files in `bin/` (its script and every module the script imports, at any depth, read from the scripts as they are on the box); `files_checked` is how many files were looked at for each. On a healthy box every `files_newer_than_start` list is `[]`. A restart between two reviews is normal: automatic security updates restart the proxy and the mutation broker (F55), a rollout step may restart a service, and BRING-UP step 7e recreates the gateway container.
- **pass rule:** a `true` in `started_after_last_pass` needs the operator's statement of when that start happened and what caused it (an automatic update, with the update log's line; a named rollout step; a reboot); unexplained, it is a FAIL. A non-empty `files_newer_than_start` is a FAIL: the service runs older code than the box holds, so the operator restarts it (`sudo systemctl restart <unit>`) and re-collects; a list holding `unit` after a unit file was reinstalled is the same case. A `started_at`, `started_after_last_pass`, `files_newer_than_start` or `files_checked` value of `could-not-check` is CANNOT-VERIFY for that entry (a time not printed in UTC, a unit that never became active, a script that could not be read). `last_pass_collected_at` `null` is CANNOT-VERIFY unless the operator states the previous collection time and the reviewer compares each `started_at` by hand.
```

  (f) In D9.1's `expected`, after the last finding it names, add `, F55 to F57`.

- [ ] **Step 5: The report template.** In `REPORT-TEMPLATE.md`, replace the `Box fingerprint` line and add
  three lines, so the header reads (other lines unchanged):

```markdown
- **Box fingerprint:** `<sha256>` (complete: true|false) — components: `clients` `<8 hex>`, `packages` `<8 hex>`, `code` `<8 hex>`, `entry_points` `<8 hex>`, `checklist` `<8 hex>`
- **Box bundle `collected_at`:** `<UTC time>` (the next review gives it to the collector as `--last-pass-collected-at`)
- **Accepted SSH keys (D1.7):** (one line per key: account, `sha12`, and `no options` or `limited to the forward`)
- **D7.1 `records`:** `<number>`
```

  In the sign-off block, after the D3.2 line, add:
  `- **D4.6 restarts:** (one line per `true` in `started_after_last_pass`: what started, when, why)`.

- [ ] **Step 6: The brief.** In `REVIEWER-BRIEF.md` item 7, replace the parenthesis with:
  `(the fingerprint and its components, the box bundle's collection time, the authorised credential set, the accepted SSH keys' short fingerprints, D4.2's `execstart_sha256`, D4.5's `alert_log`, D7.1's `records`)`.
  In item 5, after `D4.2's baseline statement (when `matches_last_pass` is `null` or `false`)`, add
  `, D4.6's statement of each restart since the last PASS, D1.7's statement of whose each key is`.

- [ ] **Step 7: Run everything.**

```bash
infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/deploy/provision.test.py && node scripts/run-all-tests.js
python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo "version_rc=$?"
awk '/^### D1\.7|^### D4\.6/{f=1} f&&/^- \*\*/{n++} /^### D1\.6|^### D4\.5/{f=0} END{print n" bullets"}' infra/hermes-agent/deploy/security-review/CHECKLIST.md
```

Expected: all four suites pass; `version_rc=0` (run after the commit of step 8: the check compares committed
text, so before the commit it reports the old state); `8 bullets` (four per new item, each one line). If a
test elsewhere counts bundle items, update the number and say so in the commit message.

- [ ] **Step 8: Commit.**

```bash
git add infra/hermes-agent/deploy/security-review infra/hermes-agent/bin
git commit -m "feat(hermes): checklist v1.18 — D1.7 accepted SSH keys, D4.6 service start times"
python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo "version_rc=$?"
```

---

### Task 6: The runbook and the README

> Superseded: paste nothing from this task. See the banner at the top.

**Files:**
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (new "Step 7e" after step 7d; new "The limited key for the
  laptop link" after it; "A security review" steps 2a and 3)
- Modify: `infra/hermes-agent/README.md` ("Using the Hermes Desktop app against the box")

**Interfaces:**
- Consumes: Task 1's measured option string; Task 2's lock-out answer.

- [ ] **Step 1: Step 7e.** Insert after step 7d's last paragraph (before the `---` that precedes "What This
  Runbook Does Not Do"). Heading `### Step 7e: Replace the dashboard password`. Opening text: why (the
  password that was plaintext until 2026-10-07 must stop working: review #8, F56), that it replaces the
  signing secret too so every session ends (operator decision 2026-10-07), that the password is never on a
  command line, in a file or on the screen, that the recovery is to run the step again, and "Quit the Hermes
  Desktop app first, so nothing retries the old password while this runs." State Task 2's lock-out result in
  one sentence. Then the blocks:

Block 0 (`hermesops@<host>`), alone:

```bash
cd /opt/hermes-agent && sudo -v && sudo grep -oE '^HERMES_DASHBOARD_BASIC_AUTH[A-Z_]*' .env | sort
```

Expected: exactly `…_PASSWORD_HASH`, `…_SECRET`, `…_USERNAME`. A line `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`
means step 7d was not finished: stop, a plaintext password would win over the new hash.

Block 1, alone (one function and its call). Generate the new password in the password manager first:
letters and digits only, 24 or more.

```bash
step7e_set() {
  local P Q E=/opt/hermes-agent/.env
  cd /opt/hermes-agent || return
  read -rs -p "NEW dashboard password: " P; echo
  read -rs -p "The same again: " Q; echo
  if [ "$P" = "$Q" ] && [ ${#P} -ge 24 ] && case "$P" in *[!A-Za-z0-9]*) false;; *) true;; esac; then
    printf '%s' "$P" | sudo docker compose exec -T -w /opt/hermes hermes-agent python3 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
      | sudo python3 bin/install-env-secret.py set --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --owner-uid 0 --owner-gid 0 --stdin \
      && sudo python3 bin/install-env-secret.py strip --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET \
      && sudo python3 bin/install-env-secret.py generate --file "$E" --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600 --owner-uid 0 --owner-gid 0
  else
    echo "REFUSED: the two entries differ, or it is under 24 characters, or it holds something other than letters and digits -- nothing written"
  fi
}; step7e_set; unset -f step7e_set
```

Expected: three `install-env-secret:` lines (`…_PASSWORD_HASH set`, `…_SECRET removed … (1 line(s))`,
`…_SECRET generated`). On `REFUSED` or any other message, stop: run block 1 again. The running gateway still
has the old password until block 2.

Block 2: the gateway is stopped and recreated. The two listener-check runs are review #8's entry 10: the
first must fail because the gateway is down, the second must be `ok`.

```bash
cd /opt/hermes-agent
sudo docker compose stop hermes-agent; echo "STOP_EXIT=$?"
sudo systemctl start hermes-listener-check.service; echo "check_while_stopped_rc=$?"
sudo docker compose up -d --force-recreate hermes-agent; echo "UP_EXIT=$?"
sleep 25; sudo docker compose ps -a hermes-agent --format '{{.Service}} {{.State}} {{.Status}}'
F=$(sudo python3 -c 'import sys; sys.path.insert(0, "bin"); import client_audit_lib as C; print((C.env_values(open(".env").read(), "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH") or [""])[0])')
C=$(sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)
[ ${#C} -eq 86 ] && [ "$F" = "$C" ] && echo "hash: file == container (len ${#C})" || echo "HASH DIFFERS (file ${#F}, container ${#C}): STOP"; unset F C
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_SECRET | awk '{print "secret: in the container (len " length($0) ")"}'
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD >/dev/null && echo "PLAINTEXT STILL SET" || echo "plaintext: not in the container"
sudo systemctl start hermes-listener-check.service; echo "check_after_rc=$?"
sudo show-listener-check | tail -n 1
systemctl list-timers hermes-listener-check.timer --no-pager | head -3
```

Expected: `STOP_EXIT=0`; `check_while_stopped_rc` NOT `0` (systemd reports the job failed: the check could
not look); `UP_EXIT=0`; `hermes-agent running Up …`; `hash: file == container (len 86)`;
`secret: in the container (len 44)`; `plaintext: not in the container`; `check_after_rc=0`;
`listener check: OK`; a timer line with a NEXT time. Keep this output for the next review's evidence
(D4.5, D4.6). On `HASH DIFFERS`: run block 1 again, then this block.

Block 3, alone (one function and its call): the OLD password must now be refused.

```bash
step7e_login() {
  local OLD NEW
  read -rs -p "OLD dashboard password: " OLD; echo
  read -rs -p "NEW dashboard password: " NEW; echo
  login() { printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' "$1" | curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:9119' --data @- http://127.0.0.1:9119/auth/password-login; }
  echo "old password -> $(login "$OLD")"
  echo "wrong password -> $(login "not-the-password-0000")"
  echo "new password -> $(login "$NEW")"
  unset -f login
}; step7e_login; unset -f step7e_login
```

Expected: `old password -> 401`, `wrong password -> 401`, `new password -> 200`. `old password -> 200` means
the new password is the old one: run the step again with a different password. `new password -> 401` means a
typing slip in block 1: run the step again. Then open the Desktop app, sign in with the new password, and
store it in the password manager.

Closing paragraph: after this step a review's header shows a new short fingerprint for
`dashboard-session-secret` (the hash is never fingerprinted), and D4.6 shows the gateway container started
after the last PASS: state "BRING-UP step 7e, <date and time UTC>" in the evidence.

- [ ] **Step 2: The limited key.** New section after step 7e: `### Step 7f: A key of its own for the laptop's
  forward`. Opening text: why (review #8 entry 4, F57), what the key can do (one forward to the dashboard's
  port) and cannot (a terminal, a command, a file transfer, any other forward, in either direction), the
  option table from the spec, a pointer to the evaluation document, and the order rule: "the box runs
  fail2ban; nothing that retries by itself is switched to the new key before the hand tests pass." Blocks:

LAPTOP 1: make the key and put the line for the box on the clipboard (the key's comment is left out).

```bash
[ -e ~/.ssh/hermes-box-tunnel ] && echo "EXISTS: stop, do not overwrite" || { ssh-keygen -q -t ed25519 -N "" -C hermes-box-tunnel -f ~/.ssh/hermes-box-tunnel && printf '%s %s\n' 'restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"' "$(cut -d' ' -f1,2 ~/.ssh/hermes-box-tunnel.pub)" | pbcopy && echo "KEY MADE, line on the clipboard"; }
```

VPS 1 (`hermesops@<host>`, alone; one function and its call; keep this session open until LAPTOP 3 passes):

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
}; tunnel_key_add; unset -f tunnel_key_add
```

Expected: `ADDED: 2 key line(s), mode 600`. Then on the laptop: `pbcopy < /dev/null`.

LAPTOP 2: the alias, with the address copied from the existing one and never printed.

```bash
A=$(ssh -G hermes-box | awk '$1=="hostname"{print $2}'); grep -q '^Host hermes-box-tunnel$' ~/.ssh/config && echo "alias exists" || printf '\nHost hermes-box-tunnel\n  HostName %s\n  User hermesops\n  IdentityFile ~/.ssh/hermes-box-tunnel\n  IdentitiesOnly yes\n  IdentityAgent none\n  ForwardAgent no\n  ServerAliveInterval 30\n  ServerAliveCountMax 3\n' "$A" >> ~/.ssh/config; unset A
ssh -G hermes-box-tunnel | grep -cE '^(identityfile .*/hermes-box-tunnel|identitiesonly yes|identityagent none)$'
```

Expected: `3`.

LAPTOP 3: the hand tests, once each. Every one of these logs in successfully, so none counts against
fail2ban; what is refused is what the key asks for afterwards.

```bash
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L 29119:127.0.0.1:9119 hermes-box-tunnel & sleep 4
echo "T1 forward to the dashboard -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29119/)"; kill %1; wait 2>/dev/null
echo "T2 command -> [$(ssh -o BatchMode=yes hermes-box-tunnel 'echo MARK' 2>/dev/null)] rc=$?"
ssh -o BatchMode=yes -N -L 29122:127.0.0.1:22 hermes-box-tunnel 2>/dev/null & sleep 4
echo "T4 forward to another port -> $(nc -w 3 127.0.0.1 29122 </dev/null | head -c 20 | wc -c | tr -d ' ') bytes"; kill %1; wait 2>/dev/null
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -R 127.0.0.1:29123:127.0.0.1:22 hermes-box-tunnel 2>/dev/null; echo "T5 remote forward -> rc=$?"
ssh -o BatchMode=yes -N -L 29124:/run/dbus/system_bus_socket hermes-box-tunnel 2>/dev/null & sleep 4
echo "T6 unix socket -> $(printf '\0AUTH\r\n' | nc -w 3 127.0.0.1 29124 | wc -c | tr -d ' ') bytes"; kill %1; wait 2>/dev/null
```

Expected: `T1 … -> 302`; `T2 command -> [] rc=1`; `T4 … -> 0 bytes`; `T5 remote forward -> rc=255`;
`T6 unix socket -> 0 bytes`. Any other result: stop, remove the line on the box
(`cp -p ~/.ssh/authorized_keys.before-tunnel-key ~/.ssh/authorized_keys`) and report it. If `T1` prints `000`
with "Permission denied" in view, do not retry: describe the message, do not paste it (it prints the address).

LAPTOP 4: only now, switch the login item.

```bash
P=~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist
[ "$(plutil -extract ProgramArguments.9 raw "$P")" = "hermes-box" ] && plutil -replace ProgramArguments.9 -string hermes-box-tunnel "$P" && launchctl bootout gui/$(id -u)/com.dentaledge.hermes-box-tunnel; sleep 2; launchctl bootstrap gui/$(id -u) "$P"; sleep 6
launchctl print gui/$(id -u)/com.dentaledge.hermes-box-tunnel | grep -E '^\s*state = '; curl -s -o /dev/null -w 'dashboard through the link -> %{http_code}\n' --max-time 5 http://127.0.0.1:19119/
```

Expected: `state = running` and `-> 302`.

LAPTOP 5: only now, the administrative key leaves the keychain. The first line removes the two settings from
the `hermes-box` alias only; without that, the next typed passphrase would be stored again.

```bash
cp -p ~/.ssh/config ~/.ssh/config.before-tunnel-key && awk '/^Host /{inblk=($2=="hermes-box" && NF==2)} !(inblk && tolower($1) ~ /^(usekeychain|addkeystoagent)$/)' ~/.ssh/config.before-tunnel-key > ~/.ssh/config && chmod 600 ~/.ssh/config
ssh-add --apple-use-keychain -d ~/.ssh/vps-hermes; ssh-add -l | grep -c vps-hermes
ssh -G hermes-box | grep -iE '^(usekeychain|addkeystoagent) '
```

Expected: `Identity removed: …`, `0`, and `addkeystoagent false` (and `usekeychain no` if the line is
printed). If either still says yes, a `Host *` block sets it: say so and stop.

LAPTOP 6, in a NEW terminal window, ONCE (this single attempt does count on the box):

```bash
ssh -o BatchMode=yes hermes-box true; echo "rc=$?"
```

Expected: `rc=255`. Describe the message, do not paste it. Then `ssh hermes-box` asks for the passphrase:
type it, and on the box run the clean-up: `rm ~/.ssh/authorized_keys.before-tunnel-key`. On the laptop:
`rm ~/.ssh/config.before-tunnel-key`.

Closing paragraph: for a work session with several connections, `ssh-add -t 1h ~/.ssh/vps-hermes` keeps the
key in memory for an hour and stores nothing in the keychain. To replace the limited key later: make a new
one, add its line, test, switch, then delete the old line; the next review's D1.7 shows a new `sha12`, and
the evidence says so.

- [ ] **Step 3: "A security review".** In step 2 add, before the probes: "First read each start time and the
  update log, and write any restart since the last PASS into the evidence (D4.6 asks): `for u in docker
  hermes-docker-proxy hermes-broker hermes-app-broker@ads-audit; do echo "$u $(systemctl show $u -p
  ActiveEnterTimestamp --value)"; done; uptime -s; grep -E 'Start-Date|Commandline' /var/log/apt/history.log |
  tail -6`. After a pull that changed a file a service loads, restart that service before collecting
  (`sudo systemctl restart <unit>`): the trial collection's D4.6 `files_newer_than_start` names it." In step
  3's command add `--last-pass-collected-at <the last PASS box bundle's collected_at>` and one sentence: "It
  is in the last PASS report's header from review #9 on; for review #9 itself, read it from review #8's
  bundle." Change the opening sentence's "Since checklist v1.17" list to add "since v1.18 it also reads the
  accepted SSH keys (D1.7) and each service's start time (D4.6)".

- [ ] **Step 4: The README.** In "Using the Hermes Desktop app against the box": the alias in step 1 becomes
  `hermes-box-tunnel` with the block of LAPTOP 2 (no keychain lines); step 2's keychain paragraph is replaced
  by "The link uses a key of its own, limited on the box to this one forward (BRING-UP step 7f). It has no
  passphrase: the limits on the box are its protection. The administrative key (`hermes-box`) is not in the
  keychain and asks for its passphrase."; step 3's command ends `hermes-box-tunnel`. Keep the two failure
  notes; add that `Permission denied` on the link now means the limited key's line is missing on the box.

- [ ] **Step 5: Check and commit.**

```bash
grep -nE "hermes-box[^-]" infra/hermes-agent/README.md | head; grep -c "Step 7e\|Step 7f" infra/hermes-agent/deploy/BRING-UP.md
infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/deploy/provision.test.py
git add infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): BRING-UP step 7e (replace the dashboard password) and 7f (a limited key for the forward)"
```

Expected: every remaining `hermes-box` mention in the README is the administrative alias on purpose; at
least `2` headings; the suites pass. The blocks in the runbook must be character for character the ones
Tasks 1 and 2 rehearsed: `diff` them against the rehearsal transcript before committing.

---

### Task 7: Findings F55 to F57

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (new section after "F52 to F54",
  before "Final state of the box")

- [ ] **Step 1: Add the section.**

```markdown
### F55 to F57: opened at security review #8 (2026-10-07)

Review #8 passed 35 of 35 and listed eleven entries beside the checklist. These three are the ones that
are findings; the change that answers them is checklist v1.18
(`docs/superpowers/plans/2026-10-07-review-9-box-change.md`), judged by review #9.

| # | Finding | Decision | Now |
|---|---|---|---|
| F55 | Automatic security updates restart the Docker proxy and the mutation broker. Seen twice: 2026-09-30 06:23 UTC and 2026-10-07 06:45 UTC, each a few seconds after `unattended-upgrade` installed a package. The cause is shown by timing only: the update tool's own restart list was not attached. D4.2 cannot show such a restart once a `daemon-reload` has followed it (review #8, entries 1 and 2). | accepted at review #8's sign-off: security updates should not wait; the proxy comes back in under a second with the reviewed unit file; an audit that loses it fails closed | **accepted (standing)**. Since v1.18, D4.6 reports every service's start time and the operator explains each start after the last PASS. Not done: excluding the two units from automatic restarts. |
| F56 | The dashboard password was hashed on 2026-10-07 (step 7d) but not changed: the value that had been in plaintext in the gateway `.env` and in the gateway container's environment still signed in, and the leak checks could no longer look for it (review #8, entry 3). | fix at the next box change | **fixed by BRING-UP step 7e** once it is run on the box: a new password, hashed from a hidden prompt, and a new signing secret, so sessions opened with the old password end too. The step proves that the old password is refused. Rehearsed on the laptop (`docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`). |
| F57 | The laptop is a standing way in. A login item keeps an SSH forward to the dashboard open, and it used the administrative key, whose passphrase was in the macOS keychain: an unlocked laptop gave a shell on the box as well as the dashboard's sign-in page (review #8, entry 4). No review item read `authorized_keys`. | reduce | **reduced by BRING-UP step 7f** once it is run: the forward has a key of its own that the box limits to that one forward (no terminal, no command, no other forward in either direction, each measured), the administrative key's passphrase is out of the keychain (operator decision 2026-10-07), and D1.7 reports every accepted key. What remains, and is decided at review #9's sign-off: any process on the unlocked laptop reaches the dashboard's sign-in page and the unauthenticated `/api/status` (F11); the limited key has no passphrase, so a copy of its file gives the same reach. |
```

- [ ] **Step 2: Commit.**

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "docs(hermes): findings F55 to F57, opened at review #8"
```

---

### Task 8: The independent review of the build, then the operator's word

- [ ] **Step 1: Everything passes on the branch.**

```bash
infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/deploy/provision.test.py && node scripts/run-all-tests.js
python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo "version_rc=$?"
git status --short | grep -v '^??' ; git log --oneline main..HEAD
```

Expected: all pass, `version_rc=0`, no modified tracked file except the two `evals/` files that predate this
work, and the commits of Tasks 1 to 7 plus the spec and this plan.

- [ ] **Step 2: A dry collection against the real repo tree,** to see the new items' real shape on real
  files (the laptop has no systemd, so the unit times are `could-not-check`; the file lists are real):

```bash
cd infra/hermes-agent/bin && python3 -c '
import importlib.util, json
s = importlib.util.spec_from_file_location("ce", "collect-review-evidence.py"); ce = importlib.util.module_from_spec(s); s.loader.exec_module(ce)
for u, (_, script) in ce.SERVICE_FILES.items(): print(u, ce._loaded_files(".", script))'
```

Expected: the proxy loads only its own script; the mutation broker and the app broker each load their script
and their `*_lib.py` modules; no test file and no collector appears.

- [ ] **Step 3: An independent review** by a fresh agent that did not write the code, given the spec, this
  plan and `git diff main...HEAD`, and asked for: correctness bugs; any path by which a key body, a key
  comment, an address or a secret could reach a bundle or a log; any `could-not-check` case that reads as
  healthy; checklist text that a healthy box would fail, or an unhealthy one pass; runbook blocks that can
  lock the operator out, write a secret to a file or a command line, or swallow a pasted line. Fix what it
  confirms (superpowers:receiving-code-review), re-run step 1, commit.

- [ ] **Step 4: Ask the operator.** Report in plain language: what was built, what the two rehearsals showed,
  what the review found and what was done about it, and what was not measured. Ask for the word to push and
  open the PR. The operator merges.

---

### Task 9: The rollout on the box (operator, block by block)

Each block is given to the operator one at a time, labelled, with what it does, what to expect and the stop
condition. Nothing here is run by the agent.

- [ ] **Step 1 (VPS):** `sudo -v` alone; then pull: `cd /opt/projects/claude_code && sudo git pull --ff-only && git log --oneline -1`.
- [ ] **Step 2 (VPS):** BRING-UP "A security review" step 2's start-time lines; record them.
- [ ] **Step 3 (VPS):** a trial collection (the collector run with a throwaway key and piped into the summary script of the handoff `docs/superpowers/handoffs/2026-10-07-next-session-open-items.md`, "The trial-collection summary") with a throwaway key (the handoff's summary script, extended by
  `print("D1.7", …)` and `print("D4.6", …)` lines that print counts, key types, option lists, times and file
  names). Expected before the change: D1.7 shows what Task 0 found; D4.6 shows real UTC times (this is the
  first sight of `ActiveEnterTimestamp` in the collector's parser: a `could-not-check` here means the box
  prints another format, and the build goes back to Task 4) and names any stale file.
- [ ] **Step 4 (VPS):** restart every service D4.6 named in `files_newer_than_start` (the app broker is
  expected: `client_audit_lib.py` changed after it started on 2026-10-01). Not during an audit. Record the time.
- [ ] **Step 5:** quit the Desktop app. BRING-UP step 7e, blocks 0 to 3. Record block 2's output. Sign in again.
- [ ] **Step 6:** BRING-UP step 7f, in the runbook's own order: VPS 0, LAPTOP 1, VPS 1 (left waiting), LAPTOP 1b, LAPTOP 2, LAPTOP 3a (the gate, alone), LAPTOP 3b, LAPTOP 4a, 4b, 4c, LAPTOP 5a, 5b, 5c, LAPTOP 6, 6b, then the clean-up. If Task 0 found a key on another account
  and the operator chose to remove it, the optional `VPS root key` block of step 7f, on the operator's decision.
- [ ] **Step 7 (VPS):** `sudo show-listener-check` ends `listener check: OK`; a second trial collection shows
  D1.7 with exactly the two keys and D4.6 with empty file lists.

---

### Task 10: Security review #9

As the handoff's "Running a review" section, with these additions:

- [ ] `--last-pass-execstart` and `--last-pass-collected-at`, both read from
  `infra/hermes-agent/security-reviews/review-8/bundle-box.json` on the laptop without printing the hash.
- [ ] The evidence file states: each `true` of D4.6 (the automatic updates under F55 if any, step 4's
  restarts, step 7e's recreate); whose each key of D1.7 is; step 7e's block 2 output as the answer to review
  #8's entry 10; the fingerprint's components and D7.1's `records` compared with review #8's bundle (the
  operator's statement, one last time); F55 to F57 under D9.1. Every statement in the operator's name is
  marked `[CONFIRM]` and confirmed before a reviewer sees it.
- [ ] `review-9/previous-pass-header.md` from review #8's report.
- [ ] If the box bundle is collected after 2026-10-12, one fresh chat audit first (D10.8).
- [ ] Both bundles and the sign-off on the same UTC day. The report's header carries the new lines of the
  template. No push without the operator's word.
