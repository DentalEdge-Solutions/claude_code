import contextlib, importlib.util, io, json, os, shutil, sys, tempfile, unittest

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


if __name__ == "__main__":
    unittest.main()
