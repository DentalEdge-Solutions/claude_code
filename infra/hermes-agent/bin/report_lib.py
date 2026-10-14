#!/usr/bin/env python3
"""The figures-report store (design 2026-10-13, Part 1). Stdlib only.

A figures run's three reader reports are written by a container (uid 10000) into
/var/lib/hermes/reports/<client>/. Root joins them into ONE document and stores it in
/var/lib/hermes/report-archive/<client>/<ts>-report.md: a store no container mounts, so a report
never reaches the drafter of a later audit. Everything read here was written by a container: each
name is opened below its folder without following a link, must be a regular file, is size-capped,
and is copied, never parsed."""
import os, re, stat, sys, unicodedata

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


# --- one text model for the isolation check and for the display (tables built once, at import) ---
_CF, _PD, _ND = [], [], []
for _cp in range(sys.maxunicode + 1):
    _cat = unicodedata.category(chr(_cp))
    if _cat == "Cf":
        _CF.append(_cp)
    elif _cat == "Pd":
        _PD.append(_cp)
    elif _cat == "Nd":
        _ND.append(_cp)
_INVISIBLE = [*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0),
              0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5, 0x2800]

# what the operator sees: C0 controls except newline and tab, DEL, C1, every Cf, U+2028/U+2029
_DISPLAY = dict.fromkeys([*range(0x00, 0x09), *range(0x0B, 0x20), *range(0x7F, 0xA0), *_CF, 0x2028, 0x2029])
_N1 = {cp: None for cp in (*_CF, *_INVISIBLE)}
_N1.update({cp: "-" for cp in (*_PD, 0x2212, 0x2043)})
_N1.update({cp: str(unicodedata.decimal(chr(cp))) for cp in _ND})
_N2 = dict(_N1)
_N2[0x00AD] = "-"                    # a soft hyphen standing in for the hyphen
_EXPAND_SLACK = 1024


def display_text(text):
    """Exactly what show-report prints."""
    return text.translate(_DISPLAY)


def isolation_texts(text):
    """The copies the isolation check reads: the original, the display copy, and two normalised copies
    (N1: soft hyphen dropped; N2: soft hyphen as a hyphen). The stored document stays the original."""
    folded = unicodedata.normalize("NFKC", text)
    if len(folded) > 2 * len(text) + _EXPAND_SLACK:
        raise ReportError("the reports expand too much when normalised")
    return (text, display_text(text), folded.translate(_N1), folded.translate(_N2))


def _customer_id(rec):
    """The record's ten digits, None when it has no id; ReportError when the record is not an object
    or its id is unusable."""
    if not isinstance(rec, dict):
        raise ReportError("a registry record cannot be read")
    cid = rec.get("customer_id")
    if cid is None or cid == "":
        return None
    if isinstance(cid, int) and not isinstance(cid, bool):
        cid = str(cid)
    elif isinstance(cid, str):
        cid = cid.replace(" ", "").replace("-", "")
    if not isinstance(cid, str) or not re.fullmatch(r"[0-9]{10}", cid):
        raise ReportError("a registry record's customer id is not ten digits")
    return cid


def _other_ids(registry, me):
    try:
        mine = _customer_id(registry.get(me))
    except ReportError:
        mine = None
    out = {}
    for slug, rec in registry.items():
        if slug == me:
            continue
        cid = _customer_id(rec)
        if cid is not None and cid != mine:
            out[slug] = cid
    return out


def other_client_ids(registry, me):
    """The ten-digit customer ids of the OTHER clients, leaving out any equal to mine."""
    return list(_other_ids(registry, me).values())


_ID_SCAN = re.compile(r"(?<![0-9])([0-9]{3})[^0-9A-Za-z\n]?([0-9]{3})[^0-9A-Za-z\n]?([0-9]{4})(?![0-9])")


def isolation_hits(text, me, registry):
    """(by_name, by_id): how many DISTINCT other clients the text names by slug, and how many by
    customer id (a client found both ways counts in both). Names are looked for in every isolation
    text, ids too (digit boundaries, at most one separator between the groups of 3-3-4). Counts only,
    never a name or an id.
    Known limits, shared with the audit's own check: a name written with a space, an underscore or a
    line break in place of the hyphen; look-alike letters of another script; a combining mark inside
    a name; an id grouped differently (for example with thousands separators)."""
    ids = _other_ids(registry, me)
    by_id_slugs = {}
    for slug, c in ids.items():
        by_id_slugs.setdefault(c, []).append(slug)
    slugs = [x for x in registry if x != me]
    by_name, by_id = set(), set()
    for t in isolation_texts(text):
        low = t.lower()
        present = [x for x in slugs if x.lower() in low]          # a slug that is no substring cannot match
        if present:
            by_name.update(L.others_named(t, me, present))
        for m in _ID_SCAN.finditer(t):
            by_id.update(by_id_slugs.get("".join(m.groups()), ()))
    by_name.discard(me)
    by_id.discard(me)
    return len(by_name), len(by_id)


def _read_one(dir_fd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReportError("a report is not a regular file")
        if st.st_size > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        chunks, total = [], 0
        while total <= MAX_REPORT_BYTES:          # a read may be short: go on until EOF or past the cap
            chunk = os.read(fd, MAX_REPORT_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_REPORT_BYTES:
            raise ReportError("a report is too large")
        return b"".join(chunks).decode("utf-8", errors="replace")
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
        names = []
        with os.scandir(fd) as it:
            for entry in it:
                names.append(entry.name)
                if len(names) > 2 * len(readers) + 8:
                    raise ReportError("too many entries in the reports folder")
        found = {}
        for name in sorted(names):
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
    # open first, judge the descriptor: no gap between the check and the use, and a trailing slash
    # (which makes some systems follow a final link) is stripped so O_NOFOLLOW sees the link.
    path = archive_base.rstrip("/") or ("/" if archive_base else "")
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise ReportError("the report store must be a real directory, owner-only")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
        os.close(fd)
        raise ReportError("the report store must be a real directory, owner-only")
    return fd


def store(archive_base, slug, ts, text, owner_uid=0):
    """Write the document as <archive>/<slug>/<ts>-report.md, 0600, never over an existing file.
    Returns the path below the archive. The client folder is created 0700 when missing."""
    if not _SLUG_RE.fullmatch(slug) or not L.TS_RE.fullmatch(ts):
        raise ReportError("invalid client name or timestamp")
    base = _archive_fd(archive_base, owner_uid)
    try:
        created = True
        try:
            os.mkdir(slug, 0o700, dir_fd=base)
        except FileExistsError:
            created = False
        cfd = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
        if created:
            os.fchmod(cfd, 0o700)          # whatever the umask; a folder that pre-existed is judged, not fixed
    finally:
        os.close(base)
    try:
        st = os.fstat(cfd)
        if st.st_uid != owner_uid or stat.S_IMODE(st.st_mode) != 0o700:
            raise ReportError("the client's report folder must be owner-only")
        name, tmp = f"{ts}-report.md", f".{ts}-report.{os.getpid()}.tmp"
        left = re.compile(r"^\." + re.escape(ts) + r"-report(\.[0-9]+)?\.tmp$")
        for entry in os.listdir(cfd):          # a killed earlier run's temporary file for this timestamp
            if left.fullmatch(entry):
                try:
                    os.unlink(entry, dir_fd=cfd)
                except FileNotFoundError:
                    pass
        try:
            os.stat(name, dir_fd=cfd, follow_symlinks=False)
            raise ReportError("a report with this timestamp exists")
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=cfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                os.fchmod(f.fileno(), 0o600)          # whatever the umask
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
    """True only for a regular <archive>/<slug>/<ts>-report.md; never raises."""
    if not isinstance(slug, str) or not isinstance(ts, str) \
            or not _SLUG_RE.fullmatch(slug) or not L.TS_RE.fullmatch(ts):
        return False
    try:
        fd = L.open_dir_below(archive_base, (slug,))
        if fd is None:
            return False
        try:
            return stat.S_ISREG(os.stat(f"{ts}-report.md", dir_fd=fd, follow_symlinks=False).st_mode)
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError):
        return False
