#!/usr/bin/env node
// scripts/retired-skill-guardian.test.js — P0-04 acceptance: the skill-guardian agent is retired, and no tracked
// file still names it or its report (PROJECT-SKILL-HEALTH.md). It had 0 invocations July-October 2026 (S2 §1) and was
// a write-capable reader of untrusted text, so a stale reference would point users and other agents at an agent
// that no longer exists. Record: docs/evaluations/2026-10-24-p0-04-retire-skill-guardian.md.
//
// Files come from `git ls-files` (what CI checks out). Without git (a source export), the test walks the tree,
// skipping .git and node_modules; such a tree holds no generated or ignored files.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
const SELF = path.relative(REPO, __filename).split(path.sep).join('/');
let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const RETIRED = /skill-guardian|PROJECT-SKILL-HEALTH/i;

// Each exclusion is a record of the past that must not be rewritten, or a path this repo never reads.
const EXCLUDED_PREFIXES = [
  // Canon changes only through brain-promote --approve (DECISION-S3-5). The charter line
  // (.project-brain/canon/2026-07-17-ai-os-charter.md:33) stays a known stale reference until the owner's
  // charter decision (D-07, option a).
  '.project-brain/canon/',
  // Dated evaluation records, including the S1-S6 strategy and this item's own record: history, not guidance.
  'docs/evaluations/',
  // Dated design plans and specs.
  'docs/superpowers/',
  // Hermes runtime data: never read by any check in this repo (project rule). Nothing there is tracked.
  'infra/hermes-agent/data/',
];
// Dated eval reports (SKILL-EVAL.md, <agent>-EVAL.md, SKILL-REFINE-LOG.md): each records one past run.
const EXCLUDED_BASENAME = /-EVAL\.md$|-REFINE-LOG\.md$/;
// Single files, by exact path. The brain's record of the retirement itself, promoted 2026-10-27: it must name the
// agent so a later session can find why it went. Like canon, it changes only through brain-promote --approve. Every
// other active decision is still checked.
const EXCLUDED_FILES = [
  '.project-brain/decisions/active/2026-10-24-p0-04-claude-md-evals-rule-amended-option-1-2026-10-24.md',
];
// One allowed line, not a file: the README's manual cleanup for targets that already have the agent installed
// (uninstall.sh discovers agents from this repo, so it cannot remove a file the repo no longer has). It must name the
// file to delete. The whole line must be equal (PR4-R-1: a substring match let a second reference ride on it), and
// the test below requires it exactly once, so the allowance cannot widen or go stale silently.
const ALLOWED_LINE = {
  file: 'README.md',
  line: 'Retired agent: `uninstall.sh` removes only the agents this repo still has, so if an earlier install copied ' +
    'the retired health-check agent into a target, delete `<target>/.claude/agents/skill-guardian.md` by hand.',
};

// null: the line names nothing retired; 'allowed': the one allowed cleanup line; 'hit': a stale reference.
function classify(rel, line) {
  if (!RETIRED.test(line)) return null;
  if (rel === ALLOWED_LINE.file && line === ALLOWED_LINE.line) return 'allowed';
  return 'hit';
}

function excluded(rel) {
  if (rel === SELF) return true;
  if (EXCLUDED_FILES.includes(rel)) return true;
  if (EXCLUDED_PREFIXES.some(p => rel.startsWith(p))) return true;
  return EXCLUDED_BASENAME.test(path.posix.basename(rel));
}

function walk(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === '.git' || e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.isFile()) out.push(path.relative(REPO, p).split(path.sep).join('/'));
  }
  return out;
}

function trackedFiles() {
  const r = spawnSync('git', ['ls-files', '-z'], { cwd: REPO, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  if (r.status === 0 && r.stdout) return { source: 'git ls-files', files: r.stdout.split('\0').filter(Boolean) };
  return { source: 'fs walk', files: walk(REPO, []) };
}

const { source, files } = trackedFiles();

test(`file list is non-empty (${source}, ${files.length} files)`, () => {
  assert.ok(files.length > 0, 'no files found');
});

test('the retired agent definition, its report and its eval scenarios are gone', () => {
  for (const f of ['.claude/agents/skill-guardian.md', 'PROJECT-SKILL-HEALTH.md', 'evals/agents/skill-guardian/evals.json']) {
    assert.ok(!files.includes(f), `${f} is still tracked`);
  }
});

test('no tracked file outside the exclusions names skill-guardian or PROJECT-SKILL-HEALTH', () => {
  const hits = [];
  let allowed = 0;
  for (const rel of files) {
    if (excluded(rel)) continue;
    const abs = path.join(REPO, rel);
    let st;
    try { st = fs.lstatSync(abs); } catch { continue; }   // tracked but deleted in the working tree
    if (!st.isFile()) continue;
    const lines = fs.readFileSync(abs, 'utf8').split('\n');
    lines.forEach((line, i) => {
      const c = classify(rel, line);
      if (c === 'allowed') allowed++;
      else if (c === 'hit') hits.push(`${rel}:${i + 1}`);
    });
  }
  assert.ok(hits.length === 0, `${hits.length} stale references:\n  ${hits.join('\n  ')}`);
  assert.strictEqual(allowed, 1, `the README cleanup line must appear exactly once (found ${allowed})`);
});

test('the exclusions are narrow: they do not cover live definitions, docs or install scripts', () => {
  for (const f of ['README.md', 'docs/USER-GUIDE.md', 'install.sh', 'CLAUDE.md', '.claude/agents/skill-scout-agent.md',
    'skills/project-audit/SKILL.md', 'evals/.gitignore',
    '.project-brain/decisions/active/2026-10-26-brain-guard-fails-closed-supersedes-the-p11-fail-open-policy.md',
    '.project-brain/decisions/candidates/x.md', '.project-brain/BRAIN.md']) {
    assert.ok(!excluded(f), `${f} must be checked`);
  }
  assert.ok(excluded('skills/agent-refine/SKILL-EVAL.md') && excluded('skills/skill-adapt/SKILL-REFINE-LOG.md'));
});

// PR4-R-1: the allowance covers that one README line exactly. Extra text on it that names the agent, or the same
// line in another file, is a stale reference.
test('the allowance is the exact README line: anything added to it, or the line elsewhere, is a hit', () => {
  const readme = fs.readFileSync(path.join(REPO, ALLOWED_LINE.file), 'utf8').split('\n');
  const line = readme.find(l => l === ALLOWED_LINE.line);
  assert.ok(line, 'the README cleanup line is missing');
  assert.strictEqual(classify(ALLOWED_LINE.file, line), 'allowed');
  assert.strictEqual(classify(ALLOWED_LINE.file, `${line} Or run skill-guardian.`), 'hit', 'a second reference appended');
  assert.strictEqual(classify(ALLOWED_LINE.file, `Run skill-guardian first. ${line}`), 'hit', 'a reference prepended');
  assert.strictEqual(classify('docs/USER-GUIDE.md', line), 'hit', 'the same line in another file');
});

if (!ok) process.exit(1);
