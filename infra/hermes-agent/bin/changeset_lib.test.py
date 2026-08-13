import json, os, sys, unittest
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

if __name__ == "__main__":
    unittest.main()
