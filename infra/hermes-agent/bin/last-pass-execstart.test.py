#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile, unittest
TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-pass-execstart.py")
VALUE = "0123456789abcdef" * 4


def run(*args):
    p = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class T(unittest.TestCase):
    def _bundle(self, value):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"items": {"D4.2": {"status": "observed", "data": {"execstart_sha256": value}}}}, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_the_value_alone_with_no_line_break(self):
        self.assertEqual(run(self._bundle(VALUE)), (0, VALUE, ""))

    def test_anything_else_prints_nothing_anywhere(self):
        for value in (VALUE.upper(), VALUE[:-1], "could-not-check", None, 7, [VALUE]):
            with self.subTest(value=value):
                self.assertEqual(run(self._bundle(value)), (1, "", ""))

    def test_a_missing_file_a_file_that_is_not_json_and_no_argument_print_nothing(self):
        f = tempfile.NamedTemporaryFile("w", delete=False); f.write("not json"); f.close()
        self.addCleanup(os.unlink, f.name)
        for args in (("/nonexistent/bundle.json",), (f.name,), ()):
            with self.subTest(args=args):
                self.assertEqual(run(*args), (1, "", ""))

    def _shell_stderr(self, tail):
        b = self._bundle(VALUE)
        err = tempfile.NamedTemporaryFile(delete=False); err.close()
        self.addCleanup(os.unlink, err.name)
        p = subprocess.run(["sh", "-c", 'python3 "$1" "$2" %s 2>"$3"' % tail, "sh", TOOL, b, err.name])
        with open(err.name) as f:
            return p.returncode, f.read()

    def test_a_closed_stdout_fails_silently(self):
        self.assertEqual(self._shell_stderr(">&-"), (1, ""))

    def test_a_reader_that_exits_at_once_leaves_no_message(self):
        self.assertEqual(self._shell_stderr("| true")[1], "")


if __name__ == "__main__":
    unittest.main()
