#!/usr/bin/env python3
import importlib.util, io, json, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("summarize_review_bundle", os.path.join(HERE, "summarize-review-bundle.py"))
SB = importlib.util.module_from_spec(spec); spec.loader.exec_module(SB)

OURS = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
PLANT = "sk-or-v1-" + "0123456789abcdef" * 4


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
                    "files": [{"path": "/home/hermesops/.ssh/authorized_keys", "users": ["hermesops"], "kind": "file",
                               "owner": "hermesops", "group": "hermesops", "mode": "0o600", "unparsed_lines": 0,
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
                "D4.2": {"status": "observed", "data": {"active": "active", "matches_last_pass": True,
                                                        "drop_in_paths": [], "execstart_sha256": "cd" * 32}},
                "D4.6": {"status": "observed", "data": {
                    "last_pass_collected_at": "2026-10-09T14:01:23Z", "started_at": {"hermes-broker": "2026-10-07T06:45:46Z"},
                    "started_after_last_pass": {"hermes-broker": False},
                    "files_newer_than_start": {"hermes-broker": []}, "files_checked": {"hermes-broker": 9}}},
                "D10.7": {"status": "observed", "data": {
                    "journal_counts": {"refused/disabled": 1, "refused/quota": 1, "refused/bad_request": 2, "ok/-": 3},
                    "note_counts": {}, "other_lines": 4, "known_secrets_checked": 7,
                    "broker_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "runner_journal": {"credential_text_lines": 0, "customer_id_lines": 0, "pattern_hits": 0, "known_secret_hits": 0},
                    "oldest_entry_read": {"broker": "2026-10-05T18:35:47Z", "runner": None}}},
                "D10.8": {"status": "observed", "data": {"out_of_whitelist": 0, "results": [
                    {"op": "run", "status": "ok", "reason": "-", "keys_ok": True, "values_ok": True},
                    {"op": "run", "status": "refused", "reason": "quota", "keys_ok": True, "values_ok": True}]}},
                "D5.3": {"status": "could-not-check", "reason": "OSError: /var/lib/hermes/x: denied"},
                "D99.9": {"status": "observed", "data": {"anything": PLANT}}}}


def planted(value):
    """The same structure with every string leaf (and every dict key that is not an item id or a
    top-level bundle key) replaced by a secret-shaped value."""
    if isinstance(value, str):
        return PLANT
    if isinstance(value, list):
        return [planted(v) for v in value] or [PLANT]
    if isinstance(value, dict):
        return {k: planted(v) for k, v in value.items()}
    return value


def run(text):
    out = io.StringIO()
    rc = SB.main([], stdin=io.StringIO(text), out=out)
    return rc, out.getvalue()


class TestSummary(unittest.TestCase):
    def test_every_item_is_listed_with_its_status_known_to_the_tool_or_not(self):
        rc, text = run(json.dumps(bundle()))
        self.assertEqual(rc, 0)
        for iid in bundle()["items"]:
            self.assertRegex(text, rf"(?m)^{iid} +(observed|could-not-check)\b")
        self.assertRegex(text, r"(?m)^items 10 \| not observed: D5\.3$")
        self.assertNotIn("anything", text)                       # an unknown item: its status alone
        self.assertNotIn("denied", text)                         # a reason is free text

    def test_counts_booleans_words_and_times_are_printed(self):
        text = run(json.dumps(bundle()))[1]
        for want in ("match_lines: 0", "reach_days: 31", "scanned_characters: 23000000",
                     "oldest_entry_read: 2026-09-18T15:11:34Z", "MaxRetentionSec: {file: <withheld>, number: 3024000, value: 35day}",
                     "refused/bad_request: 2", "matches_last_pass: true", "run/ok results: 1",
                     "keys: 2 (ssh-ed25519 options=0, ssh-ed25519 options=5 limited_to_the_forward=true)",
                     "daemon_options: {config_file_options: 0, listeners: 1, setting_options: 0}",
                     "undecodable_characters: 0", "flushed_to_disk: true", "active: true", "Storage: {file: null, number: null, value: null}"):
            self.assertIn(want, text)

    def test_no_path_no_fingerprint_and_no_option_value_is_printed(self):
        text = run(json.dumps(bundle()))[1]
        for gone in ("/etc/", "/home/", "/bin/false", "0123456789ab", "aaaaaaaaaaaa", "abab", "cdcd", "127.0.0.1", "0.0.0.0"):
            self.assertNotIn(gone, text, gone)

    def test_a_secret_planted_in_every_field_is_never_printed(self):
        b = bundle()
        b["items"] = {iid: planted(item) for iid, item in b["items"].items()}
        b["credentials"], b["fingerprint"], b["collected_at"] = planted(b["credentials"]), planted(b["fingerprint"]), PLANT
        rc, text = run(json.dumps(b))
        self.assertEqual(rc, 0)
        self.assertNotIn("sk-or", text)
        self.assertNotIn("0123456789abcdef", text)

    def test_the_closing_list_says_what_to_look_at_before_the_real_collection(self):
        text = run(json.dumps(bundle()))[1]
        closing = text[text.index("Before the real collection"):]
        self.assertIn("LOOK  every item observed (not observed: D5.3)", closing)
        for ok in ("the three live refusals are in the journal", "at least one run/ok result",
                   "retention at least 30 days, set by our file", "the journal reaches 30 days",
                   "the running journal service has read its settings", "the proxy matches the last PASS",
                   "no service runs older code", "fingerprint complete",
                   "the journal is being written to disk", "sshd runs with its default settings file and no Match line",
                   "the journal search read everything it was given"):
            self.assertRegex(closing, rf"(?m)^ok    {ok}")
        self.assertIn("Reminders, not verdicts", closing)
        self.assertEqual(len(re.findall(r"(?m)^(?:ok   |LOOK) ", closing)), 12)

    def test_the_closing_list_has_the_twelve_lines_in_order(self):
        text = run(json.dumps(bundle()))[1]
        closing = text[text.index("Before the real collection"):]
        order = ("every item observed", "sshd runs with", "the three live refusals", "at least one run/ok",
                 "retention at least 30 days", "the journal reaches 30 days", "the journal search read",
                 "the running journal service", "the journal is being written", "the proxy matches",
                 "no service runs older code", "fingerprint complete")
        positions = [closing.index(o) for o in order]
        self.assertEqual(positions, sorted(positions))

    def test_each_closing_line_turns_to_look(self):
        def closing(change):
            b = bundle()
            change(b["items"])
            text = run(json.dumps(b))[1]
            return text[text.index("Before the real collection"):]
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

    def test_every_item_observed_is_look_for_an_empty_item_list_and_a_non_string_status(self):
        for items in ({}, {"D1.1": {"status": 7}}, {"D1.1": {}}):
            b = bundle()
            b["items"] = items
            text = run(json.dumps(b))[1]
            self.assertRegex(text[text.index("Before the real collection"):], r"(?m)^LOOK  every item observed")

    def test_the_storage_word_is_printed_through_word_and_nothing_else_of_it(self):
        def look(value):
            b = bundle()
            b["items"]["D2.4"]["data"]["settings"]["Storage"] = {"value": value, "file": "/etc/x.conf", "number": None}
            text = run(json.dumps(b))[1]
            return text[text.index("Before the real collection"):]
        self.assertIn("(Storage is volatile)", look("volatile"))
        self.assertIn("(Storage is <withheld>)", look(PLANT))
        self.assertNotIn("sk-or", look(PLANT))
        for ok in (None, "auto", "persistent"):
            self.assertRegex(look(ok), r"(?m)^ok    retention at least 30 days")

    def test_not_a_bundle_is_one_line_and_exit_2(self):
        for text in ("", "collect-review-evidence: refused\n", "[]", '{"kind": "laptop", "items": {}}',
                     '{"kind": "box"}', '{"kind": "box", "items": []}'):
            rc, out = run(text)
            self.assertEqual((rc, out.count("\n")), (2, 1), text)
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
        b["fingerprint"] = None
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
