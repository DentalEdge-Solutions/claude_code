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

ONE NAME IS PRINTED BY ITS FORM: a job's name, where the bundle keys a job's values by it (an
`apps` dict, and the `hermes-app-broker@<job>` keys of D4.6), and only when it is what the
collector calls a job name (`[a-z][a-z0-9-]{0,31}`). Any other key there prints as <withheld> or
is counted. A LIST of job names is printed as its length.

THE JOBS. The box runs several chat-triggered jobs; the collector finds them itself and reports
six items per job. A closing line that reads such an item is `ok` only when it holds for EVERY
installed job, and a value of an installed job that is could-not-check makes the line LOOK. A job
that is declared and not installed yet is said once, on its own line.
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
DIR_WORDS = frozenset({"absent", "symlink", "not-a-directory"})                          # _dir_row: not a real directory
PROBE_SERVICES = frozenset({"ads-collector", "ads-reader", "ads-drafter", "egress-proxy"})   # run-client-audit's DECLARED
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
    """A dict whose keys come from a closed set (or pass `keys`, when it is a function): those are
    printed, the others counted."""
    known = keys if callable(keys) else keys.__contains__

    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        return _braced([(k, inner(v[k])) for k in sorted(v) if known(k)], sum(1 for k in v if not known(k)))
    return fmt


def is_app(name):
    return isinstance(name, str) and _APP_RE.fullmatch(name) is not None


def _app_name(name):
    """A job's name when it has the form of one; anything else is never printed."""
    return name if is_app(name) else WITHHELD


def is_service(key):
    """A fixed service, or the broker of a job whose name has the form of one."""
    return key in SERVICES or (key.startswith(BROKER_PREFIX) and is_app(key[len(BROKER_PREFIX):]))


def is_start(key):
    return key in START_KEYS or is_service(key)


def _by_name(apps):
    """The jobs in the order they are shown: those with a job's name first, by name."""
    return sorted(apps, key=lambda k: (not is_app(k), k))


def apps_inline(inner):
    """{job: value} on one line: every job is shown, under its name or as <withheld>."""
    def fmt(v):
        if _word(v):
            return _word(v)
        if not isinstance(v, dict):
            return WITHHELD
        if len(v) > MAX_LISTED:
            return f"{len(v)} (not listed)"
        return _braced([(_app_name(k), inner(v[k])) for k in _by_name(v)], 0)
    return fmt


def per_app(spec):
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
        for app in _by_name(v):
            entry = v[app]
            if not isinstance(entry, dict):
                out.append(f"    {_app_name(app)}: {_word(entry) or WITHHELD}")
                continue
            pairs, other = _fields(entry, spec)
            out.append(f"    {_app_name(app)}:")
            out += [f"      {name}: {text}" for name, text in pairs]
            if other:
                out.append(f"      +{other} other keys")
        return "\n".join(out)
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
_JOB = {"declared": flag, "installed": flag}          # every per-job entry says both
_DIR = fixed({"owner_is_root": ("owner", is_root), "group_is_root": ("group", is_root), "mode": mode})


def dir_row(v):
    """A directory's owner, group and mode, or the word for what is there instead of a directory."""
    return _DIR(v) if isinstance(v, dict) else member(DIR_WORDS)(v)


def oldest_entry(v):
    text = fixed({"journal": when, "apps": apps_inline(_BROKER_RUNNER)})(v)
    return text + (OLDER_SHAPE if isinstance(v, dict) and "apps" not in v else "")


def run_ok_results(v):
    return _word(v) or num(_run_ok({"results": v}))


SCHEMA = {
    "D1.7": {"accounts_checked": num, "unprivileged_port_start": num, "match_lines": num, "include_elsewhere": num,
             "daemon_options": fixed({"listeners": num, "config_file_options": num, "setting_options": num}),
             "sshd_settings": ("sshd", count), "files": key_files},
    "D2.3": {"journal": fixed({k: num for k in SEARCH_KEYS}), "scanned_characters": num,
             "entries": num, "fields": num, "undecodable_characters": num, "oldest_entry_read": when},
    "D2.4": {"oldest_entry": oldest_entry, "reach_days": num,
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
             "started_at": keyed(is_start, when), "started_after_last_pass": keyed(is_start, flag),
             "files_newer_than_start": keyed(is_service, count), "files_checked": keyed(is_service, num)},
    "D7.1": {"records": num, "vaults": None, "reports_rows": None, "draft_out_rows": None, "parents": None,
             "old_data": None, "audit_data": None, "audit_logs": None, "root_backups": None,
             "report_archive": fixed({"parent": dir_row, "rows": count, "rows_listed": flag,
                                      "containers_mounting": num, "containers_not_inspected": num})},
    "D10.1": {"rc": num, "probe": fixed({"matches_declared": flag, "services": count,
                                         "figures_services": listed(PROBE_SERVICES)})},
    "D10.3": {"declared_apps": count, "installed_apps": count, "on_disk_apps": count, "units_not_counted": num,
              "on_disk_not_counted": num, "installed_equal_repo": keyed(APP_UNITS, flag),
              "apps": per_app({**_JOB, "runner_path_active": member(ACTIVE_STATES), "broker_user_groups": count,
                               "broker_unit": None, "runner_unit": None, "drop_in_paths": None, "sudo_rules": None})},
    "D10.4": {"containers": num, "containers_mounting_app_state": num, "containers_not_inspected": num,
              "apps": per_app({**_JOB, "layout_problems": count, "layout_reason": member(LAYOUT_REASONS)})},
    "D10.7": {"known_secrets_checked": num,
              "apps": per_app({**_JOB, "journal_counts": journal_counts, "note_counts": keyed(NOTE_WORDS, num),
                               "other_lines": num, "broker_journal": _LEAKS, "runner_journal": _LEAKS,
                               "journal_read": fixed({k: _READ for k in UNIT_LABELS}),
                               "oldest_entry_read": _BROKER_RUNNER, "first_entry": when,
                               "installed_since_last_pass": flag})},
    "D10.8": {"apps": per_app({**_JOB, "out_of_whitelist": num, "run/ok results": ("results", run_ok_results)})},
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


def _installed(items):
    """The jobs D10.3 lists as installed; none when that list was not read (the jobs' line says so)."""
    names = _data(items, "D10.3").get("installed_apps")
    return set(names) if _names(names) else set()


def _judged(items, iid):
    """(entries, why) for a per-job item. `entries`: one dict per job a closing line must judge:
    every job D10.3 lists as installed (an empty dict when this item has no entry for it, so it
    reads as not checked), and every other entry of this item but those that say the job is not
    installed (`installed` exactly false: declared, not installed yet; `every job is declared and
    installed` says so). `why`: the reason there is nothing to judge, in fixed words; "" when
    there is."""
    why = _shape(items, iid, "apps")
    if why:
        return [], why
    apps = _data(items, iid)["apps"]
    if not isinstance(apps, dict):
        return [], JOBS_NOT_READ
    must = _installed(items)
    entries = [e if isinstance(e, dict) else {} for app, e in apps.items()
               if app in must or not (isinstance(e, dict) and e.get("installed") is False)]
    entries += [{} for app in must if app not in apps]
    return entries, "" if entries else NO_INSTALLED_JOB


def _unchecked(entry):
    """A judged job with a value that is could-not-check, at any depth, or that does not say it is
    installed: no line may read ok over it."""
    return entry.get("installed") is not True or cnc_places(entry) > 0


def _each_job(items, iid, passes):
    """(ok, note, entries): ok only when there is a job to judge and every one of them was checked
    whole and passes; the note says how many do not, never which."""
    entries, why = _judged(items, iid)
    bad = sum(1 for e in entries if _unchecked(e) or not passes(e))
    note = (f" ({bad} of {len(entries)} jobs)" if bad else "") + why
    return not note, note, entries


def _unchecked_note(entries):
    n = sum(1 for e in entries if _unchecked(e))
    return f" ({n} of {len(entries)} installed jobs: a value could not be checked)" if n else ""


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


def _jobs_line(bundle, items):
    """The three lists of D10.3 agree: every job is declared and installed, none is only on disk,
    and nothing in the two listings was left uncounted."""
    text = "every job is declared and installed"
    why = _shape(items, "D10.3", "declared_apps")
    if why:
        return False, text + why
    d = _data(items, "D10.3")
    lists = [d.get(k) for k in ("declared_apps", "installed_apps", "on_disk_apps")]
    if not all(_names(names) for names in lists):
        return False, text + JOBS_NOT_READ
    declared, installed, on_disk = (set(names) for names in lists)
    entries, why = _judged(items, "D10.3")
    apps = d.get("apps")
    named = declared | installed | on_disk | (set(apps) if isinstance(apps, dict) else set())
    counts = ((len(declared - installed), "declared but not installed"),
              (len(installed - declared), "installed but not declared"),
              (len(on_disk - declared - installed), "on disk only"),
              (sum(1 for n in named if not is_app(n)), "with a name that is not a job name"))
    note = "".join(f" ({n} {what})" for n, what in counts if n) + _unchecked_note(entries)
    for key, what in (("units_not_counted", "unit lines not counted"), ("on_disk_not_counted", "entries on disk not counted")):
        if not _is(d.get(key), 0):
            note += f" ({num(d.get(key))} {what})"
    note += why if installed or why != NO_INSTALLED_JOB else ""
    note += "" if installed else NO_INSTALLED_JOB
    return not note, text + (note or f" ({len(installed)} {'job' if len(installed) == 1 else 'jobs'})")


def _refusals(bundle, items):
    def missing(entry):
        counts = entry.get("journal_counts")
        counts = counts if isinstance(counts, dict) else {}
        return [k for k in REFUSALS if not (_int(counts.get(k)) and counts.get(k) > 0)]
    ok, note, entries = _each_job(items, "D10.7", lambda e: not missing(e))
    absent = [k for k in REFUSALS if any(k in missing(e) for e in entries)]
    return ok, "the three live refusals are in the journal" + (f" (missing: {', '.join(absent)})" if absent else "") + note


def _run_ok_line(bundle, items):
    def has_one(entry):
        n = _run_ok(entry)
        return _int(n) and n > 0
    ok, note, _ = _each_job(items, "D10.8", has_one)
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


def _reach(bundle, items):
    """The journal's reach is D2.4's. A job installed since the last PASS has no 30 days of its
    own: it is said here (D10.7), and it does not turn the line. A job whose D10.7 values could
    not be checked does: whether it is new is one of them."""
    reach = _data(items, "D2.4").get("reach_days")
    ok = _int(reach) and reach >= 30
    note = ""
    if not ok:
        note = (f" (reach is {num(reach)} days: the evidence needs the date the retention was raised)"
                if _int(reach) else " (not read)")
    entries, why = _judged(items, "D10.7")
    new = sum(1 for e in entries if e.get("installed_since_last_pass") is True)
    if new:
        note += (" (1 job installed since the last PASS: judged from its first entry)" if new == 1 else
                 f" ({new} jobs installed since the last PASS: each judged from its first entry)")
    unread = _unchecked_note(entries) + (why if why == JOBS_NOT_READ else "")
    return ok and not unread, "the journal reaches 30 days" + note + unread


def _search(bundle, items):
    d = _data(items, "D2.3")
    scanned = d.get("scanned_characters")
    ok = _int(scanned) and scanned > 0 and _is(d.get("undecodable_characters"), 0) and is_time(d.get("oldest_entry_read"))
    return ok, "the journal search read everything it was given"


def _no_leaks(bundle, items):
    """Every leak count the checklist fails on, each read by the tool's own key names: a key the tool
    does not name is not read here (the item line counts it as an other key)."""
    def read(group, keys):
        return [group.get(key) if isinstance(group, dict) else None for key in keys]

    def of_job(entry):
        return read(entry.get("broker_journal"), LEAK_KEYS) + read(entry.get("runner_journal"), LEAK_KEYS)
    search = read(_data(items, "D2.3").get("journal"), SEARCH_KEYS)
    ok, jobs, entries = _each_job(items, "D10.7", lambda e: all(_is(c, 0) for c in of_job(e)))
    counts = search + [c for e in entries for c in of_job(e)]
    if jobs == NOT_READ:                                # the item itself: every count of it was not read
        counts, jobs = counts + [None], ""
    ok = ok and all(_is(c, 0) for c in counts)
    note = ""
    if any(_int(c) and c > 0 for c in counts):
        note = " (a count is above 0: this is a FAIL, not a reminder)"
    elif not all(_is(c, 0) for c in counts):
        note = " (a count was not read)"
    return ok, "no leak count above 0 (D2.3, D10.7)" + note + jobs


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


def _code(bundle, items):
    """The two fixed services and the broker of every INSTALLED job (by this item's list and by
    D10.3's): each with files checked and none newer than its start. The broker of a job that is declared and not installed has never
    started: it may be there, and is not judged. Any other key is not a service this tool knows."""
    text = "no service runs older code than the box holds"
    why = _shape(items, "D4.6", "apps_installed")
    if why:
        return False, text + why
    d = _data(items, "D4.6")
    declared, installed = d.get("apps_declared"), d.get("apps_installed")
    if not (_names(declared) and _names(installed)):
        return False, text + JOBS_NOT_READ
    judged = set(SERVICES) | {BROKER_PREFIX + app for app in set(installed) | _installed(items)}
    allowed = judged | {BROKER_PREFIX + app for app in declared}
    newer, checked = d.get("files_newer_than_start"), d.get("files_checked")
    ok = (isinstance(newer, dict) and isinstance(checked, dict) and set(newer) <= allowed and set(checked) <= allowed
          and all(is_service(s) for s in judged)
          and all(newer.get(s) == [] and _int(checked.get(s)) and checked[s] > 0 for s in judged))
    return ok, text


def _report_store(bundle, items):
    """D7.1's report store: a root:root 0700 directory that was listed, holding only folders of
    active clients, each root-owned 0700, listed, with nothing inside but 0600 files, and mounted
    by no container. Every fault is a count."""
    text = "the report store holds only owner-only client folders"
    why = _shape(items, "D7.1", "report_archive")
    if why:
        return False, text + (" (not in this bundle)" if why == OLDER_SHAPE else why)
    store = _data(items, "D7.1")["report_archive"]
    if not isinstance(store, dict):
        return False, text + NOT_READ
    notes = []
    parent = store.get("parent")
    if not isinstance(parent, dict):
        notes.append(f"the store is {member(DIR_WORDS)(parent)}")
    elif not (parent.get("owner") == "root" and parent.get("group") == "root" and parent.get("mode") == "0o700"):
        notes.append("the store is not root:root 0700")
    if store.get("rows_listed") is not True:
        notes.append("the store was not listed")
    rows = store.get("rows")
    if not isinstance(rows, list):
        notes.append("the folders were not read")
        rows = []
    rows = [r if isinstance(r, dict) else {} for r in rows]
    faults = (("not a folder", lambda r: r.get("kind") == "dir"),
              ("not active", lambda r: r.get("status") == "active"),
              ("not listed", lambda r: r.get("listed") is True),
              ("holding something that is not a file", lambda r: _is(r.get("not_files"), 0)),
              ("not root 0700", lambda r: r.get("owner") == "root" and r.get("mode") == "0o700"),
              ("with a file that is not 0600", lambda r: isinstance(r.get("files"), dict)
               and all(k.endswith(" 0o600") for k in r["files"])))
    for what, good in faults:
        n = sum(1 for r in rows if not good(r))
        if n:
            notes.append(f"{n} {what}")
    mounting, not_inspected = store.get("containers_mounting"), store.get("containers_not_inspected")
    if _int(mounting) and _int(not_inspected):
        notes += [f"{num(n)} {what}" for n, what in ((mounting, "containers mount it"),
                                                     (not_inspected, "containers not inspected")) if n != 0]
    else:
        notes.append("the containers could not be checked")
    return not notes, text + ("".join(f" ({n})" for n in notes)
                              or f" ({len(rows)} {'folder' if len(rows) == 1 else 'folders'})")


def _fingerprint(bundle, items):
    return _get(bundle, "fingerprint", "complete") is True, "fingerprint complete"


CHECKS = (_all_observed, _no_could_not_check, _jobs_line, _sshd_default, _refusals, _run_ok_line, _retention, _reach,
          _search, _no_leaks, _service, _on_disk, _no_other_directory_no_missing_days, _proxy, _code, _report_store,
          _fingerprint)


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
    lines = [f"collected_at {when(bundle.get('collected_at'))}",
             f"items {len(items)} | not observed: {', '.join(not_observed) or 'none'}",
             f"other items: {len(items) - len(ids)}", ""]
    for iid in ids:
        lines.append(f"{iid}  {status[iid]}")
        data = _data(items, iid)
        pairs, other = _fields(data, SCHEMA[iid]) if iid in SCHEMA else ([], 0)
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
