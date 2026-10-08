# Handoff 2026-10-07 (evening): what is open after review #8, and how to pick it up

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`. This file carries no customer id, hostname, address, fingerprint or credential value. It adds the
working detail to `2026-10-07-review-8-pass.md`, which stays the record of review #8; where the two differ, this
one is later.

## Where things stand

- **`main` is at `23a27bb`** (merge of PR #106). **The box is at checkout `cffe86c`** (merge of PR #105); `main` is
  ahead of it by documentation only, which the box fingerprint does not cover. Nothing is owed on the box.
- **Security review #8: PASS 35/35, checklist v1.17, signed 2026-10-07** (`docs/security-reviews/2026-10-07-review-8.md`).
- **Live on the box since 2026-10-07:**
  - `hermes-listener-check.timer`: records the gateway's listening TCP ports every 15 minutes, read from the
    host's `/proc`. Records only. `sudo show-listener-check` ends with `listener check: OK` when all is well.
  - The dashboard signs in against a scrypt hash, with a session-signing secret; no plaintext password on the box.
- **The operator's everyday client is the Hermes Desktop app** on the laptop, connection named "Hermes Server",
  URL `http://127.0.0.1:19119`. Chat only: its Settings, Model and Credentials screens edit the box's reviewed
  configuration.
- **Merged this round:** #101 to #104 (docs), #105 (the listener check, the dashboard hash, checklist v1.17),
  #106 (review #8).

## Open work, in the order proposed to the operator

### 1. The next box change, then review #9 (one change, one review)

Build work: plan in `docs/superpowers/plans/`, measure on the laptop first, implementer, independent review, ask
before pushing. The operator has agreed to these four as the scope; nothing is planned or built yet.

| Item | Source | Notes for the plan |
|---|---|---|
| **A new dashboard password** | review #8, entry 3 | The current one sat in plaintext in the gateway `.env` and the container's environment until 2026-10-07. BRING-UP step 7a writes a plaintext line and removes every `HERMES_DASHBOARD…` line, so the hash and the signing secret go too; then step 7d. Better: a block that hashes a NEW password straight to the hash line (no plaintext step), which needs `strip` then `set --quote single --stdin`, a recreate, and the 401/200 control. Rehearse it on a throwaway Compose project first, as step 7d was. |
| **A restricted SSH key for the laptop's forward** | review #8, entry 4 | Today the login item uses the operator's admin key (`~/.ssh/vps-hermes`), whose passphrase is in the macOS keychain. Wanted: a second key in `hermesops`'s `authorized_keys` with `restrict,port-forwarding,permitopen="127.0.0.1:9119"` and no shell; the laptop alias `hermes-box` (or a new `hermes-box-tunnel`) uses it; the admin key's passphrase can then leave the keychain. This changes `authorized_keys` on the box: check what D1.x measures (D1.2 to D1.5) and whether the checklist must expect a second key. |
| **The collector reports each service's start time** | review #8, entries 2 and 8; F55 | `ActiveEnterTimestamp` for `hermes-docker-proxy`, `hermes-broker`, `hermes-app-broker@ads-audit`, and the gateway container's start time, in D4.2 or a new item; the checklist asks the operator to explain any start later than the previous collection. Also wanted by entry 8: compare a service's start time with the modification time of the files it loads. |
| **Findings document** | review #8 sign-off | Number F55 (automatic security updates restart the Docker proxy and the mutation broker: seen 2026-09-30 06:23 and 2026-10-07 06:45 UTC, by `unattended-upgrade`; accepted). Record entries 3 and 4 as findings. Carry the fingerprint's components and D7.1 `records` in the report header (entry 9; `REPORT-TEMPLATE.md`). |

A checklist change bumps the version above 1.17. Anything under `bin/` or `deploy/` changes the fingerprint.

### 2. Observe once on the box (no change needed)

A listener-check run that does not exit 0, followed by the timer's next run (review #8, entry 10). It happens at
the next gateway restart: afterwards `sudo show-listener-check` shows a `could-not-check` count, and
`systemctl list-timers hermes-listener-check.timer --no-pager` still shows a NEXT time. Record it in the next
evidence file.

### 3. The operator's weekly review (interactive; use the `brain-weekly-review` and `brain-promote` skills)

- Fourteen untracked candidates in `.project-brain/decisions/candidates/`, the newest two being review #7's and
  review #8's PASS. Eight more are zombie duplicates of promoted entries; the brain guard blocks the agent from
  deleting them, so the operator removes them.
- `docs/superpowers/handoffs/2026-10-05-hermes-v0-21-5-live-review-7-next.md` and this file are untracked. Commit
  or delete.
- Six merged local branches can be deleted: `docs/desktop-app-usage`, `docs/desktop-tailscale-evaluation`,
  `docs/review-7-follow-ups`, `docs/review-7-pass`, `docs/review-8-pass`,
  `feat/review-8-listener-check-dashboard-hash`. `origin/proposal/2026-07-24_22-54-03` holds one commit not on
  `main`.
- Two modified files under `evals/` predate this work and were not touched.
- Add to the weekly routine: `sudo show-listener-check` on the box. Until a notification exists (F54), it is the
  only way an alert reaches the operator.

### 4. Later, not scheduled

- A notification when the listener check alerts (F54).
- Tailscale: evaluated, not adopted (`docs/evaluations/2026-10-06-desktop-app-to-the-box-tailscale.md`). It would
  only replace the SSH forward; item 1's restricted key is the cheaper hardening.
- The retired Google ADMIN token is still valid at Google (accepted under D3.2; blocked on the shared grant).
- The laptop's own Docker copy of Hermes is down, and its `.env` has an empty `OPENROUTER_API_KEY`: create a
  separate laptop key before starting it. Never the box's.
- The laptop Hermes app (a git install on the `main` update track) has a stale
  `~/.hermes/.hermes-update-in-progress.lock` from 2026-10-06; its in-app update may keep failing with "Another
  Hermes update is already running". The operator chose to leave it. "Official releases only" is a separate
  application to install, not a setting.

## Dates that matter

- **2026-10-09:** the two `run`/`ok` results of 2026-10-02 expire on the box.
- **2026-10-12:** the last `run`/`ok` result (2026-10-05) expires. A review collected after that needs one fresh
  chat audit first (D10.8; one run per client per UTC day).
- **2026-11-01:** D10.7's three live refusal checks (run 2026-10-02) leave their 30 days.
- **2027-10-06:** the OpenRouter key is due for replacement (BRING-UP "Replace the OpenRouter key").

## How the laptop reaches the box

- `~/.ssh/config` has `Host hermes-box` (the address lives only there). `ssh hermes-box …` and
  `scp hermes-box:file …` need no address in a block.
- `~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist` keeps `127.0.0.1:19119 -> 127.0.0.1:9119` open
  (`launchctl print gui/$(id -u)/com.dentaledge.hermes-box-tunnel`; log `~/Library/Logs/hermes-box-tunnel.log`).
- The box runs fail2ban: never let anything retry a login that fails.

## Running a review: what this round taught

1. **Before collecting, read each service's start time and the update log**, and state any restart in the
   evidence: `systemctl show hermes-docker-proxy -p ActiveEnterTimestamp --value` (also `hermes-broker`,
   `hermes-app-broker@ads-audit`, `docker`), `uptime -s`, `/var/log/apt/history.log`. Use
   `journalctl … --no-hostname`.
2. **`--last-pass-execstart`** is review #8's D4.2 `execstart_sha256` (equal to reviews #6 and #7). Copy it on the
   laptop without printing it, and read it on the box with `read -r -p`:
   `python3 -c 'import json; print(json.load(open("infra/hermes-agent/security-reviews/review-8/bundle-box.json"))["items"]["D4.2"]["data"]["execstart_sha256"], end="")' | pbcopy`
3. **Do not run BRING-UP's `ExecStart` reconstruction unless the bundle says `matches_last_pass: false`.** After a
   `daemon-reload` the line returns to its `[n/a]` / `pid=0` form and matches by itself. (In review #8 the agent
   predicted `false`, built a reconstruction step and compared the wrong hash; the bundle said `true`.)
4. **Collect both bundles and sign on the same UTC day.** A correction to the evidence on a later day means a new
   laptop bundle; a change to the box means a new box bundle.
5. **The laptop bundle** needs the ads repo at the pin with no modified tracked file: stash
   `.claude/settings.json`, `git checkout --detach 81103e1a3b563d97b4a1087fc35c29f9e74f120f`, collect, then
   `git checkout main` and `git stash pop`. The customer id is typed at a `read` prompt.
6. **D10.5 at v1.17:** the whole privacy page; the key's whole page; the API-keys list with fragments covered by
   a FILLED rectangle; the Workspaces, Members and Management Keys pages; a search of the whole laptop home
   directory; where the key is stored. The operator has stated: one workspace, no other member, no management key.
7. **The reviewer** is a fresh agent given only what `REVIEWER-BRIEF.md` lists, including the previous PASS
   report's header and sign-off (make `review-9/previous-pass-header.md` from review #8's report). It leaves the
   sign-off empty; the agent drafts it from the confirmed evidence and the operator confirms every decision line.
8. **A statement in the operator's name is confirmed by the operator before a reviewer sees it.** Mark drafts
   `[CONFIRM]`. Twice this round a statement the operator had confirmed turned out untrue once a screen or a
   search showed more (the Data Training toggle, the "dedicated" key): check what can be checked.

### The trial-collection summary (not in the repo)

Pipe the collector into it; it prints statuses, labels, ports and counts, never a value. On the box, after
`K=$(openssl rand -hex 32); echo "throwaway key: $K"`:

```bash
cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --fp-key-tty | python3 -c '
import json,sys
b=json.load(sys.stdin); it=b["items"]
print("items", len(it), "not_observed", [k for k in it if it[k]["status"]!="observed"])
d=it.get("D4.1",{}).get("data",{})
for k in ("listeners","docker_dns_listeners","secret_env"): print("D4.1", k, d.get(k,"MISSING"))
f=it.get("D2.1",{}).get("data",{}).get("files",[])
for r in f:
    if r.get("label"): print("D2.1", r["label"], r.get("kind"), r.get("owner"), r.get("mode"), "held", r.get("secrets_held"), "unsearchable", r.get("secrets_not_searchable"), "shaped", r.get("credential_shaped_names","-"))
print("D2.1 kinds", sorted({str(r.get("kind")) for r in f}))
c=b.get("credentials")
print("credentials", sorted((x.get("label") or x.get("role"), x.get("sha12") is not None if "label" in x else True) for x in c) if isinstance(c,list) else c)
p=it.get("D4.2",{}).get("data",{})
print("D4.2 active", p.get("active"), "matches_last_pass", p.get("matches_last_pass"), "drop_ins", p.get("drop_in_paths"))
q=it.get("D4.5",{}).get("data",{})
for k in ("timer_active","timer_enabled","installed_equal_repo","drop_in_paths","state_dir","last_age_seconds","alert_present","history_counts","alert_log"): print("D4.5", k, q.get(k,"MISSING"))
l=q.get("last") or {}
print("D4.5 last", l.get("status") if isinstance(l,dict) else l, l.get("listeners") if isinstance(l,dict) else "", l.get("docker_dns_listeners") if isinstance(l,dict) else "")
e=it.get("D10.8",{}).get("data",{})
print("D10.8 out_of_whitelist", e.get("out_of_whitelist"), "run_ok", sum(1 for r in e.get("results",[]) if r.get("op")=="run" and r.get("status")=="ok"))
print("D7.1 records", it.get("D7.1",{}).get("data",{}).get("records"))
print("fingerprint_complete", b["fingerprint"].get("complete"))
'; echo "collector_rc=${PIPESTATUS[0]}"
```

Healthy at review #8: 28 items, none not observed; `listeners [9119]`, `docker_dns_listeners 1`; `secret_env`
`matches-file` for `openrouter-key`, `dashboard-password-hash`, `dashboard-session-secret` and `unset` for
`dashboard-password`; six credential rows, `dashboard-password-hash` without a fingerprint; D4.5 timer `active`
and `enabled`, `state_dir` `root root 0o700`, `last ok [9119] 1`; `records 0`.

## Working with this operator

- The operator is not a coder. Explain in plain language, say what each block does and what to expect, and give
  the stop condition. One block per paste, labelled VPS / LAPTOP / HERMES CHAT / OPENROUTER CONSOLE.
- A block that prompts (a `read`, a hidden key prompt) is pasted ALONE or is one function followed by its call;
  run `sudo -v` alone first. A prompt in the middle of a pasted block swallows the next line.
- Ask for output "starting after the prompt line": the shell prompt carries the hostname. `ssh` error messages
  print the address: ask the operator to describe them, not paste them.
- Prefer commands that print yes/no, counts, names and lengths. The agent may compare two values locally and
  print only whether they are equal.
- The operator decides by choosing among options with a recommendation; decisions made in their name are read
  back to them before anything is committed.

## Rules that apply

- No push and no PR without the operator's word; the operator merges.
- Verify against primary sources before an important decision, and record them in `docs/evaluations/`.
- Never put a client name, customer id, hostname, address, fingerprint or credential value in the repo, the brain
  or the conversation.
- The project's secret-read guard blocks the agent from reading `.env` files and from running shell commands
  that name one, including a `grep` pattern. Give the operator a command that prints names only, or put the
  transformation in a script file.
- `infra/hermes-agent/bin/run-bin-tests.sh`, `python3 infra/hermes-agent/deploy/units.test.py`,
  `python3 infra/hermes-agent/deploy/provision.test.py` and `node scripts/run-all-tests.js` pass before a commit
  that touches `infra/hermes-agent/`.
