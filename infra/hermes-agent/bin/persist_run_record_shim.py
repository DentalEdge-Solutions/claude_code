#!/usr/bin/env python3
"""Persist an executor run record into the client vault. Stdlib-only.

The executor runs in a one-shot container that deliberately does not mount the vault,
so it emits its result on stdout and the CALLER persists it. The audit log in the
governance store remains the reversibility record and is written by the executor,
fsynced per action; result.json and timeline.md are convenience artifacts for humans
and for Hermes. If this step is lost, the audit log still holds the truth and --undo
still works.
"""
import json, os

MARKER = "HERMES-RESULT-JSON "


def parse_result(text):
    """Return the LAST marker line's payload, or None. The marker must start the line —
    a substring anywhere in prose is not a result."""
    found = None
    for line in text.splitlines():
        if line.startswith(MARKER):
            try:
                found = json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                continue
    return found


def persist(vault, result):
    os.makedirs(vault, exist_ok=True)
    path = os.path.join(vault, "%s.result.json" % result["changeset_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(os.path.join(vault, "timeline.md"), "a", encoding="utf-8") as f:
        f.write("- %s  change-set `%s`  status=%s  actions=%s\n"
                % (result.get("finished_at", ""), result["changeset_id"],
                   result.get("status", "?"), result.get("applied", "?")))
    return path
