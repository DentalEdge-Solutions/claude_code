#!/usr/bin/env python3
"""Find GitHub tokens lying in files, and print fingerprints only (P0-10 step 3, P5 and P15).

RECIPE (the owner; about two minutes)
  1. Run it with every agent closed (Claude, Codex, Cursor, Hermes, ...), from Terminal at
     the repo root:   cd ~/Projects/claude_code
  2. Laptop:  python3 infra/hermes-agent/bin/scan-github-tokens.py --preset laptop --try
  3. Then type  echo $?  and note the number (0 nothing to act on, 1 read the report,
     2 typing mistake, 3 internal error: the report is incomplete).
  4. Paste stdout only (the lines the command printed) into the session. Nothing else.
  5. Hashed paths (PREFIX/<12 hex>) change between runs. To find which file one is, re-run it
     yourself on that folder alone (--root <folder>, no --preset), and do not paste that output.
  6. VPS: copy this file and review_lib.py into one folder there, then run
     python3 scan-github-tokens.py --root ~ --root <HERMES_INSTALL> --hash-paths-under <HERMES_DATA> --try
     where <HERMES_INSTALL> is the folder Hermes is installed in and <HERMES_DATA> is its data
     folder (file names there hold customer IDs). Then  echo $?  as on the laptop.

WHY THIS EXISTS
    Step 3 measures where GitHub tokens are lying around (transcripts, histories, configs,
    .env files, app data) on the laptop and on the box, and proves each one dead or alive.
    The output is pasted back into an agent session, so it NEVER holds a token value: each
    token is shown as its sha12 fingerprint (first 12 hex of sha1 over the bare value,
    review_lib.sha12, the repo's credential convention).

WHAT IT DOES
    Walks every --root (file or folder) recursively, read-only. Inside a walk a symlink is
    skipped, never followed; a --root that is itself a symlink is resolved once and its target
    scanned, with a "resolved" line. Every regular file is read as BYTES (binary, leveldb and
    sqlite files included), in chunks with an overlap, so a token across a chunk boundary is
    found exactly once. Files are opened with O_NOFOLLOW and checked with fstat.

    Each file is searched for the repo's two GitHub patterns (scripts/telemetry/
    secret-patterns.js, pinned by a test) as plain ASCII, as UTF-16LE and as UTF-16BE (Windows
    and Electron apps), and inside "Basic <base64>" Authorization values (git's extraheader,
    HTTP traces: "x-access-token:ghs_..."). A match is decoded before it is classified and
    fingerprinted, so a token has the same sha12 in every encoding.

    A match is FULL when it has the exact shape (gh[pousr]_ + 36 alphanumerics = 40
    characters; github_pat_ + 22 + "_" + 59 = 93 characters) and the character right AFTER it
    is not a token character [A-Za-z0-9_]. There is no condition on the character BEFORE it:
    JSONL transcripts escape a newline as "\\n", so a token at the start of a line sits right
    after an "n" and must still count as full (decision of 2026-10-30). Any other match is
    PARTIAL: it is listed with its type, fingerprint and length for the owner to judge, and
    never tried. A match is capped at 256 characters: a longer one is a partial shown as
    len>256 and fingerprinted over its first 256 characters.

    --preset laptop expands to the include list of the step-3 plan (§3), plus every
    .git/config and .git/modules/*/config (submodule remotes) under ~/Projects and
    ~/Documents, and every .env* file under the home folder. The .env* name search does not
    enter ~/Library, ~/Pictures, ~/Music, ~/Movies or ~/.Trash (app data and media
    libraries; walking them raises macOS privacy prompts); each one present is listed as
    "pruned". Paths that do not exist are listed as absent. The preset also hashes, by
    itself, the paths under <repo>/infra/hermes-agent/data, ~/.hermes and ~/.claude/projects:
    the folder names under ~/.claude/projects are encoded working directories
    (~/.claude/projects/<encoded cwd>), and a working directory can carry a customer ID. When
    you scan those folders with --root instead, pass --hash-paths-under for each of them.

    iCloud: ~/Library/Mobile Documents (iCloud Drive) is not in the include list and not
    searched for .env* names. A cloud-only ("dataless") file anywhere is skipped as
    "dataless" and never downloaded.

    Types: classic (ghp_), oauth (gho_), user-to-server (ghu_), installation (ghs_),
    refresh (ghr_), fine-grained (github_pat_).

    --try sends, for each distinct FULL token, at most one GET to https://api.github.com,
    sequentially, with the token in an in-memory Authorization header (never on a command
    line). Redirects are refused so the header cannot travel elsewhere, and proxy variables
    are ignored (a notice line names any *_PROXY or SSL_CERT_* variable that is set):
        classic, oauth, user-to-server, fine-grained: GET /user
        installation: GET /installation/repositories
        refresh: no request; "CANNOT BE PROVED BY USE (refresh token)"
    On a 403 or 429 that says the rate limit is reached (x-ratelimit-remaining: 0, or a
    retry-after header) it stops: that token gets a fixed line (GitHub's message holds your IP
    address and is not printed) and every token not yet tried gets
    "UNKNOWN not-tried (rate limited)". Without --try there is no network access at all.

NOT COVERED (exit 0 does not mean "no token anywhere")
    Only what is listed here as covered is searched. Not covered: base64 other than a Basic
    Authorization value; gzip and zlib data, including git objects and packfiles;
    Snappy-compressed leveldb blocks; a token wrapped across lines; JSON \\u escapes
    ("\\u0067hp_..."); UTF-32; a UTF-16BE PARTIAL right before a non-ASCII character may be
    read one character short (full tokens are read right in both UTF-16 orders); encrypted stores (the keychain, browser cookie and password
    stores, encrypted app databases); files over --max-bytes, unreadable or dataless files,
    symlinks inside a walk, and every folder outside the roots. Each skipped, pruned and absent
    path is listed so you can see what was not read.

OUTPUT (stdout, tab-separated, sorted within each section)
    error    internal error <class>; this report is incomplete       (only on an internal error)
    notice   environment sets <names>: ...                            (names only, never values)
    finding  <path> <type> <sha12> count=<n> full|partial len=<n>|len>256
    token    <sha12> <type> files=<n> full|partial len=<n>|len>256    (across files)
    try      <sha12> <type> ALIVE login=<login> | ALIVE total_count=<n> |
             DEAD (Bad credentials, 401) | DEAD (401) | UNKNOWN <code> <message> |
             UNKNOWN network-error <class> | UNKNOWN rate-limited (...) |
             UNKNOWN not-tried (rate limited) | CANNOT BE PROVED BY USE (refresh token)
    skipped  <path> symlink|size|unreadable|not-a-regular-file|dataless|error <class>
    pruned   <path> not searched for .env* names
    resolved <target> (resolved from <root>)
    absent   <path>
    note     hash prefix not found: <prefix>                        (one per missing prefix)
    note     partials found: check the partials one by one; they are never tried
    totals   files_scanned= findings= full_tokens= partial_tokens= skipped= pruned= absent=
    --hash-paths-under PREFIX prints a path under PREFIX as PREFIX/<tag>, for folders whose
    file names hold customer IDs (the Hermes data folders). The tag is NOT a fingerprint like
    sha12: it is HMAC-SHA256 of the rest of the path with a random key made for this run
    (secrets.token_bytes(32)), never printed and never stored, first 12 hex. A bare hash of a
    10-digit ID is reversed by trying every ID; a keyed one is not. The same path gives the
    same tag within one run and a different tag in the next, so tags cannot be compared across
    runs. Token fingerprints stay review_lib.sha12, comparable across runs and with the rest
    of the repo: tokens are high-entropy, so a bare hash of one cannot be reversed.
    Prefixes match by identity, not spelling: each prefix's (st_dev, st_ino) is recorded at
    start-up (symlinks followed), and a path is under a prefix when it, or any folder above it,
    is that folder. So a symlink, a case difference on a case-insensitive volume or another
    Unicode form (NFC/NFD) cannot route around the hashing. The tag covers everything below the
    matched folder and the prefix is shown as you gave it. A prefix that does not exist gets a
    "note" line. Paths under a resolved --root are shown under that root as given, and a
    "resolved" line is hashed when either side is under a prefix (a target outside every
    prefix is then shown only as a tag).
    Every printed path (prefix included), skip and absent entry and GitHub message has each
    character outside 0x20-0x7E escaped (\\xNN, \\uNNNN), so nothing can drive the terminal or
    break the columns. Token-like text in a path is replaced, and a final guard replaces any
    column holding 8 or more consecutive characters of any match (first 256 characters; a
    window of one repeated character does not count) by "[path withheld]" or "[withheld]",
    keeping the rest of the line.

EXIT CODES
    0  no full-shape token found, or (with --try) every full-shape token proved DEAD
    1  a full-shape token found without --try; or with --try any token ALIVE, UNKNOWN or
       CANNOT BE PROVED (refresh)
    2  usage error (no --root and no --preset, a bad value); nothing is scanned
    3  internal error: a file could not be processed (listed as "skipped ... error <class>")
       or the run stopped (an "error" line first). The report printed is incomplete; read it.

HOW THE OWNER RUNS IT
    Run it yourself in your own Terminal, with all agents closed (Claude and every other
    agent app), because it reads files that may hold live secrets. It prints fingerprints
    only, never a token value, so its output is safe to paste back into a session. Missing
    paths are listed as absent; there are no default roots. If a token is ALIVE and it is
    yours, revoke it in the browser at once, then re-run with --try.
"""
import argparse, base64, binascii, bisect, errno, hashlib, hmac, json, os, re, secrets, stat, sys
import urllib.parse, urllib.request, urllib.error
from http.client import HTTPException
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_lib as R

# The one pattern source is scripts/telemetry/secret-patterns.js:22-23. Python cannot import it,
# so the two bodies are copied here and pinned by a parity test in scan-github-tokens.test.py.
GH_TOKEN_PATTERN = r"gh[pousr]_[A-Za-z0-9]{20,}"
GH_PAT_PATTERN = r"github_pat_[A-Za-z0-9_]{20,}"

# The same two patterns as atoms, so they can be built capped and in UTF-16. A test checks that
# the plain, uncapped build equals the pinned bodies above.
CAP = 256                # characters; a longer match is a partial "len>256"
GH_ATOMS = (("g", ""), ("h", ""), ("[pousr]", ""), ("_", ""), ("[A-Za-z0-9]", "{20,%s}"))
PAT_ATOMS = tuple((c, "") for c in "github_pat_") + (("[A-Za-z0-9_]", "{20,%s}"),)
BODY = {"gh": "[A-Za-z0-9]", "pat": "[A-Za-z0-9_]"}
UNIT = {"plain": 1, "le": 2, "be": 2}


def build_pattern(atoms, enc, cap=None):
    fixed = sum(1 for _, q in atoms if not q)
    out = []
    for atom, quant in atoms:
        q = quant % ("" if cap is None else cap - fixed) if quant else ""
        if enc == "plain":
            out.append(atom + q)
        elif enc == "le":
            out.append("(?:%s\\x00)%s" % (atom, q))
        else:
            out.append("(?:\\x00%s)%s" % (atom, q))
    return "".join(out)


def _unit_run(fam, enc):
    """A run of body characters of a family (used to consume the rest of a long match)."""
    unit = {"plain": "%s", "le": "(?:%s\\x00)", "be": "(?:\\x00%s)"}[enc] % BODY[fam]
    return re.compile((unit + "*").encode())


# Search order (see _find): plain fine-grained, plain classic, then UTF-16 fine-grained, UTF-16
# classic; a later match that overlaps a kept one is dropped. Fine-grained first, so a ghp_ inside
# a github_pat_ body is part of it.
PATTERNS = [(fam, enc, re.compile(build_pattern(atoms, enc, CAP).encode()))
            for enc in ("plain", "le", "be") for fam, atoms in (("pat", PAT_ATOMS), ("gh", GH_ATOMS))]
SKIP_RE = {(fam, enc): _unit_run(fam, enc) for fam in BODY for enc in UNIT}
BASIC_RE = re.compile(rb"[Bb]asic[ \t]{1,8}([A-Za-z0-9+/]{16,512}={0,2})")
DECODE = {"plain": "ascii", "le": "utf-16-le", "be": "utf-16-be"}

TYPES = {"ghp_": "classic", "gho_": "oauth", "ghu_": "user-to-server",
         "ghs_": "installation", "ghr_": "refresh"}
FULL_GH_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")
FULL_PAT_RE = re.compile(r"github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}")
TOKEN_CHAR_RE = re.compile(r"[A-Za-z0-9_]")
BODY_CHAR_RE = {fam: re.compile(cls) for fam, cls in BODY.items()}

CHUNK = 1 << 20          # bytes read at a time
OVERLAP = 128            # bytes kept from the previous chunk; more than the longest pattern
                         # prefix plus its minimum body in UTF-16 (2 x 31 = 62 bytes)


def classify(text, after, long=False):
    """(type label, full, length label) for one decoded match. `after` is the decoded character
    right after it ("" at the end of a file). Full = the exact shape AND no token character
    right after it; anything else is a partial, never tried. There is deliberately no
    condition on the character BEFORE: JSONL escapes a newline as "\\n", so a token at the
    start of a line sits right after an "n" (decision of 2026-10-30)."""
    kind = "fine-grained" if text.startswith("github_pat_") else TYPES[text[:4]]
    if long:
        return kind, False, "len>%d" % CAP
    shape = FULL_PAT_RE if kind == "fine-grained" else FULL_GH_RE
    full = shape.fullmatch(text) is not None and not (after and TOKEN_CHAR_RE.fullmatch(after))
    return kind, full, "len=%d" % len(text)


def _after(buf, b, enc):
    """The decoded character right after a match ending at b; "" at the end of the data. A
    UTF-16 unit that is not ASCII decodes to a character that is never a token character."""
    if enc == "plain":
        return buf[b:b + 1].decode("latin-1")
    pair = buf[b:b + 2]
    if len(pair) < 2:
        return ""
    lo, hi = (pair[0], pair[1]) if enc == "le" else (pair[1], pair[0])
    return chr(lo) if hi == 0 else "\ufffd"


RX = {(fam, enc): rx for fam, enc, rx in PATTERNS}


def _utf16(buf, pos, fam):
    """UTF-16LE and BE matches of one family, with overlapping readings resolved. ASCII text in
    UTF-16LE is also valid UTF-16BE shifted by one byte, so both patterns match, one byte
    apart. The readings agree inside and differ only at the end, next to a non-ASCII character:
    the shifted one gains or loses a character there. Nothing local tells them apart, but a
    real token has an exact length, so keep the reading that classifies as full-shape; when
    both or neither do, keep LE (the encoding of Windows and of most app stores)."""
    def key(c):
        a, b, fam, enc = c
        return (classify(buf[a:b].decode(DECODE[enc]), _after(buf, b, enc))[1], enc == "le")
    out = []
    for c in sorted((m.start(), m.end(), fam, enc) for enc in ("le", "be") for m in RX[fam, enc].finditer(buf, pos)):
        if out and c[0] < out[-1][1]:
            if key(c) > key(out[-1]):
                out[-1] = c
            continue
        out.append(c)
    return out


def _find(buf, pos):
    """Candidate matches in buf from pos, sorted by start, never overlapping, then Basic values.
    Groups in order: plain fine-grained, plain classic, UTF-16 fine-grained, UTF-16 classic,
    Basic; a candidate that overlaps a kept one is dropped. Kept spans are non-overlapping, so
    a bisect finds overlaps."""
    starts, ends, cands = [], [], []
    groups = [[(m.start(), m.end(), fam, "plain") for m in RX[fam, "plain"].finditer(buf, pos)]
              for fam in ("pat", "gh")]
    groups += [_utf16(buf, pos, fam) for fam in ("pat", "gh")]
    groups.append([(m.start(), m.end(), "basic", "plain") for m in BASIC_RE.finditer(buf, pos)])
    for group in groups:
        new = []
        for a, b, fam, enc in group:
            i = bisect.bisect_left(starts, b)
            if i and ends[i - 1] > a:
                continue
            new.append((a, b, fam, enc))
        if new:
            cands += new
            spans = sorted(list(zip(starts, ends)) + [(a, b) for a, b, _, _ in new])
            starts, ends = [s for s, _ in spans], [e for _, e in spans]
    return sorted(cands)


def _basic(raw):
    """Tokens inside one Basic value: base64-decode it and search the plain text."""
    b64 = BASIC_RE.match(raw).group(1)
    b64 += b"=" * (-len(b64) % 4)
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return
    for a, b, fam, enc in _find(data, 0):
        if enc == "plain" and fam in BODY:
            text = data[a:b].decode("ascii")
            after = _after(data, b, "plain")
            yield text, after, len(text) >= CAP and bool(after) and bool(BODY_CHAR_RE[fam].fullmatch(after))


def iter_matches(f, chunk_size=CHUNK):
    """Yield (decoded text, decoded character after, long) for every match in a binary stream,
    each exactly once, in bounded memory. A match that touches the end of the buffer, or
    starts in its last OVERLAP bytes, is carried into the next round with everything after it;
    a carried match is at most CAP characters long, so the carry stays small. After a long
    (> CAP) match the rest of its run is consumed as it streams past, never carried."""
    carry, skip = b"", None
    while True:
        chunk = f.read(chunk_size)
        eof = not chunk
        buf = carry + chunk
        pos = 0
        if skip is not None:
            pos = skip.match(buf, 0).end()
            if not eof and pos >= len(buf) - 1:     # the run may go on (or half a UTF-16 unit)
                carry = buf[pos:]
                continue
            skip = None
        safe_end = len(buf) - OVERLAP
        next_start = None
        restart = True
        while restart and next_start is None:
            restart = False
            for a, b, fam, enc in _find(buf, pos):
                if a < pos:
                    continue
                if not eof and (b + UNIT[enc] > len(buf) or a >= safe_end):
                    next_start = a
                    break
                if fam == "basic":
                    yield from _basic(buf[a:b])
                    pos = b
                    continue
                text = buf[a:b].decode(DECODE[enc])
                after = _after(buf, b, enc)
                long = len(text) >= CAP and bool(after) and bool(BODY_CHAR_RE[fam].fullmatch(after))
                yield text, after, long
                pos = b
                if long:
                    end = SKIP_RE[fam, enc].match(buf, b).end()
                    if not eof and end >= len(buf) - 1:
                        skip, next_start = SKIP_RE[fam, enc], end
                        break
                    pos = end
                    restart = True          # candidates inside the run are void; search again
                    break
        if eof:
            return
        if next_start is None:
            next_start = max(safe_end, pos)
        carry = buf[next_start:]


# ---- walking -------------------------------------------------------------------------------

SF_DATALESS = 0x40000000     # macOS: a cloud-only file; reading it would download it


class Scan:
    def __init__(self):
        self.counts = {}      # (path, kind, sha12, full, length label) -> count in that file
        self.values = {}      # sha12 -> (kind, value) for full-shape tokens; memory only
        self.secrets = set()  # every match text (first CAP characters), for the output guard
        self.skipped = {}     # path -> reason
        self.absent = set()
        self.pruned = set()
        self.resolved = {}    # target -> the --root symlink it was resolved from
        self.seen = set()     # files already scanned, so overlapping roots count once
        self.files_scanned = 0
        self.errors = 0


def _dataless(st):
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


def scan_file(path, max_bytes, res, chunk_size=CHUNK):
    """Open with O_NOFOLLOW (a symlink swapped in after the walk is refused), then decide from
    fstat on the open file, not from an earlier lstat."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as e:
        res.skipped[path] = "symlink" if e.errno in (errno.ELOOP, errno.EMLINK) else "unreadable"
        return
    with os.fdopen(fd, "rb") as f:
        try:
            st = os.fstat(fd)
        except OSError:
            res.skipped[path] = "unreadable"
            return
        if not stat.S_ISREG(st.st_mode):
            res.skipped[path] = "not-a-regular-file"
            return
        if _dataless(st):
            res.skipped[path] = "dataless"
            return
        if st.st_size > max_bytes:
            res.skipped[path] = "size"
            return
        try:
            found = list(iter_matches(f, chunk_size))
        except OSError:
            res.skipped[path] = "unreadable"
            return
        except Exception as e:      # MemoryError or a bug: skip this file, keep going, exit 3
            res.skipped[path] = "error " + type(e).__name__
            res.errors += 1
            return
    res.files_scanned += 1
    for text, after, long in found:
        kind, full, length = classify(text, after, long)
        fp = R.sha12(text)
        res.secrets.add(text)
        if full:
            res.values[fp] = (kind, text)
        key = (path, kind, fp, full, length)
        res.counts[key] = res.counts.get(key, 0) + 1


def scan_path(root, max_bytes, res, chunk_size=CHUNK, top=True):
    """Scan one root, file or folder, read-only. Inside the walk a symlink is skipped; a
    top-level root that is a symlink is resolved once. Iterative, so a deep tree cannot
    exhaust Python's recursion limit."""
    if top:
        try:
            st = os.lstat(root)
        except FileNotFoundError:
            res.absent.add(root)
            return
        except OSError:
            res.skipped[root] = "unreadable"
            return
        if stat.S_ISLNK(st.st_mode):
            target = os.path.realpath(root)
            if not os.path.exists(target):
                res.skipped[root] = "symlink"
                return
            res.resolved[target] = root
            root = target
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
        elif _dataless(st):
            res.skipped[path] = "dataless"
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
            scan_file(path, max_bytes, res, chunk_size)


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


def _is_git_config(d, name):
    """.git/config, and .git/modules/<name>/.../config (submodule remotes)."""
    return name == "config" and (os.path.basename(d) == ".git"
                                 or os.sep + ".git" + os.sep + "modules" + os.sep in d + os.sep)


ENV_SEARCH_PRUNE = ("Library", "Pictures", "Music", "Movies", ".Trash")


def preset_laptop(home, repo_root):
    """The include list of the step-3 plan (§3). Returns (the listed paths, unreadable folders
    met while searching, folders pruned from the .env* search, prefixes to hash, files found by
    the .git/config and .env* name searches). Found files were met inside a walk, so a symlink
    among them is skipped, not resolved."""
    h = lambda *p: os.path.join(home, *p)
    paths = [h(".claude"), h(".claude.json"), h("Library", "Application Support", "Claude"),
             h("Library", "Logs", "Claude"), h(".codex"), h(".cursor"), h(".gemini"), h(".openclaw"),
             h(".openhands"), h(".hermes"), repo_root, h(".netrc"), h(".git-credentials"), h(".npmrc"),
             h(".config"), h("Library", "Application Support", "Code", "User", "settings.json"),
             h("Library", "Application Support", "Cursor", "User", "settings.json"),
             h("Library", "LaunchAgents"), h(".zshrc"), h(".zprofile"), h(".zshenv"), h(".zlogin"),
             h(".bashrc"), h(".bash_profile"), h(".profile"), h(".zsh_history"), h(".bash_history"),
             h(".zsh_sessions"), h(".gitconfig"), h("Downloads"), h("Desktop"), h("Documents")]
    unreadable, found_all = [], []
    for top in (h("Projects"), h("Documents")):
        if os.path.isdir(top) and not os.path.islink(top):
            found, bad = _find_files(top, _is_git_config)
            found_all += found
            unreadable += bad
    # The .env* name search skips ENV_SEARCH_PRUNE: app data and media libraries, not projects,
    # and walking them raises macOS privacy prompts (Mail, Messages, Photos, Music...). The app
    # folders under ~/Library that the plan names are scanned whole above.
    prune = [h(p) for p in ENV_SEARCH_PRUNE]
    found, bad = _find_files(home, lambda d, n: n.startswith(".env"), prune=set(prune))
    found_all += found
    unreadable += bad
    pruned = [p for p in prune if os.path.isdir(p) and not os.path.islink(p)]
    prefixes = [os.path.join(repo_root, "infra", "hermes-agent", "data"), h(".hermes"), h(".claude", "projects")]
    return paths, unreadable, pruned, prefixes, found_all


# ---- output --------------------------------------------------------------------------------

TOKENISH_RE = re.compile(r"gh[pousr]_[A-Za-z0-9_]{4,}|github_pat_[A-Za-z0-9_]*")


def redact(text):
    """Token-like text in anything we print that is not a fingerprint (paths, messages)."""
    return TOKENISH_RE.sub("[token-like-text]", text)


def printable(text):
    """Every character outside 0x20-0x7E as a deterministic escape, so nothing from the file
    system or from GitHub can drive the terminal (ESC sequences, BEL, newlines) or break the
    tab-separated columns: ASCII controls and DEL as \\xNN, an undecodable file-name byte
    (surrogateescape) as \\xNN of that byte, other characters as \\uNNNN or \\UNNNNNNNN."""
    out = []
    for c in text:
        o = ord(c)
        if 0x20 <= o <= 0x7E:
            out.append(c)
        elif o < 0x80:
            out.append("\\x%02x" % o)
        elif 0xDC80 <= o <= 0xDCFF:
            out.append("\\x%02x" % (o - 0xDC00))
        elif o <= 0xFFFF:
            out.append("\\u%04x" % o)
        else:
            out.append("\\U%08x" % o)
    return "".join(out)


def path_tag(key, rest):
    """Keyed tag of the part of a path under a --hash-paths-under prefix: HMAC-SHA256 with the
    per-run random key, first 12 hex. Not review_lib.sha12: a bare hash of a 10-digit customer
    ID is reversed by trying every ID. Not review_lib.hmac12 either: that one encodes with
    str.encode(), which fails on a file name that is not valid UTF-8."""
    return hmac.new(key, os.fsencode(rest), hashlib.sha256).hexdigest()[:12]


class HashPrefixes:
    """The --hash-paths-under prefixes, matched by IDENTITY, not spelling. A case-insensitive
    volume, a different Unicode normalisation (NFC/NFD) or a symlink can spell the same folder
    in another way; (st_dev, st_ino) cannot. Each prefix is recorded at start-up with os.stat
    (symlinks followed); a path is under a prefix when the path itself or one of its ancestor
    folders is that folder. The spelling the owner gave is a fast path only: it can hash, never
    reveal. A prefix that does not exist is not in the set and gets a note."""

    def __init__(self, raws):
        self.raws = list(raws)
        self.ids, self.missing, self._cache = {}, [], {}
        for raw in self.raws:
            try:
                st = os.stat(raw)
            except OSError:
                self.missing.append(raw)
                continue
            self.ids.setdefault((st.st_dev, st.st_ino), raw)

    def _id(self, path, follow=True):
        """(st_dev, st_ino) of a folder, cached per folder so each is stat-ed once a run."""
        k = (path, follow)
        if k not in self._cache:
            try:
                st = os.stat(path) if follow else os.lstat(path)
                self._cache[k] = (st.st_dev, st.st_ino)
            except OSError:
                self._cache[k] = None
        return self._cache[k]

    def match(self, path):
        """(the prefix as the owner gave it, the rest of path below it), or None."""
        for raw in self.raws:
            base = raw if raw.endswith("/") else raw + "/"
            if path == raw:
                return raw, ""
            if path.startswith(base):
                return raw, path[len(base):]
        if not self.ids:
            return None
        own = self._id(path, follow=False)
        if own in self.ids:
            return self.ids[own], ""
        child = path
        while True:
            parent = os.path.dirname(child)
            if parent == child:
                return None
            i = self._id(parent)
            if i in self.ids:
                base = parent if parent.endswith("/") else parent + "/"
                return self.ids[i], path[len(base):]
            child = parent


def _unresolve(path, resolved):
    """A path under the target of a resolved --root, mapped back onto that root: the owner sees
    the path asked for. The most specific root wins."""
    for t in sorted(resolved, key=len, reverse=True):
        if path == t or path.startswith(t.rstrip("/") + "/"):
            return resolved[t] + path[len(t):]
    return path


def _hidden(path, prefixes, key):
    """PREFIX/<tag> when path is under a hash prefix (by identity), else None. The prefix is
    printed as the owner gave it; the tag covers everything below the matched folder."""
    m = prefixes.match(path)
    if m is None:
        return None
    raw, rest = m
    if not rest:
        return redact(printable(raw))
    return redact(printable(raw if raw.endswith("/") else raw + "/") + path_tag(key, rest))


def display_path(path, prefixes, key, resolved=None):
    if not isinstance(prefixes, HashPrefixes):
        prefixes = HashPrefixes(prefixes)
    p = _unresolve(path, resolved or {})
    hidden = _hidden(p, prefixes, key)
    return hidden if hidden is not None else redact(printable(p))


def _resolved_row(target, root, prefixes, key):
    """The resolved line, hashed when either side is under a prefix: a target outside every
    prefix is then shown only as a tag, since its name may be the hidden part."""
    r = _hidden(root, prefixes, key)
    t = _hidden(target, prefixes, key)
    if t is None:
        t = "[hashed " + path_tag(key, target) + "]" if r is not None else redact(printable(target))
    if r is None:
        r = redact(printable(root))
    return ["resolved", t, f"(resolved from {r})"]


PATH_ROWS = {"finding", "skipped", "pruned", "resolved", "absent"}


def guard(rows, secrets):
    """Last line of defence, column by column: a column holding 8 or more consecutive
    characters of any match is replaced ("[path withheld]" for a path), the rest of the line
    kept. A window of one repeated character ("AAAAAAAA") does not count: it is no evidence of
    a token and would withhold innocent paths."""
    windows = {s[i:i + 8] for s in secrets for i in range(max(len(s) - 7, 0)) if len(set(s[i:i + 8])) > 1}
    out = []
    for row in rows:
        new = row[:1]
        for j, col in enumerate(row[1:], 1):
            if any(col[i:i + 8] in windows for i in range(len(col) - 7)):
                col = "[path withheld]" if j == 1 and row[0] in PATH_ROWS else "[withheld]"
            new.append(col)
        out.append(new)
    return out


HEADER = ("# scan-github-tokens: fingerprints only (sha12 = first 12 hex of sha1 of the value); "
          "no token value is printed")
NOTE_PARTIALS = "partials found: check the partials one by one; they are never tried"


def render(res, prefixes, tries, key, notices=(), error=None):
    if not isinstance(prefixes, HashPrefixes):
        prefixes = HashPrefixes(prefixes)
    rows = [[HEADER]]
    if error:
        rows.append(["error", f"internal error {error}; this report is incomplete"])
    rows += [["notice", n] for n in notices]
    disp = lambda p: display_path(p, prefixes, key, res.resolved)
    fl, per_token = [], {}
    for (path, kind, fp, full, n), c in res.counts.items():
        fl.append(["finding", disp(path), kind, fp, f"count={c}", "full" if full else "partial", n])
        per_token.setdefault((fp, kind, full, n), set()).add(path)
    rows += sorted(fl)
    rows += sorted(["token", fp, kind, f"files={len(paths)}", "full" if full else "partial", n]
                   for (fp, kind, full, n), paths in per_token.items())
    rows += [["try", fp, kind, result] for fp, kind, result in tries]
    rows += sorted(["skipped", disp(p), printable(r)] for p, r in res.skipped.items())
    rows += sorted(["pruned", disp(p), "not searched for .env* names"] for p in res.pruned)
    rows += sorted(_resolved_row(t, r, prefixes, key) for t, r in res.resolved.items())
    rows += sorted(["absent", disp(p)] for p in res.absent)
    fulls = {k[0] for k in per_token if k[2]}
    parts = {k[0] for k in per_token if not k[2]}
    rows += [["note", "hash prefix not found: " + redact(printable(p))] for p in prefixes.missing]
    if parts:
        rows.append(["note", NOTE_PARTIALS])
    rows.append(["totals", f"files_scanned={res.files_scanned}", f"findings={len(fl)}",
                 f"full_tokens={len(fulls)}", f"partial_tokens={len(parts)}",
                 f"skipped={len(res.skipped)}", f"pruned={len(res.pruned)}", f"absent={len(res.absent)}"])
    return ["\t".join(r) for r in guard(rows, res.secrets)]


def env_notice(environ):
    names = sorted(n for n in environ if n.upper().endswith("_PROXY") or n.upper().startswith("SSL_CERT_"))
    if not names:
        return []
    return ["environment sets " + printable(", ".join(names)) +
            ": --try ignores the proxy variables; SSL_CERT_* variables still apply to its TLS checks"]


# ---- proving dead or alive (--try) ---------------------------------------------------------

API = "https://api.github.com"
ENDPOINT = {"classic": "/user", "oauth": "/user", "user-to-server": "/user", "fine-grained": "/user",
            "installation": "/installation/repositories"}
HTTP_TIMEOUT = 20        # seconds
MAX_BODY = 1 << 20       # bytes of an answer read, at most
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REFRESH = "CANNOT BE PROVED BY USE (refresh token)"
RATE_LIMITED = "UNKNOWN rate-limited (stopped here; GitHub's message is not printed)"
NOT_TRIED = "UNKNOWN not-tried (rate limited)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to wherever it points: refuse it, so a
    3xx comes back as an answer (UNKNOWN), never as a second request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    # An empty ProxyHandler: HTTPS_PROXY and friends are ignored, so a proxy set in the
    # environment never sees the request (with a CONNECT proxy it would see the host name).
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _headers(h):
    return {str(k).lower(): str(v) for k, v in (h.items() if h else [])}


def github_get(url, token, opener=None):
    """The real seam: one GET with the token in an in-memory header. Returns (status, body,
    lower-cased headers); an HTTP error status is an answer, not an exception. Network errors
    raise."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.netloc != "api.github.com":
        raise ValueError("refusing a request that is not https://api.github.com")
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "scan-github-tokens"})
    try:
        with (opener or _opener()).open(req, timeout=HTTP_TIMEOUT) as r:
            return r.status, r.read(MAX_BODY), _headers(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(MAX_BODY), _headers(e.headers)
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
    msg = msg.strip()
    if _holds_token_text(msg, token):
        return "[message withheld: token text]"
    out, n = [], 0
    for c in msg:                  # escaped, then cut at 80 characters without splitting an escape
        e = printable(c)
        if n + len(e) > 80:
            break
        out.append(e)
        n += len(e)
    return "".join(out)


def try_token(kind, token, http):
    """One verdict line for one full-shape token; at most one call to `http`."""
    if kind == "refresh":
        return REFRESH
    try:
        status, body, headers = http(API + ENDPOINT[kind], token)
    except (OSError, HTTPException) as e:   # URLError, timeouts, DNS, resets, TLS: OSError
        return "UNKNOWN network-error " + type(e).__name__
    if status in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers):
        return RATE_LIMITED
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
                   help="print paths under PREFIX as PREFIX/<keyed per-run tag of the rest>; repeatable")
    p.add_argument("--try", dest="try_", action="store_true",
                   help="prove each full-shape token dead or alive with one request to api.github.com")
    return p


def _norm(path):
    return os.path.abspath(os.path.expanduser(path))


def main(argv=None, http=None, home=None, repo_root=None, stdout=None, stderr=None, path_key=None,
         environ=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        if not args.root and not args.preset:
            raise _Usage("give at least one --root PATH or --preset laptop; there are no default roots")
    except _Usage as e:
        stderr.write(redact(parser.format_usage()) + "scan-github-tokens.py: error: "
                     + redact(printable(str(e))) + "\n")
        return 2
    state = {}
    try:
        return _run(args, http or github_get, home, repo_root, stdout, path_key,
                    os.environ if environ is None else environ, state)
    except Exception as e:   # never print the message: it could hold a path or token text
        name = type(e).__name__
        if "res" in state:
            try:             # the report gathered so far, through the same escaping and guard
                out = render(state["res"], state["prefixes"], state["tries"], state["key"],
                             state["notices"], error=name)
                stdout.write("".join(line + "\n" for line in out))
            except Exception:
                pass         # e.g. still out of memory: the stderr line below is all we can say
        stderr.write(f"scan-github-tokens.py: internal error {name}; the report is incomplete\n")
        return 3


def _run(args, http, home, repo_root, stdout, path_key, environ, state):
    # Per-run key for --hash-paths-under tags; never printed, never stored. path_key is a test seam.
    state["key"] = path_key if path_key is not None else secrets.token_bytes(32)
    state["notices"] = env_notice(environ)
    state["tries"] = tries = []
    prefixes = [_norm(p).rstrip("/") or "/" for p in args.hash_paths_under]
    state["prefixes"] = prefixes
    state["res"] = res = Scan()
    tops = [_norm(r) for r in args.root]
    found = []
    if args.preset == "laptop":
        paths, unreadable, pruned, hash_prefixes, found = preset_laptop(_norm(home or "~"),
                                                                        _norm(repo_root or REPO_ROOT))
        prefixes += [p for p in hash_prefixes if p not in prefixes]
        res.pruned.update(pruned)
        for p in unreadable:
            res.skipped[p] = "unreadable"
        tops += paths
    # Record each prefix's identity at start-up, before anything is scanned.
    state["prefixes"] = prefixes = HashPrefixes(prefixes)
    for r in tops:
        scan_path(r, args.max_bytes, res)
    for r in found:
        scan_path(r, args.max_bytes, res, top=False)
    if args.try_:
        limited = False
        for fp in sorted(res.values):
            kind, value = res.values[fp]
            if limited and kind != "refresh":
                result = NOT_TRIED
            else:
                result = try_token(kind, value, http)
                limited = limited or result == RATE_LIMITED
            tries.append((fp, kind, result))
    out = render(res, prefixes, tries, state["key"], state["notices"])
    stdout.write("".join(line + "\n" for line in out))
    if res.errors:
        return 3
    if not args.try_:
        return 1 if res.values else 0
    return 1 if any(not r.startswith("DEAD") for _, _, r in tries) else 0


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # bin -> hermes-agent -> infra -> repo
if __name__ == "__main__":
    sys.exit(main())
