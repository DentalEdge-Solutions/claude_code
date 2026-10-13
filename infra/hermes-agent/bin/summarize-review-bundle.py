#!/usr/bin/env python3
"""Print a summary of a box review bundle that is safe to paste: every item with its status and,
for the items this tool knows, a fixed set of fields.

    sudo python3 collect-review-evidence.py --fp-key-tty | python3 summarize-review-bundle.py
    python3 summarize-review-bundle.py bundle-box.json

It is for the TRIAL collection (a throwaway key): it shows whether every item was observed and
what to look at before the real collection. It judges nothing: the reviewer does.

THE PRINT RULE. A string from the bundle is never printed because of what it looks like. The
tool prints only: true, false, null; an integer of at most 15 digits; a finite float rounded to
one decimal; a UTC time that is a real date; a string that is a member of the closed set declared
for that exact field (any other string prints as <other>); a dict key that is a member of the
closed key set declared for that dict (the others are only counted: "+N other keys"); and its own
fixed words. Everything else prints as <withheld>. An account name, a path, a fingerprint, an
option value, a reason and every unknown item or key are therefore never printed. The sets copied
from the collector are checked against it by the test suite.

ONE NAME IS PRINTED THAT IS NOT IN A SET OF THIS FILE: a job's name, where the bundle keys a
job's values by it (an `apps` dict, and the `hermes-app-broker@<job>` keys of D4.6), and only when
it is BOTH one of D10.3's `declared_apps` (the names of the repository's own description files)
AND of the form the collector calls a job name (`[a-z][a-z0-9-]{0,31}`). A client's name has that
form too, so the form alone prints nothing: a job that is installed or on disk without being
declared shows as <withheld>, and the closing list counts it. A LIST of job names is printed as
its length.

THE JOBS. The box runs several chat-triggered jobs; the collector finds them itself and reports
six items per job. A closing line that reads such an item is `ok` only when it holds for EVERY
installed job, and a value of an installed job that is could-not-check makes the line LOOK. A job
that is declared and not installed yet is said once, on its own line: what could not be checked
for it is expected, but a COUNT of something bad in its entry (a leak count, a result out of
whitelist, a layout problem) is said like any other job's.

THE NOTES of the closing list are for an operator who is not a programmer: plain words, counts,
never a word of the bundle.
"""
import datetime
import json
import math
import re
import sys

CNC = "could-not-check"
WITHHELD, OTHER = "<withheld>", "<other>"
MAX_DIGITS = 15
MAX_LISTED = 40                 # more list entries than this print as a count
MAX_WALK_DEPTH = 16             # the could-not-check walk: deeper than this counts as one place
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_MODE_RE = re.compile(r"0o[0-7]{3,4}")
_ID_RE = re.compile(r"D([0-9]{1,2})\.([0-9]{1,2})")

# ---- closed sets copied from collect-review-evidence.py (tests compare them with it) ----
OUR_FILE = "/etc/systemd/journald.conf.d/50-hermes-retention.conf"      # JOURNALD_DROP_IN
SETTING_NAMES = frozenset({"MaxRetentionSec", "SystemMaxUse", "SystemMaxFiles", "MaxFileSec", "Storage"})
SERVICES = ("hermes-docker-proxy", "hermes-broker")                                    # SERVICE_FILES: the two fixed ones
START_KEYS = frozenset(SERVICES) | {"boot", "docker", "systemd-journald", "gateway-container"}     # + OTHER_STARTS
BROKER_PREFIX = "hermes-app-broker@"                                                    # _app_broker_unit(app)
_APP_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")                                           # app_lib.APP_RE
UNIT_LABELS = ("broker", "runner")                                                      # _journal_units(app)
APP_UNITS = frozenset({"hermes-app-broker@.service", "hermes-app-runner@.service", "hermes-app-runner@.path"})
LAYOUT_REASONS = frozenset({"no-account", "host-layout", "other"})
LISTENER_UNITS = frozenset({"hermes-listener-check.service", "hermes-listener-check.timer"})
SECRET_LABELS = frozenset({"openrouter-key", "dashboard-password", "dashboard-password-hash",
                           "dashboard-session-secret"})
SECRET_STATES = frozenset({"matches-file", "differs-from-file", "unset"})
JOURNAL_STATUSES = frozenset({"ok", "refused", "failed", "busy", "queued", "dropped", "-", "?"})
JOURNAL_REASONS = frozenset({"bad_request", "duplicate", "inactive_client", "quota", "disabled", "timeout",
                             "interrupted", "internal", "precheck", "busy", "collect", "snapshot", "read",
                             "proxy", "draft", "isolation", "vault-write", "store", "expired", "-", "?"})
NOTE_WORDS = frozenset({"warning", "error"})
HISTORY_STATUSES = frozenset({"ok", "alert", CNC, "?"})                                  # check-gateway-listeners.py
ALERT_LOG_KEYS = frozenset({"alert", "alert-cleared", "?", "first_ts", "last_ts"})
FILE_KINDS = frozenset({"file", "symlink", "not-a-file"})
_KEY_BASES = ("ssh-rsa", "ssh-dss", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
              "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")
KEY_TYPES = frozenset(_KEY_BASES) | {b + "-cert-v01@openssh.com" for b in _KEY_BASES}    # as _KEY_TYPE_RE reads them
_READ_KEYS = ("entries", "fields", "undecodable_characters")                             # READ_COUNTS
# ---- words the collector writes without declaring a set (pinned by the tests) ----
DIR_ABSENT, DIR_LINK, DIR_NOT_A_DIRECTORY = "absent", "symlink", "not-a-directory"      # _dir_row: not a real directory
DIR_WORDS = frozenset({DIR_ABSENT, DIR_LINK, DIR_NOT_A_DIRECTORY})
ROW_DIR, ROW_ACTIVE = "dir", "active"                                                    # _archive_row: kind, status
ROW_KEYS = frozenset({"status", "owner", "mode", "kind", "files", "not_files", "files_not_read", "listed"})   # _archive_row
STORE_KEYS = frozenset({"parent", "rows", "rows_listed", "rows_not_read", "containers_mounting",
                        "containers_not_inspected"})                                     # _report_archive
STORE_FILE = "root root 0o600"                                                           # _archive_row: "owner group mode"
PROBE_SERVICES = frozenset({"ads-collector", "ads-reader", "ads-drafter", "egress-proxy"})   # run-client-audit's DECLARED
FIGURES_SERVICES = ("ads-collector", "ads-reader")      # of those, the ones that hold the Google Ads credential and no AI key
# ---- closed sets the collector does not declare (systemctl(1)'s own words, and the expected values) ----
ACTIVE_STATES = frozenset({"active", "inactive", "failed", "activating", "deactivating", "reloading",
                           "maintenance", "refreshing"})
# systemctl(1), `is-enabled`: its table of printed states, and "not-found" for a unit that does not exist.
ENABLED_STATES = frozenset({"not-found", "enabled", "enabled-runtime", "linked", "linked-runtime", "masked", "masked-runtime",
                            "static", "indirect", "disabled", "generated", "transient", "alias", "bad"})
SETTING_VALUES = frozenset({"35day", "7day", "1day", "1G", "500", "persistent", "auto", "volatile", "none"})
STORAGE_OK = (None, "auto", "persistent")

THIRTY_DAYS = 30 * 86400
LIMITED_OPTIONS = ['command="/bin/false"', 'permitlisten="127.0.0.1:1"', 'permitopen="127.0.0.1:9119"',
                   "port-forwarding", "restrict"]
REFUSALS = ("refused/disabled", "refused/quota", "refused/bad_request")
SEARCH_KEYS = ("pattern_hits", "known_secret_hits")                         # D2.3 `journal`, and D2.2's _count_cred_text
LEAK_KEYS = ("credential_text_lines", "customer_id_lines") + SEARCH_KEYS    # LEAK_COUNTS: D10.7's two journals
DEFAULT_DAEMON = {"listeners": 1, "config_file_options": 0, "setting_options": 0}
# Why a closing line could not judge the jobs, in the tool's own words.
NOT_READ, OLDER_SHAPE = " (not read)", " (older shape)"
JOBS_NOT_READ, NO_INSTALLED_JOB = " (the jobs could not be checked)", " (no installed job)"


# ------------------------------------------------------------------ the print rule
def _word(v):
    """The two words every field may print besides its own kind: null and could-not-check."""
    if v is None:
        return "null"
    return CNC if isinstance(v, str) and v == CNC else None


def is_time(v):
    if not (isinstance(v, str) and _TIME_RE.fullmatch(v)):
        return False
    try:
        datetime.datetime.strptime(v, TIME_FORMAT)
    except ValueError:
        return False
    return True


def num(v):
    if _word(v):
        return _word(v)
    if isinstance(v, bool):
        return WITHHELD
    if isinstance(v, int):
        return str(v) if len(str(abs(v))) <= MAX_DIGITS else WITHHELD
    if isinstance(v, float) and math.isfinite(v) and abs(v) < 10 ** MAX_DIGITS:
        return f"{v:.1f}"
    return WITHHELD


def flag(v):
    return _word(v) or ("true" if v is True else "false" if v is False else WITHHELD)


def when(v):
    return _word(v) or (v if is_time(v) else WITHHELD)


def count(v):
    return _word(v) or (str(len(v)) if isinstance(v, (list, dict)) else WITHHELD)


def _files_not_read(rows):
    """The entries inside the store's folders that could not be examined, over every row: a
    number, or None when a row does not hold a count that can be added."""
    if not isinstance(rows, list):
        return None
    counts = [r.get("files_not_read") if isinstance(r, dict) else None for r in rows]
    if not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c < 10 ** MAX_DIGITS for c in counts):
        return None
    return sum(counts)


def files_not_read(v):
    total = _files_not_read(v)
    return _word(v) or (num(total) if total is not None else WITHHELD)


def member(allowed):
    def fmt(v):
        if _word(v):
            return _word(v)
        return (v if v in allowed else OTHER) if isinstance(v, str) else WITHHELD
    return fmt


def mode(v):
    return _word(v) or ((v if _MODE_RE.fullmatch(v) else OTHER) if isinstance(v, str) else WITHHELD)


def is_root(v):
    return _word(v) or (("true" if v == "root" else "false") if isinstance(v, str) else WITHHELD)


def set_by(v):
    """Whose file set a journald setting; the path itself is never printed."""
    if v is None:
        return "none"
    if isinstance(v, str):
        return CNC if v == CNC else "ours" if v == OUR_FILE else "other"
    return WITHHELD


def _fields(v, spec):
    """([(name, text)], other_key_count) for a dict read by `spec`: {name: formatter} or
    {name: (source_key, formatter)}; a formatter of None is a known field that is never printed."""
    pairs, known = [], set()
    for name, entry in spec.items():
        src, fmt = entry if isinstance(entry, tuple) else (name, entry)
        known.add(src)
        if fmt is not None and src in v:
            pairs.append((name, fmt(v[src])))
    return pairs, sum(1 for k in v if k not in known)


def _braced(pairs, other):
    parts = [f"{k}: {t}" for k, t in pairs] + ([f"+{other} other keys"] if other else [])
    return "{" + ", ".join(parts) + "}"


def fixed(spec):
    def fmt(v):
        if _word(v):
            return _word(v)
        return _braced(*_fields(v, spec)) if isinstance(v, dict) else WITHHELD
    return fmt


def keyed(keys, inner):
    """A dict whose keys come from a closed set: those are printed, the others counted."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        return _braced([(k, inner(v[k])) for k in sorted(v) if k in keys], sum(1 for k in v if k not in keys))
    return fmt


def is_app(name):
    return isinstance(name, str) and _APP_RE.fullmatch(name) is not None


def is_service(key):
    """A fixed service, or the broker of a job whose name has the form of one."""
    return key in SERVICES or (key.startswith(BROKER_PREFIX) and is_app(key[len(BROKER_PREFIX):]))


def _app_name(name, shown):
    """A job's name when it is one of the declared jobs `shown`; anything else is never printed."""
    return name if name in shown else WITHHELD


def _by_name(apps, shown):
    """The jobs in the order they are shown: the declared ones first, by name."""
    return sorted(apps, key=lambda k: (k not in shown, k))


def apps_inline(inner, shown):
    """{job: value} on one line: every job is there, under its name or as <withheld>."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        if len(v) > MAX_LISTED:
            return f"{len(v)} (not listed)"
        return _braced([(_app_name(k, shown), inner(v[k])) for k in _by_name(v, shown)], 0)
    return fmt


def per_app(spec, shown):
    """{job: {field: value}}: the number of jobs, then each job's name on its own line with its
    fields under it, read by `spec` as `fixed` reads them."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        if len(v) > MAX_LISTED:
            return f"{len(v)} (not listed)"
        out = [str(len(v))]
        for app in _by_name(v, shown):
            entry = v[app]
            if not isinstance(entry, dict):
                out.append(f"    {_app_name(app, shown)}: {_word(entry) or WITHHELD}")
                continue
            pairs, other = _fields(entry, spec)
            out.append(f"    {_app_name(app, shown)}:")
            out += [f"      {name}: {text}" for name, text in pairs]
            if other:
                out.append(f"      +{other} other keys")
        return "\n".join(out)
    return fmt


def by_service(inner, shown, also=()):
    """A dict keyed by service: the fixed services and the keys of `also` under their names, a
    job's broker under its name when the job is one of `shown` and as `hermes-app-broker@<withheld>`
    when it is not; every other key is counted."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        if len(v) > MAX_LISTED:
            return f"{len(v)} (not listed)"
        rows, other = [], 0
        for k in sorted(v):
            if k in SERVICES or k in also:
                rows.append((k, inner(v[k])))
            elif k.startswith(BROKER_PREFIX):
                rows.append((BROKER_PREFIX + _app_name(k[len(BROKER_PREFIX):], shown), inner(v[k])))
            else:
                other += 1
        return _braced(rows, other)
    return fmt


def listed(allowed):
    """A list of words from a closed set, each printed by `member`."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, list):
            return WITHHELD
        if len(v) > MAX_LISTED:
            return f"{len(v)} (not listed)"
        return "[" + ", ".join(member(allowed)(x) for x in v) + "]"
    return fmt


def journal_counts(v):
    """Keys are `status/reason`; one is printed only when BOTH parts are in the collector's label sets."""
    if _word(v):
        return _word(v)
    if not isinstance(v, dict):
        return WITHHELD
    shown = [k for k in sorted(v) if isinstance(k, str) and k.partition("/")[0] in JOURNAL_STATUSES
             and k.partition("/")[2] in JOURNAL_REASONS]
    return _braced([(k, num(v[k])) for k in shown], len(v) - len(shown))


def key_list(v):
    if _word(v):
        return _word(v)
    if not isinstance(v, list):
        return WITHHELD
    if len(v) > MAX_LISTED:
        return f"{len(v)} (not listed)"
    parts = []
    for key in v:
        if not isinstance(key, dict):
            parts.append(WITHHELD)
            continue
        opts = key.get("options")
        limited = " limited_to_the_forward=true" if opts == LIMITED_OPTIONS else ""
        parts.append(f"{member(KEY_TYPES)(key.get('type'))} options={len(opts) if isinstance(opts, list) else '?'}{limited}")
    return f"{len(v)} ({', '.join(parts)})"


_KEY_FILE = fixed({"path": None, "users": count, "kind": member(FILE_KINDS), "owner_is_root": ("owner", is_root),
                   "group_is_root": ("group", is_root), "mode": mode, "unparsed_lines": num, "keys": key_list})


def key_files(v):
    """The number of authorized_keys files, then one line for each."""
    if _word(v):
        return _word(v)
    if not isinstance(v, list):
        return WITHHELD
    if len(v) > MAX_LISTED:
        return f"{len(v)} (not listed)"
    return str(len(v)) + "".join("\n    file: " + _KEY_FILE(row) for row in v)


# ------------------------------------------------------------------ what is printed for each item
_SETTING = fixed({"number": num, "set_by": ("file", set_by), "value": member(SETTING_VALUES)})
_BROKER_RUNNER = fixed({k: when for k in UNIT_LABELS})
_LEAKS = fixed({k: num for k in LEAK_KEYS})
_READ = fixed({k: num for k in _READ_KEYS})
_DIR = fixed({"owner_is_root": ("owner", is_root), "group_is_root": ("group", is_root), "mode": mode})


def dir_row(v):
    """A directory's owner, group and mode, or the word for what is there instead of a directory."""
    return _DIR(v) if isinstance(v, dict) else member(DIR_WORDS)(v)


def oldest_entry(shown):
    def fmt(v):
        text = fixed({"journal": when, "apps": apps_inline(_BROKER_RUNNER, shown)})(v)
        return text + (OLDER_SHAPE if isinstance(v, dict) and "apps" not in v else "")
    return fmt


def run_ok_results(v):
    return _word(v) or num(_run_ok({"results": v}))


def schema(shown):
    """What is printed for each item; `shown` is the set of job names that may be printed."""
    job = {"declared": flag, "installed": flag}          # every per-job entry says both
    starts = START_KEYS - frozenset(SERVICES)
    return {
        "D1.7": {"accounts_checked": num, "unprivileged_port_start": num, "match_lines": num, "include_elsewhere": num,
                 "daemon_options": fixed({"listeners": num, "config_file_options": num, "setting_options": num}),
                 "sshd_settings": ("sshd", count), "files": key_files},
        "D2.3": {"journal": fixed({k: num for k in SEARCH_KEYS}), "scanned_characters": num,
                 "entries": num, "fields": num, "undecodable_characters": num, "oldest_entry_read": when},
        "D2.4": {"oldest_entry": oldest_entry(shown), "reach_days": num,
                 "settings": keyed(SETTING_NAMES, _SETTING), "config_files": None,
                 "drop_in": fixed({"equals_repo": flag, "owner_is_root": ("owner", is_root),
                                   "group_is_root": ("group", is_root), "mode": mode, "other_files": count}),
                 "service": fixed({"active": flag, "started_at": when, "config_changed_after_start": flag}),
                 "usage": fixed({"bytes": num, "files": num, "bytes_percent_of_max_use": num,
                                 "files_percent_of_max_files": num, "free_bytes": num, "free_percent": num,
                                 "other_directories": num, "newest_entry_on_disk": when,
                                 "on_disk_age_seconds": num, "flushed_to_disk": flag})},
        "D4.1": {"paths": None, "listeners": count, "docker_dns_listeners": num,
                 "secret_env": keyed(SECRET_LABELS, member(SECRET_STATES)), "google_ads_env_names": None,
                 "anthropic_env_names": None, "openrouter_env_names": None},
        "D4.2": {"active": member(ACTIVE_STATES), "matches_last_pass": flag, "execstart_sha256": None,
                 "last_pass_execstart_sha256": None, "execstart_argv_sha256": None, "drop_in_paths": None},
        "D4.5": {"timer_active": member(ACTIVE_STATES), "timer_enabled": member(ENABLED_STATES),
                 "installed_equal_repo": keyed(LISTENER_UNITS, flag), "drop_in_paths": None, "state_dir": None,
                 "max_age_seconds": None, "last": None, "last_age_seconds": num, "alert_present": flag, "alert": None,
                 "history_counts": keyed(HISTORY_STATUSES, num),
                 "alert_log": fixed({k: when if k.endswith("_ts") else num for k in sorted(ALERT_LOG_KEYS)})},
        "D4.6": {"last_pass_collected_at": when, "apps_declared": count, "apps_installed": count,
                 "started_at": by_service(when, shown, starts), "started_after_last_pass": by_service(flag, shown, starts),
                 "files_newer_than_start": by_service(count, shown), "files_checked": by_service(num, shown)},
        "D7.1": {"records": num, "vaults": None, "reports_rows": None, "draft_out_rows": None, "parents": None,
                 "old_data": None, "audit_data": None, "audit_logs": None, "root_backups": None,
                 "report_archive": fixed({"parent": dir_row, "rows": count, "rows_listed": flag, "rows_not_read": num,
                                          "files_not_read": ("rows", files_not_read),
                                          "containers_mounting": num, "containers_not_inspected": num})},
        "D10.1": {"rc": num, "probe": fixed({"matches_declared": flag, "services": count,
                                             "figures_services": listed(PROBE_SERVICES)})},
        "D10.3": {"declared_apps": count, "installed_apps": count, "on_disk_apps": count, "units_not_counted": num,
                  "on_disk_not_counted": num, "installed_equal_repo": keyed(APP_UNITS, flag),
                  "apps": per_app({**job, "runner_path_active": member(ACTIVE_STATES), "broker_user_groups": count,
                                   "broker_unit": None, "runner_unit": None, "drop_in_paths": None, "sudo_rules": None},
                                  shown)},
        "D10.4": {"containers": num, "containers_mounting_app_state": num, "containers_not_inspected": num,
                  "apps": per_app({**job, "layout_problems": count, "layout_reason": member(LAYOUT_REASONS)}, shown)},
        "D10.7": {"known_secrets_checked": num,
                  "apps": per_app({**job, "journal_counts": journal_counts, "note_counts": keyed(NOTE_WORDS, num),
                                   "other_lines": num, "broker_journal": _LEAKS, "runner_journal": _LEAKS,
                                   "journal_read": fixed({k: _READ for k in UNIT_LABELS}),
                                   "oldest_entry_read": _BROKER_RUNNER, "first_entry": when,
                                   "installed_since_last_pass": flag}, shown)},
        "D10.8": {"apps": per_app({**job, "out_of_whitelist": num, "run/ok results": ("results", run_ok_results)}, shown)},
    }


# The key each per-job item holds since the collector finds the jobs itself: without it, the
# bundle is an older one (one job, its values at the top of the item).
PER_JOB = {"D4.6": "apps_installed", "D10.3": "apps", "D10.4": "apps", "D10.7": "apps", "D10.8": "apps"}


# ------------------------------------------------------------------ reading the bundle
def _get(value, *path):
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _data(items, iid):
    """The item's data when the item was observed; {} for anything else (a missing item, could-not-check)."""
    item = items.get(iid)
    if not isinstance(item, dict) or item.get("status") != "observed":
        return {}
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is(value, n):
    """Exactly the integer n: not True for 1, not 0.0 for 0, not a string."""
    return _int(value) and value == n


def cnc_places(root):
    """How many places in the bundle hold the string could-not-check, as a value or as a key, at any
    depth; a structure deeper than MAX_WALK_DEPTH counts as one place (it was not read)."""
    places, stack = 0, [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, str):
            places += value == CNC
        elif isinstance(value, (dict, list)):
            if depth >= MAX_WALK_DEPTH:
                places += 1
                continue
            if isinstance(value, dict):
                places += sum(1 for k in value if k == CNC)
            stack.extend((x, depth + 1) for x in (value.values() if isinstance(value, dict) else value))
    return places


def _run_ok(data):
    rows = data.get("results")
    if not isinstance(rows, list):
        return None
    return sum(1 for r in rows if isinstance(r, dict) and r.get("op") == "run" and r.get("status") == "ok"
               and r.get("keys_ok") is True and r.get("values_ok") is True)


def _shape(items, iid, key):
    """"" when the item was observed and holds `key`; else why it cannot be judged."""
    item = items.get(iid)
    data = item.get("data") if isinstance(item, dict) and item.get("status") == "observed" else None
    if not isinstance(data, dict):
        return NOT_READ
    return "" if key in data else OLDER_SHAPE


def _names(value):
    return isinstance(value, list) and all(isinstance(n, str) for n in value)


def _job_list(items, key):
    """One of D10.3's three lists of job names as a set; empty when it was not read (the jobs' line says so)."""
    names = _data(items, "D10.3").get(key)
    return set(names) if _names(names) else set()


def _shown(items):
    """The job names that may be printed: D10.3's declared jobs that have the form of a job's name."""
    return frozenset(n for n in _job_list(items, "declared_apps") if is_app(n))


def _judged(items, iid):
    """(jobs, excused, why) for a per-job item, each of the two a dict {name: entry}.
    `jobs`: what a closing line must judge whole: every job D10.3 lists as installed (an empty
    entry when this item has none for it, so it reads as not checked), and every other entry of
    this item but those in `excused`. `excused`: the entries that say the job is not installed
    (`installed` exactly false) for a job D10.3 does not list as installed: declared and not
    installed yet, or only on disk. What could not be checked for such a job is expected; a count
    of something bad in its entry is not excused (see _each_job). `why`: the reason there is
    nothing to judge, in fixed words; "" when there is."""
    why = _shape(items, iid, "apps")
    if why:
        return {}, {}, why
    apps = _data(items, iid)["apps"]
    if not isinstance(apps, dict):
        return {}, {}, JOBS_NOT_READ
    must = _job_list(items, "installed_apps")
    jobs, excused = {app: {} for app in must}, {}
    for app, entry in apps.items():
        if app not in must and isinstance(entry, dict) and entry.get("installed") is False:
            excused[app] = entry
        else:
            jobs[app] = entry if isinstance(entry, dict) else {}
    return jobs, excused, "" if jobs else NO_INSTALLED_JOB


def _unchecked(entry):
    """A judged job with a value that is could-not-check, at any depth, or that does not say it is
    installed: no line may read ok over it."""
    return entry.get("installed") is not True or cnc_places(entry) > 0


def _not_so(bad, total, unread, what="jobs"):
    """How many do not pass, never which; and whether a value that could not be checked is why."""
    if not bad:
        return ""
    return f" (not so for {bad} of {total} {what}{': a value could not be checked' if unread else ''})"


def _each_job(items, iid, passes, never=None):
    """(ok, note, jobs, excused): ok only when there is a job to judge, every judged job was
    checked whole and passes, and no excused job holds what `never` finds: a real count of
    something bad, which "not installed" does not excuse."""
    jobs, excused, why = _judged(items, iid)
    unread = sum(1 for e in jobs.values() if _unchecked(e))
    bad = sum(1 for e in jobs.values() if _unchecked(e) or not passes(e))
    bad += sum(1 for e in excused.values() if never and never(e))
    note = _not_so(bad, len(jobs) + (len(excused) if never else 0), unread) + why
    return not note, note, jobs, excused


def _unchecked_note(jobs):
    n = sum(1 for e in jobs.values() if _unchecked(e))
    return _not_so(n, len(jobs), True)


def _plain(value):
    """What a value that is not a count is, in plain words; never the value."""
    if value is None:
        return "not read"
    return "could not be checked" if isinstance(value, str) and value == CNC else "a value that is not a number"


def _counted(value, one, many):
    """`3 containers not inspected`, `1 container not inspected`; for anything but a count that can
    be printed, `containers not inspected: could not be checked`."""
    if _int(value) and len(str(abs(value))) <= MAX_DIGITS:
        return f"{value} {one if value == 1 else many}"
    return f"{many}: {_plain(value)}"


def _not_a_count(value):
    """What _counted is given for a value that may not be printed as a count: the value when it is
    not read or could not be checked (it has its own words), else something that is not a number."""
    return value if value is None or (isinstance(value, str) and value == CNC) else False


def _many(n, one, many):
    return f"{n} {one if n == 1 else many}"


_NOTE_RE = re.compile(r" \(([^()]*)\)")


def _once(notes):
    """The notes of a line, each in brackets, a repeated one said once. A note comes bare, or as
    one or more notes already in brackets (what _each_job and _shape return)."""
    bare = []
    for note in notes:
        bare += _NOTE_RE.findall(note) if note.startswith(" (") else [note] if note else []
    return "".join(f" ({n})" for n in dict.fromkeys(bare))


# ------------------------------------------------------------------ the closing list: one function per line
def _all_observed(bundle, items):
    bad = sorted(((int(m.group(1)), int(m.group(2)), i) for i, it in items.items()
                  if (not isinstance(it, dict) or it.get("status") != "observed") and (m := _ID_RE.fullmatch(i))))
    unnamed = sum(1 for i, it in items.items() if (not isinstance(it, dict) or it.get("status") != "observed")
                  and not _ID_RE.fullmatch(i))
    text = f"every item observed ({len(items)} items)"
    if bad or unnamed:
        text += f" (not observed: {', '.join([b[2] for b in bad] + ([f'{unnamed} other'] if unnamed else []))})"
    return bool(items) and not (bad or unnamed), text


def _no_could_not_check(bundle, items):
    places = cnc_places(bundle)
    # D4.5's history_counts is keyed by the status of each recorded run: a key named could-not-check
    # there is a count of runs (CHECKLIST D4.5, pass rule (1)), not a field that was not read.
    history = _data(items, "D4.5").get("history_counts")
    runs = history.get(CNC) if isinstance(history, dict) else None
    counted = _int(runs) and 0 <= runs < 10 ** MAX_DIGITS      # a longer number is not a count of runs
    places -= 1 if counted else 0
    listed = isinstance(bundle.get("credentials"), list)
    note = (f" ({places} {'place' if places == 1 else 'places'})" if places else "") \
        + ("" if listed else " (credentials is not a list)") \
        + (f" (not counted: {num(runs)} past listener-check runs in D4.5's history)" if counted and runs else "")
    return places == 0 and listed, "nothing in the bundle is could-not-check" + note


def _sshd_default(bundle, items):
    d = _data(items, "D1.7")
    daemon = d.get("daemon_options")
    ok = (_is(d.get("match_lines"), 0) and _is(d.get("include_elsewhere"), 0) and isinstance(daemon, dict)
          and set(daemon) == set(DEFAULT_DAEMON) and all(_is(daemon[k], n) for k, n in DEFAULT_DAEMON.items()))
    return ok, "sshd runs with its default settings file and no Match line"


PER_JOB_ITEMS = ("D10.3", "D10.4", "D10.7", "D10.8")


def _jobs_line(bundle, items):
    """The three lists of D10.3 agree: every job is declared and installed, none is only on disk,
    nothing in the two listings was left uncounted, and every per-job entry of the four per-job
    items is for a job of the lists and says of it what the lists say."""
    text = "every job is declared and installed"
    why = _shape(items, "D10.3", "declared_apps")
    if why:
        return False, text + why
    d = _data(items, "D10.3")
    lists = [d.get(k) for k in ("declared_apps", "installed_apps", "on_disk_apps")]
    if not all(_names(names) for names in lists):
        return False, text + JOBS_NOT_READ
    declared, installed, on_disk = (set(names) for names in lists)
    known = declared | installed | on_disk
    every = [_data(items, iid).get("apps") for iid in PER_JOB_ITEMS]
    entries = [(app, e) for apps in every if isinstance(apps, dict) for app, e in apps.items()]
    stray = {app for app, _ in entries} - known
    differ = sum(1 for app, e in entries if isinstance(e, dict) and app in known
                 and (e.get("declared") is not (app in declared) or e.get("installed") is not (app in installed)))
    jobs, _, why = _judged(items, "D10.3")
    counts = ((len(declared - installed), "declared but not installed"),
              (len(installed - declared), "installed but not declared"),
              (len(on_disk - declared - installed), "on disk only"),
              (sum(1 for n in known | stray if not is_app(n)), "with a name that is not a job name"),
              (len(stray), "in no list"),
              (differ, "per-job entry disagrees with the lists" if differ == 1 else "per-job entries disagree with the lists"))
    note = "".join(f" ({n} {what})" for n, what in counts if n) + _unchecked_note(jobs)
    for key, one, many in (("units_not_counted", "unit line not counted", "unit lines not counted"),
                           ("on_disk_not_counted", "entry on disk not counted", "entries on disk not counted")):
        if not _is(d.get(key), 0):
            note += f" ({_counted(d.get(key), one, many)})"
    note += why if installed or why != NO_INSTALLED_JOB else ""
    note += "" if installed else NO_INSTALLED_JOB
    return not note, text + (note or f" ({_many(len(installed), 'job', 'jobs')})")


def _layout_line(bundle, items):
    """D10.4: every job's spool and state folders are as host_layout's table says, and no running
    container mounts the job state. A list of problems that is not empty is a count of something
    bad: it is said for a job that is not installed too."""
    text = "every job's folders are as designed and no container mounts the job state"
    _, note, _, _ = _each_job(items, "D10.4", lambda e: e.get("layout_problems") == [],
                              never=lambda e: "layout_problems" in e and e["layout_problems"] != CNC
                              and e["layout_problems"] != [])
    notes = [note]
    if _shape(items, "D10.4", "apps") != NOT_READ:
        d = _data(items, "D10.4")
        for key, one, many in (("containers_mounting_app_state", "container mounts the job state", "containers mount the job state"),
                               ("containers_not_inspected", "container not inspected", "containers not inspected")):
            if not _is(d.get(key), 0):
                notes.append(_counted(d.get(key), one, many))
    notes = _once(notes)
    return not notes, text + notes


def _units_and_results(bundle, items):
    """D10.3: each of the three template unit files installed is byte for byte the repository's.
    D10.8: no stored result of any job is out of whitelist; a number above 0 is said for a job
    that is not installed too."""
    text = "the installed job units equal the repository's and every stored result is in whitelist"
    notes = [_shape(items, "D10.3", "installed_equal_repo")]
    if not notes[0]:
        equal = _data(items, "D10.3")["installed_equal_repo"]
        equal = equal if isinstance(equal, dict) else {}
        differ = sum(1 for unit in APP_UNITS if equal.get(unit) is not True)
        other = sum(1 for unit in equal if unit not in APP_UNITS)
        notes = [_many(differ, "unit file differs or was not read", "unit files differ or were not read") if differ else "",
                 _many(other, "entry that is not a job unit file", "entries that are not a job unit file") if other else ""]
    notes.append(_each_job(items, "D10.8", lambda e: _is(e.get("out_of_whitelist"), 0),
                           never=lambda e: "out_of_whitelist" in e and e["out_of_whitelist"] != CNC
                           and not _is(e["out_of_whitelist"], 0))[1])
    notes = _once(notes)
    return not notes, text + notes


def _probe_line(bundle, items):
    """D10.1: the credential probe ended with 0 and matches the declared map, and a figures run
    (the report job's) would start the collector and the reader and nothing else: no AI service."""
    text = "the credential probe matches the declared map and a figures run starts no AI service"
    if _shape(items, "D10.1", "probe") == NOT_READ:
        return False, text + NOT_READ
    d = _data(items, "D10.1")
    probe = d.get("probe")
    if not isinstance(probe, dict):
        return False, text + " (the probe was not read)"
    notes = []
    if not _is(d.get("rc"), 0):
        notes.append("the probe did not end with 0")
    if probe.get("matches_declared") is not True:
        notes.append("the probe does not match the declared map")
    figures = probe.get("figures_services")
    if "figures_services" not in probe:
        notes.append("not in this bundle")
    elif not _names(figures):
        notes.append("the services of a figures run were not read")
    elif sorted(figures) != sorted(FIGURES_SERVICES):
        notes.append("a figures run does not start exactly the collector and the reader")
    return not notes, text + _once(notes)


def _refusals(bundle, items):
    def missing(entry):
        counts = entry.get("journal_counts")
        counts = counts if isinstance(counts, dict) else {}
        return [k for k in REFUSALS if not (_int(counts.get(k)) and counts.get(k) > 0)]
    ok, note, jobs, _ = _each_job(items, "D10.7", lambda e: not missing(e))
    absent = [k for k in REFUSALS if any(k in missing(e) for e in jobs.values())]
    return ok, "the three live refusals are in the journal" + (f" (missing: {', '.join(absent)})" if absent else "") + note


def _run_ok_line(bundle, items):
    def has_one(entry):
        n = _run_ok(entry)
        return _int(n) and n > 0
    ok, note, _, _ = _each_job(items, "D10.8", has_one)
    return ok, "at least one run/ok result" + note


def _retention(bundle, items):
    d24 = _data(items, "D2.4")
    retention = _get(d24, "settings", "MaxRetentionSec")
    retention = retention if isinstance(retention, dict) else {}
    number = retention.get("number")
    storage = _get(d24, "settings", "Storage")
    has_value = isinstance(storage, dict) and "value" in storage
    storage_ok = has_value and storage["value"] in STORAGE_OK
    root_0644 = (is_root(_get(d24, "drop_in", "owner")) == "true" and is_root(_get(d24, "drop_in", "group")) == "true"
                 and mode(_get(d24, "drop_in", "mode")) == "0o644")
    ok = (_int(number) and number >= THIRTY_DAYS and retention.get("file") == OUR_FILE and root_0644
          and _get(d24, "drop_in", "equals_repo") is True and _get(d24, "drop_in", "other_files") == [] and storage_ok)
    note = ""
    if not storage_ok:
        note = f" (Storage is {member(SETTING_VALUES)(storage['value'])})" if has_value else " (Storage not read)"
    return ok, ("retention at least 30 days, set by our file, the file equal to the repository's, no other file, "
                "root:root 0644") + note


SINCE_LAST_PASS = (True, False, None)      # what a comparison with the last PASS may be, when it could be made


def _broker_read(entry):
    """A job's oldest broker entry in D2.4: a time or null (the broker has not logged); the key is there."""
    return "broker" in entry and (entry["broker"] is None or is_time(entry["broker"]))


def _reach(bundle, items):
    """The journal's reach is D2.4's. A job whose first journal entry is later than the last PASS
    (a new job, or one whose older entries the journal no longer holds) has no 30 days of its
    own: it is said here (D10.7), and it does not turn the line. What does: an installed job
    whose D10.7 values, or whose oldest entries in D2.4, could not be checked or are not there."""
    d24 = _data(items, "D2.4")
    reach = d24.get("reach_days")
    ok = _int(reach) and reach >= 30
    note = ""
    if not ok:
        note = (f" (reach is {num(reach)} days: the evidence needs the date the retention was raised)"
                if _int(reach) else " (not read)")
    jobs, _, why = _judged(items, "D10.7")
    new = [e for e in jobs.values() if e.get("installed_since_last_pass") is True]
    logged = sum(1 for e in new if is_time(e.get("first_entry")))
    quiet = sum(1 for e in new if e.get("first_entry") is None)
    if logged:
        note += (" (1 job whose first journal entry is later than the last PASS: new, or the journal no longer reaches that far; judged from its first entry)" if logged == 1 else
                 f" ({logged} jobs whose first journal entry is later than the last PASS: new, or the journal no longer reaches that far; each judged from its first entry)")
    if quiet:
        note += (" (1 job installed since the last PASS and it has not logged yet)" if quiet == 1 else
                 f" ({quiet} jobs installed since the last PASS and they have not logged yet)")
    # by name, so that a job unread in both items is one job
    unread = {app for app, e in jobs.items()
              if _unchecked(e) or not any(e.get("installed_since_last_pass") is v for v in SINCE_LAST_PASS)
              or (e.get("installed_since_last_pass") is True and e.get("first_entry") is not None
                  and not is_time(e.get("first_entry")))}
    names, not_read = set(jobs), why == JOBS_NOT_READ
    oldest = d24.get("oldest_entry")
    installed = _job_list(items, "installed_apps")
    if isinstance(oldest, dict) and "apps" in oldest:
        names |= installed
        if isinstance(oldest["apps"], dict):
            unread |= {app for app in installed if not isinstance(oldest["apps"].get(app), dict)
                       or cnc_places(oldest["apps"][app]) > 0 or not _broker_read(oldest["apps"][app])}
        else:
            not_read = True
    elif names or installed:                  # per-job data elsewhere, and no per-job oldest entries here
        names |= installed
        not_read = True
    tail = _not_so(len(unread), len(names), True) + (JOBS_NOT_READ if not_read else "")
    return ok and not tail, "the journal reaches 30 days" + note + tail


def _search(bundle, items):
    d = _data(items, "D2.3")
    scanned = d.get("scanned_characters")
    ok = _int(scanned) and scanned > 0 and _is(d.get("undecodable_characters"), 0) and is_time(d.get("oldest_entry_read"))
    return ok, "the journal search read everything it was given"


_ABSENT = object()      # a count that is not in the entry at all


def _no_leaks(bundle, items):
    """Every leak count the checklist fails on, each read by the tool's own key names: a key the tool
    does not name is not read here (the item line counts it as an other key). The counts of EVERY
    job's entry in D10.7 are read, whatever the entry says of the job: a count above 0 is a leak in
    the journal whether or not the job is installed. For a job that is not installed, only a count
    that is could-not-check or not there is expected."""
    def read(group, keys):
        if isinstance(group, dict):
            return [group.get(key, _ABSENT) for key in keys]
        return [group if group is _ABSENT or group == CNC else None] * len(keys)

    def of_job(entry):
        return (read(entry.get("broker_journal", _ABSENT), LEAK_KEYS)
                + read(entry.get("runner_journal", _ABSENT), LEAK_KEYS))

    def a_real_count(entry):
        return any(not (_is(c, 0) or c is _ABSENT or c == CNC) for c in of_job(entry))
    search = read(_data(items, "D2.3").get("journal"), SEARCH_KEYS)
    ok, jobs_note, jobs, excused = _each_job(items, "D10.7", lambda e: all(_is(c, 0) for c in of_job(e)), never=a_real_count)
    counts = search + [c for e in jobs.values() for c in of_job(e)]
    counts += [c for e in excused.values() for c in of_job(e) if not (c is _ABSENT or c == CNC)]
    if jobs_note == NOT_READ:                           # the item itself: every count of it was not read
        counts, jobs_note = counts + [None], ""
    ok = ok and all(_is(c, 0) for c in counts)
    note = ""
    if any(_int(c) and c > 0 for c in counts):
        note = " (a count is above 0: this is a FAIL, not a reminder)"
    elif not all(_is(c, 0) for c in counts):
        note = " (a count was not read)"
    return ok, "no leak count above 0 (D2.3, D10.7)" + note + jobs_note


def _service(bundle, items):
    d24 = _data(items, "D2.4")
    ok = _get(d24, "service", "active") is True and _get(d24, "service", "config_changed_after_start") is False
    return ok, "the running journal service has read its settings"


def _on_disk(bundle, items):
    usage = _get(_data(items, "D2.4"), "usage")
    usage = usage if isinstance(usage, dict) else {}
    age = usage.get("on_disk_age_seconds")
    return usage.get("flushed_to_disk") is True and _int(age) and 0 <= age <= 600, "the journal is being written to disk"


def _no_other_directory_no_missing_days(bundle, items):
    d24 = _data(items, "D2.4")
    usage = _get(d24, "usage")
    usage = usage if isinstance(usage, dict) else {}
    other, files, reach = usage.get("other_directories"), usage.get("files"), d24.get("reach_days")
    days_read = _int(files) and _int(reach)
    ok = _is(other, 0) and days_read and files >= reach
    note = ""
    if days_read and files < reach:
        note += " (fewer files than days: needs explaining)"
    if _int(other) and other > 0:
        note += f" ({num(other)} other: needs your statement in the evidence)"
    return ok, "no other journal directory and no missing days" + (note or ("" if ok else " (not read)"))


def _proxy(bundle, items):
    d = _data(items, "D4.2")
    return d.get("matches_last_pass") is True and d.get("active") == "active", "the proxy matches the last PASS"


START_GROUPS = ("started_at", "started_after_last_pass")
FILE_GROUPS = ("files_newer_than_start", "files_checked")


def _code(bundle, items):
    """The two fixed services and the broker of every INSTALLED job (by this item's list and by
    D10.3's): each with a start time, a comparison with the last PASS that could be made, files
    checked and none newer than its start. The broker of a job that is declared and not installed
    has never started: it may be there, and is not judged. A broker of a job in neither list, or
    any other key among the files, is not a service this tool knows."""
    text = "no service runs older code than the box holds"
    why = _shape(items, "D4.6", "apps_installed")
    if why:
        return False, text + why
    d = _data(items, "D4.6")
    declared, installed = d.get("apps_declared"), d.get("apps_installed")
    if not (_names(declared) and _names(installed)):
        return False, text + JOBS_NOT_READ
    judged = set(SERVICES) | {BROKER_PREFIX + app for app in set(installed) | _job_list(items, "installed_apps")}
    allowed = judged | {BROKER_PREFIX + app for app in declared}
    groups = {g: d.get(g) if isinstance(d.get(g), dict) else {} for g in START_GROUPS + FILE_GROUPS}
    whole = {g: d.get(g) == CNC for g in groups}                # the group itself could not be checked

    def values(service):
        return [CNC if whole[g] else groups[g].get(service, _ABSENT) for g in START_GROUPS + FILE_GROUPS]

    def passes(service):
        started, after, newer, checked = values(service)
        return (is_service(service) and is_time(started) and any(after is v for v in SINCE_LAST_PASS)
                and newer == [] and _int(checked) and checked > 0)
    bad = [s for s in judged if not passes(s)]
    unread = any(v is _ABSENT or v == CNC for s in bad for v in values(s))
    keys = {k for g in groups.values() for k in g}
    strays = sum(1 for k in keys if k.startswith(BROKER_PREFIX) and k not in allowed)
    others = sum(1 for k in {k for g in FILE_GROUPS for k in groups[g]} if not k.startswith(BROKER_PREFIX) and k not in allowed)
    notes = [_not_so(len(bad), len(judged), unread, "services"),
             _many(strays, "broker of a job in no list", "brokers of jobs in no list") if strays else "",
             _many(others, "entry that is not a service", "entries that are not a service") if others else ""]
    notes = _once(notes)
    return not notes, text + notes


STORE_WORDS = {DIR_ABSENT: "the store is not there", DIR_LINK: "the store is a link",
               DIR_NOT_A_DIRECTORY: "the store is not a directory", CNC: "the store could not be checked"}


def _report_store(bundle, items):
    """D7.1's report store: a root:root 0700 directory that was listed, holding only folders of
    active clients, each root-owned 0700, listed, with nothing inside but root:root 0600 files,
    no entry of it or of a folder left unexamined, and mounted by no container. Every fault is
    a count."""
    text = "the report store holds only owner-only client folders"
    why = _shape(items, "D7.1", "report_archive")
    if why:
        return False, text + (" (not in this bundle)" if why == OLDER_SHAPE else why)
    store = _data(items, "D7.1")["report_archive"]
    if not isinstance(store, dict):
        return False, text + NOT_READ
    notes = []
    parent = store.get("parent")
    if parent is None:
        notes.append("the store was not read")
    elif not isinstance(parent, dict):
        notes.append(STORE_WORDS.get(parent, STORE_WORDS[DIR_NOT_A_DIRECTORY]) if isinstance(parent, str)
                     else STORE_WORDS[DIR_NOT_A_DIRECTORY])
    elif not (parent.get("owner") == "root" and parent.get("group") == "root" and parent.get("mode") == "0o700"):
        notes.append("the store is not root:root 0700")
    if store.get("rows_listed") is not True:
        notes.append("the store was not listed")
    rows = store.get("rows")
    if not isinstance(rows, list):
        notes.append("the folders were not read")
        rows = []
    rows = [r if isinstance(r, dict) else {} for r in rows]
    faults = (("not a folder", lambda r: r.get("kind") == ROW_DIR),
              ("not active", lambda r: r.get("status") == ROW_ACTIVE),
              ("not listed", lambda r: r.get("listed") is True),
              ("holding something that is not a file", lambda r: _is(r.get("not_files"), 0)),
              ("not root 0700", lambda r: r.get("owner") == "root" and r.get("mode") == "0o700"),
              ("with a file that is not root root 0600", lambda r: isinstance(r.get("files"), dict)
               and all(k == STORE_FILE for k in r["files"])))
    for what, good in faults:
        n = sum(1 for r in rows if not good(r))
        if n:
            notes.append(f"{n} {what}")
    not_read = store.get("rows_not_read")                       # entries of the store that have no row
    if not _is(not_read, 0):
        notes.append(_counted(not_read if _int(not_read) and not_read > 0 else _not_a_count(not_read),
                              "entry of the store not read", "entries of the store not read"))
    inside = _files_not_read(rows)                              # entries inside a folder that were not examined
    if inside != 0:
        first = next((v for v in (r.get("files_not_read") for r in rows) if not (_int(v) and v >= 0)), False)
        notes.append(_counted(inside if inside is not None else _not_a_count(first),
                              "entry inside a folder not read", "entries inside a folder not read"))
    for key, one, many in (("containers_mounting", "container mounts it", "containers mount it"),
                           ("containers_not_inspected", "container not inspected", "containers not inspected")):
        if not _is(store.get(key), 0):
            notes.append(_counted(store.get(key), one, many))
    return not notes, text + (_once(notes) or f" ({_many(len(rows), 'folder', 'folders')})")


def _fingerprint(bundle, items):
    return _get(bundle, "fingerprint", "complete") is True, "fingerprint complete"


CHECKS = (_all_observed, _no_could_not_check, _jobs_line, _layout_line, _units_and_results, _probe_line, _sshd_default,
          _refusals, _run_ok_line, _retention, _reach, _search, _no_leaks, _service, _on_disk,
          _no_other_directory_no_missing_days, _proxy, _code, _report_store, _fingerprint)


# ------------------------------------------------------------------ the summary
def _id_key(iid):
    m = _ID_RE.fullmatch(iid)
    return (int(m.group(1)), int(m.group(2)))


def _status(item):
    got = item.get("status") if isinstance(item, dict) else None
    return got if isinstance(got, str) and got in ("observed", CNC) else OTHER


def summary(bundle):
    items = bundle["items"]
    ids = sorted((i for i in items if _ID_RE.fullmatch(i)), key=_id_key)
    status = {i: _status(items[i]) for i in ids}
    not_observed = [i for i in ids if status[i] != "observed"]
    unnamed = sum(1 for i, it in items.items() if not _ID_RE.fullmatch(i) and _status(it) != "observed")
    if unnamed:
        not_observed.append(f"{unnamed} other")
    known = schema(_shown(items))
    lines = [f"collected_at {when(bundle.get('collected_at'))}",
             f"items {len(items)} | not observed: {', '.join(not_observed) or 'none'}",
             f"other items: {len(items) - len(ids)}", ""]
    for iid in ids:
        lines.append(f"{iid}  {status[iid]}")
        data = _data(items, iid)
        pairs, other = _fields(data, known[iid]) if iid in known else ([], 0)
        lines += [f"  {name}: {text}" for name, text in pairs]
        if other:
            lines.append(f"  +{other} other keys")
        if iid in PER_JOB and _shape(items, iid, PER_JOB[iid]) == OLDER_SHAPE:
            lines.append(" " + OLDER_SHAPE)
    creds = bundle.get("credentials")
    lines += ["", f"credentials: {len(creds) if isinstance(creds, list) else WITHHELD}", "",
              "Before the real collection (ok = as expected, LOOK = look at it first):"]
    for check in CHECKS:
        ok, text = check(bundle, items)
        lines.append(f"{'ok  ' if ok else 'LOOK'}  {text}")
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
    except (OSError, ValueError, RecursionError):
        print("summarize-review-bundle: not a box bundle (did the collector stop? read its own message and its rc)", file=out)
        return 2
    print("\n".join(summary(bundle)), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
