// scripts/brain/brain-compile.test.js — compile extracts decision/lesson entries
// into candidate files with required frontmatter; notes are ignored; re-runs
// skip existing candidates; active/ and canon/ are never touched.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SCRIPT = path.join(__dirname, 'brain-compile.js');
const LIB = require('./brain-lib');
const TMP = path.join(__dirname, '__compile_test_tmp__');

function run(args) {
  const r = spawnSync('node', [SCRIPT, '--target', TMP, ...args], { encoding: 'utf8' });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

try {
  fs.rmSync(TMP, { recursive: true, force: true });
  for (const d of ['sessions/daily', 'decisions/candidates', 'decisions/active', 'lessons/memories', 'canon', 'reports']) {
    fs.mkdirSync(path.join(TMP, d), { recursive: true });
  }
  const date = '2026-07-08';
  fs.writeFileSync(path.join(TMP, 'sessions', 'daily', `${date}.md`), `# Session log — ${date}

## 10:00 [note]

Just a passing observation.

## 10:05 [decision] Use pipeline by default

We default to pipeline() over parallel() barriers.

## 11:30 [lesson]

Always run brain-verify before claiming install success.
`);

  // 1. Compile writes one decision candidate + one lesson, skips the note
  let r = run(['--date', date]);
  assert.strictEqual(r.status, 0, r.stderr);
  const dec = path.join(TMP, 'decisions', 'candidates', `${date}-use-pipeline-by-default.md`);
  assert.ok(fs.existsSync(dec), 'decision candidate written with date-slug name');
  const lessons = fs.readdirSync(path.join(TMP, 'lessons', 'memories')).filter(f => f.endsWith('.md'));
  assert.strictEqual(lessons.length, 1, 'exactly one lesson candidate');
  assert.strictEqual(fs.readdirSync(path.join(TMP, 'decisions', 'candidates')).filter(f => f.endsWith('.md')).length, 1, 'note was not compiled');

  // 2. Candidate has required frontmatter (spec delta 5) + status: candidate
  const { fields, body } = LIB.parseFrontmatter(fs.readFileSync(dec, 'utf8'));
  for (const f of ['type', 'title', 'description', 'tags', 'timestamp', 'sources']) {
    assert.ok(f in fields, `frontmatter has '${f}'`);
  }
  assert.strictEqual(fields.type, 'decision');
  assert.strictEqual(fields.status, 'candidate');
  assert.deepStrictEqual(fields.sources, [`sessions/daily/${date}.md`]);
  assert.ok(body.includes('pipeline() over parallel()'));

  // 3. Governance: nothing in active/ or canon/
  assert.strictEqual(fs.readdirSync(path.join(TMP, 'decisions', 'active')).length, 0);
  assert.strictEqual(fs.readdirSync(path.join(TMP, 'canon')).length, 0);

  // 4. Re-run without --force skips; with --force rewrites
  r = run(['--date', date]);
  assert.strictEqual(r.status, 0);
  assert.ok(r.stdout.includes('0 candidate(s) written'), `re-run skips: ${r.stdout}`);
  r = run(['--date', date, '--force']);
  assert.ok(r.stdout.includes('2 candidate(s) written'), `--force rewrites: ${r.stdout}`);

  // 5. Report written (fail-open contract: presence checked, content minimal)
  const reports = path.join(TMP, 'reports', 'compile');
  assert.ok(fs.existsSync(reports) && fs.readdirSync(reports).length >= 1, 'compile report written');

  // 6. Missing session file for date → exit 0, zero written (fail open)
  r = run(['--date', '2001-01-01']);
  assert.strictEqual(r.status, 0);
  assert.ok(r.stdout.includes('0 candidate(s) written'));

  // 7. --date path traversal → exit 1, refused before touching the filesystem
  r = run(['--date', '../../x']);
  assert.strictEqual(r.status, 1, `traversal --date must exit 1:\n${r.stderr}`);
  assert.ok(r.stderr.includes('YYYY-MM-DD'), 'refusal names the format requirement');

  // 8. Already-promoted entries are never recreated (with or without --force)
  const candName = `${date}-use-pipeline-by-default.md`;
  const lessonName = lessons[0];
  const candDir = path.join(TMP, 'decisions', 'candidates');
  const lessonDir = path.join(TMP, 'lessons', 'memories');
  const clean = () => {
    for (const d of [candDir, lessonDir, path.join(TMP, 'decisions', 'active'), path.join(TMP, 'canon')]) {
      for (const f of fs.readdirSync(d)) fs.rmSync(path.join(d, f));
    }
  };
  const report = () => {
    const dir = path.join(TMP, 'reports', 'compile');
    return JSON.parse(fs.readFileSync(path.join(dir, fs.readdirSync(dir).sort().pop()), 'utf8'));
  };
  const promoted = [
    ['decision -> canon', candDir, candName, 'canon', 'use-pipeline'],
    ['decision -> active', candDir, candName, path.join('decisions', 'active'), 'use-pipeline'],
    ['lesson -> canon', lessonDir, lessonName, 'canon', 'lesson'],
  ];
  for (const [label, srcDir, name, destRel] of promoted) {
    for (const extra of [[], ['--force']]) {
      clean();
      r = run(['--date', date]);
      fs.renameSync(path.join(srcDir, name), path.join(TMP, destRel, name));
      r = run(['--date', date, ...extra]);
      assert.strictEqual(r.status, 0, r.stderr);
      assert.ok(!fs.existsSync(path.join(srcDir, name)), `${label} ${extra}: not recreated`);
      assert.ok(r.stdout.includes('1 already promoted'), `${label} ${extra}: console: ${r.stdout}`);
      const rep = report();
      assert.strictEqual(rep.already_promoted, 1, `${label} ${extra}: report.already_promoted`);
      assert.ok(!rep.outputs.some(o => path.basename(o) === name), `${label} ${extra}: promoted entry not in outputs`);
    }
  }
  // the other entry is still handled normally alongside a promoted one
  clean();
  run(['--date', date]);
  fs.renameSync(path.join(candDir, candName), path.join(TMP, 'canon', candName));
  r = run(['--date', date]);
  assert.ok(r.stdout.includes('0 candidate(s) written, 1 skipped, 1 already promoted'), r.stdout);

  console.log('brain-compile.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
