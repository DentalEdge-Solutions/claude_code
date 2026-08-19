import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C

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
        self.assertFalse(C.kill_switch_ok(self.root))

class TestApproval(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        os.makedirs(C.changes_dir(self.vault))
        self.cs = os.path.join(C.changes_dir(self.vault), "20260812-101500-abcd1234.json")
        with open(self.cs, "wb") as f:
            f.write(C.canonical_bytes(_cs()))
        self.digest = C.file_digest(self.cs)

    def test_write_then_verify_roundtrip(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        rec = C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)
        self.assertEqual(rec["operator"], "erick")

    def test_missing_approval_refused(self):
        with self.assertRaises(ValueError):
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)

    def test_directory_in_place_of_approval_refused(self):
        os.makedirs(C.approval_path(self.vault, "20260812-101500-abcd1234"))
        with self.assertRaises(ValueError):
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)

    def test_unreadable_approval_refused(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        p = C.approval_path(self.vault, "20260812-101500-abcd1234")
        os.chmod(p, 0)
        try:
            with self.assertRaises(ValueError):
                C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)
        finally:
            os.chmod(p, 0o600)      # restore so tempdir cleanup succeeds

    def test_non_object_approval_refused(self):
        with open(C.approval_path(self.vault, "20260812-101500-abcd1234"), "w") as f:
            f.write('["not", "an", "object"]')
        with self.assertRaises(ValueError):
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)

    def test_hash_mismatch_refused(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        with open(self.cs, "ab") as f:
            f.write(b" ")                     # a single whitespace byte
        new_digest = C.file_digest(self.cs)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.vault, "20260812-101500-abcd1234", new_digest, NOW)
        self.assertIn("modified after approval", str(ctx.exception))

    def test_expired_approval_refused(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=24, seconds=1)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, later)
        self.assertIn("expired", str(ctx.exception))

    def test_within_ttl_accepted(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        later = NOW + datetime.timedelta(hours=23, minutes=59)
        self.assertEqual(
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, later)["operator"],
            "erick")

    def test_bad_operator_rejected(self):
        for bad in ["", "a b", "rm -rf /", "x" * 65, "erick\n"]:
            with self.assertRaises(ValueError):
                C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, bad, NOW, 24)

    def test_non_string_approval_datetime_refused_cleanly(self):
        C.write_approval(self.vault, "20260812-101500-abcd1234", self.digest, "erick", NOW, 24)
        with open(C.approval_path(self.vault, "20260812-101500-abcd1234"), encoding="utf-8") as f:
            rec = json.load(f)
        rec["expires_at"] = 123
        with open(C.approval_path(self.vault, "20260812-101500-abcd1234"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        with self.assertRaises(ValueError) as ctx:
            C.verify_approval(self.vault, "20260812-101500-abcd1234", self.digest, NOW)
        self.assertIn("expires_at must be a JSON string", str(ctx.exception))

class TestLog(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()

    def _line(self, **kw):
        rec = {"ts": "2026-08-12T10:15:00Z", "changeset_id": "20260812-101500-abcd1234",
               "action_index": 0, "type": "add_campaign_negative",
               "resource_name": "customers/1234567890/campaignCriteria/1~2",
               "status": "applied", "operator": "erick"}
        rec.update(kw)
        return rec

    def test_empty_log_counts_zero(self):
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_counts_actions_and_distinct_applies(self):
        C.append_log(self.vault, self._line(action_index=0))
        C.append_log(self.vault, self._line(action_index=1))
        C.append_log(self.vault, self._line(changeset_id="20260812-120000-beef0001"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 2, "actions": 3})

    def test_other_days_not_counted(self):
        C.append_log(self.vault, self._line(ts="2026-08-11T23:59:59Z"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_undone_lines_not_counted_as_applies(self):
        C.append_log(self.vault, self._line(status="undone"))
        self.assertEqual(C.day_counts(self.vault, "2026-08-12"), {"applies": 0, "actions": 0})

    def test_corrupt_log_refuses_rather_than_undercounting(self):
        C.append_log(self.vault, self._line())
        with open(C.log_path(self.vault), "a") as f:
            f.write("{not json\n")
        with self.assertRaises(ValueError) as ctx:
            C.day_counts(self.vault, "2026-08-12")
        self.assertIn("corrupt", str(ctx.exception))

    def test_append_is_durable_and_one_line_per_record(self):
        C.append_log(self.vault, self._line())
        C.append_log(self.vault, self._line(action_index=1))
        with open(C.log_path(self.vault)) as f:
            self.assertEqual(len([x for x in f.read().splitlines() if x.strip()]), 2)

if __name__ == "__main__":
    unittest.main()
