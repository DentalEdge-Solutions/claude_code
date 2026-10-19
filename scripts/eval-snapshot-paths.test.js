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
const crypto = require('crypto');
const os = require('os');
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

    // Run the doc's own step-5 snapshot commands in a temp repo (review M1): only `mkdir -p` and `cp`
    // are accepted, and they run without a shell. The recorded --snapshot-path must then exist and hold
    // exactly the --subject definition.
    test(`${file}: its step-5 commands create the recorded --snapshot-path, equal to the subject`, () => {
      const iterDir = path.posix.dirname(path.posix.dirname(snapshot));
      const start = text.indexOf('mkdir -p ' + iterDir);
      const end = text.indexOf('run-manifest.js init', start);
      assert.ok(start !== -1 && end > start, 'step 5 not found');
      const fill = t => t.replace(/<skill-name>|<agent-name>/g, 'demo').replace(/<N>/g, '1');
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'e8-snapshot-'));
      fs.mkdirSync(path.join(tmp, 'skills', 'demo', 'references'), { recursive: true });
      fs.writeFileSync(path.join(tmp, 'skills', 'demo', 'SKILL.md'), '---\nname: demo\n---\nbody\n');
      fs.writeFileSync(path.join(tmp, 'skills', 'demo', 'references', 'a.md'), 'ref\n');
      fs.mkdirSync(path.join(tmp, '.claude', 'agents'), { recursive: true });
      fs.writeFileSync(path.join(tmp, '.claude', 'agents', 'demo.md'), '---\nname: demo\n---\nagent\n');
      const cmds = [...text.slice(start, end).matchAll(/\b(mkdir -p|cp -R|cp) ([^\s`]+)(?: ([^\s`]+))?/g)];
      assert.ok(cmds.some(c => c[1].startsWith('cp')), 'no cp in step 5');
      for (const [, op, a1, a2] of cmds) {
        const args = op === 'mkdir -p' ? ['-p', fill(a1)] : [...(op === 'cp -R' ? ['-R'] : []), fill(a1), fill(a2 || '')];
        const r = spawnSync(op.split(' ')[0], args, { cwd: tmp, encoding: 'utf8' });
        assert.strictEqual(r.status, 0, `${op} ${args.join(' ')}: ${r.stderr}`);
      }
      const init = text.slice(end).split('\n')[0];
      const snap = fill(init.match(/--snapshot-path (\S+?)\]/)[1]);
      const subj = fill(init.match(/--subject (\S+)/)[1]);
      const sha = f => crypto.createHash('sha256').update(fs.readFileSync(path.join(tmp, f))).digest('hex');
      assert.ok(fs.existsSync(path.join(tmp, snap)) && fs.statSync(path.join(tmp, snap)).isFile(), `${snap} was not created`);
      assert.strictEqual(sha(snap), sha(subj), 'the snapshot differs from the subject');
    });

    // The copy runs once per iteration, like init: re-running `cp -R` nests a second copy (review M2).
    test(`${file}: on resume the snapshot copy is skipped together with init`, () => {
      assert.ok(/skip the snapshot copy and this call|\(once per iteration — skip on resume\)/.test(text), 'resume wording');
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
