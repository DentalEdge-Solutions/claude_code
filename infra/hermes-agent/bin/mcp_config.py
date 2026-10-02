#!/usr/bin/env python3
"""A strict parser for the `mcp_servers:` block of a Hermes config file, and the comparison
security-review item D10.6 makes with it. Stdlib-only, no I/O: text in, values out.

Why not a YAML library: the box has stdlib Python only, and the file is written by the party
under review. So this reads exactly the YAML subset that the committed template and the
gateway's own rewrite of it use, and refuses everything else: it never guesses, never raises
on any text, never recurses on the input's depth, and makes one pass over each line.

THE SUBSET (everything else is `unparseable`):
- Lines are split on `\\n`; a trailing `\\r` is unparseable. Blank lines and lines whose first
  non-space character is `#` are skipped. A tab anywhere in the indentation of a line of the
  block is unparseable.
- The block is the top-level line `mcp_servers:` (nothing after the colon but spaces) and the
  indented lines that follow it, up to the next top-level line.
- Top level of the WHOLE file: every line starting at column 0 that is not blank or a comment
  must match `[A-Za-z_][A-Za-z0-9_-]*:` followed by end of line or a space. Otherwise
  `top_level_not_plain`. Exactly one such key may be `mcp_servers`; none is `no_block`, more
  than one is `duplicate_key`.
- Inside the block, by indentation (spaces only; a child is indented more than its parent;
  siblings share an indent):
  - mapping entry: `key:` followed by end of line (its value is the nested mapping or list that
    follows; if nothing follows it is unparseable) or `key: <scalar>` or `key: <flow>`. Keys
    match `[A-Za-z_][A-Za-z0-9_-]*`, unquoted. A repeated key in one mapping is `duplicate_key`.
  - block list item: `- <scalar>`. Items of one list share an indent, which is at least the
    indent of the key they belong to. Items are scalars only.
  - flow: `{}` (empty mapping), `[]` (empty list), or `[a, b, c]` whose items are scalars (no
    nesting, no trailing comma).
  - scalars:
    - `true` / `false` (lower case only) -> bool;
    - `0` or `[1-9][0-9]*` -> int;
    - `"..."` with no backslash and no `"` inside, or `'...'` with no `'` inside -> that string;
    - a plain string matching `[A-Za-z0-9_./-]+` that contains at least one letter and is not,
      in any case, one of `true false yes no on off null y n` -> that string. (So `python3`,
      `--app`, `ads-audit`, `/opt/cc-bin/hermes-app-mcp.py` and `ads_audit_run` parse; `Yes`,
      `0360`, `3.5`, `~` do not.)
  - nothing may follow a value on its line (no inline comment).
- Limits: more than 200 lines in the block, a line over 2,000 characters, or nesting deeper
  than 8 is unparseable.

WHERE THAT IS SILENT, THE STRICTER READING (each one is a refusal, and each is tested):
- Characters, anywhere in the file: a control character other than `\\n` and tab, U+0085,
  U+2028, U+2029, a byte order mark, U+FFFD (what a byte that is not UTF-8 decodes to) and a
  surrogate are unparseable. A YAML loader breaks lines at `\\r`, U+0085, U+2028 and U+2029
  too, so one of them could hide a key from a parser that splits on `\\n`.
- The block's lines are its key line and every line up to the next top-level line, blank
  lines and comments included: the 200 lines count them all and none of them is over 2,000
  characters. A line of the block that is not blank or a comment holds no tab at all, a quoted
  string's included (a line of spaces and tabs is not blank; a tab inside a comment's text is
  the one tab the block allows).
- Outside the block neither rule applies: a long line or a tab-indented line under another
  key is that key's content. Such a line cannot be a top-level key: it does not start at
  column 0, or it starts with a tab and is then `top_level_not_plain` like any column-0 line
  that is not a plain key (a line of tabs only included).
- An indented line that is not blank or a comment before the first top-level key is
  `top_level_not_plain`: it is under no plain key.
- `mcp_servers:` with no entry under it, and `mcp_servers: {}`, are `no_block`. Anything else
  after that colon is unparseable. The block's value is a mapping: a list there is unparseable.
- Exactly one space follows a `key:` that has a value, a list item's `-`, and a flow list's
  comma; no space pads a flow list's brackets; no space trails a line of the block.
- A plain string starts, after any leading `-`, with a letter, `_` or `/`: a loader reads
  `0x10`, `0b11`, `1.5e-3`, `.inf` and `.nan` as numbers, and each holds a letter.
- An integer has at most 18 digits. A key that is, in any case, one of the reserved words
  above is unparseable (a loader reads `on:` as a boolean key).
- Nesting is counted in open mappings and lists, the block's own mapping being the first.
- Reasons, in order: characters (`unparseable`), then the top level (`top_level_not_plain`),
  then the number of `mcp_servers` keys, then the block.

KNOWN CAUSES OF `top_level_not_plain` ON A FILE THAT IS OTHERWISE FINE (a refusal until the
rule is deliberately widened; do not widen it in passing, every accepted spelling is one a
hostile file can use):
- a top-level key that holds an indentless block list (`platforms:` then `- name: x` at column
  0, the PyYAML and ruamel default for a list under a top-level key);
- a top-level key named outside `[A-Za-z_][A-Za-z0-9_-]*` (`api.base:`, `2fa:`, a quoted `"on":`).
And of `unparseable`: a raw U+0085 or U+2028 inside a quoted value under any key (some dumpers
write them raw).

What is NOT parsed: the content under the other top-level keys. Whatever its shape, it cannot
give a loader a top-level `mcp_servers` key this parser does not see (such a key starts a line
at column 0, and every such line is checked), and nothing inside the block spans a line, so a
loader that reads the block reads these values. What that content CAN do is keep a loader from
reading the block at all: a file the loader rejects, or an earlier key's quoted value left
open across the block's lines (PyYAML allows that at column 0). The loader then has no
`mcp_servers` key, never a different one: fewer servers than the committed block, not more.
"""
import hashlib, json, re

KEY = "mcp_servers"
REASONS = ("-", "no_block", "duplicate_key", "top_level_not_plain", "unparseable", "differs")
MAX_BLOCK_LINES, MAX_LINE_CHARS, MAX_DEPTH = 200, 2000, 8

_REFUSED_CHARS_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\ufeff\ufffd\ud800-\udfff]")
_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
_TOP_RE = re.compile(r"(%s):(?: (.*))?" % _NAME)
_ENTRY_RE = re.compile(r"( *)(%s):(?: (.+))?" % _NAME)
_ITEM_RE = re.compile(r"( *)- (.+)")
_INT_RE = re.compile(r"0|[1-9][0-9]{0,17}")
_QUOTED_RE = re.compile(r'"[^"\\]*"|' r"'[^']*'")
_PLAIN_RE = re.compile(r"-*[A-Za-z_/][A-Za-z0-9_./-]*")
_LETTER_RE = re.compile(r"[A-Za-z]")
_FLOW_ITEM_RE = re.compile(r'"[^"\\]*"|' r"'[^']*'|[^ ,\]]+")
_WORDS = frozenset("true false yes no on off null y n".split())
_NOT = object()                      # "outside the subset": its own object, so no scalar can parse to it


def _scalar(text):
    if text in ("true", "false"):
        return text == "true"
    if _INT_RE.fullmatch(text):
        return int(text)
    if _QUOTED_RE.fullmatch(text):
        return text[1:-1]
    if _PLAIN_RE.fullmatch(text) and _LETTER_RE.search(text) and text.lower() not in _WORDS:
        return text
    return _NOT


def _value(text):
    """What follows `key: `: a scalar, `{}`, `[]`, or one flow list of scalars."""
    if text in ("{}", "[]"):
        return {} if text == "{}" else []
    if not text.startswith("["):
        return _scalar(text)
    items, at = [], 1
    while True:
        m = _FLOW_ITEM_RE.match(text, at)
        item = _scalar(m.group()) if m else _NOT
        if item is _NOT:
            return _NOT
        items.append(item)
        at = m.end()
        if text.startswith(", ", at):
            at += 2
        elif text[at:] == "]":
            return items
        else:
            return _NOT


def _build(lines):
    """The block's content lines (no blank line, no comment) as a value, with a stack of the open
    mappings and lists instead of recursion. `waiting` is the key whose line ended at its colon:
    the next line must open its mapping or its list."""
    holder = {}
    stack, waiting = [], (holder, KEY, 0)
    for line in lines:
        if "\t" in line:
            return None, "unparseable"
        m = _ITEM_RE.fullmatch(line)
        if m:
            indent, key, text = len(m.group(1)), None, m.group(2)
        else:
            m = _ENTRY_RE.fullmatch(line)
            if not m:
                return None, "unparseable"
            indent, key, text = len(m.group(1)), m.group(2), m.group(3)
        if waiting:
            parent, name, at = waiting
            if key is not None and indent > at:
                opened = {}
            elif key is None and indent >= at and parent is not holder:    # the block itself is a mapping
                opened = []
            else:
                return None, "unparseable"
            if len(stack) == MAX_DEPTH:
                return None, "unparseable"
            parent[name] = opened
            stack.append((indent, opened))
            waiting = None
        else:
            while stack and stack[-1][0] > indent:
                stack.pop()
            # A list written at its key's own indent ends at the next key of that mapping.
            if stack and stack[-1][0] == indent and key is not None and isinstance(stack[-1][1], list):
                stack.pop()
            if not stack or stack[-1][0] != indent:
                return None, "unparseable"
        into = stack[-1][1]
        if (key is None) != isinstance(into, list):
            return None, "unparseable"
        if key is None:
            item = _scalar(text)
            if item is _NOT:
                return None, "unparseable"
            into.append(item)
        elif key in into:
            return None, "duplicate_key"
        elif key.lower() in _WORDS:
            return None, "unparseable"
        elif text is None:
            into[key] = None
            waiting = (into, key, indent)
        else:
            value = _value(text)
            if value is _NOT:
                return None, "unparseable"
            into[key] = value
    if waiting:
        return None, "unparseable"
    return holder[KEY], None


def block_value(text):
    """(value, None): the mapping under the file's one top-level `mcp_servers:` key. Otherwise
    (None, reason), reason one of no_block, duplicate_key, top_level_not_plain, unparseable.
    Never raises, whatever the text."""
    if _REFUSED_CHARS_RE.search(text):
        return None, "unparseable"
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()                                          # the file's final newline ends its last line
    tops, found = [], []
    for n, line in enumerate(lines):
        body = line.lstrip(" ")
        if not body or body.startswith("#"):
            continue
        if line.startswith(" "):
            if not tops:
                return None, "top_level_not_plain"
            continue
        m = _TOP_RE.fullmatch(line)
        if not m:
            return None, "top_level_not_plain"
        tops.append(n)
        if m.group(1) == KEY:
            found.append((n, len(tops), m.group(2)))
    if len(found) != 1:
        return None, "duplicate_key" if found else "no_block"
    start, nth, after = found[0]
    if after is not None and after.strip(" "):
        return None, "no_block" if after == "{}" else "unparseable"
    block = lines[start:tops[nth] if nth < len(tops) else len(lines)]
    if len(block) > MAX_BLOCK_LINES or any(len(l) > MAX_LINE_CHARS for l in block):
        return None, "unparseable"
    content = [l for l in block[1:] if l.strip(" ") and not l.lstrip(" ").startswith("#")]
    if not content:
        return None, "no_block"
    return _build(content)


def canonical(value):
    """One text per value: mapping key order does not matter, list order does, and `true` and
    `1`, `"360"` and `360` are different (in Python True == 1, so values are never compared)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def compare(box_text, repo_text):
    """The box's block against the committed one. `canonical_sha256` is of the box block's
    canonical form when it parsed, else None; `reason` is `-` when equal, `differs` when both
    parsed and differ, otherwise why the box's did not parse. The committed text is ours: when
    IT has no usable block, ValueError (nothing can be compared)."""
    repo, why = block_value(repo_text)
    if repo is None:
        raise ValueError(f"the committed text has no usable {KEY} block: {why}")
    box, why = block_value(box_text)
    if box is None:
        return {"equals_repo": False, "reason": why, "canonical_sha256": None}
    mine = canonical(box)
    equal = mine == canonical(repo)
    return {"equals_repo": equal, "reason": "-" if equal else "differs",
            "canonical_sha256": hashlib.sha256(mine.encode()).hexdigest()}
