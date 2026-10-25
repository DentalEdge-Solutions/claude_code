#!/usr/bin/env node
// scripts/refine-snapshot.test.js — every refine flow can restore the prior content of whatever one file an
// iteration edited (E16, PR #4 triage). skill-refine-agent copied only SKILL.md, so a reverted Lever D or E edit
// (REFERENCE.md, scripts/) stayed; the two refine skills made no per-iteration copy at all, so after the first
// KEEP a revert had no source.
//
// The skill flows copy the whole skill folder before each edit, into a fresh evals/<skill>/refine/pre-iter-N/
// (outside the folder the keep step syncs; fresh, because N repeats across sessions and a stale copy would turn
// "delete the file the edit created" into "restore old content"), and a revert restores only the edited file, so
// SKILL-EVAL.md and the append-only SKILL-REFINE-LOG.md keep what the iteration wrote. The agent flows copy their
// one file. Each check RUNS the commands written in the documents, placeholders filled, in a temp folder.
// Paths are quoted (review Q3: a <file> with a space made `[` fail and the else branch delete another file), and
// after a revert a diff against the copy must print nothing: it catches a wrongly named <file>, a second stray
// edit, and an empty folder a reverted new file leaves (review Q6).
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
const shOut = (cwd, cmd) => spawnSync('bash', ['-c', cmd], { cwd, encoding: 'utf8' });
function tree(dir, base = dir, out = {}) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) tree(p, base, out); else out[path.relative(base, p)] = fs.readFileSync(p, 'utf8');
  }
  return out;
}

const SKILL_FLOWS = ['skills/skill-refine/SKILL.md', '.claude/agents/skill-refine-agent.md'];
const SNAPSHOT = 'rm -rf "evals/<skill-name>/refine/pre-iter-N" && mkdir -p "evals/<skill-name>/refine/pre-iter-N" && cp -R "skills/<skill-name>/." "evals/<skill-name>/refine/pre-iter-N/"';
const RESTORE = 'if [ -e "evals/<skill-name>/refine/pre-iter-N/<file>" ]; then cp "evals/<skill-name>/refine/pre-iter-N/<file>" "skills/<skill-name>/<file>"; else rm "skills/<skill-name>/<file>"; fi';
const CHECK = 'diff -rq -x SKILL-EVAL.md -x SKILL-REFINE-LOG.md "evals/<skill-name>/refine/pre-iter-N" "skills/<skill-name>"';
// The instructions that start an iteration's edit; the copy must come before every one (review Q1). A summary
// such as skill-refine-agent's "Make exactly one surgical edit per iteration" is not one.
const EDIT_STEP = /Then make exactly\b[^\n]*edit|Make ONE surgical edit/g;

for (const file of SKILL_FLOWS) {
  const text = read(file);
  const flat = text.replace(/\s+/g, ' ');
  const all = spans(text);
  const snap = all.filter(s => s.cmd === SNAPSHOT);
  const restore = all.filter(s => s.cmd === RESTORE);
  const check = all.filter(s => s.cmd === CHECK);

  test(`${file}: one snapshot of the whole skill folder and one restore of the edited file`, () => {
    assert.strictEqual(snap.length, 1, `expected the snapshot command once, got ${snap.length}`);
    assert.ok(restore.length >= 1, 'no restore command');
    assert.ok(snap[0].at < restore[0].at, 'the restore comes before the snapshot');
    assert.ok(check.length >= 1 && check[0].at > restore[0].at, 'no check after the restore');
    const edits = [...text.matchAll(EDIT_STEP)];
    assert.ok(edits.length >= 1, 'no edit step found');
    for (const e of edits) assert.ok(snap[0].at < e.index, `the copy comes after the edit step: ${e[0]}`);
    // no other copy back from the snapshot, such as a whole-folder restore that rolls back the logs (review Q2)
    const rest = [SNAPSHOT, RESTORE].reduce((t, c) => t.split(c).join(''), text);
    assert.ok(!/\b(?:cp|rsync|ditto)\b[^\n]*pre-iter-N/.test(rest), 'another copy from or to the snapshot');
    // no older, partial form is left
    assert.ok(!/SKILL\.md\.pre-iter-N/.test(text), 'still names SKILL.md.pre-iter-N');
    assert.ok(!/REVERT to prior content exactly\./.test(text), 'a revert with no stated source');
  });

  test(`${file}: the edited file is named per lever, and the copy is the size before the edit`, () => {
    assert.ok(flat.includes('`SKILL.md` for Levers A–C, `REFERENCE.md` for D, the script for E'), 'the lever → file mapping');
    assert.ok(flat.includes('`wc -c < evals/<skill-name>/refine/pre-iter-N/SKILL.md` is the size before the edit'), 'the size before the edit');
    assert.ok(flat.includes('`SKILL-EVAL.md` and `SKILL-REFINE-LOG.md` are not restored'), 'the logs are kept');
    assert.ok(flat.includes('Then check that nothing else differs from the copy; this must print nothing:'), 'the check must print nothing (review Q11)');
    assert.ok(flat.includes('If it lists a file, restore it the same way; if it lists a folder the edit created, remove it.'), 'what to do when the check prints');
    assert.ok(flat.includes('A symlinked `<file>` is out of scope: a revert can\'t restore it, so pick another file.'), 'symlinks (review Q4)');
  });

  // Run the documented commands: an iteration edits one file, the loop rewrites SKILL-EVAL.md and appends to the
  // log, then the revert runs. The edited file returns exactly (or goes, if new); everything else keeps its state.
  for (const [edited, isNew] of [['SKILL.md', false], ['REFERENCE.md', false], ['scripts/fmt.js', false], ['REFERENCE.md', true],
    ['scripts/new.sh', true], ['scripts/my tool.sh', false], ['scripts/my tool.sh', true]]) {
    test(`${file}: revert of an edit to ${isNew ? 'a new ' : ''}${edited} restores it exactly`, () => {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'refine-snapshot-'));
      try {
        const skill = path.join(tmp, 'skills', 'demo');
        // `scripts/my` is the file an unquoted `[ -e …/scripts/my tool.sh ]` reached for (review Q3)
        const files = { 'SKILL.md': 'skill v1\n', 'scripts/fmt.js': 'fmt v1\n', 'scripts/my': 'other\n', 'SKILL-EVAL.md': 'eval 0\n', 'SKILL-REFINE-LOG.md': 'log 0\n' };
        if (!isNew) { files['REFERENCE.md'] = 'ref v1\n'; files['scripts/my tool.sh'] = 'tool v1\n'; }
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
        const c = shOut(tmp, fill(check[0].cmd, edited));
        assert.ok(c.status === 0 && c.stdout === '', `the check after the revert printed: ${c.stdout}${c.stderr}`);
      } finally {
        fs.rmSync(tmp, { recursive: true, force: true });
      }
    });
  }

  // The check catches what the restore of one file cannot: a second stray edit, and the folder a new file needed.
  test(`${file}: the check after the revert lists a stray edit and a folder the edit created`, () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'refine-snapshot-'));
    try {
      const skill = path.join(tmp, 'skills', 'demo');
      fs.mkdirSync(skill, { recursive: true });
      fs.mkdirSync(path.join(skill, 'scripts'));
      for (const [rel, body] of [['SKILL.md', 'skill v1\n'], ['REFERENCE.md', 'ref v1\n'], ['scripts/fmt.js', 'fmt v1\n']]) fs.writeFileSync(path.join(skill, rel), body);
      sh(tmp, fill(snap[0].cmd, ''));
      fs.mkdirSync(path.join(skill, 'scripts', 'new'), { recursive: true });
      fs.writeFileSync(path.join(skill, 'scripts', 'new', 'x.sh'), 'new\n');   // the edit, in a new folder
      fs.writeFileSync(path.join(skill, 'REFERENCE.md'), 'stray\n');            // a second, stray edit
      sh(tmp, fill(restore[0].cmd, 'scripts/new/x.sh'));
      const c = shOut(tmp, fill(check[0].cmd, ''));
      assert.notStrictEqual(c.status, 0, 'the check found nothing');
      assert.match(c.stdout, /REFERENCE\.md/, 'the stray edit is not listed');
      assert.match(c.stdout, /Only in skills\/demo\/scripts: new/, 'the empty new folder is not listed');
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });
}

// The refine skills' REFERENCE.md tables and rules name the copy (review Q5).
for (const [file, row] of [
  ['skills/skill-refine/REFERENCE.md', "| **REVERT** | score < baseline − 5% | Restore the edited file's exact prior content from the iteration's copy (`evals/<skill-name>/refine/pre-iter-N/`); delete a file the edit created |"],
  ['skills/agent-refine/REFERENCE.md', "| **REVERT** | score < baseline − 5% | Restore the exact prior content from the iteration's copy (`evals/agents/<name>/refine/<name>.md.pre-iter-N`) |"],
]) test(`${file}: the REVERT row names the copy`, () => assert.ok(read(file).split('\n').includes(row)));
for (const [file, what] of [['skills/skill-refine/SKILL.md', 'the skill folder'], ['skills/agent-refine/SKILL.md', 'the agent file']]) {
  test(`${file}: the rules keep the per-iteration copy`, () => {
    const text = read(file);
    assert.ok(text.includes(`- **Never skip the per-iteration copy** — step 6 copies ${what} before every edit.`));
    assert.ok(text.includes("- **Revert faithfully** — restore the exact prior content from the iteration's copy, not a rewrite of it."));
  });
}
test('.claude/agents/skill-refine-agent.md: a neutral revert restores as the REVERT bullet does, check included (review Q11)', () => {
  assert.ok(/^ {3}- baseline − 5% ≤ score ≤ baseline \+ 2% \(neutral\) → .*; if not, restore as above\. A neutral Lever D or E edit is always reverted\.$/m
    .test(read('.claude/agents/skill-refine-agent.md')), 'the neutral line no longer restores "as above"');
});
test('.claude/agents/skill-refine-agent.md: the edit may create a file (review Q7)', () => {
  assert.ok(read('.claude/agents/skill-refine-agent.md').includes('(use Edit, or Write for a new file)'));
});
{
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
  const edits = [...text.matchAll(EDIT_STEP)];
  assert.ok(edits.length >= 1, 'no edit step found (review Q10)');
  for (const e of edits) assert.ok(snap.at < e.index, `the copy comes after the edit step: ${e[0]}`);
  const rest = [AGENT_SNAPSHOT, AGENT_RESTORE].reduce((t, c) => t.split(c).join(''), text);
  assert.ok(!/\b(?:cp|rsync|ditto)\b[^\n]*pre-iter-N/.test(rest), 'another copy from or to the snapshot');
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
}

if (!ok) process.exit(1);
console.log('\nAll refine-snapshot tests passed.');
