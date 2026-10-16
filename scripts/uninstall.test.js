// scripts/uninstall.test.js — uninstall.sh refuses a target where "${TARGET}/<dir>" removals
// would hit the filesystem root, the home directory or the toolkit itself (P9), and still
// removes the installed pieces from a normal project.
// Everything runs on a COPY of uninstall.sh inside a temp fake repo, with HOME pointed at a
// temp fake home, so a failing run can only touch temp files. The "/" cases always answer "n".
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'uninstall-test-'));
const FAKE_REPO = path.join(TMP, 'repo');
const FAKE_HOME = path.join(TMP, 'home');
const PROJECT = path.join(TMP, 'project');
const SCRIPT = path.join(FAKE_REPO, 'uninstall.sh');

function touch(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, 'x\n');
}
function run(target, answer, cwd = TMP, { script = SCRIPT, env = {} } = {}) {
  const r = spawnSync('bash', target === undefined ? [script] : [script, target], {
    encoding: 'utf8', cwd, input: answer, timeout: 20000,
    env: { ...process.env, HOME: FAKE_HOME, ...env },
  });
  assert.ok(!r.error, `uninstall.sh failed to run: ${r.error && r.error.message}`);
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function assertRefused(r, label) {
  assert.notStrictEqual(r.status, 0, `${label}: must exit non-zero\n${r.stdout}\n${r.stderr}`);
  assert.ok(/Refusing/.test(r.stderr), `${label}: must explain the refusal on stderr\n${r.stderr}`);
  assert.ok(!/removed/.test(r.stdout), `${label}: must remove nothing\n${r.stdout}`);
}

try {
  touch(path.join(FAKE_REPO, 'skills', 'demo-skill', 'SKILL.md'));
  fs.copyFileSync(path.join(REPO, 'uninstall.sh'), SCRIPT);
  touch(path.join(FAKE_REPO, '.claude', 'agents', 'demo-agent.md'));
  touch(path.join(FAKE_HOME, 'skills', 'canary.md'));
  touch(path.join(FAKE_HOME, '.claude', 'skills', 'demo-skill', 'SKILL.md'));
  touch(path.join(PROJECT, 'skills', 'demo-skill', 'SKILL.md'));
  touch(path.join(PROJECT, '.claude', 'agents', 'demo-agent.md'));
  touch(path.join(PROJECT, '.claude', 'agents', 'own-agent.md'));
  fs.symlinkSync(FAKE_HOME, path.join(TMP, 'link-to-home'));
  fs.symlinkSync('/', path.join(TMP, 'link-to-root'));

  // 1. The filesystem root, directly and through a symlink (answer "n": never proceed on "/").
  assertRefused(run('/', 'n\n'), 'target /');
  assertRefused(run(path.join(TMP, 'link-to-root'), 'n\n'), 'symlink to /');
  // review U1: bash keeps a leading "//" in pwd -P, so a string compare missed these
  assertRefused(run('//', 'n\n'), 'target //');

  // 2. The home directory, directly and through a symlink. Answer "y": a missing guard would
  //    delete the fake home's skills/ — the canary shows it.
  assertRefused(run(FAKE_HOME, 'y\n'), 'target $HOME');
  assertRefused(run(path.join(TMP, 'link-to-home'), 'y\n'), 'symlink to $HOME');
  assertRefused(run('/' + FAKE_HOME, 'y\n'), '//$HOME');
  assert.ok(fs.existsSync(path.join(FAKE_HOME, 'skills', 'canary.md')), '$HOME/skills survives');
  // review U3: ~/.claude would lose ~/.claude/skills, every runtime skill, not only ours
  touch(path.join(FAKE_HOME, '.claude', 'skills', 'other-skill', 'SKILL.md'));
  assertRefused(run(path.join(FAKE_HOME, '.claude'), 'y\n'), 'target $HOME/.claude');
  assert.ok(fs.existsSync(path.join(FAKE_HOME, '.claude', 'skills', 'other-skill', 'SKILL.md')),
    '$HOME/.claude/skills survives');

  // 3. The toolkit repo itself, by absolute path and as "." from inside it.
  assertRefused(run(FAKE_REPO, 'y\n'), 'target = toolkit repo');
  assertRefused(run('.', 'y\n', FAKE_REPO), '"." inside the toolkit repo');
  // review U2: with CDPATH exported, cd prints the path and a relative script path made
  // REPO_DIR two lines long, so the repo check compared against the wrong string
  assertRefused(run(FAKE_REPO, 'y\n', TMP, { script: 'repo/uninstall.sh', env: { CDPATH: '.:/' } }),
    'toolkit repo with CDPATH set');
  assert.ok(fs.existsSync(path.join(FAKE_REPO, 'skills', 'demo-skill', 'SKILL.md')), 'repo skills/ survives');

  // 4. No target: usage, exit 1 (unchanged behaviour).
  assert.strictEqual(run(undefined, '').status, 1, 'no target exits 1');

  // 5. A normal project: the installed pieces go, the project's own files stay. The CLAUDE.md
  //    section removal must work with GNU sed too (P6: "sed -i ''" is BSD-only; CI is Linux).
  //    Review U4: a symlinked CLAUDE.md stays a symlink and the file keeps its mode.
  const claudeMd = path.join(PROJECT, 'docs-claude.md');
  fs.writeFileSync(claudeMd, '# Own title\n\nown text\n\n# >>> skill-builder >>>\npipeline\n# <<< skill-builder <<<\n\nown tail\n');
  fs.chmodSync(claudeMd, 0o600);
  fs.symlinkSync('docs-claude.md', path.join(PROJECT, 'CLAUDE.md'));
  const r = run(PROJECT, 'y\n');
  assert.strictEqual(r.status, 0, `normal uninstall failed\n${r.stdout}\n${r.stderr}`);
  assert.ok(!fs.existsSync(path.join(PROJECT, 'skills')), 'project skills/ removed');
  assert.ok(!fs.existsSync(path.join(PROJECT, '.claude', 'agents', 'demo-agent.md')), 'toolkit agent removed');
  assert.ok(fs.existsSync(path.join(PROJECT, '.claude', 'agents', 'own-agent.md')), 'project agent kept');
  assert.ok(!fs.existsSync(path.join(FAKE_HOME, '.claude', 'skills', 'demo-skill')), 'runtime skill removed');
  assert.strictEqual(fs.readFileSync(claudeMd, 'utf8'), '# Own title\n\nown text\n\n\nown tail\n',
    'CLAUDE.md loses exactly the skill-builder section');
  assert.ok(fs.lstatSync(path.join(PROJECT, 'CLAUDE.md')).isSymbolicLink(), 'CLAUDE.md is still a symlink');
  assert.strictEqual(fs.statSync(claudeMd).mode & 0o777, 0o600, 'CLAUDE.md keeps its mode');

  console.log('uninstall.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
