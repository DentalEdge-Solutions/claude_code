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

    def test_port_with_superscript_digits_rejected(self):
        """Finding 1: superscript digits pass isdigit() but fail int()"""
        with self.assertRaises(P.Refused) as cm:
            P.decide(self.head("CONNECT api.anthropic.com:4²3 HTTP/1.1"), ALLOW)
        self.assertEqual(cm.exception.reason, "bad-target")

    def test_port_zero_rejected(self):
        """Finding 1: port 0 is invalid"""
        with self.assertRaises(P.Refused) as cm:
            P.decide(self.head("CONNECT api.anthropic.com:0 HTTP/1.1"), ALLOW)
        self.assertEqual(cm.exception.reason, "bad-target")

    def test_port_too_large_rejected(self):
        """Finding 1: port > 65535 is invalid"""
        with self.assertRaises(P.Refused) as cm:
            P.decide(self.head("CONNECT api.anthropic.com:70000 HTTP/1.1"), ALLOW)
        self.assertEqual(cm.exception.reason, "bad-target")


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


class AbruptClose(socketserver.BaseRequestHandler):
    """Finding 2: server that closes abruptly without echoing"""
    def handle(self):
        self.request.close()


class TestLoopback(unittest.TestCase):
    """A real proxy on 127.0.0.1 in front of a real echo server. 'localhost' is the allowed
name, so the ip-literal rule is exercised on the refused path and not on the allowed one."""
    def setUp(self):
        self.echo = socketserver.TCPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=self.echo.serve_forever, daemon=True).start()
        self.eport = self.echo.server_address[1]

        # Pre-allocate port for abrupt close test
        self.abrupt_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.abrupt_socket.bind(("127.0.0.1", 0))
        self.aport = self.abrupt_socket.getsockname()[1]

        self.log = io.StringIO()
        # Allow echo port, abrupt port, and unused port for upstream-unreachable test
        self.proxy = P.serve("127.0.0.1:0", P.parse_allow([f"localhost:{self.eport}", f"localhost:{self.aport}", "localhost:54321"]), log=self.log)
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()
        self.pport = self.proxy.server_address[1]

    def tearDown(self):
        for s in (self.proxy, self.echo):
            s.shutdown(); s.server_close()
        try:
            self.abrupt_socket.close()
        except:
            pass

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
        # Finding 5: assert reason=header-too-large in log
        self.assertIn("reason=header-too-large", self.log.getvalue())
        c.close()

    def test_port_with_superscript_digit_refused_403_and_logged(self):
        """Finding 1: superscript digit port should get 403 and decision=deny log"""
        status, _ = self.ask(f"CONNECT localhost:4²3 HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
        log = self.log.getvalue()
        self.assertIn("decision=deny", log)
        self.assertIn("reason=bad-target", log)

    def test_port_zero_refused_403_and_logged(self):
        """Finding 1: port 0 should get 403 and decision=deny log"""
        status, _ = self.ask(f"CONNECT localhost:0 HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
        log = self.log.getvalue()
        self.assertIn("decision=deny", log)
        self.assertIn("reason=bad-target", log)

    def test_port_too_large_refused_403_and_logged(self):
        """Finding 1: port > 65535 should get 403 and decision=deny log"""
        status, _ = self.ask(f"CONNECT localhost:70000 HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
        log = self.log.getvalue()
        self.assertIn("decision=deny", log)
        self.assertIn("reason=bad-target", log)

    def test_upstream_unreachable_502_and_logged(self):
        """Finding 5: upstream with nothing listening should get 502 and reason=upstream-unreachable"""
        # Use a port that's allowed but nothing is listening
        status, _ = self.ask(f"CONNECT localhost:54321 HTTP/1.1")
        self.assertTrue(status.startswith(b"HTTP/1.1 502"), status)
        log = self.log.getvalue()
        self.assertIn("decision=deny", log)
        self.assertIn("reason=upstream-unreachable", log)

    def test_upstream_close_logs_allow_once(self):
        """Finding 2: when upstream closes abruptly, allow line must still be logged"""
        # Set up a server that closes immediately on the pre-allocated port
        self.abrupt_socket.close()  # Close the placeholder socket first
        abrupt = socketserver.TCPServer(("127.0.0.1", self.aport), AbruptClose)
        threading.Thread(target=abrupt.serve_forever, daemon=True).start()

        self.log.truncate(0)  # Clear log
        self.log.seek(0)

        # Connect to proxy with allowed abrupt-close server
        c = socket.create_connection(("127.0.0.1", self.pport), timeout=5)
        c.sendall(f"CONNECT localhost:{self.aport} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        # Should get 200 Established before the close is noticed
        status = c.recv(1024)
        self.assertTrue(status.startswith(b"HTTP/1.1 200"), status)
        c.close()

        abrupt.shutdown()
        abrupt.server_close()

        # Should see exactly one decision=allow line
        log = self.log.getvalue()
        allow_count = log.count("decision=allow")
        self.assertEqual(allow_count, 1, f"Expected 1 allow line, got {allow_count}:\n{log}")

    def test_log_injection_with_newline_in_target(self):
        """Finding 4: hostile target with newline should not create extra log lines"""
        self.ask("CONNECT evil\nfake:443 HTTP/1.1")
        log = self.log.getvalue()
        self.assertIn("target=invalid", log)
        # Count decision lines - should be exactly 1
        lines = [l for l in log.split('\n') if 'decision=' in l]
        self.assertEqual(len(lines), 1, f"Expected 1 decision line, got {len(lines)}:\n{log}")


if __name__ == "__main__":
    unittest.main()
