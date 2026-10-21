#!/usr/bin/env node
// scripts/refine-keep-revert.test.js — the keep/revert rule of the refine loop (E14, E15; PR #4 triage).
//
// E14: the six documents that state the rule disagreed on a neutral result. The refine skills' step 8 reverted it,
// both refine agents' step 7d kept it, and each skill's REFERENCE.md table (which step 8 points to) kept it too.
// Owner decision 2026-10-20: a neutral result is reverted unless the edit made the definition shorter. Every
// document now states the same three bands, one per line, and this test reads each line it states them on.
// The definition is SKILL.md for a skill (a neutral Lever D or E edit, to REFERENCE.md or scripts/, is always
// reverted) and the agent file for an agent; size is bytes; a neutral KEEP leaves the baseline where it was
// (review R2, R5). skill-guardian's own refine loop states the same rule (review R4).
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

// track: which definition's size decides a neutral result. sync: the keep step copies the skill to ~/.claude/skills.
const RULE_DOCS = [
  { file: 'skills/skill-refine/SKILL.md', track: 'skill', sync: true },
  { file: 'skills/skill-refine/REFERENCE.md', track: 'skill' },
  { file: '.claude/agents/skill-refine-agent.md', track: 'skill', sync: true },
  { file: '.claude/agents/skill-guardian.md', track: 'skill' },
  { file: 'skills/agent-refine/SKILL.md', track: 'agent' },
  { file: 'skills/agent-refine/REFERENCE.md', track: 'agent' },
  { file: '.claude/agents/agent-refine-agent.md', track: 'agent' },
];

const KEEP_BAND = 'score > baseline + 2%';
const REVERT_BAND = 'score < baseline − 5%';
const NEUTRAL_BAND = 'baseline − 5% ≤ score ≤ baseline + 2%';
const NEUTRAL_RULE = { skill: 'REVERT unless the edit made `SKILL.md` shorter', agent: 'REVERT unless the edit made the agent file shorter' };
// The measure ends the condition: nothing such as ", or the same size" may widen it.
const SHORTER_MEASURE = /fewer bytes \(`wc -c`\) than before the edit[;.]/;
const NEUTRAL_KEEP = /if it did, KEEP/i;
const BASELINE_KEPT = 'the baseline stays as it was';
const LEVER_DE = 'a neutral lever d or e edit is always reverted';
const LOOP_LINE = 'Between → revert unless the definition got shorter.';
const LOG_DECISIONS = 'KEPT/REVERTED/NEUTRAL-KEPT/NEUTRAL-REVERTED';

// Bold markers dropped, so "**REVERT unless …**" and "REVERT unless …" read the same.
const linesWith = (text, s) => text.split('\n').map(l => l.replace(/\*\*/g, '')).filter(l => l.includes(s));

for (const { file, track, sync } of RULE_DOCS) {
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

  test(`${file}: the neutral band reverts unless the ${track} definition got shorter, in bytes`, () => {
    const lines = linesWith(text, NEUTRAL_BAND);
    assert.ok(lines.length >= 1, `no line states "${NEUTRAL_BAND}"`);
    for (const l of lines) {
      assert.ok(l.includes(NEUTRAL_RULE[track]), `neutral line lacks "${NEUTRAL_RULE[track]}": ${l.trim()}`);
      assert.match(l, SHORTER_MEASURE, `neutral line lacks the byte measure, or widens it: ${l.trim()}`);
      assert.match(l, NEUTRAL_KEEP, `neutral line lacks "if it did, KEEP": ${l.trim()}`);
      assert.ok(!/if it did(?:n.t| not)/i.test(l), `neutral line keeps when the file did not get shorter: ${l.trim()}`);
      assert.ok(l.includes(BASELINE_KEPT), `neutral line lacks "${BASELINE_KEPT}": ${l.trim()}`);
      if (track === 'skill') assert.ok(l.toLowerCase().includes(LEVER_DE), `neutral line lacks "${LEVER_DE}": ${l.trim()}`);
      if (sync) assert.match(l, /if it did, KEEP and sync as above/i, `neutral KEEP does not sync: ${l.trim()}`);
    }
  });

  test(`${file}: no older form of the neutral rule is left`, () => {
    const old = [/NEUTRAL\s*\**\s*→\s*\**\s*KEEP/i, /neutral\s*→\s*\**\s*REVERT/i, /±\s*2\s*[–-]\s*5\s*%/, /simpler/i,
      /\bimproved\s*→/i, /\bRegressed\b[^\n]*→/, /same or dropped/i, /kept unless/i, /\bthe edited file shorter/i,
      /between\s*→\s*keep/i, /inside the band[^\n]*\bkept\b/i];
    for (const re of old) assert.ok(!re.test(text), `still matches ${re}`);
  });
}

for (const file of ['skills/skill-refine/SKILL.md', 'skills/agent-refine/SKILL.md']) {
  test(`${file}: the loop summary states the neutral band (review R7)`, () => {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8');
    assert.ok(text.includes(LOOP_LINE), `the RULE block lacks "${LOOP_LINE}"`);
  });
}

for (const file of ['skills/skill-refine/REFERENCE.md', 'skills/agent-refine/REFERENCE.md']) {
  test(`${file}: the neutral KEEP leaves the baseline, and the bands are percentage points (review R5, R6)`, () => {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8');
    assert.ok(text.includes('A neutral KEEP leaves the baseline where it was'), 'baseline after a neutral KEEP not stated');
    assert.ok(text.includes('a neutral KEEP is not an improvement and a neutral revert counts as a revert'), 'exhaustion/convergence counting not stated');
    assert.ok(text.includes('the bands are in percentage points'), 'unit of the bands not stated');
  });
}

// Every log format records the size and can show either neutral outcome (review R7).
for (const file of ['skills/skill-refine/assets/SKILL-REFINE-LOG.template.md', 'skills/skill-refine/REFERENCE.md',
  'skills/agent-refine/assets/AGENT-REFINE-LOG.template.md', 'skills/agent-refine/REFERENCE.md',
  '.claude/agents/skill-refine-agent.md', '.claude/agents/agent-refine-agent.md']) {
  test(`${file}: the log records the size and both neutral outcomes`, () => {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8').replace(/ \/ /g, '/');
    assert.ok(text.includes(LOG_DECISIONS), `no "${LOG_DECISIONS}"`);
    assert.match(text, /Size:\**\s*X+\s*→\s*X+ bytes|Size: X→Y bytes/, 'no size field');
  });
}

for (const file of ['.claude/agents/skill-refine-agent.md', '.claude/agents/agent-refine-agent.md']) {
  test(`${file}: a neutral revert counts toward lever exhaustion (review R5)`, () => {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8');
    assert.ok(text.includes('(a neutral revert counts as a revert; a neutral KEEP is not an improvement)'));
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

// A copy command's operands, flags dropped; the last one is the destination.
const COPY = /\b(?:cp|rsync|install|ln)\b((?:[ \t]+[^\s`;|&]+)+)/g;
const HOME = /^["']?(?:~|\$HOME|\$\{HOME\}|\/Users\/[^/]+|\/home\/[^/]+)(?:\/|["']?$)/;

test('no document copies a project agent under the home folder (E15, review R1)', () => {
  const files = [...mdFiles(path.join(REPO, 'skills')), ...mdFiles(path.join(REPO, '.claude', 'agents'))];
  assert.ok(files.length > 0, 'no documents found');
  const bad = [];
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8');
    for (const m of text.matchAll(COPY)) {
      const ops = m[1].trim().split(/[ \t]+/).filter(o => !o.startsWith('-'));
      if (ops.length < 2) continue;
      const dst = ops[ops.length - 1];
      if (!HOME.test(dst)) continue;
      const agentDst = /\.claude\/agents\b/.test(dst);
      const agentSrc = ops.slice(0, -1).some(o => /\.claude\/agents\b/.test(o) || /^["']?\$\{?[A-Z_]*AGENT/.test(o));
      if (agentDst || agentSrc) bad.push(`${path.relative(REPO, f)}: ${m[0].trim()}`);
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
