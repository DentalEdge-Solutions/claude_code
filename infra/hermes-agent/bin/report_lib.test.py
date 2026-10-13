#!/usr/bin/env python3
import os, stat, sys, tempfile, shutil, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import report_lib as RL

READERS = ("account_overview", "audit_search_terms", "audit_analyze")
TS = "2026-10-01_12-00-00"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.root, True)
        self.reports = os.path.join(self.root, "reports"); self.archive = os.path.join(self.root, "report-archive")
        self.cdir = os.path.join(self.reports, "acme-dental"); os.makedirs(self.cdir)
        os.mkdir(self.archive, 0o700)
        for r in READERS:
            self.w(f"2026-10-01_11-59-0{READERS.index(r)}-{r}.md", f"figures of {r}\n")

    def w(self, name, text):
        with open(os.path.join(self.cdir, name), "w") as f:
            f.write(text)

    def read(self):
        return RL.read_reports(self.reports, "acme-dental", READERS)


class TestRead(Base):
    def test_the_three_reports_are_joined_in_the_readers_order_with_a_heading_each(self):
        text = self.read()
        marks = [text.index(f"## {r}\n") for r in READERS]
        self.assertEqual(marks, sorted(marks))
        for r in READERS:
            self.assertIn(f"figures of {r}", text)

    def test_a_missing_report_or_two_for_one_reader_is_refused(self):
        os.unlink(os.path.join(self.cdir, "2026-10-01_11-59-00-account_overview.md"))
        with self.assertRaises(RL.ReportError):
            self.read()
        self.w("2026-10-01_11-59-00-account_overview.md", "a"); self.w("2026-10-01_11-59-09-account_overview.md", "b")
        with self.assertRaises(RL.ReportError):
            self.read()

    def test_a_link_a_fifo_an_oversized_file_and_a_stray_entry_are_refused(self):
        name = "2026-10-01_11-59-00-account_overview.md"
        target = os.path.join(self.root, "secret"); open(target, "w").write("SECRET")
        for make in (lambda p: os.symlink(target, p), lambda p: os.mkfifo(p), lambda p: os.mkdir(p),
                     lambda p: open(p, "w").write("x" * (RL.MAX_REPORT_BYTES + 1))):
            with self.subTest(make=make):
                p = os.path.join(self.cdir, name)
                os.path.isdir(p) and not os.path.islink(p) and os.rmdir(p)
                os.path.lexists(p) and os.unlink(p)
                make(p)
                with self.assertRaises((RL.ReportError, OSError)) as cm:
                    self.read()
                self.assertNotIn("SECRET", str(cm.exception))
                os.path.isdir(p) and not os.path.islink(p) and os.rmdir(p)
                os.path.lexists(p) and os.unlink(p)
                self.w(name, "ok")
        self.w("notes.txt", "x")
        with self.assertRaises(RL.ReportError):
            self.read()

    def test_a_linked_client_folder_is_refused(self):
        shutil.rmtree(self.cdir); os.symlink(self.root, self.cdir)
        with self.assertRaises(OSError):
            self.read()

    def test_bytes_that_are_not_text_are_replaced_not_fatal(self):
        with open(os.path.join(self.cdir, "2026-10-01_11-59-00-account_overview.md"), "wb") as f:
            f.write(b"a\xffb")
        self.assertIn("a�b", self.read())


class TestStore(Base):
    def store(self, text="DOC", ts=TS):
        return RL.store(self.archive, "acme-dental", ts, text, owner_uid=os.geteuid())

    def test_the_document_lands_owner_only_under_the_client_s_folder(self):
        rel = self.store()
        self.assertEqual(rel, f"acme-dental/{TS}-report.md")
        p = os.path.join(self.archive, rel)
        self.assertEqual(open(p).read(), "DOC")
        self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.dirname(p)).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), [f"{TS}-report.md"])     # no temporary file left
        self.assertTrue(RL.is_stored(self.archive, "acme-dental", TS))

    def test_an_existing_report_is_never_overwritten(self):
        self.store("first")
        with self.assertRaises((RL.ReportError, OSError)):
            self.store("second")
        self.assertEqual(open(os.path.join(self.archive, "acme-dental", f"{TS}-report.md")).read(), "first")

    def test_a_loose_or_linked_store_and_a_linked_client_folder_are_refused(self):
        os.chmod(self.archive, 0o755)
        with self.assertRaises(RL.ReportError):
            self.store()
        os.chmod(self.archive, 0o700)
        os.symlink(self.root, os.path.join(self.archive, "acme-dental"))
        with self.assertRaises(OSError):
            self.store()
        self.assertFalse(os.path.exists(os.path.join(self.root, f"{TS}-report.md")))

    def test_a_bad_timestamp_or_client_name_is_refused(self):
        for slug, ts in (("acme-dental", "2026-10-01"), ("acme-dental", "../x"), ("../x", TS), ("a/b", TS)):
            with self.subTest(slug=slug, ts=ts), self.assertRaises((RL.ReportError, ValueError, OSError)):
                RL.store(self.archive, slug, ts, "DOC", owner_uid=os.geteuid())

    def test_the_list_is_sorted_and_holds_regular_report_files_only(self):
        for ts in ("2026-10-02_00-00-00", TS):
            self.store(ts=ts)
        d = os.path.join(self.archive, "acme-dental")
        os.symlink("x", os.path.join(d, "2026-10-03_00-00-00-report.md")); open(os.path.join(d, "x.md"), "w").close()
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(RL.list_report_ts(fd), [TS, "2026-10-02_00-00-00"])
        finally:
            os.close(fd)
        self.assertFalse(RL.is_stored(self.archive, "acme-dental", "2026-10-03_00-00-00"))


if __name__ == "__main__":
    unittest.main()
