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
