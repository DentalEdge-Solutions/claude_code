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
  ALERT           created at the first alert and never overwritten; removed by --clear-alert
and prints one line, which the journal keeps. Exit 0 ok, 1 alert, 2 could-not-check.

Nothing it writes or prints carries an address or any other field of /proc/net/tcp: ports, one
count, fixed words and timestamps only. A gateway that is not running is could-not-check, never
an alert: nothing is listening in a container that does not exist.
"""
import argparse, datetime, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gateway_listeners as GL

STATE_DIR = "/var/lib/hermes/listener-check"
HISTORY_KEEP = 3000                 # about a month at four runs an hour
MAX_AGE_SECONDS = 45 * 60           # three missed runs: the timer is not doing its job
OK, ALERT, COULD_NOT_CHECK, CLEARED = "ok", "alert", "could-not-check", "alert-cleared"
EXIT = {OK: 0, ALERT: 1, COULD_NOT_CHECK: 2}
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _run_real(argv, timeout=30):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 124, "", ""
    return p.returncode, p.stdout, p.stderr


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime(TS_FMT)


def measure(run=_run_real):
    """One measurement: {status, listeners, unexpected, docker_dns_listeners, reason}. `reason` is
    a fixed word: `-`, `unexpected-port`, `docker-dns`, `no-gateway`, `exec-failed`, `unparsable`."""
    blank = {"listeners": COULD_NOT_CHECK, "unexpected": COULD_NOT_CHECK, "docker_dns_listeners": COULD_NOT_CHECK}
    rc, out, _ = run(["docker", "ps", "-q", "--no-trunc", "--filter", GL.GATEWAY_FILTER])
    gw = out.strip()
    if rc != 0 or len(gw) != 64:            # none, or more than one: there is no ONE gateway to look into
        return {"status": COULD_NOT_CHECK, "reason": "no-gateway", **blank}
    rc, out, _ = run(["docker", "exec", gw, "cat", *GL.PROC_TABLES])
    if rc != 0:
        return {"status": COULD_NOT_CHECK, "reason": "exec-failed", **blank}
    try:
        ports, dns = GL.parse(out)
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


def _history(state_dir):
    """The history's lines as written, oldest first; [] when there is no history yet."""
    try:
        with open(os.path.join(state_dir, "history.jsonl"), encoding="utf-8") as f:
            return [l for l in f.read().splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def _append(state_dir, entry):
    lines = _history(state_dir) + [json.dumps(entry, sort_keys=True)]
    _write(os.path.join(state_dir, "history.jsonl"), "\n".join(lines[-HISTORY_KEEP:]) + "\n")


def record(state_dir, result, ts):
    """Keep one result: last.json, one history line and, at the first alert, the ALERT marker."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    entry = {"ts": ts, **result}
    _write(os.path.join(state_dir, "last.json"), json.dumps(entry, sort_keys=True) + "\n")
    _append(state_dir, entry)
    if result["status"] == ALERT:
        try:
            _write(os.path.join(state_dir, "ALERT"), json.dumps(
                {"since": ts, "reason": result["reason"], "unexpected": result["unexpected"],
                 "docker_dns_listeners": result["docker_dns_listeners"]}, sort_keys=True) + "\n",
                exclusive=True)
        except FileExistsError:
            pass                            # the FIRST alert is the one that is kept


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
    return {"last": last,
            "last_age_seconds": _age_seconds(last.get("ts"), now) if isinstance(last, dict) else
            (None if last is None else COULD_NOT_CHECK),
            "alert_present": alert is not None, "alert": alert, "history_counts": counts}


def healthy(s):
    """True only when the last result is `ok`, it is recent, and no alert is waiting."""
    return (isinstance(s["last"], dict) and s["last"].get("status") == OK
            and isinstance(s["last_age_seconds"], int) and 0 <= s["last_age_seconds"] <= MAX_AGE_SECONDS
            and not s["alert_present"])


def main(argv=None, run=_run_real, state_dir=STATE_DIR, now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--clear-alert", action="store_true")
    a = ap.parse_args(argv)
    now = now or utc_now()
    if a.status:
        s = summary(state_dir, now)
        print(json.dumps(s, indent=2, sort_keys=True))
        print("listener check: " + ("OK" if healthy(s) else "LOOK AT THIS (last result not ok, too old, or an alert is waiting)"))
        return 0 if healthy(s) else 1
    if a.clear_alert:
        try:
            os.unlink(os.path.join(state_dir, "ALERT"))
        except FileNotFoundError:
            print("hermes-listener-check: no alert to clear")
            return 0
        _append(state_dir, {"ts": now, "status": CLEARED})
        print("hermes-listener-check: alert cleared")
        return 0
    result = measure(run)
    record(state_dir, result, now)
    print(line(result))
    return EXIT[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
