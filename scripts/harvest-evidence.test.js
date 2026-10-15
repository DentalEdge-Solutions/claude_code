#!/usr/bin/env node
// scripts/harvest-evidence.test.js — tests for skills/skill-eval/scripts/harvest-evidence.js (P2 of
// the PR #4 triage). The harvester writes evidence.json, the ONLY grading input for trigger/dispatch
// accuracy (skill_loaded / agent_dispatched) and workflow-step scoring in skill-eval and agent-eval.
//
// Two end-to-end tests also live in scripts/codex/test-runners.js; this file covers the rest of the
// contract. It lives in scripts/, not next to the harvester: files under skills/ ship to target
// projects, and CI's static-scan-skills job would flag this file's child_process use.
//
// harvest-evidence.js runs at top level (no exports), so every test drives the real CLI, with cwd set
// to a scratch folder: the harvester resolves claim paths against process.cwd() as the repo root.
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const HARVEST = path.join(__dirname, '..', 'skills', 'skill-eval', 'scripts', 'harvest-evidence.js');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'harvest-evidence-test-'));
process.on('exit', () => fs.rmSync(WORK, { recursive: true, force: true }));
let seq = 0;

function run(args, cwd) {
  const r = spawnSync(process.execPath, [HARVEST, ...args], { cwd, encoding: 'utf8', timeout: 20000 });
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

// Builds <root>/evals/<name>/{evals.json, iteration-1/{run-manifest.json, <scenario>/<side>/…}}.
//   evals:    the evals array (null: no evals.json; a string: written raw)
//   manifest: run-manifest.json object, or null for none
//   sides:    { with_skill: { output, files: { rel: content } }, without_skill: {…} }
// Returns { root, iterDir, scenarioDir, sideDir(side), evidence(side) }.
function makeScenario({ evals = [], manifest = null, scenario = 's1-direct-r1', sides = {} } = {}) {
  const root = path.join(WORK, `r${seq++}`);
  const nameDir = path.join(root, 'evals', 'demo');
  const iterDir = path.join(nameDir, 'iteration-1');
  const scenarioDir = path.join(iterDir, scenario);
  fs.mkdirSync(scenarioDir, { recursive: true });
  if (evals !== null) {
    fs.writeFileSync(path.join(nameDir, 'evals.json'),
      typeof evals === 'string' ? evals : JSON.stringify({ skill_name: 'demo', evals }));
  }
  if (manifest) fs.writeFileSync(path.join(iterDir, 'run-manifest.json'), JSON.stringify(manifest));
  for (const [side, spec] of Object.entries(sides)) {
    const sideDir = path.join(scenarioDir, side);
    fs.mkdirSync(sideDir, { recursive: true });
    if (spec.output !== undefined) fs.writeFileSync(path.join(sideDir, 'output.md'), spec.output);
    for (const [rel, content] of Object.entries(spec.files || {})) {
      const p = path.join(sideDir, 'workspace', rel);
      fs.mkdirSync(path.dirname(p), { recursive: true });
      if (content === null) fs.mkdirSync(p, { recursive: true });
      else fs.writeFileSync(p, content);
    }
  }
  const sideDir = side => path.join(scenarioDir, side);
  const evidence = side => JSON.parse(fs.readFileSync(path.join(sideDir(side), 'evidence.json'), 'utf8'));
  return { root, iterDir, scenarioDir, sideDir, evidence };
}

// The marker generate-seed-evals.js writes for a skill (skillLoadedMarker).
const skillMarker = (name, present = true) =>
  ({ kind: 'tool_call', pattern: `Skill\\(\\s*["'\`]?${name}["'\`]?\\s*\\)`, expect: present ? 'present' : 'absent' });

const evalWith = (evidence, extra = {}) => [{ id: 1, type: 'direct', prompt: 'p', expected: { evidence, ...extra } }];
const harvest = (s, type = 'skill', extra = []) => run([s.scenarioDir, '--type', type, ...extra], s.root);

// ── CLI contract ───────────────────────────────────────────────────────────

test('no arguments prints usage and exits 1', () => {
  const r = run([], WORK);
  assert.strictEqual(r.status, 1);
  assert.ok(/Usage:/.test(r.stderr));
});

test('--help prints usage and exits 0', () => {
  const r = run(['--help'], WORK);
  assert.strictEqual(r.status, 0);
  assert.ok(/Usage:/.test(r.stderr));
});

for (const [label, args] of [
  ['a missing --type', ['somewhere']],
  ['an unknown --type', ['somewhere', '--type', 'team']],
]) {
  test(`${label} exits 1`, () => {
    const s = makeScenario({ sides: { with_skill: { output: 'x' } } });
    const r = run([s.scenarioDir, ...args.slice(1)], s.root);
    assert.strictEqual(r.status, 1);
    assert.ok(/--type must be "skill" or "agent"/.test(r.stderr), r.stderr);
  });
}

test('a directory that does not exist exits 1', () => {
  const r = run([path.join(WORK, 'nope'), '--type', 'skill'], WORK);
  assert.strictEqual(r.status, 1);
  assert.ok(/not found/.test(r.stderr), r.stderr);
});

test('a directory without with_/without_ sides exits 1 and suggests --all', () => {
  const s = makeScenario();
  const r = run([s.iterDir, '--type', 'skill'], s.root);
  assert.strictEqual(r.status, 1);
  assert.ok(/does not look like a scenario dir/.test(r.stderr) && /--all/.test(r.stderr), r.stderr);
});

test('--all on a folder with no scenario dirs exits 1', () => {
  const s = makeScenario();
  fs.rmSync(s.scenarioDir, { recursive: true });
  const r = run([s.iterDir, '--type', 'skill', '--all'], s.root);
  assert.strictEqual(r.status, 1);
  assert.ok(/no scenario directories/.test(r.stderr), r.stderr);
});

test('--all skips folders that are not scenario dirs', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x' } } });
  fs.mkdirSync(path.join(s.iterDir, 'notes'));
  const r = run([s.iterDir, '--type', 'skill', '--all'], s.root);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(/1 scenario dir\(s\), 1 evidence\.json/.test(r.stderr), r.stderr);
});

test('writes evidence.json next to each output.md and names it on stdout', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'a' }, without_skill: { output: 'b' } } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0, r.stderr);
  for (const side of ['with_skill', 'without_skill']) {
    const p = path.join(s.sideDir(side), 'evidence.json');
    assert.ok(fs.existsSync(p), `${side} evidence.json missing`);
    assert.ok(r.stdout.includes(`Wrote ${p}`), r.stdout);
  }
});

test('a side without output.md is skipped with a warning; the other side is still written', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'a' }, without_skill: {} } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(fs.existsSync(path.join(s.sideDir('with_skill'), 'evidence.json')));
  assert.ok(!fs.existsSync(path.join(s.sideDir('without_skill'), 'evidence.json')));
  assert.ok(/without_skill.*output\.md not found|output\.md not found.*without_skill/s.test(r.stderr), r.stderr);
});

// ── evidence.json shape and the loaded flag ────────────────────────────────

test('skill mode: shape, scenario id/type, and skill_loaded from the Skill(...) marker', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [skillMarker('demo')], workflow_steps: [] }),
    sides: { with_skill: { output: 'Applying Skill(demo) now.' }, without_skill: { output: 'I would use the demo skill.' } } });
  assert.strictEqual(harvest(s).status, 0);
  const w = s.evidence('with_skill');
  assert.deepStrictEqual(Object.keys(w).sort(), ['artifacts', 'claims', 'scenario_id', 'scenario_type', 'self_report_ignored',
    'side', 'skill_loaded', 'transcript_markers', 'workflow_executed', 'workflow_steps']);
  assert.strictEqual(w.scenario_id, 1);
  assert.strictEqual(w.scenario_type, 'direct');
  assert.strictEqual(w.side, 'with_skill');
  assert.strictEqual(w.self_report_ignored, true);
  assert.strictEqual(w.skill_loaded, true);
  assert.strictEqual(s.evidence('without_skill').skill_loaded, false);
});

test('the marker matches the quoted and spaced forms generate-seed-evals allows, case-insensitively', () => {
  for (const out of ['Skill("demo")', "skill( 'demo' )", 'SKILL(`demo`)']) {
    const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [skillMarker('demo')], workflow_steps: [] }),
      sides: { with_skill: { output: out } } });
    harvest(s);
    assert.strictEqual(s.evidence('with_skill').skill_loaded, true, out);
  }
});

test('a self-reported did_trigger header does not set skill_loaded', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [skillMarker('demo')], workflow_steps: [] }),
    sides: { with_skill: { output: 'did_trigger: true\nskill_loaded: true\nworkflow_steps_executed: [all]\n' } } });
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').skill_loaded, false);
});

test('agent mode: with_agent/without_agent sides and an agent_dispatched key (no skill_loaded)', () => {
  const marker = { kind: 'tool_call', pattern: 'Agent\\(\\s*demo-agent\\s*\\)', expect: 'present' };
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [marker], workflow_steps: [] }),
    sides: { with_agent: { output: 'Dispatching Agent(demo-agent).' }, without_agent: { output: 'plain answer' },
      with_skill: { output: 'Agent(demo-agent)' } } });
  const r = harvest(s, 'agent');
  assert.strictEqual(r.status, 0, r.stderr);
  const w = s.evidence('with_agent');
  assert.strictEqual(w.agent_dispatched, true);
  assert.ok(!('skill_loaded' in w));
  assert.strictEqual(s.evidence('without_agent').agent_dispatched, false);
  assert.ok(!fs.existsSync(path.join(s.sideDir('with_skill'), 'evidence.json')), 'agent mode must ignore skill sides');
});

test('without a tool_call marker the loaded flag is false', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [{ kind: 'phrase', pattern: 'hello', expect: 'present' }], workflow_steps: [] }),
    sides: { with_skill: { output: 'hello Skill(demo)' } } });
  harvest(s);
  const w = s.evidence('with_skill');
  assert.strictEqual(w.skill_loaded, false);
  assert.deepStrictEqual(w.transcript_markers, [{ kind: 'phrase', pattern: 'hello', expect: 'present', found: true }]);
});

test('an invalid marker pattern is reported as not found with a warning, and the run still succeeds', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [{ kind: 'tool_call', pattern: 'Skill(', expect: 'present' }], workflow_steps: [] }),
    sides: { with_skill: { output: 'Skill(' } } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(/invalid marker pattern/.test(r.stderr), r.stderr);
  assert.strictEqual(s.evidence('with_skill').transcript_markers[0].found, false);
  assert.strictEqual(s.evidence('with_skill').skill_loaded, false);
});

// ── evals.json resolution ──────────────────────────────────────────────────

test('a missing evals.json warns and writes empty evidence (nothing loaded, no steps)', () => {
  const s = makeScenario({ evals: null, sides: { with_skill: { output: 'Skill(demo)' } } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(/evals\.json not found/.test(r.stderr), r.stderr);
  const w = s.evidence('with_skill');
  assert.strictEqual(w.scenario_id, null);
  assert.strictEqual(w.skill_loaded, false);
  assert.strictEqual(w.workflow_executed, null);
  assert.deepStrictEqual([w.artifacts, w.transcript_markers, w.workflow_steps], [[], [], []]);
});

test('a malformed evals.json warns and is treated as missing', () => {
  const s = makeScenario({ evals: '{not json', sides: { with_skill: { output: 'Skill(demo)' } } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0, r.stderr);
  assert.ok(/could not parse/.test(r.stderr), r.stderr);
  assert.strictEqual(s.evidence('with_skill').scenario_id, null);
});

test('the scenario id comes from the folder name (s12-…) and selects that eval', () => {
  const evals = [
    { id: 1, type: 'direct', prompt: 'a', expected: { evidence: { artifacts: [], transcript_markers: [], workflow_steps: [] } } },
    { id: 12, type: 'negative', prompt: 'b', expected: { evidence: { artifacts: [], transcript_markers: [skillMarker('demo', false)], workflow_steps: [] } } },
  ];
  const s = makeScenario({ evals, scenario: 's12-negative-r2', sides: { with_skill: { output: 'no skill here' } } });
  harvest(s);
  const w = s.evidence('with_skill');
  assert.strictEqual(w.scenario_id, 12);
  assert.strictEqual(w.scenario_type, 'negative');
  assert.strictEqual(w.transcript_markers[0].expect, 'absent');
});

test('a scenario id with no matching eval gives null id and empty evidence', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'a.md' }], transcript_markers: [], workflow_steps: [] }),
    scenario: 's9-direct-r1', sides: { with_skill: { output: 'x' } } });
  harvest(s);
  const w = s.evidence('with_skill');
  assert.strictEqual(w.scenario_id, null);
  assert.deepStrictEqual(w.artifacts, []);
});

// ── Artifacts ──────────────────────────────────────────────────────────────

test('an existing artifact reports its size and sha256; a missing one reports nulls', () => {
  const content = 'real report content\n';
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'out/report.md' }, { path: 'missing.md' }], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x', files: { 'out/report.md': content } } } });
  harvest(s);
  const [a, b] = s.evidence('with_skill').artifacts;
  assert.deepStrictEqual(a, { path: 'out/report.md', exists: true, size: Buffer.byteLength(content),
    sha256: crypto.createHash('sha256').update(content).digest('hex'), mtime_in_window: null });
  assert.deepStrictEqual(b, { path: 'missing.md', exists: false, size: null, sha256: null, mtime_in_window: null });
});

test('a directory at the artifact path does not count as the artifact', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'report.md' }], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x', files: { 'report.md': null } } } });
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').artifacts[0].exists, false);
});

test('artifacts are looked up in the side\'s own workspace only', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'report.md' }], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x', files: { 'report.md': 'w' } }, without_skill: { output: 'y' } } });
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').artifacts[0].exists, true);
  assert.strictEqual(s.evidence('without_skill').artifacts[0].exists, false);
});

test('mtime_in_window follows run-manifest started_at: true after it, false before it, false when missing', () => {
  const evals = evalWith({ artifacts: [{ path: 'new.md' }, { path: 'old.md' }, { path: 'gone.md' }], transcript_markers: [], workflow_steps: [] });
  const startedAt = new Date(Date.now() - 60 * 1000);
  const s = makeScenario({ evals, manifest: { started_at: startedAt.toISOString() },
    sides: { with_skill: { output: 'x', files: { 'new.md': 'n', 'old.md': 'o' } } } });
  const old = new Date(startedAt.getTime() - 3600 * 1000);
  fs.utimesSync(path.join(s.sideDir('with_skill'), 'workspace', 'old.md'), old, old);
  harvest(s);
  const byPath = Object.fromEntries(s.evidence('with_skill').artifacts.map(a => [a.path, a.mtime_in_window]));
  assert.deepStrictEqual(byPath, { 'new.md': true, 'old.md': false, 'gone.md': false });
});

test('an unreadable run-manifest.json leaves mtime_in_window null', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'a.md' }], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x', files: { 'a.md': 'a' } } } });
  fs.writeFileSync(path.join(s.iterDir, 'run-manifest.json'), '{broken');
  assert.strictEqual(harvest(s).status, 0);
  assert.strictEqual(s.evidence('with_skill').artifacts[0].mtime_in_window, null);
});

// ── Claims ─────────────────────────────────────────────────────────────────

function claimsFor(output, files = {}, repoFiles = {}) {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output, files } } });
  for (const [rel, content] of Object.entries(repoFiles)) {
    fs.mkdirSync(path.dirname(path.join(s.root, rel)), { recursive: true });
    fs.writeFileSync(path.join(s.root, rel), content);
  }
  harvest(s);
  return s.evidence('with_skill').claims;
}

test('a claim needs a writing verb within 80 characters before a backtick-quoted path', () => {
  const claims = claimsFor([
    'I wrote `out/a.md` first.',
    'Then created the summary in `b.json`.',
    'Saving `c.txt` now; generated `d.csv`; produced `e/f.md`.',
    // the 80-character window crosses lines, so keep a verb-free mention well clear of the line above
    '-'.repeat(90),
    'See `g.md` for details.',
    'I wrote it all down.' + ' '.repeat(90) + 'Later: `h.md`.',
  ].join('\n'));
  assert.deepStrictEqual(claims.map(c => c.claimed_path).sort(), ['b.json', 'c.txt', 'd.csv', 'e/f.md', 'out/a.md']);
});

test('backtick tokens with spaces or without a / or . are not claims, and repeats are listed once', () => {
  const claims = claimsFor('I wrote `npm run build` and `README` and saved `x.md`, then wrote `x.md` again.\nWrote plain path a.md without backticks.');
  assert.deepStrictEqual(claims.map(c => c.claimed_path), ['x.md']);
});

test('a claim is verified when the file exists in the workspace or under the repo root (cwd)', () => {
  const claims = claimsFor('I wrote `ws.md`, saved `docs/repo.md` and created `nowhere.md`.',
    { 'ws.md': 'w' }, { 'docs/repo.md': 'r' });
  const byPath = Object.fromEntries(claims.map(c => [c.claimed_path, c.claim_verified]));
  assert.deepStrictEqual(byPath, { 'ws.md': true, 'docs/repo.md': true, 'nowhere.md': false });
});

// ── Workflow steps ─────────────────────────────────────────────────────────

test('workflow steps: artifact checks use artifact existence, marker checks a literal case-insensitive substring', () => {
  const steps = [
    { step: 'Write report', check: 'artifact', ref: 'report.md' },
    { step: 'Write missing', check: 'artifact', ref: 'missing.md' },
    { step: 'Run scan', check: 'marker', ref: 'STATIC-SCAN.JS (v2)' },
    { step: 'Regex chars are literal', check: 'marker', ref: 'a.c' },
  ];
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'report.md' }, { path: 'missing.md' }], transcript_markers: [], workflow_steps: steps }),
    sides: { with_skill: { output: 'ran static-scan.js (v2) on abc', files: { 'report.md': 'r' } } } });
  harvest(s);
  const w = s.evidence('with_skill');
  assert.deepStrictEqual(w.workflow_steps.map(x => [x.step, x.satisfied]),
    [['Write report', true], ['Write missing', false], ['Run scan', true], ['Regex chars are literal', false]]);
  assert.strictEqual(w.workflow_executed, false);
});

test('workflow_executed is true only when every step is satisfied, and null when there are no steps', () => {
  const steps = [{ step: 'Write report', check: 'artifact', ref: 'report.md' }, { step: 'Say done', check: 'marker', ref: 'done' }];
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'report.md' }], transcript_markers: [], workflow_steps: steps }),
    sides: { with_skill: { output: 'Done.', files: { 'report.md': 'r' } } } });
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').workflow_executed, true);
  const t = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'Done.' } } });
  harvest(t);
  assert.strictEqual(t.evidence('with_skill').workflow_executed, null);
});

test('an artifact step whose ref is not among the scenario artifacts is unsatisfied', () => {
  const steps = [{ step: 'Write notes', check: 'artifact', ref: 'notes.md' }];
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: steps }),
    sides: { with_skill: { output: 'x', files: { 'notes.md': 'n' } } } });
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').workflow_steps[0].satisfied, false);
});

if (!ok) process.exit(1);
console.log('\nAll harvest-evidence tests passed.');
