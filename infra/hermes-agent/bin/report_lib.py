#!/usr/bin/env python3
"""The figures-report store (design 2026-10-13, Part 1). Stdlib only.

A figures run's three reader reports are written by a container (uid 10000) into
/var/lib/hermes/reports/<client>/. Root joins them into ONE document and stores it in
/var/lib/hermes/report-archive/<client>/<ts>-report.md: a store no container mounts, so a report
never reaches the drafter of a later audit. Everything read here was written by a container: each
name is opened below its folder without following a link, must be a regular file, is size-capped,
and is copied, never parsed."""
import os, re, stat

import client_audit_lib as L
import governance_lib

ARCHIVE = "/var/lib/hermes/report-archive"
MAX_REPORT_BYTES = 5 * 1024 * 1024
ISOLATION_RC = 4          # report-store.py: the document names another client; nothing was stored
_READER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SLUG_RE = governance_lib.SLUG_RE          # the registry's own rule for a client's short name, never restated
_READER_FILE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}-([a-z][a-z0-9_]{0,63})\.md$")
_REPORT_NAME_RE = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})-report\.md$")


class ReportError(Exception):
    pass


def _read_one(dir_fd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReportError("a report is not a regular file")
        if st.st_size > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        data = os.read(fd, MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        return data.decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def read_reports(reports_base, slug, readers):
    """The joined document: one `## <reader>` section per reader, in `readers`' order. Exactly one
    file per reader, and nothing else in the folder, or ReportError. Reasons never hold a name."""
    if not _SLUG_RE.fullmatch(slug) or not readers or not all(_READER_RE.fullmatch(r) for r in readers):
        raise ReportError("invalid client or reader name")
    fd = L.open_dir_below(reports_base, (slug,))
    if fd is None:
        raise ReportError("the reports folder is missing")
    try:
        found = {}
        for name in sorted(os.listdir(fd)):
            m = _READER_FILE_RE.fullmatch(name)
            if m is None or m.group(1) not in readers:
                raise ReportError("an entry that is not one of this run's reports")
            if m.group(1) in found:
                raise ReportError("two reports for one reader")
            found[m.group(1)] = name
        if set(found) != set(readers):
            raise ReportError("a report is missing")
        return "".join(f"## {r}\n\n{_read_one(fd, found[r]).rstrip()}\n\n" for r in readers)
    finally:
        os.close(fd)


def _archive_fd(archive_base, owner_uid):
    st = os.lstat(archive_base)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) \
            or st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
        raise ReportError("the report store must be a real directory, owner-only")
    return os.open(archive_base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def store(archive_base, slug, ts, text, owner_uid=0):
    """Write the document as <archive>/<slug>/<ts>-report.md, 0600, never over an existing file.
    Returns the path below the archive. The client folder is created 0700 when missing."""
    if not _SLUG_RE.fullmatch(slug) or not L.TS_RE.fullmatch(ts):
        raise ReportError("invalid client name or timestamp")
    base = _archive_fd(archive_base, owner_uid)
    try:
        try:
            os.mkdir(slug, 0o700, dir_fd=base)
        except FileExistsError:
            pass
        cfd = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
    finally:
        os.close(base)
    try:
        st = os.fstat(cfd)
        if st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
            raise ReportError("the client's report folder must be owner-only")
        name, tmp = f"{ts}-report.md", f".{ts}-report.tmp"
        try:
            os.stat(name, dir_fd=cfd, follow_symlinks=False)
            raise ReportError("a report with this timestamp exists")
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=cfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.link(tmp, name, src_dir_fd=cfd, dst_dir_fd=cfd)      # link, not rename: never replaces a file
        finally:
            try:
                os.unlink(tmp, dir_fd=cfd)
            except FileNotFoundError:
                pass
        return f"{slug}/{name}"
    finally:
        os.close(cfd)


def list_report_ts(dir_fd):
    out = []
    for name in os.listdir(dir_fd):
        m = _REPORT_NAME_RE.fullmatch(name)
        if m and stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
            out.append(m.group(1))
    return sorted(out)


def is_stored(archive_base, slug, ts):
    try:
        fd = L.open_dir_below(archive_base, (slug,))
    except OSError:
        return False
    if fd is None:
        return False
    try:
        return stat.S_ISREG(os.stat(f"{ts}-report.md", dir_fd=fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)
