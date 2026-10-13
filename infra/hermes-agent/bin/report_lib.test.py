#!/usr/bin/env python3
import os, stat, sys, tempfile, shutil, time, unittest
from unittest import mock
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
                returned = []
                with self.assertRaises((RL.ReportError, OSError)) as cm:
                    returned.append(self.read())
                self.assertNotIn("SECRET", str(cm.exception) + repr(cm.exception.args) + "".join(returned))
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


class TestReadHardening(Base):
    def test_a_report_that_grows_past_the_cap_after_the_size_check_is_refused(self):
        name = "2026-10-01_11-59-00-account_overview.md"
        with open(os.path.join(self.cdir, name), "wb") as f:
            f.write(b"x" * (RL.MAX_REPORT_BYTES + 1))
        real = os.fstat

        def small(fd):
            st = real(fd)
            return type("S", (), {"st_mode": st.st_mode, "st_size": 10})()
        with mock.patch.object(RL.os, "fstat", small), self.assertRaises(RL.ReportError) as cm:
            self.read()
        self.assertIn("too large", str(cm.exception))

    def test_a_short_read_does_not_truncate_a_report(self):
        body = "y" * 10000
        self.w("2026-10-01_11-59-00-account_overview.md", body)
        real = os.read
        with mock.patch.object(RL.os, "read", lambda fd, n: real(fd, min(n, 1000))):
            self.assertIn(body, self.read())

    def test_a_folder_with_too_many_entries_is_refused_before_any_name_is_looked_at(self):
        for i in range(200):
            self.w(f"junk-{i}.txt", "x")
        with self.assertRaises(RL.ReportError) as cm:
            self.read()
        self.assertEqual(str(cm.exception), "too many entries in the reports folder")


REG = {"acme-dental": {"customer_id": "1234567890"}, "other-dental": {"customer_id": "9998887777"}}


def hits(text, reg=REG):
    return RL.isolation_hits(text, "acme-dental", reg)


class TestDisplayText(unittest.TestCase):
    def test_controls_format_characters_and_separators_go_text_newline_and_tab_stay(self):
        self.assertEqual(RL.display_text("a\u202eb\u200bc\u2028d\u2029e\x1b[\x00\r\x7f\u009b \u00e9\n\tok\u00ad"),
                         "abcde[ \u00e9\n\tok")


class TestIsolation(unittest.TestCase):
    def test_an_id_inside_a_longer_number_is_not_a_hit(self):
        for text in ("219998887777", "99988877770000", "19998887777", "99988877771", "5999-888-77775",
                     "1999-888-7777", "999-888-77775"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (0, 0))

    def test_an_id_with_a_boundary_is_a_hit_in_every_common_form(self):
        for text in ("customers/9998887777/x", "9998887777.0", "id:9998887777", "999-888-7777", "999 888 7777",
                     "999.888.7777", "\uff19\uff19\uff19\uff18\uff18\uff18\uff17\uff17\uff17\uff17",
                     "\u0669\u0669\u0669\u0668\u0668\u0668\u0667\u0667\u0667\u0667", "999\u2011888\u20117777"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (0, 1))

    def test_registry_ids_as_numbers_or_dashed_are_checked_and_missing_ones_skipped(self):
        reg = {"acme-dental": {"customer_id": "1234567890"}, "n": {"customer_id": 9998887777},
               "none": {"status": "x"}, "nul": {"customer_id": None}, "empty": {"customer_id": ""}}
        self.assertEqual(hits("9998887777", reg), (0, 1))
        self.assertEqual(hits("nothing here", reg), (0, 0))
        reg = {"acme-dental": {"customer_id": "1234567890"}, "d": {"customer_id": "999-888-7777"}}
        self.assertEqual(hits("9998887777", reg), (0, 1))

    def test_an_id_that_cannot_be_read_refuses(self):
        for bad in ("12345", "abc", 5, True, 1.5, ["x"], "12345678901"):
            with self.subTest(bad=bad), self.assertRaises(RL.ReportError) as cm:
                hits("x", {"acme-dental": {"customer_id": "1234567890"}, "o": {"customer_id": bad}})
            self.assertEqual(str(cm.exception), "a registry record's customer id is not ten digits")

    def test_another_slug_carrying_my_own_id_does_not_refuse_my_report(self):
        reg = {"acme-dental": {"customer_id": "1234567890"}, "alias": {"customer_id": "123-456-7890"}}
        self.assertEqual(hits("my id 1234567890", reg), (0, 0))
        self.assertEqual(RL.other_client_ids(reg, "acme-dental"), [])
        self.assertEqual(RL.other_client_ids(REG, "acme-dental"), ["9998887777"])

    def test_one_client_found_by_name_and_by_id_counts_once(self):
        self.assertEqual(hits("other-dental 9998887777"), (1, 1))

    def test_hidden_characters_in_a_name_do_not_hide_it_and_a_space_still_does(self):
        for text in ("other\u00addental", "other\u200b-dental", "other\u2011dental", "other\u2043dental",
                     "\uff4f\uff54\uff48\uff45\uff52-\uff44\uff45\uff4e\uff54\uff41\uff4c", "oth\ufe0fer-dental",
                     "other\u2212dental"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (1, 0))
        self.assertEqual(hits("Other Dental"), (0, 0))       # KNOWN LIMIT, pinned: no matching across a space

    def test_an_id_next_to_a_character_that_normalises_to_a_digit_is_still_a_hit(self):
        for text in ("9998887777\u00b2", "\u24609998887777", "\u00b2\u00b29998887777\u00b9"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (0, 1))
        self.assertEqual(hits("29998887777"), (0, 0))

    def test_a_registry_record_that_is_not_an_object_refuses_but_my_own_does_not(self):
        for bad in ("9998887777", 5, None, ["x"]):
            with self.subTest(bad=bad), self.assertRaises(RL.ReportError) as cm:
                hits("x", {"acme-dental": {"customer_id": "1234567890"}, "o": bad})
            self.assertEqual(str(cm.exception), "a registry record cannot be read")
        self.assertEqual(hits("x", {"acme-dental": "not an object", "o": {"customer_id": "9998887777"}}), (0, 0))

    def test_two_ids_on_one_line_are_both_found(self):
        reg = {"acme-dental": {"customer_id": "1234567890"}, "a": {"customer_id": "9998887777"},
               "b": {"customer_id": "1112223333"}}
        self.assertEqual(hits("9998887777 1112223333", reg), (0, 2))
        self.assertEqual(hits("999 888 7777 111 222 3333", reg), (0, 2))
        self.assertEqual(hits("1112223333", reg), (0, 1))

    def test_ids_not_separated_by_at_most_one_plain_character_are_not_hits(self):
        for text in ("999\n888\n7777", "999a888b7777", "| 999 | 888 | 7777 |", "999  888  7777"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (0, 0))

    def test_the_expansion_bound_is_not_tighter_than_specified(self):
        self.assertEqual(len(RL.isolation_texts("\u00bd" * 1000)), 4)          # 3x, within 2*len + 1024
        self.assertEqual(len(RL.isolation_texts("a\u2122 b\u00bd c\u2122")), 4)
        with self.assertRaises(RL.ReportError):
            RL.isolation_texts("\u00bd" * 1200)

    def test_other_invisible_characters_and_other_dashes_do_not_hide_a_name(self):
        for text in ("oth\u2800er-dental", "oth\u3164er-dental", "other\uff0ddental", "other\u2e3adental",
                     "oth\u034fer-dental", "other\u2014dental"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), (1, 0))

    def test_a_registry_id_written_with_spaces_is_read(self):
        reg = {"acme-dental": {"customer_id": "1234567890"}, "o": {"customer_id": "999 888 7777"}}
        self.assertEqual(hits("9998887777", reg), (0, 1))

    def test_a_c1_control_other_than_csi_is_dropped_by_display_text(self):
        self.assertEqual(RL.display_text("a\u0085b\u009bc\u0080d\u009fe"), "abcde")

    def test_a_text_that_expands_too_much_is_refused(self):
        with self.assertRaises(RL.ReportError) as cm:
            RL.isolation_texts("\ufdfa" * 1000)
        self.assertEqual(str(cm.exception), "the reports expand too much when normalised")

    def test_two_megabytes_of_ordinary_text_with_a_hundred_clients_is_fast(self):
        reg = {f"client-{i:03d}": {"customer_id": f"{i + 1:010d}"} for i in range(100)}
        reg["acme-dental"] = {"customer_id": "1234567890"}
        text = ("Campaign A clicks 123 cost 45.67 conversions 8\n" * 50000)[: 2 * 1024 * 1024]
        t0 = time.time()
        self.assertEqual(hits(text, reg), (0, 0))
        self.assertLess(time.time() - t0, 5)

    def test_two_megabytes_of_ordinary_text_with_ten_clients_is_fast(self):
        reg = {f"client-{i}": {"customer_id": f"{i:010d}"} for i in range(1, 10)}
        reg["acme-dental"] = {"customer_id": "1234567890"}
        text = ("Campaign A clicks 123 cost 45.67 conversions 8\n" * 50000)[: 2 * 1024 * 1024]
        t0 = time.time()
        RL.isolation_texts(text)
        self.assertEqual(hits(text, reg), (0, 0))
        self.assertLess(time.time() - t0, 5)

    def test_the_texts_are_the_original_the_display_copy_and_two_normalised_copies(self):
        t = RL.isolation_texts("a\u200bb\u00ad-c")
        self.assertEqual(len(t), 4)
        self.assertEqual((t[0], t[1]), ("a\u200bb\u00ad-c", "ab-c"))
        self.assertEqual((t[2], t[3]), ("ab-c", "ab--c"))


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

    def test_a_loose_store_and_a_linked_client_folder_are_refused(self):
        os.chmod(self.archive, 0o755)
        with self.assertRaises(RL.ReportError):
            self.store()
        os.chmod(self.archive, 0o700)
        os.symlink(self.root, os.path.join(self.archive, "acme-dental"))
        with self.assertRaises(OSError):
            self.store()
        self.assertFalse(os.path.exists(os.path.join(self.root, f"{TS}-report.md")))

    def test_a_linked_store_is_refused_and_nothing_is_written_through_the_link(self):
        link = os.path.join(self.root, "link"); os.symlink(self.archive, link)
        for path in (link, link + "/"):
            with self.subTest(path=path), self.assertRaises((RL.ReportError, OSError)):
                RL.store(path, "acme-dental", TS, "DOC", owner_uid=os.geteuid())
        self.assertEqual(os.listdir(self.archive), [])

    def test_a_path_that_is_not_absolute_and_normal_is_refused(self):
        link = os.path.join(self.root, "lnk"); os.symlink(self.archive, link)
        for path in (link + "/.", link + "/../report-archive", "report-archive", "", self.archive + "/./",
                     self.archive + "/../report-archive"):
            with self.subTest(path=path), self.assertRaises(RL.ReportError):
                RL.store(path, "acme-dental", TS, "DOC", owner_uid=os.geteuid())
        self.assertEqual(os.listdir(self.archive), [])
        self.assertEqual(RL.store(self.archive + "/", "acme-dental", TS, "DOC", owner_uid=os.geteuid()),
                         f"acme-dental/{TS}-report.md")

    def test_the_temporary_name_carries_the_process_id(self):
        seen = []
        real = os.link

        def spy(src, dst, **kw):
            seen.append(src)
            return real(src, dst, **kw)
        with mock.patch.object(RL.os, "getpid", lambda: 4242), mock.patch.object(RL.os, "link", spy):
            self.store()
        self.assertEqual(seen, [f".{TS}-report.4242.tmp"])

    def test_is_stored_returns_false_for_a_non_string_base(self):
        self.assertIs(RL.is_stored(None, "acme-dental", TS), False)
        self.assertIs(RL.is_stored(5, "acme-dental", TS), False)

    def test_a_pre_existing_loose_client_folder_is_refused(self):
        d = os.path.join(self.archive, "acme-dental"); os.mkdir(d); os.chmod(d, 0o755)
        with self.assertRaises(RL.ReportError):
            self.store()
        self.assertEqual(os.listdir(d), [])

    def test_the_archive_and_the_client_folder_must_belong_to_the_expected_owner(self):
        with self.assertRaises(RL.ReportError):
            RL.store(self.archive, "acme-dental", TS, "DOC", owner_uid=os.geteuid() + 1)
        self.assertEqual(os.listdir(self.archive), [])
        real = RL._archive_fd           # let the archive pass, so only the client folder's owner is judged
        with mock.patch.object(RL, "_archive_fd", lambda base, uid: real(base, os.geteuid())), \
                self.assertRaises(RL.ReportError):
            RL.store(self.archive, "acme-dental", TS, "DOC", owner_uid=os.geteuid() + 1)
        self.assertEqual(os.listdir(os.path.join(self.archive, "acme-dental")), [])

    def test_a_dangling_link_at_the_final_name_is_refused_and_its_target_not_created(self):
        d = os.path.join(self.archive, "acme-dental"); os.mkdir(d, 0o700)
        target = os.path.join(self.root, "created-through-link")
        os.symlink(target, os.path.join(d, f"{TS}-report.md"))
        with self.assertRaises((RL.ReportError, OSError)):
            self.store()
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(os.listdir(d), [f"{TS}-report.md"])          # only the link; no temporary file

    def test_a_leftover_temporary_file_of_an_earlier_run_does_not_block_the_timestamp(self):
        d = os.path.join(self.archive, "acme-dental"); os.mkdir(d, 0o700)
        for left in (f".{TS}-report.tmp", f".{TS}-report.4242.tmp"):
            open(os.path.join(d, left), "w").write("half")
        self.store("DOC")
        self.assertEqual(os.listdir(d), [f"{TS}-report.md"])
        # another timestamp's leftover is not this run's to remove
        other = ".2026-10-02_00-00-00-report.7.tmp"; open(os.path.join(d, other), "w").close()
        self.store("DOC2", ts="2026-10-03_00-00-00")
        self.assertIn(other, os.listdir(d))
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(RL.list_report_ts(fd), [TS, "2026-10-03_00-00-00"])
        finally:
            os.close(fd)

    def test_the_folder_and_file_are_owner_only_whatever_the_umask(self):
        old = os.umask(0o277)
        try:
            rel = self.store()
        finally:
            os.umask(old)
        p = os.path.join(self.archive, rel)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.dirname(p)).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), 0o600)

    def test_a_bad_timestamp_or_client_name_is_refused(self):
        for slug, ts in (("acme-dental", "2026-10-01"), ("acme-dental", "../x"), ("../x", TS), ("a/b", TS)):
            with self.subTest(slug=slug, ts=ts), self.assertRaises((RL.ReportError, ValueError, OSError)):
                RL.store(self.archive, slug, ts, "DOC", owner_uid=os.geteuid())

    def test_is_stored_never_raises_and_never_answers_for_another_path(self):
        self.store()
        os.makedirs(os.path.join(self.root, "x"))
        open(os.path.join(self.root, f"{TS}-report.md"), "w").close()          # reachable by ../ from the folder
        for slug, ts in (("acme-dental", f"../{TS}"), ("acme-dental", os.path.join(self.root, TS)),
                         ("acme-dental", TS + "\0"), ("acme-dental", TS + "\n"), ("a/b", TS), ("..", TS),
                         ("acme-dental/../..", TS)):
            with self.subTest(slug=slug, ts=ts):
                self.assertIs(RL.is_stored(self.archive, slug, ts), False)
        self.assertIs(RL.is_stored(self.archive, "acme-dental", TS), True)
        self.assertIs(RL.is_stored(os.path.join(self.root, "nope"), "acme-dental", TS), False)

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
