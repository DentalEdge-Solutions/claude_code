# Review #8 box change: a periodic listener check, a hashed dashboard password, a session secret, and the runbook — Plan

> One change, one fingerprint change, one security review (#8). Build order: this plan, an implementer, an
> independent review, then ask the operator before pushing. Steps use checkbox (`- [ ]`) syntax.

**Goal.** Close what review #7 left open on the box: F50 (the API-server-off controls are measured only at
review time), F47 (a plaintext dashboard password in the gateway `.env`), the sign-out at every gateway
restart now that the Desktop app is the everyday client, and the runbook and checklist follow-ups.

**Decisions already made by the operator.**
- The listener check **records only**: it stops nothing and flips no switch (2026-10-07).
- Tailscale is out of scope (2026-10-06).
- The OpenRouter key is replaced every 12 months (2026-10-06); its steps move from the README to BRING-UP here.

**Measured facts this plan rests on.**
- `docs/evaluations/2026-10-07-dashboard-password-hash-and-session-secret.md`: a hash written raw into the
  `env_file` is silently truncated by Compose; single quotes or `$$` pass it intact; the plaintext variable wins
  over the hash; the signing secret keeps a session across a restart and a recreate.
- Review #7, D4.1: the gateway's listeners are `[9119]` and `docker_dns_listeners` is `1`.

## Global constraints

- Python stdlib only. No value of any secret is ever printed, logged or written to a state file: names, labels,
  ports, counts, timestamps and fixed words only. What cannot be measured is `could-not-check`.
- `CHECKLIST.md` goes to `version: 1.17`; items stay one line each; `check-checklist-version.py` passes.
- The D10.6 pinned `mcp_servers` canonical sha256 must not change.
- No client name, customer id, hostname, address other than loopback, or credential value in any file.
- `infra/hermes-agent/bin/run-bin-tests.sh`, `python3 infra/hermes-agent/deploy/units.test.py`,
  `python3 infra/hermes-agent/deploy/provision.test.py` and `node scripts/run-all-tests.js` pass.
- Commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push, no PR, without the operator's
  word. Nothing is run on the box by the build; the rollout is the operator's, block by block.

---

### Task 1: The periodic listener check (F50)

**Files:** new `bin/gateway_listeners.py` (shared parser), new `bin/check-gateway-listeners.py` and its test,
`bin/collect-review-evidence.py` and its test, new `deploy/hermes-listener-check.service`,
new `deploy/hermes-listener-check.timer`, new `deploy/show-listener-check`, `deploy/units.test.py`.

- [ ] **1. One parser.** Move the `/proc/net/tcp` parsing out of the collector's `_listeners` into
  `bin/gateway_listeners.py`: `parse(text) -> (sorted ports, docker_dns_count)` or raises `ValueError`
  (not exactly two tables, or a row that does not parse); `DOCKER_DNS_ADDRS` moves with it. The collector's
  D4.1 keeps its exact output and its `could-not-check` rules; its existing tests pass unchanged.
- [ ] **2. The check.** `bin/check-gateway-listeners.py`, run as root by systemd:
  - finds the one gateway container (`docker ps -q --no-trunc --filter label=com.docker.compose.service=hermes-agent`,
    a 64-character id), runs `docker exec <id> cat /proc/net/tcp /proc/net/tcp6`, and parses it;
  - `ALLOWED = (9119,)`. `status` is `ok` (every listening port is allowed and the DNS count is `1`),
    `alert` (a port outside `ALLOWED`, or a DNS count other than `1`), or `could-not-check` (no single gateway
    container, a failed `exec`, unparsable output). A stopped gateway is `could-not-check`, never `alert`;
  - writes, under `/var/lib/hermes/listener-check/` (`root:root 0700`, files `0600`), atomically:
    `last.json` (`{"ts", "status", "listeners", "unexpected", "docker_dns_listeners"}`), one line appended to
    `history.jsonl` (kept to the last 3,000 lines, about a month at four runs an hour), and, on `alert`,
    `ALERT` (the first alert's `ts` and `unexpected` ports; an existing `ALERT` is never overwritten);
  - prints one line, which the journal keeps:
    `hermes-listener-check: status=<s> listeners=<list> unexpected=<list> docker_dns_listeners=<n>`;
  - exits `0` on `ok`, `1` on `alert`, `2` on `could-not-check`, so `systemctl status` shows a failed run;
  - `--status` (read-only): the last result, its age in minutes, whether `ALERT` is present and since when, and
    counts by status over the history; exit `0` only when the last result is `ok`, it is under 45 minutes old
    and no `ALERT` is present;
  - `--clear-alert`: removes `ALERT` and appends a `{"ts", "status": "alert-cleared"}` line to the history.
- [ ] **3. Units.** `hermes-listener-check.service`: `Type=oneshot`, root, `UMask=0077`,
  `ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/check-gateway-listeners.py`, `NoNewPrivileges=true`,
  `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=yes`, `ReadWritePaths=/var/lib/hermes/listener-check`,
  `RestrictAddressFamilies=AF_UNIX` (it talks only to the Docker socket), `MemoryMax=128M`,
  `TimeoutStartSec=60`. `hermes-listener-check.timer`: `OnBootSec=3min`, `OnUnitActiveSec=15min`,
  `AccuracySec=1min`, `WantedBy=timers.target`. `deploy/show-listener-check`: a two-line wrapper for
  `check-gateway-listeners.py --status`, installed as `/usr/local/sbin/show-listener-check` like `show-audit`.
- [ ] **4. Review item D4.5** (collector `d4_5`, in `PROBES`): `timer_active` and `timer_enabled`
  (`systemctl is-active` / `is-enabled hermes-listener-check.timer`), `installed_equal_repo` for the two unit
  files, `drop_in_paths` for both, `last` (the content of `last.json`), `last_age_seconds`, `alert_present`
  with its `since` and `unexpected`, and `history_counts` by status. A missing state directory or an
  unreadable file is `could-not-check` for that field only.
- [ ] **5. Tests** (each fails before the change): the parser on the D4.1 fixtures; the check for `ok`, an
  extra port (`alert`, `ALERT` created once and not overwritten), a DNS count of `0` and `2`, no gateway, a
  failed `exec`, garbage output; the history cap; `--status` exit codes (fresh `ok`, stale, `ALERT` present);
  `--clear-alert`; no address or other `/proc` field in any output or file; D4.5 with a healthy fixture and
  with each field broken; `units.test.py` asserts the service's hardening lines and the timer's interval.

### Task 2: The dashboard's hashed password and signing secret (F47)

**Files:** `bin/install-env-secret.py` and its test, `bin/collect-review-evidence.py` and its test,
`.env.example`.

- [ ] **6. The installer can write a literal value.** `install-env-secret.py set --quote single` writes
  `NAME='value'`; it refuses a value that holds a single quote, and without the flag it refuses any value that
  holds `$` (so a hash can never again be written raw). Every other line stays byte-for-byte. Tests: the
  written line, both refusals, and that the file round-trips through the collector's env reader to the exact
  value.
- [ ] **7. The collector knows the two new secrets.** `OTHER_SECRET_NAMES[GATEWAY_ENV_FILE]` gains
  `("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", "dashboard-password-hash")` and
  `("HERMES_DASHBOARD_BASIC_AUTH_SECRET", "dashboard-session-secret")`. The hash is never fingerprinted
  (`UNFINGERPRINTED`): it is a verifier of a value a person may have chosen. The session secret is random and
  gets a sha12 in the credential set. Both join the known secrets for the leak checks and the output guard.
  The env reader must return the hash exactly as the gateway receives it when the file holds it single-quoted
  or `$$`-escaped: D4.1 `secret_env` is then `matches-file` for it. Tests: both spellings; the hash and the
  secret in the returned secrets and absent from the bundle; `secret_env` states for all four labels.
- [ ] **8. `.env.example`:** the dashboard block shows the hash and the secret as the form to use, with the
  quoting rule and the reason in two comment lines; the plaintext variable is marked as the old form.

### Task 3: Checklist v1.17, the runbook, the brief

**Files:** `deploy/security-review/CHECKLIST.md`, `REVIEWER-BRIEF.md`, `REPORT-TEMPLATE.md` (if it lists
items), `bin/security-review-checklist.test.py`, `deploy/BRING-UP.md`, `README.md`, the findings document.

- [ ] **9. CHECKLIST → 1.17**, with a header note. Changes:
  - **D2.1:** the gateway row's `secrets_held` is exactly one of `["openrouter-key"]` (dashboard off),
    `["openrouter-key", "dashboard-password"]` (the old form) or
    `["openrouter-key", "dashboard-password-hash", "dashboard-session-secret"]` (the new form; the secret is
    optional). `dashboard-password` together with `dashboard-password-hash` is a FAIL (the plaintext wins, so
    the hash does nothing).
  - **D4.1:** `secret_env` has a state for each of the four labels; each is `matches-file` when D2.1 names it
    and `unset` when it does not.
  - **D4.5 (new), "The listener check is live":** expected `timer_active: active`, `timer_enabled: enabled`,
    both units `installed == repo`, `drop_in_paths` `[]`, `last.status: ok`, `last_age_seconds` under 2,700,
    `alert_present: false`. A stopped or disabled timer, a unit that differs, a drop-in, or a last result older
    than 45 minutes is a FAIL. `alert_present: true`, or an `alert` in `history_counts`, needs the operator's
    explanation of each one; unexplained, it is a FAIL. `could-not-check` is CANNOT-VERIFY.
  - **D7.1:** documents `records` (the count of files under the governance store's `records/`; under the
    read-only posture the reviewer records the number and compares it with the previous review's).
  - **D10.5:** the operator also attaches the API-keys list (names and dates, fragments redacted), states where
    the key is stored and that the laptop was searched for a copy, and captures the whole privacy page.
- [ ] **10. REVIEWER-BRIEF:** the reviewer also receives the previous PASS report's header block (everything
  above its "Verdicts" heading) for the baselines.
- [ ] **11. BRING-UP:** (a) a block "The listener check" (create the state directory, copy the two units,
  `daemon-reload`, `enable --now` the timer, link `show-listener-check`, run it once, expect `status=ok`);
  (b) Phase 7 gains "Switch the dashboard to a hashed password and a signing secret": generate the hash inside
  the gateway container with the password read at a hidden prompt, install it with `--quote single`, install
  the secret, `strip` the plaintext line, recreate the gateway, compare the hash in the container with the file
  by `secret_env` (never by printing), control sign-in (wrong password refused, right one accepted), restart
  once and confirm the session survives; (c) "Replace the OpenRouter key", moved from the README, which keeps
  one paragraph and a pointer; (d) Phase 7 points to the README's Desktop app section; (e) "A security review"
  names D4.5 and the D4.2 note that this rollout runs a `daemon-reload`.
- [ ] **12. Findings document:** F47 and F50 marked fixed by this change, pending review #8; a new F52 for the
  Compose trap (a hash written raw into an `env_file` is silently truncated), fixed by step 6.

### Task 4: Verify and commit

- [ ] **13.** Every suite in the constraints passes; `check-checklist-version.py --base main` exits 0; the diff
  holds no 64-hex string other than ones already in the repo. Commits per task.

---

## Rollout on the box (the operator's, after the merge; not part of the build)

1. Pull `main`. This changes the fingerprint: review #7's PASS no longer covers the box.
2. BRING-UP "The listener check". It runs a `daemon-reload`, so D4.2's `matches_last_pass` will be `false`
   and the evidence carries the reconstruction of "A security review" step 3.
3. BRING-UP "Switch the dashboard to a hashed password and a signing secret". The Desktop app must sign in
   again once.
4. Review #8: both probes, a chat audit if the last `ok` is older than 7 days (the last was 2026-10-05), the
   live refusal checks only if older than 30 days (last 2026-10-02), a trial collection, the real collection,
   a same-day laptop bundle, the evidence file, a fresh reviewer against v1.17.

## What the build changed from this plan (2026-10-07)

- **The check reads the host's `/proc`, not the container's `cat`** (F53). Step 2 planned
  `docker exec <id> cat /proc/net/tcp`. The check now takes the container's init pid from
  `docker inspect` and reads `/proc/<pid>/net/tcp` and `tcp6` on the host; a pid that changed
  during the read is `could-not-check` (`gateway-changed`). D4.5 expects the check's result to
  equal D4.1's.
- **An alert log that is never trimmed** (`alerts.jsonl`, F54): the capped history alone would
  have lost a cleared alert after a month. D4.5 reports `alert_log`.
- **The installer gained two things beyond `--quote single`:** `--stdin` (the value from a pipe,
  never a terminal), so the hash goes from the container to the file without being seen or
  pasted, and `generate` (32 random bytes, base64), so the signing secret is made on the box and
  never shown.
- **Single quotes are the one form for the hash.** The env reader returns a single-quoted value
  exactly and a `$$`-escaped one as written, so `$$` would read as `differs-from-file`.
- **`REPORT-TEMPLATE.md` lists no items**, so it is unchanged; the checklist test compares the box
  items with the collector's `PROBES`, which now has `D4.5`.
- The BRING-UP block for the dashboard is "Step 7d".
- **From the independent review of the build:** checklist D2.1's `credentials` sentence named four
  labels while the collector emits six (a healthy box would have failed review #8), now fixed and
  tied to the collector by a test; on an alert the marker and the alert log are written first, under
  a lock, and a damaged history no longer blocks them; `--clear-alert` logs before it removes the
  marker; any unexpected error exits 2, never the alert code; D4.5 reports the state directory and
  states its rules in order; step 7d removes the plaintext only after the gateway is shown to hold
  the hash, and its prompting blocks are one function each; the test fixtures use a synthetic hash.
- Also different from the task list above: the unit uses `ProtectHome=tmpfs` (F22: the Docker
  client needs it), each result carries a fixed `reason` word, `max_age_seconds` is reported, and
  the Docker calls time out after 15 seconds each.

