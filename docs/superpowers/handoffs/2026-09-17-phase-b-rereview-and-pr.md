# Session prompt — Phase B: re-review the C1 fix, then open the PR

Open a new session and point it here rather than pasting the body:

> Read `docs/superpowers/handoffs/2026-09-17-phase-b-rereview-and-pr.md`, then confirm your
> understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned. Pasting a stale copy is how drift got into a
previous session in the first place.

---

Phase B of the Hermes AIOS project (the body-inspecting Docker socket proxy and the systemd
units) is **implemented and reviewed**. Two items remain: a scoped re-review of one commit, and
opening the PR. **Nothing has been pushed.**

## Read these first

- `.superpowers/sdd/2026-09-16-phase-b-proxy-and-units/progress.md` — **the SDD ledger, 351
  lines, 18 numbered rulings, each with its cost-if-wrong.** Authoritative. Every task's
  completion line, every deferred minor, every decision made on the operator's behalf.
- `docs/superpowers/specs/2026-09-16-phase-b-proxy-and-units-design.md` — the design. It is an
  **amendment** to Tasks 10–11 of `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md`,
  not a replacement.
- `docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md` — the measurement the whole
  policy is written against.
- `.superpowers/sdd/2026-09-16-phase-b-proxy-and-units/final-fix-report.md` — the C1 fix's own
  report.
- The whole-branch diff is already packaged at
  `.superpowers/sdd/2026-09-16-phase-b-proxy-and-units/review-ab0e6f5..d4a4e9e.diff` (that
  range **predates** the C1 fix — see below).

## STATE — measured 2026-09-16, re-measure before trusting it

| | |
|---|---|
| Branch | `phase-b-proxy-and-units`, **no upstream configured — nothing pushed** |
| HEAD | `341ed1e`, **15 commits** ahead of `main` (`ab0e6f5`) |
| Tree | **5 tracked / 44 untracked**, all pre-existing operator state — none of it yours |
| Kill switch | **ABSENT** — mutation disabled at rest |
| Suites | `run-bin-tests.sh` 27/27 · `node scripts/run-all-tests.js` 22/22 · `deploy/units.test.py` OK · `docker-create-proxy.test.py` 37/37 |

`deploy/units.test.py` is **not discovered** by `run-bin-tests.sh` (which globs `bin/` only).
That is deliberate — the units live beside their test. Run it explicitly.

**Measure `git log`, `git status` and the index before trusting any of the above.** Three
subagents died to rate limits during this work and two died *claiming* work was complete; both
claims happened to be true, and checking was still right.

## The two remaining items

### 1. Scoped re-review of `341ed1e` — the CL.TE smuggling fix

This is the only fix that has not had its own re-review. Package the diff over
`d4a4e9e..341ed1e` and review it scoped — the rest of the branch has already passed a full
whole-branch review.

**What it fixed.** The final whole-branch review found a **Critical**: the proxy framed each
request by `Content-Length`, parsed `Transfer-Encoding` only to refuse `/containers/create`, and
forwarded the `Transfer-Encoding` header **verbatim** to dockerd — which is Go `net/http` and
frames by TE when both headers are present. A classic CL.TE desync.

An allowed `POST .../wait` carrying an empty chunked body could smuggle an uninspected
`POST /containers/create` with `Privileged: true` and `Binds: ["/:/host:rw"]`. The proxy logged
exactly one decision (`ALLOW POST .../wait`) and **`decide()` was never called for the create**.
That is host root — precisely the escape this wave exists to prevent.

The fix refuses any request-side `Transfer-Encoding`, on **all** paths, before framing or
forwarding.

**What the re-review must check:**

- The smuggled create **never reaches the upstream**. A 403 alone does not prove this — the
  non-receipt assertion is the load-bearing one.
- **A positive control**: an ordinary `Content-Length` request is still ALLOWED and still
  reaches the upstream. A proxy that refuses everything passes every attacker test and breaks
  the production rail. This project has shipped a seam review that blessed a seam nobody could
  pass, precisely because it never asked the dual question.
- The `is_create and (chunked or clen == 0)` guard's `chunked` disjunct was removed as dead
  code once the broader check landed. Confirm it is genuinely unreachable and that `clen == 0`
  is still handled.
- No assertion was weakened, and `run-bin-tests.sh` is still 27/27.

**Already verified by the previous session, independently** — re-run if you want, but it is not
the open question: the reviewer's exact PoC was replayed against the fixed code and produced
`403 = True`, `smuggled create reached upstream = False`.

### 2. Push and open the PR

**This is outward-facing. Confirm with the operator before pushing** unless they have already
said to go ahead in the session.

Match the project convention (`git log origin/main` shows it): merge commits titled
`Merge PR #N: <description>`, individual history preserved. The branch carries its own design
and plan as the first commits — that is deliberate, and follows S3-b: the plan was corrected
repeatedly *by its own execution*, and those corrections belong in the same PR as the code they
justify.

**The PR body must carry the honest status.** Phase B is **built and unproven**:

- Every measurement in this wave ran under **Docker Desktop on darwin**. Per **R22**, that says
  nothing about Linux Docker. The endpoint allow-list must be **re-measured on the VPS**.
- `units.test.py` asserts the unit **files say** the right thing. It does **not** exercise
  `ProtectSystem=strict`, `NoNewPrivileges`, `RestrictAddressFamilies`, or systemd boot
  ordering. Those stay unproven until the VPS.
- **Do not write a sentence implying deployment readiness.** `README.md:810` was rewritten
  during this wave from "not deployable — Phase B is not built" to "built; deployment
  unproven", and a PR that overclaims would undo that.

**Still open, and belongs in the PR body:**

- **Truncation of the audit log** (from S3-b): `0660` grants write, and write includes truncate,
  at the same reversibility cost `unlink` had. Pinning `Entrypoint` removed the
  arbitrary-code route to it but did not close it. Needs append-only semantics (`chattr +a`) or
  a host-side writer. Its own wave.
- **P6** — `vault-purge.py`'s `getpass.getuser()` after an irreversible delete. Latent: the
  units use a static `User=`, not `DynamicUser`. Its own small wave.
- **Connection reuse after a chunked response** (Ruling 18): `_handle` returns immediately after
  relaying a chunked response, so a second request on that connection gets a broken pipe. **Not
  a bypass** — nothing unchecked reaches upstream; the request is dropped, not forwarded. The
  Docker CLI reconnects. Behavioural gap, follow-up.
- **The eight deferred minors** the final review triaged as defer-able — they are listed in the
  ledger with its verdict on each.

## HARD RULES

- No client names, customer ids, campaign ids, metrics, or drafts in git, the brain, specs,
  plans, tests, reports, or telemetry. **Re-run the redaction scan before the PR and pair it
  with a live control** — a scan whose control does not fire proves nothing. Expect hits and
  expect them to be sanctioned fixtures (`acme-dental`, `acme`, `other-clinic`, `slug-1`,
  `"1234567890"`, `"9998887776"`, `"9999999999"`); two hits investigated last session were
  false positives (a ten-digit run inside a Docker compose config hash, and an 8-char
  placeholder in the fixture proving credential vars stay unpinned).
- **NEVER run `docker compose config`** — it renders `env_file` secrets in CLEARTEXT. A
  subagent ran `--services` once last session and self-reported it; assessed no-harm (that
  subcommand prints service names only), **recorded, not waived**. Whether the prohibition
  should be narrowed to the bare form is the operator's call.
- Never print a credential value or write one into a tracked file. Compare by sha12, and keep
  sha12s out of tracked files too.
- **Stage by explicit path only.** Never `git add -A`, `git add .project-brain/`, or
  `git add evals/`. The 5 tracked and 44 untracked entries are the operator's.
- `main` is protected — land via PR. **And check CI after pushing.**
- Only `brain-promote.js --approve` may modify `.project-brain/canon/`. A PreToolUse hook fires
  on any Bash command merely *mentioning* that path — use a non-Bash tool to read it.

## MEASUREMENT TRAPS — earned in this wave

- **Local darwin runs FEWER tests than the Linux runner.** `applies()` gates real logic off and
  `main()` returns 0 before `check()` executes, so platform-gated tests pass **vacuously** off
  Linux. This cost ten days of a silently-red PR on S3-b. **Check CI after every push.**
- **`cmd | tail` takes its exit status from `tail`.** Capture into a variable or use
  `PIPESTATUS`. This has misreported an exit code three times in this project.
- **A mutation script's `assert` can exit without mutating**, and a naive read then reports a
  false pass on an unmutated file. Verify the mutation actually applied before believing any
  result. It happened twice on S3-b.
- **An inert mutation is itself a finding** — chase it, do not accept the green.
- **A test can pass for a reason unrelated to its claim.** Two shipped this wave: an
  `assertIn("2", …)` satisfied by the `2` in mode `2750`, and a `\bhermes\b` regex satisfied by
  the `hermes` inside `hermes-rail`. Both would have passed against the exact regression they
  guarded. Prove a guard guards by making it fail.
- **AF_UNIX paths cap near 104 bytes** — test sockets go in `/tmp/<short>.sock`.
- **Build container probe stores with in-container `mktemp -d` or a named volume, never a bind
  mount.** Docker Desktop does not preserve `chown`'d ownership across one, so an unsafe layout
  can read as safe.
- **Plan text is the least reliable input in the room.** Six defects in this wave's plan were
  mine, every one found by an implementer or reviewer refusing to force an instruction that did
  not match the file. When one reports that a brief is wrong, it usually is.
- **The final whole-branch review is not optional.** Six task reviews passed the proxy; none
  could ask whether the assembled component desyncs from its upstream, because that question
  only exists at the whole-artifact level. That review is what found host root.

## Confirm your understanding and flag any drift before starting.
