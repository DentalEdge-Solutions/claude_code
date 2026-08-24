import json, os, stat, tempfile, unittest, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spool_lib as S

GOOD_ID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"
GOOD = {"request_id": GOOD_ID, "op": "apply", "client": "pilot-1",
        "changeset": "20260824-101500-abcdef01"}


class TestPaths(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("HERMES_SPOOL_ROOT", None)

    def tearDown(self):
        os.environ.pop("HERMES_SPOOL_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_SPOOL_ROOT"] = self._saved

    def test_default_is_the_container_path(self):
        self.assertEqual(S.spool_root(), "/opt/data/spool")

    def test_env_overrides_for_host_callers(self):
        os.environ["HERMES_SPOOL_ROOT"] = "/tmp/spool"
        self.assertEqual(S.requests_dir(), "/tmp/spool/requests")
        self.assertEqual(S.results_dir(), "/tmp/spool/results")

    def test_request_and_result_paths(self):
        self.assertEqual(S.request_path(GOOD_ID, "/tmp/s"),
                         "/tmp/s/requests/%s.json" % GOOD_ID)
        self.assertEqual(S.result_path(GOOD_ID, "/tmp/s"),
                         "/tmp/s/results/%s.json" % GOOD_ID)

    def test_bad_request_id_never_becomes_a_path(self):
        for bad in ("../../etc/passwd", "no-slashes/here", GOOD_ID + "\n", "", "A" * 36):
            with self.assertRaises(S.SpoolRefused):
                S.request_path(bad, "/tmp/s")


class TestValidate(unittest.TestCase):
    def test_accepts_the_exact_four_keys(self):
        got = S.validate_request(dict(GOOD), GOOD_ID + ".json")
        self.assertEqual(got["client"], "pilot-1")
        self.assertEqual(got["changeset"], "20260824-101500-abcdef01")

    def test_extra_key_is_a_refusal_not_an_ignored_field(self):
        obj = dict(GOOD); obj["operator"] = "root"
        with self.assertRaises(S.SpoolRefused) as cm:
            S.validate_request(obj, GOOD_ID + ".json")
        self.assertIn("operator", str(cm.exception))

    def test_missing_key_refuses(self):
        obj = dict(GOOD); del obj["changeset"]
        with self.assertRaises(S.SpoolRefused):
            S.validate_request(obj, GOOD_ID + ".json")

    def test_op_undo_is_refused(self):
        # §17.2: undo bypasses the kill switch and the caps and needs no approval.
        # The syscall exposes apply only. This test is the enforcement of that rule.
        obj = dict(GOOD); obj["op"] = "undo"
        with self.assertRaises(S.SpoolRefused):
            S.validate_request(obj, GOOD_ID + ".json")

    def test_any_op_other_than_apply_is_refused(self):
        for op in ("Apply", "apply ", "", "validate_only", None, 1):
            obj = dict(GOOD); obj["op"] = op
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_bad_slug_refuses(self):
        for slug in ("../etc", "UPPER", "pilot 1", "", "a" * 65, "pilot-1\n"):
            obj = dict(GOOD); obj["client"] = slug
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_bad_changeset_id_refuses(self):
        for cid in ("20260824-101500-ABCDEF01", "nope", "", "20260824-101500-abcdef0"):
            obj = dict(GOOD); obj["changeset"] = cid
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(obj, GOOD_ID + ".json")

    def test_filename_must_match_request_id(self):
        other = "1111aaaa-2222-4bbb-8ccc-3333dddd4444"
        with self.assertRaises(S.SpoolRefused) as cm:
            S.validate_request(dict(GOOD), other + ".json")
        self.assertIn("does not match", str(cm.exception))

    def test_non_object_refuses(self):
        for junk in ([], "string", 7, None):
            with self.assertRaises(S.SpoolRefused):
                S.validate_request(junk, GOOD_ID + ".json")


class TestHostileReads(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, GOOD_ID + ".json")

    def _write(self, data):
        with open(self.p, "wb") as f:
            f.write(data)

    def test_control_a_wellformed_file_loads(self):
        # THE POSITIVE CONTROL. Every refusal below is meaningless unless this passes:
        # it proves the reader can actually read a legitimate request.
        self._write(json.dumps(GOOD).encode())
        self.assertEqual(S.load_request(self.p)["client"], "pilot-1")

    def test_oversized_file_refuses_and_is_not_read_whole(self):
        self._write(b"{" + b"x" * (S.MAX_REQUEST_BYTES * 4))
        with self.assertRaises(S.SpoolRefused) as cm:
            S.read_request_bytes(self.p)
        self.assertIn("cap", str(cm.exception))

    def test_symlink_refuses_rather_than_dereferences(self):
        # Named GOOD_ID + ".json" (not an arbitrary "target.json") because the control
        # call below goes through load_request(), whose filename/request_id cross-check
        # would otherwise refuse this on filename-shape grounds — a refusal unrelated
        # to the symlink question this control exists to isolate.
        target = os.path.join(self.d, GOOD_ID + ".json")
        with open(target, "w") as f:
            json.dump(GOOD, f)
        link = os.path.join(self.d, "1111aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.symlink(target, link)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(link)
        # control: the same bytes at a real path DO load, so the refusal is about the
        # symlink and not about the content.
        self.assertEqual(S.load_request(target)["client"], "pilot-1")

    def test_directory_in_place_of_a_request_refuses(self):
        d = os.path.join(self.d, "2222aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.mkdir(d)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(d)

    def test_fifo_refuses_without_blocking(self):
        p = os.path.join(self.d, "3333aaaa-2222-4bbb-8ccc-3333dddd4444.json")
        os.mkfifo(p)
        with self.assertRaises(S.SpoolRefused):
            S.read_request_bytes(p)

    def test_malformed_json_refuses(self):
        self._write(b"{not json")
        with self.assertRaises(S.SpoolRefused):
            S.load_request(self.p)

    def test_non_utf8_refuses(self):
        self._write(b'{"request_id": "\xff\xfe"}')
        with self.assertRaises(S.SpoolRefused):
            S.load_request(self.p)


class TestWriteResult(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_result_is_written_and_readable(self):
        p = S.write_result(GOOD_ID, {"status": "refused", "exit_code": 2}, self.root)
        with open(p) as f:
            self.assertEqual(json.load(f)["exit_code"], 2)

    def test_result_write_is_atomic_leaving_no_tmp_behind(self):
        S.write_result(GOOD_ID, {"status": "ok"}, self.root)
        leftovers = [n for n in os.listdir(S.results_dir(self.root)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
