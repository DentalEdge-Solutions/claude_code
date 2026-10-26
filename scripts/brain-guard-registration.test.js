#!/usr/bin/env node
// scripts/brain-guard-registration.test.js — the brain security guard's committed registrations
// (P0-09, D-11). Runs each registration the way Claude Code runs an exec-form command hook:
// `${CLAUDE_PROJECT_DIR}` substituted into command and args as a plain string, the same value
// exported as CLAUDE_PROJECT_DIR, the hook input on stdin, no shell
// (code.claude.com/docs/en/hooks, "Exec form and shell form", read 2026-10-26).
//
// - Root .claude/settings.json: the guard on Write|Edit|NotebookEdit|Bash, exec form, timeout 30,
//   onFailure "block". Its path resolves in the checkout that holds the file (the shared-file case:
//   a session started at the repository root or at a worktree's root, whose tracked copy of the
//   file and of hooks/brain/ it reads; V2-RS-11).
// - infra/hermes-agent/.claude/settings.json (sessions started in that folder read it instead of
//   the root file): a launcher that finds the guard whether CLAUDE_PROJECT_DIR is that folder or
//   the repository root, and never blocks because of a path that does not resolve (RK-15).
// - The telemetry hooks stay fail-open (docs/telemetry-privacy.md: a telemetry failure must never
//   block).
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
const ROOT_SETTINGS = path.join(REPO, '.claude', 'settings.json');
const HERMES_DIR = path.join(REPO, 'infra', 'hermes-agent');
const HERMES_SETTINGS = path.join(HERMES_DIR, '.claude', 'settings.json');
const MATCHER = 'Write|Edit|NotebookEdit|Bash|Monitor|PowerShell';
const PB = '.project-' + 'brain';

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}
const settingsOf = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const allHooks = s => Object.entries(s.hooks || {}).flatMap(([ev, list]) =>
  (list || []).filter(Boolean).flatMap(e => (e.hooks || []).filter(Boolean).map(h => ({ ev, matcher: e.matcher, h }))));
const isGuard = h => /brain-security-guard\.sh/.test([h.command, ...(h.args || [])].join(' '));
const guardsIn = s => allHooks(s).filter(x => isGuard(x.h));

// Run one exec-form handler as Claude Code would.
function runHandler(h, projectDir, input, cwd = REPO) {
  const sub = v => v.split('${CLAUDE_PROJECT_DIR}').join(projectDir);
  const r = spawnSync(sub(h.command), (h.args || []).map(sub), {
    input, encoding: 'utf8', timeout: 20000, cwd,
    env: { ...process.env, CLAUDE_PROJECT_DIR: projectDir },
  });
  assert.ok(!r.error, `handler failed to run: ${r.error && r.error.message}`);
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
const canonWrite = dir => JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Write',
  tool_input: { file_path: path.join(dir, PB, 'canon', 'x.md'), content: 'x' } });
const plainBash = JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } });
const isDeny = r => r.stdout.includes('"permissionDecision":"deny"');

const root = settingsOf(ROOT_SETTINGS);
const hermes = settingsOf(HERMES_SETTINGS);

test('root settings.json registers the guard once: exec form, the guarded tools, timeout 30, onFailure block', () => {
  const g = guardsIn(root);
  assert.strictEqual(g.length, 1, `one guard handler, found ${g.length}`);
  assert.strictEqual(g[0].ev, 'PreToolUse');
  assert.strictEqual(g[0].matcher, MATCHER);
  assert.deepStrictEqual(g[0].h, {
    type: 'command', command: 'bash', args: ['${CLAUDE_PROJECT_DIR}/hooks/brain/brain-security-guard.sh'],
    timeout: 30, onFailure: 'block',
  });
});

test('root registration: the path resolves in this checkout and the guard denies a canon write through it', () => {
  const [{ h }] = guardsIn(root);
  assert.ok(fs.existsSync(h.args[0].replace('${CLAUDE_PROJECT_DIR}', REPO)), 'guard path resolves');
  const r = runHandler(h, REPO, canonWrite(REPO));
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(isDeny(r), `canon write denied: ${r.stdout}`);
  const ls = runHandler(h, REPO, plainBash);
  assert.strictEqual(ls.status, 0, ls.stderr);
  assert.strictEqual(ls.stdout.trim(), '', 'an ordinary command passes');
});

test('the telemetry hooks stay fail-open: no onFailure "block" on any non-guard hook in either file', () => {
  for (const s of [root, hermes]) {
    const others = allHooks(s).filter(x => !isGuard(x.h));
    assert.deepStrictEqual(others.filter(x => x.h.onFailure === 'block').map(x => x.h.command), []);
  }
  assert.ok(allHooks(root).some(x => /scripts\/telemetry\//.test(x.h.command)), 'telemetry hooks still registered');
});

test('infra/hermes-agent settings register the guard launcher: the guarded tools, timeout 30, onFailure block', () => {
  const g = guardsIn(hermes);
  assert.strictEqual(g.length, 1, `one guard handler, found ${g.length}`);
  assert.strictEqual(g[0].ev, 'PreToolUse');
  assert.strictEqual(g[0].matcher, MATCHER);
  assert.strictEqual(g[0].h.command, 'bash');
  assert.strictEqual(g[0].h.timeout, 30);
  assert.strictEqual(g[0].h.onFailure, 'block');
  assert.strictEqual(g[0].h.args[g[0].h.args.length - 1], '${CLAUDE_PROJECT_DIR}',
    'the project folder reaches the launcher as its own argument, never inside the script text');
});

test('hermes launcher reaches the guard whether CLAUDE_PROJECT_DIR is infra/hermes-agent, a folder under it, or the repository root', () => {
  const [{ h }] = guardsIn(hermes);
  for (const dir of [HERMES_DIR, path.join(HERMES_DIR, 'bin'), REPO]) {
    const r = runHandler(h, dir, canonWrite(REPO));
    assert.strictEqual(r.status, 0, `${dir}: ${r.stderr}`);
    assert.ok(isDeny(r), `${dir}: canon write denied through the launcher: ${r.stdout}`);
    const ls = runHandler(h, dir, plainBash);
    assert.strictEqual(ls.stdout.trim(), '', `${dir}: an ordinary command passes`);
  }
});

// Background security review (E), "fail-open in infra/hermes-agent/.claude/settings.json": the
// first launcher exited 0 when it found no guard. It now walks up from CLAUDE_PROJECT_DIR (the
// session's starting folder, or the repository root: both hold the guard at or above them) and
// fails closed when no folder up to / holds it, so it never lets a call through unchecked.
test('hermes launcher fails closed when no folder at or above CLAUDE_PROJECT_DIR holds the guard', () => {
  const [{ h }] = guardsIn(hermes);
  const nowhere = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-launcher-'));
  try {
    for (const dir of [nowhere, path.join(nowhere, 'a', 'b'), path.join(nowhere, 'it has "quotes" and $(x)'), '', 'relative/dir']) {
      const r = runHandler(h, dir, plainBash, nowhere); // a relative dir walks up from the hook cwd
      assert.strictEqual(r.status, 2, `${JSON.stringify(dir)}: must block (exit 2): ${r.status} ${r.stdout} ${r.stderr}`);
      assert.match(r.stderr, /brain-security-guard.*not found.*BLOCKED/, `${dir}: stderr says why`);
      assert.match(r.stderr, /SECOND_BRAIN_SECURITY\.md/, `${dir}: stderr points at the break-glass procedure`);
    }
  } finally { fs.rmSync(nowhere, { recursive: true, force: true }); }
});

test('no settings file claims coverage it lacks: no guard handler can exit 0 without running the guard', () => {
  for (const s of [root, hermes]) for (const { h } of guardsIn(s)) {
    assert.ok(!/exit 0/.test((h.args || []).join(' ')), `a guard handler that can exit 0 unchecked: ${JSON.stringify(h)}`);
    assert.strictEqual(h.onFailure, 'block');
  }
});

if (!ok) process.exit(1);
console.log('\nAll brain-guard-registration tests passed.');
