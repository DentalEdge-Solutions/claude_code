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


_CLIENT_ID_RE = re.compile(rb"(?<!\d)\d{3}-?\d{3}-?\d{4}(?!\d)")


def refuse_client_ids(files):
    """A packaged DOC must never carry a customer-id-shaped number: the package is built from
    the ads repo, where past client deliverables sit beside the generic SOPs (spec 2026-09-29
    ads-audits-on-the-box §9). Code is exempt (it may hold the MCC id in a constant).
    Raises ValueError naming the file, never the match."""
    bad = sorted(p for p, b in files.items() if p.endswith(".md") and _CLIENT_ID_RE.search(b))
    if bad:
        raise ValueError(f"refusing to package docs holding a customer-id-shaped number: {bad}")


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
    try:
        actual = sha256_file(os.path.join(workdir, rel_path))
    except FileNotFoundError:
        raise ValueError(f"{rel_path} is listed in the installed package manifest but missing on disk — refusing")
    if actual != entry["sha256"]:
        raise ValueError(f"{rel_path} does not match the installed package manifest "
                         f"(sha256 {actual[:12]} != {entry['sha256'][:12]}) — refusing")
