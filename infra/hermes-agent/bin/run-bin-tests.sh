#!/bin/sh
# Run every stdlib-only Python suite in this directory.
#
# These suites are not discoverable by scripts/run-all-tests.js, which is node-only by
# design (*.test.js under skills/ and scripts/). That was tolerable while this directory
# held read-only tooling; it is not, now that it holds the mutation tier — the only code
# in the project permitted to change a client's external account. One command beats four
# remembered ones.
#
# Two deliberate properties:
#   * Suites are DISCOVERED, never listed. A new *.test.py is picked up automatically,
#     so a suite cannot be added and silently left out of the run.
#   * Every suite runs even after one fails, and the exit status is non-zero if ANY
#     failed. Stopping at the first failure hides the rest, and `for ... || break` in a
#     shell loop reports success for the run that broke out of it.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here" || exit 1

# python3, never python: a bare `python` does not exist in this environment, and its
# "command not found" is a SHELL error that has previously been mistaken for a failing test.
py=python3
command -v "$py" >/dev/null 2>&1 || { echo "run-bin-tests: $py not found" >&2; exit 1; }

pass=0
fail=0
failed=''
for t in *.test.py; do
  [ -e "$t" ] || { echo "run-bin-tests: no *.test.py found in $here" >&2; exit 1; }
  if out=$("$py" "$t" 2>&1); then
    pass=$((pass + 1))
    printf '  OK    %s\n' "$t"
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
echo "hermes bin: $pass passed, $fail FAILED —$failed"
exit 1
