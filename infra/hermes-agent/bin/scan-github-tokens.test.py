#!/usr/bin/env python3
"""Tests for scan-github-tokens.py (P0-10 step 3, the scan for P5 and P15).

Every token here is FAKE, generated inside the test, and lives only in temp folders. No test
reads a real folder, and no test touches the network: the HTTP call is a seam, and the
default fake raises if it is ever called.

The one property that matters most is asserted in every mode, including --try and the error
paths: the output never holds a token value, nor any 8 consecutive characters of one.
"""
import contextlib, hashlib, importlib.util, io, os, random, re, stat, string, subprocess, sys
import tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

SCRIPT = os.path.join(HERE, "scan-github-tokens.py")
spec = importlib.util.spec_from_file_location("scan_github_tokens", SCRIPT)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SECRET_PATTERNS_JS = os.path.join(REPO_ROOT, "scripts", "telemetry", "secret-patterns.js")

ALNUM = string.ascii_letters + string.digits
RNG = random.Random(20261030)


def rnd(n):
    return "".join(RNG.choice(ALNUM) for _ in range(n))


def fake(prefix, n=36):
    """A fake gh*_ token: the prefix and n alphanumerics (36 gives the full 40-character shape)."""
    return prefix + rnd(n)


def fake_fg(first=22, second=59):
    return "github_pat_" + rnd(first) + "_" + rnd(second)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    return path


class NoNetwork:
    """The default seam in tests: any call is a test failure."""
    calls = 0

    def __call__(self, url, token):
        NoNetwork.calls += 1
        raise AssertionError("the network seam was called")


class LeakMixin:
    def assertNoLeak(self, text, tokens):
        for t in tokens:
            for i in range(len(t) - 7):
                self.assertNotIn(t[i:i + 8], text, "output holds 8+ consecutive characters of a token")


class TestPatternParity(unittest.TestCase):
    """secret-patterns.js is the one pattern source; Python cannot import it, so the copy is
    pinned here. An edit to either file without the other fails this test."""

    def js_body(self, name):
        with open(SECRET_PATTERNS_JS, encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"name:\s*'" + re.escape(name) + r"',\s*re:\s*/(.+?)/\s*}", src)
        self.assertIsNotNone(m, f"{name} not found in secret-patterns.js")
        return m.group(1)

    def test_github_token_pattern_matches_js(self):
        self.assertEqual(S.GH_TOKEN_PATTERN, self.js_body("github-token"))

    def test_github_fine_grained_pattern_matches_js(self):
        self.assertEqual(S.GH_PAT_PATTERN, self.js_body("github-fine-grained-pat"))

    def test_compiled_regexes_use_the_pinned_bodies(self):
        self.assertEqual(S.GH_TOKEN_RE.pattern, S.GH_TOKEN_PATTERN.encode())
        self.assertEqual(S.GH_PAT_RE.pattern, S.GH_PAT_PATTERN.encode())


class TestClassify(unittest.TestCase):
    def test_type_labels(self):
        for prefix, label in (("ghp_", "classic"), ("gho_", "oauth"), ("ghu_", "user-to-server"),
                              ("ghs_", "installation"), ("ghr_", "refresh")):
            with self.subTest(prefix=prefix):
                self.assertEqual(S.classify(fake(prefix).encode(), b" ")[0], label)
        self.assertEqual(S.classify(fake_fg().encode(), b" ")[0], "fine-grained")

    def test_full_shapes(self):
        for tok in [fake(p) for p in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_")] + [fake_fg()]:
            with self.subTest(tok=tok[:4]):
                self.assertTrue(S.classify(tok.encode(), b"")[1])
                self.assertTrue(S.classify(tok.encode(), b"\n")[1])

    def test_wrong_lengths_are_partial(self):
        for tok in (fake("ghp_", 35), fake("ghp_", 37), fake("ghp_", 20), fake_fg(21, 59),
                    fake_fg(22, 58), fake_fg(22, 60), "github_pat_" + rnd(82)):
            with self.subTest(n=len(tok)):
                self.assertFalse(S.classify(tok.encode(), b" ")[1])

    def test_c_token_character_after_makes_it_partial(self):
        for tok in (fake("ghp_").encode(), fake_fg().encode()):
            for after in (b"_", b"a", b"Z", b"7"):
                with self.subTest(tok=tok[:4], after=after):
                    self.assertFalse(S.classify(tok, after)[1])

    def test_b_any_character_before_is_allowed(self):
        # Decision 2026-10-30: no condition on the character before. JSONL escapes a newline
        # as "\n", so a token at the start of a line sits right after an "n".
        for before in (b"x", b"n", b"7", b"_", b"\\n", b" "):
            data = b"{" + before + fake("ghp_").encode() + b"}"
            with self.subTest(before=before):
                got = matches_in(data, S.CHUNK)
                self.assertEqual(len(got), 1)
                self.assertTrue(S.classify(got[0][0].encode(), got[0][1])[1])


def matches_in(data, chunk_size):
    return [(m.decode(), a) for m, a in S.iter_matches(io.BytesIO(data), chunk_size)]


class TestByteScanner(unittest.TestCase):
    def test_overlap_is_at_least_128(self):
        self.assertGreaterEqual(S.OVERLAP, 128)

    def test_finds_tokens_in_binary_data(self):
        tok = fake("gho_")
        data = b"\x00\xff\x01SQLite format 3\x00" + tok.encode() + b"\x00\x9c\xfe"
        self.assertEqual([m for m, _ in matches_in(data, S.CHUNK)], [tok])

    def test_a_match_across_a_chunk_boundary_is_found_once(self):
        tok = fake("ghp_")
        for chunk in (7, 64, 200):
            for off in range(0, 2 * chunk + 140, 3):
                data = (b"-" * off) + tok.encode() + b"-" * 50
                with self.subTest(chunk=chunk, off=off):
                    got = matches_in(data, chunk)
                    self.assertEqual([m for m, _ in got], [tok])
                    self.assertTrue(S.classify(got[0][0].encode(), got[0][1])[1])

    def test_d_prefix_just_after_a_chunk_boundary_is_found_once_and_full(self):
        # Every offset around two boundaries, a letter right before the prefix, for each type,
        # and the after-character check across the boundary too.
        for tok in (fake("ghp_"), fake("ghs_"), fake_fg()):
            for chunk in (7, 200):
                for off in range(chunk - 120 if chunk > 120 else 0, 2 * chunk + 3):
                    data = b"-" * off + b"x" + tok.encode() + b"-"
                    with self.subTest(tok=tok[:4], chunk=chunk, off=off):
                        got = matches_in(data, chunk)
                        self.assertEqual([m for m, _ in got], [tok])
                        self.assertTrue(S.classify(got[0][0].encode(), got[0][1])[1])
                    data = b"-" * off + tok.encode() + b"_" + b"-" * 3
                    with self.subTest(tok=tok[:4], chunk=chunk, off=off, after="_"):
                        got = matches_in(data, chunk)
                        if tok.startswith("github_pat_"):     # "_" is a body character there
                            self.assertEqual([m for m, _ in got], [tok + "_"])
                        else:
                            self.assertEqual([m for m, _ in got], [tok])
                        self.assertFalse(S.classify(got[0][0].encode(), got[0][1])[1])

    def test_fine_grained_across_a_boundary_and_no_inner_classic_match(self):
        tok = fake_fg()
        for off in range(100, 400, 5):
            data = b" " * off + tok.encode() + b" "
            with self.subTest(off=off):
                self.assertEqual([m for m, _ in matches_in(data, 128)], [tok])

    def test_a_classic_shape_inside_a_fine_grained_body_is_not_a_second_match(self):
        tok = "github_pat_" + rnd(19) + "ghp_" + rnd(59)
        self.assertEqual([m for m, _ in matches_in(tok.encode(), S.CHUNK)], [tok])

    def test_adjacent_tokens_across_a_boundary_each_once(self):
        a, b = fake("ghp_"), fake("ghs_")
        for off in range(0, 300, 7):
            data = b"." * off + a.encode() + b"\n" + b.encode() + b"\n"
            with self.subTest(off=off):
                self.assertEqual([m for m, _ in matches_in(data, 100)], [a, b])

    def test_long_run_is_one_match(self):
        tok = fake("ghp_", 500)
        got = matches_in(b" " + tok.encode() + b" ", 64)
        self.assertEqual([m for m, _ in got], [tok])


def run(argv, http=None, home=None, repo_root=None):
    out, err = io.StringIO(), io.StringIO()
    code = S.main(argv, http=http or NoNetwork(), home=home, repo_root=repo_root, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def lines(text, kind):
    return [l.split("\t") for l in text.splitlines() if l.split("\t")[0] == kind]


class TempCase(LeakMixin, unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._td.name)
        NoNetwork.calls = 0

    def tearDown(self):
        for dirpath, dirnames, _ in os.walk(self.tmp):
            for d in dirnames:
                p = os.path.join(dirpath, d)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
        self._td.cleanup()

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class TestInputs(TempCase):
    def test_no_root_is_a_usage_error(self):
        code, out, err = run([])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())
        self.assertEqual(out, "")

    def test_no_root_from_the_command_line_exits_2(self):
        r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr.lower())

    def test_bad_max_bytes_and_unknown_preset_are_usage_errors(self):
        for argv in (["--root", self.tmp, "--max-bytes", "0"], ["--root", self.tmp, "--max-bytes", "x"],
                     ["--preset", "desktop"]):
            with self.subTest(argv=argv):
                self.assertEqual(run(argv)[0], 2)

    def test_usage_error_never_echoes_token_text(self):
        tok = fake("ghp_")
        code, out, err = run(["--root", self.tmp, "--max-bytes", tok])
        self.assertEqual(code, 2)
        self.assertNoLeak(out + err, [tok])

    def test_root_is_repeatable_and_takes_files_and_folders(self):
        a, b = fake("ghp_"), fake("gho_")
        write(self.p("one", "deep", "x.txt"), "a=" + a)
        f = write(self.p("two.txt"), "b=" + b)
        code, out, _ = run(["--root", self.p("one"), "--root", f])
        self.assertEqual(sorted(l[3] for l in lines(out, "finding")), sorted([R.sha12(a), R.sha12(b)]))
        self.assertNoLeak(out, [a, b])

    def test_tilde_is_expanded(self):
        tok = fake("ghp_")
        write(self.p("sub", "f"), tok)
        with mock.patch.dict(os.environ, {"HOME": self.tmp}):
            code, out, _ = run(["--root", "~/sub"])
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(tok)])

    def test_missing_root_is_absent_not_an_error(self):
        code, out, _ = run(["--root", self.p("nope")])
        self.assertEqual(code, 0)
        self.assertEqual(lines(out, "absent"), [["absent", self.p("nope")]])


class TestPreset(TempCase):
    def test_preset_expands_to_the_plan_include_list(self):
        home, repo = self.p("home"), self.p("repo")
        paths = S.preset_laptop(home, repo)[0]
        h = lambda *x: os.path.join(home, *x)
        for want in (h(".claude"), h(".claude.json"), h("Library", "Application Support", "Claude"),
                     h("Library", "Logs", "Claude"), h(".codex"), h(".cursor"), h(".gemini"),
                     h(".openclaw"), h(".openhands"), h(".hermes"), repo, h(".netrc"),
                     h(".git-credentials"), h(".npmrc"), h(".config"),
                     h("Library", "Application Support", "Code", "User", "settings.json"),
                     h("Library", "Application Support", "Cursor", "User", "settings.json"),
                     h("Library", "LaunchAgents"), h(".zshrc"), h(".zprofile"), h(".zshenv"),
                     h(".bashrc"), h(".bash_profile"), h(".profile"), h(".zsh_history"),
                     h(".bash_history"), h(".zsh_sessions"), h(".gitconfig"), h("Downloads"),
                     h("Desktop"), h("Documents")):
            with self.subTest(want=want):
                self.assertIn(want, paths)

    def test_preset_scan_finds_git_configs_and_env_files_and_reports_absent(self):
        home, repo = self.p("home"), self.p("repo")
        t = {k: fake("ghp_") for k in ("gitcfg", "gitcfg_deep", "env", "env_deep", "repo", "zsh",
                                       "notes", "libenv", "outside")}
        write(os.path.join(home, "Projects", "a", ".git", "config"), "url=https://x:" + t["gitcfg"] + "@github.com")
        write(os.path.join(home, "Projects", "b", "c", "d", ".git", "config"), t["gitcfg_deep"])
        write(os.path.join(home, ".env.local"), "T=" + t["env"])
        write(os.path.join(home, "work", "app", ".env"), "T=" + t["env_deep"])
        write(os.path.join(repo, "infra", "x.log"), t["repo"])
        write(os.path.join(home, ".zsh_history"), t["zsh"])
        # Not in the include list: other files under ~/Projects, a .env under ~/Library, a random folder.
        write(os.path.join(home, "Projects", "a", "notes.txt"), t["notes"])
        write(os.path.join(home, "Library", "Other", ".env"), t["libenv"])
        for k, sub in (("pics", "Pictures"), ("music", "Music"), ("movies", "Movies"), ("trash", ".Trash")):
            t[k] = fake("ghp_")
            write(os.path.join(home, sub, "x", ".env"), t[k])
        write(os.path.join(home, "random", "f.txt"), t["outside"])
        code, out, _ = run(["--preset", "laptop"], home=home, repo_root=repo)
        found = {l[3] for l in lines(out, "finding")}
        for k in ("gitcfg", "gitcfg_deep", "env", "env_deep", "repo", "zsh"):
            with self.subTest(k=k):
                self.assertIn(R.sha12(t[k]), found)
        for k in ("notes", "libenv", "outside", "pics", "music", "movies", "trash"):
            with self.subTest(k=k):
                self.assertNotIn(R.sha12(t[k]), found)
        absent = [l[1] for l in lines(out, "absent")]
        self.assertIn(os.path.join(home, ".codex"), absent)
        self.assertIn(os.path.join(home, "Downloads"), absent)
        self.assertEqual(code, 1)
        self.assertNoLeak(out, t.values())


class TestWalk(TempCase):
    def test_symlinks_are_skipped_never_followed(self):
        tok = fake("ghp_")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        write(os.path.join(outside.name, "secret.txt"), tok)
        os.makedirs(self.p("root"))
        os.symlink(os.path.join(outside.name, "secret.txt"), self.p("root", "file-link"))
        os.symlink(outside.name, self.p("root", "dir-link"))
        os.symlink(self.p("root"), self.p("root-link"))
        code, out, _ = run(["--root", self.p("root"), "--root", self.p("root-link")])
        self.assertEqual(lines(out, "finding"), [])
        self.assertEqual(sorted(lines(out, "skipped")),
                         sorted([["skipped", self.p("root", "dir-link"), "symlink"],
                                 ["skipped", self.p("root", "file-link"), "symlink"],
                                 ["skipped", self.p("root-link"), "symlink"]]))
        self.assertEqual(code, 0)

    def test_binary_files_are_scanned(self):
        tok = fake("ghu_")
        write(self.p("Local Storage", "leveldb", "000003.log"), b"\x00\x01\xfe" + tok.encode() + b"\x00\xff")
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(tok)])

    def test_size_cap(self):
        self.assertEqual(S.DEFAULT_MAX_BYTES, 512 * 1024 * 1024)
        tok = fake("ghp_")
        write(self.p("big.bin"), b"x" * 200 + tok.encode())
        write(self.p("small.txt"), b"ok")
        code, out, _ = run(["--root", self.tmp, "--max-bytes", "100"])
        self.assertEqual(lines(out, "skipped"), [["skipped", self.p("big.bin"), "size"]])
        self.assertEqual(lines(out, "finding"), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_unreadable_files_and_folders_are_skipped_and_the_run_continues(self):
        a, b, c = fake("ghp_"), fake("ghp_"), fake("ghp_")
        write(self.p("locked.txt"), a)
        os.chmod(self.p("locked.txt"), 0)
        write(self.p("lockeddir", "f"), b)
        os.chmod(self.p("lockeddir"), 0)
        write(self.p("ok.txt"), c)
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(sorted(lines(out, "skipped")),
                         [["skipped", self.p("locked.txt"), "unreadable"],
                          ["skipped", self.p("lockeddir"), "unreadable"]])
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(c)])

    def test_special_files_are_skipped_without_blocking(self):
        os.mkfifo(self.p("pipe"))
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(lines(out, "skipped"), [["skipped", self.p("pipe"), "not-a-regular-file"]])

    def test_a_very_deep_tree_does_not_abort_the_run(self):
        # 300 levels against a recursion limit of 150: a recursive walk dies, an iterative one
        # does not. (Linux allows paths deep enough to hit the default limit of 1000.)
        tok = fake("ghp_")
        write(os.path.join(self.tmp, *(["d"] * 300), "deep.txt"), tok)
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(150)
        try:
            code, out, err = run(["--root", self.tmp])
        finally:
            sys.setrecursionlimit(old)
        self.assertEqual(err, "")
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(tok)])

    def test_overlapping_roots_scan_each_file_once(self):
        tok = fake("ghp_")
        write(self.p("a", "b", "f"), tok)
        code, out, _ = run(["--root", self.p("a"), "--root", self.p("a", "b"), "--root", self.p("a", "b", "f")])
        self.assertEqual(lines(out, "finding")[0][4], "count=1")
        self.assertIn("files_scanned=1", lines(out, "totals")[0])


class TestOutput(TempCase):
    def test_finding_and_token_lines(self):
        full, part = fake("ghp_"), fake("ghs_", 30)
        fg = fake_fg()
        write(self.p("a.jsonl"), f'{{"t":"{full}"}} {full} {part} {fg}')
        write(self.p("b", "c.txt"), full)
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(lines(out, "finding"), sorted([
            ["finding", self.p("a.jsonl"), "classic", R.sha12(full), "count=2", "full", "len=40"],
            ["finding", self.p("a.jsonl"), "installation", R.sha12(part), "count=1", "partial", "len=34"],
            ["finding", self.p("a.jsonl"), "fine-grained", R.sha12(fg), "count=1", "full", "len=93"],
            ["finding", self.p("b", "c.txt"), "classic", R.sha12(full), "count=1", "full", "len=40"],
        ]))
        self.assertEqual(lines(out, "token"), sorted([
            ["token", R.sha12(full), "classic", "files=2", "full", "len=40"],
            ["token", R.sha12(part), "installation", "files=1", "partial", "len=34"],
            ["token", R.sha12(fg), "fine-grained", "files=1", "full", "len=93"],
        ]))
        self.assertEqual(lines(out, "totals"), [["totals", "files_scanned=2", "findings=4",
                                                 "full_tokens=2", "partial_tokens=1", "skipped=0", "absent=0"]])
        self.assertNoLeak(out, [full, part, fg])

    def test_sections_come_in_order_and_output_is_stable(self):
        write(self.p("z.txt"), fake("ghp_"))
        write(self.p("a.txt"), fake("gho_"))
        os.symlink(self.p("a.txt"), self.p("link"))
        argv = ["--root", self.tmp, "--root", self.p("missing")]
        first, second = run(argv)[1], run(argv)[1]
        self.assertEqual(first, second)
        kinds = [l.split("\t")[0] for l in first.splitlines() if not l.startswith("#")]
        self.assertEqual(kinds, ["finding", "finding", "token", "token", "skipped", "absent", "totals"])

    def test_no_value_in_any_line_and_token_like_path_text_is_redacted(self):
        tok, name_tok = fake("ghp_"), fake("gho_")
        write(self.p("dir-" + name_tok, "f.txt"), tok)
        code, out, err = run(["--root", self.tmp, "--root", self.p("gone-" + name_tok)])
        self.assertNoLeak(out + err, [tok, name_tok])
        self.assertEqual(len(lines(out, "finding")), 1)

    def test_guard_withholds_a_line_holding_8_characters_of_a_matched_text(self):
        tok = fake("ghp_")
        self.assertEqual(S.guard(["ok line", "x" + tok[9:17] + "y"], {tok}),
                         ["ok line", "withheld\ta line held token text"])
        self.assertEqual(S.guard(["x" + tok[9:16] + "y"], {tok}), ["x" + tok[9:16] + "y"])

    def test_guard_catches_a_path_holding_a_slice_of_a_found_token(self):
        # The slice has no gh*_ prefix, so path redaction cannot see it; the guard must.
        tok = fake("ghp_")
        write(self.p("dir-" + tok[6:30], "f.txt"), tok)
        code, out, _ = run(["--root", self.tmp])
        self.assertNoLeak(out, [tok])
        self.assertEqual(len(lines(out, "withheld")), 1)

    def test_hash_paths_under(self):
        tok = fake("ghp_")
        data = self.p("hermes", "data")
        write(os.path.join(data, "clients", "1234567890", "run.log"), tok)
        os.symlink(os.path.join(data, "clients"), os.path.join(data, "link-9876543210"))
        argv = ["--root", data, "--root", os.path.join(data, "5555555555"), "--hash-paths-under", data + "/"]
        code, out, _ = run(argv)
        for cid in ("1234567890", "9876543210", "5555555555"):
            self.assertNotIn(cid, out)
        self.assertEqual(lines(out, "finding")[0][1], data + "/" + R.sha12("clients/1234567890/run.log"))
        self.assertEqual(lines(out, "skipped")[0][1], data + "/" + R.sha12("link-9876543210"))
        self.assertEqual(lines(out, "absent")[0][1], data + "/" + R.sha12("5555555555"))
        # Paths outside the prefix are printed as they are.
        write(self.p("other.txt"), tok)
        out2 = run(["--root", self.tmp, "--hash-paths-under", data])[1]
        self.assertIn(self.p("other.txt"), [l[1] for l in lines(out2, "finding")])


class TestExitWithoutTry(TempCase):
    def test_nothing_found_is_0(self):
        write(self.p("f"), "nothing here")
        self.assertEqual(run(["--root", self.tmp])[0], 0)

    def test_partials_only_is_0_and_never_tried(self):
        write(self.p("f"), fake("ghp_", 25) + " " + fake("ghp_") + "_x")
        code, out, _ = run(["--root", self.tmp, "--try"])
        self.assertEqual(code, 0)
        self.assertEqual(NoNetwork.calls, 0)
        self.assertEqual([l[5] for l in lines(out, "finding")], ["partial", "partial"])

    def test_full_token_without_try_is_1_and_no_network(self):
        write(self.p("f"), fake("ghp_") + " " + fake("ghs_") + " " + fake("ghr_") + " " + fake_fg())
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(code, 1)
        self.assertEqual(NoNetwork.calls, 0)
        self.assertEqual(lines(out, "try"), [])


class FakeHttp:
    """Records every call; answers from a table keyed by token value."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url, token):
        self.calls.append((url, token))
        a = self.answers[token]
        if isinstance(a, BaseException):
            raise a
        return a


def gh_json(**kw):
    import json
    return json.dumps(kw).encode()


USER = "https://api.github.com/user"
INST = "https://api.github.com/installation/repositories"


class TestTryOne(LeakMixin, unittest.TestCase):
    def one(self, kind, tok, answer):
        http = FakeHttp({tok: answer})
        result = S.try_token(kind, tok, http)
        self.assertNoLeak(result, [tok])
        return result, http.calls

    def test_user_endpoint_alive_for_the_four_user_types(self):
        for kind, tok in (("classic", fake("ghp_")), ("oauth", fake("gho_")),
                          ("user-to-server", fake("ghu_")), ("fine-grained", fake_fg())):
            with self.subTest(kind=kind):
                result, calls = self.one(kind, tok, (200, gh_json(login="octo-cat", id=1)))
                self.assertEqual(result, "ALIVE login=octo-cat")
                self.assertEqual(calls, [(USER, tok)])

    def test_bad_credentials_401_is_dead(self):
        result, _ = self.one("classic", fake("ghp_"), (401, gh_json(message="Bad credentials")))
        self.assertEqual(result, "DEAD (Bad credentials, 401)")

    def test_other_answers_are_unknown_with_the_message(self):
        tok = fake("ghp_")
        for answer, want in (((401, gh_json(message="Requires authentication")), "UNKNOWN 401 Requires authentication"),
                             ((403, gh_json(message="Resource not accessible by integration")),
                              "UNKNOWN 403 Resource not accessible by integration"),
                             ((502, b"<html>bad gateway</html>"), "UNKNOWN 502"),
                             ((200, b"not json"), "ALIVE login=?"),
                             ((200, gh_json(login="bad login\n")), "ALIVE login=?")):
            with self.subTest(want=want):
                self.assertEqual(self.one("classic", tok, answer)[0], want)

    def test_message_is_truncated_to_80(self):
        result, _ = self.one("oauth", fake("gho_"), (403, gh_json(message="m" * 200)))
        self.assertEqual(result, "UNKNOWN 403 " + "m" * 80)

    def test_message_holding_token_text_is_withheld(self):
        tok, other = fake("ghp_"), fake("gho_")
        for msg in ("token " + tok + " is bad", "see " + tok[10:30], "other " + other):
            with self.subTest(msg=msg[:8]):
                result, _ = self.one("classic", tok, (422, gh_json(message=msg)))
                self.assertEqual(result, "UNKNOWN 422 [message withheld: token text]")
                self.assertNoLeak(result, [tok, other])

    def test_installation_endpoint(self):
        tok = fake("ghs_")
        result, calls = self.one("installation", tok, (200, gh_json(total_count=3, repositories=[])))
        self.assertEqual(result, "ALIVE total_count=3")
        self.assertEqual(calls, [(INST, tok)])
        self.assertEqual(self.one("installation", tok, (401, gh_json(message="Bad credentials")))[0],
                         "DEAD (Bad credentials, 401)")
        self.assertEqual(self.one("installation", tok, (401, b""))[0], "DEAD (401)")
        self.assertEqual(self.one("installation", tok, (500, gh_json(message="oops")))[0], "UNKNOWN 500 oops")

    def test_refresh_is_never_sent(self):
        tok = fake("ghr_")
        http = FakeHttp({})
        self.assertEqual(S.try_token("refresh", tok, http), "CANNOT BE PROVED BY USE (refresh token)")
        self.assertEqual(http.calls, [])

    def test_network_errors(self):
        import socket, urllib.error
        tok = fake("ghp_")
        for exc, name in ((urllib.error.URLError("no route " + tok), "URLError"),
                          (TimeoutError(tok), "TimeoutError"), (socket.gaierror(tok), "gaierror"),
                          (ConnectionResetError(tok), "ConnectionResetError")):
            with self.subTest(name=name):
                self.assertEqual(self.one("classic", tok, exc)[0], "UNKNOWN network-error " + name)


class TestDefaultHttp(LeakMixin, unittest.TestCase):
    """The real seam, exercised against a fake opener: no socket is ever opened."""

    class Opener:
        def __init__(self, answer):
            self.answer, self.reqs = answer, []

        def open(self, req, timeout=None):
            self.reqs.append((req, timeout))
            if isinstance(self.answer, BaseException):
                raise self.answer
            body = self.answer

            class Resp(io.BytesIO):
                status = 200
            return Resp(body)

    def test_bearer_header_in_memory_and_get(self):
        tok = fake("ghp_")
        op = self.Opener(b'{"login":"x"}')
        self.assertEqual(S.github_get(USER, tok, opener=op), (200, b'{"login":"x"}'))
        req, timeout = op.reqs[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, USER)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + tok)
        self.assertIsNotNone(timeout)

    def test_http_error_is_an_answer_not_an_exception(self):
        import urllib.error
        tok = fake("ghp_")
        err = urllib.error.HTTPError(USER, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Bad credentials"}'))
        self.assertEqual(S.github_get(USER, tok, opener=self.Opener(err)), (401, b'{"message":"Bad credentials"}'))

    def test_only_api_github_com_over_https(self):
        for url in ("http://api.github.com/user", "https://example.com/user", "https://api.github.com.evil/user"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    S.github_get(url, "x", opener=self.Opener(b""))

    def test_redirects_are_refused(self):
        # A redirect would carry the Authorization header to wherever it points.
        import urllib.request
        h = S._NoRedirect()
        req = urllib.request.Request(USER, headers={"Authorization": "Bearer x"})
        self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, "https://elsewhere.example/"))
        op = S._opener()
        self.assertTrue(any(isinstance(x, S._NoRedirect) for x in op.handlers))


class TestTryCli(TempCase):
    def test_one_request_per_distinct_full_token_in_order(self):
        a, b, r = fake("ghp_"), fake("ghs_"), fake("ghr_")
        part = fake("ghp_", 30)
        write(self.p("1.txt"), f"{a} {a} {b} {r} {part}")
        write(self.p("2.txt"), f"{a} {b}")
        http = FakeHttp({a: (401, gh_json(message="Bad credentials")), b: (401, b"")})
        code, out, err = run(["--root", self.tmp, "--try"], http=http)
        self.assertEqual(sorted(c[1] for c in http.calls), sorted([a, b]))
        self.assertEqual(lines(out, "try"), sorted([
            ["try", R.sha12(a), "classic", "DEAD (Bad credentials, 401)"],
            ["try", R.sha12(b), "installation", "DEAD (401)"],
            ["try", R.sha12(r), "refresh", "CANNOT BE PROVED BY USE (refresh token)"]]))
        self.assertNoLeak(out + err, [a, b, r, part])
        self.assertEqual(code, 1)   # the refresh token is not proved dead

    def test_a_token_after_a_jsonl_newline_escape_is_full_and_tried(self):
        tok = fake("gho_")
        write(self.p("session.jsonl"), '{"type":"user","content":"line one\\n' + tok + '\\nmore"}\n')
        http = FakeHttp({tok: (401, gh_json(message="Bad credentials"))})
        code, out, err = run(["--root", self.tmp, "--try"], http=http)
        self.assertEqual([l[5] for l in lines(out, "finding")], ["full"])
        self.assertEqual(http.calls, [(USER, tok)])
        self.assertEqual(lines(out, "try"), [["try", R.sha12(tok), "oauth", "DEAD (Bad credentials, 401)"]])
        self.assertEqual(code, 0)
        self.assertNoLeak(out + err, [tok])

    def test_all_dead_is_0(self):
        a, fg = fake("gho_"), fake_fg()
        write(self.p("f"), f"{a}\n{fg}\n")
        http = FakeHttp({a: (401, gh_json(message="Bad credentials")), fg: (401, gh_json(message="Bad credentials"))})
        code, out, err = run(["--root", self.tmp, "--try"], http=http)
        self.assertEqual(code, 0)
        self.assertEqual(len(http.calls), 2)
        self.assertNoLeak(out + err, [a, fg])

    def test_alive_or_unknown_is_1(self):
        import urllib.error
        tok = fake("ghp_")
        write(self.p("f"), tok)
        for answer in ((200, gh_json(login="someone")), (403, gh_json(message="rate limited " + tok)),
                       urllib.error.URLError(tok)):
            with self.subTest(answer=type(answer).__name__):
                code, out, err = run(["--root", self.tmp, "--try"], http=FakeHttp({tok: answer}))
                self.assertEqual(code, 1)
                self.assertEqual(len(lines(out, "try")), 1)
                self.assertNoLeak(out + err, [tok])

    def test_an_unexpected_error_prints_only_its_class_and_exits_1(self):
        tok = fake("ghp_")
        write(self.p("f"), tok)

        def boom(url, token):
            raise RuntimeError("boom " + token)
        with mock.patch.object(S, "try_token", side_effect=RuntimeError("boom " + tok)):
            code, out, err = run(["--root", self.tmp, "--try"], http=boom)
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError", err)
        self.assertNoLeak(out + err, [tok])


class TestDocstring(unittest.TestCase):
    def test_exit_codes_and_owner_section_are_documented(self):
        doc = S.__doc__
        for want in ("EXIT CODES", "0 ", "1 ", "2 ", "HOW THE OWNER RUNS IT", "agents closed",
                     "fingerprints only", "safe to paste"):
            with self.subTest(want=want):
                self.assertIn(want, doc)


if __name__ == "__main__":
    unittest.main()
