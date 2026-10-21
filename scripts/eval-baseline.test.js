#!/usr/bin/env node
// scripts/eval-baseline.test.js — what skill-eval and agent-eval compare against (E12, PR #4 triage).
//
// The flows recorded `baseline_method = snapshot` for an existing definition, but the snapshot was copied at
// eval time, so it was byte-identical to the definition measured (review M3), and both eval agents' baseline
// prompt said "Do NOT load any skill" / "Do NOT dispatch the agent" anyway. Owner decision 2026-10-20: the
// report names the baseline that actually runs, no skill (no agent); a previous-version baseline is a separate
// feature for later. So every flow records `--baseline-method none`, takes no snapshot (this replaces E8's
// eval-snapshot-paths.test.js), and a resume starts a new iteration when the subject changed since init (E10)
// or the manifest predates this change.
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

const read = f => fs.readFileSync(path.join(REPO, f), 'utf8');

const FLOWS = [
  { file: 'skills/skill-eval/SKILL.md', none: 'no skill loaded' },
  { file: '.claude/agents/skill-eval-agent.md', none: 'no skill loaded' },
  { file: 'skills/agent-eval/SKILL.md', none: 'no agent dispatched' },
  { file: '.claude/agents/agent-eval-agent.md', none: 'no agent dispatched' },
];

// Forms that offer, take or dispatch a snapshot baseline.
const SNAPSHOT_FORMS = [/eval-snapshot/, /--snapshot-path/, /none\|snapshot/, /baseline_method\s*=\s*`snapshot`/,
  /dispatch the snapshot/i, /\(or snapshot\)/i, /baseline snapshot/i, /snapshot of (?:the )?previous version/i,
  /Existing (?:skill|agent) being improved/i];

for (const { file, none } of FLOWS) {
  const text = read(file);
  const joined = text.replace(/\\\r?\n\s*/g, ' ');   // fenced commands continue over backslash-newlines
  const flat = text.replace(/\s+/g, ' ');   // prose wrapped over lines reads as one sentence

  test(`${file}: no snapshot baseline is offered, taken or dispatched`, () => {
    for (const re of SNAPSHOT_FORMS) assert.ok(!re.test(text), `still matches ${re}`);
  });

  test(`${file}: every run-manifest init records --baseline-method none`, () => {
    const inits = joined.split('\n').filter(l => /run-manifest\.js init /.test(l));
    assert.ok(inits.length >= 1, 'no init line');
    for (const l of inits) assert.match(l, /--baseline-method none(?:\s|`|$)/, l.trim());
  });

  test(`${file}: the baseline step says "${none}" and that a previous-version baseline is not run`, () => {
    assert.ok(flat.includes(`baseline is the same prompt with ${none}`), `no "baseline is the same prompt with ${none}"`);
    assert.ok(flat.includes('a baseline of an earlier version is not run'), 'the missing previous-version baseline is not stated');
  });

  test(`${file}: the resume check starts a new iteration after a subject change or an old snapshot manifest`, () => {
    assert.ok(flat.includes('If `status` prints a WARNING that the subject changed or is not found'), 'no E10 warning rule');
    assert.ok(flat.includes('or the manifest records `baseline_method=snapshot`'), 'no rule for manifests made before E12');
    assert.ok(flat.includes('start a new iteration instead of resuming'), 'no "start a new iteration instead of resuming"');
  });
}

// The two refine skills re-run scenarios with the eval's method; they named a "baseline snapshot" too.
for (const [file, side] of [['skills/skill-refine/SKILL.md', 'with-skill vs no-skill baseline'],
  ['skills/agent-refine/SKILL.md', 'with-agent vs no-agent baseline']]) {
  test(`${file}: the re-eval compares ${side}`, () => {
    const text = read(file);
    assert.ok(text.includes(`(${side})`), `no "(${side})"`);
    for (const re of SNAPSHOT_FORMS) assert.ok(!re.test(text), `still matches ${re}`);
  });
}

// The report header names the baseline that ran, in the template and its REFERENCE.md copy alike.
for (const [track, none] of [['skill', 'no skill loaded'], ['agent', 'no agent dispatched']]) {
  const header = `**Baseline:** ${none} (\`baseline_method: none\`)`;
  for (const file of [`skills/${track}-eval/assets/${track.toUpperCase()}-EVAL.template.md`, `skills/${track}-eval/REFERENCE.md`]) {
    test(`${file}: the header says ${header}`, () => {
      const lines = read(file).split('\n').filter(l => l.startsWith('**Baseline:**'));
      assert.deepStrictEqual(lines, [header]);
    });
  }
}

if (!ok) process.exit(1);
console.log('\nAll eval-baseline tests passed.');
