#!/usr/bin/env python3
"""A body-inspecting Docker Engine API allow-list for the mutation broker. Stdlib-only.

WHY OUR OWN rather than an off-the-shelf socket proxy: the constraint that matters is
"create ONLY this image, with ONLY these mounts, running ONLY this program", and all of
that lives in the JSON BODY of POST /containers/create. A proxy that filters by method
and path cannot see it, so it would satisfy the letter of spec §6.4 and none of its
intent. This file is also small enough to audit in one sitting, which is the right
property for the one component whose compromise is worst.

THE POLICY, in one sentence: anything in the create body that can redirect trust to an
attacker-writable path is pinned. The executor has exactly ONE writable mount (log/), so
every field that could point it at a file inside that mount is a hole — Image is not
enough, and neither is Image plus Entrypoint (see ALLOWED_CMD_FLAGS).

WHAT THIS DOES NOT PROTECT: a compromised broker already holds the Ads write credential
(run-ads-mutate.sh reads .env.gaw in its own process) and can reach the client account
without Docker at all. This proxy defends the HOST, and secondarily the audit trail.

THE ALLOW-LIST BELOW WAS MEASURED, NOT GUESSED (spec deviation D1, re-measured for
Phase B). Adding an endpoint is a re-measurement, never a guess.

    Measured 2026-09-16 against Docker Desktop on darwin (Docker Engine 29.7.2, API
    1.55, Docker Compose v5.4.0), via `docker compose run --rm --no-deps -T
    ads-mutator --help` through a logging pass-through in front of the real socket.
    See docs/evaluations/2026-09-16-phase-b-endpoint-measurement.md for the full
    method, raw request log, and the verbatim create body.

    Distinct endpoints observed (method, base path):
        HEAD   /_ping
        GET    /containers/json
        GET    /networks
        GET    /volumes
        GET    /images/{name}/json
        POST   /containers/create
        GET    /containers/{id}/json
        POST   /containers/{id}/attach
        POST   /containers/{id}/wait
        POST   /containers/{id}/start

    ALLOWED below additionally carries GET /_ping, GET /version, and DELETE
    /containers/{id} — not observed in this measurement, but kept: GET /_ping is the
    same health-check family as the observed HEAD variant, GET /version is a
    harmless read-only diagnostic, and DELETE /containers/{id} is the manual cleanup
    path for a stale/stuck container (AutoRemove makes it rare, not impossible — see
    Task 1's own note about needing `docker rm -f` on a stale container). An
    allow-list entry with no observed traffic is a small, auditable widening; an
    endpoint the rail actually calls but that is missing here breaks the rail on the
    VPS, which is the worse failure. Adding an endpoint is a re-measurement, never a
    guess.

DENY BY DEFAULT. Anything not matched below is refused.

THREE SOCKET-PLUMBING TRAPS, each measured against the real daemon and each costly to
find. Function docstrings below carry the detail; this is the index.

    1. HTTP KEEP-ALIVE: the Docker CLI sends MANY requests on ONE connection. Get this
       wrong and inspect only the first request, then splice — an attacker sends a
       benign HEAD /_ping first and then anything at all on the same connection,
       bypassing the policy entirely. Measured while planning: a first-request-only
       pass-through logged 3 of 14 real calls and looked like it had worked. This is
       why `_handle` LOOPS per connection instead of forwarding-then-splicing.

    2. `POST .../wait?condition=removed` DOES NOT RETURN until the container is
       removed. Get this wrong and assume request/response pairs are independent, and
       a lock-step per-connection handler would deadlock if a future Compose ever
       multiplexed `wait`, `attach`, and `start` onto one connection — Task 1 measured
       the real invocation uses THREE SEPARATE CONNECTIONS for exactly
       these three calls, each getting its own thread from `ThreadingUnixStreamServer`.
       This is a property of the Compose CLI, not of this proxy; it is Step 5's
       end-to-end control against the real daemon that would catch a future Compose
       that multiplexes them, not the unit tests, which use a fake upstream and cannot
       observe the real client's connection behavior.

    3. dockerd KEEPS THE CONNECTION OPEN after a `Transfer-Encoding: chunked` response
       (HTTP keep-alive applies to the upstream socket too). Get this wrong and relay a
       chunked body by reading until the upstream closes, and it hangs forever — dockerd
       never closes. Measured directly: `curl --unix-socket /var/run/docker.sock
       'http://localhost/v1.55/containers/json?all=1'` returns `Transfer-Encoding:
       chunked` with no `Content-Length` and no connection close. This is why
       `_relay_chunked` parses the chunk framing itself to find the real end of the body.
"""
import argparse, json, os, re, socket, socketserver, sys, threading

_V = r"(?:/v[0-9]+\.[0-9]+)?"          # optional API version prefix, e.g. /v1.55
_ID = r"[A-Za-z0-9_.-]+"

# F18: attach is defined ONCE. The allow-list entry below and _is_attach() use this same
# object, so "what may be requested" and "what may switch a connection to raw pass-through"
# cannot drift apart.
_ATTACH_RE = re.compile(_V + r"/containers/" + _ID + r"/attach")

# (method, compiled path pattern). Fullmatch only — a prefix match would let
# /containers/create/../../build through.
ALLOWED = [
    ("GET",    re.compile(r"/_ping")),
    ("HEAD",   re.compile(r"/_ping")),
    ("GET",    re.compile(_V + r"/version")),
    ("GET",    re.compile(_V + r"/images/" + _ID + r"/json")),
    ("GET",    re.compile(_V + r"/networks")),
    ("GET",    re.compile(_V + r"/volumes")),
    ("GET",    re.compile(_V + r"/containers/json")),
    ("POST",   re.compile(_V + r"/containers/create")),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/start")),
    ("POST",   _ATTACH_RE),
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/wait")),
    ("GET",    re.compile(_V + r"/containers/" + _ID + r"/json")),
    ("DELETE", re.compile(_V + r"/containers/" + _ID)),
]

# HostConfig keys that hand back what the proxy exists to withhold. "Mounts" is here
# because it is the newer API for the same capability as Binds — left open it bypasses
# the bind allow-list entirely. Task 1 confirmed Mounts is absent from Compose-issued
# create bodies entirely, so keeping it forbidden costs nothing on real traffic.
FORBIDDEN_HOSTCONFIG = (
    "Privileged", "CapAdd", "Devices", "DeviceCgroupRules", "SecurityOpt",
    "Sysctls", "UsernsMode", "CgroupParent", "Runtime", "PidMode", "IpcMode",
    "UTSMode", "CgroupnsMode", "Init", "Mounts",
)

PINNED_ENTRYPOINT = ["python3", "/opt/cc-bin/apply-changeset.py"]

# The three flags hermes-broker.py:506 actually builds. --projects and --registry are
# deliberately ABSENT: --projects selects the file read for runner and script_dir
# (changeset_lib.read_mutate_execute), i.e. which program runs, and the one writable
# mount is where an attacker would put that file.
ALLOWED_CMD_FLAGS = {
    "--client":    re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$"),
    "--changeset": re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$"),
    "--request":   re.compile(r"^[0-9a-f-]{36}$"),
}

PINNED_IMAGE = None
PINNED_BINDS = frozenset()
PINNED_GOVERNANCE_ROOT = None
PINNED_NETWORK = None


def configure(image, binds, governance_root, network):
    """Set the pinned values at startup. `binds` is an iterable of (src, dst, mode).

    Taken as flags rather than derived from docker-compose.yml because YAML is not
    stdlib and this file may not grow a dependency. proxy-policy-sync.test.py is what
    keeps the two in agreement.

    `network` pins HostConfig.NetworkMode to an allow-list (the exact Compose network
    name), not a denylist. The prior denylist (`startswith("host")`) does not catch
    NetworkMode="container:<id>", which joins another container's network namespace —
    it was the only denylist left in a file whose whole point is allow-lists.
    """
    global PINNED_IMAGE, PINNED_BINDS, PINNED_GOVERNANCE_ROOT, PINNED_NETWORK
    PINNED_IMAGE = image
    PINNED_BINDS = frozenset("%s:%s:%s" % (s, d, m) for s, d, m in binds)
    PINNED_GOVERNANCE_ROOT = governance_root
    PINNED_NETWORK = network


def _path_only(path):
    """Strip the query string and reject any traversal before matching."""
    p = path.split("?", 1)[0]
    if ".." in p or "//" in p:
        return None
    return p


def _is_attach(method, path):
    """True only for a real attach: POST, and the path WITHOUT its query string fullmatches
    the attach pattern. A substring test over the whole target was F18: `GET /_ping?x=/attach`
    and `DELETE /containers/attach` both switched the connection to uninspected pass-through."""
    return method == "POST" and bool(_ATTACH_RE.fullmatch(_path_only(path) or ""))


def _status_code(rhead):
    """The upstream response's status as an int when it is exactly three ASCII digits in the
    second space-separated field of the status line, else None. Only an exact 101 may switch
    a connection to pass-through, so anything unusual reads as None, never as 101."""
    parts = rhead.split(b"\r\n", 1)[0].split(b" ")
    if len(parts) >= 2 and len(parts[1]) == 3 and parts[1].isdigit():
        return int(parts[1])
    return None


def _check_cmd(cmd):
    if not isinstance(cmd, list) or not cmd:
        return "Cmd must be a non-empty list"
    i = 0
    seen = set()
    while i < len(cmd):
        flag = cmd[i]
        if flag not in ALLOWED_CMD_FLAGS:
            return "Cmd flag %r is not permitted" % flag
        if i + 1 >= len(cmd):
            return "Cmd flag %r has no value" % flag
        if not ALLOWED_CMD_FLAGS[flag].fullmatch(str(cmd[i + 1])):
            return "Cmd value for %s is malformed" % flag
        seen.add(flag)
        i += 2
    missing = set(ALLOWED_CMD_FLAGS) - seen
    if missing:
        return "Cmd is missing %s" % ", ".join(sorted(missing))
    return None


def decide(method, path, body):
    """Pure allow/deny. Returns (allowed, reason). No I/O — this is the whole policy,
    and it is a function so it can be tested exhaustively without a socket."""
    p = _path_only(path)
    if p is None:
        return False, "path %r contains a traversal component" % path
    if not any(m == method and pat.fullmatch(p) for m, pat in ALLOWED):
        return False, "%s %s is not on the allow-list" % (method, p)

    if not (method == "POST" and re.fullmatch(_V + r"/containers/create", p)):
        return True, "allowed"

    try:
        spec = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return False, "unparseable create body: %s" % e
    if not isinstance(spec, dict):
        return False, "create body is not an object"

    if spec.get("Image") != PINNED_IMAGE:
        return False, ("create refused: image %r is not the pinned image %r"
                       % (spec.get("Image"), PINNED_IMAGE))

    if spec.get("Entrypoint") != PINNED_ENTRYPOINT:
        return False, ("create refused: entrypoint %r is not the pinned entrypoint %r"
                       % (spec.get("Entrypoint"), PINNED_ENTRYPOINT))

    # The image sets USER hermes and compose does not override it, so a legitimate
    # create carries no User field. Task 1 measured the real field as PRESENT but
    # empty string (""), not absent — this check is written as "falsy" precisely so
    # it treats absent and present-but-empty identically. "Must not be set" — NOT
    # "must equal 10000", which would refuse every real call.
    if spec.get("User"):
        return False, "create refused: User override %r is not permitted" % spec["User"]

    problem = _check_cmd(spec.get("Cmd"))
    if problem:
        return False, "create refused: " + problem

    hc = spec.get("HostConfig") or {}
    if not isinstance(hc, dict):
        return False, "HostConfig is not an object"
    for k in FORBIDDEN_HOSTCONFIG:
        if hc.get(k):
            return False, "create refused: HostConfig.%s is not permitted" % k

    binds = hc.get("Binds") or []
    if not isinstance(binds, list):
        return False, "create refused: HostConfig.Binds is not a list"
    got = set(str(b) for b in binds)
    if got != PINNED_BINDS:
        extra = sorted(got - PINNED_BINDS)
        missing = sorted(PINNED_BINDS - got)
        return False, ("create refused: bind set does not match the pinned set "
                       "(unexpected: %s; missing: %s)" % (extra or "none", missing or "none"))

    # NetworkMode is an ALLOW-LIST (exact match against the pinned Compose network),
    # not a denylist — see configure()'s docstring for why. PidMode/IpcMode keep the
    # startswith("host") denylist because Task 1 measured no pinned value for either.
    if str(hc.get("NetworkMode", "")) != PINNED_NETWORK:
        return False, ("create refused: HostConfig.NetworkMode=%r is not the pinned "
                       "network %r" % (hc.get("NetworkMode"), PINNED_NETWORK))
    for mode_key in ("PidMode", "IpcMode"):
        if str(hc.get(mode_key, "")).startswith("host"):
            return False, "create refused: HostConfig.%s=host" % mode_key

    for entry in spec.get("Env") or []:
        name, _, value = str(entry).partition("=")
        if name == "HERMES_GOVERNANCE_ROOT" and value != PINNED_GOVERNANCE_ROOT:
            return False, ("create refused: HERMES_GOVERNANCE_ROOT=%r is not the pinned "
                           "root %r" % (value, PINNED_GOVERNANCE_ROOT))

    return True, "allowed"


MAX_BODY = 1024 * 1024


# ---- The framing hardening (spec 2026-09-23) -------------------------------------------
# This proxy forwards the ORIGINAL header block verbatim to dockerd, so its safety rests on
# one invariant: it and dockerd always agree where a request ends. Every head is therefore
# parsed ONCE, here, against a strict grammar, and anything not parseable unambiguously is
# refused — instead of depending on dockerd (Go net/http) being stricter than this file.
# Forms this closes (measurement plan 2026-09-17 §1): obs-fold continuation lines, a space
# before the colon, duplicate Content-Length, and (inferred, not measured) a bare LF, which
# Go's textproto treats as a line end while a split on CRLF does not.
_TOKEN_RE = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_TARGET_RE = re.compile(rb"[\x21-\x7e]+")
_VALUE_RE = re.compile(rb"[\t\x20-\x7e]*")
_DIGITS_RE = re.compile(rb"[0-9]+")


class HeadRefused(ValueError):
    """A request head this proxy will not forward. `reason` is one of a FIXED set of strings
    and never contains request bytes (it goes to the client and to the journal)."""

    def __init__(self, reason, method="-", path="-"):
        super().__init__(reason)
        self.reason = reason
        self.method = method
        self.path = path


def _parse_head(head):
    """(method, path, content_length) for a head that parses unambiguously, else raise
    HeadRefused. `head` is the bytes before the first CRLFCRLF."""
    lines = head.split(b"\r\n")
    for line in lines:
        if b"\r" in line or b"\n" in line or b"\x00" in line:
            raise HeadRefused("malformed request")
    parts = lines[0].split(b" ")
    if (len(parts) != 3 or not _TOKEN_RE.fullmatch(parts[0])
            or not _TARGET_RE.fullmatch(parts[1]) or parts[2] != b"HTTP/1.1"):
        raise HeadRefused("malformed request line")
    method, path = parts[0].decode("ascii"), parts[1].decode("ascii")
    clen = None
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        # The name must be a bare token that STARTS the line and is followed IMMEDIATELY by
        # ':'. An obs-fold line (leading SP/HTAB) and "Name : v" both fail here.
        if not sep or not _TOKEN_RE.fullmatch(name):
            raise HeadRefused("malformed header line", method, path)
        value = value.strip(b" \t")
        if not _VALUE_RE.fullmatch(value):
            raise HeadRefused("malformed header line", method, path)
        lname = name.lower()
        if lname == b"transfer-encoding":
            # CL.TE / TE.CL REQUEST SMUGGLING. This proxy frames every request by
            # Content-Length alone (`while len(rest) < clen` below); dockerd is Go
            # net/http, which frames by Transfer-Encoding when BOTH headers are
            # present on a request. A request that carries Transfer-Encoding at
            # all — alone, or alongside Content-Length — is therefore ambiguous:
            # this proxy would read exactly `clen` bytes as "the body" and treat
            # anything past that as the start of the NEXT request on the
            # connection, while dockerd treats (say) an empty chunked body as
            # ending THIS request and parses the remainder as a wholly separate,
            # uninspected second request. MEASURED against the real `_handle`
            # before this fix: an allowed `POST .../wait` carrying both headers,
            # with an empty chunked body followed by a smuggled `POST
            # /containers/create {Privileged: true, Binds: ["/:/host:rw"]}` in the
            # declared Content-Length tail, produced exactly one logged decision
            # (`ALLOW POST .../wait`) — `decide()` was never called for the
            # create, and dockerd executed it as a second request on the same
            # connection. Refuse unconditionally, for every path (not just
            # `/containers/create`), before any framing or forwarding, and close
            # the connection rather than trying to keep reading a stream we can
            # no longer unambiguously frame.
            raise HeadRefused("Transfer-Encoding is not permitted on requests", method, path)
        if lname == b"content-length":
            if clen is not None:
                # Refused even when both values agree: keeping one silently is exactly the
                # "which one wins" question this proxy must never answer differently from
                # dockerd.
                raise HeadRefused("duplicate Content-Length", method, path)
            # DIGITS ONLY. RFC 9110 defines Content-Length as 1*DIGIT, but
            # Python's int() also accepts "-5", "+5", "1_0" and an empty value
            # (via the old `or b"0"`), and Go's ParseUint — which is what
            # dockerd uses — accepts none of them. Every one of those is this
            # proxy and its upstream disagreeing about where the request ends,
            # which is the same shape as the CL.TE Critical documented below.
            # MEASURED 2026-09-17: `Content-Length: 7_7` parsed here as 77 and
            # carried a smuggled create's bytes through to the upstream socket;
            # `Content-Length: -5` made the framing below do
            # `rest[:-5], rest[-5:]`, silently handing the last five body bytes
            # to the next loop iteration as a request line; and a non-numeric
            # value raised ValueError out of _handle (which catches only
            # OSError) as an unhandled traceback. Refuse instead of guessing.
            # 19 digits is the most Go's ParseUint(v, 10, 63) accepts (2**63-1); staying at
            # or under it also keeps int() well under Python's 4300-digit conversion limit.
            # MAX_BODY is enforced later, in _handle.
            if not _DIGITS_RE.fullmatch(value) or len(value) > 19:
                raise HeadRefused("malformed Content-Length", method, path)
            clen = int(value)
    return method, path, (clen or 0)


def _read_until_headers(sock, buf):
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return None, buf
        buf += chunk
        if len(buf) > MAX_BODY:
            return None, buf
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head, rest


def _refuse(conn, reason):
    payload = json.dumps({"message": reason}).encode("utf-8")
    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n"
                 b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)


def _relay_chunked(conn, up, buf):
    """Forward a Transfer-Encoding: chunked response byte-for-byte while parsing the
    chunk framing ourselves, so we know exactly when the body ends.

    MEASURED against the real daemon while building this: relaying raw bytes until
    `up.recv()` returns empty (i.e. treating connection-close as end-of-body) hangs
    forever, because dockerd keeps the connection open afterward under HTTP
    keep-alive — `curl --unix-socket /var/run/docker.sock
    'http://localhost/v1.55/containers/json?all=1'` returns `Transfer-Encoding:
    chunked` with no `Content-Length` and does not close the socket. `docker compose
    run` hung on exactly this call (GET .../containers/json) during Step 5's
    end-to-end proof until this was fixed.
    """
    while True:
        while b"\r\n" not in buf:
            d = up.recv(65536)
            if not d:
                return
            buf += d
            if len(buf) > MAX_BODY:
                return
        line_end = buf.index(b"\r\n") + 2
        try:
            size = int(buf[:line_end].split(b";", 1)[0], 16)
        except ValueError:
            # A malformed chunk-size line from dockerd would be a serious anomaly, not
            # an attacker input (this stream comes from the trusted upstream) — but
            # every other path in this file fails closed and logged rather than with
            # an unhandled traceback, so this one does too.
            print("upstream sent a malformed chunk-size line: %r" % buf[:line_end],
                  file=sys.stderr)
            return
        if size == 0:
            # last-chunk: "0\r\n" followed by an (often empty) trailer section
            # terminated by a blank line, NOT by chunk-data + CRLF.
            while b"\r\n\r\n" not in buf:
                d = up.recv(65536)
                if not d:
                    conn.sendall(buf)
                    return
                buf += d
                if len(buf) > MAX_BODY:
                    conn.sendall(buf)
                    return
            end = buf.find(b"\r\n\r\n") + 4
            conn.sendall(buf[:end])
            return
        needed = line_end + size + 2   # chunk-size line + chunk-data + trailing CRLF
        while len(buf) < needed:
            d = up.recv(65536)
            if not d:
                conn.sendall(buf)
                return
            buf += d
            if len(buf) > MAX_BODY:
                # Cap the buffered response the same way the request side is capped
                # (see `_handle`'s `clen > MAX_BODY` check). Headers are already sent
                # to the client by the time we get here, so a 403 is not available —
                # close the connection instead, same as the malformed-header case above.
                print("upstream chunk exceeds %d bytes; closing" % MAX_BODY,
                      file=sys.stderr)
                return
        conn.sendall(buf[:needed])
        buf = buf[needed:]


def _pump_both(conn, up):
    """Raw two-way relay for an UPGRADED attach, until either side closes. Only ever entered
    after dockerd answered 101 to a real attach — after that the connection carries the
    container's stdio stream, not the Docker API, so there is nothing left to inspect."""
    def pump(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
    threading.Thread(target=pump, args=(conn, up), daemon=True).start()
    pump(up, conn)


def _handle(conn, upstream_path):
    up = None
    buf = b""
    try:
        while True:
            head, rest = _read_until_headers(conn, buf)
            if head is None:
                return
            # The framing hardening (spec 2026-09-23): the head is parsed ONCE, strictly,
            # by _parse_head, and anything it cannot parse unambiguously is refused. Close,
            # do not continue the loop: after an unparseable head there is no safe place to
            # resume reading. The reason is a fixed string; refused bytes never reach the
            # journal (method/path are logged only when the request line itself parsed).
            try:
                method, path, clen = _parse_head(head)
            except HeadRefused as e:
                _refuse(conn, e.reason)
                print("DENY %s %s (%s)" % (e.method, e.path, e.reason), file=sys.stderr)
                return
            # Substring, not the regex fullmatch the rest of the file uses — deliberately
            # over-inclusive relative to decide()'s ALLOWED patterns, never under. A path
            # this misses would fall through to decide() unrefused-for-uninspectability
            # only to be refused there instead (or matched and inspected normally), so
            # there is no bypass; it can only refuse a few extra non-create paths early.
            is_create = "/containers/create" in path
            # A create can no longer reach here with Transfer-Encoding set (chunked
            # or otherwise) — `_parse_head` already refused any Transfer-Encoding. What's
            # left to catch is a create with NEITHER header, where `clen` defaults
            # to 0: decide() cannot safely run against a body of unknown length.
            if is_create and clen == 0:
                _refuse(conn, "create with no Content-Length cannot be inspected")
                print("DENY %s %s (uninspectable body)" % (method, path), file=sys.stderr)
                return
            if clen > MAX_BODY:
                _refuse(conn, "body exceeds %d bytes" % MAX_BODY)
                return
            while len(rest) < clen:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                rest += chunk
            body, buf = rest[:clen], rest[clen:]

            ok, reason = decide(method, path, body)
            print("%s %s %s (%s)" % ("ALLOW" if ok else "DENY", method, path, reason),
                  file=sys.stderr)
            if not ok:
                _refuse(conn, reason)
                return

            if up is None:
                up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                up.connect(upstream_path)
            up.sendall(head + b"\r\n\r\n" + body)

            rhead, rrest = _read_until_headers(up, b"")
            if rhead is None:
                return
            # F18: decide on pass-through only AFTER dockerd has answered, and only for a real
            # attach it upgraded. Any other answer to an attach is relayed below and then the
            # connection is closed — after an attach there are exactly two outcomes, upgraded or
            # closed, and no request can follow one on the same connection.
            attach = _is_attach(method, path)
            status = _status_code(rhead)
            if attach and status == 101:
                conn.sendall(rhead + b"\r\n\r\n" + rrest)
                if buf:
                    # Client bytes already read past the attach request are the start of the
                    # stream (stdin); forward them rather than silently dropping them.
                    up.sendall(buf)
                print("UPGRADE %s %s (101)" % (method, path), file=sys.stderr)
                _pump_both(conn, up)
                return
            rclen, rchunk = 0, False
            for h in rhead.split(b"\r\n")[1:]:
                lo = h.lower()
                if lo.startswith(b"content-length:"):
                    raw = h.split(b":", 1)[1].strip()
                    if not raw.isdigit():
                        # Same rule as the request side. This stream comes from the
                        # trusted upstream, so a malformed length is an anomaly rather
                        # than an attack — but a 403 is not the right shape for "the
                        # upstream's own response was malformed", so close and log, the
                        # way the oversized-response path just below does.
                        print("upstream sent a malformed Content-Length: %r; closing"
                              % raw, file=sys.stderr)
                        return
                    rclen = int(raw)
                if lo.startswith(b"transfer-encoding:") and b"chunked" in lo:
                    rchunk = True
            if rchunk:
                # Headers must go out before the body here: the body's total length
                # isn't known up front (that's the whole point of chunked encoding),
                # so there is nothing to buffer and combine with them.
                conn.sendall(rhead + b"\r\n\r\n")
                _relay_chunked(conn, up, rrest)
                if attach:
                    print("DENY-FOLLOWUP %s %s (attach answered %s, not upgraded; connection "
                          "closed)" % (method, path, status), file=sys.stderr)
                return
            # Buffer the FULL body before sending anything, then send headers + body
            # in ONE write. MEASURED: sending headers immediately and the body in a
            # later, separate sendall() lets a client that reads once per response see
            # only the headers on this request and the stray body bytes on its NEXT
            # recv() — reproduced directly with a client that reads once per response
            # (a real HTTP client that reads exactly Content-Length bytes is not
            # confused by this, but there is no reason to split a response we already
            # hold in full).
            while len(rrest) < rclen:
                d = up.recv(65536)
                if not d:
                    break
                rrest += d
                if len(rrest) > MAX_BODY:
                    # Same cap as the request side and _relay_chunked. Nothing has
                    # been sent to the client yet in this path (unlike the chunked
                    # case above), but a 403 still isn't the right shape for "the
                    # upstream's own response was too large" — close instead, and log
                    # it like the other decisions.
                    print("DENY %s %s (upstream response exceeds %d bytes; closing)"
                          % (method, path, MAX_BODY), file=sys.stderr)
                    return
            conn.sendall(rhead + b"\r\n\r\n" + rrest[:rclen])
            if attach:
                print("DENY-FOLLOWUP %s %s (attach answered %s, not upgraded; connection "
                      "closed)" % (method, path, status), file=sys.stderr)
                return
    except OSError:
        return
    finally:
        if up is not None:
            try:
                up.close()
            except OSError:
                pass


def serve(listen, upstream):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            _handle(self.request, upstream)

    class Server(socketserver.ThreadingUnixStreamServer):
        allow_reuse_address = True
        daemon_threads = True

    if os.path.exists(listen):
        os.remove(listen)
    srv = Server(listen, Handler)
    # Under the unit's UMask=0077 the socket is created 0600; this chmod is what opens it to
    # the hermes-rail group. Containment no longer rests only on RuntimeDirectoryMode=0750 —
    # the socket is private from the instant it exists (2026-09-17 handoff §6).
    os.chmod(listen, 0o660)
    srv.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", required=True)
    ap.add_argument("--upstream", default="/var/run/docker.sock")
    ap.add_argument("--image", required=True)
    ap.add_argument("--governance-root", required=True)
    ap.add_argument("--network", required=True,
                    help="the exact HostConfig.NetworkMode value Compose issues, "
                         "e.g. hermes-agent_default")
    ap.add_argument("--allow-bind", action="append", default=[],
                    metavar="SRC:DST:MODE", required=True,
                    help="repeatable; the exact bind set the executor may request")
    args = ap.parse_args(argv)
    binds = []
    for raw in args.allow_bind:
        bits = raw.split(":")
        if len(bits) != 3 or bits[2] not in ("ro", "rw"):
            print("docker-create-proxy: --allow-bind must be SRC:DST:ro|rw, got %r" % raw,
                  file=sys.stderr)
            return 2
        binds.append(tuple(bits))
    configure(image=args.image, binds=binds, governance_root=args.governance_root,
              network=args.network)
    serve(args.listen, args.upstream)
    return 0


if __name__ == "__main__":
    sys.exit(main())
