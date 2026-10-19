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
    // E9: the commit is HEAD when the run started, so a refine loop's uncommitted definition is not
    // in it; the sha256 is what identifies the measured text, and a manifest without one says so.
    // Whole clauses, so a reworded line that reverses the meaning fails (E9 review L2).
    for (const clause of ['The sha256 identifies the measured text', 'so it does not contain an uncommitted definition',
      'Write "not recorded" when `subject` or its `commit` is null']) {
      assert.ok(expected[0].includes(clause), `Subject revision must say: ${clause}\n  got: ${expected[0]}`);
    }
  });

  // The report header repeats the subject revision; it must agree with the bullet (E9 review L1).
  test(`${track}: the template and REFERENCE.md headers give the sha256 first and the "not recorded" case`, () => {
    const headers = [template, `skills/${track}-eval/REFERENCE.md`].map(f =>
      fs.readFileSync(path.join(REPO, f), 'utf8').split('\n').filter(l => l.startsWith('**Subject revision:**')));
    for (const h of headers) assert.strictEqual(h.length, 1, `expected one header line, got ${h.length}`);
    assert.strictEqual(headers[0][0], headers[1][0]);
    const h = headers[0][0];
    assert.ok(h.indexOf('sha256') !== -1 && h.indexOf('sha256') < h.indexOf('commit'), `sha256 must come before the commit: ${h}`);
    assert.ok(h.includes('"not recorded"'), h);
  });

  for (const copy of copies) {
    test(`${track}: ${copy} has the same Evidence and Limits bullets as the template`, () => {
      assert.deepStrictEqual(evidenceBullets(copy), expected);
    });
  }
}

// The section's "Subject revision" is copied from run-manifest.json `subject`, which exists only when
// `run-manifest.js init` gets `--subject` (E7 review K5). Every init line in the skill and the agent must
// pass it, with the definition the track measures.
const INIT_SUBJECT = [
  { file: 'skills/skill-eval/SKILL.md', subject: 'skills/<skill-name>/SKILL.md' },
  { file: '.claude/agents/skill-eval-agent.md', subject: 'skills/<skill-name>/SKILL.md' },
  { file: 'skills/agent-eval/SKILL.md', subject: '.claude/agents/<agent-name>.md' },
  { file: '.claude/agents/agent-eval-agent.md', subject: '.claude/agents/<agent-name>.md' },
];
for (const { file, subject } of INIT_SUBJECT) {
  test(`${file}: run-manifest.js init passes --subject ${subject} and --commit`, () => {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8');
    // An init command may continue over backslash-newline lines (the skills' fenced bash form).
    const inits = text.replace(/\\\n\s*/g, ' ').split('\n').filter(l => /run-manifest\.js init /.test(l));
    assert.ok(inits.length >= 1, 'no run-manifest.js init line');
    for (const l of inits) {
      // Anchored at the path's end: `--subject …/SKILL.md.eval-snapshot` would pin the baseline, not the subject (K7).
      const exact = new RegExp(`--subject ${subject.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:\\s|$)`);
      assert.ok(exact.test(l), `missing --subject ${subject}: ${l.trim()}`);
      assert.ok(/--commit \S/.test(l), `missing --commit: ${l.trim()}`);
    }
  });
}

if (!ok) process.exit(1);
console.log('\nAll eval-report-sections tests passed.');
