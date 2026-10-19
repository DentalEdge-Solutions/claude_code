#!/usr/bin/env node
// scripts/eval-report-sections.test.js — the "Evidence and Limits" section of an eval report is written
// in three places per track, and they must not drift (E7, PR #4 triage: the agents' inline templates
// lacked it entirely, so agent-written reports carried no subject revision or E6 disclosure).
//
//   skills/<track>-eval/assets/<TRACK>-EVAL.template.md   the skill's report template
//   skills/<track>-eval/REFERENCE.md                      the copy skill-guardian builds reports from
//   .claude/agents/<track>-eval-agent.md                  the agent's inline step-12 template (indented)
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

// The bullet lines of the "## Evidence and Limits" section, indentation removed; [] when absent.
function evidenceBullets(file) {
  const lines = fs.readFileSync(path.join(REPO, file), 'utf8').split('\n');
  const start = lines.findIndex(l => l.trim() === '## Evidence and Limits');
  if (start === -1) return [];
  const out = [];
  for (const l of lines.slice(start + 1)) {
    const t = l.trim();
    if (t.startsWith('#') || t.startsWith('```')) break;
    if (t.startsWith('- ')) out.push(t);
  }
  return out;
}

const TRACKS = [
  { track: 'skill', marker: '`Skill(<skill-name>)`' },
  { track: 'agent', marker: '`Agent(<agent-name>)`' },
];

for (const { track, marker } of TRACKS) {
  const template = `skills/${track}-eval/assets/${track.toUpperCase()}-EVAL.template.md`;
  const copies = [`skills/${track}-eval/REFERENCE.md`, `.claude/agents/${track}-eval-agent.md`];
  const expected = evidenceBullets(template);

  test(`${track}: the template's section has the four bullets, and names the ${marker} marker`, () => {
    assert.deepStrictEqual(expected.map(b => b.match(/^- \*\*([^:*]+):\*\*/)?.[1]),
      ['Subject revision', 'Evidence source', 'Untested', 'Limitations']);
    assert.ok(expected[1].includes(marker), expected[1]);
  });

  for (const copy of copies) {
    test(`${track}: ${copy} has the same Evidence and Limits bullets as the template`, () => {
      assert.deepStrictEqual(evidenceBullets(copy), expected);
    });
  }
}

if (!ok) process.exit(1);
console.log('\nAll eval-report-sections tests passed.');
