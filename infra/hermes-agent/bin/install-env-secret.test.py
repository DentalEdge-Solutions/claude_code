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


class TestQuoteAndGenerate(unittest.TestCase):
    """F52: Compose interpolates `$` in an env_file, so a dashboard password hash written bare is
    cut short in the container. And `generate`: a secret nobody types."""
    HASH = "scrypt$16384$8$1$bm90LWEtcmVhbC1zYWx0IQ==$bm90LWEtcmVhbC1zY3J5cHQtaGFzaC0wMTIzNDU2Nzg="
    NAME = "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"
    SECRET = "HERMES_DASHBOARD_BASIC_AUTH_SECRET"

    def setUp(self):
        self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, ".env")

    def run_(self, argv, value=None, random_bytes=None):
        out = io.StringIO()
        kw = {"random_bytes": random_bytes} if random_bytes else {}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S.main(argv, read_value=lambda: value, **kw)
        return rc, out.getvalue()

    def set_(self, value, *extra):
        return self.run_(["set", "--file", self.f, "--name", self.NAME, "--prefix", "scrypt$",
                          "--mode", "0600", *extra], value)

    def test_a_value_with_a_dollar_is_refused_bare_and_the_file_is_untouched(self):
        open(self.f, "w").write("OPENROUTER_API_KEY=sk-or-x\n")
        rc, text = self.set_(self.HASH)
        self.assertEqual(rc, 2)
        self.assertIn("--quote single", text)
        self.assertNotIn("bm90LW", text)
        self.assertEqual(open(self.f).read(), "OPENROUTER_API_KEY=sk-or-x\n")

    def test_quote_single_writes_the_value_literally_and_keeps_every_other_line(self):
        open(self.f, "w").write("# c\nOPENROUTER_API_KEY=sk-or-x\nHERMES_DASHBOARD=1\n")
        rc, text = self.set_(self.HASH, "--quote", "single")
        self.assertEqual(rc, 0, text)
        self.assertEqual(open(self.f).read(),
                         "# c\nOPENROUTER_API_KEY=sk-or-x\nHERMES_DASHBOARD=1\n" + f"{self.NAME}='{self.HASH}'\n")
        self.assertNotIn("bm90LW", text)

    def test_the_quoted_line_reads_back_as_the_exact_value(self):
        """The review collector's reader (client_audit_lib.env_values) must give the value the
        gateway receives, or D4.1 `secret_env` would say differs-from-file for a healthy box."""
        import sys
        sys.path.insert(0, HERE)
        import client_audit_lib as CAL
        self.set_(self.HASH, "--quote", "single")
        self.assertEqual(CAL.env_values(open(self.f).read(), self.NAME), [self.HASH])

    def test_a_single_quote_inside_a_quoted_value_is_refused(self):
        rc, text = self.set_("scrypt$1$it's", "--quote", "single")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.f))

    def test_quote_single_replaces_an_existing_line_in_place(self):
        open(self.f, "w").write(f"A=1\n{self.NAME}=old\nB=2\n")
        self.set_(self.HASH, "--quote", "single")
        self.assertEqual(open(self.f).read(), f"A=1\n{self.NAME}='{self.HASH}'\nB=2\n")

    def test_stdin_takes_the_value_from_a_pipe_and_drops_one_line_break(self):
        for piped in (self.HASH, self.HASH + "\n"):
            with self.subTest(piped=piped[-3:]):
                if os.path.exists(self.f):
                    os.unlink(self.f)
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    rc = S.main(["set", "--file", self.f, "--name", self.NAME, "--prefix", "scrypt$", "--quote", "single",
                                 "--mode", "0600", "--stdin"], read_value=lambda: self.fail("the terminal was asked"),
                                read_pipe=lambda: piped[:-1] if piped.endswith("\n") else piped)
                self.assertEqual(rc, 0, out.getvalue())
                self.assertEqual(open(self.f).read(), f"{self.NAME}='{self.HASH}'\n")
                self.assertNotIn("bm90LW", out.getvalue())

    def test_stdin_refuses_a_terminal_and_an_empty_pipe(self):
        with mock.patch.object(S.sys, "stdin", mock.Mock(isatty=lambda: True)):
            self.assertIsNone(S._pipe_value())
        with mock.patch.object(S.sys, "stdin", io.StringIO("value\n\n")):
            self.assertEqual(S._pipe_value(), "value\n")                 # ONE line break is the pipe's
        for piped in (None, ""):                                          # a terminal, or a program that printed nothing
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = S.main(["set", "--file", self.f, "--name", self.NAME, "--prefix", "scrypt$", "--quote", "single",
                             "--mode", "0600", "--stdin"], read_pipe=lambda: piped)
            self.assertEqual(rc, 2)
            self.assertFalse(os.path.exists(self.f))

    def test_generate_writes_32_random_bytes_as_base64_and_never_prints_them(self):
        open(self.f, "w").write("A=1\n"); os.chmod(self.f, 0o600)
        rc, text = self.run_(["generate", "--file", self.f, "--name", self.SECRET, "--mode", "0600"],
                             random_bytes=lambda n: bytes(range(n)))
        self.assertEqual(rc, 0, text)
        import base64
        want = base64.b64encode(bytes(range(32))).decode()
        self.assertEqual(open(self.f).read(), f"A=1\n{self.SECRET}={want}\n")
        self.assertNotIn(want, text)
        self.assertIn("generated", text)
        self.assertNotIn("$", want)
        self.assertEqual(stat.S_IMODE(os.stat(self.f).st_mode), 0o600)

    def test_generate_uses_the_system_random_source_and_differs_each_time(self):
        seen = set()
        for i in range(2):
            f = os.path.join(self.d, f"e{i}")
            self.run_(["generate", "--file", f, "--name", self.SECRET, "--mode", "0600"])
            value = open(f).read().split("=", 1)[1].strip()
            self.assertEqual(len(value), 44)
            seen.add(value)
        self.assertEqual(len(seen), 2)

    def test_generate_refuses_a_name_that_already_has_a_value(self):
        open(self.f, "w").write(f"{self.SECRET}=keepme\n")
        rc, text = self.run_(["generate", "--file", self.f, "--name", self.SECRET, "--mode", "0600"])
        self.assertEqual(rc, 2)
        self.assertIn("strip it first", text)
        self.assertNotIn("keepme", text)
        self.assertEqual(open(self.f).read(), f"{self.SECRET}=keepme\n")

    def test_generate_fills_an_empty_assignment(self):
        open(self.f, "w").write(f"A=1\n{self.SECRET}=\nB=2\n")
        rc, _ = self.run_(["generate", "--file", self.f, "--name", self.SECRET, "--mode", "0600"],
                          random_bytes=lambda n: b"\x00" * n)
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.f).read(), f"A=1\n{self.SECRET}={'A' * 43}=\nB=2\n")


class TestTheRunbooksCommandLines(unittest.TestCase):
    """Every `install-env-secret.py` command BRING-UP tells the operator to run must be one this
    tool accepts: a flag renamed here and not there would fail on the box, mid-procedure."""
    def test_every_command_in_bring_up_runs(self):
        import re, shlex
        with open(os.path.join(os.path.dirname(HERE), "deploy", "BRING-UP.md"), encoding="utf-8") as f:
            text = f.read()
        commands = re.findall(r"bin/install-env-secret\.py ((?:set|generate|strip) [^`\n|;]*)", text)
        self.assertGreaterEqual(len({c.split()[0] for c in commands}), 3, commands)     # set, generate and strip all appear
        for command in commands:
            with self.subTest(command=command[:70]):
                d = tempfile.mkdtemp(); f = os.path.join(d, "envfile")
                argv = shlex.split(command)
                self.assertTrue(argv[argv.index("--file") + 1].startswith("/"), argv)   # an absolute path on the box
                argv[argv.index("--file") + 1] = f
                for flag in ("--owner-uid", "--owner-gid"):              # not root here: keep the flag's parsing, not chown
                    if flag in argv:
                        i = argv.index(flag); self.assertEqual(argv[i + 1], "0"); del argv[i:i + 2]
                prefix = argv[argv.index("--prefix") + 1] if "--prefix" in argv else ""
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    rc = S.main(argv, read_value=lambda: prefix + "value", read_pipe=lambda: prefix + "value")
                self.assertEqual(rc, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
