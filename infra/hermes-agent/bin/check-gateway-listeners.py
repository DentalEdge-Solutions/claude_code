#!/usr/bin/env python3
"""Periodic check of the gateway container's listening ports (finding F50). Stdlib only.

  sudo check-gateway-listeners.py                 one measurement (hermes-listener-check.service)
  sudo check-gateway-listeners.py --status        the last result and the history's counts; read-only
  sudo check-gateway-listeners.py --clear-alert   remove the ALERT marker once it is explained

The security review measures the gateway's listeners (D4.1) only when a review runs. Hermes
v0.21.5 opened an API server on port 8642 by default (F44), and the two controls that keep it
off live in files the gateway can write. This check repeats the measurement between reviews.

It RECORDS ONLY (operator decision, 2026-10-07): it stops nothing and flips no switch. Each run
writes, under STATE_DIR (root 0700, files 0600):
  last.json       the latest result
  history.jsonl   one line per run, kept to the last HISTORY_KEEP lines
  alerts.jsonl    one line per alert EVENT (a new alert, or a change in what is unexpected) and
                  per --clear-alert, appended and NEVER trimmed: an alert that was cleared must
                  still be there for a review held months later
  ALERT           created at the first alert and never overwritten; removed by --clear-alert
and prints one line, which the journal keeps. Exit 0 ok, 1 alert, 2 could-not-check (also for
anything unexpected in the check itself: only a measured alert exits 1).

On an alert the marker and the alert log are written FIRST, before the files a damaged history
could stop it reaching. A run and --clear-alert take one lock, so neither loses the other's line.

WHERE THE MEASUREMENT COMES FROM. Not from inside the container: the gateway controls its own
filesystem, so a `cat` run there (`docker exec`, as the review's D4.1 does, F35) could be made to
lie. This check asks Docker for the container's init pid and reads /proc/<pid>/net/tcp and tcp6
ON THE HOST: the host kernel's view of that network namespace, with no program of the
container's run. It asks for the pid again afterwards, and a different answer (the gateway
restarted meanwhile, so the pid may now be another process's) is could-not-check. D4.5 compares
this result with D4.1's, so the two sources check each other.

WHAT IT CANNOT SEE (known limits, in the findings document): it judges port NUMBERS, so another
program listening on an allowed port (9119) passes; anything bound to Docker's DNS address is
counted as the resolver, and only a count other than 1 is an alert; UDP and unix sockets are not
looked at; and a listener that opens and closes between two runs is missed.

Nothing it writes or prints carries an address or any other field of /proc/net/tcp: ports, one
count, fixed words and timestamps only. A gateway that is not running is could-not-check, never
an alert: nothing is listening in a container that does not exist.
"""
import argparse, contextlib, datetime, fcntl, json, os, stat, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gateway_listeners as GL

STATE_DIR = "/var/lib/hermes/listener-check"
HISTORY_KEEP = 3000                 # about a month at four runs an hour
MAX_AGE_SECONDS = 45 * 60           # three missed runs: the timer is not doing its job
OK, ALERT, COULD_NOT_CHECK, CLEARED = "ok", "alert", "could-not-check", "alert-cleared"
EXIT = {OK: 0, ALERT: 1, COULD_NOT_CHECK: 2}
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _run_real(argv, timeout=15):       # three calls a run: well inside the unit's TimeoutStartSec=60
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 124, "", ""
    return p.returncode, p.stdout, p.stderr


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime(TS_FMT)


def _read_tables(pid):
    """The two tables of the network namespace process `pid` is in, read on the host."""
    text = ""
    for table in ("tcp", "tcp6"):
        with open(f"/proc/{pid}/net/{table}", encoding="ascii", errors="replace") as f:
            text += f.read()
    return text


def _gateway_pid(run, gw):
    """The running gateway container's init pid, as Docker reports it; None when it has none."""
    rc, out, _ = run(["docker", "inspect", "--format", "{{.State.Pid}} {{.State.Running}}", gw])
    parts = out.split()
    if rc != 0 or len(parts) != 2 or parts[1] != "true" or not parts[0].isdigit() or int(parts[0]) < 2:
        return None
    return int(parts[0])


def measure(run=_run_real, read_tables=_read_tables):
    """One measurement: {status, listeners, unexpected, docker_dns_listeners, reason}. `reason` is
    a fixed word: `-`, `unexpected-port`, `docker-dns`, `no-gateway`, `no-pid`, `proc-unreadable`,
    `gateway-changed`, `unparsable`."""
    blank = {"listeners": COULD_NOT_CHECK, "unexpected": COULD_NOT_CHECK, "docker_dns_listeners": COULD_NOT_CHECK}
    rc, out, _ = run(["docker", "ps", "-q", "--no-trunc", "--filter", GL.GATEWAY_FILTER])
    gw = out.strip()
    if rc != 0 or len(gw) != 64:            # none, or more than one: there is no ONE gateway to look into
        return {"status": COULD_NOT_CHECK, "reason": "no-gateway", **blank}
    pid = _gateway_pid(run, gw)
    if pid is None:
        return {"status": COULD_NOT_CHECK, "reason": "no-pid", **blank}
    try:
        text = read_tables(pid)
    except OSError:
        return {"status": COULD_NOT_CHECK, "reason": "proc-unreadable", **blank}
    if _gateway_pid(run, gw) != pid:        # it restarted while we read: that pid may be anything now
        return {"status": COULD_NOT_CHECK, "reason": "gateway-changed", **blank}
    try:
        ports, dns = GL.parse(text)
    except ValueError:
        return {"status": COULD_NOT_CHECK, "reason": "unparsable", **blank}
    unexpected = [p for p in ports if p not in GL.ALLOWED_PORTS]
    if unexpected:
        status, reason = ALERT, "unexpected-port"
    elif dns != 1:                          # another process can bind Docker's DNS address
        status, reason = ALERT, "docker-dns"
    else:
        status, reason = OK, "-"
    return {"status": status, "reason": reason, "listeners": ports, "unexpected": unexpected,
            "docker_dns_listeners": dns}


def _write(path, text, exclusive=False):
    """Write `text` to `path`, mode 0600. Atomic (a temporary file renamed over it) unless
    `exclusive`, which creates the file and fails when it exists."""
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _lines(path):
    """A log's lines as written, oldest first; [] when there is no file yet. A byte that is not
    UTF-8 is replaced, never an error: one damaged line must not stop an alert being recorded."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [l for l in f.read().splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def _history(state_dir):
    return _lines(os.path.join(state_dir, "history.jsonl"))


def _alert_log(state_dir):
    return _lines(os.path.join(state_dir, "alerts.jsonl"))


def _append_history(state_dir, entry):
    lines = _history(state_dir) + [json.dumps(entry, sort_keys=True)]
    _write(os.path.join(state_dir, "history.jsonl"), "\n".join(lines[-HISTORY_KEEP:]) + "\n")


def _append_alert_log(state_dir, entry):
    """One line appended (O_APPEND: nothing already there is rewritten) and synced. Never trimmed
    (the history is): what a review reads to learn that something listened and was cleared since
    the last one, however long ago."""
    fd = os.open(os.path.join(state_dir, "alerts.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _last_alert_event(state_dir):
    """What the alert log's last line says is unexpected, or None when its last line is not an alert."""
    lines = _alert_log(state_dir)
    try:
        e = json.loads(lines[-1]) if lines else {}
    except ValueError:
        return None
    if not isinstance(e, dict) or e.get("status") != ALERT:
        return None
    return (e.get("reason"), e.get("unexpected"), e.get("docker_dns_listeners"))


def _prepare(state_dir):
    """The state directory: a real directory (never a symlink), mode 0700. Raises OSError."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    st = os.lstat(state_dir)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise NotADirectoryError(state_dir)
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(state_dir, 0o700)


@contextlib.contextmanager
def _locked(state_dir):
    """One writer at a time: a timer run and --clear-alert must not lose each other's line."""
    fd = os.open(os.path.join(state_dir, ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def record(state_dir, result, ts):
    """Keep one result. On an alert, FIRST the ALERT marker (created once, never overwritten) and
    the alert log (a line when the alert is new or what is unexpected changed), THEN last.json and
    the history: the two that matter most do not wait behind a file that may be damaged."""
    _prepare(state_dir)
    entry = {"ts": ts, **result}
    with _locked(state_dir):
        if result["status"] == ALERT:
            try:
                _write(os.path.join(state_dir, "ALERT"), json.dumps(
                    {"since": ts, "reason": result["reason"], "unexpected": result["unexpected"],
                     "docker_dns_listeners": result["docker_dns_listeners"]}, sort_keys=True) + "\n",
                    exclusive=True)
            except FileExistsError:
                pass                        # the FIRST alert is the one that is kept
            if _last_alert_event(state_dir) != (result["reason"], result["unexpected"], result["docker_dns_listeners"]):
                _append_alert_log(state_dir, entry)
        _write(os.path.join(state_dir, "last.json"), json.dumps(entry, sort_keys=True) + "\n")
        _append_history(state_dir, entry)


def clear_alert(state_dir, ts):
    """Remove the ALERT marker. The clearing is logged BEFORE the marker goes, so a marker never
    disappears without a line saying so. False when there is no marker."""
    _prepare(state_dir)
    with _locked(state_dir):
        if not os.path.lexists(os.path.join(state_dir, "ALERT")):
            return False
        entry = {"ts": ts, "status": CLEARED}
        _append_alert_log(state_dir, entry)
        _append_history(state_dir, entry)
        os.unlink(os.path.join(state_dir, "ALERT"))
    return True


def line(result):
    return ("hermes-listener-check: status={status} reason={reason} listeners={listeners} "
            "unexpected={unexpected} docker_dns_listeners={docker_dns_listeners}").format(
        **{k: json.dumps(v) if isinstance(v, list) else v for k, v in result.items()})


def _load(path):
    """A JSON object from `path`: None when the file is absent, COULD_NOT_CHECK when it cannot be
    read or is not a JSON object."""
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return COULD_NOT_CHECK
    return obj if isinstance(obj, dict) else COULD_NOT_CHECK


def _age_seconds(ts, now):
    try:
        then = datetime.datetime.strptime(ts, TS_FMT)
        return int((datetime.datetime.strptime(now, TS_FMT) - then).total_seconds())
    except (TypeError, ValueError):
        return COULD_NOT_CHECK


def summary(state_dir, now):
    """What --status prints and what the review's D4.5 reports: the last result, its age, the
    alert marker and the history's counts by status. A missing piece is None (never run, no
    alert); an unreadable one is COULD_NOT_CHECK."""
    last = _load(os.path.join(state_dir, "last.json"))
    alert = _load(os.path.join(state_dir, "ALERT"))
    counts = {}
    try:
        for l in _history(state_dir):
            try:
                status = json.loads(l).get("status", "?")
            except (ValueError, AttributeError):
                status = "?"
            status = status if isinstance(status, str) else "?"
            counts[status] = counts.get(status, 0) + 1
    except OSError:
        counts = COULD_NOT_CHECK
    try:
        log = {"alert": 0, "alert-cleared": 0, "?": 0, "first_ts": None, "last_ts": None}
        for l in _alert_log(state_dir):
            try:
                e = json.loads(l)
                status, ts = e.get("status"), e.get("ts")
            except (ValueError, AttributeError):
                status, ts = "?", None
            log[status if status in (ALERT, CLEARED) else "?"] += 1
            if isinstance(ts, str):
                log["first_ts"] = log["first_ts"] or ts
                log["last_ts"] = ts
    except OSError:
        log = COULD_NOT_CHECK
    return {"last": last,
            "last_age_seconds": _age_seconds(last.get("ts"), now) if isinstance(last, dict) else
            (None if last is None else COULD_NOT_CHECK),
            "alert_present": alert is not None, "alert": alert, "history_counts": counts,
            "alert_log": log}


def healthy(s):
    """True only when the last result is `ok`, it is recent (a negative age, a clock that went
    back, is not), and no alert is waiting."""
    return (isinstance(s["last"], dict) and s["last"].get("status") == OK
            and isinstance(s["last_age_seconds"], int) and 0 <= s["last_age_seconds"] < MAX_AGE_SECONDS
            and not s["alert_present"])


def main(argv=None, run=_run_real, state_dir=STATE_DIR, now=None, read_tables=_read_tables):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--clear-alert", action="store_true")
    a = ap.parse_args(argv)
    now = now or utc_now()
    try:
        if a.status:
            s = summary(state_dir, now)
            print(json.dumps(s, indent=2, sort_keys=True))
            print("listener check: " + ("OK" if healthy(s) else "LOOK AT THIS (last result not ok, too old, or an alert is waiting)"))
            return 0 if healthy(s) else 1
        if a.clear_alert:
            print("hermes-listener-check: " + ("alert cleared" if clear_alert(state_dir, now) else "no alert to clear"))
            return 0
        result = measure(run, read_tables)
        record(state_dir, result, now)
        print(line(result))
        return EXIT[result["status"]]
    except Exception as e:                  # exit 1 means a MEASURED alert, and nothing else
        print(f"hermes-listener-check: status=could-not-check reason=internal-error error={type(e).__name__}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
