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
# Values scrubbed from captured output. The two *_CUSTOMER_ID vars are account
# IDENTIFIERS (not secrets — they appear in Google Ads URLs and the account name
# already identifies the client), so they are deliberately EXCLUDED: scrubbing them
# masked useful report context as `***` and could false-scrub any unrelated 10-digit
# number in a report. The four real secrets stay scrubbed.
SECRET_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
               "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")


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


_RUNTIME_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
                     "SSL_CERT_FILE", "SSL_CERT_DIR", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
                     "REQUESTS_CA_BUNDLE")


def _child_env():
    """Env for the reader subprocess: the six injected credentials + a minimal benign
    runtime whitelist. Deliberately EXCLUDES the rest of the parent env so other
    container secrets (ANTHROPIC_API_KEY, OpenRouter key) are never handed to the
    content-untrusted reader. Callers guarantee all six CRED_VARS are present."""
    env = {k: os.environ[k] for k in _RUNTIME_ENV_KEYS if k in os.environ}
    for v in CRED_VARS:
        env[v] = os.environ[v]
    return env


def build_plan(project, report):
    workdir = read_workdir(registry_path(), project)
    cfg = read_read_execute(registry_path(), project)
    report = resolve_report(cfg, report)                       # validated bare name
    script = os.path.join(workdir, cfg["script_dir"], report + ".py")
    return {"workdir": workdir, "runner": cfg["runner"], "script": script,
            "report": report, "project": project}


def run_report(plan, now):
    missing = [v for v in CRED_VARS if not os.environ.get(v)]
    if missing:
        raise SystemExit("run-ads-report: missing injected credential vars: "
                         f"{', '.join(missing)} (operator-invoked via run-ads-report.sh only). "
                         "The complete set is required so nothing falls through to the in-tree .env.")
    secrets = [os.environ[v] for v in SECRET_VARS]
    if not os.path.isfile(plan["runner"]):
        raise SystemExit(f"run-ads-report: runner interpreter not found: {plan['runner']} "
                         "(build the /opt/ads-venv image layer — Task 1)")
    if not os.path.isfile(plan["script"]):
        raise SystemExit(f"run-ads-report: reader not found: {plan['script']}")
    scratch = tempfile.mkdtemp(prefix="ads-report-")   # defense-in-depth cwd; guarantee is override=False
    try:
        proc = subprocess.run([plan["runner"], plan["script"]],
                              cwd=scratch, env=_child_env(),
                              capture_output=True, text=True)
        err = _scrub(proc.stderr, secrets)
        if proc.returncode != 0:
            raise SystemExit(f"run-ads-report: reader {plan['report']} failed "
                             f"(exit {proc.returncode}):\n{err}")
        out = _scrub(proc.stdout, secrets)
        dest_dir = os.path.join(reports_dir(), plan["project"])
        os.makedirs(dest_dir, exist_ok=True)
        ts = now.strftime("%Y-%m-%d_%H-%M-%S")
        dest = os.path.join(dest_dir, f"{ts}-{plan['report']}.md")
        header = (f"# Google Ads read report — {plan['project']} — {plan['report']}\n\n"
                  f"_Generated {ts} UTC by Hermes read-execute (read-only credential). "
                  f"Credential values scrubbed._\n\n")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(header + "```\n" + out + "\n```\n")
        print(dest)
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)   # cleanup on success AND failure


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
    return run_report(plan, datetime.datetime.now(datetime.timezone.utc))


if __name__ == "__main__":
    sys.exit(main())
