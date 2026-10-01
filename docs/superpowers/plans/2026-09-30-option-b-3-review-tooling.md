# Option B, part 3 — Review tooling and checklist v1.11: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Security review #6 can measure everything Option B claims:
- keyed customer-id fingerprints;
- a sentinel probe of where each key goes;
- a drafter egress probe;
- the moved client data;
- the new app units and layout;
- the three review-#5 follow-ups;
- checklist v1.11 with a D10 domain.

**Architecture:**
- `review_lib` gains HMAC fingerprints for customer ids; both collectors require the review key.
- `run-client-audit` gains two root-only probes (`--probe-env` and `--probe-egress`). They reuse `plan()`'s real wiring with sentinel secrets and throwaway directories.
- `collect-review-evidence.py` edits D2.1, D4.1, D4.2 and D7.1, and adds box probes D10.1–D10.4 and D10.6–D10.8. D10.5 is manual.
- `CHECKLIST.md` goes to v1.11, and the reviewer packet (brief and template) follows.

**Tech Stack:** Python 3 stdlib only, Docker Compose, GitHub Actions (the "Bind agreement" job runs the probes on real Docker).

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` (§8, §10 PR 3). **Prerequisites:** parts 1 and 2 are merged.

## Global Constraints

- **Code and tests:** Python stdlib only; tests are `bin/<name>.test.py`. `infra/hermes-agent/bin/run-bin-tests.sh` must end `N/N suites passed`. `python3 infra/hermes-agent/bin/security-review-checklist.test.py` must pass after Task 7.
- **Fingerprints:**
  - `cid:` fingerprints are `hmac.new(key, digits, sha256).hexdigest()[:12]`.
  - The key is 32 random bytes stored as 64 hex characters at `~/.config/hermes-review/fp.key` (`0600`) on the laptop only. The box reads it from the tty (`--fp-key-tty`).
  - `refresh_token_sha12` and `client_id_sha12` stay `sha12` (high-entropy values; existing records compare against them).
  - The box fingerprint must not depend on the key.
- **Bundles never contain** a customer id, a slug, a credential value, a key, or report text. Every new probe output passes through the existing `Redactor.obj`.
- **Declared credential map (D10.1):** `ads-collector` and `ads-reader` hold `GOOGLE_ADS_*` only; `ads-drafter` holds `ANTHROPIC_API_KEY` only; `egress-proxy` holds none; the gateway holds `OPENROUTER_API_KEY` and no `ANTHROPIC_*` or `GOOGLE_ADS_*`; the broker and runner hold none.
- **Any change to `CHECKLIST.md` raises its `version:`.** This part raises it exactly once, to `1.11`.
- **The probes are root-only and not reachable from the app runner.** The manifest's ops are `run` and `list`, and the runner builds its argv only from the manifest.

## Review Focus

1. **A reviewer given two bundles collected with different keys:** the customer-id fingerprints won't match, and that must be visible rather than silently look like a different customer. Both bundles record `cid_key_id` (the first 8 hex characters of `sha256(key)`), and Task 2 tests that it's present and equal on both sides.
2. **`--probe-env` must never read a real secret file.** Even when `/etc/hermes/.env.ga` exists, the sentinel values are used. Task 3 asserts that the real credential file isn't opened.
3. **A probe interrupted mid-run** (for example Docker is down) must still remove its throwaway directories and stop `egress-proxy`. Task 3 tests the `finally`.
4. **A result file in `results/` that the operator hand-edited or a bug malformed** must show up in D10.8 as out-of-whitelist, not be silently skipped. Task 5.
5. **An `audit-logs/<client>/` file that is world-readable** must make D7.1 FAIL through the new per-file mode counts. The rows carry counts by `owner group mode`, never names. Task 6.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/review_lib.py` (+ tests) | modify | `hmac12`, `load_fp_key`, `key_id`; `Redactor(..., fp_key=)` |
| `infra/hermes-agent/bin/review-fp-key.py` (+ `.test.py`) | create | `init` creates the laptop key; `show-id` prints its id |
| `infra/hermes-agent/bin/collect-review-evidence.py` (+ tests) | modify | `--fp-key-tty`; D2.1, D4.1, D4.2 and D7.1 edits; D10 probes; review-#5 follow-ups |
| `infra/hermes-agent/bin/collect-review-evidence-laptop.py` (+ tests) | modify | `--fp-key-file` |
| `infra/hermes-agent/bin/run-client-audit.py` (+ tests) | modify | `--probe-env`, `--probe-egress` |
| `infra/hermes-agent/deploy/audit-mounts-integration.test.py` | modify | both probes on real Docker |
| `infra/hermes-agent/deploy/security-review/{CHECKLIST,REVIEWER-BRIEF,REPORT-TEMPLATE}.md` | modify | v1.11 and D10 |
| `infra/hermes-agent/deploy/BRING-UP.md` | modify | the review procedure with the key |

---

### Task 1: Keyed customer-id fingerprints in `review_lib`, and the laptop key tool

**Files:**
- Modify: `infra/hermes-agent/bin/review_lib.py`
- Create: `infra/hermes-agent/bin/review-fp-key.py`
- Test: `infra/hermes-agent/bin/review_lib.test.py` (append), `infra/hermes-agent/bin/review-fp-key.test.py`

**Interfaces:**
- Produces:
  - `review_lib.hmac12(key: bytes, value) -> str`;
  - `review_lib.load_fp_key(text: str) -> bytes`, which raises `ValueError` unless it gets exactly 64 hex characters (surrounding whitespace ignored);
  - `review_lib.key_id(key: bytes) -> str` (the first 8 hex characters of `sha256(key)`);
  - `Redactor(slugs, customer_ids, fp_key=None)` and `Redactor.from_clients_json(path, fp_key=None)`. With a key, cids become `cid:<hmac12>`; without one, `cid:<sha12>` (unchanged: `run-client-audit`'s screen output keeps using it).
  - CLI: `review-fp-key.py init [--path P]` refuses to overwrite; `review-fp-key.py show-id [--path P]`.

- [ ] **Step 1: Write the failing tests** (append to `review_lib.test.py`)

```python
class TestKeyedFingerprints(unittest.TestCase):
    KEY = bytes.fromhex("11" * 32)

    def test_hmac12_is_keyed_and_12_hex(self):
        a, b = R.hmac12(self.KEY, "1234567890"), R.hmac12(bytes.fromhex("22" * 32), "1234567890")
        self.assertEqual(len(a), 12); self.assertNotEqual(a, b)
        self.assertNotEqual(a, R.sha12("1234567890"))

    def test_redactor_uses_the_key_for_cids_only(self):
        red = R.Redactor(["acme"], ["123-456-7890"], fp_key=self.KEY)
        out = red.text("acct 1234567890 and 123-456-7890")
        self.assertEqual(out.count("cid:" + R.hmac12(self.KEY, "1234567890")), 2)
        self.assertNotIn(R.sha12("1234567890"), out)

    def test_no_key_keeps_sha12(self):
        self.assertIn(R.sha12("1234567890"), R.Redactor([], ["1234567890"]).text("1234567890"))

    def test_load_fp_key(self):
        self.assertEqual(R.load_fp_key(" " + "ab" * 32 + "\n"), bytes.fromhex("ab" * 32))
        for bad in ("", "ab" * 31, "zz" * 32, "ab" * 33):
            with self.assertRaises(ValueError):
                R.load_fp_key(bad)

    def test_key_id(self):
        self.assertEqual(len(R.key_id(self.KEY)), 8)
```

   `review-fp-key.test.py`:

```python
#!/usr/bin/env python3
import contextlib, importlib.util, io, os, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fpk", os.path.join(HERE, "review-fp-key.py"))
K = importlib.util.module_from_spec(spec); spec.loader.exec_module(K)


class T(unittest.TestCase):
    def test_init_creates_0600_and_refuses_overwrite(self):
        p = os.path.join(tempfile.mkdtemp(), "sub", "fp.key")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(K.main(["init", "--path", p]), 0)
            self.assertEqual(K.main(["init", "--path", p]), 2)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(len(open(p).read().strip()), 64)
        self.assertNotIn(open(p).read().strip(), out.getvalue())       # never printed

    def test_show_id(self):
        p = os.path.join(tempfile.mkdtemp(), "fp.key"); open(p, "w").write("ab" * 32)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(K.main(["show-id", "--path", p]), 0)
        self.assertEqual(len(out.getvalue().strip()), 8)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/review_lib.test.py -v; python3 infra/hermes-agent/bin/review-fp-key.test.py -v`
Expected: FAIL with `AttributeError: … 'hmac12'`, and `FileNotFoundError` for `review-fp-key.py`.

- [ ] **Step 3: Implement.** In `review_lib.py`, add `hmac` to the imports and add after `sha12`:

```python
def hmac12(key, value):
    """Keyed customer-id fingerprint (Option B §8): a 10-digit id cannot be brute-forced
    from it without the review key, which lives only on the operator's laptop."""
    return hmac.new(key, str(value).encode(), hashlib.sha256).hexdigest()[:12]


def load_fp_key(text):
    t = (text or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", t):
        raise ValueError("the review fingerprint key must be 64 lowercase hex characters")
    return bytes.fromhex(t)


def key_id(key):
    return hashlib.sha256(key).hexdigest()[:8]
```

   In `Redactor.__init__`, add the parameter `fp_key=None` and store `self._fp = (lambda d: hmac12(fp_key, d)) if fp_key else sha12`. In `text()`, replace `"cid:" + sha12(digits)` with `"cid:" + self._fp(digits)`. In `from_clients_json(cls, path, fp_key=None)`, pass `fp_key=fp_key` to `cls(...)`.

   `bin/review-fp-key.py`:

```python
#!/usr/bin/env python3
"""The review fingerprint key (Option B §8). Laptop only. Stdlib only.

  review-fp-key.py init     [--path ~/.config/hermes-review/fp.key]   # 32 random bytes, hex, 0600
  review-fp-key.py show-id  [--path ...]                              # 8-hex id, safe to paste

The key never goes to the box's disk: the box collector reads it from the tty for one run.
Copy it for that paste with `pbcopy < ~/.config/hermes-review/fp.key`. Never printed here."""
import argparse, os, secrets, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import review_lib as R

DEFAULT = os.path.expanduser("~/.config/hermes-review/fp.key")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("init", "show-id"))
    ap.add_argument("--path", default=DEFAULT)
    a = ap.parse_args(argv)
    if a.cmd == "init":
        os.makedirs(os.path.dirname(a.path), mode=0o700, exist_ok=True)
        try:
            fd = os.open(a.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            print(f"review-fp-key: {a.path} exists; refusing to overwrite (it would orphan past fingerprints)",
                  file=sys.stderr)
            return 2
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32) + "\n")
        print(f"review-fp-key: created {a.path} (0600)")
        return 0
    with open(a.path) as f:
        print(R.key_id(R.load_fp_key(f.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/review_lib.test.py -v && python3 infra/hermes-agent/bin/review-fp-key.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/review_lib.py infra/hermes-agent/bin/review_lib.test.py infra/hermes-agent/bin/review-fp-key.py infra/hermes-agent/bin/review-fp-key.test.py
git commit -m "feat(hermes): keyed cid fingerprints (HMAC-SHA256) + laptop review key tool (Option B §8)"
```

---

### Task 2: Both collectors require the review key

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`context`, `collect_with_secrets`, `main`)
- Modify: `infra/hermes-agent/bin/collect-review-evidence-laptop.py`
- Test: both `.test.py` files (append)

**Interfaces:**
- Produces:
  - box: `context(host, fp_key)`, `collect_with_secrets(host, fp_key)`, `collect(host, fp_key)`, and `main(argv, host, read_key=_tty_key)`. The full bundle needs `--fp-key-tty` and exits 2 without it. `--fingerprint-only` and `--credentials-only` still work without a key: they carry no cids.
  - The bundle gains `"cid_fingerprint": "hmac-sha256/12"` and `"cid_key_id": <8 hex>`.
  - laptop: `--fp-key-file` (default `~/.config/hermes-review/fp.key`), with the same two bundle fields.

- [ ] **Step 1: Write the failing tests** (append to `collect-review-evidence.test.py`)

In `Base`, add `KEY = bytes.fromhex("11" * 32)`. Change every existing `CE.collect(self.host())` to `CE.collect(self.host(), self.KEY)`, and `CE.main([], host=self.host())` to `CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)`. Then:

```python
class TestKeyedBundle(Base):
    def test_cids_are_keyed_and_key_id_recorded(self):
        b = CE.collect(self.host(), self.KEY)
        self.assertEqual(b["cid_fingerprint"], "hmac-sha256/12")
        self.assertEqual(b["cid_key_id"], R.key_id(self.KEY))
        self.assertNotIn("cid:" + R.sha12("1234567890"), json.dumps(b))

    def test_fingerprint_does_not_depend_on_the_key(self):
        a = CE.collect(self.host(), self.KEY)["fingerprint"]
        b = CE.collect(self.host(), bytes.fromhex("22" * 32))["fingerprint"]
        self.assertEqual(a, b)

    def test_full_bundle_without_key_refuses(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(CE.main([], host=self.host()), 2)
            self.assertEqual(CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "nothex"), 2)

    def test_key_never_printed(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            CE.main(["--fp-key-tty"], host=self.host(), read_key=lambda: "11" * 32)
        self.assertNotIn("11" * 32, out.getvalue())
```

   Append to `collect-review-evidence-laptop.test.py`, following its existing invocation pattern (it runs `main([...])` with `--customer` and package args). Add a test that `--fp-key-file <tmp with "11"*32>` yields `cid_key_id == R.key_id(bytes.fromhex("11"*32))`, and that a missing key file gives exit 2.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v`
Expected: FAIL with `TypeError: collect() takes 1 positional argument`.

- [ ] **Step 3: Implement (box collector)**

```python
def _tty_key():
    try:
        return getpass.getpass("review fingerprint key (hidden, from `pbcopy < ~/.config/hermes-review/fp.key`): ")
    except (EOFError, OSError):
        return ""


def context(host, fp_key=None):
    """Loaded once per run. Raises ValueError when the redaction list cannot load."""
    return {"redactor": R.Redactor.from_clients_json(host.path(GOV + "/registry/clients.json"), fp_key=fp_key)}
```

   `collect_with_secrets(host, fp_key)` calls `context(host, fp_key)` and adds `"cid_fingerprint": "hmac-sha256/12", "cid_key_id": R.key_id(fp_key)` to `bundle`. `collect(host, fp_key)` passes it through.

   In `main(argv=None, host=None, read_key=_tty_key)`, add `g.add_argument("--fp-key-tty", action="store_true")` outside the mutually exclusive group, as its own `ap.add_argument`. Then:

```python
    fp_key = None
    if a.fp_key_tty:
        try:
            fp_key = R.load_fp_key(read_key())
        except ValueError as e:
            print(f"collect-review-evidence: {e}", file=sys.stderr); return 2
    if not (a.fingerprint_only or a.credentials_only) and fp_key is None:
        print("collect-review-evidence: the full bundle needs --fp-key-tty (Option B §8: keyed cid fingerprints)",
              file=sys.stderr)
        return 2
    host = host or Host()
    try:
        ctx = context(host, fp_key)
    ...
    else:
        out, secrets = collect_with_secrets(host, fp_key)
    ...
    R.assert_no_secret(text, secrets + ([fp_key.hex()] if fp_key else []))
```

   Add `getpass` to the imports.

- [ ] **Step 4: Implement (laptop collector).** Add `ap.add_argument("--fp-key-file", default=os.path.expanduser("~/.config/hermes-review/fp.key"))`. Read it with `R.load_fp_key(open(path).read())`; on `OSError` or `ValueError`, print a one-line refusal and `return 2`. Build `red = R.Redactor([], [customer], fp_key=key)`, and add `cid_fingerprint` and `cid_key_id` to the laptop bundle dict.

- [ ] **Step 5: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v && python3 infra/hermes-agent/bin/collect-review-evidence-laptop.test.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/collect-review-evidence-laptop.py infra/hermes-agent/bin/collect-review-evidence-laptop.test.py
git commit -m "feat(hermes): review collectors require the fingerprint key; bundles record cid_key_id"
```

---

### Task 3: `run-client-audit --probe-env` and `--probe-egress`

**Files:**
- Modify: `infra/hermes-agent/bin/run-client-audit.py`
- Modify: `infra/hermes-agent/bin/run-client-audit.test.py`
- Modify: `infra/hermes-agent/deploy/audit-mounts-integration.test.py`

**Interfaces:**
- Produces:
  - `run-client-audit --probe-env` and `run-client-audit --probe-egress` (root only, no client argument; each prints one JSON object on stdout).
  - `probe_env(root, runner) -> dict`: `{"services": {svc: {"env_names": [...], "sentinel_in_files": bool}}, "matches_declared": bool}`.
  - `probe_egress(root, runner) -> dict`: `{"direct": "blocked|open", "non_allowed": "<status line>", "anthropic": "<status line>", "work_entries": [...], "host_visible": bool, "matches_expected": bool}`.
  - `DECLARED = {"ads-collector": ["GOOGLE_ADS_"], "ads-reader": ["GOOGLE_ADS_"], "ads-drafter": ["ANTHROPIC_"], "egress-proxy": []}`.
- The runner used here is `probe_runner(argv, env, timeout) -> (rc, stdout)`, which differs from the audit runner.

- [ ] **Step 1: Refactor `plan()` so the probe reuses it exactly.** Give it two optional parameters, `cred_values=None` and `anthropic_key=None`. When given, they replace `L.load_cred_env(root + CRED)` and `L.load_env_value(root + ANTHROPIC_CRED, …)`, so the probe never opens the real files. The audit path passes neither, so nothing changes.

- [ ] **Step 2: Write the failing unit tests** (append to `run-client-audit.test.py`)

```python
class TestProbes(Base):
    def fake_probe_runner(self, outputs):
        calls = []
        def run(argv, env, timeout):
            calls.append((argv, dict(env)))
            for svc, out in outputs.items():
                if svc in argv:
                    return 0, out
            return 0, ""
        return run, calls

    def test_probe_env_uses_sentinels_and_never_opens_real_secret_files(self):
        opened = []
        real_open = open
        def spy(p, *a, **k):
            opened.append(str(p)); return real_open(p, *a, **k)
        outs = {"ads-collector": "GOOGLE_ADS_REFRESH_TOKEN\nGOOGLE_ADS_CUSTOMER_ID\nSENTINEL_FILES=0\n",
                "ads-reader": "GOOGLE_ADS_REFRESH_TOKEN\nSENTINEL_FILES=0\n",
                "ads-drafter": "ANTHROPIC_API_KEY\nSENTINEL_FILES=0\n",
                "egress-proxy": "SENTINEL_FILES=0\n"}
        run, calls = self.fake_probe_runner(outs)
        with mock.patch("builtins.open", spy):
            j = RCA.probe_env(self.root, run)
        self.assertTrue(j["matches_declared"], j)
        self.assertFalse(any(p.endswith(".env.ga") or p.endswith(".env.anthropic") for p in opened))
        for argv, env in calls:
            for v in env.values():
                self.assertNotIn("sk-ant-api03-x", v); self.assertNotIn(TOKEN, v)

    def test_probe_env_flags_a_leak(self):
        outs = {"ads-collector": "GOOGLE_ADS_REFRESH_TOKEN\nSENTINEL_FILES=0\n",
                "ads-reader": "GOOGLE_ADS_REFRESH_TOKEN\nSENTINEL_FILES=0\n",
                "ads-drafter": "ANTHROPIC_API_KEY\nGOOGLE_ADS_REFRESH_TOKEN\nSENTINEL_FILES=0\n",
                "egress-proxy": "SENTINEL_FILES=0\n"}
        run, _ = self.fake_probe_runner(outs)
        self.assertFalse(RCA.probe_env(self.root, run)["matches_declared"])

    def test_probe_egress_expected_and_cleans_up(self):
        outs = {"ads-drafter": "DIRECT_BLOCKED\nHTTP/1.1 403 Forbidden\nHTTP/1.1 200 Connection Established\n"
                               "WORK=out,reports,vault\nHOST_VISIBLE=0\n"}
        run, calls = self.fake_probe_runner(outs)
        j = RCA.probe_egress(self.root, run)
        self.assertTrue(j["matches_expected"], j)
        self.assertEqual(len(self.proxy_stops), 1)
        self.assertFalse(os.path.exists(self.root + RCA.PROBE_DIR))

    def test_probe_cleans_up_when_docker_fails(self):
        def boom(argv, env, timeout):
            raise OSError("docker down")
        with self.assertRaises(OSError):
            RCA.probe_egress(self.root, boom)
        self.assertEqual(len(self.proxy_stops), 1)
        self.assertFalse(os.path.exists(self.root + RCA.PROBE_DIR))
```

   (Add `from unittest import mock` at the top if it's absent; the file already imports it.)

- [ ] **Step 3: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py TestProbes -v`
Expected: FAIL with `AttributeError: … 'probe_env'`.

- [ ] **Step 4: Implement** (in `run-client-audit.py`)

```python
PROBE_DIR = "/var/lib/hermes/probe"
PROBE_SLUG = "probe"
SENTINEL = "HERMESPROBESENTINEL0123456789"
DECLARED = {"ads-collector": ["GOOGLE_ADS_"], "ads-reader": ["GOOGLE_ADS_"],
            "ads-drafter": ["ANTHROPIC_"], "egress-proxy": []}
_ENV_PROBE = ("env | cut -d= -f1 | grep -E '^(GOOGLE_ADS_|ANTHROPIC_|OPENROUTER_)' | sort; "
              "n=$(grep -rlF " + SENTINEL + " /projects /work /opt/cc-bin /opt/skills /opt/registry 2>/dev/null | wc -l); "
              "echo SENTINEL_FILES=$n")
_EGRESS_PROBE = r'''python3 - <<'EOF'
import os, socket
def direct():
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=5); return "DIRECT_OPEN"
    except OSError:
        return "DIRECT_BLOCKED"
def via(t):
    s = socket.create_connection(("egress-proxy", 3128), timeout=10)
    s.sendall(("CONNECT %s HTTP/1.1\r\nHost: x\r\n\r\n" % t).encode())
    return s.recv(128).split(b"\r\n")[0].decode()
print(direct()); print(via("example.com:443")); print(via("api.anthropic.com:443"))
print("WORK=" + ",".join(sorted(os.listdir("/work"))))
print("HOST_VISIBLE=%d" % os.path.exists("/var/lib/hermes"))
EOF'''


def probe_runner(argv, env, timeout):
    p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout


def _probe_layout(root):
    """Throwaway, empty per-client dirs: the probes never mount a real client's data."""
    base = root + PROBE_DIR
    if os.path.lexists(base):
        shutil.rmtree(base)
    for d in ("audit-data", "vaults", "reports", "draft-out"):
        L.reset_dir(f"{base}/{d}/{PROBE_SLUG}",
                    **({"uid": os.geteuid(), "gid": os.getegid()} if DATA_UID is None
                       else {"uid": DATA_UID, "gid": DATA_GID}))
    return base


def _probe_steps(root):
    rec = {"slug": PROBE_SLUG, "customer_id": "0000000000"}
    cred = {n: SENTINEL for n in CRED_NAMES}
    steps = plan(rec, "2000-01-01_00-00-00", root, cred_values=cred, anthropic_key=SENTINEL)
    base = PROBE_DIR
    out = {}
    for key, argv, env in steps:
        if key not in ("collect", "read", "draft"):
            continue
        env = dict(env)
        for k in ("HERMES_AUDIT_DATA_DIR", "HERMES_REPORTS_DIR", "HERMES_VAULT_DIR", "HERMES_DRAFT_OUT_DIR"):
            if k in env:
                env[k] = f"{base}/" + {"HERMES_AUDIT_DATA_DIR": "audit-data", "HERMES_REPORTS_DIR": "reports",
                                       "HERMES_VAULT_DIR": "vaults", "HERMES_DRAFT_OUT_DIR": "draft-out"}[k] + "/" + PROBE_SLUG
        svc = next(s for s in ("ads-collector", "ads-reader", "ads-drafter") if s in argv)
        out.setdefault(svc, (argv, env))            # one of each service is enough
    return out


def _override(argv, svc, script):
    """Same run argv (flags, -e names, --name), entrypoint replaced by sh -c <script>."""
    i = argv.index(svc)
    return argv[:i] + ["--entrypoint", "sh", svc, "-c", script]


def probe_env(root, runner=probe_runner):
    base = _probe_layout(root)
    try:
        services = {}
        steps = _probe_steps(root)
        proxy_env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")}
        steps["egress-proxy"] = (_compose(root) + ["run", "--rm", "--no-deps", "-T", "egress-proxy"], proxy_env)
        for svc, (argv, env) in sorted(steps.items()):
            rc, out = runner(_override(argv, svc, _ENV_PROBE), env, 120)
            names = sorted(l for l in out.splitlines() if re.match(r"^(GOOGLE_ADS_|ANTHROPIC_|OPENROUTER_)", l))
            m = re.search(r"SENTINEL_FILES=(\d+)", out)
            services[svc] = {"rc": rc, "env_names": names, "sentinel_in_files": bool(m and int(m.group(1)))}
        ok = set(services) == set(DECLARED) and all(_matches(svc, s) for svc, s in services.items())
        return {"services": services, "matches_declared": ok}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _matches(svc, s):
    """A service matches the declared map when it ran, holds no sentinel in any mounted file,
    and every credential-shaped env name it holds has a declared prefix (and it holds at least
    one when a prefix is declared; none when none is)."""
    if s["rc"] != 0 or s["sentinel_in_files"]:
        return False
    prefixes = DECLARED[svc]
    if not prefixes:
        return s["env_names"] == []
    return bool(s["env_names"]) and all(any(n.startswith(p) for p in prefixes) for n in s["env_names"])
```

```python
def probe_egress(root, runner=probe_runner):
    base = _probe_layout(root)
    try:
        argv, env = _probe_steps(root)["ads-drafter"]
        env = {k: v for k, v in env.items() if k != "ANTHROPIC_API_KEY"}   # the probe needs no key
        clean, skip = [], False                                            # drop "-e ANTHROPIC_API_KEY" as a pair
        for i, a in enumerate(argv):
            if skip:
                skip = False; continue
            if a == "-e" and i + 1 < len(argv) and argv[i + 1] == "ANTHROPIC_API_KEY":
                skip = True; continue
            clean.append(a)
        argv = clean
        rc, _ = runner(_compose(root) + ["up", "-d", "--no-deps", "egress-proxy"], env, 60)
        rc, out = runner(_override(argv, "ads-drafter", _EGRESS_PROBE), env, 120)
        lines = out.splitlines()
        get = lambda i: lines[i] if len(lines) > i else ""
        work = next((l[5:].split(",") for l in lines if l.startswith("WORK=")), [])
        host_visible = any(l == "HOST_VISIBLE=1" for l in lines)
        j = {"direct": "blocked" if get(0) == "DIRECT_BLOCKED" else "open",
             "non_allowed": get(1), "anthropic": get(2), "work_entries": work, "host_visible": host_visible}
        j["matches_expected"] = (j["direct"] == "blocked" and " 403" in j["non_allowed"]
                                 and " 200" in j["anthropic"] and sorted(work) == ["out", "reports", "vault"]
                                 and not host_visible)
        return j
    finally:
        # stop_proxy(root, logs, say) since the part-1 final review: proxy.log lands in the probe's
        # temp layout, which is removed with it; a failed rm still warns on stderr.
        stop_proxy(root, base, lambda s: print(s, file=sys.stderr))
        shutil.rmtree(base, ignore_errors=True)
```

   In `main()`:
   - make `client` optional: `ap.add_argument("client", nargs="?")`;
   - add `--probe-env` and `--probe-egress` in a mutually exclusive group with `--list`;
   - make an audit, dry run or list without `client` an `ap.error`.
   
   Before `eligible_client`:

```python
    if a.probe_env or a.probe_egress:
        j = (probe_env if a.probe_env else probe_egress)(root)
        print(json.dumps(j, sort_keys=True))
        return 0 if j.get("matches_declared", j.get("matches_expected")) else 1
```

   Add `re` and `shutil` to the imports if absent. The wrapper `deploy/run-client-audit` already requires root.

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/run-client-audit.test.py -v`
Expected: all PASS.

- [ ] **Step 6: Add the real-Docker integration test** (append to `TestAuditMounts` in `audit-mounts-integration.test.py`). In `setUpClass`, write the stand-in `.env` with the interpolation variables instead of leaving it empty, so that `run-client-audit`'s env-less compose calls render:

```python
        with open(os.path.join(cls.agent, ".env"), "w") as f:
            f.write(f"HERMES_SPOOL_DIR={cls.tmp}\nHERMES_GOVERNANCE_DIR={cls.tmp}/governance\n"
                    f"HERMES_AGENT_DIR={cls.agent}\nHERMES_ADS_REPO_DIR={cls.tmp}/claude-google-ads\n")
```

```python
    def _rca(self):
        import importlib.util
        s = importlib.util.spec_from_file_location("rca_it", os.path.join(self.agent, "bin/run-client-audit.py"))
        m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
        m.AGENT_DIR = self.agent            # compose file of the copied tree
        m.PROBE_DIR = os.path.join(self.tmp, "probe")
        return m

    def test_probe_env_matches_the_declared_map(self):
        j = self._rca().probe_env("")
        self.assertTrue(j["matches_declared"], json.dumps(j, indent=1))

    def test_probe_egress_matches_expected(self):
        j = self._rca().probe_egress("")
        self.assertTrue(j["matches_expected"], json.dumps(j, indent=1))
```

   Notes: `probe_*("")` makes `root + PROBE_DIR` equal the absolute temp path set above. `_compose("")` resolves `AGENT_DIR` + `/docker-compose.yml` to the copied tree.

- [ ] **Step 7: Commit, push, and confirm the "Bind agreement" CI job passes with both probes**

```bash
git add infra/hermes-agent/bin/run-client-audit.py infra/hermes-agent/bin/run-client-audit.test.py infra/hermes-agent/deploy/audit-mounts-integration.test.py
git commit -m "feat(hermes): run-client-audit --probe-env / --probe-egress (sentinels, throwaway dirs) + real-Docker CI"
git push -u origin HEAD && gh run watch
```

Expected: CI is green.

---

### Task 4: The collector's D2.1, D4.1 and D7.1 follow the new layout

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py`
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Produces:
  - **D2.1:** `AUTHORISED_OTHER` becomes `{CHECKOUT + "/infra/hermes-agent/.env": "gateway-env", "/etc/hermes/.env.anthropic": "anthropic-key"}`. The row for `/etc/hermes/.env.anthropic` also carries `"anthropic_key_state": "real|dummy|missing"`, via `client_audit_lib.anthropic_key_state`, which never exposes the value.
  - **D4.1:**
    - `GATEWAY_PROBE_PATHS` adds `/var/lib/hermes/vaults`, `/var/lib/hermes/reports`, `/var/lib/hermes/draft-out`, `/var/lib/hermes/audit-data`, `/var/lib/hermes/app-state`, `/etc/hermes/.env.anthropic`, `/opt/data/vaults`, `/opt/data/reports` and `/opt/data/home/.claude/settings.json`;
    - the output adds `anthropic_env_names` and `openrouter_env_names` (names only).
  - **D7.1:** `vaults` rows come from `/var/lib/hermes/vaults/*`; new rows `reports_rows` and `draft_out_rows`, each `{status, owner, mode}`; `parents: {vaults|reports|draft-out: _dir_row}`; `old_data: {"data/vaults": _dir_row, "data/reports": _dir_row}`, both expected `absent`. The old `reports` key is removed.

- [ ] **Step 1: Write the failing tests** (append; follow `TestAuditsOnTheBox`'s fixture style)

```python
class TestOptionBLayout(Base):
    def test_d7_1_reads_the_new_paths_and_reports_old_data_absent(self):
        for d in ("vaults", "reports", "draft-out"):
            os.makedirs(os.path.join(self.root, "var/lib/hermes", d, "acme-dental"))
        items = CE.collect(self.host(), self.KEY)["items"]
        d = items["D7.1"]["data"]
        self.assertEqual([r["status"] for r in d["vaults"]], ["active"])
        self.assertEqual([r["status"] for r in d["reports_rows"]], ["active"])
        self.assertEqual([r["status"] for r in d["draft_out_rows"]], ["active"])
        self.assertEqual(d["old_data"], {"data/vaults": "absent", "data/reports": "absent"})
        self.assertIn("vaults", d["parents"])
        self.assertNotIn("acme-dental", json.dumps(d))

    def test_d7_1_flags_leftover_old_data(self):
        os.makedirs(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), "data/vaults/acme-dental"))
        d = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]
        self.assertIsInstance(d["old_data"]["data/vaults"], dict)

    def test_d4_1_probes_the_moved_data_and_the_key_file(self):
        for p in ("/var/lib/hermes/vaults", "/etc/hermes/.env.anthropic", "/opt/data/home/.claude/settings.json"):
            self.assertIn(p, CE.GATEWAY_PROBE_PATHS)

    def test_d2_1_anthropic_key_file_is_authorised_and_its_state_reported(self):
        self._w("/etc/hermes/.env.anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-SECRETVALUE\n")
        self.outputs[("find",)] = (0, "/etc/hermes/.env.anthropic\n", "")
        rows = CE.collect(self.host(), self.KEY)["items"]["D2.1"]["data"]["files"]
        row = [r for r in rows if r["path"] == "/etc/hermes/.env.anthropic"][0]
        self.assertEqual((row["kind"], row["label"], row["anthropic_key_state"]), ("authorised-other", "anthropic-key", "real"))
        self.assertNotIn("SECRETVALUE", json.dumps(rows))
```

   Delete or adapt the existing tests that read `data/vaults` and `data/reports` (`test_d7_1_vault_rows_carry_the_registry_status_without_slugs`, `test_d7_1_reports_reports_dir_and_absent`, `test_d7_1_symlinked_reports_dir_is_reported`) so they use the new paths and keys. Keep their symlink assertions: move them to `parents` (a symlinked `/var/lib/hermes/reports` is reported as `"symlink"`).

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v`
Expected: the new tests FAIL (`KeyError: 'reports_rows'`, …).

- [ ] **Step 3: Implement.** In `d2_1`, after assigning `authorised-other`, add:

```python
                        if p == "/etc/hermes/.env.anthropic":
                            import client_audit_lib as CAL
                            row["anthropic_key_state"] = CAL.anthropic_key_state(host.path(p))
```

   (Put `import client_audit_lib as CAL` at module top instead of inline, with the other imports.)

   In `d4_1`, after `env = …`:

```python
    names = [l.split("=", 1)[0] for l in env.splitlines() if "=" in l]
    return {"paths": out.splitlines(),
            "google_ads_env_names": sorted(n for n in names if n.startswith("GOOGLE_ADS_")),
            "anthropic_env_names": sorted(n for n in names if n.startswith("ANTHROPIC_")),
            "openrouter_env_names": sorted(n for n in names if n.startswith("OPENROUTER_"))}
```

   Replace `d7_1`'s vault block and the `reports` key:

```python
HERMES_VAR = "/var/lib/hermes"


def _client_rows(host, reg, parent):
    root = host.path(parent)
    rows = []
    if os.path.isdir(root) and not os.path.islink(root):
        for name in sorted(os.listdir(root)):
            st = os.lstat(os.path.join(root, name))
            rows.append({"status": _reg_status(reg, name), "owner": _owner(st.st_uid),
                         "mode": oct(stat.S_IMODE(st.st_mode))})
    return rows
```

   and in `d7_1` return:

```python
    return {"vaults": _client_rows(host, reg, HERMES_VAR + "/vaults"),
            "reports_rows": _client_rows(host, reg, HERMES_VAR + "/reports"),
            "draft_out_rows": _client_rows(host, reg, HERMES_VAR + "/draft-out"),
            "parents": {d: _dir_row(host, f"{HERMES_VAR}/{d}") for d in ("vaults", "reports", "draft-out")},
            "old_data": {"data/vaults": _dir_row(host, AGENT_DIR + "/data/vaults"),
                         "data/reports": _dir_row(host, AGENT_DIR + "/data/reports")},
            "audit_data": audit, "audit_logs": _audit_logs(host, reg),
            "records": …, "root_backups": …}   # the last two unchanged
```

- [ ] **Step 4: Run to verify they pass, then commit**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v`
Expected: all PASS.

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): review collector follows the Option B layout (D2.1, D4.1, D7.1)"
```

---

### Task 5: The collector's D10 box probes

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (new probes, added to `PROBES`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Produces the new `PROBES` keys `D10.1`, `D10.2`, `D10.3`, `D10.4`, `D10.6`, `D10.7` and `D10.8`, with these outputs:
  - **D10.1:** the JSON of `run-client-audit --probe-env`, plus `rc`.
  - **D10.2:** the JSON of `run-client-audit --probe-egress`, plus `rc`.
  - **D10.3:**
    - `broker_unit`: from `systemctl show hermes-app-broker@ads-audit -p User,NoNewPrivileges,CapabilityBoundingSet,PrivateNetwork,ProtectSystem,ReadWritePaths,ActiveState`;
    - `installed_equal_repo` for the three units (sha256 of `/etc/systemd/system/<unit>` versus `CHECKOUT/infra/hermes-agent/deploy/<unit>`);
    - `broker_user_groups` (`id -nG hermes-app-ads-audit`);
    - `sudo_rules` (the `sudo -l -U hermes-app-ads-audit` output, redacted; expected "not allowed");
    - `runner_path_active`.
  - **D10.4:** `layout_problems` (`host_layout.check_app("ads-audit", …)` with the system resolver), and `containers_mounting_app_state` (a count, from `docker ps -q` and `docker inspect --format '{{json .Mounts}}'`).
  - **D10.6:** `mcp_block` (the lines of `data/config.yaml` from `mcp_servers:` up to the next top-level key, with no secrets: the block has none), and `gateway_mcp_list` (`docker exec <gw> hermes mcp list` stdout, redacted).
  - **D10.7:** `journal_counts`, a `{"<status>/<reason>": n}` map from `journalctl -u hermes-app-broker@ads-audit --since -30d -o cat`, parsing `status=` and `reason=` only (slugs dropped).
  - **D10.8:** `results`, one row per file in `spool/apps/ads-audit/results/`: `{"op", "status", "reason", "keys_ok": bool, "values_ok": bool}` (slug dropped), plus `out_of_whitelist` (a count).

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestD10(Base):
    def setUp(self):
        super().setUp()
        self.outputs[("run-client-audit", "--probe-env")] = (0, json.dumps({"matches_declared": True, "services": {}}), "")
        self.outputs[("run-client-audit", "--probe-egress")] = (0, json.dumps({"matches_expected": True}), "")
        self.outputs[("journalctl",)] = (0, "hermes-app-broker[ads-audit]: request=x op=run client=acme-dental status=refused reason=quota\n"
                                            "hermes-app-broker[ads-audit]: request=y op=run client=acme-dental status=ok reason=-\n", "")
        res = os.path.join(self.root, "var/lib/hermes/spool/apps/ads-audit/results"); os.makedirs(res)
        good = {"request_id": "0f8e2c1a-1111-4222-8333-444455556666", "op": "run", "client": "acme-dental",
                "status": "ok", "reason": None, "exit_code": 0, "ts": "2026-10-01_12-00-00", "steps": [],
                "vault_path": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md"}
        json.dump(good, open(os.path.join(res, good["request_id"] + ".json"), "w"))
        bad = dict(good, request_id="1f8e2c1a-1111-4222-8333-444455556666", reason="free text")
        json.dump(bad, open(os.path.join(res, bad["request_id"] + ".json"), "w"))

    def test_probes_registered(self):
        for k in ("D10.1", "D10.2", "D10.3", "D10.4", "D10.6", "D10.7", "D10.8"):
            self.assertIn(k, CE.PROBES)
        self.assertNotIn("D10.5", CE.PROBES)                          # manual

    def test_d10_1_and_2_carry_the_probe_json(self):
        items = CE.collect(self.host(), self.KEY)["items"]
        self.assertTrue(items["D10.1"]["data"]["probe"]["matches_declared"])
        self.assertTrue(items["D10.2"]["data"]["probe"]["matches_expected"])

    def test_d10_7_counts_without_slugs(self):
        d = CE.collect(self.host(), self.KEY)["items"]["D10.7"]["data"]
        self.assertEqual(d["journal_counts"], {"refused/quota": 1, "ok/-": 1})
        self.assertNotIn("acme-dental", json.dumps(d))

    def test_d10_8_flags_out_of_whitelist_results(self):
        d = CE.collect(self.host(), self.KEY)["items"]["D10.8"]["data"]
        self.assertEqual(d["out_of_whitelist"], 1)
        self.assertNotIn("acme-dental", json.dumps(d))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestD10 -v`
Expected: FAIL (`D10.1` isn't in `PROBES`).

- [ ] **Step 3: Implement.** Add these near the other constants:

```python
APP = "ads-audit"
APP_UNITS = ("hermes-app-broker@.service", "hermes-app-runner@.service", "hermes-app-runner@.path")
APP_RESULTS = "/var/lib/hermes/spool/apps/" + APP + "/results"
```

   and the probes:

```python
def _json_probe(host, flag):
    rc, out, err = host.run(["run-client-audit", flag], timeout=300)
    try:
        return {"rc": rc, "probe": json.loads(out)}
    except ValueError:
        raise CouldNotCheck(f"run-client-audit {flag} exited {rc} without JSON")


def d10_1(host, ctx):
    return _json_probe(host, "--probe-env")


def d10_2(host, ctx):
    return _json_probe(host, "--probe-egress")


def _file_sha(host, p):
    try:
        with open(host.path(p), "rb") as f:
            return PK.sha256_bytes(f.read())
    except OSError:
        return None


def d10_3(host, ctx):
    props = _ok(host, ["systemctl", "show", f"hermes-app-broker@{APP}", "-p",
                       "User,NoNewPrivileges,CapabilityBoundingSet,PrivateNetwork,ProtectSystem,ReadWritePaths,ActiveState"])
    rc, sudo_out, _ = host.run(["sudo", "-l", "-U", f"hermes-app-{APP}"])
    return {"broker_unit": dict(l.split("=", 1) for l in props.splitlines() if "=" in l),
            "installed_equal_repo": {u: _file_sha(host, "/etc/systemd/system/" + u) is not None and
                                     _file_sha(host, "/etc/systemd/system/" + u) ==
                                     _file_sha(host, CHECKOUT + "/infra/hermes-agent/deploy/" + u) for u in APP_UNITS},
            "broker_user_groups": _ok(host, ["id", "-nG", f"hermes-app-{APP}"]).split(),
            "sudo_rules": sudo_out.strip().splitlines()[-1:] if sudo_out else [],
            "runner_path_active": _ok(host, ["systemctl", "is-active", f"hermes-app-runner@{APP}.path"]).strip()}


def d10_4(host, ctx):
    import host_layout as HL
    problems = HL.check_app(APP, host.path(HL.DEFAULT_APPS_ROOT), host.path(HL.DEFAULT_STATE_ROOT),
                            HL.system_resolver())
    ids = _ok(host, ["docker", "ps", "-q", "--no-trunc"]).split()
    n = 0
    for cid in ids:
        mounts = _ok(host, ["docker", "inspect", "--format", "{{json .Mounts}}", cid])
        if "/var/lib/hermes/app-state" in mounts:
            n += 1
    return {"layout_problems": problems, "containers_mounting_app_state": n}


def d10_6(host, ctx):
    lines, on = [], False
    with open(host.path(AGENT_DIR + "/data/config.yaml"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("mcp_servers:"):
                on = True
            elif on and line[:1].strip() and not line.startswith("#"):
                break
            if on:
                lines.append(line.rstrip("\n"))
    gw = _ok(host, ["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER]).strip()
    listing = _ok(host, ["docker", "exec", gw, "hermes", "mcp", "list"]).splitlines() if len(gw) == 64 else []
    return {"mcp_block": lines, "gateway_mcp_list": listing}


def d10_7(host, ctx):
    out = _ok(host, ["journalctl", "-u", f"hermes-app-broker@{APP}", "--since", "-30d", "-o", "cat"])
    counts = {}
    for line in out.splitlines():
        s = re.search(r"\bstatus=(\S+)", line); r = re.search(r"\breason=(\S+)", line)
        if s and r:
            k = f"{s.group(1)}/{r.group(1)}"
            counts[k] = counts.get(k, 0) + 1
    return {"journal_counts": counts}


def d10_8(host, ctx):
    import app_lib as A
    rows, bad = [], 0
    d = host.path(APP_RESULTS)
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            obj = json.loads(A.read_capped(os.path.join(d, n), A.MAX_DONE_BYTES))
        except (A.Refused, ValueError):
            rows.append({"keys_ok": False, "values_ok": False}); bad += 1; continue
        keys_ok, values_ok = A.result_in_whitelist(obj)
        rows.append({"op": obj.get("op") if obj.get("op") in A.KNOWN_OPS else "?",
                     "status": obj.get("status") if obj.get("status") in A.STATUSES else "?",
                     "reason": obj.get("reason") if obj.get("reason") in A.BROKER_REASONS + A.COMMAND_REASONS else
                               ("-" if obj.get("reason") is None else "?"),
                     "keys_ok": keys_ok, "values_ok": values_ok})
        bad += not (keys_ok and values_ok)
    return {"results": rows, "out_of_whitelist": bad}
```

   `A.result_in_whitelist` doesn't exist yet. Add it to `app_lib.py` with its own test in `app_lib.test.py`:

```python
def result_in_whitelist(r):
    """(keys_ok, values_ok) for a result file, re-checked independently of the broker (review D10.8)."""
    run_keys = {"request_id", "op", "client", "status", "reason", "exit_code", "ts", "steps", "vault_path"}
    list_keys = {"request_id", "op", "client", "status", "reason", "audits"}
    if not isinstance(r, dict):
        return False, False
    keys_ok = set(r) in (run_keys, list_keys)
    reasons = BROKER_REASONS + COMMAND_REASONS
    values_ok = keys_ok and r["status"] in STATUSES and (r["reason"] is None or r["reason"] in reasons) \
        and (r["client"] is None or _slug(r["client"])) and (r["op"] is None or r["op"] in KNOWN_OPS)
    if values_ok and "audits" in r:
        values_ok = isinstance(r["audits"], list) and all(isinstance(t, str) and TS_RE.match(t) for t in r["audits"])
    if values_ok and "vault_path" in r and r["vault_path"] is not None:
        values_ok = isinstance(r["vault_path"], str) and bool(re.match(
            r"^/var/lib/hermes/vaults/[a-z0-9][a-z0-9_-]{0,63}/audits/[0-9_-]{19}-audit\.md$", r["vault_path"]))
    return keys_ok, values_ok
```

```python
class TestWhitelist(unittest.TestCase):
    def test_result_in_whitelist(self):
        ok = A.refused_result("0f8e2c1a-1111-4222-8333-444455556666", "run", "acme", "quota")
        self.assertEqual(A.result_in_whitelist(ok), (True, True))
        self.assertEqual(A.result_in_whitelist(dict(ok, reason="free text")), (True, False))
        self.assertEqual(A.result_in_whitelist(dict(ok, extra=1)), (False, False))
```

   Register the probes: `PROBES.update({"D10.1": d10_1, "D10.2": d10_2, "D10.3": d10_3, "D10.4": d10_4, "D10.6": d10_6, "D10.7": d10_7, "D10.8": d10_8})`. Put this in the `PROBES` literal itself.

- [ ] **Step 4: Run to verify they pass** (`test_every_checklist_box_id_has_a_probe_and_nothing_else_runs` in `security-review-checklist.test.py` fails until Task 7 adds the D10 items. That's expected; run only the two suites below.)

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v && python3 infra/hermes-agent/bin/app_lib.test.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/bin/app_lib.py infra/hermes-agent/bin/app_lib.test.py
git commit -m "feat(hermes): review collector D10 probes — key placement, egress, units, layout, MCP config, journal, results"
```

---

### Task 6: The review-#5 follow-ups

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`_audit_logs`, `_memory_sweep`, `d4_2`, `main`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Produces:
  - **`audit_logs.rows[*].files`:** `{"<owner> <group> <mode>": count}` for the files inside each client dir, never names.
  - **`memory_sweep.namespace_handles`:** the paths that are `nsfs` mount targets, taken out of `unreadable`.
  - **D4.2:** gains `last_pass_execstart_sha256` (from the new flag `--last-pass-execstart SHA`, validated as 64 hex) and `matches_last_pass` (bool, or `None` when the flag is absent).

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestReview5FollowUps(Base):
    def test_audit_logs_file_modes_counted_without_names(self):
        d = os.path.join(self.root, "var/lib/hermes/audit-logs/acme-dental"); os.makedirs(d)
        for n, mode in (("collect-a.stdout", 0o600), ("collect-a.stderr", 0o644)):
            p = os.path.join(d, n); open(p, "w").close(); os.chmod(p, mode)
        row = CE.collect(self.host(), self.KEY)["items"]["D7.1"]["data"]["audit_logs"]["rows"][0]
        self.assertEqual(sum(row["files"].values()), 2)
        self.assertTrue(any(k.endswith("0o644") for k in row["files"]))
        self.assertNotIn("collect-a", json.dumps(row))

    def test_nsfs_handles_are_classified_not_unreadable(self):
        run = os.path.join(self.root, "run/docker/netns"); os.makedirs(run)
        h = os.path.join(run, "abc123"); open(h, "w").close(); os.chmod(h, 0)
        mounts = [("/run", "tmpfs"), ("/run/docker/netns/abc123", "nsfs")]
        out = CE._memory_sweep(self.host(), mounts)
        self.assertIn("/run/docker/netns/abc123", out["namespace_handles"])
        self.assertNotIn("/run/docker/netns/abc123", out["unreadable"])

    def test_d4_2_compares_with_the_last_pass(self):
        self.outputs[("systemctl", "is-active")] = (0, "active\n", "")
        self.outputs[("systemctl", "show", "hermes-docker-proxy")] = (0, "ExecStart=x\n", "")
        CE.LAST_PASS_EXECSTART = None
        d = CE.d4_2(self.host(), {})
        self.assertIsNone(d["matches_last_pass"])
        CE.LAST_PASS_EXECSTART = d["execstart_sha256"]
        self.assertTrue(CE.d4_2(self.host(), {})["matches_last_pass"])
```

   (If `d4_2`'s `is-active` call uses different argv, match the existing prefix in `self.outputs`, as the existing D4.2 tests do.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestReview5FollowUps -v`
Expected: FAIL (`KeyError: 'files'`, …).

- [ ] **Step 3: Implement**

   In `_audit_logs`, inside the per-child loop, add:

```python
            files = {}
            cdir = os.path.join(host.path(root), name)
            if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                for fn in os.listdir(cdir):
                    fst = os.lstat(os.path.join(cdir, fn))
                    k = f"{_owner(fst.st_uid)} {_group(fst.st_gid)} {oct(stat.S_IMODE(fst.st_mode))}"
                    files[k] = files.get(k, 0) + 1
            rows.append({..., "files": files})        # the existing keys plus files
```

   In `_memory_sweep`:
   - compute `ns = {t for t, fs in mounts if fs == "nsfs"}` at the top, and `handles = set()`;
   - in the file loop, before `os.lstat`, add `if shown in ns: handles.add(shown); continue`;
   - add `"namespace_handles": sorted(handles)` to the returned dict.

   Module constant: `LAST_PASS_EXECSTART = None`. In `d4_2`, return also:

```python
    sha = PK.sha256_bytes(execstart.encode())
    return {"active": active, "execstart_sha256": sha, "last_pass_execstart_sha256": LAST_PASS_EXECSTART,
            "matches_last_pass": None if LAST_PASS_EXECSTART is None else sha == LAST_PASS_EXECSTART}
```

   In `main`, add `ap.add_argument("--last-pass-execstart")`. When given, validate it with `re.fullmatch(r"[0-9a-f]{64}", …)`; if that fails, print a refusal and return 2. Then set the module global `LAST_PASS_EXECSTART`.

- [ ] **Step 4: Run to verify they pass, then commit**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py -v`
Expected: all PASS.

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): review-#5 follow-ups — audit-log file modes, nsfs handles, last-PASS execstart"
```

---

### Task 7: Checklist v1.11, the reviewer packet, the procedure, and the PR

**Files:**
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`, `REVIEWER-BRIEF.md`, `REPORT-TEMPLATE.md`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (the review procedure)

- [ ] **Step 1: Edit `CHECKLIST.md`**
  - Set `version: 1.11`, and append to the version history paragraph: `(v1.11: Option B — D2.1 Anthropic key file + OpenRouter in the gateway env; D4.1 moved client data, no gateway Anthropic key; D4.2 last-PASS baseline carried in the bundle; D7.1 new paths, per-file audit-log modes; new D10 chat-triggered apps; memory_sweep nsfs handles classified.)`
  - Edit D2.1, D4.1, D4.2 and D7.1's **expected** and **pass rule** lines to match spec §8.1 and Tasks 4 and 6:
    - **D2.1:** the `anthropic-key` row is `root:root 0o400` with `anthropic_key_state: real`; the gateway `.env` is `authorised-other` `gateway-env`; `memory_sweep.namespace_handles` is explained as nsfs and never a FAIL.
    - **D4.1:** every new probe path is `absent`; `anthropic_env_names` and `google_ads_env_names` are empty; `openrouter_env_names` is `["OPENROUTER_API_KEY"]`.
    - **D4.2:** `matches_last_pass: true` (or, for the first review after this change, the operator states the baseline).
    - **D7.1:** the parents are `root root 0o711`; every `vaults`, `reports_rows` and `draft_out_rows` row is `active`, owner 10000, `0o700`; `old_data` is both `absent`; every `audit_logs.rows[*].files` key ends in `0o600` (step logs root, `snapshot.stdout` 10000).
  - Add `## D10 Chat-triggered apps` with the eight items D10.1–D10.8. D10.5's `source` is `manual`; the rest are `box`. Each item gets **claim**, **expected** and **pass rule** lines built from the spec §8.1 table and Task 5's output keys:
    - D10.1: `probe.matches_declared: true`, `rc 0`;
    - D10.2: `probe.matches_expected: true`;
    - D10.3: `User=hermes-app-ads-audit`, `NoNewPrivileges=yes`, an empty `CapabilityBoundingSet`, `PrivateNetwork=yes`, all three units `installed_equal_repo: true`, the groups exactly `hermes-app-ads-audit hermes`, and a `sudo_rules` line saying the user is not allowed;
    - D10.4: `layout_problems: []`, `containers_mounting_app_state: 0`;
    - D10.5: the operator states the OpenRouter key's limit and whether privacy/ZDR is enforced by config or by account (per spec §13);
    - D10.6: an `mcp_block` with exactly the three tools in `include`, `env: {}`; `gateway_mcp_list` recorded as information;
    - D10.7: `journal_counts` includes at least one each of `refused/disabled`, `refused/quota` and `refused/bad_request` from the live checks;
    - D10.8: `out_of_whitelist: 0`, and at least one `run` row with `status ok`.

- [ ] **Step 2: Edit the reviewer packet**
  - `REVIEWER-BRIEF.md`: add one paragraph saying that cid fingerprints are keyed. The two bundles must show the same `cid_key_id`; if they differ, cid comparisons are CANNOT-VERIFY. The bundle carries the last PASS `execstart_sha256` for D4.2.
  - `REPORT-TEMPLATE.md`: add rows D10.1–D10.8 to the results table, in the existing row format.

- [ ] **Step 3: Edit BRING-UP's "A security review" procedure** so step 1 reads:

```markdown
1. Laptop, once: `python3 infra/hermes-agent/bin/review-fp-key.py init` (never overwrite; `show-id` prints its id).
2. Box: `git pull`, then `sudo run-client-audit --probe-env; echo rc=$?` and `sudo run-client-audit --probe-egress; echo rc=$?` (both `rc=0`; the collector re-runs them).
3. Box, ALONE (it prompts for the key on the tty; paste it from `pbcopy < ~/.config/hermes-review/fp.key`):
   `sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --fp-key-tty --last-pass-execstart <review #5 execstart_sha256> > ~/bundle-box.json`
4. Laptop: `bin/collect-review-evidence-laptop.py --customer <dormant pilot id> --package-* ...` (reads the same key file).
```

   Keep the remaining steps (copy, delete from the box, launch a fresh reviewer) unchanged.

- [ ] **Step 4: Run every suite**

Run: `infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/deploy/units.test.py && python3 infra/hermes-agent/bin/security-review-checklist.test.py -v && python3 infra/hermes-agent/bin/check-checklist-version.py --base origin/main && node scripts/run-all-tests.js`
Expected: all pass. The checklist suite confirms that the box items equal `PROBES` (D10.5 is manual and excluded) and that the version rose.

- [ ] **Step 5: Commit, push and open the PR**

```bash
git add infra/hermes-agent/deploy/security-review infra/hermes-agent/deploy/BRING-UP.md
git commit -m "docs(hermes): checklist v1.11 (D10 chat-triggered apps), reviewer packet, keyed review procedure"
git push -u origin HEAD
gh pr create --title "feat(hermes): Option B part 3 — review tooling and checklist v1.11" --body "$(cat <<'EOF'
Implements spec docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md §8 (PR 3 of 3).

- cid fingerprints are HMAC-SHA256 with a laptop-only key (read from the tty on the box); bundles record cid_key_id.
- run-client-audit --probe-env / --probe-egress: sentinel secrets and throwaway dirs; real-Docker CI.
- Collector: D2.1/D4.1/D7.1 follow the new layout; D10.1–D10.8 probes; review-#5 follow-ups (audit-log file modes, nsfs handles, last-PASS execstart).
- CHECKLIST v1.11 with the D10 domain.

After merge: box rollout per BRING-UP parts 1–2, then security review #6.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (done while writing)

- **Spec coverage:**
  - §8 keyed fingerprints → Tasks 1–2;
  - the credential-placement probe → Task 3 and D10.1;
  - the review-#5 follow-ups → Task 6;
  - §8.1: D2.1, D4.1 and D7.1 edits → Tasks 4 and 7; D10.1–D10.4 and D10.6–D10.8 → Task 5; D10.5 → Task 7 (manual); the egress proof → Task 3 and D10.2;
  - §10 PR 3 → Task 7.
- **Review Focus mapping:** 1 → Task 2 (`cid_key_id`); 2 → Task 3 (`test_probe_env_uses_sentinels_and_never_opens_real_secret_files`); 3 → Task 3 (`test_probe_cleans_up_when_docker_fails`); 4 → Task 5 (`test_d10_8_flags_out_of_whitelist_results`); 5 → Task 6 (`test_audit_logs_file_modes_counted_without_names`).
- **Consistent names:** `R.hmac12`, `R.load_fp_key`, `R.key_id`, `Redactor(fp_key=)`, `CE.collect(host, fp_key)`, `RCA.probe_env/probe_egress/PROBE_DIR/DECLARED`, `A.result_in_whitelist`, `A.BROKER_REASONS`, `A.COMMAND_REASONS` and `A.KNOWN_OPS` match their definitions here and in part 2.
