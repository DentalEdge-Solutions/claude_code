# Review #6 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the follow-ups left open by security review #6 as one batched change: fix the deferred collector and probe defects, bring the dashboard password and the non-Google keys into the credential inventory, fix two runbook lines and one stale README paragraph, and record the 16 findings in the findings doc.

**Architecture:** Small, independent fixes in three Python files (`client_audit_lib.py`, `run-client-audit.py`, `collect-review-evidence.py`), each with tests in the matching `*.test.py`. One documentation task then moves `CHECKLIST.md` to v1.15 so it describes the new evidence fields, and a last task records the findings. Nothing changes what an audit does; only what the review measures and how the runbook cleans up.

**Tech Stack:** Python 3 standard library only, `unittest`. Tests run with `infra/hermes-agent/bin/run-bin-tests.sh`.

**Spec:** There is no separate design spec. The requirements are `docs/superpowers/handoffs/2026-10-02-option-b-live-review-6-pass.md` ("Open follow-ups", items 1, 2 and 4 to 9) and `docs/security-reviews/2026-10-02-review-6.md` ("Not on the checklist", entries 2 and 7). Item 3 (revoking the retired token) is an operator action at Google and is out of scope. Item 7 (widening D10.6's top-level rule) is deliberately **not** done: the rule fails closed, no real config needs it widened, and it is recorded as accepted in Task 6.

## Global Constraints

- Work only inside this worktree: `/Users/ericksicard/Projects/claude_code/.claude/worktrees/review-6-follow-ups`. Never `cd` to the main checkout.
- Python standard library only. No new dependency, no new file under `bin/` or `deploy/` (every change is an edit to an existing file).
- Run `infra/hermes-agent/bin/run-bin-tests.sh` before each commit. Every suite must pass (the baseline is 54 of 54).
- **Secrets and identifiers.** Never write a client name, a customer id, a hostname, a credential value, or any hash, sha12 or fingerprint taken from a review report or bundle into any file. Test fixtures use the obviously fake values already in the test files (`TOKEN`, `sk-or-v1-NOT-A-REAL-KEY-0123456789abcdef`, `sk-ant-api03-SECRETVALUE`) or new ones of the same kind. Client names are written `<client>`.
- **Nothing the collector prints may carry a secret value.** A new field holds labels, counts, booleans or a sha12, never a value.
- **Fail closed.** Something that could not be measured is `could-not-check` (`R.COULD_NOT_CHECK`), never a healthy-looking value.
- `infra/hermes-agent/deploy/security-review/CHECKLIST.md` is edited only in Task 5, and that task raises `version:` from `1.14` to `1.15`.
- Do not touch anything under `.project-brain/`.
- Commits: stage the exact files the task names (`git add <paths>`, never `-A` or `.`). Commit locally only. **No push and no pull request.** End every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Match the surrounding code: dense Python, lines up to about 110 characters, a short comment that says why, not what. No type hints (the files have none).

## Review Focus

Conditions the follow-up list implies but does not spell out, most likely to bite first. Each has a test in the task named.

1. **A healthy box must not fail a new rule.** The dashboard is off by default, so a gateway `.env` with no dashboard password is normal: `secrets_held` is then `["openrouter-key"]` and nothing is a FAIL (Task 4, test 2). The probe looks for the two credential files, not for the `/etc/hermes` directory, because a base image may ship a directory of that name (Task 2).
2. **The dashboard password must never reach the bundle, in any form.** Not its value and not a hash of it: its row carries `sha12: null` (Task 4, tests 1 and 4).
3. **A probe child that ignores SIGTERM must still end.** After the grace period the collector kills it and returns `124` (Task 3, test 2).
4. **`#` inside a value is not a comment.** `KEY=abc#def` keeps `abc#def`; only whitespace followed by `#` starts a comment (Task 1).
5. **`sudo -l` answering in an unexpected form** (another locale, an error, no output) is `could-not-check`, not "0 command lines" (Task 3, test 4).

---

### Task 1: `load_env_value` strips an inline comment

**Files:**
- Modify: `infra/hermes-agent/bin/client_audit_lib.py` (the function `load_env_value`, near line 171)
- Test: `infra/hermes-agent/bin/client_audit_lib.test.py` (class `TestOptionBHelpers`, near line 202)

**Interfaces:**
- Consumes: nothing.
- Produces: `load_env_value(path, name)` keeps its signature and its `None` for a missing name. Tasks 2 to 4 rely on it unchanged.

**Background.** `load_env_value` reads one `NAME=value` from an env file as data. Today `KEY=abc # note` returns `abc # note`. Its callers pass the result to a container as a key and add it to the collector's known-secret list, so a comment would break both silently. Do **not** change `load_cred_env` or `anthropic_key_state`.

- [ ] **Step 1: Write the failing test.** Add to `TestOptionBHelpers`:

```python
    def test_load_env_value_strips_an_inline_comment(self):
        cases = {"K=abc # note": "abc",                    # whitespace then # starts a comment
                 "K=abc\t# note": "abc",
                 "K=abc#def": "abc#def",                   # no whitespace before #: part of the value
                 "K= # only a comment": "",
                 'K="abc" # note': "abc",                  # a quoted value ends at its closing quote
                 "K='abc'   # note": "abc",
                 'K="a # b"': "a # b",                     # a # inside the quotes is kept
                 'K="a"b"': 'a"b',                         # unchanged from before: outer quotes stripped
                 'K="abc': '"abc',                         # unchanged from before: no closing quote
                 "export K=abc # note": "abc",
                 "K=abc": "abc"}
        for line, want in cases.items():
            with self.subTest(line=line):
                p = os.path.join(self.d, "e")
                with open(p, "w") as f:
                    f.write("OTHER=1\n" + line + "\r\n")
                self.assertEqual(L.load_env_value(p, "K"), want)
```

- [ ] **Step 2: Run it and see it fail.**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py -k inline_comment`
Expected: FAIL on the first sub-test, `'abc # note' != 'abc'`.

- [ ] **Step 3: Implement.** Replace `load_env_value` with:

```python
_COMMENT_RE = re.compile(r"\s+#.*")


def _env_value(v):
    """The value part of NAME=value. A quoted value ends at its closing quote when only a comment
    follows; otherwise one layer of matching outer quotes is stripped, as before. An unquoted value
    ends at the first whitespace that is followed by `#` (a `#` with nothing before it is data)."""
    if v[:1] in ("\"", "'"):
        end = v.find(v[0], 1)
        if end > 0 and _COMMENT_RE.fullmatch(v[end + 1:]):
            return v[1:end]
        return v[1:-1] if len(v) >= 2 and v[0] == v[-1] else v
    return _COMMENT_RE.sub("", v, count=1)


def load_env_value(path, name):
    """One NAME=value from an env file, parsed as DATA with load_cred_env's rules, plus an inline
    comment (see _env_value): the installed files have none today, but a hand edit must not turn a
    comment into part of a key."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if line.startswith(name + "="):
                return _env_value(line.split("=", 1)[1])
    return None
```

- [ ] **Step 4: Run the tests.**

Run: `python3 infra/hermes-agent/bin/client_audit_lib.test.py`
Expected: all pass, including the existing `test_load_env_value_parses_as_data`.

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite `OK`.

- [ ] **Step 5: Commit.**

```bash
git add infra/hermes-agent/bin/client_audit_lib.py infra/hermes-agent/bin/client_audit_lib.test.py
git commit -m "fix(hermes): load_env_value strips an inline comment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The probes report a mounted credential file and their own exit codes

**Files:**
- Modify: `infra/hermes-agent/bin/run-client-audit.py` (`_ENV_PROBE` near line 318, `probe_env` near 430, `_matches` near 458, `probe_egress` near 472)
- Test: `infra/hermes-agent/bin/run-client-audit.test.py` (`ENV_OK` near line 913, class `TestProbes`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Task 5 documents these names; use them exactly):
  - `probe_env`: each entry of `services` gains `"host_credential_files_visible": <bool>`.
  - `probe_egress`: the result gains `"proxy_rc": <int>` and `"drafter_rc": <int>`.

**Background.** `--probe-env` starts each audit container with sentinel credential values and looks for the sentinel in the environment and in mounted files. A real credential file mounted into a container holds no sentinel, so the probe cannot see it. `--probe-egress` starts the proxy and a drafter and ignores both exit codes.

**Part A: the env probe looks for the two host credential files.**

- [ ] **Step 1: Update the fixture and write the failing tests.** In `ENV_OK`, append `HOST_CRED_FILES=0\n` to each of the four services' output strings. Then add to `TestProbes`:

```python
    def test_probe_env_reports_a_host_credential_file_in_a_container(self):
        run, _ = self.fake_probe_runner(ENV_OK)
        j = RCA.probe_env(self.root, run)
        self.assertTrue(j["matches_declared"], j)
        self.assertEqual({s["host_credential_files_visible"] for s in j["services"].values()}, {False})
        R = ENV_OK["ads-reader"]
        cases = {"one file is there": R.replace("HOST_CRED_FILES=0", "HOST_CRED_FILES=1"),
                 "no HOST_CRED_FILES line": R.replace("HOST_CRED_FILES=0\n", ""),
                 "a line that is not a count": R.replace("HOST_CRED_FILES=0", "HOST_CRED_FILES=")}
        for why, out in cases.items():
            with self.subTest(why=why):
                run, _ = self.fake_probe_runner(dict(ENV_OK, **{"ads-reader": out}))
                j = RCA.probe_env(self.root, run)
                self.assertIs(j["services"]["ads-reader"]["host_credential_files_visible"], True)
                self.assertFalse(j["matches_declared"], j)

    def test_the_env_probe_script_tests_both_credential_files_and_no_directory(self):
        self.assertIn('for p in ' + RCA.CRED + ' ' + RCA.ANTHROPIC_CRED + ';', RCA._ENV_PROBE)
        self.assertIn('echo HOST_CRED_FILES=$c', RCA._ENV_PROBE)
```

- [ ] **Step 2: Run and see them fail.**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -k host_credential -k credential_files`
Expected: FAIL with `KeyError: 'host_credential_files_visible'` and an `AssertionError` on the script text.

- [ ] **Step 3: Implement.** Extend `_ENV_PROBE` (keep the three existing measurements; update the comment above it to say "Four measurements" and name the fourth):

```python
_ENV_PROBE = ("env | cut -d= -f1 | grep -E '^" + _CRED_SHAPED + "' | sort; "
              "env | grep -F " + SENTINEL + " | cut -d= -f1 | sed 's/^/SENTINEL_ENV=/'; "
              "n=$(grep -rlF " + SENTINEL + " /projects /work /opt/cc-bin /opt/skills /opt/registry 2>/dev/null | wc -l); "
              "echo SENTINEL_FILES=$n; "
              # A real credential file holds no sentinel: look for the host's two files by path. The
              # files, not /etc/hermes: an image may ship a directory of that name.
              "c=0; for p in " + CRED + " " + ANTHROPIC_CRED + "; do [ -e \"$p\" ] && c=$((c+1)); done; "
              "echo HOST_CRED_FILES=$c")
```

In `probe_env`, next to `clean`, add (fail closed: absent only when the container says exactly that):

```python
            no_host_file = any(re.fullmatch(r"HOST_CRED_FILES=0", l) for l in lines)
```

and add `"host_credential_files_visible": not no_host_file` to the `services[svc]` dict.

In `_matches`, change the first test to:

```python
    if s["rc"] != 0 or s["sentinel_in_files"] or s["host_credential_files_visible"]:
        return False
```

and add one sentence to its docstring: a host credential file visible in the container is never a match.

- [ ] **Step 4: Run the probe tests.**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -k probe`
Expected: all pass. If an existing test builds a service output by hand without the new line and now fails for that reason only, add `HOST_CRED_FILES=0\n` to that fixture; do not weaken the fail-closed rule.

**Part B: the egress probe keeps its two exit codes.**

- [ ] **Step 5: Write the failing test.** Add to `TestProbes`:

```python
    def test_probe_egress_a_failed_step_is_not_expected(self):
        # "ads-drafter" first: the drafter's argv must match it before "egress-proxy".
        outs = {"ads-drafter": EGRESS_OK, "egress-proxy": ""}
        run, _ = self.fake_probe_runner(outs)
        j = RCA.probe_egress(self.root, run)
        self.assertEqual((j["proxy_rc"], j["drafter_rc"], j["matches_expected"]), (0, 0, True))
        for svc, key in (("egress-proxy", "proxy_rc"), ("ads-drafter", "drafter_rc")):
            with self.subTest(failed=svc):
                run, _ = self.fake_probe_runner(outs, {svc: 125})
                j = RCA.probe_egress(self.root, run)
                self.assertEqual(j[key], 125)
                self.assertFalse(j["matches_expected"], j)      # every line was as expected; the code was not
```

In the existing `test_probe_egress_fails_closed`, add `"proxy_rc"` and `"drafter_rc"` to the expected key set.

- [ ] **Step 6: Run and see it fail.**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -k probe_egress`
Expected: FAIL with `KeyError: 'proxy_rc'` and the key-set mismatch.

- [ ] **Step 7: Implement.** In `probe_egress` replace the two `runner(...)` lines with:

```python
        proxy_rc, _ = runner(_compose(root) + ["up", "-d", "--no-deps", "egress-proxy"], env, 60)
        drafter_rc, out = runner(_override(clean, "ads-drafter", _EGRESS_PROBE), env, 120)
```

add `"proxy_rc": proxy_rc, "drafter_rc": drafter_rc` to `j`, and make `matches_expected` also require `proxy_rc == 0 and drafter_rc == 0`. Add a comment: a failed step used to show only as missing lines; its code is now evidence of its own.

- [ ] **Step 8: Run everything.**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py` then `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite `OK`. `collect-review-evidence.test.py` feeds the collector canned probe JSON and must be unaffected.

- [ ] **Step 9: Commit.**

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py
git commit -m "fix(hermes): probes report a mounted credential file and their own exit codes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The collector lets a timed-out probe clean up, and D10.3 keeps its other parts

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`_run_real` near line 110, `_sudo_rules` near 790, `d10_3` near 799)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Task 5 documents these):
  - `TERM_GRACE = 90` (module constant) and `_run_real(argv, timeout=60)` with the same return shape `(rc, stdout, stderr)`; a timeout still returns `124`.
  - `d10_3`: `sudo_rules` is `{"rc": <int>, "not_allowed": <bool>, "command_lines": <int>}` as today, or `{"rc": <int>, "not_allowed": "could-not-check", "command_lines": "could-not-check"}`. `broker_user_groups` is a list, or `"could-not-check"`.

**Background.** Three separate defects, all in the collector:
1. `_run_real` uses `subprocess.run(timeout=...)`, which kills the child with SIGKILL on a timeout. `run-client-audit` cleans up its containers and throwaway directories on SIGTERM, so a probe that hits the collector's 600 s limit leaves them behind.
2. `_sudo_rules` reports `not_allowed: false, command_lines: 0` when `sudo` did not run at all.
3. `d10_3` calls `_ok(["id", "-nG", APP_USER])`, so a missing app user turns the whole item into `could-not-check` and the reviewer loses the unit properties too.

- [ ] **Step 1: Write the failing tests.** Add a new class near the top-level test classes (it uses real child processes, no `FakeHost`):

```python
class TestRunReal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.marker = os.path.join(self.d, "cleaned")

    def _child(self, on_term):
        # The 2 s timeout the tests use is what gives the interpreter time to install the handler.
        return [sys.executable, "-c",
                "import signal, sys, time\n"
                f"def h(s, f):\n    {on_term}\n"
                "signal.signal(signal.SIGTERM, h)\n"
                "time.sleep(60)\n"]

    def test_a_timeout_sends_sigterm_and_waits_for_the_cleanup(self):
        argv = self._child(f"open({self.marker!r}, 'w').close(); sys.exit(143)")
        rc, out, err = CE._run_real(argv, timeout=2)
        self.assertEqual((rc, out), (124, ""))
        self.assertIn("timed out", err)
        self.assertTrue(os.path.exists(self.marker))            # the child's own cleanup ran

    def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(self):
        argv = self._child("pass")
        with mock.patch.object(CE, "TERM_GRACE", 1):
            rc, _, _ = CE._run_real(argv, timeout=2)
        self.assertEqual(rc, 124)

    def test_ordinary_results_are_unchanged(self):
        self.assertEqual(CE._run_real([sys.executable, "-c", "import sys; print('o'); print('e', file=sys.stderr); sys.exit(3)"]),
                         (3, "o\n", "e\n"))
        self.assertEqual(CE._run_real(["/nonexistent/binary-for-this-test"])[0], 127)
```

Add to the class that already holds the D10.3 tests (it defines `_units` and `_item`):

```python
    def test_d10_3_sudo_that_gave_neither_answer_is_could_not_check(self):
        self._units()
        for rc, out in ((127, ""), (1, "sudo: unknown user hermes-app-ads-audit\n"), (0, ""),
                        (0, "L'utilisateur hermes-app-ads-audit n'est pas autorisé\n")):
            with self.subTest(rc=rc, out=out):
                self.outputs[("sudo", "-l", "-U")] = (rc, out, "")
                it = self._item("D10.3")
                self.assertEqual(it["status"], R.OBSERVED)
                self.assertEqual(it["data"]["sudo_rules"],
                                 {"rc": rc, "not_allowed": R.COULD_NOT_CHECK, "command_lines": R.COULD_NOT_CHECK})

    def test_d10_3_a_missing_app_user_costs_only_the_groups(self):
        self._units()
        self.outputs[("id", "-nG")] = (1, "", "id: 'hermes-app-ads-audit': no such user\n")
        it = self._item("D10.3")
        self.assertEqual(it["status"], R.OBSERVED)
        self.assertEqual(it["data"]["broker_user_groups"], R.COULD_NOT_CHECK)
        self.assertEqual(it["data"]["broker_unit"]["User"], "hermes-app-ads-audit")
        self.assertEqual(it["data"]["runner_path_active"], "active")
        self.assertNotIn("no such user", json.dumps(it))
```

- [ ] **Step 2: Run and see them fail.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -k TestRunReal -k d10_3`
Expected: the marker test fails (`False is not true`), `TERM_GRACE` does not exist, the sudo test shows `not_allowed: False`, and the missing-user test shows `status: could-not-check`.

- [ ] **Step 3: Implement `_run_real`.** Add `import signal` is **not** needed (`Popen.terminate` sends SIGTERM). Add the constant below `PROBE_TIMEOUT`:

```python
# On a timeout the child gets SIGTERM and this long to clean up before SIGKILL: run-client-audit
# removes its probe containers and throwaway dirs on TERM (each cleanup command is bounded there).
TERM_GRACE = 90
```

and replace `_run_real`:

```python
def _run_real(argv, timeout=60):
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        p.terminate()                           # not kill(): the child's `finally` must get to run
        try:
            p.communicate(timeout=TERM_GRACE)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
        return 124, "", f"{argv[0]}: timed out"
    except BaseException:                       # as subprocess.run: never leave the child behind
        p.kill()
        p.wait()
        raise
```

- [ ] **Step 4: Implement the D10.3 changes.** Replace `_sudo_rules`:

```python
def _sudo_rules(host, user):
    """`sudo -l -U <user>` as shape only: its text names the host, and its rules are not ours to
    print. It has two answers, "is not allowed to run sudo" and "may run the following commands";
    with neither (sudo did not run, an unknown user, another locale) nothing was learned."""
    rc, out, _ = host.run(["sudo", "-l", "-U", user])
    lines = out.splitlines()
    grant = next((i for i, l in enumerate(lines) if "may run the following commands" in l), None)
    not_allowed = any("is not allowed to run sudo" in l for l in lines)
    if grant is None and not not_allowed:
        return {"rc": rc, "not_allowed": R.COULD_NOT_CHECK, "command_lines": R.COULD_NOT_CHECK}
    return {"rc": rc, "not_allowed": not_allowed,
            "command_lines": 0 if grant is None else sum(1 for l in lines[grant + 1:] if l.strip())}
```

In `d10_3`, read the groups before the `return` and use the variable in the dict:

```python
    # A missing app user is `id`'s non-zero exit: it costs this value, not the unit properties.
    rc, groups, _ = host.run(["id", "-nG", APP_USER])
    ...
            "broker_user_groups": groups.split() if rc == 0 else R.COULD_NOT_CHECK,
```

- [ ] **Step 5: Run the tests.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py` then `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite `OK`. The existing `test_d10_3_reports_units_groups_sudo_and_path` and `test_d10_3_sudo_text_never_reaches_the_bundle` must pass unchanged.

- [ ] **Step 6: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "fix(hermes): collector lets a timed-out probe clean up; D10.3 keeps its other parts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The dashboard password and the non-Google keys join the credential inventory

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (constants near line 56, `d2_1` near 388, `collect_with_secrets` near 1053, `_main` near 1123, the module docstring)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (the class that defines `GATEWAY_ENV`, `OPENROUTER` and `_gateway_env`, near line 565)

**Interfaces:**
- Consumes: `CAL.load_env_value` (Task 1; signature unchanged).
- Produces (Task 5 documents these):
  - `OTHER_SECRET_NAMES`, `UNFINGERPRINTED`, `other_credentials(host) -> (rows, secrets)`.
  - D2.1: every `authorised-other` row gains `"secrets_held": [<label>, ...]`, in the order of `OTHER_SECRET_NAMES`.
  - The bundle's `credentials` and the output of `--credentials-only`: the Google rows as today, followed by one row `{"label": <label>, "sha12": <12 hex or null>}` per non-Google secret installed.

**Background.** The gateway `.env` holds the OpenRouter key and, when the dashboard is switched on, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`. Today the collector loads only the OpenRouter key into the known-secret list, so the leak checks (D2.2, D2.3, D10.7) never look for the password, and the "authorised credential set" lists Google credentials only. The dashboard is **off by default**: a gateway `.env` without the password is healthy.

A password is never fingerprinted. A short hash of a value a person may have chosen can be guessed offline, and review reports are committed. The two API keys are long random strings and get the same `R.sha12` the Google values already get.

- [ ] **Step 1: Write the failing tests.** Add next to the existing `test_d2_1_openrouter_key_value_joins_the_secrets_and_never_the_bundle`:

```python
    DASH = "NOT-A-REAL-DASHBOARD-PASSWORD-0123"

    def test_d2_1_the_dashboard_password_joins_the_secrets_and_is_never_fingerprinted(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD=1\n"
                          f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        bundle, secrets = CE.collect_with_secrets(self.host(), self.KEY)
        self.assertIn(self.DASH, secrets)
        text = json.dumps(bundle)
        self.assertNotIn(self.DASH, text)
        self.assertNotIn(R.sha12(self.DASH), text)
        row = bundle["items"]["D2.1"]["data"]["files"][0]
        self.assertEqual(row["secrets_held"], ["openrouter-key", "dashboard-password"])
        self.assertEqual(bundle["credentials"], [{"label": "dashboard-password", "sha12": None},
                                                 {"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])

    def test_d2_1_a_gateway_env_with_the_dashboard_off_is_healthy(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")
        bundle = CE.collect(self.host(), self.KEY)
        self.assertEqual(bundle["items"]["D2.1"]["data"]["files"][0]["secrets_held"], ["openrouter-key"])
        self.assertEqual(bundle["credentials"], [{"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])

    def test_the_dashboard_password_is_a_known_secret_for_the_journal_counts(self):
        self._gateway_env(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        self.outputs[("journalctl", "-o")] = (0, f"basic auth failed for {self.DASH}\n", "")
        it = CE.collect(self.host(), self.KEY)["items"]["D2.3"]
        self.assertEqual(it["data"]["journal"]["known_secret_hits"], 1)

    def test_credentials_only_lists_the_non_google_secrets_and_no_value(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD={self.DASH}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()),
                         [{"label": "anthropic-key", "sha12": R.sha12("sk-ant-api03-SECRETVALUE")},
                          {"label": "dashboard-password", "sha12": None},
                          {"label": "openrouter-key", "sha12": R.sha12(self.OPENROUTER)}])
        for value in ("SECRETVALUE", self.OPENROUTER, self.DASH):
            self.assertNotIn(value, buf.getvalue())

    def test_an_authorised_file_that_cannot_be_read_is_never_an_empty_set(self):
        self._gateway_env(f"OPENROUTER_API_KEY={self.OPENROUTER}\n")

        def denied(path, name):
            raise PermissionError(path)
        with mock.patch.object(CE.CAL, "load_env_value", denied):
            with self.assertRaises(CE.CouldNotCheck) as cm:
                CE.other_credentials(self.host())
        self.assertNotIn(self.root, str(cm.exception))                 # the reason names the label, not a path
        self.assertEqual(CE.other_credentials(self.host())[1], [self.OPENROUTER])   # control: readable again
```

If `self._gateway_env` replaces the `find` output so that the Anthropic file is not swept in the fourth test, that is fine: `other_credentials` reads the two authorised paths directly and does not depend on the sweep.

- [ ] **Step 2: Run and see them fail.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -k dashboard -k non_google -k authorised_file`
Expected: FAIL (`KeyError: 'secrets_held'`, `credentials` is `[]`, `other_credentials` does not exist).

- [ ] **Step 3: Implement the table and the reader.** Below `AUTHORISED_OTHER`:

```python
# The secret values each authorised non-Google file may hold, as (env name, label). D2.1 names the
# labels a file holds (`secrets_held`), the values join the known secrets the leak checks look
# for, and each is a row of the authorised credential set (`credentials`, --credentials-only).
OTHER_SECRET_NAMES = {
    "/etc/hermes/.env.anthropic": (("ANTHROPIC_API_KEY", "anthropic-key"),),
    CHECKOUT + "/infra/hermes-agent/.env": (("OPENROUTER_API_KEY", "openrouter-key"),
                                            ("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "dashboard-password"))}
# Listed, never fingerprinted: a short hash of a value a person may have chosen can be guessed offline.
UNFINGERPRINTED = ("dashboard-password",)
```

Below `installed_credentials`:

```python
def _other_secrets(host, p):
    """[(label, value)] for each non-empty secret the authorised file `p` holds."""
    return [(label, v) for name, label in OTHER_SECRET_NAMES[p]
            for v in [CAL.load_env_value(host.path(p), name)] if v]


def other_credentials(host):
    """(rows, secrets) for the non-Google secrets installed: one {label, sha12} row each, sha12
    null for an UNFINGERPRINTED one. A file that is absent adds nothing (D2.1's pass rule names
    the missing row); one that is there and cannot be read is could-not-check, never "none"."""
    rows, secrets = [], []
    for p in sorted(OTHER_SECRET_NAMES):
        try:
            held = _other_secrets(host, p)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            raise CouldNotCheck(f"{AUTHORISED_OTHER[p]}: {type(e).__name__}")
        for label, v in held:
            rows.append({"label": label, "sha12": None if label in UNFINGERPRINTED else R.sha12(v)})
            secrets.append(v)
    return sorted(rows, key=R.canon), secrets
```

- [ ] **Step 4: Use them.** In `d2_1`, replace the body of the `elif p in AUTHORISED_OTHER:` branch with:

```python
                        row["kind"], row["label"] = "authorised-other", AUTHORISED_OTHER[p]
                        if p == "/etc/hermes/.env.anthropic":
                            row["anthropic_key_state"] = CAL.anthropic_key_state(host.path(p))
                        # The values are loaded only to join the known secrets (assert_no_secret,
                        # D2.2, D2.3, D10.7 look for them); the row names which, never a value.
                        held = _other_secrets(host, p)
                        row["secrets_held"] = [label for label, _ in held]
                        ctx.setdefault("secrets", []).extend(v for _, v in held)
```

In `collect_with_secrets`, inside the existing `try`:

```python
        other, other_secrets = other_credentials(host)
        creds, secrets = R.credential_set(infos) + other, secrets + other_secrets
```

(replacing the line `creds = R.credential_set(infos)`).

In `_main`, in the `--credentials-only` branch: call `other_credentials(host)` inside the existing `try` that guards `installed_credentials(host)` so a `CouldNotCheck` from it exits 2 with the same message, then `out = R.credential_set(infos) + other` and `secrets = secrets + other_secrets`, so `assert_no_secret` covers the new values.

Update the module docstring's first rule to read "a credential value (Google, Anthropic, OpenRouter or the dashboard password)".

- [ ] **Step 5: Run the tests.**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py` then `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite `OK`. The existing `test_d2_1_gateway_env_without_an_openrouter_key_adds_no_secret` and `test_d2_1_anthropic_key_value_joins_the_secrets` must pass unchanged.

- [ ] **Step 6: Commit.**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): dashboard password and non-Google keys join the credential inventory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Checklist v1.15, the report template, two runbook lines and the README paragraph

**Files:**
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`
- Modify: `infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md` (line 7)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (three lines)
- Modify: `infra/hermes-agent/README.md` (the paragraph that starts `**The box's one non-Google secret file.**`)
- Test: `infra/hermes-agent/bin/security-review-checklist.test.py` (existing; run, do not edit)

**Interfaces:**
- Consumes: the field names from Tasks 2 to 4, exactly: `host_credential_files_visible`, `proxy_rc`, `drafter_rc`, `secrets_held`, the `{label, sha12}` rows of `credentials`, `could-not-check` inside `sudo_rules` and as `broker_user_groups`, and the 90 s grace.
- Produces: nothing code relies on.

Every checklist item is one very long line. Make each edit with an exact, unique substring; do not re-wrap or reflow any line. Change nothing that is not listed here.

- [ ] **Step 1: The version and its note.** Change `version: 1.14` to `version: 1.15`. In the header paragraph, append this after the last existing `(v1.14: ...)` note, on the same line, separated by one space:

```
(v1.15: review #6's follow-ups. D2.1: each `authorised-other` row names the secrets it holds (`secrets_held`), the gateway `.env` may hold the dashboard password, and the bundle's `credentials` lists the non-Google secrets too. D10.1: `host_credential_files_visible`, and a probe that times out is sent SIGTERM and given 90 s to clean up. D10.2: `proxy_rc` and `drafter_rc`. D10.3: `sudo_rules` and `broker_user_groups` can each be `could-not-check` without losing the item. D10.7: the dashboard password is a known secret.)
```

- [ ] **Step 2: D2.1.** Four edits in the D2.1 item.

  1. In **expected**, replace `` `anthropic_key_state: real` (`dummy` and `missing` mean the audit cannot draft and are a FAIL); `` with `` `anthropic_key_state: real` (`dummy` and `missing` mean the audit cannot draft and are a FAIL), `secrets_held: ["anthropic-key"]`; ``.
  2. In **expected**, replace `` `mode 0o600`, holding the OpenRouter key (the collector reads the file's content to classify it and to load the key's value for the leak checks of D2.2, D2.3 and D10.7; the content is never reported. `` with:

```
`mode 0o600`, `secrets_held` exactly `["openrouter-key"]`, or `["openrouter-key", "dashboard-password"]` when the dashboard is switched on (BRING-UP Phase 7 writes `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` into this file; the dashboard is off by default, and the operator states in the report whether it is on) (the collector reads the file's content to classify it and to load the values `secrets_held` names for the leak checks of D2.2, D2.3 and D10.7; the content is never reported.
```

  3. In **expected**, immediately before `` `example` rows are templates. `` insert:

```
The bundle's top-level `credentials` is the authorised credential set, and `--credentials-only` prints the same list: the Google rows (`role`, `refresh_token_sha12`, `client_id_sha12`), then one row per non-Google secret installed (`label`, `sha12`): `anthropic-key` and `openrouter-key` each with a `sha12`, and `dashboard-password` with `sha12: null` when a password is set (a password is listed and never fingerprinted). A `credentials` row whose label is not one of those three, or a missing `anthropic-key` or `openrouter-key` row, is a FAIL. 
```

  4. In **pass rule**, replace `` A missing `anthropic-key` or `gateway-env` row is a FAIL. `` with `` A missing `anthropic-key` or `gateway-env` row is a FAIL, and so is a `secrets_held` other than stated above (a missing `anthropic-key` or `openrouter-key`, or a label not listed). A `dashboard-password` entry with no operator statement that the dashboard is on is CANNOT-VERIFY. ``

- [ ] **Step 3: D10.1.** Three edits.

  1. In **expected**, replace `` each with `rc 0` and `sentinel_in_files: false`: `` with `` each with `rc 0`, `sentinel_in_files: false` and `host_credential_files_visible: false` (neither `/etc/hermes/.env.ga` nor `/etc/hermes/.env.anthropic` exists inside the container: a real credential file holds no sentinel, so the sentinel scan cannot see one that was mounted, and this does; the key is `true` unless the container printed that it found neither): ``
  2. In **expected**, replace `` The collector gives each probe 600 s; `--probe-env` can take about 8 minutes, so a slow run is not a hang. `` with `` The collector gives each probe 600 s; `--probe-env` can take about 8 minutes, so a slow run is not a hang. At 600 s the collector sends the probe SIGTERM and waits up to 90 s for it to remove its containers and throwaway directories before killing it; either way the item is `could-not-check` (exit 124). ``
  3. In **pass rule**, replace `` any `sentinel_in_files: true`, `` with `` any `sentinel_in_files: true`, any `host_credential_files_visible: true`, ``

- [ ] **Step 4: D10.2.** Two edits.

  1. In **expected**, replace `` `rc 0` and `probe.matches_expected: true`: `direct: "blocked"`, `` with `` `rc 0` and `probe.matches_expected: true`: `proxy_rc: 0` and `drafter_rc: 0` (the exit codes of starting the proxy and of the drafter container the answers came from), `direct: "blocked"`, ``
  2. In **pass rule**, replace `` `matches_expected` `false`, `direct` other than `blocked`, `` with `` `matches_expected` `false`, a non-zero `proxy_rc` or `drafter_rc`, `direct` other than `blocked`, ``

- [ ] **Step 5: D10.3.** One edit in **expected**: replace `` (`sudo -l -U` says the user may not run sudo; `rc` is recorded, not judged). `` with:

```
(`sudo -l -U` says the user may not run sudo; `rc` is recorded, not judged). When `sudo -l -U` gave neither of its two answers (it did not run, the user is unknown, or it printed something else), `not_allowed` and `command_lines` are both `could-not-check`. `broker_user_groups` is `could-not-check` when `id` fails (the app user does not exist); the rest of the item is still reported.
```

The pass rule already ends "A `could-not-check` value is CANNOT-VERIFY." Leave it.

- [ ] **Step 6: D10.7.** In **pass rule**, replace `` The known secrets are the installed Google credential values, the Anthropic key and the OpenRouter key `` with `` The known secrets are the installed Google credential values, the Anthropic key, the OpenRouter key and, when one is set, the dashboard password ``

- [ ] **Step 7: The report template.** In `REPORT-TEMPLATE.md` replace line 7 with:

```
- **Authorised credential set:** (the box bundle's `credentials`, one line each: a Google row is role, refresh-token sha12, client-id sha12; a non-Google row is label and sha12, or label alone for the dashboard password)
```

- [ ] **Step 8: BRING-UP.** Three one-line edits. Change nothing else in the file.

  1. Part 2 step 7: replace `` (if present: `sudo rm -f /opt/hermes-agent/data/home/.claude/settings.json`) `` with `` (if present, it holds the Anthropic key: `sudo shred -u /opt/hermes-agent/data/home/.claude/settings.json`, as part 1 step 5) ``
  2. Phase 7, the block that writes the dashboard password: replace `` sudo install -m 600 .env.new .env && sudo rm -f .env.new && echo "WRITTEN len=${#P}" `` with `` sudo install -m 600 .env.new .env && sudo shred -u .env.new && echo "WRITTEN len=${#P}" `` (`.env.new` held the password).
  3. "Ads audits on the box", the line that runs `collect-review-evidence.py --credentials-only` after installing `/etc/hermes/.env.ga`: replace its trailing comment (everything from `# one row for` to the end of the line) with `# the read row for /etc/hermes/.env.ga (role read; its sha12 equals the laptop's .env.ga row), then one row per non-Google secret already installed`. The old comment carried a literal sha12; the new one must not.

- [ ] **Step 9: README.** Replace the whole paragraph that starts `**The box's one non-Google secret file.**` (it ends with `or the next review sees it as \`unlisted\`.`) with:

```
**The box's non-Google secrets.** Two files hold them. The gateway `.env`
(`/opt/projects/claude_code/infra/hermes-agent/.env`, `root:root 0600`) holds the OpenRouter key
(Hermes's own reasoning; dedicated to the box, with a credit limit) and, when the dashboard is
switched on, the dashboard basic-auth password. `/etc/hermes/.env.anthropic` (`root:root 0400`)
holds the **real** `ANTHROPIC_API_KEY` (workspace `hermes-box`, monthly spend limit; used only by
the audit drafter, passed per run and never mounted). The gateway `.env` holds no Anthropic key.
The review collector reports the two files as `kind: authorised-other` (`label: gateway-env` and
`label: anthropic-key`; `AUTHORISED_OTHER` in `bin/collect-review-evidence.py`), names the secrets
each holds (`secrets_held`; `OTHER_SECRET_NAMES` in the same file) and looks for their values in
the shell histories and the journals. Adding another secret file to the box, or another secret to
one of these two files, means adding it there and here, or the next review sees the file as
`unlisted` or never looks for the value.
```

- [ ] **Step 10: Verify.**

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: every suite `OK` (`security-review-checklist.test.py` checks the version line, the item sources and D10.6's pinned hash, none of which this task changes except the version).

Run: `python3 infra/hermes-agent/bin/check-checklist-version.py --base main`
Expected: exit 0 (the checklist changed and its version rose).

Run: `git diff --stat main -- infra/hermes-agent/deploy infra/hermes-agent/README.md`
Expected: exactly four files: `CHECKLIST.md`, `REPORT-TEMPLATE.md`, `BRING-UP.md`, `README.md`.

Run: `git diff main -- infra/hermes-agent/deploy infra/hermes-agent/README.md | grep -E '^\+' | grep -E '[0-9a-f]{12}'`
Expected: no output (no hash or sha12 was added).

- [ ] **Step 11: Commit.**

```bash
git add infra/hermes-agent/deploy/security-review/CHECKLIST.md infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): checklist v1.15 for review #6's follow-ups; shred, not rm, for two key files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Record the findings opened at review #6

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

**Interfaces:** none. This is a documentation task: transcribe the text below exactly.

- [ ] **Step 1: Add the findings.** Insert the following block immediately **before** the line `## Final state of the box (end of session)`:

```markdown
### F26 to F42: opened at security review #6 (2026-10-02)

Review #6 (PASS 34/34, checklist v1.14) accepted sixteen findings opened since review #5, each
with a reason, under D9.1. They were recorded only in the operator's evidence for that review;
this section is their record. F42 is the reviewer's "Not on the checklist" entry 7. "Fixed"
means fixed in the review #6 follow-up change (checklist v1.15), which re-opens the review: the
box is not at that code until it is pulled and review #7 passes.

| # | Finding | Decision at review #6 | Now |
|---|---|---|---|
| F26 | The env probe cannot see a real credential file mounted into an audit container (a real file holds no sentinel). | accepted: D4.1 and the fingerprinted compose file show no such mount | **fixed**: the probe reports `host_credential_files_visible` for each container |
| F27 | When the collector's 600 s timeout kills a probe, the probe's own cleanup does not run. | accepted: the next probe or audit removes the leftovers | **fixed**: the collector sends SIGTERM and waits 90 s before it kills |
| F28 | `probe_egress` ignores its two exit codes. | accepted: a failed step shows as missing lines | **fixed**: `proxy_rc` and `drafter_rc` are reported and must be 0 |
| F29 | `_sudo_rules` reads `command_lines: 0` when `sudo` did not run. | accepted: the pass rule needs `not_allowed: true` | **fixed**: neither answer is `could-not-check` |
| F30 | `d10_3` loses the whole item when the app user is missing. | accepted: it becomes `could-not-check` | **fixed**: only `broker_user_groups` is `could-not-check` |
| F31 | `load_env_value` does not strip an inline `# comment`. | accepted: the installed files have none | **fixed** |
| F32 | The review's "authorised credential set" and `--credentials-only` cover Google values only. | accepted: the other values are covered by D2.1, D4.1, D10.1 and D10.7 | **fixed**: the set lists the Anthropic key, the OpenRouter key and the dashboard password |
| F33 | The audit lock file in `/run/lock` can be pre-created by a local user. | accepted: the worst case is a refused audit, never a run | accepted (standing) |
| F34 | D10.4 inspects running containers only. | accepted: the compose file is in the fingerprint | accepted (standing) |
| F35 | D4.1's evidence comes from `docker exec` inside the gateway container. | accepted: a known limit of that item since review #1 | accepted (standing) |
| F36 | The box bundle is written to the operator's home with the shell's umask before it is shredded. | accepted: it is redacted by design and exists for minutes | accepted (standing) |
| F37 | The broker's sweep of `jobs/` leaves an entry it cannot remove, and only runs while the broker runs. | accepted: only the app user or root can create one there | accepted (standing) |
| F38 | The app MCP server abandons a waiting call when its input ends, and an exception from the logger would leave the broker's sweep. | accepted: neither is reachable by a client | accepted (standing) |
| F39 | D10.6's stated limit (a crafted file can leave the loader with no top-level `mcp_servers` key while the collector reports equal) and its top-level-plain rule, which refuses an indentless list or a key name outside the plain pattern. | accepted: it cannot yield a different or extra server; the broker is the boundary | accepted (standing). The rule is not widened: it fails closed, and no config on the box needs it. Widen it deliberately if a future Hermes config trips `top_level_not_plain`. |
| F40 | BRING-UP part 2 step 7 removed a leftover key file with `rm -f` where part 1 step 5 uses `shred -u`. | accepted: the file was shredded in part 1 on this box | **fixed**; the dashboard step's `.env.new` is shredded too |
| F41 | The README's "one non-Google secret file" paragraph was stale. | accepted: documentation | **fixed** |
| F42 | The dashboard basic-auth password was outside the D2.1 inventory and the leak checks. | accepted for review #6: the dashboard is off by default and bound to localhost | **fixed**: D2.1 names it (`secrets_held`) and its value is a known secret; it is listed and never fingerprinted |

Still open from review #6, not findings against the code: the retired ADMIN write token is valid at
Google (accepted under D3.2; revoke it when the shared grant can be separated), and two reviewer
suggestions for the next review (the collector could name the accounts that `sudoers.d` rules
name; capture the whole Data Training section of the OpenRouter privacy screen).
```

- [ ] **Step 2: Add the open item.** At the very end of the file, after the last numbered item of `## Open items, in order`, append (keep the numbering: the last item is 17, so this is 18):

```markdown
18. **2026-10-02: security review #6 PASS (34/34, checklist v1.14); Option B (chat-triggered
    audits) is live on the box.** Its findings are F26 to F42 above. The follow-up change that
    fixes ten of them moves the checklist to v1.15 and changes the box fingerprint, so it needs a
    pull on the box and review #7 before the box is at that code.
```

Before appending, check the last numbered item. If it is not 17, use the next number and say so in your report.

- [ ] **Step 3: Verify.**

Run: `git diff --stat`
Expected: one file changed, `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`, insertions only.

Run: `git diff | grep -E '^\+' | grep -E '[0-9a-f]{12}'`
Expected: no output.

- [ ] **Step 4: Commit.**

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "docs: record the findings opened at security review #6 (F26 to F42)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the last task

The branch is not pushed. The operator decides when to push and open the pull request. Merging it changes `bin/` and `deploy/`, so it changes the box fingerprint and re-opens review #6: plan a pull on the box and review #7. Run a trial evidence collection on the box before the real one.
