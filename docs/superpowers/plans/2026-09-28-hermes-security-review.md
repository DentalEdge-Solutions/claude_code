# Hermes Security Review and App Packages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tooling that makes "the security review" a real, repeatable gate — a versioned checklist, redacting evidence collectors, a three-part box-state fingerprint — and deliver application code to the box as pinned **app packages**, verified at run time by guard 7.

**Architecture:** Two small stdlib libraries carry the logic: `package_lib.py` (manifest, reproducible tar, installed-file verification) and `review_lib.py` (redaction, credential fingerprints, the fingerprint hash). Thin CLIs sit on top: `build-app-package.py` (laptop), `install-app-package.py` (box), `collect-review-evidence.py` (box) and `collect-review-evidence-laptop.py` (laptop). The registry gains a `package:` block read by `changeset_lib.read_package`; guard 7 in `apply-changeset.py` refuses any mutator whose bytes do not match the pinned manifest. The checklist, the reviewer brief and the report template are Markdown under `deploy/security-review/`, kept in step with the collectors by a sync test.

**Tech Stack:** Python 3 standard library only (no third-party imports anywhere under `infra/hermes-agent/bin/`), `unittest`, POSIX tools on the box (`ss`, `ufw`, `sshd -T`, `systemctl`, `find`, `lsattr`, `journalctl`, `docker`, `git`, `runuser`).

**Spec:** `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`

## Global Constraints

- Stdlib only for every file under `infra/hermes-agent/bin/` — no `yaml`, no third-party packages (the registry is parsed by `changeset_lib`'s own line walker).
- Python syntax must run on **3.9+** (laptop) and 3.12 (box, Ubuntu 24.04): no `match`, no `X | Y` type unions.
- Nothing printed by any tool may contain a credential value, a client slug, or a customer id. Fingerprints use **sha1 of the bare value, first 12 hex** — the `audit-credential-access.py:95` convention (`sha12`).
- Client slugs are replaced with the literal `<client>`; customer ids with `cid:<sha12>`.
- An item that cannot be checked reports `could-not-check`, never a pass or an empty success.
- Every refusal is fail-closed: a missing, malformed or unreadable input refuses; it never defaults.
- Duplicate keys in the registry refuse, at every depth (the `read_block` rule).
- Raw evidence bundles are never committed: `infra/hermes-agent/security-reviews/` is gitignored.
- Tests are `bin/*.test.py`, discovered by `infra/hermes-agent/bin/run-bin-tests.sh`. **Confirm the suite count changed**, not only that it reports OK (baseline before this plan: **31/31**; after Task 10: **38/38**).
- Every negative test is paired with a positive control that proves the check can pass.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage by explicit path only — never `git add -A`, `.`, `.project-brain/` or `evals/` (the tree carries unrelated local changes).

## Review Focus

1. **A credential file with CRLF line endings or quoted values** must fingerprint identically to the LF, unquoted file — otherwise a Windows-edited copy reads as "a different, unaudited credential". Test in Task 6.
2. **`clients.json` missing or malformed** means the collector cannot know which slugs to hide — it must refuse to print the bundle (exit 2), not print unredacted. Test in Task 7.
3. **The gateway container not running** must make the isolation probe `could-not-check`, never "nothing readable". Test in Task 7.
4. **The install target is a symlink** (someone pointed `/opt/projects/claude-google-ads` elsewhere) — install must refuse rather than replace whatever it points at. Test in Task 4.
5. **A tool's own diagnostic output names a client** (e.g. `init-host-layout.py --check` printing `log/<slug>.jsonl`) — the collector must redact text it did not author, not only its own fields. Test in Task 7.

---

## File Structure

| File | Responsibility |
|---|---|
| `infra/hermes-agent/bin/changeset_lib.py` (modify) | `safe_package_path()`, `read_package()` — the registry's `package:` block |
| `infra/hermes-agent/bin/package_lib.py` (create) | manifest build/serialize/hash/validate, reproducible tar, file list from the registry, `verify_installed()` |
| `infra/hermes-agent/bin/package_testutil.py` (create) | test-only helper: pin a fixture workdir, emit a registry `package:` block |
| `infra/hermes-agent/bin/build-app-package.py` (create) | laptop CLI: package a verified commit |
| `infra/hermes-agent/bin/install-app-package.py` (create) | box CLI: verify and atomically install a package |
| `infra/hermes-agent/bin/apply-changeset.py` (modify) | guard 7 pins the mutator's bytes |
| `infra/hermes-agent/bin/review_lib.py` (create) | redaction, credential parsing, credential sets, fingerprint, no-secret safety net |
| `infra/hermes-agent/bin/collect-review-evidence.py` (create) | box collector: probes, bundle, `--fingerprint-only`, `--credentials-only` |
| `infra/hermes-agent/bin/collect-review-evidence-laptop.py` (create) | laptop collector: D3 audit parse, `--access-digest`, D6 package hash |
| `infra/hermes-agent/deploy/security-review/CHECKLIST.md` (create) | the versioned checklist |
| `infra/hermes-agent/deploy/security-review/REVIEWER-BRIEF.md` (create) | instructions for the independent reviewer session |
| `infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md` (create) | the report's shape |
| `infra/hermes-agent/bin/security-review-checklist.test.py` (create) | checklist ↔ collectors sync |
| `.gitignore`, `infra/hermes-agent/deploy/BRING-UP.md`, `infra/hermes-agent/README.md` (modify) | evidence ignore, pre-kill-switch checks, pointers |
| `infra/hermes-agent/registry/projects.yaml`, `bin/registry-invariants.test.py` (modify, Task 11) | the real pin for `claude_google_ads` |

---

### Task 1: The registry `package:` block

**Files:**
- Modify: `infra/hermes-agent/bin/changeset_lib.py` (add after `read_block`, ~line 236)
- Test: `infra/hermes-agent/bin/changeset_lib.test.py` (append a class)

**Interfaces:**
- Produces: `changeset_lib.safe_package_path(p: str) -> bool`; `changeset_lib.read_package(path: str, project: str, require_pin: bool = True) -> dict | None` returning `{"commit": str|None, "sha256": str|None, "include": list[str]}`.

- [ ] **Step 1: Write the failing tests** — append to `changeset_lib.test.py`:

```python
class TestReadPackage(unittest.TestCase):
    PIN = "a" * 40
    SHA = "b" * 64

    def _reg(self, body):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "projects.yaml")
        with open(p, "w") as f:
            f.write("version: 1\n\nprojects:\n  app:\n    workdir: /projects/app\n" + body +
                    "  other:\n    workdir: /projects/other\n")
        return p

    def _pin(self, extra=""):
        return (f"    package:\n      commit: {self.PIN}\n      sha256: {self.SHA}\n"
                "      include:\n        - notes.md\n" + extra)

    def test_parses_commit_sha_and_include(self):
        got = C.read_package(self._reg(self._pin()), "app")
        self.assertEqual(got, {"commit": self.PIN, "sha256": self.SHA, "include": ["notes.md"]})

    def test_absent_block_is_none(self):
        self.assertIsNone(C.read_package(self._reg(""), "app"))

    def test_scope_closes_at_a_sibling_key(self):
        got = C.read_package(self._reg(self._pin("    mutate_execute:\n      runner: /x\n")), "app")
        self.assertEqual(got["include"], ["notes.md"])

    def test_other_projects_block_is_not_read(self):
        self.assertIsNone(C.read_package(self._reg(""), "other"))

    def test_duplicate_block_refuses(self):
        with self.assertRaisesRegex(ValueError, "duplicate 'package' block"):
            C.read_package(self._reg(self._pin() + self._pin()), "app")

    def test_duplicate_key_refuses(self):
        body = f"    package:\n      commit: {self.PIN}\n      commit: {self.PIN}\n      sha256: {self.SHA}\n"
        with self.assertRaisesRegex(ValueError, "duplicate 'commit' key"):
            C.read_package(self._reg(body), "app")

    def test_duplicate_include_refuses(self):
        body = self._pin().replace("        - notes.md\n", "        - notes.md\n        - notes.md\n")
        with self.assertRaisesRegex(ValueError, "duplicate include"):
            C.read_package(self._reg(body), "app")

    def test_unknown_key_refuses(self):
        body = self._pin().replace("      include:", "      extra: 1\n      include:")
        with self.assertRaisesRegex(ValueError, "unknown key 'extra'"):
            C.read_package(self._reg(body), "app")

    def test_bad_pin_refuses_when_required(self):
        body = self._pin().replace(self.SHA, "not-a-sha")
        with self.assertRaisesRegex(ValueError, "sha256"):
            C.read_package(self._reg(body), "app")

    def test_missing_pin_allowed_for_the_builder(self):
        body = "    package:\n      include:\n        - notes.md\n"
        got = C.read_package(self._reg(body), "app", require_pin=False)
        self.assertEqual(got["include"], ["notes.md"])
        with self.assertRaisesRegex(ValueError, "commit"):
            C.read_package(self._reg(body), "app")          # control: required by default

    def test_unsafe_include_paths_refuse(self):
        for bad in ("../x.md", "/etc/passwd", "a//b", "a/./b", "a\\b"):
            body = self._pin().replace("notes.md", bad)
            with self.assertRaisesRegex(ValueError, "unsafe include", msg=bad):
                C.read_package(self._reg(body), "app")

    def test_safe_package_path(self):
        self.assertTrue(C.safe_package_path("code/x.py"))
        for bad in ("", "/x", "../x", "a/../b", "a//b", "./a", "a\\b"):
            self.assertFalse(C.safe_package_path(bad), bad)
```

(If `changeset_lib.test.py` does not already import `tempfile`, add it to its import line.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/hermes-agent/bin && python3 changeset_lib.test.py TestReadPackage -v`
Expected: FAIL — `AttributeError: module 'changeset_lib' has no attribute 'read_package'`

- [ ] **Step 3: Implement** — add to `changeset_lib.py` directly after `read_block`:

```python
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")


def safe_package_path(p):
    """A package-relative path: not absolute, no '..' or '.' segment, no empty segment,
    no backslash. The ONE definition — the registry reader, the builder, the installer
    and guard 7 all use it, so none of them can drift looser than the others."""
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p:
        return False
    return all(seg not in ("", ".", "..") for seg in p.split("/"))


def read_package(path, project, require_pin=True):
    """projects.<project>.package — the pinned app package (spec 2026-09-28 §6.3).

    Returns None when the block is absent: callers decide whether that is a refusal
    (guard 7, the installer) or nothing to pin. require_pin=False exists for ONE caller,
    build-app-package.py, which needs `include` before the hash it will produce exists.

    Duplicate keys refuse at every depth, for read_block's reason: in the file that
    decides which bytes may mutate a live account, a repeated key is a mistake, not an
    intent. An unknown key refuses too — a typo like `sha265:` must not leave the pin
    silently unset.
    """
    got = None
    inside = False
    sub = None
    seen = set()
    seen_inc = set()
    for indent, stripped in _iter_project_lines(path, project):
        if indent == 4 and stripped == "package:":
            if got is not None:
                raise ValueError(f"duplicate 'package' block for project {project!r} — refusing")
            got = {"commit": None, "sha256": None, "include": []}
            inside, sub = True, None
        elif indent <= 4:
            inside, sub = False, None
        elif inside and indent == 6:
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if key in seen:
                raise ValueError(f"duplicate {key!r} key in package for project {project!r} — "
                                 "refusing rather than taking the last value")
            seen.add(key)
            if key == "include":
                if val:
                    raise ValueError(f"package.include for project {project!r} must be a "
                                     "block list ('- path' lines), not an inline value")
                sub = "include"
            elif key in ("commit", "sha256"):
                sub = None
                got[key] = val
            else:
                raise ValueError(f"unknown key {key!r} in package for project {project!r}")
        elif inside and indent == 8 and sub == "include":
            if not stripped.startswith("- "):
                raise ValueError(f"package.include for project {project!r}: expected '- path', "
                                 f"got {stripped!r}")
            item = stripped[2:].strip()
            if not safe_package_path(item):
                raise ValueError(f"unsafe include path {item!r} in package for project {project!r}")
            if item in seen_inc:
                raise ValueError(f"duplicate include {item!r} in package for project {project!r}")
            seen_inc.add(item)
            got["include"].append(item)
        elif inside:
            raise ValueError(f"unexpected line in package for project {project!r}: {stripped!r}")
    if got is None:
        return None
    if require_pin:
        if not _SHA40_RE.fullmatch(got["commit"] or ""):
            raise ValueError(f"package.commit for project {project!r} must be a 40-hex commit")
        if not _SHA64_RE.fullmatch(got["sha256"] or ""):
            raise ValueError(f"package.sha256 for project {project!r} must be 64 hex")
    return got
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/hermes-agent/bin && python3 changeset_lib.test.py -v 2>&1 | tail -3`
Expected: `OK` (the whole file, not only the new class — `read_block` behaviour must be unchanged).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/changeset_lib.py infra/hermes-agent/bin/changeset_lib.test.py
git commit -m "feat(hermes): registry package: block — read_package + safe_package_path (spec 2026-09-28 §6.3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `package_lib` — manifest, reproducible tar, installed-file verification

**Files:**
- Create: `infra/hermes-agent/bin/package_lib.py`
- Create: `infra/hermes-agent/bin/package_testutil.py`
- Test: `infra/hermes-agent/bin/package_lib.test.py`

**Interfaces:**
- Consumes: `C.safe_package_path`, `C.read_package`, `C.read_block` (Task 1 / existing).
- Produces:
  - `MANIFEST_NAME = ".hermes-package.json"`
  - `sha256_bytes(b: bytes) -> str`, `sha256_file(path: str) -> str`
  - `package_file_list(projects_path: str, project: str) -> list[str]`
  - `build_manifest(project: str, source_repo: str, commit: str, files: dict[str, bytes]) -> dict`
  - `manifest_bytes(manifest: dict) -> bytes`, `manifest_hash(manifest: dict) -> str`
  - `load_manifest(raw: bytes) -> dict` (validated)
  - `build_tar(files: dict[str, bytes]) -> bytes`
  - `verify_installed(workdir: str, expected_sha256: str, rel_path: str) -> None` (raises `ValueError`)
  - `package_testutil.FAKE_COMMIT`, `package_testutil.pin_workdir(workdir, project, files) -> str`, `package_testutil.package_block(sha256, commit=FAKE_COMMIT, include=()) -> str`

- [ ] **Step 1: Write the failing tests** — `package_lib.test.py`:

```python
#!/usr/bin/env python3
import io, json, os, sys, tarfile, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package_lib as PK
import package_testutil as T

REG = """version: 1

projects:
  app:
    workdir: /projects/app
    read_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - reader_one
        - reader_two
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - mutator
      caps:
        actions_per_changeset: 1
    package:
      include:
        - notes.md
"""

FILES = {"code/mutator.py": b"print('m')\n", "code/reader_one.py": b"r1\n",
         "code/reader_two.py": b"r2\n", "notes.md": b"# notes\n"}


class TestFileList(unittest.TestCase):
    def test_derived_from_both_allow_lists_plus_include(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "projects.yaml")
        with open(p, "w") as f:
            f.write(REG)
        self.assertEqual(PK.package_file_list(p, "app"), sorted(FILES))

    def test_nothing_declared_refuses(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "projects.yaml")
        with open(p, "w") as f:
            f.write("version: 1\n\nprojects:\n  app:\n    workdir: /x\n")
        with self.assertRaisesRegex(ValueError, "nothing to package"):
            PK.package_file_list(p, "app")


class TestManifest(unittest.TestCase):
    def test_hash_is_stable_and_order_independent(self):
        a = PK.build_manifest("app", "repo", "c" * 40, FILES)
        b = PK.build_manifest("app", "repo", "c" * 40, dict(reversed(list(FILES.items()))))
        self.assertEqual(PK.manifest_hash(a), PK.manifest_hash(b))

    def test_one_byte_changes_the_hash(self):
        a = PK.build_manifest("app", "repo", "c" * 40, FILES)
        changed = dict(FILES); changed["notes.md"] = b"# notes!\n"
        self.assertNotEqual(PK.manifest_hash(a), PK.manifest_hash(PK.build_manifest("app", "repo", "c" * 40, changed)))

    def test_load_round_trips(self):
        m = PK.build_manifest("app", "repo", "c" * 40, FILES)
        self.assertEqual(PK.load_manifest(PK.manifest_bytes(m)), m)

    def test_load_refuses_bad_shapes(self):
        m = PK.build_manifest("app", "repo", "c" * 40, FILES)
        for mutate in (lambda x: x.pop("files"),
                       lambda x: x["files"][0].update(path="../evil"),
                       lambda x: x["files"][0].update(sha256="zz"),
                       lambda x: x["files"].append(dict(x["files"][0])),
                       lambda x: x.update(commit="short")):
            bad = json.loads(json.dumps(m)); mutate(bad)
            with self.assertRaises(ValueError):
                PK.load_manifest(PK.manifest_bytes(bad))


class TestTar(unittest.TestCase):
    def test_reproducible(self):
        self.assertEqual(PK.build_tar(FILES), PK.build_tar(dict(reversed(list(FILES.items())))))

    def test_members_are_plain_files_with_fixed_metadata(self):
        with tarfile.open(fileobj=io.BytesIO(PK.build_tar(FILES))) as tar:
            members = tar.getmembers()
        self.assertEqual([m.name for m in members], sorted(FILES))
        for m in members:
            self.assertTrue(m.isreg())
            self.assertEqual((m.mtime, m.uid, m.gid, m.mode), (0, 0, 0, 0o444))


class TestVerifyInstalled(unittest.TestCase):
    def setUp(self):
        self.wd = tempfile.mkdtemp()
        self.sha = T.pin_workdir(self.wd, "app", FILES)

    def test_untouched_file_passes(self):
        PK.verify_installed(self.wd, self.sha, "code/mutator.py")        # control: no raise

    def test_edited_file_refused(self):
        with open(os.path.join(self.wd, "code/mutator.py"), "ab") as f:
            f.write(b"# tampered\n")
        with self.assertRaisesRegex(ValueError, "does not match the installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/mutator.py")

    def test_missing_manifest_refused(self):
        os.remove(os.path.join(self.wd, PK.MANIFEST_NAME))
        with self.assertRaisesRegex(ValueError, "no installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/mutator.py")

    def test_manifest_not_matching_pin_refused(self):
        with self.assertRaisesRegex(ValueError, "does not match the registry pin"):
            PK.verify_installed(self.wd, "0" * 64, "code/mutator.py")

    def test_file_not_in_manifest_refused(self):
        with self.assertRaisesRegex(ValueError, "not in the installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/other.py")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 package_lib.test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'package_lib'`

- [ ] **Step 3: Implement `package_lib.py`**

```python
#!/usr/bin/env python3
"""App packages (spec 2026-09-28 §6).

An app package is the registry-allow-listed code of one project at one verified commit,
plus a manifest. The PACKAGE HASH is the sha256 of the manifest's canonical bytes, and it
is what the registry pins (`package.sha256`). Four consumers share this module so none
can drift: build-app-package.py (laptop), install-app-package.py (box), guard 7 in
apply-changeset.py, and the security-review collector.

Stdlib only.
"""
import hashlib, io, json, os, re, tarfile

import changeset_lib as C

MANIFEST_NAME = ".hermes-package.json"
SCHEMA = 1
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_KEYS = {"schema", "project", "source_repo", "commit", "files"}
_FILE_KEYS = {"path", "sha256", "size"}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def package_file_list(projects_path, project):
    """`<script_dir>/<name>.py` for every name on BOTH allow-lists, plus package.include.

    Derived from the registry, never chosen by hand: what may run is exactly what ships.
    """
    paths = set()
    for block in ("read_execute", "mutate_execute"):
        got = C.read_block(projects_path, project, block)
        if not got["allow"]:
            continue
        sd = got.get("script_dir")
        if not C.safe_package_path(sd or ""):
            raise ValueError(f"{block}.script_dir for project {project!r} is missing or unsafe: {sd!r}")
        for name in got["allow"]:
            if os.path.basename(name) != name or not C.safe_package_path(name):
                raise ValueError(f"allow-list name {name!r} in {block} is not a bare basename")
            paths.add(f"{sd}/{name}.py")
    pin = C.read_package(projects_path, project, require_pin=False)
    for inc in (pin or {}).get("include", []):
        paths.add(inc)
    if not paths:
        raise ValueError(f"project {project!r} declares nothing to package")
    return sorted(paths)


def build_manifest(project, source_repo, commit, files):
    return {"schema": SCHEMA, "project": project, "source_repo": source_repo, "commit": commit,
            "files": [{"path": p, "sha256": sha256_bytes(files[p]), "size": len(files[p])}
                      for p in sorted(files)]}


def manifest_bytes(manifest):
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def manifest_hash(manifest):
    return sha256_bytes(manifest_bytes(manifest))


def load_manifest(raw):
    """Parse and validate. Every malformed shape is a ValueError — never a partial read."""
    try:
        m = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"package manifest is not valid JSON: {e}")
    if not isinstance(m, dict) or set(m) != _MANIFEST_KEYS:
        raise ValueError("package manifest has the wrong keys")
    if m["schema"] != SCHEMA or not _HEX40.fullmatch(str(m["commit"])):
        raise ValueError("package manifest has an unknown schema or a malformed commit")
    if not isinstance(m["files"], list) or not m["files"]:
        raise ValueError("package manifest lists no files")
    seen = set()
    for e in m["files"]:
        if not isinstance(e, dict) or set(e) != _FILE_KEYS:
            raise ValueError("package manifest file entry has the wrong keys")
        if not C.safe_package_path(e["path"]) or e["path"] == MANIFEST_NAME:
            raise ValueError(f"package manifest names an unsafe path: {e['path']!r}")
        if not _HEX64.fullmatch(str(e["sha256"])) or not isinstance(e["size"], int):
            raise ValueError(f"package manifest entry for {e['path']!r} is malformed")
        if e["path"] in seen:
            raise ValueError(f"package manifest lists {e['path']!r} twice")
        seen.add(e["path"])
    return m


def build_tar(files):
    """Uncompressed ustar with fixed metadata — gzip would embed a timestamp. Same input,
    same bytes. Files only: parents are implied."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for p in sorted(files):
            data = files[p]
            ti = tarfile.TarInfo(p)
            ti.size, ti.mtime, ti.mode = len(data), 0, 0o444
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.type = tarfile.REGTYPE
            tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def verify_installed(workdir, expected_sha256, rel_path):
    """Refuse unless workdir's installed manifest IS the pinned one and rel_path's bytes
    are the ones it lists. Guard 7's check (spec §6.5); raises ValueError."""
    mpath = os.path.join(workdir, MANIFEST_NAME)
    try:
        with open(mpath, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise ValueError(f"no installed package manifest at {mpath} — refusing (spec 2026-09-28 §6.5)")
    got = sha256_bytes(raw)
    if got != expected_sha256:
        raise ValueError(f"installed package manifest {got[:12]} does not match the registry pin "
                         f"{expected_sha256[:12]} — refusing")
    m = load_manifest(raw)
    entry = next((e for e in m["files"] if e["path"] == rel_path), None)
    if entry is None:
        raise ValueError(f"{rel_path} is not in the installed package manifest — refusing")
    actual = sha256_file(os.path.join(workdir, rel_path))
    if actual != entry["sha256"]:
        raise ValueError(f"{rel_path} does not match the installed package manifest "
                         f"(sha256 {actual[:12]} != {entry['sha256'][:12]}) — refusing")
```

- [ ] **Step 4: Implement `package_testutil.py`**

```python
"""Test-only helpers: give a fixture workdir an installed, pinned package.

Not imported by any production file. Lives in bin/ beside the suites that use it, like
persist_run_record_shim.py.
"""
import os
import package_lib as PK

FAKE_COMMIT = "0" * 40


def pin_workdir(workdir, project, files):
    """Write each {rel_path: bytes} into workdir plus the manifest; return the pin."""
    for rel, data in files.items():
        dest = os.path.join(workdir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
    m = PK.build_manifest(project, "fixture", FAKE_COMMIT, files)
    with open(os.path.join(workdir, PK.MANIFEST_NAME), "wb") as f:
        f.write(PK.manifest_bytes(m))
    return PK.manifest_hash(m)


def package_block(sha256, commit=FAKE_COMMIT, include=()):
    """A registry `package:` block at a project's indent (4)."""
    lines = ["    package:", f"      commit: {commit}", f"      sha256: {sha256}"]
    if include:
        lines.append("      include:")
        lines += [f"        - {i}" for i in include]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 package_lib.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/package_lib.py infra/hermes-agent/bin/package_testutil.py infra/hermes-agent/bin/package_lib.test.py
git commit -m "feat(hermes): package_lib — manifest, reproducible tar, installed-file verification (spec §6)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `build-app-package.py` (laptop)

**Files:**
- Create: `infra/hermes-agent/bin/build-app-package.py`
- Test: `infra/hermes-agent/bin/build-app-package.test.py`

**Interfaces:**
- Consumes: `PK.package_file_list`, `PK.build_manifest`, `PK.manifest_bytes`, `PK.manifest_hash`, `PK.build_tar`.
- Produces: `build(project, repo, commit, projects, out_dir) -> dict` with keys `package`, `manifest`, `sha256`, `files`; CLI prints `package <path>`, `manifest <path>`, `sha256 <hex>`, `files <n>`; exit 1 on refusal.

- [ ] **Step 1: Write the failing tests** — `build-app-package.test.py`:

```python
#!/usr/bin/env python3
import importlib.util, os, subprocess, sys, tarfile, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("build_app_package", os.path.join(HERE, "build-app-package.py"))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)

REG = """version: 1

projects:
  app:
    workdir: /projects/app
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - mutator
    package:
      include:
        - notes.md
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True).stdout.decode().strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q")
        os.makedirs(os.path.join(self.repo, "code"))
        for rel, body in (("code/mutator.py", "m\n"), ("notes.md", "n\n"),
                          ("code/not_listed.py", "x\n"), ("report.md", "client data\n")):
            with open(os.path.join(self.repo, rel), "w") as f:
                f.write(body)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "c1")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        d = tempfile.mkdtemp(); self.projects = os.path.join(d, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)


class TestBuild(Base):
    def test_contains_exactly_the_registry_list(self):
        out = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        with tarfile.open(out["package"]) as tar:
            self.assertEqual(sorted(m.name for m in tar.getmembers()), ["code/mutator.py", "notes.md"])

    def test_reproducible(self):
        a = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        b = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        self.assertEqual(a["sha256"], b["sha256"])
        with open(a["package"], "rb") as fa, open(b["package"], "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_refuses_a_commit_that_is_not_head(self):
        with open(os.path.join(self.repo, "notes.md"), "a") as f:
            f.write("more\n")
        git(self.repo, "commit", "-qam", "c2")
        with self.assertRaisesRegex(ValueError, "HEAD is"):
            B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())

    def test_refuses_modified_tracked_files(self):
        with open(os.path.join(self.repo, "code/mutator.py"), "a") as f:
            f.write("dirty\n")
        with self.assertRaisesRegex(ValueError, "modified"):
            B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())

    def test_untracked_files_do_not_block(self):
        with open(os.path.join(self.repo, "audit_data.json"), "w") as f:
            f.write("{}")
        B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())   # no raise

    def test_refuses_a_short_commit(self):
        with self.assertRaisesRegex(ValueError, "40-hex"):
            B.build("app", self.repo, self.commit[:12], self.projects, tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 build-app-package.test.py -v`
Expected: FAIL — `FileNotFoundError` for `build-app-package.py`

- [ ] **Step 3: Implement `build-app-package.py`**

```python
#!/usr/bin/env python3
"""Build an app package on the LAPTOP (spec 2026-09-28 §6.2).

  python3 bin/build-app-package.py --project claude_google_ads \\
      --repo ~/Projects/claude-google-ads --commit <40-hex> --out-dir /tmp/pkg

Contents come from the registry (both allow-lists + package.include) and are read from
the COMMIT's git objects, never the working tree. Refuses unless --commit is the checked-
out HEAD and no tracked file is modified, so "what was verified" and "what ships" cannot
differ. Untracked files (audit_data/ and the like) are irrelevant and ignored.
"""
import argparse, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package_lib as PK

DEFAULT_PROJECTS = os.path.join(os.path.dirname(HERE), "registry", "projects.yaml")


def _git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if p.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def build(project, repo, commit, projects, out_dir):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--commit must be a full 40-hex commit sha")
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    if head != commit:
        raise ValueError(f"{repo} HEAD is {head[:12]}, not {commit[:12]} — check out the verified commit first")
    if _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("tracked files are modified — refusing; the package must equal the commit")
    paths = PK.package_file_list(projects, project)
    files = {p: _git(repo, "show", f"{commit}:{p}") for p in paths}
    m = PK.build_manifest(project, os.path.basename(os.path.abspath(repo)), commit, files)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"{project}-{commit[:12]}")
    with open(stem + ".tar", "wb") as f:
        f.write(PK.build_tar(files))
    with open(stem + ".manifest.json", "wb") as f:
        f.write(PK.manifest_bytes(m))
    return {"package": stem + ".tar", "manifest": stem + ".manifest.json",
            "sha256": PK.manifest_hash(m), "files": len(files)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--projects", default=DEFAULT_PROJECTS)
    a = ap.parse_args(argv)
    try:
        out = build(a.project, a.repo, a.commit, a.projects, a.out_dir)
    except (ValueError, OSError) as e:
        print(f"build-app-package: {e}", file=sys.stderr)
        return 1
    for k in ("package", "manifest", "sha256", "files"):
        print(k, out[k])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 build-app-package.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/build-app-package.py infra/hermes-agent/bin/build-app-package.test.py
git commit -m "feat(hermes): build-app-package.py — package a verified commit from the registry list (spec §6.2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `install-app-package.py` (box)

**Files:**
- Create: `infra/hermes-agent/bin/install-app-package.py`
- Test: `infra/hermes-agent/bin/install-app-package.test.py`

**Interfaces:**
- Consumes: `C.read_package`, `C.safe_package_path`, `PK.sha256_bytes`, `PK.load_manifest`, `PK.MANIFEST_NAME`.
- Produces: `verify(project, package_path, manifest_path, projects) -> (raw_manifest: bytes, files: dict[str, bytes])`; `install(target, raw_manifest, files, chown=True) -> None`; CLI `--project --package --manifest --target [--projects] [--no-chown]`.

- [ ] **Step 1: Write the failing tests** — `install-app-package.test.py`:

```python
#!/usr/bin/env python3
import importlib.util, io, os, stat, sys, tarfile, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package_lib as PK
import package_testutil as T
spec = importlib.util.spec_from_file_location("install_app_package", os.path.join(HERE, "install-app-package.py"))
I = importlib.util.module_from_spec(spec); spec.loader.exec_module(I)

FILES = {"code/mutator.py": b"m\n", "notes.md": b"n\n"}


def tar_of(members):
    """members: list of (TarInfo-kwargs dict, bytes|None)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for kw, data in members:
            ti = tarfile.TarInfo(kw.pop("name"))
            for k, v in kw.items():
                setattr(ti, k, v)
            if data is not None:
                ti.size = len(data)
            t.addfile(ti, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.m = PK.build_manifest("app", "repo", T.FAKE_COMMIT, FILES)
        self.sha = PK.manifest_hash(self.m)
        self.projects = self._reg(self.sha)
        self.manifest = self._write("m.json", PK.manifest_bytes(self.m))
        self.package = self._write("p.tar", PK.build_tar(FILES))
        self.target = os.path.join(self.d, "claude-google-ads")
        os.makedirs(self.target)
        self._write("claude-google-ads/PLACEHOLDER", b"placeholder\n")

    def _write(self, rel, data):
        p = os.path.join(self.d, rel)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def _reg(self, sha):
        return self._write("projects.yaml", ("version: 1\n\nprojects:\n  app:\n    workdir: /projects/app\n"
                                             + T.package_block(sha)).encode())

    def _install(self, package=None, manifest=None):
        raw, files = I.verify("app", package or self.package, manifest or self.manifest, self.projects)
        I.install(self.target, raw, files, chown=False)


class TestInstall(Base):
    def test_valid_package_installs_with_the_stated_modes(self):
        self._install()
        self.assertFalse(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))
        with open(os.path.join(self.target, "code/mutator.py"), "rb") as f:
            self.assertEqual(f.read(), b"m\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.target, "code/mutator.py")).st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.target, "code")).st_mode), 0o555)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o555)
        env = os.path.join(self.target, ".env")
        self.assertEqual((os.path.getsize(env), stat.S_IMODE(os.stat(env).st_mode)), (0, 0o600))
        PK.verify_installed(self.target, self.sha, "code/mutator.py")      # guard 7 would pass

    def test_reinstall_over_an_installed_package(self):
        self._install(); self._install()                                     # read-only tree replaced

    def test_manifest_not_matching_the_pin_refused(self):
        self.projects = self._reg("f" * 64)
        with self.assertRaisesRegex(ValueError, "does not match the registry pin"):
            self._install()

    def test_member_bytes_not_matching_the_manifest_refused(self):
        bad = self._write("bad.tar", PK.build_tar({"code/mutator.py": b"evil\n", "notes.md": b"n\n"}))
        with self.assertRaisesRegex(ValueError, "does not match the manifest"):
            self._install(package=bad)

    def test_unsafe_members_refused(self):
        cases = {
            "symlink": [({"name": "code/mutator.py", "type": tarfile.SYMTYPE, "linkname": "/etc/passwd"}, None)],
            "hardlink": [({"name": "code/mutator.py", "type": tarfile.LNKTYPE, "linkname": "notes.md"}, None)],
            "dotdot": [({"name": "../evil.py"}, b"x")],
            "absolute": [({"name": "/tmp/evil.py"}, b"x")],
            "extra": [({"name": "code/mutator.py"}, b"m\n"), ({"name": "notes.md"}, b"n\n"), ({"name": "extra.py"}, b"x")],
            "missing": [({"name": "code/mutator.py"}, b"m\n")],
        }
        for label, members in cases.items():
            p = self._write(f"{label}.tar", tar_of(members))
            with self.assertRaises(ValueError, msg=label):
                self._install(package=p)
        self.assertTrue(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))   # untouched

    def test_symlinked_target_refused(self):
        real = os.path.join(self.d, "elsewhere"); os.makedirs(real)
        link = os.path.join(self.d, "linked-target"); os.symlink(real, link)
        raw, files = I.verify("app", self.package, self.manifest, self.projects)
        with self.assertRaisesRegex(ValueError, "symlink"):
            I.install(link, raw, files, chown=False)

    def test_failed_swap_leaves_the_previous_tree(self):
        real_rename = os.rename
        calls = []

        def flaky(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("simulated failure between the two renames")
            return real_rename(src, dst)

        raw, files = I.verify("app", self.package, self.manifest, self.projects)
        with mock.patch.object(I.os, "rename", side_effect=flaky):
            with self.assertRaises(OSError):
                I.install(self.target, raw, files, chown=False)
        self.assertTrue(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))
        self.assertEqual([n for n in os.listdir(self.d) if ".new-" in n or ".old-" in n], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 install-app-package.test.py -v`
Expected: FAIL — `FileNotFoundError` for `install-app-package.py`

- [ ] **Step 3: Implement `install-app-package.py`**

```python
#!/usr/bin/env python3
"""Install an app package on the BOX (spec 2026-09-28 §6.4).

  sudo python3 bin/install-app-package.py --project claude_google_ads \\
      --package ~/claude_google_ads-<commit12>.tar --manifest ~/claude_google_ads-<commit12>.manifest.json \\
      --target /opt/projects/claude-google-ads

Refuses unless the manifest's sha256 equals the registry pin and every member equals its
manifest entry. Only regular files with safe relative paths are accepted, and the member
set must equal the manifest's exactly. The new tree is built beside the target and swapped
in by rename; a failed swap restores the previous tree. Files root:root 0444, directories
0555, an empty 0600 `.env` (docker-compose.yml binds its mask onto it), and the manifest
as `.hermes-package.json`.
"""
import argparse, os, shutil, stat, sys, tarfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import package_lib as PK

DEFAULT_PROJECTS = os.path.join(os.path.dirname(HERE), "registry", "projects.yaml")


def verify(project, package_path, manifest_path, projects):
    pin = C.read_package(projects, project)
    if pin is None:
        raise ValueError(f"project {project!r} has no package pin in {projects} — refusing")
    with open(manifest_path, "rb") as f:
        raw = f.read()
    if PK.sha256_bytes(raw) != pin["sha256"]:
        raise ValueError("manifest does not match the registry pin — refusing")
    m = PK.load_manifest(raw)
    if m["project"] != project or m["commit"] != pin["commit"]:
        raise ValueError("manifest project/commit does not match the registry pin — refusing")
    want = {e["path"]: e["sha256"] for e in m["files"]}
    files = {}
    with tarfile.open(package_path, mode="r:") as tar:
        for ti in tar.getmembers():
            if not ti.isreg():
                raise ValueError(f"package member {ti.name!r} is not a regular file — refusing")
            if not C.safe_package_path(ti.name):
                raise ValueError(f"package member {ti.name!r} has an unsafe path — refusing")
            if ti.name not in want:
                raise ValueError(f"package member {ti.name!r} is not in the manifest — refusing")
            if ti.name in files:
                raise ValueError(f"package member {ti.name!r} appears twice — refusing")
            data = tar.extractfile(ti).read()
            if PK.sha256_bytes(data) != want[ti.name]:
                raise ValueError(f"package member {ti.name!r} does not match the manifest — refusing")
            files[ti.name] = data
    missing = sorted(set(want) - set(files))
    if missing:
        raise ValueError(f"package is missing manifest files {missing} — refusing")
    return raw, files


def _rmtree(path):
    for root, dirs, _ in os.walk(path):
        os.chmod(root, 0o700)
        for d in dirs:
            p = os.path.join(root, d)
            if not os.path.islink(p):
                os.chmod(p, 0o700)
    shutil.rmtree(path)


def _write_new(path, data, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def install(target, raw_manifest, files, chown=True):
    target = os.path.abspath(target)
    if os.path.islink(target):
        raise ValueError(f"{target} is a symlink — refusing to replace what it points at")
    new, old = f"{target}.new-{os.getpid()}", f"{target}.old-{os.getpid()}"
    for p in (new, old):
        if os.path.lexists(p):
            raise ValueError(f"{p} already exists — a previous install was interrupted; inspect it first")
    os.mkdir(new, 0o755)
    try:
        for rel in sorted(files):
            dest = os.path.join(new, rel)
            os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)
            _write_new(dest, files[rel], 0o444)
        _write_new(os.path.join(new, PK.MANIFEST_NAME), raw_manifest, 0o444)
        _write_new(os.path.join(new, ".env"), b"", 0o600)
        for root, dirs, names in os.walk(new, topdown=False):
            for n in names:
                if chown:
                    os.chown(os.path.join(root, n), 0, 0)
            if chown:
                os.chown(root, 0, 0)
            os.chmod(root, 0o555)
    except BaseException:
        _rmtree(new)
        raise
    had_old = os.path.lexists(target)
    if had_old:
        os.rename(target, old)
    try:
        os.rename(new, target)
    except BaseException:
        if had_old:
            os.rename(old, target)
        _rmtree(new)
        raise
    if had_old:
        _rmtree(old)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--projects", default=DEFAULT_PROJECTS)
    ap.add_argument("--no-chown", action="store_true", help="tests and non-Linux dry runs only")
    a = ap.parse_args(argv)
    if sys.platform.startswith("linux") and os.geteuid() != 0 and not a.no_chown:
        print("install-app-package: must run as root on Linux (files are root-owned)", file=sys.stderr)
        return 1
    try:
        raw, files = verify(a.project, a.package, a.manifest, a.projects)
        install(a.target, raw, files, chown=not a.no_chown)
    except (ValueError, OSError, tarfile.TarError) as e:
        print(f"install-app-package: {e}", file=sys.stderr)
        return 1
    print(f"installed {a.project} package {PK.sha256_bytes(raw)[:12]} ({len(files)} files) at {a.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 install-app-package.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/install-app-package.py infra/hermes-agent/bin/install-app-package.test.py
git commit -m "feat(hermes): install-app-package.py — verify against the pin, atomic swap, read-only tree (spec §6.4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Guard 7 pins the mutator's bytes

**Files:**
- Modify: `infra/hermes-agent/bin/apply-changeset.py` (imports ~line 21; guard 7 ~lines 177-193)
- Modify: `infra/hermes-agent/bin/apply-changeset.test.py` (`_reg_text` ~line 83, `Base.setUp` ~line 108, new class)
- Modify: `infra/hermes-agent/bin/syscall-e2e.test.py` (its `setUp` registry write, ~lines 128-145)

**Interfaces:**
- Consumes: `C.read_package` (Task 1), `PK.verify_installed` (Task 2), `package_testutil.pin_workdir` / `package_block` (Task 2).
- Produces: guard 7 refusal texts — `no package pin`, `no installed package manifest`, `does not match the registry pin`, `does not match the installed package manifest`.

- [ ] **Step 1: Write the failing tests** — in `apply-changeset.test.py`:

1. Add `import package_testutil as PT` beside `import changeset_lib as C`.
2. Give `_reg_text` a `package=None` parameter and append the block when set:

```python
def _reg_text(tmp, allow="mutate_campaign_negative", caps=None, package=None):
    caps = caps or {"actions_per_changeset": 25, "actions_per_client_day": 100,
                    "applies_per_client_day": 5, "approval_ttl_hours": 24}
    text = f"""version: 1

projects:
  claude_google_ads:
    workdir: {tmp}
    read_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - account_overview
    mutate_execute:
      runner: {sys.executable}
      script_dir: code
      allow:
        - {allow}
      caps:
        actions_per_changeset: {caps['actions_per_changeset']}
        actions_per_client_day: {caps['actions_per_client_day']}
        applies_per_client_day: {caps['applies_per_client_day']}
        approval_ttl_hours: {caps['approval_ttl_hours']}
"""
    return text + (PT.package_block(package) if package else "")
```

3. In `Base.setUp`, replace the registry write (`self.projects = ...; f.write(_reg_text(self.tmp))`) with:

```python
        self.pin = PT.pin_workdir(self.tmp, "claude_google_ads",
                                  {"code/mutate_campaign_negative.py": STUB.encode()})
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, package=self.pin))
```

4. **Keep the pin in the tests that rewrite the registry.** Four existing tests replace `projects.yaml` with different caps (currently lines ~452, ~465, ~648, ~823: `f.write(_reg_text(self.tmp, caps={...}))`). Without the pin they would now refuse at guard 7 instead of exercising the cap they test. Add `package=self.pin` to each of those four calls. Leave the allow-list-overlap test (`_reg_text(self.tmp, allow="account_overview")`, ~line 489) alone: it refuses earlier in guard 7, before the pin is read. Find them with `grep -n '_reg_text(self.tmp' apply-changeset.test.py`.

5. Append the new class:

```python
class TestPackagePin(Base):
    """Guard 7 (spec 2026-09-28 §6.5): the mutator's bytes must be the pinned package's."""

    def _tamper(self):
        with open(self.stub, "a") as f:
            f.write("# edited on the box\n")

    def test_untouched_mutator_proceeds(self):                     # control
        cs = self._approved()
        self.assertEqual(self._run(cs["changeset_id"])[0], 0)
        self.assertTrue(self._calls())

    def test_edited_mutator_refused(self):
        cs = self._approved(); self._tamper()
        self._assert_refused(cs["changeset_id"], because="does not match the installed package manifest")

    def test_missing_manifest_refused(self):
        cs = self._approved()
        os.remove(os.path.join(self.tmp, ".hermes-package.json"))
        self._assert_refused(cs["changeset_id"], because="no installed package manifest")

    def test_manifest_not_matching_the_registry_pin_refused(self):
        cs = self._approved()
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp, package="f" * 64))
        self._assert_refused(cs["changeset_id"], because="does not match the registry pin")

    def test_no_package_pin_refused(self):
        cs = self._approved()
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp))
        self._assert_refused(cs["changeset_id"], because="no package pin")

    def test_undo_path_checks_the_pin_too(self):
        cs = self._approved()
        self.assertEqual(self._run(cs["changeset_id"])[0], 0)
        os.remove(self.calls); self._tamper()
        err = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(err):
            self._run(cs["changeset_id"], undo=cs["changeset_id"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self._calls(), [])
        self.assertIn("does not match the installed package manifest", err.getvalue())
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd infra/hermes-agent/bin && python3 apply-changeset.test.py TestPackagePin -v`
Expected: `test_untouched_mutator_proceeds` PASSES (the pin is written but unchecked); the other five FAIL — nothing refuses yet.

- [ ] **Step 3: Implement** — in `apply-changeset.py`, add `import package_lib as PK` after `import changeset_lib as C`, then replace the end of guard 7:

```python
    if not os.path.isfile(script):
        _refuse(f"mutator not found: {script}")
    # 7b. The mutator's BYTES must be the pinned package's (spec 2026-09-28 §6.5, F23's
    #     second gap). Existence is not identity: a file edited or swapped on the box would
    #     otherwise run with the full write credential. Both paths — undo runs the same
    #     mutator. A project with no pin refuses: there is no unpinned mutation.
    try:
        pin = C.read_package(projects_path, rec["project"])
        if pin is None:
            raise ValueError(f"no package pin for project {rec['project']!r} in the registry — "
                             "refusing (spec 2026-09-28 §6.5)")
        PK.verify_installed(workdir, pin["sha256"], os.path.join(cfg["script_dir"], name + ".py"))
    except (ValueError, OSError) as e:
        _refuse(str(e))
```

- [ ] **Step 4: Update `syscall-e2e.test.py`** — add `import package_testutil as PT` beside `import changeset_lib as C`, and change its registry write in `setUp` to pin the stub it already writes, exactly as in Step 1.3:

```python
        self.pin = PT.pin_workdir(self.tmp, "claude_google_ads",
                                  {"code/mutate_campaign_negative.py": STUB.encode()})
        self.projects = os.path.join(self.tmp, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(_reg_text(self.tmp) + PT.package_block(self.pin))
```

(`syscall-e2e.test.py` calls its own `_reg_text` without a `package` parameter; appending the block keeps that function untouched.)

- [ ] **Step 5: Run the affected suites and the whole runner**

Run: `cd infra/hermes-agent/bin && python3 apply-changeset.test.py -v 2>&1 | tail -3 && python3 syscall-e2e.test.py 2>&1 | tail -3 && ./run-bin-tests.sh 2>&1 | tail -1`
Expected: `OK`, `OK`, and `hermes bin: 34/34 suites passed` (31 + Tasks 2-4).

If `hermes-broker.test.py`, `propose-changeset.test.py` or `approve-changeset.test.py` fail with a guard 7 message, they reach the executor through a registry without a pin: pin their fixture the same way (Step 1.3's three lines). `grep -n "_reg_text\|projects.yaml" <file>` finds the spot.

- [ ] **Step 6: Commit**

```bash
git add infra/hermes-agent/bin/apply-changeset.py infra/hermes-agent/bin/apply-changeset.test.py infra/hermes-agent/bin/syscall-e2e.test.py
git commit -m "feat(hermes): guard 7 pins the mutator's bytes to the registry's package (spec §6.5; F23 second gap)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `review_lib` — redaction, credentials, fingerprint

**Files:**
- Create: `infra/hermes-agent/bin/review_lib.py`
- Test: `infra/hermes-agent/bin/review_lib.test.py`

**Interfaces:**
- Produces:
  - `CLIENT = "<client>"`, `OBSERVED = "observed"`, `COULD_NOT_CHECK = "could-not-check"`
  - `sha12(value) -> str`, `canon(value) -> bytes`
  - `class Redactor(slugs, customer_ids)`; `Redactor.from_clients_json(path) -> Redactor` (raises `ValueError` when unreadable/malformed); `.text(s) -> str`; `.obj(o) -> same shape`
  - `parse_credential_file(path) -> (info: dict, secrets: list[str])`; `info` keys `path`, `role`, `refresh_token_sha12`, `client_id_sha12`
  - `credential_set(infos) -> list[dict]` (sorted; keys `role`, `refresh_token_sha12`, `client_id_sha12`)
  - `fingerprint(components: dict) -> {"fingerprint": str, "components": {name: sha256}, "complete": bool}`
  - `assert_no_secret(text, secrets) -> None` (raises `RuntimeError`)

- [ ] **Step 1: Write the failing tests** — `review_lib.test.py`:

```python
#!/usr/bin/env python3
import hashlib, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"
CLIENT_ID = "123-fake.apps.googleusercontent.com"


def cred(d, name, body):
    p = os.path.join(d, name)
    with open(p, "w", newline="") as f:
        f.write(body)
    return p


class TestSha12(unittest.TestCase):
    def test_matches_audit_credential_access_convention(self):
        self.assertEqual(R.sha12("abc"), hashlib.sha1(b"abc").hexdigest()[:12])


class TestRedactor(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(); self.clients = os.path.join(d, "clients.json")
        with open(self.clients, "w") as f:
            json.dump({"clients": {"acme-dental": {"customer_id": "1234567890"},
                                   "acme": {"customer_id": "5555555555"}}}, f)
        self.r = R.Redactor.from_clients_json(self.clients)

    def test_slug_replaced_on_word_boundaries_only(self):
        self.assertEqual(self.r.text("log/acme-dental.jsonl and acme and acmex"),
                         "log/<client>.jsonl and <client> and acmex")

    def test_customer_ids_plain_and_dashed(self):
        out = self.r.text("id 1234567890 or 123-456-7890")
        self.assertNotIn("1234567890", out); self.assertNotIn("123-456-7890", out)
        self.assertEqual(out.count("cid:" + R.sha12("1234567890")), 2)

    def test_obj_redacts_keys_and_nested_values(self):
        out = self.r.obj({"acme-dental": ["x acme-dental", {"k": "1234567890"}], "n": 3})
        self.assertEqual(out, {"<client>": ["x <client>", {"k": "cid:" + R.sha12("1234567890")}], "n": 3})

    def test_firing_control_an_empty_redactor_redacts_nothing(self):
        self.assertIn("acme-dental", R.Redactor([], []).text("acme-dental"))

    def test_missing_or_malformed_clients_json_raises(self):
        with self.assertRaises(ValueError):
            R.Redactor.from_clients_json(self.clients + ".missing")
        with open(self.clients, "w") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            R.Redactor.from_clients_json(self.clients)


class TestCredentials(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_parse_returns_fingerprints_and_role(self):
        p = cred(self.d, ".env.gaw", f"GOOGLE_ADS_CREDENTIAL_ROLE=write\nGOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"
                                     f"GOOGLE_ADS_CLIENT_ID={CLIENT_ID}\n")
        info, secrets = R.parse_credential_file(p)
        self.assertEqual((info["role"], info["refresh_token_sha12"], info["client_id_sha12"]),
                         ("write", R.sha12(TOKEN), R.sha12(CLIENT_ID)))
        self.assertIn(TOKEN, secrets)

    def test_role_from_filename_when_undeclared(self):
        info, _ = R.parse_credential_file(cred(self.d, ".env.ga", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        self.assertEqual(info["role"], "read")

    def test_crlf_and_quotes_fingerprint_identically(self):
        a, _ = R.parse_credential_file(cred(self.d, "a.gaw", f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n"))
        b, _ = R.parse_credential_file(cred(self.d, "b.gaw", f'GOOGLE_ADS_REFRESH_TOKEN="{TOKEN}"\r\n'))
        self.assertEqual(a["refresh_token_sha12"], b["refresh_token_sha12"])

    def test_credential_set_drops_paths_and_sorts(self):
        infos = [{"path": "/b", "role": "write", "refresh_token_sha12": "b", "client_id_sha12": "c"},
                 {"path": "/a", "role": "read", "refresh_token_sha12": "a", "client_id_sha12": "c"}]
        self.assertEqual(R.credential_set(infos),
                         [{"role": "read", "refresh_token_sha12": "a", "client_id_sha12": "c"},
                          {"role": "write", "refresh_token_sha12": "b", "client_id_sha12": "c"}])


class TestFingerprint(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        a = R.fingerprint({"x": [1, 2], "y": {"b": 1, "a": 2}})
        b = R.fingerprint({"y": {"a": 2, "b": 1}, "x": [1, 2]})
        self.assertEqual(a, b); self.assertTrue(a["complete"])

    def test_any_component_change_changes_it(self):
        self.assertNotEqual(R.fingerprint({"x": "a"})["fingerprint"], R.fingerprint({"x": "b"})["fingerprint"])

    def test_could_not_check_component_marks_incomplete(self):
        self.assertFalse(R.fingerprint({"x": {R.COULD_NOT_CHECK: "unreadable"}})["complete"])


class TestNoSecret(unittest.TestCase):
    def test_raises_when_a_secret_appears(self):
        with self.assertRaises(RuntimeError):
            R.assert_no_secret("bundle ... " + TOKEN, [TOKEN])

    def test_control_clean_text_passes(self):
        R.assert_no_secret("bundle " + R.sha12(TOKEN), [TOKEN])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 review_lib.test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_lib'`

- [ ] **Step 3: Implement `review_lib.py`**

```python
#!/usr/bin/env python3
"""Security-review evidence helpers (spec 2026-09-28 §4-§5). Stdlib only.

Nothing here judges. It makes evidence safe to hand to a reviewer: slugs and customer ids
redacted, credentials reduced to fingerprints, and one canonical fingerprint hash.
"""
import hashlib, json, os, re

CLIENT = "<client>"
OBSERVED = "observed"
COULD_NOT_CHECK = "could-not-check"
SECRET_KEYS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_SECRET",
               "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CLIENT_ID")
ROLE_BY_NAME = {".env.ga": "read", ".env.gaw": "write"}
_MIN_SECRET_LEN = 8


def sha12(value):
    """sha1 of the bare value, first 12 hex — audit-credential-access.py:95's convention."""
    return hashlib.sha1(str(value).encode()).hexdigest()[:12]


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Redactor:
    def __init__(self, slugs, customer_ids):
        self._slugs = sorted({s for s in slugs if s}, key=len, reverse=True)
        cids = {str(c) for c in customer_ids if c}
        self._cids = []
        for c in sorted(cids, key=len, reverse=True):
            self._cids.append((c, c))
            if len(c) == 10 and c.isdigit():
                self._cids.append((f"{c[:3]}-{c[3:6]}-{c[6:]}", c))

    @classmethod
    def from_clients_json(cls, path):
        """Raises ValueError if the registry cannot be read — the caller must then refuse to
        print anything, because it no longer knows what to hide."""
        try:
            with open(path, encoding="utf-8") as f:
                clients = json.load(f).get("clients", {})
        except (OSError, ValueError, AttributeError) as e:
            raise ValueError(f"cannot load the redaction list: {type(e).__name__}")
        if not isinstance(clients, dict):
            raise ValueError("cannot load the redaction list: 'clients' is not an object")
        return cls(list(clients), [(v or {}).get("customer_id", "") for v in clients.values()
                                   if isinstance(v, dict)])

    def text(self, s):
        for raw, digits in self._cids:
            s = s.replace(raw, "cid:" + sha12(digits))
        for slug in self._slugs:
            s = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(slug)}(?![A-Za-z0-9_-])", CLIENT, s)
        return s

    def obj(self, o):
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {self.text(k) if isinstance(k, str) else k: self.obj(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self.obj(v) for v in o]
        return o


def parse_credential_file(path):
    """(info, secrets). Values never leave this function except as sha12 fingerprints —
    `secrets` exists only so the caller can prove none reached its output."""
    values = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            values[k] = v
    role = values.get("GOOGLE_ADS_CREDENTIAL_ROLE") or ROLE_BY_NAME.get(os.path.basename(path), "unknown")
    rt, ci = values.get("GOOGLE_ADS_REFRESH_TOKEN", ""), values.get("GOOGLE_ADS_CLIENT_ID", "")
    info = {"path": path, "role": role,
            "refresh_token_sha12": sha12(rt) if rt else None,
            "client_id_sha12": sha12(ci) if ci else None}
    return info, [values[k] for k in SECRET_KEYS if values.get(k)]


def credential_set(infos):
    rows = [{"role": i["role"], "refresh_token_sha12": i["refresh_token_sha12"],
             "client_id_sha12": i["client_id_sha12"]} for i in infos]
    return sorted(rows, key=lambda r: canon(r))


def fingerprint(components):
    digests = {k: hashlib.sha256(canon(v)).hexdigest() for k, v in sorted(components.items())}
    complete = not any(isinstance(v, dict) and COULD_NOT_CHECK in v for v in components.values())
    return {"fingerprint": hashlib.sha256(canon(digests)).hexdigest(),
            "components": digests, "complete": complete}


def assert_no_secret(text, secrets):
    """The last line of defence: refuse to print if any credential value is present. Never
    says which one."""
    for s in secrets:
        if len(s) >= _MIN_SECRET_LEN and s in text:
            raise RuntimeError("output would contain a credential value — refusing to print")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 review_lib.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/review_lib.py infra/hermes-agent/bin/review_lib.test.py
git commit -m "feat(hermes): review_lib — redaction, credential fingerprints, fingerprint hash (spec §4-§5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The box collector

**Files:**
- Create: `infra/hermes-agent/bin/collect-review-evidence.py`
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py`

**Interfaces:**
- Consumes: `review_lib` (Task 6), `PK.load_manifest`, `PK.sha256_bytes`, `PK.sha256_file`, `C.read_package`.
- Produces: `Host(root="/", run=None)` with `.path(p)` and `.run(argv) -> (rc, out, err)`; `PROBES` — an ordered dict of checklist id → probe function `(host, ctx) -> data`; `collect(host) -> dict` (bundle), `box_fingerprint(host, ctx) -> dict`, `installed_credentials(host) -> (infos, secrets)`; exceptions from a probe become `could-not-check`. CLI: default bundle, `--fingerprint-only`, `--credentials-only`; exit 2 when the redaction list cannot load.

- [ ] **Step 1: Write the failing tests** — `collect-review-evidence.test.py`:

```python
#!/usr/bin/env python3
import importlib.util, json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R
spec = importlib.util.spec_from_file_location("collect_review_evidence", os.path.join(HERE, "collect-review-evidence.py"))
CE = importlib.util.module_from_spec(spec); spec.loader.exec_module(CE)

TOKEN = "1//0gFAKEREFRESHTOKENabcdefghijklmnop"


class FakeHost(CE.Host):
    def __init__(self, root, outputs):
        super().__init__(root=root, run=self._fake)
        self.outputs, self.calls = outputs, []

    def _fake(self, argv, timeout=60):
        self.calls.append(argv)
        for prefix, result in self.outputs.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return result
        return (127, "", "not found")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._w(CE.GOV + "/registry/clients.json",
                json.dumps({"clients": {"acme-dental": {"customer_id": "1234567890", "status": "active",
                                                        "mutation_target": "dormant_pilot"}}}))
        self._w(CE.AGENT_DIR + "/.env.gaw", f"GOOGLE_ADS_CREDENTIAL_ROLE=write\nGOOGLE_ADS_REFRESH_TOKEN={TOKEN}\n")
        self.outputs = {
            ("find",): (0, CE.AGENT_DIR + "/.env.gaw\n" + CE.AGENT_DIR + "/.env.gaw.example\n", ""),
            ("ss",): (0, "LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:9119 0.0.0.0:*\n", ""),
            ("runuser",): (1, "mismatch log/acme-dental.jsonl expected 0660\n", ""),
            ("docker", "ps"): (0, "", ""),
        }

    def _w(self, rel, body):
        p = os.path.join(self.root, rel.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
        return p

    def host(self):
        return FakeHost(self.root, self.outputs)


class TestBundle(Base):
    def test_foreign_tool_output_is_redacted(self):
        out = json.dumps(CE.collect(self.host()))
        self.assertNotIn("acme-dental", out)
        self.assertIn("log/<client>.jsonl", out)

    def test_no_credential_value_or_customer_id_anywhere(self):
        out = json.dumps(CE.collect(self.host()))
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("1234567890", out)
        self.assertIn(R.sha12(TOKEN), out)                          # control: fingerprint present

    def test_failed_command_is_could_not_check(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D1.2"]["status"], R.COULD_NOT_CHECK)   # ufw: not in fake outputs
        self.assertEqual(items["D1.1"]["status"], R.OBSERVED)          # control: ss answered

    def test_gateway_not_running_is_could_not_check(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(items["D4.1"]["status"], R.COULD_NOT_CHECK)

    def test_missing_clients_json_refuses_to_print(self):
        os.remove(os.path.join(self.root, CE.GOV.lstrip("/"), "registry/clients.json"))
        self.assertEqual(CE.main([], host=self.host()), 2)

    def test_every_checklist_box_id_has_a_probe_and_nothing_else_runs(self):
        items = CE.collect(self.host())["items"]
        self.assertEqual(sorted(items), sorted(CE.PROBES))


class TestCredentialsOnly(Base):
    def test_lists_the_installed_set_by_fingerprint(self):
        infos, _ = CE.installed_credentials(self.host())
        self.assertEqual(R.credential_set(infos),
                         [{"role": "write", "refresh_token_sha12": R.sha12(TOKEN), "client_id_sha12": None}])

    def test_examples_are_not_credentials(self):
        infos, _ = CE.installed_credentials(self.host())
        self.assertEqual([os.path.basename(i["path"]) for i in infos], [".env.gaw"])


class TestFingerprint(Base):
    def test_stable_across_runs(self):
        h = self.host()
        self.assertEqual(CE.box_fingerprint(h, CE.context(h)), CE.box_fingerprint(h, CE.context(h)))

    def test_clients_change_changes_it(self):
        h = self.host(); a = CE.box_fingerprint(h, CE.context(h))
        self._w(CE.GOV + "/registry/clients.json", json.dumps({"clients": {}}))
        self.assertNotEqual(a["fingerprint"], CE.box_fingerprint(h, CE.context(h))["fingerprint"])

    def test_credentials_are_not_part_of_the_box_fingerprint(self):
        h = self.host(); a = CE.box_fingerprint(h, CE.context(h))
        os.remove(os.path.join(self.root, CE.AGENT_DIR.lstrip("/"), ".env.gaw"))
        self.assertEqual(a, CE.box_fingerprint(h, CE.context(h)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 collect-review-evidence.test.py -v`
Expected: FAIL — `FileNotFoundError` for `collect-review-evidence.py`

- [ ] **Step 3: Implement `collect-review-evidence.py`**

```python
#!/usr/bin/env python3
"""Security-review evidence collector — BOX side (spec 2026-09-28 §4.2, §5).

  sudo python3 bin/collect-review-evidence.py                    > bundle-box.json
  sudo python3 bin/collect-review-evidence.py --fingerprint-only
  sudo python3 bin/collect-review-evidence.py --credentials-only

READ-ONLY. It observes and reports; it never judges — CHECKLIST.md says what each item
should show, and the independent reviewer compares. Three rules, each tested:
  * nothing printed carries a credential value, a client slug or a customer id;
  * an item it cannot run is `could-not-check`, never silently healthy (F17);
  * if it cannot load the redaction list (clients.json) it prints nothing and exits 2.
"""
import argparse, grp, json, os, pwd, re, stat, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import package_lib as PK
import review_lib as R

AGENT_DIR = "/opt/hermes-agent"
CHECKOUT = "/opt/projects/claude_code"
GOV = "/var/lib/hermes/governance"
SPOOL = "/var/lib/hermes/spool"
UNITS = ("hermes-broker.service", "hermes-docker-proxy.service")
# One entry per app mounted into the executor: the host side of docker-compose.yml's
# HERMES_ADS_REPO_DIR bind (BRING-UP Phase 2). Add a line when an app is added.
APP_HOST_DIRS = {"claude_google_ads": "/opt/projects/claude-google-ads"}
GATEWAY_FILTER = "label=com.docker.compose.service=hermes-agent"
GATEWAY_PROBE_PATHS = ("/opt/governance", "/var/lib/hermes/governance",
                       "/projects/claude_google_ads/.env", "/opt/hermes-agent/.env.gaw",
                       "/opt/hermes-agent/.env.ga")
GATEWAY_CONTROL_PATH = "/opt/registry/projects.yaml"
SWEEP_NAMES = (".env*", "*.ga", "*.gaw", ".git-credentials", "hosts.yml", "credentials.json",
               "application_default_credentials.json", "id_rsa", "id_ecdsa", "id_ed25519")
HISTORY_FILES = (".bash_history", ".zsh_history", ".python_history")
# A value-shaped assignment, or Google's refresh-token prefix. `=//p'` (a sed we ran) and the
# rehearsal's placeholder are not values and must not count.
CRED_TEXT_RE = re.compile(r"GOOGLE_ADS_(?:REFRESH_TOKEN|CLIENT_SECRET|DEVELOPER_TOKEN)="
                          r"(?!REHEARSAL-NOT-A-CREDENTIAL)[A-Za-z0-9_./-]{16,}|\b1//0[0-9A-Za-z_-]{20,}")
CODE_PATHS = ("infra/hermes-agent/bin", "infra/hermes-agent/deploy", "infra/hermes-agent/registry",
              "infra/hermes-agent/docker-compose.yml", "infra/hermes-agent/Dockerfile")
CHECKLIST = CHECKOUT + "/infra/hermes-agent/deploy/security-review/CHECKLIST.md"


def _run_real(argv, timeout=60):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: timed out"


class Host:
    """Everything a probe touches, injectable for tests: the file root and the runner."""
    def __init__(self, root="/", run=None):
        self.root, self._run = root, run or _run_real

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    def run(self, argv, timeout=60):
        return self._run(argv, timeout)


class CouldNotCheck(Exception):
    pass


def _ok(host, argv):
    rc, out, err = host.run(argv)
    if rc != 0:
        raise CouldNotCheck(f"{argv[0]} exited {rc}: {(err or out).strip()[:200]}")
    return out


def _owner(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _stat(host, p):
    st = os.lstat(host.path(p))
    return {"owner": _owner(st.st_uid), "group": _group(st.st_gid),
            "mode": oct(stat.S_IMODE(st.st_mode)), "size": st.st_size}


def context(host):
    """Loaded once per run. Raises ValueError when the redaction list cannot load."""
    return {"redactor": R.Redactor.from_clients_json(host.path(GOV + "/registry/clients.json"))}


# ---------------------------------------------------------------- D1 host exposure
def d1_1(host, ctx):
    out = _ok(host, ["ss", "-tlnH"])
    return {"listeners": sorted({line.split()[3] for line in out.splitlines() if len(line.split()) > 3})}


def d1_2(host, ctx):
    return {"ufw": _ok(host, ["ufw", "status", "verbose"]).splitlines()}


def d1_3(host, ctx):
    keys = ("port", "permitrootlogin", "passwordauthentication", "kbdinteractiveauthentication",
            "pubkeyauthentication", "allowusers", "authenticationmethods")
    got = {}
    for line in _ok(host, ["sshd", "-T"]).splitlines():
        k, _, v = line.partition(" ")
        if k in keys:
            got[k] = v
    return got


def d1_4(host, ctx):
    rc, out, _ = host.run(["systemctl", "is-active", "fail2ban", "unattended-upgrades"])
    states = out.split()
    if len(states) != 2:
        raise CouldNotCheck("systemctl gave no answer")
    return {"fail2ban": states[0], "unattended-upgrades": states[1]}


def d1_5(host, ctx):
    shells = []
    with open(host.path("/etc/passwd")) as f:
        for line in f:
            parts = line.strip().split(":")
            if len(parts) == 7 and not parts[6].endswith(("nologin", "false", "sync")):
                shells.append({"user": parts[0], "shell": parts[6]})
    sudo = {}
    for g in ("sudo", "admin", "wheel"):
        rc, out, _ = host.run(["getent", "group", g])
        if rc == 0:
            sudo[g] = [m for m in out.strip().split(":")[-1].split(",") if m]
    sd = host.path("/etc/sudoers.d")
    return {"login_shells": shells, "sudo_groups": sudo,
            "sudoers_d": sorted(os.listdir(sd)) if os.path.isdir(sd) else []}


def d1_6(host, ctx):
    rc, out, _ = host.run(["getent", "group", "docker"])
    return {"docker_group_members": [m for m in out.strip().split(":")[-1].split(",") if m] if rc == 0 else []}


# ---------------------------------------------------------------- D2 credential inventory
def _sweep(host):
    argv = ["find", "/", "-xdev", "-type", "f", "("]
    for i, n in enumerate(SWEEP_NAMES):
        argv += (["-o"] if i else []) + ["-name", n]
    argv += [")"]
    rc, out, err = host.run(argv, timeout=600)
    if rc not in (0, 1) or (rc == 1 and not out):          # find exits 1 on unreadable subdirs
        raise CouldNotCheck(f"find exited {rc}: {err.strip()[:200]}")
    return sorted(set(line for line in out.splitlines() if line))


def installed_credentials(host):
    infos, secrets = [], []
    for p in _sweep(host):
        if p.endswith(".example"):
            continue
        try:
            info, s = R.parse_credential_file(host.path(p))
        except OSError:
            continue
        if info["refresh_token_sha12"] is None:
            continue                                        # not a Google Ads credential
        info["path"] = p
        infos.append(info); secrets += s
    return infos, secrets


def d2_1(host, ctx):
    rows = []
    for p in _sweep(host):
        row = {"path": p, "kind": "example" if p.endswith(".example") else "candidate"}
        try:
            row.update(_stat(host, p))
            if not p.endswith(".example"):
                info, s = R.parse_credential_file(host.path(p))
                ctx.setdefault("secrets", []).extend(s)
                if info["refresh_token_sha12"]:
                    row["credential"] = {k: info[k] for k in ("role", "refresh_token_sha12", "client_id_sha12")}
        except OSError as e:
            row["error"] = type(e).__name__
        rows.append(row)
    return {"files": rows}


def _count_cred_text(text, secrets):
    return {"pattern_hits": len(CRED_TEXT_RE.findall(text)),
            "known_secret_hits": sum(text.count(s) for s in secrets if len(s) >= 8)}


def d2_2(host, ctx):
    homes = ["/root"] + ["/home/" + h for h in (sorted(os.listdir(host.path("/home")))
                                                if os.path.isdir(host.path("/home")) else [])]
    out = {}
    for home in homes:
        for name in HISTORY_FILES:
            p = f"{home}/{name}"
            if os.path.isfile(host.path(p)):
                with open(host.path(p), errors="replace") as f:
                    out[p] = _count_cred_text(f.read(), ctx.get("secrets", []))
    return {"histories": out}


def d2_3(host, ctx):
    return {"journal": _count_cred_text(_ok(host, ["journalctl", "-o", "cat", "--no-pager"]), ctx.get("secrets", []))}


# ---------------------------------------------------------------- D4 isolation boundaries
def d4_1(host, ctx):
    gw = _ok(host, ["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER]).strip()
    if len(gw) != 64:
        raise CouldNotCheck("gateway container not running — isolation cannot be observed")
    script = ('for p in "$@"; do if [ -e "$p" ]; then if [ -r "$p" ]; then '
              'echo "$p readable $(wc -c < "$p" 2>/dev/null || echo dir)"; else echo "$p unreadable"; fi; '
              'else echo "$p absent"; fi; done')
    out = _ok(host, ["docker", "exec", gw, "sh", "-c", script, "sh", *GATEWAY_PROBE_PATHS, GATEWAY_CONTROL_PATH])
    env = _ok(host, ["docker", "exec", gw, "env"])
    return {"paths": out.splitlines(),
            "google_ads_env_names": sorted(l.split("=", 1)[0] for l in env.splitlines() if l.startswith("GOOGLE_ADS_"))}


def d4_2(host, ctx):
    active = host.run(["systemctl", "is-active", "hermes-docker-proxy"])[1].strip()
    execstart = _ok(host, ["systemctl", "show", "hermes-docker-proxy", "-p", "ExecStart"])
    return {"active": active, "execstart_sha256": PK.sha256_bytes(execstart.encode())}


def d4_3(host, ctx):
    out = {}
    for u in UNITS:
        inst, repo = host.path("/etc/systemd/system/" + u), host.path(CHECKOUT + "/infra/hermes-agent/deploy/" + u)
        out[u] = {"installed": PK.sha256_file(inst) if os.path.isfile(inst) else None,
                  "repo": PK.sha256_file(repo) if os.path.isfile(repo) else None}
    return out


def d4_4(host, ctx):
    rc, out, err = host.run(["runuser", "-u", "hermes-broker", "--", "python3", AGENT_DIR + "/bin/init-host-layout.py",
                             "--check", "--store-root", GOV, "--spool-root", SPOOL])
    return {"rc": rc, "output": (out + err).splitlines()[-40:]}


# ---------------------------------------------------------------- D5 governance store
def d5_1(host, ctx):
    rc, out, err = host.run(["runuser", "-u", "hermes-broker", "--", "python3",
                             AGENT_DIR + "/bin/preflight-governance-access.py", "--root", GOV])
    return {"rc": rc, "output": (out + err).splitlines()[-40:]}


def d5_2(host, ctx):
    logs = sorted(n for n in os.listdir(host.path(GOV + "/log")) if n.endswith(".jsonl"))
    sealed = 0
    for n in logs:
        rc, out, _ = host.run(["lsattr", GOV + "/log/" + n])
        if rc == 0 and "a" in out.split()[0]:
            sealed += 1
    return {"logs": len(logs), "sealed": sealed}


def d5_3(host, ctx):
    return {"kill_switch_present": os.path.lexists(host.path(GOV + "/control/mutation-enabled"))}


def d5_4(host, ctx):
    with open(host.path(GOV + "/registry/clients.json")) as f:
        clients = json.load(f).get("clients", {})
    by_status = {}
    for rec in clients.values():
        by_status[rec.get("status", "?")] = by_status.get(rec.get("status", "?"), 0) + 1
    return {"clients": len(clients), "by_status": by_status,
            "dormant_pilots": sum(1 for r in clients.values() if r.get("mutation_target") == "dormant_pilot")}


# ---------------------------------------------------------------- D6 app packages
def d6_1(host, ctx):
    projects = host.path(CHECKOUT + "/infra/hermes-agent/registry/projects.yaml")
    out = {}
    for project, d in APP_HOST_DIRS.items():
        row = {"placeholder": os.path.exists(host.path(d + "/PLACEHOLDER")),
               "git_dir": os.path.exists(host.path(d + "/.git"))}
        try:
            pin = C.read_package(projects, project)
            row["pin"] = pin and {"commit": pin["commit"], "sha256": pin["sha256"]}
        except ValueError as e:
            row["pin_error"] = str(e)
        mpath = host.path(d + "/" + PK.MANIFEST_NAME)
        if os.path.isfile(mpath):
            with open(mpath, "rb") as f:
                raw = f.read()
            m = PK.load_manifest(raw)
            bad = [e["path"] for e in m["files"]
                   if not os.path.isfile(host.path(d + "/" + e["path"]))
                   or PK.sha256_file(host.path(d + "/" + e["path"])) != e["sha256"]]
            extra = []
            for root, _, names in os.walk(host.path(d)):
                for n in names:
                    rel = os.path.relpath(os.path.join(root, n), host.path(d))
                    if rel not in {e["path"] for e in m["files"]} | {PK.MANIFEST_NAME, ".env"}:
                        extra.append(rel)
            row.update(installed_sha256=PK.sha256_bytes(raw), commit=m["commit"],
                       files=len(m["files"]), mismatched=bad, extra=sorted(extra))
        else:
            row["installed_sha256"] = None
        out[project] = row
    return out


def d6_2(host, ctx):
    rc, out, _ = host.run(["find", "/root", "/home", "-xdev", "(", "-name", ".git-credentials", "-o",
                           "-path", "*/.config/gh/hosts.yml", "-o", "-name", "id_rsa", "-o",
                           "-name", "id_ecdsa", "-o", "-name", "id_ed25519", ")"])
    if rc not in (0, 1):
        raise CouldNotCheck(f"find exited {rc}")
    return {"git_or_ssh_private_credentials": sorted(l for l in out.splitlines() if l)}


# ---------------------------------------------------------------- D7 client data
def d7_1(host, ctx):
    vaults = host.path(AGENT_DIR + "/data/vaults")
    vault_rows = []
    if os.path.isdir(vaults):
        for n in sorted(os.listdir(vaults)):
            vault_rows.append(_stat(host, AGENT_DIR + "/data/vaults/" + n))
    records = host.path(GOV + "/records")
    backups = sorted(n for n in os.listdir(host.path("/root")) if n.startswith("live-gate-")) \
        if os.path.isdir(host.path("/root")) else []
    return {"vaults": vault_rows,
            "records": sum(len(fs) for _, _, fs in os.walk(records)) if os.path.isdir(records) else 0,
            "root_backups": [{"dir": b, "files": len(os.listdir(host.path("/root/" + b)))} for b in backups]}


PROBES = {"D1.1": d1_1, "D1.2": d1_2, "D1.3": d1_3, "D1.4": d1_4, "D1.5": d1_5, "D1.6": d1_6,
          "D2.1": d2_1, "D2.2": d2_2, "D2.3": d2_3,
          "D4.1": d4_1, "D4.2": d4_2, "D4.3": d4_3, "D4.4": d4_4,
          "D5.1": d5_1, "D5.2": d5_2, "D5.3": d5_3, "D5.4": d5_4,
          "D6.1": d6_1, "D6.2": d6_2, "D7.1": d7_1}


# ---------------------------------------------------------------- fingerprint (§5.1)
def _component(fn):
    try:
        return fn()
    except (CouldNotCheck, OSError, ValueError) as e:
        return {R.COULD_NOT_CHECK: type(e).__name__}


def box_fingerprint(host, ctx):
    def clients():
        with open(host.path(GOV + "/registry/clients.json"), "rb") as f:
            return PK.sha256_bytes(f.read())

    def packages():
        out = {}
        for project, d in APP_HOST_DIRS.items():
            p = host.path(d + "/" + PK.MANIFEST_NAME)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    raw = f.read()
                out[project] = {"sha256": PK.sha256_bytes(raw), "commit": PK.load_manifest(raw)["commit"]}
            else:
                out[project] = None
        return out

    def code():
        base = ["git", "-c", f"safe.directory={CHECKOUT}", "-C", CHECKOUT]
        trees = {p: _ok(host, base + ["rev-parse", f"HEAD:{p}"]).strip() for p in CODE_PATHS}
        dirty = _ok(host, base + ["status", "--porcelain", "--", *CODE_PATHS]).strip()
        return {"trees": trees, "dirty": bool(dirty)}

    def entry_points():
        return {"listeners": d1_1(host, ctx)["listeners"],
                "ufw": _ok(host, ["ufw", "status", "verbose"]).splitlines(),
                "sshd": sorted(_ok(host, ["sshd", "-T"]).splitlines())}

    def checklist():
        with open(host.path(CHECKLIST)) as f:
            for line in f:
                m = re.match(r"^version:\s*(\S+)", line)
                if m:
                    return m.group(1)
        raise ValueError("no version line")

    return R.fingerprint({"clients": _component(clients), "packages": _component(packages),
                          "code": _component(code), "entry_points": _component(entry_points),
                          "checklist": _component(checklist)})


# ---------------------------------------------------------------- assembly
def collect_with_secrets(host):
    """The bundle (redacted) and every credential value seen, for assert_no_secret."""
    ctx = context(host)
    items = {}
    for iid, fn in PROBES.items():
        try:
            items[iid] = {"status": R.OBSERVED, "data": fn(host, ctx)}
        except (CouldNotCheck, OSError, ValueError, KeyError, IndexError) as e:
            items[iid] = {"status": R.COULD_NOT_CHECK, "reason": f"{type(e).__name__}: {e}"}
    try:
        infos, secrets = installed_credentials(host)
        creds = R.credential_set(infos)
    except CouldNotCheck as e:
        secrets, creds = [], {R.COULD_NOT_CHECK: str(e)}
    bundle = {"schema": 1, "kind": "box", "items": items,
              "fingerprint": box_fingerprint(host, ctx), "credentials": creds}
    return ctx["redactor"].obj(bundle), ctx.get("secrets", []) + secrets


def collect(host):
    return collect_with_secrets(host)[0]


def main(argv=None, host=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fingerprint-only", action="store_true")
    g.add_argument("--credentials-only", action="store_true")
    a = ap.parse_args(argv)
    host = host or Host()
    try:
        ctx = context(host)
    except ValueError as e:
        print(f"collect-review-evidence: {e} — refusing to print anything I cannot redact", file=sys.stderr)
        return 2
    if a.fingerprint_only:
        out, secrets = box_fingerprint(host, ctx), []
    elif a.credentials_only:
        infos, secrets = installed_credentials(host)
        out = R.credential_set(infos)
    else:
        out, secrets = collect_with_secrets(host)
    text = json.dumps(ctx["redactor"].obj(out), indent=2, sort_keys=True)
    R.assert_no_secret(text, secrets)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 collect-review-evidence.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "feat(hermes): box evidence collector — redacting probes, box fingerprint, credential set (spec §4.2, §5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The laptop collector

**Files:**
- Create: `infra/hermes-agent/bin/collect-review-evidence-laptop.py`
- Test: `infra/hermes-agent/bin/collect-review-evidence-laptop.test.py`

**Interfaces:**
- Consumes: `review_lib` (Task 6), `build-app-package.py`'s `build()` (Task 3).
- Produces: `parse_audit(stdout: str) -> list[dict]`; `access_digest(rows) -> str`; `ITEMS` — dict of checklist id → function; CLI `--customer <digits> [--package-project --package-repo --package-commit] [--access-digest]`.

- [ ] **Step 1: Write the failing tests** — `collect-review-evidence-laptop.test.py`:

```python
#!/usr/bin/env python3
import importlib.util, json, os, sys, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("collect_laptop", os.path.join(HERE, "collect-review-evidence-laptop.py"))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)


def doc(label, verdict, admin, rt="aaaaaaaaaaaa"):
    return json.dumps({"label": label, "fingerprints": {"refresh_token_sha12": rt, "client_id_sha12": "c"},
                       "declared_role": "write" if label.endswith("w") else "read",
                       "expected_verdict": verdict, "measured_verdict": verdict, "mismatch": False,
                       "manager_level_admin": {"admin": admin, "reason": "x"}}, indent=2)


AUDIT = ("Container x Creating\nContainer x Created\n" + doc(".env.ga", "READ_ONLY", False, "r" * 12) +
         "\nContainer y Created\n" + doc(".env.gaw", "MUTATE_CAPABLE", True) + "\n")


class TestParse(unittest.TestCase):
    def test_extracts_both_documents_through_compose_noise(self):
        rows = L.parse_audit(AUDIT)
        self.assertEqual([r["label"] for r in rows], [".env.ga", ".env.gaw"])
        self.assertEqual(rows[1]["admin"], True)

    def test_digest_is_stable_and_changes_with_access(self):
        a = L.access_digest(L.parse_audit(AUDIT))
        self.assertEqual(a, L.access_digest(L.parse_audit(AUDIT)))
        drift = AUDIT.replace('"admin": true', '"admin": false')
        self.assertNotEqual(a, L.access_digest(L.parse_audit(drift)))

    def test_no_documents_raises(self):
        with self.assertRaises(ValueError):
            L.parse_audit("Container x Created\n")


class TestAuditRun(unittest.TestCase):
    def test_exit_code_is_the_audits_own_and_stderr_is_discarded(self):
        fake = mock.Mock(returncode=3, stdout=AUDIT, stderr="Request made: ClientCustomerId: 1234567890 ...")
        with mock.patch.object(L.subprocess, "run", return_value=fake):
            out = L.run_audit("1234567890")
        self.assertEqual(out["rc"], 3)
        self.assertNotIn("1234567890", json.dumps(out))
        self.assertEqual(out["stderr_lines_discarded"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 collect-review-evidence-laptop.test.py -v`
Expected: FAIL — `FileNotFoundError`

- [ ] **Step 3: Implement `collect-review-evidence-laptop.py`**

```python
#!/usr/bin/env python3
"""Security-review evidence collector — LAPTOP side (spec 2026-09-28 §4.3, §5.1).

  python3 bin/collect-review-evidence-laptop.py --customer "$CUST" \\
      --package-project claude_google_ads --package-repo ~/Projects/claude-google-ads \\
      --package-commit <40-hex>                                  > bundle-laptop.json
  python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --access-digest

D3: runs audit-credential-access.sh --all --customer, keeps the AUDIT's own exit code (a
pipe would hide it — found 2026-09-26), and DISCARDS stderr, where the Google Ads SDK logs
raw account ids (a D9 item). D6: rebuilds the package from the verified commit and reports
its hash. Customer ids are redacted from everything printed.
"""
import argparse, hashlib, importlib.util, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

AUDIT_SH = os.path.join(os.path.dirname(HERE), "audit-credential-access.sh")


def parse_audit(stdout):
    rows, dec, i = [], json.JSONDecoder(), 0
    while True:
        i = stdout.find("{", i)
        if i < 0:
            break
        try:
            obj, end = dec.raw_decode(stdout, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and "label" in obj and "measured_verdict" in obj:
            rows.append({"label": obj["label"], "declared_role": obj.get("declared_role"),
                         "expected_verdict": obj.get("expected_verdict"),
                         "measured_verdict": obj["measured_verdict"], "mismatch": obj.get("mismatch"),
                         "admin": (obj.get("manager_level_admin") or {}).get("admin"),
                         "refresh_token_sha12": (obj.get("fingerprints") or {}).get("refresh_token_sha12"),
                         "client_id_sha12": (obj.get("fingerprints") or {}).get("client_id_sha12")})
        i = end
    if not rows:
        raise ValueError("no audit documents in the output")
    return rows


def access_digest(rows):
    keep = ("label", "measured_verdict", "mismatch", "admin", "refresh_token_sha12")
    return hashlib.sha256(R.canon(sorted(({k: r[k] for k in keep} for r in rows),
                                         key=R.canon))).hexdigest()


def run_audit(customer):
    p = subprocess.run([AUDIT_SH, "--all", "--customer", customer], capture_output=True, text=True)
    red = R.Redactor([], [customer])
    try:
        rows = parse_audit(p.stdout)
        return red.obj({"rc": p.returncode, "rows": rows, "digest": access_digest(rows),
                        "stderr_lines_discarded": len(p.stderr.splitlines())})
    except ValueError as e:
        return {"rc": p.returncode, R.COULD_NOT_CHECK: str(e),
                "stderr_lines_discarded": len(p.stderr.splitlines())}


def package_hash(project, repo, commit):
    spec = importlib.util.spec_from_file_location("build_app_package", os.path.join(HERE, "build-app-package.py"))
    B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
    out = B.build(project, repo, commit, B.DEFAULT_PROJECTS, tempfile.mkdtemp())
    return {"project": project, "commit": commit, "sha256": out["sha256"], "files": out["files"]}


ITEMS = {"D3.1": "run_audit", "D6.3": "package_hash"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--customer", required=True)
    ap.add_argument("--access-digest", action="store_true")
    ap.add_argument("--package-project"); ap.add_argument("--package-repo"); ap.add_argument("--package-commit")
    a = ap.parse_args(argv)
    if not a.customer.isdigit():
        print("collect-review-evidence-laptop: --customer must be digits", file=sys.stderr)
        return 1
    audit = run_audit(a.customer)
    if a.access_digest:
        print(audit.get("digest", R.COULD_NOT_CHECK))
        return 0 if "digest" in audit and audit["rc"] == 0 else 2
    items = {"D3.1": {"status": R.OBSERVED if "digest" in audit else R.COULD_NOT_CHECK, "data": audit}}
    if a.package_project and a.package_repo and a.package_commit:
        try:
            items["D6.3"] = {"status": R.OBSERVED,
                             "data": package_hash(a.package_project, a.package_repo, a.package_commit)}
        except (ValueError, OSError) as e:
            items["D6.3"] = {"status": R.COULD_NOT_CHECK, "reason": str(e)}
    else:
        items["D6.3"] = {"status": R.COULD_NOT_CHECK, "reason": "no --package-* arguments"}
    print(json.dumps({"schema": 1, "kind": "laptop", "items": items}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd infra/hermes-agent/bin && python3 collect-review-evidence-laptop.test.py -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence-laptop.py infra/hermes-agent/bin/collect-review-evidence-laptop.test.py
git commit -m "feat(hermes): laptop evidence collector — D3 audit with its own exit code, access digest, D6 package hash

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The checklist, the reviewer brief, the report template — kept in sync

**Files:**
- Create: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`
- Create: `infra/hermes-agent/deploy/security-review/REVIEWER-BRIEF.md`
- Create: `infra/hermes-agent/deploy/security-review/REPORT-TEMPLATE.md`
- Test: `infra/hermes-agent/bin/security-review-checklist.test.py`

**Interfaces:**
- Consumes: `CE.PROBES` (Task 7), `L.ITEMS` (Task 8).
- Produces: checklist items `### <ID> — <title>` each with a `- **source:** box|laptop|manual` line; a `version:` line.

- [ ] **Step 1: Write the failing sync test** — `security-review-checklist.test.py`:

```python
#!/usr/bin/env python3
import importlib.util, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CHECKLIST = os.path.join(os.path.dirname(HERE), "deploy", "security-review", "CHECKLIST.md")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def items():
    text = open(CHECKLIST).read()
    found = {}
    for block in re.split(r"(?m)^### ", text)[1:]:
        m = re.match(r"(D\d+\.\d+) — ", block)
        s = re.search(r"(?m)^- \*\*source:\*\* (box|laptop|manual)\s*$", block)
        if m:
            found[m.group(1)] = s.group(1) if s else None
    return text, found


class TestChecklistSync(unittest.TestCase):
    def test_has_a_version(self):
        self.assertRegex(items()[0], r"(?m)^version: \d+\.\d+$")

    def test_every_item_declares_a_source(self):
        self.assertEqual({k: v for k, v in items()[1].items() if v is None}, {})

    def test_box_items_equal_the_box_collector(self):
        box = {k for k, v in items()[1].items() if v == "box"}
        self.assertEqual(box, set(_load("ce", "collect-review-evidence.py").PROBES))

    def test_laptop_items_equal_the_laptop_collector(self):
        lap = {k for k, v in items()[1].items() if v == "laptop"}
        self.assertEqual(lap, set(_load("cl", "collect-review-evidence-laptop.py").ITEMS))

    def test_every_area_d1_to_d9_is_present(self):
        areas = {k.split(".")[0] for k in items()[1]}
        self.assertEqual(areas, {f"D{i}" for i in range(1, 10)})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra/hermes-agent/bin && python3 security-review-checklist.test.py -v`
Expected: FAIL — `FileNotFoundError` for `CHECKLIST.md`

- [ ] **Step 3: Write `CHECKLIST.md`**

````markdown
# Hermes security review — checklist

version: 1.0

Spec: `docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`. Every report
cites this version. Changing this file changes the box fingerprint's `checklist` component,
which re-triggers the review (§5).

**How to read an item.** `source` says where the evidence comes from: `box` (the box
bundle, item id as key), `laptop` (the laptop bundle), or `manual` (the operator states it
in the report). `expected` is what a healthy box shows. The reviewer marks each item
`PASS`, `FAIL` or `CANNOT-VERIFY`, quoting the evidence. An item whose evidence is
`could-not-check` is `CANNOT-VERIFY` — never `PASS`.

## D1 Host exposure

### D1.1 — Only SSH listens publicly
- **source:** box
- **claim:** the only non-loopback listener is `:22`.
- **expected:** `listeners` contains `0.0.0.0:22` and/or `[::]:22`; every other entry starts with `127.` or `[::1]` (e.g. the dashboard's `127.0.0.1:9119`).
- **pass rule:** no other non-loopback address.

### D1.2 — The firewall agrees
- **source:** box
- **claim:** `ufw` is active, default-deny inbound, and allows only 22/tcp.
- **expected:** `Status: active`, `Default: deny (incoming)`, a single `22/tcp ALLOW IN` rule (v4 and v6).
- **pass rule:** no other ALLOW IN rule.

### D1.3 — SSH is key-only, no root login
- **source:** box
- **claim:** `sshd -T` refuses passwords and root.
- **expected:** `permitrootlogin no`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`.
- **pass rule:** all four exactly.

### D1.4 — Brute-force and patch hygiene are on
- **source:** box
- **claim:** fail2ban and unattended-upgrades run.
- **expected:** both `active`.
- **pass rule:** both `active`.

### D1.5 — Only expected accounts can log in or sudo
- **source:** box
- **claim:** login shells and sudo membership are exactly the operator's.
- **expected:** login shells: `root` and `hermesops` only; sudo group: `hermesops` only; `sudoers_d` holds only files the operator recognises.
- **pass rule:** any unexplained account is a FAIL.

### D1.6 — The deploy user is not in the docker group
- **source:** box
- **claim:** `docker` group membership would be root-equivalent.
- **expected:** `docker_group_members` is empty.
- **pass rule:** empty.

## D2 Credential inventory

### D2.1 — The credential sweep finds exactly the authorised set
- **source:** box
- **claim:** a system-wide sweep (not known paths — F24) finds only authorised credentials, each `hermes-broker:hermes-broker 0600` (write) or as the README table says (read).
- **expected:** every `credential` row matches an entry in the report's authorised set; examples are `kind: example`; nothing else carries a `credential`.
- **pass rule:** an unexpected credential, or a mode wider than `0600`, is a FAIL.

### D2.2 — No credential text in shell histories
- **source:** box
- **claim:** no value-shaped credential or known secret sits in any history file.
- **expected:** every `pattern_hits` and `known_secret_hits` is `0`.
- **pass rule:** any non-zero is a FAIL until explained and cleaned.

### D2.3 — No credential text in the journal
- **source:** box
- **claim:** as D2.2, for `journalctl`.
- **expected:** both counts `0`.
- **pass rule:** any non-zero is a FAIL.

## D3 Credential access, as Google sees it

### D3.1 — Every credential measures as declared
- **source:** laptop
- **claim:** `audit-credential-access.sh --all --customer` measures each role as declared, with the audit's own exit code.
- **expected:** `rc 0`; `.env.ga` `READ_ONLY`; `.env.gaw` `MUTATE_CAPABLE`; every `mismatch false`; the fingerprints equal the authorised set.
- **pass rule:** any mismatch or non-zero `rc` is a FAIL.

### D3.2 — The ADMIN decision is made and recorded
- **source:** manual
- **claim:** the operator has decided whether the ADMIN operator account stays the write credential or is replaced by a dedicated STANDARD-access account (spec decision 7).
- **expected:** the report states the decision and the reason; the `projects.yaml` comment matches it.
- **pass rule:** no recorded decision is CANNOT-VERIFY.

## D4 Isolation boundaries

### D4.1 — The gateway cannot read credentials or the governance store
- **source:** box
- **claim:** from inside the gateway container, the governance store is absent and credential files are absent, unreadable or empty masks; the control path is readable.
- **expected:** `/opt/governance` and `/var/lib/hermes/governance` `absent`; `/projects/claude_google_ads/.env` `readable 0` (the empty mask) or `absent`; both `/opt/hermes-agent/.env.ga*` `absent`; `/opt/registry/projects.yaml` `readable <n>` (the control); `google_ads_env_names` empty.
- **pass rule:** a readable credential, or a failed control, is a FAIL; `could-not-check` is CANNOT-VERIFY.

### D4.2 — The Docker proxy is live
- **source:** box
- **claim:** `hermes-docker-proxy` is active with its reviewed ExecStart.
- **expected:** `active`; `execstart_sha256` equal to the previous PASS report's (first review: recorded).
- **pass rule:** inactive is a FAIL.

### D4.3 — Installed units equal the repo
- **source:** box
- **claim:** each installed unit file is byte-identical to `deploy/`.
- **expected:** `installed == repo` for both units.
- **pass rule:** any difference is a FAIL.

### D4.4 — The broker's layout check passes
- **source:** box
- **claim:** `init-host-layout.py --check` as `hermes-broker` passes.
- **expected:** `rc 0`.
- **pass rule:** non-zero is a FAIL.

## D5 Governance store

### D5.1 — The pre-flight passes
- **source:** box
- **claim:** `preflight-governance-access.py` as `hermes-broker` passes.
- **expected:** `rc 0`.
- **pass rule:** non-zero is a FAIL.

### D5.2 — Every registered log is sealed
- **source:** box
- **claim:** every `log/*.jsonl` carries the append-only flag (§6B).
- **expected:** `sealed == logs`.
- **pass rule:** any unsealed log is a FAIL.

### D5.3 — The kill switch is absent
- **source:** box
- **claim:** mutation is disabled during the review.
- **expected:** `kill_switch_present false`.
- **pass rule:** present is a FAIL.

### D5.4 — The registry is as expected
- **source:** box
- **claim:** client counts match the operator's own list.
- **expected:** the operator confirms the counts by status, and `dormant_pilots` is `1`.
- **pass rule:** unexplained clients are a FAIL.

## D6 App packages

### D6.1 — The installed package is the pinned package
- **source:** box
- **claim:** each app directory holds exactly the pinned package.
- **expected:** `installed_sha256 == pin.sha256`; `commit == pin.commit`; `mismatched` and `extra` empty; `placeholder false`; `git_dir false`.
- **pass rule:** any deviation is a FAIL.

### D6.2 — No git or GitHub credential on the box
- **source:** box
- **claim:** no private SSH key, `.git-credentials` or `gh` token in any home.
- **expected:** `git_or_ssh_private_credentials` empty (SSH *authorized_keys* are not listed and are fine).
- **pass rule:** anything listed is a FAIL until explained.

### D6.3 — The pin is a package built from the verified commit
- **source:** laptop
- **claim:** rebuilding from the operator-verified commit gives the pinned hash.
- **expected:** laptop `D6.3.sha256` == box `D6.1.pin.sha256`, same `commit`.
- **pass rule:** any difference is a FAIL.

## D7 Client data on the box

### D7.1 — Client data is where it should be, readable only by its owners
- **source:** box
- **claim:** vaults, run records and backups are the expected ones, none world-readable, none inside a package.
- **expected:** vault directories `0700` owned by uid 10000; `root_backups` explained by the operator (e.g. `live-gate-*`).
- **pass rule:** a world-readable client path is a FAIL.

## D8 Stop and recover

### D8.1 — Mutation can be disabled in one step
- **source:** manual
- **claim:** the operator can remove the kill switch and stop both units in one documented block.
- **expected:** the report cites the BRING-UP block.
- **pass rule:** no documented block is CANNOT-VERIFY.

### D8.2 — Revocation is written and proves death
- **source:** manual
- **claim:** the revocation procedure exists and ends by using the token and observing the refusal (canon, credential governance).
- **expected:** the report cites the procedure.
- **pass rule:** a procedure that trusts HTTP 200 is a FAIL.

## D9 Open findings

### D9.1 — Every open finding is decided
- **source:** manual
- **claim:** each open item is `accepted (reason)` or `blocking`.
- **expected:** a line each for F3, F8, F16, F17, F20, the `audit_data` data layer, repo visibility, `main` branch protection, and the SDK logger printing raw account ids — plus any finding opened since.
- **pass rule:** an undecided item is CANNOT-VERIFY.
````

- [ ] **Step 4: Write `REVIEWER-BRIEF.md`**

```markdown
# Brief for the independent security reviewer

You are reviewing a production box you did not build. You receive ONLY:

1. `CHECKLIST.md` (this directory) — cite its `version:`.
2. The box bundle and the laptop bundle (JSON, redacted by design).
3. `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`.

You do not receive the build conversation. Do not ask for it.

## Rules

- Judge every checklist item: `PASS`, `FAIL` or `CANNOT-VERIFY`. Quote the evidence (a short excerpt) for each.
- `could-not-check` evidence is `CANNOT-VERIFY`. Missing evidence is `CANNOT-VERIFY`. Never pass by default — ask the operator for more evidence instead.
- Anything alarming the checklist does not cover goes in **Not on the checklist**, with your recommendation.
- For D3.2 you may recommend a dedicated STANDARD-access account; the operator decides.
- The overall verdict is PASS only if every item is PASS (manual items: the operator's statement is the evidence).
- Never paste a client slug, a customer id or a credential value into the report — the bundles already hide them; keep it that way.

## Output

Write `docs/security-reviews/YYYY-MM-DD-review.md` from `REPORT-TEMPLATE.md`.
```

- [ ] **Step 5: Write `REPORT-TEMPLATE.md`**

```markdown
# Security review — YYYY-MM-DD

- **Checklist version:** 
- **Reviewer:** (session / model) — did not build the box: yes
- **Box fingerprint:** `<sha256>` (complete: true|false)
- **Authorised credential set:** (role, refresh-token sha12, client-id sha12 — one line each)
- **Measured-access digest:** `<sha256>`
- **Components changed since the last PASS:** (first review: n/a)

## Verdicts

| Item | Verdict | Evidence (short quote) | Note |
|---|---|---|---|
| D1.1 | | | |

## Not on the checklist

## Reviewer's overall verdict

PASS | NOT PASS — (one paragraph)

## Operator sign-off

- **Final verdict:** PASS | NOT PASS
- **D3.2 decision:** (ADMIN kept | replaced) — reason:
- **D9 decisions:** (one line per finding: accepted (reason) | blocking)
- **Signed:** operator, date
```

- [ ] **Step 6: Run the sync test and the runner**

Run: `cd infra/hermes-agent/bin && python3 security-review-checklist.test.py -v 2>&1 | tail -3 && ./run-bin-tests.sh 2>&1 | tail -1`
Expected: `OK` and `hermes bin: 38/38 suites passed`.

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/deploy/security-review/ infra/hermes-agent/bin/security-review-checklist.test.py
git commit -m "feat(hermes): security-review checklist v1.0, reviewer brief, report template, sync test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Wire it into the runbook

**Files:**
- Modify: `.gitignore` (append)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` ("Before creating the kill switch", after the F23 block)
- Modify: `infra/hermes-agent/README.md` (a short section near "Provisioning a credential")

- [ ] **Step 1: `.gitignore`** — append:

```
# Security-review raw evidence bundles — never committed (spec 2026-09-28 decision 6)
infra/hermes-agent/security-reviews/
```

Verify: `git check-ignore -v infra/hermes-agent/security-reviews/x.json` prints the rule.

- [ ] **Step 2: BRING-UP** — after the F23 "Also required" block and its attempt-1 RESULT, add:

````markdown
**The security review must PASS for the current state (spec 2026-09-28 §5.3).** The ads repo
now reaches the box as an **app package** (`bin/build-app-package.py` on the laptop,
`sudo bin/install-app-package.py` here) — not a clone, so `git rev-parse` above does not apply;
use `D6.1` instead. Three checks against the latest PASS report in `docs/security-reviews/`,
all of which must hold before the kill switch is created:

```bash
sudo python3 bin/collect-review-evidence.py --fingerprint-only     # "fingerprint" == the report's box fingerprint, "complete": true
sudo python3 bin/collect-review-evidence.py --credentials-only     # == the report's authorised credential set
# laptop: python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --access-digest   # == the report's digest
```
````

Also change the `MUTATOR_OK` block's first line to test the package instead of the placeholder:

```bash
sudo test ! -e $A/PLACEHOLDER && sudo test -f $A/code/mutate_campaign_negative.py && sudo test -f $A/.hermes-package.json && echo MUTATOR_OK   # MUTATOR_OK
```

and delete the `git rev-parse HEAD` line below it (packages carry no `.git`; D6.1 covers the commit).

- [ ] **Step 3: README** — add a section:

```markdown
## Security review and app packages

The gate for real credentials and for any app code on the box is the **security review**
(`docs/superpowers/specs/2026-09-28-hermes-security-review-design.md`): a versioned checklist
(`deploy/security-review/CHECKLIST.md`), two read-only collectors that redact by design
(`bin/collect-review-evidence.py` on the box, `bin/collect-review-evidence-laptop.py` on the
laptop), an independent reviewer (`deploy/security-review/REVIEWER-BRIEF.md`), and the
operator's sign-off. Raw bundles live in the gitignored `security-reviews/`; only the report
is committed. A PASS binds to a box fingerprint; any trigger (§5) voids it.

App code reaches the box as a **package**: the registry allow-lists' files plus
`package.include`, at a verified commit, pinned by `package.sha256` in `registry/projects.yaml`.
Guard 7 refuses a mutator whose bytes differ from the pinned manifest.
```

- [ ] **Step 4: Verify and commit**

Run: `cd infra/hermes-agent/bin && ./run-bin-tests.sh 2>&1 | tail -1 && python3 ../deploy/provision.test.py 2>&1 | tail -1`
Expected: `hermes bin: 38/38 suites passed`, `OK`.

```bash
git add .gitignore infra/hermes-agent/deploy/BRING-UP.md infra/hermes-agent/README.md
git commit -m "docs(hermes): wire the security review and app packages into BRING-UP and README; ignore raw evidence

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Pin the ads app (operator names the commit)

**Files:**
- Modify: `infra/hermes-agent/registry/projects.yaml` (`claude_google_ads` entry)
- Modify: `infra/hermes-agent/bin/registry-invariants.test.py` (append a test)

**Interfaces:**
- Consumes: `build-app-package.py` (Task 3), `C.read_package` (Task 1).

- [ ] **Step 1: The operator names the verified commit** of `~/Projects/claude-google-ads` (the one whose mutator they have reviewed). Do not choose it yourself. Check it out: `git -C ~/Projects/claude-google-ads checkout <commit>`.

- [ ] **Step 2: Write the failing invariant** — append to `registry-invariants.test.py`:

```python
    def test_every_mutating_project_is_pinned_to_a_package(self):
        # Guard 7 refuses any unpinned mutator (spec 2026-09-28 §6.5). The registry must
        # therefore pin every project that can mutate, or it ships a dead rail.
        for p in self.projects:
            if C.read_allow_list(REGISTRY, p, "mutate_execute"):
                with self.subTest(project=p):
                    self.assertIsNotNone(C.read_package(REGISTRY, p),
                                         f"{p} has a mutate_execute allow-list but no package pin")
```

(Add it to the same class as `test_allow_list_entries_are_bare_basenames`, which provides `self.projects` via `discover_projects(REGISTRY)`.)

Run: `cd infra/hermes-agent/bin && python3 registry-invariants.test.py -v 2>&1 | tail -3` — Expected: FAIL (`claude_google_ads has a mutate_execute allow-list but no package pin`).

- [ ] **Step 3: Add the `include` list, build, then pin** — in `projects.yaml` under `claude_google_ads`, at indent 4:

```yaml
    # App package (spec 2026-09-28 §6): the allow-listed code of BOTH tiers plus these
    # static inputs, at a verified commit. Guard 7 refuses a mutator whose bytes differ.
    package:
      include:
        - universal-negative-keywords.md
```

Then build:

```bash
cd infra/hermes-agent
python3 bin/build-app-package.py --project claude_google_ads --repo ~/Projects/claude-google-ads \
    --commit <commit> --out-dir security-reviews/pkg
```

Add the printed values above `include:`:

```yaml
      commit: <commit>
      sha256: <printed sha256>
```

and correct the stale comment above `mutate_execute` that says "Standard-access write credential" to "the write credential (.env.gaw) — its account and access level are recorded in the latest security review (D3.2)".

- [ ] **Step 4: Rebuild to prove the pin is stable, and run everything**

Run: `python3 bin/build-app-package.py --project claude_google_ads --repo ~/Projects/claude-google-ads --commit <commit> --out-dir security-reviews/pkg2 | grep sha256` — Expected: the same sha256 (adding `commit`/`sha256` does not change the file list).
Run: `cd bin && ./run-bin-tests.sh 2>&1 | tail -1` — Expected: `38/38`.

- [ ] **Step 5: Commit** (the package files stay in the ignored `security-reviews/`)

```bash
git add infra/hermes-agent/registry/projects.yaml infra/hermes-agent/bin/registry-invariants.test.py
git commit -m "feat(hermes): pin claude_google_ads to its app package (commit <commit12>, sha256 <sha12>)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Part B — Operator steps after merge (not implementer tasks)

These run on the box and the laptop, in this order (spec §7). The kill switch stays absent; the WRITE credential stays off the box until step 5.

1. **Pull on the box:** `cd /opt/projects/claude_code && sudo git pull --ff-only`.
2. **Install the package:** copy `security-reviews/pkg/claude_google_ads-<commit12>.{tar,manifest.json}` to `~` on the box with `scp`, then
   `sudo python3 bin/install-app-package.py --project claude_google_ads --package ~/claude_google_ads-<c12>.tar --manifest ~/claude_google_ads-<c12>.manifest.json --target /opt/projects/claude-google-ads`, then remove the two copies from `~`.
3. **Collect:** box — `sudo python3 bin/collect-review-evidence.py > ~/bundle-box.json`, copy it to the laptop's `infra/hermes-agent/security-reviews/`, delete it from the box. Laptop — `python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --package-project claude_google_ads --package-repo ~/Projects/claude-google-ads --package-commit <commit> > security-reviews/bundle-laptop.json`. (With the credential off the box, D2.1 shows no credential rows; D3.1 still measures from the laptop.)
4. **Review:** start a fresh session with only `deploy/security-review/REVIEWER-BRIEF.md`, `CHECKLIST.md`, both bundles and the findings doc. It writes `docs/security-reviews/<date>-review.md`. The operator completes the sign-off (D3.2, D8, D9) and lands it by PR; a brain decision records the verdict.
5. **If PASS:** reinstall the WRITE credential the #64 way; `--credentials-only` must equal the report's authorised set, `--fingerprint-only` its box fingerprint, and the laptop `--access-digest` its digest; `MUTATOR_OK`; then re-run the live gate from a **fresh** change-set (BRING-UP "Live gate").
6. **If NOT PASS:** fix by PR, collect again, review again. Keep every report.

---

## Self-Review (done while writing)

- **Spec coverage.** §3 D1-D9 → Task 9 items, each box/laptop item a probe in Tasks 7/8. §4 flow → Tasks 7-9, Part B. §4.4 evidence out of git → Task 10 Step 1. §5.1 three-part fingerprint → Task 7 (`box_fingerprint`, `--credentials-only`), Task 8 (`--access-digest`), credentials excluded from the box part (test `test_credentials_are_not_part_of_the_box_fingerprint`). §5.3 enforcement → Task 10 Step 2. §6.1-§6.4 → Tasks 1-4, 11. §6.5 guard 7 incl. undo → Task 5. §7 order → Part B. §8 testing → each task's Step 1; the suite count is pinned (31 → 34 → 38).
- **Placeholders.** None, except operator-supplied values in Task 11 / Part B (`<commit>`, `$CUST`), which are by design not the implementer's to choose.
- **Type consistency.** `read_package(...) -> {"commit","sha256","include"}` used by `package_file_list`, `install.verify`, guard 7 and `d6_1`. `pin_workdir(workdir, project, files) -> sha256` used in Tasks 2 and 5. `Redactor.obj/text`, `credential_set`, `fingerprint` used as defined in Task 6. `collect()` returns the bundle only; `collect_with_secrets()` is the CLI's.
- **Review Focus.** CRLF/quotes → Task 6 `test_crlf_and_quotes_fingerprint_identically`. Missing clients.json → Task 7 `test_missing_clients_json_refuses_to_print`. Gateway down → Task 7 `test_gateway_not_running_is_could_not_check`. Symlinked target → Task 4 `test_symlinked_target_refused`. Foreign output naming a client → Task 7 `test_foreign_tool_output_is_redacted`.
