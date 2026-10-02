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
