// scripts/brain/brain-reference-repo.test.js — covers reference-lib.js plus
// brain-reference-repo-{add,audit,map,refresh}.js. Standalone, zero deps.
// Fixture: a temp copy of the real reference-repositories/ tree, addressed
// via --root so nothing under the real repo root is touched.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const TMP = path.join(__dirname, '__reference_repo_test_tmp__');
const ADD = path.join(__dirname, 'brain-reference-repo-add.js');
const AUDIT = path.join(__dirname, 'brain-reference-repo-audit.js');
const MAP = path.join(__dirname, 'brain-reference-repo-map.js');
const REFRESH = path.join(__dirname, 'brain-reference-repo-refresh.js');
const registryLib = require('./reference-lib');

function run(script, args) {
  const r = spawnSync('node', [script, ...args, '--root', TMP], { encoding: 'utf8' });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function seed() {
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.mkdirSync(TMP, { recursive: true });
  fs.cpSync(
    path.join(REPO_ROOT, 'reference-repositories'),
    path.join(TMP, 'reference-repositories'),
    { recursive: true },
  );
}
function registryPath() { return path.join(TMP, 'reference-repositories', 'registry.json'); }
function registryMdPath() { return path.join(TMP, 'reference-repositories', 'registry.md'); }
function cardPath(name) { return path.join(TMP, 'reference-repositories', 'sources', name, 'source-card.md'); }
function readRegistry() { return JSON.parse(fs.readFileSync(registryPath(), 'utf8')); }

try {
  // 0. reference-lib.js direct unit checks
  assert.deepStrictEqual(registryLib.REQUIRED_ENTRY_FIELDS,
    ['name', 'url', 'status', 'types', 'install_policy', 'last_reviewed']);
  const sampleMd = registryLib.renderRegistryMd({
    repositories: [{
      name: 'x', status: 'reference', types: ['methodology-source'],
      install_policy: 'do-not-install-directly', last_reviewed: '2026-01-01',
    }],
  });
  assert.ok(sampleMd.includes('| x | reference | methodology-source | do-not-install-directly | 2026-01-01 |'),
    'renderRegistryMd produces a table row per entry');
  assert.ok(sampleMd.startsWith('# Reference Repository Registry'), 'renderRegistryMd has a heading');

  // 1. add creates entry + card + registry.md row
  seed();
  let r = run(ADD, ['--name', 'test-repo', '--url', 'https://example.com/test-repo', '--types', 'methodology-source']);
  assert.strictEqual(r.status, 0, r.stderr);
  let registry = readRegistry();
  let entry = registry.repositories.find(e => e.name === 'test-repo');
  assert.ok(entry, 'entry added to registry.json');
  assert.strictEqual(entry.install_policy, 'do-not-install-directly', 'install_policy forced');
  assert.strictEqual(entry.status, 'reference');
  assert.ok(fs.existsSync(cardPath('test-repo')), 'source card scaffolded');
  let md = fs.readFileSync(registryMdPath(), 'utf8');
  assert.ok(md.includes('test-repo'), 'registry.md row present');

  // 2. duplicate add exits 1, --force overwrites
  r = run(ADD, ['--name', 'test-repo', '--url', 'https://example.com/test-repo', '--types', 'methodology-source']);
  assert.strictEqual(r.status, 1, 'duplicate add without --force must exit 1');
  r = run(ADD, ['--name', 'test-repo', '--url', 'https://example.com/test-repo-v2', '--types', 'methodology-source', '--force']);
  assert.strictEqual(r.status, 0, r.stderr);
  registry = readRegistry();
  entry = registry.repositories.find(e => e.name === 'test-repo');
  assert.strictEqual(entry.url, 'https://example.com/test-repo-v2', '--force overwrites entry');
  assert.strictEqual(registry.repositories.filter(e => e.name === 'test-repo').length, 1, '--force does not duplicate the entry');

  // 3. add with unknown type exits 1, entry not added
  r = run(ADD, ['--name', 'bad-types', '--url', 'https://example.com/x', '--types', 'not-a-real-type']);
  assert.strictEqual(r.status, 1, 'unknown type must exit 1');
  registry = readRegistry();
  assert.ok(!registry.repositories.find(e => e.name === 'bad-types'), 'entry not added on bad type');

  // 4. audit PASSES on the seeded gstack entry
  r = run(AUDIT, ['--name', 'gstack']);
  assert.strictEqual(r.status, 0, `gstack audit should pass: ${r.stderr}`);
  assert.ok(r.stdout.includes('0 security finding(s)'), r.stdout);

  // 5. audit exits 3 when a planted evil.sh exists under sources/gstack/ (docs-only enforcement)
  const evilFile = path.join(TMP, 'reference-repositories', 'sources', 'gstack', 'evil.sh');
  fs.writeFileSync(evilFile, '#!/bin/sh\necho pwned\n');
  r = run(AUDIT, ['--name', 'gstack']);
  assert.strictEqual(r.status, 3, 'executable under sources/ must exit 3');
  assert.ok(r.stderr.includes('SECURITY'), r.stderr);
  fs.rmSync(evilFile);
  r = run(AUDIT, ['--name', 'gstack']);
  assert.strictEqual(r.status, 0, 'audit passes again once evil.sh is removed');

  // 6. audit exits 3 on a planted sk-ant-... secret in a card
  const tempCard = path.join(TMP, 'reference-repositories', 'sources', 'gstack', 'extra-notes.md');
  fs.writeFileSync(tempCard, 'Leaked key: sk-ant-abc123def456ghi789\n');
  r = run(AUDIT, ['--name', 'gstack']);
  assert.strictEqual(r.status, 3, 'sensitive content must exit 3');
  assert.ok(r.stderr.includes('SECURITY') && r.stderr.includes('sensitive content'), r.stderr);
  fs.rmSync(tempCard);
  r = run(AUDIT, ['--name', 'gstack']);
  assert.strictEqual(r.status, 0, 'audit passes again once the secret is removed');

  // 7. map returns the three GStack pattern buckets, all non-empty
  r = run(MAP, ['--name', 'gstack', '--json']);
  assert.strictEqual(r.status, 0, r.stderr);
  const map = JSON.parse(r.stdout);
  assert.ok(Array.isArray(map.patterns) && map.patterns.length > 0, 'patterns non-empty');
  assert.ok(Array.isArray(map.candidate_skills) && map.candidate_skills.length > 0, 'candidate_skills non-empty');
  assert.ok(Array.isArray(map.candidate_agents) && map.candidate_agents.length > 0, 'candidate_agents non-empty');

  // 8. refresh bumps both dates and regenerates registry.md
  registry = readRegistry();
  const gstackEntry = registry.repositories.find(e => e.name === 'gstack');
  gstackEntry.last_reviewed = '2020-01-01';
  fs.writeFileSync(registryPath(), JSON.stringify(registry, null, 2) + '\n');
  const cardBefore = fs.readFileSync(cardPath('gstack'), 'utf8');
  fs.writeFileSync(cardPath('gstack'), cardBefore.replace(/^last_reviewed:.*$/m, 'last_reviewed: 2020-01-01'));

  r = run(REFRESH, ['--name', 'gstack']);
  assert.strictEqual(r.status, 0, r.stderr);
  const today = new Date().toISOString().slice(0, 10);
  registry = readRegistry();
  const gstackAfter = registry.repositories.find(e => e.name === 'gstack');
  assert.strictEqual(gstackAfter.last_reviewed, today, 'registry last_reviewed bumped to today');
  const cardAfter = fs.readFileSync(cardPath('gstack'), 'utf8');
  assert.ok(cardAfter.includes(`last_reviewed: ${today}`), 'source card last_reviewed bumped to today');
  md = fs.readFileSync(registryMdPath(), 'utf8');
  assert.ok(md.includes(today), 'registry.md regenerated with the new date');

  // --use / --risk: one item per flag, kept verbatim (commas are prose, not
  // separators — splitting them fragmented sentences into bogus items), and
  // each flag may repeat to add more items.
  seed();
  r = run(ADD, ['--name', 'use-risk-repo', '--url', 'https://example.com/u', '--types', 'research-source',
    '--use', 'Primary source for releases, docs, and security policy',
    '--use', 'Code at the pinned tag',
    '--risk', 'Ships weekly; pin by digest, re-audit on upgrade']);
  assert.strictEqual(r.status, 0, r.stderr);
  entry = readRegistry().repositories.find(e => e.name === 'use-risk-repo');
  assert.deepStrictEqual(entry.preferred_use,
    ['Primary source for releases, docs, and security policy', 'Code at the pinned tag'],
    'each --use is one item; commas inside it are kept');
  assert.deepStrictEqual(entry.risk_notes, ['Ships weekly; pin by digest, re-audit on upgrade'],
    'a single --risk with commas stays one item');
  r = run(ADD, ['--name', 'no-use-repo', '--url', 'https://example.com/n', '--types', 'research-source']);
  assert.strictEqual(r.status, 0, r.stderr);
  entry = readRegistry().repositories.find(e => e.name === 'no-use-repo');
  assert.deepStrictEqual([entry.preferred_use, entry.risk_notes], [[], []], 'absent flags give empty arrays');

  console.log('brain-reference-repo.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
