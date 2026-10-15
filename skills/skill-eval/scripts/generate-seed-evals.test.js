// skills/skill-eval/scripts/generate-seed-evals.test.js
'use strict';
const { execFileSync } = require('child_process');
const fs   = require('fs');
const path = require('path');
const assert = require('assert');

const TMP = path.join(__dirname, '__test_tmp__');
const SKILL_DIR = path.join(TMP, 'skills', 'test-skill');
const EVALS_DIR = path.join(TMP, 'evals', 'test-skill');
const SKILL_FILE = path.join(SKILL_DIR, 'SKILL.md');
const SCRIPT = path.join(__dirname, 'generate-seed-evals.js');

// Sample skill file content
const SKILL_CONTENT = `---
name: test-skill
description: Runs automated tests for a codebase, executes the test suite, or checks test results. Use when running automated tests, executing the test suite, checking test results, or measuring test coverage.
---

# Test Skill

## Workflow

1. **Read the test config** — read \`skills/<skill-name>/test-config.json\` or the project's test config.
2. **Execute the test suite** — run the test command.
3. **Report results** — summarise pass/fail counts and coverage.
`;

const CTX_CONTENT = JSON.stringify({
  project_name: 'my-project',
  stack: ['Node.js', 'Jest'],
  workflow_terms: ['CI', 'coverage'],
  installed_skills: ['skill-eval', 'test-skill', 'skill-adapt'],
  key_phrases: ['test suite', 'coverage report'],
  artifact_paths: ['evals/'],
  hooks: [{ command: 'pre-commit-lint.js' }],
  mcp_servers: [],
  plugins: [],
});

function setup() {
  fs.mkdirSync(SKILL_DIR, { recursive: true });
  fs.mkdirSync(path.join(TMP, 'evals'), { recursive: true });
  fs.writeFileSync(SKILL_FILE, SKILL_CONTENT);
}

function teardown() {
  fs.rmSync(TMP, { recursive: true, force: true });
}

// execFileSync with an argument list: no shell in between.
function run(extraArgs = []) {
  execFileSync(
    process.execPath, [SCRIPT, SKILL_FILE, ...extraArgs],
    { cwd: TMP, stdio: 'pipe' }
  );
  return JSON.parse(fs.readFileSync(path.join(EVALS_DIR, 'evals.json'), 'utf8'));
}

// Minimal structural validator mirroring schemas/evals.schema.json — no AJV,
// same "no-dependency" pattern as scripts/codex/test-schemas.js.
function validateEvalsFile(data) {
  const errors = [];
  for (const k of ['skill_name', 'generated_from', 'project_context', 'evals']) {
    if (!(k in data)) errors.push(`missing top-level field: ${k}`);
  }
  if (!Array.isArray(data.evals)) { errors.push('evals must be an array'); return errors; }
  for (const sc of data.evals) {
    for (const k of ['id', 'eval_name', 'type', 'prompt', 'expected']) {
      if (!(k in sc)) errors.push(`scenario ${sc.id}: missing ${k}`);
    }
    const exp = sc.expected || {};
    if (!('evidence' in exp)) errors.push(`scenario ${sc.id}: expected.evidence missing`);
    if (!Array.isArray(exp.judgment) || exp.judgment.length === 0) {
      errors.push(`scenario ${sc.id}: expected.judgment must be a non-empty array`);
    }
    const ev = exp.evidence || {};
    for (const k of ['artifacts', 'transcript_markers', 'workflow_steps']) {
      if (!Array.isArray(ev[k])) errors.push(`scenario ${sc.id}: evidence.${k} must be an array`);
    }
    for (const a of ev.artifacts || []) {
      if (typeof a.path !== 'string' || typeof a.must_exist !== 'boolean') errors.push(`scenario ${sc.id}: bad artifact entry`);
    }
    for (const m of ev.transcript_markers || []) {
      if (!['tool_call', 'text'].includes(m.kind) || typeof m.pattern !== 'string') errors.push(`scenario ${sc.id}: bad transcript_marker entry`);
    }
    for (const w of ev.workflow_steps || []) {
      if (typeof w.step !== 'string' || !['artifact', 'marker'].includes(w.check) || typeof w.ref !== 'string') errors.push(`scenario ${sc.id}: bad workflow_step entry`);
    }
  }
  return errors;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

setup();

try {
  // Test 1: 6 scenarios without --context
  {
    const result = run();
    assert.strictEqual(result.skill_name, 'test-skill', 'skill_name mismatch');
    assert.ok(result.generated_from.includes('SKILL.md'), 'generated_from mismatch');
    assert.strictEqual(result.evals.length, 6, `Expected 6 scenarios, got ${result.evals.length}`);

    const types = result.evals.map(e => e.type);
    for (const t of ['direct', 'paraphrased', 'edge_case', 'negative', 'semantic', 'adversarial']) {
      assert.ok(types.includes(t), `Missing scenario type: ${t}`);
    }

    for (const e of result.evals) {
      assert.ok(typeof e.expected.triggers === 'boolean', `${e.type}: expected.triggers must be boolean`);
    }

    const neg = result.evals.find(e => e.type === 'negative');
    assert.strictEqual(neg.expected.triggers, false, 'negative must not trigger');
    const adv = result.evals.find(e => e.type === 'adversarial');
    assert.strictEqual(adv.expected.triggers, false, 'adversarial must not trigger');

    for (const t of ['direct', 'paraphrased', 'semantic', 'edge_case']) {
      const s = result.evals.find(e => e.type === t);
      assert.strictEqual(s.expected.triggers, true, `${t} must trigger`);
    }
    console.log('✓ Test 1: 6 scenarios without --context');
  }

  // Test 2: 9 scenarios with --context
  {
    const CTX_FILE = path.join(TMP, 'evals', 'project-context.json');
    fs.writeFileSync(CTX_FILE, CTX_CONTENT);
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const result = run(['--context', CTX_FILE]);
    assert.strictEqual(result.evals.length, 9, `Expected 9 scenarios, got ${result.evals.length}`);

    const types = result.evals.map(e => e.type);
    for (const t of ['project-native', 'project-workflow', 'multi-turn']) {
      assert.ok(types.includes(t), `Missing context scenario type: ${t}`);
    }
    assert.strictEqual(result.project_context, CTX_FILE, 'project_context path mismatch');
    console.log('✓ Test 2: 9 scenarios with --context');
  }

  // Test 3: target selection — every positive prompt names a concrete sibling
  // target, selection is deterministic across runs, and never targets itself.
  {
    const CTX_FILE = path.join(TMP, 'evals', 'project-context.json');
    const result1 = run(['--context', CTX_FILE]);
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const result2 = run(['--context', CTX_FILE]);

    assert.ok(result1.target_selection && result1.target_selection.target, 'target_selection.target must be set');
    assert.strictEqual(result1.target_selection.target, result2.target_selection.target,
      'target selection must be deterministic across runs');
    assert.notStrictEqual(result1.target_selection.target, 'test-skill', 'must not target itself');

    for (const type of ['direct', 'paraphrased', 'edge_case', 'semantic', 'project-native', 'project-workflow', 'multi-turn']) {
      const sc = result1.evals.find(e => e.type === type);
      if (!sc) continue;
      assert.ok(sc.prompt.includes(result1.target_selection.target),
        `${type} prompt must name the concrete target ("${result1.target_selection.target}")`);
    }

    // --target CLI override takes priority
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const overridden = run(['--context', CTX_FILE, '--target', 'skill-adapt']);
    assert.strictEqual(overridden.target_selection.target, 'skill-adapt', '--target override must win');
    assert.strictEqual(overridden.target_selection.source, 'cli', 'override source must be "cli"');
    console.log('✓ Test 3: target selection is concrete, deterministic, and overridable');
  }

  // Test 4: description-echo lint — freshly generated output passes; a
  // hand-built description-echoing prompt is caught by --lint-only.
  {
    const CTX_FILE = path.join(TMP, 'evals', 'project-context.json');
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    run(['--context', CTX_FILE]);

    let lintOutput = '';
    try {
      lintOutput = execFileSync(process.execPath, [SCRIPT, '--lint-only', path.join(EVALS_DIR, 'evals.json')], { cwd: TMP, stdio: 'pipe' }).toString();
    } catch (e) {
      lintOutput = e.stdout ? e.stdout.toString() : '';
      throw new Error(`--lint-only unexpectedly failed on freshly generated evals: ${lintOutput}`);
    }
    assert.ok(/0\/\d+ scenarios flagged/.test(lintOutput), `Expected 0 flagged scenarios, got: ${lintOutput}`);

    const badFile = path.join(TMP, 'evals', 'test-skill', 'bad-evals.json');
    const echoPrompt = 'Running automated tests for a codebase, executes the test suite, or checks test results, measuring test coverage';
    fs.writeFileSync(badFile, JSON.stringify({
      skill_name: 'test-skill',
      generated_from: SKILL_FILE,
      project_context: null,
      evals: [{ id: 1, eval_name: 'bad', type: 'direct', prompt: echoPrompt, expected: { triggers: true, evidence: { artifacts: [], transcript_markers: [], workflow_steps: [] }, judgment: ['x'] } }],
    }, null, 2));
    let failed = false;
    try {
      execFileSync(process.execPath, [SCRIPT, '--lint-only', badFile], { cwd: TMP, stdio: 'pipe' });
    } catch (e) {
      failed = true;
      const out = (e.stdout || '').toString();
      assert.ok(/FAIL/.test(out), 'lint-only output must mark the echoing scenario as FAIL');
    }
    assert.ok(failed, '--lint-only must exit non-zero when a description-echo scenario is present');
    console.log('✓ Test 4: description-echo lint passes fresh output and catches a hand-built echo');
  }

  // Test 5: evidence block structure — every scenario has evidence + judgment;
  // negative/adversarial assert skill_loaded only (no workflow_executed).
  {
    const CTX_FILE = path.join(TMP, 'evals', 'project-context.json');
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const result = run(['--context', CTX_FILE]);

    for (const sc of result.evals) {
      assert.ok(sc.expected.evidence, `${sc.type}: missing expected.evidence`);
      assert.ok(Array.isArray(sc.expected.evidence.artifacts), `${sc.type}: evidence.artifacts must be an array`);
      assert.ok(Array.isArray(sc.expected.evidence.transcript_markers), `${sc.type}: evidence.transcript_markers must be an array`);
      assert.ok(Array.isArray(sc.expected.evidence.workflow_steps), `${sc.type}: evidence.workflow_steps must be an array`);
      assert.ok(Array.isArray(sc.expected.judgment) && sc.expected.judgment.length > 0, `${sc.type}: judgment must be non-empty`);
      assert.ok(typeof sc.expected.skill_loaded === 'boolean', `${sc.type}: skill_loaded must be boolean`);
    }

    const neg = result.evals.find(e => e.type === 'negative');
    const adv = result.evals.find(e => e.type === 'adversarial');
    assert.strictEqual(neg.expected.skill_loaded, false, 'negative: skill_loaded must be false');
    assert.strictEqual(adv.expected.skill_loaded, false, 'adversarial: skill_loaded must be false');
    assert.ok(!('workflow_executed' in neg.expected), 'negative must not assert workflow_executed');
    assert.ok(!('workflow_executed' in adv.expected), 'adversarial must not assert workflow_executed');
    assert.strictEqual(neg.expected.evidence.transcript_markers[0].expect, 'absent');
    assert.strictEqual(adv.expected.evidence.transcript_markers[0].expect, 'absent');

    const direct = result.evals.find(e => e.type === 'direct');
    assert.strictEqual(direct.expected.workflow_executed, true, 'direct must assert workflow_executed: true');
    assert.strictEqual(direct.expected.evidence.transcript_markers[0].expect, 'present');
    // Artifact evidence extracted from the skill's own documented convention
    // (`skills/<skill-name>/test-config.json` in the fixture, with the concrete target substituted).
    const artifactStep = direct.expected.evidence.workflow_steps.find(w => w.check === 'artifact');
    assert.ok(artifactStep, 'direct scenario should surface at least one artifact-checked workflow step from the fixture');
    assert.ok(artifactStep.ref.includes(result.target_selection.target), 'artifact ref should have the placeholder substituted with the concrete target');
    console.log('✓ Test 5: evidence block structure + negative/adversarial semantics');
  }

  // Test 6: schema validation of generated output (both context modes)
  {
    const CTX_FILE = path.join(TMP, 'evals', 'project-context.json');
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const withCtx = run(['--context', CTX_FILE]);
    let errors = validateEvalsFile(withCtx);
    assert.deepStrictEqual(errors, [], `Schema validation errors (with context): ${errors.join('; ')}`);

    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const withoutCtx = run();
    errors = validateEvalsFile(withoutCtx);
    assert.deepStrictEqual(errors, [], `Schema validation errors (without context): ${errors.join('; ')}`);
    console.log('✓ Test 6: generated output validates against schemas/evals.schema.json structure');
  }

  // Test 7: tool_call marker must match only a genuine Skill invocation token,
  // never narrative mention of the skill's name (calibration-gate finding:
  // `Skill.*<name>` false-positived on 10 of 12 flagged reps).
  {
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const result = run();
    const direct = result.evals.find(e => e.type === 'direct');
    const marker = direct.expected.evidence.transcript_markers.find(m => m.kind === 'tool_call');
    assert.ok(marker, 'direct scenario must carry a tool_call marker');
    const re = new RegExp(marker.pattern, 'i'); // exactly how harvest-evidence.js applies it

    // Genuine invocation forms — must match
    assert.ok(re.test('`Skill(test-skill)` — the loaded skill was applied'),
      'marker must match the bare Skill(<name>) invocation token');
    assert.ok(re.test('Skill("test-skill") invoked'),
      'marker must match a double-quoted invocation token');
    assert.ok(re.test("Skill( 'test-skill' )"),
      'marker must match a single-quoted, spaced invocation token');

    // Narrative mentions — must NOT match (real false positives from the calibration gate)
    assert.ok(!re.test('**Skill under test**: `test-skill` (loaded from fixtures/...)'),
      'marker must not match a "Skill under test" narrative header');
    assert.ok(!re.test('a sibling skill so test-skill can be compared against it'),
      'marker must not match prose that mentions the skill name');
    assert.ok(!re.test('The skill named test-skill was deliberately not invoked'),
      'marker must not match a decline narration');
    console.log('✓ Test 7: tool_call marker matches invocation token only, not narrative mentions');
  }

  // Test 8: workflow-step extraction must also understand "### Step N: Title"
  // heading workflows (calibration-gate finding: the mutant fixture's format
  // produced workflow_steps: [] for all 9 scenarios).
  {
    const HEADING_SKILL = `---
name: test-skill
description: Runs automated tests for a codebase. Use when running automated tests or checking test results.
---

# Test Skill

## Workflow Overview

1. Read the config
2. Execute the suite
3. Report results

## Detailed Instructions

### Step 1: Read the test config

Read \`skills/<skill-name>/test-config.json\` before anything else.

### Step 2: Execute the test suite

Run the test command.

### Step 3: Report results

Summarise pass/fail counts and coverage.
`;
    fs.writeFileSync(SKILL_FILE, HEADING_SKILL);
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const result = run();
    const direct = result.evals.find(e => e.type === 'direct');
    const steps = direct.expected.evidence.workflow_steps;
    assert.ok(steps.length > 0, 'heading-style workflow must yield non-empty workflow_steps');
    assert.ok(steps.some(s => /read the test config/i.test(s.step)),
      'step titles must come from the "### Step N:" headings');
    const artifactStep = steps.find(s => s.check === 'artifact');
    assert.ok(artifactStep, 'artifact template extraction must still work inside heading-style step bodies');
    assert.ok(artifactStep.ref.includes(result.target_selection.target),
      'artifact ref must have the placeholder substituted');

    // Numbered-bold list format must keep taking precedence when both are present
    fs.writeFileSync(SKILL_FILE, SKILL_CONTENT);
    fs.rmSync(EVALS_DIR, { recursive: true, force: true });
    const boldResult = run();
    const boldSteps = boldResult.evals.find(e => e.type === 'direct').expected.evidence.workflow_steps;
    assert.ok(boldSteps.length > 0 && boldSteps.some(s => /read the test config/i.test(s.step)),
      'numbered-bold extraction must be unchanged');
    console.log('✓ Test 8: workflow_steps extracted from "### Step N:" heading workflows');
  }

  console.log('\n✅ All tests passed');
} finally {
  teardown();
}
