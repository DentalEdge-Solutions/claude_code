#!/usr/bin/env python3
"""CLI over migrate_governance_shim. Host-side, operator-run, dry-run by default."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance_lib
import migrate_governance_shim as M
import vault_lib


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-root", default=None)
    ap.add_argument("--governance-root", default=None)
    ap.add_argument("--bootstrap-logs", action="store_true",
                    help="pre-create a log for every REGISTERED client instead of "
                         "migrating; idempotent, and required after any hand-edit to "
                         "clients.json")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it this is a dry run")
    args = ap.parse_args(argv)
    gov = args.governance_root or governance_lib.governance_root()
    try:
        if args.bootstrap_logs:
            res = M.bootstrap_logs(gov, dry_run=not args.apply)
        else:
            res = M.migrate(args.vault_root or vault_lib.vault_root(), gov,
                            dry_run=not args.apply)
    except (OSError, RuntimeError) as e:
        print("migrate-governance: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
