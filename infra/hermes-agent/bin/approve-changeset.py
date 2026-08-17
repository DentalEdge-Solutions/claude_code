#!/usr/bin/env python3
"""Record a hash-bound approval for a proposed change-set. Stdlib-only.
HOLDS NO CREDENTIAL and performs no network I/O.

The approval binds the sha256 of the exact change-set BYTES that were reviewed, plus
an expiry. Editing the change-set afterwards — even by one whitespace byte —
invalidates the approval, because the hash no longer matches.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib


def approve(client, changeset_id, operator, now, registry=None, projects=None):
    if not C.CHANGESET_ID_RE.fullmatch(changeset_id or ""):
        raise ValueError(f"invalid --changeset: {changeset_id!r}")
    rec = vault_lib.resolve(client, registry)
    vault = rec["vault_path"]
    path = C.changeset_path(vault, changeset_id)
    if not os.path.isfile(path):
        raise ValueError(f"no change-set {changeset_id!r} for this client")
    caps = C.read_mutate_execute(projects or C.registry_projects_path(), rec["project"])["caps"]
    with open(path, encoding="utf-8") as f:
        cs = json.load(f)
    # Re-validate at approve time: never approve bytes that would be refused at apply.
    C.validate_changeset(cs, caps["actions_per_changeset"])
    if cs["client"] != rec["slug"] or cs["customer_id"] != rec["customer_id"]:
        raise ValueError("change-set identity does not match the resolved client")
    return C.write_approval(vault, changeset_id, C.file_digest(path), operator, now,
                            caps["approval_ttl_hours"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--changeset", required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--registry")
    ap.add_argument("--projects")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    try:
        rec = approve(args.client, args.changeset, args.operator, now, args.registry, args.projects)
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError) as e:
        print(f"approve-changeset: {e}", file=sys.stderr)
        return 2
    print(f"approved {rec['changeset_id']} by {rec['operator']} (expires {rec['expires_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
