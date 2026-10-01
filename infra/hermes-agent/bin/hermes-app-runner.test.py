#!/usr/bin/env python3
import importlib.util, json, os, sys, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
spec = importlib.util.spec_from_file_location("run", os.path.join(HERE, "hermes-app-runner.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
MAN = A.load_manifest(os.path.join(os.path.dirname(HERE), "registry/apps/ads-audit.json"), "ads-audit")
RID = "0f8e2c1a-1111-4222-8333-444455556666"
RID2 = "0f8e2c1a-1111-4222-8333-777788889999"


class T(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        for d in ("jobs", "running", "done"):
            os.makedirs(os.path.join(self.state, d))
        self.calls = []

    def job(self, rid=RID, op="run", client="acme-dental", raw=None):
        data = raw if raw is not None else json.dumps({"job_id": rid, "op": op, "client": client})
        open(os.path.join(self.state, "jobs", rid + ".json"), "w").write(data)

    def execute(self, argv, timeout):
        self.calls.append((argv, timeout))
        self.assertTrue(os.path.exists(os.path.join(self.state, "running", RID + ".json")))  # moved first
        return 0, '{"status": "ok"}\n', False

    def done(self, rid=RID):
        return json.load(open(os.path.join(self.state, "done", rid + ".json")))

    def test_fixed_argv_per_op_and_done_written(self):
        self.job()
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [(["/usr/local/sbin/run-client-audit", "acme-dental", "--json"], 7200)])
        d = self.done()
        self.assertEqual((d["rc"], d["timed_out"], d["interrupted"]), (0, False, False))
        self.assertEqual(os.listdir(os.path.join(self.state, "jobs")), [])
        self.assertEqual(os.listdir(os.path.join(self.state, "running")), [])

    def test_list_argv(self):
        self.job(op="list")
        calls = []
        R.run_all(MAN, self.state, execute=lambda a, t: calls.append((a, t)) or (0, "", False), owner=None)
        self.assertEqual(calls, [(["/usr/local/sbin/run-client-audit", "acme-dental", "--list", "--json"], 60)])

    def test_leftover_running_becomes_interrupted_and_is_never_run(self):
        open(os.path.join(self.state, "running", RID + ".json"), "w").write(
            json.dumps({"job_id": RID, "op": "run", "client": "acme-dental"}))
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.done()["interrupted"])

    def test_malformed_job_never_executes(self):
        for raw in ('{"job_id": "%s", "op": "run", "client": "../x"}' % RID,
                    '{"job_id": "%s", "op": "undo", "client": "a"}' % RID, "junk"):
            with self.subTest(raw=raw):
                self.job(raw=raw)
                R.run_all(MAN, self.state, execute=self.execute, owner=None)
                self.assertEqual(self.calls, [])
                d = self.done(); self.assertIsNone(d["rc"])
                os.unlink(os.path.join(self.state, "done", RID + ".json"))

    def test_symlinked_job_not_followed(self):
        target = os.path.join(self.state, "t"); open(target, "w").write("x")
        os.symlink(target, os.path.join(self.state, "jobs", RID + ".json"))
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertTrue(os.path.exists(target))

    def test_real_execute_timeout_kills_the_group(self):
        rc, out, timed_out = R._execute(["/bin/sh", "-c", "sleep 30 & sleep 30"], 1)
        self.assertEqual((rc, timed_out), (None, True))

    def test_real_execute_caps_stdout(self):
        rc, out, _ = R._execute(["/bin/sh", "-c", "head -c 200000 /dev/zero | tr '\\0' a"], 10)
        self.assertEqual((rc, len(out)), (0, A.MAX_STDOUT))

    # --- broker contract (Task 5): done BEFORE unlink, and never a removed job without a done file ---

    def _observe_done_writes(self):
        """Records, for every done file written, whether running/<id> still existed at that moment."""
        seen, real = [], A.write_json_atomic
        def spy(dirpath, name, obj, **kw):
            seen.append((name, os.path.lexists(os.path.join(self.state, "running", name))))
            return real(dirpath, name, obj, **kw)
        return seen, mock.patch.object(R.A, "write_json_atomic", spy)

    def test_done_is_written_while_running_entry_still_exists(self):
        self.job()
        seen, patch = self._observe_done_writes()
        with patch:
            R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(seen, [(RID + ".json", True)])
        self.assertEqual(os.listdir(os.path.join(self.state, "running")), [])

    def test_leftover_done_is_written_before_its_running_entry_goes(self):
        open(os.path.join(self.state, "running", RID + ".json"), "w").write("{}")
        seen, patch = self._observe_done_writes()
        with patch:
            R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(seen, [(RID + ".json", True)])

    def test_no_path_removes_a_job_without_a_done_file(self):
        real_unlink, removed = os.unlink, []
        def guarded_unlink(path, *a, **kw):
            d, name = os.path.split(os.path.abspath(path))
            if os.path.basename(d) in ("jobs", "running") and os.path.dirname(d) == os.path.abspath(self.state):
                removed.append(name)
                self.assertTrue(os.path.exists(os.path.join(self.state, "done", name)),
                                f"{path} removed with no done file")
            return real_unlink(path, *a, **kw)
        def boom(argv, timeout):
            raise OSError("exec failed")
        only_run = A.Manifest(MAN.app, MAN.user, MAN.command, {"run": MAN.ops["run"]},
                              {"run": MAN.tools["run"], "status": MAN.tools["status"]}, {"run": 300})
        cases = [
            ("valid", lambda: self.job(), MAN, self.execute),
            ("malformed", lambda: self.job(raw="junk"), MAN, self.execute),
            ("symlink", lambda: os.symlink(os.path.join(self.state, "nowhere"),
                                           os.path.join(self.state, "jobs", RID + ".json")), MAN, self.execute),
            ("leftover", lambda: open(os.path.join(self.state, "running", RID + ".json"), "w").write("x"),
             MAN, self.execute),
            ("op not in manifest", lambda: self.job(op="list"), only_run, self.execute),
            ("execute raises", lambda: self.job(), MAN, boom),
        ]
        for label, make, man, ex in cases:
            with self.subTest(case=label):
                removed.clear()
                make()
                with mock.patch.object(R.os, "unlink", guarded_unlink):
                    R.run_all(man, self.state, execute=ex, owner=None)
                self.assertEqual(removed, [RID + ".json"])
                self.assertEqual(os.listdir(os.path.join(self.state, "jobs")), [])
                self.assertEqual(os.listdir(os.path.join(self.state, "running")), [])
                real_unlink(os.path.join(self.state, "done", RID + ".json"))

    def test_execute_raising_writes_a_failed_done_and_continues(self):
        self.job(); self.job(rid=RID2)
        def boom(argv, timeout):
            raise OSError("exec failed")
        R.run_all(MAN, self.state, execute=boom, owner=None)
        for rid in (RID, RID2):
            d = self.done(rid)
            self.assertEqual((d["rc"], d["timed_out"], d["interrupted"]), (None, False, False))
        self.assertEqual(os.listdir(os.path.join(self.state, "running")), [])

    def test_op_missing_from_manifest_is_not_executed(self):
        only_run = A.Manifest(MAN.app, MAN.user, MAN.command, {"run": MAN.ops["run"]},
                              {"run": MAN.tools["run"], "status": MAN.tools["status"]}, {"run": 300})
        self.job(op="list")
        R.run_all(only_run, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.done()["rc"])

    def test_name_with_trailing_newline_is_ignored(self):
        bad = RID + ".json\n"            # FILENAME_RE's `$` would accept it under .match: fullmatch must not
        open(os.path.join(self.state, "jobs", bad), "w").write(
            json.dumps({"job_id": RID, "op": "run", "client": "acme-dental"}))
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(self.calls, [])
        self.assertEqual(os.listdir(os.path.join(self.state, "jobs")), [bad])
        self.assertEqual(os.listdir(os.path.join(self.state, "done")), [])

    def test_jobs_run_oldest_first(self):
        self.job(); self.job(rid=RID2, client="beta-dental")
        os.utime(os.path.join(self.state, "jobs", RID2 + ".json"), (1, 1))     # RID2 is older
        order = []
        R.run_all(MAN, self.state, execute=lambda a, t: order.append(a[1]) or (0, "", False), owner=None)
        self.assertEqual(order, ["beta-dental", "acme-dental"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.state, "done"))), sorted([RID + ".json", RID2 + ".json"]))

    def test_done_file_mode_is_0640(self):
        self.job()
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        self.assertEqual(os.stat(os.path.join(self.state, "done", RID + ".json")).st_mode & 0o777, 0o640)

    def test_done_file_parses_for_the_broker(self):
        self.job()
        R.run_all(MAN, self.state, execute=self.execute, owner=None)
        p = os.path.join(self.state, "done", RID + ".json")
        d = A.parse_done(A.read_capped(p, A.MAX_DONE_BYTES), RID + ".json")
        self.assertEqual(d["stdout"], '{"status": "ok"}\n')


if __name__ == "__main__":
    unittest.main()
