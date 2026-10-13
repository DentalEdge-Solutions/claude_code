# Review #10 follow-ups (Plan A of the review #11 box change) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close finding F59 and the four other follow-ups of security review #10, so they can ship with or without the `ads-report` job (Plan B).

**Architecture:** The collector's two journal leak checks (D2.3, D10.7) move from the message text to every stored field, through one `journalctl -o json --all` call read line by line. The collector tightens a redirected output file to `0600` itself. D4.6 gains the journal service's start. Two small tools are added: a one-time search and removal of the leftover journal directory, and the helper that reads the last PASS's proxy hash from a private bundle.

**Tech Stack:** Python 3 standard library only (the box has nothing else); `unittest`; `journalctl` of systemd 255.

**Spec:** `docs/superpowers/specs/2026-10-13-ads-report-job-design.md` (Part 4, "Measurements on the box", "Testing").

## Global Constraints

- Standard library only in `infra/hermes-agent/bin/`.
- Run `infra/hermes-agent/bin/run-bin-tests.sh` after every change under `infra/hermes-agent/bin/`; it must exit 0 before a commit.
- No journal line, field value, host name, machine id, path under `/var/log/journal`, customer id, client name or credential value in any output, error reason, test name, commit message or document. Counts, times and fixed words only.
- A `CouldNotCheck` reason is built from fixed words and `argv[0]`, never from stderr text.
- The whole journal is read by ONE `journalctl` call (operator's decision, 2026-10-10).
- Time limits: 300 s for the whole journal (`JOURNAL_SCAN_TIMEOUT`), 60 s for a unit's journal.
- The customer-id count skips exactly these 17 fields and no other: `__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP`, `__SEQNUM`, `__SEQNUM_ID`, `_SOURCE_REALTIME_TIMESTAMP`, `_SOURCE_MONOTONIC_TIMESTAMP`, `_BOOT_ID`, `_MACHINE_ID`, `_STREAM_ID`, `_SYSTEMD_INVOCATION_ID`, `_PID`, `_UID`, `_GID`, `_AUDIT_LOGINUID`, `_AUDIT_SESSION`, `_SYSTEMD_OWNER_UID`. The skip list never applies to the credential search.
- The checklist goes to `version: 1.20` once, in Task 2. Later tasks of this plan and Plan B edit the checklist without raising it again while they are on the same branch.
- Never commit anything under `evals/`. Never push; the operator gives the word.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work on branch `feat/review-11-box-change`, created from `docs/ads-report-job-design`.

## Review Focus

1. A journal entry journalctl prints as a line that is not a JSON object: the item must be `could-not-check`, never a healthy count (Task 1, `test_an_entry_that_does_not_parse...`).
2. A field journalctl prints as `null`: the item must be `could-not-check` (Task 1, `test_a_field_printed_as_null...`).
3. A registered customer id that appears inside a clock field by chance: not counted; the same id in `_CMDLINE`: counted (Task 1).
4. The collector's output redirected into a file that already exists with mode `0664`: `0600` before the first byte; output to a pipe: untouched (Task 3).
5. The leftover directory holding a link or a sub-directory, or other counts than expected: nothing is removed (Task 5).

## File Structure

| File | Change |
|---|---|
| `infra/hermes-agent/bin/collect-review-evidence.py` | `Host.stream`, `_search_journal`, D2.3, D10.7, D4.6, `--other-journals`, output mode |
| `infra/hermes-agent/bin/collect-review-evidence.test.py` | new tests; the fake host prints journal fixtures as JSON entries |
| `infra/hermes-agent/bin/review_lib.py` (+ test) | `restrict_output` |
| `infra/hermes-agent/bin/collect-review-evidence-laptop.py` (+ test) | calls `restrict_output` |
| `infra/hermes-agent/bin/summarize-review-bundle.py` (+ test) | new keys of D2.3, D10.7, D4.6 |
| `infra/hermes-agent/bin/remove-other-journal-dirs.py` (+ test) | new |
| `infra/hermes-agent/bin/last-pass-execstart.py` (+ test) | new |
| `infra/hermes-agent/deploy/security-review/CHECKLIST.md`, `REPORT-TEMPLATE.md` | v1.20 wording |
| `infra/hermes-agent/deploy/BRING-UP.md` | collection step, the leftover-directory chapter |
| `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` | F59's status |

---

### Task 1: the all-fields journal search (no item uses it yet)

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (imports at line 21; after `_run_real`; `class Host`; after `_journal_read`)
- Test: `infra/hermes-agent/bin/collect-review-evidence.test.py` (new class at the end, before `if __name__`)

**Interfaces:**
- Consumes: `CRED_TEXT_RE`, `R.looks_like_credential_text`, `Redactor.has_customer_id`, `_not_root_on_a_real_host`, `CouldNotCheck`, `TERM_GRACE`.
- Produces:
  - `JOURNAL_ALL_FIELDS = ["-o", "json", "--all", "--no-pager"]`
  - `CID_SKIP_FIELDS: frozenset[str]` (the 17 names)
  - `SEARCH_COUNTS = ("pattern_hits", "known_secret_hits", "credential_text_lines", "customer_id_lines", "entries", "fields", "scanned_characters", "undecodable_characters")`
  - `Host.stream(argv, timeout=60)` → an iterable of text lines with `.rc` and `.err` set once the lines have ended
  - `_search_journal(host, argv, secrets, redactor=None, timeout=60, on_message=None) -> dict[str, int]` with exactly the keys of `SEARCH_COUNTS`; raises `CouldNotCheck`

- [ ] **Step 1: Write the failing tests**

Add to `collect-review-evidence.test.py`:

```python
def _e(**fields):
    """One journal entry as `journalctl -o json` prints it."""
    return json.dumps(fields) + "\n"


class TestSearchJournal(Base):
    SECRET = "sk-or-v1-" + "0123456789abcdef" * 4
    ARGV = ["journalctl", "-o", "json", "--all", "--no-pager"]

    def _search(self, text, secrets=(), redactor=True, rc=0, err="", on_message=None):
        # A plain Host with a fake runner, not FakeHost: from Task 2 on FakeHost rewrites a line
        # that is not a JSON object into an entry, and these tests need the text as given.
        host = CE.Host(self.root, lambda argv, timeout=60: (rc, text, err))
        red = CE.context(host, self.KEY)["redactor"] if redactor else None
        return CE._search_journal(host, self.ARGV, list(secrets), red, on_message=on_message)

    def test_the_constants_are_the_design_s(self):
        self.assertEqual(CE.JOURNAL_ALL_FIELDS, ["-o", "json", "--all", "--no-pager"])
        self.assertEqual(len(CE.CID_SKIP_FIELDS), 17)
        for name in ("MESSAGE", "_CMDLINE", "COMMAND", "_COMM", "_EXE", "CPU_USAGE_NSEC", "MAX_USE"):
            self.assertNotIn(name, CE.CID_SKIP_FIELDS)
        self.assertTrue(all(n.startswith("_") for n in CE.CID_SKIP_FIELDS))     # journald-written only

    def test_a_secret_in_the_command_line_field_is_counted(self):
        c = self._search(_e(MESSAGE="Started.", _CMDLINE=f"curl -H {self.SECRET}"), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["entries"], c["fields"]), (1, 1, 2))

    def test_a_credential_pattern_in_sudo_s_command_field_is_counted(self):
        c = self._search(_e(MESSAGE="x", COMMAND=f"/usr/bin/env GOOGLE_ADS_REFRESH_TOKEN={TOKEN} true"))
        self.assertEqual((c["pattern_hits"], c["credential_text_lines"]), (1, 1))

    def test_a_value_that_is_not_text_arrives_as_bytes_and_is_searched(self):
        c = self._search(_e(MESSAGE=list(f"leak {self.SECRET} \xff".encode("latin-1"))), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["undecodable_characters"]), (1, 1))

    def test_a_secret_at_the_end_of_a_very_long_field_is_counted(self):
        c = self._search(_e(MESSAGE="x" * 100000 + self.SECRET), [self.SECRET])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_a_field_set_twice_is_searched_in_both_values(self):
        c = self._search(_e(MESSAGE=["a " + self.SECRET, list(("b " + self.SECRET).encode())]), [self.SECRET])
        self.assertEqual((c["known_secret_hits"], c["fields"]), (2, 1))

    def test_a_customer_id_in_a_clock_field_is_not_counted_and_in_the_command_line_is(self):
        entry = dict(__REALTIME_TIMESTAMP="1760123456789000", _SOURCE_REALTIME_TIMESTAMP="1761234567890123",
                     _AUDIT_LOGINUID="1234567890", MESSAGE="ok")
        self.assertEqual(self._search(_e(**entry))["customer_id_lines"], 0)
        self.assertEqual(self._search(_e(**entry, _CMDLINE="tool --customer 1234567890"))["customer_id_lines"], 1)
        self.assertEqual(self._search(_e(**entry, MAX_USE="1234567890"))["customer_id_lines"], 1)   # a program can write it

    def test_a_secret_in_a_skipped_field_is_still_counted(self):
        c = self._search(_e(_STREAM_ID=self.SECRET, MESSAGE="ok"), [self.SECRET])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_without_a_redactor_the_two_line_counts_stay_zero(self):
        c = self._search(_e(MESSAGE=f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN} 1234567890"), redactor=False)
        self.assertEqual((c["pattern_hits"], c["credential_text_lines"], c["customer_id_lines"]), (1, 0, 0))

    def test_the_size_is_the_text_read_and_the_keys_are_closed(self):
        text = _e(MESSAGE="Started.") * 3
        c = self._search(text)
        self.assertEqual(set(c), set(CE.SEARCH_COUNTS))
        self.assertEqual((c["scanned_characters"], c["entries"], c["fields"]), (len(text), 3, 3))

    def test_json_escaping_does_not_hide_a_value(self):
        secret = 'pa"ss\\word/1234'
        c = self._search(_e(MESSAGE="x " + secret), [secret])
        self.assertEqual(c["known_secret_hits"], 1)

    def test_each_message_is_handed_to_the_caller(self):
        seen = []
        self._search(_e(MESSAGE="one\ntwo", _COMM="x") + _e(MESSAGE="three"), on_message=seen.append)
        self.assertEqual(seen, ["one\ntwo", "three"])

    def test_an_entry_that_does_not_parse_makes_the_search_could_not_check(self):
        for bad in ("not json\n", "[1, 2]\n", '{"MESSAGE": "cut\n'):
            with self.subTest(bad=bad), self.assertRaises(CE.CouldNotCheck) as cm:
                self._search(_e(MESSAGE="ok") + bad)
            self.assertIn("did not parse", str(cm.exception))

    def test_a_field_printed_as_null_makes_the_search_could_not_check(self):
        with self.assertRaises(CE.CouldNotCheck) as cm:
            self._search(_e(MESSAGE=None))
        self.assertIn("not printed", str(cm.exception))

    def test_a_failed_or_warned_read_is_could_not_check_in_fixed_words(self):
        for rc, err, want in ((1, "Failed to open /var/log/journal/0123", "journalctl exited 1"),
                              (0, "Journal file /var/log/journal/0123/x corrupted", "wrote a warning on stderr")):
            with self.subTest(rc=rc), self.assertRaises(CE.CouldNotCheck) as cm:
                self._search(_e(MESSAGE="ok"), rc=rc, err=err)
            self.assertIn(want, str(cm.exception))
            self.assertNotIn("/var/log", str(cm.exception))

    def test_blank_lines_are_not_entries(self):
        self.assertEqual(self._search("\n" + _e(MESSAGE="ok") + "\n")["entries"], 1)


class TestStream(unittest.TestCase):
    def _real(self, code, timeout=30):
        return CE.Host().stream([sys.executable, "-c", code], timeout)

    def test_the_35_day_size_passes_through_the_real_stream_line_by_line(self):
        """185,000 lines of 1,000 characters: M1 of 2026-10-13 scaled to 35 days (about 184 MB)."""
        s = self._real("import sys\nline = 'x' * 999 + '\\n'\nfor i in range(185000): sys.stdout.write(line)", timeout=120)
        n = size = 0
        for line in s:
            n += 1; size += len(line)
        self.assertEqual((n, size, s.rc, s.err), (185000, 185000000, 0, ""))

    def test_a_byte_that_is_not_text_becomes_one_replacement_character(self):
        s = self._real("import sys; sys.stdout.buffer.write(b'a\\xffb\\n')")
        self.assertEqual((list(s), s.rc), (["a�b\n"], 0))

    def test_stderr_and_a_non_zero_exit_are_kept(self):
        s = self._real("import sys; print('out'); sys.stderr.write('warn'); sys.exit(3)")
        self.assertEqual((list(s), s.rc, s.err), (["out\n"], 3, "warn"))

    def test_a_command_that_does_not_exist_is_127(self):
        s = CE.Host().stream(["/nonexistent/hermes-test-binary"], 5)
        self.assertEqual((list(s), s.rc), ([], 127))

    def test_a_timeout_ends_the_lines_and_reads_as_124(self):
        s = self._real("import time; print('first', flush=True); time.sleep(60)", timeout=2)
        t0 = time.monotonic()
        self.assertEqual((list(s), s.rc), (["first\n"], 124))
        self.assertLess(time.monotonic() - t0, 30)

    def test_a_fake_runner_s_text_is_streamed_as_lines(self):
        s = CE.Host("/", lambda argv, timeout=60: (0, "a\nb\n", "w")).stream(["x"])
        self.assertEqual((list(s), s.rc, s.err), (["a\n", "b\n"], 0, "w"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestSearchJournal TestStream 2>&1 | tail -5`
Expected: FAIL/ERROR with `AttributeError: module 'collect_review_evidence' has no attribute '_search_journal'` (and `'Host' object has no attribute 'stream'`).

- [ ] **Step 3: Write the implementation**

In `collect-review-evidence.py`, add `tempfile, threading` to the import line (line 21, keep it alphabetical).

After `_run_real`, add:

```python
class _RealStream:
    """One command's stdout line by line, never held whole: `rc` and `err` are set once the lines
    have ended. Each line is decoded as UTF-8 with one replacement character for each byte, or
    cut-short sequence of bytes, that is not valid. On a timeout the child gets SIGTERM, the lines
    end and rc is 124. stderr goes to an unnamed temporary file, so a child that writes a lot of
    it cannot block on a full pipe."""
    ERR_CAP = 65536

    def __init__(self, argv, timeout):
        self._argv, self._timeout, self.rc, self.err = argv, timeout, None, ""

    def __iter__(self):
        errf = tempfile.TemporaryFile()
        try:
            p = subprocess.Popen(self._argv, stdout=subprocess.PIPE, stderr=errf)
        except FileNotFoundError:
            errf.close()
            self.rc, self.err = 127, f"{self._argv[0]}: not found"
            return
        timed_out = threading.Event()

        def stop():
            timed_out.set()
            p.terminate()                       # not kill(): as _run_real
        timer = threading.Timer(self._timeout, stop)
        timer.start()
        try:
            for raw in p.stdout:
                yield raw.decode("utf-8", errors="replace")
            try:
                p.wait(timeout=TERM_GRACE)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        finally:
            timer.cancel()
            if p.poll() is None:                # the caller stopped early, or raised: never leave the child behind
                p.kill()
                p.wait()
            p.stdout.close()
            errf.seek(0)
            err = errf.read(self.ERR_CAP).decode("utf-8", errors="replace")
            errf.close()
        self.rc, self.err = (124, f"{self._argv[0]}: timed out") if timed_out.is_set() else (p.returncode, err)


class _TextStream:
    """A fake runner's (rc, out, err) behind the same interface."""
    def __init__(self, result):
        self.rc, self._out, self.err = result

    def __iter__(self):
        return iter(self._out.splitlines(keepends=True))
```

In `class Host`, after `run_lossy`, add:

```python
    def stream(self, argv, timeout=60):
        """The same single command and limit as run_lossy(), read line by line instead of held
        whole (the journal with every field is about 184 MB at 35 days, measured 2026-10-13). A
        host built with a fake runner streams that runner's text."""
        return _RealStream(argv, timeout) if self._real else _TextStream(self._run(argv, timeout))
```

After `_journal_read`, add:

```python
# Every stored field of every entry (finding F59: `-o cat` prints the message alone, and a token in
# a command line is stored in `_CMDLINE`). `--all`: without it a field over 4096 bytes prints as null.
JOURNAL_ALL_FIELDS = ["-o", "json", "--all", "--no-pager"]
# The customer-id count skips a field only when the journal service writes it itself, no program
# can set it, and it holds a number or an identifier by construction: a ten-digit id can match a
# long number there by chance (design 2026-10-13, from the box's 70 field names). The credential
# search skips nothing.
CID_SKIP_FIELDS = frozenset({
    "__CURSOR", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "__SEQNUM", "__SEQNUM_ID",
    "_SOURCE_REALTIME_TIMESTAMP", "_SOURCE_MONOTONIC_TIMESTAMP",
    "_BOOT_ID", "_MACHINE_ID", "_STREAM_ID", "_SYSTEMD_INVOCATION_ID",
    "_PID", "_UID", "_GID", "_AUDIT_LOGINUID", "_AUDIT_SESSION", "_SYSTEMD_OWNER_UID"})
SEARCH_COUNTS = ("pattern_hits", "known_secret_hits", "credential_text_lines", "customer_id_lines",
                 "entries", "fields", "scanned_characters", "undecodable_characters")


def _byte_list(v):
    return isinstance(v, list) and all(isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 255 for b in v)


def _field_texts(value):
    """A journal field's value as the texts to search. systemd's JSON gives a string; a list of
    byte numbers for a value that is not text; a list of those two for a field set more than once.
    None for anything else (null: journalctl did not print the value), which the caller counts."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return None
    if _byte_list(value):
        return [bytes(value).decode("utf-8", errors="replace")]
    out = []
    for v in value:
        if isinstance(v, str):
            out.append(v)
        elif _byte_list(v):
            out.append(bytes(v).decode("utf-8", errors="replace"))
        else:
            return None
    return out


def _search_journal(host, argv, secrets, redactor=None, timeout=60, on_message=None):
    """One journalctl call (`argv` ends with JOURNAL_ALL_FIELDS), read entry by entry: every field
    value is parsed out of its JSON and searched for the credential patterns and the known secret
    values; with a redactor, each line of each value is also counted when it looks like
    Google-credential text or (outside CID_SKIP_FIELDS) holds a registered customer id.
    `on_message` gets each MESSAGE text. Counts only (SEARCH_COUNTS), never a value.
    CouldNotCheck, in fixed words: not root on a real host; a non-zero exit; anything on stderr
    (record R14: a damaged file is skipped with a warning and rc 0); an entry that is not a JSON
    object or a field printed as null (what was searched is then unknown)."""
    if _not_root_on_a_real_host(host):
        raise CouldNotCheck("the journal is read as root only")
    c = dict.fromkeys(SEARCH_COUNTS, 0)
    known = [s for s in set(secrets) if len(s) >= 8]
    unparsed = unprinted = 0
    stream = host.stream(argv, timeout)
    for line in stream:
        c["scanned_characters"] += len(line)
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            entry = None
        if not isinstance(entry, dict):
            unparsed += 1
            continue
        c["entries"] += 1
        for name, value in entry.items():
            texts = _field_texts(value)
            if texts is None:
                unprinted += 1
                continue
            c["fields"] += 1
            for t in texts:
                c["undecodable_characters"] += t.count("�")
                c["pattern_hits"] += len(CRED_TEXT_RE.findall(t))
                c["known_secret_hits"] += sum(t.count(s) for s in known)
                if redactor is not None:
                    for l in t.splitlines():
                        c["credential_text_lines"] += 1 if R.looks_like_credential_text(l) else 0
                        if name not in CID_SKIP_FIELDS and redactor.has_customer_id(l):
                            c["customer_id_lines"] += 1
                if on_message is not None and name == "MESSAGE":
                    on_message(t)
    if stream.rc != 0:
        raise CouldNotCheck(f"{argv[0]} exited {stream.rc}")
    if stream.err.strip():
        raise CouldNotCheck(f"{argv[0]} read the journal but wrote a warning on stderr: what it covered is unknown")
    if unparsed or unprinted:
        raise CouldNotCheck(f"{unparsed} journal entries did not parse and {unprinted} fields were not printed: "
                            "what was searched is unknown")
    return c
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py TestSearchJournal TestStream 2>&1 | tail -3`
Expected: `OK`.
Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?`
Expected: `rc=0`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py
git commit -m "collector: an all-fields journal search, read line by line (F59, not yet used)"
```

---

### Task 2: D2.3 and D10.7 use the all-fields search; checklist v1.20

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`d2_3`, `_journal`, `_journal_leaks`, `d10_7`, the comment above `JOURNAL_SCAN_TIMEOUT`)
- Modify: `infra/hermes-agent/bin/collect-review-evidence.test.py` (`FakeHost._fake`, named assertions)
- Modify: `infra/hermes-agent/bin/summarize-review-bundle.py`, `summarize-review-bundle.test.py`
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`, `REPORT-TEMPLATE.md`
- Modify: `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

**Interfaces:**
- Consumes: `_search_journal`, `JOURNAL_ALL_FIELDS`, `SEARCH_COUNTS` (Task 1).
- Produces (bundle shape):
  - D2.3 `data`: `journal` (`pattern_hits`, `known_secret_hits`), `entries`, `fields`, `scanned_characters`, `undecodable_characters`, `oldest_entry_read`.
  - D10.7 `data`: as today, plus `journal_read: {"broker": R, "runner": R}` with `R = {"entries", "fields", "undecodable_characters"}`. `broker_journal` and `runner_journal` keep exactly their four keys.
  - `_unit_search(host, unit, secrets, redactor, on_message=None)` for Plan B.

- [ ] **Step 1: The fake host prints journal fixtures as entries**

The existing tests give the fake host a journal as plain text. In `collect-review-evidence.test.py`, add above `class FakeHost` and change `_fake`:

```python
def _as_entries(text):
    """A test's journal text as `journalctl -o json` prints it: one entry per line with the line
    as MESSAGE. A line that is already a JSON object is left as it is."""
    out = []
    for line in text.splitlines():
        try:
            is_entry = isinstance(json.loads(line), dict)
        except ValueError:
            is_entry = False
        out.append(line if is_entry else json.dumps({"MESSAGE": line}, ensure_ascii=False))
    return "".join(l + "\n" for l in out)
```

```python
    def _fake(self, argv, timeout=60):
        self.calls.append(argv)
        for prefix, result in self.outputs.items():
            if tuple(argv[:len(prefix)]) == prefix:
                if result[0] == 0 and argv[0] == "journalctl" and "--all" in argv:
                    return (0, _as_entries(result[1]), result[2])
                return result
        return (127, "", "not found")
```

- [ ] **Step 2: Write the failing tests**

Add to `class TestJournalReach`:

```python
    def test_d2_3_reads_every_field_in_one_call(self):
        self.outputs[("journalctl", "-o")] = (0, _e(MESSAGE="Started.", _CMDLINE=f"tool {self.SECRET}"), "")
        self.outputs[_oldest_key()] = (0, _entry(1760000000), "")
        host = self.host()
        d = CE.d2_3(host, {"secrets": [self.SECRET]})
        self.assertEqual(d["journal"], {"pattern_hits": 0, "known_secret_hits": 1})
        self.assertEqual((d["entries"], d["fields"]), (1, 2))
        searches = [c for c in host.calls if "--all" in c]
        self.assertEqual(searches, [["journalctl", "-o", "json", "--all", "--no-pager"]])

    def test_d2_3_at_the_35_day_size_finds_what_is_at_the_far_end(self):
        """185,000 entries of about 1,000 characters (M1 of 2026-10-13, scaled to 35 days), never held whole."""
        secret, n = self.SECRET, 185000
        filler = _e(MESSAGE="x" * 600, _CMDLINE="/usr/bin/python3 " + "y" * 300, _PID="1234")

        class Lines:
            rc, err = 0, ""

            def __iter__(self):
                yield _e(MESSAGE="first", _CMDLINE=f"leak {secret}")
                for _ in range(n):
                    yield filler
                yield _e(COMMAND=f"GOOGLE_ADS_REFRESH_TOKEN={TOKEN}")

        class Big(CE.Host):
            def stream(self, argv, timeout=60):
                return Lines()
        host = Big(self.root, lambda argv, timeout=60: (0, _entry(1760000000), ""))
        t0 = time.monotonic()
        d = CE.d2_3(host, {"secrets": [secret]})
        self.assertEqual(d["journal"], {"pattern_hits": 1, "known_secret_hits": 1})
        self.assertEqual(d["entries"], n + 2)
        self.assertGreater(d["scanned_characters"], 150 * 1000 * 1000)
        self.assertLess(time.monotonic() - t0, CE.JOURNAL_SCAN_TIMEOUT / 3)
```

Add to the class that holds `test_d10_7_reads_both_units_over_the_same_window` (the one with `_journal`):

```python
    def test_d10_7_counts_a_customer_id_in_the_runner_s_command_line_field(self):
        self._journal(runner=_e(MESSAGE="Audit complete.", _CMDLINE="python3 tool --customer 1234567890",
                                __REALTIME_TIMESTAMP="1761234567890123"))
        d = self._item("D10.7")["data"]
        self.assertEqual(d["runner_journal"]["customer_id_lines"], 1)
        self.assertEqual(d["journal_read"]["runner"], {"entries": 1, "fields": 3, "undecodable_characters": 0})
        self.assertEqual(set(d["journal_read"]), {"broker", "runner"})

    def test_d10_7_reads_each_unit_with_every_field(self):
        host = self.host()
        CE.collect(host, self.KEY)
        calls = [c for c in host.calls if c[:2] == ["journalctl", "-u"] and "--all" in c]
        self.assertEqual([c[3:] for c in calls], [["--since", "-30d", "-o", "json", "--all", "--no-pager"]] * 2)
```

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py 2>&1 | tail -4`
Expected: the four new tests FAIL (`KeyError: 'entries'`, `'journal_read'`, and the call lists differ).

- [ ] **Step 3: Write the implementation**

Replace the comment above `JOURNAL_SCAN_TIMEOUT` with:

```python
# The search of the whole journal with every field measured 4 s at 7.9 days on the box (2026-10-13:
# 41,571 entries, 41.3 MB). Scaled to 35 days that is 18 s; times 10 for margin is 180 s; the limit
# is never under 300 s.
```

Replace `d2_3`:

```python
def d2_3(host, ctx):
    """Every stored field of every entry journalctl shows, as far back as it reaches (D2.4 judges
    how far). The oldest entry is read AFTER the search: entries only ever leave, so the search
    reached at least that far. An oldest entry that cannot be read is could-not-check; the counts
    of the search stay."""
    c = _search_journal(host, ["journalctl", *JOURNAL_ALL_FIELDS], ctx.get("secrets", []),
                        timeout=JOURNAL_SCAN_TIMEOUT)
    return {"journal": {k: c[k] for k in ("pattern_hits", "known_secret_hits")},
            "entries": c["entries"], "fields": c["fields"], "scanned_characters": c["scanned_characters"],
            "undecodable_characters": c["undecodable_characters"], "oldest_entry_read": _oldest_entry_or_unknown(host)}
```

Replace `_journal` and `_journal_leaks`:

```python
LEAK_COUNTS = ("credential_text_lines", "customer_id_lines", "pattern_hits", "known_secret_hits")
READ_COUNTS = ("entries", "fields", "undecodable_characters")


def _unit_search(host, unit, secrets, redactor, on_message=None):
    """What a unit's journal of the last 30 days must hold none of, in every stored field: lines
    of Google-credential-shaped text, lines with a registered customer id, credential patterns and
    the installed secret values themselves. Counts only, never a line."""
    return _search_journal(host, ["journalctl", "-u", unit, "--since", "-30d", *JOURNAL_ALL_FIELDS],
                           secrets, redactor, on_message=on_message)
```

In `d10_7`, replace the two `_journal(...)` reads, the `for line in broker.splitlines():` header and the `return` with:

```python
    secrets = sorted({s for s in ctx.get("secrets", []) if len(s) >= 8})
    lines = []
    broker = _unit_search(host, f"hermes-app-broker@{APP}", secrets, ctx["redactor"],
                          on_message=lambda t: lines.extend(t.splitlines()))
    runner = _unit_search(host, f"hermes-app-runner@{APP}", secrets, ctx["redactor"])
    oldest = {label: _oldest_entry_or_unknown(host, ("-u", unit, "--since", "-30d"))
              for label, unit in JOURNAL_UNITS.items()}
    counts, notes, other = {}, {}, 0
    for line in lines:
```

(the loop body is unchanged; delete the later `secrets = sorted(...)` line and keep its comment above the new one) and:

```python
    return {"journal_counts": counts, "note_counts": notes, "other_lines": other,
            "broker_journal": {k: broker[k] for k in LEAK_COUNTS},
            "runner_journal": {k: runner[k] for k in LEAK_COUNTS},
            "journal_read": {"broker": {k: broker[k] for k in READ_COUNTS},
                             "runner": {k: runner[k] for k in READ_COUNTS}},
            "known_secrets_checked": len(secrets), "oldest_entry_read": oldest}
```

Update `d10_7`'s docstring first sentence to: `Counts only, never a line or a field: the journal names clients and request ids by design.`

Delete `_journal_read`, `_journal` and `_journal_leaks`: nothing calls them any more (`git grep -n "_journal_read(\|_journal(\|_journal_leaks(" infra/hermes-agent/bin/collect-review-evidence.py` prints nothing). `_count_cred_text` stays (D2.2 uses it) and so does `Host.run_lossy` (it has its own tests).

- [ ] **Step 4: Update the assertions the new shape changes**

Run: `python3 infra/hermes-agent/bin/collect-review-evidence.test.py 2>&1 | grep -E "^(FAIL|ERROR)" | sort`

Each fixture line `Started.` is now the 24-character line `{"MESSAGE": "Started."}` plus its newline. Change exactly these, in `TestJournalReach` unless named otherwise:

- `test_d2_3_reports_the_size_searched_and_the_oldest_entry_read_after_the_search`: the expected dict becomes `{"journal": {"pattern_hits": 0, "known_secret_hits": 0}, "entries": 3, "fields": 3, "scanned_characters": 72, "undecodable_characters": 0, "oldest_entry_read": "2025-10-09T08:53:20Z"}`.
- Every `scanned_characters` expected as `9` (five places: the oldest-entry test and its sub-case, the two root-only tests, `test_d2_3_empty_stderr_at_rc_0_reads_as_before`) becomes `24`.
- `test_d2_3_finds_a_secret_and_a_pattern_at_the_far_end_of_35_days_of_journal`: `self.assertEqual(d["scanned_characters"], len(text))` becomes `self.assertEqual(d["scanned_characters"], len(_as_entries(text)))`.
- `test_d10_7_runner_journal_installed_secret_value_is_counted_under_the_runner_key`: unchanged (the four keys stay).
- `test_d10_7_reads_both_units_over_the_same_window`: unchanged.
- `_real_host` (a host that counts as the real one): the real host now streams through `_RealStream`, so it must be patched too, or the test would start the machine's own `journalctl`. Replace it with:

```python
    def _real_host(self):
        """A host that counts as the real one (built with the real runner) but whose commands are the fake's."""
        host = self.host()
        host._real = True
        fake = host._fake
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(CE, "_run_real", lambda argv, timeout=60, errors="strict": fake(argv, timeout)))
        stack.enter_context(mock.patch.object(CE, "_RealStream", lambda argv, timeout: CE._TextStream(fake(argv, timeout))))
        return host, stack
```

- `test_d2_3_searches_past_a_byte_that_is_not_text_and_says_how_many_were_replaced`: the child must print entries, and the stream must be the patched one. Replace the test with:

```python
    BAD_BYTE_ENTRIES = ["-c", "import sys; sys.stdout.buffer.write(b'{\"MESSAGE\": \"ok\"}\\n"
                              "{\"MESSAGE\": \"\\xff GOOGLE_ADS_REFRESH_TOKEN=" + TOKEN + "\"}\\n')"]

    def test_d2_3_searches_past_a_byte_that_is_not_text_and_says_how_many_were_replaced(self):
        argv = [sys.executable, *self.BAD_BYTE_ENTRIES]
        real = CE._RealStream
        # the real stream is reached through Host(root) with no fake: patch only the program that is started
        with mock.patch.object(CE, "_RealStream", lambda a, timeout: real(argv, timeout)), \
                mock.patch.object(CE, "_run_real", lambda a, timeout=60, errors="strict": (0, "", "")), \
                mock.patch.object(os, "geteuid", return_value=0):               # this host is the real one: root only
            d = CE.d2_3(CE.Host(self.root), {"secrets": []})
        self.assertEqual((d["journal"]["pattern_hits"], d["undecodable_characters"], d["entries"]), (1, 1, 2))
```

  (`BAD_BYTE_CHILD` and `test_the_strict_runner_raises_on_a_byte_that_is_not_text_and_the_lossy_one_replaces_it` stay as they are.)
- `summarize-review-bundle.test.py`, `test_the_leak_keys_are_the_collectors`: `set(CE._journal_leaks("", [], NoIds))` becomes `set(CE.LEAK_COUNTS)`; delete the `NoIds` class there.

A FAIL or ERROR outside this list, after these edits: STOP and report it with its name; do not edit that test.

- [ ] **Step 5: The summary tool**

In `summarize-review-bundle.py`:

```python
_READ = fixed({k: num for k in ("entries", "fields", "undecodable_characters")})
```

(after `_LEAKS`), then in `SCHEMA`: D2.3 gains `"entries": num, "fields": num`; D10.7 gains `"journal_read": fixed({"broker": _READ, "runner": _READ})`.

In `summarize-review-bundle.test.py`, the `bundle()` fixture: D2.3's data gains `"entries": 185000, "fields": 5000000`; D10.7's data gains `"journal_read": {"broker": {"entries": 40, "fields": 900, "undecodable_characters": 0}, "runner": {"entries": 90, "fields": 2000, "undecodable_characters": 0}}`. Add:

```python
    def test_the_all_fields_counts_are_printed(self):
        text = run(json.dumps(bundle()))[1]
        for want in ("entries: 185000", "fields: 5000000",
                     "journal_read: {broker: {entries: 40, fields: 900, undecodable_characters: 0}, "
                     "runner: {entries: 90, fields: 2000, undecodable_characters: 0}}"):
            self.assertIn(want, text)
```

Run: `python3 infra/hermes-agent/bin/summarize-review-bundle.test.py 2>&1 | tail -3` → `OK`. If the printed form of a nested `fixed` differs from the string above, copy the tool's own form into the test (the tool decides the form; the test pins it).

- [ ] **Step 6: The checklist, the template, the findings document**

`CHECKLIST.md`:

- `version: 1.19` → `version: 1.20`. At the end of the header paragraph's version notes add: `(v1.20: D2.3 and D10.7 search every stored field of a journal entry, not the message alone: finding F59, fixed. D10.7 names the fields its customer-id count skips. D4.6 reports the journal service's start.)`
- D2.3 **claim**: `for the MESSAGE TEXT of every entry` → `for EVERY STORED FIELD of every entry`.
- D2.3 **expected**: replace the sentence that starts `` `scanned_characters` is the size of that message text `` up to `and `oldest_entry_read`` with: `` `scanned_characters` is the size of the text read, every field included (`journalctl -o json --all`, one call, read entry by entry; 41,337,888 at 7.9 days on this box, 2026-10-13, about 5.2 million a day; it grows with the retention to about 184 million; the number jumped once, between review #10 and review #11, when the message-only read ended), `entries` and `fields` are how many entries and field values were searched, and `oldest_entry_read` ``. After `The search is given 300 seconds.` add: `An entry that is not a JSON object, or a field that journalctl prints as null, makes the whole item `could-not-check`: what was searched is then unknown.`
- D2.3 **pass rule**: `under about 300 thousand for each day ... (this box showed about 660 thousand a day on 2026-10-10: 4,630,823 characters over 7 days)` → `under about 2.5 million for each day between `oldest_entry_read` and the collection (this box showed about 5.2 million a day on 2026-10-13)`. Replace the sentence `What this item cannot show (record R14): fields other than the message (...); a credential with an invalid byte inside it (...)` with: `What this item cannot show (record R14): a credential with an invalid byte inside it (each bad byte is replaced before the search, so a credential beside one is still found); journal namespaces other than the default (no unit here uses one), and the entries that left the journal before the search.` Delete the last sentence about a message of 100 thousand characters.
- D10.7 **expected**, after the sentence on `broker_journal` and `runner_journal`: `Both are searched in every stored field (as D2.3). `customer_id_lines` skips the fields the journal service writes itself as numbers or identifiers, where a ten-digit id can match by chance: `__CURSOR`, `__REALTIME_TIMESTAMP`, `__MONOTONIC_TIMESTAMP`, `__SEQNUM`, `__SEQNUM_ID`, `_SOURCE_REALTIME_TIMESTAMP`, `_SOURCE_MONOTONIC_TIMESTAMP`, `_BOOT_ID`, `_MACHINE_ID`, `_STREAM_ID`, `_SYSTEMD_INVOCATION_ID`, `_PID`, `_UID`, `_GID`, `_AUDIT_LOGINUID`, `_AUDIT_SESSION`, `_SYSTEMD_OWNER_UID`; the other three counts skip nothing. `journal_read` gives, for `broker` and `runner`, the `entries` and `fields` searched and `undecodable_characters` (judged as in D2.3).`
- D10.7 **pass rule**: add `A `customer_id_lines` hit in a size or usage figure a program writes (`CPU_USAGE_NSEC`, `MAX_USE` and the like) is a FAIL unless the operator shows it is a coincidence of digits.`

`REPORT-TEMPLATE.md`, the "Journal search (D2.3)" line: after `` `scanned_characters` `<number>` `` add `` , `entries` `<number>` ``. The "Unit journals (D10.7)" line: add `` ; `journal_read` `<as the bundle shows it>` ``.

`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`: in F59's entry add one line: `2026-10-13: fixed in code (the leak search reads every stored field; plan 2026-10-13-review-10-follow-ups, Tasks 1 and 2). Judged by review #11.`

- [ ] **Step 7: Run everything and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`.
Run: `python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo rc=$?` → `rc=0`.

```bash
git add infra/hermes-agent/bin infra/hermes-agent/deploy/security-review docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md
git commit -m "review: D2.3 and D10.7 search every stored field of the journal (F59); checklist v1.20"
```

---

### Task 3: the bundle is owner-only

**Files:**
- Modify: `infra/hermes-agent/bin/review_lib.py`, `review_lib.test.py`
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`_main`), `collect-review-evidence-laptop.py` (before its final `print`)
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (collection steps 3 and 5)

**Interfaces:**
- Produces: `review_lib.restrict_output(stream) -> bool`: `True` when the stream is not a regular file or is now `0600`; `False` when it is a regular file whose mode could not be set.

- [ ] **Step 1: Write the failing tests**

In `review_lib.test.py`:

```python
class TestRestrictOutput(unittest.TestCase):
    def test_a_redirected_file_becomes_owner_only_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bundle.json")
            fd = os.open(p, os.O_WRONLY | os.O_CREAT, 0o664)
            os.fchmod(fd, 0o664)                       # whatever the umask
            with os.fdopen(fd, "w") as f:
                self.assertTrue(R.restrict_output(f))
                self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
                self.assertEqual(os.fstat(f.fileno()).st_size, 0)

    def test_a_pipe_and_a_stream_without_a_descriptor_are_left_alone(self):
        r, w = os.pipe()
        with os.fdopen(r), os.fdopen(w, "w") as f:
            self.assertTrue(R.restrict_output(f))
        self.assertTrue(R.restrict_output(io.StringIO()))

    def test_a_file_whose_mode_cannot_be_set_is_refused(self):
        with tempfile.TemporaryFile("w") as f, mock.patch("os.fchmod", side_effect=PermissionError):
            self.assertFalse(R.restrict_output(f))
```

(`review_lib.test.py` imports `hashlib, json, os, sys, tempfile, unittest` today: add `io, stat` and `from unittest import mock`.)

In `collect-review-evidence.test.py`, directly after `test_clean_credential_control_credentials_only_exits_0` (same class, same fixture: that run exits 0):

```python
    def test_an_output_file_that_cannot_be_made_owner_only_gets_nothing_written(self):
        with mock.patch.object(R, "restrict_output", return_value=False) as ro, \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, out.getvalue()), (2, ""))
        self.assertIn("owner-only", err.getvalue())
        ro.assert_called_once()

    def test_the_output_is_restricted_before_it_is_written(self):
        order = []
        buf = io.StringIO()
        buf.write = lambda text, w=buf.write: (order.append("write"), w(text))[1]
        with mock.patch.object(R, "restrict_output", side_effect=lambda s: order.append("restrict") or True), \
                contextlib.redirect_stdout(buf):
            rc = CE.main(["--credentials-only"], host=self.host())
        self.assertEqual((rc, order[0]), (0, "restrict"))
        self.assertIn("write", order)
```

Run both test files → FAIL (`AttributeError: ... 'restrict_output'`).

- [ ] **Step 2: Write the implementation**

`review_lib.py` (its import line is `import datetime, hashlib, hmac, json, os, re`: add `io, stat`):

```python
def restrict_output(stream):
    """A bundle redirected into a file (`> bundle-box.json`) is created by the shell with the
    shell's umask: 0664 at review #10. Called before the first byte is written: when `stream` is
    a regular file, it is set to 0600. True when there was nothing to do (a pipe, a terminal, a
    stream without a descriptor) or the mode is now 0600; False when a regular file's mode could
    not be set, and the caller then prints nothing."""
    try:
        fd = stream.fileno()
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return True
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return True
    try:
        os.fchmod(fd, 0o600)
        return stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
    except OSError:
        return False
```

`collect-review-evidence.py`, `_main`, immediately before `print(text)`:

```python
    if not R.restrict_output(sys.stdout):
        print("collect-review-evidence: the output file could not be made owner-only: nothing written",
              file=sys.stderr)
        return 2
```

`collect-review-evidence-laptop.py`, immediately before the final `print(json.dumps({"schema": 1, "kind": "laptop", ...`:

```python
    if not R.restrict_output(sys.stdout):
        print("collect-review-evidence-laptop: the output file could not be made owner-only: nothing written",
              file=sys.stderr)
        return 2
```

- [ ] **Step 3: The runbook**

`deploy/BRING-UP.md`, the review's collection steps: at the end of step 3's first paragraph add: `The collector sets the file it is redirected into to mode 0600 before it writes (owner: you). Check: `stat -c %a ~/bundle-box.json` → `600`.` Step 5 `Copy the box bundle to the laptop's `security-reviews/`, and delete it from the box.` becomes: `Copy the box bundle to the laptop's `security-reviews/` (`chmod 600` the copy), and remove it from the box with `shred -u ~/bundle-box.json` (best effort on a virtual disk), then `ls ~/bundle-box.json` → `No such file or directory`.`

- [ ] **Step 4: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`.

```bash
git add infra/hermes-agent/bin infra/hermes-agent/deploy/BRING-UP.md
git commit -m "review: both collectors make a redirected bundle owner-only before writing"
```

---

### Task 4: D4.6 reports the journal service's start

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (above `d4_6`, and `d4_6`)
- Modify: `infra/hermes-agent/bin/collect-review-evidence.test.py`, `summarize-review-bundle.py`, `summarize-review-bundle.test.py`
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`

**Interfaces:**
- Produces: `OTHER_STARTS = ("boot", "docker", "systemd-journald", "gateway-container")`; D4.6 `started_at` and `started_after_last_pass` gain the key `systemd-journald`.

- [ ] **Step 1: Write the failing tests**

In the D4.6 test class of `collect-review-evidence.test.py` (it defines `START`), add:

```python
    def test_the_journal_service_s_start_is_reported_and_compared_with_the_last_pass(self):
        self.outputs[("systemctl", "show", "systemd-journald", "-p", "ActiveEnterTimestamp", "--value")] = \
            (0, "Mon 2026-10-12 09:10:11 UTC\n", "")
        with mock.patch.object(CE, "LAST_PASS_COLLECTED_AT", "2026-10-12T13:39:00Z"):
            d = CE.d4_6(self.host(), {})
        self.assertEqual(d["started_at"]["systemd-journald"], "2026-10-12T09:10:11Z")
        self.assertIs(d["started_after_last_pass"]["systemd-journald"], False)
        self.assertNotIn("systemd-journald", d["files_newer_than_start"])
        self.assertEqual(set(d["started_at"]), set(CE.SERVICE_FILES) | set(CE.OTHER_STARTS))
```

In `summarize-review-bundle.test.py`, `test_services_and_unit_labels`: the `START_KEYS` line becomes
`self.assertEqual(SB.START_KEYS, frozenset(CE.SERVICE_FILES) | frozenset(CE.OTHER_STARTS))`.

Run → FAIL (`KeyError: 'systemd-journald'`, `AttributeError: OTHER_STARTS`).

- [ ] **Step 2: Write the implementation**

`collect-review-evidence.py`, after `SERVICE_FILES`:

```python
# The other starts D4.6 reports. The journal service since v1.20 (review #10, entry 8): its restart
# changes what the journal holds from then on, and an automatic update can cause one.
OTHER_STARTS = ("boot", "docker", "systemd-journald", "gateway-container")
```

In `d4_6`, `starts` becomes:

```python
    starts = {"boot": _boot_at(host), "docker": _unit_started_at(host, "docker"),
              "systemd-journald": _unit_started_at(host, "systemd-journald"),
              **{u: _unit_started_at(host, u) for u in SERVICE_FILES},
              "gateway-container": _gateway_started_at(host)}
```

`summarize-review-bundle.py`: `START_KEYS = frozenset(SERVICES) | {"boot", "docker", "systemd-journald", "gateway-container"}`.

`CHECKLIST.md`, D4.6 **claim**: `when the host, Docker, the three long-running Hermes services and the gateway container last started` → `when the host, Docker, the journal service, the three long-running Hermes services and the gateway container last started`. **expected**: in the list after `` `docker`, `` add `` `systemd-journald`, ``; after `A restart between two reviews is normal:` add `an automatic update of systemd restarts the journal service,`. No pass-rule change: a `true` for it is explained like any other.

- [ ] **Step 3: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`. (An existing D4.6 test that compares the whole `started_at` dict gains the key `systemd-journald` with the value its fake `systemctl` returns; update only that expected dict.)

```bash
git add infra/hermes-agent/bin infra/hermes-agent/deploy/security-review/CHECKLIST.md
git commit -m "review: D4.6 reports the journal service's start"
```

---

### Task 5: search the leftover journal directory once, then remove it

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py` (`--other-journals`), its test
- Create: `infra/hermes-agent/bin/remove-other-journal-dirs.py`, `remove-other-journal-dirs.test.py`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (new section after "The journal's retention")

**Interfaces:**
- Consumes: `_search_journal`, `JOURNAL_ALL_FIELDS`, `SEARCH_COUNTS`, `JOURNAL_DIR`, `installed_credentials`, `other_credentials`.
- Produces: `other_journals(host, ctx, secrets) -> {"directories": int, "files": int, "bytes": int, "search": {SEARCH_COUNTS}, "known_secrets_checked": int}`; the flag `--other-journals`; the script `remove-other-journal-dirs.py --expect-dirs N --expect-files N --expect-bytes N [--apply] [--root DIR]` (exit 0 done or would-do, 1 refused, 2 usage).

- [ ] **Step 1: Write the failing tests (collector)**

```python
class TestOtherJournals(Base):
    MID, OTHER = "a" * 32, "b" * 32

    def setUp(self):
        super().setUp()
        self._w("/etc/machine-id", self.MID + "\n")
        self._w(f"/var/log/journal/{self.MID}/system.journal", "x" * 10)
        self._w(f"/var/log/journal/{self.OTHER}/system.journal", "y" * 4096)

    def test_only_the_other_directory_is_searched_and_only_counts_come_back(self):
        self.outputs[("journalctl", "-D", "/var/log/journal/" + self.OTHER)] = \
            (0, _e(MESSAGE="boot", _CMDLINE="tool --customer 1234567890"), "")
        host = self.host()
        d = CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertEqual((d["directories"], d["files"], d["bytes"]), (1, 1, 4096))
        self.assertEqual(d["search"]["customer_id_lines"], 1)
        self.assertEqual(set(d["search"]), set(CE.SEARCH_COUNTS))
        self.assertEqual([c[:3] for c in host.calls if c[0] == "journalctl"],
                         [["journalctl", "-D", "/var/log/journal/" + self.OTHER]])
        self.assertNotIn(self.OTHER, json.dumps(d)); self.assertNotIn(self.MID, json.dumps(d))

    def test_no_other_directory_is_zero_and_nothing_is_read(self):
        shutil.rmtree(os.path.join(self.root, "var/log/journal", self.OTHER))
        host = self.host()
        d = CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertEqual((d["directories"], d["files"], d["search"]["entries"]), (0, 0, 0))

    def test_a_linked_directory_is_not_followed(self):
        os.symlink("/etc", os.path.join(self.root, "var/log/journal", "c" * 32))
        host = self.host()
        self.outputs[("journalctl", "-D")] = (0, "", "")
        self.assertEqual(CE.other_journals(host, CE.context(host, self.KEY), [])["directories"], 1)

    def test_a_read_that_warns_is_could_not_check_without_the_directory_s_name(self):
        self.outputs[("journalctl", "-D")] = (0, "", f"Journal file /var/log/journal/{self.OTHER}/x is truncated")
        host = self.host()
        with self.assertRaises(CE.CouldNotCheck) as cm:
            CE.other_journals(host, CE.context(host, self.KEY), [])
        self.assertNotIn(self.OTHER, str(cm.exception))
```

Run → FAIL (`AttributeError: ... 'other_journals'`).

- [ ] **Step 2: Write the implementation (collector)**

After `_journal_usage`:

```python
def other_journals(host, ctx, secrets):
    """The one-time search of what D2.3 never reads: every real directory under /var/log/journal
    other than the machine's own (a server image can leave the journal of the machine it was
    built on). Each is read with `journalctl -D` and every stored field is searched. Counts only:
    the directories' names are machine ids and go into the command, never into the result.
    Raises CouldNotCheck when a read is not whole, ValueError/OSError when the layout cannot be read."""
    with open(host.path("/etc/machine-id")) as f:
        mid = f.read(64).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise ValueError("machine-id")
    base = host.path(JOURNAL_DIR)
    if not stat.S_ISDIR(os.lstat(base).st_mode):
        raise ValueError("journal directory path")
    names = sorted(n for n in os.listdir(base)
                   if n != mid and stat.S_ISDIR(os.lstat(os.path.join(base, n)).st_mode))
    known = sorted({s for s in secrets if len(s) >= 8})
    total, files, size = dict.fromkeys(SEARCH_COUNTS, 0), 0, 0
    for n in names:
        for root, _, fs in os.walk(os.path.join(base, n)):
            for name in fs:
                files += 1
                size += os.lstat(os.path.join(root, name)).st_size
        c = _search_journal(host, ["journalctl", "-D", JOURNAL_DIR + "/" + n, *JOURNAL_ALL_FIELDS],
                            known, ctx["redactor"], timeout=JOURNAL_SCAN_TIMEOUT)
        for k in total:
            total[k] += c[k]
    return {"directories": len(names), "files": files, "bytes": size, "search": total,
            "known_secrets_checked": len(known)}
```

In `main`, add to the exclusive group: `g.add_argument("--other-journals", action="store_true")`. In `_main`, change `if not (a.fingerprint_only or a.credentials_only) and fp_key is None:` to `if not (a.fingerprint_only or a.credentials_only or a.other_journals) and fp_key is None:`, and add this branch before `else: out, secrets, _ = _collect(host, fp_key)`:

```python
    elif a.other_journals:
        try:
            infos, secrets, unparsed, unreadable = installed_credentials(host)
            other, other_secrets, other_failed = other_credentials(host)
            if other_failed or unparsed or unreadable:
                raise CouldNotCheck("the installed secret values could not all be loaded")
            secrets = secrets + other_secrets
            out = {"schema": 1, "kind": "other-journals", "collected_at": R.utc_now(),
                   **other_journals(host, ctx, secrets)}
        except (CouldNotCheck, OSError, ValueError) as e:
            reason = str(e) if isinstance(e, CouldNotCheck) else type(e).__name__
            print(f"collect-review-evidence: other journals: {reason}", file=sys.stderr)
            return 2
```

Add a `main` test:

```python
    def test_the_other_journals_mode_prints_counts_and_needs_no_key(self):
        self.outputs[("journalctl", "-D")] = (0, _e(MESSAGE="boot"), "")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = CE.main(["--other-journals"], host=self.host())
        d = json.loads(out.getvalue())
        self.assertEqual((rc, d["kind"], d["directories"], d["search"]["entries"]), (0, "other-journals", 1, 1))
        self.assertNotIn(self.OTHER, out.getvalue())
```

(`Base`'s fixture is the one `test_clean_credential_control_credentials_only_exits_0` passes with, so the secrets load.)

- [ ] **Step 3: Write the failing tests (removal script)**

Create `infra/hermes-agent/bin/remove-other-journal-dirs.test.py`:

```python
#!/usr/bin/env python3
import contextlib, importlib.util, io, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rm_other", os.path.join(HERE, "remove-other-journal-dirs.py"))
RM = importlib.util.module_from_spec(spec); spec.loader.exec_module(RM)
MID, OTHER = "a" * 32, "b" * 32


class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.j = os.path.join(self.root, "var/log/journal")
        os.makedirs(os.path.join(self.root, "etc"))
        with open(os.path.join(self.root, "etc/machine-id"), "w") as f:
            f.write(MID + "\n")
        for d, n in ((MID, 10), (OTHER, 4096)):
            os.makedirs(os.path.join(self.j, d))
            with open(os.path.join(self.j, d, "system.journal"), "w") as f:
                f.write("x" * n)

    def run_(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = RM.main(["--root", self.root, *args])
        return rc, out.getvalue()

    def left(self):
        return sorted(os.listdir(self.j))

    def test_without_apply_it_only_says_what_it_would_do(self):
        rc, out = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096")
        self.assertEqual((rc, self.left()), (0, [MID, OTHER]))
        self.assertIn("would remove: directories 1 | files 1 | bytes 4096", out)
        self.assertNotIn(OTHER, out); self.assertNotIn(MID, out)

    def test_with_apply_and_the_expected_counts_it_removes_the_other_directory_only(self):
        rc, out = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
        self.assertEqual((rc, self.left()), (0, [MID]))
        self.assertIn("removed: directories 1 | files 1 | still there: 0", out)
        self.assertTrue(os.path.exists(os.path.join(self.j, MID, "system.journal")))

    def test_any_other_count_removes_nothing(self):
        for args in (("2", "1", "4096"), ("1", "2", "4096"), ("1", "1", "4097")):
            with self.subTest(args=args):
                rc, out = self.run_("--expect-dirs", args[0], "--expect-files", args[1],
                                    "--expect-bytes", args[2], "--apply")
                self.assertEqual((rc, self.left()), (1, [MID, OTHER]))
                self.assertIn("STOPPED: nothing was removed", out)

    def test_a_link_or_a_sub_directory_inside_removes_nothing(self):
        for make in (lambda d: os.symlink("/etc/passwd", os.path.join(d, "l")), lambda d: os.mkdir(os.path.join(d, "sub"))):
            self.setUp()
            make(os.path.join(self.j, OTHER))
            rc, _ = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
            self.assertEqual((rc, self.left()), (1, [MID, OTHER]))

    def test_a_linked_other_directory_or_a_bad_machine_id_removes_nothing(self):
        os.symlink(os.path.join(self.j, MID), os.path.join(self.j, "c" * 32))
        rc, _ = self.run_("--expect-dirs", "2", "--expect-files", "2", "--expect-bytes", "4106", "--apply")
        self.assertEqual(rc, 1)
        with open(os.path.join(self.root, "etc/machine-id"), "w") as f:
            f.write("not-an-id\n")
        rc, _ = self.run_("--expect-dirs", "1", "--expect-files", "1", "--expect-bytes", "4096", "--apply")
        self.assertEqual((rc, MID in self.left()), (1, True))


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 infra/hermes-agent/bin/remove-other-journal-dirs.test.py` → ERROR (no such file).

- [ ] **Step 4: Write the removal script**

Create `infra/hermes-agent/bin/remove-other-journal-dirs.py` (mode 755):

```python
#!/usr/bin/env python3
"""Remove the journal directories under /var/log/journal that are not this machine's own. Once.

  sudo python3 bin/remove-other-journal-dirs.py --expect-dirs 1 --expect-files 1 --expect-bytes 8388608 [--apply]

A server image can leave the journal of the machine it was built on: the journal service never
trims it and journalctl never reads it. Search it first (collect-review-evidence.py
--other-journals), then remove it with this.

All or nothing. Every entry under /var/log/journal other than the machine's own must be a real
directory (not a link) holding regular files only, and their numbers and total size must equal
the three expected values; otherwise nothing is removed. Without --apply it only says what it
would do. Prints counts only: never a directory's name (a machine id) or a path. Stdlib only."""
import argparse, os, re, stat, sys


def _plan(root):
    """[(directory, [file, ...])], total bytes; ValueError when anything is not as described."""
    with open(os.path.join(root, "etc/machine-id")) as f:
        mid = f.read(64).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise ValueError("machine id")
    base = os.path.join(root, "var/log/journal")
    if not stat.S_ISDIR(os.lstat(base).st_mode) or not stat.S_ISDIR(os.lstat(os.path.join(base, mid)).st_mode):
        raise ValueError("journal directory")
    plan, size = [], 0
    for n in sorted(os.listdir(base)):
        if n == mid:
            continue
        d = os.path.join(base, n)
        if not stat.S_ISDIR(os.lstat(d).st_mode):
            raise ValueError("an entry that is not a real directory")
        files = []
        for name in sorted(os.listdir(d)):
            st = os.lstat(os.path.join(d, name))
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("an entry that is not a regular file")
            files.append(os.path.join(d, name))
            size += st.st_size
        plan.append((d, files))
    return plan, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--expect-dirs", type=int, required=True)
    ap.add_argument("--expect-files", type=int, required=True)
    ap.add_argument("--expect-bytes", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default="/")
    a = ap.parse_args(argv)
    try:
        plan, size = _plan(a.root)
    except (OSError, ValueError) as e:
        print(f"STOPPED: nothing was removed ({e if isinstance(e, ValueError) else type(e).__name__})")
        return 1
    dirs, files = len(plan), sum(len(f) for _, f in plan)
    print(f"found: directories {dirs} | files {files} | bytes {size} | "
          f"expected: {a.expect_dirs} | {a.expect_files} | {a.expect_bytes}")
    if (dirs, files, size) != (a.expect_dirs, a.expect_files, a.expect_bytes):
        print("STOPPED: nothing was removed")
        return 1
    if not a.apply:
        print(f"would remove: directories {dirs} | files {files} | bytes {size}")
        return 0
    for d, fs in plan:
        for p in fs:
            os.remove(p)
        os.rmdir(d)
    left = sum(1 for d, _ in plan if os.path.lexists(d))
    print(f"removed: directories {dirs} | files {files} | still there: {left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

Run: `chmod 755 infra/hermes-agent/bin/remove-other-journal-dirs.py && python3 infra/hermes-agent/bin/remove-other-journal-dirs.test.py 2>&1 | tail -3` → `OK`.

- [ ] **Step 5: The runbook section**

In `deploy/BRING-UP.md`, after the section "The journal's retention", add:

````markdown
## The leftover journal directory (once per box)

A server image can leave, under `/var/log/journal`, the journal of the machine it was built on. The
journal service never trims it and D2.3 never reads it; D2.4 counts it (`other_directories`) and asks
the operator to state it at every review while it exists. Search it once, then remove it. Needs the
checkout at checklist v1.20 or later. Each block is pasted ALONE; run `sudo -v` first.

**VPS 1, search (reads only).**
```bash
cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --other-journals; echo "rc=$?"
```
Expected: one JSON object with `"kind": "other-journals"`, `directories` `1`, `files` `1`, the four leak
counts in `search` (`pattern_hits`, `known_secret_hits`, `credential_text_lines`, `customer_id_lines`)
all `0`, `known_secrets_checked` above `0`, then `rc=0`. STOP when a leak count is above `0` (a finding:
decide it before anything is removed), when `rc=2` (the read was not whole: report the message), or when
`directories` is not what review #10 recorded.

**VPS 2, what would be removed (changes nothing).** Use the `files` and `bytes` VPS 1 printed.
```bash
cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/remove-other-journal-dirs.py --expect-dirs 1 --expect-files 1 --expect-bytes <bytes>; echo "rc=$?"
```
Expected: `found: ...` with the same three numbers twice, `would remove: directories 1 | files 1 | bytes <bytes>`, `rc=0`.

**VPS 3, remove (cannot be undone; on the operator's word).**
```bash
cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/remove-other-journal-dirs.py --expect-dirs 1 --expect-files 1 --expect-bytes <bytes> --apply; echo "rc=$?"
```
Expected: `removed: directories 1 | files 1 | still there: 0`, `rc=0`. `STOPPED: nothing was removed`: report it.

**VPS 4, verify.** `sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --other-journals | grep -o '"directories": [0-9]*'` → `"directories": 0`. The journal service is not restarted and the live journal is untouched: the next trial collection's D2.4 shows `other_directories: 0` and the same `oldest_entry.journal` as before.

Record in the operator evidence file: the date, the counts of VPS 1 and the line of VPS 3.
````

In `CHECKLIST.md`, D2.4, after the sentence that says `other_directories` above `0` needs the operator's statement, add: `BRING-UP "The leftover journal directory" searches such a directory once in every stored field and removes it; the operator's evidence then carries that search's counts.`

- [ ] **Step 6: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`.

```bash
git add infra/hermes-agent/bin infra/hermes-agent/deploy
git commit -m "review: search the leftover journal directory once, then remove it (counts only, all or nothing)"
```

---

### Task 6: the helper for `--last-pass-execstart`, in the repository

**Files:**
- Create: `infra/hermes-agent/bin/last-pass-execstart.py`, `last-pass-execstart.test.py`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md` (collection step 3)

**Interfaces:**
- Produces: `last-pass-execstart.py <bundle>`: writes the 64-hex value, with no line break, to standard output and exits 0; writes nothing and exits 1 otherwise.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/last-pass-execstart.test.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

Run it → FAIL (no such file).

- [ ] **Step 2: Write the tool**

Create `infra/hermes-agent/bin/last-pass-execstart.py` (mode 755):

```python
#!/usr/bin/env python3
"""Write the last PASS's D4.2 `execstart_sha256` to standard output: the one value, no line break.

  python3 bin/last-pass-execstart.py <the last PASS's private box bundle> | pbcopy

The collector takes that value as --last-pass-execstart. The public report shows it abbreviated;
the full value is only in the private box bundle. Piped to the clipboard it is never shown on
screen. Writes nothing, and exits 1, when the file cannot be read or the field is not exactly 64
lowercase hex characters: no error text, so no path and no content. Stdlib only."""
import json, re, sys


def main(argv):
    try:
        with open(argv[1], encoding="utf-8") as f:
            value = json.load(f)["items"]["D4.2"]["data"]["execstart_sha256"]
    except Exception:
        return 1
    if not (isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)):
        return 1
    sys.stdout.write(value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Run: `chmod 755 infra/hermes-agent/bin/last-pass-execstart.py && python3 infra/hermes-agent/bin/last-pass-execstart.test.py 2>&1 | tail -3` → `OK`.

- [ ] **Step 3: The runbook sentence**

`deploy/BRING-UP.md`, collection step 3. In the command, `<the last PASS report's execstart_sha256>` → `<the last PASS's execstart_sha256>`. Replace `` `--last-pass-execstart` is the last PASS report's D4.2 `execstart_sha256`, 64 lowercase hex characters. `` with:

```
`--last-pass-execstart` is the last PASS's D4.2 `execstart_sha256`, 64 lowercase hex characters. The public report shows it abbreviated: the full value is in the last PASS's private box bundle. On the laptop, in a second window: `python3 infra/hermes-agent/bin/last-pass-execstart.py <that bundle> | pbcopy; pbpaste | wc -c` → `64` (the length only; the value is never shown), then paste it into the command in place of the placeholder. `0`: the file is not a box bundle or holds no such value.
```

- [ ] **Step 4: Run and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`.

```bash
git add infra/hermes-agent/bin/last-pass-execstart.py infra/hermes-agent/bin/last-pass-execstart.test.py infra/hermes-agent/deploy/BRING-UP.md
git commit -m "review: the helper that reads the last PASS's proxy hash from the private bundle"
```

---

## After the last task

- `infra/hermes-agent/bin/run-bin-tests.sh; echo rc=$?` → `rc=0`; `node scripts/run-all-tests.js` → all suites pass (nothing under its paths changed; run once).
- `python3 infra/hermes-agent/bin/check-checklist-version.py --base main; echo rc=$?` → `rc=0`.
- A scan of the diff for a ten-digit number, a 32-character hex string, an address or a key-shaped string outside test fixtures: none.
- No push. The operator decides whether Plan A is offered for merge alone or with Plan B.
