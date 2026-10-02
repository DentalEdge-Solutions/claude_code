#!/usr/bin/env python3
import hashlib, os, random, sys, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mcp_config as M

EXPECTED = {"ads_audit": {"command": "python3", "args": ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"],
                          "env": {}, "timeout": 360,
                          "tools": {"include": ["ads_audit_run", "ads_audit_status", "ads_audit_list"],
                                    "resources": False, "prompts": False}}}

# The committed block (config.yaml.example's layout) and the block as the gateway rewrote it on
# the box: the same values, quotes dropped, the flow lists written one item per line.
TEMPLATE_BLOCK = """mcp_servers:
  ads_audit:
    command: "python3"
    args: ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"]
    env: {}
    timeout: 360
    tools:
      include: [ads_audit_run, ads_audit_status, ads_audit_list]
      resources: false
      prompts: false
"""
REWRITTEN_BLOCK = """mcp_servers:
  ads_audit:
    command: python3
    args:
      - /opt/cc-bin/hermes-app-mcp.py
      - --app
      - ads-audit
    env: {}
    timeout: 360
    tools:
      include:
        - ads_audit_run
        - ads_audit_status
        - ads_audit_list
      resources: false
      prompts: false
"""
TEMPLATE_HEAD = """# The template: comments, blank lines, quoted values.
model:
  # a comment under a key — with a dash and a § sign
  default: "deepseek/deepseek-v3.2"
  provider: "openrouter"

terminal:
  backend: "local"
  cwd: "."
  timeout: 300

# OpenRouter privacy.
provider_routing:
  data_collection: "deny"

# Option B: the one app.
"""
BOX_HEAD = """model:
  default: deepseek/deepseek-v3.2
  provider: openrouter
terminal:
  backend: local
  cwd: .
  timeout: 300
provider_routing:
  data_collection: deny
"""
# What follows the block is other keys' content: never parsed, whatever its shape.
BOX_TAIL = """onboarding:
  seen:
  - welcome
  note: |
    any shape: {not, parsed} "at all"
      - not: [a, list
  flags: {a: 1, b: [x, y]}
  when: 2026-10-02 12:00:00
"""


def real_template():
    with open(os.path.join(os.path.dirname(HERE), "config.yaml.example"), encoding="utf-8") as f:
        return f.read()


def template(block=TEMPLATE_BLOCK):
    return TEMPLATE_HEAD + block + "\n# a trailing note\nupdates:\n  channel: \"stable\"\n"


def box(block=REWRITTEN_BLOCK):
    return BOX_HEAD + block + BOX_TAIL


def sha(value):
    return hashlib.sha256(M.canonical(value).encode()).hexdigest()


class TestTheTwoRealLayouts(unittest.TestCase):
    def test_the_template_parses_to_the_expected_value(self):
        real = real_template()
        self.assertEqual(M.block_value(real), (EXPECTED, None))
        self.assertEqual(M.canonical(M.block_value(real)[0]), M.canonical(EXPECTED))
        self.assertEqual(M.block_value(template()), (EXPECTED, None))

    def test_the_rewritten_layout_equals_the_template(self):
        self.assertEqual(M.block_value(box()), (EXPECTED, None))
        self.assertEqual(M.compare(box(), template()),
                         {"equals_repo": True, "reason": "-", "canonical_sha256": sha(EXPECTED)})
        real = real_template()
        self.assertEqual(M.compare(box(), real),
                         {"equals_repo": True, "reason": "-", "canonical_sha256": sha(EXPECTED)})
        # Wherever the block sits in the file: first, in the middle, last, without a final newline.
        for text in (REWRITTEN_BLOCK + BOX_HEAD + BOX_TAIL, BOX_HEAD + BOX_TAIL + REWRITTEN_BLOCK,
                     BOX_HEAD + REWRITTEN_BLOCK.rstrip("\n"), REWRITTEN_BLOCK):
            with self.subTest(text=text[:20]):
                self.assertIs(M.compare(text, template())["equals_repo"], True)

    def test_other_keys_content_is_not_parsed_and_does_not_confuse(self):
        # An indented `mcp_servers:` is another key's content, not the block; neither is anything
        # else under another key, however it looks.
        tail = ("onboarding:\n  mcp_servers:\n    evil: {command: sh}\n  text: |\n    mcp_servers:\n"
                "      evil: 1\n  \"quoted key\": &a [1, 2]\n  <<: *a\n  ? complex\n  : value\n"
                "version: 12\nflag: yes\nlist: [a, b]\nempty:\n")
        self.assertEqual(M.block_value(BOX_HEAD + REWRITTEN_BLOCK + tail), (EXPECTED, None))
        # The stated limit of not parsing it: an earlier key's quoted value left open across the
        # block (PyYAML allows that) makes a loader read NO mcp_servers key, and is not seen here.
        # It cannot make a loader read a different one: that key would start a line at column 0.
        self.assertEqual(M.block_value("model: \"open\n" + REWRITTEN_BLOCK + "onboarding: closed\"\n"), (EXPECTED, None))
        self.assertEqual(M.block_value("model: \"open\n" + REWRITTEN_BLOCK + "onboarding: closed\"\nmcp_servers:\n  evil:\n    command: sh\n"),
                         (None, "duplicate_key"))

    def test_key_order_does_not_matter_list_order_does(self):
        shuffled = """mcp_servers:
  ads_audit:
    tools:
      prompts: false
      resources: false
      include: [ads_audit_run, ads_audit_status, ads_audit_list]
    timeout: 360
    env: {}
    args:
      - /opt/cc-bin/hermes-app-mcp.py
      - --app
      - ads-audit
    command: 'python3'
"""
        self.assertEqual(M.compare(box(shuffled), template()),
                         {"equals_repo": True, "reason": "-", "canonical_sha256": sha(EXPECTED)})
        self.assertEqual(M.canonical({"b": 1, "a": [2, 1]}), '{"a":[2,1],"b":1}')
        for swapped in (REWRITTEN_BLOCK.replace("      - --app\n      - ads-audit\n", "      - ads-audit\n      - --app\n"),
                        TEMPLATE_BLOCK.replace("ads_audit_run, ads_audit_status", "ads_audit_status, ads_audit_run")):
            got = M.compare(box(swapped), template())
            self.assertEqual((got["equals_repo"], got["reason"]), (False, "differs"))
            self.assertNotEqual(got["canonical_sha256"], sha(EXPECTED))

    def test_comments_and_blank_lines_in_the_block_are_ignored(self):
        noisy = REWRITTEN_BLOCK.replace("    env: {}\n", "\n    # no variables\n  \n# at column 0\n    env: {}\n"
                                        "          # deeper than anything\n")
        self.assertEqual(M.block_value(box(noisy)), (EXPECTED, None))
        self.assertEqual(M.block_value(BOX_HEAD + REWRITTEN_BLOCK + "\n\n# about the next key\n" + BOX_TAIL),
                         (EXPECTED, None))

    def test_indentless_list_items_parse(self):
        indentless = """mcp_servers:
  ads_audit:
    command: python3
    args:
    - /opt/cc-bin/hermes-app-mcp.py
    - --app
    - ads-audit
    env: {}
    timeout: 360
    tools:
      include:
      - ads_audit_run
      - ads_audit_status
      - ads_audit_list
      resources: false
      prompts: false
"""
        self.assertEqual(M.block_value(box(indentless)), (EXPECTED, None))
        # A list that is the last thing in its mapping, then a key of the mapping above.
        self.assertEqual(M.block_value("mcp_servers:\n  a:\n    l:\n    - x\n  b:\n    l:\n      - z\n"),
                         ({"a": {"l": ["x"]}, "b": {"l": ["z"]}}, None))


class TestScalars(unittest.TestCase):
    def _value(self, text):
        value, reason = M.block_value("mcp_servers:\n  s:\n    k: " + text + "\n")
        return value["s"]["k"] if reason is None else reason

    def test_scalars_of_the_subset(self):
        for text, want in (("true", True), ("false", False), ("0", 0), ("360", 360), ('"360"', "360"),
                           ("'false'", "false"), ('"Yes"', "Yes"), ('""', ""), ("''", ""),
                           ('"a b: c # d, [e] {f} \'g\'"', "a b: c # d, [e] {f} 'g'"), ("'say \"hi\" \\n'", 'say "hi" \\n'),
                           ("python3", "python3"), ("--app", "--app"), ("ads-audit", "ads-audit"),
                           ("/opt/cc-bin/hermes-app-mcp.py", "/opt/cc-bin/hermes-app-mcp.py"),
                           ("ads_audit_run", "ads_audit_run"), ("_x", "_x"), ("truer", "truer"), ("e3", "e3"),
                           ("{}", {}), ("[]", []), ("[a]", ["a"]),
                           ('[true, 0, "a, b", \'c]\', d/e]', [True, 0, "a, b", "c]", "d/e"])):
            with self.subTest(text=text):
                got = self._value(text)
                self.assertEqual((got, type(got)), (want, type(want)))

    def test_types_are_compared_exactly(self):
        for text, same in (('timeout: "360"', "timeout: 360"), ("timeout: '360'", "timeout: 360"),
                           ('resources: "false"', "resources: false"), ("prompts: 0", "prompts: false"),
                           ("resources: 0", "resources: false"), ('command: "python3 "', "command: python3")):
            with self.subTest(text=text):
                got = M.compare(box(REWRITTEN_BLOCK.replace(same, text)), template())
                self.assertEqual((got["equals_repo"], got["reason"]), (False, "differs"))
        # In Python True == 1 and False == 0: the comparison must not be Python's.
        one = "mcp_servers:\n  s:\n    k: 1\n    l: [0]\n"
        got = M.compare(one.replace("k: 1", "k: true").replace("[0]", "[false]"), one)
        self.assertEqual((got["equals_repo"], got["reason"]), (False, "differs"))
        self.assertNotEqual(M.canonical(True), M.canonical(1))
        self.assertNotEqual(M.canonical("360"), M.canonical(360))
        # What a YAML 1.1 (or 1.2) loader would not read as the string it looks like is outside
        # the subset: never a guess.
        words = [w for base in ("yes", "no", "on", "off", "null", "y", "n", "true", "false")
                 for w in (base, base.capitalize(), base.upper())]
        words = [w for w in words if w not in ("true", "false")] + ["~", "tRUE", "nULL"]
        numbers = ["0360", "00", "3.5", "360.0", "+360", "-360", "-0", "1e3", "1E3", "1.5e-3", "0x10", "0X1F",
                   "0b101", "0o17", "1_000", "_1", ".5", "5.", ".inf", "-.inf", ".Inf", ".nan", ".NaN",
                   "2026-10-02", "12:30", "1:30:00", "3rd", "0a", "-1a", "--1", "./x", ".x", "1" * 19]
        for text in words + numbers:
            for shape in ("k: %s", "k: [a, %s]", "k:\n      - %s"):
                with self.subTest(text=text, shape=shape):
                    self.assertEqual(M.block_value("mcp_servers:\n  s:\n    " + shape % text + "\n"),
                                     (None, "unparseable"))
        # A key a loader would read as a boolean or null is not a name either.
        for word in ("yes", "No", "ON", "off", "null", "y", "N", "true", "False"):
            with self.subTest(key=word):
                self.assertEqual(M.block_value("mcp_servers:\n  s:\n    %s: 1\n" % word), (None, "unparseable"))

    def test_any_changed_value_differs(self):
        cases = {
            "a fourth tool": REWRITTEN_BLOCK.replace("        - ads_audit_list\n", "        - ads_audit_list\n        - shell\n"),
            "a fourth tool, flow": TEMPLATE_BLOCK.replace("ads_audit_list]", "ads_audit_list, shell]"),
            "a tool removed": REWRITTEN_BLOCK.replace("        - ads_audit_list\n", ""),
            "a different command": REWRITTEN_BLOCK.replace("command: python3", "command: /bin/sh"),
            "a different argument": REWRITTEN_BLOCK.replace("- ads-audit", "- other-app"),
            "an argument added": REWRITTEN_BLOCK.replace("      - ads-audit\n", "      - ads-audit\n      - --debug\n"),
            "a non-empty env": REWRITTEN_BLOCK.replace("    env: {}\n", "    env:\n      PYTHONPATH: /tmp/x\n"),
            "env as a list": REWRITTEN_BLOCK.replace("env: {}", "env: []"),
            "resources: true": REWRITTEN_BLOCK.replace("resources: false", "resources: true"),
            "prompts: true": REWRITTEN_BLOCK.replace("prompts: false", "prompts: true"),
            "a different timeout": REWRITTEN_BLOCK.replace("timeout: 360", "timeout: 3600"),
            "a key added": REWRITTEN_BLOCK.replace("    timeout: 360\n", "    timeout: 360\n    url: http/x\n"),
            "a key removed": REWRITTEN_BLOCK.replace("    timeout: 360\n", ""),
            "a second server": REWRITTEN_BLOCK + "  other:\n    command: sh\n",
            "the server renamed": REWRITTEN_BLOCK.replace("  ads_audit:\n", "  ads_audit2:\n"),
            "a key moved up a level": REWRITTEN_BLOCK.replace("      prompts: false\n", "    prompts: false\n"),
        }
        for why, block in cases.items():
            with self.subTest(why=why):
                got = M.compare(box(block), template())
                self.assertEqual((got["equals_repo"], got["reason"]), (False, "differs"))
                self.assertRegex(got["canonical_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotEqual(got["canonical_sha256"], sha(EXPECTED))


class TestTopLevel(unittest.TestCase):
    def test_no_block_and_missing_file_text(self):
        for text in ("", "\n", "# only a comment\n", BOX_HEAD + BOX_TAIL,
                     BOX_HEAD + "mcp_servers:\n" + BOX_TAIL,                 # nothing under the key
                     BOX_HEAD + "mcp_servers:", BOX_HEAD + "mcp_servers:   \n\n  # only a comment\n\n" + BOX_TAIL,
                     BOX_HEAD + "mcp_servers: {}\n" + BOX_TAIL,
                     BOX_HEAD + "MCP_SERVERS:\n  a:\n    b: c\n", BOX_HEAD + "mcp_servers2:\n  a:\n    b: c\n",
                     "model:\n  mcp_servers:\n    a:\n      b: c\n"):
            with self.subTest(text=text[-40:]):
                self.assertEqual(M.block_value(text), (None, "no_block"))
        # Spaces after the colon are nothing; anything else there is not the block's key line.
        self.assertEqual(M.block_value("mcp_servers:   \n  a:\n    b: c\n"), ({"a": {"b": "c"}}, None))
        for after in ("[]", "~", "null", "x", "{a: 1}", "# c", "&a", "|", "{} ", " {}", "{}  # c"):
            with self.subTest(after=after):
                self.assertEqual(M.block_value("mcp_servers: " + after + "\n  a:\n    b: c\n"), (None, "unparseable"))

    def test_top_level_must_be_plain_and_single(self):
        evil = "\n  evil:\n    command: sh\n"
        for line in ('"mcp_servers":', "'mcp_servers':", '"mcp\\x5fservers":', '"mcp\\u005fservers":',
                     "!!str mcp_servers:", "!mcp_servers:", "&a mcp_servers:", "*a :", "? mcp_servers",
                     ": value", "<<:", "<<: {mcp_servers: {}}", "---", "--- ", "...", "%YAML 1.1",
                     "{mcp_servers: {}}", "[mcp_servers]", "continuation", "continuation of a value",
                     "- item", "-", "mcp_servers :", "mcp_servers:x", "mcp servers:", "mcp.servers:",
                     "1key:", "-key:", "key", "key:\u00a0x", "\u00a0mcp_servers:", "mcp_servers\uff1a",
                     "@key:", "`key`:", "|", ">", '"', "x\"", "=:", "é:"):
            for text in (box() + line + evil, line + evil + box(), BOX_HEAD + line + evil + REWRITTEN_BLOCK + BOX_TAIL):
                with self.subTest(line=line):
                    self.assertEqual(M.block_value(text), (None, "top_level_not_plain"))
                    self.assertEqual(M.compare(text, template()),
                                     {"equals_repo": False, "reason": "top_level_not_plain", "canonical_sha256": None})
        # Indented content before any top-level key is not under a plain key.
        self.assertEqual(M.block_value("  stray: 1\n" + box()), (None, "top_level_not_plain"))
        self.assertEqual(M.block_value(" mcp_servers:\n   a:\n     b: c\n"), (None, "top_level_not_plain"))
        self.assertEqual(M.block_value("# a comment\n\n  # an indented comment\n" + box()), (EXPECTED, None))
        # A second plain key: wherever it is and whatever it holds.
        for second in ("mcp_servers:" + evil, "mcp_servers: {}\n", "mcp_servers:\n", "mcp_servers: x\n", REWRITTEN_BLOCK):
            for text in (box() + second, second + box(), BOX_HEAD + second + REWRITTEN_BLOCK + BOX_TAIL):
                with self.subTest(second=second):
                    self.assertEqual(M.block_value(text), (None, "duplicate_key"))
        # A top level that is not plain is reported before a duplicate, and both before the block.
        self.assertEqual(M.block_value(box() + "mcp_servers:\n---\n"), (None, "top_level_not_plain"))
        self.assertEqual(M.block_value(box("mcp_servers:\n  a: |\n") + "mcp_servers:\n"), (None, "duplicate_key"))

    def test_other_line_breaks_and_encoding_marks_are_refused_anywhere(self):
        # A YAML loader breaks lines at \r, U+0085, U+2028 and U+2029 too, strips a byte order
        # mark and may decode the bytes differently: any of these could hide a key from a
        # parser that splits on \n, so the whole file is refused, wherever the character is.
        hidden = "mcp_servers:%s  evil:%s    command: sh%s"
        for ch in ("\r", "\x85", "\u2028", "\u2029", "\x00", "\ufeff", "\ufffd", "\x0b", "\x0c", "\x1b",
                   "\x1c", "\x1e", "\x7f", "\x9f", "\ud800"):
            for text in (box() + "updates: x" + ch + hidden % (ch, ch, ch) + "\n",
                         box().replace("deny\n", "deny" + ch + "\n"), ch + box(), box() + ch,
                         box().replace("command: python3", "command: \"python3" + ch + "\""),
                         box().replace("  note: |\n", "  note: |\n    a" + ch + "b\n"),
                         "# comment " + ch + "\n" + box()):
                with self.subTest(ch=repr(ch)):
                    self.assertEqual(M.block_value(text), (None, "unparseable"))
        self.assertEqual(M.block_value(box().replace("\n", "\r\n")), (None, "unparseable"))
        self.assertEqual(M.block_value(box().encode("utf-16").decode("utf-8", errors="replace")), (None, "unparseable"))
        self.assertEqual(M.block_value(box().encode("utf-16-le").decode("utf-8", errors="replace")), (None, "unparseable"))


class TestHostileBlocks(unittest.TestCase):
    def _reason(self, block):
        t0 = time.monotonic()
        got = M.block_value(box(block))
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIsNone(got[0])
        return got[1]

    def test_hostile_blocks_are_unparseable_not_a_crash(self):
        R = REWRITTEN_BLOCK
        cases = {
            "a tab as indentation": R.replace("    env: {}", "\tenv: {}"),
            "a tab inside the indentation": R.replace("    env: {}", "  \t  env: {}"),
            "a tab after the colon": R.replace("env: {}", "env:\t{}"),
            "a tab after the dash": R.replace("- --app", "-\t--app"),
            "a tab after a value": R.replace("env: {}", "env: {}\t"),
            "a tab in a quoted value": R.replace("command: python3", 'command: "python3\t-c"'),
            "a tab in a single-quoted item": R.replace("- --app", "- '--app\t'"),
            "a tab in a quoted flow item": R.replace("env: {}", 'env: [a, "b\tc"]'),
            "an anchor": R.replace("env: {}", "env: &e {}"),
            "an anchor on a key line": R.replace("    tools:\n", "    tools: &t\n"),
            "an alias": R.replace("env: {}", "env: *e"),
            "an alias item": R.replace("- --app", "- *a"),
            "a merge key": R.replace("    env: {}\n", "    <<: {command: sh}\n    env: {}\n"),
            "a tag": R.replace("timeout: 360", "timeout: !!str 360"),
            "a tag on a key": R.replace("    timeout: 360", "    !!str timeout: 360"),
            "a literal block scalar": R.replace("command: python3", "command: |\n      sh"),
            "a folded block scalar": R.replace("command: python3", "command: >-\n      sh"),
            "a flow mapping": R.replace("env: {}", "env: {A: b}"),
            "a flow mapping with a space": R.replace("env: {}", "env: { }"),
            "a nested flow list": R.replace("env: {}", "env: [a, [b]]"),
            "a flow mapping in a flow list": R.replace("env: {}", "env: [{}]"),
            "a trailing comma": R.replace("env: {}", "env: [a, ]"),
            "a trailing comma, no space": R.replace("env: {}", "env: [a,]"),
            "an empty flow item": R.replace("env: {}", "env: [a, , b]"),
            "no space after the comma": R.replace("env: {}", "env: [a,b]"),
            "a space before the comma": R.replace("env: {}", "env: [a , b]"),
            "padded brackets": R.replace("env: {}", "env: [ a ]"),
            "an unclosed flow list": R.replace("env: {}", "env: [a, b"),
            "a flow list continued on the next line": R.replace("env: {}", "env: [a,\n      b]"),
            "text after a flow list": R.replace("env: {}", "env: [a] b"),
            "a pair in a flow list": R.replace("env: {}", "env: [a: b]"),
            "an inline comment after a value": R.replace("timeout: 360", "timeout: 360 # seconds"),
            "an inline comment after a key": R.replace("    tools:\n", "    tools: # the three\n"),
            "an inline comment after an item": R.replace("- --app", "- --app # flag"),
            "a comment glued to a value": R.replace("command: python3", "command: python3#x"),
            "a trailing space after a value": R.replace("timeout: 360", "timeout: 360 "),
            "a trailing space after a key": R.replace("    tools:\n", "    tools: \n"),
            "two spaces after the colon": R.replace("timeout: 360", "timeout:  360"),
            "two spaces after the dash": R.replace("- --app", "-  --app"),
            "no space after the colon": R.replace("timeout: 360", "timeout:360"),
            "a space before the colon": R.replace("timeout: 360", "timeout : 360"),
            "a quoted key": R.replace("    timeout: 360", '    "timeout": 360'),
            "a single-quoted key": R.replace("    timeout: 360", "    'timeout': 360"),
            "a complex key": R.replace("    timeout: 360", "    ? timeout\n    : 360"),
            "a key with a dot": R.replace("    timeout: 360", "    time.out: 360"),
            "an escape in a double-quoted value": R.replace("command: python3", 'command: "python3\\x20-c"'),
            "a backslash at the end of a quoted value": R.replace("command: python3", 'command: "python3\\"'),
            "a doubled quote in a single-quoted value": R.replace("command: python3", "command: 'it''s'"),
            "a quote inside a double-quoted value": R.replace("command: python3", 'command: "a"b"'),
            "an unclosed quote": R.replace("command: python3", 'command: "python3'),
            "a quoted value continued on the next line": R.replace("command: python3", 'command: "python3\n      -c"'),
            "two quoted values": R.replace("command: python3", 'command: "a" "b"'),
            "text after a quoted value": R.replace("command: python3", 'command: "a"b'),
            "a plain value with a space": R.replace("command: python3", "command: python3 -c"),
            "a plain value with a colon": R.replace("command: python3", "command: a:b"),
            "a plain value ending in a colon": R.replace("command: python3", "command: python3:"),
            "a plain value with a url": R.replace("command: python3", "command: https://user:pw@host/x"),
            "a plain value with a hash": R.replace("command: python3", "command: a#b"),
            "a plain value that is not ASCII": R.replace("command: python3", "command: pythön3"),
            "a plain value continued on the next line": R.replace("    command: python3\n", "    command: python3\n      -c\n"),
            "a key under a scalar": R.replace("    command: python3\n", "    command: python3\n      evil: 1\n"),
            "a list item under a scalar": R.replace("    command: python3\n", "    command: python3\n      - evil\n"),
            "a list item under a scalar, same indent": R.replace("    command: python3\n", "    command: python3\n    - evil\n"),
            "a list item continued on the next line": R.replace("      - --app\n", "      - --app\n        more\n"),
            "a key under a list item": R.replace("      - --app\n", "      - --app\n        evil: 1\n"),
            "a mapping in a list item": R.replace("- --app", "- flag: --app"),
            "a list in a list item": R.replace("- --app", "- - --app"),
            "a flow list in a list item": R.replace("- --app", "- [--app]"),
            "an empty list item": R.replace("- --app", "-"),
            "an empty list item, with a space": R.replace("- --app", "- "),
            "a list directly under the top-level key": "mcp_servers:\n  - ads_audit\n",
            "a key with nothing under it, at the end": R + "  other:\n",
            "a key with nothing under it, then a sibling": R.replace("    tools:\n", "    tools:\n    more:\n"),
            "a key with nothing under it, then a dedent": R.replace("      prompts: false\n", "      prompts:\n") + "  other:\n    command: sh\n",
            "an explicit null": R.replace("env: {}", "env: ~"),
            "a child indented less than its sibling": R.replace("    env: {}", "   env: {}"),
            "a child indented more than its sibling": R.replace("    env: {}", "     env: {}"),
            "a dedent to no open mapping": R.replace("      resources: false", "     resources: false"),
            "list items at two indents": R.replace("      - --app", "       - --app"),
            "a list item indented less than its key": R.replace("      - /opt", "   - /opt"),
            "a key between list items": R.replace("      - --app\n", "      x: 1\n"),
            "a list item between keys": R.replace("    env: {}\n", "    - x\n"),
            "a list item after an indentless list ended": "mcp_servers:\n  s:\n    args:\n    - x\n    env: {}\n    - y\n",
            "a document marker in the block": R.replace("    env: {}\n", "    ---\n    env: {}\n"),
            "a directive in the block": R.replace("    env: {}\n", "    %YAML 1.1\n    env: {}\n"),
            "a no-break space as indentation": R.replace("    env: {}", "  \u00a0 env: {}"),
            "a full-width colon": R.replace("env: {}", "env\uff1a {}"),
            "nesting deeper than the limit": "mcp_servers:\n" + "".join(" " * (i + 1) + "k:\n" for i in range(9)) + " " * 10 + "k: v\n",
            "10,000 levels of indentation": "mcp_servers:\n" + "".join(" " * (i + 1) + "k:\n" for i in range(10000)),
            "one line indented 10,000 deep": "mcp_servers:\n" + " " * 10000 + "k: v\n",
            "a 64 KiB line": R.replace("command: python3", "command: " + "a" * 65536),
            "a 64 KiB line of brackets": R.replace("env: {}", "env: " + "[" * 65536),
            "a 64 KiB quoted line": R.replace("command: python3", 'command: "' + "a" * 65536),
            "a 64 KiB flow list": R.replace("env: {}", "env: [" + ", ".join(["a"] * 21000) + "]"),
            "more lines than the limit": "mcp_servers:\n  s:\n" + "".join("    k%d: v\n" % i for i in range(250)),
            "binary bytes": R.replace("command: python3", "command: " + bytes(range(256)).decode("utf-8", errors="replace")),
        }
        for why, block in cases.items():
            with self.subTest(why=why):
                self.assertEqual(self._reason(block), "unparseable")
        self.assertEqual(M.block_value(os.urandom(65536).decode("utf-8", errors="replace"))[0], None)
        self.assertEqual(M.block_value(box("mcp_servers:\n" + "  a:\n    b: |\n" * 30000)), (None, "unparseable"))

    def test_a_repeated_key_in_one_mapping_is_a_duplicate(self):
        R = REWRITTEN_BLOCK
        for why, block in {"a repeated scalar key": R.replace("    timeout: 360\n", "    timeout: 360\n    timeout: 360\n"),
                           "a repeated server": R + R[len("mcp_servers:\n"):],
                           "a repeated nested key": R + "    tools:\n      include: [shell]\n",
                           "a repeated key in a nested mapping": R + "      include:\n        - shell\n",
                           "a repeated key with nothing under it": R.replace("    env: {}\n", "    env: {}\n    env:\n")}.items():
            with self.subTest(why=why):
                self.assertEqual(M.block_value(box(block)), (None, "duplicate_key"))
        # The same name in two different mappings is not a repeat.
        self.assertEqual(M.block_value("mcp_servers:\n  a:\n    a:\n      a: b\n  b:\n    a: c\n"),
                         ({"a": {"a": {"a": "b"}}, "b": {"a": "c"}}, None))

    def test_the_limits(self):
        deep = lambda n: "mcp_servers:\n" + "".join(" " * (i + 1) + "k:\n" for i in range(n - 1)) + " " * n + "k: v\n"
        value = M.block_value(deep(8))[0]
        for _ in range(8):
            value = value["k"]
        self.assertEqual(value, "v")
        self.assertEqual(M.block_value(deep(9)), (None, "unparseable"))
        self.assertEqual(M.block_value("mcp_servers:\n  s:\n" + " " * 4 + "l:\n" + " " * 6 + "- x\n")[1], None)
        # The block is the key's line and what follows it, up to the next top-level line.
        many = lambda n: "mcp_servers:\n  s:\n" + "".join("    k%d: v\n" % i for i in range(n - 2))
        self.assertEqual(len(M.block_value(many(200) + "next:\n  x: 1\n" * 300)[0]["s"]), 198)
        self.assertEqual(M.block_value(many(201)), (None, "unparseable"))
        self.assertEqual(M.block_value(many(190) + "\n" * 11 + "next:\n"), (None, "unparseable"))
        self.assertEqual(M.block_value(many(190) + "# c\n" * 11), (None, "unparseable"))
        # A line of the file, whichever key it is under.
        fill = lambda n: "    command: \"" + "a" * (n - 15) + "\"\n"
        self.assertEqual(len(fill(2000)), 2001)                          # 2,000 characters and the newline
        self.assertEqual(M.block_value("mcp_servers:\n  s:\n" + fill(2000))[0], {"s": {"command": "a" * 1985}})
        self.assertEqual(M.block_value("mcp_servers:\n  s:\n" + fill(2001)), (None, "unparseable"))
        self.assertEqual(M.block_value(box() + "# " + "x" * 1998 + "\n")[1], None)
        self.assertEqual(M.block_value(box() + "# " + "x" * 1999 + "\n"), (None, "unparseable"))
        self.assertEqual(M.block_value(box() + "notes:\n  text: " + "x" * 2000 + "\n"), (None, "unparseable"))
        # An integer is at most 18 digits.
        self.assertEqual(M.block_value("mcp_servers:\n  s:\n    k: " + "9" * 18 + "\n")[0], {"s": {"k": 10 ** 18 - 1}})

    def test_never_raises_on_fuzz(self):
        rng = random.Random(20261002)
        alphabet = sorted(set(REWRITTEN_BLOCK + TEMPLATE_BLOCK)) + list("&*!|>{}[],'\"#:\t-? ") + ["\n"] * 6
        pieces = ["mcp_servers:", "mcp_servers: ", "\n", "\n  ", "\n    ", "\n      ", "- ", ": ", "{}", "[]", "[a, b]",
                  "true", "360", '"x"', "'x'", "key:", "key: v", "# c", "---", "<<:", "\r", "\x00", "\ufeff", "\u2028"]
        base = box()
        parsed = 0
        for i in range(6000):
            kind = i % 3
            if kind == 0:                                    # random characters
                text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 200)))
            elif kind == 1:                                  # random pieces of the grammar
                text = "".join(rng.choice(pieces) for _ in range(rng.randrange(0, 40)))
            else:                                            # the real file with a few characters changed
                chars = list(base)
                for _ in range(rng.randrange(1, 4)):
                    at = rng.randrange(len(chars))
                    chars[at:at + rng.randrange(0, 2)] = rng.choice(alphabet)
                text = "".join(chars)
            got = M.block_value(text)                        # an exception fails the test, with the seed above
            self.assertIsInstance(got, tuple, repr(text))
            self.assertEqual(len(got), 2, repr(text))
            value, reason = got
            if value is None:
                self.assertIn(reason, ("no_block", "duplicate_key", "top_level_not_plain", "unparseable"), repr(text))
            else:
                self.assertIsNone(reason, repr(text))
                self.assertIsInstance(value, dict, repr(text))
                M.canonical(value)
                parsed += 1
            self.assertIn(M.compare(text, base)["reason"], M.REASONS, repr(text))
        self.assertGreater(parsed, 50)                       # the fuzz reaches the builder, not only the refusals


class TestCompare(unittest.TestCase):
    def test_the_reasons_are_the_closed_set(self):
        self.assertEqual(M.REASONS, ("-", "no_block", "duplicate_key", "top_level_not_plain", "unparseable", "differs"))

    def test_compare_reports_the_boxs_reason_and_sha(self):
        self.assertEqual(M.compare(box(), template()),
                         {"equals_repo": True, "reason": "-", "canonical_sha256": sha(EXPECTED)})
        self.assertEqual(sha(EXPECTED), hashlib.sha256(
            b'{"ads_audit":{"args":["/opt/cc-bin/hermes-app-mcp.py","--app","ads-audit"],"command":"python3",'
            b'"env":{},"timeout":360,"tools":{"include":["ads_audit_run","ads_audit_status","ads_audit_list"],'
            b'"prompts":false,"resources":false}}}').hexdigest())
        changed = dict(EXPECTED, other={"command": "sh"})
        self.assertEqual(M.compare(box(REWRITTEN_BLOCK + "  other:\n    command: sh\n"), template()),
                         {"equals_repo": False, "reason": "differs", "canonical_sha256": sha(changed)})
        for text, reason in ((BOX_HEAD + BOX_TAIL, "no_block"), ("", "no_block"),
                             (box() + "mcp_servers:\n  evil:\n    command: sh\n", "duplicate_key"),
                             (box(REWRITTEN_BLOCK + "    env: {}\n"), "duplicate_key"),
                             (box() + '"mcp_servers":\n  evil:\n    command: sh\n', "top_level_not_plain"),
                             (box(REWRITTEN_BLOCK.replace("env: {}", "env: {A: b}")), "unparseable"),
                             (box().replace("\n", "\r\n"), "unparseable")):
            with self.subTest(reason=reason):
                self.assertEqual(M.compare(text, template()),
                                 {"equals_repo": False, "reason": reason, "canonical_sha256": None})

    def test_repo_text_without_a_block_raises_valueerror(self):
        for repo in ("", TEMPLATE_HEAD, template() + "mcp_servers:\n", template() + "---\n",
                     template(TEMPLATE_BLOCK.replace("env: {}", "env: {A: b}")), template("mcp_servers: {}\n")):
            for box_text in (box(), "", box() + "---\n"):
                with self.subTest(repo=repo[-30:]):
                    with self.assertRaises(ValueError) as cm:
                        M.compare(box_text, repo)
                    self.assertNotIn("\n", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
