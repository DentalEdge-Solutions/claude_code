#!/usr/bin/env python3
import importlib.util, io, os, socket, socketserver, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("egp", os.path.join(HERE, "egress-proxy.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

ALLOW = P.parse_allow(["api.anthropic.com:443"])


class TestDecide(unittest.TestCase):
    def head(self, line):
        return line + "\r\nHost: x\r\n"

    def test_allowed_host_exactly(self):
        self.assertEqual(P.decide(self.head("CONNECT api.anthropic.com:443 HTTP/1.1"), ALLOW),
                         ("api.anthropic.com", 443))

    def test_case_and_trailing_dot_normalised(self):
        self.assertEqual(P.decide(self.head("CONNECT API.Anthropic.com.:443 HTTP/1.1"), ALLOW),
                         ("api.anthropic.com", 443))

    def test_refusals(self):
        cases = {
            "GET http://api.anthropic.com/ HTTP/1.1": "not-connect",
            "CONNECT api.anthropic.com:80 HTTP/1.1": "not-allowed",
            "CONNECT example.com:443 HTTP/1.1": "not-allowed",
            "CONNECT evil.api.anthropic.com:443 HTTP/1.1": "not-allowed",
            "CONNECT 1.2.3.4:443 HTTP/1.1": "ip-literal",
            "CONNECT [::1]:443 HTTP/1.1": "ip-literal",
            "CONNECT api.anthropic.com HTTP/1.1": "bad-target",
            "CONNECT api.anthropic.com:44x HTTP/1.1": "bad-target",
            "CONNECT api.anthropic.com:443": "not-connect",
        }
        for line, reason in cases.items():
            with self.subTest(line=line):
                with self.assertRaises(P.Refused) as cm:
                    P.decide(self.head(line), ALLOW)
                self.assertEqual(cm.exception.reason, reason)

    def test_parse_allow_rejects_garbage(self):
        for bad in ("api.anthropic.com", ":443", "host:port"):
            with self.assertRaises(ValueError):
                P.parse_allow([bad])


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


class TestLoopback(unittest.TestCase):
    """A real proxy on 127.0.0.1 in front of a real echo server. 'localhost' is the allowed
name, so the ip-literal rule is exercised on the refused path and not on the allowed one."""
    def setUp(self):
        self.echo = socketserver.TCPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=self.echo.serve_forever, daemon=True).start()
        self.eport = self.echo.server_address[1]
        self.log = io.StringIO()
        self.proxy = P.serve("127.0.0.1:0", P.parse_allow([f"localhost:{self.eport}"]), log=self.log)
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()
        self.pport = self.proxy.server_address[1]

    def tearDown(self):
        for s in (self.proxy, self.echo):
            s.shutdown(); s.server_close()

    def ask(self, line, then=b""):
        c = socket.create_connection(("127.0.0.1", self.pport), timeout=5)
        c.sendall(line.encode() + b"\r\nHost: x\r\n\r\n")
        status = c.recv(1024)
        body = b""
        if then:
            c.sendall(then); body = c.recv(1024)
        c.close()
        return status, body

    def test_allowed_tunnel_carries_bytes(self):
        status, body = self.ask(f"CONNECT localhost:{self.eport} HTTP/1.1", then=b"hi")
        self.assertTrue(status.startswith(b"HTTP/1.1 200"), status)
        self.assertEqual(body, b"echo:hi")

    def test_ip_literal_refused_403_and_logged_without_content(self):
        status, _ = self.ask(f"CONNECT 127.0.0.1:{self.eport} HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
        self.assertIn("decision=deny", self.log.getvalue())
        self.assertIn("reason=ip-literal", self.log.getvalue())

    def test_hostile_target_is_not_echoed_into_the_log(self):
        self.ask("CONNECT evil\x1b[31m.example:443 HTTP/1.1")
        self.assertNotIn("\x1b", self.log.getvalue())
        self.assertIn("target=invalid", self.log.getvalue())

    def test_oversized_header_refused(self):
        c = socket.create_connection(("127.0.0.1", self.pport), timeout=5)
        c.sendall(b"CONNECT localhost:1 HTTP/1.1\r\nX: " + b"a" * 9000)
        self.assertTrue(c.recv(1024).startswith(b"HTTP/1.1 403"))
        c.close()


if __name__ == "__main__":
    unittest.main()
