// scripts/brain/brain-lib.test.js — unit tests for shared brain-kernel helpers.
'use strict';
const assert = require('assert');
const lib = require('./brain-lib');

// frontmatter round-trip
{
  const fm = lib.serializeFrontmatter(
    { type: 'decision', title: 'Use X', tags: ['a', 'b'], timestamp: '2026-07-08T10:00:00' },
    'Body line 1\n');
  const { fields, body } = lib.parseFrontmatter(fm);
  assert.strictEqual(fields.type, 'decision');
  assert.strictEqual(fields.title, 'Use X');
  assert.deepStrictEqual(fields.tags, ['a', 'b']);
  assert.ok(body.startsWith('Body line 1'));
}
// no frontmatter → fields null, body intact
{
  const { fields, body } = lib.parseFrontmatter('# Just a doc\n');
  assert.strictEqual(fields, null);
  assert.strictEqual(body, '# Just a doc\n');
}
// sensitive scanner catches planted secrets, passes clean text
{
  assert.ok(lib.scanSensitive('key is sk-ant-abc123def456ghi789').length >= 1);
  assert.ok(lib.scanSensitive('-----BEGIN RSA PRIVATE KEY-----').length >= 1);
  assert.ok(lib.scanSensitive('password = hunter22').length >= 1);
  assert.deepStrictEqual(lib.scanSensitive('we decided to use pipeline() here'), []);
}
// args
{
  const argv = ['node', 's.js', 'decisions/candidates/x.md', '--to', 'canon', '--approve', '--target', '/tmp/b'];
  assert.strictEqual(lib.getArg(argv, '--to'), 'canon');
  assert.ok(lib.hasFlag(argv, '--approve'));
  assert.deepStrictEqual(lib.positional(argv), ['decisions/candidates/x.md']);
  assert.ok(lib.resolveTarget(argv).endsWith('/tmp/b') || lib.resolveTarget(argv) === '/tmp/b');
}
// stamps are UTC-shaped; slugify
{
  const d = new Date('2026-07-08T14:03:00Z');
  assert.strictEqual(lib.todayStamp(d), '2026-07-08');
  assert.strictEqual(lib.timeStamp(d), '14:03');
  assert.strictEqual(lib.slugify('Use FTS5, not grep!'), 'use-fts5-not-grep');
}
// resolveCapsuleRelative: inside the capsule resolves; '../' escapes and
// absolute-path args are both rejected with null (path-traversal containment).
{
  const path = require('path');
  const target = '/tmp/brain-capsule-test';
  assert.strictEqual(
    lib.resolveCapsuleRelative(target, 'decisions/candidates/x.md'),
    path.resolve(target, 'decisions/candidates/x.md'),
  );
  assert.strictEqual(lib.resolveCapsuleRelative(target, '../outside.md'), null);
  assert.strictEqual(lib.resolveCapsuleRelative(target, '../../etc/passwd'), null);
  assert.strictEqual(lib.resolveCapsuleRelative(target, '/etc/passwd'), null);
}
// block lists: parse from text, quoting, empty key stays '', and round trips
{
  const text = '---\nsources:\n  - .project-brain/canon/a.md\n  - "Session 2026-07-17 (Opus): local-first, VPS"\n  - \'single q\'\nstatus: x\nempty:\nnext: y\n---\n\nB\n';
  const { fields, body } = lib.parseFrontmatter(text);
  assert.deepStrictEqual(fields.sources, ['.project-brain/canon/a.md', 'Session 2026-07-17 (Opus): local-first, VPS', 'single q']);
  assert.strictEqual(fields.status, 'x');
  assert.strictEqual(fields.empty, '', 'key with no value and no list stays empty string');
  assert.strictEqual(fields.next, 'y');
  assert.strictEqual(body, 'B\n');

  const cases = [
    ['comma', ['a, b', 'c']],
    ['colon-space', ['note: thing', 'plain']],
    ['quoted', ['"already quoted"', 'x']],
    ['hash', ['a # b']],
    ['brackets', ['[x]']],
    ['edge-space', [' lead', 'trail ']],
    ['backslash-quote', ['say "hi" \\ there, ok']],
  ];
  for (const [name, items] of cases) {
    const fm = { type: 'decision', sources: items, status: 'candidate' };
    const out = lib.serializeFrontmatter(fm, 'Body\n');
    assert.ok(out.includes('sources:\n  - '), `${name}: written as block list`);
    const back = lib.parseFrontmatter(out);
    assert.deepStrictEqual(back.fields, fm, `${name}: round trip fields`);
    assert.strictEqual(back.body, 'Body\n', `${name}: round trip body`);
  }
  // plain items keep the byte-identical inline form; empty array stays []
  assert.strictEqual(lib.serializeFrontmatter({ tags: ['a', 'b'], s: [] }, 'x\n'), '---\ntags: [a, b]\ns: []\n---\n\nx\n');
}
console.log('brain-lib.test.js: all assertions passed');
