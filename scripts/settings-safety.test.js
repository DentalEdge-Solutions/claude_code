// scripts/settings-safety.test.js — install and uninstall never damage a Claude Code settings file
// they cannot read, and uninstall removes only our hooks (triage G11 follow-ups N2, N3, N8, N10).
//   - A file that does not parse, is not a JSON object, has a "hooks" that is not an object, or
//     has a list for one of our events that is not a list is left byte for byte as it was:
//     brain-self-install.sh stops with an error (the guard hook is its job), install.sh's
//     telemetry step warns and the install goes on, uninstall.sh warns. Before, the installers
//     replaced an unparseable file with only our hooks (N2) and wrote nothing for array-shaped
//     settings while reporting hooks added (N3). An empty file still counts as {}.
//   - uninstall removes our hooks from an entry and keeps the owner's hooks in it; it drops an
//     entry only when every hook in it was ours. Before, the telemetry step kept a mixed entry
//     whole, still running a script it had deleted (N8), and the brain step deleted it whole,
//     the owner's hook included (N10).
// Runs the real scripts on temp targets with HOME pointed at a temp fake home.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'settings-safety-test-'));
const HOME = path.join(TMP, 'home');

function target(name, files) {
  const dir = path.join(TMP, name);
  for (const [rel, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(dir, rel), text);
  }
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
function run(script, args, input = '') {
  const r = spawnSync('bash', [path.join(REPO, script), ...args], {
    encoding: 'utf8', cwd: TMP, input, timeout: 120000, env: { ...process.env, HOME, USERPROFILE: HOME },
  });
  assert.ok(!r.error, `${script} failed to run: ${r.error && r.error.message}`);
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
const read = (dir, rel) => fs.readFileSync(path.join(dir, rel), 'utf8');
const json = (dir, rel) => JSON.parse(read(dir, rel));
const tail = s => s.slice(-1500);

const LOCAL = '.claude/settings.local.json';
const SHARED = '.claude/settings.json';
const BAD = [
  ['does not parse (trailing comma)', '{"hooks": {},}\n'],
  ['is a JSON array', '[]\n'],
  ['is JSON null', 'null\n'],
  ['has a "hooks" list', '{"hooks": []}\n'],
  ['has a "hooks" string', '{"hooks": "x"}\n'],
  ['has an object for Stop, one of our events', '{"hooks": {"Stop": {"hooks": []}}}\n'],
];

try {
  fs.mkdirSync(HOME, { recursive: true });

  // 1. brain-self-install.sh stops, names the file, and leaves it byte for byte.
  BAD.forEach(([why, text], i) => {
    const t = target(`brain-bad-${i}`, { [LOCAL]: text });
    const r = run('scripts/brain/brain-self-install.sh', [t]);
    assert.notStrictEqual(r.status, 0, `brain install, settings ${why}: must fail\n${tail(r.out)}`);
    assert.match(r.out, /settings\.local\.json was not changed/, `brain install, settings ${why}: names the file`);
    assert.strictEqual(read(t, LOCAL), text, `brain install, settings ${why}: file unchanged`);
  });

  // 2. install.sh warns, leaves settings.json byte for byte, and finishes the install.
  BAD.forEach(([why, text], i) => {
    const t = target(`install-bad-${i}`, { [SHARED]: text });
    const r = run('install.sh', [t], 'y\n');
    assert.strictEqual(r.status, 0, `install, settings ${why}: the install goes on\n${tail(r.out)}`);
    assert.match(r.out, /telemetry hooks not merged: .*settings\.json was left unchanged/, `install, settings ${why}: warns`);
    assert.strictEqual(read(t, SHARED), text, `install, settings ${why}: file unchanged`);
    assert.ok(read(t, 'CLAUDE.md').includes('# >>> skill-builder >>>'), `install, settings ${why}: later steps ran`);
  });

  // 3. An empty or blank settings file is {}: hooks are merged into it.
  for (const [i, text] of ['', ' \n'].entries()) {
    let t = target(`brain-empty-${i}`, { [LOCAL]: text });
    let r = run('scripts/brain/brain-self-install.sh', [t]);
    assert.strictEqual(r.status, 0, `brain install, empty settings: ${tail(r.out)}`);
    assert.match(r.out, /hook entries merged \(6 added or updated\)/);
    t = target(`install-empty-${i}`, { [SHARED]: text });
    r = run('install.sh', [t], 'y\n');
    assert.strictEqual(r.status, 0, `install, empty settings: ${tail(r.out)}`);
    assert.match(r.out, /merged 4 telemetry hook entries into/);
  }

  // 4. An event we do not touch may have any shape: the merge goes on and keeps it as found.
  {
    const t = target('brain-other-event', { [LOCAL]: '{"hooks": {"Notification": {"x": 1}}}\n' });
    const r = run('scripts/brain/brain-self-install.sh', [t]);
    assert.strictEqual(r.status, 0, tail(r.out));
    assert.deepStrictEqual(json(t, LOCAL).hooks.Notification, { x: 1 });
  }

  // 5. uninstall removes our hooks one by one and keeps the owner's hooks in the same entry.
  const own = { type: 'command', command: 'echo own-hook' };
  const inv = { type: 'command', command: 'node "$CLAUDE_PROJECT_DIR/scripts/telemetry/log-invocation.js"' };
  const end = { type: 'command', command: 'node "$CLAUDE_PROJECT_DIR/scripts/telemetry/log-outcome.js" --mode session-end' };
  const brainEnd = { type: 'command', command: 'bash "$CLAUDE_PROJECT_DIR/hooks/brain/brain-session-end.sh"' };
  const brainLoad = { type: 'command', command: 'bash "$CLAUDE_PROJECT_DIR/hooks/brain/brain-load.sh"' };
  {
    const t = target('uninstall-mixed', {
      [SHARED]: JSON.stringify({ hooks: {
        PostToolUse: [{ matcher: 'Skill|Task', hooks: [own, inv] }, { matcher: 'Skill|Task', hooks: [inv] }],
        Stop: [{ hooks: [end] }],
        SessionEnd: [null, { hooks: [null, end] }, { hooks: [] }],
      } }, null, 2),
      [LOCAL]: JSON.stringify({ hooks: {
        Stop: [{ hooks: [own, brainEnd] }],
        SessionStart: [{ hooks: [brainLoad] }],
      } }, null, 2),
      'hooks/brain/brain-load.sh': 'x\n',
    });
    const r = run('uninstall.sh', [t], 'y\n');
    assert.strictEqual(r.status, 0, tail(r.out));
    const shared = json(t, SHARED).hooks;
    assert.deepStrictEqual(shared, {
      PostToolUse: [{ matcher: 'Skill|Task', hooks: [own] }],
      // a null entry, a null hook and an empty entry are the owner's, kept as found
      SessionEnd: [null, { hooks: [null] }, { hooks: [] }],
    }, 'telemetry hooks removed one by one; the owner hook, nulls and empty entry kept');
    assert.match(r.out, /removed 4 telemetry hooks from/);
    assert.deepStrictEqual(json(t, LOCAL).hooks, { Stop: [{ hooks: [own] }] },
      "brain hooks removed one by one; the owner's hook in the same entry kept");
  }

  // 6. uninstall leaves settings it cannot read byte for byte, warns for each file, and goes on.
  //    A list that is not a list cannot hold our hooks: uninstall keeps it and has nothing to
  //    remove, so the file is not rewritten and there is no warning.
  BAD.forEach(([why, text], i) => {
    const unreadable = i < BAD.length - 1;
    const t = target(`uninstall-bad-${i}`, { [SHARED]: text, [LOCAL]: text, 'hooks/brain/brain-load.sh': 'x\n' });
    const r = run('uninstall.sh', [t], 'y\n');
    assert.strictEqual(r.status, 0, `uninstall, settings ${why}: the uninstall goes on\n${tail(r.out)}`);
    assert.strictEqual(/settings\.json was left unchanged/.test(r.out), unreadable, `uninstall, settings.json ${why}: warns iff unreadable`);
    assert.strictEqual(/settings\.local\.json was left unchanged/.test(r.out), unreadable, `uninstall, settings.local.json ${why}: warns iff unreadable`);
    assert.strictEqual(read(t, SHARED), text, `uninstall, settings.json ${why}: unchanged`);
    assert.strictEqual(read(t, LOCAL), text, `uninstall, settings.local.json ${why}: unchanged`);
    assert.ok(!fs.existsSync(path.join(t, 'hooks', 'brain')), `uninstall, settings ${why}: the brain files still go`);
  });

  console.log('settings-safety.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
