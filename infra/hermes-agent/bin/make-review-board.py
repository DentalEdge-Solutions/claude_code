#!/usr/bin/env python3
"""Create the fixed Kanban review-board shape for a project (deterministic).

--dry-run prints the planned tasks as JSON (testable, no writes). Live mode
shells `hermes kanban create` for each task. No LLM decomposition.

Usage:  make-review-board.py --project claude_code [--dry-run] [--max-runtime 20m]
"""
import argparse
import json
import os
import subprocess
import sys

ANALYSES = [
    ("analyze-architecture", "architect"),
    ("analyze-tests", "test-analyst"),
    ("analyze-risks", "risk-analyst"),
]
SKILL = "claude-code-reviewer"
DEFAULT_KANBAN_DB = "/opt/data/kanban.db"
DEFAULT_REGISTRY = "/opt/registry/projects.yaml"


def registry_path():
    if os.path.exists(DEFAULT_REGISTRY):
        return DEFAULT_REGISTRY
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "registry", "projects.yaml"))


def resolve_workdir(project):
    path = registry_path()
    current = None
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip()
                if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
                    current = line.strip()[:-1]
                elif current == project and line.startswith("    workdir:"):
                    return line.split(":", 1)[1].strip()
    except OSError as e:
        raise SystemExit(f"project registry unreadable: {path}: {e}")
    raise SystemExit(f"project not registered: {project}")


def kanban_db():
    return os.environ.get("HERMES_KANBAN_DB", DEFAULT_KANBAN_DB)


def plan(project, max_runtime, workdir=None):
    target = workdir or project
    tasks = []
    for title, assignee in ANALYSES:
        dimension = title.split("-", 1)[1]
        tasks.append({"title": title, "assignee": assignee, "parents": [],
                      "workspace": "scratch", "skill": SKILL,
                      "max_runtime": max_runtime,
                      "body": f"MODE: analysis. Project: {project}. "
                              f"Workdir: {target}. Analyze the '{dimension}' "
                              f"dimension read-only."})
    tasks.append({"title": "synthesize", "assignee": "synthesizer",
                  "parents": [t for t, _ in ANALYSES], "workspace": "scratch",
                  "skill": SKILL, "max_runtime": max_runtime,
                  "body": f"MODE: synthesis. Project: {project}. Workdir: {target}. "
                          f"Fuse the three parent handoffs into one prioritized proposal."})
    return tasks


def create(task, env, parent_ids=()):
    # --json gives a reliable task id; --parent (repeatable) creates the
    # synthesize card already gated (status=todo), auto-promoting to ready only
    # when every parent is done — the native Kanban fan-in. (Creating parent-less
    # then linking would leave it 'ready' immediately and run early.)
    cmd = ["hermes", "kanban", "create", task["title"],
           "--assignee", task["assignee"], "--workspace", task["workspace"],
           "--skill", task["skill"], "--max-runtime", task["max_runtime"],
           "--body", task["body"], "--json"]
    for pid in parent_ids:
        cmd += ["--parent", pid]
    out = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise SystemExit(f"kanban create failed for {task['title']}: {out.stderr}")
    try:
        return json.loads(out.stdout)["id"]
    except (ValueError, KeyError) as e:
        raise SystemExit(f"could not parse task id for {task['title']}: {e}\n{out.stdout}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-runtime", default="20m")
    args = ap.parse_args(argv)

    workdir = resolve_workdir(args.project)
    tasks = plan(args.project, args.max_runtime, workdir)
    if args.dry_run:
        print(json.dumps(tasks, indent=2))
        return 0

    env = os.environ.copy()
    env["HERMES_KANBAN_DB"] = kanban_db()
    # 1) the three analyses (parallel, no parents → start 'ready').
    ids = {}
    for t in tasks[:-1]:
        ids[t["title"]] = create(t, env)
    # 2) the synthesizer, created WITH its parents → starts 'todo', auto-promotes
    #    only when all three analyses are done (native fan-in; no post-hoc link).
    syn = tasks[-1]
    syn_parent_ids = [ids[title] for title in syn["parents"]]
    syn_id = create(syn, env, parent_ids=syn_parent_ids)
    print(f"created review board for {args.project}: {list(ids.values()) + [syn_id]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
