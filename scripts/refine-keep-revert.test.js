#!/usr/bin/env node
// scripts/refine-keep-revert.test.js — the keep/revert rule of the refine loop (E14, E15; PR #4 triage).
//
// E14: the six documents that state the rule disagreed on a neutral result. The refine skills' step 8 reverted it,
// both refine agents' step 7d kept it, and each skill's REFERENCE.md table (which step 8 points to) kept it too.
// Owner decision 2026-10-20: a neutral result is reverted unless the edit made the edited file shorter. Every
// document now states the same three bands, one per line, and this test reads each line it states them on.
//
// E15: agent-refine's keep step copied the agent into the root of ~/.claude/ ("cp .claude/agents/<name>.md
// ~/.claude/"). Agents are project-scoped here, and Claude Code watches .claude/agents/ and uses an edited file on
// the next delegation (code.claude.com/docs/en/sub-agents, read 2026-10-20), so no copy is needed. No document may
// copy a project agent anywhere under the home folder.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const RULE_DOCS = [
  'skills/skill-refine/SKILL.md',
  'skills/skill-refine/REFERENCE.md',
  '.claude/agents/skill-refine-agent.md',
  'skills/agent-refine/SKILL.md',
  'skills/agent-refine/REFERENCE.md',
  '.claude/agents/agent-refine-agent.md',
];

const KEEP_BAND = 'score > baseline + 2%';
const REVERT_BAND = 'score < baseline − 5%';
const NEUTRAL_BAND = 'baseline − 5% ≤ score ≤ baseline + 2%';
const NEUTRAL_RULE = 'REVERT unless the edit made the edited file shorter';
const SHORTER_MEASURE = 'fewer bytes (`wc -c`) than before the edit';

const linesWith = (text, s) => text.split('\n').filter(l => l.includes(s));

for (const file of RULE_DOCS) {
  const text = fs.readFileSync(path.join(REPO, file), 'utf8');

  test(`${file}: the keep band keeps`, () => {
    const lines = linesWith(text, KEEP_BAND);
    assert.ok(lines.length >= 1, `no line states "${KEEP_BAND}"`);
    for (const l of lines) assert.ok(/KEEP/.test(l) && !/REVERT/.test(l), `not a keep line: ${l.trim()}`);
  });

  test(`${file}: the revert band reverts`, () => {
    const lines = linesWith(text, REVERT_BAND);
    assert.ok(lines.length >= 1, `no line states "${REVERT_BAND}"`);
    for (const l of lines) assert.ok(/REVERT/.test(l) && !/KEEP/.test(l), `not a revert line: ${l.trim()}`);
  });

  test(`${file}: the neutral band reverts unless the edited file got shorter, in bytes`, () => {
    const lines = linesWith(text, NEUTRAL_BAND);
    assert.ok(lines.length >= 1, `no line states "${NEUTRAL_BAND}"`);
    for (const l of lines) {
      assert.ok(l.includes(NEUTRAL_RULE), `neutral line lacks "${NEUTRAL_RULE}": ${l.trim()}`);
      assert.ok(l.includes(SHORTER_MEASURE), `neutral line lacks "${SHORTER_MEASURE}": ${l.trim()}`);
    }
  });

  test(`${file}: no older form of the neutral rule is left`, () => {
    const old = [/NEUTRAL\s*\**\s*→\s*\**\s*KEEP/i, /neutral\s*→\s*\**\s*REVERT/i, /±\s*2\s*[–-]\s*5\s*%/, /simpler is better/i,
      /simpler isn.t worse/i, /\bImproved\s*→/, /\bRegressed\b[^\n]*→/];
    for (const re of old) assert.ok(!re.test(text), `still matches ${re}`);
  });
}

// Every Markdown file under skills/ and .claude/agents/, found at run time.
function mdFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) mdFiles(p, out);
    else if (e.name.endsWith('.md')) out.push(p);
  }
  return out;
}

test('no document copies a project agent under the home folder (E15)', () => {
  const files = [...mdFiles(path.join(REPO, 'skills')), ...mdFiles(path.join(REPO, '.claude', 'agents'))];
  assert.ok(files.length > 0, 'no documents found');
  const bad = [];
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8');
    for (const m of text.matchAll(/\bcp(?:\s+-[A-Za-z]+)*\s+(\S*\.claude\/agents\/\S*)\s+(\S+)/g)) {
      if (/^["'`]?(~|\$HOME|\$\{HOME\}|\/Users\/|\/home\/)/.test(m[2])) bad.push(`${path.relative(REPO, f)}: ${m[0]}`);
    }
  }
  assert.deepStrictEqual(bad, []);
});

test('agent-refine: the keep step says the edited agent needs no copy', () => {
  const text = fs.readFileSync(path.join(REPO, 'skills/agent-refine/SKILL.md'), 'utf8');
  const keep = linesWith(text, KEEP_BAND);
  assert.ok(keep.some(l => /no copy/i.test(l)), 'the keep line does not say that no copy is needed');
});

if (!ok) process.exit(1);
console.log('\nAll refine-keep-revert tests passed.');
