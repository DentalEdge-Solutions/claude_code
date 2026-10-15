// scripts/brain/brain-hooks.test.js — hooks parse event JSON, are no-ops without
// a capsule, capture/compile/lint through the Phase 1 scripts, and only the
// security guard ever denies.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = path.join(__dirname, '..', '..');
const HOOKS = path.join(REPO, 'hooks', 'brain');
const TMP = path.join(__dirname, '__hooks_test_tmp__');
const BRAIN = path.join(TMP, '.project-brain');
const today = new Date().toISOString().slice(0, 10);

// Every hook run has a timeout: a hanging hook (e.g. a ReDoS in the guard) must fail
// the test, not stall it. A timed-out PreToolUse hook lets the tool call through.
function runHook(name, event, root = TMP, { raw, env = {} } = {}) {
  const r = spawnSync('bash', [path.join(HOOKS, name)], {
    encoding: 'utf8', input: raw !== undefined ? raw : JSON.stringify(event),
    env: { ...process.env, CLAUDE_PROJECT_DIR: root, ...env },
    timeout: 15000, maxBuffer: 16 * 1024 * 1024,
  });
  assert.ok(!r.error, `${name} failed to run or timed out: ${r.error && r.error.message}`);
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function seedCapsule() {
  fs.rmSync(TMP, { recursive: true, force: true });
  for (const d of ['sessions/daily', 'decisions/candidates', 'decisions/active',
    'lessons/memories', 'canon', 'synthesis', 'reports']) {
    fs.mkdirSync(path.join(BRAIN, d), { recursive: true });
  }
  fs.writeFileSync(path.join(BRAIN, 'log.md'), '# Brain Log\n');
}

try {
  // 1. No capsule → every hook is a silent no-op, exit 0
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.mkdirSync(TMP, { recursive: true });
  for (const h of ['brain-pre-compact.sh', 'brain-session-end.sh', 'brain-post-lint.sh']) {
    const r = runHook(h, { hook_event_name: 'x' });
    assert.strictEqual(r.status, 0, `${h} must exit 0 without capsule: ${r.stderr}`);
    assert.strictEqual(r.stdout.trim(), '', `${h} must stay silent without capsule`);
  }

  // 2. PreCompact appends a snapshot note to today's log
  seedCapsule();
  let r = runHook('brain-pre-compact.sh', { hook_event_name: 'PreCompact', trigger: 'auto' });
  assert.strictEqual(r.status, 0, r.stderr);
  const log = path.join(BRAIN, 'sessions', 'daily', `${today}.md`);
  assert.ok(fs.existsSync(log), 'daily log created');
  assert.ok(fs.readFileSync(log, 'utf8').includes('pre-compact snapshot (auto)'));

  // 3. SessionEnd compiles: plant a decision entry, expect a candidate afterward
  seedCapsule();
  fs.writeFileSync(log, `# Session log — ${today}\n\n## 10:00 [decision] Hook test decision\n\nBody.\n`);
  r = runHook('brain-session-end.sh', { hook_event_name: 'SessionEnd' });
  assert.strictEqual(r.status, 0, r.stderr);
  const cands = fs.readdirSync(path.join(BRAIN, 'decisions', 'candidates')).filter(f => f.endsWith('.md'));
  assert.strictEqual(cands.length, 1, 'SessionEnd compiled the decision');

  // 4. Stop suggests exactly once when uncompiled entries exist
  seedCapsule();
  fs.writeFileSync(log, `# Session log — ${today}\n\n## 10:00 [lesson] L\n\nBody.\n`);
  r = runHook('brain-session-end.sh', { hook_event_name: 'Stop' });
  assert.ok(r.stdout.includes('additionalContext'), 'first Stop suggests');
  r = runHook('brain-session-end.sh', { hook_event_name: 'Stop' });
  assert.strictEqual(r.stdout.trim(), '', 'second Stop same day is silent');

  // 5. Security guard denies Write into canon/, allows normal writes
  seedCapsule();
  r = runHook('brain-security-guard.sh', {
    hook_event_name: 'PreToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(BRAIN, 'canon', 'x.md'), content: 'hi' },
  });
  assert.strictEqual(r.status, 0);
  assert.ok(r.stdout.includes('"permissionDecision":"deny"'), `canon write must be denied: ${r.stdout}`);
  r = runHook('brain-security-guard.sh', {
    hook_event_name: 'PreToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(TMP, 'src', 'app.js'), content: 'hi' },
  });
  assert.strictEqual(r.stdout.trim(), '', 'normal write passes silently');

  // 6. Guard: Bash touching canon denied unless brain-promote --approve; rm -rf on capsule denied
  const denyBash = cmd => runHook('brain-security-guard.sh',
    { hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: cmd } });
  assert.ok(denyBash('echo x >> .project-brain/canon/y.md').stdout.includes('deny'));
  assert.strictEqual(denyBash('node scripts/brain/brain-promote.js decisions/candidates/a.md --approve --to canon').stdout.trim(), '');
  assert.ok(denyBash('rm -rf .project-brain').stdout.includes('deny'));

  // 6b. Hardening regressions: path traversal, cd+relative canon, interpreter writes.
  // Raw string concat on purpose — path.join would normalize the ".." away.
  r = runHook('brain-security-guard.sh', {
    hook_event_name: 'PreToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(BRAIN, 'decisions') + '/../canon/x.md', content: 'hi' },
  });
  assert.ok(r.stdout.includes('"permissionDecision":"deny"'), `traversal into canon must be denied: ${r.stdout}`);
  assert.ok(denyBash('cd .project-brain && echo x >> canon/y.md').stdout.includes('deny'),
    'cd + relative canon append must be denied');
  assert.ok(denyBash('node -e "require(\'fs\').writeFileSync(\'.project-brain/canon/x.md\',\'x\')"').stdout.includes('deny'),
    'interpreter write into canon must be denied');
  assert.strictEqual(denyBash('node scripts/brain/brain-promote.js decisions/candidates/a.md --approve --to canon').stdout.trim(), '',
    'approved promote still passes after hardening');
  r = runHook('brain-security-guard.sh', {
    hook_event_name: 'PreToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(TMP, 'src', 'app.js'), content: 'hi' },
  });
  assert.strictEqual(r.stdout.trim(), '', 'normal write still passes silently after hardening');

  // 6c. False-positive guard: a READ command that merely references canon and uses a
  // /dev/null or stderr redirect must NOT be denied (2>/dev/null is not a canon write).
  assert.strictEqual(denyBash('ls .project-brain/canon/ 2>/dev/null').stdout.trim(), '',
    'read of canon with 2>/dev/null must pass');
  assert.strictEqual(denyBash('find .project-brain/canon -name "*.md" 2>/dev/null | grep -v gitkeep').stdout.trim(), '',
    'find under canon with stderr redirect must pass');
  assert.strictEqual(denyBash('cat .project-brain/canon/x.md >/dev/null 2>&1').stdout.trim(), '',
    'cat canon to /dev/null must pass');
  // …but a real redirect TARGETING canon is still denied.
  assert.ok(denyBash('echo x > .project-brain/canon/sneak.md 2>/dev/null').stdout.includes('deny'),
    'real redirect into canon still denied even with trailing 2>/dev/null');

  // 6d. Direct install from reference-repositories/sources/ into the skills dir is denied.
  assert.ok(denyBash('cp -R reference-repositories/sources/gstack ~/.claude/skills/gstack').stdout.includes('deny'),
    'direct install from reference sources must be denied');
  assert.ok(denyBash('rsync -a reference-repositories/sources/foo/ .claude/skills/foo/').stdout.includes('deny'),
    'rsync install from reference sources must be denied');
  // Reading/mapping a source card (no install) still passes.
  assert.strictEqual(denyBash('cat reference-repositories/sources/gstack/source-card.md 2>/dev/null').stdout.trim(), '',
    'reading a source card must pass');

  // 6e. P11 — bad input fails CLOSED: Claude Code always sends a JSON object with a
  // tool_name, so anything else is an anomaly and is denied with a reason.
  seedCapsule();
  const isDeny = res => res.stdout.includes('"permissionDecision":"deny"');
  for (const [label, raw] of [['empty', ''], ['whitespace', ' \n'], ['malformed', '{not json'],
    ['null', 'null'], ['array', '[]'], ['string', '"Bash"'], ['no tool_name', '{"tool_input":{}}'],
    ['non-object tool_input', '{"tool_name":"Bash","tool_input":"rm -rf .project-brain"}'],
    ['non-string command', '{"tool_name":"Bash","tool_input":{"command":["rm","-rf",".project-brain"]}}']]) {
    r = runHook('brain-security-guard.sh', null, TMP, { raw });
    assert.strictEqual(r.status, 0, `${label}: deny is expressed via JSON, exit 0`);
    assert.ok(isDeny(r), `${label} input must be denied: ${r.stdout}`);
    assert.ok(/malformed|unreadable/i.test(r.stdout), `${label}: the reason must say the input was bad: ${r.stdout}`);
  }

  // 6f. P11 — when node itself cannot run, the guard fails OPEN but VISIBLY: exit 1 (a
  // non-blocking hook error the user sees), a stderr warning and a log line in the capsule.
  // Allowing here is deliberate: denying would block every Write/Edit/Bash, the fix included.
  for (const code of [1, 127]) {
    seedCapsule();
    const fakeBin = path.join(TMP, 'fakebin');
    fs.mkdirSync(fakeBin, { recursive: true });
    fs.writeFileSync(path.join(fakeBin, 'node'), `#!/bin/sh\nexit ${code}\n`, { mode: 0o755 });
    r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'Bash',
      tool_input: { command: 'ls' } }, TMP, { env: { PATH: `${fakeBin}:${process.env.PATH}` } });
    assert.strictEqual(r.status, 1, `node exit ${code}: guard must exit 1 so the failure is shown: ${r.stderr}`);
    assert.strictEqual(r.stdout.trim(), '', `node exit ${code}: no decision is printed`);
    assert.ok(/failing open/.test(r.stderr), `node exit ${code}: stderr warns: ${r.stderr}`);
    const flog = path.join(BRAIN, 'reports', 'guard-failures.log');
    assert.ok(fs.existsSync(flog), `node exit ${code}: a log line is written`);
    assert.ok(/brain-security-guard.*failing open/.test(fs.readFileSync(flog, 'utf8')), 'log line names the guard');
  }

  // 6g. P11 — false positives: read-only commands where "rm" is an argument or part of a
  // file name, not the command being run, must pass.
  seedCapsule();
  for (const cmd of [
    'grep "rm" .project-brain/decisions',
    'grep -rn rm .project-brain/',
    'grep -e rm -- .project-brain/index.md',
    'git add .project-brain/decisions/active/2026-10-15-static-scan-rm-rf-root-checks.md .project-brain/index.md',
    'ls .project-brain/reports/rm-rf-notes.md',
    'node scripts/brain/brain-search.js --query "rm -rf root" && cat .project-brain/index.md',
    'cat .project-brain/log.md | grep rm',
    'sudo grep -e -delete .project-brain/log.md',
    // review R4: leaving the capsule with cd/popd ends the "inside the capsule" state
    'cd .project-brain && ls; cd .. && rm -rf build',
    'pushd .project-brain && ls && popd && rm -rf node_modules',
    'cd .project-brain && git log --oneline; cd /tmp && rm -rf scratch',
    // review R5 and the follow-up false-positive hunt
    'git -C .project-brain clean -n',
    'find .project-brain -name rm',
    'grep -rn "find .* -delete" .project-brain',
    'time grep -r rm .project-brain',
    '>/dev/null grep rm .project-brain/log.md',
    'git grep -n rm -- .project-brain',
    'rg rm .project-brain',
    // a quoted word that merely ends in "rm" is not a glued -Orm option (differential finding)
    "env -S'farm .project-brain'",
  ]) {
    r = denyBash(cmd);
    assert.strictEqual(r.stdout.trim(), '', `must allow: ${cmd} → ${r.stdout}`);
  }

  // 6h. P11 — real deletes of the capsule must be denied, including the gaps
  // (cd into the capsule first, find -delete, xargs rm) and the old rule's existing denials.
  for (const cmd of [
    'cd .project-brain && rm -rf decisions',
    'cd .project-brain; rm -rf *',
    'cd /tmp/x/.project-brain/decisions && rm candidates/a.md',
    'pushd .project-brain && rm -f log.md',
    'find .project-brain -name "*.md" -delete',
    'find .project-brain -type f -exec rm {} +',
    'find .project-brain -type f -execdir rm -f {} \\;',
    'find .project-brain -type f | xargs rm -f',
    'cd .project-brain && find . -delete',
    'rm -rf .project-brain',
    'rm -rf ".project-brain"',
    '/bin/rm -rf .project-brain',
    '\\rm -r .project-brain/sessions',
    'sudo rm -rf .project-brain/canon',
    'bash -c "rm -rf .project-brain"',
    'ls; rm -rf ./.project-brain/decisions',
    'rmdir .project-brain/synthesis',
    'unlink .project-brain/log.md',
    'git rm -r .project-brain/decisions',
    // review R1: expansions must not split the target off the delete
    'rm -rf "${CLAUDE_PROJECT_DIR}/.project-brain"',
    'rm -rf "$(pwd)/.project-brain"',
    'rm -rf $(git rev-parse --show-toplevel)/.project-brain',
    'rm -rf `pwd`/.project-brain',
    'rm -rf {.project-brain,/nonexistent}',
    'rm -rf ./{.project-brain,x}',
    'rm -rf $(echo .project-brain)',
    'rm -rf "a;b" .project-brain',
    'rm -rf "x\ny" .project-brain',
    // review R2: a redirection before the command word
    '>/dev/null rm -rf .project-brain',
    '2>/dev/null rm -rf .project-brain',
    '</dev/null rm -rf .project-brain',
    '2>&1 rm -rf .project-brain',
    // review R3: any program that runs its arguments, not a fixed runner list
    'busybox rm -rf .project-brain',
    'caffeinate rm -rf .project-brain',
    'arch -arm64 rm -rf .project-brain',
    'script -q /dev/null rm -rf .project-brain',
    'flock /tmp/l rm -rf .project-brain',
    'watch -n1 rm -rf .project-brain',
    'parallel rm -rf ::: .project-brain',
    'ssh host rm -rf .project-brain',
    'trap "rm -rf .project-brain" EXIT',
    'su -c "rm -rf .project-brain"',
    "sh <<<'rm -rf .project-brain'",
    'bash<<<"rm -rf .project-brain"',
    "env -S'rm -rf .project-brain'",
    'git --git-dir .git rm -r .project-brain',
    'git --work-tree . rm -r .project-brain',
    'git -c alias.x="!rm -rf .project-brain" x',
    'echo rm -rf .project-brain | sh',
    'printf "rm -rf .project-brain" | bash',
    'eval "$(echo rm -rf .project-brain)"',
    // review R6 and related gaps
    'echo .project-brain | xargs -I{} rm -rf {}',
    "bash -c 'cd .project-brain && rm -rf *'",
    'cd "$(git rev-parse --show-toplevel)/.project-brain" && rm -rf decisions',
    'cd ${CLAUDE_PROJECT_DIR}/.project-brain && rm -rf decisions',
    'cd .project-brain/decisions && cd .. && rm -rf candidates',
    "find .project-brain -exec sh -c 'rm \"$1\"' _ {} \\;",
    'r\\m -rf .project-brain',
    'python3 -c "import shutil; shutil.rmtree(\'.project-brain\')"',
    'node -e "require(\'fs\').rmSync(\'.project-brain\',{recursive:true})"',
    'git clean -fdx .project-brain',
    // a reader loses its exemption when it carries a command substitution
    'echo "$(rm -rf .project-brain)"',
    'cat <(rm -rf .project-brain)',
    // readers that can run a command through an option or an environment variable
    'rg --pre rm x .project-brain',
    'rg --pre=rm x .project-brain',
    'ag --pager "rm -rf .project-brain" foo',
    'sort --compress-program=rm .project-brain/log.md',
    'LESSOPEN="|rm -rf .project-brain" less x',
    'PAGER="rm -rf .project-brain" git log',
    'GIT_SSH_COMMAND="rm -rf .project-brain" git status',
    'git fetch --upload-pack="rm -rf .project-brain" origin',
    'git -C .project-brain push --receive-pack="rm -rf ." origin',
    'git diff --ext-diff -c x .project-brain/rm',
    'GIT_EXTERNAL_DIFF=rm git diff .project-brain/log.md',
    'git grep -Orm x .project-brain',
    'git grep --open-files-in-pager=rm x .project-brain',
    'git grep --open=rm x -- .project-brain',
    'sort --compress-prog=rm .project-brain/log.md',
    'rg --hostname-bin rm x .project-brain',
    // quoted pieces join into one shell word: -O"r"m is -Orm
    'git grep -O"r"m x -- .project-brain',
    "git grep -O'rm' x -- .project-brain",
    'git grep -O\\rm x -- .project-brain',
    'x=-O"r"m git grep $x x -- .project-brain',
  ]) {
    assert.ok(isDeny(denyBash(cmd)), `must deny: ${cmd}`);
  }

  // 6i. P11 — a large Write into canon is still denied (the input must not travel through an
  // environment variable, where a big payload makes node fail to start and the guard fail open).
  r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(BRAIN, 'canon', 'big.md'), content: 'x'.repeat(2 * 1024 * 1024) } });
  assert.ok(isDeny(r), `a 2 MB Write into canon must be denied: status ${r.status} ${r.stderr}`);

  // 6i-b. NotebookEdit names its path notebook_path, not file_path — it must be checked too.
  r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'NotebookEdit',
    tool_input: { notebook_path: path.join(BRAIN, 'canon', 'n.ipynb'), new_source: 'x' } });
  assert.ok(isDeny(r) && r.stdout.includes('Direct writes to .project-brain/canon/'),
    `NotebookEdit into canon must be denied as a canon write: ${r.stdout}`);
  r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'NotebookEdit',
    tool_input: { notebook_path: path.join(TMP, 'n.ipynb'), new_source: 'x' } });
  assert.strictEqual(r.stdout.trim(), '', 'NotebookEdit outside canon passes');

  // 6j. P11 — timing: every rule must stay linear. 512 KB still fits the old env-var path,
  // so these inputs reach the regexes (the old ones were quadratic: minutes, not ms).
  const K = 1 << 19;
  for (const [label, cmd] of [
    ['rm + spaces', 'rm ' + ' '.repeat(K) + '.project-brain'],
    ['many rm', 'rm '.repeat(K / 3) + '.project-brain'],
    ['many separators', 'cd .project-brain' + ' && rm'.repeat(K / 6)],
    ['find -exec', 'find .project-brain ' + '-exec '.repeat(K / 6) + 'x'],
    ['quotes', 'grep "' + '"'.repeat(K) + ' .project-brain'],
    ['canon redirects', '.project-brain/canon ' + '2>/dev/null '.repeat(K / 12)],
    ['digits', '.project-brain/canon ' + '1'.repeat(K)],
    ['many sed', '.project-brain/canon ' + 'sed '.repeat(K / 4)],
    ['many brain-promote', '.project-brain/canon > x ' + 'brain-promote '.repeat(K / 14)],
  ]) {
    const t0 = Date.now();
    denyBash(cmd);
    const ms = Date.now() - t0;
    assert.ok(ms < 3000, `${label}: guard took ${ms} ms on a 512 KB command`);
  }

  // 7. Post-lint: always exit 0; warns via additionalContext only on sensitive content
  seedCapsule();
  fs.writeFileSync(path.join(BRAIN, 'sessions', 'daily', `${today}.md`),
    '# log\n\n## 10:00 [note]\n\nleak sk-ant-abc123def456ghi789\n');
  r = runHook('brain-post-lint.sh', {
    hook_event_name: 'PostToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(BRAIN, 'sessions', 'daily', `${today}.md`) },
  });
  assert.strictEqual(r.status, 0, 'post-lint never blocks');
  assert.ok(r.stdout.includes('SENSITIVE'), 'sensitive content surfaces a warning');
  r = runHook('brain-post-lint.sh', {
    hook_event_name: 'PostToolUse', tool_name: 'Write',
    tool_input: { file_path: path.join(TMP, 'README.md') },
  });
  assert.strictEqual(r.stdout.trim(), '', 'non-brain writes are ignored');

  // 8. brain-load: emits additionalContext with protocol + top titles, ≤8000 chars
  seedCapsule();
  fs.writeFileSync(path.join(BRAIN, 'BRAIN.md'), '# Project Brain — t\n\n## Second Brain Protocol\n\n1. Read first.\n');
  fs.mkdirSync(path.join(BRAIN, 'decisions', 'active'), { recursive: true });
  fs.writeFileSync(path.join(BRAIN, 'decisions', 'active', 'd1.md'),
    '---\ntype: decision\ntitle: Loaded decision one\ndescription: d\ntags: []\ntimestamp: 2026-07-08T00:00:00\nsources: []\nstatus: active\n---\n\nBody.\n');
  r = runHook('brain-load.sh', { hook_event_name: 'SessionStart' });
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes('"additionalContext"'), 'emits additionalContext');
  assert.ok(r.stdout.includes('Second Brain Protocol'), 'includes protocol');
  assert.ok(r.stdout.includes('Loaded decision one'), 'includes active decision title');
  assert.ok(r.stdout.length < 8500, 'respects size cap');
  // no capsule → silent
  r = runHook('brain-load.sh', { hook_event_name: 'SessionStart' }, path.join(TMP, 'nowhere'));
  assert.strictEqual(r.stdout.trim(), '');

  console.log('brain-hooks.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
