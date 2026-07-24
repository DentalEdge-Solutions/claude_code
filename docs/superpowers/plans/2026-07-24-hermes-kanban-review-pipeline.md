# Kanban Multi-Agent Read-Only Review Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stand up the first AIOS Kanban orchestration use-case — a fixed-template review pipeline where provably-confined named-profile workers analyze `claude_code` in parallel (architecture/tests/risks) and a synthesizer fuses their handoffs into one improvement proposal persisted to Hermes state, project untouched.

**Architecture:** Deterministic control-plane scripts (`make-review-board.py`, `persist-review-proposal.py`, `setup-review-team.sh`) + a read-only worker skill (`claude-code-reviewer`) + four confined Hermes profiles running under the gateway's Kanban dispatcher. Confinement is by toolset, not by trust.

**Tech Stack:** Nous Hermes Agent (Docker, `infra/hermes-agent/`); `hermes kanban`/`profile`/`tools` CLIs; Python 3 (stdlib only); Markdown skill. Reuses `save-proposal.py`, `proposals-index.py`, the registry.

## Global Constraints

- **Worker confinement (five layers, must all hold):** `:ro` project mounts; a `review-readonly` toolset = ONLY `read_file, search_files, skill_view, kanban_show, kanban_complete, kanban_comment, kanban_heartbeat, kanban_block` (NO `write_file`/`patch`/`terminal`/`process`/`execute_code`/`delegate_task`/browser/web); NO fan-out tools (`kanban_create`/`kanban_link`/`kanban_unblock`); `--workspace scratch`; `--max-runtime`.
- **No `claude -p` in workers** (it needs the terminal tool → breaks confinement). Workers analyze directly.
- **Read-only on projects:** the project's git tree must be clean before AND after; the only writes are Kanban state + the proposal under `/opt/data/proposals`.
- **Never-duplicate boundary rules** (in the skill): no `skill-refine`/`agent-refine`/skill mutation; no brain `canon`/`active` writes; no reinventing telemetry/`skill-eval` (read+cite).
- **Python:** stdlib only; scripts read `PROPOSALS_DIR` default `/opt/data/proposals`; kanban DB at `/opt/data/kanban.db` overridable via `HERMES_KANBAN_DB` for tests.
- **Determinism:** decomposition is a fixed template — no LLM orchestrator; workers get no fan-out tools.

## File Structure

- `infra/hermes-agent/bin/setup-review-team.sh` — idempotent: create the `review-readonly` toolset + 4 confined profiles. New.
- `infra/hermes-agent/skills/claude-code-reviewer/SKILL.md` — read-only analysis + synthesis skill. New.
- `infra/hermes-agent/bin/make-review-board.py` (+ `.test.py`) — deterministic board creation (`--dry-run` testable). New.
- `infra/hermes-agent/bin/persist-review-proposal.py` (+ `.test.py`) — synthesis metadata → `save-proposal.py`. New.
- `infra/hermes-agent/docker-compose.yml` — mount the new skill. Modify.

---

### Task 1: Confirm the `review-readonly` toolset mechanism (spike → create or fall back)

**Files:** none yet (produces a decision + a created toolset or a documented fallback).

The custom-toolset registration path is the one unconfirmed piece. Resolve it before building on it.

- [ ] **Step 1: Probe how custom toolsets are registered**

Run (in `infra/hermes-agent`):
```bash
docker compose exec -T hermes-agent sh -c 'hermes tools --help 2>&1; echo ---; grep -rniE "platform_toolsets|save.*toolset|custom.*toolset|register_toolset|user.*toolset" /opt/hermes/hermes_cli/tools_config.py 2>/dev/null | head -20'
```
Determine whether a named custom toolset with an explicit tool list can be saved (via `hermes tools`, a `platform_toolsets` config entry, or a plugin `plugin.yaml`).

- [ ] **Step 2: Decide and record the branch**

- **Branch A — custom toolset supported:** create `review-readonly` with EXACTLY the 8 tools in Global Constraints. Record the exact command/config used.
- **Branch B — not cleanly supported:** fall back to group-level `toolsets: [file, kanban]` and **update the spec's confinement claim**: the residual is `write_file`/`patch` able to write `/opt/data` (projects stay protected by `:ro`), and `kanban_create`/`link` remain (fan-out) unless a `disabled_toolsets`/per-tool gate removes them. Document this honestly; do not claim "no write" if Branch B.

- [ ] **Step 3: Verify the toolset resolves to the intended tool set**

Run:
```bash
docker compose exec -T hermes-agent sh -c 'hermes tools list 2>&1 | grep -iE "review-readonly|read_file|write_file|terminal" | head'
```
Expected (Branch A): `review-readonly` present; includes `read_file`, excludes `write_file`/`terminal`.

- [ ] **Step 4: Commit the decision**

Record the outcome in the spec's "Deferred / open" section (edit `docs/superpowers/specs/2026-07-24-hermes-kanban-review-pipeline-design.md`), then:
```bash
git add docs/superpowers/specs/2026-07-24-hermes-kanban-review-pipeline-design.md
git commit -m "docs(hermes): record review-readonly toolset mechanism (Task 1 spike)"
```

---

### Task 2: `setup-review-team.sh` — create the four confined profiles (idempotent)

**Files:** Create `infra/hermes-agent/bin/setup-review-team.sh`

**Interfaces:** Produces profiles `architect`, `test-analyst`, `risk-analyst`, `synthesizer`, each `--no-skills`, described, and pinned to the confined toolset from Task 1.

- [ ] **Step 1: Write the script**

Create `infra/hermes-agent/bin/setup-review-team.sh`:
```bash
#!/bin/sh
# Create the four confined review-team profiles (idempotent). Each profile is
# no-skills, described for its role, and pinned to the confined toolset from
# Task 1 (default: review-readonly). Run inside the container.
set -eu
TOOLSET="${REVIEW_TOOLSET:-review-readonly}"

set_profile() {  # name  description
  name="$1"; desc="$2"
  hermes profile show "$name" >/dev/null 2>&1 || hermes profile create "$name" --no-skills
  hermes profile describe "$name" "$desc" || true
  # Pin the confined toolset in the profile's own config.yaml.
  hermes --ignore-user-config config set --profile "$name" toolsets "[$TOOLSET]" \
    2>/dev/null || hermes config set model.toolsets "[$TOOLSET]" --profile "$name" 2>/dev/null || \
    echo "WARN: could not pin toolsets for $name via CLI; set profiles/$name/config.yaml manually" >&2
  echo "profile ready: $name (toolset=$TOOLSET)"
}

set_profile architect     "Read-only software architecture analyst: structure, boundaries, coupling, design risks. Never writes."
set_profile test-analyst  "Read-only test/quality analyst: coverage gaps, test design, CI. Never writes."
set_profile risk-analyst  "Read-only risk/security analyst: failure modes, unsafe patterns, security gaps. Never writes."
set_profile synthesizer   "Read-only synthesis coordinator: fuses specialist handoffs into one prioritized improvement proposal. Never writes."
```

- [ ] **Step 2: Run it and verify confinement**

```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c 'chmod +x /opt/cc-bin/setup-review-team.sh 2>/dev/null; REVIEW_TOOLSET='"${REVIEW_TOOLSET:-review-readonly}"' /opt/cc-bin/setup-review-team.sh'
docker compose exec -T hermes-agent sh -c 'hermes profile list 2>&1 | grep -iE "architect|test-analyst|risk-analyst|synthesizer"'
```
Expected: 4 profiles listed. (If Step 1's CLI toolset-pin path failed, set each `/opt/data/profiles/<name>/config.yaml` `toolsets: [<TOOLSET>]` directly and re-verify.)

- [ ] **Step 3: Prove a profile's resolved toolset excludes write/terminal**

```bash
docker compose exec -T hermes-agent sh -c 'grep -nE "toolsets" /opt/data/profiles/architect/config.yaml 2>/dev/null; echo "must NOT include write_file/terminal"'
```
Expected: `toolsets: [review-readonly]` (or the Task 1 fallback), not `hermes-cli`.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/bin/setup-review-team.sh
git commit -m "feat(hermes): setup-review-team.sh — four confined review profiles"
```

---

### Task 3: `claude-code-reviewer` skill + compose mount

**Files:** Create `infra/hermes-agent/skills/claude-code-reviewer/SKILL.md`; Modify `infra/hermes-agent/docker-compose.yml`

- [ ] **Step 1: Write the skill**

Create `infra/hermes-agent/skills/claude-code-reviewer/SKILL.md`:
```markdown
---
name: claude-code-reviewer
description: >
  Read-only project review WORKER for the Kanban review pipeline. Two modes.
  ANALYSIS: analyze one assigned dimension (architecture | tests | risks) of a
  project by reading its files, then hand off structured findings. SYNTHESIS:
  fuse the specialist handoffs into one prioritized improvement proposal. Never
  modifies anything; has only read + minimal-kanban tools.
version: 0.1.0
author: claude_code AIOS (Kanban review pipeline)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Claude-Code, Kanban, Review, Read-Only, AIOS, Multi-Agent]
    related_skills: [claude-code-proposer]
---

# Claude Code Reviewer — read-only Kanban review worker

You are a confined Kanban worker. You have ONLY read-only file tools
(`read_file`, `search_files`), `skill_view`, and a minimal kanban subset. You
CANNOT write files, run commands, use the network, or spawn agents. Do not try.

Your task title/body tell you the MODE and the target project workdir.

## ANALYSIS mode (title starts with "analyze-")

Your dimension is in the title: `analyze-architecture` | `analyze-tests` | `analyze-risks`.
1. Read the project at its workdir using `read_file` / `search_files` (read-only).
   Focus ONLY on your dimension:
   - architecture: structure, module boundaries, coupling, design smells, altitude.
   - tests: coverage gaps, test design/quality, CI/test entry points.
   - risks: failure modes, unsafe patterns, security/secret handling, missing guardrails.
2. If the project has `.project-brain/`, `evals/telemetry/usage-summary.json`, or
   `SKILL-EVAL.md`, READ them to ground and AVOID re-proposing rejected ideas —
   read only; never write them.
3. Call `kanban_complete` with a structured handoff:
   `summary` = 1-2 sentences; `metadata` = {"dimension": "<yours>", "findings":
   [{"title","detail","evidence","impact"}]}. Ground every finding in files you read.

## SYNTHESIS mode (title == "synthesize")

1. Read the three parent handoffs via `kanban_show` (they arrive as parent context).
2. Produce ONE combined proposal in this exact markdown:
   `# Improvement proposal — <project> — <UTC ts>` / `## Summary` /
   `## Items (prioritized)` with `[P#] type: enhancement|correction|feature|new-project`,
   title, rationale, evidence, impact — deduped/merged across dimensions /
   `## Sources consulted`.
3. Call `kanban_complete` with `metadata` = {"proposal_markdown": "<the full doc>"}.
   Do NOT try to write a file — persistence is handled outside you.

## Boundaries (never duplicate claude_code's machinery)
- Never attempt skill-refine/agent-refine or skill/agent mutation (you can't — no terminal).
- Never write a project's brain canon/active (you can't — no write tool). Read only.
- Never reinvent telemetry/REFINE_RECOMMENDED/skill-eval — read and cite.
```

- [ ] **Step 2: Add the skill mount to compose**

In `infra/hermes-agent/docker-compose.yml`, add after the `claude-code-proposer` mount:
```yaml
      - ./skills/claude-code-reviewer:/opt/data/skills/claude-code-reviewer:ro  # kanban review worker skill (read-only)
```

- [ ] **Step 3: Recreate and verify the skill loads**

```bash
cd infra/hermes-agent && docker compose up -d
for i in $(seq 1 10); do docker compose exec -T hermes-agent hermes gateway status 2>/dev/null | grep -q running && break; sleep 2; done
docker compose exec -T hermes-agent sh -c 'hermes skills list 2>&1 | grep -i reviewer'
```
Expected: `claude-code-reviewer … local … enabled`.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/skills/claude-code-reviewer/SKILL.md infra/hermes-agent/docker-compose.yml
git commit -m "feat(hermes): claude-code-reviewer skill (read-only kanban review worker)"
```

---

### Task 4: `make-review-board.py` + test (deterministic board creation)

**Files:** Create `infra/hermes-agent/bin/make-review-board.py`, `infra/hermes-agent/bin/make-review-board.test.py`

**Interfaces:** `make-review-board.py --project <name> [--dry-run] [--max-runtime 20m]`. `--dry-run` prints the planned tasks as JSON (no board writes) — the testable surface. Live mode shells `hermes kanban create` per task.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/make-review-board.test.py`:
```python
import json, os, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "make-review-board.py")


def run(args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestMakeReviewBoard(unittest.TestCase):
    def test_dry_run_plans_fixed_four_task_shape(self):
        r = run(["--project", "claude_code", "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = json.loads(r.stdout)
        titles = [t["title"] for t in plan]
        self.assertEqual(titles, ["analyze-architecture", "analyze-tests",
                                  "analyze-risks", "synthesize"])
        by = {t["title"]: t for t in plan}
        self.assertEqual(by["analyze-architecture"]["assignee"], "architect")
        self.assertEqual(by["synthesize"]["parents"],
                         ["analyze-architecture", "analyze-tests", "analyze-risks"])
        for t in plan:
            self.assertEqual(t["workspace"], "scratch")
            self.assertEqual(t["skill"], "claude-code-reviewer")

    def test_requires_project(self):
        r = run(["--dry-run"])
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — verify it fails**

Run: `python3 infra/hermes-agent/bin/make-review-board.test.py -v` → FAIL (script missing).

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/make-review-board.py`:
```python
#!/usr/bin/env python3
"""Create the fixed Kanban review-board shape for a project (deterministic).

--dry-run prints the planned tasks as JSON (testable, no writes). Live mode
shells `hermes kanban create` for each task. No LLM decomposition.

Usage:  make-review-board.py --project claude_code [--dry-run] [--max-runtime 20m]
"""
import argparse
import json
import subprocess
import sys

ANALYSES = [
    ("analyze-architecture", "architect"),
    ("analyze-tests", "test-analyst"),
    ("analyze-risks", "risk-analyst"),
]
SKILL = "claude-code-reviewer"


def plan(project, max_runtime):
    tasks = []
    for title, assignee in ANALYSES:
        tasks.append({"title": title, "assignee": assignee, "parents": [],
                      "workspace": "scratch", "skill": SKILL,
                      "max_runtime": max_runtime,
                      "body": f"MODE: analysis. Project: {project}. "
                              f"Analyze the '{title.split('-', 1)[1]}' dimension read-only."})
    tasks.append({"title": "synthesize", "assignee": "synthesizer",
                  "parents": [t for t, _ in ANALYSES], "workspace": "scratch",
                  "skill": SKILL, "max_runtime": max_runtime,
                  "body": f"MODE: synthesis. Project: {project}. Fuse the three "
                          f"parent handoffs into one prioritized proposal."})
    return tasks


def create(task):
    cmd = ["hermes", "kanban", "create", task["title"],
           "--assignee", task["assignee"], "--workspace", task["workspace"],
           "--skill", task["skill"], "--max-runtime", task["max_runtime"],
           "--body", task["body"]]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"kanban create failed for {task['title']}: {out.stderr}")
    return out.stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-runtime", default="20m")
    args = ap.parse_args(argv)

    tasks = plan(args.project, args.max_runtime)
    if args.dry_run:
        print(json.dumps(tasks, indent=2))
        return 0
    # Live: create analyses first, then synthesis linked to their ids.
    ids = {}
    for t in tasks[:-1]:
        ids[t["title"]] = create(t)
    syn = tasks[-1]
    syn_cmd_id = create(syn)
    for parent_title in syn["parents"]:
        link = subprocess.run(["hermes", "kanban", "link", ids[parent_title], syn_cmd_id],
                              capture_output=True, text=True)
        if link.returncode != 0:
            print(f"warn: link {parent_title}->synthesize failed: {link.stderr}", file=sys.stderr)
    print(f"created review board for {args.project}: {list(ids.values()) + [syn_cmd_id]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test — verify it passes**

Run: `python3 infra/hermes-agent/bin/make-review-board.test.py -v` → PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/make-review-board.py infra/hermes-agent/bin/make-review-board.test.py
git commit -m "feat(hermes): make-review-board.py — deterministic kanban review board"
```

---

### Task 5: `persist-review-proposal.py` + test (synthesis → save-proposal.py)

**Files:** Create `infra/hermes-agent/bin/persist-review-proposal.py`, `infra/hermes-agent/bin/persist-review-proposal.test.py`

**Interfaces:** `persist-review-proposal.py --project <name> --content-file <path>` reads proposal markdown from the file (the synthesis task's `proposal_markdown` metadata, extracted by the caller) and pipes it to `save-proposal.py`. Kept content-agnostic and executes nothing.

- [ ] **Step 1: Write the failing test**

Create `infra/hermes-agent/bin/persist-review-proposal.test.py`:
```python
import os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "persist-review-proposal.py")


class TestPersist(unittest.TestCase):
    def test_persists_content_via_save_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            cf = os.path.join(d, "content.md")
            open(cf, "w").write("# Improvement proposal\n## Summary\nteam review.\n")
            env = {**os.environ, "PROPOSALS_DIR": d}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code",
                                "--content-file", cf], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            written = r.stdout.strip()
            self.assertTrue(written.startswith(os.path.join(d, "claude_code") + os.sep), written)
            self.assertIn("team review.", open(written).read())

    def test_missing_content_file_fails(self):
        r = subprocess.run([sys.executable, SCRIPT, "--project", "p",
                            "--content-file", "/no/such"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — verify it fails**

Run: `python3 infra/hermes-agent/bin/persist-review-proposal.test.py -v` → FAIL (script missing).

- [ ] **Step 3: Write the implementation**

Create `infra/hermes-agent/bin/persist-review-proposal.py`:
```python
#!/usr/bin/env python3
"""Persist a synthesized review proposal via save-proposal.py (trusted, out-of-worker).

Reads proposal markdown from --content-file (the synthesis task's
proposal_markdown metadata, extracted by the caller) and pipes it to
save-proposal.py. Content-agnostic; never executes the content.

Usage:  persist-review-proposal.py --project claude_code --content-file <path>
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE = os.path.join(HERE, "save-proposal.py")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--content-file", required=True)
    args = ap.parse_args(argv)

    if not os.path.isfile(args.content_file):
        print(f"persist-review-proposal: no such content file: {args.content_file}", file=sys.stderr)
        return 1
    with open(args.content_file) as f:
        content = f.read()
    out = subprocess.run([sys.executable, SAVE, "--project", args.project],
                         input=content, capture_output=True, text=True)
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    return out.returncode


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test — verify it passes**

Run: `python3 infra/hermes-agent/bin/persist-review-proposal.test.py -v` → PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/persist-review-proposal.py infra/hermes-agent/bin/persist-review-proposal.test.py
git commit -m "feat(hermes): persist-review-proposal.py — synthesis -> save-proposal"
```

---

### Task 6: End-to-end verification (confined workers, project untouched)

**Files:** none (verification). Deliverable: the pipeline proven end-to-end.

- [ ] **Step 1: Pre-run project git state**

```bash
cd infra/hermes-agent
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_code && git status --porcelain | wc -l'
```
Expected: `0`.

- [ ] **Step 2: Create the board and dispatch (bounded concurrency)**

```bash
docker compose exec -T hermes-agent python3 /opt/cc-bin/make-review-board.py --project claude_code
docker compose exec -T hermes-agent hermes kanban dispatch --max 2
# poll until synthesize is done (up to ~15m); print terminal states
docker compose exec -T hermes-agent hermes kanban list 2>&1 | tail -20
```
Expected: the four tasks progress to `done`; `synthesize` completes only after the three analyses.

- [ ] **Step 3: Confinement proof — a worker's resolved toolset excludes write/terminal**

```bash
docker compose exec -T hermes-agent sh -c 'hermes kanban runs 2>&1 | head; grep -nE "toolsets" /opt/data/profiles/architect/config.yaml'
```
Expected: `architect` toolset is the confined set (no `write_file`/`terminal`). (If Task 1 = Branch B, assert the documented fallback instead.)

- [ ] **Step 4: Persist + verify the proposal**

```bash
# extract the synthesis proposal_markdown to a file, then persist
docker compose exec -T hermes-agent sh -c 'python3 - <<PY > /tmp/prop.md
import json, sqlite3
c=sqlite3.connect("/opt/data/kanban.db"); c.row_factory=sqlite3.Row
row=[r for r in c.execute("SELECT * FROM runs ORDER BY rowid DESC")][0]
import re
# find proposal_markdown in the latest synthesize run metadata
for r in c.execute("SELECT * FROM runs"):
    d=dict(r)
    for v in d.values():
        if isinstance(v,str) and "proposal_markdown" in v:
            print(json.loads(v).get("proposal_markdown","")); raise SystemExit
PY
python3 /opt/cc-bin/persist-review-proposal.py --project claude_code --content-file /tmp/prop.md'
docker compose exec -T hermes-agent python3 /opt/cc-bin/proposals-index.py --project claude_code | head -4
```
Expected: a saved proposal path under `/opt/data/proposals/claude_code/`, listable.

- [ ] **Step 5: Read-only proof — project untouched + no fan-out**

```bash
docker compose exec -T hermes-agent sh -c 'cd /projects/claude_code && git status --porcelain | wc -l'
docker compose exec -T hermes-agent sh -c 'grep -nE "kanban_create|kanban_link" /opt/data/profiles/*/config.yaml || echo "no fan-out tools in profiles (expected)"'
```
Expected: `0` (clean); no fan-out tools.

- [ ] **Step 6: Document + commit**

Append a "Kanban review pipeline" usage note to `infra/hermes-agent/README.md` (setup-review-team.sh → make-review-board.py → dispatch → persist → proposals-index), then:
```bash
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): document the Kanban review pipeline workflow"
```

---

## Self-Review

- **Spec coverage:** confined profiles (T2) ✓; custom toolset (T1 spike, with honest fallback) ✓; reviewer skill w/ analysis+synthesis+boundaries (T3) ✓; deterministic board incl. workspace/max-runtime/skill (T4) ✓; out-of-worker persistence reusing save-proposal (T5) ✓; five-layer confinement + read-only + fan-out proofs (Global Constraints, T6) ✓; alignment/purpose live in the spec. Deferred (dynamic decomposition, domain-specialist profiles, auto-persist hook, write pipelines) intentionally out of scope.
- **Placeholder scan:** Task 1 is a genuine spike with two explicit branches + a concrete success check — not a placeholder; every code/command step is literal.
- **Type/name consistency:** `PROPOSALS_DIR`, `--project`, `--content-file`, `--dry-run`, the four profile names, the `review-readonly` toolset name, and the `claude-code-reviewer` skill name are used identically across tasks. `save-proposal.py` invoked with the same `--project` contract as its own tests.
- **Known risk carried into execution:** if Task 1 = Branch B (no custom toolset), the confinement is group-level with a documented `/opt/data`-write + fan-out residual — the plan says to update the spec's claim rather than overstate the guarantee.
