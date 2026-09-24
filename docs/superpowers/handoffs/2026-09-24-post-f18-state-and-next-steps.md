# Session prompt — post-F18: design and fix F19, the last proxy-policy gate

Open a new session and point it here instead of pasting the body:

> Read `docs/superpowers/handoffs/2026-09-24-post-f18-state-and-next-steps.md`,
> then confirm your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned. **If this document disagrees with the code, the
code wins and this document gets a PR.**

---

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing below creates it.**

## What happened since the post-F12 handoff (2026-09-23 → 24)

Every item below is merged, green on CI **on the merge commit**, and live on the box.

| Item | PRs | What it changed | Box proof |
|---|---|---|---|
| Box caught up to F12 | #45 | `records/` created by `init-host-layout.py --apply`; runbook dry run needs `sudo` | `--check` rc=2 (firing control) → rc=0; `NRestarts=0` |
| **F14** — executor attests its exit | #46, #47 | `apply-changeset.py` prints `HERMES-EXIT <nonce> <rc>` for exits it *chose*; `run-ads-mutate.sh` trusts 0–3 only on exactly one exact match for its per-run nonce, else exits **4** (`failed_unverified_exit`, "possibly modified"); `hermes-syscall` maps 4 → `EXIT_FAILED_AFTER_MUTATION`; `set +eu` after Compose | Broker restarted; `set +eu  # F14` on disk |
| **§6 part A** — proxy framing hardening + `UMask=0077` | #48, #49 | `docker-create-proxy.py` parses every request head once via `_parse_head` (refuses obs-fold, space before colon, duplicate/non-digit/>19-digit Content-Length, bare CR/LF/NUL, anything but `HTTP/1.1`, non-printable header values, any Transfer-Encoding); `UMask=0077` on both units | `ALLOW POST …/containers/create` through the stricter parser; socket still `hermes-docker-proxy:hermes-rail 660` |
| **F18** — attach pass-through | #50, #51 | Pass-through only for a real `POST …/attach` that dockerd answered **exactly 101**; any other answer to an attach is relayed and the connection closed; `buf` forwarded only after a 101 | **`UPGRADE POST /v1.55/containers/<id>/attach?stderr=1&stdin=1&stdout=1&stream=1 (101)`** |
| F17, F18, F19 recorded; runbook fixes | (in the above) | `sudo test` for the kill-switch check; one restart, not two | — |

## What is true now (re-verify before relying on it)

| | |
|---|---|
| `main` | `1ebf377` (Merge PR #51). CI on the merge commit (run 36006359647): `bind-agreement: executed 6, skipped 0` · `layout-integration: executed 30, skipped 0` · node 22/22 · hermes bin 31/31 |
| Box (`hermesops@srv1997271`) | At **`5acee36`** (one docs-only merge behind `main` — no pull needed). Both units `active`, `UMask=0077`, `NRestarts=0`. Phase 6 passes with `ALLOW` on create and `UPGRADE … (101)` on attach |
| Kill switch | **ABSENT** (check it with `sudo test`, never `[ ! -e ]` — see traps) |
| Proxy tests | `docker-create-proxy.test.py`: 81 tests |
| Required CI checks | `Bind agreement (root, Linux, real proxy)` and `Test suites (node + hermes bin)` — they gate by job NAME; never rename them |
| Open PRs | Only #4 (a stale machine-generated proposal from 2026-07-24) |
| Remote branches | 29 merged-looking branches remain (`git branch -r --merged origin/main`) if a sweep is wanted |

Run `git log`, `git status` and the suites before trusting any of this.

## THE NEXT TASK — F19

**Read first:** the F19 section of `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`
and `ALLOWED` in `infra/hermes-agent/bin/docker-create-proxy.py` (~:95–108).

**The gap.** Every container-scoped allow-list entry accepts **any** container id
(`_ID = [A-Za-z0-9_.-]+`):

| Entry | What a compromised broker can do to ANY container |
|---|---|
| `GET /containers/<id>/json` (inspect) | Read its full config **including its environment**. The Hermes gateway is started with `env_file: .env` (`docker-compose.yml`, gateway service), which holds `ANTHROPIC_API_KEY` and the Hermes provider key; the one-shot `claude-auth-init` service also loads `env_file: .env` (inspectable for as long as its exited container exists). **This is the worst one.** |
| `POST /containers/<id>/attach` | Read its output (and log history with `logs=1`); write its stdin with `stdin=1` |
| `POST /containers/<id>/start`, `…/wait` | Start or wait on it |
| `DELETE /containers/<id>` | Delete it (e.g. the gateway, with `force` in the query — the query string is never inspected on these entries) |
| `GET /containers/json` (list) | Enumerate all containers (names, labels, images) — not id-scoped, but it is how ids are discovered; decide whether it needs filtering too |

The broker is the adversary the proxy exists to contain, so this is a real policy gap. It is listed
as a kill-switch gate "until assessed" — **the first job is the assessment, then the fix.**

**Measured facts the design must respect:**
- **The legitimate rail's own attach uses `stdin=1`** — Compose sends
  `attach?stderr=1&stdin=1&stdout=1&stream=1` even under `run -T` (box, 2026-09-24). An F19 fix
  **cannot** simply refuse `stdin=1`; it must restrict *which container* is targeted.
- **Compose uses three separate connections** for `attach`, `start` and `wait` (Task 1 measurement,
  `docker-create-proxy.py` header ~:66–72), and refers to the container by the **id** dockerd
  returns from create, not by name. The create itself carries `?name=hermes-agent-ads-mutator-run-<hex>`.
- The real call sequence observed in 2026-09-16's endpoint measurement is in the proxy's header
  docstring (~:28–40): `HEAD /_ping`, `GET /containers/json`, `GET /networks`, `GET /volumes`,
  `GET /images/{name}/json`, `POST /containers/create`, `GET /containers/{id}/json`,
  `POST …/attach`, `POST …/wait`, `POST …/start`. **Any F19 policy must still pass all of these for
  the ads-mutator container** — Linux CI's bind-agreement job and box Phase 6 are the proof.
- `DELETE /containers/{id}` is on the list as a manual-cleanup path, not observed in real traffic.

**Candidate approaches** (not decided — brainstorm them properly; present trade-offs):
1. **Remember created ids.** When the proxy ALLOWs a create and dockerd answers `201` with
   `{"Id": "…"}`, record that id; allow id-scoped calls only for recorded ids. Fails closed across a
   proxy restart (a leftover container can't be inspected/deleted through the proxy — `docker rm -f`
   as root is the manual path). Needs the proxy to parse the create *response* body (it currently
   relays it untouched), a size bound, and thread-safety (ThreadingUnixStreamServer).
2. **Check the target's labels.** Before forwarding an id-scoped call, the proxy itself asks dockerd
   `GET /containers/<id>/json` and allows only if it carries the ads-mutator labels
   (`com.docker.compose.service=ads-mutator`, project `hermes-agent`). Stateless, survives restarts;
   costs an extra upstream call per request and must not itself leak the inspect result.
3. **Name-based.** Allow only ids that dockerd resolves to names matching
   `hermes-agent-ads-mutator-run-*` — similar to (2) with a weaker signal.

Whatever is chosen: the grammar/`decide()` stays pure where possible; the new state or lookup is
its own unit with its own tests; the keep-alive fake upstream from F18 (`TestAttachPassThrough`) is
the pattern for socket tests; every new refusal has a firing control; Linux CI must show the real
Compose run still passes (`ALLOW` on create **and** `UPGRADE … (101)` on attach) and a new CI or
unit assertion must show an id-scoped call to a *non*-mutator container being refused.

**Process that worked (keep it):** brainstorming (architectural path, one question at a time,
sectioned design with approval per section) → written spec → spec self-review → writing-plans →
**subagent-driven** execution (fresh implementer per task, task reviewer after each, opus for
security-critical reviews, final whole-branch review on opus, ONE fix wave) → PR → CI counts on PR
and merge commit → box rollout with explicit expected output → a small docs PR recording the box
result. The operator runs every box command and pastes output back; give exact commands with the
expected result on each line and ask them to stop at the first mismatch. The operator sometimes asks
for a plain-language explanation of a design section and which part of deployment it relates to —
answer for a non-developer.

## Other kill-switch gates and open items

**Kill-switch gates (both must close before the kill switch may be created):**
1. **F19** — above.
2. **§6 part B — audit-log truncation.** The governance audit log is `0660`; write includes truncate,
   so the executor could erase the record of what it did. Needs append-only semantics (`chattr +a`
   on the host) or a host-side writer. Source: the 2026-09-17 handoff §6, second bullet.

**The rehearsal gate** (separate from the kill switch): needs `.env.gaw` carrying the WRITE Google
Ads credential on the box — a **security decision for the operator**, not a mechanical step.

**Findings record open items** (`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`,
"Open items, in order"): F6 (deploy-key clone of the ads repo — the box's is a placeholder), F3
(`--check` for usable sudo), F8 (`data/skills` ownership), F16 (host tools defaulting to container
paths), F17 (an unreadable path reported as `mismatch` — wording only).

**Deferred minors, recorded by this session's reviews (none gate anything):**
- `_pump_both` never half-closes the upstream (`SHUT_WR`) on client EOF — stdin EOF may not reach
  dockerd. Pre-existing; the rail passes.
- Response-side framing in the proxy: no handling of 1xx interim responses or length-less bodies on
  kept-alive connections; HEAD with a non-zero Content-Length could hang the relay. Pre-existing,
  fail-closed for attach; belongs with the Ruling 18 notes.
- Duplicate `Host` header accepted by `_parse_head` (dockerd 400s it).
- No test pins a Content-Length above `MAX_BODY` reaching `_handle`'s cap, nor leading zeros.
- The older CL.TE socket tests (~`TestPlumbing`) still assert non-receipt without the race-free poll
  (the same refusal is pinned race-free by `TestParseHead`).
- `spool_lib.write_result`'s `os.makedirs(results/)` has no explicit mode (unreachable in normal
  operation: the broker's `ExecStartPre` refuses to start unless `results/` exists `2750`).
- The F18 design spec's header still calls F19 "attach may target any container" (historical text).

**Brain housekeeping (operator):**
- `decisions/candidates/2026-09-24-f18-fixed-on-pr-50-…` exists (compiled). The F14 and §6-part-A
  decision entries are in `sessions/daily/2026-09-23.md`; run `node scripts/brain/brain-compile.js`
  if they are not yet candidates, then `brain-promote --approve` what should become canon, then a
  small PR to commit it (the operator stages canon files — see hard rules).
- Stale duplicate candidates: `2026-09-22-f9-…` and `2026-09-22-f10-…` (canon already holds both).
  `! rm` them.

## HARD RULES (unchanged, and earned)

- **NEVER run `docker compose config`.** It prints `env_file` secrets in cleartext. **Never read or
  print `.env`**, and never quote a credential value — F19's writeup names the exposure without
  printing anything.
- **Do not widen the proxy allow-list to make anything pass.** A refusal is a refusal; find what the
  real client sent first.
- **Stage by explicit path only.** Never `git add -A`, `.`, `commit -a`; never stage `.project-brain/`,
  `evals/`, `CLAUDE.md`, `.obsidian/`. The working tree carries ~66 unrelated operator changes.
- `main` is protected: land via PR, and **read CI executed counts on the PR and on the merge commit.**
- Only `brain-promote.js --approve` may modify the canon directory; a PreToolUse hook fires on any Bash
  command that merely mentions that path. Ask the operator to stage canon files with `! git add …`.
- **Never edit a tracked file to run a mutation test.** Firing controls go in memory, on a test
  fixture's temp copy, or on scratch copies in a temp dir.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the
  Claude Code line. (A reviewer once flagged the Co-Authored-By model name as "wrong" — it is the
  mandated attribution, not a defect.)

## MEASUREMENT TRAPS — earned, several this session

- **An instrument that reports "safe" must be shown reporting "unsafe."** Every new refusal gets a
  test seen failing on the old code (RED), plus a firing control that re-introduces the bug.
- **A green CI job can have executed nothing.** Read `executed N, skipped M`.
- **Assert the security property FIRST, and race-free.** F18/§6A socket tests originally asserted
  the 403 first, so the RED run never exercised non-receipt; and non-receipt raced the fake
  upstream's thread (a "forward-then-refuse" mutant was caught only 71/80). Fix: poll `upstream_raw`
  for a settle window (`_poll_never_received`) and assert it before anything else.
- **Fake upstreams that close after every reply hide keep-alive bugs.** F18 was invisible to
  `TestPlumbing`'s fake. Use a keep-alive fake (`TestAttachPassThrough`) for anything involving a
  second request on one connection.
- **Socket tests must be run in a loop** (10–30×). A chunked-reply test read its first response
  only up to `{}` and flaked ~2/28 when the `0\r\n\r\n` terminator arrived separately.
- **Plan text is the least reliable input — including code the plan wrote verbatim.** Reviews found:
  `int()` on a >4300-digit Content-Length raising a bare `ValueError` (fixed with a 19-digit bound);
  a positive-control test that failed because its fake closed the connection; an `==` comparison of
  compiled regexes that could never fail (use `is`); a 4-cell row in a 3-column table.
- **`hermesops` cannot see inside the governance store** (`root:hermes 2750`, and `hermesops` is by
  design only in `sudo`/`users`). Unprivileged `init-host-layout.py` reports every child as
  `mismatch … Permission denied` (F17), and an unprivileged `[ ! -e …/mutation-enabled ]` says
  "absent" whatever is there. **Use `sudo` for both.**
- **Unit files are copies** in `/etc/systemd/system/` (`README.md:1201-1203`): a pull does not apply
  a unit change — re-`cp` both and `daemon-reload`. Code changes to the proxy/broker scripts only
  need a restart (they run from the repo).
- **Restart the proxy only**; the broker `Requires=` it and restarts with it. A second, explicit
  broker restart interrupts that one mid-`ExecStartPre` and logs a harmless-but-alarming
  "Failed with result 'signal'".
- **Darwin proves nothing about Linux ownership, systemd, or real Docker traffic.** Wrapper tests
  (`run-ads-mutate.test.py`) skip on Linux CI (`_UID_OK` needs uid 10000) — the Linux proof of the
  wrapper and proxy is `bind-agreement-integration.test.py` and box Phase 6.
- **Never claim a proof you do not have.** Fill PR numbers and CI run ids only from real runs;
  mark inferences "inferred, not measured."

## Confirm your understanding and flag any drift before starting.
