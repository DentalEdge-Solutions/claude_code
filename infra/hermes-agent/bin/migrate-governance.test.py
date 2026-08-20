import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migrate_governance_shim as M  # see Step 3 note on the module name


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.vault, True)
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.makedirs(os.path.join(self.vault, "_registry"))
        with open(os.path.join(self.vault, "_registry", "clients.json"), "w") as f:
            json.dump({"clients": {"acme-dental": {
                "customer_id": "1234567890", "project": "claude_google_ads",
                "status": "active"}}}, f)
        os.makedirs(os.path.join(self.vault, "acme-dental", "changes"))
        with open(os.path.join(self.vault, "acme-dental", "changes", "log.jsonl"), "w") as f:
            for i in range(3):
                f.write(json.dumps({"changeset_id": "20260812-101500-abcd1234",
                                    "action_index": i, "status": "applied"}) + "\n")

    def test_registry_moves(self):
        M.migrate(self.vault, self.gov)
        self.assertTrue(os.path.isfile(
            os.path.join(self.gov, "registry", "clients.json")))

    def test_every_log_record_is_carried_across(self):
        res = M.migrate(self.vault, self.gov)
        with open(os.path.join(self.gov, "log", "acme-dental.jsonl")) as f:
            lines = [x for x in f.read().splitlines() if x.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(res["counts_before"]["acme-dental"], 3)
        self.assertEqual(res["counts_after"]["acme-dental"], 3)

    def test_a_failed_copy_raises(self):
        """A failed copy must RAISE, not report success. No destination file is
        pre-created here — that would trip the idempotency `skipped` branch before
        any copy is attempted, proving nothing about the copy itself (see R12). Instead
        the destination log DIRECTORY is made read-only, so shutil.copy2 itself fails
        while creating the new file inside it."""
        dst_log_dir = os.path.join(self.gov, "log")
        os.makedirs(dst_log_dir)
        os.chmod(dst_log_dir, 0o500)
        try:
            with self.assertRaises((OSError, RuntimeError)):
                M.migrate(self.vault, self.gov)
        finally:
            os.chmod(dst_log_dir, 0o700)

    def test_a_count_mismatch_raises(self):
        """The count guard is the whole point of this task: a copy that silently drops
        records must never be reported as success, because that resets the daily caps
        that limit changes to a client's live advertising account. Monkeypatch
        _count_lines so the DESTINATION read reports a different count from the
        SOURCE read, forcing the guard to fire even though the copy itself succeeded."""
        real_count_lines = M._count_lines
        src_log = os.path.join(self.vault, "acme-dental", "changes", "log.jsonl")

        def fake_count_lines(path):
            if os.path.abspath(path) == os.path.abspath(src_log):
                return real_count_lines(path)
            return real_count_lines(path) - 1

        M._count_lines = fake_count_lines
        try:
            with self.assertRaises(RuntimeError) as ctx:
                M.migrate(self.vault, self.gov)
            msg = str(ctx.exception)
            self.assertIn("3", msg)
            self.assertIn("2", msg)
        finally:
            M._count_lines = real_count_lines

    def test_the_same_migration_succeeds_without_the_patch(self):
        """Control for test_a_count_mismatch_raises: the identical fixture, with
        _count_lines unpatched, must SUCCEED. Without this control, the mismatch test
        proves nothing — it could be passing for a reason unrelated to the guard."""
        res = M.migrate(self.vault, self.gov)
        self.assertIn("acme-dental", res["moved"])
        self.assertEqual(res["counts_before"]["acme-dental"], 3)
        self.assertEqual(res["counts_after"]["acme-dental"], 3)

    def test_is_idempotent(self):
        M.migrate(self.vault, self.gov)
        res = M.migrate(self.vault, self.gov)
        self.assertIn("acme-dental", res["skipped"])

    def test_dry_run_writes_nothing(self):
        M.migrate(self.vault, self.gov, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.gov, "registry")))

    def test_a_failed_migration_can_be_retried(self):
        """CRITICAL fix: a failed attempt must not poison a retry. A naive
        shutil.copy2-straight-to-dst-then-check leaves a partial/corrupt destination
        file in place when the count check fails. A re-run then sees
        os.path.isfile(dst_log) as True and takes the idempotency `skipped` branch
        BEFORE any count is recomputed — permanently mistaking the corrupt copy for a
        successful migration, with no count fields even present to reveal it. Force a
        count mismatch on the first call (same technique as
        test_a_count_mismatch_raises), then call migrate() again with real counting and
        assert the slug was genuinely retried: present in `moved`, absent from
        `skipped`, counts recomputed — not silently skipped."""
        real_count_lines = M._count_lines
        src_log = os.path.join(self.vault, "acme-dental", "changes", "log.jsonl")

        def fake_count_lines(path):
            if os.path.abspath(path) == os.path.abspath(src_log):
                return real_count_lines(path)
            return real_count_lines(path) - 1

        M._count_lines = fake_count_lines
        try:
            with self.assertRaises(RuntimeError):
                M.migrate(self.vault, self.gov)
        finally:
            M._count_lines = real_count_lines

        res = M.migrate(self.vault, self.gov)
        self.assertNotIn("acme-dental", res["skipped"])
        self.assertIn("acme-dental", res["moved"])
        self.assertEqual(res["counts_before"]["acme-dental"], 3)
        self.assertEqual(res["counts_after"]["acme-dental"], 3)

    def test_created_directories_are_mode_700(self):
        """Ruling R14 (promoted minor): a later task requires the governance store's
        subdirectories to be mode 700 throughout and will assert it. os.makedirs's own
        mode= argument is itself umask-affected, so directories this module creates
        must be chmod'd explicitly after creation."""
        M.migrate(self.vault, self.gov)
        reg_mode = os.stat(os.path.join(self.gov, "registry")).st_mode & 0o777
        log_mode = os.stat(os.path.join(self.gov, "log")).st_mode & 0o777
        self.assertEqual(reg_mode, 0o700)
        self.assertEqual(log_mode, 0o700)


class TestCountLines(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="count-lines-")
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def test_a_truncated_trailing_line_is_rejected(self):
        """IMPORTANT fix: the count guard must see the realistic corruption. A copy
        truncated part-way through the LAST line is the realistic short-write mode —
        far likelier than a whole line vanishing — and a splitlines()-based counter
        treats that truncated, non-JSON line as just another countable line, so the
        guard would report a match over a corrupt record. _count_lines must instead
        agree with the production reader (changeset_lib.iter_log_records) and refuse on
        a line that doesn't parse, rather than silently declining to count it."""
        path = os.path.join(self.scratch, "truncated.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"changeset_id": "20260812-101500-abcd1234",
                                "action_index": 0, "status": "applied"}) + "\n")
            f.write(json.dumps({"changeset_id": "20260812-101500-abcd1234",
                                "action_index": 1, "status": "applied"}) + "\n")
            # Truncated mid-object: no closing brace, no trailing newline.
            f.write('{"changeset_id": "20260812-101500-abcd1234", "action_i')
        with self.assertRaises(RuntimeError):
            M._count_lines(path)

    def test_a_complete_file_is_counted_normally(self):
        """Control for test_a_truncated_trailing_line_is_rejected: the same shape of
        file, fully written, must count normally. Without this, the truncation test
        proves nothing about truncation specifically — it could be rejecting every file."""
        path = os.path.join(self.scratch, "complete.jsonl")
        with open(path, "w") as f:
            for i in range(3):
                f.write(json.dumps({"changeset_id": "20260812-101500-abcd1234",
                                    "action_index": i, "status": "applied"}) + "\n")
        self.assertEqual(M._count_lines(path), 3)


if __name__ == "__main__":
    unittest.main()
