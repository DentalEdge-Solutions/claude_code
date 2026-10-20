// scripts/brain/brain-self-install.test.js — installs a capsule into a temp
// target, merges hooks into settings.local.json without clobbering, is
// idempotent, and passes brain-verify.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..', '..');
const SCRIPT = path.join(__dirname, 'brain-self-install.sh');
const TMP = path.join(__dirname, '__selfinstall_test_tmp__');

function run() {
  const r = spawnSync('bash', [SCRIPT, TMP], { encoding: 'utf8', cwd: REPO });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

try {
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.mkdirSync(path.join(TMP, '.claude'), { recursive: true });
  // Pre-existing hook that must survive the merge untouched
  fs.writeFileSync(path.join(TMP, '.claude', 'settings.local.json'), JSON.stringify({
    hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'echo preexisting' }] }] },
  }, null, 2));
  fs.writeFileSync(path.join(TMP, '.gitignore'), 'node_modules/\n');

  // 1. Install succeeds; capsule verifies; placeholders filled
  let r = run();
  assert.strictEqual(r.status, 0, `install failed:\n${r.stdout}\n${r.stderr}`);
  const brain = path.join(TMP, '.project-brain');
  const verify = spawnSync('node', [path.join(__dirname, 'brain-verify.js'), '--target', brain], { encoding: 'utf8' });
  assert.strictEqual(verify.status, 0, verify.stderr);
  const brainMd = fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8');
  assert.ok(!brainMd.includes('{{PROJECT_NAME}}'), 'placeholders filled');
  const profile = JSON.parse(fs.readFileSync(path.join(brain, 'context', 'brain-profile.json'), 'utf8'));
  assert.strictEqual(profile.project_name, path.basename(TMP));
  assert.ok(/^\d{4}-\d{2}-\d{2}/.test(profile.created_at));

  // 2. Hooks merged: 5 brain registrations present, pre-existing hook intact
  const settings = JSON.parse(fs.readFileSync(path.join(TMP, '.claude', 'settings.local.json'), 'utf8'));
  const flat = JSON.stringify(settings.hooks);
  for (const h of ['brain-pre-compact.sh', 'brain-session-end.sh', 'brain-security-guard.sh', 'brain-post-lint.sh', 'brain-load.sh']) {
    assert.ok(flat.includes(h), `${h} registered`);
  }
  assert.ok(flat.includes('echo preexisting'), 'pre-existing hook survived');
  assert.ok(Array.isArray(settings.hooks.Stop) && Array.isArray(settings.hooks.SessionEnd),
    'session-end script registered on both SessionEnd and Stop');
  // The guard has an explicit 30 s timeout. Claude Code's default is 600 s, and a PreToolUse hook
  // that times out does not block the call, so a stalled guard froze each call for 10 minutes and
  // then let it through unchecked (triage F1).
  const guardHooks = list => list.flatMap(e => e.hooks || []).filter(h => /brain-security-guard\.sh/.test(h.command || ''));
  assert.deepStrictEqual(guardHooks(settings.hooks.PreToolUse).map(h => h.timeout), [30], 'guard registered once, with timeout 30');

  // 3. .gitignore gained the sessions line exactly once
  const gi = fs.readFileSync(path.join(TMP, '.gitignore'), 'utf8');
  assert.strictEqual((gi.match(/^\.project-brain\/sessions\/$/gm) || []).length, 1);

  // 4. Idempotent: re-run changes nothing
  const settingsBefore = fs.readFileSync(path.join(TMP, '.claude', 'settings.local.json'), 'utf8');
  const brainMdBefore = fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8');
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.strictEqual(fs.readFileSync(path.join(TMP, '.claude', 'settings.local.json'), 'utf8'), settingsBefore);
  assert.strictEqual(fs.readFileSync(path.join(brain, 'BRAIN.md'), 'utf8'), brainMdBefore);
  assert.strictEqual((fs.readFileSync(path.join(TMP, '.gitignore'), 'utf8').match(/\.project-brain\/sessions\//g) || []).length, 1);

  // 5. An install from before the timeout gains it on re-run, without a second guard entry;
  //    a timeout the owner set is kept.
  const settingsFile = path.join(TMP, '.claude', 'settings.local.json');
  const guardCmd = 'bash "$CLAUDE_PROJECT_DIR/hooks/brain/brain-security-guard.sh"';
  const withGuard = hook => JSON.stringify({ hooks: { PreToolUse: [
    { matcher: 'Write|Edit|NotebookEdit|Bash', hooks: [hook] }] } }, null, 2);
  fs.writeFileSync(settingsFile, withGuard({ type: 'command', command: guardCmd }));
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  let pre = JSON.parse(fs.readFileSync(settingsFile, 'utf8')).hooks.PreToolUse;
  assert.deepStrictEqual(guardHooks(pre).map(h => h.timeout), [30], 'old guard entry gained timeout 30, no duplicate');
  fs.writeFileSync(settingsFile, withGuard({ type: 'command', command: guardCmd, timeout: 45 }));
  r = run();
  assert.strictEqual(r.status, 0, r.stderr);
  pre = JSON.parse(fs.readFileSync(settingsFile, 'utf8')).hooks.PreToolUse;
  assert.deepStrictEqual(guardHooks(pre).map(h => h.timeout), [45], 'an owner-set timeout is kept');

  console.log('brain-self-install.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
