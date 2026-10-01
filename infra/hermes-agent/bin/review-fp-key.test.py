#!/usr/bin/env python3
import contextlib, importlib.util, io, os, stat, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fpk", os.path.join(HERE, "review-fp-key.py"))
K = importlib.util.module_from_spec(spec); spec.loader.exec_module(K)


class T(unittest.TestCase):
    def test_init_creates_0600_and_refuses_overwrite(self):
        p = os.path.join(tempfile.mkdtemp(), "sub", "fp.key")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(K.main(["init", "--path", p]), 0)
            self.assertEqual(K.main(["init", "--path", p]), 2)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        with open(p) as f:
            key = f.read().strip()
        self.assertEqual(len(key), 64)
        self.assertNotIn(key, out.getvalue())       # never printed

    def test_show_id(self):
        p = os.path.join(tempfile.mkdtemp(), "fp.key")
        with open(p, "w") as f:
            f.write("ab" * 32)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(K.main(["show-id", "--path", p]), 0)
        self.assertEqual(len(out.getvalue().strip()), 8)


if __name__ == "__main__":
    unittest.main()
