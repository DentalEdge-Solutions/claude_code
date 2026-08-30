#!/usr/bin/env python3
"""Client-vault registry resolver + slug/id validation. Stdlib-only.

Reports, results and timelines stay on the Hermes volume: <VAULT_ROOT>/<slug>/...
(VAULT_ROOT defaults to /opt/data/vaults; host callers pass the host data/vaults
path) — that is `vault_root()` / `vault_path`, unchanged. The client registry
itself is CLIENT-PRIVATE and lives on the host-owned governance store; see
`registry_path()`. JSON (not YAML) to stay stdlib-only and avoid the
hand-parsed-YAML bug class (Inc-3 CRITICAL).

"Not client-private" is a PROPERTY THE WRITERS MUST MAINTAIN, not a fact about
this directory. It is not enforced here and cannot be: this module resolves
paths, it never inspects what is written to them. The vault is mounted rw into
the gateway, so every field any writer puts here is readable by the agent — and
S7 caught exactly that going wrong. apply-changeset.py's run record used to carry
the per-action `resource_name`, i.e. `customers/<resolved id>/...`, which put the
resolved customer id in the vault and silently reversed the 2026-08-19 decision
to move the client registry OUT of it. That is now withheld at the emitting end
(see EMITTED_ACTION_FIELDS there), and hermes-broker.py withholds the same class
of detail from the spool. Anything new written under here needs the same check
made deliberately; the storage location grants nothing.
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

# P7 (2026-08-30). Spec §13 requires the live gate to run "against the authorised dormant
# pilot client only ... never the live one", resolved PROGRAMMATICALLY and never hardcoded.
# The registry could not express that: every client carried status='active', which describes
# the engagement, not whether the client may be mutated in a test. So the spec asserted a
# safety property the data model had no way to represent, and the only way to pick a target
# was for a human or an agent to infer one — the exact guess that would put a live account
# one wrong inference away from a test mutation.
#
# `mutation_target: "dormant_pilot"` is that missing field. It is deliberately SEPARATE from
# `status`: a client can be an active engagement and still be the safe test target, or be
# inactive and still be off-limits. Absence means live — the fail-safe default, because a
# registry written before this field existed must never read as "safe to mutate".
MUTATION_TARGET_KEY = "mutation_target"
DORMANT_PILOT = "dormant_pilot"


def resolve_dormant_pilot(path=None):
    """The one client the live verification gate may mutate. Fail-closed BOTH ways.

    Zero matches raises, and so does MORE THAN ONE. A second dormant pilot is not a
    convenience, it is an ambiguity, and this function exists precisely so that nothing
    downstream ever resolves an ambiguity by picking. Callers get a client or an
    exception; there is no third outcome and no default.

    The error text deliberately names the FIELD and not the candidates: a message that
    listed the eligible slugs would print client-private identifiers into whatever log
    or terminal caught the refusal.
    """
    clients = load_registry(path)
    matches = sorted(
        slug for slug, rec in clients.items()
        if isinstance(rec, dict) and rec.get(MUTATION_TARGET_KEY) == DORMANT_PILOT
    )
    if not matches:
        raise ValueError(
            "no client is marked %s=%r in the registry. The live gate refuses to guess; "
            "mark exactly one client explicitly." % (MUTATION_TARGET_KEY, DORMANT_PILOT))
    if len(matches) > 1:
        raise ValueError(
            "%d clients are marked %s=%r; exactly one is required. Refusing to choose."
            % (len(matches), MUTATION_TARGET_KEY, DORMANT_PILOT))
    return resolve(matches[0], path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--client")
    g.add_argument("--dormant-pilot", action="store_true",
                   help="resolve the one client marked mutation_target=dormant_pilot")
    ap.add_argument("--field")
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        rec = (resolve_dormant_pilot(args.registry) if args.dormant_pilot
               else resolve(args.client, args.registry))
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
