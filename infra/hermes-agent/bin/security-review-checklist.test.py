#!/usr/bin/env python3
import importlib.util, json, os, re, sys, unittest
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


def blocks():
    return {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}


def part(block, name):
    return next(l for l in block.split("\n") if l.startswith(f"- **{name}:**"))


def d10_lead():
    return re.search(r"(?ms)^## D10 Chat-triggered apps\n(.*?)^### D10\.1 ", items()[0]).group(1)


JOBS = ("ads-audit", "ads-report")


RESULT_PATHS = {"ads-audit": "/var/lib/hermes/vaults/acme-dental/audits/2026-10-01_12-00-00-audit.md",
                "ads-report": "/var/lib/hermes/report-archive/acme-dental/2026-10-01_12-00-00-report.md"}


def two_job_box(ce, installed=JOBS):
    """A fake box that declares the two jobs of the repository's description files. The jobs in
    `installed` are loaded by systemd, hold their directories and one well-formed `ok` result, and
    the report store (one client folder, one file) exists only when `ads-report` is among them."""
    import shutil, tempfile
    root = tempfile.mkdtemp()
    shutil.copytree(os.path.join(os.path.dirname(HERE), "registry", "apps"), root + ce.APPS_DIR)
    reg = root + ce.GOV + "/registry/clients.json"
    os.makedirs(os.path.dirname(reg))
    with open(reg, "w") as f:
        f.write('{"clients": {"acme-dental": {"status": "active"}}}')
    if "ads-report" in installed:
        folder = root + "/var/lib/hermes/report-archive/acme-dental"
        os.makedirs(folder)
        with open(folder + "/2026-10-01_08-00-00-report.md", "w") as f:
            f.write("x")
    for app in installed:
        rid = "0f8e2c1a-1111-4222-8333-444455556666"
        os.makedirs(root + ce.HL.DEFAULT_APPS_ROOT + "/" + app + "/results")
        with open(root + ce.HL.DEFAULT_APPS_ROOT + "/" + app + "/results/" + rid + ".json", "w") as f:
            json.dump({"request_id": rid, "op": "run", "client": "acme-dental", "status": "ok", "reason": None,
                       "exit_code": 0, "ts": "2026-10-01_12-00-00", "steps": [], "vault_path": RESULT_PATHS[app]}, f)
    units = "".join(f"hermes-app-{kind}@{app}.service loaded active running x\n"
                    for app in installed for kind in ("broker", "runner"))
    host = ce.Host(root, lambda argv, timeout=60: (0, units if argv[:2] == ["systemctl", "list-units"] else "", ""))
    return host, ce.context(host, b"\x11" * 32)


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
        self.assertEqual({"apps_declared", "apps_installed"} - set(d4_6), set())
        two, ctx = two_job_box(ce)
        d4_6 = ce.d4_6(two, ctx)
        self.assertEqual((d4_6["apps_declared"], d4_6["apps_installed"]), (list(JOBS), list(JOBS)))
        for name in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
            for app in JOBS:                                     # one broker key per job, in each of the four
                self.assertIn("hermes-app-broker@" + app, d4_6[name], (name, app))
        self.assertIn("`hermes-app-broker@<app>`", blocks["D4.6"])
        for app in JOBS:                                         # no job is named: the collector finds them
            self.assertNotIn(app, blocks["D4.6"], app)

    def test_d2_3_and_d10_7_name_the_reach_fields(self):
        ce = _load("ce", "collect-review-evidence.py")
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        host, ctx = two_job_box(ce)
        d23 = ce.d2_3(host, {})
        d107 = ce.d10_7(host, ctx)
        for field in (*d23, ):
            self.assertIn(f"`{field}`", blocks["D2.3"], field)
        self.assertEqual(sorted(d107["apps"]), sorted(JOBS))
        for app in JOBS:
            for field in ("oldest_entry_read", *d107["apps"][app]["oldest_entry_read"]):
                self.assertIn(f"`{field}`", blocks["D10.7"], field)
            self.assertEqual(sorted(d107["apps"][app]["oldest_entry_read"]), ["broker", "runner"])

    def test_d2_3_says_how_many_days_it_covered_and_when_it_stands_for_30(self):
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D2.3"]
        rule = next(l for l in block.split("\n") if l.startswith("- **pass rule:**"))
        for words in ("`reach_days` of at least `30`", "states the days the search covered", "in either direction",
                      "under two days"):
            self.assertIn(words, rule, words)
        self.assertIn("read as root only", block)
        for words in ("replacement characters", "namespaces", "2.5 million", "EVERY STORED FIELD"):
            self.assertIn(words, block, words)
        self.assertNotIn("-o cat", block)
        self.assertIn("--all", block)
        self.assertNotIn("is can be", block)
        self.assertIn("not run as root", rule)

    def test_d10_7_names_every_field_its_customer_id_count_skips(self):
        ce = _load("ce", "collect-review-evidence.py")
        block = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}["D10.7"]
        for name in sorted(ce.CID_SKIP_FIELDS):
            self.assertIn(f"`{name}`", block, name)
        self.assertIn("journal_read", block)

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
        two, ctx = two_job_box(ce)
        apps = ce.d2_4(two, ctx)["oldest_entry"]["apps"]
        self.assertEqual(sorted(apps), sorted(JOBS))             # one entry per declared job
        for app in JOBS:
            for field in apps[app]:
                self.assertIn(f"`{field}`", block, field)
            self.assertNotIn(app, block, app)
        for words in ("`apps.<app>`", "`oldest_entry.apps`", "`hermes-app-broker@<app>`", "`hermes-app-runner@<app>`"):
            self.assertIn(words, block, words)
        self.assertNotIn("`oldest_entry.broker`", block)         # the keys of v1.20, gone from the bundle
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

    def test_the_version_is_1_22(self):
        text = items()[0]
        self.assertRegex(text, r"(?m)^version: 1\.22$")
        for words in ("(v1.21: the review covers every chat-triggered job the box declares: D10.3, D10.4, D10.7 and "
                      "D10.8 run once per job, D2.4 and D4.6 name every job's units, and D10.3 compares the jobs "
                      "declared with the jobs installed. A second job, `ads-report` (figures only). The report store "
                      "joins D4.1 and D7.1. D10.1 reports the services a figures run would start. D10.6: six tools.",
                      "A value that could not be checked for one installed job is CANNOT-VERIFY for the item. A job "
                      "is declared, installed or on disk, and each per-job entry says whether the job is declared and "
                      "installed, and D10.3 lists the jobs on disk.)",
                      "(v1.22: D7.1 and D10.4: an in-memory mount (Docker's `tmpfs` type, listed with an empty host "
                      "path) has no host side and is left out when a container's mounts are judged"):
            self.assertIn(words, text.split("**How to read an item.**")[0], words)

    def test_d7_1_and_d10_4_say_that_an_in_memory_mount_is_left_out(self):
        blocks = {b.split(" ", 1)[0]: b for b in re.split(r"(?m)^### ", items()[0])}
        for item in ("D7.1", "D10.4"):
            self.assertIn("an in-memory mount, Docker's `tmpfs` type listed with an empty host path, has no host "
                          "side and is left out", blocks[item], item)
            self.assertIn("Stated limit (v1.22): a named volume (Docker's `volume` type) whose driver options point it "
                          "at a host folder", blocks[item], item)
            self.assertIn("whether any running container has a `volume` mount", blocks[item], item)

    def test_there_are_38_items(self):
        self.assertEqual(len(items()[1]), 38)

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
        self.assertTrue(d10_6.startswith("D10.6 — Hermes may call exactly six tools\n"))
        self.assertEqual(sorted(set(re.findall(r"\bads_(?:audit|report)_[a-z]+\b", d10_6))),
                         sorted(f"ads_{job}_{op}" for job in ("audit", "report") for op in ("run", "status", "list")))
        for words in ("The committed block is two servers", "`ads_audit`", "`ads_report`", '"--app", "ads-report"]',
                      "beyond the two servers and their six tools"):
            self.assertIn(words, d10_6, words)
        for gone in ("three-tool `include` with `env: {}`: one server", "exactly the three audit tools", "beyond the three"):
            self.assertNotIn(gone, d10_6)
        for gone in ("mcp_block.lines", "mcp_block.sha256", "`lines`", "`sha256`"):
            self.assertNotIn(gone, d10_6)
        for reason in mcp_config.REASONS:                            # every reason the collector can emit is named
            self.assertIn(f"`{reason}`", d10_6)

    def test_d4_1_and_d7_1_name_the_report_store(self):
        ce = _load("ce", "collect-review-evidence.py")
        b = blocks()
        self.assertIn("/var/lib/hermes/report-archive", ce.GATEWAY_PROBE_PATHS)
        absent = re.search(r"in `paths`, every one of these is `absent`: (.*?)\. ", part(b["D4.1"], "expected")).group(1)
        self.assertIn("`/var/lib/hermes/report-archive`", absent)
        host, ctx = two_job_box(ce)
        archive = ce.d7_1(host, ctx)["report_archive"]
        self.assertEqual(len(archive["rows"]), 1)
        self.assertEqual(len(archive["rows"][0]["files"]), 1)
        self.assertRegex(next(iter(archive["rows"][0]["files"])), r"^\S+ \S+ 0o\d+$")
        for field in ("report_archive", *archive, *archive["parent"], *archive["rows"][0]):
            self.assertIn(f"`{field}`", b["D7.1"], field)
        for kind in ("dir", "symlink", "file", "other"):
            self.assertIn(f"`{kind}`", b["D7.1"], kind)

    def test_d7_1_says_what_the_store_shows_before_the_report_job_is_installed(self):
        """Between the pull that declares `ads-report` and its installation there is no store: the
        three values the exception names must be the ones the collector emits then."""
        ce = _load("ce", "collect-review-evidence.py")
        host, ctx = two_job_box(ce, installed=("ads-audit",))
        job = ce.d10_3(host, ctx)["apps"]["ads-report"]
        self.assertEqual((job["declared"], job["installed"]), (True, False))
        archive = ce.d7_1(host, ctx)["report_archive"]
        self.assertEqual((archive["parent"], archive["rows"], archive["rows_listed"]), ("absent", [], False))
        rule = part(blocks()["D7.1"], "pass rule")
        self.assertIn("While `ads-report` is declared and not installed (D10.3) and the operator states so, a `parent` of "
                      "`absent` with no rows and `rows_listed` `false` is expected, and is neither a FAIL nor CANNOT-VERIFY; "
                      "once `ads-report` is installed, `absent` is a FAIL.", rule)
        self.assertIn("`rows_listed` `false` beside any other `parent`", rule)
        self.assertIn("A row `status` other than `active`, `retired` or `unregistered`", rule)

    def test_the_final_review_s_rulings_keep_their_words(self):
        b = blocks()
        # D4.2: the reload a job's installation causes, typed or made by `systemctl enable`
        d42 = part(b["D4.2"], "pass rule")
        self.assertIn('BRING-UP "Add a chat-triggered job" step 4 reloads the manager for every job added: a typed '
                      "`daemon-reload` when the first job's unit files are installed, and for a later job the reload "
                      "`systemctl enable` makes itself (no `daemon-reload` is typed; step 4 prints the proxy line's hash "
                      "before and after).", d42)
        self.assertIn("the manager was reloaded (`systemctl daemon-reload`, or `systemctl enable` or `disable` of a unit)", d42)
        self.assertNotIn("part 2 step 4", b["D4.2"])
        # D7.1: an entry of the store that could not be examined is counted, and is CANNOT-VERIFY
        expected, rule = part(b["D7.1"], "expected"), part(b["D7.1"], "pass rule")
        self.assertIn("`rows_not_read` is `0`", expected)
        self.assertIn("`files_not_read` `0`", expected)
        self.assertIn("a `rows_not_read` or any row's `files_not_read` above `0` (an entry was there and could not be "
                      "examined", rule)
        self.assertRegex(rule, r"`files_not_read` above `0` \([^)]*\), is CANNOT-VERIFY for the report store and so for the item")
        # D10 lead: a PASS under "declared and not installed" does not cover that job
        lead = d10_lead()
        self.assertIn("A PASS given under this statement does not cover that job: installing it is a change that needs "
                      "a new review before the job is treated as live; its off switch comes off at the runbook's "
                      "first-run step only to produce that review's evidence (one run and the three live refusals), "
                      "and goes back on if that review does not pass.", lead)
        self.assertNotIn("before its off switch is taken off", lead)      # an order the runbook cannot follow
        self.assertIn("The same wording covers a job that was disabled and left declared", lead)
        # D10.1: the two names and no other; the order carries no meaning
        self.assertNotIn("another order", b["D10.1"])
        self.assertIn("(these two names and no other; the order they come in carries no meaning)", part(b["D10.1"], "expected"))
        # D10.3 and D10.7 are titled for every job
        self.assertTrue(b["D10.3"].startswith("D10.3 — Every job's broker is sandboxed"), b["D10.3"][:80])
        self.assertTrue(b["D10.7"].startswith("D10.7 — Every job's broker journal shows the live checks"), b["D10.7"][:80])
        for item in ("D10.3", "D10.7"):
            self.assertEqual([l.split(":**")[0] for l in b[item].split("\n") if l.startswith("- **")],
                             ["- **source", "- **claim", "- **expected", "- **pass rule"], item)

    def test_the_report_template_s_store_line_names_the_counts_the_checklist_judges(self):
        line = next(l for l in open(os.path.join(os.path.dirname(CHECKLIST), "REPORT-TEMPLATE.md")).read().split("\n")
                    if l.startswith("- **Report store (D7.1 `report_archive`):**"))
        for key in ("rows_listed", "rows_not_read", "files_not_read", "containers_mounting", "containers_not_inspected"):
            self.assertIn(f"`{key}`", line, key)

    def test_d7_1_keeps_the_words_of_the_report_store_ruling(self):
        expected, rule = part(blocks()["D7.1"], "expected"), part(blocks()["D7.1"], "pass rule")
        for words in ("`parent` is a dict `owner` `root`, `group` `root`, `mode` `0o700`", "`rows_listed` is `true`",
                      "`kind` `dir`", "`status` `active`", "`listed` `true`", "`not_files` `0`",
                      "every key is exactly `root root 0o600`", "`containers_mounting` is `0`",
                      "`containers_not_inspected` is `0`"):
            self.assertIn(words, expected, words)
        for words in ("A `report_archive.parent` other than `root`, `root`, `0o700`", "whose `kind` is not `dir`",
                      "whose `not_files` is above `0`", "(offboarding removes the folder)",
                      "any `files` key other than `root root 0o600`", "a `containers_mounting` above `0`, is a FAIL",
                      "a `dir` row with `listed: false`",
                      "is CANNOT-VERIFY for the report store and so for the item",
                      "a bind reached through a symlinked host path is not resolved",
                      "once `ads-report` is installed, `absent` is a FAIL"):
            self.assertIn(words, rule, words)

    def test_d10_1_states_what_a_figures_run_starts(self):
        b = blocks()["D10.1"]
        self.assertIn('`probe.figures_services` is exactly `["ads-collector", "ads-reader"]`', part(b, "expected"))
        self.assertIn("A `probe.figures_services` that is any other list", part(b, "pass rule"))
        self.assertIn("a figures run must start no AI service", part(b, "pass rule"))

    def test_d4_6_says_which_jobs_it_covers(self):
        rule = part(blocks()["D4.6"], "pass rule")
        for words in ("`apps_declared` or `apps_installed` of `could-not-check` is CANNOT-VERIFY",
                      "not a job known only from its directories"):
            self.assertIn(words, rule, words)

    def test_the_per_job_items_name_no_single_job_as_the_job(self):
        b = blocks()
        for item in ("D10.3", "D10.4", "D10.7", "D10.8"):
            self.assertIn("each job", b[item], item)
            self.assertIn("`apps.<app>`", b[item], item)
            self.assertNotIn("ads-audit/", b[item], item)
            self.assertNotIn("@ads-audit", b[item], item)
        self.assertIn("`declared_apps`", b["D10.3"])
        lead = d10_lead()
        for words in ("`hermes-app-broker@<app>`", "`hermes-app-runner@<app>`", "`hermes-app-<app>`"):
            self.assertIn(words, lead, words)
        for words in ('`User: "hermes-app-<app>"`',
                      "`ReadWritePaths` exactly `/var/lib/hermes/spool/apps/<app> /var/lib/hermes/app-state/<app>`",
                      '`["hermes-app-<app>", "hermes"]`', "`hermes-app-broker@<app>.service`",
                      "`hermes-app-runner@<app>.service`", "`hermes-app-runner@<app>.path`"):
            self.assertIn(words, b["D10.3"], words)
        self.assertIn("`init-host-layout.py --app <app> --check`", b["D10.4"])

    def test_the_per_job_items_name_every_key_the_collector_reports(self):
        ce = _load("ce", "collect-review-evidence.py")
        b = blocks()
        host, ctx = two_job_box(ce)
        d = {item: ce.PROBES[item](host, ctx) for item in ("D10.3", "D10.4", "D10.7", "D10.8")}
        for item, got in d.items():
            self.assertEqual(sorted(got["apps"]), sorted(JOBS), item)
            fields = set(got)
            for app in JOBS:
                entry = got["apps"][app]
                self.assertEqual((entry["declared"], entry["installed"]), (True, True), (item, app))
                fields |= set(entry)
                for value in entry.values():                    # one level down: a unit's properties, the two journals
                    if isinstance(value, dict):
                        fields |= {k for k in value if app not in k}
                    if isinstance(value, list):
                        fields |= {k for row in value if isinstance(row, dict) for k in row}
            for field in sorted(fields):
                self.assertRegex(b[item], "`" + re.escape(field) + "(`|: )", (item, field))   # `key` or `key: value`
        self.assertEqual({"declared_apps", "installed_apps", "on_disk_apps", "units_not_counted", "on_disk_not_counted",
                          "installed_equal_repo", "apps"}, set(d["D10.3"]))
        for app in JOBS:
            self.assertEqual(d["D10.8"]["apps"][app], {"results": [{"op": "run", "status": "ok", "reason": "-", "keys_ok": True,
                                                                     "values_ok": True}],
                                                       "out_of_whitelist": 0, "declared": True, "installed": True}, app)
        for field in ("op", "status", "reason", "keys_ok", "values_ok"):
            self.assertRegex(b["D10.8"], "`" + field + "(`|: )", field)
        for field in ("layout_problems", "layout_reason", "first_entry",
                      "installed_since_last_pass", "known_secrets_checked", "out_of_whitelist"):
            self.assertIn(field, " ".join(b[i] for i in d), field)
        for reason in ce.LAYOUT_REASONS:
            self.assertIn(f"`{reason}`", b["D10.4"], reason)
        for count in (*ce.LEAK_COUNTS, *ce.READ_COUNTS):
            self.assertIn(f"`{count}`", b["D10.7"], count)

    def test_d10_7_and_d10_8_name_every_step_class(self):
        import app_lib
        b = blocks()
        self.assertIn("store", app_lib.STEP_CLASSES)
        for item in ("D10.7", "D10.8"):
            named = re.search(r"\(((?:`[a-z-]+`(?:, )?)+)\)", b[item].split("step class", 1)[1]).group(1)
            self.assertEqual(sorted(re.findall(r"`([a-z-]+)`", named)), sorted(app_lib.STEP_CLASSES), item)
        self.assertIn("`failed/store`", b["D10.7"])
        self.assertIn("`failed/store`", b["D10.8"])

    def test_d10_7_judges_a_job_installed_since_the_last_pass_from_its_first_entry(self):
        b = blocks()["D10.7"]
        self.assertIn("installed since the last PASS", b)
        self.assertIn("`first_entry`", b)
        rule = part(b, "pass rule")
        for words in ("A job whose `installed_since_last_pass` is `true` (its first journal entry is later than the "
                      "last PASS's collection, or it never logged) is judged from `first_entry`: the report states the "
                      "job's install date from the rollout record, the 30-day reach is not asked of it, and the three "
                      "live refusals and the one `ok` run are still required.",
                      "`null` (no `--last-pass-collected-at`) is CANNOT-VERIFY for that job's reach.",
                      "for each installed job",
                      "The new-job rule applies only to a job with `installed: true` that the operator states was installed "
                      "since the last PASS, with its install date.",
                      "`true` only says that the journal does not reach back to the last PASS: that job is judged as when the "
                      "value is `false`, its reach read from `oldest_entry_read` and D2.4.",
                      "a `first_entry` earlier than the stated install date is CANNOT-VERIFY unless explained",
                      "a `first_entry` of `null` means the job has not logged yet"):
            self.assertIn(words, rule, words)

    def test_the_d10_area_keeps_the_words_that_carry_the_rulings_on_jobs(self):
        """A job that could not be checked, a job declared and not installed, a job installed and not
        declared: each ruling answered a route to a wrong PASS, and an edit must not drop one quietly."""
        b, lead = blocks(), d10_lead()
        one_job = ("A `could-not-check` value under `apps.<app>` for a job with `installed: true` is CANNOT-VERIFY for "
                   "that job and therefore for the item")
        for where, text in (("lead", lead), *((i, part(b[i], "pass rule")) for i in ("D10.3", "D10.4", "D10.7", "D10.8"))):
            self.assertIn(one_job, text, where)
            self.assertIn("never judges the item by its status word alone", text, where)
            self.assertIn("`declared: true` and `installed: false`", text, where)
        for words in ("the leftovers of a removed job",
                      "values are then not judged; any count in its entry still is, as for a job that is declared and not installed",
                      "Unexplained, it is a FAIL",
                      "a figures run (`ads-report`) starts `ads-collector` and `ads-reader` only and opens no Anthropic credential",
                      "reads every job's entry",
                      "the normal state only between the pull that brings a job's description file and that job's installation",
                      "it is a FAIL unless the operator states that the job is not yet installed and that the review is "
                      "not a review of that job",
                      "its expected `could-not-check` values are then not judged, but any count in its entry still is",
                      "a leak count above `0` or an `out_of_whitelist` above `0` is a FAIL whatever the job's state"):
            self.assertIn(words, lead, words)
        for item in ("D10.4", "D10.7", "D10.8"):
            self.assertIn(one_job + " (an installed job with no description file that the operator explains as the leftovers "
                          "of a removed job is judged as the lead says)", part(b[item], "pass rule"), item)
        self.assertIn("or the containers could not be listed", part(b["D10.4"], "pass rule"))
        self.assertIn("There is no rollout exception here: the box's block must already hold both servers at the review",
                      part(b["D10.6"], "pass rule"))
        rule = part(b["D10.3"], "pass rule")
        for words in ("A job that is installed and not declared, or on disk only (a job in `on_disk_apps` that is in neither "
                      "`declared_apps` nor `installed_apps`)",
                      "a `units_not_counted` or `on_disk_not_counted` above `0`",
                      "is a FAIL unless the operator explains it (a job's leftovers after its removal; a mistyped unit name)",
                      "a stopped, disabled unit shows only through `on_disk_apps`"):
            self.assertIn(words, rule, words)
        self.assertIn("a bind reached through a symlinked host path is not resolved", part(b["D10.4"], "pass rule"))
        self.assertIn("a leak count above `0` is a FAIL whatever the job's state", part(b["D10.7"], "pass rule"))
        self.assertIn("an `out_of_whitelist` above `0` is a FAIL whatever the job's state", part(b["D10.8"], "pass rule"))

    def test_every_area_d1_to_d10_is_present(self):
        areas = {k.split(".")[0] for k in items()[1]}
        self.assertEqual(areas, {f"D{i}" for i in range(1, 11)})


if __name__ == "__main__":
    unittest.main()
