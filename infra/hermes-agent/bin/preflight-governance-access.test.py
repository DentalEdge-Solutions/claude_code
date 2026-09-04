import importlib.util, io, os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PF = _load("preflight_governance_access", "preflight-governance-access.py")

ALL_DIRS = PF.READ_ONLY_DIRS + PF.READ_WRITE_DIRS


class Base(unittest.TestCase):
    """A governance store laid out the way the real one is, with every subdirectory
    present so a reported problem is about MODE, never about absence."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="governance-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        # Restore traversable modes before the rmtree above runs (cleanups run LIFO),
        # or a test that removes owner-x leaves the tempdir behind.
        self.addCleanup(self._restore_modes)
        for name in ALL_DIRS:
            os.makedirs(os.path.join(self.root, name))
        self.uid = os.getuid()
        self.gid = os.getgid()
        # A UID that is definitely not this process's owner, and a GID likewise:
        # the executor's real UID (10000) may coincidentally match on some hosts,
        # which would silently turn every negative test into a control.
        self.other_uid = self.uid + 4242
        self.other_gid = self.gid + 4242

    def _restore_modes(self):
        os.chmod(self.root, 0o700)
        for name in ALL_DIRS:
            p = os.path.join(self.root, name)
            if os.path.isdir(p):
                os.chmod(p, 0o700)

    def _chmod_all(self, mode):
        # Children first: dropping owner-x on the root would make the children
        # unreachable for their own chmod.
        for name in ALL_DIRS:
            os.chmod(os.path.join(self.root, name), mode)
        os.chmod(self.root, mode)


class TestLinuxSemantics(Base):
    """platform is passed explicitly so these run identically on macOS and on the VPS —
    the whole point of the finding is that the local host cannot reproduce the VPS."""

    def test_mode_700_owned_by_someone_else_is_refused(self):
        """The exact VPS condition: store owned by the deploy user at 700, executor
        running as uid 10000."""
        self._chmod_all(0o700)
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS) + 1)     # +1 for the root itself
        for name in ALL_DIRS:
            self.assertTrue(any(name in p for p in problems), name)

    def test_control_same_store_same_mode_but_the_owning_uid_passes(self):
        """CONTROL. Without this the refusal above proves only that the function can
        return something — it must ACCEPT the identical layout when the UID matches."""
        self._chmod_all(0o700)
        self.assertEqual(PF.check(self.root, self.uid, self.gid, platform="linux"), [])

    def test_group_readable_store_with_a_matching_gid_passes(self):
        """The documented remedy: keep the store off `other`, grant the executor's
        group. log/ is 2750 — group read+traverse, NO group write (write on the
        directory is what grants unlink), setgid so host-created log files inherit
        gid 10000."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_group_writable_log_dir_still_passes_because_it_over_grants(self):
        """HONEST NEGATIVE RESULT, recorded rather than hidden. This gate checks that
        the executor CAN work, not that it is minimally privileged, so the old 0770
        layout still returns zero problems — the pre-flight is NOT what stops an
        operator re-widening log/. The deploy documentation and REMEDY text are, and
        Task 5's container probe is what measures the difference. Asserting a refusal
        here would be asserting a guarantee this script does not make."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o770)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_world_readable_store_passes_the_dirs_but_flags_an_unwritable_log_file(self):
        """S3-b moved the write requirement from the DIRECTORY to the FILE. 0o755
        throughout is now a correct layout for log/ itself — r-x is all append_log needs
        from the directory — so the directory pass here is not a weakened check, it is
        the check landing on the right object. The requirement did not go away: an
        existing log/<slug>.jsonl the executor cannot append to is still exactly the
        mid-apply exit-3 this script exists to prevent, and is still reported."""
        self._chmod_all(0o755)
        log_file = os.path.join(self.root, "log", "acme.jsonl")
        with open(log_file, "w") as f:
            f.write("{}\n")
        os.chmod(log_file, 0o644)          # readable, NOT writable by group or other
        problems = PF.check(self.root, self.other_uid, self.other_gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("acme.jsonl", problems[0])
        for name in PF.READ_ONLY_DIRS:
            self.assertFalse(any("%s:" % name in p for p in problems), name)

    def test_control_the_same_store_with_an_appendable_log_file_is_healthy(self):
        """POSITIVE CONTROL for the test above. Without it, that assertion would also
        pass against an implementation that reported every log file as a problem."""
        self._chmod_all(0o755)
        log_file = os.path.join(self.root, "log", "acme.jsonl")
        with open(log_file, "w") as f:
            f.write("{}\n")
        os.chmod(log_file, 0o666)
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.other_gid, platform="linux"), [])

    def test_owner_class_wins_even_when_group_and_other_are_wider(self):
        """POSIX selects exactly ONE permission class. A directory owned by the
        executor at mode 0o077 is unreadable to it however wide `other` is; an
        implementation that OR'd the classes would wrongly pass this."""
        self._chmod_all(0o077)
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertEqual(len(problems), len(ALL_DIRS) + 1)

    def test_a_missing_subdirectory_is_reported(self):
        self._chmod_all(0o755)
        os.rmdir(os.path.join(self.root, "control"))
        problems = PF.check(self.root, self.uid, self.gid, platform="linux")
        self.assertTrue(any("control" in p and "cannot stat" in p for p in problems))


class TestFileLevelChecks(Base):
    """R19: check() historically stat'd the governance ROOT and its five DIRECTORIES
    only, never the FILES inside them. Directories at 0770 with a matching gid but
    log/<slug>.jsonl or registry/clients.json at 0600 owned by the deploy user returned
    ZERO problems — yet append_log opens that existing log file with mode "a", which is
    exactly the mid-apply exit-3 this whole script exists to prevent."""

    SLUG = "acme"
    CID = "20260101-000000-deadbeef"

    def _configure_group_readable_dirs(self):
        """The documented remedy layout (S3-b): root and read-only dirs at 0750, and
        log/ at 2750 — group read+traverse but NOT group write, because directory write
        is what grants unlink, and setgid so host-created log files inherit the
        executor's group. append_log fsyncs the log/ directory fd, so r-x is required
        and traverse alone would not do. Mirrors
        test_group_readable_store_with_a_matching_gid_passes above."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)

    def _configure_full_correct_store(self):
        """Directories AND files all at the correct mode for a group-matching
        executor. This is the positive control every negative test below starts from —
        breaking exactly one file's mode is the only difference."""
        self._configure_group_readable_dirs()
        for name in PF.READ_WRITE_DIRS:  # log/
            p = os.path.join(self.root, name, "%s.jsonl" % self.SLUG)
            with open(p, "w") as f:
                f.write("{}\n")
            os.chmod(p, 0o660)
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        with open(reg, "w") as f:
            f.write("{}")
        os.chmod(reg, 0o640)
        switch = os.path.join(self.root, *PF.KILL_SWITCH_REL)
        open(switch, "w").close()
        os.chmod(switch, 0o640)
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        os.makedirs(slug_dir)
        os.chmod(slug_dir, 0o750)
        for suffix in ("approval.json", "changeset.json"):
            p = os.path.join(slug_dir, "%s.%s" % (self.CID, suffix))
            open(p, "w").close()
            os.chmod(p, 0o640)

    def test_control_fully_correct_store_including_files_is_healthy(self):
        """POSITIVE CONTROL. Without this, the negative tests below prove nothing — a
        check that reported every file as a problem would also "pass" them."""
        self._configure_full_correct_store()
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_fresh_store_with_correct_dirs_and_no_files_is_healthy(self):
        """Design point 1: a file that does not exist is NOT a problem. Absence is the
        normal resting state — no kill switch means mutation disabled (the safe
        default), no log yet means no applies yet. A check that treated a missing file
        as a problem would turn a healthy fresh store into a refusal."""
        self._configure_group_readable_dirs()
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_existing_log_file_with_bad_mode_is_reported(self):
        """THE NEGATIVE. The exact case that returned zero problems before this fix:
        directories correct (2750, matching gid), but an existing log/<slug>.jsonl at
        an owner-only mode. append_log opens this file with mode "a" — this is the
        mid-apply exit-3 the pre-flight exists to prevent."""
        self._configure_full_correct_store()
        log_file = os.path.join(self.root, "log", "%s.jsonl" % self.SLUG)
        os.chmod(log_file, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("log" in p and "acme.jsonl" in p for p in problems))

    def test_seen_set_is_not_an_executor_requirement(self):
        """S3-a, the COUPLED half of dropping seen/ from ads-mutator's mounts.

        A REALISTIC store: seen/ exists next to log/, owned by the host user at a mode
        that gives the executor's uid nothing at all — 0o700 on the directory and 0o600
        on the per-client file inside it, which is what the real store looks like. That
        used to be two problems and a refusal. It must now be ZERO, because the
        executor no longer has seen/ mounted and no code path under its entrypoint
        touches the seen-set (every caller is host-side in hermes-broker.py).

        Reporting a problem here would be a FALSE REFUSAL that blocks broker startup
        over a path the executor cannot even see — the same over-checking failure as
        R19b, which is exactly as harmful as under-checking. The mode chosen is
        deliberately the harshest one available: if the seen/ tree were still being
        walked, this could not return an empty list."""
        self._configure_full_correct_store()
        seen_dir = os.path.join(self.root, "seen")
        os.makedirs(seen_dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, seen_dir, True)
        seen_file = os.path.join(seen_dir, "%s.jsonl" % self.SLUG)
        with open(seen_file, "w") as f:
            f.write("{}\n")
        os.chmod(seen_file, 0o600)
        os.chmod(seen_dir, 0o700)
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])
        self.assertNotIn("seen", PF.READ_WRITE_DIRS)
        self.assertNotIn("seen", PF.READ_ONLY_DIRS)

    def test_control_the_same_harsh_mode_on_log_IS_still_reported(self):
        """DISCRIMINATING CONTROL for the test above. Identical construction, on log/
        instead of seen/. If this also returned [], the test above would prove only
        that check() had gone blind — not that seen/ was deliberately dropped."""
        self._configure_full_correct_store()
        log_file = os.path.join(self.root, "log", "%s.jsonl" % self.SLUG)
        os.chmod(log_file, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("log" in p and "acme.jsonl" in p for p in problems))

    def test_a_rotated_log_does_not_false_refuse_and_block_startup(self):
        """S5-M2. log/ was walked with NO allowlist, so EVERY regular file in it had to
        be executor-writable. A rotated log or an operator's backup — files the
        executor never opens — refused the pre-flight and took the whole mutation rail
        down at startup. That is R19b's over-checking failure on a path R19 did not
        cover, and over-checking is as harmful as under-checking.

        Every name here is at the harshest mode available, so a walk that still looked
        at them could not possibly return an empty list."""
        self._configure_full_correct_store()
        log_dir = os.path.join(self.root, "log")
        for junk in ("%s.jsonl.1" % self.SLUG,          # logrotate
                     "%s.jsonl.bak" % self.SLUG,        # operator backup
                     "%s.jsonl.gz" % self.SLUG,         # compressed rotation
                     "%s.jsonl.tmp" % self.SLUG,        # interrupted write
                     ".DS_Store", "notes.txt", "README"):
            p = os.path.join(log_dir, junk)
            with open(p, "w") as f:
                f.write("x")
            os.chmod(p, 0o600)                          # executor gets nothing at all
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_control_the_real_client_log_is_STILL_checked(self):
        """DISCRIMINATING CONTROL, and the one that matters: an allowlist that excluded
        everything would pass the test above while checking nothing at all. The file
        the executor actually appends to must still be reported at the same mode the
        junk above is ignored at."""
        self._configure_full_correct_store()
        log_file = os.path.join(self.root, "log", "%s.jsonl" % self.SLUG)
        os.chmod(log_file, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("%s.jsonl" % self.SLUG, problems[0])

    def test_the_log_allowlist_matches_exactly_what_append_log_opens(self):
        """Unit-level, so the allowlist's shape is pinned independently of the store
        fixture. It must accept precisely `<slug>.jsonl` for a governance_lib slug —
        the only name changeset_lib.log_path can ever produce — and nothing else."""
        for good in ("acme.jsonl", "acme-dental.jsonl", "a.jsonl", "a_b-9.jsonl"):
            self.assertTrue(PF.is_client_log_name(good), good)
        for bad in ("acme.jsonl.1", "acme.jsonl.bak", "acme.jsonl.gz", "acme.jsonl.tmp",
                    ".DS_Store", "notes.txt", "acme.json", ".jsonl", "jsonl",
                    "ACME.jsonl", "-acme.jsonl", "../etc.jsonl", "a/b.jsonl"):
            self.assertFalse(PF.is_client_log_name(bad), bad)

    def test_the_allowlist_shares_one_definition_of_a_slug(self):
        """Matched against governance_lib.SLUG_RE itself rather than a restated
        pattern. Restating it is how two validators drift into disagreeing about what a
        slug is — the failure this repo names explicitly elsewhere."""
        self.assertTrue(PF.is_client_log_name("x" * 64 + ".jsonl"))
        self.assertFalse(PF.is_client_log_name("x" * 65 + ".jsonl"))

    def test_existing_kill_switch_file_with_bad_mode_is_reported(self):
        """control/mutation-enabled is READ-required, not read+write — a distinct code
        path from log/ and seen/. When it exists with a bad mode it must be reported,
        even though its absence must not be."""
        self._configure_full_correct_store()
        switch = os.path.join(self.root, *PF.KILL_SWITCH_REL)
        os.chmod(switch, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("mutation-enabled" in p for p in problems))

    def test_existing_clients_registry_file_with_bad_mode_is_reported(self):
        self._configure_full_correct_store()
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        os.chmod(reg, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("clients.json" in p for p in problems))

    def test_existing_approval_file_with_bad_mode_is_reported(self):
        """approvals/ is nested one level by client slug — this exercises that walk,
        not just the flat directories."""
        self._configure_full_correct_store()
        approval = os.path.join(self.root, "approvals", self.SLUG,
                                 "%s.approval.json" % self.CID)
        os.chmod(approval, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("approval.json" in p for p in problems))

    def test_existing_changeset_snapshot_file_with_bad_mode_is_reported(self):
        self._configure_full_correct_store()
        snapshot = os.path.join(self.root, "approvals", self.SLUG,
                                 "%s.changeset.json" % self.CID)
        os.chmod(snapshot, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("changeset.json" in p for p in problems))

    def test_approval_lock_sidecar_is_ignored_healthy_store_stays_healthy(self):
        """FINDING 1 regression (CRITICAL). approvals/<slug>/ also holds
        <cid>.approval.lock (governance_lib.approval_lock_path), created 0600 by
        changeset_lib._approval_lock and deliberately never unlinked — removing it
        would reopen a wrong-inode race. It is HOST-SIDE ONLY: hermes-broker.py takes
        it, apply-changeset.py (the executor) never references approval_lock_path at
        all. A store that has ever reserved a change-set must still report ZERO
        problems even though this sidecar sits there at an executor-unreadable 0600 —
        demanding it be readable would false-refuse every such store, which is exactly
        the class of bug R19 exists to fix, one level down."""
        self._configure_full_correct_store()
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        lock = os.path.join(slug_dir, "%s.approval.lock" % self.CID)
        open(lock, "w").close()
        os.chmod(lock, 0o600)  # exactly as changeset_lib._approval_lock creates it
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_approval_lock_sidecar_present_does_not_mask_a_real_approval_problem(self):
        """PAIRED NEGATIVE for Finding 1. Without this, "fixing" the false refusal
        above by skipping the approvals walk entirely would also pass — this proves
        the allowlist still catches a genuinely unreadable .approval.json sitting in
        the very same directory as an ignorable .approval.lock."""
        self._configure_full_correct_store()
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        lock = os.path.join(slug_dir, "%s.approval.lock" % self.CID)
        open(lock, "w").close()
        os.chmod(lock, 0o600)
        approval = os.path.join(slug_dir, "%s.approval.json" % self.CID)
        os.chmod(approval, 0o600)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(any("approval.json" in p for p in problems))
        self.assertFalse(any("approval.lock" in p for p in problems))

    def test_kill_switch_path_that_is_a_directory_is_reported_not_a_regular_file(self):
        """FINDING 3: the fixed-name _check_file path's "not a regular file" branch is
        reachable with no root and no foreign uid — a directory sitting where a file
        is expected is enough."""
        self._configure_full_correct_store()
        switch = os.path.join(self.root, *PF.KILL_SWITCH_REL)
        os.remove(switch)
        os.makedirs(switch)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(
            any("mutation-enabled" in p and "not a regular file" in p
                for p in problems))

    def test_approvals_slug_dir_that_the_executor_cannot_traverse_is_reported(self):
        """S5-M1. Nothing checked the slug DIRECTORY's own bits, only the files inside
        it — and the file walk runs as this process (the host user, who can happily
        list its own 0700 directory), so it modelled nothing about the executor's
        access to the directory itself. Measured before the fix: a host-owned 0700 slug
        dir returned ZERO problems, while a 0600 file inside it returned one. The check
        saw through a door the executor cannot open, to files behind it."""
        self._configure_full_correct_store()
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        os.chmod(slug_dir, 0o700)                       # owner-only: executor gets ---
        self.addCleanup(os.chmod, slug_dir, 0o750)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertTrue(any(slug_dir in p and "read+traverse" in p for p in problems),
                        problems)

    def test_control_the_same_store_at_the_documented_mode_is_still_healthy(self):
        """R19b GUARD, and the half that matters more. This is a TIGHTENING of a gate
        that blocks broker startup, so the documented-remedy layout must still return
        ZERO problems — a check that cries wolf on a healthy store is one operators
        learn to disable, which is worse than the gap it closed."""
        self._configure_full_correct_store()
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_the_slug_dir_is_not_required_to_be_writable(self):
        """The executor READS approvals and never writes them; approvals/ is mounted
        :ro into it. Demanding write here would false-refuse every correct store — the
        exact over-checking shape R19 hit three times. A group r-x directory with no
        write bit must be healthy."""
        self._configure_full_correct_store()
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        os.chmod(slug_dir, 0o750)                       # group r-x, no w
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_approvals_slug_dir_that_cannot_be_stat_is_reported_not_raised(self):
        """FINDING 4: forced deterministically via a scoped mock rather than chmod,
        because chmod-based reproduction of "cannot access" is unreliable when the
        test runner is root — root bypasses POSIX permission checks entirely, so
        chmod 000 would not actually block anything."""
        self._configure_full_correct_store()
        slug_dir = os.path.join(self.root, "approvals", self.SLUG)
        real_lstat = os.lstat

        def fake_lstat(path, *a, **kw):
            if path == slug_dir:
                raise OSError(13, "Permission denied")
            return real_lstat(path, *a, **kw)

        with mock.patch.object(PF.os, "lstat", side_effect=fake_lstat):
            problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertTrue(
            any(slug_dir in p and "cannot stat" in p for p in problems))


class TestScope(Base):
    def test_non_linux_reports_nothing_even_when_unreadable(self):
        """Deliberate scope, not an oversight: Docker Desktop remaps ownership on
        macOS, so a stat-based prediction there would be false. Paired with the Linux
        test above, which refuses the identical layout."""
        self._chmod_all(0o700)
        self.assertEqual(PF.check(self.root, self.other_uid, self.other_gid,
                                  platform="darwin"), [])
        self.assertFalse(PF.applies("darwin"))
        self.assertTrue(PF.applies("linux"))

    def test_non_linux_ignores_file_level_problems_too(self):
        """Same guard, extended to files (R19): an existing log/<slug>.jsonl at an
        owner-only mode predicts nothing on macOS either, for the identical reason —
        Docker Desktop remaps ownership there, so a stat-based prediction on the FILE
        would be just as false as one on the directory."""
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)
        log_file = os.path.join(self.root, "log", "acme.jsonl")
        with open(log_file, "w") as f:
            f.write("{}\n")
        os.chmod(log_file, 0o600)
        self.assertEqual(
            PF.check(self.root, self.other_uid, self.gid, platform="darwin"), [])


class TestCli(Base):
    def _main(self, argv):
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            rc = PF.main(argv)
        finally:
            sys.stderr = old
        return rc, err.getvalue()

    def test_cli_exits_zero_when_the_store_is_usable(self):
        self._chmod_all(0o700)
        rc, _ = self._main(["--root", self.root, "--uid", str(self.uid),
                            "--gid", str(self.gid)])
        self.assertEqual(rc, 0)

    @unittest.skipUnless(PF.applies(), "stat-based prediction only holds on Linux")
    def test_cli_exits_two_and_names_the_remedy(self):
        self._chmod_all(0o700)
        rc, err = self._main(["--root", self.root, "--uid", str(self.other_uid),
                              "--gid", str(self.other_gid)])
        self.assertEqual(rc, 2)
        self.assertIn("chown", err)
        self.assertIn("Do NOT `chmod 777`", err)


class TestRegisteredClientLogs(Base):
    """S3-b/D2. Under the append-but-not-unlink layout the executor cannot CREATE
    log/<slug>.jsonl, so a registered client with no log is a store it cannot use —
    R19's own class of finding, and R19 exists so that surfaces at startup rather than
    mid-apply as exit 3 after a live account change."""

    def _write_registry(self, text):
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        with open(reg, "w") as f:
            f.write(text)
        os.chmod(reg, 0o640)

    def _healthy_dirs(self):
        os.chmod(self.root, 0o750)
        for name in PF.READ_ONLY_DIRS:
            os.chmod(os.path.join(self.root, name), 0o750)
        for name in PF.READ_WRITE_DIRS:
            os.chmod(os.path.join(self.root, name), 0o2750)

    def test_a_registered_client_without_a_log_is_refused(self):
        self._healthy_dirs()
        self._write_registry('{"clients": {"acme-dental": {"status": "active"}}}')
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("--bootstrap-logs", problems[0])

    def test_control_the_same_registry_with_the_log_present_is_healthy(self):
        """POSITIVE CONTROL. Without it the refusal above would also pass against a
        check that refused every store with a non-empty registry."""
        self._healthy_dirs()
        self._write_registry('{"clients": {"acme-dental": {"status": "active"}}}')
        p = os.path.join(self.root, "log", "acme-dental.jsonl")
        with open(p, "w"):
            pass
        os.chmod(p, 0o660)
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_the_refusal_names_a_count_not_the_slugs(self):
        """Client slugs are client-private and this text reaches stderr, which the
        systemd journal captures under Phase B. vault_lib.resolve_dormant_pilot makes
        the same choice for the same reason."""
        self._healthy_dirs()
        self._write_registry(
            '{"clients": {"acme-dental": {"status": "active"}, '
            '"other-clinic": {"status": "dormant_pilot"}}}')
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertEqual(len(problems), 1)
        self.assertIn("2", problems[0])
        self.assertNotIn("acme-dental", problems[0])
        self.assertNotIn("other-clinic", problems[0])

    def test_an_unparseable_registry_is_refused(self):
        self._healthy_dirs()
        self._write_registry("{not json")
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertTrue(any("registry" in p for p in problems))

    def test_a_registry_this_process_cannot_read_is_not_double_reported(self):
        """Ruling 9. This is the ONLY check in the module that does real I/O rather than
        simulating access for a hypothetical (uid, gid). When the checking process itself
        cannot read the registry, the registry/ directory check has ALREADY reported that
        fault — adding a second problem for the same cause counts one fault twice and
        breaks the exact-count assertions, which is R19b's over-checking failure again."""
        self._healthy_dirs()
        self._write_registry('{"clients": {"acme-dental": {"status": "active"}}}')
        reg = os.path.join(self.root, *PF.CLIENTS_REGISTRY_REL)
        os.chmod(reg, 0o000)                       # unreadable by THIS process
        self.addCleanup(os.chmod, reg, 0o640)
        problems = PF.check(self.root, self.other_uid, self.gid, platform="linux")
        self.assertFalse(any("malformed" in p for p in problems))

    def test_an_absent_registry_is_not_a_fault(self):
        """Absence stays absence. _check_file already treats a missing registry as the
        normal resting state of a fresh store, and this check must not change that —
        turning a fresh store into a refusal is R19b's cry-wolf failure."""
        self._healthy_dirs()
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])

    def test_an_empty_registry_requires_nothing(self):
        self._healthy_dirs()
        self._write_registry('{"clients": {}}')
        self.assertEqual(PF.check(self.root, self.other_uid, self.gid, platform="linux"), [])


if __name__ == "__main__":
    unittest.main()
