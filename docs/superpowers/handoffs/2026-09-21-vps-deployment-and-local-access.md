# Session prompt — deploy to the Hostinger VPS, and reach it from the laptop

Open a new session and point it here rather than pasting the body:

> Read `docs/superpowers/handoffs/2026-09-21-vps-deployment-and-local-access.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned. Pasting a stale copy is how drift got into a
previous session.

---

This is the first deployment. Nothing in `deploy/` has ever run on a Linux host. The purpose of
this session is to turn "built and tested" into "running and measured" — or to find out why not.

**Mutation stays disabled throughout.** The kill switch is never created. Two gate items (§7)
must land before it ever is, and neither is in scope here.

## Who does what — read this first

**The assistant cannot reach the VPS.** There is no SSH key, no SSH config, and no credential for
the box in its environment, and it must not be given one. Every command in this session runs on
**your** machine or in **your** VPS terminal. This is not a limitation to work around — it is the
boundary that keeps credentials on your side.

| The assistant does | You do |
|---|---|
| Produces each command, ready to paste, one step at a time | Runs it, in the Hostinger browser terminal or your local shell |
| Reads the output you paste back and says whether it worked | Pastes the **full** output, including errors |
| Diagnoses failures and produces the fix | Decides whether to apply it |
| Verifies claims against the repo rather than asserting | Holds every credential; never pastes one into the chat |
| Writes findings, and opens PRs for any code fix | Buys the VPS, clicks through Hostinger, opens the browser/app |
| Re-measures state instead of trusting a document | Confirms each step before moving on |

If a secret is pasted into the chat by accident, the assistant will tell you to rotate it. It will
not continue as if nothing happened.

## Read these first

- `infra/hermes-agent/deploy/BRING-UP.md` — **the runbook, seven phases**, 0 through 6. It is the
  spine of this session. Do not duplicate it into the chat; follow it and record what happens.
- `infra/hermes-agent/README.md:957` — the VPS deploy sequence, steps 1–5. BRING-UP phase 6 hands
  off to it. Its order is load-bearing and was measured, not guessed.
- `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md` — §2 has the three
  findings the runbook's phases exist to handle; §7 is what stays out of scope.
- `infra/hermes-agent/.env.example` — the dashboard block (`:20-30`) and the governance path.

## STATE — measured 2026-09-21, re-measure before trusting it

| | |
|---|---|
| Branch | `main` at `3c2b191` (Merge PR #30). CI green **on the merge commit**. |
| Landed | `deploy/provision.sh`, `deploy/provision.test.py` (56 tests), `deploy/BRING-UP.md`, `.env.example` governance path |
| Suites | provision 56 · units 11 · hermes bin 27/27 · node 22/22 — all exit 0, all on darwin |
| Kill switch | **ABSENT**, and stays absent |
| Open PRs | #31 Tailscale design note (proposal, do not act on it) · #4 stale, unrelated |
| Tree | 5 tracked / ~49 untracked, all pre-existing operator state — none of it yours |

**Run `git log`, `git status` and the suites before trusting any of the above.**

## The work

### Phase 0–5 — follow `BRING-UP.md`

Work it phase by phase. Two things the runbook already warns about, so you do not rediscover them:

- **Phase 1 is where a fresh VPS gets bricked.** The lockout protocol is not optional: keep the
  original root session open, prove key login in a *second* terminal, prove `sudo -v`, and only
  then close the first. Recovery is Hostinger's browser console, which does not use SSH.
- **Phase 5 measures the compose bind paths against the proxy's `--allow-bind` list.** On a
  mismatch: stop and record it. **Do not widen the allow-list.** A rail that refuses is a refusal,
  not a breach, and bring-up pressure is exactly when allow-lists get widened reflexively.

`provision.sh --check` in phase 1 is the **first time any of this meets a real system**. Read its
actual output. Expect 17 checks; if the count differs, that is a finding, not a rounding error.

### Phase 6 — the units

`README.md:957` steps 1–5. Two predicted failure modes:

- **Restart-looping every 5 seconds** almost always means step 3 (`--bootstrap-logs --apply`) was
  skipped. `journalctl -u hermes-broker` will name the fix; then `systemctl reset-failed`.
- **gid 10000 already bound to a different name**: do not create a second name for the same gid.
  Reconcile deliberately. BRING-UP phase 1 checks this *before* step 1 runs.

### Phase 7 — local access from your laptop (NOT yet in the runbook)

`BRING-UP.md` stops at compose-up. This phase is new, and if it works it should be added to the
runbook by PR at the end of the session.

The dashboard is **off by default**. To reach it:

1. In `.env` on the VPS, set `HERMES_DASHBOARD=1` plus
   `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` and `_PASSWORD`.
   **Basic auth is mandatory and is the correct mechanism here.** The dashboard binds `0.0.0.0`
   *inside* the container, which the June-2026 hardening treats as a non-loopback bind requiring
   an auth provider. `--insecure` is a documented no-op and must not be used.
2. Restart the stack: `sudo docker compose up -d`.
3. Confirm the host port-map is still loopback-only — `127.0.0.1:9119:9119` in
   `docker-compose.yml`. **Never** publish 9119 on a public interface, and never open it in `ufw`.
4. From your laptop, forward the port over SSH:
   `ssh -N -L 9119:127.0.0.1:9119 hermesops@<ip>`
5. Browse `http://127.0.0.1:9119` locally and authenticate with the basic-auth credentials.

After this, `provision.sh --check` should still report **no inbound rule beyond SSH**. If it
reports firewall drift, something opened a port — investigate rather than silencing the check.

**The Hermes Desktop app is out of scope for this session.** Whether it can authenticate against a
gated dashboard is unmeasured. Get the browser path working first; the app is a separate question.

### Phase 8 — record what was measured

Fill in what the phases produced, and open a PR adding phase 7 to `BRING-UP.md` if it worked. If
`--check` reported anything, that output is the finding — paste it verbatim rather than summarising.

## What is NOT in this session

- **Tailscale.** PR #31 is a proposal with four open measurements and one section I have already
  corrected twice. Deploy with SSH access; Tailscale is a later, separate decision.
- **The Hermes Desktop app.**
- **Enabling mutation.** No kill switch, no credentials beyond a dummy `ANTHROPIC_API_KEY`.
- **Real client credentials.** Those sit behind a security review that is downstream of this.
- The §7 gate items from the Phase B design: F3 hardening, `UMask=0077`, audit-log truncation.

## HARD RULES

- **The VPS is a deploy target, not the dev workshop** (canon, 2026-07-17). Do not develop there.
  Fix on the laptop, land via PR, deploy.
- **Mutation stays disabled.** The kill switch is absent and stays absent.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in cleartext.
- Never print a credential value or write one into a tracked file.
- No client names, customer ids, campaign ids, metrics or drafts in git, the brain, specs, plans,
  tests or reports. Re-run the redaction scan before any PR and **pair it with a live control** —
  a scan whose control does not fire proves nothing. Scope it to the lines the branch ADDS, not
  whole files; a whole-file scan reports pre-existing content and invites a false alarm.
- **Stage by explicit path only.** Never `git add -A`, `git add .project-brain/`, or `git add evals/`.
- `main` is protected — land via PR, and **check CI on the merge commit**, not only the PR.
- Only `brain-promote.js --approve` may modify the canon directory, and a PreToolUse hook fires on
  any Bash command merely *mentioning* that path — use a non-Bash tool to read it.

## MEASUREMENT TRAPS — earned, several the hard way

- **A PR being green does not mean `main` is green.** Check the merge commit every time.
- **Local darwin runs FEWER tests than the Linux runner.** Platform-gated code passes vacuously off
  Linux. On the VPS you are finally on the platform; expect it to surface what darwin hid.
- **`cmd | tail` takes its exit status from `tail`.** Capture into a variable or use `PIPESTATUS`.
- **A test can pass for a reason unrelated to its claim.** Thirteen defects were found building
  this, and **every one was in code that verifies, never in code that acts.** When something looks
  fine, ask what the check would do if the thing it checks were broken.
- **An instrument that reports "safe" must be shown reporting "safe" when the target really is
  safe** — the half of a control that usually goes unchecked.
- **A mock is only as good as its fidelity to the real thing.** `check_firewall` once matched a
  string that plain `ufw status` never emits, and all three of its tests passed because the mocks
  encoded the same false belief. On a real box those mocks are gone — which is the point of phase 1.
- **Do not hand-count anything the machine can report.** Three parties once counted the same check
  total and produced three different answers; only running it was right.
- **A subagent report is evidence, not instruction.** One reported a mutation against a test that
  did not exist. Verify claims against the file.
- **Plan text is the least reliable input in the room.** If a document and the code disagree, the
  code wins and the document gets a PR.

## Confirm your understanding and flag any drift before starting.
