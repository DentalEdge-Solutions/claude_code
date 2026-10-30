#!/usr/bin/env python3
"""Find GitHub tokens lying in files, and print fingerprints only (P0-10 step 3, P5 and P15).

WHY THIS EXISTS
    Step 3 measures where GitHub tokens are lying around (transcripts, histories, configs,
    .env files, app data) on the laptop and on the box, and proves each one dead or alive.
    The output is pasted back into an agent session, so it NEVER holds a token value: each
    token is shown as its sha12 fingerprint (first 12 hex of sha1 over the bare value,
    review_lib.sha12, the repo's credential convention).

WHAT IT DOES
    Walks every --root (file or folder) recursively, read-only, never following a symlink,
    and reads every regular file as BYTES (binary, leveldb and sqlite files included), in
    chunks with an overlap so a token across a chunk boundary is found exactly once. The
    patterns are the repo's own (scripts/telemetry/secret-patterns.js, pinned by a test).

    A match is FULL when it has the exact shape (gh[pousr]_ + 36 alphanumerics = 40
    characters; github_pat_ + 22 + "_" + 59 = 93 characters) and the character right AFTER it
    is not a token character [A-Za-z0-9_]. There is no condition on the character BEFORE it:
    JSONL transcripts escape a newline as "\\n", so a token at the start of a line sits right
    after an "n" and must still count as full (decision of 2026-10-30). Any other match is
    PARTIAL: it is listed with its type, fingerprint and length for the owner to judge, and
    never tried.

    --preset laptop expands to the include list of the step-3 plan (§3), plus every
    .git/config under ~/Projects and ~/Documents and every .env* file under the home folder.
    The .env* name search does not enter ~/Library, ~/Pictures, ~/Music, ~/Movies or ~/.Trash
    (app data and media libraries; walking them raises macOS privacy prompts). Paths that do
    not exist are listed as absent.

    Types: classic (ghp_), oauth (gho_), user-to-server (ghu_), installation (ghs_),
    refresh (ghr_), fine-grained (github_pat_).

    --try sends, for each distinct FULL token, at most one GET to https://api.github.com,
    sequentially, with the token in an in-memory Authorization header (never on a command
    line; redirects are refused so the header cannot travel elsewhere):
        classic, oauth, user-to-server, fine-grained: GET /user
        installation: GET /installation/repositories
        refresh: no request; "CANNOT BE PROVED BY USE (refresh token)"
    Without --try there is no network access at all.

OUTPUT (stdout, tab-separated, sorted within each section)
    finding  <path> <type> <sha12> count=<n> full|partial len=<n>
    token    <sha12> <type> files=<n> full|partial len=<n>        (across files)
    try      <sha12> <type> ALIVE login=<login> | ALIVE total_count=<n> |
             DEAD (Bad credentials, 401) | DEAD (401) | UNKNOWN <code> <message> |
             UNKNOWN network-error <class> | CANNOT BE PROVED BY USE (refresh token)
    skipped  <path> symlink|size|unreadable|not-a-regular-file
    absent   <path>
    totals   files_scanned= findings= full_tokens= partial_tokens= skipped= absent=
    --hash-paths-under PREFIX prints a path under PREFIX as PREFIX/<sha12 of the rest>, for
    folders whose file names hold customer IDs (the Hermes data folders). Token-like text in a
    path is replaced, and a final guard withholds any line holding 8 or more consecutive
    characters of any matched text.

EXIT CODES
    0  no full-shape token found, or (with --try) every full-shape token proved DEAD
    1  a full-shape token found without --try; or with --try any token ALIVE, UNKNOWN or
       CANNOT BE PROVED (refresh); or an unexpected internal error (class name on stderr)
    2  usage error (no --root and no --preset, a bad value); nothing is scanned

HOW THE OWNER RUNS IT
    Run it yourself in your own Terminal, with all agents closed (Claude and every other
    agent app), because it reads files that may hold live secrets. It prints fingerprints
    only, never a token value, so its output is safe to paste back into a session. Run it
    first without --try, then with --try. Examples:
        python3 infra/hermes-agent/bin/scan-github-tokens.py --preset laptop \\
            --hash-paths-under ~/Projects/claude_code/infra/hermes-agent/data \\
            --hash-paths-under ~/.hermes --try
        python3 scan-github-tokens.py --root ~ --root <hermes install> --hash-paths-under <hermes data>
    Missing paths are listed as absent; there are no default roots. If a token is ALIVE and
    it is yours, revoke it in the browser at once, then re-run with --try.
"""
import argparse, json, os, re, stat, sys, urllib.parse, urllib.request, urllib.error
from http.client import HTTPException
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

# The one pattern source is scripts/telemetry/secret-patterns.js:22-23. Python cannot import it,
# so the two bodies are copied here and pinned by a parity test in scan-github-tokens.test.py.
GH_TOKEN_PATTERN = r"gh[pousr]_[A-Za-z0-9]{20,}"
GH_PAT_PATTERN = r"github_pat_[A-Za-z0-9_]{20,}"
GH_TOKEN_RE = re.compile(GH_TOKEN_PATTERN.encode())
GH_PAT_RE = re.compile(GH_PAT_PATTERN.encode())

TYPES = {b"ghp_": "classic", b"gho_": "oauth", b"ghu_": "user-to-server",
         b"ghs_": "installation", b"ghr_": "refresh"}
FULL_GH_RE = re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}")
FULL_PAT_RE = re.compile(rb"github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}")
TOKEN_CHAR_RE = re.compile(rb"[A-Za-z0-9_]")

CHUNK = 1 << 20          # bytes read at a time
OVERLAP = 128            # bytes kept from the previous chunk; longer than any pattern's prefix + minimum


def classify(match, after):
    """(type label, full) for one match. `after` is the single byte right after it (b"" at
    the end of a file). Full = the exact shape AND no token character right after it; anything
    else is a partial, never tried. There is deliberately no condition on the byte BEFORE:
    JSONL escapes a newline as "\\n", so a token at the start of a line sits right after an
    "n" (decision of 2026-10-30)."""
    kind = "fine-grained" if match.startswith(b"github_pat_") else TYPES[match[:4]]
    shape = FULL_PAT_RE if kind == "fine-grained" else FULL_GH_RE
    full = shape.fullmatch(match) is not None and not (after and TOKEN_CHAR_RE.fullmatch(after))
    return kind, full


def _find(buf, start):
    """Pattern matches in buf from `start`, sorted, with a gh*_ match that starts inside a
    github_pat_ match dropped (it is part of that token, not a second one)."""
    pats = [m.span() for m in GH_PAT_RE.finditer(buf, start)]
    ghs = [m.span() for m in GH_TOKEN_RE.finditer(buf, start)
           if not any(a <= m.start() < b for a, b in pats)]
    return sorted(pats + ghs)


def iter_matches(f, chunk_size=CHUNK):
    """Yield (match bytes, byte after) for every match in a binary stream, each exactly once.
    Reads in chunks; a match that touches the end of the buffer, or starts in its last OVERLAP
    bytes, is carried into the next round with everything after it. A match that was yielded
    is never carried, so it cannot be found twice."""
    carry = b""
    while True:
        chunk = f.read(chunk_size)
        buf = carry + chunk
        eof = not chunk
        safe_end = len(buf) - OVERLAP
        next_start = None
        last_end = 0
        for a, b in _find(buf, 0):
            if not eof and (b >= len(buf) or a >= safe_end):
                next_start = a
                break
            yield buf[a:b], buf[b:b + 1]
            last_end = b
        if eof:
            return
        if next_start is None:
            next_start = max(safe_end, last_end, 0)
        carry = buf[next_start:]


# ---- walking -------------------------------------------------------------------------------

class Scan:
    def __init__(self):
        self.counts = {}      # (path, kind, sha12, full, length) -> count in that file
        self.values = {}      # sha12 -> (kind, value) for full-shape tokens; memory only
        self.secrets = set()  # every matched text, full or partial, for the output guard
        self.skipped = {}     # path -> reason
        self.absent = set()
        self.seen = set()     # files already scanned, so overlapping roots count once
        self.files_scanned = 0


def scan_file(path, st, max_bytes, res, chunk_size=CHUNK):
    if st.st_size > max_bytes:
        res.skipped[path] = "size"
        return
    try:
        with open(path, "rb") as f:
            found = list(iter_matches(f, chunk_size))
    except OSError:
        res.skipped[path] = "unreadable"
        return
    res.files_scanned += 1
    for m, after in found:
        kind, full = classify(m, after)
        text = m.decode("ascii")
        fp = R.sha12(text)
        res.secrets.add(text)
        if full:
            res.values[fp] = (kind, text)
        key = (path, kind, fp, full, len(m))
        res.counts[key] = res.counts.get(key, 0) + 1


def scan_path(root, max_bytes, res, chunk_size=CHUNK):
    """Scan one root, file or folder, read-only, never following a symlink. Iterative, so a
    deep tree cannot exhaust Python's recursion limit and abort the run."""
    stack = [(root, True)]
    while stack:
        path, is_root = stack.pop()
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            if is_root:
                res.absent.add(path)
            continue            # a file that vanished mid-walk is not "absent" from the list
        except OSError:
            res.skipped[path] = "unreadable"
            continue
        if stat.S_ISLNK(st.st_mode):
            res.skipped[path] = "symlink"
        elif stat.S_ISDIR(st.st_mode):
            try:
                with os.scandir(path) as it:
                    names = [e.name for e in it]
            except OSError:
                res.skipped[path] = "unreadable"
                continue
            stack += [(os.path.join(path, n), False) for n in sorted(names, reverse=True)]
        elif not stat.S_ISREG(st.st_mode):
            res.skipped[path] = "not-a-regular-file"
        elif path not in res.seen:
            res.seen.add(path)
            scan_file(path, st, max_bytes, res, chunk_size)


def _find_files(root, wanted, prune=()):
    """Files under root whose name satisfies wanted(dirpath, name); never follows a symlink and
    never enters a folder in prune. Returns (paths, unreadable folders)."""
    found, unreadable, stack = [], [], [root]
    while stack:                   # iterative: os.walk is recursive before Python 3.12
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = [(e.name, e.is_dir(follow_symlinks=False)) for e in it]
        except OSError:
            unreadable.append(d)
            continue
        for name, is_dir in sorted(entries):
            p = os.path.join(d, name)
            if is_dir:
                if p not in prune:
                    stack.append(p)
            elif wanted(d, name):  # files, symlinks (reported as skipped later) and specials
                found.append(p)
    return found, unreadable


ENV_SEARCH_PRUNE = ("Library", "Pictures", "Music", "Movies", ".Trash")


def preset_laptop(home, repo_root):
    """The include list of the step-3 plan (§3). Returns (paths, unreadable folders met while
    searching for .git/config and .env* files)."""
    h = lambda *p: os.path.join(home, *p)
    paths =[h(".claude"), h(".claude.json"), h("Library", "Application Support", "Claude"),
             h("Library", "Logs", "Claude"), h(".codex"), h(".cursor"), h(".gemini"), h(".openclaw"),
             h(".openhands"), h(".hermes"), repo_root, h(".netrc"), h(".git-credentials"), h(".npmrc"),
             h(".config"), h("Library", "Application Support", "Code", "User", "settings.json"),
             h("Library", "Application Support", "Cursor", "User", "settings.json"),
             h("Library", "LaunchAgents"), h(".zshrc"), h(".zprofile"), h(".zshenv"), h(".zlogin"),
             h(".bashrc"), h(".bash_profile"), h(".profile"), h(".zsh_history"), h(".bash_history"),
             h(".zsh_sessions"), h(".gitconfig"), h("Downloads"), h("Desktop"), h("Documents")]
    unreadable = []
    for top in (h("Projects"), h("Documents")):
        if os.path.isdir(top) and not os.path.islink(top):
            found, bad = _find_files(top, lambda d, n: n == "config" and os.path.basename(d) == ".git")
            paths += found
            unreadable += bad
    # The .env* name search skips ENV_SEARCH_PRUNE: app data and media libraries, not projects,
    # and walking them raises macOS privacy prompts (Mail, Messages, Photos, Music...). The app
    # folders under ~/Library that the plan names are scanned whole above.
    found, bad = _find_files(home, lambda d, n: n.startswith(".env"),
                             prune={h(p) for p in ENV_SEARCH_PRUNE})
    paths += found
    unreadable += bad
    return paths, unreadable


# ---- output --------------------------------------------------------------------------------

TOKENISH_RE = re.compile(r"gh[pousr]_[A-Za-z0-9_]{4,}|github_pat_[A-Za-z0-9_]*")


def redact(text):
    """Token-like text in anything we print that is not a fingerprint (paths, messages)."""
    return TOKENISH_RE.sub("[token-like-text]", text)


def display_path(path, prefixes):
    for pre in prefixes:
        if path == pre:
            return redact(pre)
        if path.startswith(pre + "/"):
            return redact(pre + "/" + R.sha12(path[len(pre) + 1:]))
    return redact(path.encode("utf-8", "backslashreplace").decode("ascii", "backslashreplace")
                  .replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r"))


def guard(lines, secrets):
    """Last line of defence: withhold any line holding 8+ consecutive characters of any
    matched text. Nothing printed is expected to trip it; it exists for the case we missed."""
    windows = {s[i:i + 8] for s in secrets for i in range(max(len(s) - 7, 0))}
    out = []
    for line in lines:
        if any(line[i:i + 8] in windows for i in range(len(line) - 7)):
            out.append("withheld\ta line held token text")
        else:
            out.append(line)
    return out


HEADER = ("# scan-github-tokens: fingerprints only (sha12 = first 12 hex of sha1 of the value); "
          "no token value is printed")


def render(res, prefixes, tries):
    out = [HEADER]
    fl = []
    per_token = {}
    for (path, kind, fp, full, n), c in res.counts.items():
        fl.append(["finding", display_path(path, prefixes), kind, fp, f"count={c}",
                   "full" if full else "partial", f"len={n}"])
        per_token.setdefault((fp, kind, full, n), set()).add(path)
    out += ["\t".join(l) for l in sorted(fl)]
    out += sorted("\t".join(["token", fp, kind, f"files={len(paths)}", "full" if full else "partial",
                             f"len={n}"]) for (fp, kind, full, n), paths in per_token.items())
    out += ["\t".join(["try", fp, kind, result]) for fp, kind, result in tries]
    out += sorted(f"skipped\t{display_path(p, prefixes)}\t{r}" for p, r in res.skipped.items())
    out += sorted(f"absent\t{display_path(p, prefixes)}" for p in res.absent)
    fulls = {k[0] for k in per_token if k[2]}
    parts = {k[0] for k in per_token if not k[2]}
    out.append("\t".join(["totals", f"files_scanned={res.files_scanned}", f"findings={len(fl)}",
                          f"full_tokens={len(fulls)}", f"partial_tokens={len(parts)}",
                          f"skipped={len(res.skipped)}", f"absent={len(res.absent)}"]))
    return guard(out, res.secrets)


# ---- proving dead or alive (--try) ---------------------------------------------------------

API = "https://api.github.com"
ENDPOINT = {"classic": "/user", "oauth": "/user", "user-to-server": "/user", "fine-grained": "/user",
            "installation": "/installation/repositories"}
HTTP_TIMEOUT = 20        # seconds
MAX_BODY = 1 << 20       # bytes of an answer read, at most
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to wherever it points: refuse it, so a
    3xx comes back as an answer (UNKNOWN), never as a second request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect())


def github_get(url, token, opener=None):
    """The real seam: one GET with the token in an in-memory header. Returns (status, body);
    an HTTP error status is an answer, not an exception. Network errors raise."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.netloc != "api.github.com":
        raise ValueError("refusing a request that is not https://api.github.com")
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "scan-github-tokens"})
    try:
        with (opener or _opener()).open(req, timeout=HTTP_TIMEOUT) as r:
            return r.status, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(MAX_BODY)
        finally:
            e.close()


def _json(body):
    try:
        v = json.loads(body.decode("utf-8"))
        return v if isinstance(v, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _holds_token_text(text, token):
    if TOKENISH_RE.search(text):
        return True
    return any(token[i:i + 8] in text for i in range(len(token) - 7))


def _message(body, token):
    msg = _json(body).get("message")
    if not isinstance(msg, str):
        return ""
    msg = "".join(c if " " <= c <= "~" else " " for c in msg).strip()
    if _holds_token_text(msg, token):
        return "[message withheld: token text]"
    return msg[:80]


def try_token(kind, token, http):
    """One verdict line for one full-shape token; at most one call to `http`."""
    if kind == "refresh":
        return "CANNOT BE PROVED BY USE (refresh token)"
    try:
        status, body = http(API + ENDPOINT[kind], token)
    except (OSError, HTTPException) as e:   # URLError, timeouts, DNS, resets, TLS: OSError
        return "UNKNOWN network-error " + type(e).__name__
    data = _json(body)
    if status == 200 and kind == "installation":
        n = data.get("total_count")
        return "ALIVE total_count=" + (str(n) if isinstance(n, int) else "?")
    if status == 200:
        login = data.get("login")
        ok = isinstance(login, str) and LOGIN_RE.fullmatch(login) and not _holds_token_text(login, token)
        return "ALIVE login=" + (login if ok else "?")
    msg = _message(body, token)
    if status == 401 and msg == "Bad credentials":
        return "DEAD (Bad credentials, 401)"
    if status == 401 and kind == "installation":
        return "DEAD (401)"
    return f"UNKNOWN {int(status)}" + (" " + msg if msg else "")


# ---- command line --------------------------------------------------------------------------

DEFAULT_MAX_BYTES = 512 * 1024 * 1024


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _positive_int(text):
    v = int(text)
    if v <= 0:
        raise ValueError(text)
    return v


def _parser():
    p = _Parser(prog="scan-github-tokens.py", add_help=True,
                description="Find GitHub tokens in files; print fingerprints only.")
    p.add_argument("--root", action="append", default=[], metavar="PATH",
                   help="a file or folder to scan; repeatable; ~ is expanded")
    p.add_argument("--preset", choices=["laptop"], help="the laptop include list of the step-3 plan")
    p.add_argument("--max-bytes", type=_positive_int, default=DEFAULT_MAX_BYTES,
                   help="skip files larger than this (default 512 MiB)")
    p.add_argument("--hash-paths-under", action="append", default=[], metavar="PREFIX",
                   help="print paths under PREFIX as PREFIX/<sha12 of the rest>; repeatable")
    p.add_argument("--try", dest="try_", action="store_true",
                   help="prove each full-shape token dead or alive with one request to api.github.com")
    return p


def _norm(path):
    return os.path.abspath(os.path.expanduser(path))


def main(argv=None, http=None, home=None, repo_root=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        if not args.root and not args.preset:
            raise _Usage("give at least one --root PATH or --preset laptop; there are no default roots")
    except _Usage as e:
        stderr.write(redact(parser.format_usage()) + "scan-github-tokens.py: error: " + redact(str(e)) + "\n")
        return 2
    try:
        return _run(args, http or github_get, home, repo_root, stdout)
    except Exception as e:   # never print the message: it could hold a path or token text
        stderr.write(f"scan-github-tokens.py: internal error {type(e).__name__}; nothing printed is complete\n")
        return 1


def _run(args, http, home, repo_root, stdout):
    roots = [_norm(r) for r in args.root]
    res = Scan()
    if args.preset == "laptop":
        found, unreadable = preset_laptop(_norm(home or "~"), _norm(repo_root or REPO_ROOT))
        roots += found
        for p in unreadable:
            res.skipped[p] = "unreadable"
    for r in roots:
        scan_path(r, args.max_bytes, res)
    tries = []
    if args.try_:
        for fp in sorted(res.values):
            kind, value = res.values[fp]
            tries.append((fp, kind, try_token(kind, value, http)))
    prefixes = [_norm(p).rstrip("/") or "/" for p in args.hash_paths_under]
    out = render(res, prefixes, tries)
    stdout.write("".join(line + "\n" for line in out))
    if not args.try_:
        return 1 if res.values else 0
    return 1 if any(not r.startswith("DEAD") for _, _, r in tries) else 0


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # bin -> hermes-agent -> infra -> repo
if __name__ == "__main__":
    sys.exit(main())
