// scripts/brain/brain-lint.test.js — lint warns on schema/staleness/orphans
// (exit 0, fail open) and fails with exit 3 on sensitive content anywhere.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SCRIPT = path.join(__dirname, 'brain-lint.js');
const TMP = path.join(__dirname, '__lint_test_tmp__');

function run() {
  const r = spawnSync('node', [SCRIPT, '--target', TMP], { encoding: 'utf8' });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function seed() {
  fs.rmSync(TMP, { recursive: true, force: true });
  for (const d of ['sessions/daily', 'decisions/active', 'lessons/memories', 'canon', 'synthesis', 'reports']) {
    fs.mkdirSync(path.join(TMP, d), { recursive: true });
  }
}
const GOOD = `---
type: decision
title: Good decision
description: A well-formed decision
tags: [pipeline]
timestamp: ${new Date().toISOString().slice(0, 19)}
sources: [sessions/daily/2026-07-08.md]
status: active
---

Body referencing [[good-lesson]].
`;
const GOOD_LESSON = GOOD.replace('type: decision', 'type: lesson').replace('Good decision', 'good lesson');

try {
  // 1. Clean brain → exit 0, zero findings
  seed();
  fs.writeFileSync(path.join(TMP, 'decisions', 'active', 'good-decision.md'), GOOD);
  fs.writeFileSync(path.join(TMP, 'lessons', 'memories', 'good-lesson.md'), GOOD_LESSON);
  let r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes('0 security finding(s)'), r.stdout);

  // 2. Missing frontmatter field + stale timestamp + orphan link → warnings, still exit 0
  fs.writeFileSync(path.join(TMP, 'decisions', 'active', 'bad.md'), `---
type: decision
title: No description or tags
timestamp: 2024-01-01T00:00:00
sources: []
---

Links to [[does-not-exist]].
`);
  r = run();
  assert.strictEqual(r.status, 0, 'quality issues fail open');
  assert.ok(r.stderr.includes("missing frontmatter field 'description'"), r.stderr);
  assert.ok(r.stderr.includes('stale'), r.stderr);
  assert.ok(r.stderr.includes('orphan link [[does-not-exist]]'), r.stderr);

  // 2b. Staleness looks at status and reviewed_at, not the timestamp alone
  const old = (name, extra) => {
    const dir = path.join(TMP, 'decisions', 'superseded');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${name}.md`), `---
type: decision
title: ${name}
description: An old decision
tags: []
timestamp: 2024-01-01T00:00:00
sources: []
${extra}
---

Body.
`);
  };
  const recent = new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10);
  old('old-superseded', 'status: superseded');
  old('old-retired', 'status: retired');
  old('old-reviewed-recently', `status: active\nreviewed_at: ${recent}`);
  old('old-reviewed-long-ago', 'status: active\nreviewed_at: 2024-02-01');
  old('old-bad-review-date', 'status: active\nreviewed_at: not-a-date');
  old('old-future-review-date', 'status: active\nreviewed_at: 2999-01-01');
  old('old-quoted-superseded', 'status: "superseded"');
  old('old-quoted-review-date', `status: active\nreviewed_at: "${recent}"`);
  r = run();
  assert.strictEqual(r.status, 0, 'quality issues fail open');
  const staleFor = name => r.stderr.includes(`${name}.md: stale`);
  assert.ok(!staleFor('old-superseded'), 'a superseded item is reviewed: not stale');
  assert.ok(!staleFor('old-retired'), 'a retired item is reviewed: not stale');
  assert.ok(!staleFor('old-reviewed-recently'), 'a recent reviewed_at resets the 90 days');
  assert.ok(staleFor('old-reviewed-long-ago'), 'an old reviewed_at is stale again');
  assert.ok(staleFor('old-bad-review-date'), 'an unreadable reviewed_at does not hide an old timestamp');
  assert.ok(staleFor('old-future-review-date'), 'a reviewed_at in the future (a typo) does not hide an old timestamp');
  assert.ok(!staleFor('old-quoted-superseded'), 'a quoted status is read like a bare one');
  assert.ok(!staleFor('old-quoted-review-date'), 'a quoted reviewed_at is read like a bare one');
  assert.ok(staleFor('bad'), 'an old active item with no reviewed_at is still stale');

  // 3. Planted fake token in a session log → exit 3 (spec acceptance criterion 5)
  fs.writeFileSync(path.join(TMP, 'sessions', 'daily', '2026-07-08.md'),
    '# Session log\n\n## 10:00 [note]\n\napi key sk-ant-abc123def456ghi789 leaked here\n');
  r = run();
  assert.strictEqual(r.status, 3, 'sensitive content must exit 3');
  assert.ok(r.stderr.includes('SECURITY'), r.stderr);

  // 4. Report file written with both sections
  const reportDir = path.join(TMP, 'reports', 'lint');
  const reports = fs.readdirSync(reportDir);
  assert.ok(reports.length >= 1, 'lint report written');
  const report = fs.readFileSync(path.join(reportDir, reports[0]), 'utf8');
  assert.ok(report.includes('## Security') && report.includes('## Warnings'));

  console.log('brain-lint.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
