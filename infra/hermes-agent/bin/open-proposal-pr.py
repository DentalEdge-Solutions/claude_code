#!/usr/bin/env python3
"""Open a DRAFT PR that adds a persisted proposal as a brain candidate.

Operator-invoked (reads CLAUDE_CODE_PR_PAT from the container env, injected per
invocation by open-proposal-pr.sh via `docker compose exec -e`). Writes ONLY an
ephemeral clone — never the :ro project mount. --dry-run prints the plan and does no
git/network. STDLIB ONLY. See docs/superpowers/specs/2026-07-24-hermes-proposal-draft-pr-design.md
"""
import argparse, datetime, json, os, re, subprocess, sys, tempfile, shutil

DEFAULT_REGISTRY = "/opt/registry/projects.yaml"
DEFAULT_PROPOSALS = "/opt/data/proposals"


def registry_path():
    return os.environ.get("PR_REGISTRY") or (
        DEFAULT_REGISTRY if os.path.exists(DEFAULT_REGISTRY)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registry", "projects.yaml"))


def read_pr_target(path, project):
    """Stdlib line-parser for projects.<project>.pr_target.{repo,base,path}."""
    cur_project = None
    in_pr = False
    got = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent == 2 and line.rstrip().endswith(":"):      # a project name
                cur_project = line.strip()[:-1]; in_pr = False
            elif indent == 4 and cur_project == project and line.strip() == "pr_target:":
                in_pr = True
            elif indent == 4 and cur_project == project and not line.rstrip().endswith(":"):
                in_pr = False                                    # a sibling scalar of pr_target
            elif indent == 6 and in_pr and cur_project == project:
                k, _, v = line.strip().partition(":")
                got[k.strip()] = v.strip()
    if not {"repo", "base", "path"} <= set(got):
        raise SystemExit(f"open-proposal-pr: no pr_target(repo,base,path) for project {project!r}")
    return {"repo": got["repo"], "base": got["base"], "path": got["path"]}


def proposals_dir():
    return os.environ.get("PROPOSALS_DIR", DEFAULT_PROPOSALS)


def resolve_proposal(project, which):
    d = os.path.join(proposals_dir(), project)
    if not os.path.isdir(d):
        raise SystemExit(f"open-proposal-pr: no proposals dir for {project!r}: {d}")
    files = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    if not files:
        raise SystemExit(f"open-proposal-pr: no proposals under {d}")
    fn = files[-1] if which in (None, "latest") else (which if which.endswith(".md") else which + ".md")
    p = os.path.join(d, fn)
    if not os.path.isfile(p):
        raise SystemExit(f"open-proposal-pr: proposal not found: {p}")
    return p, fn[:-3]


def _title(text):
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Hermes improvement proposal"


def _description(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## summary"):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return _title(text)


def _strip_trailing_dates(title):
    # Proposal H1s look like "Improvement proposal — claude_code — 2026-07-24T22:51Z".
    # Drop trailing date/timestamp segments (and their separators) before slugifying so
    # the filename isn't date-twice-plus-noise. Keep the FULL title in frontmatter.
    prev = None
    s = title
    while s != prev:
        prev = s
        s = re.sub(r"[\s—–:\-]+\d{4}-\d{2}-\d{2}(?:[T ][0-9:.\-Z]+)?\s*$", "", s)
    return s.strip(" —–-:") or title


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s[:60] or "proposal")


def render_candidate(proposal_text, proposal_path, run_id, now):
    title = _title(proposal_text)
    desc = _description(proposal_text)
    date = now.strftime("%Y-%m-%d")
    filename = f"{date}-{slugify(_strip_trailing_dates(title))}.md"
    # Hand-rendered YAML frontmatter. json.dumps(ensure_ascii=False) gives valid
    # double-quoted YAML scalars while keeping non-ASCII (em-dashes) as literal UTF-8,
    # matching the body. timestamp is DATE-ONLY by choice (existing candidates are mixed
    # date/datetime; brain-promote accepts either) — date-only for brevity.
    def q(s):
        return json.dumps(s, ensure_ascii=False)
    fm = (
        "---\n"
        "type: decision\n"
        f"title: {q(title)}\n"
        f"description: {q(desc)}\n"
        "tags: [hermes-generated]\n"
        "author: hermes\n"
        f"timestamp: {date}\n"
        "sources:\n"
        f"  - {q(proposal_path)}\n"
        f"  - {q('hermes-run:' + run_id)}\n"
        "status: candidate\n"
        "---\n\n"
    )
    body = proposal_text if proposal_text.endswith("\n") else proposal_text + "\n"
    return filename, fm + body


def build_plan(project, which, run_id, now):
    tgt = read_pr_target(registry_path(), project)
    ppath, pts = resolve_proposal(project, which)
    with open(ppath, encoding="utf-8") as f:
        text = f.read()
    filename, content = render_candidate(text, ppath, run_id or pts, now)
    branch = f"proposal/{pts}"
    dest = f"{tgt['path'].rstrip('/')}/{filename}"
    return {"target": tgt, "branch": branch, "dest": dest, "content": content,
            "proposal_path": ppath, "title": _title(text), "desc": _description(text)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--proposal", default="latest")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    plan = build_plan(args.project, args.proposal, args.run_id,
                      datetime.datetime.now(datetime.timezone.utc))
    if args.dry_run:
        print(f"repo:   {plan['target']['repo']}")
        print(f"base:   {plan['target']['base']}")
        print(f"branch: {plan['branch']}")
        print(f"add:    {plan['dest']}")
        print(f"title:  {plan['title']}")
        return 0
    return _run_live(plan, args.project)  # noqa: F821  (defined in Task 3)


if __name__ == "__main__":
    sys.exit(main())
