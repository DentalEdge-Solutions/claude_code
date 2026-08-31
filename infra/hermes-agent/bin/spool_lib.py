#!/usr/bin/env python3
"""Request-spool contract for the governed mutation syscall. Stdlib-only.

The spool is the ONE surface Hermes can write, so every read here is hostile-input
handling (spec §8), not parsing. This module holds the whole of that discipline:
a closed four-key schema where an extra key REFUSES rather than being ignored, a
byte cap enforced twice, O_NOFOLLOW, and a regular-file assertion on the FD.

It imports only governance_lib, so it sits beside governance_lib at the bottom of the
dependency graph and shares that module's identifier regexes rather than restating
them. Restating them is how two validators drift into disagreeing about what a slug is.

It holds NO credential, performs NO network I/O, and makes NO policy decision. Whether
a validated request is ALLOWED is the broker's business; this module only decides
whether the bytes on disk are a well-formed request at all.
"""
import errno, json, os, re, stat, tempfile

import governance_lib

DEFAULT_SPOOL_ROOT = "/opt/data/spool"

# A few KB. A well-formed request is ~150 bytes; anything approaching this is either a
# mistake or an attempt to make the broker read an unbounded file into memory.
MAX_REQUEST_BYTES = 4096

REQUEST_KEYS = frozenset(("request_id", "op", "client", "changeset"))
OPS = ("apply",)                      # v1: apply only. NEVER undo — spec §17.2.

# Exactly the spec's §8.1 character class. Deliberately not tightened to a strict uuid4
# pattern: the filename and the request_id are cross-checked against each other, and a
# gratuitous divergence from the written spec is a worse defect than a permissive
# charset over a value that is never interpolated anywhere.
FILENAME_RE = re.compile(r"^[0-9a-f-]{36}\.json$")
REQUEST_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


class SpoolRefused(ValueError):
    """A request that cannot be proven well-formed. Subclasses ValueError so callers
    with an existing fail-closed ValueError handler refuse rather than crash."""


def spool_root():
    return os.environ.get("HERMES_SPOOL_ROOT", DEFAULT_SPOOL_ROOT)


def _root(root):
    return root or spool_root()


def requests_dir(root=None):
    return os.path.join(_root(root), "requests")


def results_dir(root=None):
    return os.path.join(_root(root), "results")


def _rid(request_id):
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise SpoolRefused("invalid request_id: %r" % (request_id,))
    return request_id


def request_path(request_id, root=None):
    return os.path.join(requests_dir(root), "%s.json" % _rid(request_id))


def result_path(request_id, root=None):
    return os.path.join(results_dir(root), "%s.json" % _rid(request_id))


def _open_regular_ro(path):
    """Open for reading with O_NOFOLLOW, then assert on the FD that it is a regular
    file of acceptable size.

    O_NONBLOCK matters: without it, opening a fifo that Hermes planted would BLOCK the
    single-threaded broker forever — a denial of service that looks like a hang, not a
    refusal. With it, the open succeeds and the fstat below rejects it as non-regular.

    Checked on the FD, never on the path, so nothing can be swapped between the test
    and the read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):
            raise SpoolRefused("%s is a symlink, refusing to follow it" % path)
        raise SpoolRefused("%s cannot be opened: %s" % (path, e))
    try:
        try:
            st = os.fstat(fd)
        except OSError as e:
            # An fstat failure used to re-raise RAW, which broke this module's one
            # promise: SpoolRefused subclasses ValueError so "callers with an existing
            # fail-closed ValueError handler refuse rather than crash". A bare OSError
            # is not that, and the consequence was not local — hermes-broker._parse_all
            # catches only SpoolRefused, so the exception escaped the whole parse loop,
            # which sits OUTSIDE drain()'s per-request handler. One unstattable file
            # would therefore abort the entire drain and starve every other client's
            # queued requests, which is precisely the batch-wide starvation the rest of
            # this module's guards exist to prevent.
            raise SpoolRefused("%s cannot be inspected after opening: %s" % (path, e))
        if not stat.S_ISREG(st.st_mode):
            raise SpoolRefused("%s is not a regular file, refusing" % path)
        if st.st_size > MAX_REQUEST_BYTES:
            raise SpoolRefused("%s is %d bytes, over the %d-byte cap — refusing"
                               % (path, st.st_size, MAX_REQUEST_BYTES))
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_request_bytes(path):
    """Read at most MAX_REQUEST_BYTES + 1 bytes and refuse if the file delivered more.

    The size is checked TWICE on purpose. The fstat in _open_regular_ro rejects a file
    that is already oversized; the bounded read rejects one that GREW between the fstat
    and the read, which is a writer Hermes controls and can therefore arrange.
    """
    fd = _open_regular_ro(path)
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        raise SpoolRefused("%s exceeded the %d-byte cap while being read — refusing"
                           % (path, MAX_REQUEST_BYTES))
    return data


def validate_request(obj, filename):
    """Validate a parsed request against the closed schema. Returns the request dict.

    Order follows spec §8: filename shape, exact key set, op, identifiers, then the
    filename/request_id cross-check. Replay is NOT checked here — the seen-set lives in
    the governance store and belongs to the broker (§8), because a replay record Hermes
    could reach is not replay protection.
    """
    if not FILENAME_RE.fullmatch(filename):
        raise SpoolRefused("filename %r does not match the request-file pattern" % filename)
    if not isinstance(obj, dict):
        raise SpoolRefused("request must be a JSON object, got %s" % type(obj).__name__)

    keys = set(obj)
    if keys != REQUEST_KEYS:
        extra = sorted(keys - REQUEST_KEYS)
        missing = sorted(REQUEST_KEYS - keys)
        raise SpoolRefused(
            "request schema is closed: extra=%s missing=%s — an unexpected key is a "
            "refusal, never an ignored field" % (extra, missing))

    op = obj["op"]
    if op not in OPS:
        raise SpoolRefused(
            "op %r is not permitted; v1 accepts only %r (undo is operator-only — it "
            "bypasses the kill switch and the caps and requires no approval)" % (op, OPS[0]))

    rid = obj["request_id"]
    if not isinstance(rid, str) or not REQUEST_ID_RE.fullmatch(rid):
        raise SpoolRefused("invalid request_id: %r" % (rid,))
    if filename != "%s.json" % rid:
        raise SpoolRefused("filename %r does not match request_id %r" % (filename, rid))

    client = obj["client"]
    if not isinstance(client, str) or not governance_lib.SLUG_RE.fullmatch(client):
        raise SpoolRefused("invalid client slug: %r" % (client,))

    cid = obj["changeset"]
    if not isinstance(cid, str) or not governance_lib.CHANGESET_ID_RE.fullmatch(cid):
        raise SpoolRefused("invalid changeset id: %r" % (cid,))

    return dict(obj)


def load_request(path):
    """read_request_bytes + JSON parse + validate_request, against the file's basename."""
    data = read_request_bytes(path)
    try:
        obj = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SpoolRefused("%s is not valid UTF-8 JSON: %s" % (path, e))
    return validate_request(obj, os.path.basename(path))


def write_result(request_id, payload, root=None):
    """Write <spool>/results/<request_id>.json atomically. Returns the path.

    A result is written on EVERY outcome including refusal (spec §12), so FILE
    EXISTENCE is the discriminator between "the broker has not processed this yet" and
    "the broker processed it and refused". Those are different events, and emptiness
    cannot separate them.
    """
    path = result_path(request_id, root)
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".%s." % request_id, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
