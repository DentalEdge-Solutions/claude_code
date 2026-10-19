#!/usr/bin/env node
// scripts/claude-settings.test.js — tests for this repo's own .claude/settings.json deny rules (HR1).
//
// HR1 (docs/evaluations/2026-10-14-gsd-global-install-audit.md §7): secret files in this repo that the
// global GSD secret-read guard does not cover (the Hermes container home, the credential pool) were
// readable by Claude Code. The project settings now deny Read and Edit on them. A Read deny also covers
// Edit/Write; the Edit rule adds NotebookEdit (code.claude.com/docs/en/permissions, read 2026-10-19).
//
// Project settings load only from the session's starting folder (no parent fallback), and a `/path`
// rule is anchored there (code.claude.com/docs/en/permissions and /settings, read 2026-10-19). So the
// rules are committed twice: at the repo root and in infra/hermes-agent/, where sessions also start
// (independent review H1). Sessions in worktrees reading the main tree by absolute path need the
// user-level rules (layer B in docs/evaluations/2026-10-19-hr1-secret-read-controls.md).
//
// The matcher below covers only `/`-anchored patterns, `**/<name>` and a bare `<name>` (both "any
// depth" in the docs). It refuses every other form, including unanchored patterns with a `/` whose
// anchoring the docs and measured behaviour disagree on (review H5), so a rule it cannot judge fails
// the test instead of passing silently.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
// Each settings file and the repo folder its `/` rules are anchored at.
const SETTINGS_FILES = [
  { dir: '', file: path.join(REPO, '.claude', 'settings.json'), telemetry: true },
  { dir: 'infra/hermes-agent', file: path.join(REPO, 'infra', 'hermes-agent', '.claude', 'settings.json') },
];

// Secret files (present or expected) that must be unreadable to Claude Code's tools in this repo.
const PROTECTED = [
  'infra/hermes-agent/.env',
  'infra/hermes-agent/.env.ga',
  'infra/hermes-agent/.env.gaw',
  'infra/hermes-agent/.env.pr',
  'infra/hermes-agent/data/auth.json',
  'infra/hermes-agent/data/home/.claude/settings.json',
  'infra/hermes-agent/data/home/.claude/projects/-projects-claude-code/session.jsonl',
  'infra/hermes-agent/data/profiles/architect/.env',
  'infra/hermes-agent/data/.claude/settings.json',
  'infra/hermes-agent/data/.claude/projects/-opt-data/session.jsonl',
  'infra/hermes-agent/data/.claude.json',
  'some/other/dir/.env',
  '.env',
];

// Files sessions must still be able to read.
const READABLE = [
  'infra/hermes-agent/.env.example',
  'infra/hermes-agent/.env.ga.example',
  'infra/hermes-agent/data/config.yaml',
  'infra/hermes-agent/data/logs/gateway.log',
  'infra/hermes-agent/data/profiles/architect/SOUL.md',
  '.claude/settings.json',
];

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// Repo-relative path → does the rule's path pattern match it?
function globToRegExp(pattern) {
  if (/[?[\]{}!\\]/.test(pattern) || pattern.startsWith('~') || pattern.startsWith('//') || pattern.startsWith('./')
      || (!pattern.startsWith('/') && pattern.replace(/^\*\*\//, '').includes('/'))) {
    throw new Error(`rule path form not supported by this test: ${pattern}`);
  }
  const anchored = pattern.startsWith('/');
  const body = anchored ? pattern.slice(1) : pattern;
  let re = '';
  for (let i = 0; i < body.length; i++) {
    if (body.startsWith('**/', i)) { re += '(?:.*/)?'; i += 2; }
    else if (body.startsWith('**', i)) { re += '.*'; i += 1; }
    else if (body[i] === '*') re += '[^/]*';
    else re += body[i].replace(/[.+^$()|]/g, '\\$&');
  }
  return new RegExp(`^${anchored ? '' : '(?:.*/)?'}${re}$`);
}

function rulesFor(tool, deny) {
  return deny
    .map(r => r.match(new RegExp(`^${tool}\\((.*)\\)$`)))
    .filter(Boolean)
    .map(m => ({ rule: `${tool}(${m[1]})`, re: globToRegExp(m[1]) }));
}

test('the matcher reads anchored, any-depth and wildcard forms the way the docs describe', () => {
  assert.ok(globToRegExp('/a/b/**').test('a/b/c/d'));
  assert.ok(!globToRegExp('/a/b/**').test('x/a/b/c'));
  assert.ok(globToRegExp('**/.env').test('.env') && globToRegExp('**/.env').test('x/y/.env'));
  assert.ok(globToRegExp('.env').test('x/.env'));
  assert.ok(globToRegExp('/a/*/.env').test('a/p/.env') && !globToRegExp('/a/*/.env').test('a/p/q/.env'));
  assert.ok(!globToRegExp('/a/.env').test('a/.env.example'));
  for (const bad of ['~/x', 'data/home/**', '*/.env', '//abs', './x']) assert.throws(() => globToRegExp(bad), bad);
});

const r = spawnSync('git', ['ls-files', '-z'], { cwd: REPO, encoding: 'utf8' });
const tracked = r.status === 0 ? r.stdout.split('\0').filter(Boolean) : [];
test('git ls-files lists the repo', () => assert.ok(tracked.length > 100, r.stderr));

// Repo-relative paths under `dir`, made relative to it (the paths a session started there sees).
const under = (dir, paths) => paths.filter(p => !dir || p.startsWith(dir + '/')).map(p => (dir ? p.slice(dir.length + 1) : p));

for (const { dir, file, telemetry } of SETTINGS_FILES) {
  const where = path.relative(REPO, file);
  let deny = [];
  test(`${where} parses and holds a deny list`, () => {
    const settings = JSON.parse(fs.readFileSync(file, 'utf8'));
    deny = (settings.permissions && settings.permissions.deny) || [];
    assert.ok(deny.length > 0);
    if (telemetry) assert.ok(settings.hooks && settings.hooks.PostToolUse && settings.hooks.Stop, 'telemetry hooks missing');
  });

  for (const tool of ['Read', 'Edit']) {
    test(`${where}: every protected secret path under ${dir || 'the repo root'} has a ${tool} deny rule`, () => {
      const rules = rulesFor(tool, deny);
      assert.deepStrictEqual(under(dir, PROTECTED).filter(p => !rules.some(x => x.re.test(p))), []);
    });
  }

  test(`${where}: no deny rule matches a path sessions must still read, or a tracked file`, () => {
    const rules = [...rulesFor('Read', deny), ...rulesFor('Edit', deny)];
    const paths = [...under(dir, READABLE), ...under(dir, tracked)];
    assert.deepStrictEqual(paths.flatMap(p => rules.filter(x => x.re.test(p)).map(x => `${p} ← ${x.rule}`)), []);
  });

  test(`${where}: every Read deny rule has a matching Edit rule, and deny holds only Read/Edit rules`, () => {
    const read = deny.filter(x => x.startsWith('Read(')).map(x => x.slice(5));
    const edit = deny.filter(x => x.startsWith('Edit(')).map(x => x.slice(5));
    assert.deepStrictEqual(edit.sort(), read.sort());
    assert.deepStrictEqual(deny.filter(x => !/^(Read|Edit)\(/.test(x)), []);
  });
}

if (!ok) process.exit(1);
console.log('\nAll claude-settings tests passed.');
