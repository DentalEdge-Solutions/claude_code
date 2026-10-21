#!/usr/bin/env node
// scripts/refine-snapshot.test.js — every refine flow can restore the prior content of whatever one file an
// iteration edited (E16, PR #4 triage). skill-refine-agent copied only SKILL.md, so a reverted Lever D or E edit
// (REFERENCE.md, scripts/) stayed; the two refine skills made no per-iteration copy at all, so after the first
// KEEP a revert had no source; skill-guardian had no copy step either.
//
// The skill flows copy the whole skill folder before each edit, into a fresh evals/<skill>/refine/pre-iter-N/
// (outside the folder the keep step syncs; fresh, because N repeats across sessions and a stale copy would turn
// "delete the file the edit created" into "restore old content"), and a revert restores only the edited file, so
// SKILL-EVAL.md and the append-only SKILL-REFINE-LOG.md keep what the iteration wrote. The agent flows copy their
// one file. Each check RUNS the commands written in the documents, placeholders filled, in a temp folder.
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const read = f => fs.readFileSync(path.join(REPO, f), 'utf8');
const spans = text => [...text.matchAll(/`([^`\n]+)`/g)].map(m => ({ cmd: m[1], at: m.index }));
const fill = (cmd, file) => cmd.replace(/<skill-name>|<agent-name>|<name>/g, 'demo')
  .replace(/pre-iter-N\b/g, 'pre-iter-3').replace(/<file>/g, file);
function sh(cwd, cmd) {
  const r = spawnSync('bash', ['-c', cmd], { cwd, encoding: 'utf8' });
  assert.strictEqual(r.status, 0, `command failed: ${cmd}\n${r.stderr}`);
}
function tree(dir, base = dir, out = {}) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) tree(p, base, out); else out[path.relative(base, p)] = fs.readFileSync(p, 'utf8');
  }
  return out;
}

const SKILL_FLOWS = ['skills/skill-refine/SKILL.md', '.claude/agents/skill-refine-agent.md', '.claude/agents/skill-guardian.md'];
const SNAPSHOT = 'rm -rf evals/<skill-name>/refine/pre-iter-N && mkdir -p evals/<skill-name>/refine/pre-iter-N && cp -R skills/<skill-name>/. evals/<skill-name>/refine/pre-iter-N/';
const RESTORE = 'if [ -e evals/<skill-name>/refine/pre-iter-N/<file> ]; then cp evals/<skill-name>/refine/pre-iter-N/<file> skills/<skill-name>/<file>; else rm skills/<skill-name>/<file>; fi';

for (const file of SKILL_FLOWS) {
  const text = read(file);
  const flat = text.replace(/\s+/g, ' ');
  const all = spans(text);
  const snap = all.filter(s => s.cmd === SNAPSHOT);
  const restore = all.filter(s => s.cmd === RESTORE);

  test(`${file}: one snapshot of the whole skill folder and one restore of the edited file`, () => {
    assert.strictEqual(snap.length, 1, `expected the snapshot command once, got ${snap.length}`);
    assert.ok(restore.length >= 1, 'no restore command');
    assert.ok(snap[0].at < restore[0].at, 'the restore comes before the snapshot');
    // no older, partial form is left
    assert.ok(!/SKILL\.md\.pre-iter-N/.test(text), 'still names SKILL.md.pre-iter-N');
    assert.ok(!/REVERT to prior content exactly\./.test(text), 'a revert with no stated source');
  });

  test(`${file}: the edited file is named per lever, and the copy is the size before the edit`, () => {
    assert.ok(flat.includes('`SKILL.md` for Levers A–C, `REFERENCE.md` for D, the script for E'), 'the lever → file mapping');
    assert.ok(flat.includes('`wc -c < evals/<skill-name>/refine/pre-iter-N/SKILL.md` is the size before the edit'), 'the size before the edit');
    assert.ok(flat.includes('`SKILL-EVAL.md` and `SKILL-REFINE-LOG.md` are not restored'), 'the logs are kept');
  });

  // Run the documented commands: an iteration edits one file, the loop rewrites SKILL-EVAL.md and appends to the
  // log, then the revert runs. The edited file returns exactly (or goes, if new); everything else keeps its state.
  for (const [edited, isNew] of [['SKILL.md', false], ['REFERENCE.md', false], ['scripts/fmt.js', false], ['REFERENCE.md', true], ['scripts/new.sh', true]]) {
    test(`${file}: revert of an edit to ${isNew ? 'a new ' : ''}${edited} restores it exactly`, () => {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'refine-snapshot-'));
      try {
        const skill = path.join(tmp, 'skills', 'demo');
        const files = { 'SKILL.md': 'skill v1\n', 'scripts/fmt.js': 'fmt v1\n', 'SKILL-EVAL.md': 'eval 0\n', 'SKILL-REFINE-LOG.md': 'log 0\n' };
        if (!isNew) files['REFERENCE.md'] = 'ref v1\n';
        for (const [rel, body] of Object.entries(files)) {
          fs.mkdirSync(path.dirname(path.join(skill, rel)), { recursive: true });
          fs.writeFileSync(path.join(skill, rel), body);
        }
        // a stale copy from an earlier session's iteration 3 holds the file this edit creates
        const stale = path.join(tmp, 'evals', 'demo', 'refine', 'pre-iter-3', edited);
        fs.mkdirSync(path.dirname(stale), { recursive: true });
        fs.writeFileSync(stale, 'stale\n');
        const before = tree(skill);

        sh(tmp, fill(snap[0].cmd, edited));
        assert.ok(!fs.existsSync(path.join(skill, 'pre-iter-3')), 'the copy is inside the skill folder');
        fs.mkdirSync(path.dirname(path.join(skill, edited)), { recursive: true });
        fs.writeFileSync(path.join(skill, edited), 'edited\n');                  // the one edit
        fs.writeFileSync(path.join(skill, 'SKILL-EVAL.md'), 'eval 1\n');          // the re-eval's report
        fs.appendFileSync(path.join(skill, 'SKILL-REFINE-LOG.md'), 'iter 3\n');   // the log entry
        sh(tmp, fill(restore[0].cmd, edited));

        assert.deepStrictEqual(tree(skill), { ...before, 'SKILL-EVAL.md': 'eval 1\n', 'SKILL-REFINE-LOG.md': 'log 0\niter 3\n' });
      } finally {
        fs.rmSync(tmp, { recursive: true, force: true });
      }
    });
  }
}

// agent-refine (the skill) copies its one file before each edit, as agent-refine-agent already did.
const AGENT_SNAPSHOT = 'cp .claude/agents/<name>.md evals/agents/<name>/refine/<name>.md.pre-iter-N';
const AGENT_RESTORE = 'cp evals/agents/<name>/refine/<name>.md.pre-iter-N .claude/agents/<name>.md';
test('skills/agent-refine/SKILL.md: a per-iteration copy before the edit, and the revert restores it', () => {
  const text = read('skills/agent-refine/SKILL.md');
  const all = spans(text);
  const snap = all.find(s => s.cmd === AGENT_SNAPSHOT);
  const restore = all.find(s => s.cmd === AGENT_RESTORE);
  assert.ok(snap, 'no per-iteration copy');
  assert.ok(restore, 'no restore from it');
  assert.ok(snap.at < restore.at, 'restore before copy');
  assert.ok(!/REVERT to prior content exactly\./.test(text), 'a revert with no stated source');
  assert.ok(text.replace(/\s+/g, ' ').includes('`wc -c < evals/agents/<name>/refine/<name>.md.pre-iter-N` is the size before the edit'), 'the size before the edit');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'refine-snapshot-'));
  try {
    fs.mkdirSync(path.join(tmp, '.claude', 'agents'), { recursive: true });
    fs.mkdirSync(path.join(tmp, 'evals', 'agents', 'demo', 'refine'), { recursive: true });
    const agent = path.join(tmp, '.claude', 'agents', 'demo.md');
    fs.writeFileSync(agent, 'agent v1\n');
    sh(tmp, fill(snap.cmd, ''));
    fs.writeFileSync(agent, 'edited\n');
    sh(tmp, fill(restore.cmd, ''));
    assert.strictEqual(fs.readFileSync(agent, 'utf8'), 'agent v1\n');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

// skill-guardian's edit step names every lever's file, Lever E included (it named SKILL.md or REFERENCE.md only).
test('.claude/agents/skill-guardian.md: the edit step covers Lever E', () => {
  const text = read('.claude/agents/skill-guardian.md');
  assert.ok(!/Make ONE surgical edit to `\.\/skills\/<skill-name>\/SKILL\.md` \(or REFERENCE\.md for Lever D\)/.test(text), 'the old edit step');
});

if (!ok) process.exit(1);
console.log('\nAll refine-snapshot tests passed.');
