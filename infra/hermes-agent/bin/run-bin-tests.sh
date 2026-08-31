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
#   * Every suite runs under a bounded timeout, UNLESS the operator has explicitly
#     opted out (see HERMES_BIN_TEST_TIMEOUT below) or no bounding tool exists on this
#     host — and either of those unbounded states is announced loudly, both up front
#     AND in the final summary line, never left to be inferred from a clean pass.
#     Verified against a real hanging suite, not just read: see hermes-broker.py Task
#     7's mutation row 1, which demonstrated the un-bounded version of this script
#     hangs forever on `--once --watch` falling through the removed mutual-exclusion
#     check into the real, infinite poll loop.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here" || exit 1

# python3, never python: a bare `python` does not exist in this environment, and its
# "command not found" is a SHELL error that has previously been mistaken for a failing test.
py=python3
command -v "$py" >/dev/null 2>&1 || { echo "run-bin-tests: $py not found" >&2; exit 1; }

# Per-suite timeout in seconds, overridable by HERMES_BIN_TEST_TIMEOUT. Every suite here
# runs in well under a second today, so 120s is generous headroom, not a tight budget.
#
# FAIL CLOSED on a malformed value (post-Task-7 review, Finding 1 — CRITICAL). GNU
# timeout treats DURATION 0 as "no timeout" (measured directly: `timeout 0 sleep 3`
# runs to completion, NOT an instant kill), so `${HERMES_BIN_TEST_TIMEOUT:-120}` used
# unvalidated would let a `=0` typo silently revert this script to fully unbounded —
# and since the timeout BINARY is still present in that case, the missing-binary
# WARNING below would never fire either, so the operator would see nothing at all.
# Reject 0, negative values, and non-numerics outright: refuse to run rather than fall
# back to the default or run unbounded. The one sanctioned way to disable the bound is
# the unmistakable literal HERMES_BIN_TEST_TIMEOUT=none, which gets the exact same loud
# UNBOUNDED warning as the missing-binary path — never a bare 0.
timeout_secs=120
unbounded_reason=''
case "${HERMES_BIN_TEST_TIMEOUT:-}" in
  '')
    ;;
  none|NONE)
    unbounded_reason="HERMES_BIN_TEST_TIMEOUT=none (explicit operator opt-out)"
    ;;
  *[!0-9]*)
    echo "run-bin-tests: HERMES_BIN_TEST_TIMEOUT='$HERMES_BIN_TEST_TIMEOUT' is not a positive integer (or the literal 'none' to explicitly disable the bound) — refusing to run" >&2
    exit 1
    ;;
  *)
    if [ "$HERMES_BIN_TEST_TIMEOUT" -eq 0 ]; then
      echo "run-bin-tests: HERMES_BIN_TEST_TIMEOUT=0 is rejected — GNU timeout treats duration 0 as \"no timeout\" (measured: 'timeout 0 sleep 3' runs to completion), not \"instant timeout\", so this would silently disable the whole protection with no warning. Use HERMES_BIN_TEST_TIMEOUT=none if you really want that — it prints the same loud UNBOUNDED warning as a missing timeout binary." >&2
      exit 1
    fi
    timeout_secs="$HERMES_BIN_TEST_TIMEOUT"
    ;;
esac

# PORTABILITY: `timeout(1)` is GNU coreutils — present by default on Linux CI, absent
# from base macOS (where `brew install coreutils` provides it only as `gtimeout`).
# Detect one or the other; if NEITHER exists, degrade to running unbounded rather than
# failing the whole run over a missing convenience tool — but say so loudly exactly
# once up front (and again in the final summary — Finding 5), so an unbounded run is
# never mistaken for a bounded one that simply didn't fire.
timeout_bin=''
if [ -n "$unbounded_reason" ]; then
  echo "run-bin-tests: WARNING — $unbounded_reason; suites run UNBOUNDED on this host" >&2
elif command -v timeout >/dev/null 2>&1; then
  timeout_bin='timeout'
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_bin='gtimeout'
else
  unbounded_reason="no 'timeout' or 'gtimeout' found on PATH"
  echo "run-bin-tests: WARNING — $unbounded_reason; suites run UNBOUNDED on this host" >&2
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
    # 124 is what timeout/gtimeout itself exits with when IT does the killing. But this
    # is not a structural guarantee (post-Task-7 review, Finding 3 — measured directly:
    # `timeout 5 sh -c 'exit 124'` also returns 124, because timeout passes the wrapped
    # command's own exit status through unchanged when it does NOT have to kill it). A
    # suite that genuinely exited 124 on its own would be misreported as a TIMEOUT here.
    # In practice unittest.main() only ever exits 0 or 1, so that collision is not
    # expected to arise for this script's actual suites — but this comment states that
    # as the reason it is fine, not as a guarantee the code enforces.
    fail=$((fail + 1))
    timed_out=$((timed_out + 1))
    failed="$failed $t"
    printf '  TIMEOUT  %s (exceeded %ss)\n' "$t" "$timeout_secs"
    printf '%s\n' "$out" | sed 's/^/        /'
  elif [ -n "$timeout_bin" ] && [ "$rc" -eq 125 ]; then
    # 125 is timeout/gtimeout's OWN usage-error exit code (e.g. a malformed duration it
    # was invoked with) — a harness misconfiguration, not a test failure. Finding 1's
    # up-front validation of HERMES_BIN_TEST_TIMEOUT should make this unreachable in
    # practice; this branch is belt-and-braces defense in depth, not load-bearing, kept
    # so that IF it ever does fire, it is never silently folded into a plain FAIL that
    # looks like the suite itself is broken (Finding 4).
    fail=$((fail + 1))
    failed="$failed $t"
    printf '  FAIL  %s (HARNESS MISCONFIGURED: %s exited 125, its own usage-error code — this should be unreachable since HERMES_BIN_TEST_TIMEOUT is validated above; investigate the harness, not this suite)\n' "$t" "$timeout_bin"
    printf '%s\n' "$out" | sed 's/^/        /'
  else
    fail=$((fail + 1))
    failed="$failed $t"
    printf '  FAIL  %s\n' "$t"
    printf '%s\n' "$out" | sed 's/^/        /'
  fi
done

echo "---"
summary_suffix=''
if [ -n "$unbounded_reason" ]; then
  summary_suffix=" [UNBOUNDED: $unbounded_reason]"
fi
if [ "$fail" -eq 0 ]; then
  echo "hermes bin: $pass/$pass suites passed$summary_suffix"
  exit 0
fi
if [ "$timed_out" -gt 0 ]; then
  echo "hermes bin: $pass passed, $fail FAILED ($timed_out of which TIMED OUT)$summary_suffix —$failed"
else
  echo "hermes bin: $pass passed, $fail FAILED$summary_suffix —$failed"
fi
exit 1
