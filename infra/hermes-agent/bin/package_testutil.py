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
