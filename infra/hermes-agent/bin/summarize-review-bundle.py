#!/usr/bin/env python3
"""Print a summary of a box review bundle that is safe to paste: every item with its status,
and, for the items this tool knows, counts, booleans, times and short words only.

    sudo python3 collect-review-evidence.py --fp-key-tty | python3 summarize-review-bundle.py
    python3 summarize-review-bundle.py bundle-box.json

It is for the TRIAL collection (a throwaway key): it shows whether every item was observed and
what to look at before the real collection. It judges nothing: the reviewer does. Anything that
is not a number, a boolean, a UTC time or a short word prints as <withheld>: a path, a
fingerprint, an option value, free text. An item this tool does not know prints its status alone.
"""
import json
import re
import sys

WITHHELD = "<withheld>"
MAX_ENTRIES = 40
OUR_FILE = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"
THIRTY_DAYS = 30 * 86400
LIMITED_OPTIONS = ['command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                   "port-forwarding", "restrict"]
DEFAULT_DAEMON = {"listeners": 1, "config_file_options": 0, "setting_options": 0}
REFUSALS = ("refused/disabled", "refused/quota", "refused/bad_request")
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_WORD_RE = re.compile(r"[A-Za-z0-9?-][A-Za-z0-9_@.+-]{0,31}(/[A-Za-z0-9_?.-]{1,24})?")
_HEX_RUN_RE = re.compile(r"[0-9A-Fa-f]{8,}")

# The fields printed for each item this tool knows, by their names in the item's data.
FIELDS = {
    "D1.7": ("accounts_checked", "unprivileged_port_start", "match_lines", "include_elsewhere", "daemon_options",
             "sshd"),
    "D2.3": ("journal", "scanned_characters", "undecodable_characters", "oldest_entry_read"),
    "D2.4": ("oldest_entry", "reach_days", "settings", "drop_in", "service", "usage"),
    "D4.1": ("listeners", "docker_dns_listeners", "secret_env"),
    "D4.2": ("active", "matches_last_pass"),
    "D4.5": ("timer_active", "timer_enabled", "installed_equal_repo", "last_age_seconds", "alert_present",
             "history_counts", "alert_log"),
    "D4.6": ("last_pass_collected_at", "started_at", "started_after_last_pass", "files_newer_than_start",
             "files_checked"),
    "D7.1": ("records",),
    "D10.7": ("journal_counts", "note_counts", "other_lines", "broker_journal", "runner_journal",
              "known_secrets_checked", "oldest_entry_read"),
    "D10.8": ("out_of_whitelist",),
}


def word(text):
    if not isinstance(text, str):
        return WITHHELD
    if _TIME_RE.fullmatch(text):
        return text
    return text if _WORD_RE.fullmatch(text) and not _HEX_RUN_RE.search(text) else WITHHELD


def show(value, depth=0):
    """A value as text, by the rule in the module's first lines."""
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return word(value)
    if depth >= 4 or not isinstance(value, (list, dict)):
        return WITHHELD
    if len(value) > MAX_ENTRIES:
        return f"<{len(value)} entries>"
    if isinstance(value, list):
        return "[" + ", ".join(show(v, depth + 1) for v in value) + "]"
    pairs = sorted(((word(k), v) for k, v in value.items()), key=lambda kv: kv[0])
    return "{" + ", ".join(f"{k}: {show(v, depth + 1)}" for k, v in pairs) + "}"


def _data(items, iid):
    """The item's data when the item was observed; {} for anything else (a missing item, could-not-check)."""
    item = items.get(iid)
    if not isinstance(item, dict) or item.get("status") != "observed":
        return {}
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _int(value):
    """An integer that is not a boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is(value, n):
    """Exactly the integer n: not True for 1, not 0.0 for 0, not a string."""
    return _int(value) and value == n


def _get(value, *path):
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _keys_line(data):
    lines = []
    for row in data.get("files") if isinstance(data.get("files"), list) else []:
        if not isinstance(row, dict):
            continue
        head = "  file: " + ", ".join(f"{k}: {show(row.get(k))}" for k in ("users", "kind", "owner", "group", "mode", "unparsed_lines"))
        keys = row.get("keys")
        if not isinstance(keys, list):
            lines += [head, f"  keys: {show(keys)}"]
            continue
        parts = []
        for key in keys:
            opts = key.get("options") if isinstance(key, dict) else None
            n = len(opts) if isinstance(opts, list) else "?"
            limited = " limited_to_the_forward=true" if opts == LIMITED_OPTIONS else ""
            parts.append(f"{show(key.get('type') if isinstance(key, dict) else None)} options={n}{limited}")
        lines += [head, f"  keys: {len(keys)} ({', '.join(parts)})"]
    return lines


def _run_ok(data):
    rows = data.get("results")
    if not isinstance(rows, list):
        return None
    return sum(1 for r in rows if isinstance(r, dict) and r.get("op") == "run" and r.get("status") == "ok")


def _checks(bundle, items, not_observed):
    """(ok, text) pairs: what to look at before the real collection. Reminders, not verdicts."""
    d24, d107 = _data(items, "D2.4"), _data(items, "D10.7")
    counts = d107.get("journal_counts") if isinstance(d107.get("journal_counts"), dict) else {}
    missing = [k for k in REFUSALS if not (_int(counts.get(k)) and counts.get(k) > 0)]
    run_ok = _run_ok(_data(items, "D10.8"))
    retention = _get(d24, "settings", "MaxRetentionSec")
    retention = retention if isinstance(retention, dict) else {}
    number = retention.get("number")
    storage = _get(d24, "settings", "Storage")
    storage_ok = isinstance(storage, dict) and "value" in storage and storage["value"] in (None, "auto", "persistent")
    setting_ok = (_int(number) and number >= THIRTY_DAYS and retention.get("file") == OUR_FILE
                  and _get(d24, "drop_in", "equals_repo") is True and _get(d24, "drop_in", "other_files") == []
                  and storage_ok)
    storage_note = ""
    if not storage_ok:
        storage_note = f" (Storage is {word(storage['value'])})" if isinstance(storage, dict) and "value" in storage else " (Storage not read)"
    reach = d24.get("reach_days")
    reach_ok = _int(reach) and reach >= 30
    reach_note = ""
    if not reach_ok:
        reach_note = (f" (reach is {reach} days: the evidence needs the date the retention was raised)"
                      if _int(reach) else " (not read)")
    usage = d24.get("usage") if isinstance(d24.get("usage"), dict) else {}
    age = usage.get("on_disk_age_seconds")
    disk_ok = usage.get("flushed_to_disk") is True and _int(age) and 0 <= age <= 600
    service_ok = _get(d24, "service", "active") is True and _get(d24, "service", "config_changed_after_start") is False
    d17, d23 = _data(items, "D1.7"), _data(items, "D2.3")
    daemon = d17.get("daemon_options")
    sshd_ok = (_is(d17.get("match_lines"), 0) and _is(d17.get("include_elsewhere"), 0) and isinstance(daemon, dict)
               and set(daemon) == set(DEFAULT_DAEMON) and all(_is(daemon[k], n) for k, n in DEFAULT_DAEMON.items()))
    scanned = d23.get("scanned_characters")
    oldest_read = d23.get("oldest_entry_read")
    search_ok = (_int(scanned) and scanned > 0 and _is(d23.get("undecodable_characters"), 0)
                 and isinstance(oldest_read, str) and bool(_TIME_RE.fullmatch(oldest_read)))
    newer = _get(_data(items, "D4.6"), "files_newer_than_start")
    code_ok = isinstance(newer, dict) and bool(newer) and all(v == [] for v in newer.values())
    return [
        (bool(items) and not not_observed, "every item observed" + (f" (not observed: {', '.join(not_observed)})" if not_observed else "")),
        (sshd_ok, "sshd runs with its default settings file and no Match line"),
        (not missing, "the three live refusals are in the journal" + (f" (missing: {', '.join(missing)})" if missing else "")),
        (isinstance(run_ok, int) and run_ok > 0, "at least one run/ok result"),
        (setting_ok, "retention at least 30 days, set by our file, the file equal to the repository's, no other file"
                     + storage_note),
        (reach_ok, "the journal reaches 30 days" + reach_note),
        (search_ok, "the journal search read everything it was given"),
        (service_ok, "the running journal service has read its settings"),
        (disk_ok, "the journal is being written to disk"),
        (_get(_data(items, "D4.2"), "matches_last_pass") is True, "the proxy matches the last PASS"),
        (code_ok, "no service runs older code than the box holds"),
        (_get(bundle, "fingerprint", "complete") is True, "fingerprint complete"),
    ]


def summary(bundle):
    items = bundle["items"]
    ids = sorted(items, key=lambda i: [int(n) if n.isdigit() else n for n in re.findall(r"[0-9]+|[^0-9]+", str(i))])
    status = {i: word(items[i].get("status")) if isinstance(items[i], dict) else WITHHELD for i in ids}
    not_observed = [word(i) for i in ids if status[i] != "observed"]
    lines = [f"collected_at {show(bundle.get('collected_at'))}",
             f"items {len(ids)} | not observed: {', '.join(not_observed) or 'none'}", ""]
    for iid in ids:
        lines.append(f"{word(iid)}  {status[iid]}")
        data = _data(items, iid)
        for field in FIELDS.get(iid, ()):
            if field in data:
                lines.append(f"  {field}: {show(data[field])}")
        if iid == "D1.7":
            lines += _keys_line(data)
        if iid == "D10.8":
            lines.append(f"  run/ok results: {show(_run_ok(data))}")
    creds = bundle.get("credentials")
    lines += ["", f"credentials: {len(creds) if isinstance(creds, list) else show(creds)}", "",
              "Before the real collection (ok = as expected, LOOK = look at it first):"]
    lines += [f"{'ok  ' if ok else 'LOOK'}  {text}" for ok, text in _checks(bundle, items, not_observed)]
    lines.append("Reminders, not verdicts: the reviewer judges the real bundle against the checklist.")
    return lines


def main(argv=None, stdin=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    out = out or sys.stdout
    try:
        if argv:
            with open(argv[0], encoding="utf-8") as f:
                bundle = json.load(f)
        else:
            bundle = json.load(stdin or sys.stdin)
        if not (isinstance(bundle, dict) and bundle.get("kind") == "box" and isinstance(bundle.get("items"), dict)):
            raise ValueError("not a box bundle")
    except (OSError, ValueError):
        print("summarize-review-bundle: not a box bundle (did the collector stop? read its own message and its rc)", file=out)
        return 2
    print("\n".join(summary(bundle)), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
