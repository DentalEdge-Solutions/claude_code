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

    def test_the_built_patterns_are_the_pinned_bodies(self):
        # Uncapped plain build == the JS bodies; the capped plain build only adds the cap; the
        # compiled search patterns are exactly the capped builds, plain and UTF-16.
        self.assertEqual(S.build_pattern(S.GH_ATOMS, "plain"), S.GH_TOKEN_PATTERN)
        self.assertEqual(S.build_pattern(S.PAT_ATOMS, "plain"), S.GH_PAT_PATTERN)
        self.assertEqual(S.build_pattern(S.GH_ATOMS, "plain", 256), S.GH_TOKEN_PATTERN.replace("{20,}", "{20,252}"))
        self.assertEqual(S.build_pattern(S.PAT_ATOMS, "plain", 256), S.GH_PAT_PATTERN.replace("{20,}", "{20,245}"))
        compiled = {(fam, enc): rx.pattern for fam, enc, rx in S.PATTERNS}
        for enc in ("plain", "le", "be"):
            self.assertEqual(compiled["gh", enc], S.build_pattern(S.GH_ATOMS, enc, 256).encode())
            self.assertEqual(compiled["pat", enc], S.build_pattern(S.PAT_ATOMS, enc, 256).encode())


class TestClassify(unittest.TestCase):
    def test_type_labels(self):
        for prefix, label in (("ghp_", "classic"), ("gho_", "oauth"), ("ghu_", "user-to-server"),
                              ("ghs_", "installation"), ("ghr_", "refresh")):
            with self.subTest(prefix=prefix):
                self.assertEqual(S.classify(fake(prefix), " ")[0], label)
        self.assertEqual(S.classify(fake_fg(), " ")[0], "fine-grained")

    def test_full_shapes(self):
        for tok in [fake(p) for p in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_")] + [fake_fg()]:
            with self.subTest(tok=tok[:4]):
                self.assertTrue(S.classify(tok, "")[1])
                self.assertTrue(S.classify(tok, "\n")[1])

    def test_wrong_lengths_are_partial(self):
        for tok in (fake("ghp_", 35), fake("ghp_", 37), fake("ghp_", 20), fake_fg(21, 59),
                    fake_fg(22, 58), fake_fg(22, 60), "github_pat_" + rnd(82)):
            with self.subTest(n=len(tok)):
                self.assertFalse(S.classify(tok, " ")[1])

    def test_c_token_character_after_makes_it_partial(self):
        for tok in (fake("ghp_"), fake_fg()):
            for after in ("_", "a", "Z", "7"):
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
                self.assertTrue(S.classify(got[0][0], got[0][1])[1])


def matches_in(data, chunk_size):
    return [(t, a) for t, a, _ in S.iter_matches(io.BytesIO(data), chunk_size)]


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
                    self.assertTrue(S.classify(got[0][0], got[0][1])[1])

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
                        self.assertTrue(S.classify(got[0][0], got[0][1])[1])
                    data = b"-" * off + tok.encode() + b"_" + b"-" * 3
                    with self.subTest(tok=tok[:4], chunk=chunk, off=off, after="_"):
                        got = matches_in(data, chunk)
                        if tok.startswith("github_pat_"):     # "_" is a body character there
                            self.assertEqual([m for m, _ in got], [tok + "_"])
                        else:
                            self.assertEqual([m for m, _ in got], [tok])
                        self.assertFalse(S.classify(got[0][0], got[0][1])[1])

    def test_fine_grained_across_a_boundary_and_no_inner_classic_match(self):
        tok = fake_fg()
        for off in range(100, 400, 5):
            data = b" " * off + tok.encode() + b" "
            with self.subTest(off=off):
                self.assertEqual([m for m, _ in matches_in(data, 128)], [tok])

    def test_the_tail_of_a_processed_match_is_not_searched_again(self):
        # A fine-grained-shaped match that ends past the carry point: its tail (holding a ghp_
        # shape) must not be carried into the next round and found a second time.
        pat = "github_pat_" + rnd(30) + "_ghp_" + rnd(36)
        for chunk in (200, 300):
            for off in range(0, chunk + 10):
                data = b" " * off + pat.encode() + b" " * 300
                with self.subTest(chunk=chunk, off=off):
                    self.assertEqual([t for t, _ in matches_in(data, chunk)], [pat])

    def test_a_fine_grained_token_wins_over_a_classic_shape_running_into_it(self):
        fg = fake_fg()
        data = (" ghp_" + rnd(20) + fg + " ").encode()
        got = matches_in(data, S.CHUNK)
        self.assertEqual([t for t, _ in got], [fg])
        self.assertTrue(S.classify(got[0][0], got[0][1])[1])

    def test_a_classic_shape_inside_a_fine_grained_body_is_not_a_second_match(self):
        tok = "github_pat_" + rnd(19) + "ghp_" + rnd(59)
        self.assertEqual([m for m, _ in matches_in(tok.encode(), S.CHUNK)], [tok])

    def test_adjacent_tokens_across_a_boundary_each_once(self):
        a, b = fake("ghp_"), fake("ghs_")
        for off in range(0, 300, 7):
            data = b"." * off + a.encode() + b"\n" + b.encode() + b"\n"
            with self.subTest(off=off):
                self.assertEqual([m for m, _ in matches_in(data, 100)], [a, b])

    def test_long_run_is_one_capped_match(self):
        tok = fake("ghp_", 500)
        got = list(S.iter_matches(io.BytesIO(b" " + tok.encode() + b" "), 64))
        self.assertEqual([(t, l) for t, _, l in got], [(tok[:256], True)])


def run(argv, http=None, home=None, repo_root=None, path_key=None, environ=None):
    out, err = io.StringIO(), io.StringIO()
    code = S.main(argv, http=http or NoNetwork(), home=home, repo_root=repo_root, stdout=out, stderr=err,
                  path_key=path_key, environ={} if environ is None else environ)
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
        # Inside a walk a symlink is skipped; a top-level root that is a symlink is resolved once,
        # and paths under its target are shown under the root as given.
        self.assertEqual(sorted(lines(out, "skipped")),
                         sorted([["skipped", self.p("root-link", "dir-link"), "symlink"],
                                 ["skipped", self.p("root-link", "file-link"), "symlink"]]))
        self.assertEqual(lines(out, "resolved"), [["resolved", self.p("root"), "(resolved from " + self.p("root-link") + ")"]])
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
                                                 "full_tokens=2", "partial_tokens=1", "skipped=0", "pruned=0",
                                                 "absent=0"]])
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
        row = ["finding", "/a/x" + tok[9:17] + "y", "classic", "0123456789ab", "count=1", "full", "len=40"]
        self.assertEqual(S.guard([["totals", "ok"], row], {tok}),
                         [["totals", "ok"], ["finding", "[path withheld]"] + row[2:]])
        short = ["finding", "/a/-" + tok[9:16] + "-", "classic"]     # "-" is never a token character
        self.assertEqual(S.guard([short], {tok}), [short])

    def test_guard_catches_a_path_holding_a_slice_of_a_found_token(self):
        # The slice has no gh*_ prefix, so path redaction cannot see it; the guard must.
        tok = fake("ghp_")
        write(self.p("dir-" + tok[6:30], "f.txt"), tok)
        code, out, _ = run(["--root", self.tmp])
        self.assertNoLeak(out, [tok])
        self.assertEqual(lines(out, "finding"), [["finding", "[path withheld]", "classic", R.sha12(tok), "count=1",
                                                  "full", "len=40"]])

    def test_hash_paths_under(self):
        tok = fake("ghp_")
        data = self.p("hermes", "data")
        write(os.path.join(data, "clients", "1234567890", "run.log"), tok)
        os.symlink(os.path.join(data, "clients"), os.path.join(data, "link-9876543210"))
        argv = ["--root", data, "--root", os.path.join(data, "5555555555"), "--hash-paths-under", data + "/"]
        key = bytes(range(32))
        code, out, _ = run(argv, path_key=key)
        for cid in ("1234567890", "9876543210", "5555555555"):
            self.assertNotIn(cid, out)
        self.assertEqual(lines(out, "finding")[0][1], data + "/" + S.path_tag(key, "clients/1234567890/run.log"))
        self.assertEqual(lines(out, "skipped")[0][1], data + "/" + S.path_tag(key, "link-9876543210"))
        self.assertEqual(lines(out, "absent")[0][1], data + "/" + S.path_tag(key, "5555555555"))
        # Paths outside the prefix are printed as they are.
        write(self.p("other.txt"), tok)
        out2 = run(["--root", self.tmp, "--hash-paths-under", data])[1]
        self.assertIn(self.p("other.txt"), [l[1] for l in lines(out2, "finding")])


class TestKeyedPathTags(TempCase):
    """--hash-paths-under uses HMAC-SHA256 with a per-run random key: a bare sha12 of a
    10-digit customer ID is reversed by trying all 10^10 IDs."""

    def tags(self, out):
        return sorted(l[1] for l in lines(out, "finding"))

    def setUp(self):
        super().setUp()
        self.tok = fake("ghp_")
        for d in ("d1", "d2"):
            write(self.p(d, "clients", "1234567890", "run.log"), self.tok)
        self.argv = ["--root", self.tmp, "--hash-paths-under", self.p("d1"), "--hash-paths-under", self.p("d2")]

    def test_same_rest_same_tag_within_a_run(self):
        out = run(self.argv)[1]
        t1, t2 = self.tags(out)
        self.assertEqual(t1[len(self.p("d1")):], t2[len(self.p("d2")):])
        key = os.urandom(32)
        self.assertEqual(S.path_tag(key, "clients/1"), S.path_tag(key, "clients/1"))

    def test_different_runs_give_different_tags(self):
        a = self.tags(run(self.argv, path_key=b"\x01" * 32)[1])
        b = self.tags(run(self.argv, path_key=b"\x02" * 32)[1])
        self.assertNotEqual(a, b)
        # And with no key injected, each run makes its own.
        self.assertNotEqual(self.tags(run(self.argv)[1]), self.tags(run(self.argv)[1]))

    def test_default_key_is_32_random_bytes(self):
        with mock.patch.object(S.secrets, "token_bytes", return_value=b"\x07" * 32) as tb:
            out = run(self.argv)[1]
        tb.assert_called_once_with(32)
        self.assertEqual(self.tags(out)[0], self.p("d1") + "/" + S.path_tag(b"\x07" * 32, "clients/1234567890/run.log"))

    def test_tag_is_keyed_hmac_not_a_bare_hash(self):
        import hmac
        rest = "clients/1234567890/run.log"
        key = b"\x05" * 32
        tag = S.path_tag(key, rest)
        self.assertRegex(tag, r"^[0-9a-f]{12}$")
        self.assertEqual(tag, hmac.new(key, rest.encode(), hashlib.sha256).hexdigest()[:12])
        self.assertNotEqual(tag, R.sha12(rest))
        self.assertNotIn(tag, hashlib.sha1(rest.encode()).hexdigest())
        self.assertNotIn(tag, hashlib.sha256(rest.encode()).hexdigest())
        out = run(self.argv, path_key=key)[1]
        self.assertNotIn(R.sha12(rest), out)

    def test_the_key_never_appears_in_the_output(self):
        key = bytes(range(100, 132))
        code, out, err = run(self.argv + ["--try"], path_key=key,
                             http=FakeHttp({self.tok: (401, gh_json(message="Bad credentials"))}))
        text = out + err
        h = key.hex()
        for i in range(len(h) - 15):
            self.assertNotIn(h[i:i + 16], text)
        self.assertNotIn(key.decode("latin-1"), text)

    def test_token_fingerprints_stay_sha12(self):
        out = run(self.argv, path_key=b"\x09" * 32)[1]
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(self.tok)] * 2)


PRINTABLE_LINE = re.compile(r"^[\x20-\x7e\t]*$")


class TestEscaping(TempCase):
    NAMES = {"esc": "x\x1b[31mred\x1b[0m", "bel": "bell\x07", "ctl": "c\x01\x1f\x7fz",
             "nl": "two\nlines", "tab": "a\tb", "uni": "café-日本"}
    WANT = {"esc": "x\\x1b[31mred\\x1b[0m", "bel": "bell\\x07", "ctl": "c\\x01\\x1f\\x7fz",
            "nl": "two\\x0alines", "tab": "a\\x09b", "uni": "caf\\u00e9-\\u65e5\\u672c"}

    def assertPrintable(self, text):
        for line in text.splitlines():
            self.assertRegex(line, PRINTABLE_LINE)

    def test_file_names_print_as_escapes_only(self):
        toks = []
        for k, name in self.NAMES.items():
            toks.append(fake("ghp_"))
            write(self.p("f-" + name), toks[-1])
            os.symlink(self.p("f-" + name), self.p("l-" + name))
        argv = ["--root", self.tmp] + [x for n in self.NAMES.values() for x in ("--root", self.p("gone-" + n))]
        code, out, err = run(argv)
        self.assertPrintable(out + err)
        found = [l[1] for l in lines(out, "finding")]
        skipped = [l[1] for l in lines(out, "skipped")]
        absent = [l[1] for l in lines(out, "absent")]
        for k, want in self.WANT.items():
            with self.subTest(k=k):
                self.assertIn(self.p("f-" + want), found)
                self.assertIn(self.p("l-" + want), skipped)
                self.assertIn(self.p("gone-" + want), absent)
        self.assertNoLeak(out + err, toks)

    def test_the_unhashed_prefix_is_escaped_too(self):
        tok = fake("ghp_")
        data = self.p("da\x1bta")
        write(os.path.join(data, "123"), tok)
        out = run(["--root", self.tmp, "--hash-paths-under", data], path_key=b"\x01" * 32)[1]
        self.assertPrintable(out)
        self.assertEqual(lines(out, "finding")[0][1], self.p("da\\x1bta") + "/" + S.path_tag(b"\x01" * 32, "123"))

    def test_github_messages_are_escaped(self):
        tok = fake("ghp_")
        msg = "bad\x1b[2J\x07thingé\nend"
        self.assertEqual(S.try_token("classic", tok, FakeHttp({tok: (403, gh_json(message=msg))})),
                         "UNKNOWN 403 bad\\x1b[2J\\x07thing\\u00e9\\x0aend")
        long = "\x1b" * 100
        r = S.try_token("classic", tok, FakeHttp({tok: (403, gh_json(message=long))}))
        self.assertLessEqual(len(r) - len("UNKNOWN 403 "), 80)
        self.assertRegex(r, r"^UNKNOWN 403 (\\x1b)+$")

    def test_every_line_is_printable_ascii_with_try(self):
        tok = fake("gho_")
        write(self.p("f-\x1b]0;title\x07"), tok)
        http = FakeHttp({tok: (500, gh_json(message="\x1b[31mboom"))})
        code, out, err = run(["--root", self.tmp, "--try", "--root", self.p("\x1b[2J")], http=http)
        self.assertPrintable(out + err)
        self.assertIn("UNKNOWN 500 \\x1b[31mboom", out)

    def test_usage_errors_are_escaped(self):
        code, out, err = run(["--root", self.tmp, "--max-bytes", "\x1b[2J"])
        self.assertEqual(code, 2)
        self.assertPrintable(err)


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
        return tuple(a) + ({},) * (3 - len(a))   # (status, body, headers)


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


class TestPresetHashing(TempCase):
    """TS-R-1: the preset hashes the folders whose names can carry a customer ID by itself."""

    def test_preset_hashes_hermes_data_hermes_home_and_claude_projects(self):
        home, repo = self.p("home"), self.p("repo")
        pre = {"1234567890": os.path.join(repo, "infra", "hermes-agent", "data"),
               "2345678901": os.path.join(home, ".hermes"),
               "3456789012": os.path.join(home, ".claude", "projects")}
        rest = {"1234567890": ("clients", "1234567890", "run.log"),
                "2345678901": ("sessions", "2345678901.json"),
                "3456789012": ("-Users-x-Projects-client-3456789012", "s.jsonl")}
        toks = []
        for cid in pre:
            toks.append(fake("ghp_"))
            write(os.path.join(pre[cid], *rest[cid]), toks[-1])
        key = b"\x03" * 32
        code, out, _ = run(["--preset", "laptop"], home=home, repo_root=repo, path_key=key)
        for cid in pre:
            with self.subTest(cid=cid):
                self.assertNotIn(cid, out)
                self.assertIn(pre[cid] + "/" + S.path_tag(key, "/".join(rest[cid])),
                              [l[1] for l in lines(out, "finding")])
        self.assertNoLeak(out, toks)

    def test_preset_returns_its_hash_prefixes(self):
        home, repo = self.p("home"), self.p("repo")
        self.assertEqual(S.preset_laptop(home, repo)[3],
                         [os.path.join(repo, "infra", "hermes-agent", "data"), os.path.join(home, ".hermes"),
                          os.path.join(home, ".claude", "projects")])


class TestHashingThroughSymlinks(TempCase):
    """A hash prefix, or a root, reached through a symlink must still hide what is under it."""
    CID = "1234567890"

    def assertHidden(self, out):
        for line in out.splitlines():
            self.assertNotIn(self.CID, line)

    def test_a_symlinked_hermes_home_under_the_preset(self):
        home, repo = self.p("home"), self.p("repo")
        real = self.p("elsewhere", "hermes-real")
        tok = fake("ghp_")
        write(os.path.join(real, "clients", self.CID, "x"), tok)
        os.makedirs(home)
        os.symlink(real, os.path.join(home, ".hermes"))
        key = b"\x04" * 32
        out = run(["--preset", "laptop"], home=home, repo_root=repo, path_key=key)[1]
        self.assertHidden(out)
        self.assertEqual([l[1] for l in lines(out, "finding")],
                         [os.path.join(home, ".hermes") + "/" + S.path_tag(key, "clients/" + self.CID + "/x")])
        self.assertNoLeak(out, [tok])

    def test_a_symlinked_prefix_given_with_hash_paths_under(self):
        real, link = self.p("real-data"), self.p("link-data")
        tok = fake("ghp_")
        write(os.path.join(real, "clients", self.CID, "x"), tok)
        os.symlink(real, link)
        key = b"\x05" * 32
        want = link + "/" + S.path_tag(key, "clients/" + self.CID + "/x")
        for roots in (["--root", link], ["--root", real], ["--root", self.tmp]):
            with self.subTest(roots=roots[1][len(self.tmp):]):
                out = run(roots + ["--hash-paths-under", link], path_key=key)[1]
                self.assertHidden(out)
                self.assertEqual([l[1] for l in lines(out, "finding")], [want])

    def test_a_prefix_reached_through_a_symlinked_parent(self):
        preal, plink = self.p("preal"), self.p("plink")
        tok = fake("ghp_")
        write(os.path.join(preal, "data", self.CID, "x"), tok)
        os.symlink(preal, plink)
        key = b"\x06" * 32
        for root, prefix in ((os.path.join(preal, "data"), os.path.join(plink, "data")),
                             (os.path.join(plink, "data"), os.path.join(preal, "data")),
                             (os.path.join(plink, "data"), os.path.join(plink, "data"))):
            with self.subTest(root=root[len(self.tmp):], prefix=prefix[len(self.tmp):]):
                out = run(["--root", root, "--hash-paths-under", prefix], path_key=key)[1]
                self.assertHidden(out)
                self.assertEqual([l[1] for l in lines(out, "finding")],
                                 [prefix + "/" + S.path_tag(key, self.CID + "/x")])

    def test_the_resolved_line_does_not_reveal_the_hidden_part(self):
        data = self.p("data")
        target = self.p("outside", "client-" + self.CID)
        tok = fake("ghp_")
        write(os.path.join(target, "x"), tok)
        os.makedirs(data)
        os.symlink(target, os.path.join(data, "link"))
        key = b"\x07" * 32
        out = run(["--root", os.path.join(data, "link"), "--hash-paths-under", data], path_key=key)[1]
        self.assertHidden(out)
        resolved = lines(out, "resolved")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0][2], "(resolved from " + data + "/" + S.path_tag(key, "link") + ")")
        self.assertEqual([l[1] for l in lines(out, "finding")], [data + "/" + S.path_tag(key, "link/x")])


class TestHashingByIdentity(TempCase):
    """A prefix matches the same folder however the path is spelled (case, Unicode form)."""
    CID = "1234567890"

    def same_folder(self, a, b):
        try:
            return os.path.samefile(a, b)
        except OSError:
            return False

    def check(self, made, given_root, given_prefix):
        tok = fake("ghp_")
        write(os.path.join(made, "clients", self.CID, "x"), tok)
        key = b"\x08" * 32
        out = run(["--root", given_root, "--hash-paths-under", given_prefix], path_key=key)[1]
        for line in out.splitlines():
            self.assertNotIn(self.CID, line)
        found = [l[1] for l in lines(out, "finding")]
        self.assertEqual(len(found), 1)
        shown = S.printable(given_prefix)                                    # escaped, as every path is
        self.assertTrue(found[0].startswith(shown + "/"), found[0])           # shown as the owner gave it
        self.assertRegex(found[0][len(shown) + 1:], r"^[0-9a-f]{12}$")
        self.assertNoLeak(out, [tok])

    def test_a_case_difference_between_root_and_prefix(self):
        made = self.p("hermes-data")
        os.makedirs(made)
        upper = self.p("HERMES-DATA")
        if not self.same_folder(made, upper):
            self.skipTest("the temp volume is case-sensitive")
        self.check(made, upper, made)
        self.check(made, made, upper)

    def test_nfc_and_nfd_spellings(self):
        import unicodedata
        nfc = self.p(unicodedata.normalize("NFC", "café-data"))
        nfd = self.p(unicodedata.normalize("NFD", "café-data"))
        os.makedirs(nfc)
        if nfc == nfd or not self.same_folder(nfc, nfd):
            self.skipTest("the temp volume is normalisation-sensitive")
        self.check(nfc, nfd, nfc)
        self.check(nfc, nfc, nfd)

    def test_a_path_outside_every_prefix_is_shown_in_clear(self):
        tok = fake("ghp_")
        write(self.p("data", "clients", "x"), fake("gho_"))
        write(self.p("other", "notes", "f.txt"), tok)
        out = run(["--root", self.tmp, "--hash-paths-under", self.p("data")], path_key=b"\x09" * 32)[1]
        self.assertIn(self.p("other", "notes", "f.txt"), [l[1] for l in lines(out, "finding")])

    def test_a_missing_prefix_gets_a_note_and_is_still_hashed_by_spelling(self):
        tok = fake("ghp_")
        write(self.p("f"), tok)
        out = run(["--root", self.tmp, "--hash-paths-under", self.p("nope", self.CID)])[1]
        self.assertEqual(lines(out, "note"), [["note", "hash prefix not found: " + self.p("nope", self.CID)]])
        out = run(["--root", self.p("nope", self.CID, "deeper"), "--hash-paths-under", self.p("nope")])[1]
        self.assertEqual(lines(out, "absent")[0][1][:len(self.p("nope")) + 1], self.p("nope") + "/")
        self.assertNotIn(self.CID, "".join(l[1] for l in lines(out, "absent")))

    def test_the_stat_results_are_cached_per_folder(self):
        for i in range(30):
            write(self.p("big", "d", "f%d" % i), fake("ghp_"))
        calls = []
        real_stat = os.stat

        def counting(path, *a, **k):
            calls.append(str(path))
            return real_stat(path, *a, **k)
        os.makedirs(self.p("elsewhere"))               # exists, so identity matching runs
        with mock.patch.object(S.os, "stat", counting):
            out = run(["--root", self.p("big"), "--hash-paths-under", self.p("elsewhere")])[1]
        self.assertEqual(len(lines(out, "finding")), 30)
        self.assertEqual(calls.count(self.p("big", "d")), 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_the_prefix_folder_itself_under_another_spelling_is_shown_as_given(self):
        real, link = self.p("real-" + self.CID), self.p("link-data")
        os.makedirs(real)
        os.symlink(real, link)
        os.chmod(real, 0)
        out = run(["--root", real, "--hash-paths-under", link])[1]
        self.assertEqual(lines(out, "skipped"), [["skipped", link, "unreadable"]])
        self.assertNotIn(self.CID, out)


class TestUtf16(TempCase):
    """TS-R-2: Windows and Electron apps store strings as UTF-16."""

    def test_found_in_each_encoding_with_the_plain_text_fingerprint(self):
        for enc in ("utf-16-le", "utf-16-be", "utf-16"):
            for tok in (fake("ghp_"), fake("ghs_"), fake_fg()):
                with self.subTest(enc=enc, tok=tok[:4]):
                    data = b"\x00\x01" + ('{"k":"' + tok + '","x":"y"}').encode(enc) + b"\xff"
                    got = matches_in(data, S.CHUNK)
                    self.assertEqual([t for t, _ in got], [tok])
                    self.assertTrue(S.classify(got[0][0], got[0][1])[1])

    def test_a_token_character_after_keeps_a_utf16_token_partial(self):
        for enc in ("utf-16-le", "utf-16-be"):
            tok = fake("ghp_")
            got = matches_in((" " + tok + "_x ").encode(enc), S.CHUNK)
            with self.subTest(enc=enc):
                self.assertEqual([t for t, _ in got], [tok])
                self.assertFalse(S.classify(got[0][0], got[0][1])[1])

    def test_a_non_ascii_character_after_is_not_a_token_character(self):
        # U+0141 is 0x41 0x01 in UTF-16LE: its low byte is "A", but the character is not ASCII.
        for enc in ("utf-16-le", "utf-16-be"):
            for before in (" ", "x ", "Ł", "Ł "):
                for tok in (fake("ghp_"), fake_fg()):
                    got = matches_in((before + tok + "Ł ").encode(enc), S.CHUNK)
                    with self.subTest(enc=enc, before=before, tok=tok[:4]):
                        self.assertEqual([t for t, _ in got], [tok])
                        self.assertTrue(S.classify(got[0][0], got[0][1])[1])

    def test_a_utf16le_partial_next_to_a_non_ascii_character_keeps_its_own_text(self):
        part = fake("ghp_", 46)          # 50 characters: a partial in either reading
        got = matches_in(("x " + part + "Ł ").encode("utf-16-le"), S.CHUNK)
        self.assertEqual([t for t, _ in got], [part])

    def test_across_chunk_boundaries_once(self):
        for enc in ("utf-16-le", "utf-16-be"):
            for tok in (fake("ghs_"), fake_fg()):
                for chunk in (64, 200):
                    for off in range(0, 2 * chunk + 3):
                        data = b"\x01" * off + (" " + tok + " ").encode(enc)
                        with self.subTest(enc=enc, tok=tok[:4], chunk=chunk, off=off):
                            got = matches_in(data, chunk)
                            self.assertEqual([t for t, _ in got], [tok])
                            self.assertTrue(S.classify(got[0][0], got[0][1])[1])

    def test_same_token_in_three_encodings_is_one_token_with_no_double_count(self):
        tok = fake("gho_")
        write(self.p("plain.txt"), " " + tok + " ")
        write(self.p("le.dat"), (" " + tok + " ").encode("utf-16-le"))
        write(self.p("be.dat"), (" " + tok + " ").encode("utf-16-be"))
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(sorted(lines(out, "finding")), sorted(
            [["finding", self.p(n), "oauth", R.sha12(tok), "count=1", "full", "len=40"]
             for n in ("plain.txt", "le.dat", "be.dat")]))
        self.assertEqual(lines(out, "token"), [["token", R.sha12(tok), "oauth", "files=3", "full", "len=40"]])

    def test_the_guard_covers_the_decoded_value(self):
        tok = fake("ghp_")
        write(self.p("d-" + tok[5:20], "x.dat"), (" " + tok + " ").encode("utf-16-le"))
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual(lines(out, "finding")[0][1], "[path withheld]")
        self.assertNoLeak(out, [tok])


class TestBasicAuth(TempCase):
    """TS-R-3: git's extraheader and HTTP traces carry tokens as Basic base64(user:token)."""

    def test_x_access_token_in_a_basic_header_is_decoded_and_tried(self):
        import base64
        ghs = fake("ghs_")
        b64 = base64.b64encode(("x-access-token:" + ghs).encode()).decode()
        write(self.p("repo", ".git", "config"), "[http]\n\textraheader = AUTHORIZATION: basic " + b64 + "\n")
        http = FakeHttp({ghs: (401, gh_json(message="Bad credentials"))})
        code, out, err = run(["--root", self.tmp, "--try"], http=http)
        self.assertEqual(lines(out, "finding"), [["finding", self.p("repo", ".git", "config"), "installation",
                                                  R.sha12(ghs), "count=1", "full", "len=40"]])
        self.assertEqual(http.calls, [(INST, ghs)])
        self.assertNoLeak(out + err, [ghs, b64])

    def test_basic_header_in_a_trace_with_a_classic_token(self):
        import base64
        tok = fake("ghp_")
        b64 = base64.b64encode(("someone:" + tok).encode()).decode()
        write(self.p("trace.log"), "> GET / HTTP/1.1\r\n> Authorization: Basic " + b64 + "\r\n")
        code, out, _ = run(["--root", self.tmp])
        self.assertEqual([(l[2], l[3], l[5]) for l in lines(out, "finding")], [("classic", R.sha12(tok), "full")])

    def test_basic_header_without_a_token_is_nothing(self):
        import base64
        write(self.p("t"), "Authorization: Basic " + base64.b64encode(b"user:password123").decode())
        self.assertEqual(lines(run(["--root", self.tmp])[1], "finding"), [])


class TestLongMatches(TempCase):
    """TS-R-4: a match is capped at 256 characters."""

    def test_a_match_over_256_is_a_partial_fingerprinted_on_its_first_256(self):
        for tok, kind in (("ghp_" + rnd(1000), "classic"), ("github_pat_" + rnd(300), "fine-grained")):
            with self.subTest(kind=kind):
                with open(self.p("f"), "w") as f:
                    f.write(" " + tok + " ")
                out = run(["--root", self.p("f")])[1]
                self.assertEqual(lines(out, "finding"), [["finding", self.p("f"), kind, R.sha12(tok[:256]),
                                                          "count=1", "partial", "len>256"]])
                self.assertNoLeak(out, [tok])

    def test_exactly_256_is_len_256(self):
        tok = "ghp_" + rnd(252)
        write(self.p("f"), " " + tok + " ")
        self.assertEqual(lines(run(["--root", self.tmp])[1], "finding")[0][6], "len=256")

    def test_guard_windows_come_from_the_first_256_only(self):
        tok = "ghp_" + rnd(5000)
        write(self.p("f"), tok)
        res = S.Scan()
        S.scan_path(self.p("f"), S.DEFAULT_MAX_BYTES, res)
        self.assertEqual(res.secrets, {tok[:256]})

    def test_a_long_run_does_not_hide_a_token_after_it(self):
        tok = fake("gho_")
        for enc in ("ascii", "utf-16-le"):
            with self.subTest(enc=enc):
                data = ("ghp_" + "Ab1" * 3000 + " " + tok + " ").encode(enc)
                got = [(t, l) for t, _, l in S.iter_matches(io.BytesIO(data), 64)]
                self.assertEqual(got, [(("ghp_" + "Ab1" * 3000)[:256], True), (tok, False)])

    def test_a_token_shape_inside_a_long_fine_grained_run_is_not_a_second_match(self):
        # The rest of a long run is consumed whole, in the same buffer and across buffers, so a
        # ghp_ shape inside a long github_pat_ run is never reported on its own.
        for enc in ("ascii", "utf-16-le"):
            for inner_at in (20, 300, 3000):
                run_ = "github_pat_" + "x" * inner_at + "_ghp_" + rnd(36) + "_" + "y" * 400
                data = (" " + run_ + " ").encode(enc)
                for chunk in (64, 4096):
                    with self.subTest(enc=enc, inner_at=inner_at, chunk=chunk):
                        got = [(t, l) for t, _, l in S.iter_matches(io.BytesIO(data), chunk)]
                        self.assertEqual(got, [(run_[:256], True)])

    def test_a_long_run_is_bounded_in_time_and_memory(self):
        import time, tracemalloc
        for enc, data in (("plain", b"ghp_" + b"A" * (4 << 20) + b" "),
                          ("utf-16-le", ("ghp_" + "A" * (2 << 20) + " ").encode("utf-16-le"))):
            with self.subTest(enc=enc):
                f = io.BytesIO(data)
                tracemalloc.start()
                t0 = time.monotonic()
                try:
                    got = list(S.iter_matches(f, 4096))
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertEqual([(len(t), l) for t, _, l in got], [(256, True)])
                self.assertLess(peak, 256 * 1024)
                self.assertLess(time.monotonic() - t0, 20)


class TestGuardDetails(TempCase):
    """TS-R-5 and TS-R-10: the guard, column by column."""

    def row(self, path):
        return ["finding", path, "classic", "0123456789ab", "count=1", "full", "len=40"]

    def test_the_last_and_first_windows_are_covered(self):
        tok = fake("ghp_")
        for piece in (tok[-8:], tok[:8]):
            with self.subTest(piece=piece[:3]):
                self.assertEqual(S.guard([self.row("/x/" + piece + "/f")], {tok}),
                                 [["finding", "[path withheld]"] + self.row("")[2:]])

    def test_windows_of_one_repeated_character_are_ignored(self):
        tok = "ghp_" + "A" * 20 + rnd(16)
        r = self.row("/backup/AAAAAAAAAAAA/f")
        self.assertEqual(S.guard([r], {tok}), [r])

    def test_a_column_other_than_the_path_is_withheld_as_such(self):
        tok = fake("ghp_")
        r = ["try", "0123456789ab", "classic", "UNKNOWN 403 " + tok[10:20]]
        self.assertEqual(S.guard([r], {tok}), [["try", "0123456789ab", "classic", "[withheld]"]])

    def test_partials_are_in_the_guard_set(self):
        part = fake("ghp_", 25)
        write(self.p("d-" + part[6:20], "f"), part)
        out = run(["--root", self.tmp])[1]
        self.assertEqual(lines(out, "finding")[0][1], "[path withheld]")
        self.assertNoLeak(out, [part])


class TestWalkDetails(TempCase):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_an_unreadable_root_is_reported(self):
        write(self.p("locked", "child", "f"), "x")
        os.chmod(self.p("locked"), 0)
        code, out, _ = run(["--root", self.p("locked", "child")])
        self.assertEqual(lines(out, "skipped"), [["skipped", self.p("locked", "child"), "unreadable"]])
        self.assertEqual(lines(out, "absent"), [])

    def test_git_config_search_is_not_any_file_named_config(self):
        home, repo = self.p("home"), self.p("repo")
        a, b, c = fake("ghp_"), fake("ghp_"), fake("ghp_")
        write(os.path.join(home, "Projects", "app", "config"), a)
        write(os.path.join(home, "Projects", "app", "src", "config"), b)
        write(os.path.join(home, "Projects", "app", ".git", "modules", "vendor", "lib", "config"), c)
        out = run(["--preset", "laptop"], home=home, repo_root=repo)[1]
        found = {l[3] for l in lines(out, "finding")}
        self.assertNotIn(R.sha12(a), found)
        self.assertNotIn(R.sha12(b), found)
        self.assertIn(R.sha12(c), found)          # TS-R-12: submodule remotes

    def test_submodule_config_is_found(self):
        home, repo = self.p("home"), self.p("repo")
        tok = fake("ghp_")
        write(os.path.join(home, "Projects", "app", ".git", "modules", "sub", "config"), "url=https://x:" + tok + "@github.com")
        write(os.path.join(home, "Projects", "app", ".git", "modules", "sub", "description"), fake("ghp_"))
        out = run(["--preset", "laptop"], home=home, repo_root=repo)[1]
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(tok)])

    def test_redact_applies_to_hashed_paths(self):
        name_tok, tok = fake("gho_"), fake("ghp_")
        data = self.p("data-" + name_tok)
        write(os.path.join(data, "123", "f"), tok)
        code, out, err = run(["--root", self.tmp, "--hash-paths-under", data])
        self.assertNoLeak(out + err, [name_tok, tok])
        self.assertEqual(len(lines(out, "finding")), 1)

    def test_an_undecodable_file_name_byte_prints_as_that_byte(self):
        # Platform-independent: os.fsdecode turns byte 0xff into U+DCFF (surrogateescape).
        self.assertEqual(S.printable(os.fsdecode(b"f-\xff")), "f-\\xff")
        self.assertEqual(S.printable("f-\udc80"), "f-\\x80")

    def test_a_symlink_found_by_the_preset_name_search_is_skipped_not_resolved(self):
        home, repo = self.p("home"), self.p("repo")
        tok = fake("ghp_")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        write(os.path.join(outside.name, "real.env"), "T=" + tok)
        os.makedirs(os.path.join(home, "app"))
        os.symlink(os.path.join(outside.name, "real.env"), os.path.join(home, "app", ".env"))
        out = run(["--preset", "laptop"], home=home, repo_root=repo)[1]
        self.assertEqual(lines(out, "finding"), [])
        self.assertIn(["skipped", os.path.join(home, "app", ".env"), "symlink"], lines(out, "skipped"))
        self.assertEqual(lines(out, "resolved"), [])

    @unittest.skipIf(sys.platform == "darwin", "APFS refuses file names that are not UTF-8")
    def test_a_non_utf8_file_name_prints_its_byte_escaped(self):
        tok = fake("ghp_")
        with open(os.path.join(os.fsencode(self.tmp), b"f-\xff"), "wb") as f:
            f.write(tok.encode())
        out = run(["--root", self.tmp])[1]
        self.assertEqual([l[1] for l in lines(out, "finding")], [self.p("f-\\xff")])

    def test_top_level_symlink_root_is_resolved_once(self):
        tok, inner = fake("ghp_"), fake("gho_")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = os.path.realpath(outside.name)
        write(os.path.join(target, "f.txt"), tok)
        write(self.p("elsewhere", "g.txt"), inner)
        os.symlink(self.p("elsewhere"), os.path.join(target, "inner-link"))
        os.symlink(target, self.p("root-link"))
        os.symlink(os.path.join(target, "f.txt"), self.p("file-link"))
        os.symlink(self.p("nowhere"), self.p("dangling"))
        code, out, _ = run(["--root", self.p("root-link"), "--root", self.p("file-link"), "--root", self.p("dangling")])
        # Shown under the root the owner gave; the most specific root wins (file-link names the file).
        self.assertEqual(lines(out, "finding"), [["finding", self.p("file-link"), "classic", R.sha12(tok),
                                                  "count=1", "full", "len=40"]])
        self.assertEqual(sorted(lines(out, "resolved")), sorted([
            ["resolved", target, "(resolved from " + self.p("root-link") + ")"],
            ["resolved", os.path.join(target, "f.txt"), "(resolved from " + self.p("file-link") + ")"]]))
        self.assertEqual(sorted(lines(out, "skipped")), sorted([
            ["skipped", self.p("root-link", "inner-link"), "symlink"],
            ["skipped", self.p("dangling"), "symlink"]]))

    def test_dataless_files_are_skipped_without_being_opened(self):
        a, b = fake("ghp_"), fake("gho_")
        write(self.p("cloud.txt"), a)
        write(self.p("local.txt"), b)
        real_lstat, real_open, opened = os.lstat, os.open, []

        class FakeStat:
            def __init__(self, st):
                self._st, self.st_flags = st, 0x40000000

            def __getattr__(self, name):
                return getattr(self._st, name)

        def fake_lstat(path, *a, **k):
            st = real_lstat(path, *a, **k)
            return FakeStat(st) if str(path).endswith("cloud.txt") else st

        def spy_open(path, flags, *a, **k):
            opened.append((str(path), flags))
            return real_open(path, flags, *a, **k)
        with mock.patch.object(S.os, "lstat", fake_lstat), mock.patch.object(S.os, "open", spy_open):
            code, out, _ = run(["--root", self.tmp])
        self.assertEqual(lines(out, "skipped"), [["skipped", self.p("cloud.txt"), "dataless"]])
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(b)])
        self.assertNotIn(self.p("cloud.txt"), [p for p, _ in opened])
        # TS-R-12: files are opened with O_NOFOLLOW, then checked with fstat.
        self.assertTrue(all(fl & os.O_NOFOLLOW for p, fl in opened if p == self.p("local.txt")))
        self.assertIn(self.p("local.txt"), [p for p, _ in opened])

    def test_a_symlink_swapped_in_after_the_walk_is_not_followed(self):
        tok = fake("ghp_")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        write(os.path.join(outside.name, "s"), tok)
        write(self.p("f"), "x")
        res = S.Scan()
        os.remove(self.p("f"))
        os.symlink(os.path.join(outside.name, "s"), self.p("f"))
        S.scan_file(self.p("f"), S.DEFAULT_MAX_BYTES, res)
        self.assertEqual(res.counts, {})
        self.assertEqual(res.skipped, {self.p("f"): "symlink"})

    def test_a_file_of_exactly_max_bytes_is_scanned(self):
        tok = fake("ghp_")
        write(self.p("f"), tok)
        out = run(["--root", self.tmp, "--max-bytes", str(len(tok))])[1]
        self.assertEqual(len(lines(out, "finding")), 1)


class TestPruned(TempCase):
    """TS-R-8: folders the .env* name search does not enter are listed."""

    def test_pruned_lines_and_totals(self):
        home, repo = self.p("home"), self.p("repo")
        os.makedirs(os.path.join(home, "Library"))
        os.makedirs(os.path.join(home, "Pictures"))
        out = run(["--preset", "laptop"], home=home, repo_root=repo)[1]
        self.assertEqual(lines(out, "pruned"), [
            ["pruned", os.path.join(home, "Library"), "not searched for .env* names"],
            ["pruned", os.path.join(home, "Pictures"), "not searched for .env* names"]])
        self.assertIn("pruned=2", lines(out, "totals")[0])


class TestNotes(TempCase):
    def test_partials_get_a_check_line(self):
        write(self.p("f"), fake("ghp_", 25))
        out = run(["--root", self.tmp])[1]
        self.assertEqual(lines(out, "note"), [["note", "partials found: check the partials one by one; "
                                               "they are never tried"]])
        write(self.p("f"), fake("ghp_"))
        self.assertEqual(lines(run(["--root", self.tmp])[1], "note"), [])

    def test_proxy_and_ca_variables_get_one_notice_names_only(self):
        write(self.p("f"), "x")
        env = {"HTTPS_PROXY": "http://u:s3cr3t@proxy.example:1", "no_proxy": "localhost",
               "SSL_CERT_FILE": "/tmp/evil-ca.pem", "PATH": "/bin"}
        out = run(["--root", self.tmp], environ=env)[1]
        notices = lines(out, "notice")
        self.assertEqual(len(notices), 1)
        for name in ("HTTPS_PROXY", "no_proxy", "SSL_CERT_FILE"):
            self.assertIn(name, notices[0][1])
        for value in ("s3cr3t", "proxy.example", "evil-ca", "localhost", "PATH"):
            self.assertNotIn(value, out)
        self.assertEqual(lines(run(["--root", self.tmp], environ={"PATH": "/bin"})[1], "notice"), [])


class TestLoginCheck(LeakMixin, unittest.TestCase):
    def test_a_login_holding_token_text_is_not_printed(self):
        tok = fake("ghp_")
        r = S.try_token("classic", tok, FakeHttp({tok: (200, gh_json(login=tok[4:24]))}))
        self.assertEqual(r, "ALIVE login=?")


class TestDefaultHttp(LeakMixin, unittest.TestCase):
    """The real seam, exercised against a fake opener: no socket is ever opened."""

    class Opener:
        def __init__(self, answer, headers=None):
            self.answer, self.headers, self.reqs, self.reads = answer, headers or {}, [], []

        def open(self, req, timeout=None):
            self.reqs.append((req, timeout))
            if isinstance(self.answer, BaseException):
                raise self.answer
            outer = self

            class Resp(io.BytesIO):
                status = 200
                headers = outer.headers

                def read(self, n=-1):
                    outer.reads.append(n)
                    return super().read(n)
            return Resp(self.answer)

    def test_bearer_header_in_memory_and_get(self):
        tok = fake("ghp_")
        op = self.Opener(b'{"login":"x"}', {"X-RateLimit-Remaining": "59"})
        self.assertEqual(S.github_get(USER, tok, opener=op), (200, b'{"login":"x"}', {"x-ratelimit-remaining": "59"}))
        req, timeout = op.reqs[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, USER)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + tok)

    def test_timeout_and_body_read_are_bounded(self):
        op = self.Opener(b"x" * 10)
        S.github_get(USER, "t", opener=op)
        self.assertEqual(op.reqs[0][1], S.HTTP_TIMEOUT)
        self.assertLessEqual(S.HTTP_TIMEOUT, 60)
        self.assertEqual(op.reads, [S.MAX_BODY])
        self.assertLessEqual(S.MAX_BODY, 1 << 20)

    def test_http_error_is_an_answer_with_a_bounded_read(self):
        import urllib.error
        reads = []

        class Body(io.BytesIO):
            def read(self, n=-1):
                reads.append(n)
                return super().read(n)
        err = urllib.error.HTTPError(USER, 401, "Unauthorized", {"Retry-After": "60"},
                                     Body(b'{"message":"Bad credentials"}'))
        self.assertEqual(S.github_get(USER, "t", opener=self.Opener(err)),
                         (401, b'{"message":"Bad credentials"}', {"retry-after": "60"}))
        self.assertEqual(reads, [S.MAX_BODY])

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

    def test_proxy_map_is_empty_even_with_proxy_variables_set(self):
        import urllib.request
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
                                          "ALL_PROXY": "socks5://127.0.0.1:9"}):
            op = S._opener()
            control = urllib.request.build_opener()
        proxies = lambda o: [h.proxies for h in o.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies]
        # An empty ProxyHandler({}) has no *_open methods, so the opener does not even keep it;
        # passing it is what stops build_opener from adding the default, environment-reading one.
        self.assertEqual(proxies(op), [])
        self.assertNotEqual(proxies(control), [])     # the control: a default opener would use them


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
        for answer in ((200, gh_json(login="someone")), (403, gh_json(message="forbidden " + tok)),
                       urllib.error.URLError(tok)):
            with self.subTest(answer=type(answer).__name__):
                code, out, err = run(["--root", self.tmp, "--try"], http=FakeHttp({tok: answer}))
                self.assertEqual(code, 1)
                self.assertEqual(len(lines(out, "try")), 1)
                self.assertNoLeak(out + err, [tok])

    def test_a_programming_error_in_the_seam_is_an_internal_error_not_a_network_error(self):
        tok = fake("ghp_")
        write(self.p("f"), tok)

        def boom(url, token):
            raise RuntimeError("boom " + token)
        code, out, err = run(["--root", self.tmp, "--try"], http=boom)
        self.assertEqual(code, 3)
        self.assertNotIn("network-error", out)
        self.assertIn("RuntimeError", out + err)
        self.assertNoLeak(out + err, [tok])

    def test_an_internal_error_still_prints_the_report_gathered_so_far_and_exits_3(self):
        tok, other = fake("ghp_"), fake("gho_")
        write(self.p("f"), tok + " " + other)
        for exc in (RuntimeError("boom " + tok), MemoryError()):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(S, "try_token", side_effect=exc):
                    code, out, err = run(["--root", self.tmp, "--try"])
                self.assertEqual(code, 3)
                self.assertEqual(len(lines(out, "finding")), 2)
                self.assertEqual(lines(out, "error"), [["error", "internal error " + type(exc).__name__ +
                                                        "; this report is incomplete"]])
                self.assertNoLeak(out + err, [tok, other])

    def test_an_error_in_one_file_skips_it_and_the_run_continues_with_exit_3(self):
        bad, good = fake("ghp_"), fake("gho_")
        write(self.p("a-bad"), bad)
        write(self.p("b-good"), good)
        real, calls = S.iter_matches, []

        def flaky(f, chunk_size=S.CHUNK):      # files are scanned in name order: a-bad first
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("inside " + bad)
            return real(f, chunk_size)
        with mock.patch.object(S, "iter_matches", side_effect=flaky):
            code, out, err = run(["--root", self.tmp])
        self.assertEqual(code, 3)
        self.assertEqual([l[3] for l in lines(out, "finding")], [R.sha12(good)])
        self.assertIn(["skipped", self.p("a-bad"), "error RuntimeError"], lines(out, "skipped"))
        self.assertNoLeak(out + err, [bad, good])


class TestRateLimit(TempCase):
    IP = "203.0.113.9"

    def toks(self):
        t = sorted([fake("ghp_"), fake("gho_"), fake("ghu_"), fake("ghr_")], key=R.sha12)
        write(self.p("f"), " ".join(t))
        return t

    def check(self, limited_answer):
        t = self.toks()
        answers = {x: (401, gh_json(message="Bad credentials")) for x in t}
        first = [x for x in t if not x.startswith("ghr_")][0]
        answers[first] = limited_answer
        http = FakeHttp(answers)
        code, out, err = run(["--root", self.tmp, "--try"], http=http)
        self.assertEqual([c[1] for c in http.calls], [first])          # stopped after the first
        results = {l[1]: l[3] for l in lines(out, "try")}
        self.assertEqual(results[R.sha12(first)], S.RATE_LIMITED)
        for x in t:
            if x == first:
                continue
            want = S.REFRESH if x.startswith("ghr_") else "UNKNOWN not-tried (rate limited)"
            self.assertEqual(results[R.sha12(x)], want)
        self.assertNotIn(self.IP, out + err)
        self.assertEqual(code, 1)
        self.assertNoLeak(out + err, t)

    def test_403_with_no_remaining_requests(self):
        self.check((403, gh_json(message="API rate limit exceeded for " + self.IP), {"x-ratelimit-remaining": "0"}))

    def test_429_with_retry_after(self):
        self.check((429, gh_json(message="Too many requests from " + self.IP), {"retry-after": "60"}))

    def test_a_plain_403_is_not_a_rate_limit(self):
        tok = fake("ghp_")
        r = S.try_token("classic", tok, FakeHttp({tok: (403, gh_json(message="Forbidden"), {"x-ratelimit-remaining": "12"})}))
        self.assertEqual(r, "UNKNOWN 403 Forbidden")


class TestDocstring(unittest.TestCase):
    def test_exit_codes_and_owner_section_are_documented(self):
        doc = S.__doc__
        for want in ("EXIT CODES", "0 ", "1 ", "2 ", "3 ", "HOW THE OWNER RUNS IT", "agents closed",
                     "fingerprints only", "safe to paste", "NOT COVERED", "exit 0 does not mean",
                     "Mobile Documents", "~/.claude/projects"):
            with self.subTest(want=want):
                self.assertIn(want, doc)

    def test_the_recipe_comes_first(self):
        head = S.__doc__[:1600]
        for want in ("repo root", "every agent closed", "--preset laptop", "stdout only", "echo $?",
                     "change between runs", "do not paste", "--root"):
            with self.subTest(want=want):
                self.assertIn(want, head)


if __name__ == "__main__":
    unittest.main()
