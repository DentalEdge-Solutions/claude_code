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
