#!/usr/bin/env python3
"""Move client data out of the gateway's data/ (Option B §4). Stdlib only. Run as root, gateway stopped.

  sudo python3 bin/migrate-client-data.py [--agent-dir /opt/hermes-agent] [--dest-root /var/lib/hermes] [--apply]

vaults/<client>/ is copied to <dest>/vaults/<client>/ with owner, mode and mtime preserved, then
every file is re-hashed at the destination; only when all match are data/vaults and data/reports
removed (reports are per run and rebuilt by the next audit, so they are not copied).
Exit: 0 done; 1 copy/verify failed or the source changed (source intact: remove the listed
destination dirs and re-run); 2 refused before copying; 3 copies verified but removing the source
failed (keep the destination; finish removing data/vaults and data/reports by hand). A symlink
anywhere in the source, an existing destination client dir, or a destination parent that is
not root 0711 refuses before anything is copied. The source is owned by the gateway and is
treated as hostile: every source file is opened O_NOFOLLOW and checked (regular file, same
inode as when walked) at open time. Never prints file contents."""
import argparse, hashlib, os, shutil, stat, sys

ROOT_UID = 0


class Refused(Exception):
    pass


def _sha256(path):
    """Hash a regular file, never following a symlink at the final component."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        h = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            h.update(chunk)
        return h.hexdigest()
    finally:
        os.close(fd)


def _onerror(e):
    raise Refused(f"cannot read the source tree: {e.filename and os.path.basename(e.filename)} ({e.strerror})")


def _signature(entries):
    """Comparable identity of a walked tree: dirs by inode, files by inode+size+mtime."""
    return {(rel, st.st_dev, st.st_ino,
             None if stat.S_ISDIR(st.st_mode) else st.st_size,
             None if stat.S_ISDIR(st.st_mode) else st.st_mtime_ns) for rel, st in entries}


def _walk(src):
    """(relpath, lstat) for every entry below src; a symlink anywhere refuses."""
    out = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False, onerror=_onerror):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                raise Refused(f"symlink in the source: {os.path.relpath(p, src)}")
            if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise Refused(f"not a file or directory: {os.path.relpath(p, src)}")
            out.append((os.path.relpath(p, src), st))
    return out


def _check_parent(p):
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        raise Refused(f"{p} is missing; create it root:root 0711 first")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) \
            or st.st_uid != ROOT_UID or stat.S_IMODE(st.st_mode) != 0o711:
        raise Refused(f"{p} must be a root-owned 0711 directory")


def _same(a, b):
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _copy_file(s, d, est):
    """Copy one regular file; refuses if s is not (still) the regular file that was walked.
    Returns (size, sha256 of the bytes read from the source)."""
    try:
        sfd = os.open(s, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise Refused(f"cannot open source file safely: {os.path.basename(s)} ({e.strerror})")
    try:
        sst = os.fstat(sfd)
        if not stat.S_ISREG(sst.st_mode) or not _same(sst, est):
            raise Refused(f"source file changed since it was walked: {os.path.basename(s)}")
        dfd = os.open(d, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            h, n = hashlib.sha256(), 0
            while True:
                chunk = os.read(sfd, 1 << 16)
                if not chunk:
                    break
                h.update(chunk); n += len(chunk)
                while chunk:
                    chunk = chunk[os.write(dfd, chunk):]
            os.fchown(dfd, sst.st_uid, sst.st_gid)
            os.fchmod(dfd, stat.S_IMODE(sst.st_mode))
            os.utime(dfd, ns=(sst.st_atime_ns, sst.st_mtime_ns))
            return n, h.hexdigest()
        finally:
            os.close(dfd)
    finally:
        os.close(sfd)


def _copy_client(src, dst, entries):
    """Returns {relpath: (size, sha256)} for the files copied."""
    st = os.lstat(src)
    os.mkdir(dst, 0o700)
    seen = {}
    for rel, est in entries:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if stat.S_ISDIR(est.st_mode):
            cur = os.lstat(s)
            if not stat.S_ISDIR(cur.st_mode) or not _same(cur, est):
                raise Refused(f"source directory changed since it was walked: {rel}")
            os.mkdir(d, 0o700)
        else:
            seen[rel] = _copy_file(s, d, est)
    # Deepest first and the client dir LAST: until then dst stays root's 0700, so nobody else can
    # swap a name below it while these path-based calls run (owner/mode/mtime of each dir would
    # otherwise be applied under a dir already handed to uid 10000).
    dirs = sorted((e for e in entries if stat.S_ISDIR(e[1].st_mode)),
                  key=lambda e: -e[0].count(os.sep)) + [("", st)]
    for rel, est in dirs:
        d = os.path.join(dst, rel) if rel else dst
        os.chown(d, est.st_uid, est.st_gid, follow_symlinks=False)
        os.chmod(d, stat.S_IMODE(est.st_mode))
        os.utime(d, ns=(est.st_atime_ns, est.st_mtime_ns))
    return seen


def _no_link(p):
    if os.path.lexists(p) and stat.S_ISLNK(os.lstat(p).st_mode):
        raise Refused(f"{p} is a symlink")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent-dir", default="/opt/hermes-agent")
    ap.add_argument("--dest-root", default="/var/lib/hermes")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    agent = os.path.realpath(a.agent_dir)
    src_vaults = os.path.join(agent, "data", "vaults")
    src_reports = os.path.join(agent, "data", "reports")
    dst_vaults = os.path.join(a.dest_root, "vaults")
    try:
        _check_parent(dst_vaults)
        _check_parent(os.path.join(a.dest_root, "reports"))
        _no_link(os.path.join(agent, "data")); _no_link(src_vaults); _no_link(src_reports)
        clients = sorted(os.listdir(src_vaults)) if os.path.isdir(src_vaults) else []
        plan = []
        for c in clients:
            src = os.path.join(src_vaults, c)
            cst = os.lstat(src)
            if stat.S_ISLNK(cst.st_mode):
                raise Refused(f"vault {c!r} is a symlink")
            if not stat.S_ISDIR(cst.st_mode):
                raise Refused(f"vault {c!r} is not a directory")
            if os.path.lexists(os.path.join(dst_vaults, c)):
                raise Refused(f"destination vault for {c!r} already exists")
            plan.append((c, src, _walk(src)))
        if os.path.lexists(src_reports):
            _walk(src_reports)
    except (Refused, OSError) as e:
        print(f"migrate-client-data: refused: {e}", file=sys.stderr)
        return 2
    for c, _, entries in plan:
        files = sum(1 for _, st in entries if stat.S_ISREG(st.st_mode))
        print(f"vault {c}: {files} file(s) -> {dst_vaults}/{c}")
    print(f"reports: {'remove ' + src_reports if os.path.lexists(src_reports) else 'none'}")
    if not a.apply:
        print("dry run: nothing changed (re-run with --apply)")
        return 0
    created, copied = [], {}
    try:
        for c, src, entries in plan:
            created.append(os.path.join(dst_vaults, c))
            copied[c] = _copy_client(src, created[-1], entries)
    except (Refused, OSError) as e:
        return _fail(f"copy failed: {e}", created)
    bad = []
    for c, src, entries in plan:
        for rel, st in entries:
            if stat.S_ISREG(st.st_mode):
                d = os.path.join(dst_vaults, c, rel)
                size, digest = copied[c][rel]
                try:
                    dst_st = os.lstat(d)
                    ok = (stat.S_ISREG(dst_st.st_mode) and dst_st.st_size == size
                          and _sha256(d) == digest)
                except OSError:
                    ok = False
                if not ok:
                    bad.append(f"{c}/{rel}")
    if bad:
        return _fail(f"VERIFY FAILED for {len(bad)} file(s): " + ", ".join(bad), created)
    # Removal is gated on the source still being exactly the verified set.
    try:
        changed = []
        if sorted(os.listdir(src_vaults)) != clients:
            changed.append("(client list)")
        for c, src, entries in plan:
            if _signature(_walk(src)) != _signature(entries):
                changed.append(c)
    except (Refused, OSError) as e:
        changed = [f"(re-walk failed: {e})"]
    if changed:
        return _fail("the source changed after it was walked (" + ", ".join(changed) +
                     f"); nothing removed, re-run after the gateway is really stopped", created)
    try:
        for tree in (src_vaults, src_reports):
            if os.path.lexists(tree):
                shutil.rmtree(tree)
    except OSError as e:
        print(f"migrate-client-data: copies verified; removing the source failed ({e.strerror or e}). "
              f"DO NOT remove the destination: it may now be the only full copy. Finish removing "
              f"data/vaults and data/reports by hand", file=sys.stderr)
        return 3
    print("migrate-client-data: done; data/vaults and data/reports removed")
    return 0


def _fail(msg, created):
    print(f"migrate-client-data: {msg}; the source is intact. Destination dirs created by "
          f"this run (remove each, then re-run):", file=sys.stderr)
    for p in created:
        print(f"  {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
