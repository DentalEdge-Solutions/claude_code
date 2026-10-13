#!/usr/bin/env python3
import contextlib, importlib.util, io, json, os, shutil, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rs", os.path.join(HERE, "report-store.py"))
RS = importlib.util.module_from_spec(spec); spec.loader.exec_module(RS)
RS.OWNER_UID = os.geteuid()
RL = RS.RL

READERS = ("account_overview", "audit_search_terms", "audit_analyze")
TS = "2026-10-01_12-00-00"


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.root, True)
        self.reports = os.path.join(self.root, "reports"); self.archive = os.path.join(self.root, "report-archive")
        self.cdir = os.path.join(self.reports, "acme-dental"); os.makedirs(self.cdir)
        os.mkdir(self.archive, 0o700)
        self.registry = os.path.join(self.root, "clients.json")
        with open(self.registry, "w") as f:
            json.dump({"clients": {
                "acme-dental": {"customer_id": "1234567890", "status": "active", "project": "claude_google_ads"},
                "other-dental": {"customer_id": "9998887777", "status": "active", "project": "claude_google_ads"}}}, f)
        for i, r in enumerate(READERS):
            self.w(f"2026-10-01_11-59-0{i}-{r}.md", f"figures of {r}\n")

    def w(self, name, text):
        with open(os.path.join(self.cdir, name), "w") as f:
            f.write(text)

    def args(self, **over):
        d = {"--client": "acme-dental", "--ts": TS, "--reports-dir": self.reports,
             "--archive": self.archive, "--registry": self.registry}
        d.update(over)
        out = [x for k, v in d.items() for x in (k, v)]
        for r in READERS:
            out += ["--reader", r]
        return out

    def run_(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = RS.main(argv)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def stored(self):
        d = os.path.join(self.archive, "acme-dental")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_a_clean_run_stores_one_owner_only_file_and_prints_nothing_on_stdout(self):
        rc, out, err = self.run_(self.args())
        self.assertEqual(rc, 0, err); self.assertEqual(out, "")
        p = os.path.join(self.archive, "acme-dental", f"{TS}-report.md")
        self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), 0o600)
        self.assertEqual(self.stored(), [f"{TS}-report.md"])

    def test_a_report_naming_another_client_stores_nothing_and_leaks_nothing(self):
        self.w("2026-10-01_11-59-01-audit_search_terms.md", "line one SECRETLINE about other-dental\n")
        rc, out, err = self.run_(self.args())
        self.assertEqual(rc, RL.ISOLATION_RC)
        self.assertEqual(self.stored(), [])
        self.assertNotIn("other-dental", err + out); self.assertNotIn("SECRETLINE", err + out)

    def test_a_missing_report_fails_and_stores_nothing(self):
        os.unlink(os.path.join(self.cdir, "2026-10-01_11-59-00-account_overview.md"))
        rc, _, _ = self.run_(self.args())
        self.assertEqual(rc, 1); self.assertEqual(self.stored(), [])

    def test_an_unreadable_registry_fails_and_stores_nothing(self):
        for body in (None, "{not json"):
            with self.subTest(body=body):
                if body is None:
                    os.unlink(self.registry)
                else:
                    with open(self.registry, "w") as f:
                        f.write(body)
                rc, _, err = self.run_(self.args())
                self.assertEqual(rc, 1); self.assertEqual(self.stored(), [])
                self.assertNotIn("Traceback", err)

    def test_a_repeated_reader_and_an_abbreviated_option_are_usage_errors(self):
        rc, _, _ = self.run_(self.args() + ["--reader", "account_overview"])
        self.assertEqual(rc, 2)
        rc, _, _ = self.run_(["--clie", "acme-dental"] + self.args()[2:])
        self.assertEqual(rc, 2)
        self.assertEqual(self.stored(), [])

    def test_an_invalid_reader_name_is_a_usage_error(self):
        for bad in ("Account", "../x", "a b", "", "9x", "x" * 65):
            with self.subTest(bad=bad):
                rc, _, _ = self.run_(self.args()[:-2] + ["--reader", bad])
                self.assertEqual(rc, 2)

    def test_an_unexpected_failure_is_one_clean_line_and_rc_1(self):
        with open(self.registry, "w") as f:
            f.write("[]")                       # a registry whose top level is a list
        rc, _, err = self.run_(self.args())
        self.assertEqual(rc, 1); self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1); self.assertIn("unexpected", err)
        self.assertEqual(self.stored(), [])

    def put(self, text):
        self.w("2026-10-01_11-59-01-audit_search_terms.md", text)

    def test_hidden_or_look_alike_characters_do_not_hide_another_clients_name(self):
        for text in ("other\u200b-dental", "other\u2011dental", "other\u00ad-dental",
                     "\uff4f\uff54\uff48\uff45\uff52-\uff44\uff45\uff4e\uff54\uff41\uff4c", "OTHER\u2212DENTAL",
                     "o\u202ether-dental"):
            with self.subTest(text=text):
                self.put(text + "\n")
                rc, out, err = self.run_(self.args())
                self.assertEqual(rc, RL.ISOLATION_RC); self.assertEqual(self.stored(), [])
                self.assertNotIn("dental", (out + err).replace("acme-dental", ""))

    def test_a_name_with_a_space_is_not_matched_a_known_limit(self):
        # KNOWN LIMIT, shared with the audit's own check: no matching across spaces, underscores or
        # line breaks. This test pins the limit so a change to it is deliberate.
        self.put("Other Dental and other_dental\n")
        self.assertEqual(self.run_(self.args())[0], 0)

    def test_another_clients_customer_id_is_an_isolation_failure_the_own_id_is_not(self):
        for text in ("id 9998887777 here", "id 999-888-7777 here", "id 999\u2011888\u20117777 here"):
            with self.subTest(text=text):
                self.put(text + "\n")
                rc, out, err = self.run_(self.args())
                self.assertEqual(rc, RL.ISOLATION_RC); self.assertEqual(self.stored(), [])
                self.assertNotRegex(out + err, r"[0-9]{3}-?[0-9]{3}-?[0-9]{4}")
        self.put("own id 1234567890 and 123-456-7890\n")
        self.assertEqual(self.run_(self.args())[0], 0)

    def test_a_registry_record_without_a_usable_id_is_skipped(self):
        with open(self.registry, "w") as f:
            json.dump({"clients": {"acme-dental": {"customer_id": "1234567890"}, "no-id": {"status": "x"},
                                   "short": {"customer_id": "12345"}, "odd": "not a record",
                                   "num": {"customer_id": 5}}}, f)
        self.put("12345 and 5 and 999-888-7777\n")
        rc, _, err = self.run_(self.args())
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
