#!/usr/bin/env python3
import importlib.util, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CHECKLIST = os.path.join(os.path.dirname(HERE), "deploy", "security-review", "CHECKLIST.md")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def items():
    text = open(CHECKLIST).read()
    found = {}
    for block in re.split(r"(?m)^### ", text)[1:]:
        m = re.match(r"(D\d+\.\d+) — ", block)
        s = re.search(r"(?m)^- \*\*source:\*\* (box|laptop|manual)\s*$", block)
        if m:
            found[m.group(1)] = s.group(1) if s else None
    return text, found


class TestChecklistSync(unittest.TestCase):
    def test_has_a_version(self):
        self.assertRegex(items()[0], r"(?m)^version: \d+\.\d+$")

    def test_every_item_declares_a_source(self):
        self.assertEqual({k: v for k, v in items()[1].items() if v is None}, {})

    def test_box_items_equal_the_box_collector(self):
        box = {k for k, v in items()[1].items() if v == "box"}
        self.assertEqual(box, set(_load("ce", "collect-review-evidence.py").PROBES))

    def test_laptop_items_equal_the_laptop_collector(self):
        lap = {k for k, v in items()[1].items() if v == "laptop"}
        self.assertEqual(lap, set(_load("cl", "collect-review-evidence-laptop.py").ITEMS))

    def test_d2_1_and_d4_1_name_every_non_google_secret_label_the_collector_can_emit(self):
        """Review #8's first draft bumped `secrets_held` and left the `credentials` sentence naming
        four labels: a healthy box would have failed D2.1. Every label the collector lists must be
        named in D2.1 (among them in its `credentials` sentence), every gateway label in D4.1,
        and the count the checklist states must be the number of labels."""
        ce = _load("ce", "collect-review-evidence.py")
        labels = [label for names in ce.OTHER_SECRET_NAMES.values() for _, label in names]
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        sentence = re.search(r"A `credentials` row whose label is not one of those (\w+) \(([^)]*)\)", blocks["D2.1"])
        self.assertIsNotNone(sentence)
        words = {"four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
        self.assertEqual(words[sentence.group(1)], len(labels))
        self.assertEqual(sorted(re.findall(r"`([a-z-]+)`", sentence.group(2))), sorted(labels))
        for label in labels:
            self.assertIn(f"`{label}`", blocks["D2.1"])
        for _, label in ce.OTHER_SECRET_NAMES[ce.GATEWAY_ENV_FILE]:
            self.assertIn(f"`{label}`", blocks["D4.1"], label)
        self.assertEqual({l for l in ce.UNFINGERPRINTED}, {l for l in labels if f"`{l}` with `sha12: null`" in blocks["D2.1"]})

    def test_d4_5_names_every_field_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        import tempfile
        host = ce.Host(tempfile.mkdtemp(), lambda argv, timeout=60: (0, "", ""))
        for field in ce.d4_5(host, {}):
            self.assertIn(f"`{field}`", blocks["D4.5"], field)

    def test_d1_7_and_d4_6_name_every_field_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        import tempfile
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "etc"))
        with open(os.path.join(root, "etc/passwd"), "w") as f:
            f.write("root:x:0:0:root:/root:/bin/bash\n")
        os.makedirs(os.path.join(root, "root/.ssh"))
        with open(os.path.join(root, "root/.ssh/authorized_keys"), "w") as f:
            f.write("ssh-ed25519 " + "A" * 68 + "\n")
        host = ce.Host(root, lambda argv, timeout=60: (0, "authorizedkeysfile .ssh/authorized_keys\n", ""))
        d1_7 = ce.d1_7(host, {})
        for field in [*d1_7, *d1_7["sshd"], *d1_7["files"][0], *d1_7["files"][0]["keys"][0]]:
            self.assertIn(f"`{field}`", blocks["D1.7"], field)
        d4_6 = ce.d4_6(host, {})
        for field in [*d4_6, *d4_6["started_at"]]:
            self.assertIn(f"`{field}`", blocks["D4.6"], field)

    def test_d2_3_and_d10_7_name_the_reach_fields(self):
        ce = _load("ce", "collect-review-evidence.py")
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        import tempfile
        root = tempfile.mkdtemp()
        reg = root + ce.GOV + "/registry/clients.json"
        os.makedirs(os.path.dirname(reg))
        with open(reg, "w") as f:
            f.write('{"clients": {}}')
        host = ce.Host(root, lambda argv, timeout=60: (0, "", ""))
        d23 = ce.d2_3(host, {})
        d107 = ce.d10_7(host, ce.context(host, b"\x11" * 32))
        for field in (*d23, ):
            self.assertIn(f"`{field}`", blocks["D2.3"], field)
        for field in ("oldest_entry_read", *d107["oldest_entry_read"]):
            self.assertIn(f"`{field}`", blocks["D10.7"], field)
        self.assertEqual(sorted(d107["oldest_entry_read"]), ["broker", "runner"])

    def test_d2_3_says_how_many_days_it_covered_and_when_it_stands_for_30(self):
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D2.3"]
        rule = next(l for l in block.split("\n") if l.startswith("- **pass rule:**"))
        for words in ("`reach_days` of at least `30`", "states the days the search covered", "in either direction",
                      "under two days"):
            self.assertIn(words, rule, words)
        self.assertIn("read as root only", block)
        for words in ("replacement characters", "namespaces", "300 thousand", "can be stored"):
            self.assertIn(words, block, words)
        self.assertNotIn("is can be", block)
        self.assertIn("not run as root", rule)

    def test_d10_7_says_what_the_report_states_when_the_journal_is_short(self):
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D10.7"]
        rule = next(l for l in block.split("\n") if l.startswith("- **pass rule:**"))
        claim = next(l for l in block.split("\n") if l.startswith("- **claim:**"))
        self.assertIn("states the days", rule)
        self.assertIn("up to 30 days back", claim)
        self.assertNotIn("(30 days)", claim)

    def test_d2_4_names_every_field_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D2.4"]
        import tempfile
        root = tempfile.mkdtemp()
        files = {"/etc/systemd/journald.conf": "[Journal]\nSystemMaxUse=1G\nMaxRetentionSec=7day\nMaxFileSec=1day\n",
                 ce.JOURNALD_DROP_IN: "[Journal]\nMaxRetentionSec=35day\nSystemMaxFiles=500\n"}
        for path, body in files.items():
            os.makedirs(os.path.dirname(root + path), exist_ok=True)
            with open(root + path, "w") as f:
                f.write(body)
        cat = "\n".join(f"# {p}\n{c}" for p, c in files.items())
        host = ce.Host(root, lambda argv, timeout=60: (0, cat if argv == ce.JOURNALD_CAT_CONFIG else "", ""))
        d = ce.d2_4(host, {})
        self.assertEqual(sorted(d["service"]), ["active", "config_changed_after_start", "started_at"])
        self.assertEqual(list(d["usage"])[-3:], ["newest_entry_on_disk", "on_disk_age_seconds", "flushed_to_disk"])
        self.assertIn("`/run/systemd/journal/flushed`", block)
        self.assertIn("Storage", d["settings"])
        for word in ("auto", "persistent", "volatile", "none"):
            self.assertIn(f"`{word}`", block, word)
        self.assertEqual(d["config_files"], list(files))                # the real dict, not could-not-check
        self.assertEqual(sorted(d["settings"]), sorted(ce.JOURNALD_SETTINGS))
        for part in ("oldest_entry", "drop_in", "service", "usage"):
            self.assertIsInstance(d[part], dict, part)
        fields = [*d, *d["oldest_entry"], *d["settings"], *d["settings"]["MaxRetentionSec"], *d["drop_in"],
                  *d["service"], *d["usage"]]
        for field in fields:
            self.assertIn(f"`{field}`", block, field)
        self.assertIn(f"`{ce.JOURNALD_DROP_IN}`", block)
        self.assertIn("`/etc/systemd/journald.conf.d/50-hermes-retention.conf`", block)
        self.assertIn("`2592000`", block)
        self.assertIn("`" + " ".join(ce.JOURNALD_CAT_CONFIG) + "`", block)
        for d_ in ce.JOURNALD_DROP_IN_DIRS:
            self.assertIn(f"`{d_}`", block)
        lines = [l for l in block.split("\n")[1:] if l and not l.startswith("## ")]
        self.assertEqual([l.split("**")[1] for l in lines if l.startswith("- **")],     # four bullets, one line each
                         ["source:", "claim:", "expected:", "pass rule:"])
        self.assertEqual(len(lines), 4)

    def test_d2_4_keeps_the_words_that_carry_its_rulings(self):
        """Each of these was a ruling after a review found a route to a wrong PASS; an edit must not drop one quietly."""
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D2.4"]
        rule = next(l for l in block.split("\n") if l.startswith("- **pass rule:**"))
        parts = dict(re.findall(r"\((\d)\) \*\*([^*]+):\*\*", rule))
        self.assertEqual(parts, {"1": "Not read", "2": "The setting", "3": "In force", "4": "Written to disk",
                                 "5": "The reach", "6": "The limits", "7": "Other directories", "8": "No missing days"})
        text = dict(zip(parts.values(), re.split(r"\(\d\) \*\*[^*]+:\*\*", rule)[1:]))
        for part, words in (("Not read", ("WHOLE item", "`usage.on_disk_age_seconds`", "`usage.flushed_to_disk`", "`service.active`", "informational")),
                            ("The setting", ("`volatile`, `none` or any other value is a FAIL", "`0`, which systemd reads as no limit")),
                            ("In force", ("`service.active` other than `true` is CANNOT-VERIFY",)),
                            ("Written to disk", ("`usage.flushed_to_disk` other than `true` is CANNOT-VERIFY", "`usage.on_disk_age_seconds` above `600`",
                                                "either alone")),
                            ("The limits", ("no explanation replaces the measurement", "`reach_days` as measured is at least `30`")),
                            ("No missing days", ("`usage.files` lower than `reach_days`",))):
            for w in words:
                self.assertIn(w, text[part], (part, w))
        self.assertNotIn("for its part", rule)
        self.assertNotIn("less than 600 seconds before the collection", rule)
        self.assertNotIn("unless the operator explains it: at a limit", rule)

    def test_d1_7_states_the_limited_keys_exact_options(self):
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        for opt in ('command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                    "port-forwarding", "restrict"):
            self.assertIn(f"`{opt}`", blocks["D1.7"], opt)

    def test_the_version_is_1_19(self):
        self.assertRegex(items()[0], r"(?m)^version: 1\.19$")

    def test_d10_6_states_the_committed_mcp_block(self):
        """D10.6 judges the box's `mcp_servers:` block by `equals_repo`, `reason` and the sha256 of
        its canonical form, which the checklist states: it must be config.yaml.example's, as the
        collector's parser computes it, so changing the committed block's values means changing
        (and re-versioning) this file. The line count and the sha256 of the lines are gone: they
        described layout, which the gateway rewrites."""
        import mcp_config
        with open(os.path.join(os.path.dirname(HERE), "config.yaml.example"), encoding="utf-8") as f:
            template = f.read()
        pinned = mcp_config.compare(template, template)
        self.assertEqual((pinned["equals_repo"], pinned["reason"]), (True, "-"))
        self.assertRegex(pinned["canonical_sha256"], r"^[0-9a-f]{64}$")
        d10_6 = re.split(r"(?m)^### ", items()[0])
        d10_6 = next(b for b in d10_6 if b.startswith("D10.6 — "))
        self.assertIn(f"`mcp_block.canonical_sha256` is `{pinned['canonical_sha256']}`", d10_6)
        self.assertEqual(re.findall(r"\b[0-9a-f]{64}\b", d10_6), [pinned["canonical_sha256"]])
        self.assertIn("`mcp_block.equals_repo` is `true`", d10_6)
        self.assertIn("`mcp_block.reason` is `-`", d10_6)
        for gone in ("mcp_block.lines", "mcp_block.sha256", "`lines`", "`sha256`"):
            self.assertNotIn(gone, d10_6)
        for reason in mcp_config.REASONS:                            # every reason the collector can emit is named
            self.assertIn(f"`{reason}`", d10_6)

    def test_every_area_d1_to_d10_is_present(self):
        areas = {k.split(".")[0] for k in items()[1]}
        self.assertEqual(areas, {f"D{i}" for i in range(1, 11)})


if __name__ == "__main__":
    unittest.main()
