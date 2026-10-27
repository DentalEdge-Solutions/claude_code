# Laptop collector — Docker pre-flight and a loud D3.1 failure

> **Date:** 2026-10-27 · **Branch:** `fix/laptop-collector-docker-preflight` (base `78b446c`) · **Spec:**
> `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md` §4.3, §5.1, §5.3 · **Lesson:** the active
> brain lesson of 2026-10-14, "The laptop collector needs Docker Desktop running". **Installed:** Python 3.14.6,
> node v26.9.0. Implementer's record; the independent reviewer closes findings (`docs/REVIEW_PROTOCOL.md`).

## The trap

`bin/collect-review-evidence-laptop.py` runs D3.1 as `audit-credential-access.sh --all --customer <id>`. That
script runs each credential's audit with `docker compose ... run` (`set -eu`; it echoes `===== .env.ga =====`
per credential and exits with the last failing audit's code). With Docker Desktop off, `docker compose` fails on
stderr (discarded by the collector, which only counts its lines), stdout holds only the separator lines,
`parse_audit` raises "no audit documents in the output", D3.1 is recorded `could-not-check` — and the collector
still exited **0**. The only sign was inside the bundle. Nothing was asked of Google.

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
   is incomplete: do not use it; ...`, and exit **4**. Precedent: the box collector's `--fingerprint-only` prints
   an incomplete fingerprint and exits 2 (E3).
4. **`--access-digest`** keeps its contract (stdout a digest or `could-not-check`; exit 0 or 2), and now says why
   on stderr in one line: the Docker pre-flight reason, `no access digest: D3.1 could not be checked: ...`, or
   `the audit exited N, not 0: this digest does not certify the access`. Kept at 2 rather than the bundle mode's
   3 because BRING-UP §5.3's check and the spec define this mode as "digest or not".
5. **Unchanged:** customer-id redaction (keyed `cid:` fingerprints), audit stderr discarded, `restrict_output`
   (owner-only, nothing written otherwise), the `--customer` digits check, the key file's 0600 check (it still
   runs first: a bad key exits 2 without asking Docker). D6.3 `could-not-check` for missing `--package-*`
   arguments still exits 0 (the code's tested behaviour, `test_package_items_need_all_three_args`; the runbook
   always passes them and the status check below catches it). Only reasons the collector wrote itself and the
   audit's integer exit code are printed.

## Exit codes

| Mode | Case | Before | After |
|---|---|---|---|
| bundle | D3.1 observed | 0 | 0 |
| bundle | `--customer` not digits | 1 | 1 |
| bundle | review key unusable / output not owner-only / argparse error | 2 | 2 |
| bundle | Docker not reachable | 0, bundle with D3.1 `could-not-check` | **3**, one stderr line, no audit, nothing written |
| bundle | Docker up, no audit document | 0, bundle with D3.1 `could-not-check` | **4**, bundle written, one stderr line |
| bundle | D6.3 `could-not-check` (no `--package-*`, or the build failed) | 0 | 0 (unchanged) |
| `--access-digest` | digest, audit rc 0 | 0 | 0 |
| `--access-digest` | Docker not reachable | 2, `could-not-check`, silent | 2, `could-not-check`, one stderr line; the audit does not run |
| `--access-digest` | no document | 2, silent | 2, one stderr line |
| `--access-digest` | digest, audit rc ≠ 0 | 2, digest, silent | 2, digest, one stderr line |

## Callers checked

`git grep` over the repository, excluding `infra/hermes-agent/data/`:

- **`deploy/BRING-UP.md`, security-review step 4** (the laptop collection runbook): the only caller that reads the
  exit code's meaning — it said "still ends with exit code 0". **Updated**: the pre-flight, exit codes 2/3/4, the
  empty file a failed redirect leaves, D6.3 not showing in the code, and `; echo "collector_rc=$?"` →
  `collector_rc=0`; the per-item status check is kept.
- **`deploy/BRING-UP.md`, the spec §5.3 checks before the kill switch, laptop line** (`--access-digest` == the report's digest): compares stdout; stdout and
  the 0/2 contract are unchanged. One comment line added naming exit 2 and the stderr line.
- **`bin/security-review-checklist.test.py`**: reads `ITEMS` only (unchanged: `D3.1`, `D6.3`). Passes.
- **`bin/summarize-review-bundle.py`**: box bundles only (`kind == "box"`); never reads a laptop bundle.
- **`bin/collect-review-evidence.py`** (box): does not read the laptop bundle or call the collector.
- **`deploy/security-review/CHECKLIST.md`, `REVIEWER-BRIEF.md`, `REPORT-TEMPLATE.md`**: describe bundle contents,
  not the collector's exit code; a bundle with D3.1 `could-not-check` is still CANNOT-VERIFY. Not changed (so no
  checklist version bump).
- **Handoffs and plans** (`docs/superpowers/handoffs/2026-09-29-…`, `2026-09-30-…`, `2026-10-09-review-9-pass.md`;
  plans `2026-09-28-…`, `2026-09-29-…`, `2026-09-30-…`, `2026-10-02-…`, `2026-10-13-…`) and
  `docs/security-reviews/2026-09-29-review-2.md`: historical records; none scripts on the exit code. Not changed.
- No script, hook or CI job invokes the collector.

## Docs updated

`infra/hermes-agent/deploy/BRING-UP.md` (step 4 and the §5.3 comment), `infra/hermes-agent/README.md` ("Security
review and app packages": one sentence), the module docstring (exit-code table). `infra/hermes-agent/CLAUDE.md`
does not exist.

## Tests

`bin/collect-review-evidence-laptop.test.py`, stdlib only, faking `subprocess.run` and `docker_problem` (no real
Docker, no audit): 15 → 29 tests. Red commit `9a49211` (kept: 24 errors — every `TestMain` test too, since its
`setUp` patches the not yet existing `docker_problem` to keep Docker up for the existing tests — and 1 failure,
the runbook sentence). New: `TestDockerProblem` (argv `["docker", "info"]`, all three streams `DEVNULL`, the
timeout ≤ 30 s; non-zero, missing command, timeout and `OSError` are problems); `TestLoudFailures` (Docker down →
3, one line, empty stdout, audit not run; key checked before Docker; Docker up + no document → 4, bundle with D3.1
`could-not-check`, one line; normal path 0 and empty stderr with D6.3 no-args still 0; `--access-digest` Docker
down / no document / rc 3 / normal; distinct exit codes; every case asserts no customer id, no audit stderr text
and no key in stdout or stderr); `TestRunbookNamesTheExitCodes` (BRING-UP step 4 names exit codes 3 and 4 and no
longer says "still ends with exit code 0"; the docstring names them).

- `infra/hermes-agent/bin/run-bin-tests.sh`: **61/61 suites passed**.
- `node scripts/run-all-tests.js` (alone): **47/47 suites passed**.

## Not measured

- **No Docker-off run on the owner's laptop.** That `docker info` exits non-zero with Docker Desktop quit, and
  answers within 15 s when it is up, is from Docker's documented behaviour and the runbook's own existing
  `docker info >/dev/null 2>&1` check, not measured here (the brief forbade running Docker). Owner probe, on the
  laptop, from `infra/hermes-agent` at the merged `main`:
  1. Quit Docker Desktop (menu bar → Quit Docker Desktop); wait until `docker info >/dev/null 2>&1; echo $?`
     prints a non-zero number.
  2. Harmless invocation (the access digest needs no key and writes no file):
     `python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --access-digest; echo "rc=$?"` → stdout
     `could-not-check`, stderr one line `collect-review-evidence-laptop: Docker is not running: start Docker
     Desktop, then re-run (...); the audit did not run`, then `rc=2`. Bundle mode, to a throwaway file:
     `( umask 077; python3 bin/collect-review-evidence-laptop.py --customer "$CUST" > /tmp/probe-laptop.json );
     echo "rc=$?"; wc -c < /tmp/probe-laptop.json; rm -f /tmp/probe-laptop.json` → the same line ending
     `nothing written`, `rc=3`, `0` (bundle mode reads the review key first: a missing or non-0600 key
     exits 2 before Docker is asked). Neither prints a customer id.
  3. Start Docker Desktop, wait for `docker info >/dev/null 2>&1; echo $?` → `0`, and run the normal collection
     of BRING-UP step 4 → `collector_rc=0` and `{'D3.1': 'observed', 'D6.3': 'observed'}`.
- The exit-4 path with a real Docker (for example a missing compose plugin) was not reproduced.
- A changed `bin/` and `deploy/` tree changes the box fingerprint's code component once the box's checkout is
  pulled: expected, review #12 measures the new tree. The laptop collector runs from the laptop's checkout, so the
  laptop must be at the merged `main` before review #12's laptop collection.

## Brain

The active lesson (2026-10-14) stays valid: Docker Desktop must still be running. At the weekly review it can be
updated to say the collector now fails loudly (exit 3 before the audit, exit 4 for an incomplete D3.1) and that
the per-item status check remains. `.project-brain/` was not edited.

## Open item for the reviewer

D6.3 `could-not-check` when the `--package-*` arguments were given but the build failed still exits 0 (out of
this brief's scope; BRING-UP's status check catches it). Making that loud too would be the same pattern.
