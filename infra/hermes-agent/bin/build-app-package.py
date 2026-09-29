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
