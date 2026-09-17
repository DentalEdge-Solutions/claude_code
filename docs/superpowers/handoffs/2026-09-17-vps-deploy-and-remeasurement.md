# Session prompt — VPS: deploy Phase B, then re-measure what darwin could not tell you

Open a new session and point it here rather than pasting the body:

> Read `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md`, then confirm
> your understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned. Pasting a stale copy is how drift got into a
previous session in the first place.

---

Phase B is **merged and unproven**. The proxy and the units exist, are tested, and have never
run on Linux. This session is where "built" becomes "measured" — or does not.

**This session does not enable mutation.** The kill switch stays absent throughout. Two items
(§6) must land before it is ever turned on, and neither is in scope here.

## Read these first

- `infra/hermes-agent/README.md:957` — **the VPS deploy sequence.** Five steps, and the order
  is load-bearing: it was measured, not guessed. Skipping or reordering produces failures that
  look like a hang rather than a clean error. Reads together with "Ownership on a Linux host".
- `docs/evaluations/2026-09-17-f3-framing-disagreement-measurement-plan.md` — **the F3 plan,
  self-contained**, with the harness embedded and already self-tested. §2 is the safety rule,
  §5 is the table to fill in, §6 decides what each outcome means *before* the numbers exist,
  and §8 is the end-to-end check the Content-Length fix still owes.
- `docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md` — the darwin measurement being
  re-run. §Method (`:13`) describes the throwaway logging pass-through and how it was driven.
- `docs/superpowers/specs/2026-09-16-phase-b-proxy-and-units-design.md:16` — **§1, the threat
  model.** Read it before judging the severity of anything you find. The proxy protects **the
  host** against **a compromised broker**; it does not protect the client account, which is
  already lost at the moment of compromise.
- `.superpowers/sdd/2026-09-16-phase-b-proxy-and-units/progress.md` — the SDD ledger, 351 lines,
  18 numbered rulings, each with its cost-if-wrong.

## STATE — measured 2026-09-17, re-measure before trusting it

| | |
|---|---|
| Branch | `main` at `f8878e2`, `origin/main` identical (0/0) |
| Last merges | `#25` Phase B (`1ab18fc`) · `#26` strict Content-Length + F3 plan (`f8878e2`) |
| Tree | **5 tracked / 45 untracked**, all pre-existing operator state — none of it yours |
| Kill switch | **ABSENT** — mutation disabled at rest. It stays that way this session. |
| Suites | bin 27/27 · node 22/22 · `deploy/units.test.py` 11/11 · `docker-create-proxy.test.py` 40/40 |

`deploy/units.test.py` is **not** discovered by `run-bin-tests.sh` (which globs `bin/` only).
Since `f93d41f` CI invokes it as its own step, but locally you still run it explicitly.

**Measure `git log`, `git status` and the index before trusting any of the above.**

## The work

### 1. Deploy — `README.md:957`, steps 1–5

Follow it as written. Two failure modes it already predicts, so you do not rediscover them:

- **Restart-looping every 5 seconds** almost always means step 3 (`--bootstrap-logs --apply`)
  was skipped. Since S3-b the pre-flight refuses when a registered client has no pre-created
  log, and the broker runs it as `ExecStartPre` with `Restart=on-failure`/`RestartSec=5`.
  `journalctl -u hermes-broker` will name the fix. Then `systemctl reset-failed` before
  re-enabling.
- **gid 10000 already bound to a different name** on this host: do **not** create a second name
  for the same gid. Reconcile deliberately.

Step 5's verifications have never run on any real VPS. Read the actual output.

### 2. Prove the hardening directives actually apply — the thing units.test.py cannot

`units.test.py` asserts the unit **files say** the right thing. It does not exercise
`ProtectSystem=strict`, `NoNewPrivileges`, `RestrictAddressFamilies`, or boot ordering. Those
are unproven until you check them here, on the running units:

```bash
systemctl show hermes-docker-proxy hermes-broker \
  -p ProtectSystem -p NoNewPrivileges -p RestrictAddressFamilies -p After -p Requires
```

Then prove one of them **bites** rather than merely being reported — a directive systemd
accepts and ignores reads identically to one it enforces. Attempt a write outside the allowed
paths as the unit's user and confirm it is refused.

### 3. Re-measure the endpoint allow-list — R22

**The allow-list is re-measured on the VPS, not inherited.** Re-run the Task 1 measurement
(method at `2026-09-16-phase-b-endpoint-measurement.md:13`) against Linux Docker and diff the
resulting endpoint set against the darwin one.

- If Linux calls endpoints darwin never did, **the rail fails closed** — a refusal, not a
  breach. That is the safe direction.
- Each endpoint you add is a policy decision. Bring-up pressure is exactly when allow-lists get
  widened reflexively, and the obvious way to make a failing rail pass is to widen the policy —
  the same reflex that would have weakened the `Cmd` check when Task 3's positive control failed
  (`f80c939`). Write down why each addition is safe, not just that it was needed.

### 4. Run the F3 measurement — the plan is self-contained

`docs/evaluations/2026-09-17-f3-framing-disagreement-measurement-plan.md`. Run `--self-test`
**before** trusting any result from it, fill in §5, and apply §6's pre-decided interpretation
rather than inventing one on the day.

Three rows: obs-fold continuation line, `Transfer-Encoding : chunked`, duplicate
`Content-Length`. In all three the create's bytes reach the upstream on darwin; whether dockerd
frames them as a **second request** is the open question and the only thing that makes any of
them a bypass. **Read-only: the smuggled request is `GET /_ping`.** Two responses to one send is
the whole proof — never substitute a privileged create "to be sure."

If `CONTROL-POS` does not see two responses, record no verdict at all. A "1" everywhere might
only mean the instrument cannot count.

### 5. The end-to-end positive control the Content-Length fix owes — §8 of that plan

`65df9b1` made the proxy refuse **more**: a `Content-Length` that is not `1*DIGIT`, including an
empty value the old fallback coerced to `0`. Verified on darwin only at unit level, plus the
reasoning that Go's `http.Request.Write` cannot emit any refused form. No end-to-end run — the
dev machine had no running daemon, and the 2026-09-16 measurement records method, path,
connection and call counts, **not header blocks**, so it cannot settle it either.

Run the real rail end to end through the proxy and confirm an ordinary mutation path is still
**ALLOWED**, in the proxy's own log, end to end.

**If a real request is refused with `malformed Content-Length`, that is the finding.** Do not
widen the parse to make it pass. Identify which client emitted it and what it emitted.

### 6. NOT this session — but the gate before mutation is ever enabled

- **F3 hardening**, if §4 finds a desync — or at normal priority if it does not. Refuse what
  cannot be parsed unambiguously instead of depending on dockerd being stricter than Python.
  §7 of the plan has the three rules and the constraint: **re-run the positive control.**
- **Audit-log truncation.** `0660` grants write, and write includes truncate, at the same
  reversibility cost `unlink` had. Pinning `Entrypoint` removed the arbitrary-code route but did
  not close it. The design's §1 names the audit trail as the secondary property worth defending
  and says a log writable by attacker-chosen code "undoes that purchase one wave later." Needs
  append-only semantics (`chattr +a`) or a host-side writer. Its own wave.

Also open, neither a gate: **P6** (`vault-purge.py`'s `getpass.getuser()` after an irreversible
delete — latent while the units use a static `User=`; do not switch to `DynamicUser`), and
**Ruling 18** (`_handle` returns after relaying a chunked response, so a second request on that
connection gets a broken pipe — **not a bypass**, nothing unchecked reaches upstream, the Docker
CLI reconnects). Expect Ruling 18 to surface during bring-up as intermittent connection
weirdness; it is known, not new.

## HARD RULES

- **The VPS is a deploy target, not the dev workshop** (canon, 2026-07-17). Hermes is built
  local-first. Do not develop there; fix on the laptop, commit, deploy.
- **Mutation stays disabled.** The kill switch is absent and stays absent this session.
- No client names, customer ids, campaign ids, metrics, or drafts in git, the brain, specs,
  plans, tests, reports, or telemetry. **Re-run the redaction scan before any PR and pair it
  with a live control** — a scan whose control does not fire proves nothing. Sanctioned
  fixtures: `acme-dental`, `acme`, `other-clinic`, `slug-1`, `"1234567890"`, `"9998887776"`,
  `"9999999999"`.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in CLEARTEXT.
- Never print a credential value or write one into a tracked file. Compare by sha12, and keep
  sha12s out of tracked files too.
- **Stage by explicit path only.** Never `git add -A`, `git add .project-brain/`, or
  `git add evals/`. The 5 tracked and 45 untracked entries are the operator's.
- `main` is protected — land via PR. **And check CI after pushing**, on the merge commit, not
  only on the PR.
- Only `brain-promote.js --approve` may modify the canon directory. A PreToolUse hook fires on
  any Bash command merely *mentioning* that path — use a non-Bash tool to read it.

## MEASUREMENT TRAPS — earned, and several of them the hard way

- **Local darwin runs FEWER tests than the Linux runner.** `applies()` gates real logic off and
  `main()` returns 0 before `check()` executes, so platform-gated tests pass **vacuously** off
  Linux. This cost ten days of a silently-red PR on S3-b. On the VPS you are finally on the
  platform — expect tests to do more, and expect that to surface things darwin hid.
- **`cmd | tail` takes its exit status from `tail`.** Capture into a variable or use
  `PIPESTATUS`. This has misreported an exit code three times in this project.
- **A mutation script's `assert` can exit without mutating**, and a naive read then reports a
  false pass on an unmutated file. Verify the mutation actually applied before believing any
  result.
- **An inert mutation is itself a finding** — chase it, do not accept the green.
- **A test can pass for a reason unrelated to its claim.** Five shipped in this project so far:
  an `assertIn("2", …)` satisfied by the `2` in mode `2750`; a `\bhermes\b` regex satisfied by
  the `hermes` inside `hermes-rail`; a non-receipt assertion that could not see a request
  smuggled into the same `sendall()`; a `clen == 0` guard whose test passed with the guard
  deleted; and an `assertIn("ExecStartPre", body)` satisfied by `#ExecStartPre=`. **Reading
  found none of them. Mutation found all five.** Prove a guard guards by making it fail.
- **An instrument that reports "safe" needs to be shown reporting "safe" when the target really
  is safe** — not just "unsafe" when it is unsafe. That is the half of a control that usually
  goes unchecked.
- **AF_UNIX paths cap near 104 bytes** — test sockets go in `/tmp/<short>.sock`.
- **Build container probe stores with in-container `mktemp -d` or a named volume, never a bind
  mount.** Docker Desktop does not preserve `chown`'d ownership across one, so an unsafe layout
  can read as safe. Verify whether this holds on Linux rather than assuming it carries over.
- **Plan text is the least reliable input in the room.** Six defects in the Phase B plan were
  the controller's, every one found by an implementer or reviewer refusing to force an
  instruction that did not match the file. When one reports that a brief is wrong, it usually is.
- **A document that does not record something cannot be used to rule it out.** The endpoint
  measurement's silence about `Content-Length` headers is absence of evidence, and was briefly
  misread as evidence of absence during the F4 review.

## One unreviewed change to know about

`#26` merged without independent review of a change to `_handle`'s request-framing path — the
exact code C1 lived in. Small, well-tested, fails closed, and every new test was confirmed to
fail against the unfixed code first. But it was written and reviewed by the same session. If
anything in §5 behaves oddly, start there.

## Confirm your understanding and flag any drift before starting.
