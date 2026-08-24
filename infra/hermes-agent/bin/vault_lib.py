#!/usr/bin/env python3
"""Client-vault registry resolver + slug/id validation. Stdlib-only.

Reports, results and timelines are NOT client-private and stay on the Hermes
volume: <VAULT_ROOT>/<slug>/... (VAULT_ROOT defaults to /opt/data/vaults; host
callers pass the host data/vaults path) — that is `vault_root()` / `vault_path`,
unchanged. The client registry itself is CLIENT-PRIVATE and lives on the
host-owned governance store; see `registry_path()`. JSON (not YAML) to stay
stdlib-only and avoid the hand-parsed-YAML bug class (Inc-3 CRITICAL).
"""
import argparse, json, os, re, sys

import governance_lib

SLUG_RE = governance_lib.SLUG_RE      # one definition, shared, so the two cannot drift
CID_RE = re.compile(r"^[0-9]{1,15}$")

def vault_root():
    return os.environ.get("VAULT_ROOT", "/opt/data/vaults")

def registry_path():
    """The client registry is CLIENT-PRIVATE and moved into the host-owned governance
    store on 2026-08-19. It was previously under VAULT_ROOT, which is the container's
    one read-write mount — meaning Hermes could flip a dormant client to 'active'."""
    return governance_lib.clients_registry_path()

def validate_slug(slug):
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid client slug: {slug!r} (allowed ^[a-z0-9][a-z0-9_-]{{0,63}}$)")
    return slug

def validate_customer_id(cid):
    if not isinstance(cid, str) or not CID_RE.fullmatch(cid):
        raise ValueError(f"invalid customer_id: {cid!r} (digits only, no dashes)")
    return cid

def load_registry(path=None):
    path = path or registry_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"client registry not found: {path}")
    with open(path) as f:
        data = json.load(f)
    clients = data.get("clients", {})
    if not isinstance(clients, dict):
        raise ValueError("registry 'clients' must be a JSON object")
    return clients

def resolve(slug, path=None):
    validate_slug(slug)
    clients = load_registry(path)
    if slug not in clients:
        raise KeyError(f"unknown client slug: {slug!r}")
    rec = dict(clients[slug])
    customer_id = str(rec.get("customer_id", ""))
    validate_customer_id(customer_id)
    rec["customer_id"] = customer_id
    rec["slug"] = slug
    rec["vault_path"] = os.path.join(vault_root(), slug)
    return rec

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--field")
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        rec = resolve(args.client, args.registry)
    except (ValueError, KeyError, OSError, TypeError) as e:
        print(f"vault-lib: {e}", file=sys.stderr); return 2
    if args.field:
        if args.field not in rec:
            print(f"vault-lib: no field {args.field!r}", file=sys.stderr); return 2
        print(rec[args.field])
    else:
        print(json.dumps(rec, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
