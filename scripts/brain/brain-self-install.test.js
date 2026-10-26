// scripts/brain/brain-self-install.test.js — installs a capsule into a temp
// target, merges hooks without clobbering, is idempotent, and passes brain-verify.
// P0-09: the security guard is registered in the target's shared .claude/settings.json in exec
// form with onFailure "block" and a 30 s timeout (a guard that cannot start, fails or times out
// blocks the call); the five other brain hooks stay in .claude/settings.local.json; the old
// shell-form, fail-open guard registration is removed from settings.local.json.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..', '..');
const SCRIPT = path.join(__dirname, 'brain-self-install.sh');
const TMP = path.join(__dirname, '__selfinstall_test_tmp__');
const LOCAL = path.join(TMP, '.claude', 'settings.local.json');
const SHARED = path.join(TMP, '.claude', 'settings.json');

function run() {
  const r = spawnSync('bash', [SCRIPT, TMP], { encoding: 'utf8', cwd: REPO });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const MATCHER = 'Write|Edit|NotebookEdit|Bash';
const GUARD = {
  type: 'command', command: 'bash', args: ['${CLAUDE_PROJECT_DIR}/hooks/brain/brain-security-guard.sh'],
  timeout: 30, onFailure: 'block',
};
const OLD_GUARD_CMD = 'bash "$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh"';
const isGuard = h => h && (/brain-security-guard\.sh/.test(h.command || '')
  || (Array.isArray(h.args) && h.args.some(a => /brain-security-guard\.sh/.test(a))));
const guardHooks = list => (list || []).filter(Boolean).flatMap(e => (e.hooks || []).filter(Boolean)).filter(isGuard);

try {
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.mkdirSync(path.join(TMP, '.claude'), { recursive: true });
  // Pre-existing hooks that must survive the merge untouched, in both files
  fs.writeFileSync(LOCAL, JSON.stringify({
    hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'echo preexisting' }] }] },
  }, null, 2));
  const sharedOwn = { permissions: { deny: ['Read(**/.env)'] },
    hooks: { Stop: [{ hooks: [{ type: 'command', command: 'echo shared-own' }] }] } };
  fs.writeFileSync(SHARED, JSON.stringify(sharedOwn, null, 2) + '\n');
  fs.writeFileSync(path.join(TMP, '.gitignore'), 'node_modules/\n');

  // 1. Install succeeds; capsule verifies; placeholders filled
  let r = run();
  assert.strictEqual(r.status, 0, `install failed:\n${r.stdout}\n${r.stderr}`);
  // six registrations, each counted once: five local hooks and the guard in settings.json
  assert.match(r.stdout, /hook entries merged \(6 added or updated\)/);
  const brain = path.join(TMP, '.project-brain');
  const verify = spawnSync('node', [path.join(__dirname, 'brain-verify.js'), '--target', brain], { encoding: 'utf8' });
  assert.strictEqual(verify.status, 0, verify.stderr);
  const brainMd = fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8');
  assert.ok(!brainMd.includes('{{PROJECT_NAME}}'), 'placeholders filled');
  const profile = JSON.parse(fs.readFileSync(path.join(brain, 'context', 'brain-profile.json'), 'utf8'));
  assert.strictEqual(profile.project_name, path.basename(TMP));
  assert.ok(/^\d{4}-\d{2}-\d{2}/.test(profile.created_at));

  // 2. Five brain hooks in settings.local.json, the guard only in settings.json; owner hooks intact
  const local = json(LOCAL);
  const flat = JSON.stringify(local.hooks);
  for (const h of ['brain-pre-compact.sh', 'brain-session-end.sh', 'brain-post-lint.sh', 'brain-load.sh']) {
    assert.ok(flat.includes(h), `${h} registered`);
  }
  assert.ok(!flat.includes('brain-security-guard.sh'), 'the guard is not in settings.local.json');
  assert.ok(flat.includes('echo preexisting'), 'pre-existing local hook survived');
  assert.ok(Array.isArray(local.hooks.Stop) && Array.isArray(local.hooks.SessionEnd),
    'session-end script registered on both SessionEnd and Stop');
  const brainHooks = Object.values(local.hooks).flat().flatMap(e => e.hooks || [])
    .filter(h => /hooks\/brain\//.test(h.command || ''));
  assert.strictEqual(brainHooks.length, 5, 'five brain hook registrations in settings.local.json');
  assert.ok(brainHooks.every(h => !('timeout' in h) && !('onFailure' in h)),
    'no other brain hook gets a timeout or onFailure: they stay fail-open (review G5)');
  const shared = json(SHARED);
  assert.deepStrictEqual(shared.permissions, sharedOwn.permissions, 'shared permissions kept');
  assert.deepStrictEqual(shared.hooks.Stop, sharedOwn.hooks.Stop, 'shared owner hook kept');
  assert.deepStrictEqual(shared.hooks.PreToolUse, [{ matcher: MATCHER, hooks: [GUARD] }],
    'guard registered once in settings.json: exec form, timeout 30, onFailure block');

  // 3. .gitignore gained the sessions line exactly once
  const gi = fs.readFileSync(path.join(TMP, '.gitignore'), 'utf8');
  assert.strictEqual((gi.match(/^\.project-brain\/sessions\/$/gm) || []).length, 1);

  // 4. Idempotent: re-run changes nothing in either file
  const localBefore = fs.readFileSync(LOCAL, 'utf8');
  const sharedBefore = fs.readFileSync(SHARED, 'utf8');
  const brainMdBefore = fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8');
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.match(r.stdout, /hook entries merged \(0 added or updated\)/);
  assert.strictEqual(fs.readFileSync(LOCAL, 'utf8'), localBefore);
  assert.strictEqual(fs.readFileSync(SHARED, 'utf8'), sharedBefore);
  assert.strictEqual(fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8'), brainMdBefore);
  assert.strictEqual((fs.readFileSync(path.join(TMP, '.gitignore'), 'utf8').match(/\.project-brain\/sessions\//g) || []).length, 1);

  // 5. Migration: an install from before P0-09 has the shell-form guard in settings.local.json.
  //    A re-run removes every copy of it there (any matcher, any timeout), keeps an owner hook
  //    that shares its entry, and registers the exec-form guard in settings.json.
  const old = { type: 'command', command: OLD_GUARD_CMD, timeout: 30 };
  fs.writeFileSync(LOCAL, JSON.stringify({ hooks: { PreToolUse: [
    { matcher: MATCHER, hooks: [old] },
    { matcher: 'Bash', hooks: [{ type: 'command', command: 'echo own-pre' }, { type: 'command', command: OLD_GUARD_CMD }] },
  ] } }, null, 2));
  fs.rmSync(SHARED);
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.match(r.stdout, /hook entries merged \(6 added or updated\)/);
  assert.match(r.stdout, /removed 2 old fail-open guard registrations from .*settings\.local\.json/);
  assert.deepStrictEqual(json(LOCAL).hooks.PreToolUse, [{ matcher: 'Bash', hooks: [{ type: 'command', command: 'echo own-pre' }] }],
    'old guard copies gone; the owner hook in the same entry kept');
  assert.deepStrictEqual(guardHooks(json(SHARED).hooks.PreToolUse), [GUARD], 'the new guard is in settings.json');

  // 6. An existing exec-form guard without timeout or onFailure gains both; a value the owner set
  //    is kept (an explicit "continue" is the owner's documented choice); no duplicate is added.
  const bare = { type: 'command', command: 'bash', args: GUARD.args };
  fs.writeFileSync(SHARED, JSON.stringify({ hooks: { PreToolUse: [
    { matcher: MATCHER, hooks: [bare] }, { matcher: 'Bash', hooks: [{ ...bare }] }] } }, null, 2));
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.match(r.stdout, /hook entries merged \(2 added or updated\)/, 'two copies updated, none added');
  assert.deepStrictEqual(guardHooks(json(SHARED).hooks.PreToolUse), [GUARD, GUARD], 'every copy gained timeout and onFailure');
  fs.writeFileSync(SHARED, JSON.stringify({ hooks: { PreToolUse: [
    { matcher: MATCHER, hooks: [{ ...bare, timeout: 45, onFailure: 'continue' }] }] } }, null, 2));
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.deepStrictEqual(guardHooks(json(SHARED).hooks.PreToolUse), [{ ...bare, timeout: 45, onFailure: 'continue' }],
    'owner-set timeout and onFailure kept');

  // 7. A null entry, or a null hook inside an entry, in any list the installer writes to is kept
  //    as found and does not stop the install (review G11), in both files.
  const EVENTS = ['PreToolUse', 'PostToolUse', 'SessionStart', 'PreCompact', 'SessionEnd', 'Stop'];
  fs.writeFileSync(LOCAL, JSON.stringify({ hooks: {
    ...Object.fromEntries(EVENTS.map(ev => [ev, [null]])),
    PreToolUse: [null, { matcher: MATCHER, hooks: [null, { type: 'command', command: OLD_GUARD_CMD }] }],
  } }, null, 2));
  fs.writeFileSync(SHARED, JSON.stringify({ hooks: {
    PreToolUse: [null, { matcher: MATCHER, hooks: [null, { ...GUARD }] }],
  } }, null, 2));
  r = run();
  assert.strictEqual(r.status, 0, `install failed on null entries:\n${r.stdout}\n${r.stderr}`);
  // 5 other hooks added; the guard is found past the nulls; the old local copy removed
  assert.match(r.stdout, /hook entries merged \(5 added or updated\)/);
  assert.match(r.stdout, /removed 1 old fail-open guard registration from /);
  let hooks = json(LOCAL).hooks;
  for (const ev of EVENTS) assert.strictEqual(hooks[ev][0], null, `${ev}: the null entry is kept`);
  assert.deepStrictEqual(hooks.PreToolUse[1], { matcher: MATCHER, hooks: [null] }, 'the null hook beside the old guard is kept');
  const sh = json(SHARED).hooks;
  assert.strictEqual(sh.PreToolUse[0], null, 'settings.json null entry kept');
  assert.deepStrictEqual(sh.PreToolUse[1].hooks, [null, GUARD], 'one guard, past a null hook');
  const beforeLocal = fs.readFileSync(LOCAL, 'utf8');
  const beforeShared = fs.readFileSync(SHARED, 'utf8');
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.strictEqual(fs.readFileSync(LOCAL, 'utf8'), beforeLocal, 'a re-run over null entries changes nothing (local)');
  assert.strictEqual(fs.readFileSync(SHARED, 'utf8'), beforeShared, 'a re-run over null entries changes nothing (shared)');

  // 8. The guard path the registration names resolves inside the target (install.sh copies
  //    hooks/brain there): with onFailure "block", a path that does not resolve blocks every call.
  const resolved = GUARD.args[0].replace('${CLAUDE_PROJECT_DIR}', REPO);
  assert.ok(fs.existsSync(resolved), `the registered guard path resolves: ${resolved}`);

  console.log('brain-self-install.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
