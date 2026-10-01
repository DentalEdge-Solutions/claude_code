#!/usr/bin/env python3
"""Root runner for one chat-trigger app (Option B spec 2026-09-30 §3.4). Stdlib only.

  hermes-app-runner.py --app ads-audit        (systemd: hermes-app-runner@ads-audit, a oneshot
                                               started by hermes-app-runner@ads-audit.path)

The ONLY root code Option B adds. It reads only job files the broker user wrote, never the
spool. It executes exactly [manifest.command, <slug>, *manifest.ops[op].args] — no shell, the
slug one argv element — after moving the job into running/. Anything found in running/ at
start was cut off by a crash or reboot: it becomes an `interrupted` done file and is NEVER
re-run. Done files are root:<app user> 0640 in the broker-owned done/ dir."""
import argparse, os, pwd, signal, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A

KILL_GRACE = 90   # run-client-audit needs time after SIGTERM to stop the proxy and remove containers (part 1 final fix, cleanup bounded at 20 s per call)
SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def _execute(argv, timeout):
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, env=SAFE_ENV,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(timeout=KILL_GRACE)
                break
            except subprocess.TimeoutExpired:
                continue
        p.stdout.close()
        return None, "", True
    return p.returncode, out[:A.MAX_STDOUT].decode("utf-8", "replace"), False


def _done(state, job_id, rc, stdout, timed_out, interrupted, owner):
    uid, gid = owner if owner else (None, None)
    A.write_json_atomic(os.path.join(state, "done"), job_id + ".json",
                        {"job_id": job_id, "rc": rc, "stdout": stdout, "timed_out": timed_out,
                         "interrupted": interrupted}, mode=0o640, uid=uid, gid=gid)


def _oldest(d):
    names = [n for n in os.listdir(d) if A.FILENAME_RE.fullmatch(n)]   # fullmatch: `$` alone admits "…json\n"
    return sorted(names, key=lambda n: os.lstat(os.path.join(d, n)).st_mtime)


def run_all(manifest, state, execute=_execute, owner=None):
    jobs, running = os.path.join(state, "jobs"), os.path.join(state, "running")
    for n in _oldest(running):                              # cut off earlier: report, never re-run
        _done(state, n[:-5], None, "", False, True, owner)
        os.unlink(os.path.join(running, n))
    while True:
        names = _oldest(jobs)
        if not names:
            return
        n = names[0]
        p = os.path.join(jobs, n)
        try:
            job = A.parse_job(A.read_capped(p, A.MAX_JOB_BYTES), n)
        except A.Refused:
            _done(state, n[:-5], None, "", False, False, owner)   # the broker maps this to internal
            os.unlink(p)
            continue
        os.rename(p, os.path.join(running, n))              # moved BEFORE executing (broker recover)
        op = manifest.ops[job["op"]] if job["op"] in manifest.ops else None
        rc, out, timed_out = None, "", False
        if op is not None:
            try:
                rc, out, timed_out = execute([manifest.command, job["client"]] + list(op["args"]),
                                             op["timeout"])
            except Exception:                               # e.g. the command is missing: a failed
                rc, out, timed_out = None, "", False        # done, never a job stuck in running/
        _done(state, job["job_id"], rc, out, timed_out, False, owner)   # done BEFORE the unlink
        os.unlink(os.path.join(running, n))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/hermes-agent/registry/apps")
    ap.add_argument("--state-root", default="/var/lib/hermes/app-state")
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    pw = pwd.getpwnam(m.user)
    run_all(m, A.state_dir(a.app, a.state_root), owner=(0, pw.pw_gid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
