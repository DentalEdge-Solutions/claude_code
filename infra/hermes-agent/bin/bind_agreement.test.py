"""Unit tests for bind_agreement.py, on FIXTURE text (not the real files — Task 2's
agreement test in proxy-policy-sync.test.py reads those)."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bind_agreement as BA

COMPOSE = """services:
  gateway:
    volumes:
      - ./data:/opt/data
  ads-mutator:
    image: hermes-agent-claude
    volumes:
      - ${GOV:?GOV must be set, see README}/approvals:/opt/governance/approvals:ro
      # a comment line inside the list
      - ${GOV:?GOV must be set, see README}/log:/opt/governance/log
      - ${AGENT:?AGENT must be set}/bin:/opt/cc-bin:ro  # trailing comment
  other:
    volumes:
      - ./x:/y
"""

UNIT = """[Service]
User=example
Environment=A=/one
Environment=B=/two/three
# Environment=C=/commented
ExecStart=/opt/x/bin/tool.py \\
    --listen /run/x.sock \\
    --allow-bind /a:/b:ro \\
    --allow-bind /c:/d:rw
Restart=on-failure
"""

INTERPRETER_UNIT = """[Service]
ExecStart=/usr/bin/python3 /opt/hermes-agent/bin/hermes-broker.py --watch --interval 5
"""


class TestInterpolate(unittest.TestCase):
    def test_a_guarded_set_variable_is_substituted(self):
        self.assertEqual(BA.interpolate("${A:?msg}/x", {"A": "/one"}), "/one/x")

    def test_a_guarded_unset_variable_raises_with_its_message(self):
        with self.assertRaises(BA.Unresolved) as cm:
            BA.interpolate("${A:?A must be set}/x", {})
        self.assertIn("A must be set", str(cm.exception))

    def test_a_guarded_empty_variable_raises(self):
        with self.assertRaises(BA.Unresolved):
            BA.interpolate("${A:?m}", {"A": ""})

    def test_an_unguarded_unset_variable_is_empty_like_compose(self):
        self.assertEqual(BA.interpolate("${A}/x", {}), "/x")


class TestSplitVolume(unittest.TestCase):
    def test_a_guard_message_with_colon_space_and_comma_stays_in_the_source(self):
        self.assertEqual(
            BA.split_volume("${G:?G must be set, see README}/log:/opt/governance/log"),
            ("${G:?G must be set, see README}/log", "/opt/governance/log", None))

    def test_the_mode_is_the_third_part(self):
        self.assertEqual(BA.split_volume("/a:/b:ro"), ("/a", "/b", "ro"))

    def test_a_long_form_or_garbage_entry_is_refused(self):
        with self.assertRaises(ValueError):
            BA.split_volume("/a")


class TestServiceVolumes(unittest.TestCase):
    def test_only_the_named_service_comments_stripped(self):
        self.assertEqual(BA.service_volumes(COMPOSE, "ads-mutator"), [
            "${GOV:?GOV must be set, see README}/approvals:/opt/governance/approvals:ro",
            "${GOV:?GOV must be set, see README}/log:/opt/governance/log",
            "${AGENT:?AGENT must be set}/bin:/opt/cc-bin:ro",
        ])

    def test_an_unknown_service_raises(self):
        with self.assertRaises(ValueError):
            BA.service_volumes(COMPOSE, "nope")


class TestComposeBinds(unittest.TestCase):
    ENV = {"GOV": "/var/lib/g", "AGENT": "/opt/agent"}

    def test_absolute_sources_verbatim_and_a_bare_entry_gains_rw(self):
        """M2 (verbatim) and M3 (bare -> :rw), spec §2."""
        self.assertEqual(BA.compose_binds(COMPOSE, self.ENV), [
            "/var/lib/g/approvals:/opt/governance/approvals:ro",
            "/var/lib/g/log:/opt/governance/log:rw",
            "/opt/agent/bin:/opt/cc-bin:ro",
        ])

    def test_firing_control_a_relative_source_is_refused(self):
        """M1/M6: a relative source's string depends on how Compose was invoked."""
        with self.assertRaises(ValueError) as cm:
            BA.compose_binds(COMPOSE, self.ENV, service="other")
        self.assertIn("relative", str(cm.exception))

    def test_firing_control_an_unset_guarded_variable_is_refused(self):
        with self.assertRaises(BA.Unresolved):
            BA.compose_binds(COMPOSE, {"GOV": "/var/lib/g"})


class TestUnits(unittest.TestCase):
    def test_exec_args_exclude_the_program_and_join_continuations(self):
        self.assertEqual(BA.unit_exec_args(UNIT), [
            "--listen", "/run/x.sock", "--allow-bind", "/a:/b:ro", "--allow-bind", "/c:/d:rw"])

    def test_allow_binds(self):
        self.assertEqual(BA.allow_binds(UNIT), ["/a:/b:ro", "/c:/d:rw"])

    def test_environment_ignores_commented_lines(self):
        self.assertEqual(BA.unit_environment(UNIT), {"A": "/one", "B": "/two/three"})

    def test_a_unit_without_exec_start_raises(self):
        with self.assertRaises(ValueError):
            BA.unit_exec_args("[Service]\nUser=x\n")

    def test_an_interpreter_exec_start_keeps_the_script_path_in_the_args(self):
        """Documented contract: only the FIRST token is dropped. allow_binds is unaffected
        because it selects by flag name."""
        self.assertEqual(BA.unit_exec_args(INTERPRETER_UNIT),
                         ["/opt/hermes-agent/bin/hermes-broker.py", "--watch", "--interval", "5"])
        self.assertEqual(BA.allow_binds(INTERPRETER_UNIT), [])


if __name__ == "__main__":
    unittest.main()
