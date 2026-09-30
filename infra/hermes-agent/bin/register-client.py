#!/usr/bin/env python3
"""Register a spending client in the governance registry, atomically.

    sudo python3 bin/register-client.py --slug <client> --fingerprint <12hex> [--registry PATH]

The customer id is read from /root/.cid (one line of digits, written by BRING-UP "Ads audits on
the box" step 5 part A), never from argv. The tool refuses, with one line and no traceback, and
never prints the id, when: the current registry is missing, empty, unparsable or lacks a
`clients` object; the slug or the id is already registered; the slug is malformed; or the id does
not match --fingerprint (sha1(id)[:12]). On 2026-09-29 an ad-hoc paste installed an EMPTY registry:
this tool never starts from an empty file, and swaps the new one in with os.replace only after
re-parsing it. The new entry has no mutation_target: the dormant pilot stays the only one.
"""
import argparse, grp, hashlib, json, os, re, sys

DEFAULT_REGISTRY = "/var/lib/hermes/governance/registry/clients.json"
DEFAULT_CID_FILE = "/root/.cid"
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class Refused(Exception):
    pass


def load_clients(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise Refused(f"registry unreadable ({type(e).__name__}): nothing changed")
    if not raw.strip():
        raise Refused("registry is empty: nothing changed")
    try:
        d = json.loads(raw)
    except ValueError:
        raise Refused("registry does not parse: nothing changed")
    if not isinstance(d, dict) or not isinstance(d.get("clients"), dict):
        raise Refused("registry has no 'clients' object: nothing changed")
    return d


def read_cid(path):
    try:
        with open(path) as f:
            cid = f.read().strip()
    except OSError as e:
        raise Refused(f"customer id file unreadable ({type(e).__name__})")
    if not re.fullmatch(r"\d{10}", cid):
        raise Refused("customer id file does not hold a 10-digit id")
    return cid


def register(slug, fingerprint, registry, cid_file):
    if not SLUG_RE.fullmatch(slug):
        raise Refused("bad slug")
    cid = read_cid(cid_file)
    if hashlib.sha1(cid.encode()).hexdigest()[:12] != fingerprint:
        raise Refused("id does not match its fingerprint")
    d = load_clients(registry)
    c = d["clients"]
    if slug in c:
        raise Refused("slug already registered")
    if any(isinstance(v, dict) and v.get("customer_id") == cid for v in c.values()):
        raise Refused("customer id already registered")
    before = len(c)
    c[slug] = {"project": "claude_google_ads", "customer_id": cid, "currency": "USD",
               "timezone": "America/New_York", "status": "active"}
    tmp = registry + ".new"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # holds customer ids: never world-readable
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        with open(tmp) as f:
            after = json.load(f)["clients"]
        if len(after) != before + 1:
            raise Refused("new registry failed its own check: nothing changed")
        if os.geteuid() == 0:
            os.chown(tmp, 0, grp.getgrnam("hermes").gr_gid)
        os.chmod(tmp, 0o640)
        os.replace(tmp, registry)                  # atomic: the old file stays until the new one is complete
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return summary(registry)


def summary(registry):
    """`N [statuses] pilots`. Runs AFTER the swap, so it must never raise or claim nothing changed."""
    try:
        with open(registry) as f:
            vs = [v for v in json.load(f)["clients"].values() if isinstance(v, dict)]
        return "%d %s %d" % (len(vs), sorted(str(v.get("status")) for v in vs),
                             sum(v.get("mutation_target") == "dormant_pilot" for v in vs))
    except (OSError, KeyError, ValueError, AttributeError):
        return "registered (summary unavailable)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--cid-file", default=DEFAULT_CID_FILE)
    a = ap.parse_args(argv)
    try:
        print(register(a.slug, a.fingerprint, a.registry, a.cid_file))
    except Refused as e:
        print(f"register-client: refused: {e}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError) as e:
        print(f"register-client: failed ({type(e).__name__}): nothing changed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
