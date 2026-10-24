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

function excluded(rel) {
  if (rel === SELF) return true;
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
  for (const rel of files) {
    if (excluded(rel)) continue;
    const abs = path.join(REPO, rel);
    let st;
    try { st = fs.lstatSync(abs); } catch { continue; }   // tracked but deleted in the working tree
    if (!st.isFile()) continue;
    const lines = fs.readFileSync(abs, 'utf8').split('\n');
    lines.forEach((line, i) => { if (RETIRED.test(line)) hits.push(`${rel}:${i + 1}`); });
  }
  assert.ok(hits.length === 0, `${hits.length} stale references:\n  ${hits.join('\n  ')}`);
});

test('the exclusions are narrow: they do not cover live definitions, docs or install scripts', () => {
  for (const f of ['README.md', 'docs/USER-GUIDE.md', 'install.sh', 'CLAUDE.md', '.claude/agents/skill-scout-agent.md',
    'skills/project-audit/SKILL.md', 'evals/.gitignore']) {
    assert.ok(!excluded(f), `${f} must be checked`);
  }
  assert.ok(excluded('skills/agent-refine/SKILL-EVAL.md') && excluded('skills/skill-adapt/SKILL-REFINE-LOG.md'));
});

if (!ok) process.exit(1);
