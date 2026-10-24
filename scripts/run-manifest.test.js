#!/usr/bin/env node
// scripts/run-manifest.test.js — end-to-end tests for
// skills/skill-eval/scripts/run-manifest.js. Lives under scripts/ (not the skill
// dir) because it spawns the CLI, and skills/ is held to the no-child_process
// static scan; see .github/skill-scan-baseline.json for why that matters.
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const CLI = path.join(__dirname, '..', 'skills', 'skill-eval', 'scripts', 'run-manifest.js');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}
function run(...args) {
  // cwd = tmpdir: a misparsed argument taken as a relative iteration dir lands
  // there, never in the repo (the red phase once created dirs in the repo root).
  const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd: os.tmpdir() });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function runIn(cwd, ...args) {
  const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'run-manifest-')); }
function manifest(dir) { return JSON.parse(fs.readFileSync(path.join(dir, 'run-manifest.json'), 'utf8')); }

test('init without subject flags still works (backward compatible)', () => {
  const dir = path.join(tmp(), 'iteration-1');
  const r = run('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, 0, r.out);
  const m = manifest(dir);
  assert.strictEqual(m.baseline_method, 'none');
  assert.strictEqual(m.subject, null, 'subject recorded as null when not given');
});

test('status says "subject=not recorded" when the manifest has no subject (E9)', () => {
  const dir = path.join(tmp(), 'iteration-1');
  assert.strictEqual(run('init', dir, '--baseline-method', 'none').status, 0);
  assert.match(run('status', dir).out, /^subject=not recorded$/m);
});

test('init --subject records the path and sha256 of the definition under test', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, '---\nname: demo\n---\nbody\n');
  const dir = path.join(root, 'iteration-1');
  const r = run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'bca59c5');
  assert.strictEqual(r.status, 0, r.out);
  const m = manifest(dir);
  assert.strictEqual(m.subject.path, subject);
  assert.strictEqual(m.subject.sha256, crypto.createHash('sha256').update(fs.readFileSync(subject)).digest('hex'));
  assert.strictEqual(m.subject.commit, 'bca59c5');
});

test('init --subject on a missing file fails instead of recording a bogus hash', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', path.join(root, 'nope.md'));
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /subject/i);
  assert.ok(!fs.existsSync(path.join(root, 'it', 'run-manifest.json')), 'no manifest written');
});

test('init --commit rejects a value that is not a hex SHA', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', subject, '--commit', 'main; rm -rf /');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /commit/i);
});

test('the flag values are not mistaken for the iteration dir', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const dir = path.join(root, 'iteration-2');
  const r = run('init', '--subject', subject, dir, '--baseline-method', 'none', '--commit', 'abcdef1');
  assert.strictEqual(r.status, 0, r.out);
  assert.ok(fs.existsSync(path.join(dir, 'run-manifest.json')));
});

test('status prints the subject revision', () => {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'x');
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'abcdef1');
  const r = run('status', dir);
  assert.match(r.out, /subject=.*SKILL\.md/);
  assert.doesNotMatch(r.out, /subject=not recorded/);   // only when there is no subject (E9 review L3)
  assert.match(r.out, /commit=abcdef1/);
});

test('R5: --commit without --subject is refused, not silently dropped', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--commit', 'abc1234');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--commit requires --subject/);
});

test('R6: a value flag with no value (or another flag as its value) is refused', () => {
  const root = tmp();
  let r = run('init', path.join(root, 'a'), '--baseline-method', 'none', '--subject');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--subject needs a value/);
  r = run('init', path.join(root, 'b'), '--baseline-method', 'none', '--subject', '--commit', 'abc1234');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /--subject needs a value/);
});

test('R6: --subject pointing at a directory fails cleanly, without a stack trace', () => {
  const root = tmp();
  const r = run('init', path.join(root, 'it'), '--baseline-method', 'none', '--subject', root);
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /not a file/);
  assert.doesNotMatch(r.out, /EISDIR|at Object\./);
});

// E10 (PR #4 triage): the subject's sha256 is taken once, at init. A resumed run must see when the definition
// changed since then, because the resumed scenarios would measure a different text. status re-hashes the
// subject and warns; its exit code is unchanged (it stays the artifacts-and-grading gate).
function gradedIteration() {
  const root = tmp();
  const subject = path.join(root, 'SKILL.md');
  fs.writeFileSync(subject, 'v1');
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none', '--subject', subject, '--commit', 'abcdef1');
  for (const side of ['with_skill', 'without_skill']) {
    const d = path.join(dir, 's1-x-r1', side);
    fs.mkdirSync(d, { recursive: true });
    for (const f of ['output.md', 'timing.json', 'evidence.json']) fs.writeFileSync(path.join(d, f), '{}');
  }
  run('mark', dir, 's1-x-r1', 'graded');
  return { subject, dir };
}

test('E10: status says the subject is unchanged when it is', () => {
  const { dir } = gradedIteration();
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /subject unchanged since init/);
  assert.doesNotMatch(r.out, /WARNING/);
});

test('E10: status warns when the subject changed since init, with the same exit code', () => {
  const { subject, dir } = gradedIteration();
  fs.writeFileSync(subject, 'v2');
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /WARNING: the subject changed since init/);
  const now = crypto.createHash('sha256').update('v2').digest('hex').slice(0, 12);
  assert.ok(r.out.includes(now), `the current sha256 ${now} is not printed`);
  assert.match(r.out, /start a new iteration/);
  assert.doesNotMatch(r.out, /subject unchanged/);
});

test('E10: status warns when the subject is gone, with the same exit code', () => {
  const { subject, dir } = gradedIteration();
  fs.rmSync(subject);
  const r = run('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /WARNING: the subject .*SKILL\.md is not found/);
});

test('E10: a changed subject does not turn a failing status into a passing one', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.writeFileSync(subject, 'v2');
  const r = run('status', dir);
  assert.notStrictEqual(r.status, 0);
  assert.match(r.out, /WARNING: the subject changed since init/);
});

test('E10 review R3: the not-found warning says to start a new iteration', () => {
  const { subject, dir } = gradedIteration();
  fs.rmSync(subject);
  assert.match(run('status', dir).out, /WARNING: the subject [^\n]*not found[^\n]*start a new iteration/);
});

test('E10 review R3: a relative subject resolves against the working directory, as at init', () => {
  const root = tmp();
  fs.writeFileSync(path.join(root, 'SKILL.md'), 'v1');
  fs.mkdirSync(path.join(root, 'sub'));
  runIn(root, 'init', 'iteration-1', '--baseline-method', 'none', '--subject', 'SKILL.md', '--commit', 'abcdef1');
  assert.match(runIn(root, 'status', 'iteration-1').out, /subject unchanged since init/);
  fs.writeFileSync(path.join(root, 'SKILL.md'), 'v2');
  assert.match(runIn(root, 'status', 'iteration-1').out, /WARNING: the subject changed since init/);
  assert.match(runIn(path.join(root, 'sub'), 'status', path.join('..', 'iteration-1')).out, /WARNING: the subject SKILL\.md is not found/);
});

// Review R1: after a warning, the closing line must not tell the reader to resume.
const RESUME_LINE = /Resume by dispatching only the incomplete scenarios/;
test('E10 review R1: a failing status after a subject change closes with "start a new iteration", not "Resume"', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.writeFileSync(subject, 'v2');
  const last = run('status', dir).out.trim().split('\n').pop();
  assert.match(last, /^STATUS: FAILED/);
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E10 review R8: a failing status with the subject gone closes with "start a new iteration", not "Resume"', () => {
  const { subject, dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  fs.rmSync(subject);
  const last = run('status', dir).out.trim().split('\n').pop();
  assert.match(last, /^STATUS: FAILED/);
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E12 review R1: a snapshot manifest (made before E12) is warned about and not resumed', () => {
  const root = tmp();
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'snapshot', '--snapshot-path', path.join(root, 'snap.md'));
  run('mark', dir, 's1-x-r1', 'pending');
  const out = run('status', dir).out;
  assert.match(out, /WARNING: this manifest records baseline_method=snapshot/);
  const last = out.trim().split('\n').pop();
  assert.match(last, /start a new iteration/);
  assert.doesNotMatch(last, RESUME_LINE);
});

test('E10 review R1: a plain failing status still says to resume', () => {
  const { dir } = gradedIteration();
  run('mark', dir, 's2-x-r1', 'pending');
  assert.match(run('status', dir).out.trim().split('\n').pop(), RESUME_LINE);
});

test('E10: no subject, no check line', () => {
  const root = tmp();
  const dir = path.join(root, 'iteration-1');
  run('init', dir, '--baseline-method', 'none');
  const r = run('status', dir);
  assert.doesNotMatch(r.out, /subject unchanged|WARNING: the subject/);
});

// P0-11: init also pins the evaluator (harvester, this script, both scenario generators, the rubric), and status
// refuses resumption when it changed, so a refine loop cannot edit its own judge. These tests mutate evaluator
// files, so they run a copy of skill-eval/ and agent-eval/ in a fresh temp dir, never the repo's own files.
// Every temp dir they make is removed when the test ends (ptest), so runs leave nothing in os.tmpdir().
const REPO_SKILLS = path.join(__dirname, '..', 'skills');
const EVALUATOR_LABELS = [
  'skill-eval/scripts/harvest-evidence.js',
  'skill-eval/scripts/run-manifest.js',
  'skill-eval/scripts/generate-seed-evals.js',
  'agent-eval/scripts/generate-agent-evals.js',
  'skill-eval/REFERENCE.md',
];
const EVALUATOR_REFUSED = 2;
const NO_RESUME = /Do not resume this iteration: start a new iteration/;
const HARVESTER = 'skill-eval/scripts/harvest-evidence.js';

const made = [];
function mkroot(prefix) { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); made.push(d); return d; }
function ptest(label, fn) {
  test(label, () => {
    try { fn(); }
    finally { while (made.length) fs.rmSync(made.pop(), { recursive: true, force: true }); }
  });
}

// A copied skills tree; returns its root, the copied skills dir, and a runner for the copied CLI (cwd = the root).
function evaluatorCopy() {
  const root = mkroot('run-manifest-evaluator-');
  const skills = path.join(root, 'skills');
  for (const s of ['skill-eval', 'agent-eval']) fs.cpSync(path.join(REPO_SKILLS, s), path.join(skills, s), { recursive: true });
  const cli = path.join(skills, 'skill-eval', 'scripts', 'run-manifest.js');
  const runCopy = (...args) => {
    const r = spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8', cwd: root });
    return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
  };
  return { root, skills, runCopy };
}
// Like gradedIteration, against a copied evaluator: one scenario, graded, every artifact present.
function gradedCopy() {
  const c = evaluatorCopy();
  const dir = path.join(c.root, 'iteration-1');
  const r = c.runCopy('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, 0, r.out);
  for (const side of ['with_skill', 'without_skill']) {
    const d = path.join(dir, 's1-x-r1', side);
    fs.mkdirSync(d, { recursive: true });
    for (const f of ['output.md', 'timing.json', 'evidence.json']) fs.writeFileSync(path.join(d, f), '{}');
  }
  c.runCopy('mark', dir, 's1-x-r1', 'graded');
  return { ...c, dir, ref: path.join(dir, 'run-manifest.json') };
}
const sha = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
// Rewrites the evaluator block of a manifest (fn gets the block, returns the new one; undefined deletes it).
function editEvaluator(manifestFile, fn) {
  const m = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
  const next = fn(m.evaluator);
  if (next === undefined) delete m.evaluator; else m.evaluator = next;
  fs.writeFileSync(manifestFile, JSON.stringify(m, null, 2));
}
// Replaces a copied evaluator file by a symlink to an identical copy outside the skills tree.
function symlinkInPlace(root, skills, label) {
  const outside = path.join(root, 'outside-copy');
  fs.copyFileSync(path.join(skills, label), outside);
  fs.rmSync(path.join(skills, label));
  fs.symlinkSync(outside, path.join(skills, label));
}

ptest('P0-11: init records an evaluator block, label -> sha256, for exactly the five evaluator files', () => {
  const { skills, dir } = gradedCopy();
  const m = manifest(dir);
  assert.ok(m.evaluator && typeof m.evaluator === 'object', 'no evaluator block');
  assert.deepStrictEqual(Object.keys(m.evaluator).sort(), [...EVALUATOR_LABELS].sort());
  for (const label of EVALUATOR_LABELS) assert.strictEqual(m.evaluator[label], sha(path.join(skills, label)), label);
  assert.strictEqual(m.evaluator_ref, null);
});

ptest('P0-11 acceptance: a harvester edited between init and status is refused, even with every scenario graded', () => {
  const { skills, dir, runCopy } = gradedCopy();
  fs.appendFileSync(path.join(skills, HARVESTER), '\n// edited by a refine lever\n');
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/scripts\/harvest-evidence\.js/);
  assert.match(r.out, NO_RESUME);
  assert.doesNotMatch(r.out, /STATUS: OK/);
  assert.ok(r.out.includes(sha(path.join(skills, HARVESTER)).slice(0, 12)), 'the current short hash is not printed');
});

ptest('P0-11: the grading rubric REFERENCE.md edited between init and status is refused', () => {
  const { skills, dir, runCopy } = gradedCopy();
  fs.appendFileSync(path.join(skills, 'skill-eval/REFERENCE.md'), '\nA lenient new rubric line.\n');
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/REFERENCE\.md/);
  assert.doesNotMatch(r.out, /harvest-evidence\.js/, 'only the changed file is named');
  assert.match(r.out, NO_RESUME);
});

ptest('P0-11: an evaluator file deleted between init and status is refused', () => {
  const { skills, dir, runCopy } = gradedCopy();
  fs.rmSync(path.join(skills, 'agent-eval/scripts/generate-agent-evals.js'));
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /agent-eval\/scripts\/generate-agent-evals\.js[^\n]*missing/);
});

ptest('P0-11: an evaluator file replaced by a symlink (same content) is refused by status: not a regular file', () => {
  const { root, skills, dir, runCopy } = gradedCopy();
  symlinkInPlace(root, skills, HARVESTER);
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /harvest-evidence\.js[^\n]*not a regular file/);
});

ptest('P0-11: an unchanged evaluator with every scenario graded still passes (exit 0)', () => {
  const { dir, runCopy } = gradedCopy();
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /evaluator unchanged since init/);
  assert.match(r.out, /STATUS: OK/);
});

ptest('P0-11: the evaluator refusal wins over an ordinary failing status (exit 2, never "Resume")', () => {
  const { skills, dir, runCopy } = gradedCopy();
  runCopy('mark', dir, 's2-x-r1', 'pending');
  fs.appendFileSync(path.join(skills, 'skill-eval/scripts/generate-seed-evals.js'), '\n');
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  const last = r.out.trim().split('\n').pop();
  assert.match(last, NO_RESUME);
  assert.doesNotMatch(last, RESUME_LINE);
});

ptest('P0-11: a refused manifest with no scenarios recorded still exits 2, not 1', () => {
  const { root, skills, runCopy } = evaluatorCopy();
  const dir = path.join(root, 'iteration-1');
  assert.strictEqual(runCopy('init', dir, '--baseline-method', 'none').status, 0);
  fs.appendFileSync(path.join(skills, HARVESTER), '\n');
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out.trim().split('\n').pop(), NO_RESUME);
});

ptest('P0-11: a manifest with no evaluator record (made before P0-11) is refused', () => {
  const { dir, ref, runCopy } = gradedCopy();
  editEvaluator(ref, () => undefined);
  const r = runCopy('status', dir);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /evaluator not recorded/i);
  assert.match(r.out, NO_RESUME);
});

// A record is checked against the script's own list, never against the labels it happens to contain.
ptest('P0-11: status refuses an empty, a partial, and an extra-label evaluator record', () => {
  const cases = [
    ['empty {}', () => ({}), /harvest-evidence\.js/],
    ['missing one label', ev => { const e = { ...ev }; delete e['skill-eval/REFERENCE.md']; return e; }, /skill-eval\/REFERENCE\.md[^\n]*recorded none/],
    ['an extra label', ev => ({ ...ev, 'skill-eval/scripts/old-judge.js': 'a'.repeat(64) }), /old-judge\.js[^\n]*no longer part of the evaluator/],
    ['an array', () => [], /evaluator not recorded/i],
  ];
  for (const [name, fn, named] of cases) {
    const { dir, ref, runCopy } = gradedCopy();
    editEvaluator(ref, fn);
    const r = runCopy('status', dir);
    assert.strictEqual(r.status, EVALUATOR_REFUSED, `${name}: ${r.out}`);
    assert.match(r.out, named, name);
  }
});

ptest('P0-11: init refuses, writing no manifest, when a listed evaluator file is missing', () => {
  const { root, skills, runCopy } = evaluatorCopy();
  fs.rmSync(path.join(skills, 'skill-eval/scripts/generate-seed-evals.js'));
  const dir = path.join(root, 'iteration-1');
  const r = runCopy('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/scripts\/generate-seed-evals\.js/);
  assert.ok(!fs.existsSync(path.join(dir, 'run-manifest.json')), 'no manifest written');
});

ptest('P0-11: init refuses when a listed evaluator path is a directory or a symlink (not a regular file)', () => {
  const { root, skills, runCopy } = evaluatorCopy();
  fs.rmSync(path.join(skills, 'skill-eval/REFERENCE.md'));
  fs.mkdirSync(path.join(skills, 'skill-eval/REFERENCE.md'));
  let dir = path.join(root, 'iteration-1');
  let r = runCopy('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/REFERENCE\.md/);
  assert.doesNotMatch(r.out, /EISDIR|at Object\./);
  assert.ok(!fs.existsSync(path.join(dir, 'run-manifest.json')), 'no manifest written');

  const c = evaluatorCopy();
  symlinkInPlace(c.root, c.skills, HARVESTER);
  dir = path.join(c.root, 'iteration-1');
  r = c.runCopy('init', dir, '--baseline-method', 'none');
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /harvest-evidence\.js/);
  assert.ok(!fs.existsSync(path.join(dir, 'run-manifest.json')), 'no manifest written');
});

ptest('P0-11 acceptance: every listed evaluator file exists in the repo tree (the list cannot drift on a rename)', () => {
  const r = run('evaluator');
  assert.strictEqual(r.status, 0, r.out);
  const labels = r.out.trim().split('\n').map(l => l.trim().split(/\s+/).pop());
  assert.deepStrictEqual(labels, EVALUATOR_LABELS, 'the pinned list changed: update this test and the P0-11 record together');
  for (const label of labels) {
    const p = path.join(REPO_SKILLS, label);
    assert.ok(fs.existsSync(p) && fs.lstatSync(p).isFile(), `${label} is not a regular file under skills/`);
    assert.ok(r.out.includes(`${sha(p)}  ${label}`), `${label}: sha256 not printed`);
  }
});

ptest('P0-11: the evaluator subcommand prints MISSING / NOT-A-FILE and exits 1 for an absent or symlinked file', () => {
  const { root, skills, runCopy } = evaluatorCopy();
  fs.rmSync(path.join(skills, 'skill-eval/REFERENCE.md'));
  symlinkInPlace(root, skills, HARVESTER);
  const r = runCopy('evaluator');
  assert.strictEqual(r.status, 1, r.out);
  assert.match(r.out, /^MISSING {2}skill-eval\/REFERENCE\.md$/m);
  assert.match(r.out, /^NOT-A-FILE {2}skill-eval\/scripts\/harvest-evidence\.js$/m);
  assert.match(r.out, /^[0-9a-f]{64} {2}skill-eval\/scripts\/run-manifest\.js$/m);
});

ptest('P0-11: init --evaluator-ref with the same evaluator succeeds and records the reference path and its sha256', () => {
  const { root, dir, ref, runCopy } = gradedCopy();
  const dir2 = path.join(root, 'iteration-2');
  const r = runCopy('init', dir2, '--baseline-method', 'none', '--evaluator-ref', path.relative(root, ref));
  assert.strictEqual(r.status, 0, r.out);
  const m = manifest(dir2);
  assert.deepStrictEqual(m.evaluator_ref, { path: fs.realpathSync(ref), sha256: sha(ref) });
  assert.deepStrictEqual(m.evaluator, manifest(dir).evaluator);
});

ptest('P0-11: init --evaluator-ref refuses, writing no manifest, when the evaluator changed since the referenced run', () => {
  const { root, skills, ref, runCopy } = gradedCopy();
  fs.appendFileSync(path.join(skills, HARVESTER), '\n// edited between iterations\n');
  const dir2 = path.join(root, 'iteration-2');
  const r = runCopy('init', dir2, '--baseline-method', 'none', '--evaluator-ref', ref);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/scripts\/harvest-evidence\.js/);
  assert.ok(!fs.existsSync(path.join(dir2, 'run-manifest.json')), 'no manifest written');
});

// Every way a reference can be unusable exits 2 and writes nothing: a refine stops on it rather than dropping the flag.
function badReferences(root, ref) {
  const write = (name, text) => { const p = path.join(root, name); fs.writeFileSync(p, text); return p; };
  const m = JSON.parse(fs.readFileSync(ref, 'utf8'));
  const withEvaluator = (name, ev) => { const c = { ...m }; if (ev === undefined) delete c.evaluator; else c.evaluator = ev; return write(name, JSON.stringify(c)); };
  const partial = { ...m.evaluator }; delete partial[HARVESTER];
  return [
    ['a missing file', path.join(root, 'nope.json'), /could not be read|no such file/i],
    ['an empty file', write('empty.json', ''), /--evaluator-ref|reference/],
    ['a directory', root, /--evaluator-ref|reference/],
    ['garbage JSON', write('garbage.json', '{not json'), /--evaluator-ref|reference/],
    ['JSON null', write('null.json', 'null'), /no evaluator record/i],
    ['no evaluator record', withEvaluator('old.json', undefined), /no evaluator record/i],
    ['an array record', withEvaluator('array.json', []), /no evaluator record/i],
    ['an empty {} record', withEvaluator('emptyrec.json', {}), /harvest-evidence\.js/],
    ['a partial record', withEvaluator('partial.json', partial), /harvest-evidence\.js[^\n]*recorded none/],
    ['an extra label', withEvaluator('extra.json', { ...m.evaluator, 'x/old.js': 'b'.repeat(64) }), /x\/old\.js/],
  ];
}

ptest('P0-11: init --evaluator-ref refuses every unusable reference with exit 2 and writes no manifest', () => {
  const { root, ref, runCopy } = gradedCopy();
  for (const [name, bad, named] of badReferences(root, ref)) {
    const dir2 = path.join(root, `it-${name.replace(/\W+/g, '-')}`);
    const r = runCopy('init', dir2, '--baseline-method', 'none', '--evaluator-ref', bad);
    assert.strictEqual(r.status, EVALUATOR_REFUSED, `${name}: ${r.out}`);
    assert.match(r.out, named, name);
    assert.doesNotMatch(r.out, /at Object\.|at Module\./, `${name}: stack trace`);
    assert.ok(!fs.existsSync(path.join(dir2, 'run-manifest.json')), `${name}: manifest written`);
  }
});

ptest('P0-11: --evaluator-ref with no value, a flag as its value, or given twice is refused (exit 2), no manifest', () => {
  const { root, ref, runCopy } = gradedCopy();
  const cases = [
    ['a', ['--baseline-method', 'none', '--evaluator-ref'], /--evaluator-ref needs a value/],
    ['b', ['--evaluator-ref', '--baseline-method', 'none'], /--evaluator-ref needs a value/],
    ['c', ['--baseline-method', 'none', '--evaluator-ref', ref, '--evaluator-ref', ref], /--evaluator-ref given more than once/],
  ];
  for (const [d, args, msg] of cases) {
    const r = runCopy('init', path.join(root, d), ...args);
    assert.strictEqual(r.status, EVALUATOR_REFUSED, `${d}: ${r.out}`);
    assert.match(r.out, msg, d);
    assert.ok(!fs.existsSync(path.join(root, d, 'run-manifest.json')), `manifest written in ${d}`);
  }
});

ptest('P0-11: the flag value of --evaluator-ref is not mistaken for the iteration dir', () => {
  const { root, ref, runCopy } = gradedCopy();
  const dir2 = path.join(root, 'iteration-2');
  const r = runCopy('init', dir2, '--baseline-method', 'none', '--evaluator-ref', ref);
  assert.strictEqual(r.status, 0, r.out);
  assert.ok(fs.existsSync(path.join(dir2, 'run-manifest.json')));
});

// check-ref: the refine's start-of-session check, before any edit (PR2-R-2).
ptest('P0-11: check-ref exits 0 when the reference matches the evaluator now', () => {
  const { ref, runCopy } = gradedCopy();
  const r = runCopy('check-ref', ref);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /evaluator matches/);
});

ptest('P0-11: check-ref exits 2 when the evaluator changed, or a file is a symlink, naming the file', () => {
  const { root, skills, ref, runCopy } = gradedCopy();
  fs.appendFileSync(path.join(skills, 'skill-eval/REFERENCE.md'), '\n');
  let r = runCopy('check-ref', ref);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /skill-eval\/REFERENCE\.md/);
  const c = gradedCopy();
  symlinkInPlace(c.root, c.skills, HARVESTER);
  r = c.runCopy('check-ref', c.ref);
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /harvest-evidence\.js[^\n]*not a regular file/);
  assert.ok(root);
});

ptest('P0-11: check-ref exits 2 for every unusable reference, and with no argument', () => {
  const { root, ref, runCopy } = gradedCopy();
  for (const [name, bad, named] of badReferences(root, ref)) {
    const r = runCopy('check-ref', bad);
    assert.strictEqual(r.status, EVALUATOR_REFUSED, `${name}: ${r.out}`);
    assert.match(r.out, named, name);
    assert.doesNotMatch(r.out, /at Object\.|at Module\./, `${name}: stack trace`);
  }
  const r = runCopy('check-ref');
  assert.strictEqual(r.status, EVALUATOR_REFUSED, r.out);
  assert.match(r.out, /check-ref requires/);
});

// The instruction layer. Each refine definition forbids editing every pinned file (read from the script, so a change
// to the list fails here until the definitions follow), checks the reference before any edit, takes it from
// refine-input.json's eval_manifest, runs its re-evals in refine/re-eval-N (never an eval iteration-<N>), stops on any
// non-zero init after reverting the pending edit, and refuses an evaluator subject.
// RUN_MANIFEST_DEFS_ROOT may point at another checkout (used to show these fail on earlier definitions).
const DEFS_ROOT = process.env.RUN_MANIFEST_DEFS_ROOT || path.join(__dirname, '..');
const defText = def => fs.readFileSync(path.join(DEFS_ROOT, def), 'utf8');
const REFINE_DEFS = ['skills/skill-refine/SKILL.md', 'skills/agent-refine/SKILL.md',
  '.claude/agents/skill-refine-agent.md', '.claude/agents/agent-refine-agent.md'];
// skill-guardian runs its own refine loop (Phase 4): it gets the never-edit list and the evaluator-subject refusal,
// not the reference handshake (PR2-R-12; the agent is due for retirement, OPP-30).
for (const def of [...REFINE_DEFS, '.claude/agents/skill-guardian.md']) {
  test(`P0-11: ${def} forbids editing each evaluator file and refuses an evaluator subject`, () => {
    const text = defText(def);
    const labels = run('evaluator').out.trim().split('\n').map(l => l.trim().split(/\s+/).pop());
    for (const label of labels) assert.ok(text.includes(`\`${label}\``), `does not name ${label}`);
    const i = text.indexOf('frozen-copy procedure');
    assert.ok(i !== -1, 'no refusal for an evaluator subject');
    const refusal = text.slice(Math.max(0, i - 300), i);   // the refusal names the four subjects just before
    for (const subject of ['skill-eval', 'agent-eval', 'skill-eval-agent', 'agent-eval-agent']) {
      assert.match(refusal, new RegExp(`(^|[^-\\w])${subject}([^-\\w]|$)`), `the refusal does not name ${subject}`);
    }
  });
}
test('P0-11 review: skill-guardian says its loop has no evaluator-reference check and points to skill-refine-agent', () => {
  assert.match(defText('.claude/agents/skill-guardian.md'), /no evaluator-reference check[^\n]*skill-refine-agent/);
});
for (const def of REFINE_DEFS) {
  test(`P0-11: ${def} passes --evaluator-ref`, () => {
    assert.match(defText(def), /--evaluator-ref/);
  });

  test(`P0-11 review: ${def} runs re-evals in refine/re-eval-N, never in an eval iteration-<N> dir`, () => {
    const text = defText(def);
    assert.ok(text.includes('refine/re-eval-N'), 'no refine/re-eval-N dir');
    const inits = text.split('\n').filter(l => /run-manifest\.js init /.test(l));
    for (const l of inits) {
      assert.match(l, /refine\/re-eval-N/, `init outside refine/re-eval-N: ${l.trim()}`);
      assert.doesNotMatch(l, /iteration-/, `init names an eval iteration dir: ${l.trim()}`);
    }
    assert.match(text, /cp [^\n]*evals\.json[^\n]*refine\/evals\.json/, 'evals.json is not copied where the harvester looks for it');
  });

  test(`P0-11 review: ${def} takes the reference from eval_manifest and checks it with check-ref before any edit`, () => {
    const text = defText(def);
    assert.ok(text.includes('eval_manifest'), 'does not read eval_manifest');
    assert.match(text, /run-manifest\.js check-ref/);
    const check = text.indexOf('check-ref');
    const firstEdit = text.indexOf('pre-iter-N');
    assert.ok(check !== -1 && check < firstEdit, 'check-ref must come before the first mutation step');
    assert.match(text, /fresh eval/i, 'does not say a fresh eval is needed when the reference fails');
    assert.doesNotMatch(text, /highest-numbered[^\n]*iteration-<B>/, 'still guesses B from the highest-numbered iteration');
  });

  test(`P0-11 review: ${def} stops on any non-zero init/status after reverting the pending edit, and never edits a manifest`, () => {
    const text = defText(def);
    assert.match(text, /non-zero[^\n]*pre-iter-N/, 'no revert-then-stop on a non-zero init/status');
    assert.match(text, /never edit[^\n]*run-manifest\.json/i, 'no rule against editing run manifests');
  });

  // PR2-R-11: the scenarios a re-eval dispatches and the ones the harvester scores against are the same file, and
  // that file is the one the baseline eval used.
  test(`P0-11 review 2: ${def} pins the scenario set before any edit and never regenerates it mid-loop`, () => {
    const text = defText(def);
    const firstEdit = text.indexOf('pre-iter-N');
    const copy = text.search(/cp [^\n]*evals\.json[^\n]*refine\/evals\.json/);
    assert.ok(copy !== -1 && copy < firstEdit, 'evals.json is not copied to refine/ before the first mutation step');
    const check = text.search(/shasum -a 256[^\n]*refine\/evals\.json/);
    assert.ok(check !== -1 && check < firstEdit, 'the copy is not hashed before the first mutation step');
    const field = text.indexOf('eval_scenarios_sha256');
    assert.ok(field !== -1 && field < firstEdit, 'the copy is not checked against eval_scenarios_sha256 before the first edit');
    assert.match(text, /do not regenerate[^\n]*refine\/evals\.json/i, 'the mid-loop re-eval may regenerate the scenarios');
    assert.doesNotMatch(text, /refine\/evals\.json[^\n]*`--evaluator-ref` compares against/, '--evaluator-ref does not compare evals.json');
  });

  // PR2-R-14: re-eval-0 (the staleness re-run) has no pending edit to revert.
  test(`P0-11 review 2: ${def} says re-eval-0 has no pending edit wherever it names re-eval-0`, () => {
    const text = defText(def);
    if (text.includes('re-eval-0')) assert.ok(text.includes('(none for re-eval-0)'), 'no "(none for re-eval-0)" on the refusal clause');
  });
}
for (const def of ['skills/skill-eval/SKILL.md', 'skills/agent-eval/SKILL.md',
  '.claude/agents/skill-eval-agent.md', '.claude/agents/agent-eval-agent.md']) {
  test(`P0-11: ${def} says an evaluator refusal (status exit 2) means a new iteration`, () => {
    const text = defText(def);
    assert.ok((text.match(/exits? 2[^\n]*start a new iteration/gi) || []).length >= 2, 'resume check and integrity step must both say it');
  });

  test(`P0-11 review: ${def} carries a caller's --evaluator-ref, stops on its refusal, explains init exit 2, writes eval_manifest`, () => {
    const text = defText(def);
    assert.match(text, /--evaluator-ref/);
    assert.match(text, /EVALUATOR_REFUSED/);
    assert.match(text, /never start another iteration/i);
    assert.match(text, /`init` exits 2/);
    assert.ok(text.includes('eval_manifest'), 'refine-input.json handoff does not name eval_manifest');
  });

  test(`P0-11 review 2: ${def} writes eval_scenarios_sha256 (shasum -a 256 of the evals.json it used) beside eval_manifest`, () => {
    const text = defText(def);
    assert.ok(text.includes('eval_scenarios_sha256'), 'refine-input.json handoff does not name eval_scenarios_sha256');
    assert.match(text, /eval_scenarios_sha256[^\n]*evals\.json|evals\.json[^\n]*eval_scenarios_sha256/, 'does not say which file it hashes');
  });
}
test('P0-11 review: the agent-eval handoff format in REFERENCE.md has eval_manifest and eval_scenarios_sha256', () => {
  const text = defText('skills/agent-eval/REFERENCE.md');
  assert.match(text, /"eval_manifest": "evals\/agents\/[^"]*\/iteration-\d+\/run-manifest\.json"/);
  assert.match(text, /"eval_scenarios_sha256": "[^"]*evals\/agents\/[^"]*\/evals\.json[^"]*"/);
});

ptest('P0-11: the usage text documents the exit codes, the evaluator refusal, --evaluator-ref and check-ref', () => {
  const r = run('--help');
  assert.match(r.out, /--evaluator-ref/);
  assert.match(r.out, /check-ref/);
  assert.match(r.out, /Exit codes/i);
  assert.match(r.out, /2\b[^\n]*evaluator/);
});

if (!ok) process.exit(1);
console.log('\nrun-manifest.test.js: all tests passed');
