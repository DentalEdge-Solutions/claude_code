#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, stat, sys, tempfile, unittest, unittest.mock
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


PID = 4242


def runner(ps=(0, GW + "\n", ""), cat=(0, HEALTHY, ""), inspect=(0, f"{PID} true\n", "")):
    """A fake Docker CLI and a fake host /proc. `cat` is (rc, text): what reading the gateway's two
    tables on the host gives (a non-zero rc is an OSError). `inspect` is one answer, or a list
    of answers given in turn."""
    calls, answers, read = [], list(inspect) if isinstance(inspect, list) else None, []

    def run(argv, timeout=30):
        calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            return ps
        if argv[:2] == ["docker", "inspect"]:
            return answers.pop(0) if answers else inspect
        return (127, "", "not found")

    def read_tables(pid):
        read.append(pid)
        if cat[0] != 0:
            raise PermissionError(13, "Permission denied")
        return cat[1]
    run.calls, run.read_tables, run.read = calls, read_tables, read
    return run


def measure(run):
    return C.measure(run, run.read_tables)


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
        self.assertEqual(measure(run), {"status": "ok", "reason": "-", "listeners": [9119],
                                          "unexpected": [], "docker_dns_listeners": 1})
        # The pid comes from Docker, the tables from the HOST's /proc, and Docker is asked again
        # afterwards. Nothing is run inside the container: no `docker exec`.
        ask = ["docker", "inspect", "--format", "{{.State.Pid}} {{.State.Running}}", GW]
        self.assertEqual(run.calls[1:], [ask, ask])
        self.assertEqual(run.read, [PID])
        self.assertFalse([c for c in run.calls if "exec" in c])

    def test_the_real_reader_reads_the_host_proc_of_that_pid_and_nothing_else(self):
        opened = []

        class F(io.StringIO):
            def __exit__(self, *a):
                return False

        def fake_open(path, **kw):
            opened.append(path)
            return F(TCP_HEADER if path.endswith("/tcp") else TCP6_HEADER)
        with unittest.mock.patch("builtins.open", fake_open):
            self.assertEqual(C._read_tables(PID), TCP_HEADER + TCP6_HEADER)
        self.assertEqual(opened, [f"/proc/{PID}/net/tcp", f"/proc/{PID}/net/tcp6"])

    def test_the_dashboard_off_is_healthy(self):
        r = measure(runner(cat=(0, TCP_HEADER + DNS4 + TCP6_HEADER, "")))
        self.assertEqual((r["status"], r["listeners"]), ("ok", []))

    def test_the_api_server_port_is_an_alert(self):
        r = measure(runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, "")))
        self.assertEqual((r["status"], r["reason"], r["listeners"], r["unexpected"]),
                         ("alert", "unexpected-port", [8642, 9119], [8642]))

    def test_a_docker_dns_count_other_than_one_is_an_alert(self):
        for cat, n in ((TCP_HEADER + DASH4 + TCP6_HEADER, 0), (TCP_HEADER + DNS4 + DNS4.replace("8693", "8694") + DASH4 + TCP6_HEADER, 2)):
            with self.subTest(n=n):
                r = measure(runner(cat=(0, cat, "")))
                self.assertEqual((r["status"], r["reason"], r["docker_dns_listeners"], r["unexpected"]),
                                 ("alert", "docker-dns", n, []))

    def test_no_single_gateway_is_could_not_check_never_an_alert(self):
        for ps in ((0, "", ""), (0, GW + "\n" + "b" * 64 + "\n", ""), (1, "", "Cannot connect to the Docker daemon"),
                   (124, "", "")):
            with self.subTest(ps=ps):
                run = runner(ps=ps)
                r = measure(run)
                self.assertEqual((r["status"], r["reason"], r["listeners"]),
                                 ("could-not-check", "no-gateway", "could-not-check"))
                self.assertEqual((len(run.calls), run.read), (1, []))       # nothing more is asked or read

    def test_no_pid_is_could_not_check(self):
        for inspect in ((1, "", "No such object"), (0, "0 false\n", ""), (0, f"{PID} false\n", ""), (0, "1 true\n", ""),
                        (0, "garbage\n", ""), (0, "", ""), (0, f"{PID} true extra\n", "")):
            with self.subTest(inspect=inspect):
                run = runner(inspect=inspect)
                r = measure(run)
                self.assertEqual((r["status"], r["reason"], run.read), ("could-not-check", "no-pid", []))

    def test_a_gateway_that_restarted_while_we_read_is_could_not_check_never_an_alert(self):
        """The pid may be another process's by then: its tables (here the host's, with sshd and an
        API port) must not be judged as the gateway's."""
        for second in ((0, f"{PID + 1} true\n", ""), (0, "0 false\n", ""), (1, "", "No such object")):
            with self.subTest(second=second):
                run = runner(cat=(0, TCP_HEADER + API4 + TCP6_HEADER, ""), inspect=[(0, f"{PID} true\n", ""), second])
                r = measure(run)
                self.assertEqual((r["status"], r["reason"], r["unexpected"]),
                                 ("could-not-check", "gateway-changed", "could-not-check"))

    def test_an_unreadable_proc_and_unparsable_output(self):
        self.assertEqual(measure(runner(cat=(1, "", "")))["reason"], "proc-unreadable")
        for out in ("", "garbage\n", TCP_HEADER + DASH4):
            with self.subTest(out=out[:10]):
                r = measure(runner(cat=(0, out, "")))
                self.assertEqual((r["status"], r["reason"]), ("could-not-check", "unparsable"))


class TestRecordAndMain(unittest.TestCase):
    def setUp(self):
        self.d = os.path.join(tempfile.mkdtemp(), "listener-check")

    def main(self, argv=(), run=None, now="2026-10-07T12:00:00Z"):
        out, run = io.StringIO(), run or runner()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = C.main(list(argv), run=run, state_dir=self.d, now=now, read_tables=run.read_tables)
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
        self.assertEqual(sorted(os.listdir(self.d)), [".lock", "history.jsonl", "last.json"])   # no temporary file left

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
        self.assertEqual([(json.loads(l)["ts"], json.loads(l)["unexpected"]) for l in self.read("alerts.jsonl").splitlines()],
                         [("2026-10-07T12:00:00Z", [8642]), ("2026-10-07T12:15:00Z", [8080, 8642])])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.d, "alerts.jsonl")).st_mode), 0o600)

    def test_an_alert_and_its_clearing_outlive_the_history_cap(self):
        """The history keeps about a month. A review held later must still learn that something
        listened and that the marker was cleared: the alert log is never trimmed."""
        self.main(run=runner(cat=(0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, "")), now="2026-06-01T00:00:00Z")
        self.main(["--clear-alert"], now="2026-06-01T00:05:00Z")
        with open(os.path.join(self.d, "history.jsonl"), "w") as f:      # months of healthy runs later
            f.write("".join(json.dumps({"ts": "x", "status": "ok"}) + "\n" for _ in range(C.HISTORY_KEEP)))
        self.main(now="2026-10-07T12:00:00Z")
        rc, text = self.main(["--status"], now="2026-10-07T12:01:00Z")
        s = json.loads(text[:text.rindex("listener check:")])
        self.assertEqual(s["history_counts"], {"ok": C.HISTORY_KEEP})                   # the alert has aged out here
        self.assertEqual(s["alert_log"], {"alert": 1, "alert-cleared": 1, "?": 0,
                                          "first_ts": "2026-06-01T00:00:00Z", "last_ts": "2026-06-01T00:05:00Z"})
        self.assertEqual(rc, 0)                                                         # healthy now; the log is for the review

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
        blob = text + self.read("last.json") + self.read("history.jsonl") + self.read("ALERT") + self.read("alerts.jsonl")
        for fragment in ("0B00007F", "0100007F", "020012AC", "030012AC", "34451", "54004", "443", "10000", GW, str(PID)):
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
        self.assertEqual(s["alert_log"], {"alert": 0, "alert-cleared": 0, "?": 0, "first_ts": None, "last_ts": None})
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

    BAD = (0, TCP_HEADER + DNS4 + DASH4 + API4 + TCP6_HEADER, "")

    def test_an_alert_is_still_marked_and_logged_when_the_history_is_damaged(self):
        """The marker and the alert log are written first: a history file with a byte that is not
        UTF-8, or one that cannot be rewritten at all, must not stop them."""
        os.makedirs(self.d)
        with open(os.path.join(self.d, "history.jsonl"), "wb") as f:
            f.write(b'{"ts": "x", "status": "ok"}\n\xff\xfe not utf-8\n')
        with open(os.path.join(self.d, "alerts.jsonl"), "wb") as f:
            f.write(b"\xff damaged line\n")
        rc, text = self.main(run=runner(cat=self.BAD))
        self.assertEqual(rc, 1, text)
        self.assertEqual(json.loads(self.read("ALERT"))["unexpected"], [8642])
        self.assertEqual(json.loads(open(os.path.join(self.d, "alerts.jsonl"), "rb").read().splitlines()[-1])["unexpected"], [8642])
        rc, text = self.main(["--status"], now="2026-10-07T12:01:00Z")
        s = json.loads(text[:text.rindex("listener check:")])
        self.assertEqual((rc, s["alert_present"], s["alert_log"]["alert"], s["alert_log"]["?"]), (1, True, 1, 1))
        self.assertEqual(s["history_counts"], {"ok": 1, "?": 1, "alert": 1})

    def test_an_alert_is_marked_and_logged_even_when_the_history_cannot_be_written(self):
        real = C._append_history
        with unittest.mock.patch.object(C, "_append_history", side_effect=OSError(28, "No space left on device")):
            rc, text = self.main(run=runner(cat=self.BAD))
        self.assertEqual(rc, 2)                                        # the run failed: never the alert code by accident
        self.assertIn("status=could-not-check reason=internal-error error=OSError", text)
        self.assertTrue(os.path.exists(os.path.join(self.d, "ALERT")))
        self.assertEqual(len(self.read("alerts.jsonl").splitlines()), 1)
        self.assertIs(C._append_history, real)

    def test_an_unexpected_error_exits_2_never_the_alert_code(self):
        def boom(argv, timeout=15):
            raise RuntimeError("anything")
        boom.read_tables = lambda pid: ""
        rc, text = self.main(run=boom)
        self.assertEqual((rc, text), (2, "hermes-listener-check: status=could-not-check reason=internal-error error=RuntimeError\n"))

    def test_a_state_directory_that_is_a_file_or_a_symlink_is_refused_with_exit_2(self):
        parent = os.path.dirname(self.d)
        open(self.d, "w").close()
        self.assertEqual(self.main()[0], 2)
        os.unlink(self.d)
        elsewhere = os.path.join(parent, "elsewhere"); os.makedirs(elsewhere)
        os.symlink(elsewhere, self.d)
        rc, text = self.main(run=runner(cat=self.BAD))
        self.assertEqual(rc, 2)
        self.assertEqual(os.listdir(elsewhere), [])                    # nothing was written through the link

    def test_a_state_directory_with_a_wider_mode_is_put_back_to_0700(self):
        os.makedirs(self.d, mode=0o755); os.chmod(self.d, 0o755)
        self.main()
        self.assertEqual(stat.S_IMODE(os.stat(self.d).st_mode), 0o700)

    def test_the_alert_log_gets_one_line_per_event_not_one_per_run(self):
        for minute in ("00", "15", "30"):                              # the same alert, three runs
            self.main(run=runner(cat=self.BAD), now=f"2026-10-07T12:{minute}:00Z")
        self.assertEqual(len(self.read("alerts.jsonl").splitlines()), 1)
        self.assertEqual(len(self.read("history.jsonl").splitlines()), 3)
        self.main(now="2026-10-07T12:45:00Z")                          # healthy
        self.main(run=runner(cat=self.BAD), now="2026-10-07T13:00:00Z")    # the same port again, still not cleared
        self.assertEqual(len(self.read("alerts.jsonl").splitlines()), 1)
        self.main(["--clear-alert"], now="2026-10-07T13:05:00Z")
        self.main(run=runner(cat=self.BAD), now="2026-10-07T13:15:00Z")    # after a clearing it is a new event
        self.assertEqual([json.loads(l)["status"] for l in self.read("alerts.jsonl").splitlines()],
                         ["alert", "alert-cleared", "alert"])

    def test_clear_alert_logs_the_clearing_before_the_marker_goes(self):
        self.main(run=runner(cat=self.BAD), now="2026-10-07T11:00:00Z")
        with unittest.mock.patch.object(C, "_append_alert_log", side_effect=OSError(28, "No space left on device")):
            rc, text = self.main(["--clear-alert"])
        self.assertEqual(rc, 2)
        self.assertTrue(os.path.exists(os.path.join(self.d, "ALERT")))     # not cleared without a line saying so

    def test_a_failed_write_leaves_no_temporary_file(self):
        with unittest.mock.patch.object(C.os, "replace", side_effect=OSError(5, "Input/output error")):
            self.assertEqual(self.main()[0], 2)
        self.assertEqual([n for n in os.listdir(self.d) if ".tmp." in n], [])

    def test_a_result_exactly_45_minutes_old_or_from_the_future_is_not_healthy(self):
        self.main(now="2026-10-07T12:00:00Z")
        for now, age in (("2026-10-07T12:45:00Z", 2700), ("2026-10-07T11:00:00Z", -3600)):
            with self.subTest(age=age):
                rc, text = self.main(["--status"], now=now)
                self.assertEqual((rc, json.loads(text[:text.rindex("listener check:")])["last_age_seconds"]), (1, age))

    def test_the_real_docker_calls_together_fit_inside_the_units_start_timeout(self):
        import inspect
        per_call = inspect.signature(C._run_real).parameters["timeout"].default
        unit = open(os.path.join(os.path.dirname(HERE), "deploy", "hermes-listener-check.service")).read()
        limit = int(next(l.split("=")[1] for l in unit.splitlines() if l.startswith("TimeoutStartSec=")))
        self.assertLess(3 * per_call, limit)

    def test_status_and_clear_alert_run_nothing(self):
        run = runner()
        self.main(["--status"], run=run)
        self.main(["--clear-alert"], run=run)
        self.assertEqual(run.calls, [])


if __name__ == "__main__":
    unittest.main()
