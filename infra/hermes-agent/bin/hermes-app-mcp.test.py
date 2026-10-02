#!/usr/bin/env python3
import importlib.util, io, json, os, queue, shutil, subprocess, sys, tempfile, threading, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("mcp", os.path.join(HERE, "hermes-app-mcp.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")


class T(unittest.TestCase):
    def setUp(self):
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        self.t = [0.0]
        self.s = M.Server(MAN, self.spool, sleep=lambda s: self.t.__setitem__(0, self.t[0] + s),
                          clock=lambda: self.t[0])

    def call(self, name, **args):
        r = self.s.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})
        return r["result"]

    def test_initialize_echoes_supported_version(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_exactly_three_tools(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(sorted(t["name"] for t in r["result"]["tools"]),
                         ["ads_audit_list", "ads_audit_run", "ads_audit_status"])

    def test_run_writes_a_valid_request_and_returns_pending(self):
        res = self.call("ads_audit_run", client="acme-dental")
        body = json.loads(res["content"][0]["text"])
        self.assertEqual(body["status"], "pending"); self.assertFalse(res["isError"])
        names = os.listdir(os.path.join(self.spool, "requests"))
        self.assertEqual(len(names), 1)
        with open(os.path.join(self.spool, "requests", names[0]), "rb") as f:
            req = A.parse_request(f.read(), names[0], MAN)
        self.assertEqual((req["op"], req["client"]), ("run", "acme-dental"))
        self.assertGreaterEqual(self.t[0], 300)            # waited the manifest's run budget

    def test_run_returns_the_result_when_it_appears(self):
        def sleep(s):
            names = os.listdir(os.path.join(self.spool, "requests"))
            rid = names[0][:-5]
            A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                                A.refused_result(rid, "run", "acme-dental", "quota"))
        self.s.sleep = sleep
        body = json.loads(self.call("ads_audit_run", client="acme-dental")["content"][0]["text"])
        self.assertEqual((body["status"], body["reason"]), ("refused", "quota"))

    def test_bad_slug_is_an_error_and_files_nothing(self):
        res = self.call("ads_audit_run", client="../etc")
        self.assertTrue(res["isError"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])

    def test_trailing_newline_is_not_a_slug_or_request_id(self):
        self.assertTrue(self.call("ads_audit_run", client="acme-dental\n")["isError"])
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertTrue(self.call("ads_audit_status",
                                  request_id="0f8e2c1a-1111-4222-8333-444455556666\n")["isError"])

    def test_status_never_files_a_request(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        body = json.loads(self.call("ads_audit_status", request_id=rid)["content"][0]["text"])
        self.assertEqual(body, {"status": "pending", "request_id": rid})
        self.assertEqual(os.listdir(os.path.join(self.spool, "requests")), [])
        self.assertTrue(self.call("ads_audit_status", request_id="../x")["isError"])

    def test_garbage_result_file_is_pending_not_a_crash(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        for junk in (b"not json {{", b"[1, 2]", b"\xff\xfe", b'"str"'):
            with open(os.path.join(self.spool, "results", rid + ".json"), "wb") as f:
                f.write(junk)
            body = json.loads(self.call("ads_audit_status", request_id=rid)["content"][0]["text"])
            self.assertEqual(body, {"status": "pending", "request_id": rid}, junk)

    def test_status_returns_a_present_result_verbatim(self):
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        A.write_json_atomic(os.path.join(self.spool, "results"), rid + ".json",
                            A.refused_result(rid, "run", "acme-dental", "quota"))
        res = self.call("ads_audit_status", request_id=rid)
        body = json.loads(res["content"][0]["text"])
        self.assertEqual((body["status"], body["reason"]), ("refused", "quota"))
        self.assertFalse(res["isError"])               # a refusal is never a retryable error

    def test_unknown_method_and_tool(self):
        self.assertEqual(self.s.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})["error"]["code"], -32601)
        self.assertTrue(self.call("delete_everything")["isError"])


class StdioLoop(unittest.TestCase):
    def run_main(self, lines, boom=False):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "spool", "ads-audit", "requests"))
        os.makedirs(os.path.join(d, "spool", "ads-audit", "results"))
        mdir = os.path.join(d, "man")
        os.makedirs(mdir)
        shutil.copy(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), mdir)
        old = sys.stdin, sys.stdout, M.Server.handle
        sys.stdin, sys.stdout = io.StringIO("".join(l + "\n" for l in lines)), io.StringIO()
        if boom:
            def handle(self, msg):
                raise RuntimeError("boom")
            M.Server.handle = handle
        try:
            M.main(["--app", "ads-audit", "--manifest-dir", mdir, "--spool-root", os.path.join(d, "spool")])
            return [json.loads(l) for l in sys.stdout.getvalue().splitlines()]
        finally:
            sys.stdin, sys.stdout, M.Server.handle = old

    def test_non_dict_lines_do_not_kill_the_loop(self):
        out = self.run_main(["[1,2]", "5", '"x"', "null", "garbage",
                             json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})])
        self.assertEqual(out[-1], {"jsonrpc": "2.0", "id": 9, "result": {}})
        self.assertEqual([o["error"]["code"] for o in out[:-1]], [-32600] * 4 + [-32700])

    def test_exception_in_handle_is_internal_error_and_loop_survives(self):
        out = self.run_main([json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}),
                             json.dumps({"jsonrpc": "2.0", "method": "notifications/x"}),
                             json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"})], boom=True)
        self.assertEqual([(o["id"], o["error"]["code"]) for o in out], [(4, -32603), (5, -32603)])

class Concurrency(unittest.TestCase):
    """serve() with real threads, the real clock and a real spool: the read loop must stay free
    while a call waits. Nothing here synchronises on a bare sleep: every wait has a deadline."""
    def setUp(self):
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)
        for d in ("requests", "results"):
            os.makedirs(os.path.join(self.spool, d))
        self.s = M.Server(MAN, self.spool, poll=0.05)
        self.cond, self.lines = threading.Condition(), []
        self.q, self.th, self.raised = queue.Queue(), None, []
        self.before = set(threading.enumerate())
        self.err, self.old_err = io.StringIO(), sys.stderr
        sys.stderr = self.err                          # a thread's traceback would land here
        self.addCleanup(self.finish)

    def extra_threads(self):
        return [t for t in threading.enumerate() if t not in self.before]

    def finish(self):
        """EOF, answer whatever still waits, and leave no thread and no stderr noise behind."""
        self.q.put(None)
        deadline = time.monotonic() + 5
        while self.extra_threads() and time.monotonic() < deadline:
            for rid in self.requests():
                if not os.path.exists(os.path.join(self.spool, "results", rid + ".json")):
                    self.answer(rid)
            time.sleep(0.01)
        sys.stderr = self.old_err
        self.assertEqual(self.extra_threads(), [])
        self.assertEqual(self.err.getvalue(), "")
        self.assertEqual(self.raised, [])

    def feed(self):
        """serve's input: blocks on the queue, ends on None, raises a queued exception."""
        for item in iter(self.q.get, None):
            if isinstance(item, BaseException):
                raise item
            yield item

    def start(self, write=None, **kw):
        serve = M.serve

        def run():
            try:
                serve(self.s, self.feed(), write or self.write, **kw)
            except BaseException as e:                 # serve must never raise: finish() checks
                self.raised.append(e)
        self.th = threading.Thread(target=run)
        self.th.start()

    def write(self, text):
        with self.cond:
            self.lines.append(text)
            self.cond.notify_all()

    def send(self, mid, method, **params):
        self.q.put(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}) + "\n")

    def tool(self, mid, name, **args):
        self.send(mid, "tools/call", name=name, arguments=args)

    def ids(self):
        with self.cond:
            return [json.loads(l)["id"] for l in self.lines]

    def reply(self, mid, timeout=5):
        """The reply with this id, waiting for it up to `timeout`."""
        with self.cond:
            self.assertTrue(self.cond.wait_for(lambda: mid in self.ids(), timeout),
                            "no reply with id %r within %ss" % (mid, timeout))
            return next(r for r in map(json.loads, self.lines) if r["id"] == mid)

    def requests(self, spool=None):
        names = os.listdir(os.path.join(spool or self.spool, "requests"))
        return sorted(n[:-5] for n in names if not n.startswith("."))      # not the atomic write's temp file

    def until(self, pred, timeout=5):
        deadline = time.monotonic() + timeout
        while not pred():
            self.assertLess(time.monotonic(), deadline, "condition not met within %ss" % timeout)
            time.sleep(0.005)

    def answer(self, rid, spool=None, **extra):
        res = dict({"request_id": rid, "status": "ok", "ts": "2026-10-02T10:00:00Z"}, **extra)
        A.write_json_atomic(os.path.join(spool or self.spool, "results"), rid + ".json", res)
        return res

    def join_waiters(self):
        for t in self.extra_threads():
            if t is not self.th:
                t.join(5)

    def test_a_ping_is_answered_while_a_run_waits(self):
        self.start()
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        self.send(2, "ping")
        self.assertEqual(self.reply(2), {"jsonrpc": "2.0", "id": 2, "result": {}})
        self.assertEqual(self.ids(), [2])              # answered WHILE the run still waits
        res = self.answer(self.requests()[0])
        out = self.reply(1)["result"]
        self.assertFalse(out["isError"])
        self.assertEqual(json.loads(out["content"][0]["text"]), res)
        self.assertEqual(self.ids(), [2, 1])

    def test_inline_messages_keep_their_order(self):
        writers = []

        def write(text):
            writers.append(threading.current_thread())
            self.write(text)
        self.start(write=write)
        self.send(1, "initialize", protocolVersion="2025-06-18", capabilities={})
        self.send(2, "tools/list")
        self.send(3, "ping")
        self.tool(4, "ads_audit_status", request_id="0f8e2c1a-1111-4222-8333-444455556666")
        self.send(5, "resources/list")
        self.assertEqual(self.reply(5)["error"]["code"], -32601)
        self.assertEqual(self.ids(), [1, 2, 3, 4, 5])
        self.assertEqual(writers, [self.th] * 5)       # each answered by the read loop itself, no thread
        self.assertEqual(self.requests(), [])

    def test_concurrent_replies_never_interleave(self):
        mutex, stream, state = threading.Lock(), [], {"active": 0, "peak": 0, "calls": 0}

        def write(text):
            """A slow writer in two halves: without serve's lock the halves of two replies mix."""
            with mutex:
                state["active"] += 1; state["calls"] += 1
                state["peak"] = max(state["peak"], state["active"])
                first = state["calls"] == 1
                stream.append(text[:len(text) // 2])
            if first:
                time.sleep(0.2)                        # long enough for the other five to arrive
            with mutex:
                stream.append(text[len(text) // 2:])
                state["active"] -= 1
            self.write(text)
        self.start(write=write, max_waiting=8)
        for i in range(6):
            self.tool(i + 1, "ads_audit_list", client="client-%d" % i)
        self.until(lambda: len(self.requests()) == 6)
        for rid in self.requests():
            self.answer(rid, audits=[])
        with self.cond:
            self.assertTrue(self.cond.wait_for(lambda: len(self.lines) == 6, 5))
        for line in self.lines:
            self.assertTrue(line.endswith("\n")); self.assertEqual(line.count("\n"), 1)
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")
        self.assertEqual(sorted(self.ids()), [1, 2, 3, 4, 5, 6])
        self.assertEqual(state["peak"], 1)             # one writer at a time
        self.assertEqual(sorted(json.loads(l)["id"] for l in "".join(stream).splitlines()), [1, 2, 3, 4, 5, 6])

    def test_more_than_the_cap_is_refused_at_once(self):
        self.start(max_waiting=1)
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        self.tool(2, "ads_audit_run", client="other-dental")
        out = self.reply(2, timeout=2)["result"]
        self.assertTrue(out["isError"])
        self.assertIn("too many", json.loads(out["content"][0]["text"])["error"])
        self.assertEqual(self.ids(), [2])
        self.assertEqual(len(self.requests()), 1)      # refused, never queued: nothing was filed
        self.answer(self.requests()[0])
        self.assertFalse(self.reply(1)["result"]["isError"])
        self.join_waiters()                            # the finished call gave its place back
        self.tool(3, "ads_audit_list", client="acme-dental")
        self.until(lambda: len(self.requests()) == 2)

    def test_eof_while_a_call_waits_exits_cleanly(self):
        self.start()
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        rid = self.requests()[0]
        self.q.put(None)
        self.th.join(2)
        self.assertFalse(self.th.is_alive())           # serve returned without waiting for the call
        self.assertEqual(self.requests(), [rid])       # the filed request stays with the broker
        self.assertEqual(self.ids(), [])
        self.finish()                                  # asserts: nothing on stderr, nothing raised

    def test_a_write_error_does_not_raise(self):
        for exc in (BrokenPipeError(32, "Broken pipe"), ValueError("I/O operation on closed file")):
            with self.subTest(exc=exc):
                calls = []

                def write(text):
                    with self.cond:
                        calls.append(text)
                        self.cond.notify_all()
                    raise exc
                self.q = queue.Queue()
                self.start(write=write)
                self.send(1, "ping")
                self.send(2, "ping")                   # still reading after the first failed write
                with self.cond:
                    self.assertTrue(self.cond.wait_for(lambda: len(calls) == 2, 5))
                self.q.put(None)
                self.th.join(2)
                self.assertFalse(self.th.is_alive())
                self.assertEqual(self.raised, [])

    def test_no_reply_is_written_after_eof(self):
        self.start()
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        self.q.put(None)
        self.th.join(2)
        self.assertFalse(self.th.is_alive())
        self.answer(self.requests()[0])                # the result lands after the client has gone
        self.join_waiters()
        self.assertEqual(self.lines, [])               # a write here would race interpreter shutdown

    def test_no_reply_is_written_after_the_input_raises(self):
        boom = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")   # what bad stdin bytes raise
        self.start()
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        self.q.put(boom)
        self.th.join(2)
        self.assertFalse(self.th.is_alive())
        self.assertEqual(self.raised, [boom])          # it still comes out of serve, as before
        self.raised.clear()
        self.answer(self.requests()[0])
        self.join_waiters()
        self.assertEqual(self.lines, [])               # the same shutdown race as after EOF

    def test_eof_waits_for_a_reply_being_written(self):
        entered, go = threading.Event(), threading.Event()

        def write(text):
            entered.set()
            go.wait(5)
            self.write(text)
        self.start(write=write)
        self.tool(1, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)
        self.answer(self.requests()[0])
        self.assertTrue(entered.wait(5))               # the call's thread is inside write()
        self.q.put(None)
        self.th.join(0.2)
        self.assertTrue(self.th.is_alive())            # serve never returns over a half-written reply
        go.set()
        self.th.join(2)
        self.assertFalse(self.th.is_alive())
        self.assertEqual(self.ids(), [1])

    def test_a_thread_that_cannot_start_is_a_refusal_and_frees_its_place(self):
        real = M.threading.Thread

        class NoThread:
            def __init__(self, *a, **kw):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")
        self.start(max_waiting=1)
        # M.threading IS the threading module, so this replaces Thread for the whole process until
        # it is put back below (and again in cleanup). Start no thread from the test in that window.
        M.threading.Thread = NoThread
        self.addCleanup(setattr, M.threading, "Thread", real)
        self.tool(1, "ads_audit_run", client="acme-dental")
        out = self.reply(1)["result"]
        self.assertTrue(out["isError"])
        self.assertEqual(self.requests(), [])
        self.send(2, "ping")                           # the loop outlived it
        self.reply(2)
        M.threading.Thread = real
        self.tool(3, "ads_audit_run", client="acme-dental")
        self.until(lambda: len(self.requests()) == 1)  # and its place was given back

    def spawn(self, pump=True):
        """The real server process over a temp spool root; returns (process, spool, reply queue).
        Every deadline on the real process is 15 s: it only matters on a starved runner."""
        root = os.path.join(self.spool, "root")
        spool = os.path.join(root, "ads-audit")
        for d in ("requests", "results"):
            os.makedirs(os.path.join(spool, d))
        p = subprocess.Popen([sys.executable, os.path.join(HERE, "hermes-app-mcp.py"), "--app", "ads-audit",
                              "--manifest-dir", os.path.join(os.path.dirname(HERE), "registry/apps"),
                              "--spool-root", root],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, bufsize=1)
        out = queue.Queue()

        def read():
            for line in p.stdout:
                out.put(line)
        reader = threading.Thread(target=read if pump else lambda: None)
        reader.start()

        def reap():
            if p.poll() is None:
                p.kill()
            p.wait()
            reader.join(15)
            for f in (p.stdin, p.stdout, p.stderr):
                f.close()
        self.addCleanup(reap)
        return p, spool, out

    def line(self, out, timeout):
        try:
            return json.loads(out.get(timeout=timeout))
        except queue.Empty:
            self.fail("no reply from the server within %ss" % timeout)

    def test_real_process_answers_ping_during_a_run(self):
        p, spool, out = self.spawn()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "ads_audit_run", "arguments": {"client": "acme-dental"}}}) + "\n")
        self.until(lambda: len(self.requests(spool)) == 1, timeout=15)
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
        self.assertEqual(self.line(out, 15), {"jsonrpc": "2.0", "id": 2, "result": {}})
        res = self.answer(self.requests(spool)[0], spool)
        got = self.line(out, 15)                       # the real server polls every 2 s
        self.assertEqual(got["id"], 1)
        self.assertEqual(json.loads(got["result"]["content"][0]["text"]), res)
        p.stdin.close()
        self.assertEqual(p.wait(15), 0)
        self.assertEqual(p.stderr.read(), "")

    def test_real_process_exits_cleanly_with_a_call_waiting(self):
        p, spool, out = self.spawn()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "ads_audit_run", "arguments": {"client": "acme-dental"}}}) + "\n")
        self.until(lambda: len(self.requests(spool)) == 1, timeout=15)
        p.stdin.close()                                # the client hangs up; the waiting thread is a daemon
        self.assertEqual(p.wait(15), 0)
        self.assertEqual(p.stderr.read(), "")
        self.assertEqual(len(self.requests(spool)), 1)

    def test_real_process_exits_cleanly_after_the_client_closes_stdout(self):
        p, spool, _ = self.spawn(pump=False)
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "ads_audit_run", "arguments": {"client": "acme-dental"}}}) + "\n")
        self.until(lambda: len(self.requests(spool)) == 1, timeout=15)
        p.stdout.close()
        for i in (2, 3):                               # each reply is written into a closed pipe
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "ping"}) + "\n")
        p.stdin.close()
        self.assertEqual(p.wait(15), 0)
        self.assertEqual(p.stderr.read(), "")          # not even "Exception ignored while flushing sys.stdout"
        self.assertEqual(len(self.requests(spool)), 1)


if __name__ == "__main__":
    unittest.main()
