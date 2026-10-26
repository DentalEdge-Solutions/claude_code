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
// the test, not stall it.
// F1 quarantine (P0-09 step 0, docs/evaluations/2026-10-26-p0-09-brain-guard-fail-closed.md): the
// 512 KB timing loop (6j) once in about 1,930 runs saw the guard process stall past this timeout on
// an input that otherwise takes about 0.1 s; the root cause is not found (triage F1). A timing run
// that times out is therefore retried once, and the retry must meet the same bound. A super-linear
// pattern is deterministic and fails both runs; a one-off stall is reported on stderr, never hidden.
function runHook(name, event, root = TMP, { raw, env = {}, retryOnTimeout = false } = {}) {
  let ms = 0;
  const spawn = () => {
    const t0 = Date.now();
    const res = spawnSync('bash', [path.join(HOOKS, name)], {
      encoding: 'utf8', input: raw !== undefined ? raw : JSON.stringify(event),
      env: { ...process.env, CLAUDE_PROJECT_DIR: root, ...env },
      timeout: 15000, maxBuffer: 16 * 1024 * 1024,
    });
    ms = Date.now() - t0;
    return res;
  };
  let r = spawn();
  if (retryOnTimeout && r.error && r.error.code === 'ETIMEDOUT') {
    process.stderr.write(`F1 quarantine: ${name} timed out once (${r.error.message}); retrying once\n`);
    r = spawn();
  }
  assert.ok(!r.error, `${name} failed to run or timed out: ${r.error && r.error.message}`);
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', ms };
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

  // 6f. P0-09 (supersedes P11's fail-open): when node cannot run the guard — it is missing, exits
  // non-zero, is killed, cannot start, or runs past the guard's deadline — the guard fails CLOSED:
  // exit 2 (Claude Code blocks the call and shows stderr to Claude), a stderr reason, and a log line
  // in the capsule. The registration's onFailure "block" covers a guard that cannot start at all.
  const flog = path.join(BRAIN, 'reports', 'guard-failures.log');
  const fakeNode = (body, extra = {}) => {
    const fakeBin = path.join(TMP, 'fakebin');
    fs.mkdirSync(fakeBin, { recursive: true });
    fs.writeFileSync(path.join(fakeBin, 'node'), `#!/bin/sh\n${body}\n`, { mode: 0o755 });
    for (const [name, text] of Object.entries(extra)) fs.writeFileSync(path.join(fakeBin, name), text, { mode: 0o755 });
    return { PATH: `${fakeBin}:${process.env.PATH}` };
  };
  const lsEvent = { hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } };
  const blockedClosed = (res, label) => {
    assert.strictEqual(res.status, 2, `${label}: the guard must exit 2 so the call is blocked: ${res.status} ${res.stderr}`);
    assert.strictEqual(res.stdout.trim(), '', `${label}: no decision is printed`);
    assert.ok(/BLOCKED/.test(res.stderr) && /fails closed/.test(res.stderr), `${label}: stderr says why: ${res.stderr}`);
    assert.ok(/SECOND_BRAIN_SECURITY\.md/.test(res.stderr), `${label}: stderr points at the break-glass procedure`);
    assert.ok(!/failing open/.test(res.stderr), `${label}: never "failing open"`);
    assert.ok(fs.existsSync(flog), `${label}: a log line is written`);
    assert.ok(/brain-security-guard.*fails closed/.test(fs.readFileSync(flog, 'utf8')), `${label}: the log line names the guard`);
  };
  for (const [label, body] of [['node exits 1', 'exit 1'], ['node missing (127)', 'exit 127'], ['node killed', 'kill -9 $$']]) {
    seedCapsule();
    blockedClosed(runHook('brain-security-guard.sh', lsEvent, TMP, { env: fakeNode(body) }), label);
  }
  // a real node that cannot start: a preload module that does not exist
  seedCapsule();
  blockedClosed(runHook('brain-security-guard.sh', lsEvent, TMP,
    { env: { NODE_OPTIONS: '--require /nonexistent-p0-09-preload.js' } }), 'node cannot start');
  // timeout: a node that hangs is stopped at the deadline, and the call is blocked
  seedCapsule();
  {
    const t0 = Date.now();
    const res = runHook('brain-security-guard.sh', lsEvent, TMP, { env: { ...fakeNode('exec sleep 30'), BRAIN_GUARD_DEADLINE_S: '1' } });
    const ms = Date.now() - t0;
    blockedClosed(res, 'node hangs');
    assert.ok(ms < 8000, `node hangs: blocked at the 1 s deadline, not after ${ms} ms`);
    assert.ok(/deadline/.test(res.stderr), `node hangs: stderr names the deadline: ${res.stderr}`);
  }
  // the deadline never cuts a normal check short: with a sleep that fails at once, nothing is killed
  seedCapsule();
  {
    const env = fakeNode('exec "$REAL_NODE" "$@"', { sleep: '#!/bin/sh\nexit 1\n' });
    env.REAL_NODE = process.execPath;
    let res = runHook('brain-security-guard.sh', lsEvent, TMP, { env });
    assert.strictEqual(res.status, 0, `broken sleep: an ordinary command still passes: ${res.stderr}`);
    assert.strictEqual(res.stdout.trim(), '');
    res = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'Write',
      tool_input: { file_path: path.join(BRAIN, 'canon', 'x.md'), content: 'x' } }, TMP, { env });
    assert.ok(isDeny(res), `broken sleep: a canon write is still denied: ${res.stdout}`);
  }
  // a normal check returns at once: the deadline's watcher never holds the output open
  seedCapsule();
  {
    const t0 = Date.now();
    const res = runHook('brain-security-guard.sh', lsEvent, TMP, { env: { BRAIN_GUARD_DEADLINE_S: '30' } });
    assert.strictEqual(res.status, 0, res.stderr);
    assert.ok(Date.now() - t0 < 5000, 'a normal check does not wait for the deadline');
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
    // P11 re-review RR1/RR2: a global option's value is skipped, so the real subcommand is seen
    'git --work-tree . grep -n rm -- .project-brain',
    'git --no-pager grep -n rm -- .project-brain',
    // a real dry run of git clean stays allowed, wherever the -n sits
    'git clean -nd .project-brain',
    'git clean --dry-run -d .project-brain',
    'git clean -fd .project-brain -n',
    'git clean -nd -- .project-brain',
    // a clean word that is not git clean (a message, a search pattern) is not a delete
    'git commit -m "clean up .project-brain notes"',
    'git log --grep clean -- .project-brain',
    'grep "git clean" .project-brain/log.md',
    // a line continuation in an ordinary command still passes
    'git add .project-brain/decisions/a.md \\\n  .project-brain/index.md',
    'grep -rn "rm -rf" \\\n  .project-brain/decisions',
    'echo "a # b" \\\n  && ls .project-brain',
    // P0-09 G3: a canon file whose name holds the word rm, read by a pure reader pipeline
    'cat .project-brain/canon/rm-notes.md',
    'grep rm .project-brain/canon/x.md',
    'grep -rn "rm -rf" .project-brain/canon/',
    'ls .project-brain/canon/2026-10-15-static-scan-rm-rf-root.md',
    'git add .project-brain/canon/rm-x.md',
    'head -5 .project-brain/canon/rm.md | grep x',
    'git log --oneline -- .project-brain/canon/rm-x.md',
    'wc -l .project-brain/canon/rm-x.md 2>/dev/null',
    // P0-09 G1: exactly one brain-promote call keeps its exemption
    'node scripts/brain/brain-promote.js decisions/candidates/a.md --approve --to canon',
    // (an rm word before the capsule name would meet the delete rule's floor, which P0-09 does not relax)
    'node scripts/brain/brain-promote.js --target .project-brain canon/a-rm-note.md --approve',
    'node ./scripts/brain/brain-promote.js --target .project-brain canon/rm-x.md --approve --to active',
    // P0-09: decisions/active/ is readable, and the weekly review's route through brain-promote passes
    'cat .project-brain/decisions/active/d.md',
    'cat .project-brain/decisions/active/2026-10-15-static-scan-rm-rf-root-checks.md',
    'ls .project-brain/decisions/active/',
    'git add .project-brain/decisions/active/d.md',
    'grep -rn x .project-brain/decisions/active 2>/dev/null',
    'git diff -- .project-brain/decisions/active/',
    'node scripts/brain/brain-promote.js decisions/active/d.md --approve --to superseded',
    'node scripts/brain/brain-promote.js decisions/candidates/d.md --approve --to active --force',
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
    // inside the capsule, an rm NOT adjacent to .project-brain (floor does not fire) that still
    // reaches a shell or runs via substitution — the downstream-stage and !SUBST exemption checks
    'cd .project-brain; echo rm -rf decisions | sh',
    'cd .project-brain; echo rm -rf decisions | bash',
    'cd .project-brain; echo "$(rm -rf decisions)"',
    'cd .project-brain; cat <(rm -rf decisions)',
    // round 3: parser desync — a quote in a comment, ANSI-C quoting, a heredoc body
    "echo hi # it's\nrm -rf .project-brain",
    "ls # don't\nrm -rf .project-brain",
    "echo $'\\'' ; rm -rf .project-brain ; echo ''",
    "cat <<'EOF'\necho it's\nEOF\nrm -rf .project-brain",
    'bash <<EOF\nrm -rf .project-brain\nEOF',
    // round 3: write a delete script then run it (main denies the adjacency)
    'echo rm -rf .project-brain > /tmp/x.sh && sh /tmp/x.sh',
    'echo rm -rf .project-brain | tee /tmp/x.sh; sh /tmp/x.sh',
    'printf "rm -rf .project-brain" >> /tmp/x.sh',
    // round 3: a cd that does NOT change the parent shell's directory, then a delete
    'cd .project-brain; (cd /tmp); rm -rf decisions',
    'cd .project-brain; cd /tmp | cat; rm -rf decisions',
    'cd .project-brain; cd /tmp & rm -rf decisions',
    // round 3 (security review): a brace group { ...; } runs in the CURRENT shell, so its cd
    // DOES move the parent directory — a later relative delete then hits the capsule
    'cd /tmp; { cd .project-brain; }; rm -rf decisions',
    '{ cd .project-brain; rm -rf decisions; }',
    // round 3 (security review 2): a brace group inside a pipeline or background runs in a
    // SUBSHELL, so its cd out does NOT move the parent — the parent stays in the capsule and the
    // relative delete hits it. Leaving the capsule is honored only from a plain standalone cd, so
    // these stay denied (the standalone-brace case is a documented conservative denial too).
    'cd .project-brain; { cd /tmp; } | cat; rm -rf decisions',
    'cd .project-brain; { cd /tmp; } & rm -rf decisions',
    'cd .project-brain; { cd /tmp; }; rm -rf decisions',
    // round 3 (security review 3-5): a cd can run inside a group that does not move the parent
    // (a subshell, or a brace group that is piped/backgrounded), including when it is not the first
    // statement in the group. Rather than parse nesting (fragile, repeatedly bypassed), any grouping
    // construct anywhere on the line — ( ), { }, or a case statement — makes a capsule-LEAVING cd
    // non-plain, so it is not honored. These stay denied; a line that leaves the capsule next to a
    // harmless ( ) is a documented conservative denial.
    'cd .project-brain; { true; cd /tmp; } | cat; rm -rf decisions',
    'cd .project-brain; { true; cd /tmp; } & rm -rf decisions',
    'cd .project-brain; (true; cd /tmp); rm -rf decisions',
    'cd .project-brain; (ls); cd /tmp; rm -rf build',
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
    // P11 re-review RR1: the value of a git global option is not the subcommand. Here "log" is
    // the namespace (or work tree, ...) and the real subcommand runs rm through a shell.
    'git --namespace log rebase -x "rm -rf .project-brain" HEAD~1',
    'git --git-dir=.git --work-tree log rebase -x "rm -rf .project-brain" HEAD~1',
    'git --attr-source show submodule foreach "rm -rf .project-brain"',
    'git --shallow-file log bisect run rm -rf .project-brain',
    // P11 re-review RR2: git clean deletes unless a dry run is really in effect. -e takes the
    // rest of its word or the next word, -- ends the options, and a later --no-dry-run wins.
    'git clean -f -en .project-brain',
    'git clean -f -e -n .project-brain',
    'git clean -fe n .project-brain',
    'git clean -f -- -n .project-brain',
    'git clean -f --exc -n .project-brain',
    'git clean -n --no-dry-run -f .project-brain',
    'git clean -n -fd --no-d .project-brain',
    'git --work-tree .project-brain clean -fd',
    'git --namespace x clean -fd .project-brain',
    'git -C -n clean -fd .project-brain',
    // re-review round 2 (V1): an option value with a space is one shell word, so "log" in
    // "x log" is not the subcommand; a variable value may split, so it ends the exemption
    'git --namespace "x log" rebase -x "rm -rf .project-brain" HEAD~1',
    'git --namespace x\\ log rebase -x "rm -rf .project-brain" HEAD~1',
    'git --namespace $V rebase -x "rm -rf .project-brain" HEAD~1',
    // V2/V3: a dry run is recognized only in a plain grammar (no quotes, escapes, redirects,
    // -e, --, --end-of-options); anything else counts as a delete
    'git clean -fd .project-brain "x -n"',
    'git clean -fd .project-brain x\\ -n',
    'git clean -f -e "x -n" .project-brain',
    'git clean -fd .project-brain > -n',
    'git clean -fd .project-brain <<< -n',
    'cd .project-brain && git clean -fdx . "a -n"',
    'git clean -fd --end-of-options .project-brain -n',
    'git clean -fd --end-of-options x -n .project-brain',
    'git clean -n -e foo .project-brain',
    // V4: git clean behind a wrapper, xargs or an alias
    'env git clean -fd .project-brain',
    'command git clean -fd .project-brain',
    'nice git clean -fd .project-brain',
    'echo .project-brain | xargs git clean -fd',
    'git -c alias.x=clean x -fd .project-brain',
    // review round 2 (W1): git words are read from the command word, not from the first word
    // that merely ends in /git (a redirect target or an assignment)
    '2>./git git clean -fd .project-brain',
    'A=./git git clean -fd .project-brain',
    '</usr/bin/git git clean -fd .project-brain',
    'A=./git git -c alias.x=clean x -fd .project-brain',
    // W2: a subcommand spelled with $, quoting or a glob is unknown, so it counts as a delete
    "git $'cl\\x65an' -fd .project-brain",
    "git cl$'e'an -fd .project-brain",
    // X1: an executor running a nested git clean
    'git rebase -x "git clean -fd .project-brain" HEAD~1',
    // W3: bash removes backslash-newline, so these are rm and clean; inside a # comment the
    // newline still ends the comment, so the next line is a command of its own
    'r\\\nm -rf .project-brain',
    'git cl\\\nean -fd .project-brain',
    "echo 'a\\\nb' ; r\\\nm -rf .project-brain",
    'cd .project-brain\nls # note \\\nrm -rf decisions',
    'cd .project-brain && ls # x \\\nrm decisions',
    // W3 follow-up: a # inside quotes is not a comment, so the continuation still joins
    'echo " #"; r\\\nm -rf .project-brain',
    "echo ' #'; r\\\nm -rf .project-brain",
    'cd .project-brain; echo " #" && r\\\nm -rf decisions',
    'echo "a\\\n#" ; r\\\nm -rf .project-brain',
    'git log --grep " #"; git cl\\\nean -fd .project-brain',
    // fail-closed: a continuation kept (single quotes, comment, or a quoting the guard misreads)
    // with a deleter after it, in a command that names the capsule
    "echo $'a\\'b #' ; r\\\nm -rf .project-brain",
    // review X2: the kept-continuation check was a word list; a glued -O option or an
    // ANSI-C subcommand slipped past it. A kept continuation in a command naming the capsule
    // now denies outright.
    "cat <<EOF\nit's\nEOF\ngit grep --untracked -Or\\\nm x -- .project-brain",
    "echo $'\\' #' ; git grep --untracked -Or\\\nm x -- .project-brain",
    "cat <<EOF\nit's\nEOF\ngit $'cl\\x65an' -fd \\\n.project-brain",
    "echo $'\\' #' ; git $'cl\\x65an' -fd \\\n.project-brain",
    // review X3: the kept pair can split the capsule name itself, so the capsule is looked
    // for in the fully joined text
    "cat <<EOF\nit's\nEOF\nrm -rf .project-\\\nbrain",
    "echo $'\\' #' ; rm -rf .project-\\\nbrain",
    "cat <<EOF\nit's\nEOF\ncd .project-\\\nbrain && rm -rf decisions",
    // P0-09 G1: the brain-promote exemption covers exactly one call, nothing chained to it
    'node scripts/brain/brain-promote.js decisions/candidates/a.md --approve && echo x > .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js decisions/candidates/a.md --approve; echo x >> .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js x --approve; echo x > .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js a.md --approve\necho x > .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js a.md --approve | tee .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js a.md --approve > .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js a.md --approve & echo x > .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js $(cp x .project-brain/canon/y.md) --approve',
    'node scripts/brain/brain-promote.js `cp x .project-brain/canon/y.md` --approve',
    'cp x .project-brain/canon/y.md && node scripts/brain/brain-promote.js a.md --approve',
    'echo x > .project-brain/canon/y.md # node scripts/brain/brain-promote.js a.md --approve',
    'node /tmp/evil/brain-promote.js .project-brain/canon/y.md --approve --rm',
    'FOO=1 node scripts/brain/brain-promote.js a.md --approve; mv x .project-brain/canon/y.md',
    'node scripts/brain/brain-promote.js a.md --approve && sed -i s/a/b/ .project-brain/decisions/active/d.md',
    // P0-09 G3: the narrowed rm check still denies every real mutation of canon
    'cat .project-brain/canon/rm-x.md | sh',
    'cat .project-brain/canon/rm-x.md > .project-brain/canon/y.md',
    'D=.project-brain/canon; rm $D/x.md',
    'cat .project-brain/canon/rm-x.md; rm -f canon/x.md',
    'echo "$(rm .project-brain/canon/x.md)"',
    'xargs rm < .project-brain/canon/list.md',
    'cat .project-brain/canon/rm-x.md & rm canon/y.md',
    'cat .project-brain/canon/rm-x.md | xargs rm',
    'grep -l x .project-brain/canon/* | xargs rm',
    // P0-09: decisions/active/ is protected like canon/ (writes, edits, moves; deletes were already)
    'echo x >> .project-brain/decisions/active/d.md',
    'sed -i s/a/b/ .project-brain/decisions/active/d.md',
    'cd .project-brain/decisions && echo x > active/d.md',
    'cd .project-brain && cp /tmp/x decisions/active/d.md',
    'git mv .project-brain/decisions/active/a.md .project-brain/decisions/superseded/a.md',
    'mv .project-brain/decisions/active/a.md .project-brain/decisions/superseded/',
    'cp x .project-brain/decisions/active/',
    'tee .project-brain/decisions/active/d.md < x',
    'node -e "require(\'fs\').writeFileSync(\'.project-brain/decisions/active/d.md\',\'x\')"',
    'python3 -c "open(\'.project-brain/decisions/active/d.md\',\'w\')"',
    'perl -e 1 .project-brain/decisions/active/d.md',
    'rm .project-brain/decisions/active/d.md',
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

  // 6i-c. P0-09: Write, Edit and NotebookEdit into decisions/active/ are denied (path-normalized);
  // candidates, superseded and look-alike folders are not.
  for (const tool of ['Write', 'Edit', 'NotebookEdit']) {
    const at = p => (tool === 'NotebookEdit' ? { notebook_path: p, new_source: 'x' } : { file_path: p, content: 'x' });
    for (const p of [path.join(BRAIN, 'decisions', 'active', 'd.md'), path.join(BRAIN, 'decisions') + '/candidates/../active/d.md']) {
      r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: tool, tool_input: at(p) });
      assert.ok(isDeny(r) && r.stdout.includes('decisions/active/'), `${tool} into decisions/active must be denied: ${p} → ${r.stdout}`);
    }
    for (const p of [path.join(BRAIN, 'decisions', 'candidates', 'd.md'), path.join(BRAIN, 'decisions', 'superseded', 'd.md'),
      path.join(BRAIN, 'decisions', 'activex', 'd.md'), path.join(TMP, 'src', 'active', 'd.md')]) {
      r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: tool, tool_input: at(p) });
      assert.strictEqual(r.stdout.trim(), '', `${tool} must pass: ${p} → ${r.stdout}`);
    }
  }

  // 6i-d. P0-09: every brain-promote command the weekly review names passes the guard, so its
  // decision step completes by the brain-promote route (placeholders filled with a file name).
  {
    const skill = fs.readFileSync(path.join(REPO, 'skills', 'brain-weekly-review', 'SKILL.md'), 'utf8');
    const cmds = [...skill.matchAll(/`(node scripts\/brain\/brain-promote\.js [^`]+)`/g)].map(m => m[1].replace(/<[^>]+>/g, '2026-10-21-x'));
    assert.ok(cmds.some(c => /--to active --force/.test(c)) && cmds.some(c => /--to superseded/.test(c)),
      `the weekly review names both brain-promote routes: ${JSON.stringify(cmds)}`);
    for (const c of cmds) assert.strictEqual(denyBash(c).stdout.trim(), '', `weekly-review command must pass: ${c}`);
  }

  // 6i-e. P0-09 background security review ("authorization-bypass" on e8c673e). The G3 change let
  // an rm word pass in any pipeline of programs that never RUN their arguments, but several of
  // those WRITE: git restore/switch/branch, touch, mkdir, find -fprint. Main denied these when a
  // canon file name held "rm". The reader set for G3 is now programs that neither run nor write.
  // The same review closed gaps the new decisions/active/ rule shared with canon/ (writers the
  // mutation words missed, case variants on a case-insensitive disk, symlinked Write paths) and
  // narrowed the G1 script path to this project's scripts/brain/brain-promote.js.
  for (const cmd of [
    // regressions found on e8c673e (main denied each one)
    'git restore --source=HEAD~3 .project-brain/canon/rm-x.md',
    'git restore .project-brain/canon/rm-x.md',
    'touch .project-brain/canon/rm-x.md',
    'mkdir .project-brain/canon/rm-dir',
    'git switch -f rm-branch -- .project-brain/canon',
    'git branch -f rm .project-brain/canon',
    'find .project-brain/canon -name rm -fprint .project-brain/canon/y.md',
    'git log --output=.project-brain/canon/rm-x.md',
    'git diff --output .project-brain/canon/rm-x.md',
    'uniq .project-brain/canon/rm-a.md .project-brain/canon/rm-b.md',
    // writers the mutation words missed, on canon/ and decisions/active/
    'git restore .project-brain/decisions/active/d.md',
    'git checkout -- .project-brain/decisions/active/d.md',
    'git checkout HEAD~3 -- .project-brain/canon/x.md',
    'git restore --source=HEAD~9 .project-brain/decisions/active/rm-x.md',
    'git log --output=.project-brain/decisions/active/d.md',
    'touch .project-brain/decisions/active/new.md',
    'mkdir .project-brain/decisions/active/sub',
    'ln -s /tmp/x .project-brain/decisions/active/new.md',
    'truncate -s0 .project-brain/decisions/active/d.md',
    'dd if=/tmp/x of=.project-brain/decisions/active/d.md',
    'install /tmp/x .project-brain/decisions/active/d.md',
    'rsync /tmp/x .project-brain/decisions/active/d.md',
    'rsync -a --delete /tmp/e/ .project-brain/canon/',
    'tar -xf /tmp/t.tar -C .project-brain/decisions/active',
    'patch .project-brain/decisions/active/d.md /tmp/p.diff',
    // case variants: macOS disks are case-insensitive by default
    'echo x > .PROJECT-BRAIN/decisions/active/d.md',
    'echo x > .Project-Brain/canon/y.md',
    'echo x > .project-brain/decisions/ACTIVE/d.md',
    'echo x > .project-brain/CANON/y.md',
    'rm -rf .PROJECT-BRAIN',
    'cd .Project-Brain && rm -rf decisions',
    // G1: only this project's scripts/brain/brain-promote.js keeps the exemption
    'node /tmp/scripts/brain/brain-promote.js .project-brain/canon/y.md --approve --rm',
    'node /tmp/scripts/brain/brain-promote.js --approve --cp x .project-brain/canon/y.md',
    'node x/scripts/brain/brain-promote.js --approve --cp x .project-brain/canon/y.md',
  ]) {
    assert.ok(isDeny(denyBash(cmd)), `must deny (background review): ${cmd}`);
  }
  for (const cmd of [
    // still allowed: readers of an rm-named canon file, and a promote by this project's path
    'cat .project-brain/canon/rm-notes.md',
    'grep rm .project-brain/canon/x.md',
    'git log --oneline -- .project-brain/canon/rm-x.md',
    'git diff -- .project-brain/canon/rm-x.md',
    'find .project-brain/canon -name "*rm*"',
    `node ${path.join(REPO, 'scripts', 'brain', 'brain-promote.js')} --target .project-brain canon/rm-x.md --approve`,
  ]) {
    r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: cmd } }, REPO);
    assert.strictEqual(r.stdout.trim(), '', `must allow (background review): ${cmd} → ${r.stdout}`);
  }
  // Write/Edit/NotebookEdit through a symlink into the capsule, or with a case variant of a
  // protected folder, are denied.
  seedCapsule();
  fs.symlinkSync(path.join(BRAIN, 'decisions', 'active'), path.join(TMP, 'lnk-active'));
  fs.symlinkSync(path.join(BRAIN, 'canon'), path.join(TMP, 'lnk-canon'));
  for (const tool of ['Write', 'Edit', 'NotebookEdit']) {
    const at = p => (tool === 'NotebookEdit' ? { notebook_path: p, new_source: 'x' } : { file_path: p, content: 'x' });
    for (const p of [path.join(TMP, 'lnk-active', 'd.md'), path.join(TMP, 'lnk-canon', 'new', 'd.md'),
      path.join(TMP, '.PROJECT-BRAIN', 'decisions', 'active', 'd.md'), path.join(BRAIN, 'Decisions', 'Active', 'd.md'),
      path.join(BRAIN, 'CANON', 'd.md')]) {
      r = runHook('brain-security-guard.sh', { hook_event_name: 'PreToolUse', tool_name: tool, tool_input: at(p) });
      assert.ok(isDeny(r), `${tool} must be denied (background review): ${p} → ${r.stdout}`);
    }
  }

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
    // P11 re-review RR3: the git clean dry-run check was /^-[A-Za-z]*n[A-Za-z]*$/, quadratic
    ['git clean option', 'git clean -' + 'n'.repeat(K) + '1 .project-brain'],
    ['many git options', 'git ' + '--bare '.repeat(K / 7) + 'clean .project-brain'],
    // joinLines once read the last character of the string it was building, which flattened it
    // on every # (4 s at 512 KB, 16 s at 1 MB)
    ['comments and continuations', 'ls # x ' + '\\\n#'.repeat(K / 3) + ' .project-brain'],
    // P0-09: the G3 reader check, the G1 one-call check and the decisions/active rule
    ['canon rm readers', '.project-brain/canon/rm ' + '| cat '.repeat(K / 6)],
    ['canon rm words', 'cat .project-brain/canon/x ' + 'rm '.repeat(K / 3)],
    ['canon rm stages', 'cat .project-brain/canon/rm' + ' | grep x'.repeat(K / 9)],
    ['active redirects', '.project-brain/decisions/active/x ' + '2>/dev/null '.repeat(K / 12) + '> y'],
    ['active words', 'cd .project-brain && ' + 'active/ '.repeat(K / 8) + '> x'],
    ['promote args', 'node scripts/brain/brain-promote.js ' + 'a '.repeat(K / 2) + '--approve .project-brain/canon/rm'],
    ['promote chain', 'node scripts/brain/brain-promote.js a --approve' + ' && x'.repeat(K / 5) + ' .project-brain/canon/rm'],
    ['promote path', 'node ' + 'a/'.repeat(K / 2) + 'scripts/brain/brain-promote.js --approve .project-brain/canon/rm'],
  ]) {
    // A runner timeout retries once (F1 quarantine, see runHook); the bound applies to the run kept.
    const { ms } = runHook('brain-security-guard.sh', null, TMP, { retryOnTimeout: true,
      raw: JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: cmd } }) });
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
