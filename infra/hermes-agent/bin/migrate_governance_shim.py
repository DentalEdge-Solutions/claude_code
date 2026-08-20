#!/usr/bin/env python3
"""Move mutation-governance state out of the read-write vault into the host-owned
governance store. Stdlib-only, idempotent, and count-verified.

Count verification is the point. Moving the audit log without carrying its records
resets the daily caps to zero — a guard that reads as green while measuring nothing.
"""
import json, os, shutil


def _count_lines(path):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return len([x for x in f.read().splitlines() if x.strip()])


def migrate(vault_root, governance_root, dry_run=False):
    result = {"moved": [], "skipped": [], "counts_before": {}, "counts_after": {}}

    src_reg = os.path.join(vault_root, "_registry", "clients.json")
    dst_reg = os.path.join(governance_root, "registry", "clients.json")
    if os.path.isfile(src_reg) and not os.path.isfile(dst_reg):
        if not dry_run:
            os.makedirs(os.path.dirname(dst_reg), exist_ok=True)
            shutil.copy2(src_reg, dst_reg)
        result["moved"].append("registry")
    elif os.path.isfile(dst_reg):
        result["skipped"].append("registry")

    src_switch = os.path.join(vault_root, "_governance", "mutation-enabled")
    if os.path.isfile(src_switch):
        # Deliberately NOT copied. The safe state is disabled, and a migration that
        # silently re-enables mutation in a new location is exactly the class of
        # surprise this whole increment exists to remove.
        result["skipped"].append("kill-switch (left disabled by design)")

    for slug in sorted(os.listdir(vault_root)):
        if slug.startswith("_"):
            continue
        src_log = os.path.join(vault_root, slug, "changes", "log.jsonl")
        if not os.path.isfile(src_log):
            continue
        dst_log = os.path.join(governance_root, "log", "%s.jsonl" % slug)
        if os.path.isfile(dst_log):
            result["skipped"].append(slug)
            continue
        before = _count_lines(src_log)
        result["counts_before"][slug] = before
        if dry_run:
            continue
        os.makedirs(os.path.dirname(dst_log), exist_ok=True)
        shutil.copy2(src_log, dst_log)
        after = _count_lines(dst_log)
        result["counts_after"][slug] = after
        if after != before:
            raise RuntimeError(
                "migration lost records for %r: %d before, %d after — refusing to "
                "continue, because a short log silently resets the daily caps"
                % (slug, before, after))
        result["moved"].append(slug)

    return result
