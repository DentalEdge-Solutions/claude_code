#!/usr/bin/env node
// scripts/check-skill-deploy.test.js — check-skill-deploy.js compares every project skill with its
// installed copy. On 2026-10-22, 14 installed skills were found running versions from June and July
// (an August change was never deployed) and gstack-pattern-audit had never been installed: deploys
// copied only the skills each change touched, and nothing compared the whole set.
// Each check builds a project and an installed folder in a temp directory and runs the script on them.
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const SCRIPT = path.join(__dirname, 'check-skill-deploy.js');
let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

function write(root, files) {
  for (const [rel, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  }
}
// Every temp folder is removed at exit (review C6: 13 were left behind per run).
const temps = [];
process.on('exit', () => {
  for (const d of temps) {
    try { chmodTree(d); fs.rmSync(d, { recursive: true, force: true }); } catch { /* best effort */ }
  }
});
function chmodTree(dir) {
  fs.chmodSync(dir, 0o755);
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isSymbolicLink()) continue;
    if (e.isDirectory()) chmodTree(p); else fs.chmodSync(p, 0o644);
  }
}
// A project skills/ folder and an installed folder holding the same two skills.
function setup() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-deploy-'));
  temps.push(tmp);
  const files = {
    'alpha/SKILL.md': '---\nname: alpha\n---\nalpha body\n',
    'alpha/scripts/sub/tool.js': 'console.log(1)\n',
    'beta/SKILL.md': '---\nname: beta\n---\nbeta body\n',
  };
  write(path.join(tmp, 'skills'), files);
  write(path.join(tmp, 'installed'), files);
  return { tmp, src: path.join(tmp, 'skills'), inst: path.join(tmp, 'installed') };
}
function run(args, env = process.env) {
  return spawnSync(process.execPath, [SCRIPT, ...args], { encoding: 'utf8', env });
}
const check = t => run(['--source', t.src, '--installed', t.inst]);

test('every skill identical → exit 0 and the count of skills checked', () => {
  const t = setup();
  const r = check(t);
  assert.strictEqual(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /2 skills? checked/);
  assert.match(r.stdout, /all match/i);
});

test('a skill missing from the installed folder → exit 1, named as missing', () => {
  const t = setup();
  fs.rmSync(path.join(t.inst, 'beta'), { recursive: true });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /beta: not installed/);
  assert.doesNotMatch(r.stdout, /alpha:/);
});

test('a file whose content differs → exit 1, naming the skill and the file', () => {
  const t = setup();
  write(t.inst, { 'alpha/SKILL.md': '---\nname: alpha\n---\nOLD body\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: differs: SKILL\.md/);
});

test('a nested file that differs is found', () => {
  const t = setup();
  write(t.inst, { 'alpha/scripts/sub/tool.js': 'console.log(2)\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: differs: scripts\/sub\/tool\.js/);
});

test('a file only in the installed copy (a leftover) → exit 1', () => {
  const t = setup();
  write(t.inst, { 'beta/SKILL.md.pre-iter-1': 'stale copy\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /beta: only installed: SKILL\.md\.pre-iter-1/);
});

test('a file only in the project (not deployed) → exit 1', () => {
  const t = setup();
  write(t.src, { 'beta/REFERENCE.md': 'new reference\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /beta: not deployed: REFERENCE\.md/);
});

test('skills are discovered from the folder, so a new skill is checked too', () => {
  const t = setup();
  write(t.src, { 'gamma/SKILL.md': 'gamma\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /3 skills? checked/);
  assert.match(r.stdout, /gamma: not installed/);
});

test('installed skills that are not in the project are ignored (other tools install skills there)', () => {
  const t = setup();
  write(t.inst, { 'someone-elses-skill/SKILL.md': 'x\n' });
  const r = check(t);
  assert.strictEqual(r.status, 0, r.stdout);
});

test('file contents are never printed, only names', () => {
  const t = setup();
  const secretish = 'CONTENT-' + 'MARKER-' + 'xyz123';
  write(t.inst, { 'alpha/SKILL.md': secretish + '\n' });
  write(t.src, { 'beta/new.md': secretish + '\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.ok(!(r.stdout + r.stderr).includes(secretish), 'output must not contain file content');
});

test('a differing file: neither side\'s content is printed (review C2)', () => {
  const t = setup();
  const a = 'MARKER-' + 'SOURCE-' + 'aaa111';
  const b = 'MARKER-' + 'INSTALLED-' + 'bbb222';
  write(t.src, { 'alpha/SKILL.md': a + '\n' });
  write(t.inst, { 'alpha/SKILL.md': b + '\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: differs: SKILL\.md/);
  for (const m of [a, b]) assert.ok(!(r.stdout + r.stderr).includes(m), `output must not contain ${m}`);
});

// Symlinks are compared as links, by target, and never followed (review C1).
test('the same symlink on both sides → match', () => {
  const t = setup();
  fs.symlinkSync('SKILL.md', path.join(t.src, 'alpha', 'link.md'));
  fs.symlinkSync('SKILL.md', path.join(t.inst, 'alpha', 'link.md'));
  const r = check(t);
  assert.strictEqual(r.status, 0, r.stdout);
});

test('a symlink with a different target → differs, even when both targets hold the same text', () => {
  const t = setup();
  write(t.src, { 'alpha/one.md': 'same\n' });
  write(t.inst, { 'alpha/one.md': 'same\n', 'alpha/two.md': 'same\n' });
  write(t.src, { 'alpha/two.md': 'same\n' });
  fs.symlinkSync('one.md', path.join(t.src, 'alpha', 'link.md'));
  fs.symlinkSync('two.md', path.join(t.inst, 'alpha', 'link.md'));
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: differs: link\.md/);
});

test('a symlink on one side and a file with the same text on the other → differs', () => {
  const t = setup();
  fs.symlinkSync('SKILL.md', path.join(t.src, 'alpha', 'copy.md'));
  write(t.inst, { 'alpha/copy.md': fs.readFileSync(path.join(t.src, 'alpha', 'SKILL.md'), 'utf8') });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: differs: copy\.md/);
});

test('a folder on one side and a file with the same name on the other → differs', () => {
  const t = setup();
  write(t.src, { 'beta/refs/a.md': 'a\n' });
  write(t.inst, { 'beta/refs': 'a file\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /beta: differs: refs/);
});

test('.DS_Store files are ignored on both sides (review C5)', () => {
  const t = setup();
  write(t.inst, { 'alpha/.DS_Store': 'finder\n' });
  write(t.src, { 'alpha/scripts/sub/.DS_Store': 'finder\n' });
  const r = check(t);
  assert.strictEqual(r.status, 0, r.stdout);
});

const isRoot = typeof process.getuid === 'function' && process.getuid() === 0;
test('an unreadable installed file → exit 2, a named "cannot read" line, no stack trace (review C3)', () => {
  if (isRoot) { console.log('  (skipped: running as root, chmod does not block reads)'); return; }
  const t = setup();
  fs.chmodSync(path.join(t.inst, 'alpha', 'SKILL.md'), 0o000);
  const r = check(t);
  assert.strictEqual(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stdout, /alpha: cannot read: installed alpha\/SKILL\.md \(EACCES\)/);
  assert.doesNotMatch(r.stdout + r.stderr, /\n\s+at /, 'no stack trace');
});

test('an unreadable project subfolder → exit 2, and the other skills are still checked', () => {
  if (isRoot) { console.log('  (skipped: running as root)'); return; }
  const t = setup();
  write(t.inst, { 'beta/SKILL.md': 'changed\n' });
  fs.chmodSync(path.join(t.src, 'alpha', 'scripts'), 0o000);
  const r = check(t);
  assert.strictEqual(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stdout, /alpha: cannot read: project alpha\/scripts \(EACCES\)/);
  assert.match(r.stdout, /beta: differs: SKILL\.md/);
});

test('dotfiles other than .DS_Store are still compared (review C13)', () => {
  const t = setup();
  write(t.src, { 'alpha/.gitkeep': '', 'beta/.env.example': 'A=1\n' });
  write(t.inst, { 'beta/.env.example': 'A=2\n' });
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: not deployed: \.gitkeep/);
  assert.match(r.stdout, /beta: differs: \.env\.example/);
});

// Read errors on the two top-level folders also end in exit 2, never a crash or a false "not installed" (review C12).
test('an unreadable project skills folder → exit 2, "cannot read", no stack trace', () => {
  if (isRoot) { console.log('  (skipped: running as root)'); return; }
  const t = setup();
  fs.chmodSync(t.src, 0o000);
  const r = check(t);
  assert.strictEqual(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stderr, /cannot read the project skills folder .* \(EACCES\)/);
  assert.doesNotMatch(r.stdout + r.stderr, /\n\s+at /, 'no stack trace');
});

test('an unreadable installed skills folder → exit 2 "cannot read", not "not installed"', () => {
  if (isRoot) { console.log('  (skipped: running as root)'); return; }
  const t = setup();
  fs.chmodSync(t.inst, 0o000);
  const r = check(t);
  assert.strictEqual(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stdout, /alpha: cannot read: installed alpha \(EACCES\)/);
  assert.doesNotMatch(r.stdout, /not installed/);
});

test('an installed skill folder that is a symlink to an identical copy → followed, match (review C15)', () => {
  const t = setup();
  const elsewhere = path.join(t.tmp, 'elsewhere-beta');
  fs.cpSync(path.join(t.inst, 'beta'), elsewhere, { recursive: true });
  fs.rmSync(path.join(t.inst, 'beta'), { recursive: true });
  fs.symlinkSync(elsewhere, path.join(t.inst, 'beta'));
  const r = check(t);
  assert.strictEqual(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /all match/);
});

test('an installed skill folder that is a self-looping symlink → not installed, exit 1', () => {
  const t = setup();
  fs.rmSync(path.join(t.inst, 'beta'), { recursive: true });
  fs.symlinkSync('beta', path.join(t.inst, 'beta'));
  const r = check(t);
  assert.strictEqual(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, /beta: not installed/);
});

test('an installed skill that is a dangling symlink → not installed', () => {
  const t = setup();
  fs.rmSync(path.join(t.inst, 'beta'), { recursive: true });
  fs.symlinkSync(path.join(t.tmp, 'nowhere'), path.join(t.inst, 'beta'));
  const r = check(t);
  assert.strictEqual(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, /beta: not installed/);
});

test('a read error is labelled with its own side even when the project folder sits inside the installed one', () => {
  if (isRoot) { console.log('  (skipped: running as root)'); return; }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-deploy-'));
  temps.push(tmp);
  const inst = tmp;
  const src = path.join(tmp, 'skills');
  write(src, { 'a/SKILL.md': 'a\n' });
  write(inst, { 'a/SKILL.md': 'a\n' });
  fs.chmodSync(path.join(src, 'a', 'SKILL.md'), 0o000);
  const r = run(['--source', src, '--installed', inst]);
  assert.strictEqual(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stdout, /a: cannot read: project a\/SKILL\.md \(EACCES\)/);
});

// Argument errors are usage errors, exit 2 (review C4).
{
  const t = setup();
  for (const [label, args, msg] of [
    ['a flag with no value', ['--source'], /--source needs a value/],
    ['a flag whose value is another flag', ['--source', '--installed', t.inst], /--source needs a value/],
    ['an unknown flag', ['--bogus', 'x'], /unknown argument --bogus/],
    ['the --flag=value form', ['--source=x'], /unknown argument --source=x/],
    ['a repeated flag', ['--source', t.src, '--installed', t.inst, '--source', t.src], /--source given more than once/],
    ['a stray argument', ['extra'], /unknown argument extra/],
  ]) {
    test(`${label} → exit 2 with a clear message`, () => {
      const r = run(args);
      assert.strictEqual(r.status, 2, r.stdout + r.stderr);
      assert.match(r.stderr, msg);
    });
  }
}

test('a skill that is a file, not a folder, in the installed copy → exit 1', () => {
  const t = setup();
  fs.rmSync(path.join(t.inst, 'beta'), { recursive: true });
  fs.writeFileSync(path.join(t.inst, 'beta'), 'not a folder\n');
  const r = check(t);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /beta: not installed/);
});

test('a missing project skills folder → exit 2, not a pass', () => {
  const t = setup();
  const r = run(['--source', path.join(t.tmp, 'nope'), '--installed', t.inst]);
  assert.strictEqual(r.status, 2);
});

test('a missing installed folder → exit 1, every skill not installed', () => {
  const t = setup();
  const r = run(['--source', t.src, '--installed', path.join(t.tmp, 'nope')]);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /alpha: not installed/);
  assert.match(r.stdout, /beta: not installed/);
});

test('defaults: the repo skills/ folder against $HOME/.claude/skills', () => {
  const t = setup();
  const home = path.join(t.tmp, 'home');
  fs.mkdirSync(path.join(home, '.claude', 'skills'), { recursive: true });
  const r = run([], { ...process.env, HOME: home });
  assert.strictEqual(r.status, 1, 'an empty installed folder cannot match the repo');
  const repoSkills = fs.readdirSync(path.join(__dirname, '..', 'skills'), { withFileTypes: true })
    .filter(e => e.isDirectory()).length;
  assert.match(r.stdout, new RegExp(`${repoSkills} skills? checked`));
});

test('--help prints usage and exits 0', () => {
  const r = run(['--help']);
  assert.strictEqual(r.status, 0);
  assert.match(r.stdout, /usage/i);
});

if (!ok) process.exit(1);
console.log('check-skill-deploy.test.js: all assertions passed');
