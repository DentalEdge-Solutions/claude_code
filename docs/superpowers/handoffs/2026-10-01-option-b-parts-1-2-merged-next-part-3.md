# Handoff 2026-10-01: Option B parts 1–2 merged; next is part 3 (review tooling)

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. The spec and the part-3
plan carry the detail. Client names are written as `<client>`; no customer ids or fingerprints appear here.

## Where things stand

- **Merged to `main`:**
  - **#85, part 1:** isolation and egress.
  - **#86, part 2:** the chat trigger.
- **Not on the box:** nothing from Option B has been applied. The box still runs review #5's code: `sudo run-client-audit <client>` over SSH, draft run in the gateway.
- **Ordering.** The BRING-UP gate says to apply parts 1 and 2 only after part 3 merges and security review #6 is scheduled.
- **Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md`. §13 records the measurements of the pinned Hermes image.
- **Plans:** `docs/superpowers/plans/2026-09-30-option-b-{1,2,3}-*.md`. Part 3 is
  `2026-09-30-option-b-3-review-tooling.md`, not started.
- **Brain:**
  - **Active decision:** `decisions/active/2026-10-01-option-b-parts-1-2-merged-…` records what's merged and the key rulings.
  - **Today's session note:** `sessions/daily/2026-10-01.md` lists the parked follow-ups. It's gitignored and local only; the same list is below.

## What parts 1–2 built (for orientation)

**Part 1:**
- Client vaults, reports and the transient draft live under `/var/lib/hermes/{vaults,reports,draft-out}/<client>`, never mounted into the gateway.
- The Opus draft runs in a per-client one-shot `ads-drafter` on an internal network. Its only exit is `egress-proxy` (`api.anthropic.com:443` only, log kept in `audit-logs/<client>/proxy.log`).
- The Anthropic key lives in `/etc/hermes/.env.anthropic`.
- `run-client-audit` gained `--json`, `--list`, SIGTERM-safe cleanup and `--probe-*` hooks (the probes come in part 3).
- New tools: `install-env-secret`, `migrate-client-data` (rc 3 = copies good, finish removal by hand) and `show-audit`.

**Part 2:**
- **The chain:** `hermes-app-mcp` (gateway, three tools, no policy) → `hermes-app-broker@ads-audit` → `hermes-app-runner@ads-audit` → back to the broker, which writes the whitelisted result.
  - **Broker:** user `hermes-app-ads-audit`, no capabilities, no network. It enforces the schema, replay protection, the kill switch, client status and quota (reserved before the job).
  - **Runner:** a root oneshot started by a `.path` unit. It runs only `run-client-audit <slug> --json|--list --json` and never re-runs a job cut off by a crash.
  - **Result:** built by the `app_lib.map_done` whitelist.
- **Manifest:** `registry/apps/ads-audit.json`. Run timeout 7200 s; quota 1 per client and 5 per box per day.
- **Gateway:** holds only the OpenRouter key. `claude-auth-init` is retired. Config sets `provider_routing.data_collection: "deny"`.

## Next: part 3

Execute `docs/superpowers/plans/2026-09-30-option-b-3-review-tooling.md` with subagent-driven development, from up-to-date
`main`. It adds:
- keyed (HMAC) customer-id fingerprints, with the key on the laptop only;
- `run-client-audit --probe-env` and `--probe-egress`;
- the review collector's D2.1, D4.1, D4.2 and D7.1 edits;
- D10.1–D10.8;
- the review-#5 follow-ups;
- checklist v1.11.

**Check these against the plan before starting, because parts 1–2 changed things the plan predates:**
- `stop_proxy` now takes `(root, logs, say)`. The plan's Task 3 was already updated.
- **Part-3 plan text that differs from what parts 1–2 shipped:**
  - **D2.1:** must also expect no gateway Anthropic key.
  - **D10.3:**
    - the runner unit now has `StartLimitIntervalSec=0`, `KillMode=control-group` and `TimeoutStartSec=12h`;
    - the broker unit's sandbox is as committed.
  - **D10.5:** records that ZDR is an OpenRouter **account** setting. Hermes has no `zdr` key (spec §13).
  - **D10.7:** journal lines now include `dropped`, `expired` and fixed-text lines.
  - **D10.8:** result files may include `reason: busy` and step classes including `proxy`. `app_lib` keeps `COMMAND_REASONS`, `BROKER_REASONS` and `STATUS_REASONS`.

## Parked follow-ups (decide in part 3 or a small follow-up)

1. **Runner restart spin:** a non-job entry left in `app-state/<app>/jobs/` makes the runner restart in a tight loop, because `StartLimitIntervalSec=0`. Only the broker or root can write there. Fix: a broker-side sweep of names that don't match.
2. **Rollback backups:**
   - BRING-UP part 2 creates `/opt/hermes-agent/.env.pre-optb2` and `/root/config.yaml.pre-optb2`, and says to shred both before review #6's evidence collection.
   - The review credential sweep matches `.env*`. The collector could flag either file if present.
3. **Refusal cap:** after 1000 refusals in a UTC day, further refusals get no result, so the caller sees `pending`. This is intended (it stops `results/` flooding); document it in D10.7/D10.8 expectations.
4. **`recover()`** runs at startup and every 30 broker passes. A reservation whose job and result writes both failed waits for that.
5. **Minor test hygiene across the new suites:** ResourceWarnings from `open(...).write` without `with`.

## How the build ran (worth repeating)

- **Setup:** one worktree per part (`git worktree add ../claude_code-optbN -b feat/... main`). The SDD ledger lives in the worktree's gitignored `.superpowers/sdd/<plan>/progress.md`. Briefs and reports are files there.
- **Model tiers:**
  - Implementers: Sonnet, or Opus for root and security-core code.
  - Reviewers: Sonnet, or Opus for broker, runner and final reviews.
  - **Haiku once shipped an assertion-free stub test and reported it done; don't use it for implementers.**
- **Reviews:** per-task reviews caught real defects every time. Recurring classes:
  - unhandled exceptions in hostile-input loops;
  - `.match` with `$` accepting a trailing newline (use `fullmatch`);
  - ledger/result write ordering;
  - temp files left behind.
- **No push** until the operator says. Then a PR against `main` and a CI watch. The Linux "Bind agreement" job runs the root/Docker integration suites.
- **Local Docker** may need starting (`open -a Docker`). It's needed only for compose rendering and image inspection.

## After part 3

1. Merge part 3 (CI green).
2. **Box rollout,** in order:
   - BRING-UP "Chat-triggered audits — part 1", then "part 2";
   - the manual audit;
   - the first chat audit;
   - the D10.7 live checks (kill switch, quota, malformed request);
   - shredding the rollback backups.
3. **Review #6 preparation:**
   - collect both bundles (box: `--fp-key-tty`, `--last-pass-execstart <review #5 value>`);
   - run a fresh reviewer against checklist v1.11.
4. **Sign-off:** operator sign-off, then a brain decision. Promote "live on the box, review #6 PASS" to canon.
