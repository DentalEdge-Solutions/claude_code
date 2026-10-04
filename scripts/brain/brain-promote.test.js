// scripts/brain/brain-promote.test.js — promote hard-fails without --approve
// (writing NOTHING), moves candidates to active/ or canon/ with updated
// frontmatter + log entry, refuses overwrite without --force and sensitive content.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SCRIPT = path.join(__dirname, 'brain-promote.js');
const LIB = require('./brain-lib');
const TMP = path.join(__dirname, '__promote_test_tmp__');
const CAND = 'decisions/candidates/2026-07-08-use-pipeline.md';

function run(args) {
  const r = spawnSync('node', [SCRIPT, '--target', TMP, ...args], { encoding: 'utf8' });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function snapshot(dir) {
  const out = {};
  for (const f of LIB.walkMarkdown(path.join(TMP, dir))) out[f] = fs.readFileSync(f, 'utf8');
  return JSON.stringify(out);
}
function seed() {
  fs.rmSync(TMP, { recursive: true, force: true });
  for (const d of ['decisions/candidates', 'decisions/active', 'canon']) {
    fs.mkdirSync(path.join(TMP, d), { recursive: true });
  }
  fs.writeFileSync(path.join(TMP, 'log.md'), '# Brain Log\n');
  fs.writeFileSync(path.join(TMP, CAND), LIB.serializeFrontmatter({
    type: 'decision', title: 'Use pipeline', description: 'd', tags: [],
    timestamp: '2026-07-08T10:05:00', sources: ['sessions/daily/2026-07-08.md'],
    status: 'candidate',
  }, 'We default to pipeline().\n'));
}

try {
  // 1. Without --approve → exit 2, capsule byte-identical (acceptance criterion 3)
  seed();
  const before = snapshot('.');
  let r = run([CAND]);
  assert.strictEqual(r.status, 2, `must exit 2 without --approve:\n${r.stderr}`);
  assert.ok(r.stderr.includes('--approve'), 'refusal names the missing flag');
  assert.strictEqual(snapshot('.'), before, 'NOTHING written on refusal');

  // 2. With --approve → moved to decisions/active/, status+promoted_at set, logged
  r = run([CAND, '--approve']);
  assert.strictEqual(r.status, 0, r.stderr);
  const dest = path.join(TMP, 'decisions', 'active', '2026-07-08-use-pipeline.md');
  assert.ok(fs.existsSync(dest), 'moved to active');
  assert.ok(!fs.existsSync(path.join(TMP, CAND)), 'removed from candidates');
  const { fields } = LIB.parseFrontmatter(fs.readFileSync(dest, 'utf8'));
  assert.strictEqual(fields.status, 'active');
  assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(fields.promoted_at));
  assert.ok(fs.readFileSync(path.join(TMP, 'log.md'), 'utf8').includes('promoted decisions/candidates/2026-07-08-use-pipeline.md'));

  // 3. --to canon → lands in canon/ with status: canon
  seed();
  r = run([CAND, '--approve', '--to', 'canon']);
  assert.strictEqual(r.status, 0, r.stderr);
  const canonDest = path.join(TMP, 'canon', '2026-07-08-use-pipeline.md');
  assert.strictEqual(LIB.parseFrontmatter(fs.readFileSync(canonDest, 'utf8')).fields.status, 'canon');

  // 4. Destination exists → exit 1 without --force; succeeds with --force
  seed();
  fs.writeFileSync(path.join(TMP, 'decisions', 'active', '2026-07-08-use-pipeline.md'), 'existing\n');
  r = run([CAND, '--approve']);
  assert.strictEqual(r.status, 1, 'overwrite refused without --force');
  assert.ok(fs.existsSync(path.join(TMP, CAND)), 'candidate not consumed on refusal');
  r = run([CAND, '--approve', '--force']);
  assert.strictEqual(r.status, 0, r.stderr);

  // 5. Sensitive content in candidate → exit 3, not promoted
  seed();
  fs.appendFileSync(path.join(TMP, CAND), '\nkey: sk-ant-abc123def456ghi789\n');
  r = run([CAND, '--approve']);
  assert.strictEqual(r.status, 3, 'sensitive candidate must exit 3');
  assert.ok(fs.existsSync(path.join(TMP, CAND)), 'candidate stays put');

  // 6. Usage errors → exit 1: no file given; bad --to; missing file
  seed();
  assert.strictEqual(run(['--approve']).status, 1);
  assert.strictEqual(run([CAND, '--approve', '--to', 'superseded']).status, 1);
  assert.strictEqual(run(['decisions/candidates/nope.md', '--approve']).status, 1);

  // 7. Path traversal ('../') → exit 1, outside file untouched, capsule untouched
  seed();
  const outside = path.join(path.dirname(TMP), '__promote_outside_probe__.md');
  fs.writeFileSync(outside, 'secret outside content\n');
  try {
    const beforeOutside = fs.readFileSync(outside, 'utf8');
    const beforeCapsule = snapshot('.');
    r = run(['../' + path.basename(outside), '--approve', '--to', 'canon']);
    assert.strictEqual(r.status, 1, `path traversal must exit 1:\n${r.stderr}`);
    assert.ok(r.stderr.includes('escapes the capsule'), 'refusal names the traversal');
    assert.strictEqual(fs.readFileSync(outside, 'utf8'), beforeOutside, 'outside file untouched');
    assert.strictEqual(snapshot('.'), beforeCapsule, 'capsule untouched by traversal attempt');
  } finally {
    fs.rmSync(outside, { force: true });
  }

  // 8. Absolute-path arg → exit 1, refused before any filesystem access
  seed();
  const absOutside = path.join(path.dirname(TMP), '__promote_abs_probe__.md');
  fs.writeFileSync(absOutside, 'abs secret\n');
  try {
    const beforeAbs = fs.readFileSync(absOutside, 'utf8');
    r = run([absOutside, '--approve', '--to', 'canon']);
    assert.strictEqual(r.status, 1, `absolute path must exit 1:\n${r.stderr}`);
    assert.ok(r.stderr.includes('escapes the capsule'), 'refusal names the traversal');
    assert.ok(fs.existsSync(absOutside), 'absolute-path target untouched');
    assert.strictEqual(fs.readFileSync(absOutside, 'utf8'), beforeAbs, 'absolute-path target byte-identical');
  } finally {
    fs.rmSync(absOutside, { force: true });
  }

  // 9. Block-list sources (incl. an item with a comma) survive promotion
  seed();
  const srcs = ['.project-brain/canon/2026-07-17-ai-os-charter.md', 'Session discussion 2026-07-17 (Opus): local-first, vs VPS-first'];
  fs.writeFileSync(path.join(TMP, CAND), LIB.serializeFrontmatter({
    type: 'decision', title: 'Use pipeline', description: 'd', tags: [],
    timestamp: '2026-07-08T10:05:00', sources: srcs, status: 'candidate',
  }, 'We default to pipeline().\n'));
  r = run([CAND, '--approve', '--to', 'canon']);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.deepStrictEqual(
    LIB.parseFrontmatter(fs.readFileSync(path.join(TMP, 'canon', '2026-07-08-use-pipeline.md'), 'utf8')).fields.sources, srcs);
  // and a hand-written block-list candidate (the real-world shape)
  seed();
  fs.writeFileSync(path.join(TMP, CAND), '---\ntype: decision\ntitle: T\nsources:\n  - .project-brain/canon/x.md\n  - "Session: y"\nstatus: candidate\n---\n\nBody\n');
  r = run([CAND, '--approve']);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.deepStrictEqual(
    LIB.parseFrontmatter(fs.readFileSync(path.join(TMP, 'decisions', 'active', '2026-07-08-use-pipeline.md'), 'utf8')).fields.sources,
    ['.project-brain/canon/x.md', 'Session: y']);

  console.log('brain-promote.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
