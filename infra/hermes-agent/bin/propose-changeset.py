#!/usr/bin/env python3
"""Validate an operator-authored actions file into a typed change-set in the client
vault. Stdlib-only. HOLDS NO CREDENTIAL and performs no network I/O — this command
is structurally incapable of touching the ad account.

The operator supplies ONLY the actions array. Identity fields (client, project,
customer_id) come from the client resolver, so an operator cannot typo a customer id
into a change-set, and the apply-time identity check becomes a tamper check.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib

ALLOWED_INPUT_FIELDS = {"actions"}


def propose(client, actions_file, now, registry=None, projects=None):
    rec = vault_lib.resolve(client, registry)          # validates slug + customer_id
    projects_path = projects or C.registry_projects_path()
    caps = C.read_mutate_execute(projects_path, rec["project"])["caps"]
    with open(actions_file, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("actions file must be a JSON object with an 'actions' key")
    extra = set(payload) - ALLOWED_INPUT_FIELDS
    if extra:
        raise ValueError(f"actions file may only contain 'actions'; identity fields are "
                         f"supplied by the resolver, not the operator (got {sorted(extra)})")
    cs = {
        "changeset_id": f"{now.strftime('%Y%m%d-%H%M%S')}-{os.urandom(4).hex()}",
        "client": rec["slug"],
        "project": rec["project"],
        "customer_id": rec["customer_id"],
        "created_at": now.strftime(C.ISO),
        "actions": payload.get("actions"),
    }
    C.validate_changeset(cs, caps["actions_per_changeset"])
    vault = rec["vault_path"]
    d = C.changes_dir(vault)
    os.makedirs(d, exist_ok=True)
    path = C.changeset_path(vault, cs["changeset_id"])
    with open(path, "wb") as f:                        # canonical bytes; hashed later
        f.write(C.canonical_bytes(cs))
        f.flush()
        os.fsync(f.fileno())
    # fsync the directory too, same as changeset_lib.append_log: this file is newly
    # created, and the approval step hashes it byte-for-byte. Losing the directory
    # entry that names it loses the artifact the whole approval rests on.
    dfd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return cs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--from", dest="actions_file", required=True)
    ap.add_argument("--registry", help="clients.json (default: <VAULT_ROOT>/_registry)")
    ap.add_argument("--projects", help="projects.yaml (default: /opt/registry or ../registry)")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    try:
        cs = propose(args.client, args.actions_file, now, args.registry, args.projects)
    except (ValueError, KeyError, OSError, TypeError) as e:   # JSONDecodeError IS a ValueError
        print(f"propose-changeset: {e}", file=sys.stderr)
        return 2
    # Do NOT re-resolve here. A second registry read after the change-set is already on
    # disk can raise for a transient reason and produce a traceback plus a non-2 exit for
    # an operation that SUCCEEDED, breaking the exit 0/2 contract. vault_path is by
    # definition <VAULT_ROOT>/<slug>, so the path needs no registry at all.
    vault = os.path.join(vault_lib.vault_root(), cs["client"])
    print(C.changeset_path(vault, cs["changeset_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
