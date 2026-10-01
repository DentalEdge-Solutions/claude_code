#!/usr/bin/env python3
"""The gateway's MCP stdio server for one chat-trigger app (Option B spec 2026-09-30 §3.1). Stdlib only.

  python3 /opt/cc-bin/hermes-app-mcp.py --app ads-audit

DELIBERATELY DUMB, like hermes-syscall.py: it writes a request into the app's spool and reads
a result back. It holds no credential, does no network I/O and makes no policy decision —
everything is decided by the host-side broker, which treats every byte written here as hostile.
A refusal is returned as a normal (non-error) tool result stating it is final, never as a
retryable error: a model that retries a refusal is a model applying pressure to a guard."""
import argparse, json, os, sys, time
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/registry/apps")
    ap.add_argument("--spool-root", default="/opt/data/spool/apps")
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    s = Server(m, A.spool_dir(a.app, a.spool_root))
    for line in sys.stdin:
        out = serve_line(s, line)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
