import contextlib, importlib.util, inspect, io, json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import persist_run_record_shim as P
import governance_lib


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PRR = _load("persist_run_record", "persist-run-record.py")

RESULT = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
          "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}


class TestParse(unittest.TestCase):
    def test_finds_the_marker_line(self):
        text = "apply-changeset: ok\nHERMES-RESULT-JSON {\"changeset_id\": \"x\"}\n"
        self.assertEqual(P.parse_result(text), {"changeset_id": "x"})

    def test_absent_marker_returns_none(self):
        self.assertIsNone(P.parse_result("apply-changeset: refused\n"))

    def test_ignores_the_marker_word_inside_ordinary_output(self):
        """Control: the discriminator is a line PREFIX, not a substring anywhere."""
        self.assertIsNone(P.parse_result("see HERMES-RESULT-JSON for details\n"))

    def test_last_marker_wins(self):
        text = ('HERMES-RESULT-JSON {"n": 1}\n'
                'HERMES-RESULT-JSON {"n": 2}\n')
        self.assertEqual(P.parse_result(text), {"n": 2})


class _RecordsBase(unittest.TestCase):
    """The per-client records directory laid out the way production lays it out:
    <GOVERNANCE_ROOT>/records/<slug> (F12 — this used to be <VAULT_ROOT>/<slug>).

    realpath() on the tempdir because macOS puts /var behind a symlink to /private/var;
    persist() resolves its destinations, so a test comparing raw paths against resolved
    ones would fail for a reason that has nothing to do with what it is testing.
    """
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.records = governance_lib.records_dir("acme-dental", root=self.root)
        os.makedirs(self.records)
        self._old_gov_root = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        self.addCleanup(self._restore_gov_root)
        # Stands in for another tree inside the governance store — control/ (the kill
        # switch), log/ (the audit log) — that the persist step must never be able to
        # reach, however records/<slug> is shaped.
        self.outside = os.path.realpath(tempfile.mkdtemp(prefix="governance-outside-"))
        self.addCleanup(shutil.rmtree, self.outside, True)

    def _restore_gov_root(self):
        if self._old_gov_root is None:
            os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        else:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._old_gov_root


class TestPersist(_RecordsBase):

    def test_writes_result_json_and_appends_timeline(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.records, res)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.records, "timeline.md")) as f:
            self.assertIn("20260812-101500-abcd1234", f.read())

    def test_persist_writes_to_the_canonical_record_path(self):
        """F12: governance_lib.record_path is the single definition of where a result
        file lives (<records>/<slug>/<cid>.result.json, no "changes/" component any
        more) — persist() must obtain the destination's basename from it rather than
        composing a second, divergent convention."""
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.records, res)
        self.assertEqual(path, governance_lib.record_path(
            "acme-dental", res["changeset_id"], root=self.root))
        # And the canonical path is directly inside the per-client records directory,
        # not a nested "changes" subdirectory — that layer no longer exists.
        self.assertEqual(os.path.dirname(path), self.records)

    def test_timeline_appends_rather_than_truncates(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 1,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        P.persist(self.records, res)
        P.persist(self.records, dict(res, changeset_id="20260812-111500-beef5678"))
        with open(os.path.join(self.records, "timeline.md")) as f:
            body = f.read()
        self.assertIn("abcd1234", body)
        self.assertIn("beef5678", body)

    def test_the_record_and_timeline_are_group_readable_not_umask_dependent(self):
        """F12: UMask=0077 must not make records unreadable. The modes are explicit."""
        old = os.umask(0o077)
        try:
            path = P.persist(self.records, RESULT)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        timeline = os.path.join(self.records, "timeline.md")
        self.assertEqual(stat.S_IMODE(os.stat(timeline).st_mode), 0o640)

    def test_the_per_client_directory_is_setgid_2750_not_umask_dependent(self):
        """F12 review (Important 2): nothing asserted the per-client directory's own
        mode — deleting the os.fchmod(rfd, ...) call in persist() left the whole suite
        green. The FULL mode is asserted (stat.S_IMODE, not `& 0o777`), because the bit
        under test IS the setgid bit: 0750 without it is the exact regression the spec
        correction (R1) fixed — it strips the group inheritance records/'s setgid bit
        exists to give, and files then land group-owned by the writer's own primary
        group (hermes-broker) instead of the intended "hermes".

        A FRESH per-client directory — not self.records, which _RecordsBase.setUp
        already created under whatever umask the test process happened to have — is
        created here, and only inside the os.umask(0o077) block, so a pass can only be
        explained by persist()'s explicit os.fchmod, never by a mode that happened to
        already be right before persist() ran.
        """
        fresh = governance_lib.records_dir("other-clinic", root=self.root)
        self.assertFalse(os.path.exists(fresh), "fixture bug: this must be created "
                         "fresh, by persist(), under the hostile umask below")
        old = os.umask(0o077)
        try:
            P.persist(fresh, RESULT)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(fresh).st_mode),
                         governance_lib.RECORDS_DIR_MODE)


class TestSymlinkEscape(_RecordsBase):
    """C1 (final whole-branch review, F12-updated). persist() runs HOST-SIDE and writes
    into records/<slug>/ in the governance store. That tree is not mounted into any
    container and not writable by the gateway, so the symlink-planting attack this
    class was originally written against (2026-08-19, against the client vault) is no
    longer reachable through the gateway or the mutation-path client vault — see
    persist_run_record_shim's module docstring. The containment stays anyway, as
    defence in depth, so these refusals remain load-bearing regression coverage for a
    future writer or a mis-set mode, not coverage of a currently-reachable attack.

    The refusals below are only evidence because TestPersistControl proves the
    ordinary, non-symlinked write still succeeds against the same code.
    """

    def _kill_switch(self):
        p = governance_lib.kill_switch_path(self.outside)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def test_symlinked_timeline_pointing_outside_the_records_dir_is_refused(self):
        """timeline.md is appended with O_APPEND|O_CREAT, so following a planted
        symlink there would CREATE whatever it points at — historically the kill
        switch, since kill_switch_ok() only asks whether the file exists."""
        target = self._kill_switch()
        self.assertFalse(os.path.exists(target))
        os.symlink(target, os.path.join(self.records, "timeline.md"))
        with self.assertRaises(ValueError):
            P.persist(self.records, RESULT)
        self.assertFalse(os.path.exists(target),
                         "the symlink target was created — records/ is writable "
                         "somewhere it should not be")

    def test_symlinked_result_tmp_is_refused(self):
        """The .tmp write is O_TRUNC, so following a planted symlink there would
        truncate whatever it points at — historically the audit log, whose records
        are the reversibility record and the daily-cap count."""
        target = os.path.join(self.outside, "log", "acme-dental.jsonl")
        os.makedirs(os.path.dirname(target))
        original = b'{"status":"applied","ts":"2026-08-12T10:00:00Z"}\n' * 3
        with open(target, "wb") as f:
            f.write(original)
        os.symlink(target, governance_lib.record_path(
            "acme-dental", RESULT["changeset_id"], root=self.root) + ".tmp")
        with self.assertRaises(ValueError):
            P.persist(self.records, RESULT)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), original, "the audit log was rewritten through "
                                                 "the .tmp symlink")

    def test_symlinked_result_json_is_refused(self):
        """The final rename is not the only reachable step: refuse a symlinked
        destination outright rather than relying on rename's non-following semantics."""
        target = os.path.join(self.outside, "clients.json")
        with open(target, "w") as f:
            f.write("{}")
        os.symlink(target, governance_lib.record_path(
            "acme-dental", RESULT["changeset_id"], root=self.root))
        with self.assertRaises(ValueError):
            P.persist(self.records, RESULT)
        with open(target) as f:
            self.assertEqual(f.read(), "{}")

    def test_records_dir_that_is_itself_a_symlink_is_refused(self):
        records = os.path.join(os.path.dirname(self.records), "other-clinic")
        os.symlink(self.outside, records)
        with self.assertRaises(ValueError):
            P.persist(records, RESULT)
        self.assertEqual(sorted(os.listdir(self.outside)), [])

    def test_records_dir_outside_the_configured_root_is_refused(self):
        """Containment is checked against the resolved records root, not merely
        against whatever directory the caller happened to pass."""
        stray = os.path.join(self.outside, "acme-dental")
        os.makedirs(stray)
        with self.assertRaises(ValueError):
            P.persist(stray, RESULT)
        self.assertEqual(os.listdir(stray), [])

    def test_a_directory_where_timeline_belongs_is_refused_not_crashed(self):
        os.mkdir(os.path.join(self.records, "timeline.md"))
        with self.assertRaises(ValueError):
            P.persist(self.records, RESULT)


class TestPersistControl(_RecordsBase):
    """The control the refusals above depend on: with nothing planted, the same
    persist() call must still write both artifacts and touch nothing outside."""

    def test_ordinary_persist_succeeds_and_writes_only_inside_the_records_dir(self):
        before = sorted(os.listdir(self.outside))
        path = P.persist(self.records, RESULT)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.records, "timeline.md")) as f:
            self.assertIn(RESULT["changeset_id"], f.read())
        self.assertEqual(sorted(os.listdir(self.outside)), before)


class TestMain(unittest.TestCase):
    """Deferred minor #11: persist-run-record.py's main() had no automated cover.

    F12: persist now writes into the governance store's records/ tree, resolved via
    HERMES_GOVERNANCE_ROOT — the vault is no longer involved in this step at all.
    """

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self._old_gov = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        self.addCleanup(self._restore_gov)
        reg = governance_lib.clients_registry_path(self.root)
        os.makedirs(os.path.dirname(reg), exist_ok=True)
        with open(reg, "w") as f:
            json.dump({"clients": {"acme-dental": {"project": "claude_google_ads",
                                                   "customer_id": "1234567890",
                                                   "status": "active"}}}, f)
        # F12 review: persist() now REFUSES a missing records/ tree rather than
        # auto-creating it (the layout row is a hard prerequisite, laid down by
        # init-host-layout.py --apply) — lay it down here the same way that would, for
        # the same reason run-ads-mutate.test.py's fixture now does.
        os.makedirs(os.path.join(self.root, "records"), exist_ok=True)
        self.records = governance_lib.records_dir("acme-dental", root=self.root)

    def _restore_gov(self):
        if self._old_gov is None:
            os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        else:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._old_gov

    def _run(self, argv, stdin_text):
        out = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            with contextlib.redirect_stdout(out):
                rc = PRR.main(argv)
        finally:
            sys.stdin = old_stdin
        return rc, out.getvalue()

    def test_no_marker_returns_zero(self):
        """A refusal emits no result line. That is not an error for this step, and it
        must not be turned into one — the executor's own exit status is the verdict."""
        rc, _ = self._run(["--client", "acme-dental"], "apply-changeset: refused\n")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.records, "timeline.md")))

    def test_output_passes_through_unchanged(self):
        text = "apply-changeset: ok\nHERMES-RESULT-JSON %s\n" % json.dumps(RESULT)
        rc, out = self._run(["--client", "acme-dental"], text)
        self.assertEqual(rc, 0)
        self.assertEqual(out, text)
        self.assertTrue(os.path.exists(governance_lib.record_path(
            "acme-dental", RESULT["changeset_id"], root=self.root)))

    def test_unknown_client_exits_non_zero(self):
        text = "HERMES-RESULT-JSON %s\n" % json.dumps(RESULT)
        rc, out = self._run(["--client", "no-such-client"], text)
        self.assertNotEqual(rc, 0)
        self.assertEqual(out, text, "the executor's output must reach the operator even "
                                    "when persisting it fails")

    def test_a_notimplementederror_from_persist_is_a_refusal_not_a_traceback(self):
        """S1-M1. persist() is built entirely out of dir_fd calls, and Python raises
        NotImplementedError for a dir_fd it cannot honour. That was not in main()'s
        except tuple, so it escaped as a raw TRACEBACK and exit 1 — indistinguishable
        from a crash, on a path where every other failure is a one-line exit 2.

        Raised from persist() directly rather than by simulating an unsupported
        platform: the subject under test is main()'s handler, and going through
        os.supports_dir_fd would test the shim's import guard instead."""
        text = "HERMES-RESULT-JSON %s\n" % json.dumps(RESULT)
        err = io.StringIO()

        def boom(*a, **kw):
            raise NotImplementedError("dir_fd unavailable on this platform")

        with mock.patch.object(PRR.P, "persist", side_effect=boom):
            with contextlib.redirect_stderr(err):
                rc, out = self._run(["--client", "acme-dental"], text)
        self.assertEqual(rc, 2)
        self.assertEqual(out, text)                    # pass-through still happens
        self.assertIn("NotImplementedError", err.getvalue())

    def test_control_the_same_handler_still_refuses_an_ordinary_oserror(self):
        """CONTROL: proves the widened tuple did not change the existing paths, so the
        test above measures the NEW exception type rather than a handler that catches
        everything for some unrelated reason."""
        text = "HERMES-RESULT-JSON %s\n" % json.dumps(RESULT)
        err = io.StringIO()
        with mock.patch.object(PRR.P, "persist", side_effect=OSError("disk full")):
            with contextlib.redirect_stderr(err):
                rc, _ = self._run(["--client", "acme-dental"], text)
        self.assertEqual(rc, 2)
        self.assertIn("OSError", err.getvalue())


class TestDirFdGuardCoversEveryDependedOnCall(unittest.TestCase):
    """S1-M1. The import-time guard checked os.open and os.rename only, while the
    comment beside it named four calls as measured and persist() depends on all four —
    os.mkdir and os.unlink became load-bearing dir_fd calls in T8 and were never added.
    A CHECKED set that has drifted from the DEPENDED-ON set is the same defect class as
    a requirement list written from memory."""

    def test_the_guard_covers_every_dir_fd_call_persist_actually_makes(self):
        names = {f.__name__ for f in P._REQUIRED_DIR_FD_CALLS}
        self.assertEqual(names, {"open", "rename", "mkdir", "unlink"})

    def test_the_guarded_set_matches_the_dir_fd_calls_in_the_source(self):
        """Derives the expected set from the MODULE SOURCE rather than restating the
        literal, so adding a dir_fd call without adding it to the guard fails here.

        NOT a source-text canary of the shape this plan has already been burnt by: it
        does not assert that some string is present somewhere. It extracts the os.<fn>
        calls that are passed a dir_fd/*_dir_fd keyword and asserts that SET equals the
        guarded set, so it fails on a real divergence and cannot be satisfied by a
        mention in a comment — comments are stripped by ast before this looks."""
        import ast
        tree = ast.parse(inspect.getsource(P))
        used = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"):
                continue
            if any(kw.arg and kw.arg.endswith("dir_fd") for kw in node.keywords):
                used.add(node.func.attr)
        self.assertTrue(used, "found no dir_fd calls — the extractor is blind")
        self.assertEqual(used, {f.__name__ for f in P._REQUIRED_DIR_FD_CALLS})


class TestParkedResiduals(unittest.TestCase):
    """R20 (a) hardlinks, (b) directory-component TOCTOU, (c) makedirs before check.

    F12: the per-client records directory now sits directly under the governance
    store's records/ tree (no intermediate "changes" subdirectory) — the (b) swap
    below targets that directory relative to its parent instead of the old "changes"
    subdirectory relative to the vault.
    """

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.records = governance_lib.records_dir("slug-1", root=self.root)
        os.makedirs(self.records, exist_ok=True)
        # Stands in for a tree outside records/ that persist() must never be able to
        # write into or through, even via a swapped-in symlink (Important 3 below).
        self.outside = os.path.join(self.root, "outside")
        os.makedirs(self.outside, exist_ok=True)
        self.result = {"changeset_id": "20260824-101500-abcdef01",
                       "status": "applied", "applied": 1,
                       "finished_at": "2026-08-24T10:15:00Z"}

    def test_control_a_normal_persist_still_works(self):
        # The must-SUCCEED control. Several refusals are exercised below; if any of
        # them over-reaches, this is the test that catches it.
        p = P.persist(self.records, self.result, root=self.root)
        self.assertTrue(os.path.isfile(p))

    # --- (a) hardlinks -------------------------------------------------------------
    def test_a_hardlinked_timeline_is_refused(self):
        # O_NOFOLLOW does not see a hardlink and S_ISREG accepts one, so both existing
        # barriers pass it. With the broker running this step as the governance store's
        # OWNER, a hardlink from records/ to a store file elsewhere is a write primitive.
        outside = os.path.join(self.root, "outside.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        os.link(outside, os.path.join(self.records, "timeline.md"))
        with self.assertRaises(P.PersistRefused) as cm:
            P.persist(self.records, self.result, root=self.root)
        self.assertIn("hard link", str(cm.exception).lower())
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")   # untouched

    def test_a_hardlinked_result_file_is_refused(self):
        # Unlike the timeline case, the final result.json is never opened directly —
        # it is written to a .tmp name and then swapped in with os.rename, and rename
        # replaces a directory ENTRY rather than writing through the old inode, so a
        # hard link planted here is not a corruption vector the way timeline.md's is.
        # It is refused anyway (via _refuse_if_hardlinked, checked before the rename)
        # as a matter of policy: silently letting a name entangled with a file outside
        # records/ be swapped is exactly the kind of coincidence R20(a) exists to
        # surface as a named refusal rather than best-effort silence.
        outside = os.path.join(self.root, "outside2.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        dest = governance_lib.record_path("slug-1", self.result["changeset_id"],
                                          root=self.root)
        os.link(outside, dest)
        with self.assertRaises(P.PersistRefused):
            P.persist(self.records, self.result, root=self.root)
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")

    def test_control_a_single_linked_file_is_accepted(self):
        # Proves the nlink check refuses hardlinks specifically and not ordinary
        # pre-existing files.
        with open(os.path.join(self.records, "timeline.md"), "w") as f:
            f.write("- earlier\n")
        self.assertTrue(os.path.isfile(P.persist(self.records, self.result,
                                                  root=self.root)))

    def test_hardlinked_tmp_content_survives_even_with_the_precheck_disabled(self):
        # FINDING 1 (post-implementation review, 2026-08-26): the coordinator measured
        # that _refuse_if_hardlinked's own check-then-act window is exploitable on the
        # .tmp path specifically, because the old O_TRUNC open truncated as a side
        # effect of the open() syscall itself — before the nlink check on the
        # resulting fd ever ran. The fix is _create_tmp_exclusive's O_CREAT|O_EXCL,
        # which makes the existence test and the create the SAME syscall, closing the
        # window structurally rather than tightening the check.
        #
        # This test disables the pre-check entirely (monkeypatches
        # _refuse_if_hardlinked to a no-op) so a pass here can only be explained by
        # the structural O_EXCL fix, not by the belt-and-braces check. It also makes
        # the assertion the earlier hardlink tests do not make: not merely that an
        # exception was raised, but that the outside file's CONTENT is byte-identical
        # afterwards. A refusal that fires after the damage is not a refusal.
        outside = os.path.join(self.root, "outside3.txt")
        known = "do-not-truncate-me\n" * 50
        with open(outside, "w") as f:
            f.write(known)
        tmp_dest = governance_lib.record_path(
            "slug-1", self.result["changeset_id"], root=self.root) + ".tmp"
        os.link(outside, tmp_dest)

        real_refuse = P._refuse_if_hardlinked
        P._refuse_if_hardlinked = lambda *a, **k: None
        try:
            with self.assertRaises(P.PersistRefused):
                P.persist(self.records, self.result, root=self.root)
        finally:
            P._refuse_if_hardlinked = real_refuse

        with open(outside) as f:
            self.assertEqual(f.read(), known, "the outside file was truncated "
                             "through the hardlinked .tmp name even with the "
                             "pre-check disabled — the structural O_EXCL fix did "
                             "not hold")

    # --- (b) directory-component TOCTOU --------------------------------------------
    # NOTE: a source-text canary (asserting "dir_fd"/"O_DIRECTORY" appear via
    # inspect.getsource) previously lived here and was DELETED on review (2026-08-26).
    # It passed through the exact regression it was named for: with the dirfd chain
    # gutted back to path-based opens on the result-file branch, it stayed green
    # because those two strings still appear elsewhere in the file. A test whose name
    # claims a property it structurally cannot verify is worse than no test — it
    # reads as coverage to a future reader. The behavioural test immediately below
    # fully supersedes it and is the one mutation-proven to catch that regression.

    def test_dirfd_chain_resists_a_swapped_records_directory(self):
        """Behavioural companion, F12-adapted: with the "changes" subdirectory gone,
        the equivalent TOCTOU-sensitive step is the per-client records directory
        itself, opened relative to its PARENT (the records/ tree) via dir_fd. Hooks
        `P._open_dir` to swap the per-client directory ENTRY, by path, in the exact
        gap between persist() opening it (capturing a directory descriptor via
        openat) and persist() writing through that descriptor. A descriptor obtained
        via open()/openat() refers to the underlying inode, not the name used to
        obtain it — an os.rename() of that name afterwards cannot redirect it. If
        persist() re-resolved the path instead of reusing the descriptor, the write
        would land in the ATTACKER directory that now occupies the per-client name; if
        it genuinely uses the descriptor, the write lands in the original directory
        regardless of what that name now resolves to.
        """
        original_records = self.records
        parent = os.path.dirname(self.records)
        slug_name = os.path.basename(self.records)
        attacker_dir = os.path.join(self.root, "attacker-records")
        os.makedirs(attacker_dir, exist_ok=True)
        displaced = os.path.join(parent, slug_name + "-displaced")

        real_open_dir = P._open_dir
        state = {"swapped": False}

        def swapping_open_dir(name, dir_fd=None):
            fd = real_open_dir(name, dir_fd=dir_fd)
            # Only the call that opens the per-client name RELATIVE TO the parent
            # (records/) fd — the parent-level open itself (dir_fd=None) must be left
            # alone, or nothing would be left to open the (now-renamed) directory
            # through.
            if not state["swapped"] and name == slug_name and dir_fd is not None:
                state["swapped"] = True
                os.rename(original_records, displaced)
                os.rename(attacker_dir, original_records)
            return fd

        P._open_dir = swapping_open_dir
        try:
            path = P.persist(self.records, self.result, root=self.root)
        finally:
            P._open_dir = real_open_dir

        self.assertTrue(state["swapped"], "the hook never fired — test is not "
                        "exercising the swap it claims to")
        # The write must have landed in the ORIGINAL directory (now renamed aside),
        # not in the attacker directory that currently occupies the per-client name.
        self.assertTrue(os.path.isfile(os.path.join(displaced, os.path.basename(path))))
        self.assertEqual(os.listdir(original_records), [],
                         "the write followed the swapped NAME instead of the "
                         "descriptor captured before the swap — the TOCTOU is open")

    def test_a_symlinked_per_client_directory_is_refused_by_nofollow_not_islink(self):
        """F12 review (Important 3). Retirement #3
        (`test_a_changes_symlink_resolving_back_inside_the_vault_is_still_refused`,
        deleted from the pre-F12 suite) discriminated `_open_dir`'s O_NOFOLLOW from a
        path-level `islink` check — nothing in the F12 suite did, so mutating either
        one away left every test green. This restores that discrimination for the
        per-client directory.

        MEASURED, not assumed: my first attempt at this test swapped the per-client
        entry for a symlink and left it swapped for the rest of the call, exactly as
        the review comment describes. That does NOT kill the O_NOFOLLOW mutation
        (removing O_NOFOLLOW from `_open_dir`'s flags at persist_run_record_shim.py:183
        and re-running left this test GREEN) — because `_check_dest`'s own, entirely
        separate, path-based `os.path.realpath` re-check on the FINAL FILE names
        (`path`, `path + ".tmp"`, the timeline) also resolves through the still-present
        symlink and raises `PersistRefused` on its own, independently of whether
        `_open_dir`'s open ever refused anything. That masked the very regression this
        test exists to catch.

        The fix: put the symlink in place ONLY for the single `_open_dir` call that
        opens the per-client name relative to the parent descriptor (`dir_fd is not
        None` — `_resolve_records`'s own islink check already ran, on an ordinary
        directory, before this point), then restore an ordinary empty directory at
        that name immediately afterwards, in a `finally`, BEFORE `_check_dest` or
        anything else downstream ever looks at the path again. That isolates exactly
        one property: whether THIS open, by itself, refuses to follow the symlink.
        Under the real code it does (O_NOFOLLOW -> ELOOP -> PersistRefused, before the
        restore even matters) and `self.outside` is never touched. Under the mutation
        it does not: the open follows the symlink, returns an fd bound to
        `self.outside`'s inode, and every subsequent write in `persist()` — the
        restored on-disk name no longer being what the fd refers to — lands inside
        `self.outside` instead, so `persist()` returns successfully (no
        `PersistRefused` at all) and `self.outside` gains files. Both assertions below
        independently catch that.
        """
        real_open_dir = P._open_dir
        state = {"hooked": False}

        def swapping_open_dir(name, dir_fd=None):
            # Only the call that opens the per-client name RELATIVE TO the parent
            # (records/) fd — the parent-level open itself (dir_fd=None) is left alone.
            if state["hooked"] or dir_fd is None:
                return real_open_dir(name, dir_fd=dir_fd)
            state["hooked"] = True
            shutil.rmtree(self.records)
            os.symlink(self.outside, self.records)
            try:
                return real_open_dir(name, dir_fd=dir_fd)
            finally:
                # Restore an ordinary, valid, self-contained directory regardless of
                # outcome — so nothing downstream of THIS open (_check_dest's separate
                # path-based re-check included) can independently catch the symlink
                # and mask whether _open_dir's own O_NOFOLLOW was the thing that fired.
                os.unlink(self.records)
                os.makedirs(self.records)

        P._open_dir = swapping_open_dir
        try:
            with self.assertRaises(P.PersistRefused):
                P.persist(self.records, self.result, root=self.root)
        finally:
            P._open_dir = real_open_dir

        self.assertTrue(state["hooked"], "the hook never fired — test is not "
                        "exercising the swap it claims to")
        self.assertEqual(os.listdir(self.outside), [],
                         "the symlink was followed and something was written "
                         "into the outside tree through it")

    # --- (c) makedirs before the containment check ---------------------------------
    def test_an_out_of_root_records_dir_is_refused_without_being_created(self):
        outside = os.path.join(tempfile.mkdtemp(), "not-in-the-root")
        with self.assertRaises(P.PersistRefused):
            P.persist(outside, self.result, root=self.root)
        # The mkdir belongs BELOW the check: refusing after creating the directory
        # leaves an attacker-chosen path on disk.
        self.assertFalse(os.path.exists(outside))


if __name__ == "__main__":
    unittest.main()
