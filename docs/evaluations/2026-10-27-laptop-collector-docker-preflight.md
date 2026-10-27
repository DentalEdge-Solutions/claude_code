# Laptop collector — Docker pre-flight and loud incomplete bundles

> **Date:** 2026-10-27 · **Branch:** `fix/laptop-collector-docker-preflight` (base `78b446c`) · **Spec:**
> `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md` §4.3, §5.1, §5.3 · **Lesson:** the active
> brain lesson of 2026-10-14, "The laptop collector needs Docker Desktop running". **Installed:** Python 3.14.6,
> node v26.9.0. Implementer's record; the independent reviewer closes findings (`docs/REVIEW_PROTOCOL.md`).
> Includes review round 1 (LC-R-1 to LC-R-8), below.

## The trap

`bin/collect-review-evidence-laptop.py` runs D3.1 as `audit-credential-access.sh --all --customer <id>`. That
script runs each credential's audit with `docker compose ... run` (`set -eu`; it echoes `===== .env.ga =====`
per credential and exits with the last failing audit's code). With Docker Desktop off, `docker compose` fails on
stderr (discarded by the collector, which only counts its lines), stdout holds only the separator lines,
`parse_audit` raises "no audit documents in the output", D3.1 is recorded `could-not-check` — and the collector
still exited **0**. The only sign was inside the bundle. Nothing was asked of Google. Review round 1 found the
same trap for D6.3: a failed package build was `could-not-check` with exit 0.

## The change

1. **Pre-flight**, after the `--customer` and review-key checks and before the audit, in both modes:
   `docker_problem()` runs `docker info` with stdin, stdout and stderr on `/dev/null` and a 15 s timeout. It
   returns `None` or one of four fixed reasons (`Docker is not running`, `the docker command was not found`,
   `Docker did not answer within 15s`, `the docker command could not be started`). Docker's own output is never
   relayed. On a problem: one stderr line `collect-review-evidence-laptop: <reason>: start Docker Desktop, then
   re-run (D3.1 runs the credential audit in a Docker container); the audit did not run, nothing written`.
2. **No bundle on a failed pre-flight.** Justification: the spec's rule "an item it cannot run is
   `could-not-check`, never a pass" (§4, item 2) is about a bundle that is used; a review bundle missing its central
   laptop item cannot serve a review (CHECKLIST D3.1 would be CANNOT-VERIFY, so not PASS), and BRING-UP already
   told the operator to set such a file aside. Writing nothing makes the cause the only output.
3. **Docker up, still no document** (for example a missing `docker compose` plugin, an image that fails, or no
   credential file — `--all` skips a missing `.env.ga`/`.env.gaw` and exits 0 with no document): the bundle **is**
   written, as before (it is the evidence: the audit's `rc` and the count of discarded stderr lines), followed by
   one stderr line `D3.1 could not be checked: no audit documents in the output (the audit exited N); the bundle
   is incomplete: do not use it; Docker answered, so check that .env.ga (and .env.gaw, if it is authorised) is next
   to audit-credential-access.sh and that `docker compose` works, then collect again`, and exit **4**. Precedent:
   the box collector's `--fingerprint-only` prints an incomplete fingerprint and exits 2 (E3).
4. **A failed package build** (all three `--package-*` arguments given, `package_hash` raises): the bundle is
   written with D6.3 `could-not-check` and exit **4** too, with one stderr line `D6.3 could not be checked: the
   package build failed: <reason>; the bundle is incomplete: ...`. `<reason>` and the bundle's D6.3 `reason` are
   **fixed words**, mapped from the known `build()` messages (`package_reason()`): not a full 40-hex commit; the
   repository not checked out at the commit; tracked files modified; a git command failed; a packaged doc holds a
   customer-id-shaped number; anything else "the package build failed". Before, the bundle carried `str(e)`, which
   for `build()` holds the repository's full path (`<repo> HEAD is …`), git's own stderr, or file names — in a file
   that goes to the reviewer. Both incomplete items give one line each.
5. **The `--package-*` arguments go together.** One or two of the three is a usage error (`ap.error`, exit 2,
   nothing run). None keeps D6.3 `could-not-check` ("no --package-* arguments") with exit 0 — now documented in
   the docstring and BRING-UP, which also say the exit code alone does not show it and that the review
   collection always passes all three.
6. **`--access-digest`** keeps its contract (stdout a digest or `could-not-check`; exit 0 or 2), and now says why
   on stderr in one line: the Docker pre-flight reason, `no access digest: D3.1 could not be checked: ...`, or
   `the audit exited N, not 0: this digest does not certify the access`. Kept at 2 rather than the bundle mode's
   3 because BRING-UP's spec §5.3 check and the spec define this mode as "digest or not".
7. **Unchanged:** customer-id redaction (keyed `cid:` fingerprints), audit stderr discarded, `restrict_output`
   (owner-only, nothing written otherwise), the `--customer` digits check, the key file's 0600 check (it still
   runs first: a bad key exits 2 without asking Docker). Every message starts with `PROG`. Only words the
   collector wrote itself, the audit's integer exit code and (for the review key only, as before) the key file's
   path are printed.

## Exit codes

| Mode | Case | Before | After |
|---|---|---|---|
| bundle | D3.1 observed; D6.3 observed or not asked for | 0 | 0 |
| bundle | `--customer` not digits | 1 | 1 |
| bundle | review key unusable / output not owner-only / argparse error | 2 | 2 |
| bundle | one or two of the three `--package-*` arguments | 0, bundle with D6.3 `could-not-check` | **2**, usage error, nothing run or written |
| bundle | Docker not reachable | 0, bundle with D3.1 `could-not-check` | **3**, one stderr line, no audit, nothing written |
| bundle | Docker up, no audit document | 0, bundle with D3.1 `could-not-check` | **4**, bundle written, one stderr line |
| bundle | package build failed (all three `--package-*` given) | 0, bundle with D6.3 `could-not-check` and `str(e)` | **4**, bundle written with a fixed reason, one stderr line |
| bundle | no `--package-*` argument at all | 0, D6.3 `could-not-check` | 0 (unchanged, now documented) |
| `--access-digest` | digest, audit rc 0 | 0 | 0 |
| `--access-digest` | Docker not reachable | 2, `could-not-check`, silent | 2, `could-not-check`, one stderr line; the audit does not run |
| `--access-digest` | no document | 2, silent | 2, one stderr line |
| `--access-digest` | digest, audit rc ≠ 0 | 2, digest, silent | 2, digest, one stderr line |

## Callers checked

`git grep` over the repository, excluding `infra/hermes-agent/data/`:

- **`deploy/BRING-UP.md`, security-review step 4** (the laptop collection runbook): the only caller that reads the
  exit code's meaning — it said "still ends with exit code 0". **Updated**: `python3 bin/…` from
  `infra/hermes-agent` (the file is 100644; as written it was rc 126, measured by the reviewer), the three
  `--package-*` arguments spelled out, the pre-flight, exit codes 0 to 4 with the D3.1 and D6.3 lines, the empty
  file a failed redirect leaves, the no-`--package-*` case, and `; echo "collector_rc=$?"` → `collector_rc=0`; the
  per-item status check is kept.
- **`deploy/BRING-UP.md`, the spec §5.3 checks before the kill switch, laptop line** (`--access-digest` == the
  report's digest): compares stdout; stdout and the 0/2 contract are unchanged. One comment line added naming exit
  2 and the stderr line.
- **`bin/security-review-checklist.test.py`**: reads `ITEMS` only (unchanged: `D3.1`, `D6.3`). Passes.
- **`bin/summarize-review-bundle.py`**: box bundles only (`kind == "box"`); never reads a laptop bundle.
- **`bin/collect-review-evidence.py`** (box): does not read the laptop bundle or call the collector.
- **`deploy/security-review/CHECKLIST.md`, `REVIEWER-BRIEF.md`, `REPORT-TEMPLATE.md`**: describe bundle contents,
  not the collector's exit code; a bundle with D3.1 or D6.3 `could-not-check` is still CANNOT-VERIFY; D6.3's
  `reason` is not read by any of them. Not changed (so no checklist version bump).
- **Handoffs and plans** (`docs/superpowers/handoffs/2026-09-29-…`, `2026-09-30-…`, `2026-10-09-review-9-pass.md`;
  plans `2026-09-28-…`, `2026-09-29-…`, `2026-09-30-…`, `2026-10-02-…`, `2026-10-13-…`) and
  `docs/security-reviews/2026-09-29-review-2.md`: historical records; none scripts on the exit code. Not changed.
- No script, hook or CI job invokes the collector.

## Docs updated

`infra/hermes-agent/deploy/BRING-UP.md` (step 4 and the §5.3 comment), `infra/hermes-agent/README.md` ("Security
review and app packages": "in bundle mode" exit 3, exit 4 for D3.1 or a requested D6.3, `--access-digest` exit 2,
and "every exit code, 0 to 4" listed in the docstring and step 4 — now true), the module docstring (the
`--package-*` rule and the exit-code table). `infra/hermes-agent/CLAUDE.md` does not exist.

## Tests

`bin/collect-review-evidence-laptop.test.py`, stdlib only, faking `subprocess.run`, `docker_problem` and (round 1)
`package_hash` (no real Docker, no audit, no build): 15 → 29 → 34 tests.

- Red `9a49211` (kept: 24 errors — every `TestMain` test too, since its `setUp` patches the not yet existing
  `docker_problem` to keep Docker up for the existing tests — and 1 failure, the runbook sentence).
  `TestDockerProblem` (argv `["docker", "info"]`, all three streams `DEVNULL`, the timeout ≤ 30 s; non-zero,
  missing command, timeout and `OSError` are problems); `TestLoudFailures` (Docker down → 3, one line, empty
  stdout, audit not run; key checked before Docker; Docker up + no document → 4; normal path 0 with empty stderr;
  `--access-digest` Docker down / no document / rc 3 / normal; distinct exit codes; every case asserts no customer
  id, no audit stderr text and no key in stdout or stderr); `TestRunbookNamesTheExitCodes`.
- Round 1 red `4e57394` (kept: 12 errors, 3 failures): partial `--package-*` → `SystemExit(2)` for all six
  combinations, nothing printed to stdout, the audit not run (replaces the old test that expected a bundle);
  a build failure → 4, bundle written with D3.1 observed and D6.3's fixed reason, one stderr line, for seven
  messages (five known, an `OSError`, an unknown `ValueError`), with no `/Users/someone` path and no `fatal:` in
  stdout or stderr; a successful build → 0; D3.1 and D6.3 both incomplete → 4 and two lines; the D3.1 line names
  `.env.ga` and `docker compose` and not Docker Desktop; no literal `collect-review-evidence-laptop:` prefix in
  the source (PROG); BRING-UP step 4 (the "4. Laptop" line and the D3.1 line) names exit codes 1, 2, 3, 4 and
  D6.3, runs `` `python3 bin/collect-review-evidence-laptop.py --customer``, has no bare `bin/…laptop.py`, and
  carries `echo "collector_rc=$?"` and `` `collector_rc=0` ``; the docstring names exit 1 to 4 and D6.3.
- `infra/hermes-agent/bin/run-bin-tests.sh`: **61/61 suites passed**.
- `node scripts/run-all-tests.js` (alone): **47/47 suites passed**.

## Not measured

- **No Docker-off run on the owner's laptop.** That `docker info` exits non-zero with Docker Desktop quit, and
  answers within 15 s when it is up, is from Docker's documented behaviour and the runbook's own existing
  `docker info >/dev/null 2>&1` check, not measured here (the brief forbade running Docker). Owner probe, on the
  laptop, from `infra/hermes-agent` at the merged `main`, with `CUST` set to the dormant pilot id:
  1. Quit Docker Desktop (menu bar → Quit Docker Desktop).
  2. Paste, as one block (fail-closed: it runs nothing while Docker still answers; the bundle-mode run reads the
     0600 review key first, and a missing key gives exit 2 before Docker is asked):

     ```sh
     if docker info >/dev/null 2>&1; then echo "Docker still answers: quit it first"; else
       python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --access-digest; echo "digest_rc=$?"
       f=$(mktemp)
       python3 bin/collect-review-evidence-laptop.py --customer "$CUST" > "$f"; echo "bundle_rc=$?"
       echo "bytes=$(wc -c < "$f" | tr -d ' ')"; rm -f "$f"
     fi
     ```

     Expected: `could-not-check`, then one stderr line `collect-review-evidence-laptop: Docker is not running:
     start Docker Desktop, then re-run (...); the audit did not run`, `digest_rc=2`; the same line ending
     `, nothing written`, `bundle_rc=3`, `bytes=0`. (`mktemp` creates the file 0600; `tr` removes the padding
     macOS `wc -c` prints.) No customer id is printed.
  3. Start Docker Desktop, wait for `docker info >/dev/null 2>&1; echo $?` → `0`, and run BRING-UP step 4 →
     `collector_rc=0` and `{'D3.1': 'observed', 'D6.3': 'observed'}`.
- The exit-4 paths with a real Docker (a missing compose plugin) or a real failed build were not reproduced; the
  mapping of real `build()` messages to fixed reasons is tested with messages copied from `build-app-package.py`
  and `package_lib.py`, not from a run.
- A changed `bin/` and `deploy/` tree changes the box fingerprint's code component once the box's checkout is
  pulled: expected, review #12 measures the new tree. The laptop collector runs from the laptop's checkout, so the
  laptop must be at the merged `main` before review #12's laptop collection.

## Brain

The active lesson of 2026-10-14 ("The laptop collector needs Docker Desktop running") becomes **stale on merge**
in one part: it says the collector exits 0 with Docker off, which is no longer true (exit 3 before the audit,
exit 4 for an incomplete D3.1 or a failed requested D6.3). Its advice — start Docker Desktop first and read both
items' status — stays right. It is updated through capture → compile → `brain-promote --approve` at the weekly
review. `.project-brain/` was not edited.

## Review round 1

Reviewer findings LC-R-1 to LC-R-8 on head `a7f2bdd`; coordinator decisions applied. Red `4e57394`, fix
`e7b2cbf`. The reviewer closes them.

| Finding | Change | Where |
|---|---|---|
| LC-R-1 (same trap, D6.3) | build failure → exit 4 with the bundle; fixed reason in the bundle and on stderr, never `str(e)`; partial `--package-*` → `ap.error` (2); none → 0, documented; `EXIT_D31_INCOMPLETE` renamed `EXIT_INCOMPLETE` | `collect-review-evidence-laptop.py` docstring, `EXIT_INCOMPLETE`, `PACKAGE_REASONS`, `package_reason()`, `main()`; BRING-UP step 4 |
| LC-R-2 | step 4 runs `python3 bin/collect-review-evidence-laptop.py` from `infra/hermes-agent` with the three arguments spelled out; the build hint also uses `python3` (`build-app-package.py` is 100644 too) | BRING-UP step 4 |
| LC-R-3 | owner probe fail-closed (`if docker info …`), `mktemp` file, `wc -c` padding removed | this record, "Not measured" |
| LC-R-4 | the D3.1 exit-4 line no longer asks about Docker Desktop; it points at `.env.ga`/`.env.gaw` and `docker compose` | `main()`; BRING-UP step 4 |
| LC-R-5 | README: "in bundle mode" for exit 3; "every exit code, 0 to 4" is now listed in step 4 too | README "Security review and app packages" |
| LC-R-6 | test: step 4 carries the `python3` invocation, `echo "collector_rc=$?"` and `` `collector_rc=0` `` | `test_bring_up_laptop_step_runs_the_collector_with_python3_and_shows_its_rc` |
| LC-R-7 | the brain lesson's staleness stated | "Brain", above |
| LC-R-8 | every message uses `PROG`; a test forbids the literal prefix | `main()`; `test_every_message_names_the_program` |
