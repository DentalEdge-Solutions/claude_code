#!/usr/bin/env python3
"""Run an allow-listed READ-ONLY Google Ads reporting script for a registered project.

Operator-invoked (credentials injected per-invocation by run-ads-report.sh via
`docker compose exec -e`). Executes ONLY scripts named in the project's
read_execute allow-list, under the pinned /opt/ads-venv interpreter, and scrubs
all six GOOGLE_ADS_* credential values from captured output before persisting.
STDLIB ONLY. Never writes the :ro project mount; writes only under /opt/data.
See docs/superpowers/specs/2026-08-03-hermes-ads-read-execute-design.md
"""
import argparse, datetime, os, re, shutil, subprocess, sys, tempfile

DEFAULT_REGISTRY = "/opt/registry/projects.yaml"
DEFAULT_REPORTS = "/opt/data/reports"
CRED_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
             "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")


def registry_path():
    return os.environ.get("ADS_REGISTRY") or (
        DEFAULT_REGISTRY if os.path.exists(DEFAULT_REGISTRY)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registry", "projects.yaml"))


def reports_dir():
    return os.environ.get("REPORTS_DIR", DEFAULT_REPORTS)


def _strip_inline_comment(stripped):
    """Remove a trailing inline YAML comment (# preceded by whitespace).

    A '#' flush against a value (no preceding whitespace) is part of the value,
    not a comment, per YAML inline-comment semantics.
    """
    return re.sub(r"\s+#.*$", "", stripped)


def read_workdir(path, project):
    """Stdlib line-parser for projects.<project>.workdir."""
    cur = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = _strip_inline_comment(line.strip())
            if indent == 2 and stripped.endswith(":"):
                cur = stripped[:-1]
            elif indent == 4 and cur == project and stripped.startswith("workdir:"):
                return stripped.split(":", 1)[1].strip()
    raise SystemExit(f"run-ads-report: no workdir for project {project!r}")


def read_read_execute(path, project):
    """Stdlib line-parser for projects.<project>.read_execute {runner, script_dir, allow[]}.

    Scope discipline mirrors the Inc-2 review fix: ANY sibling/shallower line closes
    the read_execute scope, so a later sibling key cannot bleed into `allow`.
    """
    cur = None
    in_re = False
    in_allow = False
    got = {"allow": []}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = _strip_inline_comment(line.strip())
            if indent == 2 and stripped.endswith(":"):        # a project name
                cur = stripped[:-1]; in_re = False; in_allow = False
            elif indent == 4 and cur == project and stripped == "read_execute:":
                in_re = True; in_allow = False
            elif indent <= 4:                                  # any sibling/shallower closes scope
                in_re = False; in_allow = False
            elif indent == 6 and in_re and cur == project:
                if stripped == "allow:":
                    in_allow = True
                else:
                    in_allow = False
                    k, _, v = stripped.partition(":")
                    got[k.strip()] = v.strip()
            elif indent == 8 and in_allow and in_re and cur == project and stripped.startswith("- "):
                got["allow"].append(stripped[2:].strip())
    if not got.get("runner") or not got.get("script_dir") or not got["allow"]:
        raise SystemExit(f"run-ads-report: no read_execute(runner,script_dir,allow) for project {project!r}")
    return {"runner": got["runner"], "script_dir": got["script_dir"], "allow": got["allow"]}


def resolve_report(cfg, report):
    if os.path.basename(report) != report:                    # reject path separators / traversal
        raise SystemExit(f"run-ads-report: --report must be a bare name, got {report!r}")
    if report not in cfg["allow"]:
        raise SystemExit(f"run-ads-report: report {report!r} not in read_execute allow-list "
                         f"{cfg['allow']} — readers only; mutators are never allow-listed")
    return report


def _scrub(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def build_plan(project, report):
    workdir = read_workdir(registry_path(), project)
    cfg = read_read_execute(registry_path(), project)
    resolve_report(cfg, report)
    script = os.path.join(workdir, cfg["script_dir"], report + ".py")
    return {"workdir": workdir, "runner": cfg["runner"], "script": script,
            "report": report, "project": project}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    plan = build_plan(args.project, args.report)
    if args.dry_run:
        print(f"project: {plan['project']}")
        print(f"runner:  {plan['runner']}")
        print(f"script:  {plan['script']}")
        print(f"report:  {plan['report']}")
        print(f"writes:  {os.path.join(reports_dir(), plan['project'])}/<ts>-{plan['report']}.md")
        return 0
    return run_report(plan, datetime.datetime.now(datetime.timezone.utc))  # noqa: F821 (Task 4)


if __name__ == "__main__":
    sys.exit(main())
