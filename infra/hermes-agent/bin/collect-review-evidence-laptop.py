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

The audit runs in a Docker container ON THE LAPTOP. Before it, a pre-flight asks the Docker
daemon (`docker info`, its output discarded, at most DOCKER_INFO_TIMEOUT seconds). Found
2026-10-14: with Docker Desktop off the collector used to exit 0 with D3.1 could-not-check.

Exit codes, bundle mode:
  exit 0  the bundle is written and D3.1 is observed (D6.3 without --package-* arguments is
          could-not-check and does not change the exit code)
  exit 1  --customer is not digits
  exit 2  the review key cannot be used, or the output file cannot be made owner-only;
          nothing written (argparse's own usage errors are 2 as well)
  exit 3  Docker is not reachable: one stderr line names the cause and the fix; the audit
          does not run and nothing is written
  exit 4  the bundle IS written, but D3.1 is could-not-check (the audit gave no document):
          one stderr line says so; do not use that bundle
--access-digest: exit 0 with the digest on stdout; otherwise exit 2 with `could-not-check` (or
the digest of an audit that did not exit 0) on stdout and one stderr line saying why — Docker
not reachable, no audit document, or the audit's own non-zero exit code.
"""
import argparse, hashlib, importlib.util, json, os, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

AUDIT_SH = os.path.join(os.path.dirname(HERE), "audit-credential-access.sh")
PROG = "collect-review-evidence-laptop"
DOCKER_INFO_TIMEOUT = 15            # seconds; Docker Desktop answers in well under that once up
EXIT_DOCKER_DOWN = 3                # nothing written
EXIT_D31_INCOMPLETE = 4             # bundle written, D3.1 could-not-check


def docker_problem(timeout=DOCKER_INFO_TIMEOUT):
    """None when the Docker daemon answers `docker info`; otherwise a fixed reason. Docker's own
    output is discarded, never relayed: only these fixed words are ever printed."""
    try:
        p = subprocess.run(["docker", "info"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=timeout)
    except FileNotFoundError:
        return "the docker command was not found"
    except subprocess.TimeoutExpired:
        return f"Docker did not answer within {timeout}s"
    except OSError:
        return "the docker command could not be started"
    return None if p.returncode == 0 else "Docker is not running"


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


def run_audit(customer, fp_key=None):
    p = subprocess.run([AUDIT_SH, "--all", "--customer", customer], capture_output=True, text=True)
    red = R.Redactor([], [customer], fp_key=fp_key)
    try:
        rows = parse_audit(p.stdout)
        return red.obj({"rc": p.returncode, "rows": rows, "digest": access_digest(rows),
                        "stderr_lines_discarded": len(p.stderr.splitlines())})
    except ValueError as e:
        return {"rc": p.returncode, R.COULD_NOT_CHECK: str(e),
                "stderr_lines_discarded": len(p.stderr.splitlines())}


def package_hash(project, repo, commit, projects=None):
    spec = importlib.util.spec_from_file_location("build_app_package", os.path.join(HERE, "build-app-package.py"))
    B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
    if projects is None:
        projects = B.DEFAULT_PROJECTS
    # E2 (final-review): B.build() writes a real .tar and .manifest.json into this
    # directory — only their hash/count is wanted here, so build into a
    # TemporaryDirectory and let it clean itself up rather than leaking one
    # mkdtemp() per D6.3 evidence collection.
    with tempfile.TemporaryDirectory() as scratch:
        out = B.build(project, repo, commit, projects, scratch)
        return {"project": project, "commit": commit, "sha256": out["sha256"], "files": out["files"]}


ITEMS = {"D3.1": run_audit, "D6.3": package_hash}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--customer", required=True)
    ap.add_argument("--access-digest", action="store_true")
    ap.add_argument("--package-project"); ap.add_argument("--package-repo"); ap.add_argument("--package-commit")
    ap.add_argument("--fp-key-file", default=os.path.expanduser("~/.config/hermes-review/fp.key"))
    a = ap.parse_args(argv)
    if not a.customer.isdigit():
        print("collect-review-evidence-laptop: --customer must be digits", file=sys.stderr)
        return 1
    key = None
    if not a.access_digest:                                  # the digest carries no cids
        try:
            with open(a.fp_key_file) as f:
                mode = stat.S_IMODE(os.fstat(f.fileno()).st_mode)
                if mode & 0o077:                                 # spec §8: the key file is 0600
                    raise ValueError(f"{a.fp_key_file} is mode {mode:04o}; it must be 0600 "
                                     "(no group or other access): chmod 600 it")
                key = R.load_fp_key(f.read())
        except (OSError, ValueError) as e:
            print(f"collect-review-evidence-laptop: cannot use the review key: {e}", file=sys.stderr)
            return 2
    problem = docker_problem()
    if problem:
        print(f"{PROG}: {problem}: start Docker Desktop, then re-run (D3.1 runs the credential audit "
              f"in a Docker container); the audit did not run"
              + ("" if a.access_digest else ", nothing written"), file=sys.stderr)
        if a.access_digest:
            print(R.COULD_NOT_CHECK)                         # stdout as before: a digest or this word
            return 2
        return EXIT_DOCKER_DOWN
    audit = run_audit(a.customer, key)
    if a.access_digest:
        print(audit.get("digest", R.COULD_NOT_CHECK))
        if "digest" not in audit:
            print(f"{PROG}: no access digest: D3.1 could not be checked: {audit[R.COULD_NOT_CHECK]} "
                  f"(the audit exited {audit['rc']})", file=sys.stderr)
            return 2
        if audit["rc"] != 0:
            print(f"{PROG}: the audit exited {audit['rc']}, not 0: this digest does not certify the access "
                  "(3 = a declared role and its measured access disagree)", file=sys.stderr)
            return 2
        return 0
    items = {"D3.1": {"status": R.OBSERVED if "digest" in audit else R.COULD_NOT_CHECK, "data": audit}}
    if a.package_project and a.package_repo and a.package_commit:
        try:
            items["D6.3"] = {"status": R.OBSERVED,
                             "data": package_hash(a.package_project, a.package_repo, a.package_commit)}
        except (ValueError, OSError) as e:
            items["D6.3"] = {"status": R.COULD_NOT_CHECK, "reason": str(e)}
    else:
        items["D6.3"] = {"status": R.COULD_NOT_CHECK, "reason": "no --package-* arguments"}
    if not R.restrict_output(sys.stdout):
        print("collect-review-evidence-laptop: the output file could not be made owner-only: nothing written",
              file=sys.stderr)
        return 2
    print(json.dumps({"schema": 1, "kind": "laptop", "collected_at": R.utc_now(),
                      "cid_fingerprint": "hmac-sha256/12", "cid_key_id": R.key_id(key), "items": items}, indent=2, sort_keys=True))
    if "digest" not in audit:                                # written, as the evidence; but never quietly
        print(f"{PROG}: D3.1 could not be checked: {audit[R.COULD_NOT_CHECK]} (the audit exited {audit['rc']}); "
              "the bundle is incomplete: do not use it; is Docker Desktop running? fix the cause and collect again",
              file=sys.stderr)
        return EXIT_D31_INCOMPLETE
    return 0


if __name__ == "__main__":
    sys.exit(main())
