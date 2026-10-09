# Handoff 2026-10-08: the review #9 box change is rolled out; security review #9 is next

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written
as `<client>`. This file carries no customer id, hostname, address, fingerprint or credential value. Where it
differs from `2026-10-07-next-session-open-items.md`, this one is later.

## Where things stand

- **`main` is at `df58e10`** (merge of PR #107). **The box is at checkout `df58e10`** (pulled 2026-10-08).
- **Checklist v1.18** (37 items: new D1.7 accepted SSH keys, D4.6 service start times) is on the box.
- **Rolled out on 2026-10-08, by the operator, block by block** (every output was as the runbook expects):
  - BRING-UP step 7e: a new dashboard password and a new signing secret. Gateway recreated about 18:10 UTC.
  - BRING-UP step 7f: the laptop's forward runs on its own limited key (`hermes-box-tunnel`); the
    administrative key's passphrase is out of the keychain and is typed; the unused key on `root` was removed.
  - `hermes-app-broker@ads-audit` restarted at 2026-10-08 17:57:17 UTC (D4.6 had named `client_audit_lib.py`).
- Step 7f's last block finished about 2:58 pm on the operator's clock (laptop time zone EDT, UTC-4), which is about 18:58 UTC `[CONFIRM]`. The Hermes Desktop app is connected and works with the new dashboard password (operator, 2026-10-08).
- **Security review #9 has not started.** Nothing is owed on the box before it.

## Evidence already gathered for review #9 (operator's outputs, 2026-10-08)

Put these in the operator evidence file. Every statement in the operator's name is marked `[CONFIRM]` and
confirmed by the operator before a reviewer sees it.

- **Before any change** (after the pull): `docker` started 2026-09-21 16:49:31 UTC; `hermes-docker-proxy` and
  `hermes-broker` 2026-10-07 06:45:46 UTC (before review #8's collection, 2026-10-07T16:21:22Z);
  `hermes-app-broker@ads-audit` 2026-10-01 23:04:14 UTC; boot 2026-09-21 15:09:38. Update log:
  `unattended-upgrade` on 2026-10-07 06:45:39 and 2026-10-08 06:58:35 (the second restarted neither service).
- **sshd `Match` count: `0`** (covers `/etc/ssh/sshd_config` and `/etc/ssh/sshd_config.d/*.conf`).
- **Trial collection before the changes:** 30 items, none not observed, `collector_rc=0`. D1.7: 34 accounts,
  port start `1024`, the eight sshd settings as the checklist states, two key files (`hermesops`, `root`), each
  one `ssh-ed25519` with no options. D4.6: every start `after_last_pass False`; `files_newer_than_start`
  named `client_audit_lib.py` for the app broker only.
- **Restarts since the last PASS that D4.6 will show, and why:**
  - `hermes-app-broker@ads-audit`, 2026-10-08 17:57:17 UTC: restarted by the operator because D4.6 named a
    file it loads that had changed since its start.
  - the gateway container, 2026-10-08 about 18:10 UTC: BRING-UP step 7e, block 2 (the collector's
    `StartedAt` gives the exact time).
- **Step 7e:** block 0 the three names; block 1 three `install-env-secret:` lines; block 2 `STOP_EXIT=0`,
  `check_while_stopped_rc=1` with systemd's "Job … failed", `UP_EXIT=0`, `hermes-agent running Up 25 seconds`,
  `hash: file == container (len 86)`, `secret: in the container (len 44)`, `plaintext: not in the container`,
  `check_after_rc=0`, `listener check: OK`, timer NEXT 2026-10-08 18:25:44 UTC; block 3 `401`, `401`, `200`.
  **This is review #8's entry 10** (a listener-check run that did not exit 0, then an `ok` run, the timer
  still scheduled). D4.5's `history_counts` will hold one `could-not-check`: it is this stated recreate.
- **Step 7f:** `VPS look` as on the first look; `VPS root key` (a) `same` (root's key was the operator's own
  administrative key, placed at the first bring-up); (b) moved aside, later deleted in the clean-up;
  port start `1024`; `KEY MADE`; `182 characters`; `ADDED: 2 key line(s), mode 600`; alias count `3`;
  **gate `rc=1`**; T1 `302`, T4 `0 bytes, link up`, T5a `refused`, T5b `refused`, T6 `0 bytes, link up`,
  T7 `rc=255`; `SWITCHED IN THE FILE`; `RELOADED: bootstrap rc=0`; `state = running`, `302`,
  `ssh on the new alias: 1; ssh on the old alias: 0`; `PASSPHRASE OK` after asking; `EDITED: 2 line(s)
  removed`, `addkeystoagent false`, `UseKeychain lines left in the file: 0`; agent before `1`, after `0`,
  `keychain load rc=0`, supplied by the keychain `0`; `ssh hermes-box` asked for the passphrase and got in;
  after the login `0`, `rc=0`, `0`. Final look: `hermesops authorized_keys lines=2 types= 2 ssh-ed25519;
  options=1`, no `root` line.
- **D1.7's statement of whose each key is:** the administrative key (the operator's, from the first
  bring-up); the forward's key, made on 2026-10-08 in step 7f. The key on `root` was removed on 2026-10-08.

## Review #9: how to run it

As `2026-10-07-next-session-open-items.md`, "Running a review", with:

- The collector takes two baselines from review #8's box bundle
  (`infra/hermes-agent/security-reviews/review-8/bundle-box.json`): `--last-pass-execstart` (copy it on the
  laptop without printing it) and `--last-pass-collected-at 2026-10-07T16:21:22Z`.
- **The agent can no longer run `ssh hermes-box` or `scp hermes-box:…`**: the key asks for its passphrase.
  Every box block goes through the operator; copying the bundle off the box is the operator's `scp`.
  For a work session, `ssh-add -t 1h ~/.ssh/vps-hermes` keeps the key in memory for an hour.
- The checklist has 37 items; the trial summary prints `items 30` (30 box probes).
- The fingerprint's components and D7.1 `records` are compared with review #8's bundle by the operator's
  statement, one last time; review #9's header carries them from then on.
- `review-9/previous-pass-header.md` is made from review #8's report.
- Both bundles and the sign-off on the same UTC day.

## Dates that matter

- **2026-10-09:** the two `run`/`ok` results of 2026-10-02 expire on the box.
- **2026-10-12:** the last `run`/`ok` result (2026-10-05) expires. A box bundle collected after that needs
  one fresh chat audit first (D10.8).
- **2026-11-01:** D10.7's three live refusal checks leave their 30 days.

## Follow-ups found during the rollout (not done)

Each is a change under `deploy/`, so it changes the box fingerprint: do them with the next box change, not
alone.

- BRING-UP LAPTOP 4c expects one `state = running` line; this macOS also prints two `state = active` lines
  (nested sections of `launchctl print`). Say so in the expected text.
- LAPTOP 5c's first and third lines print the key's path and comment (`Identity added: …`, `Identity
  removed: …`): tell the operator not to paste them.
- The measured facts of this rollout (the `launchctl` lines, the keychain lines with the real key and macOS's
  own agent, `keychain load rc=0`, LAPTOP 6 on macOS, the gate and the six tests against the real box) can
  replace the "first run on this laptop / not rehearsed" marks.
- Two known false-FAIL cases in D1.7's reader (an unbalanced double quote in a key's comment; a CR line
  ending): not seen on this box (`unparsed 0`).

## Housekeeping still open (operator's weekly review)

As in the 2026-10-07 handoff, item 3. Also: the local branch `feat/review-9-box-change` is merged and can be
deleted; the build's working notes are in the git-ignored `.superpowers/sdd/2026-10-07-review-9-box-change/`
(`progress.md` is the full record of every review finding and ruling) and can be deleted once review #9 is
signed.

## Working with this operator

As in the 2026-10-07 handoff. One addition: ask for output "starting after the prompt line" every time; a
pasted prompt carries the host name.
