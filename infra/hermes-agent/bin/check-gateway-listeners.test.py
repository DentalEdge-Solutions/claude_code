#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, stat, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gateway_listeners as GL
spec = importlib.util.spec_from_file_location("cgl", os.path.join(HERE, "check-gateway-listeners.py"))
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

GW = "a" * 64
TCP_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
TCP6_HEADER = "  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
DNS4 = "   0: 0B00007F:8693 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 5 1 0 100 0 0 10 0\n"
DASH4 = "   1: 00000000:239F 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10000 0 6 1 0 100 0 0 10 0\n"
API4 = "   2: 0100007F:21C2 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10000 0 7 1 0 100 0 0 10 0\n"
ESTAB4 = "   3: 020012AC:D2F4 030012AC:01BB 01 00000000:00000000 00:00000000 00000000 10000 0 8 1 0 100 0 0 10 0\n"
HEALTHY = TCP_HEADER + DNS4 + DASH4 + ESTAB4 + TCP6_HEADER


def runner(ps=(0, GW + "\n", ""), cat=(0, HEALTHY, "")):
    calls = []

    def run(argv, timeout=30):
        calls.append(argv)
        return ps if argv[:2] == ["docker", "ps"] else cat
    run.calls = calls
    return run


class TestParse(unittest.TestCase):
    def test_the_box_as_reviewed(self):
        self.assertEqual(GL.parse(HEALTHY), ([9119], 1))

    def test_an_established_connection_is_not_a_listener(self):
        self.assertEqual(GL.parse(TCP_HEADER + ESTAB4 + TCP6_HEADER), ([], 0))

    def test_not_two_tables_or_a_bad_row_raises(self):
        for text in ("", "not a table\n", TCP_HEADER + DASH4, TCP_HEADER + "   0: garbage\n" + TCP6_HEADER,
                     DASH4 + TCP_HEADER + TCP6_HEADER):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                GL.parse(text)

    def test_8642_is_not_an_allowed_port(self):
        self.assertEqual(GL.ALLOWED_PORTS, (9119,))


class TestMeasure(unittest.TestCase):
    def test_healthy(self):
        run = runner()
        self.assertEqual(C.measure(run), {"status": "ok", "reason": "-", "listeners": [9119],
                                          "unexpected": [], "docker_dns_listeners": 1})
        self.assertEqual(run.calls[1], ["docker", "exec", GW, "cat", "/proc/net/tcp", "/proc/net/tcp6"])

    def test_the_dashboard_off_is_healthy(self):
        r = C.measure(runner(cat=(0, TCP_HEADER + DNS4 + TCP6_HEADER, "")))
        self.assertEqual((r["status"], r["listeners"]), ("ok", []))

    def test_the_api_server_port_is_an_alert(self):
        r = C.measure(runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, "")))
        self.assertEqual((r["status"], r["reason"], r["listeners"], r["unexpected"]),
                         ("alert", "unexpected-port", [8642, 9119], [8642]))

    def test_a_docker_dns_count_other_than_one_is_an_alert(self):
        for cat, n in ((TCP_HEADER + DASH4 + TCP6_HEADER, 0), (TCP_HEADER + DNS4 + DNS4.replace("8693", "8694") + DASH4 + TCP6_HEADER, 2)):
            with self.subTest(n=n):
                r = C.measure(runner(cat=(0, cat, "")))
                self.assertEqual((r["status"], r["reason"], r["docker_dns_listeners"], r["unexpected"]),
                                 ("alert", "docker-dns", n, []))

    def test_no_single_gateway_is_could_not_check_never_an_alert(self):
        for ps in ((0, "", ""), (0, GW + "\n" + "b" * 64 + "\n", ""), (1, "", "Cannot connect to the Docker daemon"),
                   (124, "", "")):
            with self.subTest(ps=ps):
                run = runner(ps=ps)
                r = C.measure(run)
                self.assertEqual((r["status"], r["reason"], r["listeners"]),
                                 ("could-not-check", "no-gateway", "could-not-check"))
                self.assertEqual(len(run.calls), 1)                 # nothing is exec'd into

    def test_a_failed_exec_and_unparsable_output(self):
        self.assertEqual(C.measure(runner(cat=(1, "", "container is not running")))["reason"], "exec-failed")
        for out in ("", "garbage\n", TCP_HEADER + DASH4):
            with self.subTest(out=out[:10]):
                r = C.measure(runner(cat=(0, out, "")))
                self.assertEqual((r["status"], r["reason"]), ("could-not-check", "unparsable"))


class TestRecordAndMain(unittest.TestCase):
    def setUp(self):
        self.d = os.path.join(tempfile.mkdtemp(), "listener-check")

    def main(self, argv=(), run=None, now="2026-10-07T12:00:00Z"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = C.main(list(argv), run=run or runner(), state_dir=self.d, now=now)
        return rc, out.getvalue()

    def read(self, name):
        with open(os.path.join(self.d, name)) as f:
            return f.read()

    def test_a_healthy_run_writes_last_and_history_and_exits_0(self):
        rc, text = self.main()
        self.assertEqual(rc, 0)
        self.assertEqual(text, "hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[] "
                               "docker_dns_listeners=1\n")
        last = json.loads(self.read("last.json"))
        self.assertEqual(last, {"ts": "2026-10-07T12:00:00Z", "status": "ok", "reason": "-", "listeners": [9119],
                                "unexpected": [], "docker_dns_listeners": 1})
        self.assertEqual([json.loads(l) for l in self.read("history.jsonl").splitlines()], [last])
        self.assertFalse(os.path.exists(os.path.join(self.d, "ALERT")))
        self.assertEqual(stat.S_IMODE(os.stat(self.d).st_mode), 0o700)
        for name in ("last.json", "history.jsonl"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.d, name)).st_mode), 0o600, name)
        self.assertEqual(sorted(os.listdir(self.d)), ["history.jsonl", "last.json"])    # no temporary file left

    def test_an_alert_exits_1_and_keeps_the_first_alert(self):
        bad = runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, ""))
        rc, text = self.main(run=bad, now="2026-10-07T12:00:00Z")
        self.assertEqual(rc, 1)
        self.assertIn("status=alert reason=unexpected-port listeners=[8642, 9119] unexpected=[8642]", text)
        first = json.loads(self.read("ALERT"))
        self.assertEqual(first, {"since": "2026-10-07T12:00:00Z", "reason": "unexpected-port",
                                 "unexpected": [8642], "docker_dns_listeners": 1})
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.d, "ALERT")).st_mode), 0o600)
        worse = runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + API4.replace("21C2", "1F90") + TCP6_HEADER, ""))
        self.main(run=worse, now="2026-10-07T12:15:00Z")
        self.assertEqual(json.loads(self.read("ALERT")), first)                         # never overwritten
        self.main(now="2026-10-07T12:30:00Z")                                           # healthy again
        self.assertEqual(json.loads(self.read("ALERT")), first)                         # and never removed by a run
        self.assertEqual([json.loads(l)["status"] for l in self.read("history.jsonl").splitlines()],
                         ["alert", "alert", "ok"])

    def test_could_not_check_exits_2_and_is_no_alert(self):
        rc, text = self.main(run=runner(ps=(0, "", "")))
        self.assertEqual(rc, 2)
        self.assertIn("status=could-not-check reason=no-gateway", text)
        self.assertFalse(os.path.exists(os.path.join(self.d, "ALERT")))

    def test_the_history_is_capped(self):
        os.makedirs(self.d)
        with open(os.path.join(self.d, "history.jsonl"), "w") as f:
            f.write("".join(json.dumps({"ts": "x", "status": "ok", "n": i}) + "\n" for i in range(C.HISTORY_KEEP)))
        self.main()
        lines = self.read("history.jsonl").splitlines()
        self.assertEqual(len(lines), C.HISTORY_KEEP)
        self.assertEqual(json.loads(lines[0])["n"], 1)                                  # the oldest one went
        self.assertEqual(json.loads(lines[-1])["ts"], "2026-10-07T12:00:00Z")

    def test_nothing_written_or_printed_carries_an_address_or_another_field(self):
        _, text = self.main(run=runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + ESTAB4 + TCP6_HEADER, "")))
        blob = text + self.read("last.json") + self.read("history.jsonl") + self.read("ALERT")
        for fragment in ("0B00007F", "0100007F", "020012AC", "030012AC", "34451", "54004", "443", "10000", GW):
            self.assertNotIn(fragment, blob, fragment)

    def test_status_is_ok_only_for_a_fresh_ok_with_no_alert(self):
        self.main(now="2026-10-07T12:00:00Z")
        rc, text = self.main(["--status"], now="2026-10-07T12:44:59Z")
        self.assertEqual(rc, 0)
        self.assertIn("listener check: OK", text)
        s = json.loads(text[:text.rindex("listener check:")])
        self.assertEqual((s["last"]["status"], s["last_age_seconds"], s["alert_present"], s["history_counts"]),
                         ("ok", 2699, False, {"ok": 1}))
        rc, text = self.main(["--status"], now="2026-10-07T12:45:01Z")                  # the timer has stopped
        self.assertEqual(rc, 1)
        self.assertIn("LOOK AT THIS", text)

    def test_status_before_any_run_and_with_a_damaged_file(self):
        rc, text = self.main(["--status"])
        self.assertEqual(rc, 1)
        s = json.loads(text[:text.rindex("listener check:")])
        self.assertEqual((s["last"], s["last_age_seconds"], s["alert_present"], s["history_counts"]),
                         (None, None, False, {}))
        os.makedirs(self.d)
        with open(os.path.join(self.d, "last.json"), "w") as f:
            f.write("{not json")
        rc, text = self.main(["--status"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(text[:text.rindex("listener check:")])["last"], "could-not-check")

    def test_status_reads_only(self):
        self.main()
        before = {n: self.read(n) for n in os.listdir(self.d)}
        self.main(["--status"])
        self.assertEqual({n: self.read(n) for n in os.listdir(self.d)}, before)

    def test_an_alert_keeps_status_unhealthy_until_it_is_cleared(self):
        self.main(run=runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, "")), now="2026-10-07T11:00:00Z")
        self.main(now="2026-10-07T12:00:00Z")                                           # healthy again
        rc, text = self.main(["--status"], now="2026-10-07T12:01:00Z")
        self.assertEqual(rc, 1)
        s = json.loads(text[:text.rindex("listener check:")])
        self.assertEqual((s["alert_present"], s["alert"]["since"], s["alert"]["unexpected"]),
                         (True, "2026-10-07T11:00:00Z", [8642]))
        rc, text = self.main(["--clear-alert"], now="2026-10-07T12:02:00Z")
        self.assertEqual((rc, text), (0, "hermes-listener-check: alert cleared\n"))
        self.assertFalse(os.path.exists(os.path.join(self.d, "ALERT")))
        self.assertEqual(json.loads(self.read("history.jsonl").splitlines()[-1]),
                         {"ts": "2026-10-07T12:02:00Z", "status": "alert-cleared"})
        rc, text = self.main(["--status"], now="2026-10-07T12:03:00Z")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(text[:text.rindex("listener check:")])["history_counts"],
                         {"alert": 1, "ok": 1, "alert-cleared": 1})
        self.assertEqual(self.main(["--clear-alert"])[1], "hermes-listener-check: no alert to clear\n")

    def test_status_and_clear_alert_run_nothing(self):
        run = runner()
        self.main(["--status"], run=run)
        self.main(["--clear-alert"], run=run)
        self.assertEqual(run.calls, [])


if __name__ == "__main__":
    unittest.main()
