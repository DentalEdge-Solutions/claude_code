#!/usr/bin/env python3
"""Retention/offboarding: export-then-hard-purge a client vault, audit-log the
deletion, flip registry status to offboarded. Stdlib-only. Export ALWAYS precedes
delete. Refuses an active client without --force, and refuses without --confirm."""
import argparse, getpass, json, os, shutil, sys, tarfile
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib

class PostPurgeError(Exception):
    """Raised when destruction (export+delete) succeeded but post-delete bookkeeping failed."""
    def __init__(self, tar_path, cause):
        self.tar_path = tar_path; self.cause = cause
        super().__init__(str(cause))

def _dir_bytes(path):
    total = 0
    for root,_,files in os.walk(path):
        for f in files: total += os.path.getsize(os.path.join(root,f))
    return total

def purge(client, export_to, confirm, force, registry=None):
    if not confirm:
        raise ValueError("refusing to purge without --confirm")
    rec = vault_lib.resolve(client, registry)
    if rec.get("status") == "active" and not force:
        raise ValueError(f"client {client!r} is active — pass --force to purge an active client")
    vault = rec["vault_path"]
    if not os.path.isdir(vault):
        raise FileNotFoundError(f"vault not found: {vault}")
    os.makedirs(export_to, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    tar_path = os.path.join(export_to, f"{client}-{ts}.tar.gz")
    nbytes = _dir_bytes(vault)
    with tarfile.open(tar_path, "w:gz") as tar:       # 1. EXPORT
        tar.add(vault, arcname=client)
    shutil.rmtree(vault)                               # 2. HARD DELETE (irreversible)
    try:
        gov = os.path.join(vault_lib.vault_root(), "_governance")
        os.makedirs(gov, exist_ok=True)
        with open(os.path.join(gov, "deletions.log"), "a") as f:   # 3. AUDIT LOG
            f.write(json.dumps({"slug": client, "ts": ts, "operator": getpass.getuser(),
                                "bytes_exported": nbytes, "export": tar_path}) + "\n")
        path = registry or vault_lib.registry_path()       # 4. STATUS FLIP (atomic)
        with open(path) as f:
            data = json.load(f)
        data["clients"][client]["status"] = "offboarded"
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        raise PostPurgeError(tar_path, e)
    return tar_path

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--export-to", required=True)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        tar = purge(args.client, args.export_to, args.confirm, args.force, args.registry)
    except PostPurgeError as e:
        print(f"vault-purge: WARNING — vault was EXPORTED to {e.tar_path} and DELETED, but "
              f"post-delete bookkeeping failed: {e.cause}. Complete the audit-log/status flip manually.",
              file=sys.stderr)
        return 3
    except (ValueError, KeyError, FileNotFoundError, OSError, TypeError, tarfile.TarError) as e:
        print(f"vault-purge: {e}", file=sys.stderr); return 2
    print(tar); return 0

if __name__ == "__main__":
    sys.exit(main())
