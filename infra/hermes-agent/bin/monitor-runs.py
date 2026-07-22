#!/usr/bin/env python3
"""Monitor Hermes cron runs of Claude Code operator workflows (read-only).

Joins cron job definitions (jobs.json), durable execution history
(executions.db), and per-run output reports into one status digest — so you can
see, from the Hermes side, what scheduled/triggered workflows did.

Usage (inside the container):
  python3 /opt/cc-bin/monitor-runs.py            # digest of all jobs + recent runs
  python3 /opt/cc-bin/monitor-runs.py --json     # machine-readable JSON
  python3 /opt/cc-bin/monitor-runs.py --job NAME # filter to one job (name or id)
  python3 /opt/cc-bin/monitor-runs.py --limit N  # recent executions per job (default 5)
"""
import argparse
import json
import os
import sqlite3
from datetime import datetime

CRON = os.environ.get("HERMES_CRON_DIR", "/opt/data/cron")
JOBS = os.path.join(CRON, "jobs.json")
DB = os.path.join(CRON, "executions.db")
OUT = os.path.join(CRON, "output")


def load_jobs():
    try:
        return json.load(open(JOBS)).get("jobs", [])
    except Exception:
        return []


def executions(job_id, limit):
    if not os.path.exists(DB):
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT status, started_at, finished_at, error, source "
            "FROM executions WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def duration(a, b):
    try:
        d = datetime.fromisoformat(b) - datetime.fromisoformat(a)
        return f"{d.total_seconds():.0f}s"
    except Exception:
        return "-"


def latest_report(job_id):
    d = os.path.join(OUT, job_id)
    try:
        files = sorted(os.listdir(d), reverse=True)
        return os.path.join(d, files[0]) if files else None
    except Exception:
        return None


def build(job, limit):
    jid = job.get("id")
    return {
        "name": job.get("name"),
        "id": jid,
        "state": job.get("state") or ("active" if job.get("enabled") else "paused"),
        "schedule": job.get("schedule_display") or (job.get("schedule") or {}).get("display"),
        "skill": job.get("skill") or (job.get("skills") or [None])[0],
        "workdir": job.get("workdir"),
        "last_status": job.get("last_status"),
        "last_run_at": job.get("last_run_at"),
        "next_run_at": job.get("next_run_at"),
        "model": job.get("model_snapshot"),
        "provider": job.get("provider_snapshot"),
        "latest_report": latest_report(jid),
        "runs": [
            {**e, "duration": duration(e.get("started_at"), e.get("finished_at"))}
            for e in executions(jid, limit)
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--job", help="filter to one job by name or id")
    ap.add_argument("--limit", type=int, default=5, help="recent executions per job")
    args = ap.parse_args()

    jobs = load_jobs()
    if args.job:
        jobs = [j for j in jobs if args.job in (j.get("name"), j.get("id"))]
    data = [build(j, args.limit) for j in jobs]

    if args.json:
        print(json.dumps(data, indent=2))
        return

    if not data:
        print("No cron jobs registered.")
        return
    for d in data:
        flag = "●" if d["state"] == "active" else "‖"
        print(f"\n{flag} {d['name']}  [{d['state']}]  ({d['id']})")
        print(f"   schedule: {d['schedule']}   skill: {d['skill']}   model: {d['provider']}/{d['model']}")
        print(f"   workdir:  {d['workdir']}")
        print(f"   last: {d['last_status']} @ {d['last_run_at']}   next: {d['next_run_at']}")
        if d["latest_report"]:
            print(f"   report:   {d['latest_report']}")
        for r in d["runs"]:
            err = f"  ERROR: {r['error']}" if r.get("error") else ""
            print(f"     - {r['status']:10} {r.get('started_at', '?')} ({r['duration']}) src={r.get('source')}{err}")


if __name__ == "__main__":
    main()
