# Session prompt — post-F19: assess and close §6 part B, the last kill-switch gate

Open a new session and point it here instead of pasting the body:

> Read `docs/superpowers/handoffs/2026-09-24-post-f19-state-and-next-steps.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned. **If this document disagrees with the code, the
code wins and this document gets a PR.**

---

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing below creates it.**

## What happened since the post-F18 handoff (2026-09-24)

Every item below is merged, green on CI **on the merge commit**, and live on the box.

| Item | PRs | What it changed | Box proof |
|---|---|---|---|
| **F19** — container-scoped calls target only ads-mutator runs | #53 | `docker-create-proxy.py`: container ids must be a full 64-hex id (`_CID`); after `decide()` allows and before any byte goes upstream, `_handle` asks dockerd about the target on its own connection (`lookup_target`, stdlib `http.client`, unversioned, 5 s timeout, `MAX_BODY` cap, fail-closed on any exception) and forwards only if `is_mutator_shaped` finds the pinned image **and** the pinned entrypoint (and `Id == cid`). Per request. `ALLOW` is logged only after the check | Gateway inspect probe as `hermes-broker`: **`200` before, `403` after**; Phase 6: `rc=2`, `ALLOW` create, `UPGRADE … (101)`, **no DENY of any kind** |
| F19 records | #53, #54 | Findings record, BRING-UP "After pulling F19" (with a `RESULT` block), proxy header docstring | — |

Spec: `docs/superpowers/specs/2026-09-24-f19-container-scope-design.md`. Plan:
`docs/superpowers/plans/2026-09-24-f19-container-scope.md`.

## What is true now (re-verify before relying on it)

| | |
|---|---|
| `main` | `a26f2a3` (Merge PR #54). CI on the merge commit (run 36032491938): `bind-agreement: executed 7, skipped 0` · `layout-integration: executed 30, skipped 0` · node 22/22 · hermes bin 31/31 |
| Box (`hermesops@srv1997271`) | At **`d4fbb29`** (one docs-only merge behind `main` — no pull needed). Both units `active`, `NRestarts=0` |
| Kill switch | **ABSENT** (check it with `sudo test`, never `[ ! -e ]`) |
| Proxy tests | `docker-create-proxy.test.py`: 112 tests |
| Required CI checks | `Bind agreement (root, Linux, real proxy)` and `Test suites (node + hermes bin)` — they gate by job NAME; never rename them |
| Open PRs | Only #4 (a stale machine-generated proposal from 2026-07-24) |
| Remote branches | 31 merged-looking branches (`git branch -r --merged origin/main`) if a sweep is wanted |

Run `git log`, `git status` and the suites before trusting any of this.

## THE NEXT TASK — §6 part B: audit-log truncation

**Read first:**
- `docs/superpowers/specs/2026-09-04-s3b-audit-log-integrity-design.md` §2 "Truncation" (~:56-71) —
  the measurement and why S3-b left it open.
- `docs/superpowers/handoffs/2026-09-17-phase-b-rereview-and-pr.md` (~:112) — where it became a gate.
- `infra/hermes-agent/bin/changeset_lib.py`: `append_log` (~:732), `log_path` (~:410),
  `iter_log_records`, `day_counts` (~:1119); `apply-changeset.py` step 6 "daily caps" (~:155).
- `infra/hermes-agent/bin/governance_lib.py:31-32` (`LOG_DIR_MODE = 0o2750`, `LOG_FILE_MODE = 0o660`),
  `migrate_governance_shim.py:bootstrap_logs` (~:124), `host_layout.py` (the `log` row, ~:45).
- `infra/hermes-agent/deploy/hermes-broker.service` (`SupplementaryGroups`, `ReadWritePaths`).

**The gap, as measured by S3-b (2026-09-04, container uid 10000, log/ host-owned 2750, file host-owned
0660):** `rm -f log/acme.jsonl` → `Permission denied` (unlink closed), but `: > log/acme.jsonl` →
exit 0, record count 1 → 0. **Truncation is open.** The file still exists afterwards, so
`iter_log_records`, the pre-flight and `bootstrap_logs` all call the store healthy.

**Why it matters — two consequences, not one:**
1. **The record of what was done is erasable by the party it audits** (and `--undo` reads the log).
2. **The daily caps are computed from that same log** (`day_counts`, called in `apply-changeset.py`
   step 6). An emptied log reads as zero applies today, so truncation also **resets the caps**.

**Assess before designing. Open questions, in order — measure, do not infer:**
1. **Who can truncate today?** Not only the executor. `hermes-broker.service` has
   `SupplementaryGroups=hermes-rail hermes` and `ReadWritePaths=/var/lib/hermes/governance …`, and
   the log files are `0660` group `hermes` — so **the broker process on the host appears able to
   truncate the log too** (inferred from the unit and the modes; **not measured**). The broker is
   the adversary the proxy exists to contain, so this may be the larger half of the gap. List every
   principal with write on `log/<slug>.jsonl` on the box (as root: `stat`, `getfacl`, group
   membership, unit sandboxing) — never by reading the log's contents.
2. **Who legitimately writes the log?** `append_log` is the executor's only governance write (per the
   S3-a correction in `changeset_lib.py`); confirm nothing on the host appends, rotates, or rewrites
   it (grep every `log_path` / `open(... "a")` / `"w"` use).
3. **What reads it, and does anything need to modify it after the fact?** (`day_counts`,
   `iter_log_records`, `--undo`, audits, any rotation.)
4. **What does the box's filesystem support?** Which filesystem backs `/var/lib/hermes`; whether
   `chattr +a` works there; whether an append-only file survives the Docker bind mount with the
   semantics we need (append allowed, truncate/overwrite refused) **for the container's uid and
   for the broker's**. Measure on Linux (CI can do root + real Docker); Darwin proves nothing.

**Candidate approaches** (not decided — brainstorm them properly; present trade-offs):
1. **`chattr +a` on each `log/<slug>.jsonl`.** Kernel-enforced append-only for every user including
   root-less writers; small change. Costs: only root can set/clear it; `bootstrap_logs` /
   `init-host-layout.py` must set it on create and `--check` must verify it (with a firing control);
   any legitimate rewrite/rotation needs root to clear it; filesystem support must be measured;
   `O_APPEND` writes still work, `open("a")` must be the only mode used.
2. **A host-side writer.** The executor gets no writable log mount; it hands each record to
   something on the host that appends it (the broker? a new root-owned helper?). Costs: a new channel
   into or out of the container, new code on the security path — and if the broker is the writer,
   it does not help against a compromised broker (question 1).
3. **Both / other** — e.g. `chattr +a` now as the enforceable floor, and remove the broker's write
   access if question 1 confirms it has one it does not need.

Whatever is chosen: the caps must not be resettable by the executor or the broker; every new refusal
gets a firing control; Linux CI (`bind-agreement` / `layout-integration`, root, real Docker) must
prove it — `layout-integration` already creates the store as root, so it is the natural place for a
"truncate is refused, append works" test; the box needs a before/after measurement the same shape as
F19's (`: > file` succeeds before, fails after — **on a scratch file, never a real client log**).

**Process that worked (keep it):** brainstorming (architectural path, one question at a time,
sectioned design with approval per section) → written spec → spec self-review → writing-plans →
**subagent-driven** execution (fresh implementer per task, task reviewer after each, opus for
security-critical reviews, final whole-branch review on opus, ONE fix wave) → PR → CI counts on PR
and merge commit → box rollout with explicit expected output → a small docs PR recording the box
result. The operator runs every box command and pastes output back; give exact commands with the
expected result on each line and ask them to stop at the first mismatch. The operator sometimes asks
for a plain-language explanation of a design section and which part of deployment it relates to —
answer for a non-developer. **Put the new CI/integration test FIRST and show it RED on a draft PR**
(CI runs only on PRs to `main`) — F19 did this and it caught a real test defect.

## Other open items

**The rehearsal gate** (separate from the kill switch): needs `.env.gaw` carrying the WRITE Google
Ads credential on the box — a **security decision for the operator**, not a mechanical step.

**Findings record open items** (`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`,
"Open items, in order"): F6 (deploy-key clone of the ads repo — the box's is a placeholder), F3
(`--check` for usable sudo), F8 (`data/skills` ownership), F16 (host tools defaulting to container
paths), F17 (an unreadable path reported as `mismatch` — wording only).

**Deferred minors, recorded by the F19 reviews (none gate anything):**
- `lookup_target` bounds each socket operation, not the whole lookup — a trickling dockerd could
  hold a handler thread longer than 5 s (spec-accepted; dockerd is the peer).
- The keep-alive fake's `serve_conn` never closes its accepted socket (ResourceWarning noise in the
  proxy suite; pre-existing from F18, more frequent now). A `finally: c.close()` fixes it.
- `test_an_unforeseen_exception_is_refused` swaps `PX.json` module-wide for one test (restored via
  `addCleanup`); a leftover daemon thread calling `decide()` in that window would hit it —
  theoretical.
- `test_a_trailing_slash_after_the_id_is_refused` passes on pre-F19 code too (a regression guard,
  not RED evidence).
- Still open from post-F18: `_pump_both` never half-closes upstream on client EOF; response-side
  framing gaps (1xx, length-less bodies on keep-alive, HEAD with a Content-Length); duplicate `Host`
  accepted by `_parse_head`; no test pins a Content-Length above `MAX_BODY` reaching `_handle`'s cap
  or leading zeros; older CL.TE socket tests lack the race-free poll; `spool_lib.write_result`'s
  `os.makedirs(results/)` has no explicit mode.

**Brain housekeeping (operator):**
- `sessions/daily/2026-09-24.md` has two new entries: `[decision]` F19 fixed and applied, and
  `[lesson]` check why a RED is red. Run `node scripts/brain/brain-compile.js`, then
  `brain-promote --approve` what should become canon, then a small PR (the operator stages canon files).
- The F14 and §6-part-A decisions in `sessions/daily/2026-09-23.md` may still need compiling.
- Stale duplicate candidates `2026-09-22-f9-…` and `2026-09-22-f10-…` (canon holds both): `! rm` them.

## HARD RULES (unchanged, and earned)

- **NEVER run `docker compose config`.** It prints `env_file` secrets in cleartext. **Never read or
  print `.env`**, and never quote a credential value.
- **Never read, print, truncate or append to a real client audit log** to measure §6B. Use a scratch
  file in the same directory with the same owner/mode, or a CI fixture.
- **Do not widen the proxy allow-list to make anything pass.** A refusal is a refusal; find what the
  real client sent first.
- **Stage by explicit path only.** Never `git add -A`, `.`, `commit -a`; never stage `.project-brain/`,
  `evals/`, `CLAUDE.md`, `.obsidian/`, `infra/hermes-agent/CLAUDE.md`. The working tree carries ~68
  unrelated operator changes.
- `main` is protected: land via PR, and **read CI executed counts on the PR and on the merge commit.**
- Only `brain-promote.js --approve` may modify the canon directory; a PreToolUse hook fires on any Bash
  command that merely mentions that path. Ask the operator to stage canon files with `! git add …`.
- **Never edit a tracked file to run a mutation test.** Firing controls go in memory, on a test
  fixture's temp copy, or on scratch copies in a temp dir.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the
  Claude Code line. (The Co-Authored-By model name is the mandated attribution, not a defect.)
- Reviewers and implementers must not delete untracked files they did not create (an F19 reviewer
  removed the operator's `deploy/__pycache__/`; harmless, but not theirs to remove).

## MEASUREMENT TRAPS — earned, several this cycle

- **Check WHY a RED is red.** F19's first CI RED failed on `400 Bad Request` — the probe pinned
  `/v1.55` and CI's dockerd 28.0.4 caps at API 1.48 — so the security assertions passed
  **vacuously** while the test still went red on a later status check. Read the failing assertion;
  confirm it is the property the test names. Use **unversioned** Docker API paths in probes that run
  on more than one Engine.
- **An instrument that reports "safe" must be shown reporting "unsafe."** Every new refusal gets a
  test seen failing on the old code (RED), plus a firing control that re-introduces the bug. F19's box
  proof was the same probe returning `200` before and `403` after.
- **A broad assertion can measure pre-existing behaviour.** A "no `DENY` at all" CI check failed on
  two refusals that predate F19 (`GET /info`, `GET /networks/<name>` — sent by CI's Compose,
  tolerated; the box's Compose does not send them). Assert the property you changed.
- **Name collisions in a 700+-line module.** The plan's `_TARGET_RE` silently rebound an existing
  regex and broke `_parse_head`; only the FULL suite caught it. Grep for every new module-level
  name before adding it, and run the full file, not just the new class.
- **Interpreter-dependent tests.** Deep-nesting `RecursionError` depends on the Python version and
  stack size (3.14 parses 100k levels on the main thread). Make "unforeseen error" tests
  deterministic with a scoped, restored substitution.
- **Defence in depth can absorb a firing control.** `lookup_target` has a bounded read AND a length
  check; mutating one alone changes nothing observable. Mutate until the test goes red, and say which
  mutation proved it.
- **`journalctl --since` includes the whole second** — a check window started right after a probe can
  include that probe's own line. `sleep 1` before taking `T0`.
- **A green CI job can have executed nothing.** Read `executed N, skipped M`.
- **Assert the security property FIRST, and race-free** (poll for a settle window; judge the proxy's
  own lookup apart from client requests by its `User-Agent`).
- **Socket tests must be run in a loop** (10–30×).
- **Plan text is the least reliable input — including code the plan wrote verbatim.**
- **`hermesops` cannot see inside the governance store** (`root:hermes 2750`). **Use `sudo`** for
  `init-host-layout.py` and for the kill-switch check.
- **Unit files are copies** in `/etc/systemd/system/`: a pull does not apply a unit change — re-`cp`
  both and `daemon-reload`. Code changes to the proxy/broker scripts only need a restart. **§6B may
  change a unit** (e.g. the broker's `ReadWritePaths`/groups) — if so, the rollout needs the re-`cp`.
- **Restart the proxy only**; the broker `Requires=` it and restarts with it.
- **Darwin proves nothing about Linux ownership, `chattr`, systemd, or real Docker traffic.**
- **Never claim a proof you do not have.** Fill PR numbers and CI run ids only from real runs;
  mark inferences "inferred, not measured."

## Confirm your understanding and flag any drift before starting.
