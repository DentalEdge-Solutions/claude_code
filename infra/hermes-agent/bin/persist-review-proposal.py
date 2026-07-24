#!/usr/bin/env python3
"""Persist a synthesized review proposal via save-proposal.py.

Reads proposal markdown from --content-file, or from the latest completed
synthesize task in the Kanban DB (source-resilient: task.result → run.summary →
run.metadata.proposal_markdown), and pipes it to save-proposal.py.
Content-agnostic; never executes the content.

Usage:  persist-review-proposal.py --project claude_code [--content-file <path>]
Env:    HERMES_KANBAN_DB  Kanban DB path (default /opt/data/kanban.db)
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE = os.path.join(HERE, "save-proposal.py")
DEFAULT_KANBAN_DB = "/opt/data/kanban.db"


def kanban_db():
    return os.environ.get("HERMES_KANBAN_DB", DEFAULT_KANBAN_DB)


def read_content_file(path):
    if not os.path.isfile(path):
        print(f"persist-review-proposal: no such content file: {path}", file=sys.stderr)
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _row_content(row):
    """Best proposal text on a completed-synthesize row, in priority order:
    the task result, then the run summary, then metadata.proposal_markdown.
    Returns (content, metadata_project) or (None, None). Source-resilient so
    it works however the synthesizer worker returned its proposal."""
    for key in ("result", "summary"):
        val = row[key] if key in row.keys() else None
        if isinstance(val, str) and val.strip():
            return val, None
    raw = row["metadata"] if "metadata" in row.keys() else None
    if raw:
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            meta = {}
        pm = meta.get("proposal_markdown")
        if isinstance(pm, str) and pm.strip():
            return pm, meta.get("project")
    return None, None


def _project_match(body, metadata_project, project):
    if metadata_project == project:
        return True
    return bool(body) and f"Project: {project}" in body


def read_content_db(project):
    path = kanban_db()
    if not os.path.isfile(path):
        print(f"persist-review-proposal: no such kanban DB: {path}", file=sys.stderr)
        return None

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT t.body AS body, t.result AS result,
                   r.summary AS summary, r.metadata AS metadata
            FROM tasks t
            LEFT JOIN task_runs r ON r.task_id = t.id
            WHERE t.title = 'synthesize'
              AND t.status IN ('done', 'completed')
            ORDER BY
                COALESCE(r.ended_at, t.completed_at, r.started_at, t.created_at, 0) DESC,
                r.id DESC
            """
        ).fetchall()
    except sqlite3.Error as e:
        print(f"persist-review-proposal: could not read kanban DB: {e}", file=sys.stderr)
        return None
    finally:
        conn.close()

    fallback = None
    for row in rows:
        content, meta_project = _row_content(row)
        if content is None:
            continue
        if _project_match(row["body"], meta_project, project):
            return content
        if fallback is None:
            fallback = content

    if fallback is not None:
        return fallback
    print("persist-review-proposal: no completed synthesize proposal found", file=sys.stderr)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--content-file")
    args = ap.parse_args(argv)

    content = read_content_file(args.content_file) if args.content_file else read_content_db(args.project)
    if content is None:
        return 1

    out = subprocess.run([sys.executable, SAVE, "--project", args.project],
                         input=content, capture_output=True, text=True)
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    return out.returncode


if __name__ == "__main__":
    sys.exit(main())
