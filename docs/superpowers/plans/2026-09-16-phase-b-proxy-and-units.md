# Phase B Implementation Plan — socket proxy and systemd units

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a compromised mutation broker from reaching host root, by putting a body-inspecting allow-list proxy in front of the Docker socket and running the broker outside the docker group.

**Architecture:** A stdlib-only Unix-socket proxy terminates the Docker Engine API, decides allow/deny per request with a pure function, and forwards only what the mutation rail legitimately needs. Two systemd units separate the one component that touches the real socket (the proxy, in the docker group) from the one that drains the spool (the broker, deliberately not). The proxy pins `Image`, `Entrypoint`, `User`, the `Cmd` flags, the `Binds` set, and `HERMES_GOVERNANCE_ROOT`, because the executor has exactly one writable mount and anything that redirects trust into it is a hole.

**Tech Stack:** Python 3 stdlib only (`socket`, `socketserver`, `http.client`, `json`, `re`), `unittest`, systemd unit files, Docker Engine API over a Unix socket.

**Spec:** `docs/superpowers/specs/2026-09-16-phase-b-proxy-and-units-design.md`
**Brief:** `docs/superpowers/specs/2026-09-16-phase-b-brief.md`
**Amends:** `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md` — **Task 10 at `:2740`, Task 11 at `:3027`.** Those tasks stand where this plan is silent; where they disagree, this plan wins.

## Global Constraints

- **Python 3 stdlib only** under `infra/hermes-agent/bin/` — the proxy included. No new dependency may enter on this path. (YAML is **not** stdlib: the proxy must never parse `docker-compose.yml`.)
- **Exactly one trailing `unittest.main()`** per test file.
- **Fail closed** — an unparseable body refuses and is never forwarded.
- **Deny by default** — anything not explicitly allowed is refused.
- No client names, customer ids, campaign ids, or credential values. Sanctioned invented fixtures: `acme-dental`, `acme`, `other-clinic`, `slug-1`, `"1234567890"`, `"9998887776"`, `"9999999999"`.
- **NEVER run `docker compose config`** — it renders `env_file` secrets in cleartext.
- **`--log-only` must not survive into the unit.** *A proxy with a bypass flag is not a proxy.*
- The kill switch is the **file** `~/.hermes/governance/control/mutation-enabled` and stays absent.
- Stage by explicit path only. NEVER `git add -A`, `git add .`, `git add .project-brain/`, `git add evals/`. The tree carries **5 tracked and 44 untracked pre-existing entries** that are not yours; leave every one exactly as it is, including `.project-brain/reports/compile/2026-09-04.json` (a hook artifact — do not stage it, do not delete it).
- `cmd | tail` takes its exit status from `tail`. Capture into a variable (`out=$(cmd 2>&1); rc=$?`) or use `PIPESTATUS`.
- Bash working directory persists between tool calls. Start each command with an explicit `cd`, or use absolute paths.
- **AF_UNIX paths cap at ~104 bytes.** Put test sockets in `/tmp/<short>.sock`, never in a long scratchpad path — measured 2026-09-16: `OSError: AF_UNIX path too long`.
- Container probe stores use in-container `mktemp -d` or a named volume, **never a bind mount** — Docker Desktop does not preserve `chown`'d ownership across one, so an unsafe layout can read as safe.
- **`main` is protected — land via PR, and CHECK CI AFTER PUSHING.** Local darwin runs fewer tests than the Linux runner: `applies()` gates real logic off and `main()` returns 0 before `check()` runs, so platform-gated tests pass vacuously off Linux. That cost ten days of a silently-red PR on S3-b.
- Baselines: `infra/hermes-agent/bin/run-bin-tests.sh` → 25/25 exit 0; `node scripts/run-all-tests.js` → 22/22 exit 0.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `infra/hermes-agent/bin/docker-create-proxy.py` | The proxy: `decide()` (pure policy) + keep-alive-aware socket plumbing. The one component whose compromise is worst, so it stays small enough to audit in one sitting. | 2, 3 |
| `infra/hermes-agent/bin/docker-create-proxy.test.py` | Exhaustive `decide()` tests, every refusal paired with a positive control. | 2, 3 |
| `infra/hermes-agent/bin/proxy-policy-sync.test.py` | Asserts the proxy's constants still match `docker-compose.yml` and `hermes-broker.py`'s argv, and that `seen/` is absent from the binds. | 4 |
| `infra/hermes-agent/deploy/hermes-docker-proxy.service` | Proxy unit. Runs as the only user touching the real socket. | 5 |
| `infra/hermes-agent/deploy/hermes-broker.service` | Broker unit. Deliberately **not** in the docker group. | 5 |
| `infra/hermes-agent/deploy/units.test.py` | Asserts unit *content* — and says in its docstring that this is not a behavioural proof. | 5 |
| `infra/hermes-agent/README.md` | The VPS deploy sequence, including bootstrap-before-enable and the group memberships. | 6 |
| `docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md` | Task 1's measured endpoint set and create body — the ground truth the policy is written against. | 1 |

---

## Task 1: MEASURE the endpoint set and the create body

Everything downstream is written against this. **Do not skip it and do not inherit the existing D1 table** — D1 was measured on 2026-08-31 against a different Compose version, and per R22 a darwin measurement says nothing about Linux.

**Files:**
- Create: `docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md`
- Create (throwaway, NOT committed): a logging pass-through

**Interfaces:**
- Consumes: nothing.
- Produces: the measured endpoint list and the verbatim `POST /containers/create` body that Tasks 2–4 are written against.

- [ ] **Step 1: Write a keep-alive-aware logging pass-through**

**This is the part that goes wrong.** The Docker CLI uses HTTP keep-alive: **many requests share one connection.** A pass-through that reads one request and then splices the rest of the connection logs only the first and silently misses the others.

Measured 2026-09-16 while writing this plan: a first-request-only pass-through logged **3** calls and a partially-fixed one logged **5**, against D1's **14**. Both looked like they had worked.

Write it to loop: parse request line and headers, read exactly `Content-Length` bytes, log, forward, relay the response, **then loop for the next request on the same connection**. Treat `/attach` specially — it upgrades to a bidirectional stream and must be pumped, not parsed.

Put the socket at `/tmp/hbproxy.sock`. Long paths fail with `OSError: AF_UNIX path too long`.

- [ ] **Step 2: Run one real invocation through it**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent
export HERMES_GOVERNANCE_DIR=$(mktemp -d)
mkdir -p "$HERMES_GOVERNANCE_DIR"/{approvals,control,registry,log}
DOCKER_HOST=unix:///tmp/hbproxy.sock timeout 90 docker compose -f docker-compose.yml \
    run --rm --no-deps -T ads-mutator --help >/dev/null 2>&1
echo "exit: $?"
```

- [ ] **Step 3: Sanity-check the measurement before trusting it**

Count the calls. **If the total is far below D1's 14, your pass-through is dropping requests — fix it and re-measure.** A short list is the failure mode, not a result. Confirm `POST /containers/create` appears; if it does not, no container was created and the run proved nothing (a stale container from an earlier attempt can cause this — `docker ps -a` and remove leftovers).

- [ ] **Step 4: Record the measurement**

Write `docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md` containing: the date, the Compose and Engine versions, the full normalised endpoint list with counts, and the **verbatim create body** pretty-printed. Then answer these four questions explicitly, because Tasks 2–4 depend on them:

1. Does the body carry a `User` field, and what is its value? **The design PREDICTS it is absent or empty** (`Dockerfile:38` sets `USER hermes` and compose does not override) — **this is a prediction, not a measurement.** If it is present, say so and Task 2's check must match reality.
2. Are binds in `HostConfig.Binds`, or `HostConfig.Mounts`? (Measured 2026-09-16 for the plain `docker` CLI: `Binds` used, `Mounts` null. Compose may differ, and the design blocks `Mounts` outright — if Compose uses `Mounts`, that block would break the rail and Task 2 must be re-thought.)
3. What are the seven bind sources **as resolved absolute paths**? Three are relative in compose (`../../../claude-google-ads`, `./registry`, `./bin`) and Compose resolves them before sending.
4. What API version prefix appears? (Observed 2026-09-16: `/v1.55/`.)

Add this closing line: *"Measured under Docker Desktop on darwin. Per R22 this says nothing about the VPS; Task 10's allow-list must be re-measured there before deploy."*

- [ ] **Step 5: Commit the evidence, not the throwaway**

```bash
cd /Users/ericksicard/Projects/claude_code
git add docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md
git commit -m "docs(hermes): measure the Docker endpoint set and create body for Phase B"
```

---

## Task 2: `decide()` — the pure policy function

**Files:**
- Create: `infra/hermes-agent/bin/docker-create-proxy.py`
- Create: `infra/hermes-agent/bin/docker-create-proxy.test.py`

**Interfaces:**
- Consumes: Task 1's measured create body and endpoint list.
- Produces: `decide(method, path, body) -> (bool, str)`; module constants `ALLOWED`, `FORBIDDEN_HOSTCONFIG`, `PINNED_ENTRYPOINT`, `ALLOWED_CMD_FLAGS`; and `configure(image, binds, governance_root)` which sets the pinned values at startup. Task 3 consumes `decide`; Task 4 consumes the constants.

- [ ] **Step 1: Write the failing tests**

Create `infra/hermes-agent/bin/docker-create-proxy.test.py`. Every refusal is paired with a positive control — a refusal-only suite would pass against a proxy that refuses everything, which breaks the rail and is the failure this project has recorded before (Task 12's seam S4).

```python
import importlib.util, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PX = _load("docker_create_proxy", "docker-create-proxy.py")

GOV = "/var/lib/hermes/governance"
PROJ = "/opt/hermes-agent"
BINDS = [
    ("%s/approvals" % GOV, "/opt/governance/approvals", "ro"),
    ("%s/control" % GOV, "/opt/governance/control", "ro"),
    ("%s/registry" % GOV, "/opt/governance/registry", "ro"),
    ("%s/log" % GOV, "/opt/governance/log", "rw"),
    ("/opt/projects/claude-google-ads", "/projects/claude_google_ads", "ro"),
    ("%s/registry" % PROJ, "/opt/registry", "ro"),
    ("%s/bin" % PROJ, "/opt/cc-bin", "ro"),
]


def _binds_payload(overrides=None):
    out = []
    for src, dst, mode in BINDS:
        out.append("%s:%s:%s" % (src, dst, mode))
    return overrides if overrides is not None else out


def _create_body(**over):
    body = {
        "Image": "hermes-agent-claude",
        "Entrypoint": ["python3", "/opt/cc-bin/apply-changeset.py"],
        "Cmd": ["--client", "acme-dental",
                "--changeset", "20260101-000000-deadbeef",
                "--request", "00000000-0000-0000-0000-000000000000"],
        "Env": ["HERMES_GOVERNANCE_ROOT=/opt/governance",
                "GOOGLE_ADS_DEVELOPER_TOKEN=x"],
        "HostConfig": {"Binds": _binds_payload()},
    }
    body.update(over)
    return json.dumps(body).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance")

    def allow(self, body=None, path="/v1.55/containers/create", method="POST"):
        return PX.decide(method, path, body if body is not None else _create_body())


class TestPositiveControls(Base):
    """Without these, every refusal below would also pass against a proxy that
    refuses everything — which breaks the rail and is the failure mode this
    project has already shipped once (Task 12's seam S4)."""

    def test_the_real_create_is_allowed(self):
        ok, why = self.allow()
        self.assertTrue(ok, why)

    def test_each_allowed_endpoint_is_allowed(self):
        for method, path in (
            ("HEAD", "/_ping"),
            ("GET", "/v1.55/version"),
            ("GET", "/v1.55/images/hermes-agent-claude/json"),
            ("POST", "/v1.55/containers/abc123/start"),
            ("POST", "/v1.55/containers/abc123/attach"),
            ("POST", "/v1.55/containers/abc123/wait"),
            ("GET", "/v1.55/containers/abc123/json"),
            ("GET", "/v1.55/containers/json"),
            ("DELETE", "/v1.55/containers/abc123"),
        ):
            ok, why = PX.decide(method, path, b"")
            self.assertTrue(ok, "%s %s refused: %s" % (method, path, why))


class TestEndpointAllowList(Base):
    def test_an_unlisted_endpoint_is_refused(self):
        ok, why = PX.decide("POST", "/v1.55/build", b"")
        self.assertFalse(ok)
        self.assertIn("allow-list", why)

    def test_exec_create_is_refused(self):
        """docker exec into the running executor would be arbitrary code with the
        rail's own mounts."""
        ok, _ = PX.decide("POST", "/v1.55/containers/abc123/exec", b"")
        self.assertFalse(ok)

    def test_a_traversal_path_is_refused(self):
        ok, why = PX.decide("POST", "/v1.55/containers/create/../../build", b"")
        self.assertFalse(ok)
        self.assertIn("traversal", why)


class TestImageAndEntrypoint(Base):
    def test_a_different_image_is_refused(self):
        ok, why = self.allow(_create_body(Image="alpine"))
        self.assertFalse(ok)
        self.assertIn("image", why)

    def test_an_overridden_entrypoint_is_refused(self):
        """THE gap this task exists to close. A pinned image whose entrypoint is
        free is arbitrary code execution in that image."""
        ok, why = self.allow(_create_body(Entrypoint=["/bin/sh", "-c", "id"]))
        self.assertFalse(ok)
        self.assertIn("entrypoint", why.lower())

    def test_a_missing_entrypoint_is_refused(self):
        body = json.loads(_create_body())
        del body["Entrypoint"]
        ok, _ = self.allow(json.dumps(body).encode())
        self.assertFalse(ok)

    def test_a_user_override_is_refused(self):
        ok, why = self.allow(_create_body(User="0"))
        self.assertFalse(ok)
        self.assertIn("user", why.lower())


class TestCmdFlags(Base):
    def test_projects_flag_is_refused(self):
        """--projects selects the file read for runner and script_dir
        (changeset_lib.read_mutate_execute), i.e. WHICH PROGRAM RUNS. log/ is the
        one writable mount, so an attacker writes a YAML there and points at it."""
        ok, why = self.allow(_create_body(
            Cmd=["--client", "acme-dental", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000",
                 "--projects", "/opt/governance/log/evil.yaml"]))
        self.assertFalse(ok)
        self.assertIn("--projects", why)

    def test_registry_flag_is_refused(self):
        ok, why = self.allow(_create_body(
            Cmd=["--client", "acme-dental", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000",
                 "--registry", "/opt/governance/log/evil.json"]))
        self.assertFalse(ok)
        self.assertIn("--registry", why)

    def test_a_malformed_slug_is_refused(self):
        ok, _ = self.allow(_create_body(
            Cmd=["--client", "../etc", "--changeset", "20260101-000000-deadbeef",
                 "--request", "00000000-0000-0000-0000-000000000000"]))
        self.assertFalse(ok)


class TestBinds(Base):
    def test_an_extra_bind_is_refused(self):
        ok, why = self.allow(_create_body(HostConfig={"Binds": _binds_payload(
            _binds_payload() + ["/etc/shadow:/x:ro"])}))
        self.assertFalse(ok)
        self.assertIn("bind", why.lower())

    def test_etc_shadow_alone_is_refused(self):
        """The old denylist matched '/etc' exactly, so '/etc/shadow' passed."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": ["/etc/shadow:/x:ro"]}))
        self.assertFalse(ok)

    def test_the_governance_store_mounted_rw_is_refused(self):
        """The worst case: it hands the governed party the approvals directory and
        the kill switch."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": [
            "%s:/opt/governance:rw" % GOV]}))
        self.assertFalse(ok)

    def test_a_permitted_source_with_rw_instead_of_ro_is_refused(self):
        """The flag is part of the match, not decoration. A read-only mount turned
        writable is the whole attack."""
        bad = ["%s:%s:rw" % (s, d) if m == "ro" else "%s:%s:%s" % (s, d, m)
               for s, d, m in BINDS]
        ok, why = self.allow(_create_body(HostConfig={"Binds": bad}))
        self.assertFalse(ok)
        self.assertIn("bind", why.lower())

    def test_the_docker_socket_is_refused(self):
        ok, _ = self.allow(_create_body(HostConfig={"Binds": [
            "/var/run/docker.sock:/var/run/docker.sock:rw"]}))
        self.assertFalse(ok)

    def test_a_missing_bind_is_refused(self):
        """Exact set: fewer is as wrong as more, because a missing :ro mount could
        be re-supplied by a symlink inside a writable one."""
        ok, _ = self.allow(_create_body(HostConfig={"Binds": _binds_payload()[:-1]}))
        self.assertFalse(ok)


class TestHostConfigAndEnv(Base):
    def test_privileged_is_refused(self):
        hc = {"Binds": _binds_payload(), "Privileged": True}
        ok, why = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)
        self.assertIn("Privileged", why)

    def test_mounts_api_is_refused(self):
        """Mounts is the newer API for the same capability — left open it bypasses
        the Binds allow-list entirely."""
        hc = {"Binds": _binds_payload(),
              "Mounts": [{"Type": "bind", "Source": "/etc", "Target": "/x"}]}
        ok, _ = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)

    def test_host_network_is_refused(self):
        hc = {"Binds": _binds_payload(), "NetworkMode": "host"}
        ok, _ = self.allow(_create_body(HostConfig=hc))
        self.assertFalse(ok)

    def test_a_redirected_governance_root_is_refused(self):
        """Left free, an attacker repoints the root at a fake store built inside
        the one writable mount."""
        ok, why = self.allow(_create_body(
            Env=["HERMES_GOVERNANCE_ROOT=/opt/governance/log/fake"]))
        self.assertFalse(ok)
        self.assertIn("HERMES_GOVERNANCE_ROOT", why)

    def test_the_credential_vars_stay_free(self):
        """POSITIVE CONTROL. They carry the credential and vary per run; a check
        that pinned them would refuse every real call."""
        ok, why = self.allow(_create_body(
            Env=["HERMES_GOVERNANCE_ROOT=/opt/governance",
                 "GOOGLE_ADS_REFRESH_TOKEN=whatever", "GOOGLE_ADS_CUSTOMER_ID=1234567890"]))
        self.assertTrue(ok, why)


class TestBodyHandling(Base):
    def test_an_unparseable_body_is_refused(self):
        ok, why = self.allow(b"{not json")
        self.assertFalse(ok)
        self.assertIn("unparseable", why)

    def test_a_non_object_body_is_refused(self):
        ok, _ = self.allow(b"[]")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 docker-create-proxy.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -8; echo "exit: $rc"
```

Expected: FAIL — `docker-create-proxy.py` does not exist.

- [ ] **Step 3: Implement `decide()` and `configure()`**

Create `infra/hermes-agent/bin/docker-create-proxy.py`. The module docstring must carry the measured endpoint list from Task 1 verbatim, with its date, and the sentence: *"Adding an endpoint is a re-measurement, never a guess."*

```python
#!/usr/bin/env python3
"""A body-inspecting Docker Engine API allow-list for the mutation broker. Stdlib-only.

WHY OUR OWN rather than an off-the-shelf socket proxy: the constraint that matters is
"create ONLY this image, with ONLY these mounts, running ONLY this program", and all of
that lives in the JSON BODY of POST /containers/create. A proxy that filters by method
and path cannot see it, so it would satisfy the letter of spec §6.4 and none of its
intent. This file is also small enough to audit in one sitting, which is the right
property for the one component whose compromise is worst.

THE POLICY, in one sentence: anything in the create body that can redirect trust to an
attacker-writable path is pinned. The executor has exactly ONE writable mount (log/), so
every field that could point it at a file inside that mount is a hole — Image is not
enough, and neither is Image plus Entrypoint (see ALLOWED_CMD_FLAGS).

WHAT THIS DOES NOT PROTECT: a compromised broker already holds the Ads write credential
(run-ads-mutate.sh reads .env.gaw in its own process) and can reach the client account
without Docker at all. This proxy defends the HOST, and secondarily the audit trail.

THE ALLOW-LIST BELOW WAS MEASURED, NOT GUESSED (spec deviation D1, re-measured for
Phase B). Adding an endpoint is a re-measurement, never a guess.

    <PASTE TASK 1'S MEASURED ENDPOINT LIST HERE, WITH ITS DATE>

DENY BY DEFAULT. Anything not matched below is refused.
"""
import argparse, json, os, re, socket, socketserver, sys, threading

_V = r"(?:/v[0-9]+\.[0-9]+)?"          # optional API version prefix, e.g. /v1.55
_ID = r"[A-Za-z0-9_.-]+"

# (method, compiled path pattern). Fullmatch only — a prefix match would let
# /containers/create/../../build through.
ALLOWED = [
    ("GET",    re.compile(r"/_ping")),
    ("HEAD",   re.compile(r"/_ping")),
    ("GET",    re.compile(_V + r"/version")),
    ("GET",    re.compile(_V + r"/images/" + _ID + r"/json")),
    ("GET",    re.compile(_V + r"/networks")),
    ("GET",    re.compile(_V + r"/volumes")),
    ("GET",    re.compile(_V + r"/containers/json")),
    ("POST",   re.compile(_V + r"/containers/create")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/start")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/attach")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/wait")),
    ("GET",    re.compile(_V + r"/containers/" + _ID + r"/json")),
    ("DELETE", re.compile(_V + r"/containers/" + _ID)),
]

# HostConfig keys that hand back what the proxy exists to withhold. "Mounts" is here
# because it is the newer API for the same capability as Binds — left open it bypasses
# the bind allow-list entirely.
FORBIDDEN_HOSTCONFIG = (
    "Privileged", "CapAdd", "Devices", "DeviceCgroupRules", "SecurityOpt",
    "Sysctls", "UsernsMode", "CgroupParent", "Runtime", "PidMode", "IpcMode",
    "UTSMode", "CgroupnsMode", "Init", "Mounts",
)

PINNED_ENTRYPOINT = ["python3", "/opt/cc-bin/apply-changeset.py"]

# The three flags hermes-broker.py:506 actually builds. --projects and --registry are
# deliberately ABSENT: --projects selects the file read for runner and script_dir
# (changeset_lib.read_mutate_execute), i.e. which program runs, and the one writable
# mount is where an attacker would put that file.
ALLOWED_CMD_FLAGS = {
    "--client":    re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$"),
    "--changeset": re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$"),
    "--request":   re.compile(r"^[0-9a-f-]{36}$"),
}

PINNED_IMAGE = None
PINNED_BINDS = frozenset()
PINNED_GOVERNANCE_ROOT = None


def configure(image, binds, governance_root):
    """Set the pinned values at startup. `binds` is an iterable of (src, dst, mode).

    Taken as flags rather than derived from docker-compose.yml because YAML is not
    stdlib and this file may not grow a dependency. proxy-policy-sync.test.py is what
    keeps the two in agreement.
    """
    global PINNED_IMAGE, PINNED_BINDS, PINNED_GOVERNANCE_ROOT
    PINNED_IMAGE = image
    PINNED_BINDS = frozenset("%s:%s:%s" % (s, d, m) for s, d, m in binds)
    PINNED_GOVERNANCE_ROOT = governance_root


def _path_only(path):
    """Strip the query string and reject any traversal before matching."""
    p = path.split("?", 1)[0]
    if ".." in p or "//" in p:
        return None
    return p


def _check_cmd(cmd):
    if not isinstance(cmd, list) or not cmd:
        return "Cmd must be a non-empty list"
    i = 0
    seen = set()
    while i < len(cmd):
        flag = cmd[i]
        if flag not in ALLOWED_CMD_FLAGS:
            return "Cmd flag %r is not permitted" % flag
        if i + 1 >= len(cmd):
            return "Cmd flag %r has no value" % flag
        if not ALLOWED_CMD_FLAGS[flag].fullmatch(str(cmd[i + 1])):
            return "Cmd value for %s is malformed" % flag
        seen.add(flag)
        i += 2
    missing = set(ALLOWED_CMD_FLAGS) - seen
    if missing:
        return "Cmd is missing %s" % ", ".join(sorted(missing))
    return None


def decide(method, path, body):
    """Pure allow/deny. Returns (allowed, reason). No I/O — this is the whole policy,
    and it is a function so it can be tested exhaustively without a socket."""
    p = _path_only(path)
    if p is None:
        return False, "path %r contains a traversal component" % path
    if not any(m == method and pat.fullmatch(p) for m, pat in ALLOWED):
        return False, "%s %s is not on the allow-list" % (method, p)

    if not (method == "POST" and re.fullmatch(_V + r"/containers/create", p)):
        return True, "allowed"

    try:
        spec = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return False, "unparseable create body: %s" % e
    if not isinstance(spec, dict):
        return False, "create body is not an object"

    if spec.get("Image") != PINNED_IMAGE:
        return False, ("create refused: image %r is not the pinned image %r"
                       % (spec.get("Image"), PINNED_IMAGE))

    if spec.get("Entrypoint") != PINNED_ENTRYPOINT:
        return False, ("create refused: entrypoint %r is not the pinned entrypoint %r"
                       % (spec.get("Entrypoint"), PINNED_ENTRYPOINT))

    # The image sets USER hermes and compose does not override it, so a legitimate
    # create carries no User field. "Must not be set" — NOT "must equal 10000", which
    # would refuse every real call.
    if spec.get("User"):
        return False, "create refused: User override %r is not permitted" % spec["User"]

    problem = _check_cmd(spec.get("Cmd"))
    if problem:
        return False, "create refused: " + problem

    hc = spec.get("HostConfig") or {}
    if not isinstance(hc, dict):
        return False, "HostConfig is not an object"
    for k in FORBIDDEN_HOSTCONFIG:
        if hc.get(k):
            return False, "create refused: HostConfig.%s is not permitted" % k
    for mode_key in ("NetworkMode", "PidMode", "IpcMode"):
        if str(hc.get(mode_key, "")).startswith("host"):
            return False, "create refused: HostConfig.%s=host" % mode_key

    binds = hc.get("Binds") or []
    if not isinstance(binds, list):
        return False, "create refused: HostConfig.Binds is not a list"
    got = set(str(b) for b in binds)
    if got != PINNED_BINDS:
        extra = sorted(got - PINNED_BINDS)
        missing = sorted(PINNED_BINDS - got)
        return False, ("create refused: bind set does not match the pinned set "
                       "(unexpected: %s; missing: %s)" % (extra or "none", missing or "none"))

    for entry in spec.get("Env") or []:
        name, _, value = str(entry).partition("=")
        if name == "HERMES_GOVERNANCE_ROOT" and value != PINNED_GOVERNANCE_ROOT:
            return False, ("create refused: HERMES_GOVERNANCE_ROOT=%r is not the pinned "
                           "root %r" % (value, PINNED_GOVERNANCE_ROOT))

    return True, "allowed"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 docker-create-proxy.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

Expected: PASS. **If `test_the_real_create_is_allowed` fails, stop** — the policy is refusing the legitimate call, and every other green test is meaningless.

- [ ] **Step 5: Reconcile against Task 1's measurement**

Compare `ALLOWED` against Task 1's measured endpoint list. Remove any endpoint the measurement did not show; add any it did. **Report the difference** — do not silently reconcile. If the measured body carries a `User` value, the design's prediction was wrong and Step 3's check must change to match; say so explicitly.

- [ ] **Step 6: Mutation proofs**

Each mutant is applied, verified to have actually applied, run, and reverted:

| Mutation | Must red |
|---|---|
| `Entrypoint` check → always pass | `test_an_overridden_entrypoint_is_refused` |
| `ALLOWED_CMD_FLAGS` gains `--projects` | `test_projects_flag_is_refused` |
| bind comparison `!=` → `not got.issubset(PINNED_BINDS)` | `test_a_missing_bind_is_refused` |
| `User` check → `if False:` | `test_a_user_override_is_refused` |
| drop `"Mounts"` from `FORBIDDEN_HOSTCONFIG` | `test_mounts_api_is_refused` |

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
cp docker-create-proxy.py /tmp/px.orig
python3 - <<'PY'
import io
p = "docker-create-proxy.py"
s = io.open(p).read()
old = '    if spec.get("Entrypoint") != PINNED_ENTRYPOINT:'
assert s.count(old) == 1, "anchor found %d times" % s.count(old)
io.open(p, "w").write(s.replace(old, "    if False:"))
PY
python3 -c "import ast; ast.parse(open('docker-create-proxy.py').read())" && echo "mutant parses"
grep -c 'if False:' docker-create-proxy.py     # confirms it actually applied
out=$(python3 docker-create-proxy.test.py 2>&1); rc=$?
printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | sort; echo "mutant exit: $rc"
cp /tmp/px.orig docker-create-proxy.py && rm /tmp/px.orig
git diff --stat docker-create-proxy.py   # must be empty — no stranded mutant
```

Repeat for each row. **An `assert` that trips means the script exited WITHOUT mutating, and a naive read of the run reports a false pass on an unmutated file** — that happened twice on the S3-b wave. Verify each mutation applied before believing any result. If one reds nothing, that is a coverage finding: report it.

- [ ] **Step 7: Run both suites and commit**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -2; echo "node exit: $rc"
git add infra/hermes-agent/bin/docker-create-proxy.py \
        infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(cat <<'MSG'
feat(hermes): body-inspecting Docker API policy for the mutation broker

decide() pins Image, Entrypoint, User, the Cmd flags, the exact bind set with
its ro/rw flags, and HERMES_GOVERNANCE_ROOT. One principle: the executor has
exactly one writable mount, so anything in the create body that can redirect
trust into it is pinned.

Pinning the image alone was not enough, and neither was image plus entrypoint:
--projects selects the file read for runner and script_dir, i.e. which program
runs, and log/ is where an attacker would write it. hermes-broker.py:506 passes
exactly three flags, so refusing --projects and --registry costs nothing.

The bind check is an allow-list including the ro/rw flag, replacing a denylist
that matched "/etc" exactly and so let /etc/shadow — and the governance store
mounted rw — straight through.

Every refusal is paired with a positive control, because a proxy that refuses
everything passes an attacker-only suite and breaks the rail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 3: The socket plumbing, keep-alive-aware

**Files:**
- Modify: `infra/hermes-agent/bin/docker-create-proxy.py` (append the server + CLI)
- Modify: `infra/hermes-agent/bin/docker-create-proxy.test.py` (append `TestPlumbing`)

**Interfaces:**
- Consumes: `decide()` from Task 2.
- Produces: CLI `docker-create-proxy.py --listen PATH --upstream PATH --image IMAGE --governance-root PATH --allow-bind SRC:DST:MODE ...` (repeatable), for Task 5's unit.

- [ ] **Step 1: Write the failing plumbing tests**

**The keep-alive test is the one that matters.** Measured 2026-09-16 while writing this plan: a pass-through that inspects the first request on a connection and then splices logged 3 of 14 calls. Built that way, **an attacker sends a benign `HEAD /_ping` first and then anything at all on the same connection, bypassing the policy entirely.**

Append to `docker-create-proxy.test.py`, above `unittest.main()`:

```python
class TestPlumbing(unittest.TestCase):
    """The socket half. These use a fake upstream so no Docker daemon is needed."""

    def setUp(self):
        import tempfile, threading, socket as _s
        PX.configure(image="hermes-agent-claude", binds=BINDS,
                     governance_root="/opt/governance")
        # AF_UNIX paths cap near 104 bytes — /tmp, never a long temp path.
        self.up_path = "/tmp/pxup-%d.sock" % os.getpid()
        self.li_path = "/tmp/pxli-%d.sock" % os.getpid()
        for p in (self.up_path, self.li_path):
            if os.path.exists(p):
                os.remove(p)
        self.upstream_saw = []
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(self.up_path)
        srv.listen(8)

        def fake_upstream():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                data = conn.recv(65536)
                self.upstream_saw.append(data.split(b"\r\n")[0].decode("latin1"))
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                conn.close()

        threading.Thread(target=fake_upstream, daemon=True).start()
        self.addCleanup(srv.close)
        for p in (self.up_path, self.li_path):
            self.addCleanup(lambda q=p: os.path.exists(q) and os.remove(q))

    def test_a_second_request_on_the_same_connection_is_also_inspected(self):
        """THE keep-alive bypass. A proxy that inspects the first request and then
        splices lets an attacker send a benign HEAD /_ping and then anything at all
        on the same connection. Measured while planning this: a first-request-only
        pass-through saw 3 of 14 real calls and looked like it had worked."""
        import threading, socket as _s
        t = threading.Thread(target=PX.serve,
                             kwargs=dict(listen=self.li_path, upstream=self.up_path),
                             daemon=True)
        t.start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            import time; time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"HEAD /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
        c.recv(65536)
        c.sendall(b"POST /v1.55/build HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp,
                      "second request on the connection was not inspected")
        self.assertNotIn("POST /v1.55/build HTTP/1.1", self.upstream_saw,
                         "a refused request reached the upstream socket")

    def test_a_create_with_no_content_length_is_refused(self):
        """A chunked body cannot be inspected before forwarding, and forwarding an
        uninspected create is the one thing this file exists to prevent."""
        import threading, socket as _s, time
        threading.Thread(target=PX.serve,
                         kwargs=dict(listen=self.li_path, upstream=self.up_path),
                         daemon=True).start()
        for _ in range(50):
            if os.path.exists(self.li_path):
                break
            time.sleep(0.05)
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.connect(self.li_path)
        c.sendall(b"POST /v1.55/containers/create HTTP/1.1\r\nHost: d\r\n"
                  b"Transfer-Encoding: chunked\r\n\r\n")
        resp = c.recv(65536)
        c.close()
        self.assertIn(b"403", resp)
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 docker-create-proxy.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -8; echo "exit: $rc"
```

Expected: FAIL — `PX.serve` does not exist.

- [ ] **Step 3: Implement the server and CLI**

Append to `docker-create-proxy.py`. Requirements, each load-bearing:

- **Loop per connection.** Parse request line and headers, read exactly `Content-Length` bytes, call `decide`, forward or refuse, relay the response, **then loop for the next request on the same connection.** Never splice after the first request.
- **`/attach` upgrades** to a bidirectional stream: once allowed, pump both directions and stop parsing that connection.
- **Refuse a `POST /containers/create` with no `Content-Length`** (chunked or absent).
- **Cap the buffered body at 1 MiB**; refuse above it.
- **Log every decision** — allow and deny — with method, path, and reason, to stderr.
- On refusal return `403 Forbidden` with `{"message": reason}` and `Content-Length` set.
- Create the listening socket, then `os.chmod(path, 0o660)` so the broker's group can connect (Task 5 supplies the shared group). **Do not attempt `os.chown` to another user** — the proxy runs non-root with `NoNewPrivileges=true` and cannot.

```python
MAX_BODY = 1024 * 1024


def _read_until_headers(sock, buf):
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return None, buf
        buf += chunk
        if len(buf) > MAX_BODY:
            return None, buf
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head, rest


def _refuse(conn, reason):
    payload = json.dumps({"message": reason}).encode("utf-8")
    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n"
                 b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)


def _handle(conn, upstream_path):
    up = None
    buf = b""
    try:
        while True:
            head, rest = _read_until_headers(conn, buf)
            if head is None:
                return
            line = head.split(b"\r\n")[0].decode("latin1")
            parts = line.split(" ")
            if len(parts) < 2:
                _refuse(conn, "malformed request line")
                return
            method, path = parts[0], parts[1]
            clen, chunked = 0, False
            for h in head.split(b"\r\n")[1:]:
                lo = h.lower()
                if lo.startswith(b"content-length:"):
                    clen = int(h.split(b":", 1)[1].strip() or b"0")
                if lo.startswith(b"transfer-encoding:") and b"chunked" in lo:
                    chunked = True
            is_create = "/containers/create" in path
            if is_create and (chunked or clen == 0):
                _refuse(conn, "create with no Content-Length cannot be inspected")
                print("DENY %s %s (uninspectable body)" % (method, path), file=sys.stderr)
                return
            if clen > MAX_BODY:
                _refuse(conn, "body exceeds %d bytes" % MAX_BODY)
                return
            while len(rest) < clen:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                rest += chunk
            body, buf = rest[:clen], rest[clen:]

            ok, reason = decide(method, path, body)
            print("%s %s %s (%s)" % ("ALLOW" if ok else "DENY", method, path, reason),
                  file=sys.stderr)
            if not ok:
                _refuse(conn, reason)
                return

            if up is None:
                up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                up.connect(upstream_path)
            up.sendall(head + b"\r\n\r\n" + body)

            if "/attach" in path:
                def pump(a, b):
                    try:
                        while True:
                            d = a.recv(65536)
                            if not d:
                                break
                            b.sendall(d)
                    except OSError:
                        pass
                threading.Thread(target=pump, args=(conn, up), daemon=True).start()
                pump(up, conn)
                return

            rhead, rrest = _read_until_headers(up, b"")
            if rhead is None:
                return
            rclen, rchunk = 0, False
            for h in rhead.split(b"\r\n")[1:]:
                lo = h.lower()
                if lo.startswith(b"content-length:"):
                    rclen = int(h.split(b":", 1)[1].strip() or b"0")
                if lo.startswith(b"transfer-encoding:") and b"chunked" in lo:
                    rchunk = True
            conn.sendall(rhead + b"\r\n\r\n")
            if rchunk:
                conn.sendall(rrest)
                while True:
                    d = up.recv(65536)
                    if not d:
                        break
                    conn.sendall(d)
                return
            while len(rrest) < rclen:
                d = up.recv(65536)
                if not d:
                    break
                rrest += d
            conn.sendall(rrest[:rclen])
    except OSError:
        return
    finally:
        if up is not None:
            try:
                up.close()
            except OSError:
                pass


def serve(listen, upstream):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            _handle(self.request, upstream)

    class Server(socketserver.ThreadingUnixStreamServer):
        allow_reuse_address = True
        daemon_threads = True

    if os.path.exists(listen):
        os.remove(listen)
    srv = Server(listen, Handler)
    os.chmod(listen, 0o660)
    srv.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", required=True)
    ap.add_argument("--upstream", default="/var/run/docker.sock")
    ap.add_argument("--image", required=True)
    ap.add_argument("--governance-root", required=True)
    ap.add_argument("--allow-bind", action="append", default=[],
                    metavar="SRC:DST:MODE", required=True,
                    help="repeatable; the exact bind set the executor may request")
    args = ap.parse_args(argv)
    binds = []
    for raw in args.allow_bind:
        bits = raw.split(":")
        if len(bits) != 3 or bits[2] not in ("ro", "rw"):
            print("docker-create-proxy: --allow-bind must be SRC:DST:ro|rw, got %r" % raw,
                  file=sys.stderr)
            return 2
        binds.append(tuple(bits))
    configure(image=args.image, binds=binds, governance_root=args.governance_root)
    serve(args.listen, args.upstream)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**There is no `--log-only`.** It is not implemented, so it cannot survive into the unit. Task 1's measurement used a separate throwaway script, which is why.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 docker-create-proxy.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -6; echo "exit: $rc"
```

- [ ] **Step 5: End-to-end proof against the real daemon — a refusal AND a success**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent
export HERMES_GOVERNANCE_DIR=$(mktemp -d)
mkdir -p "$HERMES_GOVERNANCE_DIR"/{approvals,control,registry,log}
python3 bin/docker-create-proxy.py --listen /tmp/pxe2e.sock \
  --upstream /var/run/docker.sock --image hermes-agent-claude \
  --governance-root /opt/governance \
  --allow-bind "$HERMES_GOVERNANCE_DIR/approvals:/opt/governance/approvals:ro" \
  --allow-bind "$HERMES_GOVERNANCE_DIR/control:/opt/governance/control:ro" \
  --allow-bind "$HERMES_GOVERNANCE_DIR/registry:/opt/governance/registry:ro" \
  --allow-bind "$HERMES_GOVERNANCE_DIR/log:/opt/governance/log:rw" \
  --allow-bind "$(cd ../../.. && pwd)/claude-google-ads:/projects/claude_google_ads:ro" \
  --allow-bind "$(pwd)/registry:/opt/registry:ro" \
  --allow-bind "$(pwd)/bin:/opt/cc-bin:ro" 2>/tmp/pxe2e.log &
PROXY=$!
sleep 1
echo "--- NEGATIVE: an unpinned image must be refused ---"
DOCKER_HOST=unix:///tmp/pxe2e.sock docker run --rm alpine true 2>&1 | tail -2
echo "--- POSITIVE CONTROL: the real rail must still work ---"
DOCKER_HOST=unix:///tmp/pxe2e.sock timeout 90 docker compose -f docker-compose.yml \
    run --rm --no-deps -T ads-mutator --help >/dev/null 2>&1
echo "real rail exit: $?"
kill $PROXY 2>/dev/null
grep -cE '^(ALLOW|DENY)' /tmp/pxe2e.log
```

Expected: the `alpine` run **refused**; the real rail **exit 0**. **The positive control is load-bearing** — a proxy that refuses everything passes the negative and breaks the rail, which is the shape of a seam this project once passed as clean because nobody asked whether the authorised caller could get through.

If the real rail fails, read `/tmp/pxe2e.log` for the `DENY` line and reconcile `ALLOWED`/`PINNED_BINDS` against it. **Report any endpoint you had to add.**

- [ ] **Step 6: Run both suites and commit**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -2; echo "node exit: $rc"
git add infra/hermes-agent/bin/docker-create-proxy.py \
        infra/hermes-agent/bin/docker-create-proxy.test.py
git commit -m "$(cat <<'MSG'
feat(hermes): keep-alive-aware socket plumbing for the Docker policy proxy

Every request on a connection is parsed, not just the first. Measured while
planning: a first-request-only pass-through saw 3 of 14 real calls and looked
like it had worked — built that way, an attacker sends a benign HEAD /_ping and
then anything at all on the same connection, bypassing the policy entirely.

Refuses a create with no Content-Length, because a chunked body cannot be
inspected before forwarding and forwarding an uninspected create is the one
thing this file exists to prevent. Caps the buffered body at 1 MiB and logs
every decision, allow and deny.

No --log-only mode exists: a proxy with a bypass flag is not a proxy, and the
measurement that needed one used a separate throwaway script.

Proven end to end against the real daemon with BOTH halves: an unpinned image
refused, and the real rail still exits 0.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 4: The sync test — proxy constants vs compose vs broker argv

Without this, the pins drift from what the rail actually sends and the failure surfaces on the VPS. This is the same rule the project already applies to `install.sh`/`uninstall.sh` and to S3-b's verbatim-identical `REMEDY`/README.

**Files:**
- Create: `infra/hermes-agent/bin/proxy-policy-sync.test.py`

**Interfaces:**
- Consumes: `PINNED_ENTRYPOINT`, `ALLOWED_CMD_FLAGS` from Task 2; `docker-compose.yml`; `hermes-broker.py`.
- Produces: nothing — it is a guard.

- [ ] **Step 1: Write the test**

YAML is not stdlib, so parse the two files textually. That is deliberate: the test must not import a dependency the proxy itself is forbidden.

```python
import importlib.util, os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
COMPOSE = os.path.join(os.path.dirname(HERE), "docker-compose.yml")
BROKER = os.path.join(HERE, "hermes-broker.py")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PX = _load("docker_create_proxy", "docker-create-proxy.py")


def _ads_mutator_block():
    """The ads-mutator service block, textually. YAML is not stdlib and the proxy may
    not grow a dependency, so neither may its guard."""
    text = open(COMPOSE, encoding="utf-8").read()
    start = text.index("\n  ads-mutator:")
    rest = text[start + 1:]
    m = re.search(r"\n  [a-z0-9-]+:\n", rest)
    return rest[:m.start()] if m else rest


class TestProxyMatchesCompose(unittest.TestCase):
    """If these drift, the proxy refuses the real rail — on the VPS, at runtime.
    The same coupling install.sh/uninstall.sh carry, and S3-b's REMEDY/README."""

    def test_the_pinned_entrypoint_matches_compose(self):
        block = _ads_mutator_block()
        m = re.search(r"entrypoint:\s*(\[[^\]]*\])", block)
        self.assertIsNotNone(m, "no entrypoint found in the ads-mutator block")
        declared = [s.strip().strip('"\'') for s in m.group(1).strip("[]").split(",")]
        self.assertEqual(declared, PX.PINNED_ENTRYPOINT)

    def test_every_compose_volume_is_representable_as_an_allow_bind(self):
        """The proxy takes binds as flags, so this asserts SHAPE and count — the
        unit supplies the resolved paths, and Task 5's unit test pins those."""
        block = _ads_mutator_block()
        vols = re.findall(r"^\s+- (\S+:\S+)$", block, re.M)
        self.assertEqual(len(vols), 7,
                         "compose declares %d volumes; the proxy's unit supplies 7 "
                         "--allow-bind flags. Update both together." % len(vols))
        rw = [v for v in vols if not v.endswith(":ro")]
        self.assertEqual(len(rw), 1, "exactly one writable mount is expected: log/")
        self.assertIn("/log:", rw[0])

    def test_seen_is_not_mounted_into_the_executor(self):
        """iter_seen_records (changeset_lib.py) still fails OPEN on a missing file,
        safe ONLY because the governed party cannot reach seen/. Phase B is the wave
        most likely to touch mounts, so the assertion lives here."""
        self.assertNotIn("/seen:", _ads_mutator_block())


class TestProxyMatchesBrokerArgv(unittest.TestCase):
    def test_the_allowed_cmd_flags_match_what_the_broker_builds(self):
        """hermes-broker.py builds the executor's argv. A flag it starts passing that
        the proxy does not allow breaks the rail; a flag the proxy allows that the
        broker never passes is attack surface."""
        text = open(BROKER, encoding="utf-8").read()
        m = re.search(r"argv = \[MUTATE_SH,([^\]]*)\]", text)
        self.assertIsNotNone(m, "could not find the broker's argv construction")
        flags = set(re.findall(r'"(--[a-z-]+)"', m.group(1)))
        self.assertEqual(flags, set(PX.ALLOWED_CMD_FLAGS),
                         "broker argv flags and proxy ALLOWED_CMD_FLAGS have drifted")

    def test_projects_and_registry_are_not_allowed(self):
        """--projects selects the file read for runner and script_dir, i.e. which
        program runs, and log/ is the one writable mount."""
        self.assertNotIn("--projects", PX.ALLOWED_CMD_FLAGS)
        self.assertNotIn("--registry", PX.ALLOWED_CMD_FLAGS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it — it must pass immediately**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin
out=$(python3 proxy-policy-sync.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -5; echo "exit: $rc"
```

Expected: PASS. This is a guard over existing agreement, not a change — if it fails now, the proxy and compose already disagree and that is a finding to report before proceeding.

- [ ] **Step 3: Prove the guard actually guards**

Temporarily add an eighth volume to the `ads-mutator` block in `docker-compose.yml`, re-run, confirm `test_every_compose_volume_is_representable_as_an_allow_bind` **fails**, then revert and confirm `git diff` is clean. A sync test that does not fail on drift is decoration.

- [ ] **Step 4: Commit**

```bash
cd /Users/ericksicard/Projects/claude_code
git add infra/hermes-agent/bin/proxy-policy-sync.test.py
git commit -m "test(hermes): pin the proxy's policy to compose and the broker's argv"
```

---

## Task 5: The systemd units, with the socket handoff fixed

**Files:**
- Create: `infra/hermes-agent/deploy/hermes-docker-proxy.service`
- Create: `infra/hermes-agent/deploy/hermes-broker.service`
- Create: `infra/hermes-agent/deploy/units.test.py`

**Interfaces:**
- Consumes: the Task 3 CLI.
- Produces: the unit files Task 6's deploy sequence installs.

- [ ] **Step 1: Write the proxy unit**

The planned unit had the broker unable to reach the socket. **MEASURED 2026-09-16** in `hermes-agent-claude:latest` with a live listener: `RuntimeDirectory=hermes` at `RuntimeDirectoryMode=0750` owned by the proxy user gives the broker `[Errno 13] Permission denied`; a shared group on both directory and socket **CONNECTED**. Without this fix the rail is dead on first boot.

Create `infra/hermes-agent/deploy/hermes-docker-proxy.service`:

```ini
[Unit]
Description=Hermes Docker API allow-list proxy (pins container creation to one image)
After=docker.service
Requires=docker.service

[Service]
Type=simple
# This unit is the ONLY component in the group that touches the real Docker socket.
# It runs as a user in the docker group; the broker deliberately is not.
User=hermes-docker-proxy
SupplementaryGroups=docker
# The shared group is what lets the broker CONNECT to the socket below. MEASURED:
# with the directory and socket owned by the proxy's own group, the broker gets
# EACCES and the rail is dead on first boot.
#
# Deliberately NOT Group=hermes-broker, which would also work: that would give this
# proxy read access to .env.gaw — the write credential it has no business seeing.
# hermes-rail carries no other rights, which is the point.
Group=hermes-rail
RuntimeDirectory=hermes
RuntimeDirectoryMode=0750
ExecStart=/opt/hermes-agent/bin/docker-create-proxy.py \
    --listen /run/hermes/docker-proxy.sock \
    --upstream /var/run/docker.sock \
    --image hermes-agent-claude \
    --governance-root /opt/governance \
    --allow-bind /var/lib/hermes/governance/approvals:/opt/governance/approvals:ro \
    --allow-bind /var/lib/hermes/governance/control:/opt/governance/control:ro \
    --allow-bind /var/lib/hermes/governance/registry:/opt/governance/registry:ro \
    --allow-bind /var/lib/hermes/governance/log:/opt/governance/log:rw \
    --allow-bind /opt/projects/claude-google-ads:/projects/claude_google_ads:ro \
    --allow-bind /opt/hermes-agent/registry:/opt/registry:ro \
    --allow-bind /opt/hermes-agent/bin:/opt/cc-bin:ro
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX
MemoryMax=128M

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write the broker unit**

Create `infra/hermes-agent/deploy/hermes-broker.service`:

```ini
[Unit]
Description=Hermes mutation request broker (drains the spool, invokes the governed rail)
After=hermes-docker-proxy.service
Requires=hermes-docker-proxy.service

[Service]
Type=simple
# Its own user. .env.gaw and the governance store are readable ONLY by this user, so
# even the deploy user's shell cannot read the write credential (spec §16.2).
User=hermes-broker
Group=hermes-broker
# hermes-rail: connect to the proxy socket. hermes (gid 10000): read the governance
# store — required, because ExecStartPre's pre-flight READS clients.json, and a broker
# outside gid 10000 refuses with four spurious "cannot stat" problems instead of the
# real finding (MEASURED 2026-09-16).
SupplementaryGroups=hermes-rail hermes
WorkingDirectory=/opt/hermes-agent
# NOT in the docker group. Docker access is exclusively through the proxy socket.
Environment=DOCKER_HOST=unix:///run/hermes/docker-proxy.sock
Environment=HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance
Environment=HERMES_GOVERNANCE_ROOT=/var/lib/hermes/governance
Environment=HERMES_SPOOL_ROOT=/opt/hermes-agent/data/spool
# Refuses at BOOT rather than mid-apply, where the failure is exit 3 after a live
# account change. Since S3-b this also refuses when a registered client has no
# pre-created log — so --bootstrap-logs MUST have been run before this unit is
# enabled, or Restart=on-failure turns it into a five-second restart loop.
ExecStartPre=/usr/bin/python3 /opt/hermes-agent/bin/preflight-governance-access.py \
    --root /var/lib/hermes/governance
ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-broker.py --watch --interval 5
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/hermes/governance /opt/hermes-agent/data/spool
RestrictAddressFamilies=AF_UNIX
MemoryMax=256M

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write the unit-content test**

Create `infra/hermes-agent/deploy/units.test.py`:

```python
import os, re, unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def unit(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


class TestUnits(unittest.TestCase):
    """WHAT THIS PROVES, AND WHAT IT DOES NOT.

    These assert that the unit FILES SAY the right thing. They do NOT prove systemd
    behaves that way: nothing here exercises ProtectSystem=strict, NoNewPrivileges,
    RestrictAddressFamilies, or boot ordering. Those stay UNPROVEN until the VPS, and
    the PR body must say so — "the units are tested" would otherwise read as a
    guarantee this wave does not make.
    """

    def test_the_broker_is_not_in_the_docker_group(self):
        """The entire point of the proxy. A broker in the docker group has host root
        and every other guarantee in this tier is decoration."""
        body = unit("hermes-broker.service")
        for line in body.splitlines():
            if line.startswith(("Group=", "SupplementaryGroups=")):
                self.assertNotIn("docker", line, line)

    def test_only_the_proxy_touches_the_real_socket(self):
        self.assertIn("/var/run/docker.sock", unit("hermes-docker-proxy.service"))
        self.assertNotIn("/var/run/docker.sock", unit("hermes-broker.service"))

    def test_the_broker_reaches_docker_only_through_the_proxy(self):
        self.assertIn("DOCKER_HOST=unix:///run/hermes/docker-proxy.sock",
                      unit("hermes-broker.service"))

    def test_the_preflight_runs_before_the_broker_starts(self):
        body = unit("hermes-broker.service")
        self.assertIn("ExecStartPre", body)
        self.assertIn("preflight-governance-access.py", body)

    def test_both_users_share_the_rail_group_so_the_socket_is_reachable(self):
        """MEASURED 2026-09-16: without a shared group on the runtime directory and
        the socket, the broker gets EACCES and the rail is dead on first boot."""
        self.assertIn("Group=hermes-rail", unit("hermes-docker-proxy.service"))
        self.assertIn("hermes-rail", unit("hermes-broker.service"))

    def test_the_proxy_does_not_get_the_brokers_group(self):
        """That would work for the socket AND hand the proxy read access to .env.gaw."""
        self.assertNotIn("Group=hermes-broker", unit("hermes-docker-proxy.service"))

    def test_the_broker_can_read_the_governance_store(self):
        """The pre-flight READS clients.json. A broker outside gid 10000 refuses with
        four spurious 'cannot stat' problems instead of naming --bootstrap-logs."""
        self.assertRegex(unit("hermes-broker.service"),
                         r"SupplementaryGroups=.*\bhermes\b")

    def test_the_proxy_has_no_log_only_bypass(self):
        """A proxy with a bypass flag is not a proxy."""
        self.assertNotIn("--log-only", unit("hermes-docker-proxy.service"))

    def test_every_allow_bind_flag_is_well_formed(self):
        for raw in re.findall(r"--allow-bind (\S+)", unit("hermes-docker-proxy.service")):
            bits = raw.split(":")
            self.assertEqual(len(bits), 3, raw)
            self.assertIn(bits[2], ("ro", "rw"), raw)

    def test_exactly_one_bind_is_writable(self):
        modes = [r.split(":")[2] for r in
                 re.findall(r"--allow-bind (\S+)", unit("hermes-docker-proxy.service"))]
        self.assertEqual(modes.count("rw"), 1)
        self.assertEqual(len(modes), 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Confirm `run-bin-tests.sh` does NOT pick this up, then decide**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?
printf '%s\n' "$out" | tail -2; echo "bin exit: $rc"
```

`run-bin-tests.sh` discovers `*.test.py` in `bin/` only, so `deploy/units.test.py` will **not** run. Either run it explicitly in Task 7's verification, or move it to `bin/`. **Prefer running it explicitly and say so in the report** — `deploy/` is where the units live, and splitting them from their test to satisfy a discovery glob is the tail wagging the dog.

- [ ] **Step 5: Run the unit test and commit**

```bash
cd /Users/ericksicard/Projects/claude_code/infra/hermes-agent/deploy
out=$(python3 units.test.py 2>&1); rc=$?
printf '%s\n' "$out" | tail -4; echo "exit: $rc"
cd /Users/ericksicard/Projects/claude_code
git add infra/hermes-agent/deploy/
git commit -m "$(cat <<'MSG'
feat(hermes): systemd units — broker outside the docker group, proxy in front

The proxy is the only component that touches the real Docker socket; the broker
reaches Docker exclusively through it and is deliberately not in the docker
group.

Fixes a socket handoff that would have been dead on first boot. MEASURED with a
live listener: RuntimeDirectory at 0750 owned by the proxy's own group gives the
broker EACCES; a shared group on the directory and socket connects. The shared
group is hermes-rail rather than hermes-broker on purpose — the latter would
also work and would hand the proxy read access to .env.gaw.

The broker additionally joins gid 10000 so its ExecStartPre pre-flight can READ
clients.json: outside that group it refuses with four spurious "cannot stat"
problems instead of naming --bootstrap-logs.

units.test.py asserts unit CONTENT and says plainly in its docstring that this
is not a behavioural proof — ProtectSystem, NoNewPrivileges and boot ordering
stay unproven until the VPS.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01X7iREgFjmiBrXQNhZFbNug
MSG
)"
```

---

## Task 6: The deploy sequence

**Files:**
- Modify: `infra/hermes-agent/README.md` (a new "VPS deploy sequence" section near the ownership section around `:894`)

**Interfaces:**
- Consumes: the units from Task 5.
- Produces: the operator-facing sequence.

- [ ] **Step 1: Write the sequence**

Ordering is the point. Add a section that reads, in this order:

1. **Create the users and groups** — `hermes-docker-proxy` (in `docker`), `hermes-broker`, and the shared `hermes-rail` containing both. Add `hermes-broker` to gid `10000` so the pre-flight can read the registry.
2. **Lay out the governance store** — the S3-b ownership block already in the README: `chgrp -R 10000`, `chmod -R g+rX`, `chmod 2750 log`, `find log -type f -name '*.jsonl' -exec chmod 0660 {} +`.
3. **Bootstrap the logs** — `migrate-governance.py --bootstrap-logs --apply`. **Before enabling any unit.**
4. **Install the units**, `systemctl daemon-reload`, then `systemctl enable --now hermes-docker-proxy` followed by `hermes-broker`.
5. **Verify**: `systemctl status` both; confirm the broker is not in the docker group (`id hermes-broker`); confirm the socket is reachable.

Add this warning verbatim, because the failure is silent-looking:

> **Run `--bootstrap-logs` BEFORE enabling the broker.** Since S3-b the pre-flight refuses
> when a registered client has no pre-created log, and the broker runs it as `ExecStartPre`.
> With `Restart=on-failure` and `RestartSec=5`, an unbootstrapped store does not fail once —
> the unit **restart-loops every five seconds**. `journalctl -u hermes-broker` will show the
> refusal naming `migrate-governance.py --bootstrap-logs --apply`.

And this one:

> **The endpoint allow-list is re-measured on the VPS, not inherited.** Per R22 the darwin
> measurement says nothing about Linux Docker. Re-run Task 1's measurement on the target
> before trusting the proxy there.

- [ ] **Step 2: Commit**

```bash
cd /Users/ericksicard/Projects/claude_code
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): VPS deploy sequence — bootstrap before enable, groups spelled out"
```

---

## Task 7: Verification and PR

**Files:** none modified.

- [ ] **Step 1: Every suite, exit status captured**

```bash
cd /Users/ericksicard/Projects/claude_code
out=$(infra/hermes-agent/bin/run-bin-tests.sh 2>&1); rc=$?; printf '%s\n' "$out" | tail -3; echo "bin exit: $rc"
out=$(node scripts/run-all-tests.js 2>&1); rc=$?; printf '%s\n' "$out" | tail -2; echo "node exit: $rc"
cd infra/hermes-agent/deploy
out=$(python3 units.test.py 2>&1); rc=$?; printf '%s\n' "$out" | tail -2; echo "units exit: $rc"
```

Expected: 27/27 bin (25 + the two new bin suites), 22/22 node, units green.

- [ ] **Step 2: Redaction scan, scoped to the diff, with a live control**

```bash
cd /Users/ericksicard/Projects/claude_code
git diff main...HEAD > /tmp/pb.diff
grep -nE '[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10}|customers/[0-9]+' /tmp/pb.diff | head -20
echo "--- CONTROL (must fire) ---"
printf 'customer 123-456-7890 and 5556667778\n' \
  | grep -qE '[0-9]{3}-[0-9]{3}-[0-9]{4}|[0-9]{10}' \
  && echo "CONTROL FIRED — the scan is live" || echo "CONTROL DEAD — scan invalid"
```

Expect hits and expect them to be sanctioned fixtures (`acme-dental`, `"1234567890"`, …). Confirm each; if a hit is anything else, stop.

- [ ] **Step 3: Tree and kill switch**

```bash
cd /Users/ericksicard/Projects/claude_code
echo "tracked (expect 5):   $(git status --porcelain | grep -vc '^??')"
echo "untracked (expect 44): $(git status --porcelain | grep -c '^??')"
test -f ~/.hermes/governance/control/mutation-enabled \
  && echo "PRESENT — turn it off" || echo "kill switch ABSENT"
```

- [ ] **Step 4: Push and open the PR, then CHECK CI**

```bash
cd /Users/ericksicard/Projects/claude_code
git push -u origin <branch>
gh pr create --base main --head <branch> --title "Phase B: Docker socket proxy and systemd units" --body "<see below>"
sleep 75
gh pr checks <n>
```

The PR body must carry, in its own section:

> **What is NOT proven.** systemd actually applying `ProtectSystem=strict`,
> `NoNewPrivileges` and `RestrictAddressFamilies`; the real endpoint set against Linux
> Docker; and boot ordering under real systemd are **unproven until the VPS**. `units.test.py`
> asserts that the unit files *say* the right thing, not that the system behaves that way.
> Per R22 every measurement here ran under Docker Desktop.
>
> **Still open:** truncation of the audit log (`0660` grants write, and write includes
> truncate). Pinning `Entrypoint` removes the arbitrary-code route to it but does not close
> it; that needs append-only semantics or a host-side writer, and is its own wave. P6
> (`vault-purge`'s `getpass.getuser()`) remains latent — the units use a static `User=`.

**CI runs Linux and local darwin runs fewer tests. Do not report the PR as opened without checking the checks** — that cost ten days on S3-b.
