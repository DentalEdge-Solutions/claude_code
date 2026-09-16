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

PLUMBING ASSUMPTION, load-bearing for `_handle`'s lock-step design: Task 1's measurement
found the real Compose invocation uses THREE SEPARATE CONNECTIONS to the socket — `wait`
on one, `attach` on a second, `start` on a third. `_handle` below sends a request, then
blocks reading its response, then loops for the next request on the SAME connection; that
is only correct because each of those three arrives on its own connection and therefore
gets its own thread from `ThreadingUnixStreamServer`. If a future Docker Compose ever
multiplexed those onto one connection, lock-step `_handle` would deadlock — e.g. blocking
to read the response to `wait` (which the daemon does not send until the container is
removed) while `start` sits unsent behind it. This is a property of the Compose CLI, not
of this proxy, and it is Step 5's end-to-end control — a real `docker compose run` against
the real daemon — that would catch such a change, not the unit tests, which use a fake
upstream and cannot observe the real client's connection behavior.
"""
import argparse, json, os, re, socket, socketserver, sys, threading

_V = r"(?:/v[0-9]+\.[0-9]+)?"          # optional API version prefix, e.g. /v1.55
_ID = r"[A-Za-z0-9_.-]+"

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
    ("POST",   re.compile(_V + r"/containers/" + _ID + r"/attach")),
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
        size = int(buf[:line_end].split(b";", 1)[0], 16)
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
        conn.sendall(buf[:needed])
        buf = buf[needed:]


def _handle(conn, upstream_path):
    up = None
    buf = b""
    try:
        while True:
            head, rest = _read_until_headers(conn, buf)
            if head is None:
                return
            line = head.split(b"\r\n")[0].decode("latin1")
            parts = line.split(" ")
            if len(parts) < 2:
                _refuse(conn, "malformed request line")
                return
            method, path = parts[0], parts[1]
            clen, chunked = 0, False
            for h in head.split(b"\r\n")[1:]:
                lo = h.lower()
                if lo.startswith(b"content-length:"):
                    clen = int(h.split(b":", 1)[1].strip() or b"0")
                if lo.startswith(b"transfer-encoding:") and b"chunked" in lo:
                    chunked = True
            is_create = "/containers/create" in path
            if is_create and (chunked or clen == 0):
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

            if "/attach" in path:
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
                return

            rhead, rrest = _read_until_headers(up, b"")
            if rhead is None:
                return
            rclen, rchunk = 0, False
            for h in rhead.split(b"\r\n")[1:]:
                lo = h.lower()
                if lo.startswith(b"content-length:"):
                    rclen = int(h.split(b":", 1)[1].strip() or b"0")
                if lo.startswith(b"transfer-encoding:") and b"chunked" in lo:
                    rchunk = True
            conn.sendall(rhead + b"\r\n\r\n")
            if rchunk:
                _relay_chunked(conn, up, rrest)
                return
            while len(rrest) < rclen:
                d = up.recv(65536)
                if not d:
                    break
                rrest += d
            conn.sendall(rrest[:rclen])
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
