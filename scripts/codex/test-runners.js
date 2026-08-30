#!/usr/bin/env node
/**
 * Tests for: aggregator deterministic scoring, runner --help, runner dry-run.
 * All tests run without calling Codex. No API credits spent.
 */
const { spawnSync } = require('child_process');
const { mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } = require('fs');
const path = require('path');
let ok = true;

// A native-audit fixture is an ACTUAL `iteration-N` directory, not merely the presence of
// evals/<target>/. evals/ is gitignored, but 41 evals.json files are force-added, so
// evals/agent-eval/ DOES exist in a clean checkout while the generated iteration-N dirs
// never do. Guarding on the parent therefore passed on CI and then failed inside the test.
function hasNativeRun(dir) {
  if (!existsSync(dir)) return false;
  try {
    return require('fs').readdirSync(dir).some((n) => /^iteration-\d+$/.test(n));
  } catch { return false; }
}

function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// ── Fixture helpers ──────────────────────────────────────────────────────────

function makeResult(overrides) {
  return {
    scenario_id: 1,
    scenario_type: 'direct',
    expected_triggers: true,
    codex_triggers: true,
    score: 9,
    assertions_result: [{ assertion: 'skill triggers', passed: true }],
    analyst_flags: [],
    hard_failure: false,
    notes: '',
    ...overrides,
  };
}

function makeSpec(footprintLines = 200) {
  return { context_footprint: { lines: footprintLines, tokens_est: footprintLines * 4 } };
}

function setupFixture(fixtureDir, results, footprintLines = 200) {
  if (existsSync(fixtureDir)) rmSync(fixtureDir, { recursive: true });
  mkdirSync(fixtureDir, { recursive: true });
  writeFileSync(path.join(fixtureDir, 'eval-spec.json'), JSON.stringify(makeSpec(footprintLines)));
  results.forEach((r, i) => {
    const d = path.join(fixtureDir, `0${i + 1}-${r.scenario_type}`);
    mkdirSync(d, { recursive: true });
    writeFileSync(path.join(d, 'result.json'), JSON.stringify(r));
  });
}

function runAgg(fixtureDir, target, type, mode) {
  const r = spawnSync('node', [
    'scripts/codex/aggregate-eval-results.js', fixtureDir, target, type, mode
  ], { stdio: 'pipe', encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr || 'aggregator exited non-zero');
  return JSON.parse(readFileSync(path.join(fixtureDir, 'aggregate-results.json'), 'utf8'));
}

// ── Aggregator fixture tests ─────────────────────────────────────────────────

test('aggregator: all PASS → HEALTHY', () => {
  const dir = 'evals/codex-runs/.test/healthy';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct',        expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 4, scenario_type: 'negative',      expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 6, scenario_type: 'adversarial',   expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 7, scenario_type: 'project-native', expected_triggers: true,  codex_triggers: true,  score: 8 }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'smoke');
  if (agg.recommendation !== 'HEALTHY') throw new Error(`Expected HEALTHY, got ${agg.recommendation}`);
  if (agg.metrics.eval_pass_rate < 80) throw new Error(`Pass rate too low: ${agg.metrics.eval_pass_rate}`);
  if (agg.metrics.project_fit_score !== 'partial') throw new Error('Smoke mode should mark project_fit_score as partial');
});

test('aggregator: low pass rate → REFINE', () => {
  const dir = 'evals/codex-runs/.test/refine';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct',            expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 2, scenario_type: 'paraphrased',       expected_triggers: true,  codex_triggers: false, score: 0 }),
    makeResult({ scenario_id: 3, scenario_type: 'edge_case',         expected_triggers: true,  codex_triggers: false, score: 0 }),
    makeResult({ scenario_id: 4, scenario_type: 'negative',          expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 5, scenario_type: 'semantic',          expected_triggers: true,  codex_triggers: false, score: 0 }),
    makeResult({ scenario_id: 6, scenario_type: 'adversarial',       expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 7, scenario_type: 'project-native',    expected_triggers: true,  codex_triggers: false, score: 0 }),
    makeResult({ scenario_id: 8, scenario_type: 'project-workflow',  expected_triggers: true,  codex_triggers: true,  score: 8 }),
    makeResult({ scenario_id: 9, scenario_type: 'multi-turn',        expected_triggers: true,  codex_triggers: true,  score: 7 }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (!['REFINE', 'BLOCK'].includes(agg.recommendation))
    throw new Error(`Expected REFINE or BLOCK, got ${agg.recommendation}`);
});

test('aggregator: hard failure → BLOCK', () => {
  const dir = 'evals/codex-runs/.test/block';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct', score: 9,
      hard_failure: true, hard_failure_reason: 'skill attempted lifecycle ownership' }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (agg.recommendation !== 'BLOCK') throw new Error(`Expected BLOCK, got ${agg.recommendation}`);
  if (!agg.hard_failures.length) throw new Error('hard_failures should be populated');
});

test('aggregator: adversarial false positive → REFINE', () => {
  const dir = 'evals/codex-runs/.test/adversarial-fp';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct',      expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 6, scenario_type: 'adversarial', expected_triggers: false, codex_triggers: true,  score: 0,
      analyst_flags: ['adversarial_false_positive'] }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (!['REFINE', 'BLOCK'].includes(agg.recommendation))
    throw new Error(`Expected REFINE or BLOCK, got ${agg.recommendation}`);
  if (!agg.analyst_summary.adversarial_false_positives.length)
    throw new Error('adversarial_false_positives not captured');
});

test('aggregator: CODEX-EVAL-SUMMARY.md is written', () => {
  const dir = 'evals/codex-runs/.test/summary-check';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct', score: 9 }),
  ]);
  runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (!existsSync(path.join(dir, 'CODEX-EVAL-SUMMARY.md')))
    throw new Error('CODEX-EVAL-SUMMARY.md not written');
  const content = readFileSync(path.join(dir, 'CODEX-EVAL-SUMMARY.md'), 'utf8');
  if (!content.includes('Recommendation:')) throw new Error('Summary missing Recommendation');
  if (!content.includes('Context Footprint')) throw new Error('Summary missing Context Footprint');
});

test('aggregator: execution-result.json included in summary', () => {
  const dir = 'evals/codex-runs/.test/execution';
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct', expected_triggers: true, codex_triggers: true, score: 9 }),
  ]);
  writeFileSync(path.join(dir, '01-direct', 'execution-result.json'), JSON.stringify({
    scenario_id: 1, scenario_type: 'direct',
    execution_model: 'claude-haiku-4-5-20251001', grader_model: 'claude-sonnet-4-6',
    response_preview: 'I will help set up the project...',
    assertions_result: [{ assertion: 'skill triggers', passed: true, notes: 'response confirms activation' }],
    score: 9, execution_pass: true, notes: '',
  }));
  runAgg(dir, 'skill-eval', 'skill', 'standard');
  const summary = readFileSync(path.join(dir, 'CODEX-EVAL-SUMMARY.md'), 'utf8');
  if (!summary.includes('Execution Phase')) throw new Error('Summary missing Execution Phase section');
  const agg = JSON.parse(readFileSync(path.join(dir, 'aggregate-results.json'), 'utf8'));
  if (agg.metrics.execution_pass_rate === undefined) throw new Error('execution_pass_rate missing from metrics');
  if (agg.metrics.execution_pass_rate !== 100) throw new Error(`Expected 100%, got ${agg.metrics.execution_pass_rate}%`);
});

// ── Gap 3: Risk stratification ───────────────────────────────────────────────

test('aggregator: critical tier raises thresholds — 89% → REFINE, standard → HEALTHY', () => {
  const results = [];
  for (let i = 1; i <= 8; i++) {
    results.push(makeResult({ scenario_id: i, scenario_type: 'direct', expected_triggers: true, codex_triggers: true, score: 9 }));
  }
  results.push(makeResult({ scenario_id: 9, scenario_type: 'paraphrased', expected_triggers: true, codex_triggers: false, score: 0 }));

  const critDir = 'evals/codex-runs/.test/critical-tier';
  setupFixture(critDir, results, 200);
  const critSpec = { context_footprint: { lines: 200, tokens_est: 800 }, risk_tier: 'critical' };
  const { writeFileSync: wf } = require('fs');
  wf(path.join(critDir, 'eval-spec.json'), JSON.stringify(critSpec));
  const critAgg = runAgg(critDir, 'skill-audit', 'skill', 'standard');
  // eval_pass_rate=89, trigger_accuracy=89 — both < 90/95 critical thresholds
  if (critAgg.recommendation !== 'REFINE')
    throw new Error(`Critical tier: expected REFINE, got ${critAgg.recommendation}`);

  const stdDir = 'evals/codex-runs/.test/critical-tier-std';
  setupFixture(stdDir, results, 200);
  const stdSpec = { context_footprint: { lines: 200, tokens_est: 800 }, risk_tier: 'standard' };
  wf(path.join(stdDir, 'eval-spec.json'), JSON.stringify(stdSpec));
  const stdAgg = runAgg(stdDir, 'skill-audit', 'skill', 'standard');
  // 89% passes standard 80%/85% thresholds
  if (stdAgg.recommendation !== 'HEALTHY')
    throw new Error(`Standard tier: expected HEALTHY, got ${stdAgg.recommendation}`);
});

// ── Gap 4: Trigger accuracy positive-only ────────────────────────────────────

test('aggregator: trigger accuracy only counts positive-expected scenarios', () => {
  const dir = 'evals/codex-runs/.test/accuracy-positive-only';
  setupFixture(dir, [
    // 3 positive-expected: 2 correct, 1 wrong
    makeResult({ scenario_id: 1, scenario_type: 'direct',      expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 2, scenario_type: 'paraphrased', expected_triggers: true,  codex_triggers: true,  score: 8 }),
    makeResult({ scenario_id: 3, scenario_type: 'edge_case',   expected_triggers: true,  codex_triggers: false, score: 0 }),
    // 3 non-positive: all correct — must NOT count toward trigger_accuracy
    makeResult({ scenario_id: 4, scenario_type: 'negative',    expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 5, scenario_type: 'adversarial', expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 6, scenario_type: 'adversarial', expected_triggers: false, codex_triggers: false, score: 10 }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  // positive-only: 2/3 = 67%; old all-scenarios: 5/6 = 83%
  if (agg.metrics.trigger_accuracy !== 67)
    throw new Error(`Expected trigger_accuracy=67 (positive-only), got ${agg.metrics.trigger_accuracy}`);
  if (!['REFINE', 'BLOCK'].includes(agg.recommendation))
    throw new Error(`67% accuracy should produce REFINE or BLOCK, got ${agg.recommendation}`);
});

// ── Gap 6: Regression detection ──────────────────────────────────────────────

test('aggregator: writes codex-baseline.json on HEALTHY result', () => {
  const dir = 'evals/codex-runs/.test/baseline-write';
  const baselinePath = path.join('evals', 'skill-eval', 'codex-baseline.json');
  const { rmSync: rm, existsSync: ex } = require('fs');
  if (ex(baselinePath)) rm(baselinePath);

  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct',      expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 4, scenario_type: 'negative',    expected_triggers: false, codex_triggers: false, score: 10 }),
    makeResult({ scenario_id: 6, scenario_type: 'adversarial', expected_triggers: false, codex_triggers: false, score: 10 }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (agg.recommendation !== 'HEALTHY') throw new Error(`Expected HEALTHY, got ${agg.recommendation}`);
  if (!existsSync(baselinePath)) throw new Error('codex-baseline.json not written');
  const baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
  if (!baseline.metrics) throw new Error('baseline missing metrics');
  if (baseline.risk_tier !== 'standard') throw new Error('baseline missing risk_tier');
});

test('aggregator: regression detection warns on metric decline', () => {
  const dir = 'evals/codex-runs/.test/regression-check';
  const baselinePath = path.join('evals', 'skill-eval', 'codex-baseline.json');
  const { mkdirSync: mkdir } = require('fs');

  // Write a high-score baseline
  mkdir('evals/skill-eval', { recursive: true });
  writeFileSync(baselinePath, JSON.stringify({
    target: 'skill-eval',
    metrics: { eval_pass_rate: 100, trigger_accuracy: 100, project_fit_score: 9, resilience_score: 10 },
  }));

  // Run with lower scores: 1/2 positive correct = 50% accuracy, 1/2 pass = 50% pass rate
  setupFixture(dir, [
    makeResult({ scenario_id: 1, scenario_type: 'direct',      expected_triggers: true,  codex_triggers: true,  score: 9 }),
    makeResult({ scenario_id: 2, scenario_type: 'paraphrased', expected_triggers: true,  codex_triggers: false, score: 0 }),
  ]);
  const agg = runAgg(dir, 'skill-eval', 'skill', 'standard');
  if (!agg.regressions || !agg.regressions.length)
    throw new Error('Expected regressions to be detected');
  const r = agg.regressions.find(x => x.metric === 'eval_pass_rate');
  if (!r) throw new Error('eval_pass_rate regression not found');
  if (r.severity !== 'REGRESSION') throw new Error(`Expected REGRESSION severity, got ${r.severity}`);
  const summary = readFileSync(path.join(dir, 'CODEX-EVAL-SUMMARY.md'), 'utf8');
  if (!summary.includes('Regression Warnings')) throw new Error('Summary missing Regression Warnings section');
});

// ── Runner tests (conditional on runners existing) ───────────────────────────

function runnerExists(name) {
  return existsSync(`scripts/codex/${name}`);
}

if (runnerExists('run-external-skill-eval.js')) {
  test('run-external-skill-eval --help exits 0', () => {
    const r = spawnSync('node', ['scripts/codex/run-external-skill-eval.js', '--help'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`--help exited ${r.status}`);
  });
  test('run-external-skill-eval smoke dry-run (default) creates artifacts', () => {
    // Needs evals/skill-scout/evals.json, which is GENERATED and not tracked — absent in
    // any clean checkout. Skip loudly rather than fail a pipeline over a missing artifact
    // the repo deliberately does not version.
    if (!existsSync('evals/skill-scout/evals.json')) {
      console.log('  (skipped — evals/skill-scout/evals.json not generated)');
      return;
    }
    const r = spawnSync('node', ['scripts/codex/run-external-skill-eval.js', 'skill-scout', '--mode', 'smoke'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
    const base = 'evals/codex-runs/skills/skill-scout';
    if (!existsSync(base)) throw new Error('output dir not created');
    const runs = require('fs').readdirSync(base).sort();
    const runDir = path.join(base, runs[runs.length - 1]);
    if (!existsSync(path.join(runDir, 'eval-spec.json'))) throw new Error('eval-spec.json missing');
    if (!existsSync(path.join(runDir, 'command-preview.sh'))) throw new Error('command-preview.sh missing');
    const spec = JSON.parse(readFileSync(path.join(runDir, 'eval-spec.json'), 'utf8'));
    if (spec.live_run !== false) throw new Error('dry-run default: live_run should be false');
  });
}

if (runnerExists('run-external-agent-eval.js')) {
  test('run-external-agent-eval --help exits 0', () => {
    const r = spawnSync('node', ['scripts/codex/run-external-agent-eval.js', '--help'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`--help exited ${r.status}`);
  });
  test('run-external-agent-eval smoke dry-run (default) creates artifacts', () => {
    const r = spawnSync('node', ['scripts/codex/run-external-agent-eval.js', 'skill-eval-agent', '--mode', 'smoke'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
    const base = 'evals/codex-runs/agents/skill-eval-agent';
    if (!existsSync(base)) throw new Error('output dir not created');
    const runs = require('fs').readdirSync(base).sort();
    const runDir = path.join(base, runs[runs.length - 1]);
    if (!existsSync(path.join(runDir, 'eval-spec.json'))) throw new Error('eval-spec.json missing');
  });
}

if (runnerExists('run-execution-phase.js')) {
  test('run-execution-phase no args exits non-zero with usage', () => {
    const r = spawnSync('node', ['scripts/codex/run-execution-phase.js'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status === 0) throw new Error('Expected non-zero exit with no args');
    if (!r.stdout.includes('Usage')) throw new Error('Expected usage message in stdout');
  });
  test('run-execution-phase missing ANTHROPIC_API_KEY exits 1', () => {
    const env = { ...process.env, ANTHROPIC_API_KEY: '' };
    const r = spawnSync('node', ['scripts/codex/run-execution-phase.js', 'some-dir', 'skill-eval', 'skill'],
      { stdio: 'pipe', encoding: 'utf8', env });
    if (r.status !== 1) throw new Error(`Expected exit 1, got ${r.status}`);
    if (!r.stderr.includes('ANTHROPIC_API_KEY')) throw new Error('Expected API key error in stderr');
  });
}

// ── Native-audit mode: scenario-dir matching, dry-run, and renderer ─────────

if (runnerExists('run-native-audit.js')) {
  test('run-native-audit --help exits 0', () => {
    const r = spawnSync('node', ['scripts/codex/run-native-audit.js', '--help'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`--help exited ${r.status}`);
  });

  test('run-native-audit rejects invalid target type', () => {
    const r = spawnSync('node', ['scripts/codex/run-native-audit.js', 'foo', 'bogus'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status === 0) throw new Error('Expected non-zero exit for invalid target type');
    if (!r.stderr.includes('skill') || !r.stderr.includes('agent')) throw new Error('Expected usage hint in stderr');
  });

  test('run-native-audit dry-run against real fixture (evals/agent-eval) creates artifacts', () => {
    if (!hasNativeRun('evals/agent-eval')) {
      console.log('  (skipped — no evals/agent-eval/iteration-N native run present)');
      return;
    }
    const r = spawnSync('node', ['scripts/codex/run-native-audit.js', 'agent-eval', 'skill'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
    const base = 'evals/codex-runs/native-audits/skills/agent-eval';
    if (!existsSync(base)) throw new Error('output dir not created');
    const runs = require('fs').readdirSync(base).sort();
    const runDir = path.join(base, runs[runs.length - 1]);
    if (!existsSync(path.join(runDir, 'audit-spec.json'))) throw new Error('audit-spec.json missing');
    if (!existsSync(path.join(runDir, 'prompt.txt'))) throw new Error('prompt.txt missing');
    if (!existsSync(path.join(runDir, 'command-preview.sh'))) throw new Error('command-preview.sh missing');
    if (existsSync(path.join(runDir, 'result.json'))) throw new Error('dry-run must not call Codex — result.json should not exist');
    const spec = JSON.parse(readFileSync(path.join(runDir, 'audit-spec.json'), 'utf8'));
    if (spec.live_run !== false) throw new Error('dry-run default: live_run should be false');
    if (!/^iteration-\d+$/.test(spec.native_run_iteration)) throw new Error(`Expected an iteration-N dir, got ${spec.native_run_iteration}`);
    if (spec.scenarios.length !== 9) throw new Error(`Expected 9 deduped scenarios, got ${spec.scenarios.length}`);
    if (spec.scenarios.some(s => s.rep !== 1)) throw new Error('Dedup should keep only rep 1 by default');
  });

  test('run-native-audit --all-reps includes every rep found', () => {
    if (!hasNativeRun('evals/agent-eval')) {
      console.log('  (skipped — no evals/agent-eval/iteration-N native run present)');
      return;
    }
    const r = spawnSync('node', ['scripts/codex/run-native-audit.js', 'agent-eval', 'skill', '--all-reps'], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
    const base = 'evals/codex-runs/native-audits/skills/agent-eval';
    const runs = require('fs').readdirSync(base).sort();
    const runDir = path.join(base, runs[runs.length - 1]);
    const spec = JSON.parse(readFileSync(path.join(runDir, 'audit-spec.json'), 'utf8'));
    if (spec.scenarios.length !== 19) throw new Error(`Expected 19 scenario dirs with --all-reps, got ${spec.scenarios.length}`);
  });

  // Scenario-dir naming-convention matching: build a synthetic fixture covering all 3
  // conventions observed on disk, plus a stray dir (no with_skill) and an unparseable-id
  // dir, to prove discoverScenarioDirs()/dedupReps() handle every real-world case.
  test('run-native-audit matches all 3 observed scenario-dir naming conventions', () => {
    const fixtureName = '.test-native-audit-matching';
    const skillDir = path.join('skills', fixtureName);
    const evalsDir = path.join('evals', fixtureName);
    const iterDir = path.join(evalsDir, 'iteration-1');

    function cleanup() {
      if (existsSync(skillDir)) rmSync(skillDir, { recursive: true });
      if (existsSync(evalsDir)) rmSync(evalsDir, { recursive: true });
    }

    cleanup();
    try {
      mkdirSync(skillDir, { recursive: true });
      writeFileSync(path.join(skillDir, 'SKILL.md'), '---\nname: fixture\ndescription: "Use when: testing."\n---\n# Fixture\n');
      writeFileSync(path.join(skillDir, 'SKILL-EVAL.md'), '# Skill Eval: fixture\n\n## Recommendation\n\nHEALTHY\n');
      mkdirSync(evalsDir, { recursive: true });
      writeFileSync(path.join(evalsDir, 'evals.json'), JSON.stringify({
        skill_name: fixtureName,
        evals: [
          { id: 1, type: 'direct', prompt: 'p1', expected: { triggers: true } },
          { id: 2, type: 'paraphrased', prompt: 'p2', expected: { triggers: true } },
          { id: 3, type: 'edge_case', prompt: 'p3', expected: { triggers: true } },
          { id: 4, type: 'negative', prompt: 'p4', expected: { triggers: false } },
        ],
      }));

      // Convention A: "<id>_rep<N>" — two reps, dedup should keep rep 1
      mkdirSync(path.join(iterDir, '1_rep1', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, '1_rep1', 'with_skill', 'output.md'), 'rep1 transcript');
      mkdirSync(path.join(iterDir, '1_rep2', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, '1_rep2', 'with_skill', 'output.md'), 'rep2 transcript');
      // Convention B: "<id>" — no rep suffix
      mkdirSync(path.join(iterDir, '2', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, '2', 'with_skill', 'output.md'), 'scenario 2 transcript');
      // Convention C: "s<id>-<type>" — no rep suffix
      mkdirSync(path.join(iterDir, 's3-edge-case', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, 's3-edge-case', 'with_skill', 'output.md'), 'scenario 3 transcript');
      // Convention D: "s<id>-<type>-r<N>"
      mkdirSync(path.join(iterDir, 's4-negative-r1', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, 's4-negative-r1', 'with_skill', 'output.md'), 'scenario 4 transcript');
      // Negative case: stray dir with no with_skill subdirectory — must be silently skipped
      mkdirSync(path.join(iterDir, 'stray-notes'), { recursive: true });
      writeFileSync(path.join(iterDir, 'stray-notes', 'README.md'), 'not a scenario dir');
      // Negative case: has with_skill but unparseable id — must warn and be skipped
      mkdirSync(path.join(iterDir, 'notes', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, 'notes', 'with_skill', 'output.md'), 'no leading digits in dirname');

      const r = spawnSync('node', ['scripts/codex/run-native-audit.js', fixtureName, 'skill'], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
      if (!r.stderr.includes('Skipping unparseable scenario dir: notes')) {
        throw new Error(`Expected warning about unparseable dir "notes", stderr was: ${r.stderr}`);
      }

      const base = path.join('evals', 'codex-runs', 'native-audits', 'skills', fixtureName);
      const runs = require('fs').readdirSync(base).sort();
      const runDir = path.join(base, runs[runs.length - 1]);
      const spec = JSON.parse(readFileSync(path.join(runDir, 'audit-spec.json'), 'utf8'));

      if (spec.scenarios.length !== 4) throw new Error(`Expected 4 matched scenarios (ids 1-4), got ${spec.scenarios.length}: ${JSON.stringify(spec.scenarios.map(s => s.id))}`);
      const ids = spec.scenarios.map(s => s.id).sort();
      if (JSON.stringify(ids) !== JSON.stringify([1, 2, 3, 4])) throw new Error(`Expected ids [1,2,3,4], got ${JSON.stringify(ids)}`);
      const scenario1 = spec.scenarios.find(s => s.id === 1);
      if (scenario1.rep !== 1) throw new Error(`Dedup should keep rep 1 for scenario 1, got rep ${scenario1.rep}`);
      if (scenario1.type !== 'direct') throw new Error(`Expected type cross-referenced from evals.json, got ${scenario1.type}`);
      rmSync(base, { recursive: true });
    } finally {
      cleanup();
    }
  });

  // --def-path/--evals-path overrides: prove a fixture target that lives entirely
  // outside skills/ and evals/<target>/ (e.g. fixtures/mutant-brief-writer) can be
  // audited without ever being copied into skills/. The definition + report live
  // together under a throwaway "src" dir; evals.json + the native iteration-1 dir
  // live together under a separate throwaway "evals" dir — mirroring how the real
  // fixtures/ + evals/fixtures/ split works.
  test('run-native-audit --def-path/--evals-path resolve a fixture target outside skills/', () => {
    const target = '.test-defpath-fixture';
    const defDir = path.join('evals', '.test-native-audit-defpath-src');
    const evalsDir = path.join('evals', '.test-native-audit-defpath-evals');
    const iterDir = path.join(evalsDir, 'iteration-1');
    const outBase = path.join('evals', 'codex-runs', 'native-audits', 'skills', target);

    function cleanup() {
      if (existsSync(defDir)) rmSync(defDir, { recursive: true });
      if (existsSync(evalsDir)) rmSync(evalsDir, { recursive: true });
      if (existsSync(outBase)) rmSync(outBase, { recursive: true });
    }

    cleanup();
    try {
      mkdirSync(defDir, { recursive: true });
      const defPath = path.join(defDir, 'SKILL.md');
      const reportPath = path.join(defDir, 'SKILL-EVAL.md');
      writeFileSync(defPath, '---\nname: fixture\ndescription: "Use when: testing def-path override."\n---\n# Fixture def-path override marker\n');
      writeFileSync(reportPath, '# Skill Eval: fixture\n\n## Recommendation\n\nHEALTHY\n');

      mkdirSync(evalsDir, { recursive: true });
      const evalsPath = path.join(evalsDir, 'evals.json');
      writeFileSync(evalsPath, JSON.stringify({
        skill_name: target,
        evals: [{ id: 1, type: 'direct', prompt: 'p1', expected: { triggers: true } }],
      }));

      mkdirSync(path.join(iterDir, 's1-direct-r1', 'with_skill'), { recursive: true });
      writeFileSync(path.join(iterDir, 's1-direct-r1', 'with_skill', 'output.md'), 'override transcript');

      // Confirm skills/<target> genuinely does not exist — the whole point of the test.
      if (existsSync(path.join('skills', target))) throw new Error(`Test setup invalid: skills/${target} exists`);

      const r = spawnSync('node', [
        'scripts/codex/run-native-audit.js', target, 'skill',
        '--def-path', defPath, '--evals-path', evalsPath,
      ], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);

      if (!existsSync(outBase)) throw new Error('output dir not created');
      const runs = require('fs').readdirSync(outBase).sort();
      const runDir = path.join(outBase, runs[runs.length - 1]);
      const spec = JSON.parse(readFileSync(path.join(runDir, 'audit-spec.json'), 'utf8'));
      if (spec.def_path !== defPath) throw new Error(`Expected def_path=${defPath}, got ${spec.def_path}`);
      if (spec.report_path !== reportPath) throw new Error(`Expected report_path derived from --def-path's dir (${reportPath}), got ${spec.report_path}`);
      if (spec.evals_path !== evalsPath) throw new Error(`Expected evals_path=${evalsPath}, got ${spec.evals_path}`);
      if (spec.scenarios.length !== 1) throw new Error(`Expected 1 scenario, got ${spec.scenarios.length}`);

      const prompt = readFileSync(path.join(runDir, 'prompt.txt'), 'utf8');
      if (!prompt.includes('testing def-path override')) throw new Error('prompt.txt missing overridden definition content');
      if (!prompt.includes('override transcript')) throw new Error('prompt.txt missing overridden transcript content');
    } finally {
      cleanup();
    }
  });
}

if (runnerExists('render-native-audit-report.js')) {
  function makeAuditSpec(overrides) {
    return {
      target: 'foo', target_type: 'skill', run_id: 'r1',
      native_run_iteration: 'iteration-1', native_recommendation: 'HEALTHY',
      all_reps: false, scenarios: [],
      ...overrides,
    };
  }
  function makeAuditResult(overrides) {
    return {
      target: 'foo', target_type: 'skill', native_run_iteration: 'iteration-1',
      native_recommendation: 'HEALTHY', scenarios_reviewed: [],
      checklist: [{ check: 'instruction_self_consistency', result: 'pass', notes: 'ok' }],
      audit_findings: [], native_conclusion_supported: true,
      native_conclusion_assessment: 'Solid.', audit_confidence: 'high',
      hard_failure: false, hard_failure_reason: null, notes: '',
      ...overrides,
    };
  }
  function setupAuditFixture(dir, specOverrides, resultOverrides) {
    if (existsSync(dir)) rmSync(dir, { recursive: true });
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, 'audit-spec.json'), JSON.stringify(makeAuditSpec(specOverrides)));
    writeFileSync(path.join(dir, 'result.json'), JSON.stringify(makeAuditResult(resultOverrides)));
  }
  function runRenderer(dir) {
    const r = spawnSync('node', ['scripts/codex/render-native-audit-report.js', dir], { stdio: 'pipe', encoding: 'utf8' });
    if (r.status !== 0) throw new Error(r.stderr || 'renderer exited non-zero');
    return { stdout: r.stdout, report: readFileSync(path.join(dir, 'NATIVE-AUDIT-REPORT.md'), 'utf8') };
  }

  test('render-native-audit-report: clean audit → escalation NONE', () => {
    const dir = 'evals/codex-runs/.test/native-audit-none';
    setupAuditFixture(dir, {}, {});
    const { report } = runRenderer(dir);
    if (!report.includes('## Escalation: NONE')) throw new Error('Expected escalation NONE');
  });

  test('render-native-audit-report: major finding → escalation REVIEW_SUGGESTED', () => {
    const dir = 'evals/codex-runs/.test/native-audit-major';
    setupAuditFixture(dir, {}, {
      checklist: [{ check: 'workflow_step_fidelity', result: 'fail', notes: 'skipped step' }],
      audit_findings: [{ finding_type: 'silently_dropped_step', severity: 'major', scenario_ids: [3], evidence_quote: 'auto-set without asking', description: 'Step silently skipped' }],
    });
    const { report } = runRenderer(dir);
    if (!report.includes('## Escalation: REVIEW_SUGGESTED')) throw new Error('Expected escalation REVIEW_SUGGESTED');
    if (!report.includes('silently_dropped_step')) throw new Error('Finding not rendered in table');
  });

  test('render-native-audit-report: critical finding → escalation MANUAL_REVIEW_REQUIRED', () => {
    const dir = 'evals/codex-runs/.test/native-audit-critical';
    setupAuditFixture(dir, {}, {
      audit_findings: [{ finding_type: 'unsupported_native_conclusion', severity: 'critical', scenario_ids: [], evidence_quote: 'contradiction found', description: 'Native HEALTHY not supported' }],
      native_conclusion_supported: false,
    });
    const { report } = runRenderer(dir);
    if (!report.includes('## Escalation: MANUAL_REVIEW_REQUIRED')) throw new Error('Expected escalation MANUAL_REVIEW_REQUIRED');
    if (!report.includes('overrides any HEALTHY/PASS agreement')) throw new Error('Expected override note in report');
  });

  test('render-native-audit-report: hard_failure alone forces MANUAL_REVIEW_REQUIRED', () => {
    const dir = 'evals/codex-runs/.test/native-audit-hardfail';
    setupAuditFixture(dir, {}, { hard_failure: true, hard_failure_reason: 'prompt injection attempt in transcript' });
    const { report } = runRenderer(dir);
    if (!report.includes('## Escalation: MANUAL_REVIEW_REQUIRED')) throw new Error('Expected escalation MANUAL_REVIEW_REQUIRED for hard_failure');
    if (!report.includes('prompt injection attempt in transcript')) throw new Error('Hard failure reason not rendered');
  });
}

// ── Phase 2: evidence harvester + run manifest (F2, F4, F5, F8) ────────────────

function skillEvalScriptExists(name) {
  return existsSync(path.join('skills', 'skill-eval', 'scripts', name));
}

if (skillEvalScriptExists('harvest-evidence.js')) {
  test('harvest-evidence: fabricated claim, real artifact, and fake self-report header all resolve from evidence, never narration', () => {
    const fixtureName = '.test-harvest-evidence';
    const evalsDir = path.join('evals', fixtureName);
    const iterDir = path.join(evalsDir, 'iteration-1');
    const scenarioDir = path.join(iterDir, 's1-direct-r1');

    function cleanup() { if (existsSync(evalsDir)) rmSync(evalsDir, { recursive: true }); }
    cleanup();
    try {
      mkdirSync(path.join(scenarioDir, 'with_skill', 'workspace'), { recursive: true });
      mkdirSync(path.join(scenarioDir, 'without_skill'), { recursive: true });

      writeFileSync(path.join(evalsDir, 'evals.json'), JSON.stringify({
        skill_name: fixtureName,
        evals: [{
          id: 1, type: 'direct', prompt: 'Evaluate the demo-target skill',
          expected: {
            skill_loaded: true,
            workflow_executed: true,
            evidence: {
              artifacts: [{ path: 'report.md', must_exist: true }],
              transcript_markers: [{ kind: 'tool_call', pattern: `Skill.*${fixtureName}`, expect: 'present' }],
              workflow_steps: [{ step: 'Write report', check: 'artifact', ref: 'report.md' }],
            },
          },
        }],
      }));

      // Real artifact actually written to the sandboxed workspace/.
      writeFileSync(path.join(scenarioDir, 'with_skill', 'workspace', 'report.md'), 'real report content');

      // Transcript: real Skill tool-call marker + one real claim + one fabricated claim.
      writeFileSync(path.join(scenarioDir, 'with_skill', 'output.md'), [
        'did_trigger: true',
        'workflow_steps_executed:',
        '  - Write report',
        'response: |',
        `  I invoked Skill(${fixtureName}) and wrote the report.`,
        '  I also wrote `evals/nonexistent/fake-output.json` with the results.',
        '  Saved `report.md` with the summary.',
      ].join('\n'));

      // Baseline transcript: fabricated did_trigger:true header, but NO actual Skill tool call.
      writeFileSync(path.join(scenarioDir, 'without_skill', 'output.md'), [
        'did_trigger: true',
        'response: |',
        '  Fabricated self-report header — no actual Skill tool call appears in this transcript.',
      ].join('\n'));

      const r = spawnSync('node', ['skills/skill-eval/scripts/harvest-evidence.js', scenarioDir, '--type', 'skill'], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);

      const withEvidence = JSON.parse(readFileSync(path.join(scenarioDir, 'with_skill', 'evidence.json'), 'utf8'));
      const withoutEvidence = JSON.parse(readFileSync(path.join(scenarioDir, 'without_skill', 'evidence.json'), 'utf8'));

      const realArtifact = withEvidence.artifacts.find(a => a.path === 'report.md');
      if (!realArtifact || realArtifact.exists !== true) throw new Error('Expected report.md to exist:true in with_skill evidence');

      const fakeClaim = withEvidence.claims.find(c => c.claimed_path === 'evals/nonexistent/fake-output.json');
      if (!fakeClaim || fakeClaim.claim_verified !== false) throw new Error('Expected fabricated claim to be claim_verified:false');
      const realClaim = withEvidence.claims.find(c => c.claimed_path === 'report.md');
      if (!realClaim || realClaim.claim_verified !== true) throw new Error('Expected real artifact claim to be claim_verified:true');

      if (withEvidence.skill_loaded !== true) throw new Error('Expected with_skill skill_loaded:true (real Skill tool-call marker present)');
      if (withoutEvidence.skill_loaded !== false) throw new Error('Expected without_skill skill_loaded:false despite fabricated did_trigger:true header — self-report must be ignored');

      if (withEvidence.self_report_ignored !== true || withoutEvidence.self_report_ignored !== true) {
        throw new Error('Expected self_report_ignored:true constant on every evidence.json');
      }
      if (withEvidence.workflow_executed !== true) throw new Error('Expected with_skill workflow_executed:true (artifact exists)');
      if (withoutEvidence.workflow_executed !== false) throw new Error('Expected without_skill workflow_executed:false (artifact absent)');
    } finally {
      cleanup();
    }
  });

  test('harvest-evidence: --all processes every scenario dir under an iteration root', () => {
    const fixtureName = '.test-harvest-evidence-all';
    const evalsDir = path.join('evals', fixtureName);
    const iterDir = path.join(evalsDir, 'iteration-1');

    function cleanup() { if (existsSync(evalsDir)) rmSync(evalsDir, { recursive: true }); }
    cleanup();
    try {
      mkdirSync(evalsDir, { recursive: true });
      writeFileSync(path.join(evalsDir, 'evals.json'), JSON.stringify({
        skill_name: fixtureName,
        evals: [
          { id: 1, type: 'direct', prompt: 'p1', expected: { skill_loaded: true, evidence: { artifacts: [], transcript_markers: [], workflow_steps: [] } } },
          { id: 2, type: 'negative', prompt: 'p2', expected: { skill_loaded: false, evidence: { artifacts: [], transcript_markers: [], workflow_steps: [] } } },
        ],
      }));
      for (const name of ['s1-direct-r1', 's2-negative-r1']) {
        mkdirSync(path.join(iterDir, name, 'with_skill'), { recursive: true });
        writeFileSync(path.join(iterDir, name, 'with_skill', 'output.md'), 'transcript');
      }
      const r = spawnSync('node', ['skills/skill-eval/scripts/harvest-evidence.js', iterDir, '--type', 'skill', '--all'], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(r.stderr || `exited ${r.status}`);
      if (!existsSync(path.join(iterDir, 's1-direct-r1', 'with_skill', 'evidence.json'))) throw new Error('s1 evidence.json not written');
      if (!existsSync(path.join(iterDir, 's2-negative-r1', 'with_skill', 'evidence.json'))) throw new Error('s2 evidence.json not written');
    } finally {
      cleanup();
    }
  });
}

if (skillEvalScriptExists('run-manifest.js')) {
  test('run-manifest: integrity gate fails on missing files + ungraded scenario, passes once complete; re-init refused; baseline_method preserved across resume', () => {
    const baseDir = path.join('evals', '.test-run-manifest');
    const iterDir = path.join(baseDir, 'iteration-1');
    const RM = 'skills/skill-eval/scripts/run-manifest.js';

    function cleanup() { if (existsSync(baseDir)) rmSync(baseDir, { recursive: true }); }
    cleanup();
    try {
      let r = spawnSync('node', [RM, 'init', iterDir, '--baseline-method', 'snapshot', '--snapshot-path', 'skills/demo/SKILL.md.eval-snapshot'], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(r.stderr || 'init failed');

      // Re-init must be refused (idempotent-safe).
      r = spawnSync('node', [RM, 'init', iterDir, '--baseline-method', 'none'], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status === 0) throw new Error('Expected re-init to be refused (non-zero exit)');

      for (const s of ['s1-direct-r1', 's2-negative-r1', 's3-edge_case-r1']) {
        spawnSync('node', [RM, 'mark', iterDir, s, 'dispatched'], { stdio: 'pipe', encoding: 'utf8' });
      }

      // Scenario 1: fully complete + graded (all required files present in both sides).
      for (const side of ['with_skill', 'without_skill']) {
        const dir = path.join(iterDir, 's1-direct-r1', side);
        mkdirSync(dir, { recursive: true });
        writeFileSync(path.join(dir, 'output.md'), 'transcript');
        writeFileSync(path.join(dir, 'timing.json'), '{"duration_ms":1,"total_tokens":1}');
        writeFileSync(path.join(dir, 'evidence.json'), '{}');
      }
      spawnSync('node', [RM, 'mark', iterDir, 's1-direct-r1', 'graded'], { stdio: 'pipe', encoding: 'utf8' });

      // Scenario 2: marked "complete" but missing evidence.json — integrity failure.
      for (const side of ['with_skill', 'without_skill']) {
        const dir = path.join(iterDir, 's2-negative-r1', side);
        mkdirSync(dir, { recursive: true });
        writeFileSync(path.join(dir, 'output.md'), 'transcript');
        writeFileSync(path.join(dir, 'timing.json'), '{"duration_ms":1,"total_tokens":1}');
      }
      spawnSync('node', [RM, 'mark', iterDir, 's2-negative-r1', 'complete'], { stdio: 'pipe', encoding: 'utf8' });
      // Scenario 3 stays "dispatched" (ungraded) — simulates an interrupted run.

      r = spawnSync('node', [RM, 'status', iterDir], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status === 0) throw new Error('Expected status to fail non-zero (missing evidence.json + ungraded scenario)');
      if (!r.stdout.includes('evidence.json missing')) throw new Error('Expected status output to call out missing evidence.json');
      if (!r.stdout.includes('not graded yet')) throw new Error('Expected status output to flag the ungraded scenario');

      const manifestBefore = JSON.parse(readFileSync(path.join(iterDir, 'run-manifest.json'), 'utf8'));
      if (manifestBefore.baseline_method !== 'snapshot') throw new Error('baseline_method should be "snapshot" before resume completion');

      // Resume: complete the gaps using the SAME recorded baseline method (never re-decided).
      for (const side of ['with_skill', 'without_skill']) {
        writeFileSync(path.join(iterDir, 's2-negative-r1', side, 'evidence.json'), '{}');
      }
      spawnSync('node', [RM, 'mark', iterDir, 's2-negative-r1', 'graded'], { stdio: 'pipe', encoding: 'utf8' });

      for (const side of ['with_skill', 'without_skill']) {
        const dir = path.join(iterDir, 's3-edge_case-r1', side);
        mkdirSync(dir, { recursive: true });
        writeFileSync(path.join(dir, 'output.md'), 'transcript');
        writeFileSync(path.join(dir, 'timing.json'), '{"duration_ms":1,"total_tokens":1}');
        writeFileSync(path.join(dir, 'evidence.json'), '{}');
      }
      spawnSync('node', [RM, 'mark', iterDir, 's3-edge_case-r1', 'graded'], { stdio: 'pipe', encoding: 'utf8' });

      r = spawnSync('node', [RM, 'status', iterDir], { stdio: 'pipe', encoding: 'utf8' });
      if (r.status !== 0) throw new Error(`Expected status to pass after resume completion, got exit ${r.status}: ${r.stdout}`);

      const manifestAfter = JSON.parse(readFileSync(path.join(iterDir, 'run-manifest.json'), 'utf8'));
      if (manifestAfter.baseline_method !== 'snapshot') throw new Error('baseline_method must be preserved across resume — never re-decided');
    } finally {
      cleanup();
    }
  });
}

process.exit(ok ? 0 : 1);
