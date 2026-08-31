#!/usr/bin/env python3
"""Record a hash-bound approval for a proposed change-set. Stdlib-only.
HOLDS NO CREDENTIAL and performs no network I/O.

The approval binds the sha256 of the exact change-set BYTES that were reviewed, plus
an expiry, and copies those bytes into the host-owned governance store — the snapshot
`apply` actually executes from. Editing the vault copy afterwards has no effect on what
runs, and editing the snapshot invalidates the approval, because the hash no longer
matches.

WHAT THIS DOES NOT CLOSE (spec §7, corrected 2026-08-20). The snapshot is taken HERE,
at approve time. It closes approve -> apply completely. It does NOT close
review -> approve: whatever is in the vault copy when this command runs is what gets
snapshotted and bound, so bytes written after the human read the change-set and before
the operator typed this command are what the approval binds. That is why this command
PRINTS the digest and one line per action: the printed summary is the operator's chance
to confirm that what is being bound is what was reviewed.

`--expect-sha256` is now the DEFAULT path (2026-08-24): omitting it refuses instead of
binding silently, printing the digest and one line per action first so the operator can
read what they are about to bind and re-run with a paste-ready value. This converts a
reading task into a mechanical confirmation — it does NOT make review -> approve
structurally closed. An operator who pastes the digest without reading the printed
summary above it has confirmed nothing. The real reason that window stays empty in v1
is a separate rule (spec §17.1: no model authors a change-set), not this flag. What this
removes is the silent default, not the human.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib


class ExpectShaRequired(Exception):
    """Not an error in the change-set — the operator has not yet confirmed the bytes.

    Carries everything needed to print a paste-ready next command, so the refusal is a
    step in the workflow rather than an obstacle to route around. A refusal an operator
    learns to bypass is worse than no refusal.
    """

    def __init__(self, digest, actions, changeset_id):
        super().__init__("confirmation required")
        self.digest, self.actions, self.changeset_id = digest, actions, changeset_id


def approve(client, changeset_id, operator, now, registry=None, projects=None,
            expect_sha256=None):
    """Snapshot and approve. Returns the approval record with two extra keys the CLI
    prints — `actions` (what is being bound) and `changeset` (the parsed change-set) —
    so the caller never has to re-read the file to describe what it approved."""
    if not C.CHANGESET_ID_RE.fullmatch(changeset_id or ""):
        raise ValueError(f"invalid --changeset: {changeset_id!r}")
    rec = vault_lib.resolve(client, registry)
    vault = rec["vault_path"]
    path = C.changeset_path(vault, changeset_id)
    if not os.path.isfile(path):
        raise ValueError(f"no change-set {changeset_id!r} for this client")
    caps = C.read_mutate_execute(projects or C.registry_projects_path(), rec["project"])["caps"]
    # ONE read. Everything below — validation, the identity check, the digest, the
    # snapshot and the printed summary — is derived from these exact bytes, so the
    # operator's confirmation and the executed artefact cannot describe different
    # content.
    with open(path, "rb") as f:
        data = f.read()
    cs = json.loads(data.decode("utf-8"))
    # Re-validate at approve time: never approve bytes that would be refused at apply.
    C.validate_changeset(cs, caps["actions_per_changeset"])
    if cs["client"] != rec["slug"] or cs["customer_id"] != rec["customer_id"]:
        raise ValueError("change-set identity does not match the resolved client")
    import hashlib
    actual = hashlib.sha256(data).hexdigest()
    if expect_sha256 is None:
        # The review -> approve window is not closed by the snapshot (spec §7). Making
        # --expect-sha256 the DEFAULT path turns the operator's confirmation into a
        # refusal rather than a reading task. It does not remove the human: an operator
        # who pastes without reading has confirmed nothing. What it removes is the
        # silent default, where the command bound whatever happened to be on disk.
        raise ExpectShaRequired(actual, cs["actions"], changeset_id)
    if not C.SHA256_RE.fullmatch(expect_sha256.strip().lower()):
        raise ValueError(f"invalid --expect-sha256: {expect_sha256!r}")
    if actual != expect_sha256.strip().lower():
        raise ValueError(
            f"--expect-sha256 mismatch: the change-set on disk hashes to {actual}, "
            f"not {expect_sha256.strip().lower()} — these are not the bytes you "
            "reviewed; re-read it before approving")
    digest = C.write_snapshot_bytes(rec["slug"], changeset_id, data)
    out = dict(C.write_approval(rec["slug"], changeset_id, digest, operator, now,
                                caps["approval_ttl_hours"]))
    out["actions"] = cs["actions"]
    out["changeset"] = cs
    return out


def summarise(rec):
    """One line per action, plus the digest the approval binds. This is what the
    operator confirms — the approval is only as good as the operator's ability to see
    what it covers."""
    lines = [f"approved {rec['changeset_id']} by {rec['operator']} "
             f"(expires {rec['expires_at']})",
             f"  sha256 {rec['sha256']}",
             f"  {len(rec['actions'])} action(s) bound by this approval:"]
    for i, a in enumerate(rec["actions"], 1):
        lines.append("    %d. %s  campaign %s  %s  %r"
                     % (i, a["type"], a["campaign_id"], a["match_type"], a["keyword"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--changeset", required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--registry")
    ap.add_argument("--projects")
    ap.add_argument("--expect-sha256", dest="expect_sha256",
                    help="required: refuse unless the change-set on disk hashes to "
                         "this value — binds the approval to the bytes you actually "
                         "reviewed. Omit it on a first attempt to see the digest and "
                         "action summary you need to build this value, then re-run "
                         "with it.")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    try:
        rec = approve(args.client, args.changeset, args.operator, now, args.registry,
                      args.projects, args.expect_sha256)
    except ExpectShaRequired as e:
        print("change-set %s binds these %d action(s):" % (e.changeset_id, len(e.actions)))
        for i, a in enumerate(e.actions, 1):
            print("    %d. %s  campaign %s  %s  %r"
                  % (i, a["type"], a["campaign_id"], a["match_type"], a["keyword"]))
        print("\n  sha256 %s" % e.digest)
        print("\nRead the actions above. If they are what you reviewed, re-run with:\n"
              "  --expect-sha256 %s" % e.digest, file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError,
            UnicodeDecodeError) as e:
        print(f"approve-changeset: {e}", file=sys.stderr)
        return 2
    print(summarise(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
