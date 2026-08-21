#!/usr/bin/env python3
"""Path contract for the host-owned governance store. Stdlib-only.

Everything the mutation guards TRUST lives here, and nothing Hermes can write does.
The gateway container does not mount this tree at all. The one-shot executor mounts
approvals/, control/ and registry/ READ-ONLY and log/ + seen/ read-write.

This module is deliberately the bottom of the dependency graph — it imports nothing
from bin/ — so it can own the shared identifier regexes instead of leaving duplicates
in changeset_lib and vault_lib to drift apart.

Root resolution mirrors vault_lib.vault_root(): a container default that host callers
override with HERMES_GOVERNANCE_ROOT.
"""
import os, re

DEFAULT_ROOT = "/opt/governance"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CHANGESET_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")


def governance_root():
    return os.environ.get("HERMES_GOVERNANCE_ROOT", DEFAULT_ROOT)


def _slug(s):
    # fullmatch, not match: "acme\n" must not pass as "acme".
    if not isinstance(s, str) or not SLUG_RE.fullmatch(s):
        raise ValueError("invalid client slug: %r" % (s,))
    return s


def _cid(c):
    if not isinstance(c, str) or not CHANGESET_ID_RE.fullmatch(c):
        raise ValueError("invalid changeset id: %r" % (c,))
    return c


def _root(root):
    return root or governance_root()


def kill_switch_path(root=None):
    return os.path.join(_root(root), "control", "mutation-enabled")


def clients_registry_path(root=None):
    return os.path.join(_root(root), "registry", "clients.json")


def approvals_dir(slug, root=None):
    return os.path.join(_root(root), "approvals", _slug(slug))


def approval_path(slug, cid, root=None):
    return os.path.join(approvals_dir(slug, root), "%s.approval.json" % _cid(cid))


def snapshot_path(slug, cid, root=None):
    return os.path.join(approvals_dir(slug, root), "%s.changeset.json" % _cid(cid))


def log_path(slug, root=None):
    return os.path.join(_root(root), "log", "%s.jsonl" % _slug(slug))


def seen_path(slug, root=None):
    return os.path.join(_root(root), "seen", "%s.jsonl" % _slug(slug))
