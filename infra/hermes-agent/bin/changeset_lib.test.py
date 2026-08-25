import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import governance_lib as G

def _action(**kw):
    a = {"type": "add_campaign_negative", "campaign_id": "22233344455",
         "keyword": "free consultation", "match_type": "PHRASE"}
    a.update(kw)
    return a

def _cs(**kw):
    cs = {"changeset_id": "20260812-101500-abcd1234", "client": "acme-dental",
          "project": "claude_google_ads", "customer_id": "1234567890",
          "created_at": "2026-08-12T10:15:00Z", "actions": [_action()]}
    cs.update(kw)
    return cs

class TestAction(unittest.TestCase):
    def test_valid_action_accepted(self):
        self.assertEqual(C.validate_action(_action())["match_type"], "PHRASE")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(type="set_campaign_budget"))

    def test_bad_match_type_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(match_type="EXACTLY"))

    def test_non_digit_campaign_id_rejected(self):
        for bad in ["222-333", "abc", "", "22 33", "1" * 16]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(campaign_id=bad))

    def test_trailing_newline_campaign_id_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(campaign_id="22233344455\n"))

    def test_oversize_keyword_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(keyword="x" * (C.KEYWORD_MAX + 1)))

    def test_control_characters_in_keyword_rejected(self):
        for bad in ["free\nconsult", "free\tconsult", "free\x00consult", "free\x7fconsult"]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(keyword=bad))

    def test_empty_keyword_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(keyword="   "))

    def test_unknown_action_field_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_action(_action(bid_micros=1000))


    def test_numeric_campaign_id_refused(self):
        """A JSON number must not pass a digits-only check via str() coercion — it
        would serialize unquoted and break the schema the approval hash covers."""
        with self.assertRaises(ValueError):
            C.validate_action(_action(campaign_id=22233344455))

    def test_non_string_keyword_refused(self):
        for bad in [12345, None, ["free"], {"t": "free"}]:
            with self.assertRaises(ValueError):
                C.validate_action(_action(keyword=bad))

class TestChangeset(unittest.TestCase):
    def test_valid_changeset_accepted(self):
        self.assertEqual(len(C.validate_changeset(_cs(), 25)["actions"]), 1)

    def test_over_cap_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(actions=[_action()] * 4), 3)

    def test_at_cap_accepted(self):
        self.assertEqual(len(C.validate_changeset(_cs(actions=[_action()] * 3), 3)["actions"]), 3)

    def test_empty_actions_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(actions=[]), 25)

    def test_bad_slug_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(client="../etc"), 25)

    def test_bad_customer_id_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(customer_id="123-456"), 25)

    def test_bad_changeset_id_rejected(self):
        for bad in ["", "nope", "20260812-101500-ABCD1234", "20260812-101500-abcd123"]:
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(changeset_id=bad), 25)

    def test_bad_created_at_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(created_at="2026/08/12 10:15"), 25)

    def test_unknown_top_level_field_rejected(self):
        with self.assertRaises(ValueError):
            C.validate_changeset(_cs(approved=True), 25)

    def test_non_string_identity_fields_refused(self):
        """Type is validated, not coerced — every identity field must be a JSON string."""
        for field, bad in [("changeset_id", 20260812), ("client", 123),
                           ("project", 7), ("customer_id", 1234567890),
                           ("created_at", 20260812101500)]:
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(**{field: bad}), 25)

    def test_null_identity_fields_refused(self):
        for field in ("changeset_id", "client", "project", "customer_id", "created_at"):
            with self.assertRaises(ValueError):
                C.validate_changeset(_cs(**{field: None}), 25)


class TestCanonical(unittest.TestCase):
    def test_canonical_is_key_order_independent(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        self.assertEqual(C.canonical_bytes(a), C.canonical_bytes(b))

    def test_canonical_uses_compact_separators(self):
        """Exact bytes prove compact separators WITHOUT forbidding spaces inside string
        values — a keyword is free text and legitimately contains them."""
        self.assertEqual(C.canonical_bytes({"b": 1, "a": "x y"}), b'{"a":"x y","b":1}')

    def test_canonical_roundtrips(self):
        self.assertEqual(json.loads(C.canonical_bytes(_cs()).decode()), _cs())

    def test_canonical_differs_on_any_value_change(self):
        self.assertNotEqual(C.canonical_bytes(_cs()),
                            C.canonical_bytes(_cs(actions=[_action(keyword="free consult")])))

import tempfile

REG = """version: 1

projects:
  claude_code:
    workdir: /projects/claude_code
    scope: read
  claude_google_ads:
    workdir: /projects/claude_google_ads
    scope: read-execute
    read_execute:
      runner: /opt/ads-venv/bin/python3
      script_dir: code
      allow:
        - account_overview
        - audit_analyze
    mutate_execute:
      runner: /opt/ads-venv/bin/python3   # inline comment must be stripped
      script_dir: code
      allow:
        - mutate_campaign_negative
      caps:
        actions_per_changeset: 25
        actions_per_client_day: 100
        applies_per_client_day: 5
        approval_ttl_hours: 24
"""

def _reg_file(text):
    fd, p = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p

class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.p = _reg_file(REG)

    def test_reads_mutate_execute(self):
        cfg = C.read_mutate_execute(self.p, "claude_google_ads")
        self.assertEqual(cfg["runner"], "/opt/ads-venv/bin/python3")
        self.assertEqual(cfg["script_dir"], "code")
        self.assertEqual(cfg["allow"], ["mutate_campaign_negative"])

    def test_reads_caps_as_ints(self):
        caps = C.read_mutate_execute(self.p, "claude_google_ads")["caps"]
        self.assertEqual(caps["actions_per_changeset"], 25)
        self.assertEqual(caps["applies_per_client_day"], 5)
        self.assertIsInstance(caps["approval_ttl_hours"], int)

    def test_read_execute_entries_do_not_bleed_into_mutate_allow(self):
        cfg = C.read_mutate_execute(self.p, "claude_google_ads")
        self.assertNotIn("account_overview", cfg["allow"])

    def test_project_without_mutate_execute_refused(self):
        with self.assertRaises(ValueError):
            C.read_mutate_execute(self.p, "claude_code")

    def test_unknown_project_refused(self):
        with self.assertRaises(ValueError):
            C.read_mutate_execute(self.p, "no_such_project")

    def test_missing_cap_refuses_rather_than_defaults(self):
        text = REG.replace("        applies_per_client_day: 5\n", "")
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("applies_per_client_day", str(ctx.exception))

    def test_malformed_cap_refuses(self):
        for bad in ["many", "-1", "0", "2.5", ""]:
            text = REG.replace("actions_per_changeset: 25", f"actions_per_changeset: {bad}")
            with self.assertRaises(ValueError):
                C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_missing_allow_refuses(self):
        text = REG.replace("        - mutate_campaign_negative\n", "")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_allow_header_refused(self):
        """A repeated allow: header must not accumulate — that would silently admit a
        second mutator into the list that decides what may touch a live account."""
        text = REG.replace("        - mutate_campaign_negative\n",
                           "        - mutate_campaign_negative\n      allow:\n        - apply_negatives\n")
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("duplicate", str(ctx.exception))

    def test_duplicate_caps_header_refused(self):
        text = REG.replace("      caps:\n", "      caps:\n        actions_per_changeset: 999\n      caps:\n")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_scalar_key_refused(self):
        """A repeated runner: would otherwise silently swap the interpreter."""
        text = REG.replace("      script_dir: code\n", "      script_dir: code\n      runner: /bin/sh\n")
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_duplicate_cap_key_refused(self):
        """The duplicate check must reach INSIDE caps:, not just the keys above it.

        This is the worst depth to allow a silent winner: applies_per_client_day is the
        load-bearing cap against a malfunction repeating, so a merge artifact raising it
        would leave every visible guard reading as correct while the limit was gone.
        """
        text = REG.replace("        applies_per_client_day: 5\n",
                           "        applies_per_client_day: 5\n        applies_per_client_day: 9999\n")
        self.assertIn("applies_per_client_day: 9999", text)     # the edit actually landed
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("duplicate", str(ctx.exception))

    def test_duplicate_allow_entry_refused(self):
        text = REG.replace("        - mutate_campaign_negative\n",
                           "        - mutate_campaign_negative\n        - mutate_campaign_negative\n")
        with self.assertRaises(ValueError) as ctx:
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")
        self.assertIn("duplicate", str(ctx.exception))

    def test_duplicate_workdir_refused(self):
        """workdir is half the path Hermes executes; a silent winner picks the tree."""
        text = REG.replace("    workdir: /projects/claude_google_ads\n",
                           "    workdir: /projects/claude_google_ads\n    workdir: /tmp/evil\n")
        self.assertIn("/tmp/evil", text)                        # the edit actually landed
        with self.assertRaises(ValueError) as ctx:
            C.read_workdir(_reg_file(text), "claude_google_ads")
        self.assertIn("duplicate", str(ctx.exception))

    def test_duplicate_block_refused(self):
        text = REG + """    mutate_execute:
      runner: /bin/sh
      script_dir: code
      allow:
        - evil
      caps:
        actions_per_changeset: 1
        actions_per_client_day: 1
        applies_per_client_day: 1
        approval_ttl_hours: 1
"""
        with self.assertRaises(ValueError):
            C.read_mutate_execute(_reg_file(text), "claude_google_ads")

    def test_read_workdir(self):
        self.assertEqual(C.read_workdir(self.p, "claude_google_ads"), "/projects/claude_google_ads")
        self.assertEqual(C.read_workdir(self.p, "claude_code"), "/projects/claude_code")

    def test_read_workdir_unknown_project_refused(self):
        with self.assertRaises(ValueError):
            C.read_workdir(self.p, "no_such_project")

    def test_read_allow_list_reads_each_block_separately(self):
        self.assertEqual(C.read_allow_list(self.p, "claude_google_ads", "read_execute"),
                         ["account_overview", "audit_analyze"])
        self.assertEqual(C.read_allow_list(self.p, "claude_google_ads", "mutate_execute"),
                         ["mutate_campaign_negative"])

    def test_read_allow_list_absent_block_is_empty(self):
        self.assertEqual(C.read_allow_list(self.p, "claude_code", "mutate_execute"), [])

    def test_walker_ignores_other_projects(self):
        """A block belonging to another project must never leak into this one."""
        self.assertEqual(C.read_allow_list(self.p, "claude_code", "read_execute"), [])

class TestDisjointness(unittest.TestCase):
    def test_disjoint_lists_pass(self):
        C.assert_allow_lists_disjoint(["account_overview"], ["mutate_campaign_negative"])

    def test_overlap_refused(self):
        with self.assertRaises(ValueError) as ctx:
            C.assert_allow_lists_disjoint(["account_overview", "shared"], ["shared"])
        self.assertIn("shared", str(ctx.exception))

    def test_real_registry_lists_are_disjoint(self):
        """The shipped registry must never list a script as both reader and mutator."""
        here = os.path.dirname(os.path.abspath(__file__))
        real = os.path.join(here, "..", "registry", "projects.yaml")
        mut = C.read_mutate_execute(real, "claude_google_ads")
        read_allow = C.read_allow_list(real, "claude_google_ads", "read_execute")
        self.assertTrue(read_allow, "read_execute allow-list should not be empty")
        C.assert_allow_lists_disjoint(read_allow, mut["allow"])

import datetime

NOW = datetime.datetime(2026, 8, 12, 10, 15, 0, tzinfo=datetime.timezone.utc)

class TestKillSwitchInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gov-")
        os.makedirs(os.path.join(self.root, "control"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _switch(self):
        return os.path.join(self.root, "control", "mutation-enabled")

    def test_absent_means_disabled(self):
        self.assertFalse(C.kill_switch_ok(self.root))

    def test_present_and_readable_means_enabled(self):
        open(self._switch(), "w").close()
        self.assertTrue(C.kill_switch_ok(self.root))

    def test_directory_in_its_place_means_disabled(self):
        os.makedirs(self._switch())
        self.assertFalse(C.kill_switch_ok(self.root))

    def test_unreadable_means_disabled(self):
        open(self._switch(), "w").close()
        os.chmod(self._switch(), 0o000)
        try:
            self.assertFalse(C.kill_switch_ok(self.root))
        finally:
            os.chmod(self._switch(), 0o600)

    def test_it_no_longer_reads_the_vault_location(self):
        """The control that proves the move actually happened: a switch at the OLD
        vault path must NOT enable mutation."""
        vault_root = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, vault_root, True)
        os.makedirs(os.path.join(vault_root, "_governance"))
        open(os.path.join(vault_root, "_governance", "mutation-enabled"), "w").close()
        self.assertFalse(C.kill_switch_ok(vault_root))

class TestApproval(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.slug = "acme-dental"
        self.srcdir = tempfile.mkdtemp()
        self.cs = os.path.join(self.srcdir, "20260812-101500-abcd1234.json")
        with open(self.cs, "wb") as f:
            f.write(C.canonical_bytes(_cs()))
        self.digest = C.file_digest(self.cs)

    def test_write_then_verify_roundtrip(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        rec = C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)
        self.assertEqual(rec["operator"], "erick")

    def test_missing_approval_refused(self):
        with self.assertRaises(ValueError):
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)

    def test_directory_in_place_of_approval_refused(self):
        os.makedirs(C.approval_path(self.slug, "20260812-101500-abcd1234"))
        with self.assertRaises(ValueError):
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)

    def test_unreadable_approval_refused(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        p = C.approval_path(self.slug, "20260812-101500-abcd1234")
        os.chmod(p, 0)
        try:
            with self.assertRaises(ValueError):
                C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)
        finally:
            os.chmod(p, 0o600)      # restore so tempdir cleanup succeeds

    def test_non_object_approval_refused(self):
        os.makedirs(G.approvals_dir(self.slug), exist_ok=True)
        with open(C.approval_path(self.slug, "20260812-101500-abcd1234"), "w") as f:
            f.write('["not", "an", "object"]')
        with self.assertRaises(ValueError):
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)

    def test_hash_mismatch_refused(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        with open(self.cs, "ab") as f:
            f.write(b" ")                     # a single whitespace byte
        new_digest = C.file_digest(self.cs)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.slug, "20260812-101500-abcd1234", new_digest, NOW)
        self.assertIn("modified after approval", str(ctx.exception))

    def test_expired_approval_refused(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=24, seconds=1)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, later)
        self.assertIn("expired", str(ctx.exception))

    def test_within_ttl_accepted(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=23, minutes=59)
        self.assertEqual(
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, later)["operator"],
            "erick")

    def test_bad_operator_rejected(self):
        for bad in ["", "a b", "rm -rf /", "x" * 65, "erick\n"]:
            with self.assertRaises(ValueError):
                C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, bad, NOW, 24)

    def test_non_string_approval_datetime_refused_cleanly(self):
        C.write_approval(self.slug, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        with open(C.approval_path(self.slug, "20260812-101500-abcd1234"), encoding="utf-8") as f:
            rec = json.load(f)
        rec["expires_at"] = 123
        with open(C.approval_path(self.slug, "20260812-101500-abcd1234"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.slug, "20260812-101500-abcd1234", self.digest, NOW)
        self.assertIn("expires_at must be a JSON string", str(ctx.exception))

class TestLog(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        self.slug = "acme-dental"

    def _line(self, **kw):
        rec = {"ts": "2026-08-12T10:15:00Z", "changeset_id": "20260812-101500-abcd1234",
               "action_index": 0, "type": "add_campaign_negative",
               "resource_name": "customers/1234567890/campaignCriteria/1~2",
               "status": "applied", "operator": "erick"}
        rec.update(kw)
        return rec

    def test_empty_log_counts_zero(self):
        self.assertEqual(C.day_counts(self.slug, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_counts_actions_and_distinct_applies(self):
        C.append_log(self.slug, self._line(action_index=0))
        C.append_log(self.slug, self._line(action_index=1))
        C.append_log(self.slug, self._line(changeset_id="20260812-120000-beef0001"))
        self.assertEqual(C.day_counts(self.slug, "2026-08-12"), {"applies": 2, "actions": 3})

    def test_other_days_not_counted(self):
        C.append_log(self.slug, self._line(ts="2026-08-11T23:59:59Z"))
        self.assertEqual(C.day_counts(self.slug, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_undone_lines_not_counted_as_applies(self):
        C.append_log(self.slug, self._line(status="undone"))
        self.assertEqual(C.day_counts(self.slug, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_corrupt_log_refuses_rather_than_undercounting(self):
        C.append_log(self.slug, self._line())
        with open(C.log_path(self.slug), "a") as f:
            f.write("{not json\n")
        with self.assertRaises(ValueError) as ctx:
            C.day_counts(self.slug, "2026-08-12")
        self.assertIn("corrupt", str(ctx.exception))

    def test_append_is_durable_and_one_line_per_record(self):
        C.append_log(self.slug, self._line())
        C.append_log(self.slug, self._line(action_index=1))
        with open(C.log_path(self.slug)) as f:
            self.assertEqual(len([x for x in f.read().splitlines() if x.strip()]), 2)


class TestApprovalSnapshot(unittest.TestCase):
    CID = "20260812-101500-abcd1234"

    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)
        # Irregular spacing + a trailing newline: NOT a fixed point of
        # json.dumps(json.loads(x)) under Python's default separators, so a
        # parse-and-reserialise implementation of write_snapshot (rather than a true
        # byte copy) would silently normalise this away and the test would go
        # undetected. A pretty-printed '{"actions": []}' input would survive such a
        # round trip unchanged and prove nothing.
        self.src = os.path.join(self.gov, "draft.json")
        self.ORIGINAL = '{"actions"  :  []}\n'
        with open(self.src, "w") as f:
            f.write(self.ORIGINAL)

    def test_snapshot_is_byte_identical(self):
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        with open(G.snapshot_path("acme-dental", self.CID)) as f:
            self.assertEqual(f.read(), self.ORIGINAL)
        self.assertEqual(digest, C.file_digest(self.src))

    def test_editing_the_source_afterwards_does_not_change_the_snapshot(self):
        """This is the race the snapshot exists to close."""
        C.write_snapshot("acme-dental", self.CID, self.src)
        with open(self.src, "w") as f:
            f.write('{"actions": [{"type": "add_campaign_negative"}]}')
        with open(G.snapshot_path("acme-dental", self.CID)) as f:
            self.assertEqual(f.read(), self.ORIGINAL)

    def test_verify_refuses_a_reserved_approval(self):
        now = datetime.datetime(2026, 8, 12, 10, 0, tzinfo=datetime.timezone.utc)
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        C.write_approval("acme-dental", self.CID, digest, "operator", now, 24)
        p = G.approval_path("acme-dental", self.CID)
        with open(p) as f:
            rec = json.load(f)
        rec["reserved_at"] = "2026-08-12T10:30:00Z"
        with open(p, "w") as f:
            json.dump(rec, f)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval("acme-dental", self.CID, digest, now)
        self.assertIn("reserved", str(ctx.exception))

    def test_verify_accepts_an_unreserved_approval(self):
        """The control: without this, the refusal above proves nothing."""
        now = datetime.datetime(2026, 8, 12, 10, 0, tzinfo=datetime.timezone.utc)
        digest = C.write_snapshot("acme-dental", self.CID, self.src)
        C.write_approval("acme-dental", self.CID, digest, "operator", now, 24)
        rec = C.verify_approval("acme-dental", self.CID, digest, now)
        self.assertEqual(rec["operator"], "operator")


class TestAuditLogInGovernanceStore(unittest.TestCase):
    def setUp(self):
        self.gov = tempfile.mkdtemp(prefix="gov-")
        self.addCleanup(shutil.rmtree, self.gov, True)
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.gov
        self.addCleanup(os.environ.pop, "HERMES_GOVERNANCE_ROOT", None)

    def _rec(self, **kw):
        r = {"changeset_id": "20260812-101500-abcd1234", "action_index": 0,
             "status": "applied", "operator": "operator",
             "resource_name": "customers/1234567890/campaignCriteria/111~222",
             # "ts" is the field day_counts/iter_log_records actually key off of
             # (see TestLog._line above); "applied_at" is kept alongside it only
             # because it happens to appear on real records too.
             "ts": "2026-08-12T10:15:00Z", "applied_at": "2026-08-12T10:15:00Z"}
        r.update(kw)
        return r

    def test_append_writes_under_the_governance_root(self):
        C.append_log("acme-dental", self._rec())
        self.assertTrue(os.path.isfile(
            os.path.join(self.gov, "log", "acme-dental.jsonl")))

    def test_one_line_per_record(self):
        C.append_log("acme-dental", self._rec())
        C.append_log("acme-dental", self._rec(action_index=1))
        with open(C.log_path("acme-dental")) as f:
            self.assertEqual(len([x for x in f.read().splitlines() if x.strip()]), 2)

    # DELETED (deferred #6, resolved 2026-08-20): test_clients_do_not_share_a_log
    # could not fail. It asserted that appending for one slug leaves the OTHER slug's
    # path absent — two different literal path fragments that never collide under
    # either the old vault-based signature or the new governance-store one, so it
    # passed identically against the code it was written to discriminate. Per ruling
    # R8, a control that cannot fail is deleted rather than shipped. Per-slug log
    # isolation is genuinely covered by governance_lib.test.py, which asserts
    # log_path() composes the slug into the filename.

    def test_day_counts_reads_the_new_location(self):
        C.append_log("acme-dental", self._rec())
        counts = C.day_counts("acme-dental", "2026-08-12")
        self.assertEqual(counts["actions"], 1)

    def test_a_vault_path_argument_is_rejected_not_silently_misread(self):
        """Control, rewritten from the brief (see task-5-report.md, R8): the
        brief's original version called C.day_counts("acme-dental", ...) — a bare
        SLUG — while writing its decoy record under an unrelated tempdir. That
        decoy is never on the path either signature actually reads for a bare
        slug, so the assertion (0 actions) held under BOTH the old and the new
        implementation and proved nothing.

        Before this task, day_counts's first argument was the resolved vault path
        (<VAULT_ROOT>/<slug> — see vault_lib.resolve: rec["vault_path"] =
        os.path.join(vault_root(), slug)), never a bare slug; every real
        pre-migration caller passed that path. This version writes a real record
        at exactly that OLD location and calls day_counts with that same path —
        the actual old calling convention — and asserts it is now REFUSED outright
        rather than silently read (which would either double-count real
        pre-migration data or return a zero indistinguishable from 'nothing to
        migrate'). Task 6 migrates any such stray data deliberately."""
        vault = tempfile.mkdtemp(prefix="vault-")
        self.addCleanup(shutil.rmtree, vault, True)
        os.makedirs(os.path.join(vault, "changes"))
        with open(os.path.join(vault, "changes", "log.jsonl"), "w") as f:
            f.write(json.dumps(self._rec()) + "\n")
        with self.assertRaises(ValueError):
            C.day_counts(vault, "2026-08-12")


class TestSpoolQuotas(unittest.TestCase):
    HEAD = ("version: 1\n"
            "projects:\n"
            "  proj:\n"
            "    workdir: /projects/proj\n"
            "    mutate_execute:\n"
            "      runner: /opt/ads-venv/bin/python3\n"
            "      script_dir: code\n"
            "      allow:\n"
            "        - mutate_campaign_negative\n"
            "      caps:\n")

    def _reg(self, caps_lines):
        fd, p = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(self.HEAD + caps_lines)
        self.addCleanup(os.unlink, p)
        return p

    FULL = ("        actions_per_changeset: 25\n"
            "        actions_per_client_day: 100\n"
            "        applies_per_client_day: 5\n"
            "        approval_ttl_hours: 24\n"
            "        max_pending_requests: 8\n"
            "        accepted_requests_per_client_day: 20\n")

    def test_reads_both_quotas(self):
        q = C.read_spool_quotas(self._reg(self.FULL), "proj")
        self.assertEqual(q["max_pending_requests"], 8)
        self.assertEqual(q["accepted_requests_per_client_day"], 20)

    def test_missing_quota_refuses_rather_than_becoming_unlimited(self):
        for drop in ("max_pending_requests", "accepted_requests_per_client_day"):
            partial = "".join(l for l in self.FULL.splitlines(True)
                              if not l.strip().startswith(drop + ":"))
            with self.assertRaises(ValueError) as cm:
                C.read_spool_quotas(self._reg(partial), "proj")
            self.assertIn(drop, str(cm.exception))

    def test_malformed_quota_refuses(self):
        for bad in ("0", "-1", "abc", "", "1e6", "999999999"):
            broken = self.FULL.replace("max_pending_requests: 8",
                                       "max_pending_requests: %s" % bad)
            with self.assertRaises(ValueError):
                C.read_spool_quotas(self._reg(broken), "proj")

    def test_control_the_existing_caps_still_parse_unchanged(self):
        # THE POSITIVE CONTROL for this task: adding two keys to the caps block must
        # not disturb the executor's own cap reader. If this breaks, the quotas were
        # added in the wrong place.
        m = C.read_mutate_execute(self._reg(self.FULL), "proj")
        self.assertEqual(m["caps"]["applies_per_client_day"], 5)
        self.assertEqual(m["caps"]["approval_ttl_hours"], 24)
        self.assertNotIn("max_pending_requests", m["caps"])

    def test_duplicate_quota_key_still_refuses(self):
        dup = self.FULL + "        max_pending_requests: 9999\n"
        with self.assertRaises(ValueError):
            C.read_spool_quotas(self._reg(dup), "proj")


class TestSeenSet(unittest.TestCase):
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_unseen_then_seen(self):
        self.assertFalse(C.seen_contains("pilot-1", self.RID))
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertTrue(C.seen_contains("pilot-1", self.RID))

    def test_the_seen_set_is_written_into_the_governance_store(self):
        # The WHOLE POINT. If this lands in the spool, Hermes can delete it and every
        # request_id becomes replayable.
        C.append_seen("pilot-1", self.RID, NOW)
        expected = G.seen_path("pilot-1", self.root)
        self.assertTrue(os.path.isfile(expected))
        self.assertNotIn("spool", expected)

    def test_seen_is_per_client_not_global(self):
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertFalse(C.seen_contains("pilot-2", self.RID))

    def test_unreadable_seen_set_refuses_rather_than_reporting_unseen(self):
        # Fail-closed. An unreadable seen-set reported as "not seen" would ADMIT every
        # replay — the same shape as the caps rule: an unreadable limit must never
        # become an unlimited one.
        p = G.seen_path("pilot-1", self.root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.mkdir(p)                      # a directory where the file should be
        with self.assertRaises(ValueError):
            C.seen_contains("pilot-1", self.RID)

    def test_control_a_readable_seen_set_does_not_raise(self):
        # The positive control for the refusal above.
        C.append_seen("pilot-1", self.RID, NOW)
        self.assertTrue(C.seen_contains("pilot-1", self.RID))


class TestReservation(unittest.TestCase):
    CID = "20260824-101500-abcdef01"
    RID = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"
    DIGEST = "a" * 64

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        C.write_approval("pilot-1", self.CID, self.DIGEST, "operator", NOW, 24)

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_reserving_records_the_timestamp_and_the_request(self):
        rec = C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        self.assertEqual(rec["request_id"], self.RID)
        self.assertEqual(rec["reserved_at"], NOW.strftime(C.ISO))

    def test_a_reserved_approval_no_longer_verifies(self):
        # This is the single-use property, asserted through the EXECUTOR's own guard
        # rather than by re-reading the file — verify_approval is what actually stops
        # the second apply, so that is what must be shown to refuse.
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError) as cm:
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)
        self.assertIn("already reserved", str(cm.exception))

    def test_control_an_unreserved_approval_verifies(self):
        # The positive control: without it, the refusal above could be caused by
        # anything at all.
        self.assertEqual(
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)["sha256"],
            self.DIGEST)

    def test_double_reservation_refuses(self):
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError):
            C.reserve_approval("pilot-1", self.CID, "1111aaaa-2222-4bbb-8ccc-3333dddd4444", NOW)

    def test_reserving_a_nonexistent_approval_refuses(self):
        with self.assertRaises(ValueError):
            C.reserve_approval("pilot-1", "20260824-101500-99999999", self.RID, NOW)

    def test_outcome_requires_a_prior_reservation(self):
        # An outcome without a reservation means the ordering was inverted somewhere.
        with self.assertRaises(ValueError):
            C.record_outcome("pilot-1", self.CID, "applied", NOW)

    def test_outcome_is_recorded_after_reservation(self):
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        rec = C.record_outcome("pilot-1", self.CID, "applied", NOW)
        self.assertEqual(rec["outcome"], "applied")
        self.assertEqual(rec["request_id"], self.RID)

    def test_an_interrupted_apply_is_not_a_reusable_approval(self):
        # Reserved but no outcome ever written — the crash case. The approval must
        # still be dead. This is the ordering property from spec §7 stated as a test:
        # a crash costs an unusable approval, never a duplicate account change.
        C.reserve_approval("pilot-1", self.CID, self.RID, NOW)
        with self.assertRaises(ValueError):
            C.verify_approval("pilot-1", self.CID, self.DIGEST, NOW)


import threading, time, unittest.mock

class TestReservationConcurrency(unittest.TestCase):
    """FIX ROUND 1: reserve_approval's read-check-write must be mutually exclusive
    against ITSELF, not just against verify_approval. This proves it, by forcing two
    concurrent attempts on the SAME approval to actually overlap."""
    CID = "20260824-101500-abcdef01"
    RID_A = "0f9c1a2b-3d4e-4f50-8a1b-2c3d4e5f6071"
    RID_B = "1111aaaa-2222-4bbb-8ccc-3333dddd4444"
    DIGEST = "a" * 64

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        C.write_approval("pilot-1", self.CID, self.DIGEST, "operator", NOW, 24)

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_concurrent_reservations_are_mutually_exclusive(self):
        # Widen the window between the read-check and the write completing, by
        # slowing down the (real) write call. This does not change what
        # reserve_approval does — only how long its write takes — but it makes the
        # race deterministic to observe either way: WITH the lock, the second thread
        # cannot even begin its read until the first's entire locked section
        # (including this slow write) has finished, so it always sees the
        # already-reserved record and refuses. WITHOUT the lock (see the mutation
        # proof in task-4-report.md), both threads pass the read-check before either
        # writes, and both "succeed" — which this test must catch.
        real_write = C._atomic_write_json
        calls = []

        def slow_write(path, obj):
            calls.append(path)
            time.sleep(0.05)
            return real_write(path, obj)

        started = []
        results = {}

        def attempt(name, rid):
            started.append(name)          # positive control: proves this thread ran
            try:
                results[name] = C.reserve_approval("pilot-1", self.CID, rid, NOW)
            except ValueError as e:
                results[name] = e

        with unittest.mock.patch.object(C, "_atomic_write_json", slow_write):
            t1 = threading.Thread(target=attempt, args=("a", self.RID_A))
            t2 = threading.Thread(target=attempt, args=("b", self.RID_B))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        # Positive control: both threads must have actually run and recorded a
        # result, or the assertions below would pass vacuously (e.g. if the second
        # thread never got scheduled at all).
        self.assertEqual(sorted(started), ["a", "b"])
        self.assertEqual(len(results), 2, results)

        successes = [v for v in results.values() if isinstance(v, dict)]
        failures = [v for v in results.values() if isinstance(v, ValueError)]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertIn("already reserved", str(failures[0]))


class TestWriteApprovalConcurrency(unittest.TestCase):
    """FIX ROUND 2: write_approval shares the exact _atomic_write_json shared-tmp-path
    hazard that TestReservationConcurrency's mutation proof demonstrated against
    reserve_approval — proven, not merely suspected, which is why it gets fixed here
    rather than ticketed. Two concurrent write_approval calls for the SAME (slug, cid)
    must neither corrupt the file nor raise from the race on the shared .tmp path."""
    CID = "20260824-101500-abcdef01"
    DIGEST = "a" * 64

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_concurrent_writes_do_not_corrupt_or_crash(self):
        # Same widening technique as TestReservationConcurrency: slow the real write
        # down so any missing serialization is forced to manifest as real overlap,
        # rather than relying on thread-scheduling luck.
        real_write = C._atomic_write_json

        def slow_write(path, obj):
            time.sleep(0.05)
            return real_write(path, obj)

        started = []
        results = {}

        def attempt(name, operator):
            started.append(name)          # positive control: proves this thread ran
            try:
                results[name] = C.write_approval(
                    "pilot-1", self.CID, self.DIGEST, operator, NOW, 24)
            except Exception as e:
                results[name] = e

        with unittest.mock.patch.object(C, "_atomic_write_json", slow_write):
            t1 = threading.Thread(target=attempt, args=("a", "operator-a"))
            t2 = threading.Thread(target=attempt, args=("b", "operator-b"))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        # Positive control: both threads must have actually run and recorded a
        # result, or the assertions below would pass vacuously.
        self.assertEqual(sorted(started), ["a", "b"])
        self.assertEqual(len(results), 2, results)

        # Neither call may raise. Catching only the swallowed-exception shape (a
        # missing result) is not enough here — write_approval never refuses a second
        # write, so an unlocked race manifests as a raised exception, not as two
        # results where one should have been a refusal.
        for name, r in results.items():
            self.assertNotIsInstance(r, Exception, f"{name} raised: {r!r}")

        # The file left on disk must be valid, complete JSON belonging to one of the
        # two attempts -- not truncated or interleaved.
        with open(G.approval_path("pilot-1", self.CID), encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertIn(on_disk["operator"], ("operator-a", "operator-b"))


class TestFreshApprovalsDirectory(unittest.TestCase):
    """FIX ROUND 2: covers the brand-new-client case, where the approvals directory
    _approval_lock's sidecar file lives inside does not exist yet. Every other
    TestApproval-family fixture in this file has already caused that directory to
    exist by the time write_approval runs (via an earlier write_approval or
    write_snapshot call in the same test), so nothing before this round actually
    exercised the very first approval ever written for a client.

    NOTE, corrected after mutation testing: this does NOT prove write_approval's
    makedirs-then-lock ordering is load-bearing. _approval_lock defensively creates
    its own sidecar's parent directory before opening it, so this test passes
    regardless of whether write_approval's own makedirs runs before or after the
    lock is taken (verified: moving the lock above the makedirs did not turn this
    test red — see task-4-report.md FIX ROUND 2). What this test actually proves is
    the narrower, still-true thing: a brand-new client's first approval succeeds and
    is readable back."""
    CID = "20260824-101500-abcdef01"
    DIGEST = "a" * 64

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.get("HERMES_GOVERNANCE_ROOT")
        os.environ["HERMES_GOVERNANCE_ROOT"] = self.root
        # Deliberately nothing else here -- the absence of the approvals directory
        # for this brand-new client IS the case under test.

    def tearDown(self):
        os.environ.pop("HERMES_GOVERNANCE_ROOT", None)
        if self._saved is not None:
            os.environ["HERMES_GOVERNANCE_ROOT"] = self._saved

    def test_first_ever_approval_for_a_client_succeeds(self):
        self.assertFalse(os.path.isdir(G.approvals_dir("brand-new-client")))
        rec = C.write_approval("brand-new-client", self.CID, self.DIGEST, "operator", NOW, 24)
        self.assertEqual(rec["operator"], "operator")
        # Positive control: the record actually landed on disk and is independently
        # readable back through verify_approval, not just that write_approval
        # returned without raising.
        readback = C.verify_approval("brand-new-client", self.CID, self.DIGEST, NOW)
        self.assertEqual(readback["operator"], "operator")


if __name__ == "__main__":
    unittest.main()
