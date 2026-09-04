# Session prompt — S3-b: audit-log integrity

Open a new session and point it here rather than pasting the body:

> Read `docs/superpowers/handoffs/2026-09-03-s3b-audit-log-integrity.md`, then confirm your
> understanding and flag any drift before starting.

Pointing at the file keeps corrections versioned; pasting a stale copy is how the drifts
corrected on 2026-09-04 got into the last session in the first place.

---

We're continuing the Hermes AIOS project (Nous Hermes Agent as a Dockerized control plane
operating registered Claude Code projects). **Plan 1 and Plan 2 Phase A are merged, and the
approval-handoff CRITICAL found by the live gate is fixed and merged.** This session plans and
executes the **S3-b wave: audit-log integrity**.

## Read these first

- `docs/superpowers/specs/2026-09-03-s3b-audit-log-integrity-brief.md` — **the brief for this
  wave.** It is a brief, not a plan: brainstorm from it. It carries the P2/P3 measurements, why
  this is three *coupled* changes, and the test technique most likely to be got wrong.
- `.superpowers/sdd/2026-08-24-hermes-governed-syscall/progress.md` — Plan 2's ledger. ~25
  numbered rulings (R19–R25), the Task 12 seam review, Task 13's live gate, and every parked
  minor. Authoritative.
- `.superpowers/sdd/2026-09-02-hermes-syscall-approval-handoff/HANDOFF.md` — the CRITICAL fix's
  rulings and open items.
- `docs/evaluations/2026-08-30-hermes-phase-a-deployment-readiness.md` — findings P1–P6.
- `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` — the binding spec. §7
  and §9 were **corrected 2026-09-03** (dated, original struck); §6.4 carries deviation D1.
  **Trust the code over any document where they disagree.**

## STATE — measured, not asserted

> **Corrected 2026-09-04.** The original STATE was written before PR #21 merged and carried four
> drifts, each re-measured below. The struck values are kept so a reader can tell a correction
> from a fresh claim.

`main` at **`a9fb2bf`** (~~`15907a5`~~ — that is PR #20's merge, two commits back). **Nothing in
flight.** PR #21 is **MERGED** (~~open~~), so the brief and this file are already on `main`.

- `infra/hermes-agent/bin/run-bin-tests.sh` → **25/25 suites** (re-measured 2026-09-04, exit 0)
- `node scripts/run-all-tests.js` → **22/22 suites** (re-measured 2026-09-04, exit 0)
- CI has four jobs and **does now run the tests** — verified in the runner log, not the tick.
- Kill switch: the switch is the **file** `~/.hermes/governance/control/mutation-enabled`
  (`preflight-governance-access.py:50`), and it is **absent — mutation disabled at rest.**
  ~~The directory `control/` is absent~~ — **the directory EXISTS** and holds `.locks/`, so
  `ls control/` returns 0 and proves nothing. **Test the file, and pair it with a live control**
  (create → detect → remove); a directory-existence check here is exactly the no-op gate this
  document warns about below. Leave the switch off except where a live gate demands otherwise,
  and turn it off again immediately after.
- Working tree dirt — **5 tracked changes and 43 untracked entries**, not the ~~5 tracked plus
  `.obsidian/`~~ originally stated. Tracked: `.project-brain/log.md`, two deleted
  `.project-brain` candidates, two `evals/*.json`. Untracked: `.obsidian/`, ~40 files under
  `.project-brain/reports/` and `.project-brain/decisions/candidates/`, and three under
  `evals/`. **`evals/` is only PARTIALLY gitignored**, contrary to the rule in `CLAUDE.md`.
  Never `git add -A` — and for the same reason never `git add .project-brain/` or
  `git add evals/`. **Stage by explicit path only.**
- The dormant pilot is marked `mutation_target="dormant_pilot"` in the registry. Resolve it
  programmatically via `vault_lib.resolve_dormant_pilot()` — **never hardcode a client**. The
  resolver refuses if zero or more than one client is marked.

### Corrections to the documents this file points at

- **`HANDOFF.md` is stale on one parked minor.** Its deferred-minors list still shows the
  `REQUEST_ID_RE` divergence (its item 8) as open. It was **fixed in `6645879`** — unified into
  `governance_lib` — and is already on `main`. Nothing to do there.
- **The brief's line reference has drifted.** It cites `apply-changeset.py:194` for "the undo
  path and the caps path both read through `iter_log_records`". The claim is verbatim-correct
  but now lives at **`:208`** (docstring) and **`:213`** (the call). `changeset_lib.py:610`
  independently documents that the executor can still delete the log — a useful anchor.
- **Image name.** The brief's prose says "the `ads-mutator` image" while its own example command
  says `hermes-agent-claude`. Only **`hermes-agent-claude:latest`** exists as an image;
  `ads-mutator` is the **compose service** name. Use the image tag in `docker run`.

### Environment changes landed 2026-09-04 (a `/doctor` pass, unrelated to S3-b)

Harmless to the wave, but they change what you will see, so do not mistake them for drift:

- **`CLAUDE.md`'s Codex External Eval Layer moved** to `.claude/skills/codex-eval/SKILL.md` and
  now loads on demand. Its **`Never` list stayed in `CLAUDE.md`** — safety prohibitions remain
  always-loaded. S3-b touches none of it.
- **`Bash(node *)`, `Bash(curl *)`, `Bash(python3 *)`, `Bash(gh api *)`, `Bash(git fetch *)` and
  `Bash(git pull *)` were removed** from `.claude/settings.local.json`'s allow-list — they were
  standing arbitrary-execution grants. `node scripts/run-all-tests.js` is therefore evaluated
  rather than waved through. **This is expected. Do not re-add a wildcard to silence it.**
- **Auto mode is now the default permission mode**, and 151 dormant skills were archived to
  `~/.claude/skills-removed-2026-09-04/` (restorable via `_RESTORE.sh`). The skill listing is
  39 entries, not 190.

## The task

**S3-b: the executor can delete its own audit log.** This costs **reversibility**, not merely
quota — `apply-changeset.py:194` says the undo path and the caps path both read through
`iter_log_records`. Three changes must land **together** (details in the brief):

1. invert the pre-flight's `log/` requirement (traverse+read on the dir, write on the *file*),
2. a registration bootstrap riding `migrate-governance.py` — there is **no programmatic
   registration hook**; `clients.json` is hand-edited,
3. the deploy permission change (`log/` `0750`, per-client files `0660`).

Applying (3) without (1) reproduces R19's over-checking failure a fourth time and blocks broker
startup.

## Also open — NOT this wave

- **Phase B** (Tasks 10–11: the body-inspecting Docker socket proxy and the systemd units). Its
  own plan. **The real precondition for any VPS deploy** — on a VPS the broker's Docker access
  is host root. Phase A must never be described as deployed or deployable without it. D1 is
  measured and recorded in spec §6.4: the proxy's real allow-list is **10 endpoints**, not
  `create`/`start`, and `POST /containers/create` is the one whose *body* must be inspected.
- **P6** — `vault-purge.py:42` calls `getpass.getuser()` *after* the vault is exported and
  deleted; raises with no passwd entry and no `USER`. A systemd `DynamicUser` hazard. Smaller,
  separate.

## HARD RULES

- No client names, account ids, campaign ids, metrics, or drafts in git, the brain, specs,
  plans, tests, reports, or telemetry. Redact as `<slug-1>` / `<digits>`. **Re-run the redaction
  scan before any PR, and pair it with a live control** — a scan whose control does not fire
  proves nothing.
- NEVER print a credential value or write one into a tracked file. Compare by sha12. **A sha12
  is a durable identifier of a live credential — keep it out of tracked files too.**
  `.env.*.example` are TRACKED.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in CLEARTEXT.
- `:ro` project mounts; Hermes never writes a project tree.
- Nothing mutates without an explicit per-action approval. Leave the kill switch OFF.
- `main` is protected in both repos — open a PR.
- **Only `brain-promote.js --approve` may modify `.project-brain/canon/`.** A PreToolUse hook
  fires on any Bash command merely *mentioning* that path — use a non-Bash tool to read it.
- Do not install directly from reference repositories; external skills/agents pass
  scout → audit → adapt → eval.

## MEASUREMENT TRAPS

The originals still apply. These were **earned in the last two sessions**:

- **A gate that is a no-op on your platform is not a passing gate.**
  `preflight-governance-access.py`'s `applies()` returns False off Linux. I ran it, got exit 0
  with no output, and reported it as "zero problems — the requirement holds". It was a no-op. Use
  the `ads-mutator` image (Linux, uid 10000, the real executor identity) for anything about
  UIDs, mount permissions, or the pre-flight.
- **An empty result is not evidence until the control fires.** This bit me repeatedly: two of
  three permission probes were invalid because ancestors were untraversable and append failed for
  an irrelevant reason; a customer-id scan failed closed and *told me* it was invalid; and three
  of my own verification greps reported gaps that were my patterns, not the work.
- **A seam review that only asks "can an attacker get through?" will bless a seam NOBODY can
  pass.** Task 12's seam S4 examined the exact interaction that made the syscall non-functional
  and passed it CLEAN, because it never asked whether the *authorised* caller could get through.
  Every "clean — the guard holds" needs its dual: a positive control proving the guard still
  admits the legitimate case.
- **An inert mutation is itself a finding.** When a mutation reds nothing, that is a coverage
  claim — chase it. One inert mutation exposed a completely untested wire whose regression would
  have silently restored the CRITICAL with a green suite.
- **An honest negative beats a contrived positive.** Twice, an implementer reporting "my proof
  failed and here is why" produced the session's best findings. Ask for negative results
  explicitly — "report what you checked and found *fine*" is what distinguishes "I checked" from
  "I didn't."
- **Hand-written fixtures pass vacuously.** If a fixture's format is subtly wrong, the guard
  refuses *for the wrong reason*, every "a refusal happened" assertion still passes, and the
  suite proves nothing while green. Generate fixtures through the real code path.
- **SUBAGENTS DIE — eight times across these two sessions** (session limits, and once a computer
  sleep). Never trust a dead agent's last words. Measure `git log`, `git status`, and the index
  before resuming, and tell the resumed agent exactly what you measured. If it died with
  uncommitted work, **inspect it before committing** — a leftover file is either real work or an
  unreverted mutation, and committing the latter commits a deliberate bug.
- **Front-load facts, not just warnings.** One agent died having spent its whole budget
  rediscovering a fixture format. The re-dispatch that carried the measured facts succeeded.
- **`cmd | tail` takes its exit status from `tail`.** This has now misreported an exit code
  twice here. Capture into a variable, or use `PIPESTATUS`.
- **`git checkout --` is only a safe revert AFTER the implementation is committed**, and
  **`git branch -f` — never `reset --hard`** — when moving a commit off a branch with a dirty
  tree, or you destroy the operator's uncommitted work.
- **Plan text is the least reliable input in the room.** Ten of Plan 2's defects were in the
  plan; **five in the CRITICAL-fix plan were mine**, including omitting a spec amendment
  entirely while my own self-review claimed the spec was preserved.

## Confirm your understanding and flag any drift before starting.
