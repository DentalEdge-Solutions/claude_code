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
                key = R.load_fp_key(f.read())
        except (OSError, ValueError) as e:
            print(f"collect-review-evidence-laptop: cannot use the review key: {e}", file=sys.stderr)
            return 2
    audit = run_audit(a.customer, key)
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
    print(json.dumps({"schema": 1, "kind": "laptop", "collected_at": R.utc_now(),
                      "cid_fingerprint": "hmac-sha256/12", "cid_key_id": R.key_id(key), "items": items}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
