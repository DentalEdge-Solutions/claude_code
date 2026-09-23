# F14 — Attested executor exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The broker never reports "nothing was mutated" unless the executor itself proved it chose that exit; every unproven exit becomes status 4, "possibly modified".

**Architecture:** `apply-changeset.py` prints `HERMES-EXIT <nonce> <rc>` as its last stdout line, only for exits it chose. `run-ads-mutate.sh` generates the nonce, passes it into the container, and after Compose returns trusts `rc` only if exactly one line matches it exactly; anything else exits 4. The broker maps 4 to `failed_unverified_exit` and the Hermes client maps 4 to `EXIT_FAILED_AFTER_MUTATION`.

**Tech Stack:** Python 3 stdlib (`unittest`), POSIX `sh`, Docker Compose (Linux CI only).

**Spec:** `docs/superpowers/specs/2026-09-23-f14-attested-executor-exit-design.md`

## Global Constraints

- **Mutation stays disabled. The kill switch is ABSENT and nothing in this plan creates it.**
- **NEVER run `docker compose config`** — it prints `env_file` secrets in cleartext. Never read or print `.env`.
- **Do not widen the proxy allow-list.** No change to `docker-create-proxy.py` or `hermes-docker-proxy.service`.
- **Never edit a tracked file to run a mutation test.** Every firing control in this plan is built in memory (`mock.patch`) or on the test fixture's temp copy of the wrapper.
- **Stage by explicit path only.** Never `git add -A`, `.project-brain/`, `evals/`, `CLAUDE.md`. The working tree carries unrelated operator changes.
- Status meanings 0/1/2/3 are unchanged. New wrapper status: `4` = unverified.
- Nonce: exactly 32 lowercase hex characters, `^[0-9a-f]{32}$`, env var `HERMES_EXIT_NONCE`.
- Attestation line, exact: `HERMES-EXIT <nonce> <rc>` (single spaces, no trailing text).
- Banner text, exact substring: `EXECUTOR EXIT NOT VERIFIED`.
- Classification, exact: `failed_unverified_exit`, status `failed`.
- Required CI job names are gates: **do not rename** `Bind agreement (root, Linux, real proxy)` or `Test suites (node + hermes bin)`.
- A green CI job can have executed nothing: read `executed N, skipped M` on the PR **and** on the merge commit.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The wrapper tests skip on Linux CI** (`run-ads-mutate.test.py`'s `_UID_OK` gate needs uid 10000). They execute only on darwin; the Linux proof of the wrapper is `bind-agreement-integration.test.py` (Task 4). A reviewer must not read "hermes bin 31/31" as Linux coverage of Task 2.
2. **A line that is in the output but for a different rc** (e.g. rc 0, line says 2) and **a second line with the same nonce but another rc** — both must be 4. Pinned in Task 2 (tests `test_a_line_disagreeing_with_rc_is_not_verified`, `test_a_second_nonce_line_with_another_rc_is_not_verified`).
3. **Stdout write failing inside the executor's attestation** (broken pipe) — must not produce a partial line that verifies. It raises, the process exits 1 with no complete line, the wrapper gives 4. Pinned in Task 1 (`test_a_failing_stdout_is_not_attested`).
4. **`SystemExit(True)`** — `bool` is an `int` subclass; it must not be attested as 1. Pinned in Task 1 (`test_a_bool_or_string_exit_is_not_attested`).
5. **Nonce generation failing on the host** (`od` missing, `/dev/urandom` unreadable) — must exit 1 **before** Compose runs, never run with an empty nonce. Pinned in Task 2 (`test_no_nonce_means_no_run`).

---

### Task 1: The executor attests the exits it chose

**Files:**
- Modify: `infra/hermes-agent/bin/apply-changeset.py` (constants near `:50`; new function before `main` at `:402`; `__main__` at `:435-436`)
- Test: `infra/hermes-agent/bin/apply-changeset.test.py` (new class before `if __name__` at `:832`)

**Interfaces:**
- Produces: `EXIT_NONCE_VAR = "HERMES_EXIT_NONCE"`; `_attested_exit(main_fn, environ=None)` — calls `main_fn()`, always ends by raising `SystemExit` (or re-raising a crash); prints `HERMES-EXIT <nonce> <rc>` only for a chosen int status and a valid nonce.

- [ ] **Step 1: Write the failing tests**

Append before `if __name__ == "__main__":` in `apply-changeset.test.py`:

```python
NONCE = "0123456789abcdef0123456789abcdef"


class TestAttestedExit(unittest.TestCase):
    """F14. The executor states, on its LAST stdout line, the exit it chose, bound to the
    wrapper's per-run nonce. It must never attest a crash: the wrapper trusts 0/1/2/3 only
    when this line proves the executor itself picked it (spec 2026-09-23 §3.1)."""

    def _attest(self, fn, environ):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            X._attested_exit(fn, environ=environ)
        return ctx.exception.code, out.getvalue()

    def _assert_attested_last(self, out, rc):
        lines = out.splitlines()
        self.assertEqual(lines[-1], "HERMES-EXIT %s %d" % (NONCE, rc), out)
        self.assertEqual(sum(1 for l in lines if l.startswith("HERMES-EXIT")), 1, out)

    def test_a_returned_status_is_attested_last(self):
        for rc in (0, 1, 2, 3):
            def fn(rc=rc):
                print("executor output")
                return rc
            code, out = self._attest(fn, {X.EXIT_NONCE_VAR: NONCE})
            self.assertEqual(code, rc)
            self._assert_attested_last(out, rc)

    def test_a_chosen_system_exit_is_attested(self):
        for raised, rc in ((SystemExit(2), 2), (SystemExit(3), 3), (SystemExit(None), 0)):
            def fn(raised=raised):
                print("executor output")
                raise raised
            code, out = self._attest(fn, {X.EXIT_NONCE_VAR: NONCE})
            self.assertEqual(code, rc)
            self._assert_attested_last(out, rc)

    def test_a_crash_is_never_attested(self):
        for exc in (RuntimeError("boom"), KeyboardInterrupt()):
            def fn(exc=exc):
                raise exc
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(type(exc)):
                X._attested_exit(fn, environ={X.EXIT_NONCE_VAR: NONCE})
            self.assertNotIn("HERMES-EXIT", out.getvalue())

    def test_a_bool_or_string_exit_is_not_attested(self):
        for raised in (SystemExit(True), SystemExit("a message")):
            def fn(raised=raised):
                raise raised
            code, out = self._attest(fn, {X.EXIT_NONCE_VAR: NONCE})
            self.assertEqual(code, raised.code)
            self.assertNotIn("HERMES-EXIT", out)

    def test_no_valid_nonce_means_no_line(self):
        for env in ({}, {X.EXIT_NONCE_VAR: ""}, {X.EXIT_NONCE_VAR: NONCE.upper()},
                    {X.EXIT_NONCE_VAR: NONCE[:-1]}, {X.EXIT_NONCE_VAR: NONCE + "0"},
                    {X.EXIT_NONCE_VAR: NONCE + "\n"}):
            code, out = self._attest(lambda: 2, env)
            self.assertEqual(code, 2)
            self.assertNotIn("HERMES-EXIT", out, env)

    def test_a_failing_stdout_is_not_attested(self):
        class Broken(io.StringIO):
            def write(self, s):
                if "HERMES-EXIT" in s:
                    raise BrokenPipeError(32, "Broken pipe")
                return super().write(s)
        out = Broken()
        with contextlib.redirect_stdout(out), self.assertRaises(BrokenPipeError):
            X._attested_exit(lambda: 2, environ={X.EXIT_NONCE_VAR: NONCE})
        self.assertNotIn("HERMES-EXIT", out.getvalue())

    def test_the_nonce_never_reaches_the_mutator(self):
        env = dict(FULL_CRED, **{X.EXIT_NONCE_VAR: NONCE})
        with mock.patch.dict(os.environ, env):
            self.assertNotIn(X.EXIT_NONCE_VAR, X._child_env())

    def test_control_the_child_env_probe_can_see_the_nonce(self):
        """Firing control for the test above, in memory — never by editing the file."""
        env = dict(FULL_CRED, **{X.EXIT_NONCE_VAR: NONCE})
        widened = X._RUNTIME_ENV_KEYS + (X.EXIT_NONCE_VAR,)
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(X, "_RUNTIME_ENV_KEYS", widened):
            self.assertIn(X.EXIT_NONCE_VAR, X._child_env())

    def test_control_an_early_line_is_caught(self):
        """Firing control: a variant that attests BEFORE main() finishes must fail the
        'last line' assertion the tests above rely on."""
        out = "HERMES-EXIT %s 2\nexecutor output\n" % NONCE
        with self.assertRaises(AssertionError):
            self._assert_attested_last(out, 2)

    def test_control_a_finally_variant_would_attest_a_crash(self):
        """Firing control: `finally: print(line)` attests a crash. Shows the crash test's
        assertion discriminates."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                try:
                    raise RuntimeError("boom")
                finally:
                    print("HERMES-EXIT %s 1" % NONCE)
            except RuntimeError:
                pass
        with self.assertRaises(AssertionError):
            self.assertNotIn("HERMES-EXIT", out.getvalue())

    def test_the_cli_attests_its_usage_exits(self):
        """The wire: the real __main__ goes through _attested_exit."""
        env = dict(os.environ, **{X.EXIT_NONCE_VAR: NONCE})
        for argv, rc in ((["--client", "acme-dental", "--changeset", "whatever",
                           "--request", "not-a-uuid"], 1),
                         ([], 2)):                                   # argparse: missing args
            r = subprocess.run([sys.executable, APPLY] + argv, capture_output=True,
                               text=True, env=env)
            self.assertEqual(r.returncode, rc, r.stderr)
            self._assert_attested_last(r.stdout, rc)

    def test_the_cli_without_a_nonce_prints_no_line(self):
        env = {k: v for k, v in os.environ.items() if k != X.EXIT_NONCE_VAR}
        r = subprocess.run([sys.executable, APPLY], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("HERMES-EXIT", r.stdout)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `infra/hermes-agent/bin`): `python3 apply-changeset.test.py TestAttestedExit -v`
Expected: FAIL/ERROR — `AttributeError: module 'apply_changeset' has no attribute '_attested_exit'` (and `EXIT_NONCE_VAR`); the two CLI tests fail on the missing line. The four `test_control_*` tests that do not touch new names may already pass — that is fine; they test the assertions, not the code.

- [ ] **Step 3: Implement**

In `apply-changeset.py`, after `_RUNTIME_ENV_KEYS` (`:50-52`), add:

```python

# F14 (spec 2026-09-23 §3.1). The wrapper's per-run nonce. The executor echoes it on its
# attested exit line; the wrapper trusts 0/1/2/3 only when that line matches. It must NEVER
# be added to _RUNTIME_ENV_KEYS: _child_env() is an allow-list precisely so the mutator —
# whose stderr is echoed into _refuse messages — cannot learn the nonce and forge the line.
EXIT_NONCE_VAR = "HERMES_EXIT_NONCE"
_EXIT_NONCE_RE = re.compile(r"[0-9a-f]{32}")
```

Before `def main(argv=None):` (`:402`), add:

```python
def _chosen_status(code):
    """The int status for a CHOSEN exit, or None when it was not one. bool is excluded
    (SystemExit(True) is not a status anyone chose); None means 0, as sys.exit does."""
    if code is None:
        return 0
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    return None


def _attested_exit(main_fn, environ=None):
    """F14. Run main_fn and exit with its status. For an exit the executor CHOSE (a
    returned int, or SystemExit with an int/None code) print `HERMES-EXIT <nonce> <rc>` as
    the last stdout line first. A crash — any other exception, KeyboardInterrupt, a
    non-int SystemExit — propagates unattested, so the wrapper cannot read it as "usage,
    nothing mutated". No valid nonce: no line (a manual in-container run is unchanged)."""
    environ = os.environ if environ is None else environ
    try:
        returned = main_fn()
    except SystemExit as e:
        rc = _chosen_status(e.code)
        if rc is None:
            raise
    else:
        # try/except/ELSE, not a SystemExit raised inside the try: that would be re-caught
        # by the except above and attested as a chosen status.
        rc = _chosen_status(returned)
        if rc is None:
            raise SystemExit(returned)
    nonce = environ.get(EXIT_NONCE_VAR, "")
    if _EXIT_NONCE_RE.fullmatch(nonce):
        sys.stderr.flush()
        sys.stdout.write("HERMES-EXIT %s %d\n" % (nonce, rc))
        sys.stdout.flush()
    raise SystemExit(rc)
```

Replace `:435-436`:

```python
if __name__ == "__main__":
    _attested_exit(main)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 apply-changeset.test.py -v 2>&1 | tail -5`
Expected: `OK` — the whole file, not only the new class (the existing CLI tests at `:791`, `:823` run through the new `__main__`).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py
git commit -m "$(printf 'fix(hermes): F14 — the executor attests the exits it chose\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 2: The wrapper verifies the attestation; everything else is 4

**Files:**
- Modify: `infra/hermes-agent/run-ads-mutate.sh` (nonce before `tmp_out` at `:82`; `-e HERMES_EXIT_NONCE` in the compose line `:92-96`; post-Compose block `:97-130`; header comment)
- Test: `infra/hermes-agent/bin/run-ads-mutate.test.py` (`FAKE_DOCKER` at `:72-79`; `Base._fake_docker`/`_run` at `:141-161`; new classes)

**Interfaces:**
- Consumes: Task 1's line format `HERMES-EXIT <nonce> <rc>` and `HERMES_EXIT_NONCE`.
- Produces: wrapper exit statuses 0/1/2/3 (attested) and 4 (unverified), banner `EXECUTOR EXIT NOT VERIFIED`.

- [ ] **Step 1: Teach the fake `docker` to attest, and keep the existing tests meaning what they meant**

In `run-ads-mutate.test.py`, replace `FAKE_DOCKER` (`:72-79`) with:

```python
FAKE_DOCKER = """#!/bin/sh
# Stands in for the real `docker`. Emits what the executor would have printed and
# exits with the status this test asked for. It NEVER creates a container.
# /bin/cat, not cat: a test puts a failing `cat` first on PATH to prove the WRAPPER's
# own post-Compose `cat` cannot decide its status (F14).
printf '%%s\n' "$@" > "$(dirname "$0")/docker.argv"
printf '%%s\n' "${HERMES_EXIT_NONCE-<unset>}" >> "$(dirname "$0")/docker.nonces"
/bin/cat <<'HERMES_FAKE_DOCKER_EOF'
HERMES-RESULT-JSON %(payload)s
HERMES_FAKE_DOCKER_EOF
%(attest)s
exit %(rc)s
"""

_SAME = object()
FORGED_NONCE = "fedcba9876543210fedcba9876543210"
```

Replace `_fake_docker` and `_run` (`:141-161`) with:

```python
    def _fake_docker(self, rc=0, attest_rc=_SAME, attest_times=1, extra=""):
        """attest_rc: the status the fake EXECUTOR attests (default: the same as rc; None:
        no line — Compose's own failure). extra: one more raw shell line (a forgery)."""
        if attest_rc is _SAME:
            attest_rc = rc
        lines = []
        if attest_rc is not None:
            lines = ["printf 'HERMES-EXIT %%s %d\\n' \"$HERMES_EXIT_NONCE\"" % attest_rc] \
                * attest_times
        if extra:
            lines.append(extra)
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as f:
            f.write(FAKE_DOCKER % {"payload": json.dumps(RESULT), "rc": rc,
                                   "attest": "\n".join(lines)})
        os.chmod(p, 0o755)

    def _run(self, executor_rc=0, **fake):
        self._fake_docker(executor_rc, **fake)
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["HERMES_GOVERNANCE_DIR"] = self.gov
        # F9: compose-only interpolation inputs. The wrapper never lets Compose read .env
        # (--env-file /dev/null), so they must come from the environment, as on the VPS.
        env["HERMES_AGENT_DIR"] = self.home
        env["HERMES_ADS_REPO_DIR"] = os.path.join(self.tmp, "ads-repo")
        env["HERMES_SPOOL_DIR"] = os.path.join(self.tmp, "spool")
        env.pop("VAULT_ROOT", None)          # hostenv.sh owns it; see the class docstring
        env.pop("HERMES_EXIT_NONCE", None)   # the wrapper must generate its own
        p = subprocess.run(
            ["/bin/sh", self.wrapper, "--client", SLUG, "--changeset", CID],
            capture_output=True, text=True, env=env, timeout=120)
        return p

    def _patch_wrapper(self, old, new):
        """Firing controls edit the fixture's TEMP COPY of the wrapper, never the tracked
        file. `old` must occur exactly once, so a control cannot silently patch nothing."""
        with open(self.wrapper) as f:
            text = f.read()
        self.assertEqual(text.count(old), 1, "control anchor %r not found once" % old)
        with open(self.wrapper, "w") as f:
            f.write(text.replace(old, new))

    def _nonces(self):
        with open(os.path.join(self.bin, "docker.nonces")) as f:
            return f.read().splitlines()
```

- [ ] **Step 2: Write the failing F14 tests**

Append before `if __name__ == "__main__":`:

```python
class TestTheExitIsAttested(Base):
    """F14 (spec 2026-09-23 §3.2). The wrapper passes Compose's status through ONLY when
    exactly one `HERMES-EXIT <nonce> <rc>` line proves the executor chose it. Anything
    else is 4: "the executor may have run; possibly modified"."""

    def test_an_attested_status_passes_through(self):
        for rc in (0, 1, 2, 3):
            p = self._run(executor_rc=rc)
            self.assertEqual(p.returncode, rc, p.stderr)
            self.assertNotIn("EXECUTOR EXIT NOT VERIFIED", p.stderr)

    def test_an_unattested_2_is_not_verified(self):
        p = self._run(executor_rc=2, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=2)", p.stderr)
        self.assertIn("possibly modified", p.stderr)

    def test_compose_failing_with_1_is_not_verified(self):
        """THE F14 CASE: Compose exits 1 on its own (a refused create, a lost connection);
        no executor line exists."""
        p = self._run(executor_rc=1, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", p.stderr)

    def test_a_forged_line_with_the_wrong_nonce_is_not_verified(self):
        p = self._run(executor_rc=2, attest_rc=None,
                      extra="echo 'HERMES-EXIT %s 2'" % FORGED_NONCE)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_line_disagreeing_with_rc_is_not_verified(self):
        p = self._run(executor_rc=0, attest_rc=2)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_second_nonce_line_with_another_rc_is_not_verified(self):
        p = self._run(executor_rc=2,
                      extra="printf 'HERMES-EXIT %s 0\\n' \"$HERMES_EXIT_NONCE\"")
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_two_matching_lines_are_not_verified(self):
        p = self._run(executor_rc=2, attest_times=2)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_an_unknown_status_is_not_verified(self):
        p = self._run(executor_rc=137, attest_rc=None)
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_a_failing_cat_after_compose_cannot_decide_the_status(self):
        cat = os.path.join(self.bin, "cat")
        with open(cat, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(cat, 0o755)
        p = self._run(executor_rc=2)
        self.assertEqual(p.returncode, 2, p.stderr)

    def test_the_nonce_is_passed_and_fresh_per_run(self):
        self._run(executor_rc=0)
        self._run(executor_rc=0)
        nonces = self._nonces()
        self.assertEqual(len(nonces), 2, nonces)
        for n in nonces:
            self.assertRegex(n, r"^[0-9a-f]{32}$")
        self.assertNotEqual(nonces[0], nonces[1])
        argv = open(os.path.join(self.bin, "docker.argv")).read().splitlines()
        i = argv.index("HERMES_EXIT_NONCE")
        self.assertEqual(argv[i - 1], "-e")
        self.assertLess(i, argv.index("ads-mutator"))

    def test_no_nonce_means_no_run(self):
        """Nonce generation failing must refuse BEFORE Compose — never run unattestable."""
        od = os.path.join(self.bin, "od")
        with open(od, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(od, 0o755)
        p = self._run(executor_rc=0)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("exit nonce", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.bin, "docker.argv")),
                         "Compose ran without a nonce")


class TestAttestationFiringControls(Base):
    """Each control breaks the fixture's TEMP COPY of the wrapper the way a regression
    would, and shows the matching test above would have caught it."""

    def test_control_a_wrapper_that_trusts_rc_passes_an_unattested_2(self):
        self._patch_wrapper("final=4  # F14", "final=$rc  # F14")
        p = self._run(executor_rc=2, attest_rc=None)
        self.assertEqual(p.returncode, 2, "control did not fire:\n" + p.stderr)

    def test_control_set_e_after_compose_lets_cat_decide(self):
        self._patch_wrapper("set +e  # F14", "set -e  # F14")
        cat = os.path.join(self.bin, "cat")
        with open(cat, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(cat, 0o755)
        p = self._run(executor_rc=2)
        self.assertEqual(p.returncode, 1, "control did not fire:\n" + p.stderr)
```

- [ ] **Step 3: Run to verify the new tests fail and the old ones now fail too**

Run (from `infra/hermes-agent/bin`): `python3 run-ads-mutate.test.py -v 2>&1 | tail -30`
Expected: `TestTheExitIsAttested` fails (unattested cases return 2/1/0/137, `docker.nonces` holds `<unset>`, the od test runs Compose); both controls ERROR with `control anchor ... not found once`. Existing tests still pass (the extra line is harmless to today's wrapper).

- [ ] **Step 4: Implement in `run-ads-mutate.sh`**

(a) Directly before `# The executor runs in the one-shot ads-mutator container` (`:77`), insert:

```sh
# F14 (spec 2026-09-23 §3.2): a fresh per-run nonce. The executor echoes it on its
# attested exit line, and the status below is trusted only when that line matches.
# Failing to make one is refused HERE, before anything runs: an unattestable run would
# always end as 4 anyway, and exit 1 before Compose is still an honest "nothing ran".
nonce=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n') || nonce=""
case "$nonce" in
  *[!0-9a-f]*) nonce="" ;;
esac
if [ "${#nonce}" -ne 32 ]; then
  echo "run-ads-mutate: could not generate the exit nonce — refusing before anything runs" >&2
  exit 1
fi
export HERMES_EXIT_NONCE="$nonce"
```

(b) In the compose invocation, change the line `-e GOOGLE_ADS_CREDENTIAL_ROLE \` to:

```sh
  -e GOOGLE_ADS_CREDENTIAL_ROLE -e HERMES_EXIT_NONCE \
```

(c) Replace the single line `cat "$tmp_out"` (`:98`) with:

```sh
# F14: from here on NOTHING may end this script except the single `exit "$final"` at the
# bottom. Under `set -e` a failing `cat` (or grep, or anything) would exit with ITS status
# — 1, which the broker reads as "nothing was mutated" — about a run that may have applied.
set +e  # F14
cat "$tmp_out"
# Trust Compose's status only when the executor attested it: exactly one line
# `HERMES-EXIT <nonce> <rc>` for THIS run's nonce, and no other line for this nonce.
# Anything else — Compose's own failure (possibly after the container started), a
# killed container, a forged or disagreeing line, an unreadable file — is 4.
final=4  # F14: unverified until the attestation below proves otherwise
case "$rc" in
  0|1|2|3)
    exact=$(grep -Fxc "HERMES-EXIT $nonce $rc" "$tmp_out" 2>/dev/null)
    any=$(grep -c "^HERMES-EXIT $nonce " "$tmp_out" 2>/dev/null)
    if [ "$exact" = "1" ] && [ "$any" = "1" ]; then
      final=$rc
    fi
    ;;
esac
if [ "$final" -eq 4 ]; then
  echo "" >&2
  echo "!!! ================================================================" >&2
  echo "!!! EXECUTOR EXIT NOT VERIFIED (compose rc=$rc) — the executor may have" >&2
  echo "!!! run; treat the account as possibly modified; reconcile from the" >&2
  echo "!!! governance audit log before doing anything else with this client." >&2
  echo "!!! ================================================================" >&2
  echo "" >&2
fi
```

(d) In the persist banner, change `echo "!!! The executor's own status ($rc) is UNCHANGED and is still what says" >&2` to use `$final`:

```sh
  echo "!!! The executor's own status ($final) is UNCHANGED and is still what says" >&2
```

and change the last line `exit "$rc"` to:

```sh
exit "$final"
```

(e) In the header comment, after the paragraph ending `...two files are deliberately separate so the read path keeps its platform-level backstop.`, add:

```sh
#
# Exit status (F14): 0/1/2/3 are the EXECUTOR's, passed through only when it attested
# them (`HERMES-EXIT <nonce> <rc>`); 1 is also this script's own refusals before Compose.
# 4 = the executor's exit could not be verified — treat the account as possibly modified.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 run-ads-mutate.test.py -v 2>&1 | tail -8`
Expected: `OK`, including `TestControlsFirst`, `TestPersistRefusalIsLoud`, `TestComposeNeverReadsEnv`, both control tests. Then `sh -n ../run-ads-mutate.sh` → no output.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/run-ads-mutate.sh infra/hermes-agent/bin/run-ads-mutate.test.py
git commit -m "$(printf 'fix(hermes): F14 — the wrapper trusts only an attested exit; else 4\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 3: Broker and Hermes client map 4 to "possibly modified"

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-broker.py:510-535` (comment, `CLASSIFICATION_BY_RC`, `DETAIL_BY_CLASSIFICATION`)
- Modify: `infra/hermes-agent/bin/hermes-syscall.py:27-29` (`_EXIT_BY_CODE` + comment)
- Test: `infra/hermes-agent/bin/hermes-broker.test.py:810-821` (`TestExecution.test_exit_codes_are_not_collapsed`), new test in `TestExecution`
- Test: `infra/hermes-agent/bin/hermes-syscall.test.py:209-219` (`TestResult`), new test
- Test: `infra/hermes-agent/bin/run-ads-mutate.test.py` (new seam class)

**Interfaces:**
- Consumes: wrapper status 4 (Task 2).
- Produces: `CLASSIFICATION_BY_RC[4] == ("failed_unverified_exit", "failed")`; `_EXIT_BY_CODE[4] == EXIT_FAILED_AFTER_MUTATION`.

- [ ] **Step 1: Write the failing tests**

`hermes-broker.test.py`, in `test_exit_codes_are_not_collapsed`, extend `cases`:

```python
        cases = {0: ("accepted_applied", "applied"),
                 1: ("refused_usage", "refused"),
                 2: ("refused_preflight", "refused"),
                 3: ("failed_after_mutation", "failed"),
                 4: ("failed_unverified_exit", "failed")}
```

and add to `TestExecution`, right after that test:

```python
    def test_an_unverified_exit_is_possibly_modified_never_nothing_mutated(self):
        """F14. Wrapper status 4: the executor's exit could not be verified. The detail
        must say "possibly modified" and must never carry the refusal promise."""
        rid = self.file_request()
        self.drain(RecordingRunner(rc=4))
        got = self.result_for(rid)
        self.assertEqual(got["classification"], "failed_unverified_exit")
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["exit_code"], 4)
        self.assertIn("possibly modified", got["detail"])
        self.assertNotIn("nothing was mutated", got["detail"])
```

`hermes-syscall.test.py`, in `test_control_the_real_integer_codes_still_map`, extend the tuple:

```python
        for code, expected in ((0, K.EXIT_OK), (2, K.EXIT_REFUSED),
                               (3, K.EXIT_FAILED_AFTER_MUTATION),
                               (4, K.EXIT_FAILED_AFTER_MUTATION)):
```

and add to `TestResult`:

```python
    def test_an_unverified_exit_reaches_the_agent_as_possibly_modified(self):
        """F14. Broker exit_code 4 must not fall through to the EXIT_REFUSED default:
        that tells the agent "refused" about a run that may have changed the account."""
        self._result({"request_id": self.RID, "status": "failed",
                      "classification": "failed_unverified_exit",
                      "exit_code": 4, "finished_at": "2026-08-24T10:15:00Z"})
        rc, out, _ = self.run_cli(["result", "--request-id", self.RID])
        self.assertEqual(rc, K.EXIT_FAILED_AFTER_MUTATION)
        self.assertNotEqual(rc, K.EXIT_REFUSED)
        self.assertIn("failed_unverified_exit", out)
```

`run-ads-mutate.test.py` — the seam, wrapper → broker → client, with the real maps. After `PF = _load(...)` add:

```python
B = _load("hermes_broker", "hermes-broker.py")
K = _load("hermes_syscall", "hermes-syscall.py")
```

and before `if __name__ == "__main__":`:

```python
class TestTheF14ChainEndToEnd(Base):
    """F14 on the laptop, across the real seam: a Compose failure with no executor line
    becomes wrapper 4 → broker failed_unverified_exit → agent EXIT_FAILED_AFTER_MUTATION.
    Nowhere on the chain may it read as "nothing was mutated"."""

    def test_a_compose_failure_is_possibly_modified_all_the_way_to_the_agent(self):
        p = self._run(executor_rc=1, attest_rc=None)
        classification, status = B.CLASSIFICATION_BY_RC.get(p.returncode, B.UNKNOWN_RC)
        self.assertEqual((classification, status), ("failed_unverified_exit", "failed"))
        self.assertNotIn("nothing was mutated", B.DETAIL_BY_CLASSIFICATION[classification])
        self.assertEqual(K._EXIT_BY_CODE.get(p.returncode), K.EXIT_FAILED_AFTER_MUTATION)

    def test_control_an_attested_usage_exit_is_still_a_refusal(self):
        """Discriminating control: an attested 1 must still read as refused_usage, or the
        test above would pass against a chain that turned everything into a failure."""
        p = self._run(executor_rc=1)
        self.assertEqual(B.CLASSIFICATION_BY_RC[p.returncode][0], "refused_usage")
```

- [ ] **Step 2: Run to verify they fail**

Run (from `infra/hermes-agent/bin`):
`python3 hermes-broker.test.py TestExecution -v 2>&1 | tail -6; python3 hermes-syscall.test.py TestResult -v 2>&1 | tail -6; python3 run-ads-mutate.test.py TestTheF14ChainEndToEnd -v 2>&1 | tail -6`
Expected: broker — rc 4 gives `failed_unknown_exit`; syscall — 4 gives `EXIT_REFUSED` (2); seam — `('failed_unknown_exit', 'failed') != ('failed_unverified_exit', 'failed')`. The seam control passes.

- [ ] **Step 3: Implement**

`hermes-broker.py` — replace the comment and both maps (`:510-535`):

```python
# Exit semantics are load-bearing and must not be collapsed (spec §12):
#   0 success · 1 usage · 2 pre-flight refusal (NOTHING was mutated) · 3 failure after
#   at least one live mutation landed · 4 (F14) the executor's exit could not be
#   verified — run-ads-mutate.sh passes 0-3 through only when the executor attested
#   them, so 4 covers Compose's own failures, including one after the container started.
# An unrecognised code is treated as a FAILURE, never as a success: the only safe
# reading of "the executor did something we do not understand" is that it may have
# touched the account.
CLASSIFICATION_BY_RC = {
    0: ("accepted_applied", "applied"),
    1: ("refused_usage", "refused"),
    2: ("refused_preflight", "refused"),
    3: ("failed_after_mutation", "failed"),
    4: ("failed_unverified_exit", "failed"),
}
```

and in `DETAIL_BY_CLASSIFICATION`, after the `"failed_unknown_exit"` entry, add:

```python
    "failed_unverified_exit": "the executor's exit could not be verified (e.g. Compose "
                              "failed, possibly after the container started); treat the "
                              "account as possibly modified and reconcile from the audit log",
```

`hermes-syscall.py` — replace `:29`:

```python
# Keys are the BROKER's exit_code values, not this client's own exit statuses: the
# broker's 4 (F14, "exit could not be verified") and this client's EXIT_PENDING = 4 are
# different namespaces, and this map is the translation. 4 is "possibly modified", never
# the EXIT_REFUSED default.
_EXIT_BY_CODE = {0: EXIT_OK, 2: EXIT_REFUSED, 3: EXIT_FAILED_AFTER_MUTATION,
                 4: EXIT_FAILED_AFTER_MUTATION}
```

- [ ] **Step 4: Run to verify they pass, then every suite**

Run: `python3 hermes-broker.test.py 2>&1 | tail -3; python3 hermes-syscall.test.py 2>&1 | tail -3; python3 run-ads-mutate.test.py 2>&1 | tail -3`
Expected: three `OK`s.
Then from the repo root: `infra/hermes-agent/bin/run-bin-tests.sh 2>&1 | tail -2` → `hermes bin: 31/31 suites passed`; `node scripts/run-all-tests.js 2>&1 | tail -1` → `22/22 suites passed`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-broker.py infra/hermes-agent/bin/hermes-syscall.py \
  infra/hermes-agent/bin/hermes-broker.test.py infra/hermes-agent/bin/hermes-syscall.test.py \
  infra/hermes-agent/bin/run-ads-mutate.test.py
git commit -m "$(printf 'fix(hermes): F14 — broker and client read status 4 as possibly modified\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 4: Measure it on real Linux

**Files:**
- Modify: `infra/hermes-agent/deploy/bind-agreement-integration.test.py:251-256` (broker-path test), `:276-296` (both firing controls)

**Interfaces:**
- Consumes: the whole chain (Tasks 1–3) running through the real proxy, the real image and the real executor on CI.

This file cannot execute on darwin (it needs root, Linux and Docker); `why_not_runnable()` skips it locally. Its proof is the required CI job.

- [ ] **Step 1: Strengthen the assertions**

Add at module level after `CREATE_DENIED` (`:56`):

```python
# F14: the real executor's attested exit line, nonce-bound (spec 2026-09-23 §3.1).
ATTESTED_2 = re.compile(r"^HERMES-EXIT [0-9a-f]{32} 2$", re.MULTILINE)
```

In `test_the_broker_path_reaches_the_executor_and_the_kill_switch_refuses`, after `self.assertIn("mutation is disabled", out)`, add:

```python
        # F14: the nonce crossed `docker compose run -e` and the real proxy, and the real
        # executor attested its own refusal — the 2 above is PROVEN, not inferred.
        self.assertEqual(len(ATTESTED_2.findall(out)), 1, out)
        self.assertNotIn("EXECUTOR EXIT NOT VERIFIED", out)
```

In `test_one_altered_allow_bind_is_refused`, replace the `assertNotEqual(r.returncode, 2, ...)` statement with:

```python
        # F14, MEASURED: the proxy refused the create, so Compose exited 1 on its own and
        # no executor ever ran to attest anything. The wrapper must say "unverified" (4),
        # never "nothing was mutated" (1) and never the executor's own refusal (2).
        self.assertEqual(r.returncode, 4, out)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", out)
```

In `test_one_wrong_path_in_the_broker_environment_is_refused`, replace `self.assertNotEqual(r.returncode, 2, out)` with:

```python
        self.assertEqual(r.returncode, 4, out)
        self.assertIn("EXECUTOR EXIT NOT VERIFIED (compose rc=1)", out)
```

- [ ] **Step 2: Check syntax and the local skip**

Run (repo root): `python3 -m py_compile infra/hermes-agent/deploy/bind-agreement-integration.test.py && python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py 2>&1 | tail -2`
Expected: compiles; the run reports it is not runnable here (skipped), exit 0.

- [ ] **Step 3: Commit, push, open the PR**

```bash
git add infra/hermes-agent/deploy/bind-agreement-integration.test.py
git commit -m "$(printf 'test(hermes): F14 — measure the unverified exit on real Linux\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
git push -u origin spec/f14-attested-executor-exit
gh pr create --base main --title "fix(hermes): F14 — the executor attests its exit; unattested fails closed" --body "$(cat <<'BODY'
## Summary
F14: a Compose failure could be reported as "refused, nothing was mutated" about a run that may have changed the account.
- The executor prints `HERMES-EXIT <nonce> <rc>` for the exits it chose, never for a crash.
- `run-ads-mutate.sh` passes 0-3 through only on exactly one exact match for its per-run nonce; otherwise it exits **4**. `set +e` after Compose so no later command decides the status.
- The broker maps 4 to `failed_unverified_exit` ("possibly modified"); `hermes-syscall` maps it to `EXIT_FAILED_AFTER_MUTATION`, not the refused default.
- Linux CI measures it: the proxy refusing the create now gives 4 (`compose rc=1`); the broker path's real refusal is attested.

Spec: `docs/superpowers/specs/2026-09-23-f14-attested-executor-exit-design.md`. Mutation disabled; kill switch absent; proxy allow-list unchanged.

## Test plan
- [x] apply-changeset, run-ads-mutate, hermes-broker, hermes-syscall suites (darwin)
- [x] hermes bin 31/31, node 22/22
- [ ] CI: bind-agreement executed 6 skipped 0, layout-integration executed 30 skipped 0 — on the PR and on the merge commit

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

- [ ] **Step 4: Read CI on the PR — counts, not colours**

Run: `gh pr checks <PR> --watch`, then
`gh run view <run-id> --log | grep -oE "(bind-agreement|layout-integration): executed [0-9]+, skipped [0-9]+|[0-9]+/[0-9]+ suites passed" | sort -u`
Expected: `bind-agreement: executed 6, skipped 0` · `layout-integration: executed 30, skipped 0` · `22/22` · `31/31`.
If bind-agreement fails, read the failing assertion's `out` before changing anything: a 1 or 2 where 4 was expected is a real F14 finding, not a test to loosen.

---

### Task 5: Records

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (`:256`, F14 section `:267-277`, open items `:350`)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md:449-451`
- Modify: `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` §12

- [ ] **Step 1: Findings record**

Retitle `### F14: a Compose failure is reported as "refused, nothing was mutated" (recorded, not fixed)` to `### F14: a Compose failure is reported as "refused, nothing was mutated" — fixed (PR #<n>)` and append to the section:

```markdown
**Fix (PR #<n>, spec `2026-09-23-f14-attested-executor-exit-design.md`).** The executor prints
`HERMES-EXIT <nonce> <rc>` for the exits it chose, bound to a per-run nonce the wrapper
generates; `run-ads-mutate.sh` passes 0–3 through only on exactly one exact match and
otherwise exits **4**, which the broker records as `failed_unverified_exit` ("possibly
modified") and the Hermes client returns as `EXIT_FAILED_AFTER_MUTATION`. Pre-start Compose
failures are now false alarms by decision. **Measured on Linux CI** (run <id>): the proxy
refusing the create gives wrapper status 4 with `compose rc=1`; the broker path's real refusal
is attested (`bind-agreement: executed 6, skipped 0`). **Still unmeasured:** an actual
connection loss after the container started — the fix does not depend on it.
```

Fill `<n>` and `<id>` **only from the real PR number and CI run** (Task 4 Step 4). In `:256` and the open-items list (`:350`), mark F14 fixed with the PR number.

- [ ] **Step 2: BRING-UP**

Replace the paragraph at `:449-451` (`**Still required before the kill switch can be created:** F14 (...), and the §6 hardening gates.`) with:

```markdown
**Still required before the kill switch can be created:** the §6 hardening gates. (F14 —
a Compose failure reported as "nothing was mutated" — is fixed: an unverified executor exit is
now status 4, "possibly modified".)
```

- [ ] **Step 3: Syscall spec §12**

After the paragraph ending `...mutation landed.` in `## 12 · Failure semantics`, add:

```markdown
**Amended 2026-09-23 (F14).** `run-ads-mutate.sh` passes `0`–`3` through only when the executor
attested them on a nonce-bound `HERMES-EXIT <nonce> <rc>` line; any other outcome is wrapper
status `4`, recorded as `failed_unverified_exit` — possibly modified — and returned by
`hermes-syscall` as its failed-after-mutation status, never as a refusal.
```

- [ ] **Step 4: Commit and push**

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md \
  infra/hermes-agent/deploy/BRING-UP.md docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md
git commit -m "$(printf 'docs(hermes): F14 — record the fix and the Linux CI measurement\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
git push
```

Re-read CI counts on the new head (Task 4 Step 4 command).

- [ ] **Step 5: Brain candidate (left unpromoted)**

Use the `brain-capture` skill to record a `[decision]` entry: "F14 fixed (PR #<n>): the executor attests its exit; unattested exits are status 4, possibly modified; measured on Linux CI run <id>." Do **not** stage anything under `.project-brain/`; the operator promotes and stages.

- [ ] **Step 6: After the operator merges — the merge commit**

```bash
git checkout main && git pull --ff-only
gh run list --branch main --limit 1
gh run view <merge-run-id> --log | grep -oE "(bind-agreement|layout-integration): executed [0-9]+, skipped [0-9]+|[0-9]+/[0-9]+ suites passed" | sort -u
```

Expected: the same four counts as on the PR.
