# Hermes AIOS Improvement-Proposal Layer (Track A, Increment 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Hermes a read-only "improvement analyst" that, on request or on a schedule, analyzes a registered Claude Code project and writes a structured improvement proposal to Hermes state — never modifying the project.

**Architecture:** A new read-only `claude-code-proposer` skill runs `claude -p` (Sonnet, plan-mode, `Read,Grep,Glob`) to analyze a project, pipes the structured proposal to a deterministic `save-proposal.py` that persists it under `/opt/data/proposals/<project>/<ts>.md`, and surfaces the summary. A `proposals-index.py` lists/opens past proposals. Persistence and listing are Python (not LLM-driven) so they're deterministic and unit-testable.

**Tech Stack:** Nous Hermes Agent (Docker, `infra/hermes-agent/`); `claude -p` executor (Anthropic); Python 3 (stdlib only) for the two helpers; Markdown for the skill.

## Global Constraints

- **Read-only on projects, always:** every `claude -p` call uses `--permission-mode plan --allowedTools 'Read,Grep,Glob'`. Never write, edit, or run mutating commands in a project directory. The only artifact written is the proposal file, into Hermes state (`/opt/data/proposals`), never a project dir.
- **Three "never duplicate" rules (from the spec):** (1) never run `skill-refine`/`agent-refine` or mutate skills/agents; (2) never write a project's brain `canon/`/`active`; (3) never reinvent telemetry/`REFINE_RECOMMENDED`/`skill-eval` — read and cite them.
- **Grounding is file-reads only:** consume a project's brain/telemetry/eval by reading their files with `Read`/`Grep`/`Glob` — no script execution (preserves the no-Bash posture).
- **Model:** the proposer's `claude -p` analysis runs on `claude-sonnet-5`.
- **Python:** stdlib only (no new dependencies). Both helpers read their base dir from the `PROPOSALS_DIR` env var (default `/opt/data/proposals`) so they are testable on the host, mirroring `monitor-runs.py`'s `HERMES_CRON_DIR` pattern.
- **No registry or project-mount changes:** `claude_google_ads` stays `scope: read`; the proposer uses the existing `:ro` mounts, `/opt/registry`, `/opt/data`, and `/opt/cc-bin`.

## File Structure

- `infra/hermes-agent/bin/save-proposal.py` — persist a proposal (stdin → timestamped file). New.
- `infra/hermes-agent/bin/save-proposal.test.py` — unit test. New.
- `infra/hermes-agent/bin/proposals-index.py` — list/open proposals (read-only). New.
- `infra/hermes-agent/bin/proposals-index.test.py` — unit test. New.
- `infra/hermes-agent/skills/claude-code-proposer/SKILL.md` — the read-only proposer skill. New.
- `infra/hermes-agent/docker-compose.yml` — add the proposer-skill `:ro` mount. Modify.

---

### Task 1: `save-proposal.py` — deterministic proposal persistence

**Files:**
- Create: `infra/hermes-agent/bin/save-proposal.py`
- Test: `infra/hermes-agent/bin/save-proposal.test.py`

**Interfaces:**
- Consumes: proposal markdown on **stdin**; `--project <name>` arg; optional `--now <stamp>` (test hook); `PROPOSALS_DIR` env.
- Produces: writes `$PROPOSALS_DIR/<slug(project)>/<ts>.md`; prints the absolute written path to stdout; exit 0 on success, 1 on empty stdin.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/save-proposal.test.py`:

```python
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "save-proposal.py")


def run(args, stdin, env_extra):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, SCRIPT, *args],
                          input=stdin, capture_output=True, text=True, env=env)


class TestSaveProposal(unittest.TestCase):
    def test_writes_proposal_and_prints_path(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "claude_google_ads", "--now", "2026-07-23_10-00-00"],
                    "# Proposal\nbody", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            expected = os.path.join(d, "claude_google_ads", "2026-07-23_10-00-00.md")
            self.assertEqual(r.stdout.strip(), expected)
            self.assertEqual(open(expected).read(), "# Proposal\nbody")

    def test_slugs_project_name(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "My Ads!", "--now", "t"], "x", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "my-ads", "t.md")))

    def test_empty_stdin_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--project", "x", "--now", "t"], "   ", {"PROPOSALS_DIR": d})
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/bin/save-proposal.test.py -v`
Expected: FAIL — `save-proposal.py` does not exist (subprocess returns non-zero / errors).

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/save-proposal.py`:

```python
#!/usr/bin/env python3
"""Persist an improvement proposal to Hermes state (proposal read from stdin).

Deterministic persistence so the proposer skill never relies on the LLM to
write files. Reads proposal markdown from stdin, writes it to
$PROPOSALS_DIR/<project>/<UTC-timestamp>.md, and prints the written path.

Usage:  echo "<proposal md>" | save-proposal.py --project claude_google_ads
Env:    PROPOSALS_DIR  base dir (default /opt/data/proposals)
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone


def slug(s):
    return re.sub(r"[^a-z0-9_-]+", "-", s.strip().lower()).strip("-") or "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--now", help="override UTC timestamp (ISO-ish) for tests")
    args = ap.parse_args(argv)

    content = sys.stdin.read()
    if not content.strip():
        print("save-proposal: empty proposal on stdin; nothing written", file=sys.stderr)
        return 1

    base = os.environ.get("PROPOSALS_DIR", "/opt/data/proposals")
    ts = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    dest_dir = os.path.join(base, slug(args.project))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{ts}.md")
    with open(dest, "w") as f:
        f.write(content)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/bin/save-proposal.test.py -v`
Expected: PASS (3 tests OK).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/save-proposal.py infra/hermes-agent/bin/save-proposal.test.py
git commit -m "feat(hermes): save-proposal.py — deterministic proposal persistence"
```

---

### Task 2: `proposals-index.py` — list/open proposals (read-only monitor)

**Files:**
- Create: `infra/hermes-agent/bin/proposals-index.py`
- Test: `infra/hermes-agent/bin/proposals-index.test.py`

**Interfaces:**
- Consumes: `PROPOSALS_DIR` env; flags `--project <name>`, `--open <path>`, `--json`.
- Produces: default = human list (newest first) of `[project] <ts>` + summary + path; `--json` = list of `{project, timestamp, path, summary}`; `--open` = prints one file's content. Summary = first line under a `## Summary` heading, else first non-heading line.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/proposals-index.test.py`:

```python
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "proposals-index.py")


def run(args, env_extra):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, env=env)


class TestProposalsIndex(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = os.path.join(self.d, "claude_google_ads")
        os.makedirs(p)
        self.f = os.path.join(p, "2026-07-23_10-00-00.md")
        open(self.f, "w").write("# Improvement proposal\n## Summary\nTwo corrections found.\n")

    def test_json_lists_proposal_with_summary(self):
        r = run(["--json"], {"PROPOSALS_DIR": self.d})
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project"], "claude_google_ads")
        self.assertEqual(rows[0]["summary"], "Two corrections found.")

    def test_open_prints_content(self):
        r = run(["--open", self.f], {"PROPOSALS_DIR": self.d})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Two corrections found.", r.stdout)

    def test_empty_dir_reports_none(self):
        with tempfile.TemporaryDirectory() as empty:
            r = run([], {"PROPOSALS_DIR": empty})
            self.assertEqual(r.returncode, 0)
            self.assertIn("No proposals yet", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 infra/hermes-agent/bin/proposals-index.test.py -v`
Expected: FAIL — `proposals-index.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/proposals-index.py`:

```python
#!/usr/bin/env python3
"""List / open Hermes improvement proposals (read-only).

Usage:
  proposals-index.py                 # list all (newest first)
  proposals-index.py --project NAME  # filter to one project
  proposals-index.py --open PATH     # print one proposal's content
  proposals-index.py --json          # machine-readable list
Env:  PROPOSALS_DIR  base dir (default /opt/data/proposals)
"""
import argparse
import json
import os
import sys


def summary_of(path):
    try:
        lines = open(path).read().splitlines()
    except Exception:
        return ""
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("## summary"):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    for ln in lines:
        if ln.strip() and not ln.startswith("#"):
            return ln.strip()
    return ""


def collect(base, project=None):
    rows = []
    if not os.path.isdir(base):
        return rows
    projects = [project] if project else sorted(os.listdir(base))
    for proj in projects:
        pdir = os.path.join(base, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir), reverse=True):
            if fn.endswith(".md"):
                path = os.path.join(pdir, fn)
                rows.append({"project": proj, "timestamp": fn[:-3],
                             "path": path, "summary": summary_of(path)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--open")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base = os.environ.get("PROPOSALS_DIR", "/opt/data/proposals")

    if args.open:
        if not os.path.isfile(args.open):
            print(f"proposals-index: not found: {args.open}", file=sys.stderr)
            return 1
        sys.stdout.write(open(args.open).read())
        return 0

    rows = collect(base, args.project)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No proposals yet.")
        return 0
    for r in rows:
        print(f"[{r['project']}] {r['timestamp']}")
        print(f"    {r['summary']}")
        print(f"    {r['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 infra/hermes-agent/bin/proposals-index.test.py -v`
Expected: PASS (3 tests OK).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/proposals-index.py infra/hermes-agent/bin/proposals-index.test.py
git commit -m "feat(hermes): proposals-index.py — list/open improvement proposals"
```

---

### Task 3: `claude-code-proposer` skill + compose mount + load verification

**Files:**
- Create: `infra/hermes-agent/skills/claude-code-proposer/SKILL.md`
- Modify: `infra/hermes-agent/docker-compose.yml` (add the proposer-skill `:ro` mount)

**Interfaces:**
- Consumes: the project registry at `/opt/registry/projects.yaml`; `/opt/cc-bin/save-proposal.py` (Task 1); the read-only `:ro` project mounts.
- Produces: a loaded Hermes skill named `claude-code-proposer` that, given a project name, produces and persists a proposal.

- [ ] **Step 1: Write the skill**

Create `infra/hermes-agent/skills/claude-code-proposer/SKILL.md`:

```markdown
---
name: claude-code-proposer
description: >
  Analyze a REGISTERED Claude Code project (read-only) and produce a structured
  IMPROVEMENT PROPOSAL — enhancements, corrections, new features, or new
  projects — grounded in the project's code and any existing results. Use when
  the user asks to "review", "propose improvements for", "audit for
  opportunities", or "suggest enhancements/new features" for a project by name.
  Proposes only; never modifies the project. Writes the proposal to Hermes
  state via save-proposal.py.
version: 0.1.0
author: claude_code AIOS (P5 Track A)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Claude-Code, Improvement-Proposal, Read-Only, AIOS, Analysis]
    related_skills: [claude-code-operator, claude-code]
---

# Claude Code Proposer — read-only improvement proposals

You are the control plane. This skill analyzes a registered Claude Code project
and proposes improvements. It is strictly READ-ONLY on projects: it never edits,
commits, or runs mutating commands. It proposes; the human + Claude Code build.

## 1. Resolve the project (read-only)

Read the registry to resolve the project name to its read `workdir`:

    cat /opt/registry/projects.yaml

If the name is not present, tell the user and list the registered names. Never
analyze an unregistered path.

## 2. Analyze (read-only claude -p, Sonnet)

Run Claude Code in the project's read-only workdir to analyze it. Use EXACTLY:

    terminal(
      command="claude -p '<analysis instruction below>' \
        --model claude-sonnet-5 --allowedTools 'Read,Grep,Glob' --permission-mode plan",
      workdir="<workdir from registry>",
      timeout=240
    )

Analysis instruction to pass to claude -p:

    Analyze this project and produce a STRUCTURED IMPROVEMENT PROPOSAL in this
    exact markdown shape:

    # Improvement proposal — <project> — <UTC timestamp>
    ## Summary
    <2-3 sentences>
    ## Items (prioritized)
    - [P1] type: enhancement | correction | feature | new-project
          title: ...
          rationale: ... (grounded in what you actually read)
          evidence: <file paths / observed facts>
          impact / effort: <rough sizing>
    - [P2] ...
    ## Sources consulted
    <code paths; and any brain/telemetry/eval files you read>

    Ground every item in evidence you actually read. Prefer corrections and
    high-impact enhancements first. It is fine to propose an entirely new
    project when the gap warrants it.

## 3. Ground on claude_code signals IF present (read-only, file reads only)

If the project contains any of these, READ them (Read/Grep/Glob only — do NOT
execute scripts) and fold their signals into the proposal, citing them:
- `.project-brain/` — read `canon/`, `decisions/`, `index.md`, `MEMORY.md` to
  align with governance and AVOID re-proposing already-rejected ideas.
- `evals/telemetry/usage-summary.json` and any `REFINE_RECOMMENDED` flags —
  real-usage signals.
- `SKILL-EVAL.md` / `<agent>-EVAL.md` / `project-audit` outputs — quality signals.

## 4. Boundaries — NEVER duplicate claude_code's own machinery

- NEVER run `skill-refine` / `agent-refine` or mutate skills/agents. Capability-
  level improvement is delegated to the project's OWN pipeline if installed —
  you only surface and cite its `REFINE_RECOMMENDED` flags.
- NEVER write to a project's brain `canon/` or `active/`. Read only.
- NEVER reinvent telemetry / `REFINE_RECOMMENDED` / `skill-eval`. Read and cite.

You work at the OPERATIONS/project level (features, corrections, strategy, new
projects); the capability level (skills/agents) belongs to the project's pipeline.

## 5. Persist and surface

Take claude's full proposal output and persist it deterministically:

    <claude's proposal markdown> | python3 /opt/cc-bin/save-proposal.py --project <name>

save-proposal.py prints the written path. Then give the user the `## Summary`
and the saved path. Do NOT write anywhere except via save-proposal.py (which
writes only under Hermes state, never a project).

## 6. Scheduling & monitoring

To run unattended: `hermes cron create <schedule> --skill claude-code-proposer
"review <project> and propose improvements"`. List past proposals with
`python3 /opt/cc-bin/proposals-index.py` (add `--project <name>` or `--open <path>`).
```

- [ ] **Step 2: Verify the skill frontmatter parses**

Run:
```bash
python3 - <<'PY'
import re, sys
t = open("infra/hermes-agent/skills/claude-code-proposer/SKILL.md").read()
m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
assert m, "no frontmatter block"
fm = m.group(1)
for key in ("name:", "description:", "version:"):
    assert key in fm, f"missing {key}"
assert "name: claude-code-proposer" in fm
print("frontmatter OK")
PY
```
Expected: prints `frontmatter OK`.

- [ ] **Step 3: Add the proposer-skill mount to compose**

In `infra/hermes-agent/docker-compose.yml`, in the `hermes-agent` service `volumes:` list, add the proposer mount immediately after the `claude-code-operator` mount:

```yaml
      - ./skills/claude-code-operator:/opt/data/skills/claude-code-operator:ro  # operator skill
      - ./skills/claude-code-proposer:/opt/data/skills/claude-code-proposer:ro  # proposer skill (read-only)
      - ./bin:/opt/cc-bin:ro            # operational helpers (run monitor, read-only)
```

- [ ] **Step 4: Recreate and verify the skill loads**

Run:
```bash
cd infra/hermes-agent && docker compose up -d
for i in $(seq 1 10); do docker compose exec -T hermes-agent hermes gateway status 2>/dev/null | grep -q running && break; sleep 2; done
docker compose exec -T hermes-agent sh -c 'ls /opt/data/skills/claude-code-proposer/ && hermes skills list 2>&1 | grep -i proposer'
```
Expected: `SKILL.md` listed, and a `claude-code-proposer … local … enabled` row.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/skills/claude-code-proposer/SKILL.md infra/hermes-agent/docker-compose.yml
git commit -m "feat(hermes): claude-code-proposer skill (read-only improvement proposals)"
```

---

### Task 4: End-to-end verification (real proposal, project untouched)

**Files:** none (verification task). Deliverable: the working feature, proven end-to-end.

**Interfaces:**
- Consumes: Tasks 1–3 (skill loaded, `save-proposal.py`, `proposals-index.py`).
- Produces: evidence that a proposal is generated, persisted, listable, and the project is untouched.

- [ ] **Step 1: Capture the project's pre-run git state (to prove it's untouched)**

Run:
```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_google_ads && git status --porcelain | wc -l'
```
Expected: `0` (clean working tree in the read-only mount).

- [ ] **Step 2: Ask Hermes to produce a proposal (read-only)**

Run:
```bash
cd infra/hermes-agent
timeout 300 docker compose exec -T hermes-agent hermes --accept-hooks -z \
"Use the claude-code-proposer skill. Review the claude_google_ads project and propose improvements. Then tell me the summary and the saved path."
```
Expected: a summary plus a saved path under `/opt/data/proposals/claude_google_ads/…md`.

- [ ] **Step 3: Verify the proposal was persisted with structure**

Run:
```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c '
  f=$(ls -t /opt/data/proposals/claude_google_ads/*.md 2>/dev/null | head -1);
  echo "FILE: $f";
  grep -qE "^## Items" "$f" && grep -qE "\[P1\]" "$f" && echo "STRUCTURED OK" || echo "STRUCTURE MISSING"'
```
Expected: `FILE: …` and `STRUCTURED OK`.

- [ ] **Step 4: Verify the project is untouched**

Run:
```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_google_ads && git status --porcelain | wc -l'
```
Expected: `0` (still clean — the proposer wrote nothing into the project).

- [ ] **Step 5: Verify the proposal is listable via the index**

Run:
```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent python3 /opt/cc-bin/proposals-index.py --project claude_google_ads
```
Expected: one row for `claude_google_ads` with a timestamp, summary, and path.

- [ ] **Step 6: Commit the verification evidence (README note)**

Append a short "Improvement proposals (Track A)" usage note to `infra/hermes-agent/README.md` documenting the ask command, `proposals-index.py`, and the `/opt/data/proposals` location, then:

```bash
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): document the improvement-proposal (Track A) workflow"
```

---

## Self-Review

- **Spec coverage:** proposer skill (Task 3) ✓; written-proposal form + structure/template (Task 3 skill + Task 1 persistence) ✓; storage `/opt/data/proposals/<project>/<ts>.md` (Task 1) ✓; Sonnet model (Task 3, Global Constraints) ✓; on-demand trigger (Task 4) + schedulable via cron (Task 3 skill §6) ✓; monitor/index (Task 2) ✓; boundaries + three never-duplicate rules (Task 3 skill §4, Global Constraints) ✓; grounding by file-reads on brain/telemetry/eval (Task 3 skill §3) ✓; read-only guardrails + project-untouched verification (Global Constraints, Task 4) ✓. Deferred items (draft-PR delivery, Track B, install brain into ads project, Central Operator Brain) are intentionally out of scope for this plan.
- **Placeholder scan:** no TBD/TODO; all code and commands are literal. The `<...>` tokens inside the skill's *instruction text* are intentional templates the LLM fills at runtime, not plan placeholders.
- **Type consistency:** `PROPOSALS_DIR` env, `--project`/`--now`/`--open`/`--json` flags, and the `{project, timestamp, path, summary}` row shape are used identically across Tasks 1, 2, and the skill's `save-proposal.py` invocation.
