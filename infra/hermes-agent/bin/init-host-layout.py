#!/usr/bin/env python3
"""Create or verify the governance store and spool layout on a Linux host (F10).

Operator-run, host-side, the same governed-operator-CLI pattern as
`migrate-governance.py --bootstrap-logs` (ruling R23):

    init-host-layout.py            dry run: print what would be created (the default)
    init-host-layout.py --apply    create what is missing (root only; refuses on
                                   anything that exists and is wrong — never repairs)
    init-host-layout.py --check    verify only; the broker unit's first ExecStartPre

Exit 0 ok · 1 usage · 2 refusal or drift. The layout itself is bin/host_layout.py.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_layout as H

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2


def main(argv=None, resolver_factory=None, ancestor_uids=(0,), ancestor_top="/",
         geteuid=os.geteuid):
    ap = argparse.ArgumentParser(
        prog="init-host-layout",
        description="Create or verify the governance store and spool layout.")
    ap.add_argument("--store-root", default=H.DEFAULT_STORE_ROOT)
    ap.add_argument("--spool-root", default=H.DEFAULT_SPOOL_ROOT)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="create what is missing (root only)")
    mode.add_argument("--check", action="store_true", help="verify only")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:                  # argparse exits 2; usage here is 1
        return EXIT_OK if e.code == 0 else EXIT_USAGE
    kw = dict(ancestor_uids=ancestor_uids, ancestor_top=ancestor_top)
    try:
        resolver = (resolver_factory or H.system_resolver)()
        if args.apply:
            for p in H.apply(args.store_root, args.spool_root, resolver,
                             geteuid=geteuid, **kw):
                print("created  %s" % p)
        if args.apply or args.check:
            problems = H.check(args.store_root, args.spool_root, resolver, **kw)
            if problems:
                print("init-host-layout: the layout does not match (this tool never "
                      "repairs — set each path to the expected state by hand):",
                      file=sys.stderr)
                for p in problems:
                    print("  - %s" % p, file=sys.stderr)
                return EXIT_REFUSED
            print("init-host-layout: layout OK")
            return EXIT_OK
        steps = H.plan(args.store_root, args.spool_root, resolver, **kw)
        for s in steps:
            print("%-8s %s%s" % (s.action, s.path, "  " + s.detail if s.detail else ""))
        return EXIT_REFUSED if any(s.action == "mismatch" for s in steps) else EXIT_OK
    except (H.LayoutError, OSError) as e:
        print("init-host-layout: %s" % e, file=sys.stderr)
        for note in getattr(e, "__notes__", ()):
            print("init-host-layout: %s" % note, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
