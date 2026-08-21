"""Invariants asserted against the REAL registry/projects.yaml.

Every other suite in this directory builds a synthetic registry fixture, which is
right for exercising parser edge cases but means a bad edit to the actual
`registry/projects.yaml` is caught only at runtime, by apply-changeset.py's
guard 8, at the moment someone tries to apply a change-set. That is a fail-closed
guard and the account stays safe — but the feedback arrives late and only on the
mutation path, so a mistake on the READ side is never caught at all.

This suite closes that gap: it asserts the invariants against the file that ships.
It is deliberately narrow — structure and safety invariants only, no behaviour —
so it stays green as readers are added and does not become a change-detector.

Stdlib-only, like every suite here. Discovered automatically by run-bin-tests.sh.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, os.pardir, "registry", "projects.yaml")

# Mutating scripts in claude-google-ads that must NEVER appear on a read allow-list.
# Hardcoded deliberately: this is a security denylist, not an inventory, and it must
# not silently shrink because a discovery helper stopped finding something.
# `mutate_campaign_negative` is the one governed mutator and belongs to
# mutate_execute only; the other four are the ungoverned repo mutators, now guarded
# at the script via code/injected_credentials.py.
KNOWN_MUTATORS = (
    "mutate_campaign_negative",
    "add_campaign_negative",
    "add_competitor_negatives",
    "apply_negatives",
    "attach_audience",
)


def discover_projects(path):
    """Project names = keys at exactly one indent level under `projects:`.

    Discovered, never hardcoded — a project added to the registry is covered by
    these invariants without editing this file.
    """
    names = []
    in_projects = False
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if line.rstrip() == "projects:":
                in_projects = True
                continue
            if in_projects:
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    in_projects = False          # left the projects block
                    continue
                if indent == 2 and stripped.endswith(":"):
                    names.append(stripped[:-1].strip())
    return names


class TestRegistryDiscovery(unittest.TestCase):
    def test_registry_exists(self):
        self.assertTrue(os.path.isfile(REGISTRY), f"registry not found: {REGISTRY}")

    def test_discovers_at_least_one_project(self):
        # Guards the discovery helper itself: if the indentation convention ever
        # changes, every other test here would vacuously pass on an empty list.
        self.assertTrue(discover_projects(REGISTRY), "discovered no projects — helper is blind")


class TestAllowListInvariants(unittest.TestCase):
    def setUp(self):
        self.projects = discover_projects(REGISTRY)

    def test_read_and_mutate_allow_lists_are_disjoint(self):
        for p in self.projects:
            with self.subTest(project=p):
                C.assert_allow_lists_disjoint(
                    C.read_allow_list(REGISTRY, p, "read_execute"),
                    C.read_allow_list(REGISTRY, p, "mutate_execute"),
                )

    def test_disjointness_check_actually_fires(self):
        # Negative control: without this, the test above passes even if
        # assert_allow_lists_disjoint were gutted to a no-op.
        with self.assertRaises(ValueError):
            C.assert_allow_lists_disjoint(["account_overview"], ["account_overview"])

    def test_no_known_mutator_on_any_read_allow_list(self):
        for p in self.projects:
            read_allow = C.read_allow_list(REGISTRY, p, "read_execute")
            for m in KNOWN_MUTATORS:
                with self.subTest(project=p, mutator=m):
                    self.assertNotIn(
                        m, read_allow,
                        f"{m!r} is a mutator and must never be on a read allow-list")

    def test_allow_list_entries_are_bare_basenames(self):
        # Path separators / traversal in an allow-list entry would defeat the
        # resolver's fail-closed name check.
        for p in self.projects:
            for block in ("read_execute", "mutate_execute"):
                for name in C.read_allow_list(REGISTRY, p, block):
                    with self.subTest(project=p, block=block, name=name):
                        self.assertEqual(os.path.basename(name), name)
                        self.assertNotIn(os.sep, name)
                        self.assertNotIn("..", name)

    def test_no_duplicate_entries_within_an_allow_list(self):
        for p in self.projects:
            for block in ("read_execute", "mutate_execute"):
                names = C.read_allow_list(REGISTRY, p, block)
                with self.subTest(project=p, block=block):
                    self.assertEqual(len(names), len(set(names)),
                                     f"duplicate entry in {block}.allow for {p}")


class TestMutateTierInvariants(unittest.TestCase):
    def setUp(self):
        self.projects = discover_projects(REGISTRY)

    def test_mutate_allow_holds_at_most_one_entry(self):
        # apply-changeset.py guard 8 refuses anything other than exactly one entry.
        # Asserting it here turns a runtime refusal into a test failure.
        for p in self.projects:
            allow = C.read_allow_list(REGISTRY, p, "mutate_execute")
            with self.subTest(project=p):
                self.assertLessEqual(len(allow), 1,
                                     "mutate_execute.allow must hold at most one entry")

    def test_mutate_execute_blocks_parse_with_fail_closed_caps(self):
        # read_mutate_execute raises on a missing/malformed cap. Any project that
        # declares a mutate tier must parse cleanly, caps included.
        for p in self.projects:
            if not C.read_allow_list(REGISTRY, p, "mutate_execute"):
                continue
            with self.subTest(project=p):
                cfg = C.read_mutate_execute(REGISTRY, p)
                self.assertTrue(cfg["runner"])
                self.assertTrue(cfg["script_dir"])
                for cap, val in cfg["caps"].items():
                    self.assertGreaterEqual(val, 1, f"cap {cap} must be >= 1")


def _service_block(compose_text, service):
    """Lines belonging to `<service>:` in docker-compose's `services:` map (an
    indent-2 key), excluding the header line itself.

    Scoping every mount check below to ONE service is the point: a mount that
    exists only on a DIFFERENT service (e.g. ads-mutator) must never be able to
    satisfy an assertion about whether the gateway (hermes-agent) is masked.
    """
    lines = compose_text.split("\n")
    block = []
    in_service = False
    header = "  %s:" % service
    for line in lines:
        if line.rstrip() == header:
            in_service = True
            continue
        if in_service:
            if line.strip() and (len(line) - len(line.lstrip(" "))) <= 2:
                break                       # next top-level service (or dedent past services:)
            block.append(line)
    return block


def _volumes_entries(service_block):
    """(indent, content) for every non-comment line inside the service's
    `volumes:` list.

    Whole-line comments are dropped entirely and inline comments stripped, so a
    mask path that appears only in a COMMENT can never be mistaken for a mount —
    closing exactly the gap a raw substring search over the whole file left open.
    """
    out = []
    in_volumes = False
    for raw in service_block:
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 4:
            in_volumes = (stripped == "volumes:")
            continue
        if in_volumes:
            content = re.sub(r"\s+#.*$", "", raw).strip()
            if content:
                out.append((indent, content))
    return out


def _mount_target_present(entries, target):
    """True iff `target` is the destination of a REAL mount entry in `entries`.

    Covers both mask syntaxes this project uses, and only those two shapes —
    neither branch matches a bare substring appearing anywhere else (a comment,
    a different service, a source path that happens to contain `target`):

      - bind / short form:  "- <src>:<target>[:<mode>]"   (e.g. the ads .env mask)
      - tmpfs / long form:  "- type: tmpfs" immediately followed (within the same
        list item, before the next list item at the same indent) by
        "target: <target>"                                (e.g. the repo-dir mask)
    """
    esc = re.escape(target)
    bind_re = re.compile(r"^-\s+\S.*:%s(:\S+)?$" % esc)
    for indent, content in entries:
        if indent == 6 and bind_re.match(content):
            return True
    for idx, (indent, content) in enumerate(entries):
        if indent == 6 and content == "- type: tmpfs":
            for nxt_indent, nxt_content in entries[idx + 1:]:
                if nxt_indent <= 6:
                    break                    # next list item: this tmpfs entry had no target
                if nxt_indent == 8 and nxt_content == "target: %s" % target:
                    return True
    return False


class TestMaskPathsAreActuallyMounted(unittest.TestCase):
    """A declared mask that compose does not implement is worse than no declaration:
    it reads as protection while providing none.

    Every check here is scoped to the `hermes-agent` service's `volumes:` list and
    anchored to real mount syntax — not a raw substring search over the whole file
    — because that is the ONLY service the AI agent has a shell in. A mount on a
    different service, or the path merely appearing in a comment, must not be able
    to satisfy these assertions.
    """

    SERVICE = "hermes-agent"

    def setUp(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "docker-compose.yml"), encoding="utf-8") as f:
            self.compose = f.read()
        self.entries = _volumes_entries(_service_block(self.compose, self.SERVICE))

    def test_reader_finds_the_declarations(self):
        """Guards the reader itself: if the indentation convention changes, the
        assertion below would pass vacuously on an empty list."""
        total = sum(len(C.read_mask_paths(REGISTRY, p))
                    for p in discover_projects(REGISTRY))
        self.assertGreater(total, 0, "read_mask_paths found nothing — reader is blind")

    def test_every_declared_mask_has_a_mount(self):
        for project in discover_projects(REGISTRY):
            workdir = C.read_workdir(REGISTRY, project)
            for rel in C.read_mask_paths(REGISTRY, project):
                target = "%s/%s" % (workdir.rstrip("/"), rel)
                self.assertTrue(
                    _mount_target_present(self.entries, target),
                    "project %r declares mask_paths entry %r but no REAL mount "
                    "targeting %s exists in %s's volumes: (a comment mentioning "
                    "the path, or a mount on a different service, does not count)"
                    % (project, rel, target, self.SERVICE))

    def test_a_bogus_target_would_be_caught(self):
        """Control: prove the containment check can fail."""
        self.assertNotIn("/projects/claude_code/definitely-not-mounted", self.compose)
        self.assertFalse(
            _mount_target_present(self.entries, "/projects/claude_code/definitely-not-mounted"))

    def test_a_comment_only_mention_would_not_count(self):
        """Control: the exact failure mode the scoping fix closes. A path that
        appears ONLY inside a comment (never as a real mount target) must not
        satisfy _mount_target_present — otherwise a declared mask could pass this
        suite while protecting nothing."""
        fake_entries = [(6, "# see /projects/claude_code/infra/hermes-agent for context")]
        self.assertFalse(_mount_target_present(fake_entries, "/projects/claude_code/infra/hermes-agent"))

    def test_a_mount_on_another_service_would_not_count(self):
        """Control: a real mount for the same target string, but scoped to a
        DIFFERENT service's volumes:, must not satisfy the hermes-agent check —
        that is exactly 'the mask exists on ads-mutator while the gateway stays
        unmasked', the scenario the review flagged."""
        other_entries = _volumes_entries(_service_block(self.compose, "ads-mutator"))
        self.assertFalse(
            _mount_target_present(other_entries, "/projects/claude_code/infra/hermes-agent"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
