# Proposals as Draft PRs — Implementation Plan (Increment 2 · first write capability)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A trusted deterministic script `open-proposal-pr.py` opens a **draft** PR on `dentaledgesolutions/claude_code` that adds one machine-authored brain-candidate markdown file (a persisted improvement proposal) — with the `:ro` production mount provably untouched, `main` unwritable by the bot, and the bot PAT never exposed.

**Architecture:** No LLM in the write path. The script reads a persisted proposal from Hermes state, clones the target repo into an **ephemeral workspace** via a **bot-account** PAT (never the `:ro` mount), writes the candidate file, commits on a `proposal/<ts>` branch, pushes, and opens a draft PR. A dedicated **machine account** (collaborator = write, not admin) plus a **`main` ruleset with admin-only bypass** make the bot's direct `main` pushes server-side-rejectable — the owner keeps pushing to `main`. Design: `docs/superpowers/specs/2026-07-24-hermes-proposal-draft-pr-design.md`.

**Tech Stack:** Python 3 (**stdlib only** — tests run on the host without deps); `git` + `gh` (or GitHub REST via `curl`) inside the Hermes container; the existing `infra/hermes-agent/` control plane; reuses `save-proposal.py`/`proposals-index.py` and `registry/projects.yaml`.

## Global Constraints

- **The `:ro` production mount is NEVER written.** All writes happen in an ephemeral clone under `mktemp -d`, deleted on success AND failure. `/projects/claude_code` stays byte-identical.
- **Bot identity, not owner:** the PAT is minted from a dedicated **machine account** added as a **collaborator** (write, not admin). Every guardrail test runs **AS THE BOT** — testing as the owner proves nothing.
- **Payload is doc-only:** exactly one markdown file added under the repo's `pr_target.path`; no code, no executables. Proposal content is DATA — never executed.
- **PR is draft only.** The script never marks a PR ready, never merges, never pushes to `pr_target.base`.
- **Python stdlib only** (no PyYAML/requests): hand-render YAML frontmatter using `json.dumps` for safe scalar escaping; hand-parse the registry.
- **Secrets:** the bot PAT lives only in `infra/hermes-agent/.env` (gitignored, `env_file`) as `CLAUDE_CODE_PR_PAT`, read directly by the operator-invoked script; never printed, logged, committed, or embedded in a URL that gets echoed.
- **Candidate file provenance:** every generated file carries `author: hermes`, a `hermes-generated` tag, and `sources` naming the originating proposal path + run id.

## Prerequisites (HUMAN-performed, gated on plan review — NOT done by any worker)

Do these by hand only after approving this plan; the plan's tasks assume they exist. **No task creates the machine account, PAT, or GitHub settings.**

1. Create a dedicated machine account (e.g. `dentaledge-hermes-bot`) with its own email/2FA.
2. Add it as a **collaborator** on `dentaledgesolutions/claude_code` (Settings → Collaborators). On a user-owned repo this grants **write, not admin**.
3. As the machine account, mint a **fine-grained PAT**: resource owner = `dentaledgesolutions`, repository = `claude_code` only, permissions = **Contents: Read/Write** + **Pull requests: Read/Write** (nothing else), **expiry = 90 days**. Put it in `infra/hermes-agent/.env` as `CLAUDE_CODE_PR_PAT=...`.
4. Add a **ruleset** on `main` (Settings → Rules → Rulesets): target `main`, require a pull request before merging, **bypass list = Repository admin** (the owner). Do NOT add the bot to the bypass list.
5. `cd infra/hermes-agent && docker compose up -d --force-recreate` so the container env picks up `CLAUDE_CODE_PR_PAT`.

## File Structure

- `infra/hermes-agent/bin/open-proposal-pr.py` — the write step (proposal → candidate → branch → push → draft PR). New.
- `infra/hermes-agent/bin/open-proposal-pr.test.py` — unit tests for the offline logic (resolution, rendering, hook, dry-run). New.
- `infra/hermes-agent/bin/pre-push-refuse-base.sh` — the pre-push hook installed into the ephemeral clone; refuses pushes to the base branch. New.
- `infra/hermes-agent/registry/projects.yaml` — add structured `pr_target` to `claude_code`. Modify.
- `infra/hermes-agent/.env.example` — document `CLAUDE_CODE_PR_PAT` (write-scoped, gitignored). Modify.
- `infra/hermes-agent/README.md` — setup, rotation, usage. Modify.

---

### Task 1: Guardrail + identity verification — AS THE BOT (the gate; no script yet)

**Files:** none (records the empirical result that everything else rests on). If any check fails, STOP and fix the identity model before writing code.

**Interfaces:** Produces a verified go/no-go. Consumes the human prerequisites.

- [ ] **Step 1: Confirm env-scrub — an agent-launched process cannot read the PAT**

Operator-invoked path CAN read it; agent-launched path CANNOT.
```bash
cd infra/hermes-agent
# operator-invoked (docker exec): expect the token's LENGTH (not the value) printed
docker compose exec -T hermes-agent sh -c 'printf "operator sees len=%s\n" "${#CLAUDE_CODE_PR_PAT}"'
# agent-launched (Hermes terminal tool): expect EMPTY
docker compose exec -T hermes-agent hermes --accept-hooks -z \
  "Use your terminal tool to run exactly: printf 'agent sees [%s]\n' \"\$CLAUDE_CODE_PR_PAT\" — return only that line."
```
Expected: operator `len=<nonzero>`; agent `agent sees []` (empty). If the agent sees the token, STOP — do not proceed to any auto-trigger; the operator-only boundary is the whole basis for reading the PAT from env.

- [ ] **Step 2: PRECONDITION — the `main` ruleset must EXIST (distinct signal from "identity broken")**

Do NOT run Step 3 until this returns a ruleset. If `main` has no ruleset, Step 3's push would be *accepted* — indistinguishable from a broken identity model unless the signals differ. This step makes "prerequisite missing" and "identity model wrong" two different messages.
```bash
cd infra/hermes-agent
# ruleset count (fine-grained rulesets), plus classic branch-protection as a fallback signal
docker compose exec -T hermes-agent sh -c '
n=$(GH_TOKEN="$CLAUDE_CODE_PR_PAT" gh api repos/dentaledgesolutions/claude_code/rulesets --jq "length" 2>/dev/null || echo "?")
GH_TOKEN="$CLAUDE_CODE_PR_PAT" gh api repos/dentaledgesolutions/claude_code/branches/main/protection --jq ".url" >/dev/null 2>&1 && c=present || c=none
echo "rulesets=$n classic_protection=$c"
if [ "$n" = "0" ] || [ "$n" = "?" ]; then
  if [ "$c" = "none" ]; then echo "PREREQUISITE MISSING: no main ruleset — complete prereq 4 before Step 3"; fi
fi'
```
Expected: `rulesets=<N≥1>` (or `classic_protection=present`). If you see **`PREREQUISITE MISSING`**, STOP and complete prereq 4 — this is deliberately NOT the same signal as Step 3's `IDENTITY MODEL WRONG`. (No `gh`? Use `curl -s -H "Authorization: Bearer $CLAUDE_CODE_PR_PAT" https://api.github.com/repos/dentaledgesolutions/claude_code/rulesets` and confirm a non-empty array.)

- [ ] **Step 3: As the bot, a direct push to `main` is REJECTED server-side** (only after Step 2 confirms a ruleset)

```bash
docker compose exec -T hermes-agent sh -c '
set -e
W=$(mktemp -d); cd "$W"
git clone --depth 1 "https://x-access-token:${CLAUDE_CODE_PR_PAT}@github.com/dentaledgesolutions/claude_code" repo >/dev/null 2>&1
cd repo
git config user.email bot@dentaledge.local; git config user.name hermes-bot
git commit --allow-empty -m "guardrail probe (should be rejected)" >/dev/null
# Attempt the forbidden push; capture result WITHOUT leaking the token
if git push origin HEAD:main 2>push.err; then echo "PUSH-TO-MAIN: ACCEPTED (IDENTITY MODEL WRONG)"; else echo "PUSH-TO-MAIN: REJECTED (expected)"; fi
grep -oiE "protected branch|required|pull request|ruleset|denied" push.err | head -1
cd /; rm -rf "$W"'
```
Expected: `PUSH-TO-MAIN: REJECTED (expected)` and a ruleset/protected-branch reason. If ACCEPTED, STOP — the bot is bypassing (likely added to the bypass list, or the ruleset is not enforced) — fix before continuing.

- [ ] **Step 4: As the bot, a non-base branch push + draft PR SUCCEEDS, then clean up**

```bash
docker compose exec -T hermes-agent sh -c '
set -e
W=$(mktemp -d); cd "$W"
git clone --depth 1 "https://x-access-token:${CLAUDE_CODE_PR_PAT}@github.com/dentaledgesolutions/claude_code" repo >/dev/null 2>&1
cd repo; git config user.email bot@dentaledge.local; git config user.name hermes-bot
B="probe/guardrail-$(date +%s)"; git checkout -b "$B" >/dev/null 2>&1
git commit --allow-empty -m "guardrail probe branch" >/dev/null
git push origin "$B" >/dev/null 2>&1 && echo "PUSH-BRANCH: OK"
# open + immediately close a draft PR (gh if present, else REST)
if command -v gh >/dev/null 2>&1; then
  GH_TOKEN="$CLAUDE_CODE_PR_PAT" gh pr create --repo dentaledgesolutions/claude_code --draft --base main --head "$B" --title "guardrail probe" --body "probe" && \
  GH_TOKEN="$CLAUDE_CODE_PR_PAT" gh pr close --repo dentaledgesolutions/claude_code "$B"
  echo "GH: available"
else
  echo "GH: absent — plan will use REST for PR creation"
fi
git push origin --delete "$B" >/dev/null 2>&1 && echo "CLEANUP: branch deleted"
cd /; rm -rf "$W"'
```
Expected: `PUSH-BRANCH: OK`, a `GH: available|absent` line (records which PR mechanism Task 3 uses), `CLEANUP: branch deleted`. Record the `GH:` result — it decides Task 3's PR path.

- [ ] **Step 5: Record the outcome**

Append the results (env-scrub, ruleset-present, main-rejected, branch+PR-ok, gh-vs-REST) to the SDD ledger. No commit (no code changed).

---

### Task 2: `open-proposal-pr.py` offline core — resolution, candidate rendering, `--dry-run`

**Files:** Create `infra/hermes-agent/bin/open-proposal-pr.py` + `infra/hermes-agent/bin/open-proposal-pr.test.py`; Modify `infra/hermes-agent/registry/projects.yaml`, `infra/hermes-agent/.env.example`.

**Interfaces:**
- Consumes: `registry/projects.yaml` (`pr_target: {repo, base, path}`), proposals under `PROPOSALS_DIR/<project>/<ts>.md`.
- Produces (for Task 3): `read_pr_target(registry_path, project) -> dict(repo, base, path)`; `resolve_proposal(project, which) -> (path, ts)`; `render_candidate(proposal_text, proposal_path, run_id, now) -> (filename, content)`; `main(argv)` supporting `--project`, `--proposal latest|<ts>`, `--run-id`, `--dry-run`.

- [ ] **Step 1: Add structured `pr_target` to the registry**

In `infra/hermes-agent/registry/projects.yaml`, under the `claude_code` entry (mount stays `scope: read`), add:
```yaml
    pr_target:
      repo: dentaledgesolutions/claude_code
      base: main
      path: .project-brain/decisions/candidates
```

- [ ] **Step 2: Document the PAT in `.env.example`**

Append to `infra/hermes-agent/.env.example`:
```bash
# --- Draft-PR delivery (Increment 2) — bot-account PAT, NOT the owner's ---
# Fine-grained PAT minted from the machine collaborator account: single repo
# (dentaledgesolutions/claude_code), Contents+Pull-requests write only, 90-day expiry.
# Read only by the OPERATOR-invoked open-proposal-pr.py (Hermes scrubs agent-launched env).
# CLAUDE_CODE_PR_PAT=
```

- [ ] **Step 3: Write the failing tests**

Create `infra/hermes-agent/bin/open-proposal-pr.test.py`:
```python
import datetime, os, subprocess, sys, tempfile, unittest, json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "open-proposal-pr.py")
mod = {}
with open(SCRIPT) as f:
    exec(compile(f.read(), SCRIPT, "exec"), mod)  # import functions without running main

PROPOSAL = ("# Improvement proposal — claude_code — 2026-07-24\n"
            "## Summary\nUnify the divergent secret-scanning pattern lists.\n"
            "## Items (prioritized)\n- [P1] correction: one pattern source.\n"
            "## Sources consulted\n- .project-brain/\n")

class TestOfflineCore(unittest.TestCase):
    def test_read_pr_target(self):
        reg = ("version: 1\nprojects:\n  claude_code:\n    workdir: /projects/claude_code\n"
               "    scope: read\n    pr_target:\n      repo: dentaledgesolutions/claude_code\n"
               "      base: main\n      path: .project-brain/decisions/candidates\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(reg); p = f.name
        t = mod["read_pr_target"](p, "claude_code")
        self.assertEqual(t, {"repo": "dentaledgesolutions/claude_code",
                             "base": "main", "path": ".project-brain/decisions/candidates"})
        os.unlink(p)

    def test_read_pr_target_missing_project(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("version: 1\nprojects:\n  other:\n    scope: read\n"); p = f.name
        with self.assertRaises(SystemExit):
            mod["read_pr_target"](p, "claude_code")
        os.unlink(p)

    def test_render_candidate_filename_and_frontmatter(self):
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        fn, content = mod["render_candidate"](
            PROPOSAL, "/opt/data/proposals/claude_code/2026-07-24_22-54-03.md",
            "2026-07-24_22-54-03", now)
        self.assertTrue(fn.startswith("2026-07-25-"), fn)
        self.assertTrue(fn.endswith(".md"))
        self.assertIn("type: decision", content)
        self.assertIn("author: hermes", content)
        self.assertIn("hermes-generated", content)
        self.assertIn("status: candidate", content)
        # provenance sources present
        self.assertIn("/opt/data/proposals/claude_code/2026-07-24_22-54-03.md", content)
        self.assertIn("2026-07-24_22-54-03", content)
        # body carried verbatim
        self.assertIn("Unify the divergent secret-scanning pattern lists.", content)
        # frontmatter is valid: exactly two '---' fences at the top
        self.assertEqual(content.split("\n")[0], "---")
        self.assertEqual(content.count("\n---\n"), 1)

    def test_render_candidate_escapes_colon_in_title(self):
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        text = "# Proposal: fix things\n## Summary\nA: B needed.\n"
        _, content = mod["render_candidate"](text, "/p/x.md", "x", now)
        # title line must be a valid quoted YAML scalar (json.dumps form)
        self.assertIn('title: "Proposal: fix things"', content)

    def test_render_candidate_real_h1_strips_trailing_timestamp(self):
        # The ACTUAL proposal H1 on disk (review item #3) — must NOT slugify to date-twice-plus-noise.
        now = datetime.datetime(2026, 7, 25, 9, 30, 0)
        text = "# Improvement proposal — claude_code — 2026-07-24T22:51Z\n## Summary\nUnify things.\n"
        fn, content = mod["render_candidate"](text, "/opt/data/proposals/claude_code/x.md", "x", now)
        self.assertEqual(fn, "2026-07-25-improvement-proposal-claude-code.md")   # one date, no timestamp
        self.assertNotIn("22-51z", fn)
        self.assertNotIn("2026-07-24", fn)
        # frontmatter keeps the FULL title, but timestamp is DATE-ONLY (item #4)
        self.assertIn("title: \"Improvement proposal — claude_code — 2026-07-24T22:51Z\"", content)
        self.assertIn("timestamp: 2026-07-25\n", content)
        self.assertNotIn("timestamp: 2026-07-25T", content)

    def test_dry_run_no_side_effects(self):
        with tempfile.TemporaryDirectory() as d:
            pdir = os.path.join(d, "claude_code"); os.makedirs(pdir)
            pf = os.path.join(pdir, "2026-07-24_22-54-03.md")
            open(pf, "w").write(PROPOSAL)
            reg = os.path.join(d, "projects.yaml")
            open(reg, "w").write("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
                                 "    pr_target:\n      repo: dentaledgesolutions/claude_code\n"
                                 "      base: main\n      path: docs/proposals\n")
            env = {**os.environ, "PROPOSALS_DIR": d, "PR_REGISTRY": reg}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code",
                                "--proposal", "latest", "--dry-run"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dentaledgesolutions/claude_code", r.stdout)
            self.assertIn("proposal/", r.stdout)          # branch name
            self.assertIn("docs/proposals/2026-07-25-", r.stdout)  # candidate path
            self.assertNotIn(os.environ.get("CLAUDE_CODE_PR_PAT", "NO_TOKEN_SET"), r.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the tests — verify they fail**

Run: `python3 infra/hermes-agent/bin/open-proposal-pr.test.py -v`
Expected: FAIL (module has no such functions yet / file missing).

- [ ] **Step 5: Write the offline core**

Create `infra/hermes-agent/bin/open-proposal-pr.py`:
```python
#!/usr/bin/env python3
"""Open a DRAFT PR that adds a persisted proposal as a brain candidate.

Operator-invoked (reads CLAUDE_CODE_PR_PAT from the container env). Writes ONLY an
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
            key = line.strip().rstrip(":") if line.strip().endswith(":") else line.strip().split(":", 1)[0]
            if indent == 2 and line.rstrip().endswith(":"):      # a project name
                cur_project = line.strip()[:-1]; in_pr = False
            elif indent == 4 and cur_project == project and line.strip() == "pr_target:":
                in_pr = True
            elif indent == 4 and cur_project == project and line.rstrip().endswith(":") is False:
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
    # Hand-rendered YAML frontmatter; json.dumps gives valid double-quoted YAML scalars.
    # timestamp is DATE-ONLY to match the recent candidate convention (2026-07-17, 2026-07-21).
    fm = (
        "---\n"
        "type: decision\n"
        f"title: {json.dumps(title)}\n"
        f"description: {json.dumps(desc)}\n"
        "tags: [hermes-generated]\n"
        "author: hermes\n"
        f"timestamp: {date}\n"
        "sources:\n"
        f"  - {json.dumps(proposal_path)}\n"
        f"  - {json.dumps('hermes-run:' + run_id)}\n"
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
    # live path (Task 3) is appended below during that task
    return _run_live(plan, args.project)  # noqa: F821  (defined in Task 3)


if __name__ == "__main__":
    sys.exit(main())
```
Note: `_run_live` is added in Task 3; `--dry-run` returns before calling it, so the offline tests pass now.

- [ ] **Step 6: Run the tests — verify they pass**

Run: `python3 infra/hermes-agent/bin/open-proposal-pr.test.py -v`
Expected: PASS (all offline tests).

- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/open-proposal-pr.py infra/hermes-agent/bin/open-proposal-pr.test.py infra/hermes-agent/registry/projects.yaml infra/hermes-agent/.env.example
git commit -m "feat(hermes): open-proposal-pr.py offline core — resolution, candidate rendering, dry-run"
```

---

### Task 3: pre-push hook + live git/PR mechanics

**Files:** Create `infra/hermes-agent/bin/pre-push-refuse-base.sh`; Modify `infra/hermes-agent/bin/open-proposal-pr.py` (+ its test).

**Interfaces:** Consumes the Task-2 `build_plan` dict. Produces `_run_live(plan, project)` used by `main`.

- [ ] **Step 1: Write the pre-push hook + its test**

Create `infra/hermes-agent/bin/pre-push-refuse-base.sh`:
```sh
#!/bin/sh
# git pre-push hook: refuse any push whose remote ref is the protected base branch.
# git feeds "<local ref> <local sha> <remote ref> <remote sha>" lines on stdin.
# BASE_REF is injected by the installer (open-proposal-pr.py) as an env var.
base="refs/heads/${PREPUSH_BASE:-main}"
while read local_ref local_sha remote_ref remote_sha; do
  if [ "$remote_ref" = "$base" ]; then
    echo "pre-push: refusing to push to protected base $base" >&2
    exit 1
  fi
done
exit 0
```

Add to `open-proposal-pr.test.py`:
```python
class TestPrePushHook(unittest.TestCase):
    HOOK = os.path.join(HERE, "pre-push-refuse-base.sh")
    def _run(self, remote_ref):
        stdin = f"refs/heads/x deadbeef {remote_ref} 0000000\n"
        return subprocess.run(["sh", self.HOOK], input=stdin, capture_output=True, text=True,
                              env={**os.environ, "PREPUSH_BASE": "main"})
    def test_refuses_main(self):
        self.assertEqual(self._run("refs/heads/main").returncode, 1)
    def test_allows_feature_branch(self):
        self.assertEqual(self._run("refs/heads/proposal/2026-07-24_22-54-03").returncode, 0)


class TestSecretHandling(unittest.TestCase):
    def test_no_token_leak_on_clone_failure(self):
        # Blocking review item #1: force a clone failure (bogus .invalid host = fast NXDOMAIN)
        # and assert the token appears in NEITHER stdout NOR stderr — including any traceback.
        with tempfile.TemporaryDirectory() as d:
            pdir = os.path.join(d, "claude_code"); os.makedirs(pdir)
            with open(os.path.join(pdir, "2026-07-24_22-54-03.md"), "w") as f:
                f.write(PROPOSAL)
            reg = os.path.join(d, "projects.yaml")
            with open(reg, "w") as f:
                f.write("version: 1\nprojects:\n  claude_code:\n    scope: read\n"
                        "    pr_target:\n      repo: dentaledgesolutions/claude_code\n"
                        "      base: main\n      path: docs/proposals\n")
            SENTINEL = "ghp_SENTINELtoken000000000000000000000000"
            env = {**os.environ, "PROPOSALS_DIR": d, "PR_REGISTRY": reg,
                   "CLAUDE_CODE_PR_PAT": SENTINEL, "PR_GIT_HOST": "example.invalid"}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code", "--proposal", "latest"],
                               capture_output=True, text=True, env=env)
            self.assertNotEqual(r.returncode, 0)          # clone must fail
            self.assertNotIn(SENTINEL, r.stdout)
            self.assertNotIn(SENTINEL, r.stderr)


class TestRestFallback(unittest.TestCase):
    def test_open_draft_pr_rest_posts_draft(self):
        # Review item #9: the REST path never runs live when gh is present, so unit-test it
        # with gh forced absent and a stubbed urlopen.
        import urllib.request as ur
        captured = {}
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"html_url": "https://github.com/o/r/pull/7"}'
        def fake_urlopen(req):
            captured["data"] = req.data.decode(); captured["auth"] = req.headers.get("Authorization")
            return FakeResp()
        orig_which, orig_urlopen = mod["shutil"].which, ur.urlopen
        mod["shutil"].which = lambda name: None
        ur.urlopen = fake_urlopen
        try:
            out = mod["_open_draft_pr"](
                {"repo": "o/r", "base": "main"},
                {"title": "T", "branch": "proposal/x", "dest": "docs/x.md", "proposal_path": "/p/x.md"},
                "SENTINELPAT")
        finally:
            mod["shutil"].which, ur.urlopen = orig_which, orig_urlopen
        self.assertIn("pull/7", out)
        self.assertIn('"draft": true', captured["data"])
        self.assertIn("proposal/x", captured["data"])
        self.assertEqual(captured["auth"], "Bearer SENTINELPAT")
```

- [ ] **Step 2: Run — verify hook tests fail then pass**

Run: `python3 infra/hermes-agent/bin/open-proposal-pr.test.py -v` → the two hook tests FAIL (hook missing) until Step 1's file exists, then PASS. `chmod +x infra/hermes-agent/bin/pre-push-refuse-base.sh`.

- [ ] **Step 3: Add `_run_live` to `open-proposal-pr.py`**

Insert before `main` in `open-proposal-pr.py`. Uses `gh` if present else GitHub REST via `curl` (decided by Task 1 Step 3). The token is read from env and injected into the clone URL and PR call — **never printed**.
```python
def _scrub(text, secret):
    return text.replace(secret, "***") if secret else text


def _git(repo, *args, env=None, secret=None):
    """Run git; never let the PAT surface in an exception. With GIT_ASKPASS the token
    is never in argv/URL/config, so stderr is already token-free — the scrub is
    belt-and-suspenders for the 90-day-expiry failure path (blocking review item #1)."""
    r = subprocess.run(["git", "-C", repo, *args], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"open-proposal-pr: git {args[0]} failed: {_scrub(r.stderr.strip(), secret)}")
    return r


def _run_live(plan, project):
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
        # re-run guard (review item #12): refuse if the proposal branch already exists remotely
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
        print(_open_draft_pr(tgt, plan, pat))
        return 0
    finally:
        shutil.rmtree(ws, ignore_errors=True)   # cleanup on success AND failure


def _open_draft_pr(tgt, plan, pat):
    if shutil.which("gh"):
        out = subprocess.run(
            ["gh", "pr", "create", "--repo", tgt["repo"], "--draft",
             "--base", tgt["base"], "--head", plan["branch"],
             "--title", f"Proposal: {plan['title']} (machine-generated)",
             "--body", f"Machine-generated improvement proposal from Hermes AIOS.\n\n"
                       f"Source: `{plan['proposal_path']}`. Adds `{plan['dest']}` as a brain candidate."],
            check=True, capture_output=True, text=True, env={**os.environ, "GH_TOKEN": pat})
        return out.stdout.strip()
    # REST fallback
    import urllib.request, urllib.error
    body = json.dumps({"title": f"Proposal: {plan['title']} (machine-generated)",
                       "head": plan["branch"], "base": tgt["base"], "draft": True,
                       "body": f"Machine-generated proposal. Source: {plan['proposal_path']}. Adds {plan['dest']}."}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{tgt['repo']}/pulls", data=body,
                                 headers={"Authorization": f"Bearer {pat}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "hermes-aios"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()).get("html_url", "(PR created)")
```

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/bin/pre-push-refuse-base.sh infra/hermes-agent/bin/open-proposal-pr.py infra/hermes-agent/bin/open-proposal-pr.test.py
git commit -m "feat(hermes): pre-push base-refusal hook + live clone/push/draft-PR mechanics"
```

---

### Task 4: End-to-end live verification + README

**Files:** Modify `infra/hermes-agent/README.md`. Deliverable: a real draft PR + the guarantees proven.

**Interfaces:** Consumes a real persisted proposal (from the Increment-1 pipeline) and the human prerequisites.

- [ ] **Step 1: Pre-run `:ro` mount snapshot**

```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_code && git status --porcelain | sort | sha256sum'
```
Record the hash.

- [ ] **Step 2: Open the draft PR from a real proposal**

```bash
docker compose exec -T hermes-agent python3 /opt/cc-bin/open-proposal-pr.py --project claude_code --proposal latest
```
Expected: a single line — the draft PR URL. Open it: the diff is EXACTLY one added file under `.project-brain/decisions/candidates/YYYY-MM-DD-<slug>.md`, PR is **draft**, frontmatter shows `author: hermes` + `hermes-generated` + `sources` (proposal path + run id).

- [ ] **Step 3: Prove the guarantees**

```bash
cd infra/hermes-agent
# (a) :ro mount byte-identical (must equal Step 1's hash)
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_code && git status --porcelain | sort | sha256sum'

# (b) PAT not exposed — pattern read from a 0600 FILE (never a ps-visible argv), require the
#     var set (no vacuous pass), and check BOTH in-container logs AND `docker compose logs`
#     (where a traceback would land — review item #8).
docker compose exec -T hermes-agent sh -c '[ -n "$CLAUDE_CODE_PR_PAT" ] || { echo "PAT NOT SET — check inconclusive"; exit 2; }
umask 077; printf %s "$CLAUDE_CODE_PR_PAT" > /tmp/.tok
grep -rlFf /tmp/.tok /opt/data/logs 2>/dev/null && echo "LEAK: /opt/data/logs" || echo "clean: /opt/data/logs"
rm -f /tmp/.tok'
docker compose logs --no-color 2>&1 | grep -Ff <(docker compose exec -T hermes-agent sh -c 'printf %s "$CLAUDE_CODE_PR_PAT"') >/dev/null && echo "LEAK: docker logs" || echo "clean: docker logs"

# (c) ephemeral workspace gone
docker compose exec -T hermes-agent sh -c 'ls -d /tmp/proposal-pr-* 2>/dev/null && echo "LEFTOVER" || echo "workspace cleaned"'

# (d) Layers 2 & 6 ASSERTED, not eyeballed (review item #5): draft==true AND exactly one
#     changed file whose path is the candidate path. PR = the URL/number Step 2 printed.
PR="<PR url or number from Step 2>"
docker compose exec -T hermes-agent sh -c "GH_TOKEN=\"\$CLAUDE_CODE_PR_PAT\" gh pr view \"$PR\" --repo dentaledgesolutions/claude_code --json isDraft,files --jq '{draft:.isDraft, n:(.files|length), path:(.files[0].path)}'"
```
Expected: (a) hash matches Step 1; (b) `clean: /opt/data/logs` AND `clean: docker logs`; (c) `workspace cleaned`; (d) `{"draft":true,"n":1,"path":".project-brain/decisions/candidates/2026-..."}` — draft, one file, candidate path.

- [ ] **Step 4: Write the README section**

Add an "Improvement proposals as draft PRs (Increment 2)" section to `infra/hermes-agent/README.md` covering: the one-time human setup (machine account → collaborator → fine-grained bot PAT with 90-day expiry → `main` ruleset with admin-only bypass), the **90-day PAT rotation step** (mint new → update `.env` → `docker compose up -d --force-recreate`), the usage (`open-proposal-pr.py --project claude_code --proposal latest`), the safety model (bot ≠ owner; `:ro` mount never written; draft-only; operator-invoked because Hermes scrubs agent-launched env), and the **test invocation** — `python3 infra/hermes-agent/bin/open-proposal-pr.test.py` (review item #10: the hermes `bin/` tests are not auto-discovered by `run-all-tests.js`, which only scans `skills/` and `scripts/` for `*.test.js`; run them directly, as with the other hermes bin tests).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): document draft-PR delivery — setup, rotation, usage, safety model"
```

---

## Self-Review

- **Spec text (separate from this plan's implementation — review item #2):** the bot-identity model is corrected in the *spec* at commit `dbc19d3` (Layer 3/5/residual + "Identity model" section). This plan does not re-edit the spec; it implements what the spec now says. If the identity mechanism changes during implementation, the spec section is updated in the same commit.
- **Plan coverage:** machine-account identity + admin-bypass ruleset (Prereqs + Task 1 Steps 2–4) ✓; two-signal gate — `PREREQUISITE MISSING` vs `IDENTITY MODEL WRONG` (Task 1 Step 2 vs 3) ✓; env-scrub verified as the bot (Task 1 Step 1) ✓; structured `pr_target` + parser test (Task 2) ✓; candidate filename strips trailing timestamps + full-title frontmatter + date-only `timestamp` + provenance (Task 2 `render_candidate`; tests incl. the REAL H1) ✓; **no token leak on clone failure** — `GIT_ASKPASS` (token never in argv/URL/config/stderr) + `_scrub` + regression test (Task 3 `TestSecretHandling`) ✓; re-run guard on existing branch (Task 3) ✓; pre-push base refusal (hook + tests) ✓; draft-only PR via gh|REST, REST unit-tested (Task 3 `TestRestFallback`) ✓; `:ro` never written / ephemeral clone / cleanup on success+failure (`_run_live` finally) ✓; draft + one-file diff ASSERTED via `gh --json` (Task 4 Step 3d) ✓; log-leak check covers `/opt/data/logs` AND `docker compose logs`, token off argv (Task 4 Step 3b) ✓; 90-day expiry + rotation + test-invocation doc (Task 4 README) ✓.
- **Placeholder scan:** none — every code/command step is literal. `_run_live`/`_scrub`/`_git` are introduced in Task 3 (Task 2's `main` returns before calling `_run_live` under `--dry-run`, so Task 2 tests pass without it).
- **Type/name consistency:** `read_pr_target`, `resolve_proposal`, `render_candidate`, `_strip_trailing_dates`, `slugify`, `build_plan`, `_run_live`, `_git`, `_scrub`, `_open_draft_pr`, the `{repo,base,path}` dict, `PROPOSALS_DIR`/`PR_REGISTRY`/`PR_GIT_HOST`/`CLAUDE_CODE_PR_PAT`/`PREPUSH_BASE` env vars, and the `proposal/<ts>` branch name are used identically across tasks.
- **Ambiguity check:** gh-vs-REST is resolved empirically in Task 1 Step 4 AND the REST path is unit-tested (item #9), so it ships covered regardless of `gh` presence; the registry hand-parser and the timestamp-stripping slug are unit-tested for the exact real inputs.

## Notes for the executor

- **Do NOT perform the Prerequisites** — they are the owner's to do after reviewing this plan (create bot account, PAT, ruleset). Every task assumes they exist and tests **as the bot**.
- Task 1 is a two-signal gate: **Step 2** (precondition) fails with `PREREQUISITE MISSING` if no `main` ruleset exists; **Step 3** fails with `IDENTITY MODEL WRONG` only if a ruleset exists AND the bot still pushed to `main`. Never run Step 3 before Step 2 confirms a ruleset.
- Never echo `$CLAUDE_CODE_PR_PAT`; the `GIT_ASKPASS` mechanism keeps it out of argv/URL/`.git/config`/git-stderr; the `_scrub` + the leak test are the regression guard.
- **Spec is already corrected (review item #2):** the bot-identity model lives in `docs/superpowers/specs/2026-07-24-hermes-proposal-draft-pr-design.md` as of commit `dbc19d3` (rewritten Layer 3, Layer 5, residual + an "Identity model" section) — committed BEFORE this plan. No spec-edit task is needed; if the identity mechanism changes during implementation, update that spec section in the same commit.
- **`proposals-index.py` reuse (review item #11):** `resolve_proposal` re-implements newest/explicit selection inline rather than shelling `proposals-index.py`, to avoid a subprocess dependency for one-line selection logic. Intentional divergence — if `proposals-index.py`'s selection semantics change, mirror them here.
