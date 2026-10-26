// scripts/install-hooks-merge.test.js — install.sh step 7 merges the telemetry hooks into the
// target's .claude/settings.json without clobbering: a null entry, or a null hook inside an entry,
// is kept as found and does not stop the install (review G11), and a re-run adds nothing.
// uninstall.sh, its mirror, removes our hooks past the same nulls and keeps them (review N1: it
// crashed after deleting the telemetry scripts, leaving hooks that pointed at deleted files).
// Runs the real install.sh and uninstall.sh on a temp target with HOME pointed at a temp fake
// home, so the runtime skill sync writes only temp files.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'install-hooks-test-'));
const HOME = path.join(TMP, 'home');
const PROJECT = path.join(TMP, 'project');
const SETTINGS = path.join(PROJECT, '.claude', 'settings.json');
const LOCAL = path.join(PROJECT, '.claude', 'settings.local.json');

function install(script = 'install.sh', args = [], input = 'y\n') {
  const r = spawnSync('bash', [path.join(REPO, script), ...args, PROJECT], {
    encoding: 'utf8', cwd: TMP, input, timeout: 120000,
    env: { ...process.env, HOME, USERPROFILE: HOME },
  });
  assert.ok(!r.error, `${script} failed to run: ${r.error && r.error.message}`);
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

try {
  fs.mkdirSync(HOME, { recursive: true });
  fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
  const EVENTS = ['PostToolUse', 'UserPromptSubmit', 'Stop', 'SessionEnd'];
  const invCmd = 'node "$CLAUDE_PROJECT_DIR/scripts/telemetry/log-invocation.js"';
  fs.writeFileSync(SETTINGS, JSON.stringify({ hooks: {
    ...Object.fromEntries(EVENTS.map(ev => [ev, [null]])),
    PostToolUse: [null, { matcher: 'Skill|Task', hooks: [null, { type: 'command', command: invCmd }] }],
  } }, null, 2));

  // 1. The install finishes; the three missing telemetry hooks are added past the nulls, and the
  //    existing invocation hook is found, not duplicated.
  let r = install();
  assert.strictEqual(r.status, 0, `install.sh failed on null entries:\n${r.stdout.slice(-2000)}\n${r.stderr}`);
  assert.match(r.stdout, /merged 3 telemetry hook entries into/);
  const hooks = JSON.parse(fs.readFileSync(SETTINGS, 'utf8')).hooks;
  for (const ev of EVENTS) assert.strictEqual(hooks[ev][0], null, `${ev}: the null entry is kept`);
  assert.strictEqual(hooks.PostToolUse[1].hooks[0], null, 'the null hook inside an entry is kept');
  const commands = ev => hooks[ev].filter(Boolean).flatMap(e => (e.hooks || []).filter(Boolean)).map(h => h.command);
  assert.deepStrictEqual(commands('PostToolUse'), [invCmd], 'invocation hook once');
  assert.ok(commands('UserPromptSubmit').some(c => /log-outcome\.js" --mode correction$/.test(c)), 'correction hook added');
  for (const ev of ['Stop', 'SessionEnd'])
    assert.ok(commands(ev).some(c => /log-outcome\.js" --mode session-end$/.test(c)), `${ev} session-end hook added`);

  // 2. A re-run changes nothing.
  const before = fs.readFileSync(SETTINGS, 'utf8');
  r = install();
  assert.strictEqual(r.status, 0, r.stderr);
  assert.match(r.stdout, /telemetry hook entries already present/);
  assert.strictEqual(fs.readFileSync(SETTINGS, 'utf8'), before, 'a re-run over null entries changes nothing');

  // 3. With the second brain, over null entries in settings.local.json too, then uninstall: the
  //    uninstall finishes, removes every hook we added, and keeps the nulls and the owner's hook.
  const BRAIN_EVENTS = ['PreToolUse', 'PostToolUse', 'SessionStart', 'PreCompact', 'SessionEnd', 'Stop'];
  const ownCmd = 'echo own-hook';
  fs.writeFileSync(LOCAL, JSON.stringify({ hooks: {
    ...Object.fromEntries(BRAIN_EVENTS.map(ev => [ev, [null]])),
    Stop: [null, { hooks: [null, { type: 'command', command: ownCmd }] }],
  } }, null, 2));
  r = install('install.sh', ['--with-second-brain']);
  assert.strictEqual(r.status, 0, `install --with-second-brain failed:\n${r.stdout.slice(-2000)}\n${r.stderr}`);
  assert.ok(/hooks\/brain\//.test(fs.readFileSync(LOCAL, 'utf8')), 'brain hooks registered');
  // P0-09: the guard is registered in the shared file, fail-closed; the other brain hooks stay local
  assert.ok(/brain-security-guard\.sh/.test(fs.readFileSync(SETTINGS, 'utf8')), 'guard registered in settings.json');
  assert.ok(!/brain-security-guard\.sh/.test(fs.readFileSync(LOCAL, 'utf8')), 'guard not in settings.local.json');
  r = install('uninstall.sh', [], 'y\nn\n');
  assert.strictEqual(r.status, 0, `uninstall.sh failed on null entries:\n${r.stdout.slice(-2000)}\n${r.stderr}`);
  const after = JSON.parse(fs.readFileSync(SETTINGS, 'utf8')).hooks;
  // Every telemetry hook goes, our hook in the mixed PostToolUse entry too; the null hook beside
  // it is not ours, so the entry stays with it (review N8: it used to stay whole, still running a
  // script uninstall had deleted).
  assert.ok(!/scripts\/telemetry\//.test(JSON.stringify(after)), 'telemetry hooks removed');
  assert.ok(!/hooks\/brain\//.test(JSON.stringify(after)), 'the guard registration removed from settings.json');
  assert.deepStrictEqual(after.PostToolUse, [null, { matcher: 'Skill|Task', hooks: [null] }],
    'our hook leaves the mixed entry; the nulls stay');
  for (const ev of EVENTS) assert.strictEqual(after[ev][0], null, `settings.json ${ev}: the null entry is kept`);
  const local = JSON.parse(fs.readFileSync(LOCAL, 'utf8')).hooks;
  assert.ok(!/hooks\/brain\//.test(JSON.stringify(local)), 'brain hooks removed');
  for (const ev of BRAIN_EVENTS) assert.strictEqual(local[ev][0], null, `settings.local.json ${ev}: the null entry is kept`);
  assert.deepStrictEqual(local.Stop[1], { hooks: [null, { type: 'command', command: ownCmd }] }, "the owner's hook is kept");

  console.log('install-hooks-merge.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
