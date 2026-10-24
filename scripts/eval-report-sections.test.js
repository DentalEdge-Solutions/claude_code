#!/usr/bin/env node
// scripts/eval-report-sections.test.js — the "Evidence and Limits" section of an eval report is written
// in three places per track, and they must not drift (E7, PR #4 triage: the agents' inline templates
// lacked it entirely, so agent-written reports carried no subject revision or E6 disclosure).
//
//   skills/<track>-eval/assets/<TRACK>-EVAL.template.md   the skill's report template
//   skills/<track>-eval/REFERENCE.md                      the copy <track>-eval SKILL.md step 12 builds reports from
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
  { track: 'skill', marker: '`Skill(<skill-name>)`', none: 'no skill loaded', what: 'the skill against no skill' },
  { track: 'agent', marker: '`Agent(<agent-name>)`', none: 'no agent dispatched', what: 'the agent against no agent' },
];

for (const { track, marker, none, what } of TRACKS) {
  const template = `skills/${track}-eval/assets/${track.toUpperCase()}-EVAL.template.md`;
  const copies = [`skills/${track}-eval/REFERENCE.md`, `.claude/agents/${track}-eval-agent.md`];
  const expected = evidenceBullets(template);

  test(`${track}: the template's section has the five bullets, and names the ${marker} marker`, () => {
    assert.deepStrictEqual(expected.map(b => b.match(/^- \*\*([^:*]+):\*\*/)?.[1]),
      ['Subject revision', 'Baseline', 'Evidence source', 'Untested', 'Limitations']);
    assert.ok(expected[2].includes(marker), expected[2]);
    // E12: the baseline that ran is no skill (no agent), so the delta is not a change from an earlier version.
    for (const clause of [`the same prompt with ${none} (\`baseline_method: none\`)`,
      `The delta measures ${what}, not against an earlier version of it`]) {
      assert.ok(expected[1].includes(clause), `Baseline must say: ${clause}\n  got: ${expected[1]}`);
    }
    // E9: the commit is HEAD when the run started, so a refine loop's uncommitted definition is not
    // in it; the sha256 is what identifies the measured text, and a manifest without one says so.
    // Whole clauses, so a reworded line that reverses the meaning fails (E9 review L2).
    for (const clause of ['The sha256 identifies the measured text', 'so it does not contain an uncommitted definition',
      'Write "not recorded" for whichever of `subject` and its `commit` is null, keeping the other']) {
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
    assert.ok(h.includes('"not recorded" when missing'), h);   // the phrase alone passed `never "not recorded"` (L6)
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

// E11: team-eval writes no run manifest, so its report pins every definition by sha256 itself, and the review
// protocol says which report pins its revision how.
// Hashed before any run, like run-manifest.js init, and re-checked when the report is written (review R5).
test('team-eval pins the orchestrator and every member by sha256 before the runs, and re-checks them (E11)', () => {
  const text = fs.readFileSync(path.join(REPO, 'skills/team-eval/SKILL.md'), 'utf8').replace(/\s+/g, ' ');
  const pin = text.indexOf('record the sha256 of the orchestrator and of every member definition');
  const step3 = text.indexOf('3. **Execute scenarios**');
  const step7 = text.indexOf('7. **Write the report**');
  assert.ok(pin !== -1, 'no per-definition sha256');
  assert.ok(step3 !== -1 && pin < step3, 'the sha256 must be recorded before step 3 runs the scenarios');
  assert.ok(text.includes('`shasum -a 256 <file>`') && text.includes('`git rev-parse --short HEAD`'), 'no commands');
  const report = text.slice(step7);
  assert.ok(report.includes('re-hash every definition; if any differs from step 1, the report says which'), 'no re-check at step 7');
  assert.ok(report.includes('the commit is HEAD when the run started, so it does not contain uncommitted edits'), 'no commit caveat');
});

test('REVIEW_PROTOCOL.md says how each eval report pins its revision (E11)', () => {
  const text = fs.readFileSync(path.join(REPO, 'docs/REVIEW_PROTOCOL.md'), 'utf8');
  assert.ok(!/TEAM-EVAL, with the revision pinned by `run-manifest\.js init --subject`/.test(text), 'still says team-eval uses run-manifest');
  assert.ok(text.includes('SKILL-EVAL and AGENT-EVAL pin the measured definition with `run-manifest.js init --subject`'), 'skill/agent rule');
  assert.ok(text.includes('TEAM-EVAL lists the sha256 of the orchestrator and of every member, taken before the runs (team-eval steps 1 and 7)'), 'team rule');
});

if (!ok) process.exit(1);
console.log('\nAll eval-report-sections tests passed.');
