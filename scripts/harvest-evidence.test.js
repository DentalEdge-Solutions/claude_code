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

test('E3: an invalid started_at warns and leaves mtime_in_window null, for found and missing artifacts', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'a.md' }, { path: 'gone.md' }], transcript_markers: [], workflow_steps: [] }),
    manifest: { started_at: 'not-a-date' }, sides: { with_skill: { output: 'x', files: { 'a.md': 'a' } } } });
  const r = harvest(s);
  assert.strictEqual(r.status, 0);
  assert.deepStrictEqual(s.evidence('with_skill').artifacts.map(a => a.mtime_in_window), [null, null]);
  assert.match(r.stderr, /started_at/);
});

// E1 (P2 findings): an artifact counts only when it resolves to a regular file inside the side's own
// workspace. A link to a file outside, a linked folder that leads outside, or a spec path that climbs out
// would otherwise satisfy an artifact workflow step without the run writing anything.
function linkCase({ files = {}, links = {}, artifact = 'report.md', outside = {} }) {
  const steps = [{ step: 'Write report', check: 'artifact', ref: artifact }];
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: artifact }], transcript_markers: [], workflow_steps: steps }),
    sides: { with_skill: { output: 'x', files } } });
  const outDir = path.join(s.root, 'outside');
  for (const [rel, content] of Object.entries(outside)) {
    fs.mkdirSync(path.dirname(path.join(outDir, rel)), { recursive: true });
    fs.writeFileSync(path.join(outDir, rel), content);
  }
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  fs.mkdirSync(ws, { recursive: true });
  for (const [rel, target] of Object.entries(links)) {
    const to = target.startsWith('outside/') ? path.join(s.root, target) : path.join(ws, target);
    fs.mkdirSync(path.dirname(path.join(ws, rel)), { recursive: true });
    fs.symlinkSync(to, path.join(ws, rel));
  }
  const r = harvest(s);
  return { r, w: s.evidence('with_skill') };
}

for (const [label, spec] of [
  ['a link to a file outside the workspace', { outside: { 'old.md': 'old' }, links: { 'report.md': 'outside/old.md' } }],
  ['a linked folder that leads outside', { outside: { 'dir/report.md': 'old' }, links: { out: 'outside/dir' }, artifact: 'out/report.md' }],
  // the workspace sits six levels below the scratch root: evals/demo/iteration-1/s1-direct-r1/with_skill/workspace
  ['a spec path that climbs out of the workspace', { outside: { 'report.md': 'old' }, artifact: '../'.repeat(6) + 'outside/report.md' }],
]) {
  test(`E1: ${label} is not an artifact, and the step is unsatisfied`, () => {
    const { r, w } = linkCase(spec);
    assert.strictEqual(r.status, 0, r.stderr);
    assert.strictEqual(w.artifacts[0].exists, false, JSON.stringify(w.artifacts[0]));
    assert.strictEqual(w.artifacts[0].sha256, null);
    assert.strictEqual(w.workflow_steps[0].satisfied, false);
    assert.strictEqual(w.workflow_executed, false);
    assert.ok(/outside the workspace/.test(r.stderr), r.stderr);
  });
}

test('E1: a sibling folder whose name starts with "workspace" is outside', () => {
  const steps = [{ step: 'Write report', check: 'artifact', ref: '../workspace-evil/report.md' }];
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: '../workspace-evil/report.md' }], transcript_markers: [], workflow_steps: steps }),
    sides: { with_skill: { output: 'x', files: { 'keep.md': 'k' } } } });
  const evil = path.join(s.sideDir('with_skill'), 'workspace-evil');
  fs.mkdirSync(evil, { recursive: true });
  fs.writeFileSync(path.join(evil, 'report.md'), 'planted');
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').artifacts[0].exists, false);
});

test('E1: a link to another file inside the same workspace still counts', () => {
  const { w } = linkCase({ files: { 'real.md': 'r' }, links: { 'report.md': 'real.md' } });
  assert.strictEqual(w.artifacts[0].exists, true);
  assert.strictEqual(w.workflow_executed, true);
});

test('E1: a broken link is not an artifact', () => {
  const { r, w } = linkCase({ links: { 'report.md': 'outside/never-written.md' } });
  assert.strictEqual(r.status, 0, r.stderr);
  assert.strictEqual(w.artifacts[0].exists, false);
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

test('a claim is verified by a file in the workspace, or by a repo-root (cwd) path into this side\'s folder', () => {
  const claims = claimsFor('I wrote `ws.md`, saved `evals/demo/iteration-1/s1-direct-r1/with_skill/workspace/ws.md`, '
    + 'saved `docs/repo.md` and created `nowhere.md`.', { 'ws.md': 'w' }, { 'docs/repo.md': 'r' });
  const byPath = Object.fromEntries(claims.map(c => [c.claimed_path, c.claim_verified]));
  assert.deepStrictEqual(byPath, { 'ws.md': true, 'evals/demo/iteration-1/s1-direct-r1/with_skill/workspace/ws.md': true,
    'docs/repo.md': false, 'nowhere.md': false });
});

// E2–E5 (P2 findings): a claim is verified only by a file the run could have written: inside the
// side's workspace or the repo root, links followed, and changed since started_at when it is known.
// The claim window stops at the end of the previous sentence.

// Like claimsFor, plus a run-manifest and per-file ages: ages = { 'ws:a.md' | 'repo:docs/a.md': ms before now }.
function claimsWithWindow(output, { files = {}, repoFiles = {}, startedAt, ages = {} } = {}) {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    manifest: startedAt === undefined ? null : { started_at: startedAt },
    sides: { with_skill: { output, files } } });
  for (const [rel, content] of Object.entries(repoFiles)) {
    fs.mkdirSync(path.dirname(path.join(s.root, rel)), { recursive: true });
    fs.writeFileSync(path.join(s.root, rel), content);
  }
  for (const [key, ms] of Object.entries(ages)) {
    const [where, rel] = key.split(/:(.*)/s);
    const p = where === 'ws' ? path.join(s.sideDir('with_skill'), 'workspace', rel) : path.join(s.root, rel);
    const t = new Date(Date.now() - ms);
    fs.utimesSync(p, t, t);
  }
  const r = harvest(s);
  return { s, r, byPath: Object.fromEntries(s.evidence('with_skill').claims.map(c => [c.claimed_path, c.claim_verified])) };
}

test('E2: a claim path that climbs out of the workspace and the repo root is not verified', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x' } } });
  const outside = path.join(WORK, `outside-${seq++}.md`);
  fs.writeFileSync(outside, 'o');
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  fs.mkdirSync(ws, { recursive: true });
  const fromWs = path.relative(ws, outside);
  const fromRepo = path.relative(s.root, outside);
  fs.writeFileSync(path.join(s.sideDir('with_skill'), 'output.md'),
    `I wrote \`${fromWs}\` and saved \`${fromRepo}\` and created \`${outside}\`.`);
  harvest(s);
  const claims = s.evidence('with_skill').claims;
  assert.strictEqual(claims.length, 3, JSON.stringify(claims));
  for (const c of claims) assert.strictEqual(c.claim_verified, false, c.claimed_path);
});

test('E2: a workspace link to a file outside does not verify a claim; a link inside still does', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'I wrote `out.md` and saved `in.md`.', files: { 'real.md': 'r' } } } });
  const outside = path.join(WORK, `outside-${seq++}.md`);
  fs.writeFileSync(outside, 'o');
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  fs.symlinkSync(outside, path.join(ws, 'out.md'));
  fs.symlinkSync(path.join(ws, 'real.md'), path.join(ws, 'in.md'));
  harvest(s);
  const byPath = Object.fromEntries(s.evidence('with_skill').claims.map(c => [c.claimed_path, c.claim_verified]));
  assert.deepStrictEqual(byPath, { 'out.md': false, 'in.md': true });
});

test('E2: an absolute claim path inside the workspace is verified', () => {
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    sides: { with_skill: { output: 'x', files: { 'abs.md': 'a' } } } });
  const abs = path.join(s.sideDir('with_skill'), 'workspace', 'abs.md');
  fs.writeFileSync(path.join(s.sideDir('with_skill'), 'output.md'), `I wrote \`${abs}\`.`);
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').claims[0].claim_verified, true);
});

test('E4: with a run window, a claimed file not changed since started_at is not verified', () => {
  const startedAt = new Date(Date.now() - 60 * 1000).toISOString();
  const { byPath } = claimsWithWindow(
    'I wrote `new.md`, saved `old.md`, created `README.md` and generated `docs/fresh.md`.',
    { files: { 'new.md': 'n', 'old.md': 'o' }, repoFiles: { 'README.md': 'r', 'docs/fresh.md': 'f' }, startedAt,
      ages: { 'ws:old.md': 3600 * 1000, 'repo:README.md': 3600 * 1000 } });
  // docs/fresh.md changed in the window but is outside this side's folder (review V3)
  assert.deepStrictEqual(byPath, { 'new.md': true, 'old.md': false, 'README.md': false, 'docs/fresh.md': false });
});

test('E4: without a run window, an existing old file is still verified (existence is all that can be checked)', () => {
  const { byPath } = claimsWithWindow('I wrote `old.md`.', { files: { 'old.md': 'o' }, ages: { 'ws:old.md': 3600 * 1000 } });
  assert.deepStrictEqual(byPath, { 'old.md': true });
});

test('E5: the claim window stops at the end of the previous sentence', () => {
  const claims = claimsFor([
    'I produced `a.md`.',
    'See `b.md` for details.',
    'I wrote `c.md`. Then read `d.md` again!',
    'Saved it? Open `e.md` next.',
  ].join('\n'));
  assert.deepStrictEqual(claims.map(c => c.claimed_path).sort(), ['a.md', 'c.md']);
});


test('E5: list, heading and abbreviation formats keep their claims (review V1)', () => {
  const cases = {
    'Created:\n1. `n1.md`\n2. `n2.md`': ['n1.md', 'n2.md'],
    'I created the following files:\n\n- `report.md`\n- `summary.md`': ['report.md', 'summary.md'],
    '## Files created\n\n`h.md`': ['h.md'],
    'I wrote, e.g. `eg.md`, etc. `etc.md`': ['eg.md', 'etc.md'],
    'Files created:\n- `d1.md`.\n- `d2.md`.': ['d1.md', 'd2.md'],
    'I created these files:\n1. Main report `m1.md`\n2. Summary `m2.md`': ['m1.md', 'm2.md'],
    'Created:\n  10. Report: `m3.md`': ['m3.md'],
    'I created files, e.g. the `lc.md`': ['lc.md'],
  };
  for (const [output, expected] of Object.entries(cases)) {
    assert.deepStrictEqual(claimsFor(output).map(c => c.claimed_path).sort(), expected, JSON.stringify(output));
  }
});

test('E5: a sentence ends at ! or ?, after a closing quote or bracket, and across CRLF (review V2, V5)', () => {
  const cases = {
    'Done! I produced `a.md`. See `b.md`.': ['a.md'],
    'I wrote it all! See `x.md`.': [],
    'I wrote `a2.md`. Éste es `b2.md`.': ['a2.md'],
    'I wrote it.") See `q.md`.': [],
    'I wrote it.) See `r.md`.': [],
    'I produced `c.md`.\r\nSee `d.md`.\r\n': ['c.md'],
  };
  for (const [output, expected] of Object.entries(cases)) {
    assert.deepStrictEqual(claimsFor(output).map(c => c.claimed_path).sort(), expected, JSON.stringify(output));
  }
});

test('E4: only paths inside this side\'s folder verify — not evals.json, the other side or other repo files (review V3)', () => {
  const startedAt = new Date(Date.now() - 60 * 1000).toISOString();
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    manifest: { started_at: startedAt },
    sides: { with_skill: { output: 'x', files: { 'mine.md': 'm' } }, without_skill: { output: 'y', files: { 'theirs.md': 't' } } } });
  fs.mkdirSync(path.join(s.root, 'docs'), { recursive: true });
  fs.writeFileSync(path.join(s.root, 'docs', 'touched.md'), 'changed during the run');
  const rel = p => path.relative(s.root, p);
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  const claimed = {
    [rel(path.join(ws, 'mine.md'))]: true,
    [rel(path.join(s.sideDir('with_skill'), 'output.md'))]: true,
    [rel(path.join(s.root, 'evals', 'demo', 'evals.json'))]: false,
    [rel(path.join(s.sideDir('without_skill'), 'workspace', 'theirs.md'))]: false,
    'docs/touched.md': false,
  };
  fs.writeFileSync(path.join(s.sideDir('with_skill'), 'output.md'),
    Object.keys(claimed).map(p => `I wrote \`${p}\`.`).join('\n'));
  harvest(s);
  const byPath = Object.fromEntries(s.evidence('with_skill').claims.map(c => [c.claimed_path, c.claim_verified]));
  assert.deepStrictEqual(byPath, claimed);
});

test('E4: a new link to an old file is not "written" in the run window (the file\'s time counts, review V5)', () => {
  const startedAt = new Date(Date.now() - 60 * 1000).toISOString();
  const s = makeScenario({ evals: evalWith({ artifacts: [], transcript_markers: [], workflow_steps: [] }),
    manifest: { started_at: startedAt },
    sides: { with_skill: { output: 'I wrote `link.md`.', files: { 'old.md': 'o' } } } });
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  const old = new Date(Date.now() - 3600 * 1000);
  fs.utimesSync(path.join(ws, 'old.md'), old, old);
  fs.symlinkSync(path.join(ws, 'old.md'), path.join(ws, 'link.md'));
  harvest(s);
  assert.strictEqual(s.evidence('with_skill').claims[0].claim_verified, false);
});

test('the run window allows 2 s for coarse file times: 1 s before started_at is in, 3 s before is out (review V6)', () => {
  const started = Date.now() - 60 * 1000;
  const s = makeScenario({ evals: evalWith({ artifacts: [{ path: 'near.md' }, { path: 'far.md' }], transcript_markers: [], workflow_steps: [] }),
    manifest: { started_at: new Date(started).toISOString() },
    sides: { with_skill: { output: 'I wrote `near.md` and `far.md`.', files: { 'near.md': 'n', 'far.md': 'f' } } } });
  const ws = path.join(s.sideDir('with_skill'), 'workspace');
  fs.utimesSync(path.join(ws, 'near.md'), new Date(started - 1000), new Date(started - 1000));
  fs.utimesSync(path.join(ws, 'far.md'), new Date(started - 3000), new Date(started - 3000));
  harvest(s);
  const e = s.evidence('with_skill');
  assert.deepStrictEqual(e.artifacts.map(a => a.mtime_in_window), [true, false]);
  assert.deepStrictEqual(Object.fromEntries(e.claims.map(c => [c.claimed_path, c.claim_verified])), { 'near.md': true, 'far.md': false });
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
