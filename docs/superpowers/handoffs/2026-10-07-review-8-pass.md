# Handoff 2026-10-07: review #8 PASS; the listener check and the hashed dashboard password are live

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`. This file carries no customer id, hostname, fingerprint or credential value. It supersedes
`2026-10-06-review-7-pass-key-rotated.md`.

## Where things stand

- **Security review #8: PASS, 35 of 35, checklist v1.17**, signed 2026-10-07. Report:
  `docs/security-reviews/2026-10-07-review-8.md`.
- **The box** is at checkout `cffe86c` (merge of PR #105), Hermes v0.21.5.
  - `hermes-listener-check.timer` records the gateway's listening ports every 15 minutes (F50). It records
    only. `sudo show-listener-check` reads it. Six clean runs at collection; no alert ever.
  - The gateway `.env` holds the dashboard password's scrypt hash (single-quoted) and a session-signing secret;
    the plaintext line is gone (F47). The password itself is in the operator's password manager only.
  - The OpenRouter key is the box-only key of 2026-10-06 (replace by 2027-10-06).
- **The operator's everyday client is the Hermes Desktop app** on the laptop, against the box's dashboard through
  an SSH forward kept open by a login item (README "Using the Hermes Desktop app against the box"). Chat only:
  the app's Settings, Model and Credentials screens edit the box's reviewed configuration.
- **Local, git-ignored evidence:** `infra/hermes-agent/security-reviews/2026-10-07-operator-evidence-review8.md`
  and `review-8/` (both bundles, three console screens, the previous-pass header).

## What this round found

1. **Compose cuts a bare password hash short** (F52): measured on the laptop before the box was touched. The
   installer writes it single-quoted and refuses a bare value holding `$`.
2. **Automatic security updates restart the Docker proxy and the mutation broker** (to be numbered F55): seen
   on 2026-10-07 at 06:45 UTC and on 2026-09-30. Accepted. D4.2's hash cannot show such a restart once a
   `daemon-reload` follows, so the operator states it.
3. **The independent review of the build caught a checklist error** that would have failed a healthy box
   (D2.1's `credentials` sentence). A test now ties the checklist's labels to the collector.

## Follow-ups, for the next box change (it re-opens the review)

- **Set a new dashboard password** (review #8 entry 3): the old one sat in plaintext on the box until
  2026-10-07. Redo BRING-UP step 7a, then 7d.
- **A separate SSH key for the laptop's forward**, limited to it (`restrict`, `permitopen`), no shell (entry 4).
- **Collector:** report each service's start time (entries 2 and 8); carry the fingerprint components and D7.1
  `records` in the report header (entry 9).
- **Findings document:** number F55; record entries 3 and 4 as findings.
- **Observe once:** a listener-check run that does not exit 0, then the timer's next run (entry 10). It will
  happen at the next gateway restart; `systemctl list-timers hermes-listener-check.timer` must still show a
  NEXT time.
- **Notification** when the listener check alerts (F54): a later feature.

Carried over: the old Google ADMIN token is still valid at Google (accepted under D3.2); the laptop Docker stack
is down and needs its own OpenRouter key before it runs again; thirteen brain candidates and eight zombie
duplicates await the operator's weekly review; `origin/proposal/2026-07-24_22-54-03` holds one commit not on
`main`. Tailscale is not adopted: the Desktop app works over the SSH forward
(`docs/evaluations/2026-10-06-desktop-app-to-the-box-tailscale.md`).

## For the next review (#9)

- `--last-pass-execstart` is review #8's `execstart_sha256`, the D4.2 value in `review-8/bundle-box.json`
  (equal to reviews #6 and #7). Copy it with `pbcopy`, read it on the box with `read -r -p`. Do NOT run BRING-UP's
  `ExecStart` reconstruction unless the bundle says `matches_last_pass: false`.
- Before collecting, read each service's start time and the automatic-update log, and state any restart:
  `systemctl show hermes-docker-proxy -p ActiveEnterTimestamp --value`, `/var/log/apt/history.log`.
- D10.8 needs a chat audit that returned `ok` within 7 days (the last was 2026-10-05; its row expires
  2026-10-12). D10.7's live refusal checks were last run 2026-10-02 and are good for 30 days.
- D10.5 (v1.17): the whole privacy page, the key's whole page, the API-keys list with fragments covered by a
  filled rectangle, plus the Workspaces, Members and Management Keys pages; where the key is stored; a search of
  the whole laptop home directory.
- D4.5: explain every `could-not-check` run that is not around a stated gateway restart, and every alert.
- The reviewer receives the previous PASS report's header and sign-off (REVIEWER-BRIEF item 7).
- Collect both bundles and sign on the same UTC day.

## Rules that apply

- No push and no PR without the operator's word; the operator merges.
- Build work: plan, implementer, independent review, then ask before pushing. Measure on the laptop first.
- Any change under `infra/hermes-agent/bin/` or `deploy/` changes the box fingerprint. Any change to
  `CHECKLIST.md` bumps the version above 1.17.
- Never put a client name, customer id, hostname, address, fingerprint or credential value in the repo, the
  brain or the conversation. Label every block VPS / LAPTOP / HERMES CHAT. A block that prompts is one function
  followed by its call; run `sudo -v` alone first. Error messages from `ssh` print the address: describe them.
- The laptop reaches the box as `hermes-box` (an alias in the laptop's `~/.ssh/config`), so no block needs the
  address.
- The project's secret-read guard blocks the agent from reading `.env` files, and commands that name one.
