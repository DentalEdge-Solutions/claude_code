#!/usr/bin/env python3
"""Allow-list HTTPS egress proxy for the ads-drafter (spec 2026-09-30 §5.2). Stdlib only.

  egress-proxy.py --listen 0.0.0.0:3128 --allow api.anthropic.com:443 [--allow host:port ...]

HTTP CONNECT to an allow-listed host:port is tunnelled; everything else gets 403 and the
connection closes. It never terminates TLS and never logs content: one line per decision
(target, decision, reason, byte counts). The drafter's network is `internal`, so this is
its only way out: no proxy, no draft.

Reasons: not-connect, bad-target, ip-literal, not-allowed, header-too-large, upstream-unreachable, client-gone."""
import argparse, ipaddress, re, select, socket, socketserver, sys

MAX_HEADER = 8192
IDLE_SECONDS = 300
_SAFE = re.compile(r"^[A-Za-z0-9.\-]{1,253}:[0-9]{1,5}$")


def _is_valid_port(port_str):
    """Finding 1: validate port is ASCII digits and in range 1-65535"""
    if not port_str or not all(c in "0123456789" for c in port_str):
        return False
    if len(port_str) > 5:
        return False
    try:
        p = int(port_str)
        return 1 <= p <= 65535
    except ValueError:
        return False


class Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_allow(values):
    out = set()
    for v in values:
        host, _, port = v.rpartition(":")
        if not host or not _is_valid_port(port):
            raise ValueError(f"bad --allow value {v!r}: expected host:port")
        out.add((host.lower().rstrip("."), int(port)))
    return frozenset(out)


def _is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def decide(head, allow):
    parts = head.split("\r\n", 1)[0].split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or not parts[2].startswith("HTTP/1."):
        raise Refused("not-connect")
    target = parts[1]
    if target.startswith("[") and "]" in target:
        raise Refused("ip-literal")
    host, _, port = target.rpartition(":")
    if not host or not _is_valid_port(port):
        raise Refused("bad-target")
    if _is_ip(host):
        raise Refused("ip-literal")
    key = (host.lower().rstrip("."), int(port))
    if key not in allow:
        raise Refused("not-allowed")
    return key


def _target_for_log(head):
    parts = head.split("\r\n", 1)[0].split(" ")
    t = parts[1] if len(parts) >= 2 else ""
    return t if _SAFE.fullmatch(t) else "invalid"


def _pump(a, b, first=b""):
    up = down = 0
    try:
        if first:
            b.sendall(first); up += len(first)
        socks = [a, b]
        while True:
            r, _, _ = select.select(socks, [], [], IDLE_SECONDS)
            if not r:
                return up, down
            for s in r:
                data = s.recv(65536)
                if not data:
                    return up, down
                (b if s is a else a).sendall(data)
                if s is a:
                    up += len(data)
                else:
                    down += len(data)
    except OSError:
        return up, down


def _establish(client, upstream, target, log_fn):
    """Send 200 to the client; if the client is already gone, log deny/client-gone,
    close upstream and return False."""
    try:
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    except OSError:
        log_fn("deny", target, "client-gone")
        upstream.close()
        return False
    return True


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        c, log = self.request, self.server.log
        c.settimeout(30)
        raw = b""
        try:
            while b"\r\n\r\n" not in raw:
                chunk = c.recv(4096)
                if not chunk:
                    return
                raw += chunk
                if len(raw) > MAX_HEADER:
                    raise Refused("header-too-large")
            head, rest = raw.split(b"\r\n\r\n", 1)
            text = head.decode("latin-1")
            host, port = decide(text, self.server.allow)
        except Refused as r:
            text = raw.split(b"\r\n", 1)[0].decode("latin-1")
            self._log("deny", _target_for_log(text), r.reason)
            try:
                c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return
        except OSError:
            return
        try:
            up = socket.create_connection((host, port), timeout=30)
        except OSError:
            self._log("deny", f"{host}:{port}", "upstream-unreachable")
            try:
                c.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return
        if not _establish(c, up, f"{host}:{port}", self._log):
            return
        c.settimeout(None); up.settimeout(None)
        n_up, n_down = 0, 0
        try:
            n_up, n_down = _pump(c, up, rest)
        except OSError:
            pass
        finally:
            self._log("allow", f"{host}:{port}", "", n_up, n_down)
            up.close()

    def _log(self, decision, target, reason, up=0, down=0):
        print(f"egress-proxy: decision={decision} target={target} reason={reason} up={up} down={down}",
              file=self.server.log, flush=True)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(listen, allow, log=sys.stderr):
    host, _, port = listen.rpartition(":")
    srv = _Server((host, int(port)), _Handler)
    srv.allow, srv.log = allow, log
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", required=True)
    ap.add_argument("--allow", action="append", required=True)
    a = ap.parse_args(argv)
    srv = serve(a.listen, parse_allow(a.allow))
    srv.serve_forever()


if __name__ == "__main__":
    main()
