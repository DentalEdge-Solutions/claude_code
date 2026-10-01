# Handoff 2026-10-01: Option B part 3 merged; next is the box rollout, then review #6

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`; no customer ids or fingerprints appear here.

## Where things stand

- **Merged to `main`:** all three Option B parts.
  - **#85, part 1:** isolation and egress.
  - **#86, part 2:** the chat trigger.
  - **#88, part 3:** review tooling and checklist v1.11. CI was green on all five checks. The "Bind agreement"
    job ran both probes on real Docker for the first time, and both passed.
- **Not on the box:** nothing from Option B has been applied. The box still runs review #5's code:
  `sudo run-client-audit <client>` over SSH, draft run in the gateway.
- **Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md`.
- **Brain:**
  - **Active decision:** `decisions/active/2026-10-01-option-b-part-3-merged-pr-88-…` records what merged and
    the key rulings.
  - **Today's session note:** `sessions/daily/2026-10-01.md` holds the follow-up list. It's gitignored and
    local only; the same list is below.

## What part 3 built (for orientation)

- **Keyed fingerprints.** Customer-id fingerprints are HMAC-SHA256.
  - The key is created once on the laptop with `bin/review-fp-key.py init` (`~/.config/hermes-review/fp.key`,
    `0600`). The laptop collector refuses a key file with group or other access.
  - The box collector reads it from the tty (`--fp-key-tty`) and never from disk.
  - Both bundles record `cid_key_id`. If the two differ, cid comparisons are CANNOT-VERIFY.
- **Probes:** `run-client-audit --probe-env` and `--probe-egress`, root only.
  - They use sentinel values and throwaway directories, and never open a real secret file.
  - They take the audit lock. Exit 3 with no JSON means an audit was running: collect again.
  - `--probe-env` can take about 8 minutes in the worst case. The collector re-runs both and allows 600 s each.
- **Collector:** D2.1, D4.1, D4.2 and D7.1 follow the Option B layout. D10.1–D10.4 and D10.6–D10.8 are new box
  probes; D10.5 is manual. The review-#5 follow-ups are in: audit-log file modes, Docker nsfs handles, and the
  last-PASS proxy hash (`--last-pass-execstart`).
- **Checklist v1.11** with the D10 domain, the reviewer packet, and two BRING-UP additions:
  - "A security review": the procedure with the key;
  - "Chat-triggered audits — part 2", step 11: the three D10.7 live checks.

## Where part 3 departs from its plan

The plan predated parts 1–2. Each change below was ruled against the spec.

- **Env probe:** also reports env names whose value holds the sentinel (`sentinel_env_names`). The sentinel is
  assembled at run time, because `bin/` is mounted into the containers the probe searches.
- **D10.7:** counts credential text and customer ids in both the broker and runner journals, including the
  installed Google, Anthropic and OpenRouter values. `known_secrets_checked` must be above zero, or a zero count
  proves nothing.
- **D10.6:** never prints the gateway-writable `data/config.yaml`. It reports whether the `mcp_servers:` block
  equals the block committed in `infra/hermes-agent/config.yaml.example`, and the checklist pins that block's
  sha256 and line count.
  - The comparison is line-based, not a YAML parse. The checklist states that limit; the broker stays the
    boundary.
  - Changing the template's MCP block needs a checklist version bump.
- **D4.2:** the existing ExecStart hash is unchanged, so `matches_last_pass` reads `false` after any proxy
  restart or reboot.
  - That is a FAIL unless the operator states the restart, D4.3 shows the unit unchanged, and
    `drop_in_paths` is empty.
  - `execstart_argv_sha256` is new and restart-stable. Review #6 records it as the baseline for review #7.
- **D10.3:** also reports the broker's and runner's environment names and drop-ins, all expected empty.
- **D10.8:** `result_in_whitelist` re-checks each result through the broker's own builders and never raises.

## Next: the box rollout

In order. Every step is in BRING-UP.

1. **"Chat-triggered audits — part 1"**, then **"part 2"**.
2. **The manual audit**, then **the first chat audit** (part 2 step 10).
   - Step 10 ends by shredding the rollback backups (`.env.pre-optb2` and `/root/config.yaml.pre-optb2`) once
     the chat audit is `ok`. After that, step 12's rollback has nothing to restore from.
   - A leftover `.env.pre-optb2` is an `unlisted` D2.1 hit and a FAIL.
3. **Part 2 step 11, the live checks** (kill switch, quota, malformed request). Read these before starting:
   - The quota check works only on the same UTC day as the first chat audit. Run the guard first. Only
     `HELD_RUNS=1` means the next paste is safe; any other output means skip the quota check that day, because
     the request would start a real audit.
   - In the kill-switch check, remove `DISABLED` only after the `reason=disabled` line appears. If it doesn't
     appear, delete the request file first.

**Record on the first run, before collecting evidence.** These could not be tested off the box:
- whether the real Hermes image bakes in an `ANTHROPIC_*` or `OPENROUTER_*` env name. That would fail D10.1 and
  D4.1 on a healthy box.
- the exact `systemctl show` output: `NoNewPrivileges=yes`, an empty `CapabilityBoundingSet=`, `UMask=0077`,
  `Environment=` printed when unset, and whether the ExecStart line has an `argv[]=` segment.
- the `sudo -l -U hermes-app-ads-audit` wording, and `hermes mcp list` without a TTY.
- whether Hermes re-creates `data/reports` at start (that would fail D7.1's `old_data`), and whether it
  re-serialises `data/config.yaml` (that would fail D10.6 until the template's MCP block is re-installed).

## Then: review #6

1. **Timing:** collect within 7 days of the chat audit. The broker deletes results after 7 days, and D10.8
   needs a `run`/`ok` row.
2. **Collect both bundles** per BRING-UP "A security review". The box command takes `--fp-key-tty` and
   `--last-pass-execstart <review #5 value>`.
3. **Operator evidence file:** the manual items (D3.2, D8.1, D8.2, D9.1, D10.5) and the D4.2 statement if
   `matches_last_pass` is `false`. For D10.5, state the OpenRouter key limit ($10, monthly reset) and that ZDR is
   set on the account: Hermes has no `zdr` key.
4. **Run a fresh reviewer** against checklist v1.11. The packet now includes `config.yaml.example`.
5. **Sign-off:** operator sign-off, then a brain decision. Promote "live on the box, review #6 PASS" to canon.

## Open follow-ups

**Must land before review #6's evidence, or be listed under D9.1.** `bin/` and `deploy/` are in the box
fingerprint, so a later change re-binds the review.

1. **Runner restart spin** (parked since part 2, still not built): a non-job entry left in
   `app-state/<app>/jobs/` makes the runner restart in a tight loop. Fix: a broker-side sweep of names that
   don't match.

**Deferred code items.** Each fails closed today.

2. The env probe can't detect a mounted real credential file, because the real file holds no sentinel. A
   `test -e /etc/hermes` line would.
3. When the collector's 600 s timeout kills a probe, the probe's cleanup doesn't run. The next probe or audit
   cleans up.
4. `probe_egress` ignores both return codes; a failed `up -d` shows only as missing lines.
5. `_sudo_rules` reads clean when `sudo` did not run (the pass rule still requires `not_allowed: true`).
6. `d10_3` loses the whole item when the app user is missing.
7. `load_env_value` doesn't strip an inline `# comment`, so a value written that way never matches a leak.
8. `collect-review-evidence.py` is over 1,000 lines; the D10 block could move to its own module.

**Set aside as outside the part 3 plan.** Decide whether any becomes work.

9. The review's `--credentials-only` mode and "authorised credential set" cover Google values only. Rotating the
   Anthropic or OpenRouter key triggers nothing.
10. The audit lock file in `/run/lock` can be pre-created by a local user.
11. D10.4 inspects running containers only.
12. D4.1's evidence comes from `docker exec` inside the container the reviewed agent controls.
13. `~/bundle-box.json` is written with the shell's umask before it's deleted.
14. The README's "one non-Google secret file" paragraph is stale.

**Rules that now apply:**
- Any change to `CHECKLIST.md` needs a version bump above 1.11.
- Any change under `bin/` or `deploy/` changes the box fingerprint.

## How the build ran (worth repeating)

- **Setup:** one worktree (`../claude_code-optb3`, branch `feat/option-b-3-review-tooling`). The SDD ledger,
  briefs and reports live in its gitignored `.superpowers/sdd/` and go when the worktree is removed.
- **Model tiers:** Opus for root and security-core implementers and for their reviews; Sonnet elsewhere. Opus
  returned HTTP 529 several times; re-dispatching the same brief on Sonnet worked.
- **Reviews caught real defects in four of seven tasks, and again at the whole-branch review:**
  - plan code that didn't meet the spec (the env probe checked names and files, not values);
  - a crash on hostile input (deeply nested JSON in a result file took the whole collector down);
  - a feature its own unit test hid (the nsfs classification was unreachable through the real mount listing);
  - checklist rules that would fail a healthy box (D4.2 after a restart, D10.8 after 7 days);
  - a runbook step that could start a real, paid audit (the first quota guard counted the wrong ledger lines);
  - a collector reading a gateway-writable file as root with a plain `open()`.
- **Checklist text was checked against the code key by key.** Later fix rounds changed output keys after the
  text was written, so this had to be repeated at the end.
- **No push** until the operator said. Then the PR and a CI watch.
