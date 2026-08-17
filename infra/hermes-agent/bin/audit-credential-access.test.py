"""Unit tests for the pure classification logic in audit-credential-access.py.

Only the decision logic is covered — the probes themselves need a live account and
belong to operator-run verification, not a test suite. The logic here is worth
testing precisely because two bugs in it each produced a WRONG access-level
verdict during development:

  1. reading customer_user_access was treated as proof of ADMIN, so a credential
     whose mutate was refused in the same run was still reported ADMIN;
  2. OPERATION_NOT_PERMITTED_FOR_CONTEXT (wrong campaign type) was treated as an
     authorization refusal, which would report a mutate-capable credential as
     read-only.

Both are silent failures — a confident wrong answer, which is worse here than an
error, because the whole point of the tool is to replace assertions with evidence.

Stdlib-only. The module under test guards its SDK import so it stays importable
on the host, where google-ads is not installed.
"""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "audit-credential-access.py")

spec = importlib.util.spec_from_file_location("audit_credential_access", MODULE)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


class TestImportGuard(unittest.TestCase):
    def test_module_imports_without_the_sdk(self):
        # If this fails the suite cannot run host-side at all.
        self.assertTrue(hasattr(A, "classify_mutate_error"))


class TestMutateErrorClassification(unittest.TestCase):
    def test_authorization_refusal_is_denied(self):
        for code in A.AUTH_DENIED:
            with self.subTest(code=code):
                self.assertIs(A.classify_mutate_error(f"{code}: some message"), False)

    def test_context_error_is_inconclusive_not_denied(self):
        # The regression that mattered: this is a wrong-campaign-type refusal and
        # says nothing about access level.
        sig = "context_error: OPERATION_NOT_PERMITTED_FOR_CONTEXT: The operation is not allowed"
        self.assertIsNone(A.classify_mutate_error(sig))

    def test_unrelated_errors_are_inconclusive(self):
        for sig in ("internal_error: INTERNAL_ERROR",
                    "quota_error: RESOURCE_EXHAUSTED",
                    "request_error: INVALID_CUSTOMER_ID",
                    ""):
            with self.subTest(sig=sig):
                self.assertIsNone(A.classify_mutate_error(sig))

    def test_denied_codes_are_not_substrings_of_benign_ones(self):
        # Guards against a future edit turning the membership test into something
        # that matches too eagerly.
        self.assertIsNone(A.classify_mutate_error("SOMETHING_ELSE_ENTIRELY"))


class TestVerdict(unittest.TestCase):
    OK = {"ok": True}
    BAD = {"ok": False}

    def test_unreadable_is_unusable(self):
        self.assertEqual(A.verdict(self.BAD, {"permitted": True}), "UNUSABLE")

    def test_read_plus_denied_mutate_is_read_only(self):
        self.assertEqual(A.verdict(self.OK, {"permitted": False}), "READ_ONLY")

    def test_read_plus_permitted_mutate_is_mutate_capable(self):
        self.assertEqual(A.verdict(self.OK, {"permitted": True}), "MUTATE_CAPABLE")

    def test_unknown_mutate_is_inconclusive_never_read_only(self):
        # The dangerous rounding: "we could not tell" must never become
        # "it is safely read-only".
        self.assertEqual(A.verdict(self.OK, {"permitted": None}), "INCONCLUSIVE")


class TestAccessRoleMap(unittest.TestCase):
    def test_roles_match_the_sdk_enum_values(self):
        # Verified against SDK v24: 2=ADMIN, 3=STANDARD, 4=READ_ONLY.
        self.assertEqual(A.ACCESS_ROLE[2], "ADMIN")
        self.assertEqual(A.ACCESS_ROLE[3], "STANDARD")
        self.assertEqual(A.ACCESS_ROLE[4], "READ_ONLY")

    def test_read_only_and_admin_are_not_confused(self):
        self.assertNotEqual(A.ACCESS_ROLE[2], A.ACCESS_ROLE[4])


class TestDigits(unittest.TestCase):
    def test_strips_dashes_and_spaces(self):
        self.assertEqual(A.digits("123-456-7890", "x"), "1234567890")
        self.assertEqual(A.digits("123 456 7890", "x"), "1234567890")

    def test_rejects_non_digits(self):
        for bad in ("", "abc", "12a34", "-", "1" * 16):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    A.digits(bad, "x")


class TestFingerprintConvention(unittest.TestCase):
    def test_matches_the_bare_shasum_convention(self):
        # Must equal: printf '%s' "$v" | shasum | cut -c1-12
        self.assertEqual(A.sha12("NEWREFRESH"), "797e38433d69")


if __name__ == "__main__":
    unittest.main(verbosity=2)
