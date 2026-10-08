# Review #9 box change: a new dashboard password, a limited key for the laptop link, service start times, and findings F55 to F57 — Design

Date: 2026-10-07. Approved in conversation by the operator on 2026-10-07 (decisions 1 to 3 below). This file is
the written form for the operator's review; the plan follows in `docs/superpowers/plans/`.

Source: security review #8 (`docs/security-reviews/2026-10-07-review-8.md`), "Not on the checklist" entries 1 to
4, 8, 9 and 10, and the handoff `docs/superpowers/handoffs/2026-10-07-next-session-open-items.md`.

## Goal

One change to the box, judged by one security review (#9), that closes what review #8 left open:

- the dashboard password that sat in plaintext on the box until 2026-10-07 stops working (entry 3);
- the laptop's always-on link stops using the administrative SSH key (entry 4);
- a review can see when each service last started and whether it runs older code than the box holds
  (entries 2 and 8);
- the findings document and the report header carry what review #8 asked for (entries 1 and 9).

Success: review #9 is PASS on checklist v1.18 (37 items), with the second key, the start times and the new
dashboard secrets visible in the evidence.

## Decisions made by the operator (2026-10-07)

1. The administrative key's passphrase leaves the macOS keychain. The operator types it once per work session.
2. The session-signing secret is replaced together with the password, so every existing dashboard session ends.
3. The limited key has no passphrase. Its protection is the limits the box puts on it.

## Part 1: a new dashboard password and signing secret

A new BRING-UP step, "Step 7e: Replace the dashboard password". Nothing under `bin/` changes for it:
`install-env-secret.py set` already replaces an existing line in place (`--quote single --stdin`), and
`strip` followed by `generate` replaces the signing secret.

Blocks, each for `hermesops@<host>`:

- **Block 0, alone:** `cd /opt/hermes-agent && sudo -v`.
- **Block 1 (one function and its call):** two hidden prompts for the NEW password. Refuses unless both are
  equal, 24 or more characters, letters and digits only. The password goes on stdin to `hash_password` inside
  the gateway container, and the hash on stdin to `install-env-secret.py set … --quote single --stdin`. Then
  `strip` and `generate` for `HERMES_DASHBOARD_BASIC_AUTH_SECRET`. A refusal writes nothing.
- **Block 2:** stop the gateway, run the listener check once (see "The listener-check observation"), recreate
  the gateway, compare the hash in the file with the hash in the container (equal, length 86), confirm the
  secret is in the container (length 44) and the plaintext variable is unset, run the listener check again.
- **Block 3 (one function and its call):** three sign-in attempts over loopback, each password on stdin: the
  OLD password is refused (401), a wrong one is refused (401), the NEW one is accepted (200).

Before block 1 the operator quits the Hermes Desktop app, so nothing retries a sign-in with the old password
while the step runs. After block 3 the operator signs in again in the app and updates the password manager.

**If it fails.** The hash is replaced before the gateway is recreated, so a mistake shows at block 3. The
remedy is to run the step again from block 0. SSH does not depend on the dashboard. Step 7a's plaintext
fallback is not used.

**What a review then shows.** D2.1's gateway row and D4.1's `secret_env` are unchanged in form. In the
report header, `dashboard-session-secret` has a new short fingerprint; the hash row is never fingerprinted.

**Measured on the laptop first** (throwaway Compose project, test values only, as step 7d was):
- the four blocks end to end, run twice in a row;
- `set` replaces the hash line in place and leaves every other line byte-identical;
- whether the dashboard limits repeated failed sign-ins: N wrong attempts, then the right password. If it
  locks out, the step says for how long.

The result is recorded in `docs/evaluations/`.

## Part 2: a limited SSH key for the laptop's forward

### On the box

A second line in `hermesops`'s `authorized_keys`, added by a runbook block (`provision.sh` accepts bare keys
only and is not changed). The line's options, each for a stated reason:

| Option | Why |
|---|---|
| `restrict` | no terminal, no agent or X11 forwarding, no `~/.ssh/rc` |
| `port-forwarding` | puts forwarding back, which `restrict` removed |
| `permitopen="127.0.0.1:9119"` | a local forward may reach the dashboard's port and nothing else |
| a `permitlisten` value that allows nothing useful | `port-forwarding` also puts REMOTE forwarding (`ssh -R`) back; without this the key could open listeners on the box |
| `command="…"` naming a program that only exits | `restrict` does not stop `ssh host <command>`; a forced command does. The link uses `ssh -N`, which asks for no command, so it is unaffected |

The handoff's recipe (`restrict,port-forwarding,permitopen=…`) had neither of the last two. The exact
`permitlisten` value and forced command are fixed by the rehearsal, not by this document: the manual gives no
"none" form for `permitlisten` in `authorized_keys`.

### On the laptop

- A new key pair, `~/.ssh/hermes-box-tunnel`, ed25519, no passphrase, mode 600.
- A new alias `Host hermes-box-tunnel`: the same address and user, `IdentityFile` the new key,
  `IdentitiesOnly yes`, `ForwardAgent no`, the keep-alive lines; no keychain lines.
- The login item (`com.dentaledge.hermes-box-tunnel.plist`) uses the new alias.
- The alias `hermes-box` loses `UseKeychain yes` and `AddKeysToAgent yes`. Without that edit the next typed
  passphrase would be stored in the keychain again.
- `ssh-add --apple-use-keychain -d ~/.ssh/vps-hermes` removes the key from the agent and its passphrase from
  the keychain (`man ssh-add` on this laptop, read 2026-10-07).

From then on `ssh hermes-box` and `scp hermes-box:…` ask for the passphrase, for the operator and for any
agent session alike.

### Order (fail2ban counts every refused attempt)

1. Add the line on the box from an administrative session, which stays open.
2. Test by hand, once each, with `BatchMode=yes`: the forward to 9119 works on a spare local port; a command
   is refused; a terminal is refused; a forward to another port is refused; a remote forward is refused; a
   forward to a unix socket is refused.
3. Only then switch the login item to the new alias, and check it (`state = running`, HTTP 302 on 19119).
4. Only then edit `hermes-box` and remove the passphrase from the keychain. Prove it: a new terminal, and
   `ssh -o BatchMode=yes hermes-box true` must FAIL locally. This one attempt counts on the box; it is run once.

**Measured on the laptop first:** an OpenSSH server of the box's own version in a throwaway container, with
the candidate line, and the six tests of step 2. The operator reads the box's version with one read-only
command (`ssh -V`), which prints no address.

### New checklist item D1.7 — the accepted SSH keys are the expected ones

Today no item reads `authorized_keys`, so a second key would be invisible to the reviewer.

The collector reports, for EVERY account in `/etc/passwd` (an account with no login shell can still be used
for forwarding), each file named by sshd's `authorizedkeysfile`:

- owner and mode of the file;
- for each key: its type, its options as a sorted list, and a short fingerprint (sha256 of the key body, 12
  characters). Never the key body, never the comment (a comment can hold a name or a host).
- from `sshd -T`: `authorizedkeyscommand`, `trustedusercakeys`, `authorizedprincipalsfile`,
  `allowtcpforwarding`, `permittunnel`, `gatewayports`: the other ways a key or a forward could be accepted.
- a line that does not parse as a key is counted, never skipped silently; an unreadable file is
  `could-not-check`.

Expected: `hermesops` holds exactly two keys, one with no options (the administrative key) and one with
exactly the option set above; no other key on any account unless the operator explains it; no key command, no
CA, no principals file. The report header carries the short fingerprints, so the next review sees a change.

What the box holds today is not known from the laptop. Before the expected text is final, the operator runs
one read-only block that prints account names, counts and key types only.

## Part 3: service start times — new checklist item D4.6

The collector reports:

- `ActiveEnterTimestamp`, as UTC, for `hermes-docker-proxy`, `hermes-broker`, `hermes-app-broker@ads-audit`
  and `docker`; the gateway container's `StartedAt`; the host's boot time;
- with the new flag `--last-pass-collected-at <the previous PASS bundle's collected_at>`, for each of those:
  `started_after_last_pass` (`true`, `false`, or `null` without the flag);
- for the three Hermes services: `files_newer_than_start`, the names of the files the service loads whose
  modification time is later than its start. The file list is the unit file, the service's script and the
  `bin/` modules it imports. A test derives the same list from the scripts' own import statements, so the
  list cannot fall behind the code.

A timestamp the collector cannot parse, or that is not UTC, is `could-not-check`.

Pass rule:

- a service or the container that started after the last PASS needs the operator's explanation (when, and
  what caused it: an automatic update under F55, a rollout step, a reboot). Unexplained: FAIL.
- a non-empty `files_newer_than_start` is a FAIL: the service runs older code than the box holds. The
  operator restarts it and re-collects.
- `null` without the operator's stated baseline is CANNOT-VERIFY.

D4.2 stays as it is. Its text gains one sentence: an equal hash does not show "not restarted"; D4.6 does.

The collector is tested with fake hosts on the laptop. The real format of `ActiveEnterTimestamp` on the box
is confirmed by the trial collection that every review already runs before the real one.

## Part 4: documents

- **Findings document:** F55 (automatic security updates restart the Docker proxy and the mutation broker;
  seen 2026-09-30 06:23 and 2026-10-07 06:45 UTC; accepted). F56 (the dashboard password was hashed, not
  changed: fixed by step 7e). F57 (the laptop is a standing way in to the dashboard: reduced by the limited
  key and decision 1; what remains is the dashboard's sign-in page and F11's `/api/status`, decided at
  sign-off).
- **`REPORT-TEMPLATE.md`:** the header gains the fingerprint's five components (shortened), D7.1's
  `records`, D1.7's key fingerprints and the collection time the next review passes to
  `--last-pass-collected-at`. `REVIEWER-BRIEF.md` item 7 already names the first two.
- **Review #8's report is not edited.** It is signed. At review #9 the operator states the components and
  `records` once more, as at review #8; from review #9 on the header carries them.
- **`CHECKLIST.md`:** `version: 1.18`; D1.7 and D4.6 added; D4.2's sentence; D9.1 names F55 to F57.
- **`BRING-UP.md`:** step 7e; "The limited key for the laptop link"; "A security review" names the new flag
  and the read of each service's start time before collecting.
- **`README.md`,** "Using the Hermes Desktop app against the box": the alias, the login item and the
  passphrase rule as they now are.

## The listener-check observation (review #8, entry 10)

Step 7e's block 2 stops the gateway, so it is used to see what entry 10 asked for: with the gateway stopped,
`sudo systemctl start hermes-listener-check.service` records `could-not-check` and exits non-zero; after the
recreate a second run records `ok`; `systemctl list-timers hermes-listener-check.timer` still shows a NEXT
time. D4.5 fails when the LAST run is not `ok`, so the second run is part of the block. The output goes in
review #9's evidence file.

## Rollout and review #9

1. Build on a branch: the collector, its tests, the checklist, the runbook, the documents. Both rehearsals on
   the laptop. An independent review of the build. The operator's word before any push; the operator merges.
2. On the box, block by block: pull; step 7e; the limited key (box, then laptop).
3. Review #9 as the handoff describes, with `--last-pass-execstart` and `--last-pass-collected-at` from
   review #8's bundle. Both bundles and the sign-off on the same UTC day.

The fingerprint changes (`code`, `checklist`). Neither the gateway `.env` nor `authorized_keys` is part of it.

Collecting by 2026-10-12 avoids a fresh chat audit (D10.8). After that date, one audit comes first.

## Out of scope

A notification when the listener check alerts (F54). Tailscale. Revoking the retired Google token. The
laptop's own Hermes copy and its update lock. Excluding the two services from automatic restarts (F55 is
accepted as it is).

## Risks

- **A lockout from the dashboard** (a mistyped new password): repeat step 7e. SSH is unaffected.
- **A ban by fail2ban** (the login item retrying a refused key): the hand tests come before anything retries.
- **A lockout from the box** is not possible through this change: the administrative key's line is not
  touched, and the session that adds the second line stays open until the hand tests pass.
- **The limited key's limits are weaker than designed** (remote or unix-socket forwarding): each is a test in
  the rehearsal and again on the box. If one cannot be closed by key options, the plan stops and the operator
  decides.
