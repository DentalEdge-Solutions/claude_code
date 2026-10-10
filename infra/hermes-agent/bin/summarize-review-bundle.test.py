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


def bundle():
    setting = lambda v, f, n: {"value": v, "file": f, "number": n}
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
                                                        "scanned_characters": 23000000, "undecodable_characters": 0,
                                                        "oldest_entry_read": "2026-09-18T15:11:34Z"}},
                "D2.4": {"status": "observed", "data": {
                    "oldest_entry": {"journal": "2026-09-18T15:11:34Z", "broker": "2026-10-05T18:35:47Z", "runner": None},
                    "reach_days": 31,
                    "settings": {"MaxRetentionSec": setting("35day", OURS, 3024000),
                                 "SystemMaxFiles": setting("500", OURS, 500),
                                 "SystemMaxUse": setting("1G", "/etc/systemd/journald.conf", 1 << 30),
                                 "MaxFileSec": setting("1day", "/etc/systemd/journald.conf", 86400),
                                 "Storage": setting(None, None, None)},
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
                    "started_at": {"boot": "2026-10-01T00:00:00Z", "hermes-broker": "2026-10-07T06:45:46Z",
                                   "hermes-docker-proxy": "2026-10-07T06:45:40Z", "hermes-app-broker@ads-audit": "2026-10-07T06:45:50Z"},
                    "started_after_last_pass": {"hermes-broker": False, "hermes-docker-proxy": False, "hermes-app-broker@ads-audit": False},
                    "files_newer_than_start": {"hermes-broker": [], "hermes-docker-proxy": [], "hermes-app-broker@ads-audit": []},
                    "files_checked": {"hermes-broker": 9, "hermes-docker-proxy": 5, "hermes-app-broker@ads-audit": 7}}},
                "D7.1": {"status": "observed", "data": {"records": 412, "vaults": [{"client": "acmecorp"}], "root_backups": []}},
                "D10.7": {"status": "observed", "data": {
                    "journal_counts": {"refused/disabled": 1, "refused/quota": 1, "refused/bad_request": 2, "ok/-": 3},
                    "note_counts": {"warning": 2}, "other_lines": 4, "known_secrets_checked": 7,
                    "broker_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "runner_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "oldest_entry_read": {"broker": "2026-10-05T18:35:47Z", "runner": None}}},
                "D10.8": {"status": "observed", "data": {"out_of_whitelist": 0, "results": [
                    {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
                    {"op": "run", "status": "refused", "reason": "quota", "keys_ok": True, "values_ok": True}]}},
                "D5.3": {"status": "could-not-check", "reason": "OSError: /var/lib/hermes/x: denied"},
                "D99.9": {"status": "observed", "data": {"anything": PLANT}}}}


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
        self.assertEqual(SB.SERVICES, tuple(CE.SERVICE_FILES))
        self.assertEqual(SB.START_KEYS, frozenset(CE.SERVICE_FILES) | {"boot", "docker", "gateway-container"})
        self.assertEqual(SB.JOURNAL_LABELS, frozenset(CE.JOURNAL_UNITS) | {"journal"})
        self.assertEqual(SB.LISTENER_UNITS, frozenset(CE.LISTENER_UNITS))

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
        self.assertRegex(text, r"(?m)^items 13 \| not observed: D5\.3$")
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
                     "files_checked: {hermes-app-broker@ads-audit: 7, hermes-broker: 9, hermes-docker-proxy: 5}",
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
        b["items"]["D10.7"]["data"]["journal_counts"]["ok/acmecorp"] = 3
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
        b["items"]["D10.7"]["data"]["oldest_entry_read"]["zz"] = "2026-10-01T00:00:00Z"
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
        self.assertIn("LOOK  every item observed (13 items) (not observed: D5.3)", closing)
        for ok in ("nothing in the bundle is could-not-check", "the three live refusals are in the journal",
                   "at least one run/ok result", "retention at least 30 days, set by our file",
                   "the journal reaches 30 days", "the running journal service has read its settings",
                   "the proxy matches the last PASS", "no service runs older code", "fingerprint complete",
                   "the journal is being written to disk", "sshd runs with its default settings file and no Match line",
                   "the journal search read everything it was given"):
            self.assertRegex(closing, rf"(?m)^(ok    |LOOK  ){ok}")
        for ok in ("the three live refusals are in the journal", "at least one run/ok result",
                   "retention at least 30 days, set by our file", "the journal reaches 30 days",
                   "the running journal service has read its settings", "the proxy matches the last PASS",
                   "no service runs older code", "fingerprint complete",
                   "the journal is being written to disk", "sshd runs with its default settings file and no Match line",
                   "the journal search read everything it was given"):
            self.assertRegex(closing, rf"(?m)^ok    {ok}")
        self.assertIn("Reminders, not verdicts", closing)
        self.assertEqual(len(re.findall(r"(?m)^(?:ok   |LOOK) ", closing)), 13)

    def test_a_clean_bundle_is_ok_on_all_thirteen(self):
        b = bundle()
        del b["items"]["D5.3"]
        closing = closing_of(b)
        self.assertEqual(len(re.findall(r"(?m)^ok    ", closing)), 13)
        self.assertIn("ok    every item observed (12 items)", closing)

    def test_the_closing_list_has_the_thirteen_lines_in_order(self):
        closing = closing_of(bundle())
        order = ("every item observed", "nothing in the bundle", "sshd runs with", "the three live refusals",
                 "at least one run/ok", "retention at least 30 days", "the journal reaches 30 days",
                 "the journal search read", "the running journal service", "the journal is being written",
                 "the proxy matches", "no service runs older code", "fingerprint complete")
        positions = [closing.index(o) for o in order]
        self.assertEqual(positions, sorted(positions))

    def test_each_closing_line_turns_to_look(self):
        def closing(change):
            b = bundle()
            del b["items"]["D5.3"]                      # so that every case starts from thirteen ok
            change(b["items"])
            return closing_of(b)
        cases = (
            (lambda it: it["D10.7"]["data"]["journal_counts"].pop("refused/quota"), "the three live refusals"),
            (lambda it: it["D10.8"]["data"]["results"].pop(0), "at least one run/ok result"),
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
            (lambda it: it["D10.7"]["data"]["journal_counts"].update({"refused/quota": True}), "the three live refusals"),
            (lambda it: it["D10.7"]["data"].update(journal_counts="x"), "the three live refusals"),
            (lambda it: it["D10.7"].update(status="could-not-check"), "the three live refusals"),
            (lambda it: it.pop("D10.7"), "the three live refusals"),
            (lambda it: it.pop("D10.8"), "at least one run/ok result"),
            (lambda it: it["D10.8"]["data"].update(results={}), "at least one run/ok result"),
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
            del b["items"]["D5.3"]                      # so that every case starts from thirteen ok
            change(b)
            return closing_of(b)
        cases = (
            (lambda b: b["fingerprint"].update(complete=False), "fingerprint complete"),
            (lambda b: b["fingerprint"].update(complete="true"), "fingerprint complete"),
            (lambda b: b["fingerprint"].update(complete=1), "fingerprint complete"),
            (lambda b: b.update(fingerprint=None), "fingerprint complete"),
            (lambda b: b.pop("fingerprint"), "fingerprint complete"),
            (lambda b: b["items"]["D10.8"]["data"].update(results=[{"op": "?", "status": "ok", "keys_ok": True, "values_ok": True}]), "at least one run/ok result"),
            (lambda b: b["items"]["D10.8"]["data"].update(results=[{"op": "run", "status": "ok", "keys_ok": False, "values_ok": True}]), "at least one run/ok result"),
            (lambda b: b["items"]["D10.8"]["data"].update(results=[{"op": "run", "status": "ok", "keys_ok": True, "values_ok": False}]), "at least one run/ok result"),
            (lambda b: b["items"]["D10.8"]["data"].update(results=[{"op": "run", "status": "ok"}]), "at least one run/ok result"),
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

    def test_nothing_could_not_check_counts_the_places(self):
        b = bundle()
        b["items"]["D1.7"]["data"]["files"][0]["keys"] = "could-not-check"
        b["items"]["D1.7"]["data"]["unprivileged_port_start"] = "could-not-check"
        self.assertIn("LOOK  nothing in the bundle is could-not-check (3 places)", closing_of(b))   # D5.3's status is the third

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
        self.assertRegex(text, r"(?m)^LOOK  nothing in the bundle is could-not-check \(1 places\) \(credentials is not a list\)$")
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
                b = bundle()
                del b["items"]["D5.3"]
                change(b["items"]["D10.7"]["data"]["journal_counts"])
                self.assertRegex(closing_of(b), rf"(?m)^LOOK  the three live refusals are in the journal \(missing: {key}\)", key)

    def test_journal_counts_need_both_parts_in_the_label_sets(self):
        b = bundle()
        counts = b["items"]["D10.7"]["data"]["journal_counts"]
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
        self.assertRegex(text, r"(?m)^items 13 \| not observed: 1 other$")
        self.assertIn("LOOK  every item observed (13 items) (not observed: 1 other)", text)
        self.assertNotIn("acmecorp", text)
        b["items"]["D5.3"] = {"status": "could-not-check"}
        self.assertRegex(run(json.dumps(b))[1], r"(?m)^items 14 \| not observed: D5\.3, 1 other$")

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


if __name__ == "__main__":
    unittest.main()
