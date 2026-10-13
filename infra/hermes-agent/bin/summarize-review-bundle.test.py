#!/usr/bin/env python3
import importlib.util, io, json, math, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("summarize_review_bundle", os.path.join(HERE, "summarize-review-bundle.py"))
SB = importlib.util.module_from_spec(spec); spec.loader.exec_module(SB)
cspec = importlib.util.spec_from_file_location("collect_review_evidence", os.path.join(HERE, "collect-review-evidence.py"))
CE = importlib.util.module_from_spec(cspec); cspec.loader.exec_module(CE)

OURS = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
PLANT = "sk-or-v1-" + "0123456789abcdef" * 4
# What a sensitive value can look like and still pass a test of SHAPE: none of these may ever print.
PLANTS = (PLANT, "acmecorp", "host.example.com", "10.0.0.5", "ops@acme.com", "123-456-7890",
          "client-acme.json", "etc/passwd", "AKIAIOSFODNN7EXAMPLE", "deadbee")
ACCOUNTS = ("jsmith", "acme-ops")


JOBS = ("ads-audit", "ads-report")
BROKERS = tuple("hermes-app-broker@" + j for j in JOBS)
APP_UNIT_FILES = ("hermes-app-broker@.service", "hermes-app-runner@.service", "hermes-app-runner@.path")


def _setting(v, f, n):
    return {"value": v, "file": f, "number": n}


def _base():
    """What both shapes of the bundle hold alike: everything but the per-job items."""
    return {"schema": 1, "kind": "box", "collected_at": "2026-10-20T14:00:00Z",
            "fingerprint": {"complete": True, "sha256": "ab" * 32},
            "credentials": [{"role": "read", "refresh_token_sha12": "0123456789ab"},
                            {"label": "openrouter-key", "sha12": "ba9876543210"}],
            "items": {
                "D1.1": {"status": "observed", "data": {"listeners": ["tcp 0.0.0.0:22", "tcp 127.0.0.1:9119"]}},
                "D1.7": {"status": "observed", "data": {
                    "accounts_checked": 34, "unprivileged_port_start": 1024, "match_lines": 0, "include_elsewhere": 0,
                    "daemon_options": {"listeners": 1, "config_file_options": 0, "setting_options": 0},
                    "sshd": {"gatewayports": "no", "authorizedkeysfile": ".ssh/authorized_keys .ssh/authorized_keys2"},
                    "files": [{"path": "/home/acme-ops/.ssh/authorized_keys", "users": list(ACCOUNTS), "kind": "file",
                               "owner": "acme-ops", "group": "jsmith", "mode": "0o600", "unparsed_lines": 0,
                               "keys": [{"type": "ssh-ed25519", "options": [], "sha12": "aaaaaaaaaaaa"},
                                        {"type": "ssh-ed25519", "sha12": "bbbbbbbbbbbb",
                                         "options": ['command="/bin/false"', 'permitlisten="127.0.0.1:1"',
                                                     'permitopen="127.0.0.1:9119"', "port-forwarding", "restrict"]}]}]}},
                "D2.3": {"status": "observed", "data": {"journal": {"pattern_hits": 0, "known_secret_hits": 0},
                                                        "scanned_characters": 23000000, "entries": 185000, "fields": 5000000,
                                                        "undecodable_characters": 0,
                                                        "oldest_entry_read": "2026-09-18T15:11:34Z"}},
                "D2.4": {"status": "observed", "data": {
                    "oldest_entry": {"journal": "2026-09-18T15:11:34Z",
                                     "apps": {"ads-audit": {"broker": "2026-10-05T18:35:47Z", "runner": None},
                                              "ads-report": {"broker": "2026-10-08T09:00:00Z", "runner": None}}},
                    "reach_days": 31,
                    "settings": {"MaxRetentionSec": _setting("35day", OURS, 3024000),
                                 "SystemMaxFiles": _setting("500", OURS, 500),
                                 "SystemMaxUse": _setting("1G", "/etc/systemd/journald.conf", 1 << 30),
                                 "MaxFileSec": _setting("1day", "/etc/systemd/journald.conf", 86400),
                                 "Storage": _setting(None, None, None)},
                    "config_files": ["/etc/systemd/journald.conf", OURS],
                    "drop_in": {"equals_repo": True, "owner": "root", "group": "root", "mode": "0o644", "other_files": []},
                    "service": {"active": True, "started_at": "2026-10-14T16:00:00Z", "config_changed_after_start": False},
                    "usage": {"bytes": 400000000, "files": 110, "bytes_percent_of_max_use": 37.3,
                              "files_percent_of_max_files": 22.0, "free_bytes": 80000000000, "free_percent": 86.5,
                              "other_directories": 0, "newest_entry_on_disk": "2026-10-20T13:59:40Z",
                              "on_disk_age_seconds": 20, "flushed_to_disk": True}}},
                "D4.1": {"status": "observed", "data": {
                    "paths": ["/opt/x readable 12"], "listeners": ["9119", "8642"], "docker_dns_listeners": 1,
                    "secret_env": {"openrouter-key": "matches-file", "dashboard-password": "unset",
                                   "dashboard-password-hash": "matches-file", "dashboard-session-secret": "differs-from-file"},
                    "google_ads_env_names": ["GOOGLE_ADS_X"], "anthropic_env_names": [], "openrouter_env_names": []}},
                "D4.2": {"status": "observed", "data": {"active": "active", "matches_last_pass": True,
                                                        "drop_in_paths": [], "execstart_sha256": "cd" * 32}},
                "D4.5": {"status": "observed", "data": {
                    "timer_active": "active", "timer_enabled": "enabled",
                    "installed_equal_repo": {"hermes-listener-check.service": True, "hermes-listener-check.timer": True},
                    "drop_in_paths": {"hermes-listener-check.timer": []}, "state_dir": {"path": "/var/lib/x", "owner": "root"},
                    "max_age_seconds": 2700, "last": {"status": "ok", "ts": "2026-10-20T13:50:00Z"},
                    "last_age_seconds": 600, "alert_present": False, "alert": None,
                    "history_counts": {"ok": 300, "alert": 1, "?": 2},
                    "alert_log": {"alert": 1, "alert-cleared": 1, "?": 0,
                                  "first_ts": "2026-09-01T10:00:00Z", "last_ts": "2026-09-02T10:00:00Z"}}},
                "D4.6": {"status": "observed", "data": {
                    "last_pass_collected_at": "2026-10-09T14:01:23Z",
                    "apps_declared": list(JOBS), "apps_installed": list(JOBS),
                    "started_at": {"boot": "2026-10-01T00:00:00Z", "hermes-broker": "2026-10-07T06:45:46Z",
                                   "hermes-docker-proxy": "2026-10-07T06:45:40Z", BROKERS[0]: "2026-10-07T06:45:50Z",
                                   BROKERS[1]: "2026-10-08T09:00:00Z"},
                    "started_after_last_pass": {"hermes-broker": False, "hermes-docker-proxy": False, BROKERS[0]: False,
                                                BROKERS[1]: False},
                    "files_newer_than_start": {"hermes-broker": [], "hermes-docker-proxy": [], BROKERS[0]: [], BROKERS[1]: []},
                    "files_checked": {"hermes-broker": 9, "hermes-docker-proxy": 5, BROKERS[0]: 7, BROKERS[1]: 6}}},
                "D7.1": {"status": "observed", "data": {
                    "records": 412, "vaults": [{"client": "acmecorp"}], "root_backups": [],
                    "report_archive": {
                        "parent": {"owner": "root", "group": "root", "mode": "0o700"}, "rows_listed": True,
                        "rows": [{"status": "active", "owner": "root", "mode": "0o700", "kind": "dir",
                                  "files": {"root root 0o600": 2}, "not_files": 0, "listed": True},
                                 {"status": "active", "owner": "root", "mode": "0o700", "kind": "dir",
                                  "files": {}, "not_files": 0, "listed": True}],
                        "containers_mounting": 0, "containers_not_inspected": 0}}},
                "D10.1": {"status": "observed", "data": {"rc": 0, "probe": {
                    "services": {s: {"rc": 0, "env_names": ["GOOGLE_ADS_X"], "sentinel_env_names": [],
                                     "sentinel_in_files": False, "host_credential_files_visible": False}
                                 for s in ("ads-collector", "ads-reader", "ads-drafter", "egress-proxy")},
                    "figures_services": ["ads-collector", "ads-reader"], "matches_declared": True}}},
                "D10.3": {"status": "observed", "data": {
                    "declared_apps": list(JOBS), "installed_apps": list(JOBS), "on_disk_apps": list(JOBS),
                    "units_not_counted": 0, "on_disk_not_counted": 0,
                    "installed_equal_repo": {u: True for u in APP_UNIT_FILES},
                    "apps": {j: {"declared": True, "installed": True,
                                 "broker_unit": {"User": "hermes-app-" + j, "NoNewPrivileges": "yes"},
                                 "runner_unit": {"Environment": ["HOME"], "EnvironmentFiles": []},
                                 "drop_in_paths": {u.replace("@.", "@" + j + "."): [] for u in APP_UNIT_FILES},
                                 "broker_user_groups": ["hermes-app-" + j, "hermes"],
                                 "sudo_rules": {"rc": 0, "not_allowed": False, "command_lines": 1},
                                 "runner_path_active": "active"} for j in JOBS}}},
                "D10.4": {"status": "observed", "data": {
                    "apps": {j: {"declared": True, "installed": True, "layout_problems": [], "layout_reason": None}
                             for j in JOBS},
                    "containers": 3, "containers_mounting_app_state": 0, "containers_not_inspected": 0}},
                "D10.7": {"status": "observed", "data": {"known_secrets_checked": 7, "apps": {j: {
                    "declared": True, "installed": True,
                    "journal_counts": {"refused/disabled": 1, "refused/quota": 1, "refused/bad_request": 2, "ok/-": 3},
                    "note_counts": {"warning": 2}, "other_lines": 4,
                    "broker_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "runner_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "journal_read": {"broker": {"entries": 40, "fields": 900, "undecodable_characters": 0},
                                     "runner": {"entries": 90, "fields": 2000, "undecodable_characters": 0}},
                    "oldest_entry_read": {"broker": "2026-10-05T18:35:47Z", "runner": None},
                    "first_entry": "2026-10-05T18:35:47Z", "installed_since_last_pass": False} for j in JOBS}}},
                "D10.8": {"status": "observed", "data": {"apps": {j: {
                    "declared": True, "installed": True, "out_of_whitelist": 0, "results": [
                        {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
                        {"op": "run", "status": "refused", "reason": "quota", "keys_ok": True, "values_ok": True}]}
                    for j in JOBS}}},
                "D5.3": {"status": "could-not-check", "reason": "OSError: /var/lib/hermes/x: denied"},
                "D99.9": {"status": "observed", "data": {"anything": PLANT}}}}


def bundle():
    """A healthy box with both jobs declared, installed and on disk (the only fault: D5.3)."""
    return _base()


def old_bundle():
    """The shape of the previous review's bundle: one job, no `apps` level, no report store, no job lists."""
    b = _base()
    it = b["items"]
    for gone in ("D10.1", "D10.3", "D10.4"):
        del it[gone]
    del it["D7.1"]["data"]["report_archive"]
    it["D2.4"]["data"]["oldest_entry"] = {"journal": "2026-09-18T15:11:34Z", "broker": "2026-10-05T18:35:47Z", "runner": None}
    d46 = it["D4.6"]["data"]
    del d46["apps_declared"], d46["apps_installed"]
    for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
        del d46[group][BROKERS[1]]
    job = it["D10.7"]["data"]["apps"]["ads-audit"]
    for gone in ("declared", "installed", "first_entry", "installed_since_last_pass"):
        del job[gone]
    it["D10.7"]["data"] = {**job, "known_secrets_checked": 7}
    it["D10.8"]["data"] = {k: it["D10.8"]["data"]["apps"]["ads-audit"][k] for k in ("out_of_whitelist", "results")}
    return b


def clean():
    """bundle() without its one fault, so that every closing line starts from ok."""
    b = bundle()
    del b["items"]["D5.3"]
    return b


def job(items, iid, app="ads-audit"):
    return items[iid]["data"]["apps"][app]


def not_installed(b, app="ads-report"):
    """`app` as the collector reports a job that is declared and not installed yet (between a pull and
    the job's installation): no account, no results directory, a broker that never started."""
    it = b["items"]
    it["D10.3"]["data"]["installed_apps"].remove(app)
    it["D10.3"]["data"]["on_disk_apps"].remove(app)
    it["D4.6"]["data"]["apps_installed"].remove(app)
    for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
        job(it, iid, app)["installed"] = False
    job(it, "D10.3", app).update(broker_user_groups="could-not-check", runner_path_active="inactive")
    job(it, "D10.4", app).update(layout_problems="could-not-check", layout_reason="no-account")
    job(it, "D10.8", app).update(results="could-not-check", out_of_whitelist="could-not-check")
    job(it, "D10.7", app).update(journal_counts={}, note_counts={}, other_lines=0, first_entry=None,
                                 installed_since_last_pass=True, oldest_entry_read={"broker": None, "runner": None})
    broker = "hermes-app-broker@" + app
    for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
        it["D4.6"]["data"][group][broker] = "could-not-check"
    return b


def planted(value, plant=PLANT, keys=True, _n=[0]):
    """The same structure with every string VALUE and (keys=True) every dict KEY replaced by the plant
    (a key gets a counter after it, so two keys stay two keys)."""
    if isinstance(value, str):
        return plant
    if isinstance(value, list):
        return [planted(v, plant, keys) for v in value] or [plant]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            _n[0] += 1
            out[f"{plant}{_n[0]}" if keys else k] = planted(v, plant, keys)
        return out
    return value


def planted_bundle(plant, keys=True, status=None):
    """Everything the bundle holds from the box is planted; the structure the tool reads by (the
    top-level keys, each item's `status` and `data`) stays; the status is planted too, unless `status` is
    given (then the data is read, and everything in it is planted)."""
    b = bundle()
    b["items"] = {iid: {"status": status or plant, "data": planted(item.get("data"), plant, keys)} if "data" in item
                  else {"status": plant, "reason": plant} for iid, item in b["items"].items()}
    b["credentials"], b["fingerprint"], b["collected_at"] = planted(b["credentials"], plant), planted(b["fingerprint"], plant, keys), plant
    return b


def run(text):
    out = io.StringIO()
    rc = SB.main([], stdin=io.StringIO(text), out=out)
    return rc, out.getvalue()


def closing_of(b):
    text = run(json.dumps(b))[1]
    return text[text.index("Before the real collection"):]


class TestPrintRule(unittest.TestCase):
    def test_integers_are_printed_up_to_fifteen_digits_and_booleans_are_not_numbers(self):
        self.assertEqual(SB.num(0), "0")
        self.assertEqual(SB.num(-5), "-5")
        self.assertEqual(SB.num(10 ** 15 - 1), str(10 ** 15 - 1))
        self.assertEqual(SB.num(10 ** 15), SB.WITHHELD)
        self.assertEqual(SB.num(10 ** 400), SB.WITHHELD)
        self.assertEqual(SB.num(True), SB.WITHHELD)
        self.assertEqual(SB.num("12"), SB.WITHHELD)

    def test_floats_are_rounded_to_one_decimal_and_a_float_that_is_not_finite_is_withheld(self):
        self.assertEqual(SB.num(37.34), "37.3")
        self.assertEqual(SB.num(22.0), "22.0")
        for bad in (float("nan"), float("inf"), float("-inf"), 1e300):
            self.assertEqual(SB.num(bad), SB.WITHHELD)

    def test_null_and_could_not_check_are_printed_for_every_kind(self):
        for fmt in (SB.num, SB.flag, SB.when, SB.count, SB.member({"a"}), SB.mode, SB.is_root):
            self.assertEqual(fmt(None), "null")
            self.assertEqual(fmt("could-not-check"), "could-not-check")

    def test_booleans(self):
        self.assertEqual((SB.flag(True), SB.flag(False)), ("true", "false"))
        self.assertEqual(SB.flag(1), SB.WITHHELD)
        self.assertEqual(SB.flag("true"), SB.WITHHELD)

    def test_a_time_must_be_a_real_date(self):
        self.assertEqual(SB.when("2026-10-20T14:00:00Z"), "2026-10-20T14:00:00Z")
        for bad in ("9999-99-99T99:99:99Z", "2026-02-30T00:00:00Z", "2026-10-20 14:00:00", "2026-1-2T1:2:3Z",
                    "2026-10-20T14:00:00Z\n", 1760000000, True):
            self.assertEqual(SB.when(bad), SB.WITHHELD, bad)

    def test_a_string_prints_only_as_a_member_of_its_set(self):
        fmt = SB.member({"alpha", "beta"})
        self.assertEqual(fmt("alpha"), "alpha")
        self.assertEqual(fmt("alphx"), SB.OTHER)
        self.assertEqual(fmt("Alpha"), SB.OTHER)
        self.assertEqual(fmt("acmecorp"), SB.OTHER)
        self.assertEqual(fmt(["alpha"]), SB.WITHHELD)
        self.assertEqual(fmt(5), SB.WITHHELD)

    def test_a_dict_prints_its_declared_keys_and_counts_the_others(self):
        fmt = SB.fixed({"a": SB.num, "b": SB.flag, "skipped": None})
        self.assertEqual(fmt({"a": 1, "b": True, "skipped": "acmecorp"}), "{a: 1, b: true}")
        self.assertEqual(fmt({"a": 1, "acmecorp": 2, "10.0.0.5": 3}), "{a: 1, +2 other keys}")
        self.assertEqual(fmt([1]), SB.WITHHELD)
        keyed = SB.keyed({"x", "y"}, SB.num)
        self.assertEqual(keyed({"y": 2, "x": 1, "acmecorp": 3}), "{x: 1, y: 2, +1 other keys}")

    def test_counts(self):
        self.assertEqual(SB.count(["a", "b"]), "2")
        self.assertEqual(SB.count({"acmecorp": 1}), "1")
        self.assertEqual(SB.count("acmecorp"), SB.WITHHELD)

    def test_modes_and_roots(self):
        self.assertEqual(SB.mode("0o600"), "0o600")
        self.assertEqual(SB.mode("0o4755"), "0o4755")
        for bad in ("0o60", "600", "0o680", "0o60000", "acmecorp"):
            self.assertEqual(SB.mode(bad), SB.OTHER)
        self.assertEqual((SB.is_root("root"), SB.is_root("acme-ops")), ("true", "false"))
        self.assertEqual(SB.is_root(0), SB.WITHHELD)

    def test_the_walk_for_could_not_check_is_bounded_and_counts_keys_and_values(self):
        cnc = "could-not-check"
        self.assertEqual(SB.cnc_places({"a": [cnc, {cnc: 1}], "b": cnc}), 3)
        self.assertEqual(SB.cnc_places({"a": "x"}), 0)
        deep = leaf = []
        for _ in range(5000):
            leaf = [leaf]
        self.assertEqual(SB.cnc_places(leaf), 1)                 # too deep to read: one place, no exception

    def test_ids_that_sort_the_same_way_never_raise(self):
        b = bundle()
        b["items"] = {"D1.7": {"status": "observed"}, "1.7": {"status": "observed"}, "D01.7": {"status": "observed"},
                      "D2.10": {"status": "observed"}, "D2.9": {"status": "observed"}, "": {"status": "observed"}}
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertLess(text.index("D2.9"), text.index("D2.10"))
        self.assertIn("other items: 2", text)


class TestSetsMatchTheCollector(unittest.TestCase):
    """Every vocabulary the collector declares is copied into the tool; these tests fail when they drift."""
    def test_journal_labels(self):
        self.assertEqual(SB.JOURNAL_STATUSES, frozenset(CE.JOURNAL_STATUSES) | {"-", "?"})
        self.assertEqual(SB.JOURNAL_REASONS, frozenset(CE.JOURNAL_REASONS) | {"?"})

    def test_journal_note_words(self):
        self.assertEqual(SB.NOTE_WORDS, frozenset({"warning", "error"}))
        for w in SB.NOTE_WORDS:
            self.assertEqual(CE._NOTE_RE.match(w + ": ").group(1), w)
        self.assertIsNone(CE._NOTE_RE.match("notice: "))

    def test_journald_setting_names_and_our_file(self):
        self.assertEqual(SB.SETTING_NAMES, frozenset(CE.JOURNALD_SETTINGS))
        self.assertEqual(SB.OUR_FILE, CE.JOURNALD_DROP_IN)

    def test_services_and_unit_labels(self):
        self.assertEqual(SB.SERVICES, tuple(CE.SERVICE_FILES))                       # the two fixed services
        self.assertEqual(SB.START_KEYS, frozenset(CE.SERVICE_FILES) | frozenset(CE.OTHER_STARTS))
        for app in JOBS:                                                             # a job's broker is built from its name
            self.assertEqual(SB.BROKER_PREFIX + app, CE._app_broker_unit(app))
            self.assertEqual(SB.UNIT_LABELS, tuple(CE._journal_units(app)))
            self.assertEqual(CE._journal_units(app)["broker"], SB.BROKER_PREFIX + app)
        self.assertEqual(SB.LISTENER_UNITS, frozenset(CE.LISTENER_UNITS))
        self.assertEqual(SB.APP_UNITS, frozenset(CE.APP_UNITS))
        self.assertEqual(SB.APP_UNITS, frozenset(APP_UNIT_FILES))
        self.assertEqual(SB.LAYOUT_REASONS, frozenset(CE.LAYOUT_REASONS))
        self.assertEqual(tuple(SB._READ_KEYS), tuple(CE.READ_COUNTS))

    def test_a_job_name_is_what_the_collector_calls_one(self):
        self.assertEqual("^" + SB._APP_RE.pattern + "$", CE.A.APP_RE.pattern)
        for name in JOBS + ("a", "a" * 32, "x9-y"):
            self.assertTrue(SB._APP_RE.fullmatch(name) and CE.A.APP_RE.fullmatch(name), name)
        for name in ("", "a" * 33, "Ads", "9a", "-a", "a_b", "a.b", "a b", "ads-audit\n", "a/b", "a@b"):
            self.assertIsNone(SB._APP_RE.fullmatch(name), name)

    def test_the_report_store_words_are_the_collector_s(self):
        # The collector declares no set for these: it is asked, with a real directory, what it writes.
        import tempfile, types
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "store"))
            os.mkdir(os.path.join(root, "store", "acme-dental"))
            open(os.path.join(root, "file"), "w").close()
            os.symlink(os.path.join(root, "store"), os.path.join(root, "link"))
            host = types.SimpleNamespace(path=lambda p: os.path.join(root, p))
            self.assertEqual({CE._dir_row(host, n) for n in ("missing", "link", "file")},
                             {SB.DIR_ABSENT, SB.DIR_LINK, SB.DIR_NOT_A_DIRECTORY})
            self.assertEqual((CE._dir_row(host, "missing"), CE._dir_row(host, "link"), CE._dir_row(host, "file")),
                             (SB.DIR_ABSENT, SB.DIR_LINK, SB.DIR_NOT_A_DIRECTORY))
            self.assertEqual(set(CE._dir_row(host, "store")), {"owner", "group", "mode"})
            row = CE._archive_row({"acme-dental": {"status": "active"}}, os.path.join(root, "store"), "acme-dental")
            self.assertEqual((row["kind"], row["status"], row["listed"], row["not_files"]), (SB.ROW_DIR, SB.ROW_ACTIVE, True, 0))
        self.assertEqual(SB.DIR_WORDS, frozenset({SB.DIR_ABSENT, SB.DIR_LINK, SB.DIR_NOT_A_DIRECTORY}))

    def test_the_probe_s_services_are_run_client_audit_s(self):
        # The collector passes the probe through and names no service: run-client-audit's DECLARED does.
        rspec = importlib.util.spec_from_file_location("rca_for_summary", os.path.join(HERE, "run-client-audit.py"))
        RCA = importlib.util.module_from_spec(rspec); rspec.loader.exec_module(RCA)
        self.assertEqual(SB.PROBE_SERVICES, frozenset(RCA.DECLARED))
        # a figures run starts the services that hold the Google Ads credential and nothing else
        self.assertEqual(SB.FIGURES_SERVICES, tuple(sorted(s for s, names in RCA.DECLARED.items() if names == ["GOOGLE_ADS_"])))
        self.assertEqual(SB.FIGURES_SERVICES, ("ads-collector", "ads-reader"))

    def test_secret_env_labels_and_states(self):
        self.assertEqual(SB.SECRET_LABELS, frozenset(l for _, l in CE.OTHER_SECRET_NAMES[CE.GATEWAY_ENV_FILE]))
        self.assertEqual(SB.SECRET_STATES, frozenset({CE.MATCHES_FILE, CE.DIFFERS_FROM_FILE, CE.UNSET}))

    def test_the_sshd_setting_names_are_only_counted(self):
        self.assertEqual(len(CE.SSHD_KEY_SOURCES), 8)
        b = bundle()
        b["items"]["D1.7"]["data"]["sshd"] = {name: "acmecorp" for name in CE.SSHD_KEY_SOURCES}
        text = run(json.dumps(b))[1]
        self.assertIn("sshd_settings: 8", text)
        for gone in (*CE.SSHD_KEY_SOURCES, "acmecorp"):
            self.assertNotIn(gone, text)

    def test_key_types_are_exactly_what_the_collector_accepts(self):
        for t in SB.KEY_TYPES:
            self.assertTrue(CE._KEY_TYPE_RE.fullmatch(t), t)
        base = {"ssh-rsa", "ssh-dss", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com"}
        self.assertEqual(SB.KEY_TYPES, base | {t + "-cert-v01@openssh.com" for t in base})
        self.assertEqual(len(SB.KEY_TYPES), 16)

    def test_the_listener_check_words(self):
        import gateway_listeners  # noqa: F401  (the collector imports it by name)
        lspec = importlib.util.spec_from_file_location("check_gateway_listeners", os.path.join(HERE, "check-gateway-listeners.py"))
        L = importlib.util.module_from_spec(lspec); lspec.loader.exec_module(L)
        self.assertEqual(SB.HISTORY_STATUSES, frozenset({L.OK, L.ALERT, L.COULD_NOT_CHECK, "?"}))
        self.assertEqual(SB.ALERT_LOG_KEYS, frozenset({L.ALERT, L.CLEARED, "?", "first_ts", "last_ts"}))

    def test_the_file_kinds(self):
        self.assertEqual(SB.FILE_KINDS, frozenset({"file", "symlink", "not-a-file"}))

    def test_the_sets_the_collector_does_not_declare_are_pinned(self):
        # systemctl is-active / is-enabled print systemd's own words (systemctl(1)): no collector constant.
        self.assertEqual(SB.ACTIVE_STATES, frozenset({"active", "inactive", "failed", "activating", "deactivating",
                                                      "reloading", "maintenance", "refreshing"}))
        self.assertEqual(SB.ENABLED_STATES, frozenset({"not-found", "enabled", "enabled-runtime", "linked", "linked-runtime", "masked",
                                                       "masked-runtime", "static", "indirect", "disabled", "generated",
                                                       "transient", "alias", "bad"}))
        self.assertEqual(SB.SETTING_VALUES, frozenset({"35day", "7day", "1day", "1G", "500", "persistent", "auto",
                                                       "volatile", "none"}))
        self.assertEqual(SB.STORAGE_OK, (None, "auto", "persistent"))


class TestSummary(unittest.TestCase):
    def test_every_item_is_listed_with_its_status_known_to_the_tool_or_not(self):
        rc, text = run(json.dumps(bundle()))
        self.assertEqual(rc, 0)
        for iid in bundle()["items"]:
            self.assertRegex(text, rf"(?m)^{re.escape(iid)} +(observed|could-not-check)\b")
        self.assertRegex(text, r"(?m)^items 16 \| not observed: D5\.3$")
        self.assertRegex(text, r"(?m)^other items: 0$")
        self.assertNotIn("anything", text)                       # an unknown item: its status alone
        self.assertNotIn("denied", text)                         # a reason is free text

    def test_counts_booleans_words_and_times_are_printed(self):
        text = run(json.dumps(bundle()))[1]
        for want in ("match_lines: 0", "reach_days: 31", "scanned_characters: 23000000",
                     "oldest_entry_read: 2026-09-18T15:11:34Z",
                     "MaxRetentionSec: {number: 3024000, set_by: ours, value: 35day}",
                     "SystemMaxUse: {number: 1073741824, set_by: other, value: 1G}",
                     "Storage: {number: null, set_by: none, value: null}",
                     "refused/bad_request: 2", "matches_last_pass: true", "run/ok results: 1",
                     "keys: 2 (ssh-ed25519 options=0, ssh-ed25519 options=5 limited_to_the_forward=true)",
                     "daemon_options: {listeners: 1, config_file_options: 0, setting_options: 0}",
                     "undecodable_characters: 0", "flushed_to_disk: true", "active: true",
                     "users: 2", "owner_is_root: false", "kind: file", "mode: 0o600", "sshd_settings: 2",
                     "drop_in: {equals_repo: true, owner_is_root: true, group_is_root: true, mode: 0o644, other_files: 0}",
                     "secret_env: {dashboard-password: unset, dashboard-password-hash: matches-file, "
                     "dashboard-session-secret: differs-from-file, openrouter-key: matches-file}",
                     "listeners: 2", "docker_dns_listeners: 1", "active: active", "timer_enabled: enabled",
                     "history_counts: {?: 2, alert: 1, ok: 300}", "first_ts: 2026-09-01T10:00:00Z",
                     "files_checked: {hermes-app-broker@ads-audit: 7, hermes-app-broker@ads-report: 6, hermes-broker: 9, "
                     "hermes-docker-proxy: 5}",
                     "records: 412", "note_counts: {warning: 2}"):
            self.assertIn(want, text)

    def test_no_account_name_path_fingerprint_or_option_value_is_printed(self):
        text = run(json.dumps(bundle()))[1]
        for gone in ("/etc/", "/home/", "/bin/false", "0123456789ab", "aaaaaaaaaaaa", "abab", "cdcd", "127.0.0.1",
                     "0.0.0.0", "authorized_keys", "acmecorp", "GOOGLE_ADS", *ACCOUNTS):
            self.assertNotIn(gone, text, gone)

    def test_unknown_keys_are_counted_never_named(self):
        b = bundle()
        b["items"]["D2.3"]["data"]["acmecorp"] = 1
        b["items"]["D2.3"]["data"]["journal"]["10.0.0.5"] = 2
        b["items"]["D2.3"]["data"]["journal"]["ops@acme.com"] = 3
        job(b["items"], "D10.7")["journal_counts"]["ok/acmecorp"] = 3
        b["items"]["D4.5"]["data"]["history_counts"]["client-acme.json"] = 1
        text = run(json.dumps(b))[1]
        self.assertIn("journal: {pattern_hits: 0, known_secret_hits: 0, +2 other keys}", text)
        self.assertIn("history_counts: {?: 2, alert: 1, ok: 300, +1 other keys}", text)
        self.assertIn("ok/-: 3, refused/bad_request: 2, refused/disabled: 1, refused/quota: 1, +1 other keys}", text)
        self.assertRegex(text, r"(?m)^D2\.3 .*\n(.*\n)*  \+1 other keys$")
        for gone in ("acmecorp", "10.0.0.5", "ops@acme.com", "client-acme.json"):
            self.assertNotIn(gone, text)

    def test_what_prints_for_a_dict_is_built_from_the_pinned_sets(self):
        b = bundle()
        b["items"]["D4.5"]["data"]["alert_log"]["zz"] = 1
        b["items"]["D2.4"]["data"]["oldest_entry"]["zz"] = "2026-10-01T00:00:00Z"
        job(b["items"], "D10.7")["oldest_entry_read"]["zz"] = "2026-10-01T00:00:00Z"
        text = run(json.dumps(b))[1]
        self.assertNotIn("zz", text)
        self.assertEqual(text.count("+1 other keys"), 3)

    def test_a_status_outside_the_two_words_is_other(self):
        b = bundle()
        b["items"]["D5.3"]["status"] = "acmecorp"
        text = run(json.dumps(b))[1]
        self.assertRegex(text, r"(?m)^D5\.3 +<other>$")
        self.assertNotIn("acmecorp", text)

    def test_nothing_from_the_box_is_printed_whatever_it_looks_like(self):
        for plant in PLANTS:
            for keys in (False, True):
                for status in (None, "observed"):
                    rc, text = run(json.dumps(planted_bundle(plant, keys, status)))
                    self.assertEqual(rc, 0)
                    self.assertNotIn(plant, text, (plant, keys, status))
                    for part in ("0123456789abcdef", "sk-or", "acme", "example", "10.0.0", "passwd"):
                        self.assertNotIn(part, text, (plant, part))
                    if status and not keys:
                        self.assertIn("reach_days", text)           # the data was read: the plant is not hidden by the status
            # the plant as a job's name, in every place the bundle keys a job's values by it: it is not one of
            # the declared jobs, so it is never printed, whether or not it has the form of a job's name
            for status in (None, "observed"):
                b = planted_bundle(plant, False, status)
                it = b["items"]
                it["D10.3"]["data"]["declared_apps"] = list(JOBS)
                for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
                    it[iid]["data"]["apps"][plant] = it[iid]["data"]["apps"].pop("ads-report")
                oldest = it["D2.4"]["data"]["oldest_entry"]["apps"]
                oldest[plant] = oldest.pop("ads-report")
                for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
                    it["D4.6"]["data"][group]["hermes-app-broker@" + plant] = it["D4.6"]["data"][group].pop(BROKERS[1])
                rc, text = run(json.dumps(b))
                self.assertEqual(rc, 0)
                self.assertNotIn(plant, text, (plant, status))
                for part in ("0123456789abcdef", "sk-or", "acme", "example", "10.0.0", "passwd", "deadbee"):
                    self.assertNotIn(part, text, (plant, part))
                if status:
                    self.assertEqual(len(re.findall(r"(?m)^    <withheld>:$", text)), 4, plant)
                    self.assertIn("hermes-app-broker@<withheld>: ", text)

    def test_an_item_id_that_is_a_plant_is_counted_not_named(self):
        for plant in PLANTS:
            b = bundle()
            b["items"] = {plant: {"status": "observed"}, "D1.7": {"status": "observed"}}
            text = run(json.dumps(b))[1]
            self.assertNotIn(plant, text)
            self.assertIn("other items: 1", text)
            self.assertIn("items 2 | not observed: none", text)

    def test_the_closing_list_says_what_to_look_at_before_the_real_collection(self):
        closing = closing_of(bundle())
        self.assertIn("LOOK  every item observed (16 items) (not observed: D5.3)", closing)
        for ok in ("nothing in the bundle is could-not-check", "the three live refusals are in the journal",
                   "at least one run/ok result", "retention at least 30 days, set by our file",
                   "the journal reaches 30 days", "the running journal service has read its settings",
                   "the proxy matches the last PASS", "no service runs older code", "fingerprint complete",
                   "the journal is being written to disk", "sshd runs with its default settings file and no Match line",
                   "the journal search read everything it was given", r"no leak count above 0 \(D2\.3, D10\.7\)",
                   "no other journal directory and no missing days", "every job is declared and installed",
                   "the report store holds only owner-only client folders",
                   "every job's folders are as designed and no container mounts the job state",
                   "the installed job units equal the repository's and every stored result is in whitelist",
                   "the credential probe matches the declared map and a figures run starts no AI service"):
            self.assertRegex(closing, rf"(?m)^(ok    |LOOK  ){ok}")
        for ok in ("the three live refusals are in the journal", "at least one run/ok result",
                   "retention at least 30 days, set by our file", "the journal reaches 30 days",
                   "the running journal service has read its settings", "the proxy matches the last PASS",
                   "no service runs older code", "fingerprint complete",
                   "the journal is being written to disk", "sshd runs with its default settings file and no Match line",
                   "the journal search read everything it was given", r"no leak count above 0 \(D2\.3, D10\.7\)$",
                   "no other journal directory and no missing days$", r"every job is declared and installed \(2 jobs\)$",
                   r"the report store holds only owner-only client folders \(2 folders\)$",
                   "every job's folders are as designed and no container mounts the job state$",
                   "the installed job units equal the repository's and every stored result is in whitelist$",
                   "the credential probe matches the declared map and a figures run starts no AI service$"):
            self.assertRegex(closing, rf"(?m)^ok    {ok}")
        self.assertIn("ok    retention at least 30 days, set by our file, the file equal to the repository's, "
                      "no other file, root:root 0644\n", closing)
        self.assertIn("Reminders, not verdicts", closing)
        self.assertEqual(len(re.findall(r"(?m)^(?:ok   |LOOK) ", closing)), 20)

    def test_a_clean_bundle_is_ok_on_all_twenty(self):
        closing = closing_of(clean())
        self.assertEqual(len(re.findall(r"(?m)^ok    ", closing)), 20)
        self.assertEqual(len(SB.CHECKS), 20)
        self.assertIn("ok    every item observed (15 items)", closing)

    def test_the_closing_list_has_the_twenty_lines_in_order(self):
        closing = closing_of(bundle())
        order = ("every item observed", "nothing in the bundle", "every job is declared and installed",
                 "every job's folders are as designed", "the installed job units equal", "the credential probe matches",
                 "sshd runs with", "the three live refusals",
                 "at least one run/ok", "retention at least 30 days", "the journal reaches 30 days",
                 "the journal search read", "no leak count above 0", "the running journal service",
                 "the journal is being written", "no other journal directory and no missing days", "the proxy matches", "no service runs older code",
                 "the report store holds only", "fingerprint complete")
        positions = [closing.index(o) for o in order]
        self.assertEqual(positions, sorted(positions))

    def test_each_closing_line_turns_to_look(self):
        def closing(change):
            b = bundle()
            del b["items"]["D5.3"]                      # so that every case starts from twenty ok
            change(b["items"])
            return closing_of(b)
        cases = (
            (lambda it: job(it, "D10.7")["journal_counts"].pop("refused/quota"), "the three live refusals"),
            (lambda it: job(it, "D10.8")["results"].pop(0), "at least one run/ok result"),
            (lambda it: it["D2.4"]["data"]["settings"]["MaxRetentionSec"].update(file="/etc/systemd/journald.conf"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["drop_in"].update(other_files=["99-x.conf"]), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"].update(reach_days=12), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"]["service"].update(config_changed_after_start=True), "the running journal service"),
            (lambda it: it["D4.2"]["data"].update(matches_last_pass=False), "the proxy matches the last PASS"),
            (lambda it: it["D4.6"]["data"]["files_newer_than_start"].update({"hermes-broker": ["app_lib.py"]}), "no service runs older code"),
            (lambda it: it.pop("D2.4"), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"].update(Storage={"value": "volatile", "file": None, "number": None}), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"].pop("Storage"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"]["Storage"].pop("value"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"]["Storage"].update(value=7), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["service"].update(active=False), "the running journal service"),
            (lambda it: it["D2.4"]["data"]["service"].update(active="could-not-check"), "the running journal service"),
            (lambda it: it["D2.4"]["data"]["service"].pop("active"), "the running journal service"),
            (lambda it: it["D2.4"]["data"]["usage"].update(flushed_to_disk=False), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].update(flushed_to_disk="could-not-check"), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].update(on_disk_age_seconds=601), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].update(on_disk_age_seconds="could-not-check"), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].update(on_disk_age_seconds=True), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].update(on_disk_age_seconds=-1), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"]["usage"].pop("flushed_to_disk"), "the journal is being written to disk"),
            (lambda it: it["D2.4"]["data"].update(usage={}), "the journal is being written to disk"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(config_file_options=1), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(setting_options=1), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(listeners=2), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(listeners=True), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(config_file_options=False), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(listeners="could-not-check"), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"]["daemon_options"].update(extra=0), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(daemon_options="x"), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(daemon_options={}), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].pop("daemon_options"), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(match_lines=1), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(match_lines=False), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(match_lines="could-not-check"), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(include_elsewhere=1), "sshd runs with its default"),
            (lambda it: it["D1.7"]["data"].update(include_elsewhere=0.5), "sshd runs with its default"),
            (lambda it: it["D1.7"].update(status="could-not-check"), "sshd runs with its default"),
            (lambda it: it.pop("D1.7"), "sshd runs with its default"),
            (lambda it: it["D2.3"]["data"].update(undecodable_characters=3), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(undecodable_characters=False), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].pop("undecodable_characters"), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(scanned_characters=0), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(scanned_characters=True), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(scanned_characters="could-not-check"), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(oldest_entry_read=None), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(oldest_entry_read="could-not-check"), "the journal search read everything"),
            (lambda it: it["D2.3"]["data"].update(oldest_entry_read=1760000000), "the journal search read everything"),
            (lambda it: it["D2.3"].update(status="could-not-check"), "the journal search read everything"),
            (lambda it: it.pop("D2.3"), "the journal search read everything"),
            # the brief's lines, against a bool where a number is expected or a wrong type
            (lambda it: job(it, "D10.7")["journal_counts"].update({"refused/quota": True}), "the three live refusals"),
            (lambda it: job(it, "D10.7").update(journal_counts="x"), "the three live refusals"),
            (lambda it: it["D10.7"].update(status="could-not-check"), "the three live refusals"),
            (lambda it: it.pop("D10.7"), "the three live refusals"),
            (lambda it: it.pop("D10.8"), "at least one run/ok result"),
            (lambda it: job(it, "D10.8").update(results={}), "at least one run/ok result"),
            (lambda it: it["D2.4"]["data"]["settings"]["MaxRetentionSec"].update(number=True), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"]["MaxRetentionSec"].update(number="could-not-check"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["settings"].update(MaxRetentionSec={}), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"].update(settings="could-not-check"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["drop_in"].update(equals_repo="could-not-check"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"]["drop_in"].update(other_files="could-not-check"), "retention at least 30 days"),
            (lambda it: it["D2.4"]["data"].update(reach_days=True), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"].update(reach_days=None), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"].update(reach_days="could-not-check"), "the journal reaches 30 days"),
            (lambda it: it["D2.4"]["data"]["service"].update(config_changed_after_start="could-not-check"), "the running journal service"),
            (lambda it: it["D2.4"].update(status="could-not-check"), "the running journal service"),
            (lambda it: it.pop("D4.2"), "the proxy matches the last PASS"),
            (lambda it: it["D4.2"]["data"].update(matches_last_pass="could-not-check"), "the proxy matches the last PASS"),
            (lambda it: it["D4.2"]["data"].update(matches_last_pass=None), "the proxy matches the last PASS"),
            (lambda it: it["D4.6"]["data"].update(files_newer_than_start={}), "no service runs older code"),
            (lambda it: it["D4.6"]["data"].update(files_newer_than_start="could-not-check"), "no service runs older code"),
            (lambda it: it["D4.6"]["data"]["files_newer_than_start"].update({"hermes-broker": "could-not-check"}), "no service runs older code"),
            (lambda it: it.pop("D4.6"), "no service runs older code"),
        )
        for change, line in cases:
            self.assertRegex(closing(change), rf"(?m)^LOOK  {line}", line)
        self.assertIn("reach is 12 days: the evidence needs the date the retention was raised",
                      closing(lambda it: it["D2.4"]["data"].update(reach_days=12)))

    def test_lines_that_read_other_parts_of_the_bundle_turn_to_look(self):
        def closing(change):
            b = bundle()
            del b["items"]["D5.3"]                      # so that every case starts from twenty ok
            change(b)
            return closing_of(b)
        cases = (
            (lambda b: b["fingerprint"].update(complete=False), "fingerprint complete"),
            (lambda b: b["fingerprint"].update(complete="true"), "fingerprint complete"),
            (lambda b: b["fingerprint"].update(complete=1), "fingerprint complete"),
            (lambda b: b.update(fingerprint=None), "fingerprint complete"),
            (lambda b: b.pop("fingerprint"), "fingerprint complete"),
            (lambda b: job(b["items"], "D10.8").update(results=[{"op": "?", "status": "ok", "keys_ok": True, "values_ok": True}]), "at least one run/ok result"),
            (lambda b: job(b["items"], "D10.8").update(results=[{"op": "run", "status": "ok", "keys_ok": False, "values_ok": True}]), "at least one run/ok result"),
            (lambda b: job(b["items"], "D10.8").update(results=[{"op": "run", "status": "ok", "keys_ok": True, "values_ok": False}]), "at least one run/ok result"),
            (lambda b: job(b["items"], "D10.8").update(results=[{"op": "run", "status": "ok"}]), "at least one run/ok result"),
            (lambda b: b["items"]["D4.6"]["data"]["files_newer_than_start"].pop("hermes-broker"), "no service runs older code"),
            (lambda b: b["items"]["D4.6"]["data"]["files_checked"].pop("hermes-app-broker@ads-audit"), "no service runs older code"),
            (lambda b: b["items"]["D4.6"]["data"]["files_checked"].update({"hermes-broker": 0}), "no service runs older code"),
            (lambda b: b["items"]["D4.6"]["data"]["files_checked"].update({"hermes-broker": True}), "no service runs older code"),
            (lambda b: b["items"]["D4.6"]["data"]["files_checked"].update({"hermes-broker": "could-not-check"}), "no service runs older code"),
            (lambda b: b["items"]["D4.2"]["data"].update(active="failed"), "the proxy matches the last PASS"),
            (lambda b: b["items"]["D4.2"]["data"].pop("active"), "the proxy matches the last PASS"),
            (lambda b: b.update(credentials={"could-not-check": "x"}), "nothing in the bundle is could-not-check"),
            (lambda b: b.update(credentials="x"), "nothing in the bundle is could-not-check"),
            (lambda b: b.pop("credentials"), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D1.7"]["data"]["files"][0].update(keys="could-not-check"), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D1.7"]["data"].update(unprivileged_port_start="could-not-check"), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D4.1"]["data"]["secret_env"].update({"openrouter-key": "could-not-check"}), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D2.4"]["data"]["usage"].update(bytes="could-not-check"), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D1.1"]["data"].update({"could-not-check": 1}), "nothing in the bundle is could-not-check"),
            (lambda b: b["items"]["D2.3"]["data"].update(oldest_entry_read="9999-99-99T99:99:99Z"), "the journal search read everything"),
            (lambda b: b["items"]["D2.3"]["data"].update(oldest_entry_read="2026-02-30T00:00:00Z"), "the journal search read everything"),
        )
        for change, line in cases:
            self.assertRegex(closing(change), rf"(?m)^LOOK  {line}", line)

    LEAK_LINE = r"no leak count above 0 \(D2\.3, D10\.7\)"
    DIRS_LINE = "no other journal directory and no missing days"
    ABOVE = " (a count is above 0: this is a FAIL, not a reminder)"

    @staticmethod
    def _closing(change):
        b = bundle()
        del b["items"]["D5.3"]                          # so that every case starts from twenty ok
        change(b["items"])
        return closing_of(b)

    JOB_NOTE = r" \(not so for 1 of 2 jobs(: a value could not be checked)?\)"

    def _leak_places(self):
        """(where the group of counts is, the count's key, what the line adds when the place is a job's)."""
        return ([(lambda it: it["D2.3"]["data"], "journal", k, "") for k in ("pattern_hits", "known_secret_hits")]
                + [(lambda it, app=app: job(it, "D10.7", app), j, k, self.JOB_NOTE) for app in JOBS
                   for j in ("broker_journal", "runner_journal")
                   for k in ("credential_text_lines", "customer_id_lines", "pattern_hits", "known_secret_hits")])

    def test_the_leak_keys_are_the_collectors(self):
        self.assertEqual(set(SB.SEARCH_KEYS), set(CE.SEARCH_HIT_COUNTS))
        self.assertEqual(set(SB.LEAK_KEYS), set(CE.LEAK_COUNTS))
        self.assertEqual(len(self._leak_places()), len(SB.SEARCH_KEYS) + len(JOBS) * 2 * len(SB.LEAK_KEYS))

    def test_the_all_fields_counts_are_printed(self):
        text = run(json.dumps(bundle()))[1]
        for want in ("entries: 185000", "fields: 5000000",
                     "journal_read: {broker: {entries: 40, fields: 900, undecodable_characters: 0}, "
                     "runner: {entries: 90, fields: 2000, undecodable_characters: 0}}"):
            self.assertIn(want, text)

    def test_every_leak_count_above_zero_turns_the_leak_line_to_look_in_fixed_words(self):
        for where, group, key, jobs in self._leak_places():
            for n in (1, 7, 10 ** 400):
                text = self._closing(lambda it: where(it)[group].update({key: n}))
                self.assertRegex(text, rf"(?m)^LOOK  {self.LEAK_LINE} \(a count is above 0: this is a FAIL, not a reminder\){jobs}$", (group, key))
                self.assertEqual(len(re.findall(r"(?m)^ok    ", text)), 19, (group, key))
                self.assertNotRegex(text[text.index("no leak count"):], r"[0-9]{16}")

    def test_a_leak_count_that_was_not_read_is_look_without_the_fail_words(self):
        for where, group, key, jobs in self._leak_places():
            for change in (lambda g: g.update({key: True}), lambda g: g.update({key: False}), lambda g: g.update({key: "0"}),
                           lambda g: g.update({key: "could-not-check"}), lambda g: g.update({key: None}),
                           lambda g: g.update({key: 0.0}), lambda g: g.update({key: -1}), lambda g: g.pop(key)):
                text = self._closing(lambda it: change(where(it)[group]))
                self.assertRegex(text, rf"(?m)^LOOK  {self.LEAK_LINE} \(a count was not read\){jobs}$", (group, key))
                self.assertNotIn(self.ABOVE, text)
        for change in (lambda it: it["D2.3"].update(status="could-not-check"), lambda it: it.pop("D2.3"),
                       lambda it: it["D10.7"].update(status="could-not-check"), lambda it: it.pop("D10.7"),
                       lambda it: it["D2.3"]["data"].update(journal="could-not-check")):
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.LEAK_LINE} \(a count was not read\)$")
        for change in (lambda it: job(it, "D10.7").update(broker_journal="could-not-check"),
                       lambda it: job(it, "D10.7", "ads-report").update(runner_journal=[]),
                       lambda it: job(it, "D10.7", "ads-report").pop("runner_journal")):
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.LEAK_LINE} \(a count was not read\){self.JOB_NOTE}$")

    def test_a_count_above_zero_is_said_even_beside_one_that_was_not_read(self):
        def change(it):
            job(it, "D10.7", "ads-report")["runner_journal"]["customer_id_lines"] = 2
            it["D2.3"]["data"]["journal"].pop("pattern_hits")
        self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.LEAK_LINE} \(a count is above 0: this is a FAIL, not a reminder\){self.JOB_NOTE}$")

    def test_a_key_the_tool_does_not_name_changes_nothing_on_the_leak_line_and_is_never_printed(self):
        text = self._closing(lambda it: job(it, "D10.7")["broker_journal"].update({"acmecorp": 9}))
        self.assertRegex(text, rf"(?m)^ok    {self.LEAK_LINE}$")
        self.assertNotIn("acmecorp", text)

    def test_the_settings_file_must_be_root_root_0644(self):
        line = "retention at least 30 days, set by our file"
        for field, values in (("owner", ("acme-ops", "Root", "could-not-check", None, 0, True)),
                              ("group", ("jsmith", "wheel", "could-not-check", None, 0, True)),
                              ("mode", ("0o666", "0o664", "0o600", "0o0644", "644", "could-not-check", None, 420, True))):
            for value in values:
                text = self._closing(lambda it: it["D2.4"]["data"]["drop_in"].update({field: value}))
                self.assertRegex(text, rf"(?m)^LOOK  {line}", (field, value))
                for gone in ACCOUNTS + ("wheel",):
                    self.assertNotIn(gone, text)
            text = self._closing(lambda it: it["D2.4"]["data"]["drop_in"].pop(field))
            self.assertRegex(text, rf"(?m)^LOOK  {line}", field)

    def test_another_journal_directory_is_look_with_its_count(self):
        look = lambda n: self._closing(lambda it: it["D2.4"]["data"]["usage"].update(other_directories=n))
        self.assertRegex(look(1), rf"(?m)^LOOK  {self.DIRS_LINE} \(1 other: needs your statement in the evidence\)$")
        self.assertRegex(look(3), rf"(?m)^LOOK  {self.DIRS_LINE} \(3 other: needs your statement in the evidence\)$")
        self.assertRegex(look(10 ** 400), rf"(?m)^LOOK  {self.DIRS_LINE} \(<withheld> other: needs your statement in the evidence\)$")
        for bad in (True, False, "could-not-check", None, "0", 0.0, -1, PLANT):
            text = look(bad)
            self.assertRegex(text, rf"(?m)^LOOK  {self.DIRS_LINE} \(not read\)$", bad)
            self.assertNotIn("sk-or", text)
        text = self._closing(lambda it: it["D2.4"]["data"]["usage"].pop("other_directories"))
        self.assertRegex(text, rf"(?m)^LOOK  {self.DIRS_LINE} \(not read\)$")

    def test_fewer_journal_files_than_days_is_look(self):
        def look(files, reach=31):
            def change(it):
                it["D2.4"]["data"]["usage"]["files"] = files
                it["D2.4"]["data"]["reach_days"] = reach
            return self._closing(change)
        self.assertRegex(look(30), rf"(?m)^LOOK  {self.DIRS_LINE} \(fewer files than days: needs explaining\)$")
        self.assertRegex(look(6, 7), rf"(?m)^LOOK  {self.DIRS_LINE} \(fewer files than days: needs explaining\)$")
        self.assertRegex(look(31), rf"(?m)^ok    {self.DIRS_LINE}$")
        self.assertRegex(look(7, 7), rf"(?m)^ok    {self.DIRS_LINE}$")
        self.assertRegex(look(32), rf"(?m)^ok    {self.DIRS_LINE}$")
        for files, reach in ((True, 31), ("could-not-check", 31), (None, 31), (110, True), (110, None),
                             (110, "could-not-check"), (110.0, 31), ("110", 31)):
            self.assertRegex(look(files, reach), rf"(?m)^LOOK  {self.DIRS_LINE} \(not read\)$", (files, reach))
        text = self._closing(lambda it: it["D2.4"]["data"]["usage"].pop("files"))
        self.assertRegex(text, rf"(?m)^LOOK  {self.DIRS_LINE} \(not read\)$")
        for change in (lambda it: it.pop("D2.4"), lambda it: it["D2.4"].update(status="could-not-check"),
                       lambda it: it["D2.4"]["data"].update(usage="could-not-check")):
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.DIRS_LINE} \(not read\)$")

    def test_another_directory_and_fewer_files_are_both_said(self):
        def change(it):
            it["D2.4"]["data"]["usage"].update(other_directories=1, files=3)
        self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.DIRS_LINE} \(fewer files than days: needs explaining\) "
                                                r"\(1 other: needs your statement in the evidence\)$")

    def test_nothing_could_not_check_counts_the_places(self):
        b = bundle()
        b["items"]["D1.7"]["data"]["files"][0]["keys"] = "could-not-check"
        b["items"]["D1.7"]["data"]["unprivileged_port_start"] = "could-not-check"
        self.assertIn("LOOK  nothing in the bundle is could-not-check (3 places)", closing_of(b))   # D5.3's status is the third

    def test_a_history_key_named_could_not_check_is_a_count_of_runs_not_a_place(self):
        def clean():                                              # the fixture's D5.3 is could-not-check
            b = bundle()
            del b["items"]["D5.3"]
            return b
        # Seen on the box on 2026-10-12: history_counts {could-not-check: 1, ok: 477}, which CHECKLIST
        # D4.5 calls a count of runs. The line stays ok and says what it did not count.
        b = clean()
        b["items"]["D4.5"]["data"]["history_counts"]["could-not-check"] = 1
        self.assertRegex(closing_of(b), r"(?m)^ok    nothing in the bundle is could-not-check "
                                        r"\(not counted: 1 past listener-check runs in D4\.5's history\)$")
        b["items"]["D1.7"]["data"]["unprivileged_port_start"] = "could-not-check"
        self.assertRegex(closing_of(b), r"(?m)^LOOK  nothing in the bundle is could-not-check \(1 place\) "
                                        r"\(not counted: 1 past listener-check runs in D4\.5's history\)$")

    def test_only_that_one_key_with_a_count_is_left_out(self):
        def clean():
            b = bundle()
            del b["items"]["D5.3"]
            return b
        for change in (lambda d: d["history_counts"].__setitem__("could-not-check", "x"),      # not a count
                       lambda d: d["history_counts"].__setitem__("could-not-check", True),
                       lambda d: d["history_counts"].__setitem__("could-not-check", -1),
                       lambda d: d["history_counts"].__setitem__("could-not-check", 10 ** 15),   # too long to print
                       lambda d: d.__setitem__("history_counts", "could-not-check"),           # the field not read
                       lambda d: d["alert_log"].__setitem__("could-not-check", 1),             # another dict
                       lambda d: d.__setitem__("could-not-check", 1)):
            b = clean()
            change(b["items"]["D4.5"]["data"])
            self.assertRegex(closing_of(b), r"(?m)^LOOK  nothing in the bundle is could-not-check \(1 place\)$")
        b = clean()                                               # no number longer than the print rule allows
        b["items"]["D4.5"]["data"]["history_counts"]["could-not-check"] = 4111111111111111
        self.assertNotIn("4111111111111111", closing_of(b))
        b["items"]["D4.5"]["data"]["history_counts"]["could-not-check"] = 10 ** 15 - 1
        self.assertIn("(not counted: 999999999999999 past", closing_of(b))
        b = clean()                                               # an item that was not observed is not excused
        b["items"]["D4.5"] = {"status": "could-not-check", "data": {"history_counts": {"could-not-check": 1}}}
        self.assertRegex(closing_of(b), r"(?m)^LOOK  nothing in the bundle is could-not-check \(2 places\)$")

    def test_a_storage_word_outside_the_set_is_other(self):
        def look(value):
            b = bundle()
            b["items"]["D2.4"]["data"]["settings"]["Storage"] = {"value": value, "file": "/etc/x.conf", "number": None}
            return closing_of(b)
        self.assertIn("(Storage is volatile)", look("volatile"))
        self.assertIn("(Storage is <other>)", look(PLANT))
        self.assertIn("(Storage is <withheld>)", look(["x"]))
        self.assertNotIn("sk-or", look(PLANT))
        for ok in (None, "auto", "persistent"):
            self.assertRegex(look(ok), r"(?m)^ok    retention at least 30 days")

    def test_every_item_observed_is_look_for_an_empty_item_list_and_a_non_string_status(self):
        for items in ({}, {"D1.1": {"status": 7}}, {"D1.1": {}}):
            b = bundle()
            b["items"] = items
            self.assertRegex(closing_of(b), r"(?m)^LOOK  every item observed")

    def test_credentials_as_the_dict_the_collector_produces_is_withheld_and_look(self):
        b = bundle()
        del b["items"]["D5.3"]
        b["credentials"] = {"could-not-check": "OSError: /var/lib/hermes/acmecorp.json: denied"}
        text = run(json.dumps(b))[1]
        self.assertRegex(text, r"(?m)^credentials: <withheld>$")
        self.assertRegex(text, r"(?m)^LOOK  nothing in the bundle is could-not-check \(1 place\) \(credentials is not a list\)$")
        for gone in ("/var/lib", "acmecorp", "denied", "OSError"):
            self.assertNotIn(gone, text)
        b["credentials"] = {"role": "x"}                 # not a list, nothing could-not-check in it
        text = run(json.dumps(b))[1]
        self.assertRegex(text, r"(?m)^LOOK  nothing in the bundle is could-not-check \(credentials is not a list\)$")
        self.assertRegex(run(json.dumps(bundle()))[1], r"(?m)^credentials: 2$")

    def test_the_thresholds_are_exactly_thirty_days(self):
        def closing(change):
            b = bundle()
            del b["items"]["D5.3"]
            change(b["items"]["D2.4"]["data"])
            return closing_of(b)
        ret = lambda n: (lambda d: d["settings"]["MaxRetentionSec"].update(number=n))
        for n in (604800, 30 * 86400 - 1, 29 * 86400, 0):
            self.assertRegex(closing(ret(n)), r"(?m)^LOOK  retention at least 30 days", n)
        self.assertRegex(closing(ret(30 * 86400)), r"(?m)^ok    retention at least 30 days")
        self.assertRegex(closing(ret(30 * 86400 + 1)), r"(?m)^ok    retention at least 30 days")
        reach = lambda n: (lambda d: d.update(reach_days=n))
        for n in (0, 12, 13, 29):
            self.assertRegex(closing(reach(n)), r"(?m)^LOOK  the journal reaches 30 days", n)
        for n in (30, 31):
            self.assertRegex(closing(reach(n)), r"(?m)^ok    the journal reaches 30 days", n)
        age = lambda n: (lambda d: d["usage"].update(on_disk_age_seconds=n))
        self.assertRegex(closing(age(600)), r"(?m)^ok    the journal is being written")
        self.assertRegex(closing(age(601)), r"(?m)^LOOK  the journal is being written")

    def test_the_reach_note_goes_through_the_number_formatter(self):
        def note(n):
            b = bundle()
            b["items"]["D2.4"]["data"]["reach_days"] = n
            return closing_of(b)
        text = note(-(10 ** 4000))
        self.assertIn("LOOK  the journal reaches 30 days", text)
        self.assertNotRegex(text, r"[0-9]{16}")
        self.assertIn("reach is <withheld> days", text)
        self.assertIn("reach is 12 days", note(12))
        self.assertIn("reach is -3 days", note(-3))

    def test_each_refusal_is_needed_with_a_count_above_zero(self):
        for key in ("refused/disabled", "refused/quota", "refused/bad_request"):
            for change in (lambda c: c.pop(key), lambda c: c.update({key: 0}), lambda c: c.update({key: -1})):
                for app in JOBS:
                    b = clean()
                    change(job(b["items"], "D10.7", app)["journal_counts"])
                    self.assertRegex(closing_of(b), rf"(?m)^LOOK  the three live refusals are in the journal \(missing: {key}\)", key)

    def test_journal_counts_need_both_parts_in_the_label_sets(self):
        b = bundle()
        counts = job(b["items"], "D10.7")["journal_counts"]
        counts.update({"acmecorp/quota": 4, "refused/acmecorp": 5, "10.0.0.5/-": 6})
        text = run(json.dumps(b))[1]
        self.assertIn("refused/quota: 1, +3 other keys}", text)
        for gone in ("acmecorp", "10.0.0.5"):
            self.assertNotIn(gone, text)

    def test_an_unobserved_item_whose_id_is_not_a_d_id_is_counted_in_header_and_closing_line(self):
        b = bundle()
        del b["items"]["D5.3"]
        b["items"]["acmecorp"] = {"status": "could-not-check"}
        text = run(json.dumps(b))[1]
        self.assertRegex(text, r"(?m)^items 16 \| not observed: 1 other$")
        self.assertIn("LOOK  every item observed (16 items) (not observed: 1 other)", text)
        self.assertNotIn("acmecorp", text)
        b["items"]["D5.3"] = {"status": "could-not-check"}
        self.assertRegex(run(json.dumps(b))[1], r"(?m)^items 17 \| not observed: D5\.3, 1 other$")

    def test_the_limited_mark_needs_exactly_the_limited_options(self):
        b = bundle()
        keys = b["items"]["D1.7"]["data"]["files"][0]["keys"]
        keys[1]["options"] = ["a", "b", "c", "d", "e"]
        keys[0]["options"] = ["restrict"]
        text = run(json.dumps(b))[1]
        self.assertIn("keys: 2 (ssh-ed25519 options=1, ssh-ed25519 options=5)", text)
        self.assertNotIn("limited_to_the_forward", text)

    def test_the_could_not_check_walk_matches_the_exact_string_only(self):
        self.assertEqual(SB.cnc_places({"a": "could-not-check: x", "could-not-check x": 1, "b": "x could-not-check"}), 0)
        b = bundle()
        del b["items"]["D5.3"]
        b["items"]["D1.1"]["data"]["note"] = "could-not-check: x"
        self.assertRegex(closing_of(b), r"(?m)^ok    nothing in the bundle is could-not-check$")

    def test_a_key_outside_the_service_set_makes_the_code_line_look(self):
        for extra in ({"acmecorp": ["app_lib.py"]}, {"acmecorp": []}):
            b = bundle()
            del b["items"]["D5.3"]
            b["items"]["D4.6"]["data"]["files_newer_than_start"].update(extra)
            self.assertRegex(closing_of(b), r"(?m)^LOOK  no service runs older code")

    def test_not_a_bundle_is_one_line_and_exit_2(self):
        for text in ("", "collect-review-evidence: refused\n", "[]", '{"kind": "laptop", "items": {}}',
                     '{"kind": "box"}', '{"kind": "box", "items": []}', "[" * 100000):
            rc, out = run(text)
            self.assertEqual((rc, out.count("\n")), (2, 1), text[:20])
            self.assertTrue(out.startswith("summarize-review-bundle: not a box bundle"), out)

    def test_odd_shapes_never_raise(self):
        b = bundle()
        b["items"]["D1.7"] = {"status": "observed"}                                  # no data
        b["items"]["D2.4"] = {"status": "observed", "data": {"settings": "could-not-check", "usage": 7}}
        b["items"]["D10.8"] = {"status": "observed", "data": {"results": "x"}}
        b["items"]["D10.7"] = {"status": "observed", "data": []}
        b["items"]["D4.6"] = "observed"
        b["items"]["D1.7"] = {"status": "observed", "data": {"daemon_options": "x", "match_lines": True, "files": "x"}}
        b["items"]["D2.4"]["data"]["usage"] = {"on_disk_age_seconds": True, "flushed_to_disk": "x"}
        b["items"]["D2.4"]["data"]["settings"] = {"Storage": "x", "MaxRetentionSec": []}
        b["items"]["D2.4"]["data"]["service"] = []
        b["items"]["D2.3"] = {"status": "observed", "data": {"undecodable_characters": [], "scanned_characters": {}}}
        b["items"]["D4.1"] = {"status": "observed", "data": {"secret_env": ["x"], "listeners": 5, "docker_dns_listeners": {}}}
        b["items"]["D4.5"] = {"status": "observed", "data": {"history_counts": 3, "alert_log": [], "installed_equal_repo": "x"}}
        b["items"]["D7.1"] = {"status": "observed", "data": {"records": float("nan")}}
        b["items"]["D10.7"] = {"status": "observed", "data": {"journal_counts": {"ok/-": "x", 3: 1}, "note_counts": []}}
        b["fingerprint"] = None
        b["credentials"] = 7
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertIn("D4.6", text)

    def test_it_reads_a_file_named_on_the_command_line(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bundle(), f)
        out = io.StringIO()
        try:
            self.assertEqual(SB.main([f.name], out=out), 0)
        finally:
            os.unlink(f.name)
        self.assertIn("reach_days: 31", out.getvalue())


PER_JOB = ("D10.3", "D10.4", "D10.7", "D10.8")


class TestEveryJob(unittest.TestCase):
    """The per-job shape: the item lines show each job under its name, and a closing line is ok only
    when it holds for every installed job."""
    REFUSALS = "the three live refusals are in the journal"
    RUN_OK = "at least one run/ok result"
    LEAKS = r"no leak count above 0 \(D2\.3, D10\.7\)"
    CODE = "no service runs older code than the box holds"
    REACH = "the journal reaches 30 days"
    JOBS_LINE = "every job is declared and installed"
    CNC_LINE = "nothing in the bundle is could-not-check"
    LAYOUT = "every job's folders are as designed and no container mounts the job state"
    UNITS = "the installed job units equal the repository's and every stored result is in whitelist"
    PROBE = "the credential probe matches the declared map and a figures run starts no AI service"
    FAIL = r" \(a count is above 0: this is a FAIL, not a reminder\)"
    ONE = r" \(not so for 1 of 2 jobs\)"
    ONE_UNREAD = r" \(not so for 1 of 2 jobs: a value could not be checked\)"
    # (what to put in a job's entry, the line that must say it, its note): a count of something bad, in any job
    NEVER_EXCUSED = (
        (lambda it, app: job(it, "D10.7", app)["broker_journal"].update(known_secret_hits=1), LEAKS, FAIL + ONE),
        (lambda it, app: job(it, "D10.7", app)["runner_journal"].update(customer_id_lines=3), LEAKS, FAIL + ONE),
        (lambda it, app: job(it, "D10.7", app)["runner_journal"].update(pattern_hits=10 ** 400), LEAKS, FAIL + ONE),
        (lambda it, app: job(it, "D10.8", app).update(out_of_whitelist=2), UNITS, ONE),
        (lambda it, app: job(it, "D10.4", app).update(layout_problems=["acmecorp is not 0700"]), LAYOUT, ONE),
    )

    @staticmethod
    def _closing(change):
        b = clean()
        change(b["items"])
        return closing_of(b)

    def _status(self, closing, line):
        m = re.search(rf"(?m)^(ok    |LOOK  ){line}(.*)$", closing)
        self.assertIsNotNone(m, line)
        return m.group(1).strip(), m.group(2)

    def test_the_item_lines_print_each_job_s_values_under_its_name(self):
        text = run(json.dumps(bundle()))[1]
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            block = text[text.index(f"\n{iid} "):].split("\nD", 2)[1]
            self.assertRegex(block, r"(?m)^  apps: 2$", iid)
            self.assertRegex(block, r"(?m)^    ads-audit:\n      declared: true\n      installed: true\n(      .*\n)*"
                                    r"    ads-report:\n      declared: true\n      installed: true$", iid)
        for want in ("      runner_path_active: active", "      broker_user_groups: 2",
                     "      layout_problems: 0\n      layout_reason: null",
                     "      journal_counts: {ok/-: 3, refused/bad_request: 2, refused/disabled: 1, refused/quota: 1}",
                     "      first_entry: 2026-10-05T18:35:47Z\n      installed_since_last_pass: false",
                     "      out_of_whitelist: 0\n      run/ok results: 1",
                     "  declared_apps: 2\n  installed_apps: 2\n  on_disk_apps: 2\n  units_not_counted: 0\n  on_disk_not_counted: 0",
                     "  installed_equal_repo: {hermes-app-broker@.service: true, hermes-app-runner@.path: true, "
                     "hermes-app-runner@.service: true}",
                     "  containers: 3\n  containers_mounting_app_state: 0\n  containers_not_inspected: 0",
                     "  oldest_entry: {journal: 2026-09-18T15:11:34Z, apps: {ads-audit: {broker: 2026-10-05T18:35:47Z, "
                     "runner: null}, ads-report: {broker: 2026-10-08T09:00:00Z, runner: null}}}",
                     "  apps_declared: 2\n  apps_installed: 2",
                     "started_at: {boot: 2026-10-01T00:00:00Z, hermes-app-broker@ads-audit: 2026-10-07T06:45:50Z, "
                     "hermes-app-broker@ads-report: 2026-10-08T09:00:00Z, hermes-broker"):
            self.assertIn(want, text)
        self.assertEqual(text.count("      run/ok results: 1"), 2)
        self.assertNotIn("older shape", text)
        self.assertNotIn("hermes-app-ads", text)                 # an account name is still never printed

    def test_a_job_name_that_is_not_a_job_name_is_withheld_wherever_it_is(self):
        for bad in ("Acme-Dental", "acme_dental", "10.0.0.5", "ops@acme.com", "a" * 33, "9lives", PLANT, "acme dental", ""):
            b = bundle()
            it = b["items"]
            for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
                it[iid]["data"]["apps"][bad] = it[iid]["data"]["apps"].pop("ads-report")
            it["D2.4"]["data"]["oldest_entry"]["apps"][bad] = it["D2.4"]["data"]["oldest_entry"]["apps"].pop("ads-report")
            for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
                it["D4.6"]["data"][group]["hermes-app-broker@" + bad] = it["D4.6"]["data"][group].pop(BROKERS[1])
            for key in ("declared_apps", "installed_apps", "on_disk_apps"):
                it["D10.3"]["data"][key] = ["ads-audit", bad]
            rc, text = run(json.dumps(b))
            self.assertEqual(rc, 0)
            if bad:
                self.assertNotIn(bad, text, bad)
            self.assertNotIn("ads-report", text)
            self.assertEqual(len(re.findall(r"(?m)^    <withheld>:$", text)), 4, bad)
            self.assertIn("apps: {ads-audit: {broker: 2026-10-05T18:35:47Z, runner: null}, "
                          "<withheld>: {broker: 2026-10-08T09:00:00Z, runner: null}}", text)
            self.assertRegex(text, r"(?m)^  files_checked: \{.*hermes-app-broker@<withheld>: 6.*\}$")
            self.assertIn("hermes-app-broker@ads-audit: 7", text)
            self.assertNotIn("other keys}", text[text.index("\nD4.6 "):text.index("\nD7.1 ")])
            self.assertRegex(text, rf"(?m)^LOOK  {self.JOBS_LINE} \(1 with a name that is not a job name\)$")
            # D4.6's own list still names the job whose broker key is now under another name: two services are not as they should be
            self.assertRegex(text, rf"(?m)^LOOK  {self.CODE} \(not so for 2 of 5 services: a value could not be checked\)$")

    def test_every_job_is_declared_and_installed(self):
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.JOBS_LINE} \(2 jobs\)$")
        d3 = lambda it: it["D10.3"]["data"]
        cases = (
            (lambda it: [d3(it).update(installed_apps=["ads-audit"])] + [job(it, i, "ads-report").update(installed=False) for i in PER_JOB],
             r" \(1 declared but not installed\)"),
            (lambda it: [d3(it).update(declared_apps=["ads-audit"])] + [job(it, i, "ads-report").update(declared=False) for i in PER_JOB],
             r" \(1 installed but not declared\)"),
            # the lists alone changed: every item's entry for that job now says otherwise
            (lambda it: d3(it).update(installed_apps=["ads-audit"]),
             r" \(1 declared but not installed\) \(4 per-job entries disagree with the lists\)"),
            (lambda it: d3(it).update(on_disk_apps=["ads-audit", "ads-report", "parked", "stopped"]), r" \(2 on disk only\)"),
            (lambda it: d3(it).update(declared_apps=[], installed_apps=[], on_disk_apps=[], apps={}),
             r" \(2 in no list\) \(no installed job\)"),
            (lambda it: d3(it).update(units_not_counted=3), r" \(3 unit lines not counted\)"),
            (lambda it: d3(it).update(units_not_counted=1), r" \(1 unit line not counted\)"),
            (lambda it: d3(it).update(on_disk_not_counted=1), r" \(1 entry on disk not counted\)"),
            (lambda it: d3(it).update(on_disk_not_counted=2), r" \(2 entries on disk not counted\)"),
            (lambda it: d3(it).update(units_not_counted="could-not-check"), r" \(unit lines not counted: could not be checked\)"),
            (lambda it: d3(it).update(units_not_counted=True), r" \(unit lines not counted: a value that is not a number\)"),
            (lambda it: d3(it).update(units_not_counted=10 ** 400), r" \(unit lines not counted: a value that is not a number\)"),
            (lambda it: d3(it).pop("on_disk_not_counted"), r" \(entries on disk not counted: not read\)"),
            (lambda it: d3(it).update(installed_apps="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: d3(it).update(declared_apps=None), r" \(the jobs could not be checked\)"),
            (lambda it: d3(it).update(on_disk_apps=[7]), r" \(the jobs could not be checked\)"),
            (lambda it: d3(it).pop("on_disk_apps"), r" \(the jobs could not be checked\)"),
            (lambda it: d3(it).update(apps="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: d3(it).update(apps={}), r" \(not so for 2 of 2 jobs: a value could not be checked\)"),
            (lambda it: d3(it).pop("apps"), r" \(older shape\)"),
            (lambda it: d3(it).pop("declared_apps"), r" \(older shape\)"),
            (lambda it: it["D10.3"].update(status="could-not-check"), r" \(not read\)"),
            (lambda it: it.pop("D10.3"), r" \(not read\)"),
            (lambda it: job(it, "D10.3").update(broker_user_groups="could-not-check"),
             r" \(not so for 1 of 2 jobs: a value could not be checked\)"),
            (lambda it: job(it, "D10.3")["broker_unit"].update(User="could-not-check"),
             r" \(not so for 1 of 2 jobs: a value could not be checked\)"),
            (lambda it: job(it, "D10.3").pop("installed"),
             r" \(1 per-job entry disagrees with the lists\) \(not so for 1 of 2 jobs: a value could not be checked\)"),
            (lambda it: job(it, "D10.7", "ads-report").update(declared=False), r" \(1 per-job entry disagrees with the lists\)"),
            (lambda it: job(it, "D10.4").update(installed="could-not-check"), r" \(1 per-job entry disagrees with the lists\)"),
            (lambda it: [job(it, i, "ads-report").update(declared=False) for i in ("D10.7", "D10.8")],
             r" \(2 per-job entries disagree with the lists\)"),
            (lambda it: it["D10.8"]["data"]["apps"].update(parked={"declared": False, "installed": False}), r" \(1 in no list\)"),
            (lambda it: [it[i]["data"]["apps"].update(parked={"declared": False, "installed": False}) for i in PER_JOB],
             r" \(1 in no list\)"),
            (lambda it: d3(it)["apps"].update({"ads-report": "could-not-check"}),
             r" \(not so for 1 of 2 jobs: a value could not be checked\)"),
        )
        for change, note in cases:
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.JOBS_LINE}{note}$", note)

    def test_one_job_failing_a_line_is_look_with_how_many_jobs(self):
        for app in JOBS:
            cases = (
                (lambda it: job(it, "D10.7", app)["journal_counts"].pop("refused/disabled"),
                 self.REFUSALS, r" \(missing: refused/disabled\) \(not so for 1 of 2 jobs\)"),
                (lambda it: job(it, "D10.7", app).update(journal_counts={}),
                 self.REFUSALS, r" \(missing: refused/disabled, refused/quota, refused/bad_request\) \(not so for 1 of 2 jobs\)"),
                (lambda it: job(it, "D10.8", app)["results"].pop(0), self.RUN_OK, r" \(not so for 1 of 2 jobs\)"),
                (lambda it: job(it, "D10.8", app).update(results=[]), self.RUN_OK, r" \(not so for 1 of 2 jobs\)"),
                (lambda it: job(it, "D10.7", app)["runner_journal"].update(customer_id_lines=4), self.LEAKS,
                 r" \(a count is above 0: this is a FAIL, not a reminder\) \(not so for 1 of 2 jobs\)"),
                (lambda it: job(it, "D10.7", app)["broker_journal"].pop("pattern_hits"), self.LEAKS,
                 r" \(a count was not read\) \(not so for 1 of 2 jobs\)"),
                (lambda it: it["D4.6"]["data"]["files_newer_than_start"].update({"hermes-app-broker@" + app: ["unit"]}),
                 self.CODE, r" \(not so for 1 of 4 services\)"),
                (lambda it: it["D4.6"]["data"]["files_checked"].pop("hermes-app-broker@" + app), self.CODE,
                 r" \(not so for 1 of 4 services: a value could not be checked\)"),
                (lambda it: it["D4.6"]["data"]["files_newer_than_start"].update({"hermes-app-broker@" + app: "could-not-check"}),
                 self.CODE, r" \(not so for 1 of 4 services: a value could not be checked\)"),
            )
            for change, line, note in cases:
                closing = self._closing(change)
                self.assertRegex(closing, rf"(?m)^LOOK  {line}{note}$", (app, line))
                self.assertNotRegex(closing, r"ads-audit|ads-report")          # how many jobs, never which
        both = self._closing(lambda it: [job(it, "D10.8", a).update(results=[]) for a in JOBS])
        self.assertRegex(both, rf"(?m)^LOOK  {self.RUN_OK} \(not so for 2 of 2 jobs\)$")

    def test_three_leak_counts_at_zero_for_one_job_do_not_hide_a_hit_in_the_other(self):
        closing = self._closing(lambda it: job(it, "D10.7", "ads-report")["broker_journal"].update(known_secret_hits=1))
        self.assertRegex(closing, rf"(?m)^LOOK  {self.LEAKS} \(a count is above 0: this is a FAIL, not a reminder\) \(not so for 1 of 2 jobs\)$")

    def test_a_job_installed_since_the_last_pass_is_said_on_the_reach_line(self):
        one = self._closing(lambda it: job(it, "D10.7", "ads-report").update(installed_since_last_pass=True))
        self.assertRegex(one, rf"(?m)^ok    {self.REACH} \(1 job installed since the last PASS: judged from its first entry\)$")
        two = self._closing(lambda it: [job(it, "D10.7", a).update(installed_since_last_pass=True) for a in JOBS])
        self.assertRegex(two, rf"(?m)^ok    {self.REACH} \(2 jobs installed since the last PASS: each judged from its first entry\)$")
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.REACH}$")
        for none in (None, False):                       # no --last-pass-collected-at, or installed before it
            self.assertRegex(self._closing(lambda it: job(it, "D10.7").update(installed_since_last_pass=none)),
                             rf"(?m)^ok    {self.REACH}$")
        def short(it):
            it["D2.4"]["data"]["reach_days"] = 12
            job(it, "D10.7", "ads-report")["installed_since_last_pass"] = True
        self.assertRegex(self._closing(short), rf"(?m)^LOOK  {self.REACH} \(reach is 12 days: .*\) "
                                               r"\(1 job installed since the last PASS: judged from its first entry\)$")
        unread = self._closing(lambda it: job(it, "D10.7").update(installed_since_last_pass="could-not-check"))
        self.assertRegex(unread, rf"(?m)^LOOK  {self.REACH} \(not so for 1 of 2 jobs: a value could not be checked\)$")

    def test_the_report_store_and_the_figures_services_are_printed_and_are_not_other_keys(self):
        text = run(json.dumps(bundle()))[1]
        self.assertIn("  report_archive: {parent: {owner_is_root: true, group_is_root: true, mode: 0o700}, rows: 2, "
                      "rows_listed: true, containers_mounting: 0, containers_not_inspected: 0}", text)
        self.assertIn("D10.1  observed\n  rc: 0\n  probe: {matches_declared: true, services: 4, "
                      "figures_services: [ads-collector, ads-reader]}\n", text)
        for iid in ("D7.1", "D10.1"):
            block = text[text.index(f"\n{iid} "):].split("\nD", 2)[1]
            self.assertNotIn("other keys", block, iid)
        b = bundle()
        b["items"]["D10.1"]["data"]["probe"]["figures_services"] = ["ads-collector", "ads-drafter", "acmecorp", 7]
        b["items"]["D7.1"]["data"]["report_archive"]["parent"] = "symlink"
        text = run(json.dumps(b))[1]
        self.assertIn("figures_services: [ads-collector, ads-drafter, <other>, <withheld>]", text)
        self.assertIn("report_archive: {parent: symlink, rows: 2", text)
        self.assertNotIn("acmecorp", text)

    def test_the_previous_review_s_shape_prints_without_a_traceback(self):
        rc, text = run(json.dumps(old_bundle()))
        self.assertEqual(rc, 0)
        for iid in ("D4.6", "D10.7", "D10.8"):
            self.assertRegex(text, rf"(?m)^{re.escape(iid)}  observed\n(  .*\n)*  \(older shape\)$", iid)
        self.assertIn("  oldest_entry: {journal: 2026-09-18T15:11:34Z, +2 other keys} (older shape)", text)
        self.assertNotIn("run/ok results", text)
        closing = text[text.index("Before the real collection"):]
        for line in (self.REFUSALS, self.RUN_OK, self.LEAKS, self.CODE):
            self.assertRegex(closing, rf"(?m)^LOOK  {line} \(older shape\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.JOBS_LINE} \(not read\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.LAYOUT} \(not read\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.UNITS} \(not read\) \(older shape\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.PROBE} \(not read\)$")
        self.assertIn("hermes-app-broker@<withheld>: 7", text)       # no list of declared jobs: no name is printed
        self.assertRegex(closing, r"(?m)^LOOK  the report store holds only owner-only client folders \(not in this bundle\)$")
        self.assertRegex(closing, rf"(?m)^ok    {self.REACH}$")
        self.assertEqual(len(re.findall(r"(?m)^(?:ok   |LOOK) ", closing)), 20)
        b = old_bundle()                                 # an old D10.3, D10.4: observed, with keys this tool does not know
        b["items"]["D10.3"] = {"status": "observed", "data": {"broker_unit": {"User": "hermes-app-ads-audit"}}}
        b["items"]["D10.4"] = {"status": "observed", "data": {"layout_problems": [], "containers": 3}}
        b["items"]["D2.3"]["data"]["journal"]["pattern_hits"] = 2
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertRegex(text, r"(?m)^D10\.3  observed\n  \+1 other keys\n  \(older shape\)$")
        self.assertRegex(text, r"(?m)^D10\.4  observed\n  containers: 3\n  \+1 other keys\n  \(older shape\)$")
        self.assertRegex(text, rf"(?m)^LOOK  {self.JOBS_LINE} \(older shape\)$")
        self.assertRegex(text, rf"(?m)^LOOK  {self.LEAKS} \(a count is above 0: this is a FAIL, not a reminder\) \(older shape\)$")
        self.assertNotIn("hermes-app-ads", text)

    # ---- R-A: a job's could-not-check is as loud as an item's
    def test_a_could_not_check_inside_a_job_is_counted_in_the_places(self):
        cases = (
            (lambda it: job(it, "D10.4").update(layout_problems="could-not-check", layout_reason="other"), 1),
            (lambda it: job(it, "D10.8", "ads-report").update(results="could-not-check", out_of_whitelist="could-not-check"), 2),
            (lambda it: job(it, "D10.7")["journal_read"]["runner"].update(entries="could-not-check"), 1),
            (lambda it: it["D10.7"]["data"].update(apps="could-not-check"), 1),
            (lambda it: it["D2.4"]["data"]["oldest_entry"].update(apps="could-not-check"), 1),
            (lambda it: it["D2.4"]["data"]["oldest_entry"]["apps"]["ads-report"].update(broker="could-not-check"), 1),
            (lambda it: it["D4.6"]["data"].update(apps_installed="could-not-check"), 1),
            (lambda it: it["D10.3"]["data"]["apps"].update({"ads-report": "could-not-check"}), 1),
        )
        for change, places in cases:
            self.assertRegex(self._closing(change),
                             rf"(?m)^LOOK  {self.CNC_LINE} \({places} place{'' if places == 1 else 's'}\)$", places)

    def test_an_installed_job_that_could_not_be_checked_turns_every_line_that_reads_its_item(self):
        unread = self.ONE_UNREAD
        lines = {"D10.3": ((self.JOBS_LINE, unread),),
                 "D10.4": ((self.LAYOUT, unread),),
                 "D10.7": ((self.REFUSALS, r"( \(missing: [a-z_/, ]+\))?" + unread), (self.LEAKS, r"( \(a count was not read\))?" + unread),
                           (self.REACH, unread)),
                 "D10.8": ((self.RUN_OK, unread), (self.UNITS, unread))}
        for iid, depend in lines.items():
            for app in JOBS:
                def whole(it):
                    entry = job(it, iid, app)
                    for key in entry:
                        if key not in ("declared", "installed"):
                            entry[key] = "could-not-check"
                def one_value(it):                       # a value no line reads by itself
                    job(it, iid, app)["acmecorp"] = {"deep": ["could-not-check"]}
                for change in (whole, one_value):
                    closing = self._closing(change)
                    for line, note in depend:
                        self.assertRegex(closing, rf"(?m)^LOOK  {line}{note}$", (iid, app, line, change.__name__))
                    self.assertRegex(closing, rf"(?m)^LOOK  {self.CNC_LINE} \([0-9]+ places?\)$")
                    self.assertNotIn("acmecorp", closing)

    def test_the_restart_item_s_per_job_values_turn_its_line(self):
        # D4.6 holds no entry per job: its four dicts are keyed by each service, a job's broker among them
        groups = ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked")
        d = lambda it: it["D4.6"]["data"]
        for group in groups:
            for broker in BROKERS:
                for change in (lambda it: d(it)[group].update({broker: "could-not-check"}), lambda it: d(it)[group].pop(broker)):
                    self.assertRegex(self._closing(change),
                                     rf"(?m)^LOOK  {self.CODE} \(not so for 1 of 4 services: a value could not be checked\)$", group)
            # a broker of a job that is in no list
            closing = self._closing(lambda it: d(it)[group].update({"hermes-app-broker@parked": d(it)[group][BROKERS[0]]}))
            self.assertRegex(closing, rf"(?m)^LOOK  {self.CODE} \(1 broker of a job in no list\)$", group)
            self.assertNotIn("parked", closing)
        both = self._closing(lambda it: [d(it)[g].update({"hermes-app-broker@parked": 1, "hermes-app-broker@stopped": 1}) for g in groups])
        self.assertRegex(both, rf"(?m)^LOOK  {self.CODE} \(2 brokers of jobs in no list\)$")
        cases = (
            (lambda it: d(it)["started_at"].update({BROKERS[1]: "yesterday"}), r" \(not so for 1 of 4 services\)"),
            (lambda it: d(it)["started_after_last_pass"].update({BROKERS[1]: "no"}), r" \(not so for 1 of 4 services\)"),
            (lambda it: d(it)["started_after_last_pass"].update({BROKERS[1]: None, "hermes-broker": True}), ""),   # no last PASS given; a restart
            (lambda it: d(it)["files_newer_than_start"].update({"hermes-broker": ["app_lib.py"], BROKERS[0]: ["unit"]}),
             r" \(not so for 2 of 4 services\)"),
            (lambda it: d(it).update(started_at="could-not-check"), r" \(not so for 4 of 4 services: a value could not be checked\)"),
            (lambda it: d(it)["files_checked"].update(acmecorp=3), r" \(1 entry that is not a service\)"),
        )
        for change, note in cases:
            closing = self._closing(change)
            self.assertRegex(closing, rf"(?m)^{'LOOK  ' if note else 'ok    '}{self.CODE}{note}$", note)
        for key in ("apps_declared", "apps_installed"):
            closing = self._closing(lambda it: d(it).update({key: "could-not-check"}))
            self.assertRegex(closing, rf"(?m)^LOOK  {self.CODE} \(the jobs could not be checked\)$", key)

    def test_a_job_that_is_not_installed_excuses_only_an_absent_or_unread_value_on_the_layout_and_whitelist_lines(self):
        def closing(change):
            b = not_installed(clean())
            change(b["items"])
            return closing_of(b)
        for iid, key, line, odd in (("D10.8", "out_of_whitelist", self.UNITS, (1.0, True, None, "0", -1, 2)),
                                    ("D10.4", "layout_problems", self.LAYOUT, (0, True, None, "", {}, ["x"]))):
            for value in odd:
                self.assertRegex(closing(lambda it: job(it, iid, "ads-report").update({key: value})),
                                 rf"(?m)^LOOK  {line} .*not so for 1 of 2 jobs.*$", (key, value))
            for good in ("could-not-check", "absent"):
                def change(it):
                    if good == "absent":
                        job(it, iid, "ads-report").pop(key, None)
                    else:
                        job(it, iid, "ads-report")[key] = good
                self.assertRegex(closing(change), rf"(?m)^ok    {line}$", (key, good))

    def test_the_reach_line_reads_every_installed_job_s_oldest_entry_and_first_entry(self):
        oldest = lambda it: it["D2.4"]["data"]["oldest_entry"]
        cases = (
            (lambda it: oldest(it)["apps"].update({"ads-report": {}}), self.ONE_UNREAD),
            (lambda it: oldest(it)["apps"].update({"ads-report": {"broker": 5, "runner": None}}), self.ONE_UNREAD),
            (lambda it: oldest(it)["apps"].update({"ads-report": {"broker": "yesterday", "runner": None}}), self.ONE_UNREAD),
            (lambda it: oldest(it)["apps"].update({"ads-report": {"broker": True}}), self.ONE_UNREAD),
            (lambda it: it["D2.4"]["data"].update(oldest_entry="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: it["D2.4"]["data"].update(oldest_entry=None), r" \(the jobs could not be checked\)"),
            (lambda it: oldest(it).pop("apps"), r" \(the jobs could not be checked\)"),
            (lambda it: job(it, "D10.7", "ads-report").update(installed_since_last_pass=True, first_entry="yesterday"), self.ONE_UNREAD),
            (lambda it: job(it, "D10.7", "ads-report").update(installed_since_last_pass=True, first_entry=7), self.ONE_UNREAD),
            (lambda it: job(it, "D10.7", "ads-report").update(installed_since_last_pass=True, first_entry={}), self.ONE_UNREAD),
        )
        for change, note in cases:
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.REACH}.*{note}$", note)
        for good in (None, "2026-10-08T09:00:00Z"):                          # a null broker is a job that has not logged
            self.assertRegex(self._closing(lambda it: oldest(it)["apps"].update({"ads-report": {"broker": good, "runner": None}})),
                             rf"(?m)^ok    {self.REACH}$")

    def test_the_reach_item_s_per_job_values_turn_the_reach_line(self):
        apps = lambda it: it["D2.4"]["data"]["oldest_entry"]["apps"]
        cases = (
            (lambda it: it["D2.4"]["data"]["oldest_entry"].update(apps="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: it["D2.4"]["data"]["oldest_entry"].update(apps=[]), r" \(the jobs could not be checked\)"),
            (lambda it: apps(it).pop("ads-report"), self.ONE_UNREAD),
            (lambda it: apps(it)["ads-audit"].update(runner="could-not-check"), self.ONE_UNREAD),
            (lambda it: apps(it).update({"ads-report": "could-not-check"}), self.ONE_UNREAD),
            (lambda it: [apps(it)[a].update(broker="could-not-check") for a in JOBS],
             r" \(not so for 2 of 2 jobs: a value could not be checked\)"),
            # one job unread here and the other unread in D10.7: two jobs, said once
            (lambda it: [apps(it).pop("ads-report"), job(it, "D10.7", "ads-audit").update(first_entry="could-not-check")],
             r" \(not so for 2 of 2 jobs: a value could not be checked\)"),
        )
        for change, note in cases:
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.REACH}{note}$", note)
        # a job that is declared and not installed has no entry to wait for
        b = not_installed(clean())
        b["items"]["D2.4"]["data"]["oldest_entry"]["apps"]["ads-report"] = {"broker": "could-not-check", "runner": "could-not-check"}
        self.assertRegex(closing_of(b), rf"(?m)^ok    {self.REACH}$")

    def test_installed_since_the_last_pass_is_one_of_four_values(self):
        for odd in ("yes", "true", 1, 0, [], {"x": 1}, "2026-10-08T09:00:00Z"):
            closing = self._closing(lambda it: job(it, "D10.7", "ads-report").update(installed_since_last_pass=odd))
            self.assertRegex(closing, rf"(?m)^LOOK  {self.REACH}{self.ONE_UNREAD}$", odd)
        closing = self._closing(lambda it: job(it, "D10.7", "ads-report").pop("installed_since_last_pass"))
        self.assertRegex(closing, rf"(?m)^ok    {self.REACH}$")                  # absent reads as null: no last PASS was given
        quiet = lambda it, app: job(it, "D10.7", app).update(installed_since_last_pass=True, first_entry=None)
        self.assertRegex(self._closing(lambda it: quiet(it, "ads-report")),
                         rf"(?m)^ok    {self.REACH} \(1 job installed since the last PASS and it has not logged yet\)$")
        self.assertRegex(self._closing(lambda it: [quiet(it, a) for a in JOBS]),
                         rf"(?m)^ok    {self.REACH} \(2 jobs installed since the last PASS and they have not logged yet\)$")
        def one_of_each(it):
            quiet(it, "ads-report")
            job(it, "D10.7", "ads-audit")["installed_since_last_pass"] = True
        self.assertRegex(self._closing(one_of_each),
                         rf"(?m)^ok    {self.REACH} \(1 job installed since the last PASS: judged from its first entry\) "
                         r"\(1 job installed since the last PASS and it has not logged yet\)$")
        self.assertRegex(self._closing(lambda it: [job(it, "D10.7", "ads-report").update(installed_since_last_pass=True),
                                                   job(it, "D10.7", "ads-report").pop("first_entry")]),
                         rf"(?m)^ok    {self.REACH} \(1 job installed since the last PASS and it has not logged yet\)$")

    def test_only_a_declared_job_s_name_is_printed(self):
        def undeclared(name):
            b = clean()
            it = b["items"]
            it["D10.3"]["data"].update(declared_apps=["ads-audit"], installed_apps=["ads-audit", name], on_disk_apps=["ads-audit", name])
            it["D4.6"]["data"].update(apps_declared=["ads-audit"], apps_installed=["ads-audit", name])
            for iid in PER_JOB:
                it[iid]["data"]["apps"][name] = dict(it[iid]["data"]["apps"].pop("ads-report"), declared=False)
            oldest = it["D2.4"]["data"]["oldest_entry"]["apps"]
            oldest[name] = oldest.pop("ads-report")
            for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
                it["D4.6"]["data"][group]["hermes-app-broker@" + name] = it["D4.6"]["data"][group].pop(BROKERS[1])
            return run(json.dumps(b))[1]
        for name in ("acme-dental", "acmecorp", "parked", "ads-report", "a"):      # each has the form of a job's name
            text = undeclared(name)
            self.assertNotRegex(text, rf"(?m)\b{re.escape(name)}\b" if len(name) > 1 else r"(?m)^    a:$", name)
            self.assertEqual(len(re.findall(r"(?m)^    <withheld>:$", text)), 4, name)
            self.assertEqual(len(re.findall(r"(?m)^    ads-audit:$", text)), 4, name)
            self.assertIn("apps: {ads-audit: {broker: 2026-10-05T18:35:47Z, runner: null}, "
                          "<withheld>: {broker: 2026-10-08T09:00:00Z, runner: null}}", text)
            for group, value in (("started_at", "2026-10-08T09:00:00Z"), ("started_after_last_pass", "false"),
                                 ("files_newer_than_start", "0"), ("files_checked", "6")):
                self.assertRegex(text, rf"(?m)^  {group}: \{{.*hermes-app-broker@<withheld>: {value}[,}}]", (name, group))
            self.assertRegex(text, rf"(?m)^LOOK  {self.JOBS_LINE} \(1 installed but not declared\)$")
            self.assertRegex(text, rf"(?m)^ok    {self.CODE}$")              # it is installed, so it is judged, unnamed
        # a name in the declared list that has not the form of one is not printed either
        b = clean()
        b["items"]["D10.3"]["data"]["declared_apps"] = ["ads-audit", "ads-report", "Acme Dental"]
        b["items"]["D10.7"]["data"]["apps"]["Acme Dental"] = {"declared": True, "installed": False}
        self.assertNotIn("Acme", run(json.dumps(b))[1])

    def test_apps_that_could_not_be_checked_or_holds_no_job_is_look_on_every_line_that_reads_it(self):
        lines = {"D10.3": (self.JOBS_LINE,), "D10.7": (self.REFUSALS, self.LEAKS), "D10.8": (self.RUN_OK,)}
        for iid, depend in lines.items():
            for value in ("could-not-check", None, []):
                closing = self._closing(lambda it: it[iid]["data"].update(apps=value))
                for line in depend:
                    self.assertRegex(closing, rf"(?m)^LOOK  {line} \(the jobs could not be checked\)$", (iid, value, line))
            # no entry at all for the two jobs D10.3 lists as installed: neither was checked
            closing = self._closing(lambda it: it[iid]["data"].update(apps={}))
            for line in depend:
                self.assertRegex(closing, rf"(?m)^LOOK  {line}.* \(not so for 2 of 2 jobs: a value could not be checked\)", (iid, line))
        closing = self._closing(lambda it: it["D10.7"]["data"].update(apps="could-not-check"))
        self.assertRegex(closing, rf"(?m)^LOOK  {self.REACH} \(the jobs could not be checked\)$")

    def test_a_box_with_no_job_at_all_is_look_on_every_line_that_needs_one(self):
        def none(it):
            it["D10.3"]["data"].update(declared_apps=[], installed_apps=[], on_disk_apps=[])
            it["D4.6"]["data"].update(apps_declared=[], apps_installed=[])
            for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
                it[iid]["data"]["apps"] = {}
            it["D2.4"]["data"]["oldest_entry"]["apps"] = {}
            for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
                for broker in BROKERS:
                    del it["D4.6"]["data"][group][broker]
        closing = self._closing(none)
        for line in (self.JOBS_LINE, self.REFUSALS, self.RUN_OK, self.LEAKS):
            self.assertRegex(closing, rf"(?m)^LOOK  {line} \(no installed job\)$", line)
        self.assertRegex(closing, rf"(?m)^LOOK  {self.LAYOUT} \(no installed job\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.UNITS} \(no installed job\)$")
        self.assertEqual(len(re.findall(r"(?m)^ok    ", closing)), 14)      # the two fixed services are still judged

    def test_a_job_declared_and_not_installed_yet_is_said_once_and_is_not_an_installed_job_s_fault(self):
        b = not_installed(clean())
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        closing = text[text.index("Before the real collection"):]
        self.assertRegex(closing, rf"(?m)^LOOK  {self.JOBS_LINE} \(1 declared but not installed\)$")
        # its expected could-not-check values are counted, and are the only other LOOK
        self.assertRegex(closing, rf"(?m)^LOOK  {self.CNC_LINE} \(8 places\)$")
        self.assertEqual(len(re.findall(r"(?m)^ok    ", closing)), 18)
        for line in (self.REFUSALS, self.RUN_OK, self.LEAKS, self.CODE, self.REACH, self.LAYOUT, self.UNITS):
            self.assertRegex(closing, rf"(?m)^ok    {line}$", line)
        # could-not-check or absent is what "not installed" excuses; a COUNT of something bad never is
        for change, line, note in self.NEVER_EXCUSED:
            b = not_installed(clean())
            change(b["items"], "ads-report")
            self.assertRegex(closing_of(b), rf"(?m)^LOOK  {line}{note}$", line)
        for change in (lambda it: job(it, "D10.7", "ads-report").update(broker_journal="could-not-check"),
                       lambda it: job(it, "D10.7", "ads-report").pop("runner_journal"),
                       lambda it: job(it, "D10.7", "ads-report")["runner_journal"].pop("pattern_hits"),
                       lambda it: job(it, "D10.8", "ads-report").pop("out_of_whitelist"),
                       lambda it: job(it, "D10.4", "ads-report").pop("layout_problems")):
            b = not_installed(clean())
            change(b["items"])
            closing = closing_of(b)
            for line in (self.LEAKS, self.UNITS, self.LAYOUT):
                self.assertRegex(closing, rf"(?m)^ok    {line}$", line)
        self.assertIn("    ads-report:\n      declared: true\n      installed: false", text)
        # the installed job is still judged: its own fault is not hidden by the other's state
        b = not_installed(clean())
        job(b["items"], "D10.8")["results"] = []
        self.assertRegex(closing_of(b), rf"(?m)^LOOK  {self.RUN_OK} \(not so for 1 of 1 jobs\)$")
        # and the job that is not installed cannot make a line ok by itself
        b = not_installed(not_installed(clean(), "ads-report"), "ads-audit")
        closing = closing_of(b)
        for line in (self.REFUSALS, self.RUN_OK, self.LEAKS, self.LAYOUT):
            self.assertRegex(closing, rf"(?m)^LOOK  {line} \(no installed job\)$", line)
        self.assertRegex(closing, rf"(?m)^LOOK  {self.JOBS_LINE} \(2 declared but not installed\) \(no installed job\)$")

    def test_an_installed_job_an_item_has_no_entry_for_or_calls_not_installed_is_not_excused(self):
        # D10.3 lists the installed jobs: an item that leaves one out, or says it is not installed, did not check it.
        lines = {"D10.3": (self.JOBS_LINE,), "D10.7": (self.REFUSALS, self.LEAKS, self.REACH), "D10.8": (self.RUN_OK,)}
        for iid, depend in lines.items():
            for change in (lambda it: it[iid]["data"]["apps"].pop("ads-report"),
                           lambda it: job(it, iid, "ads-report").update(installed=False)):
                closing = self._closing(change)
                for line in depend:
                    self.assertEqual(self._status(closing, line)[0], "LOOK", (iid, line))
                self.assertRegex(closing, r"\(not so for 1 of 2 jobs")
        def broker_left_out(it):
            it["D4.6"]["data"]["apps_installed"] = ["ads-audit"]
            for group in ("started_at", "started_after_last_pass", "files_newer_than_start", "files_checked"):
                del it["D4.6"]["data"][group][BROKERS[1]]
        self.assertRegex(self._closing(broker_left_out),
                         rf"(?m)^LOOK  {self.CODE} \(not so for 1 of 4 services: a value could not be checked\)$")

    def test_a_job_only_on_disk_is_said_on_the_jobs_line_and_judged_nowhere_else(self):
        def parked(it):
            it["D10.3"]["data"]["on_disk_apps"].append("parked")
            for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
                it[iid]["data"]["apps"]["parked"] = {"declared": False, "installed": False, "results": "could-not-check",
                                                     "out_of_whitelist": "could-not-check", "journal_counts": {}}
        closing = self._closing(parked)
        self.assertRegex(closing, rf"(?m)^LOOK  {self.JOBS_LINE} \(1 on disk only\)$")
        self.assertRegex(closing, rf"(?m)^LOOK  {self.CNC_LINE} \(8 places\)$")
        self.assertEqual(len(re.findall(r"(?m)^ok    ", closing)), 18)
        for change, line, note in self.NEVER_EXCUSED:        # a count of something bad in it is still said
            def both(it):
                parked(it)
                for iid, fill in (("D10.7", {"broker_journal": {}, "runner_journal": {}}), ("D10.4", {"layout_problems": "could-not-check"})):
                    it[iid]["data"]["apps"]["parked"].update(fill)
                change(it, "parked")
            self.assertRegex(self._closing(both), rf"(?m)^LOOK  {line}{note.replace('of 2', 'of 3')}$", line)

    def test_a_count_in_a_job_that_is_in_no_list_at_all_is_still_said(self):
        for change, line, note in self.NEVER_EXCUSED:
            def stray(it):
                it["D10.7"]["data"]["apps"]["stray"] = {"declared": False, "installed": False, "broker_journal": {}, "runner_journal": {}}
                it["D10.8"]["data"]["apps"]["stray"] = {"declared": False, "installed": False}
                it["D10.4"]["data"]["apps"]["stray"] = {"declared": False, "installed": False}
                change(it, "stray")
            closing = self._closing(stray)
            self.assertRegex(closing, rf"(?m)^LOOK  {line}{note.replace('of 2', 'of 3')}$", line)
            self.assertRegex(closing, rf"(?m)^LOOK  {self.JOBS_LINE} \(1 in no list\)$")
            self.assertNotIn("stray", closing)

    def test_a_job_whose_installed_word_is_not_true_or_false_is_not_excused(self):
        for value in ("could-not-check", None, "false", 0, "no"):
            closing = self._closing(lambda it: job(it, "D10.8", "ads-report").update(installed=value, results="could-not-check"))
            self.assertRegex(closing, rf"(?m)^LOOK  {self.RUN_OK}{self.ONE_UNREAD}$", value)

    def test_an_installed_broker_is_judged_and_one_only_declared_is_not(self):
        def extra(it):                                   # a broker of a job in neither list
            it["D4.6"]["data"]["files_newer_than_start"]["hermes-app-broker@parked"] = []
            it["D4.6"]["data"]["files_checked"]["hermes-app-broker@parked"] = 4
        self.assertRegex(self._closing(extra), rf"(?m)^LOOK  {self.CODE} \(1 broker of a job in no list\)$")
        def undeclared(it):                              # installed without a description file: it runs, so it is judged
            it["D4.6"]["data"]["apps_declared"] = ["ads-audit"]
            it["D4.6"]["data"]["files_newer_than_start"][BROKERS[1]] = ["hermes-app-broker.py"]
        self.assertRegex(self._closing(undeclared), rf"(?m)^LOOK  {self.CODE} \(not so for 1 of 4 services\)$")
        self.assertRegex(self._closing(lambda it: it["D4.6"]["data"].update(apps_declared=["ads-audit"])), rf"(?m)^ok    {self.CODE}$")
        self.assertRegex(self._closing(lambda it: it["D4.6"]["data"].pop("apps_installed")), rf"(?m)^LOOK  {self.CODE} \(older shape\)$")

    def test_every_job_s_folders_are_as_designed_and_no_container_mounts_the_job_state(self):
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.LAYOUT}$")
        d = lambda it: it["D10.4"]["data"]
        cases = (
            (lambda it: job(it, "D10.4", "ads-report").update(layout_problems=["state dir is 0755"]), self.ONE),
            (lambda it: [job(it, "D10.4", a).update(layout_problems=["x", "y"]) for a in JOBS], r" \(not so for 2 of 2 jobs\)"),
            (lambda it: job(it, "D10.4").update(layout_problems="could-not-check", layout_reason="host-layout"), self.ONE_UNREAD),
            (lambda it: job(it, "D10.4").pop("layout_problems"), self.ONE),
            (lambda it: job(it, "D10.4").update(layout_problems=None), self.ONE),
            (lambda it: job(it, "D10.4").update(layout_problems={}), self.ONE),
            (lambda it: d(it)["apps"].pop("ads-report"), self.ONE_UNREAD),                  # an installed job with no entry
            (lambda it: d(it).update(apps="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: d(it).pop("apps"), r" \(older shape\)"),
            (lambda it: it["D10.4"].update(status="could-not-check"), r" \(not read\)"),
            (lambda it: it.pop("D10.4"), r" \(not read\)"),
            (lambda it: d(it).update(containers_mounting_app_state=1), r" \(1 container mounts the job state\)"),
            (lambda it: d(it).update(containers_mounting_app_state=2), r" \(2 containers mount the job state\)"),
            (lambda it: d(it).update(containers_not_inspected=1), r" \(1 container not inspected\)"),
            (lambda it: d(it).update(containers_not_inspected=3), r" \(3 containers not inspected\)"),
            (lambda it: d(it).update(containers_not_inspected="could-not-check"), r" \(containers not inspected: could not be checked\)"),
            (lambda it: d(it).update(containers_mounting_app_state="could-not-check"),
             r" \(containers mount the job state: could not be checked\)"),
            (lambda it: d(it).pop("containers_mounting_app_state"), r" \(containers mount the job state: not read\)"),
            (lambda it: d(it).update(containers_not_inspected=False), r" \(containers not inspected: a value that is not a number\)"),
            (lambda it: [job(it, "D10.4").update(layout_problems=["x"]), d(it).update(containers_mounting_app_state=1)],
             self.ONE + r" \(1 container mounts the job state\)"),
        )
        for change, note in cases:
            closing = self._closing(change)
            self.assertRegex(closing, rf"(?m)^LOOK  {self.LAYOUT}{note}$", note)
            self.assertNotIn("0755", closing)

    def test_the_installed_job_units_equal_the_repository_s_and_every_stored_result_is_in_whitelist(self):
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.UNITS}$")
        units = lambda it: it["D10.3"]["data"]["installed_equal_repo"]
        cases = (
            (lambda it: units(it).update({"hermes-app-broker@.service": False}), r" \(1 unit file differs or was not read\)"),
            (lambda it: [units(it).update({u: False}) for u in APP_UNIT_FILES], r" \(3 unit files differ or were not read\)"),
            (lambda it: units(it).update({"hermes-app-runner@.path": "could-not-check"}), r" \(1 unit file differs or was not read\)"),
            (lambda it: units(it).pop("hermes-app-runner@.service"), r" \(1 unit file differs or was not read\)"),
            (lambda it: units(it).update({"hermes-app-runner@.path": 1}), r" \(1 unit file differs or was not read\)"),
            (lambda it: units(it).update(acmecorp=True), r" \(1 entry that is not a job unit file\)"),
            (lambda it: it["D10.3"]["data"].update(installed_equal_repo="could-not-check"), r" \(3 unit files differ or were not read\)"),
            (lambda it: it["D10.3"]["data"].update(installed_equal_repo={}), r" \(3 unit files differ or were not read\)"),
            (lambda it: it["D10.3"]["data"].pop("installed_equal_repo"), r" \(older shape\)"),
            (lambda it: it.pop("D10.3"), r" \(not read\)( \(not so for 2 of 2 jobs: a value could not be checked\))?"),
            (lambda it: job(it, "D10.8", "ads-report").update(out_of_whitelist=1), self.ONE),
            (lambda it: [job(it, "D10.8", a).update(out_of_whitelist=5) for a in JOBS], r" \(not so for 2 of 2 jobs\)"),
            (lambda it: job(it, "D10.8").update(out_of_whitelist="could-not-check", results="could-not-check"), self.ONE_UNREAD),
            (lambda it: job(it, "D10.8").pop("out_of_whitelist"), self.ONE),
            (lambda it: job(it, "D10.8").update(out_of_whitelist=True), self.ONE),
            (lambda it: job(it, "D10.8").update(out_of_whitelist=-1), self.ONE),
            (lambda it: it["D10.8"]["data"]["apps"].pop("ads-audit"), self.ONE_UNREAD),
            (lambda it: it["D10.8"]["data"].update(apps="could-not-check"), r" \(the jobs could not be checked\)"),
            (lambda it: it["D10.8"]["data"].pop("apps"), r" \(older shape\)"),
            (lambda it: it.pop("D10.8"), r" \(not read\)"),
            (lambda it: [units(it).update({"hermes-app-runner@.path": False}), job(it, "D10.8").update(out_of_whitelist=1)],
             r" \(1 unit file differs or was not read\)" + self.ONE),
        )
        for change, note in cases:
            closing = self._closing(change)
            self.assertRegex(closing, rf"(?m)^LOOK  {self.UNITS}{note}$", note)
            self.assertNotIn("acmecorp", closing)

    def test_the_credential_probe_matches_the_declared_map_and_a_figures_run_starts_no_ai_service(self):
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.PROBE}$")
        d = lambda it: it["D10.1"]["data"]
        figures = lambda value: (lambda it: d(it)["probe"].update(figures_services=value))
        other = r" \(a figures run does not start exactly the collector and the reader\)"
        unread = r" \(the services of a figures run were not read\)"
        cases = (
            (figures(["ads-collector", "ads-drafter", "ads-reader"]), other),
            (figures(["ads-collector", "ads-reader", "egress-proxy"]), other),
            (figures(["ads-collector"]), other),
            (figures([]), other),
            (figures(["ads-collector", "ads-reader", "ads-reader"]), other),
            (figures(["ads-collector", "acmecorp"]), other),
            (figures("could-not-check"), unread),
            (figures(None), unread),
            (figures(["ads-collector", 7]), unread),
            (figures({"ads-collector": 1, "ads-reader": 1}), unread),
            (lambda it: d(it)["probe"].pop("figures_services"), r" \(not in this bundle\)"),
            (lambda it: d(it)["probe"].update(matches_declared=False), r" \(the probe does not match the declared map\)"),
            (lambda it: d(it)["probe"].update(matches_declared="could-not-check"), r" \(the probe does not match the declared map\)"),
            (lambda it: d(it)["probe"].pop("matches_declared"), r" \(the probe does not match the declared map\)"),
            (lambda it: d(it).update(rc=1), r" \(the probe did not end with 0\)"),
            (lambda it: d(it).update(rc=False), r" \(the probe did not end with 0\)"),
            (lambda it: d(it).pop("rc"), r" \(the probe did not end with 0\)"),
            (lambda it: d(it).update(rc=1, probe={"matches_declared": False, "figures_services": ["ads-drafter"]}),
             r" \(the probe did not end with 0\) \(the probe does not match the declared map\)" + other),
            (lambda it: d(it).update(probe="could-not-check"), r" \(the probe was not read\)"),
            (lambda it: d(it).pop("probe"), r" \(the probe was not read\)"),
            (lambda it: it["D10.1"].update(status="could-not-check"), r" \(not read\)"),
            (lambda it: it.pop("D10.1"), r" \(not read\)"),
        )
        for change, note in cases:
            closing = self._closing(change)
            self.assertRegex(closing, rf"(?m)^LOOK  {self.PROBE}{note}$", note)
            self.assertNotIn("acmecorp", closing)
        self.assertRegex(self._closing(figures(["ads-reader", "ads-collector"])), rf"(?m)^ok    {self.PROBE}$")   # the order is not the point

    def test_odd_per_job_shapes_never_raise(self):
        shapes = ("could-not-check", None, 7, [], {}, {"ads-audit": None}, {"ads-audit": "x"}, {"ads-audit": []},
                  {"ads-audit": {"installed": True, "results": 3, "journal_counts": [], "broker_journal": "x",
                                 "journal_read": 5, "oldest_entry_read": [], "layout_problems": 2, "broker_user_groups": {}}},
                  {str(i): {} for i in range(60)})
        for iid in ("D10.3", "D10.4", "D10.7", "D10.8"):
            for shape in shapes:
                b = clean()
                b["items"][iid]["data"]["apps"] = shape
                rc, text = run(json.dumps(b))
                self.assertEqual(rc, 0, (iid, shape))
                self.assertIn("Reminders, not verdicts", text)
        for shape in shapes:
            b = clean()
            b["items"]["D2.4"]["data"]["oldest_entry"]["apps"] = shape
            b["items"]["D4.6"]["data"].update(apps_declared=shape, apps_installed=shape)
            b["items"]["D10.3"]["data"].update(declared_apps=shape, installed_apps=shape, on_disk_apps=shape)
            b["items"]["D7.1"]["data"]["report_archive"] = shape
            b["items"]["D10.1"]["data"]["probe"] = shape
            self.assertEqual(run(json.dumps(b))[0], 0, shape)
            b["items"]["D7.1"]["data"]["report_archive"] = {"parent": shape, "rows": shape, "rows_listed": shape,
                                                            "containers_mounting": shape, "containers_not_inspected": shape}
            self.assertEqual(run(json.dumps(b))[0], 0, shape)
            b["items"]["D7.1"]["data"]["report_archive"] = {"rows": [shape, {"files": shape, "kind": shape}]}
            self.assertEqual(run(json.dumps(b))[0], 0, shape)
        b = clean()
        b["items"]["D10.7"]["data"]["apps"] = {str(i): {} for i in range(60)}
        self.assertIn("  apps: 60 (not listed)", run(json.dumps(b))[1])


class TestReportStore(unittest.TestCase):
    """R-B: the report store holds only owner-only client folders."""
    LINE = "the report store holds only owner-only client folders"

    def _closing(self, change):
        b = clean()
        change(b["items"]["D7.1"]["data"]["report_archive"])
        text = run(json.dumps(b))[1]
        for gone in ("acmecorp", "acme-ops", "jsmith"):
            self.assertNotIn(gone, text)
        return text[text.index("Before the real collection"):]

    def test_a_healthy_store_is_ok_with_its_number_of_folders(self):
        self.assertRegex(closing_of(clean()), rf"(?m)^ok    {self.LINE} \(2 folders\)$")
        self.assertRegex(self._closing(lambda ra: ra.update(rows=[])), rf"(?m)^ok    {self.LINE} \(0 folders\)$")
        self.assertRegex(self._closing(lambda ra: ra["rows"].pop()), rf"(?m)^ok    {self.LINE} \(1 folder\)$")

    def test_every_fault_is_look_with_a_count_and_never_a_name(self):
        row = lambda ra: ra["rows"][0]
        cases = (
            (lambda ra: row(ra).update(kind="symlink", listed=False, mode="0o777"),
             r" \(1 not a folder\) \(1 not listed\) \(1 not root 0700\)"),
            (lambda ra: row(ra).update(kind="file", listed=False), r" \(1 not a folder\) \(1 not listed\)"),
            (lambda ra: row(ra).update(kind="other", listed=False), r" \(1 not a folder\) \(1 not listed\)"),
            (lambda ra: row(ra).update(kind="acmecorp"), r" \(1 not a folder\)"),
            (lambda ra: row(ra).pop("kind"), r" \(1 not a folder\)"),
            (lambda ra: [r.update(status="unregistered") for r in ra["rows"]], r" \(2 not active\)"),
            (lambda ra: row(ra).update(status="retired"), r" \(1 not active\)"),
            (lambda ra: row(ra).update(status="acmecorp"), r" \(1 not active\)"),
            (lambda ra: row(ra).update(listed=False, not_files="could-not-check"),
             r" \(1 not listed\) \(1 holding something that is not a file\)"),
            (lambda ra: row(ra).update(not_files=2), r" \(1 holding something that is not a file\)"),
            (lambda ra: row(ra).update(not_files=False), r" \(1 holding something that is not a file\)"),
            (lambda ra: row(ra).update(mode="0o750"), r" \(1 not root 0700\)"),
            (lambda ra: row(ra).update(mode="0o0700"), r" \(1 not root 0700\)"),
            (lambda ra: row(ra).update(owner="acme-ops"), r" \(1 not root 0700\)"),
            (lambda ra: row(ra).update(owner=0), r" \(1 not root 0700\)"),
            (lambda ra: row(ra).update(files={"root root 0o600": 2, "root root 0o644": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"root root 0o0600": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"jsmith jsmith 0o640": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"jsmith root 0o600": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"root jsmith 0o600": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"root root 0o600": 2, "acme-ops acme-ops 0o600": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files={"x root root 0o600": 1}), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).update(files="could-not-check"), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: row(ra).pop("files"), r" \(1 with a file that is not root root 0600\)"),
            (lambda ra: ra["rows"].append("acmecorp"),
             r" \(1 not a folder\) \(1 not active\) \(1 not listed\) \(1 holding something that is not a file\) "
             r"\(1 not root 0700\) \(1 with a file that is not root root 0600\)"),
            (lambda ra: ra.update(rows_listed=False), r" \(the store was not listed\)"),
            (lambda ra: ra.update(rows_listed="true"), r" \(the store was not listed\)"),
            (lambda ra: ra.pop("rows_listed"), r" \(the store was not listed\)"),
            (lambda ra: ra.update(rows="could-not-check"), r" \(the folders were not read\)"),
            (lambda ra: ra.pop("rows"), r" \(the folders were not read\)"),
            (lambda ra: ra.update(parent="absent", rows=[], rows_listed=False), r" \(the store is not there\) \(the store was not listed\)"),
            (lambda ra: ra.update(parent="symlink"), r" \(the store is a link\)"),
            (lambda ra: ra.update(parent="not-a-directory"), r" \(the store is not a directory\)"),
            (lambda ra: ra.update(parent="acmecorp"), r" \(the store is not a directory\)"),
            (lambda ra: ra.update(parent="could-not-check"), r" \(the store could not be checked\)"),
            (lambda ra: ra.pop("parent"), r" \(the store was not read\)"),
            (lambda ra: ra["parent"].update(mode="0o755"), r" \(the store is not root:root 0700\)"),
            (lambda ra: ra["parent"].update(owner="acme-ops"), r" \(the store is not root:root 0700\)"),
            (lambda ra: ra["parent"].update(group="jsmith"), r" \(the store is not root:root 0700\)"),
            (lambda ra: ra["parent"].pop("mode"), r" \(the store is not root:root 0700\)"),
            (lambda ra: ra.update(containers_mounting=1), r" \(1 container mounts it\)"),
            (lambda ra: ra.update(containers_mounting=2), r" \(2 containers mount it\)"),
            (lambda ra: ra.update(containers_not_inspected=1), r" \(1 container not inspected\)"),
            (lambda ra: ra.update(containers_not_inspected=2), r" \(2 containers not inspected\)"),
            (lambda ra: ra.update(containers_mounting=1, containers_not_inspected=1),
             r" \(1 container mounts it\) \(1 container not inspected\)"),
            (lambda ra: ra.update(containers_mounting="could-not-check", containers_not_inspected="could-not-check"),
             r" \(containers mount it: could not be checked\) \(containers not inspected: could not be checked\)"),
            (lambda ra: ra.update(containers_mounting=False), r" \(containers mount it: a value that is not a number\)"),
            (lambda ra: ra.pop("containers_not_inspected"), r" \(containers not inspected: not read\)"),
            (lambda ra: ra.update(containers_mounting=10 ** 400), r" \(containers mount it: a value that is not a number\)"),
        )
        for change, note in cases:
            self.assertRegex(self._closing(change), rf"(?m)^LOOK  {self.LINE}{note}$", note)

    def test_a_store_that_is_not_in_the_bundle_or_was_not_read_is_look(self):
        def closing(change):
            b = clean()
            change(b["items"])
            return closing_of(b)
        self.assertRegex(closing(lambda it: it["D7.1"]["data"].pop("report_archive")), rf"(?m)^LOOK  {self.LINE} \(not in this bundle\)$")
        for change in (lambda it: it["D7.1"]["data"].update(report_archive="could-not-check"),
                       lambda it: it["D7.1"]["data"].update(report_archive=None),
                       lambda it: it["D7.1"]["data"].update(report_archive=[]),
                       lambda it: it["D7.1"].update(status="could-not-check"), lambda it: it.pop("D7.1")):
            self.assertRegex(closing(change), rf"(?m)^LOOK  {self.LINE} \(not read\)$")
        self.assertRegex(closing(lambda it: it["D7.1"]["data"].update(report_archive={})),
                         rf"(?m)^LOOK  {self.LINE} \(the store was not read\) \(the store was not listed\) "
                         r"\(the folders were not read\) \(containers mount it: not read\) \(containers not inspected: not read\)$")
        for word in ("null", "could-not-check", "<withheld>", "<other>", "symlink"):       # no programmer's word in a note
            for change in (lambda ra: ra.update(parent=None, containers_mounting=None), lambda ra: ra.update(parent="symlink"),
                           lambda ra: ra.update(parent="could-not-check", containers_mounting="could-not-check", containers_not_inspected=[]),
                           lambda ra: ra.update(parent="acmecorp", containers_mounting=10 ** 400)):
                b = clean()
                change(b["items"]["D7.1"]["data"]["report_archive"])
                line = re.search(rf"(?m)^LOOK  {self.LINE}.*$", closing_of(b)).group(0)
                self.assertNotIn(word, line)


if __name__ == "__main__":
    unittest.main()
