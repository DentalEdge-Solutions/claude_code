#!/usr/bin/env node
// scripts/eval-snapshot-paths.test.js — where skill-eval and agent-eval keep the baseline snapshot (E8, PR #4
// triage). The snapshot used to live in the definition's own folder (`skills/<name>/SKILL.md.eval-snapshot`),
// next to it (`skills/<name>-eval-snapshot/`, which install.sh step 2 syncs into ~/.claude/skills as a second
// copy of the skill) or in `.claude/agents/`. None of those was gitignored in this repo. It now lives in the
// iteration folder, which is ignored here (evals/.gitignore) and in target projects (install.sh ignores evals/).
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const TRACKS = [
  { files: ['skills/skill-eval/SKILL.md', '.claude/agents/skill-eval-agent.md'],
    snapshot: 'evals/<skill-name>/iteration-<N>/eval-snapshot/SKILL.md',
    sample: 'evals/demo/iteration-1/eval-snapshot/SKILL.md' },
  { files: ['skills/agent-eval/SKILL.md', '.claude/agents/agent-eval-agent.md'],
    snapshot: 'evals/agents/<agent-name>/iteration-<N>/eval-snapshot/<agent-name>.md',
    sample: 'evals/agents/demo/iteration-1/eval-snapshot/demo.md' },
];

// Every path-like token that names an eval snapshot.
const snapshotTokens = text => text.match(/[^\s`'"()\[\]]*eval-snapshot[^\s`'"()\[\]]*/g) || [];

for (const { files, snapshot, sample } of TRACKS) {
  for (const file of files) {
    const text = fs.readFileSync(path.join(REPO, file), 'utf8').replace(/\\\n\s*/g, ' ');

    test(`${file}: every snapshot path is inside the iteration folder`, () => {
      const bad = snapshotTokens(text).filter(t => !t.startsWith(path.posix.dirname(path.posix.dirname(snapshot)) + '/')
        && !t.startsWith(path.posix.dirname(snapshot)));
      assert.deepStrictEqual(bad, []);
      assert.ok(snapshotTokens(text).length > 0, 'no snapshot path at all');
    });

    test(`${file}: init records --snapshot-path ${snapshot}`, () => {
      const inits = text.split('\n').filter(l => /run-manifest\.js init /.test(l));
      assert.ok(inits.length >= 1);
      for (const l of inits) assert.ok(l.includes(`--snapshot-path ${snapshot}]`), l.trim());
    });

    test(`${file}: the snapshot is copied into that folder after the iteration folder exists`, () => {
      const mk = text.indexOf('mkdir -p ' + path.posix.dirname(path.posix.dirname(snapshot)));
      const cp = text.search(/(^|`|\s)cp (-R )?\S+ evals\/\S*eval-snapshot/m);
      assert.ok(mk !== -1, 'no mkdir of the iteration folder');
      assert.ok(cp !== -1, 'no cp into the snapshot folder');
      assert.ok(mk < cp, 'the copy must come after the iteration folder is created (step 5), or N is miscounted');
    });
  }

  test(`${sample} is gitignored in this repo`, () => {
    const r = spawnSync('git', ['check-ignore', '-q', sample], { cwd: REPO });
    assert.strictEqual(r.status, 0, `${sample} is not ignored`);
  });
}

test('install.sh ignores evals/ in target projects', () => {
  assert.match(fs.readFileSync(path.join(REPO, 'install.sh'), 'utf8'), /^\s*"evals\/"\s*$/m);
});

if (!ok) process.exit(1);
console.log('\nAll eval-snapshot-paths tests passed.');
