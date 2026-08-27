import contextlib, importlib.util, inspect, io, json, os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import persist_run_record_shim as P
import changeset_lib as C
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


class _VaultBase(unittest.TestCase):
    """A vault laid out the way production lays it out: <VAULT_ROOT>/<slug>.

    realpath() on the tempdir because macOS puts /var behind a symlink to /private/var;
    persist() resolves its destinations, so a test comparing raw paths against resolved
    ones would fail for a reason that has nothing to do with what it is testing.
    """
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="vaultroot-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.vault = os.path.join(self.root, "acme-dental")
        os.makedirs(self.vault)
        self._old_vault_root = os.environ.get("VAULT_ROOT")
        os.environ["VAULT_ROOT"] = self.root
        self.addCleanup(self._restore_vault_root)
        # Stands in for the host-owned governance store: a tree OUTSIDE the vault that
        # the persist step must never be able to write, however the vault is shaped.
        self.outside = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.outside, True)

    def _restore_vault_root(self):
        if self._old_vault_root is None:
            os.environ.pop("VAULT_ROOT", None)
        else:
            os.environ["VAULT_ROOT"] = self._old_vault_root


class TestPersist(_VaultBase):

    def test_writes_result_json_and_appends_timeline(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.vault, res)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn("20260812-101500-abcd1234", f.read())

    def test_persist_writes_to_the_canonical_result_path(self):
        """R15: changeset_lib.result_path is the single definition of where a result
        file lives (<vault>/changes/<cid>.result.json) — persist() must obtain the
        destination from it rather than composing a second, divergent convention (a
        prior version of this function wrote to <vault>/<cid>.result.json, the vault
        ROOT, which this test would catch: that path is not equal to result_path()'s,
        so the assertEqual below fails against it)."""
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 2,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        path = P.persist(self.vault, res)
        self.assertEqual(path, C.result_path(self.vault, res["changeset_id"]))
        # And the canonical path is genuinely inside changes/, not the vault root.
        self.assertEqual(os.path.dirname(path), os.path.join(self.vault, "changes"))

    def test_timeline_appends_rather_than_truncates(self):
        res = {"changeset_id": "20260812-101500-abcd1234", "applied": 1,
               "status": "ok", "finished_at": "2026-08-12T10:20:00Z"}
        P.persist(self.vault, res)
        P.persist(self.vault, dict(res, changeset_id="20260812-111500-beef5678"))
        with open(os.path.join(self.vault, "timeline.md")) as f:
            body = f.read()
        self.assertIn("abcd1234", body)
        self.assertIn("beef5678", body)


class TestSymlinkEscape(_VaultBase):
    """C1 (final whole-branch review). persist() runs HOST-SIDE and writes into
    data/vaults — the one tree Hermes has read-write. Every destination it opens is
    therefore attacker-shaped, and a plain open() follows a symlink out of the vault
    into anything the host user can reach: the governance store's kill switch (create
    it => mutation globally enabled) or the audit log (truncate it => the cap
    consumption the guards count is erased).

    The refusals below are only evidence because TestPersistControl proves the
    ordinary, non-symlinked write still succeeds against the same code.
    """

    def _kill_switch(self):
        p = governance_lib.kill_switch_path(self.outside)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def test_symlinked_timeline_pointing_outside_the_vault_is_refused(self):
        """The demonstrated attack: timeline.md is appended with O_APPEND|O_CREAT, so
        following it CREATES the kill switch — which is the whole enable-mutation
        primitive, since kill_switch_ok() only asks whether the file exists."""
        target = self._kill_switch()
        self.assertFalse(os.path.exists(target))
        os.symlink(target, os.path.join(self.vault, "timeline.md"))
        with self.assertRaises(ValueError):
            P.persist(self.vault, RESULT)
        self.assertFalse(os.path.exists(target),
                         "the symlink target was created — the kill switch is writable "
                         "from the vault")

    def test_symlinked_result_tmp_is_refused(self):
        """The second demonstrated attack: the .tmp write is O_TRUNC, so following it
        truncates whatever it points at — here the audit log, whose records are the
        reversibility record and the daily-cap count."""
        target = os.path.join(self.outside, "log", "acme-dental.jsonl")
        os.makedirs(os.path.dirname(target))
        original = b'{"status":"applied","ts":"2026-08-12T10:00:00Z"}\n' * 3
        with open(target, "wb") as f:
            f.write(original)
        changes = os.path.join(self.vault, "changes")
        os.makedirs(changes)
        os.symlink(target, C.result_path(self.vault, RESULT["changeset_id"]) + ".tmp")
        with self.assertRaises(ValueError):
            P.persist(self.vault, RESULT)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), original, "the audit log was rewritten through "
                                                 "the .tmp symlink")

    def test_symlinked_result_json_is_refused(self):
        """The final rename is not the only reachable step: refuse a symlinked
        destination outright rather than relying on rename's non-following semantics."""
        target = os.path.join(self.outside, "clients.json")
        with open(target, "w") as f:
            f.write("{}")
        changes = os.path.join(self.vault, "changes")
        os.makedirs(changes)
        os.symlink(target, C.result_path(self.vault, RESULT["changeset_id"]))
        with self.assertRaises(ValueError):
            P.persist(self.vault, RESULT)
        with open(target) as f:
            self.assertEqual(f.read(), "{}")

    def test_symlinked_changes_directory_is_refused(self):
        """makedirs(exist_ok=True) succeeds on a symlink-to-directory, so the
        containment check has to cover the intermediate component too."""
        target = os.path.join(self.outside, "log")
        os.makedirs(target)
        os.symlink(target, os.path.join(self.vault, "changes"))
        with self.assertRaises(ValueError):
            P.persist(self.vault, RESULT)
        self.assertEqual(os.listdir(target), [])

    def test_vault_that_is_itself_a_symlink_is_refused(self):
        vault = os.path.join(self.root, "other-clinic")
        os.symlink(self.outside, vault)
        with self.assertRaises(ValueError):
            P.persist(vault, RESULT)
        self.assertEqual(sorted(os.listdir(self.outside)), [])

    def test_vault_outside_the_configured_root_is_refused(self):
        """Containment is checked against the resolved VAULT_ROOT, not merely against
        whatever directory the caller happened to pass."""
        stray = os.path.join(self.outside, "acme-dental")
        os.makedirs(stray)
        with self.assertRaises(ValueError):
            P.persist(stray, RESULT)
        self.assertEqual(os.listdir(stray), [])

    def test_a_directory_where_timeline_belongs_is_refused_not_crashed(self):
        os.mkdir(os.path.join(self.vault, "timeline.md"))
        with self.assertRaises(ValueError):
            P.persist(self.vault, RESULT)


class TestPersistControl(_VaultBase):
    """The control the refusals above depend on: with nothing planted, the same
    persist() call must still write both artifacts and touch nothing outside."""

    def test_ordinary_persist_succeeds_and_writes_only_inside_the_vault(self):
        before = sorted(os.listdir(self.outside))
        path = P.persist(self.vault, RESULT)
        with open(path) as f:
            self.assertEqual(json.load(f)["applied"], 2)
        with open(os.path.join(self.vault, "timeline.md")) as f:
            self.assertIn(RESULT["changeset_id"], f.read())
        self.assertEqual(sorted(os.listdir(self.outside)), before)


class TestMain(_VaultBase):
    """Deferred minor #11: persist-run-record.py's main() had no automated cover."""

    def setUp(self):
        super().setUp()
        self._old_gov = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.outside
        self.addCleanup(self._restore_gov)
        reg = governance_lib.clients_registry_path(self.outside)
        os.makedirs(os.path.dirname(reg), exist_ok=True)
        with open(reg, "w") as f:
            json.dump({"clients": {"acme-dental": {"project": "claude_google_ads",
                                                   "customer_id": "1234567890",
                                                   "status": "active"}}}, f)

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
        self.assertFalse(os.path.exists(os.path.join(self.vault, "timeline.md")))

    def test_output_passes_through_unchanged(self):
        text = "apply-changeset: ok\nHERMES-RESULT-JSON %s\n" % json.dumps(RESULT)
        rc, out = self._run(["--client", "acme-dental"], text)
        self.assertEqual(rc, 0)
        self.assertEqual(out, text)
        self.assertTrue(os.path.exists(C.result_path(self.vault, RESULT["changeset_id"])))

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

    Uses `P` (persist_run_record_shim), the same alias the rest of this file already
    uses — not the `PR` alias the original task brief used, which does not exist in
    this file's imports.
    """

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="vaultroot-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.vault = os.path.join(self.root, "pilot-1")
        os.makedirs(os.path.join(self.vault, "changes"), exist_ok=True)
        self.result = {"changeset_id": "20260824-101500-abcdef01",
                       "status": "applied", "applied": 1,
                       "finished_at": "2026-08-24T10:15:00Z"}

    def test_control_a_normal_persist_still_works(self):
        # The must-SUCCEED control. Three refusals are about to be added; if any of
        # them over-reaches, this is the test that catches it.
        p = P.persist(self.vault, self.result, root=self.root)
        self.assertTrue(os.path.isfile(p))

    # --- (a) hardlinks -------------------------------------------------------------
    def test_a_hardlinked_timeline_is_refused(self):
        # O_NOFOLLOW does not see a hardlink and S_ISREG accepts one, so both existing
        # barriers pass it. With the broker running this step as the governance store's
        # OWNER, a hardlink from the vault to a store file is a write primitive.
        outside = os.path.join(self.root, "outside.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        os.link(outside, os.path.join(self.vault, "timeline.md"))
        with self.assertRaises(P.PersistRefused) as cm:
            P.persist(self.vault, self.result, root=self.root)
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
        # the vault be swapped is exactly the kind of coincidence R20(a) exists to
        # surface as a named refusal rather than best-effort silence.
        outside = os.path.join(self.root, "outside2.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        dest = os.path.join(self.vault, "changes",
                            "20260824-101500-abcdef01.result.json")
        os.link(outside, dest)
        with self.assertRaises(P.PersistRefused):
            P.persist(self.vault, self.result, root=self.root)
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")

    def test_control_a_single_linked_file_is_accepted(self):
        # Proves the nlink check refuses hardlinks specifically and not ordinary
        # pre-existing files.
        with open(os.path.join(self.vault, "timeline.md"), "w") as f:
            f.write("- earlier\n")
        self.assertTrue(os.path.isfile(P.persist(self.vault, self.result,
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
        tmp_dest = os.path.join(self.vault, "changes",
                                "20260824-101500-abcdef01.result.json.tmp")
        os.link(outside, tmp_dest)

        real_refuse = P._refuse_if_hardlinked
        P._refuse_if_hardlinked = lambda *a, **k: None
        try:
            with self.assertRaises(P.PersistRefused):
                P.persist(self.vault, self.result, root=self.root)
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
    # gutted back to path-based opens on the result-file branch (mutation row 3
    # below), it stayed green because those two strings still appear elsewhere in the
    # file (in _open_dir and in the untouched timeline.md call). A test whose name
    # claims a property it structurally cannot verify is worse than no test — it
    # reads as coverage to a future reader. The behavioural test immediately below
    # fully supersedes it and is the one mutation-proven to catch that regression.

    def test_dirfd_chain_resists_a_swapped_changes_directory(self):
        """Behavioural companion to the canary above. Hooks `P._open_dir` to swap the
        `changes` directory ENTRY, by path, in the exact gap between persist() opening
        it (capturing a directory descriptor via openat) and persist() writing through
        that descriptor. A descriptor obtained via open()/openat() refers to the
        underlying inode, not the name used to obtain it — an os.rename() of that name
        afterwards cannot redirect it. If persist() re-resolved the path instead of
        reusing the descriptor, the write would land in the ATTACKER directory that
        now occupies the `changes` name; if it genuinely uses the descriptor, the
        write lands in the original directory regardless of what `changes` now names.
        """
        original_changes = os.path.join(self.vault, "changes")
        attacker_dir = os.path.join(self.root, "attacker-changes")
        os.makedirs(attacker_dir, exist_ok=True)
        displaced = os.path.join(self.vault, "changes-displaced")

        real_open_dir = P._open_dir
        state = {"swapped": False}

        def swapping_open_dir(name, dir_fd=None):
            fd = real_open_dir(name, dir_fd=dir_fd)
            # Only the call that opens "changes" RELATIVE TO the vault fd — the
            # vault-level open itself (dir_fd=None) must be left alone, or nothing
            # would be left to open the (now-renamed) changes directory through.
            if not state["swapped"] and name == "changes" and dir_fd is not None:
                state["swapped"] = True
                os.rename(original_changes, displaced)
                os.rename(attacker_dir, original_changes)
            return fd

        P._open_dir = swapping_open_dir
        try:
            path = P.persist(self.vault, self.result, root=self.root)
        finally:
            P._open_dir = real_open_dir

        self.assertTrue(state["swapped"], "the hook never fired — test is not "
                        "exercising the swap it claims to")
        # The write must have landed in the ORIGINAL directory (now renamed aside),
        # not in the attacker directory that currently occupies the "changes" name.
        self.assertTrue(os.path.isfile(os.path.join(displaced, os.path.basename(path))))
        self.assertEqual(os.listdir(original_changes), [],
                         "the write followed the swapped NAME instead of the "
                         "descriptor captured before the swap — the TOCTOU is open")

    def test_a_symlinked_changes_directory_is_still_refused(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere, exist_ok=True)
        changes = os.path.join(self.vault, "changes")
        os.rmdir(changes)
        os.symlink(elsewhere, changes)
        with self.assertRaises(P.PersistRefused):
            P.persist(self.vault, self.result, root=self.root)

    def test_a_changes_symlink_resolving_back_inside_the_vault_is_still_refused(self):
        # Companion to the test above, added while investigating whether deleting
        # _resolve_subdir's own `os.path.islink(p)` check is a killable mutation.
        # `elsewhere` above is OUTSIDE the vault, so _resolve_subdir's downstream
        # _contained() check catches it independently of the islink check — that
        # mutation does not turn it red. This variant targets a symlink whose target
        # resolves BACK inside the vault, which slips past _contained() too (the
        # target IS contained), on the theory that only the islink check would be
        # left to catch it.
        #
        # MEASURED: it still does not turn red when the islink check is deleted.
        # _open_dir("changes", dir_fd=vfd), added for R20(b), opens the "changes"
        # component with O_NOFOLLOW independently of anything _resolve_subdir
        # decided — so a symlinked "changes" is refused by the dirfd chain itself
        # regardless of target. That makes _resolve_subdir's islink check genuinely
        # redundant now (good: defense in depth), but also means no behavioural test
        # can distinguish "the islink check ran" from "the dirfd open blocked it
        # anyway" — this mutation row is UNKILLABLE with the current architecture.
        # Kept as coverage of the resolves-back-inside-vault case, not as a killer.
        decoy = os.path.join(self.vault, "decoy")
        os.makedirs(decoy, exist_ok=True)
        changes = os.path.join(self.vault, "changes")
        os.rmdir(changes)
        os.symlink(decoy, changes)
        with self.assertRaises(P.PersistRefused):
            P.persist(self.vault, self.result, root=self.root)

    # --- (c) makedirs before the containment check ---------------------------------
    def test_an_out_of_root_vault_is_refused_without_being_created(self):
        outside = os.path.join(tempfile.mkdtemp(), "not-in-the-root")
        with self.assertRaises(P.PersistRefused):
            P.persist(outside, self.result, root=self.root)
        # The mkdir belongs BELOW the check: refusing after creating the directory
        # leaves an attacker-chosen path on disk.
        self.assertFalse(os.path.exists(outside))


if __name__ == "__main__":
    unittest.main()
