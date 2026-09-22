# F9 — Executor Bind Paths and the Proxy Allow-List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bind sources Compose sends for `ads-mutator` equal the proxy's pinned
`--allow-bind` set by construction, let the broker run Compose without reading `.env`, and prove
both on Linux CI with a test that fails on drift.

**Architecture:** `ads-mutator`'s seven compose sources become absolute, `:?`-guarded variables.
On the box the broker unit supplies them; locally `.env` does. `run-ads-mutate.sh` always passes
`--env-file /dev/null`, so Compose never opens `.env`. A stdlib module (`bin/bind_agreement.py`)
computes the strings Compose will send and reads both units. A static test compares them on every
platform, and a root-on-Linux integration test drives the real wrapper as `hermes-broker`,
through the real proxy started with the unit's own flags, to the real executor, which refuses
because the kill switch is absent.

**Tech Stack:** Python 3 stdlib only (`unittest`, `re`, `shlex`, `subprocess`, `pwd`, `grp`),
POSIX shell, systemd unit files, Docker Engine + Compose v2, GitHub Actions (`ubuntu-latest`),
`setpriv` (util-linux).

**Spec:** `docs/superpowers/specs/2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md`
(including §8, amendments R1–R3). Read it before starting any task, especially §2 (the spike's
measurements M1–M6). Where this plan and the code disagree, the code wins. Stop and report the
disagreement rather than bending the code to fit the plan.

## Global Constraints

- **Mutation stays disabled.** Nothing creates `control/mutation-enabled`. No task touches the VPS.
- **Do not widen the allow-list or change the proxy.** `deploy/hermes-docker-proxy.service` and
  `bin/docker-create-proxy.py` are not modified by any task.
- **The spool stays out of `data/` and off the allow-list** (F10 §8). It is not mounted into
  `ads-mutator`.
- **F12 and F14 are not fixed here.** F14 is only recorded (Task 6).
- **Every new check needs a firing control:** a test that shows it fails on a mismatched input.
- **Stdlib only** in `infra/hermes-agent/bin/` and `infra/hermes-agent/deploy/*.py`. Invoke
  `python3`, never `python`.
- **Linux behaviour is proven on the Linux CI runner, and its executed count is read.** Docker is
  unavailable on the laptop.
- **NEVER run `docker compose config`.** It prints the `env_file` secrets in cleartext.
- **Never read or print `.env`.** Never print a credential value or write one into a tracked file.
- **No client names, customer ids, campaign ids, metrics or drafts** in any added line. Sanctioned
  fixtures only: `acme-dental`, `acme`, `other-clinic`, `slug-1`, `"1234567890"`, `"9998887776"`,
  `"9999999999"`.
- **Stage by explicit path only.** Never `git add -A`, `.project-brain/`, `evals/` or `CLAUDE.md`.
  The working tree carries unrelated operator changes; leave them alone.
- **Canon is read-only.** A PreToolUse hook fires on any Bash command that mentions the canon
  directory, including `git add`. Never stage or edit anything there.
- **Never pipe a test command into `tail`.** The pipeline takes its exit status from `tail`.
  Capture into a variable or read `${PIPESTATUS[0]}`.
- **Commit messages** end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## File map

| File | Change | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/bind_agreement.py` | Create | Compute the binds Compose sends; parse unit `ExecStart`/`Environment=` |
| `infra/hermes-agent/bin/bind_agreement.test.py` | Create | Unit tests for the module, on fixtures |
| `infra/hermes-agent/bin/proxy-policy-sync.test.py` | Modify | Replace the count-only check with the string agreement test + firing controls |
| `infra/hermes-agent/docker-compose.yml` | Modify (`ads-mutator` volumes only) | Absolute, `:?`-guarded sources |
| `infra/hermes-agent/deploy/hermes-broker.service` | Modify | `Environment=` for the three new variables |
| `infra/hermes-agent/deploy/units.test.py` | Modify | Pin the new `Environment=` values against `.env.example` and `ExecStart` |
| `infra/hermes-agent/.env.example` | Modify | Document `HERMES_AGENT_DIR`, `HERMES_ADS_REPO_DIR` |
| `infra/hermes-agent/hostenv.sh` | Modify | Parse four variables per-variable; never open an unreadable `.env` |
| `infra/hermes-agent/bin/hostenv.test.py` | Create | `hostenv.sh` behaviour, including an unreadable `.env` |
| `infra/hermes-agent/run-ads-mutate.sh` | Modify | `docker compose --env-file /dev/null` |
| `infra/hermes-agent/bin/run-ads-mutate.test.py` | Modify | Harness supplies the new variables; assert the flag reaches `docker` |
| `infra/hermes-agent/deploy/fixtures/executor-standin.Dockerfile` | Create | CI-only stand-in for `hermes-agent-claude` |
| `infra/hermes-agent/deploy/bind-agreement-integration.test.py` | Create | Root-on-Linux: wrapper → real proxy → real executor |
| `.github/workflows/ci.yml` | Modify | New `bind-agreement` job |
| `infra/hermes-agent/README.md` | Modify | Step 2 append lines, executor bind sources, 2026-09-21 box list |
| `infra/hermes-agent/deploy/BRING-UP.md` | Modify | Phase 3 key list, new Phase 5 after the units, Phase 6 banner, rehearsal gate |
| `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` | Modify | F9 fixed + correction, `.env` defect, F14, tables |
| `docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md` | Modify | Correction note |

---

### Task 1: `bind_agreement.py` — the binds Compose sends, and the units' own values

**Files:**
- Create: `infra/hermes-agent/bin/bind_agreement.py`
- Test: `infra/hermes-agent/bin/bind_agreement.test.py` (discovered by `run-bin-tests.sh`)

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 2 and 4):
  - `class Unresolved(ValueError)` — a `${VAR:?msg}` with VAR unset or empty.
  - `interpolate(text: str, env: dict) -> str`
  - `split_volume(entry: str) -> tuple[str, str, str | None]` — `(source, target, mode)`
  - `service_block(compose_text: str, service: str) -> str`
  - `service_volumes(compose_text: str, service: str) -> list[str]` — short-form entries, comments stripped
  - `compose_binds(compose_text: str, env: dict, service: str = "ads-mutator") -> list[str]` — `"src:dst:mode"`; raises `ValueError` on a relative source, `Unresolved` on a guarded unset variable
  - `unit_exec_args(unit_text: str) -> list[str]` — `ExecStart` argv **after** the program path
  - `unit_environment(unit_text: str) -> dict[str, str]`
  - `allow_binds(unit_text: str) -> list[str]` — every `--allow-bind` value in `ExecStart`

- [ ] **Step 1: Write the failing tests**

Create `infra/hermes-agent/bin/bind_agreement.test.py`:

```python
"""Unit tests for bind_agreement.py, on FIXTURE text (not the real files — Task 2's
agreement test in proxy-policy-sync.test.py reads those)."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bind_agreement as BA

COMPOSE = """services:
  gateway:
    volumes:
      - ./data:/opt/data
  ads-mutator:
    image: hermes-agent-claude
    volumes:
      - ${GOV:?GOV must be set, see README}/approvals:/opt/governance/approvals:ro
      # a comment line inside the list
      - ${GOV:?GOV must be set, see README}/log:/opt/governance/log
      - ${AGENT:?AGENT must be set}/bin:/opt/cc-bin:ro  # trailing comment
  other:
    volumes:
      - ./x:/y
"""

UNIT = """[Service]
User=example
Environment=A=/one
Environment=B=/two/three
# Environment=C=/commented
ExecStart=/opt/x/bin/tool.py \\
    --listen /run/x.sock \\
    --allow-bind /a:/b:ro \\
    --allow-bind /c:/d:rw
Restart=on-failure
"""


class TestInterpolate(unittest.TestCase):
    def test_a_guarded_set_variable_is_substituted(self):
        self.assertEqual(BA.interpolate("${A:?msg}/x", {"A": "/one"}), "/one/x")

    def test_a_guarded_unset_variable_raises_with_its_message(self):
        with self.assertRaises(BA.Unresolved) as cm:
            BA.interpolate("${A:?A must be set}/x", {})
        self.assertIn("A must be set", str(cm.exception))

    def test_a_guarded_empty_variable_raises(self):
        with self.assertRaises(BA.Unresolved):
            BA.interpolate("${A:?m}", {"A": ""})

    def test_an_unguarded_unset_variable_is_empty_like_compose(self):
        self.assertEqual(BA.interpolate("${A}/x", {}), "/x")


class TestSplitVolume(unittest.TestCase):
    def test_a_guard_message_with_colon_space_and_comma_stays_in_the_source(self):
        self.assertEqual(
            BA.split_volume("${G:?G must be set, see README}/log:/opt/governance/log"),
            ("${G:?G must be set, see README}/log", "/opt/governance/log", None))

    def test_the_mode_is_the_third_part(self):
        self.assertEqual(BA.split_volume("/a:/b:ro"), ("/a", "/b", "ro"))

    def test_a_long_form_or_garbage_entry_is_refused(self):
        with self.assertRaises(ValueError):
            BA.split_volume("/a")


class TestServiceVolumes(unittest.TestCase):
    def test_only_the_named_service_comments_stripped(self):
        self.assertEqual(BA.service_volumes(COMPOSE, "ads-mutator"), [
            "${GOV:?GOV must be set, see README}/approvals:/opt/governance/approvals:ro",
            "${GOV:?GOV must be set, see README}/log:/opt/governance/log",
            "${AGENT:?AGENT must be set}/bin:/opt/cc-bin:ro",
        ])

    def test_an_unknown_service_raises(self):
        with self.assertRaises(ValueError):
            BA.service_volumes(COMPOSE, "nope")


class TestComposeBinds(unittest.TestCase):
    ENV = {"GOV": "/var/lib/g", "AGENT": "/opt/agent"}

    def test_absolute_sources_verbatim_and_a_bare_entry_gains_rw(self):
        """M2 (verbatim) and M3 (bare -> :rw), spec §2."""
        self.assertEqual(BA.compose_binds(COMPOSE, self.ENV), [
            "/var/lib/g/approvals:/opt/governance/approvals:ro",
            "/var/lib/g/log:/opt/governance/log:rw",
            "/opt/agent/bin:/opt/cc-bin:ro",
        ])

    def test_firing_control_a_relative_source_is_refused(self):
        """M1/M6: a relative source's string depends on how Compose was invoked."""
        with self.assertRaises(ValueError) as cm:
            BA.compose_binds(COMPOSE, self.ENV, service="other")
        self.assertIn("relative", str(cm.exception))

    def test_firing_control_an_unset_guarded_variable_is_refused(self):
        with self.assertRaises(BA.Unresolved):
            BA.compose_binds(COMPOSE, {"GOV": "/var/lib/g"})


class TestUnits(unittest.TestCase):
    def test_exec_args_exclude_the_program_and_join_continuations(self):
        self.assertEqual(BA.unit_exec_args(UNIT), [
            "--listen", "/run/x.sock", "--allow-bind", "/a:/b:ro", "--allow-bind", "/c:/d:rw"])

    def test_allow_binds(self):
        self.assertEqual(BA.allow_binds(UNIT), ["/a:/b:ro", "/c:/d:rw"])

    def test_environment_ignores_commented_lines(self):
        self.assertEqual(BA.unit_environment(UNIT), {"A": "/one", "B": "/two/three"})

    def test_a_unit_without_exec_start_raises(self):
        with self.assertRaises(ValueError):
            BA.unit_exec_args("[Service]\nUser=x\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/bind_agreement.test.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bind_agreement'`.

- [ ] **Step 3: Write the module**

Create `infra/hermes-agent/bin/bind_agreement.py`:

```python
"""F9: the strings Compose sends as ads-mutator's HostConfig.Binds, computed without Docker,
and the values the two systemd units pin.

Stdlib only: the proxy may not grow a dependency, so neither may its guard. Used by
proxy-policy-sync.test.py (static, every platform) and
deploy/bind-agreement-integration.test.py (real Docker, Linux CI), which also checks this
model against real Compose on every run.

THE MODEL (measured, spec §2): Compose v2 sends an ABSOLUTE source verbatim — no symlink
resolution, no cleaning (M2) — and gives a bare entry the mode "rw" (M3). A RELATIVE source is
joined to a project directory whose spelling depends on how Compose was started (-f form, PWD,
sudo: M1, M6). That dependence is F9 itself, so a relative source is refused here rather than
guessed at.
"""
import re
import shlex

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:\?([^}]*))?\}")
_MASK = re.compile(r"\x00(\d+)\x00")


class Unresolved(ValueError):
    """A ${VAR:?msg} whose VAR is unset or empty: Compose would stop with msg."""


def interpolate(text, env):
    def sub(m):
        name, guard, msg = m.group(1), m.group(2), m.group(3)
        val = env.get(name, "")
        if guard and not val:
            raise Unresolved("%s: %s" % (name, msg or "required"))
        return val
    return _VAR.sub(sub, text)


def _mask(text):
    """Hide every ${...} (which may hold ':', ' ', ',' or '#') behind a placeholder."""
    found = []

    def hide(m):
        found.append(m.group(0))
        return "\x00%d\x00" % (len(found) - 1)
    return _VAR.sub(hide, text), (lambda s: _MASK.sub(lambda m: found[int(m.group(1))], s))


def split_volume(entry):
    masked, unmask = _mask(entry)
    parts = [unmask(p) for p in masked.split(":")]
    if len(parts) not in (2, 3):
        raise ValueError("not a short-form volume entry: %r" % entry)
    return parts[0], parts[1], (parts[2] if len(parts) == 3 else None)


def service_block(compose_text, service):
    marker = "\n  %s:\n" % service
    start = compose_text.find(marker)
    if start < 0:
        raise ValueError("service %r not found in the compose file" % service)
    rest = compose_text[start + 1:]
    m = re.search(r"\n  [A-Za-z0-9_-]+:\n", rest)
    return rest[:m.start()] if m else rest


def service_volumes(compose_text, service):
    out, inside = [], False
    for line in service_block(compose_text, service).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 4 and stripped == "volumes:":
            inside = True
            continue
        if not inside:
            continue
        if indent <= 4:
            break
        if stripped.startswith("- "):
            masked, unmask = _mask(stripped[2:])
            out.append(unmask(re.split(r"\s+#", masked, maxsplit=1)[0].strip()))
    return out


def compose_binds(compose_text, env, service="ads-mutator"):
    out = []
    for entry in service_volumes(compose_text, service):
        src, dst, mode = split_volume(entry)
        src = interpolate(src, env)
        if not src.startswith("/"):
            raise ValueError(
                "relative bind source %r (from %r): its string depends on how Compose was "
                "invoked (spec §2, M1/M6), so it cannot be pinned" % (src, entry))
        out.append("%s:%s:%s" % (src, dst, mode or "rw"))
    return out


def _directives(unit_text):
    joined = re.sub(r"\\\n", " ", unit_text)
    return [l.strip() for l in joined.splitlines()
            if l.strip() and not l.strip().startswith(("#", ";"))]


def unit_exec_args(unit_text):
    for line in _directives(unit_text):
        if line.startswith("ExecStart="):
            return shlex.split(line[len("ExecStart="):])[1:]
    raise ValueError("the unit has no ExecStart=")


def unit_environment(unit_text):
    env = {}
    for line in _directives(unit_text):
        if line.startswith("Environment="):
            key, _, val = line[len("Environment="):].partition("=")
            env[key] = val
    return env


def allow_binds(unit_text):
    args = unit_exec_args(unit_text)
    return [args[i + 1] for i, a in enumerate(args) if a == "--allow-bind" and i + 1 < len(args)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/bind_agreement.test.py`
Expected: every test OK.

Then the whole bin suite: `infra/hermes-agent/bin/run-bin-tests.sh; echo "exit $?"`
Expected: `30/30 suites passed` (29 + the new one), exit 0.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/bind_agreement.py infra/hermes-agent/bin/bind_agreement.test.py
git commit -m "feat(hermes): bind_agreement — the binds Compose sends, and the units' values

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The agreement test, then absolute compose sources and the broker's environment

The agreement test is written first and **must be seen failing against today's compose**. That
failure is the firing control against the real F9 drift. The same task then makes it pass.

**Files:**
- Modify: `infra/hermes-agent/bin/proxy-policy-sync.test.py` (replace `test_every_compose_volume_is_representable_as_an_allow_bind`)
- Modify: `infra/hermes-agent/docker-compose.yml` (`ads-mutator` volumes, currently ~lines 98-124)
- Modify: `infra/hermes-agent/deploy/hermes-broker.service` (the `Environment=` block, ~lines 20-25)
- Modify: `infra/hermes-agent/deploy/units.test.py` (new class after `TestSpoolPathContract`)
- Modify: `infra/hermes-agent/.env.example` (after the spool block, ~line 46)

**Interfaces:**
- Consumes: `bind_agreement.compose_binds`, `unit_environment`, `allow_binds`, `Unresolved` (Task 1).
- Produces: the broker unit's `Environment=HERMES_AGENT_DIR=/opt/hermes-agent`,
  `Environment=HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads`,
  `Environment=HERMES_SPOOL_DIR=/var/lib/hermes/spool` (Tasks 3, 4, 5 rely on these names).

- [ ] **Step 1: Replace the count-only test with the agreement test**

In `infra/hermes-agent/bin/proxy-policy-sync.test.py`, add near the top (after the `BROKER = …` line):

```python
DEPLOY = os.path.join(os.path.dirname(HERE), "deploy")
PROXY_UNIT = os.path.join(DEPLOY, "hermes-docker-proxy.service")
BROKER_UNIT = os.path.join(DEPLOY, "hermes-broker.service")
import bind_agreement as BA
```

Delete `test_every_compose_volume_is_representable_as_an_allow_bind` (and its docstring) from
`TestProxyMatchesCompose`, and add this class after `TestProxyMatchesCompose`:

```python
class TestComposeBindsEqualThePinnedSet(unittest.TestCase):
    """F9. The strings Compose will send for ads-mutator, computed from the BROKER unit's
    environment (the broker is what runs Compose), must equal the PROXY unit's --allow-bind
    set, AS STRINGS. The count-and-shape check this replaces passed while every path was
    wrong: that is how F9 shipped. The model is checked against real Compose by
    deploy/bind-agreement-integration.test.py on Linux CI."""

    def setUp(self):
        self.compose = open(COMPOSE, encoding="utf-8").read()
        self.env = BA.unit_environment(open(BROKER_UNIT, encoding="utf-8").read())
        self.pinned = BA.allow_binds(open(PROXY_UNIT, encoding="utf-8").read())

    def test_compose_binds_equal_the_pinned_set(self):
        got = BA.compose_binds(self.compose, self.env)
        self.assertEqual(len(got), len(set(got)), "a bind is declared twice: %s" % got)
        self.assertEqual(sorted(got), sorted(self.pinned))

    def test_exactly_one_bind_is_writable_and_it_is_log(self):
        rw = [b for b in BA.compose_binds(self.compose, self.env) if not b.endswith(":ro")]
        self.assertEqual(len(rw), 1, rw)
        self.assertIn(":/opt/governance/log:", rw[0])

    def test_firing_control_a_moved_checkout_is_a_mismatch(self):
        env = dict(self.env, HERMES_AGENT_DIR="/opt/elsewhere")
        self.assertNotEqual(sorted(BA.compose_binds(self.compose, env)), sorted(self.pinned))

    def test_firing_control_a_relative_source_is_refused(self):
        drifted, n = re.subn(r"- \$\{HERMES_AGENT_DIR:\?[^}]*\}/bin:", "- ./bin:",
                             self.compose, count=1)
        self.assertEqual(n, 1, "the control did not find the bin source to drift")
        with self.assertRaises(ValueError):
            BA.compose_binds(drifted, self.env)

    def test_firing_control_a_broker_without_the_variable_is_refused(self):
        env = {k: v for k, v in self.env.items() if k != "HERMES_ADS_REPO_DIR"}
        with self.assertRaises(BA.Unresolved):
            BA.compose_binds(self.compose, env)
```

- [ ] **Step 2: Run it and record the failure against today's compose**

Run: `python3 infra/hermes-agent/bin/proxy-policy-sync.test.py -v`
Expected: the new tests ERROR with
`ValueError: relative bind source '../../../claude-google-ads' …` (or `./registry` / `./bin`,
whichever the parser meets first). **Copy that line into the commit message body.** It is the
evidence that the test catches the real drift. `test_firing_control_a_relative_source_is_refused`
also fails at this point (`n == 0`: no `${HERMES_AGENT_DIR` source exists yet). That is expected.

- [ ] **Step 3: Make `ads-mutator`'s sources absolute and guarded**

In `infra/hermes-agent/docker-compose.yml`, in the `ads-mutator` service only, change the seven
source lines. Keep every existing comment block in place (the `log/` S3-b comment and the NO
`seen/` comment are load-bearing documentation). Only these lines change:

```yaml
      - ${HERMES_GOVERNANCE_DIR:?HERMES_GOVERNANCE_DIR must be set, see .env.example}/approvals:/opt/governance/approvals:ro
      - ${HERMES_GOVERNANCE_DIR:?HERMES_GOVERNANCE_DIR must be set, see .env.example}/control:/opt/governance/control:ro
      - ${HERMES_GOVERNANCE_DIR:?HERMES_GOVERNANCE_DIR must be set, see .env.example}/registry:/opt/governance/registry:ro
```
```yaml
      - ${HERMES_GOVERNANCE_DIR:?HERMES_GOVERNANCE_DIR must be set, see .env.example}/log:/opt/governance/log
```
```yaml
      - ${HERMES_ADS_REPO_DIR:?HERMES_ADS_REPO_DIR must be set, see README Executor bind sources}:/projects/claude_google_ads:ro
      - ${HERMES_AGENT_DIR:?HERMES_AGENT_DIR must be set, see README Executor bind sources}/registry:/opt/registry:ro
      - ${HERMES_AGENT_DIR:?HERMES_AGENT_DIR must be set, see README Executor bind sources}/bin:/opt/cc-bin:ro
```

Directly above the `ads-mutator` `volumes:` key, add this comment:

```yaml
    # F9: EVERY source here is absolute and comes from a :?-guarded variable. Compose sends an
    # absolute source verbatim (spec 2026-09-22 §2, M2), so the strings the proxy compares are
    # exactly the values the broker unit sets — and those equal hermes-docker-proxy.service's
    # --allow-bind sources (proxy-policy-sync.test.py asserts it). NEVER use a relative source
    # here: Compose joins it to a project directory whose spelling depends on how Compose was
    # started (-f form, PWD, sudo — M1/M6), and the proxy refuses anything but an exact match.
```

- [ ] **Step 4: Give the broker unit the three variables**

In `infra/hermes-agent/deploy/hermes-broker.service`, after the existing
`Environment=HERMES_SPOOL_ROOT=/var/lib/hermes/spool` line, add:

```ini
# F9: the executor's bind sources. run-ads-mutate.sh runs `docker compose --env-file /dev/null`
# (this user cannot read .env, and must not), so Compose takes every variable from HERE. The
# values must equal hermes-docker-proxy.service's --allow-bind sources exactly:
# proxy-policy-sync.test.py and units.test.py assert it.
Environment=HERMES_AGENT_DIR=/opt/hermes-agent
Environment=HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads
# Compose interpolates the WHOLE file, so the gateway's ${HERMES_SPOOL_DIR:?} must resolve even
# for `run ads-mutator`, which never mounts the spool. Same path as HERMES_SPOOL_ROOT.
Environment=HERMES_SPOOL_DIR=/var/lib/hermes/spool
```

- [ ] **Step 5: Document the two new keys in `.env.example`**

In `infra/hermes-agent/.env.example`, after the `HERMES_SPOOL_DIR=/var/lib/hermes/spool` line, add:

```sh

# --- Executor bind sources (mutation tier, F9) ---
# The ads-mutator container's bind sources. REQUIRED — Compose interpolates the whole file, so
# every `docker compose` command stops without them, not only the mutation rail. NOT free-choice
# on a VPS: hermes-broker.service sets the same values and hermes-docker-proxy.service pins
# them, so a different path means the proxy DENIES the executor. Locally, any path that points
# at this directory and at the ads repo checkout works (relative values resolve against this
# directory), because darwin has no proxy.
HERMES_AGENT_DIR=/opt/hermes-agent
HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads
```

- [ ] **Step 6: Pin the unit values in `units.test.py`**

In `infra/hermes-agent/deploy/units.test.py`, add `import bind_agreement as BA` after
`import host_layout as H`, and this class after `TestSpoolPathContract`:

```python
class TestExecutorBindContract(unittest.TestCase):
    """F9. The broker unit, .env.example and the units' own program paths must name the same
    executor bind sources. proxy-policy-sync.test.py compares them with the proxy's pins."""

    def setUp(self):
        self.env = BA.unit_environment(unit("hermes-broker.service"))
        self.example = open(os.path.join(AGENT, ".env.example"), encoding="utf-8").read()

    def test_the_broker_sets_the_executor_bind_sources(self):
        self.assertEqual(self.env.get("HERMES_AGENT_DIR"), "/opt/hermes-agent")
        self.assertEqual(self.env.get("HERMES_ADS_REPO_DIR"), "/opt/projects/claude-google-ads")

    def test_the_brokers_spool_dir_is_its_spool_root(self):
        self.assertEqual(self.env.get("HERMES_SPOOL_DIR"), self.env.get("HERMES_SPOOL_ROOT"))
        self.assertEqual(self.env.get("HERMES_SPOOL_DIR"), H.DEFAULT_SPOOL_ROOT)

    def test_env_example_agrees_with_the_broker(self):
        for key in ("HERMES_AGENT_DIR", "HERMES_ADS_REPO_DIR", "HERMES_GOVERNANCE_DIR",
                    "HERMES_SPOOL_DIR"):
            self.assertRegex(self.example,
                             r"(?m)^%s=%s$" % (key, re.escape(self.env[key])), key)

    def test_both_units_run_their_program_from_the_agent_dir(self):
        """HERMES_AGENT_DIR is the checkout both units already execute from; a unit that
        runs from one path and binds from another is F9 again."""
        agent = self.env["HERMES_AGENT_DIR"]
        for name in ("hermes-broker.service", "hermes-docker-proxy.service"):
            start = [l for l in live_lines(unit(name)) if l.startswith("ExecStart=")]
            self.assertEqual(len(start), 1, name)
            self.assertIn(agent + "/bin/", start[0], name)

    def test_firing_control_a_drifted_example_fails_the_regex(self):
        drifted = self.example.replace("HERMES_AGENT_DIR=/opt/hermes-agent",
                                       "HERMES_AGENT_DIR=/opt/elsewhere")
        self.assertNotEqual(drifted, self.example, "the control did not drift anything")
        self.assertNotRegex(drifted, r"(?m)^HERMES_AGENT_DIR=/opt/hermes-agent$")
```

- [ ] **Step 7: Run everything touched and confirm green**

```bash
python3 infra/hermes-agent/bin/proxy-policy-sync.test.py -v; echo "sync exit $?"
python3 infra/hermes-agent/deploy/units.test.py; echo "units exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "bin exit $?"
```
Expected: all exit 0. `proxy-policy-sync` now passes all tests, including the three firing
controls. Bin `30/30`.

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/proxy-policy-sync.test.py infra/hermes-agent/docker-compose.yml \
  infra/hermes-agent/deploy/hermes-broker.service infra/hermes-agent/deploy/units.test.py \
  infra/hermes-agent/.env.example
git commit -m "fix(hermes): F9 — absolute executor bind sources, pinned against the proxy

The agreement test failed against the old compose with:
<paste the Step 2 ValueError line here>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The wrapper never lets Compose read `.env`

**Files:**
- Modify: `infra/hermes-agent/hostenv.sh`
- Create: `infra/hermes-agent/bin/hostenv.test.py`
- Modify: `infra/hermes-agent/run-ads-mutate.sh` (the `docker compose` line, ~line 88)
- Modify: `infra/hermes-agent/bin/run-ads-mutate.test.py` (`_run`, the fake `docker`, one new test)

**Interfaces:**
- Consumes: the four variable names from Task 2.
- Produces: `hostenv.sh` exports `HERMES_GOVERNANCE_DIR`, `HERMES_AGENT_DIR`,
  `HERMES_ADS_REPO_DIR`, `HERMES_SPOOL_DIR` (each only if set) and never opens an unreadable
  `.env`. `run-ads-mutate.sh` calls `docker compose --env-file /dev/null -f "$here/docker-compose.yml" run …`
  (Task 4 drives this for real).

- [ ] **Step 1: Write the failing `hostenv.sh` tests**

Create `infra/hermes-agent/bin/hostenv.test.py`:

```python
"""hostenv.sh, sourced the way run-ads-mutate.sh and changeset.sh source it.

F9 (spec §3.3, R1): it parses FOUR variables from .env as data, each only when unset, and it
must never open .env when it does not need to — on the VPS the broker sources it with every
value set by its unit and .env 600 root:root, and a failed redirect under `set -eu` aborts.
Runs as an ordinary user everywhere; the unreadable case is skipped only when run as root
(root can read a 000 file)."""
import os, shutil, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTENV = os.path.join(os.path.dirname(HERE), "hostenv.sh")
KEYS = ("HERMES_GOVERNANCE_DIR", "HERMES_AGENT_DIR", "HERMES_ADS_REPO_DIR", "HERMES_SPOOL_DIR")

PRINT = ('set -eu; here="$1"; . "$here/hostenv.sh"; '
         'for k in ' + " ".join(KEYS) + '; do eval "v=\\${$k:-}"; echo "$k=$v"; done')


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        shutil.copy2(HOSTENV, os.path.join(self.home, "hostenv.sh"))

    def write_env(self, text, mode=0o600):
        p = os.path.join(self.home, ".env")
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        self.addCleanup(os.chmod, p, 0o600)       # so rmtree can always remove it

    def source(self, **env):
        base = {"PATH": os.environ["PATH"]}
        base.update(env)
        p = subprocess.run(["/bin/sh", "-c", PRINT, "sh", self.home],
                           capture_output=True, text=True, env=base)
        vals = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
        return p, vals


class TestParsing(Base):
    def test_all_four_are_read_from_env_as_data(self):
        self.write_env("ANTHROPIC_API_KEY=placeholder-not-a-key\n"
                       "HERMES_GOVERNANCE_DIR=/g\nHERMES_AGENT_DIR=/a\n"
                       "HERMES_ADS_REPO_DIR='/r'\nHERMES_SPOOL_DIR=\"./data/spool\"\n")
        p, v = self.source()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(v, {"HERMES_GOVERNANCE_DIR": "/g", "HERMES_AGENT_DIR": "/a",
                             "HERMES_ADS_REPO_DIR": "/r", "HERMES_SPOOL_DIR": "./data/spool"})

    def test_an_environment_value_wins_per_variable(self):
        self.write_env("HERMES_GOVERNANCE_DIR=/g\nHERMES_AGENT_DIR=/from-file\n")
        p, v = self.source(HERMES_AGENT_DIR="/from-env")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(v["HERMES_AGENT_DIR"], "/from-env")
        self.assertEqual(v["HERMES_GOVERNANCE_DIR"], "/g")

    def test_no_other_key_leaks_into_the_environment(self):
        self.write_env("HERMES_GOVERNANCE_DIR=/g\nANTHROPIC_API_KEY=placeholder-not-a-key\n")
        p = subprocess.run(["/bin/sh", "-c", 'set -eu; here="$1"; . "$here/hostenv.sh"; env',
                            "sh", self.home], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"]})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("ANTHROPIC_API_KEY", p.stdout)


class TestUnreadableEnv(Base):
    def setUp(self):
        super().setUp()
        if os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        self.write_env("HERMES_GOVERNANCE_DIR=/g\n", mode=0o000)

    def test_all_set_means_env_is_never_opened(self):
        """The VPS case: the broker unit sets all four; .env is 600 root:root."""
        p, v = self.source(HERMES_GOVERNANCE_DIR="/g", HERMES_AGENT_DIR="/a",
                           HERMES_ADS_REPO_DIR="/r", HERMES_SPOOL_DIR="/s")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Permission denied", p.stderr)
        self.assertEqual(v["HERMES_AGENT_DIR"], "/a")

    def test_firing_control_an_unset_governance_dir_still_refuses(self):
        """An unreadable .env is skipped, not trusted: the R4 guard must still fire."""
        p, _ = self.source(HERMES_AGENT_DIR="/a")
        self.assertEqual(p.returncode, 1)
        self.assertIn("HERMES_GOVERNANCE_DIR is unset or empty", p.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 infra/hermes-agent/bin/hostenv.test.py -v`
Expected: `test_all_four_are_read_from_env_as_data` FAILS (only `HERMES_GOVERNANCE_DIR` is
parsed today). `test_all_set_means_env_is_never_opened` may pass or fail on the old script
(today's guard skips the read only because `HERMES_GOVERNANCE_DIR` is set). Record which.

- [ ] **Step 3: Rewrite the parsing block of `hostenv.sh`**

In `infra/hermes-agent/hostenv.sh`, replace the header paragraph that begins
`` `.env` is parsed as DATA`` and the `if [ -z "${HERMES_GOVERNANCE_DIR:-}" ] && [ -f "$here/.env" ]; then … fi`
block with the following. Leave the R4 guard, the absolute-path check and the exports below it
as they are, except for the one added `export` line in Step 4.

```sh
# `.env` is parsed as DATA, never sourced — the same rule run-ads-mutate.sh applies to
# `.env.gaw`, and the rule this capsule writes down. Only the four keys below are read; every
# other line, including every credential, is ignored and never evaluated.
#
# An explicit environment value always wins over `.env`, PER KEY, so a one-off run against a
# different store stays a prefix on the command line.
#
# F9 (spec 2026-09-22 §3.3, R1). The three keys after HERMES_GOVERNANCE_DIR are Compose
# interpolation input only: run-ads-mutate.sh runs `docker compose --env-file /dev/null`, so
# Compose never opens .env and must get them from the environment. They are PARSED here, not
# guarded — compose's own ${VAR:?} refuses an unset one, and changeset.sh, which also sources
# this file, never runs Compose. `.env` is opened only when a key is missing AND the file is
# readable: on the VPS the broker sources this with all four set by its unit and .env
# 600 root:root, and a failed redirect under `set -eu` would abort the wrapper.
_hermes_env_default() {
  eval "_cur=\${$1:-}"
  [ -z "$_cur" ] || return 0
  [ -r "$here/.env" ] || return 0
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      "$1"=*) : ;;
      *) continue ;;
    esac
    _val=${_line#"$1"=}
    case "$_val" in
      \"*\") _val=${_val#\"}; _val=${_val%\"} ;;
      \'*\') _val=${_val#\'}; _val=${_val%\'} ;;
    esac
    eval "$1=\$_val"
  done < "$here/.env"
}
for _hermes_key in HERMES_GOVERNANCE_DIR HERMES_AGENT_DIR HERMES_ADS_REPO_DIR HERMES_SPOOL_DIR; do
  _hermes_env_default "$_hermes_key"
done
```

(`eval` only ever sees one of the four fixed key names above, never file content: `_val` is
assigned by reference, `\$_val`.)

- [ ] **Step 4: Export the three new keys when set**

At the end of `hostenv.sh`, after `export VAULT_ROOT="$here/data/vaults"`, add:

```sh
# Compose reads these from the environment (run-ads-mutate.sh passes --env-file /dev/null).
# Exported only when set: an unset one must stay unset so compose's :? names it.
for _hermes_key in HERMES_AGENT_DIR HERMES_ADS_REPO_DIR HERMES_SPOOL_DIR; do
  eval "_cur=\${$_hermes_key:-}"
  [ -z "$_cur" ] || export "$_hermes_key"
done
```

- [ ] **Step 5: Run the `hostenv.sh` tests**

Run: `python3 infra/hermes-agent/bin/hostenv.test.py -v`
Expected: all OK.

- [ ] **Step 6: Write the failing wrapper test**

In `infra/hermes-agent/bin/run-ads-mutate.test.py`, change `FAKE_DOCKER` so the fake records its
argv (insert as the first line after the shebang comment block, before `cat <<'HERMES_FAKE_DOCKER_EOF'`):

```sh
printf '%%s\n' "$@" > "$(dirname "$0")/docker.argv"
```

(`%%s` because `FAKE_DOCKER` is a `%`-format string.) In `Base._run`, after
`env["HERMES_GOVERNANCE_DIR"] = self.gov`, add:

```python
        # F9: compose-only interpolation inputs. The wrapper never lets Compose read .env
        # (--env-file /dev/null), so they must come from the environment, as on the VPS.
        env["HERMES_AGENT_DIR"] = self.home
        env["HERMES_ADS_REPO_DIR"] = os.path.join(self.tmp, "ads-repo")
        env["HERMES_SPOOL_DIR"] = os.path.join(self.tmp, "spool")
```

Add this class at the end of the file (before `if __name__`):

```python
class TestComposeNeverReadsEnv(Base):
    """F9 (spec §3.3): as hermes-broker, .env is 600 root:root and Compose aborts on it even
    with every variable exported (spike M4). The wrapper must pass --env-file /dev/null.
    Exercised for real, through Docker, by deploy/bind-agreement-integration.test.py."""

    def test_the_wrapper_passes_env_file_dev_null_before_run(self):
        p = self._run(executor_rc=0)
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = open(os.path.join(self.bin, "docker.argv")).read().splitlines()
        self.assertEqual(argv[:3], ["compose", "--env-file", "/dev/null"], argv)
        self.assertIn("run", argv)
        self.assertLess(argv.index("--env-file"), argv.index("run"))
```

- [ ] **Step 7: Run it to verify it fails**

Run: `python3 infra/hermes-agent/bin/run-ads-mutate.test.py -v`
Expected (darwin): `test_the_wrapper_passes_env_file_dev_null_before_run` FAILS because
`argv[:3]` is `['compose', '-f', …]`. Every other test still passes. (On Linux as non-uid-10000
the whole file SKIPS by design. That's why Task 4 exists.)

- [ ] **Step 8: Change the wrapper**

In `infra/hermes-agent/run-ads-mutate.sh`, change the line
`docker compose -f "$here/docker-compose.yml" run --rm --no-deps \`
to
`docker compose --env-file /dev/null -f "$here/docker-compose.yml" run --rm --no-deps \`
and add this comment directly above the `docker compose` call (below any existing comment there):

```sh
# F9: --env-file /dev/null — Compose must never open .env here. On the VPS this runs as
# hermes-broker and .env is 600 root:root (it holds ANTHROPIC_API_KEY); Compose aborts on an
# unreadable .env even when every variable is exported (spec 2026-09-22 §2, M4). The
# interpolation inputs come from the environment instead: the broker unit on the VPS,
# hostenv.sh (parsing .env as data) locally.
```

- [ ] **Step 9: Run the suites**

```bash
python3 infra/hermes-agent/bin/run-ads-mutate.test.py -v; echo "wrapper exit $?"
infra/hermes-agent/bin/run-bin-tests.sh; echo "bin exit $?"
```
Expected: exit 0 for both; bin `31/31`.

- [ ] **Step 10: Commit**

```bash
git add infra/hermes-agent/hostenv.sh infra/hermes-agent/bin/hostenv.test.py \
  infra/hermes-agent/run-ads-mutate.sh infra/hermes-agent/bin/run-ads-mutate.test.py
git commit -m "fix(hermes): F9 — the mutation wrapper never lets Compose read .env

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The Linux integration test and its CI job

**Files:**
- Create: `infra/hermes-agent/deploy/fixtures/executor-standin.Dockerfile`
- Create: `infra/hermes-agent/deploy/bind-agreement-integration.test.py`
- Modify: `.github/workflows/ci.yml` (new job after `tests`)

**Interfaces:**
- Consumes: `bind_agreement.unit_exec_args`, `unit_environment`, `allow_binds`, `compose_binds`
  (Task 1); the broker unit's variables (Task 2); the wrapper's `--env-file /dev/null` (Task 3).
- Produces: CI log line `bind-agreement: executed N, skipped M, failures F, errors E`.

- [ ] **Step 1: The stand-in image**

Create `infra/hermes-agent/deploy/fixtures/executor-standin.Dockerfile`:

```dockerfile
# CI ONLY — a stand-in for hermes-agent-claude, built by bind-agreement-integration.test.py.
# The proxy pins the image NAME and the entrypoint `python3 /opt/cc-bin/apply-changeset.py`
# (docker-create-proxy.py PINNED_ENTRYPOINT); the executor and its libraries are stdlib-only,
# so an official python image runs the REAL executor from the bind-mounted bin/. uid 10000
# matches the real image's `USER hermes`. What this does NOT prove: anything about the real
# image (its Python, its layers) — BRING-UP Phase 5 runs the real image on the box.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
RUN groupadd -g 10000 hermes && useradd -u 10000 -g 10000 -M -s /usr/sbin/nologin hermes
USER hermes
```

- [ ] **Step 2: Write the integration test**

Create `infra/hermes-agent/deploy/bind-agreement-integration.test.py`:

```python
#!/usr/bin/env python3
"""F9 Tier 2: ads-mutator's REAL binds, through the REAL proxy started with the unit's own
flags, driven the way the broker drives it.

WHAT RUNS. The box layout (BRING-UP Phase 2: a checkout under /opt/projects, /opt/hermes-agent
a symlink to it, the ads repo placeholder, the store from init-host-layout.py --apply). The
proxy with hermes-docker-proxy.service's ExecStart arguments (only --listen moved). As
hermes-broker, with hermes-broker.service's Environment= and .env 600 root:root:
/opt/hermes-agent/run-ads-mutate.sh — hostenv.sh, the pre-flight, `docker compose
--env-file /dev/null … run ads-mutator`, the proxy's create check, the real executor in a
stand-in image, which refuses because the kill switch is absent (exit 2).

WHERE IT RUNS. As root on Linux with Docker: the CI `bind-agreement` job runs it under sudo
with HERMES_REQUIRE_LINUX_INTEGRATION=1. Anywhere else it prints SKIPPED and exits 0, unless
that variable is set, in which case any skip is a FAILURE. It prints how many tests executed:
read that line on the PR run AND on the merge commit.

NOT FOR THE VPS. It creates /opt/projects/claude_code, /opt/hermes-agent and the governance
store, and REFUSES to run if any of them already exists.

FIDELITY GAPS (say so, do not paper over): the proxy runs as root here, not as
hermes-docker-proxy (the socket's group, hermes-rail, is what the broker needs, and that is
reproduced); the image is a stand-in; systemd itself is not involved.
"""
import grp, json, os, pwd, re, shutil, subprocess, sys, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(AGENT, "bin"))
import bind_agreement as BA

REQUIRED = os.environ.get("HERMES_REQUIRE_LINUX_INTEGRATION") == "1"
PROXY_UNIT = open(os.path.join(HERE, "hermes-docker-proxy.service"), encoding="utf-8").read()
BROKER_UNIT = open(os.path.join(HERE, "hermes-broker.service"), encoding="utf-8").read()
UNIT_ENV = BA.unit_environment(BROKER_UNIT)
AGENT_DIR = UNIT_ENV["HERMES_AGENT_DIR"]
ADS_REPO = UNIT_ENV["HERMES_ADS_REPO_DIR"]
STORE = UNIT_ENV["HERMES_GOVERNANCE_DIR"]
SPOOL = UNIT_ENV["HERMES_SPOOL_DIR"]
CHECKOUT = "/opt/projects/claude_code"
REAL_AGENT = os.path.join(CHECKOUT, "infra", "hermes-agent")
SOCK_DIR = "/run/hermes-f9-it"
IMAGE = "hermes-agent-claude"
BROKER = ["setpriv", "--reuid", "hermes-broker", "--regid", "hermes-broker",
          "--groups", "hermes,hermes-rail"]
CMD = ["--client", "slug-1", "--changeset", "20260922-120000-abcdef01",
       "--request", "00000000-0000-4000-8000-000000000000"]
BIN_PIN = "%s/bin:/opt/cc-bin:ro" % AGENT_DIR
CREATE_ALLOWED = re.compile(r"ALLOW POST /v[0-9.]+/containers/create")
CREATE_DENIED = re.compile(r"DENY POST /v[0-9.]+/containers/create")
PROXIES = []
_UNIT_PROXY = []


def run(argv, env=None, check=False, timeout=300):
    return subprocess.run(argv, env=env, capture_output=True, text=True, check=check,
                          timeout=timeout)


def why_not_runnable():
    if not sys.platform.startswith("linux"):
        return "not Linux"
    if os.geteuid() != 0:
        return "not root"
    if shutil.which("setpriv") is None:
        return "setpriv not found"
    if shutil.which("docker") is None or run(["docker", "info"]).returncode != 0:
        return "docker unavailable"
    if run(["docker", "compose", "version"]).returncode != 0:
        return "docker compose unavailable"
    for p in (CHECKOUT, AGENT_DIR, STORE, ADS_REPO):
        if os.path.lexists(p):
            return "%s already exists — this suite builds the box layout and must not run on a real host" % p
    return None


def root_env():
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(UNIT_ENV)
    env.pop("DOCKER_HOST", None)          # root talks to the real daemon for setup only
    return env


def setUpModule():
    why = why_not_runnable()
    if why:
        raise unittest.SkipTest(why)
    # README step 1's identities, idempotently (the same as layout-integration.test.py).
    run(["groupadd", "-f", "hermes-rail"], check=True)
    run(["groupadd", "-f", "hermes-broker"], check=True)
    if run(["getent", "group", "hermes"]).returncode != 0:
        run(["groupadd", "-g", "10000", "hermes"], check=True)
    if run(["id", "hermes-broker"]).returncode != 0:
        run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
             "-g", "hermes-broker", "hermes-broker"], check=True)
    # BRING-UP Phase 2: a checkout under /opt/projects, /opt/hermes-agent a SYMLINK to it.
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "data", ".env", ".env.gaw")
    shutil.copytree(AGENT, REAL_AGENT, ignore=skip, symlinks=True)
    run(["chmod", "-R", "a+rX", "/opt/projects"], check=True)
    os.symlink(REAL_AGENT, AGENT_DIR)
    os.makedirs(ADS_REPO, 0o755)
    # BRING-UP Phase 3: .env root 600, dummy values only. Includes every interpolation input.
    env_file = os.path.join(AGENT_DIR, ".env")
    with open(env_file, "w") as f:
        f.write("ANTHROPIC_API_KEY=placeholder-not-a-key\n")
        for k in ("HERMES_GOVERNANCE_DIR", "HERMES_SPOOL_DIR", "HERMES_AGENT_DIR",
                  "HERMES_ADS_REPO_DIR"):
            f.write("%s=%s\n" % (k, UNIT_ENV[k]))
    os.chown(env_file, 0, 0)
    os.chmod(env_file, 0o600)
    # The wrapper refuses without .env.gaw declaring the WRITE role. Placeholders only: the
    # executor refuses at the kill switch, before any credential is read.
    gaw = os.path.join(AGENT_DIR, ".env.gaw")
    with open(gaw, "w") as f:
        f.write("GOOGLE_ADS_CREDENTIAL_ROLE=write\n"
                "GOOGLE_ADS_DEVELOPER_TOKEN=placeholder-not-a-token\n"
                "GOOGLE_ADS_CLIENT_ID=placeholder-not-a-client-id\n"
                "GOOGLE_ADS_CLIENT_SECRET=placeholder-not-a-secret\n"
                "GOOGLE_ADS_REFRESH_TOKEN=placeholder-not-a-token\n"
                "GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890\n"
                "GOOGLE_ADS_CUSTOMER_ID=1234567890\n")
    os.chown(gaw, 0, grp.getgrnam("hermes-broker").gr_gid)
    os.chmod(gaw, 0o640)
    # README step 2: the store and spool, the documented way.
    r = run(["python3", os.path.join(AGENT_DIR, "bin", "init-host-layout.py"),
             "--store-root", STORE, "--spool-root", SPOOL, "--apply"], env=root_env())
    if r.returncode != 0:
        raise RuntimeError("init-host-layout --apply failed:\n" + r.stdout + r.stderr)
    # The stand-in image.
    fixtures = os.path.join(HERE, "fixtures")
    run(["docker", "build", "-q", "-t", IMAGE, "-f",
         os.path.join(fixtures, "executor-standin.Dockerfile"), fixtures], check=True)
    # The Compose network. On the box the running stack created it; the proxy does not
    # allow network creation. Created here AFTER the layout exists, so Docker lays nothing
    # down as root, then the container is removed.
    r = run(["docker", "compose", "--env-file", "/dev/null", "-f",
             os.path.join(AGENT_DIR, "docker-compose.yml"), "--profile", "tools",
             "create", "ads-mutator"], env=root_env())
    if r.returncode != 0:
        raise RuntimeError("network setup failed:\n" + r.stdout + r.stderr)
    remove_mutator_containers()


def tearDownModule():
    for p in PROXIES:
        p.kill()
        p.wait()
    remove_mutator_containers()


def remove_mutator_containers():
    ids = run(["docker", "ps", "-aq", "--filter",
               "label=com.docker.compose.service=ads-mutator"]).stdout.split()
    if ids:
        run(["docker", "rm", "-f"] + ids)


def start_proxy(name, args):
    """The real proxy with ARGS (the unit's ExecStart arguments), --listen moved to a test
    socket whose group is hermes-rail, as the unit's Group=hermes-rail makes it on the box."""
    os.makedirs(SOCK_DIR, exist_ok=True)
    os.chmod(SOCK_DIR, 0o755)
    sock = os.path.join(SOCK_DIR, name + ".sock")
    log = os.path.join(SOCK_DIR, name + ".log")
    args = list(args)
    i = args.index("--listen")
    args[i + 1] = sock
    p = subprocess.Popen(["python3", os.path.join(AGENT_DIR, "bin", "docker-create-proxy.py")]
                         + args, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    PROXIES.append(p)
    for _ in range(200):
        if os.path.exists(sock):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("proxy %s never created its socket; log:\n%s" % (name, open(log).read()))
    os.chown(sock, 0, grp.getgrnam("hermes-rail").gr_gid)
    return sock, log


def unit_proxy():
    """ONE proxy with the unit's own flags, shared by every class (two would fight over one
    socket path and truncate one log)."""
    if not _UNIT_PROXY:
        _UNIT_PROXY.append(start_proxy("unit", BA.unit_exec_args(PROXY_UNIT)))
    return _UNIT_PROXY[0]


def broker_env(sock, **over):
    """hermes-broker.service's Environment=, DOCKER_HOST pointed at SOCK, HOME as systemd
    would set it for this user (from passwd; the directory does not exist)."""
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
           "HOME": pwd.getpwnam("hermes-broker").pw_dir}
    env.update(UNIT_ENV)
    env["DOCKER_HOST"] = "unix://" + sock
    env.update(over)
    return env


def log_after(log, offset):
    with open(log) as f:
        f.seek(offset)
        return f.read()


class BrokerPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sock, cls.log = unit_proxy()

    def wrapper(self, sock, log, **over):
        offset = os.path.getsize(log)
        r = run(BROKER + [os.path.join(AGENT_DIR, "run-ads-mutate.sh")] + CMD,
                env=broker_env(sock, **over))
        return r, r.stdout + r.stderr, log_after(log, offset)


class TestTheBrokerPath(BrokerPath):
    def test_precondition_the_kill_switch_is_absent(self):
        self.assertFalse(os.path.lexists(os.path.join(STORE, "control", "mutation-enabled")))

    def test_the_broker_path_reaches_the_executor_and_the_kill_switch_refuses(self):
        self.assertFalse(os.path.lexists(os.path.join(STORE, "control", "mutation-enabled")))
        r, out, plog = self.wrapper(self.sock, self.log)
        self.assertRegex(plog, CREATE_ALLOWED, "proxy log:\n%s\nwrapper:\n%s" % (plog, out))
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("mutation is disabled", out)

    def test_the_static_model_matches_real_compose(self):
        """bind_agreement's model (verbatim absolute sources, bare -> :rw) against what real
        Compose puts in HostConfig.Binds, and both against the proxy unit's pins."""
        remove_mutator_containers()
        r = run(["docker", "compose", "--env-file", "/dev/null", "-f",
                 os.path.join(AGENT_DIR, "docker-compose.yml"), "--profile", "tools",
                 "create", "ads-mutator"], env=root_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        cid = run(["docker", "ps", "-aq", "--filter",
                   "label=com.docker.compose.service=ads-mutator"]).stdout.split()[0]
        binds = run(["docker", "inspect", "--format", "{{json .HostConfig.Binds}}", cid],
                    check=True).stdout
        remove_mutator_containers()
        real = sorted(json.loads(binds))
        compose_text = open(os.path.join(AGENT_DIR, "docker-compose.yml"), encoding="utf-8").read()
        self.assertEqual(real, sorted(BA.compose_binds(compose_text, UNIT_ENV)))
        self.assertEqual(real, sorted(BA.allow_binds(PROXY_UNIT)))


class TestFiringControls(BrokerPath):
    def test_one_altered_allow_bind_is_refused(self):
        args = BA.unit_exec_args(PROXY_UNIT)
        altered = [BIN_PIN.replace("/bin:", "/bin-elsewhere:") if a == BIN_PIN else a
                   for a in args]
        self.assertNotEqual(altered, args, "the control did not alter the bin pin")
        sock, log = start_proxy("altered", altered)
        r, out, plog = self.wrapper(sock, log)
        self.assertRegex(plog, CREATE_DENIED, plog)
        self.assertIn("bind set does not match", plog)
        self.assertNotEqual(r.returncode, 2, "a refused create must not look like the "
                                             "executor's own exit-2 refusal:\n" + out)

    def test_one_wrong_path_in_the_broker_environment_is_refused(self):
        r, out, plog = self.wrapper(self.sock, self.log,
                                    HERMES_ADS_REPO_DIR="/opt/projects/elsewhere")
        self.assertRegex(plog, CREATE_DENIED, plog)
        self.assertIn("bind set does not match", plog)
        self.assertNotEqual(r.returncode, 2, out)

    def test_without_env_file_compose_cannot_read_env(self):
        """Spike M4, kept as a control: the defect --env-file /dev/null exists to avoid."""
        offset = os.path.getsize(self.log)
        r = run(BROKER + ["docker", "compose", "-f", os.path.join(AGENT_DIR, "docker-compose.yml"),
                          "run", "--rm", "--no-deps", "-T", "ads-mutator"] + CMD,
                env=broker_env(self.sock))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("permission denied", (r.stdout + r.stderr).lower())
        self.assertNotRegex(log_after(self.log, offset), CREATE_ALLOWED)


if __name__ == "__main__":
    why = why_not_runnable()
    if why:
        print("bind-agreement: SKIPPED — %s" % why)
        sys.exit(1 if REQUIRED else 0)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = res.testsRun - len(res.skipped)
    print("bind-agreement: executed %d, skipped %d, failures %d, errors %d"
          % (executed, len(res.skipped), len(res.failures), len(res.errors)))
    if not res.wasSuccessful():
        sys.exit(1)
    if REQUIRED and (res.skipped or executed == 0):
        print("bind-agreement: HERMES_REQUIRE_LINUX_INTEGRATION=1 and not every test "
              "executed — failing", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 3: Check it locally for syntax and the skip path**

```bash
python3 -m py_compile infra/hermes-agent/deploy/bind-agreement-integration.test.py; echo "compile $?"
python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py; echo "exit $?"
HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py; echo "required exit $?"
```
Expected on darwin: compile 0; `bind-agreement: SKIPPED — not Linux`, exit 0; with the variable
set, the same line and exit 1. The last one is the firing control for "a skip must fail when
required".

- [ ] **Step 4: Add the CI job**

In `.github/workflows/ci.yml`, add this job after the `tests` job (same indentation as `tests:`):

```yaml
  bind-agreement:
    name: Bind agreement (root, Linux, real proxy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      # F9: ads-mutator's real binds, through the real proxy started with the unit's own
      # flags, driven as hermes-broker through run-ads-mutate.sh to the real executor, which
      # must refuse (kill switch absent). Its own job, not a step in `tests`: F10 Tier 2 also
      # creates users and paths as root. HERMES_REQUIRE_LINUX_INTEGRATION=1 turns any skip
      # into a failure — read "executed N" on the PR run AND on the merge commit.
      - name: Bind agreement integration
        run: sudo env HERMES_REQUIRE_LINUX_INTEGRATION=1 python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py
```

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/deploy/fixtures/executor-standin.Dockerfile \
  infra/hermes-agent/deploy/bind-agreement-integration.test.py .github/workflows/ci.yml
git commit -m "test(hermes): F9 Tier 2 — the broker path through the real proxy, on Linux CI

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Run it on Linux CI: draft PR (ask the operator first)**

CI runs only on pull requests to `main` (spec R3). Opening a PR is outward-facing, so **ask the
operator before pushing or opening it.** Then:

```bash
git push -u origin fix/f9-bind-paths
gh pr create --draft --base main --title "fix(hermes): F9 — executor bind paths vs the proxy allow-list" \
  --body "Draft: running the new bind-agreement job. Full description on ready-for-review.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Wait for the run, then read the count **from the log**, not from the green tick:

```bash
id=$(gh run list --branch fix/f9-bind-paths --workflow CI --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$id" --exit-status; echo "watch exit $?"
gh run view "$id" --log | grep -E 'bind-agreement: (executed|SKIPPED)'
```
Expected: `bind-agreement: executed 6, skipped 0, failures 0, errors 0`, plus layout-integration
still `executed 22, skipped 0`.

**If the positive test fails, do not adjust the test to pass. Read the output:**
- A failure inside `docker` about `HOME` or a config directory is a **real box defect** (the
  broker's `HOME` from passwd does not exist). Stop and report it to the operator. Do not
  set `HOME` to a writable directory in the test to make it pass.
- A proxy `DENY` on a new endpoint means Compose's Linux endpoint set differs from what the
  proxy allows. Stop and report it. Do not widen the proxy.
- A pre-flight refusal means the layout the test built disagrees with what
  `preflight-governance-access.py` expects. Compare with `layout-integration.test.py`'s
  `test_preflight_passes_as_the_broker_on_a_fresh_store`, fix the **test's** setup if it
  diverges from README step 2, and report which.

---

### Task 5: Runbook and README

**Files:**
- Modify: `infra/hermes-agent/README.md` (VPS deploy sequence step 2, ~lines 1058-1108; a new "Executor bind sources" subsection right after the spool section that ends near line ~752)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (Phase 3 key list ~line 265; Phase 5 ~lines 336-395; Phase 6 ~lines 397-416)

**Interfaces:**
- Consumes: the variable names and values from Task 2; the executor's refusal text
  `mutation is disabled` (`apply-changeset.py:95`).
- Produces: documentation only.

- [ ] **Step 1: README step 2, the two new `.env` keys**

In README "VPS deploy sequence" step 2, replace the paragraph **Make sure `.env` sets the spool.**
and its code block with:

````markdown
   **Make sure `.env` sets the spool and the executor bind sources.** A `.env` copied from
   `.env.example` already has all three; an older one does not. Compose interpolates the whole
   file, so every `docker compose` command stops without them. `.env` is root `600`, and these
   lines add each key only when it is missing, without printing the file:

   ```bash
   sudo grep -q '^HERMES_SPOOL_DIR=' .env    || echo 'HERMES_SPOOL_DIR=/var/lib/hermes/spool' | sudo tee -a .env >/dev/null
   sudo grep -q '^HERMES_AGENT_DIR=' .env    || echo 'HERMES_AGENT_DIR=/opt/hermes-agent' | sudo tee -a .env >/dev/null
   sudo grep -q '^HERMES_ADS_REPO_DIR=' .env || echo 'HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads' | sudo tee -a .env >/dev/null
   ```
````

In the **box from the first bring-up (2026-09-21)** list in the same step, change item 2 to:
`2. Add HERMES_SPOOL_DIR, HERMES_AGENT_DIR and HERMES_ADS_REPO_DIR to .env with the non-printing lines above.`
and change the sentence before the list from "its `.env` predates `HERMES_SPOOL_DIR`" to
"its `.env` predates `HERMES_SPOOL_DIR`, `HERMES_AGENT_DIR` and `HERMES_ADS_REPO_DIR`".

- [ ] **Step 2: README, the "Executor bind sources" subsection**

Add after the spool section (use the same heading level as the spool section's heading):

```markdown
### Executor bind sources (F9)

`ads-mutator` is the only container created through the allow-list proxy, and the proxy
refuses any create whose bind set is not **exactly** the `--allow-bind` set in
`deploy/hermes-docker-proxy.service`. So every `ads-mutator` source is an absolute path from a
`:?`-guarded variable: `HERMES_GOVERNANCE_DIR`, `HERMES_AGENT_DIR`, `HERMES_ADS_REPO_DIR`.
Compose sends an absolute source verbatim. A relative one (`./bin`) would be joined to a
project directory whose spelling depends on how Compose was started, which is how F9 happened
(spec `docs/superpowers/specs/2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md` §2).

On a VPS the broker runs the executor, and `hermes-broker.service` sets the values. They
equal the proxy's pins, and `proxy-policy-sync.test.py` fails if they drift.
`run-ads-mutate.sh` passes `--env-file /dev/null`, because `hermes-broker` cannot read `.env`
and must not (it holds `ANTHROPIC_API_KEY`). `.env` still needs the same keys for the
operator's own `docker compose` commands (step 2). On a laptop, `.env` supplies them and
`hostenv.sh` passes them on. Any paths that point at this directory and at the ads repo
checkout work.
```

- [ ] **Step 3: BRING-UP Phase 3, the key list**

In BRING-UP Phase 3, change the sentence "`HERMES_GOVERNANCE_DIR` already defaults to
`/var/lib/hermes/governance` in the example, and `HERMES_SPOOL_DIR` to `/var/lib/hermes/spool`."
to "`.env.example` already sets `HERMES_GOVERNANCE_DIR`, `HERMES_SPOOL_DIR`, `HERMES_AGENT_DIR`
and `HERMES_ADS_REPO_DIR` to the box's paths." and change the verify comment
`# ANTHROPIC_API_KEY, HERMES_GOVERNANCE_DIR, HERMES_SPOOL_DIR` to
`# ANTHROPIC_API_KEY, HERMES_GOVERNANCE_DIR, HERMES_SPOOL_DIR, HERMES_AGENT_DIR, HERMES_ADS_REPO_DIR`.

- [ ] **Step 4: BRING-UP, remove the old Phase 5 and renumber**

Delete the whole `## Phase 5: Measure the Bind Paths` section (heading through its trailing
`---`). Its 2026-09-21 result moves to the findings record in Task 6. Rename
`## Phase 6: Hand Off` to `## Phase 5: Hand Off`. Steps 5 and 6 then add the new Phase 6 and
the Gate after it. `## Phase 7: Reach the Dashboard From the Laptop` keeps its number. The
resulting order is:

`Phase 4` → `Phase 5: Hand Off` → `Phase 6: Confirm the Bind Agreement` →
`Gate: First Approved Request (Rehearsal)` → `Phase 7: Reach the Dashboard From the Laptop`.

After Steps 5 and 6, fix every reference that meant the old numbers:
`grep -n 'Phase [5-7]' infra/hermes-agent/deploy/BRING-UP.md` and
`grep -rn 'Phase 5\|Phase 6' infra/hermes-agent/README.md docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`.
A reference to "Phase 5" that meant the old measuring instrument now points at Phase 6
(Confirm). A reference to "Phase 6" that meant unit installation now points at Phase 5 (Hand
Off). Leave the findings record's historical outcome table rows to Task 6.

- [ ] **Step 5: BRING-UP, the new Phase 5 banner (was Phase 6)**

Replace the `**Blocked on F9 only** …` paragraph of the Hand Off phase with:

```markdown
**Not blocked.** Installing and verifying the units creates no container: the proxy only opens
its socket at start, the broker's `ExecStartPre` checks make no Docker call, and the
`curl …/version` probe is on the proxy's allow-list (F9 spec §3.1). The store and spool layout
(F10) is landed, and README step 1 (users and groups) was run and verified on 2026-09-21.
```

Change the line "Once the bind paths match (or are reconciled), hand off to:" to "Hand off to:".

- [ ] **Step 6: BRING-UP, the new Phase 6 (Confirm the Bind Agreement)**

Insert after the Hand Off phase:

````markdown
## Phase 6: Confirm the Bind Agreement

**Run this only after README "VPS deploy sequence" steps 2–5**: the store exists, both units
run, and the kill switch is **absent**. CI already proved the agreement on Linux (the
`bind-agreement` job). This confirms it on the box's own Compose version and real image, on
the broker's real path: as `hermes-broker`, through the proxy socket, with the broker unit's
environment and `--env-file /dev/null`. The ids are dummies. The executor checks the kill
switch before it reads anything else, so this cannot touch an account.

```bash
sudo -u hermes-broker env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  HOME="$(getent passwd hermes-broker | cut -d: -f6)" \
  DOCKER_HOST=unix:///run/hermes/docker-proxy.sock \
  HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance HERMES_AGENT_DIR=/opt/hermes-agent \
  HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads HERMES_SPOOL_DIR=/var/lib/hermes/spool \
  docker compose --env-file /dev/null -f /opt/hermes-agent/docker-compose.yml \
  run --rm --no-deps -T ads-mutator \
  --client slug-1 --changeset 20260922-120000-abcdef01 --request 00000000-0000-4000-8000-000000000000
echo "rc=$?"
sudo journalctl -u hermes-docker-proxy --since "-5 min" --no-pager | grep 'containers/create'
```

Expected: `rc=2`, output containing `mutation is disabled`, and a journal line
`ALLOW POST /v…/containers/create`. The values in the command are the ones in
`hermes-broker.service`; if you changed the unit, use its values.

**On anything else:** stop and record it. A `DENY … bind set does not match` means the box's
Compose sends different strings than CI measured. Do not widen the allow-list. A refusal is a
refusal, not a breach, and widening a policy to make bring-up pass is the reflex this runbook
exists to prevent. Never run the old `sudo docker compose --profile tools create ads-mutator`
instrument. Run as root from the working directory, Compose resolves the symlink the broker
does not (F9 spec §2, M6), and before README step 2 it makes Docker create governance
directories as root.

---

## Gate: First Approved Request (Rehearsal)

This gate is not run by this runbook. It sits between Phase 6 and anything that touches the
kill switch. **It needs:** F9 (landed), F12 (a working approval writer: `approve-changeset.py`
cannot reach `data/vaults` as `hermes-broker` today), `.env.gaw` with the write credential, and
Phase 6 passed.

**The proof:** with the kill switch **absent**, a human-approved request goes broker → proxy →
container and comes back `refused_preflight` ("mutation is disabled"). That exercises the
broker's own path (reservation, the wrapper, persistence), which Phase 6 does not.

**Still required before the kill switch can be created:** F12, F14 (a Compose failure is
reported as "refused, nothing was mutated", which could be false mid-run), and the §6
hardening gates.

---
````

- [ ] **Step 7: Check the runbook renders and references resolve**

```bash
grep -n '^## ' infra/hermes-agent/deploy/BRING-UP.md
grep -n 'Phase [0-9]' infra/hermes-agent/deploy/BRING-UP.md
grep -n 'profile tools create ads-mutator' infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
```
Expected: headings in order (… Phase 4, Phase 5 Hand Off, Phase 6 Confirm, Gate, Phase 7 …); every
`Phase N` reference points at the right section; the old instrument appears only inside the
"Never run the old … instrument" sentence.

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/README.md infra/hermes-agent/deploy/BRING-UP.md
git commit -m "docs(hermes): F9 — bind confirmation after the units, Phase 5 unblocked, rehearsal gate

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Findings record and handoff correction

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (outcome table ~lines 12-26; F9 ~lines 101-127; add F14 after F12 ~line 202; open items ~line 214)
- Modify: `docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md` (a note at the top)

**Interfaces:**
- Consumes: the draft PR number from Task 4 Step 6 (written `#<N>` below; replace it).
- Produces: documentation only.

- [ ] **Step 1: F9, fixed, with the correction**

Change the F9 heading to
`### F9: the bind paths do not match the proxy allow-list — fixed (PR #<N>)`
and append to the end of the F9 entry (after its **Open:** paragraph, which becomes history, so
prefix that paragraph with `**Was open:**` instead of `**Open:**`):

```markdown
**Correction (2026-09-22, measured on Linux CI).** The measurement above was partly caused by how
it was taken. `sudo docker compose` run from the working directory has no `PWD`, so Compose
takes the resolved path as its project directory. The broker's real path
(`run-ads-mutate.sh`, `-f /opt/hermes-agent/docker-compose.yml`) sends `/opt/hermes-agent/bin`
and `/opt/hermes-agent/registry`, which match the pins, and `/claude-google-ads`, which does not.
No invocation matched all seven. The root cause was the relative sources. See spec
`2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md` §2, M1 and M6.

**Fix (PR #<N>).** Every `ads-mutator` source is an absolute `:?`-guarded variable, set by the
broker unit and equal to the proxy's pins. The allow-list and the proxy are unchanged.
`proxy-policy-sync.test.py` compares the strings on every platform, and the CI job
`bind-agreement` drives the broker's path through the real proxy on Linux.

**Second defect on the same path, fixed in the same PR.** `hermes-broker` cannot read `.env`
(`600 root:root`), and Compose aborts on an unreadable `.env` even when every variable is
exported (M4). `run-ads-mutate.sh` now passes `--env-file /dev/null`, and the broker unit
supplies the variables. The handoff's first half was wrong: `hostenv.sh` never read `.env` as
the broker, because the unit already sets `HERMES_GOVERNANCE_DIR`.

**Remaining:** the box confirmation (BRING-UP Phase 6) on the box's own Compose and real image.
```

- [ ] **Step 2: F14**

Add after the F12 entry:

```markdown
### F14: a Compose failure is reported as "refused, nothing was mutated" (recorded, not fixed)

`docker compose run` exits 1 on any Compose-level failure. Two such failures were measured on
Linux CI (2026-09-22): a proxy refusal at create, and an unreadable `.env`. The broker maps
exit 1 to `refused_usage`, whose detail says "nothing was mutated" (`hermes-broker.py`,
`CLASSIFICATION_BY_RC` / `DETAIL_BY_CLASSIFICATION`). For a refusal at create, that is true.
If Compose loses the proxy connection **after** the container started, it may also return 1
while the executor is mid-apply, and the broker would promise "nothing was mutated" about a run
that may have changed the account. That goes around the exit-2 guarantee in
`apply-changeset.py`. **Inferred, not measured.** It gates the kill switch, not the rehearsal:
the kill switch is absent there, so nothing can be mutated. **Open:** a distinct wrapper exit
code for "Compose failed before the container started", designed in its own PR (F9 spec §3.7,
§5).
```

- [ ] **Step 3: The outcome table and open items**

In the outcome table, change the Phase 5 row to
`| 5 Bind paths | **fixed in the repo** (F9, PR #<N>); box confirmation pending (BRING-UP Phase 6) |`
and the Phase 6 row to
`| 6 Units | **not blocked** — README step 1 done and verified; F10 landed (PR #35); F9 does not gate unit installation |`.

In **Open items, in order**, replace item 1 with
`1. BRING-UP Phase 6: confirm the bind agreement on the box, after README steps 2–5.`
and append
`6. F14: Compose failures reported as "nothing was mutated". Gates the kill switch.`

- [ ] **Step 4: The handoff correction note**

In `docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md`, insert after the
first `---` line:

```markdown
> **Correction (2026-09-22, after the F9 session).** Two premises below were wrong. See the spec
> `docs/superpowers/specs/2026-09-22-f9-bind-paths-and-proxy-allow-list-design.md`.
> 1. "No container is created until an accepted apply, and that needs the kill switch." The
>    kill switch is checked **inside** the container (`apply-changeset.py:94`). A container is
>    created for any broker-accepted request that has a human approval (spec §3.1).
> 2. "`hostenv.sh` fails to read `.env` as the broker, and the R4 guard refuses." The broker
>    unit sets `HERMES_GOVERNANCE_DIR`, so `hostenv.sh` never reads `.env`. The real failure is
>    Compose itself, which aborts on the unreadable file (spec §2, M4).
> The measured F9 was also partly caused by how it was taken (spec §2, M6).
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md \
  docs/superpowers/handoffs/2026-09-22-f9-bind-paths-and-proxy-allow-list.md
git commit -m "docs(hermes): F9 fixed with its correction; the .env defect; F14 recorded

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Brain session entry (left unstaged)

**Files:** `.project-brain/sessions/daily/2026-09-22.md`, via the `brain-capture` skill. **Never staged or committed.**

- [ ] **Step 1: Capture a decision entry with the `brain-capture` skill**

Invoke the `brain-capture` skill with a `[decision]` entry whose text is:

> F9 design landed on branch fix/f9-bind-paths (PR #<N>): ads-mutator's bind sources are absolute
> :?-guarded variables set by the broker unit and equal to the proxy's unchanged pins; the wrapper
> passes --env-file /dev/null so hermes-broker never needs .env. Measured on Linux CI: the
> 2026-09-21 box mismatch was partly an artifact of `sudo docker compose` from the cwd (no PWD →
> resolved project dir). SUPERSEDES the canon line "F9 is the only blocker for Phase 6": F9 never
> blocked unit installation (no container is created at unit start); the new gate is "first
> approved request (rehearsal)", which needs F9 + F12 + .env.gaw. F14 recorded: compose exit 1
> is reported as "nothing was mutated". Candidate for brain-promote --approve.

- [ ] **Step 2: Confirm it is not staged**

Run: `git status --short .project-brain/ | head -5; git diff --cached --name-only`
Expected: the daily file shows as modified or untracked; `--cached` lists nothing under `.project-brain/`.

---

### Task 8: Final review, PR ready, merge, and cleanup

- [ ] **Step 1: Full local suites (no `tail`)**

```bash
nlog=$(mktemp); node scripts/run-all-tests.js > "$nlog" 2>&1; echo "node exit $?"; grep -E 'suites passed' "$nlog"
blog=$(mktemp); infra/hermes-agent/bin/run-bin-tests.sh > "$blog" 2>&1; echo "bin exit $?"; grep -E 'suites passed' "$blog"
python3 infra/hermes-agent/deploy/units.test.py; echo "units exit $?"
python3 infra/hermes-agent/deploy/provision.test.py; echo "provision exit $?"
python3 infra/hermes-agent/deploy/layout-integration.test.py; echo "tier2 exit $?"
python3 infra/hermes-agent/deploy/bind-agreement-integration.test.py; echo "f9 tier2 exit $?"
```
Expected: node 22/22, bin 31/31, units OK, provision OK, both Tier 2 suites `SKIPPED — not Linux`
with exit 0. Every exit 0. Record the actual counts.

- [ ] **Step 2: Final whole-branch review**

Dispatch a fresh reviewer (`superpowers:requesting-code-review`) over `git diff origin/main...HEAD`
with the spec and this plan. F10's final review caught two defects the task reviews missed, so
this step is not optional. Fix what it confirms, re-run Step 1, and commit the fixes by explicit
path.

- [ ] **Step 3: Redaction scan over added lines only, with a live control**

```bash
added=$(git diff origin/main...HEAD -U0 | grep '^+' | grep -v '^+++')
printf '%s\n' "$added" | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b' \
  | grep -vE '"?(1234567890|9998887776|9999999999)"?'; echo "scan exit: $?"
printf 'control: customer 5551234567 and 555-123-4567\n' \
  | grep -niE 'dentaledge|[0-9]{3}-[0-9]{3}-[0-9]{4}|\b[0-9]{10}\b'; echo "control exit: $?"
```
Expected: the scan prints nothing and exits 1; the control prints its line and exits 0. If the
control does not fire, the pattern is dead and the scan proves nothing. Read any hit by eye.

- [ ] **Step 4: Confirm the diff holds only this plan's files**

Run: `git diff --stat origin/main...HEAD`
Expected: the files in the file map, plus the spec and this plan. Nothing under `.project-brain/`,
`evals/`, `CLAUDE.md`, or the spike's `f9-spike.*` files.

- [ ] **Step 5: Fill in the PR number, push, mark ready (ask the operator first)**

Replace every `#<N>` in the findings record with the draft PR's number, commit that file by
explicit path, and push. Then write the PR body. It must state:
- what landed (Tasks 1–6), and that `deploy/hermes-docker-proxy.service` and the proxy are unchanged;
- the spike's finding that the recorded F9 was partly caused by how it was measured;
- the `.env` defect, fixed; F14, recorded, not fixed;
- the **local `.env` consequence**: `HERMES_AGENT_DIR` and `HERMES_ADS_REPO_DIR` are now required
  by every `docker compose` command (the operator adds them to the laptop's `.env`);
- the 2026-09-21 box's upgrade (README step 2 list);
- that nothing touched the VPS and the kill switch is absent;
- what stays unproven until the box (BRING-UP Phase 6: the box's Compose version, the real image,
  the broker's `HOME`, systemd itself);
- the `bind-agreement` executed count from the PR run.

End the body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Then
`gh pr edit <N> --body-file <body>` and `gh pr ready <N>`.

- [ ] **Step 6: Ask about the required check**

Ask the operator whether to add `Bind agreement (root, Linux, real proxy)` to `main`'s required
status checks. It's a settings change on their account; do not make it unasked.

- [ ] **Step 7: After the operator merges: CI on the merge commit**

```bash
sha=$(gh pr view <N> --json mergeCommit -q .mergeCommit.oid)
id=$(gh run list --commit "$sha" --workflow CI --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$id" --exit-status; echo "watch exit $?"
gh run view "$id" --log | grep -E '(bind-agreement|layout-integration): (executed|SKIPPED)'
```
Expected: both lines `executed N, skipped 0`, run green. Quote both counts to the operator.

- [ ] **Step 8: Delete the spike branch**

```bash
git push origin --delete spike/f9-measure
git branch -D spike/f9-measure
```
