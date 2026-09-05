import importlib.util, json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migrate_governance_shim as M  # see Step 3 note on the module name


def _load_cli():
    """migrate-governance.py has a hyphen in its name, so it cannot be imported —
    the same loader idiom preflight-governance-access.test.py uses."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "migrate_governance_cli", os.path.join(here, "migrate-governance.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="vault-")
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.vault, True)
        self.addCleanup(shutil.rmtree, self.gov, True)
        # I3: migrate() now verifies a freshly-created log/'s group against
        # governance_lib.EXECUTOR_GID (10000) before trusting it — the same
        # D4 setgid-inheritance hazard S3-b closes for bootstrap_logs, applied here
        # because migrate() can also be the one laying log/ down from scratch. These
        # fixtures create log/ as THIS test process, whose real primary group is
        # whatever the host/CI assigns it, not 10000 — patch the expectation to match,
        # the same idiom test_cli_dry_run_then_apply already uses for bootstrap_logs.
        import governance_lib
        real_gid = governance_lib.EXECUTOR_GID
        governance_lib.EXECUTOR_GID = os.getgid()
        self.addCleanup(setattr, governance_lib, "EXECUTOR_GID", real_gid)
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
        must be chmod'd explicitly after creation.

        S3-b (abeb662) is that later task, and it decided log/ must be 2750 — setgid,
        group read+traverse, NOT group-writable — so the executor can append without
        being able to unlink. R14's blanket 700-everywhere assumption is superseded for
        log/ specifically; registry/ is untouched by that decision and stays 700."""
        M.migrate(self.vault, self.gov)
        reg_mode = os.stat(os.path.join(self.gov, "registry")).st_mode & 0o777
        log_mode = os.stat(os.path.join(self.gov, "log")).st_mode & 0o7777
        self.assertEqual(reg_mode, 0o700)
        self.assertEqual(log_mode, M.governance_lib.LOG_DIR_MODE)

    def test_a_freshly_created_log_dir_with_the_wrong_group_refuses(self):
        """I3/D4: migrate() can be the one laying log/ down from scratch (the normal
        deploy pre-creates it host-side, but nothing enforces that before migration
        runs) — _ensure_dir sets the MODE but a directory made by an unprivileged
        process still inherits that process's own primary group, not EXECUTOR_GID.
        Reproduces the exact hazard bootstrap_logs' own D4 test proves, one call site
        over. Forced by asking for a gid this process cannot land on, same technique as
        the bootstrap_logs equivalent."""
        import governance_lib
        governance_lib.EXECUTOR_GID = os.getgid() + 4242
        self.addCleanup(setattr, governance_lib, "EXECUTOR_GID", os.getgid())
        with self.assertRaises(RuntimeError) as cm:
            M.migrate(self.vault, self.gov)
        self.assertIn("group", str(cm.exception))
        self.assertFalse(
            os.path.exists(os.path.join(self.gov, "log")),
            "a log/ this call created and then refused must not be left behind")


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


class TestBootstrapLogs(unittest.TestCase):
    """S3-b: every REGISTERED client must be guaranteed a pre-created log, or a missing
    log stays ambiguous between 'never used' and 'deleted'."""

    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.makedirs(os.path.join(self.gov, "registry"))
        os.makedirs(os.path.join(self.gov, "log"), mode=0o2750)
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            json.dump({"clients": {
                "acme-dental": {"customer_id": "1234567890", "status": "active"},
                "other-clinic": {"customer_id": "9998887776", "status": "dormant_pilot"},
            }}, f)

    def _log(self, slug):
        return os.path.join(self.gov, "log", "%s.jsonl" % slug)

    def test_dry_run_creates_nothing(self):
        """dry_run is passed explicitly here, not relied on as a default. The library
        default is dry_run=False, matching migrate()'s own signature in this same module
        (rule 6645879 — one behavior, not two functions quietly disagreeing on what their
        shared parameter name means); dry-run-by-default is a CLI-level property, and the
        CLI gets it by passing dry_run=not args.apply explicitly for both functions."""
        res = M.bootstrap_logs(self.gov, dry_run=True, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])
        self.assertFalse(os.path.exists(self._log("acme-dental")))
        self.assertFalse(os.path.exists(self._log("other-clinic")))

    def test_apply_creates_one_empty_log_per_registered_client_at_0660(self):
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])
        for slug in ("acme-dental", "other-clinic"):
            st = os.stat(self._log(slug))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o660, slug)
            self.assertEqual(st.st_size, 0, slug)

    def test_an_existing_log_is_skipped_and_left_byte_identical(self):
        """THE load-bearing idempotency test. A bootstrap that opened the file with mode
        'w' would truncate exactly the reversibility record this wave exists to protect,
        and an existence-only assertion would call that a pass."""
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        with open(self._log("acme-dental"), "w") as f:
            f.write('{"status": "applied", "ts": "2026-09-04T00:00:00Z", '
                    '"changeset_id": "20260904-000000-abcd1234"}\n')
        with open(self._log("acme-dental"), "rb") as f:
            before = f.read()
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["skipped"]), ["acme-dental", "other-clinic"])
        self.assertEqual(res["created"], [])
        with open(self._log("acme-dental"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_a_missing_log_directory_refuses_rather_than_creating_it(self):
        """Creating log/ here would lay it down at the wrong mode and produce exactly
        the unusable store the pre-flight exists to catch."""
        shutil.rmtree(os.path.join(self.gov, "log"))
        with self.assertRaises(RuntimeError) as cm:
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertIn("log", str(cm.exception))

    def test_a_file_landing_with_the_wrong_group_refuses(self):
        """THE D4 HAZARD as an executable test. log/ without setgid gives new files the
        creating user's primary group; 0660 then grants the WRONG group and uid 10000
        falls through to `other` — a layout that passes a delete probe and fails the
        append control. A bootstrap that only created the file would report success on a
        log the executor cannot use. Forced here by asking for a gid this process cannot
        produce, which needs no root.

        I2(b) NOTE: this fixture's log/ already carries the wrong group (setUp never
        chgrp's it to the requested expected_gid), so as of I2(b) this is now caught by
        the upfront directory-level check rather than the per-file check exercised
        before — same root cause, earlier refusal point. Both paths raise RuntimeError
        naming "group", so this assertion still discriminates correctly."""
        with self.assertRaises(RuntimeError) as cm:
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid() + 4242)
        self.assertIn("group", str(cm.exception))
        self.assertFalse(os.path.exists(self._log("acme-dental")),
                         "a file that failed verification must not be left behind")

    def test_a_group_writable_log_directory_refuses(self):
        """I2(b): a log/ that is group-writable is refused before any file is created,
        regardless of gid — write on a directory is what grants unlink, and populating
        such a store with correctly-owned files would not close that hole."""
        os.chmod(os.path.join(self.gov, "log"), 0o2770)
        with self.assertRaises(RuntimeError) as cm:
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertIn("group-writable", str(cm.exception))
        self.assertFalse(os.path.exists(self._log("acme-dental")))

    def test_control_the_same_call_with_the_real_gid_succeeds(self):
        """POSITIVE CONTROL for the two tests above — without it, either refusal would
        also pass against a bootstrap that refused everything."""
        res = M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        self.assertEqual(sorted(res["created"]), ["acme-dental", "other-clinic"])

    def test_an_unparseable_registry_refuses(self):
        with open(os.path.join(self.gov, "registry", "clients.json"), "w") as f:
            f.write("{not json")
        with self.assertRaises(RuntimeError):
            M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())

    def test_cli_dry_run_then_apply(self):
        import governance_lib
        CLI = _load_cli()
        real = governance_lib.EXECUTOR_GID
        governance_lib.EXECUTOR_GID = os.getgid()
        self.addCleanup(setattr, governance_lib, "EXECUTOR_GID", real)
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov]), 0)
        self.assertFalse(os.path.exists(self._log("acme-dental")))
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov, "--apply"]), 0)
        self.assertTrue(os.path.isfile(self._log("acme-dental")))

    def test_cli_returns_2_on_a_missing_log_directory(self):
        CLI = _load_cli()
        shutil.rmtree(os.path.join(self.gov, "log"))
        self.assertEqual(
            CLI.main(["--bootstrap-logs", "--governance-root", self.gov, "--apply"]), 2)

    def test_a_toctou_race_between_the_exists_check_and_create_refuses_without_clobbering(
            self):
        """THE O_EXCL WITNESS. `os.path.exists(dst)` and the `os.open(..., O_EXCL, ...)`
        that follows it are two separate syscalls with a window between them. If another
        process (a concurrent bootstrap run, or the real client writing its first record)
        creates log/<slug>.jsonl inside that window, O_CREAT|O_EXCL is what makes THIS
        call's os.open fail loudly instead of silently truncating a file someone else just
        wrote. Simulated by making the exists() check lie exactly once for the target
        path — reporting 'missing' while the file is genuinely present with real content
        on disk — while every other path keeps answering truthfully, so the missing-log/
        and unparseable-registry refusals are not what fires here.

        A mutation to plain `open(dst, 'w')` (Mutant B from Step 8) cannot fail this race
        at all — it would silently truncate the winner's file — so this is the test that
        must kill it; test_an_existing_log_is_skipped_and_left_byte_identical cannot, since
        a truthful exists() check there never reaches the create line in the first place.
        """
        M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())
        target = self._log("acme-dental")
        with open(target, "w") as f:
            f.write('{"status": "applied", "ts": "2026-09-04T00:00:00Z", '
                    '"changeset_id": "20260904-000000-abcd1234"}\n')
        with open(target, "rb") as f:
            before = f.read()

        real_exists = os.path.exists
        lied = {"done": False}

        def fake_exists(p):
            if not lied["done"] and p == target:
                lied["done"] = True
                return False
            return real_exists(p)

        with mock.patch.object(M.os.path, "exists", side_effect=fake_exists):
            with self.assertRaises(FileExistsError):
                M.bootstrap_logs(self.gov, dry_run=False, expected_gid=os.getgid())

        self.assertTrue(lied["done"], "the race was never actually simulated")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), before,
                              "a lost create race must not destroy the pre-existing log")


if __name__ == "__main__":
    unittest.main()
