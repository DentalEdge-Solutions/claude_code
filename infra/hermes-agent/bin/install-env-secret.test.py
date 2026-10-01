#!/usr/bin/env python3
import contextlib, importlib.util, io, os, stat, tempfile, unittest, warnings
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ies", os.path.join(HERE, "install-env-secret.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, ".env")

    def run_(self, argv, value=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S.main(argv, read_value=lambda: value)
        return rc, out.getvalue()

    def test_set_creates_with_mode_and_never_prints_value(self):
        rc, text = self.run_(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                              "--prefix", "sk-ant-", "--mode", "0400"], "sk-ant-SECRET")
        self.assertEqual(rc, 0, text)
        self.assertEqual(open(self.f).read(), "ANTHROPIC_API_KEY=sk-ant-SECRET\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.f).st_mode), 0o400)
        self.assertNotIn("SECRET", text)

    def test_set_replaces_only_its_line(self):
        open(self.f, "w").write("A=1\nOPENROUTER_API_KEY=sk-or-old\n# c\n")
        rc, _ = self.run_(["set", "--file", self.f, "--name", "OPENROUTER_API_KEY",
                           "--prefix", "sk-or-", "--mode", "0600"], "sk-or-new")
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f).read(), "A=1\nOPENROUTER_API_KEY=sk-or-new\n# c\n")

    def test_bad_prefix_empty_or_multiline_refused_and_file_untouched(self):
        open(self.f, "w").write("A=1\n")
        for v in ("nope", "", "sk-ant-a\nB=2", None):
            rc, _ = self.run_(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                               "--prefix", "sk-ant-", "--mode", "0400"], v)
            self.assertEqual(rc, 2)
            self.assertEqual(open(self.f).read(), "A=1\n")

    def test_strip_removes_every_assignment_of_the_name(self):
        open(self.f, "w").write("ANTHROPIC_API_KEY=sk-ant-x\nA=1\nexport ANTHROPIC_API_KEY=y\n")
        os.chmod(self.f, 0o600)
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "ANTHROPIC_API_KEY"])
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.f).st_mode), 0o600)   # mode preserved

    def test_symlink_refused(self):
        real = os.path.join(self.d, "real"); open(real, "w").write("A=1\n"); os.symlink(real, self.f)
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "A"])
        self.assertEqual(rc, 2)
        self.assertEqual(open(real).read(), "A=1\n")

    def test_bad_name_refused(self):
        rc, _ = self.run_(["strip", "--file", self.f, "--name", "a b"])
        self.assertEqual(rc, 2)

    def test_stale_temp_file_is_a_clean_refusal_and_nothing_replaced(self):
        open(self.f, "w").write("A=1\n")
        stale = os.path.join(self.d, ".%s.%d.tmp" % (".env", os.getpid()))
        open(stale, "w").write("stale")
        rc, text = self.run_(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                              "--prefix", "sk-ant-", "--mode", "0400"], "sk-ant-SECRET")
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("SECRET", text)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self.assertEqual(open(stale).read(), "stale")   # the other run's temp is not touched

    def _set(self, value, name="ANTHROPIC_API_KEY", prefix="sk-ant-"):
        return self.run_(["set", "--file", self.f, "--name", name, "--prefix", prefix,
                          "--mode", "0400"], value)

    def _no_temps(self):
        self.assertEqual([n for n in os.listdir(self.d) if n.endswith(".tmp")], [])

    def test_rename_failure_removes_temp_and_keeps_original(self):
        open(self.f, "w").write("A=1\n")
        with mock.patch.object(S.os, "rename", side_effect=OSError("boom")):
            rc, text = self._set("sk-ant-SECRET")
        self.assertEqual(rc, 2); self.assertNotIn("SECRET", text)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self._no_temps()

    def test_no_progress_write_refused_and_cleaned_up(self):
        open(self.f, "w").write("A=1\n")
        with mock.patch.object(S.os, "write", return_value=0):
            rc, _ = self._set("sk-ant-SECRET")
        self.assertEqual(rc, 2)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self._no_temps()

    def test_short_write_is_completed_never_truncated(self):
        real = os.write; calls = []
        def short(fd, data):
            calls.append(len(data))
            return real(fd, bytes(data)[:3]) if len(calls) == 1 else real(fd, data)
        with mock.patch.object(S.os, "write", side_effect=short):
            rc, text = self._set("sk-ant-SECRET")
        self.assertEqual(rc, 0, text); self.assertGreater(len(calls), 1)
        self.assertEqual(open(self.f).read(), "ANTHROPIC_API_KEY=sk-ant-SECRET\n")

    def test_getpass_stdin_fallback_is_refused(self):
        def fallback(prompt=""):
            warnings.warn("no tty", S.getpass.GetPassWarning)
            return "sk-ant-FROMSTDIN"
        with mock.patch.object(S.getpass, "getpass", side_effect=fallback):
            self.assertIsNone(S._tty_value())
            open(self.f, "w").write("A=1\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = S.main(["set", "--file", self.f, "--name", "ANTHROPIC_API_KEY",
                             "--prefix", "sk-ant-", "--mode", "0400"])
        self.assertEqual(rc, 2); self.assertEqual(open(self.f).read(), "A=1\n")

    def test_empty_prefix_refused(self):
        rc, _ = self._set("anything", prefix="")
        self.assertEqual(rc, 2); self.assertFalse(os.path.exists(self.f))

    def test_other_lines_preserved_byte_for_byte_crlf_and_formfeed(self):
        raw = b"A=1\r\n\x0cANTHROPIC_API_KEY=keepme\nB=2\x0c\r\nANTHROPIC_API_KEY=old\r\nlast"
        open(self.f, "wb").write(raw)
        rc, _ = self._set("sk-ant-new")
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f, "rb").read(),
                         b"A=1\r\n\x0cANTHROPIC_API_KEY=keepme\nB=2\x0c\r\nANTHROPIC_API_KEY=sk-ant-new\nlast")

    def test_lone_surrogate_value_refused_without_leaking(self):
        open(self.f, "w").write("A=1\n")
        rc, text = self._set("sk-ant-\udc80X")
        self.assertEqual(rc, 2)
        self.assertNotIn("udc80", text.lower()); self.assertNotIn("\udc80", text)
        self.assertEqual(open(self.f).read(), "A=1\n")
        self._no_temps()


if __name__ == "__main__":
    unittest.main()
