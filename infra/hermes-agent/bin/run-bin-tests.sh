#!/bin/sh
# Run every stdlib-only Python suite in this directory.
#
# These suites are not discoverable by scripts/run-all-tests.js, which is node-only by
# design (*.test.js under skills/ and scripts/). That was tolerable while this directory
# held read-only tooling; it is not, now that it holds the mutation tier — the only code
# in the project permitted to change a client's external account. One command beats four
# remembered ones.
#
# Three deliberate properties:
#   * Suites are DISCOVERED, never listed. A new *.test.py is picked up automatically,
#     so a suite cannot be added and silently left out of the run.
#   * Every suite runs even after one fails, and the exit status is non-zero if ANY
#     failed. Stopping at the first failure hides the rest, and `for ... || break` in a
#     shell loop reports success for the run that broke out of it.
#   * Every suite runs under a bounded timeout. A suite that blocks (an unguarded fifo
#     read, a subprocess that never returns, a flock that never releases) must count as
#     a FAILURE distinctly labeled TIMEOUT, not wedge this script — and not silently
#     upgrade a hang into a false green by letting the shell wait forever. Verified
#     against a real hanging suite, not just read: see hermes-broker.py Task 7's mutation
#     row 1, which demonstrated the un-bounded version of this script hangs forever on
#     `--once --watch` falling through the removed mutual-exclusion check into the real,
#     infinite poll loop.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here" || exit 1

# python3, never python: a bare `python` does not exist in this environment, and its
# "command not found" is a SHELL error that has previously been mistaken for a failing test.
py=python3
command -v "$py" >/dev/null 2>&1 || { echo "run-bin-tests: $py not found" >&2; exit 1; }

# Per-suite timeout in seconds, overridable by env var. Every suite here runs in well
# under a second today, so 120s is generous headroom, not a tight budget.
timeout_secs="${HERMES_BIN_TEST_TIMEOUT:-120}"

# PORTABILITY: `timeout(1)` is GNU coreutils — present by default on Linux CI, absent
# from base macOS (where `brew install coreutils` provides it only as `gtimeout`).
# Detect one or the other; if NEITHER exists, degrade to running unbounded rather than
# failing the whole run over a missing convenience tool — but say so loudly exactly
# once, so an unbounded run is never mistaken for a bounded one that simply didn't fire.
timeout_bin=''
if command -v timeout >/dev/null 2>&1; then
  timeout_bin='timeout'
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_bin='gtimeout'
else
  echo "run-bin-tests: WARNING — no 'timeout' or 'gtimeout' found; suites run UNBOUNDED on this host" >&2
fi

pass=0
fail=0
timed_out=0
failed=''
for t in *.test.py; do
  [ -e "$t" ] || { echo "run-bin-tests: no *.test.py found in $here" >&2; exit 1; }
  if [ -n "$timeout_bin" ]; then
    out=$("$timeout_bin" "$timeout_secs" "$py" "$t" 2>&1)
    rc=$?
  else
    out=$("$py" "$t" 2>&1)
    rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    pass=$((pass + 1))
    printf '  OK    %s\n' "$t"
  elif [ -n "$timeout_bin" ] && [ "$rc" -eq 124 ]; then
    # 124 is `timeout`/`gtimeout`'s own reserved exit code for "the command was killed
    # because it exceeded the bound" — distinct from any exit code the suite itself
    # could produce, so this can never be confused with a suite that genuinely exits 124.
    fail=$((fail + 1))
    timed_out=$((timed_out + 1))
    failed="$failed $t"
    printf '  TIMEOUT  %s (exceeded %ss)\n' "$t" "$timeout_secs"
    printf '%s\n' "$out" | sed 's/^/        /'
  else
    fail=$((fail + 1))
    failed="$failed $t"
    printf '  FAIL  %s\n' "$t"
    printf '%s\n' "$out" | sed 's/^/        /'
  fi
done

echo "---"
if [ "$fail" -eq 0 ]; then
  echo "hermes bin: $pass/$pass suites passed"
  exit 0
fi
if [ "$timed_out" -gt 0 ]; then
  echo "hermes bin: $pass passed, $fail FAILED ($timed_out of which TIMED OUT) —$failed"
else
  echo "hermes bin: $pass passed, $fail FAILED —$failed"
fi
exit 1
