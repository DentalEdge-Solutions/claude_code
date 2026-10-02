#!/usr/bin/env python3
"""The gateway's MCP stdio server for one chat-trigger app (Option B spec 2026-09-30 §3.1). Stdlib only.

  python3 /opt/cc-bin/hermes-app-mcp.py --app ads-audit

It serves until stdin ends, and EOF abandons a call that is still waiting: piping one `run`
line in (`printf ... | hermes-app-mcp.py`) exits at once, usually before the request is filed.

DELIBERATELY DUMB, like hermes-syscall.py: it writes a request into the app's spool and reads
a result back. It holds no credential, does no network I/O and makes no policy decision —
everything is decided by the host-side broker, which treats every byte written here as hostile.
A refusal is returned as a normal (non-error) tool result stating it is final, never as a
retryable error: a model that retries a refusal is a model applying pressure to a guard."""
import argparse, json, os, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DESCRIPTIONS = {
    "run": "Run a Google Ads trend audit for one registered client. Takes minutes. Returns a result "
           "with status ok|refused|failed|busy, or pending with a request_id. A refused or failed "
           "result is FINAL: do not call this tool again for that client today.",
    "list": "List the timestamps of a client's past audits. Returns timestamps only.",
    "status": "Check the result of an earlier request by its request_id. Files nothing.",
}


class Server:
    def __init__(self, manifest, spool, sleep=time.sleep, clock=time.monotonic, poll=2.0):
        self.m, self.spool, self.sleep, self.clock, self.poll = manifest, spool, sleep, clock, poll
        self.by_tool = {v: k for k, v in manifest.tools.items()}

    def _tools(self):
        out = []
        for op, name in sorted(self.m.tools.items()):
            if op == "status":
                schema = {"type": "object", "properties": {"request_id": {"type": "string"}},
                          "required": ["request_id"], "additionalProperties": False}
            else:
                schema = {"type": "object", "properties": {"client": {"type": "string",
                          "description": "the client's registered short name (slug)"}},
                          "required": ["client"], "additionalProperties": False}
            out.append({"name": name, "description": DESCRIPTIONS[op], "inputSchema": schema})
        return out

    def _result(self, rid):
        """The result dict, or None (missing, unreadable, garbage or not an object: all 'pending')."""
        p = os.path.join(self.spool, "results", rid + ".json")
        try:
            r = json.loads(A.read_capped(p, A.MAX_DONE_BYTES))
        except (A.Refused, ValueError):               # UnicodeDecodeError is a ValueError
            return None
        return r if isinstance(r, dict) else None

    def _wait(self, rid, seconds):
        deadline = self.clock() + seconds
        while True:
            r = self._result(rid)
            if r is not None:
                return r
            if self.clock() >= deadline:
                return {"status": "pending", "request_id": rid}
            self.sleep(self.poll)

    def _text(self, obj, error=False):
        return {"content": [{"type": "text", "text": json.dumps(obj, sort_keys=True)}], "isError": error}

    def call(self, name, args):
        op = self.by_tool.get(name) if isinstance(name, str) else None
        if op is None or not isinstance(args, dict):
            return self._text({"error": "unknown tool"}, error=True)
        if op == "status":
            rid = args.get("request_id")
            if set(args) != {"request_id"} or not isinstance(rid, str) or not A.REQUEST_ID_RE.fullmatch(rid):
                return self._text({"error": "request_id must be a request id"}, error=True)
            return self._text(self._result(rid) or {"status": "pending", "request_id": rid})
        client = args.get("client")
        if set(args) != {"client"} or not isinstance(client, str) or not A.SLUG_RE.fullmatch(client):
            return self._text({"error": "client must be a registered short name"}, error=True)
        req = A.make_request(self.m, op, client)
        A.write_json_atomic(os.path.join(self.spool, "requests"), req["request_id"] + ".json", req)
        return self._text(self._wait(req["request_id"], self.m.wait_seconds[op]))

    def handle(self, msg):
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:                               # a notification: never answered
            return None
        if method == "initialize":
            want = (msg.get("params") or {}).get("protocolVersion")
            ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            res = {"protocolVersion": ver, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "hermes-app-" + self.m.app, "version": "1"}}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": self._tools()}
        elif method == "tools/call":
            p = msg.get("params") or {}
            res = self.call(p.get("name"), p.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve_line(server, line):
    """One stdin line -> the reply dict or None. Never raises: this loop must outlive any message."""
    try:
        msg = json.loads(line)
    except ValueError:
        return _err(None, -32700, "parse error")
    if not isinstance(msg, dict):
        return _err(None, -32600, "invalid request")
    try:
        return server.handle(msg)
    except Exception:                                 # a bug must not become a dead gateway tool
        mid = msg.get("id")
        return _err(mid, -32603, "internal error") if mid is not None else None


MAX_WAITING = 8     # run/list calls waiting on the broker at once; one more is refused, never queued


def _waits(server, msg):
    """True for a tools/call that waits on the broker's result (run, list): minutes, not milliseconds."""
    if not isinstance(msg, dict) or msg.get("method") != "tools/call" or msg.get("id") is None:
        return False
    p = msg.get("params")
    name = p.get("name") if isinstance(p, dict) else None
    return isinstance(name, str) and server.by_tool.get(name) in ("run", "list")


def serve(server, lines, write, max_waiting=MAX_WAITING):
    """Answer every input line. A run or list call waits for the broker's result, so it gets its
    own thread and this loop keeps reading: the client's liveness ping must be answered WHILE a
    call waits. Hermes pings each MCP server on a cadence (default 180 s), allows 30 s, and
    reconnects on silence, which discarded the reply of every audit that outlasted a ping
    (first box run, 2026-10-02: the audit finished `ok` in 233 s, Hermes saw a 360 s timeout).
    One lock keeps replies whole; a reply nobody can read any more is dropped, never raised.
    EOF abandons the calls still waiting: their replies are not written, and a call read just
    before EOF may not have filed its request yet (a request already filed stays with the broker)."""
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(max_waiting)
    closed = []                                   # non-empty once the input has ended

    def emit(out):
        if out is None:
            return
        try:
            with lock:
                if not closed:
                    write(json.dumps(out) + "\n")
        except (OSError, ValueError):             # the client hung up (closed pipe / closed file)
            pass

    def waited(line):
        try:
            emit(serve_line(server, line))
        finally:
            slots.release()

    def started(line):
        """True once the call has its own thread; False, holding nothing, at the cap or when the
        OS has no thread to give (RuntimeError from start() must not end this loop)."""
        if not slots.acquire(blocking=False):
            return False
        try:
            threading.Thread(target=waited, args=(line,), daemon=True).start()
        except RuntimeError:
            slots.release()
            return False
        return True

    try:
        for line in lines:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = None
            if _waits(server, msg):
                if not started(line):
                    emit({"jsonrpc": "2.0", "id": msg["id"],
                          "result": server._text({"error": "too many requests are waiting; try again later"},
                                                 error=True)})
                continue
            emit(serve_line(server, line))
    finally:
        # EOF, or the input itself raised (bytes that are not UTF-8): either way the process is
        # about to exit with calls still waiting on daemon threads. Wait out a reply being written
        # and let none start: a daemon thread inside sys.stdout.write when the interpreter shuts
        # down aborts it ("could not acquire lock for <_io.BufferedWriter name='<stdout>'> at
        # interpreter shutdown", SIGABRT) or leaves half a line.
        with lock:
            closed.append(True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/registry/apps")
    ap.add_argument("--spool-root", default="/opt/data/spool/apps")
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    s = Server(m, A.spool_dir(a.app, a.spool_root))

    def write(text):
        try:
            sys.stdout.write(text); sys.stdout.flush()
        except BrokenPipeError:                       # the client closed its end: serve drops the reply.
            fd = os.open(os.devnull, os.O_WRONLY)     # What is left in the buffer goes to /dev/null, or the
            os.dup2(fd, sys.stdout.fileno())          # flush at exit complains on stderr and exits 120.
            os.close(fd)
            raise
    serve(s, sys.stdin, write)


if __name__ == "__main__":
    main()
