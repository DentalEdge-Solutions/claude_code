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
            elif indent <= 4:
                in_pr = False                                    # ANY sibling/shallower line closes pr_target scope
                # — including a mapping-valued sibling (ends in ':'); guards against key bleed
            elif indent == 6 and in_pr and cur_project == project:
                k, _, v = line.strip().partition(":")
                got[k.strip()] = v.strip()
    missing = [k for k in ("repo", "base", "path") if not got.get(k)]
    if missing:
        raise SystemExit(f"open-proposal-pr: pr_target for project {project!r} missing/empty: {', '.join(missing)}")
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
    if os.path.basename(fn) != fn:                              # reject path separators / traversal in --proposal
        raise SystemExit(f"open-proposal-pr: --proposal must be a bare filename, got {which!r}")
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


def _scrub(text, secret):
    return text.replace(secret, "***") if secret else text


def _git(repo, *args, env=None, secret=None):
    """Run git; never let the PAT surface in an exception. With GIT_ASKPASS the token
    is never in argv/URL/config, so stderr is already token-free — the scrub is
    belt-and-suspenders for the 90-day-expiry failure path."""
    r = subprocess.run(["git", "-C", repo, *args], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"open-proposal-pr: git {args[0]} failed: {_scrub(r.stderr.strip(), secret)}")
    return r


def _open_draft_pr(tgt, plan, pat):
    if shutil.which("gh"):
        try:
            out = subprocess.run(
                ["gh", "pr", "create", "--repo", tgt["repo"], "--draft",
                 "--base", tgt["base"], "--head", plan["branch"],
                 "--title", f"Proposal: {plan['title']} (machine-generated)",
                 "--body", f"Machine-generated improvement proposal from Hermes AIOS.\n\n"
                           f"Source: `{plan['proposal_path']}`. Adds `{plan['dest']}` as a brain candidate."],
                check=True, capture_output=True, text=True, env={**os.environ, "GH_TOKEN": pat})
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"open-proposal-pr: gh pr create failed: {_scrub((e.stderr or '').strip(), pat)}")
        return out.stdout.strip()
    # REST fallback (no gh in the container)
    import urllib.request, urllib.error
    body = json.dumps({"title": f"Proposal: {plan['title']} (machine-generated)",
                       "head": plan["branch"], "base": tgt["base"], "draft": True,
                       "body": f"Machine-generated proposal. Source: {plan['proposal_path']}. "
                               f"Adds {plan['dest']}."}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{tgt['repo']}/pulls", data=body,
                                 headers={"Authorization": f"Bearer {pat}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "hermes-aios"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()).get("html_url", "(PR created)")
    except urllib.error.HTTPError as e:
        # Surface GitHub's explanation (the 422 body says WHY) — scrubbed, never a bare traceback.
        detail = _scrub((e.read().decode(errors="replace") or "").strip(), pat)
        code = e.code
        e.close()
        raise SystemExit(f"open-proposal-pr: GitHub API PR create failed ({code}): {detail}")


def _run_live(plan):
    pat = os.environ.get("CLAUDE_CODE_PR_PAT")
    if not pat:
        raise SystemExit("open-proposal-pr: CLAUDE_CODE_PR_PAT not in env (operator-invoked only)")
    tgt = plan["target"]
    host = os.environ.get("PR_GIT_HOST", "github.com")            # test seam only
    ws = tempfile.mkdtemp(prefix="proposal-pr-")
    repo = os.path.join(ws, "repo")
    try:
        # GIT_ASKPASS supplies the token at runtime; the askpass FILE embeds no token
        # (it reads $CLAUDE_CODE_PR_PAT from env), and the clone URL carries NO token —
        # so the token never lands in argv, the remote URL, .git/config, or git stderr.
        askpass = os.path.join(ws, ".askpass")
        with open(askpass, "w") as f:
            f.write('#!/bin/sh\nprintf "%s" "$CLAUDE_CODE_PR_PAT"\n')
        os.chmod(askpass, 0o700)
        genv = {**os.environ, "GIT_ASKPASS": askpass, "GIT_TERMINAL_PROMPT": "0"}
        url = f"https://x-access-token@{host}/{tgt['repo']}"       # username only, NO token
        cl = subprocess.run(["git", "clone", "--depth", "1", url, repo],
                            env=genv, capture_output=True, text=True)
        if cl.returncode != 0:
            raise SystemExit(f"open-proposal-pr: clone failed: {_scrub(cl.stderr.strip(), pat)}")
        # pre-push hook (refuse the base branch); .git/hooks is git's default path
        hook_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pre-push-refuse-base.sh")
        hook_dst = os.path.join(repo, ".git", "hooks", "pre-push")
        shutil.copyfile(hook_src, hook_dst); os.chmod(hook_dst, 0o755)
        _git(repo, "config", "user.email", "bot@dentaledge.local", env=genv, secret=pat)
        _git(repo, "config", "user.name", "hermes-bot", env=genv, secret=pat)
        # re-run guard: refuse if the proposal branch already exists remotely
        ls = _git(repo, "ls-remote", "--heads", "origin", plan["branch"], env=genv, secret=pat)
        if ls.stdout.strip():
            raise SystemExit(f"open-proposal-pr: branch {plan['branch']} already exists on the remote — "
                             f"close/delete its PR (or pick a different --proposal); not re-pushing")
        _git(repo, "checkout", "-b", plan["branch"], env=genv, secret=pat)
        dest = os.path.join(repo, plan["dest"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(plan["content"])
        _git(repo, "add", plan["dest"], env=genv, secret=pat)
        _git(repo, "commit", "-m", f"proposal: {plan['title']} (Hermes AIOS, machine-generated)",
             env=genv, secret=pat)
        _git(repo, "push", "origin", plan["branch"],
             env={**genv, "PREPUSH_BASE": tgt["base"]}, secret=pat)
        try:
            print(_open_draft_pr(tgt, plan, pat))
        except SystemExit as e:
            # Branch is already on the remote; the re-run guard would block a naive retry.
            # Give the operator the exact recovery path instead of a dead end.
            raise SystemExit(
                f"{e}\nopen-proposal-pr: branch {plan['branch']} WAS pushed but the draft PR was NOT created. "
                f"Open the PR manually from that branch, or delete the remote branch to retry:\n"
                f"    git push origin --delete {plan['branch']}")
        return 0
    finally:
        shutil.rmtree(ws, ignore_errors=True)   # cleanup on success AND failure


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
    return _run_live(plan)


if __name__ == "__main__":
    sys.exit(main())
