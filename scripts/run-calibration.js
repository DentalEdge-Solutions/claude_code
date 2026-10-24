#!/usr/bin/env node
/**
 * run-calibration.js — reproducible calibration test for the eval pipeline (Phase 3 / F1).
 *
 * Orchestrates the calibration workflow around the committed fixtures in fixtures/:
 * a deliberately defective skill (fixtures/mutant-brief-writer/SKILL.md, 4 known
 * injected defects) plus a ground-truth manifest (expected-findings.json). The test
 * proves the native eval + Codex native-audit layers together catch all 4 defect
 * classes. See fixtures/README.md and fixtures/GATE-RUNBOOK.md.
 *
 * THIS SCRIPT NEVER CALLS CODEX AND NEVER SPENDS API CREDITS. The live steps
 * (native eval via skill-eval-agent, run-native-audit.js --live) are human-invoked;
 * this script only prepares inputs ("generate") and diffs outputs ("check").
 *
 * Steps:
 *   generate  Run the Phase 1 scenario generator on the mutant with the golden
 *             fixture as the concrete --target; relocate output to
 *             evals/fixtures/mutant-brief-writer/evals.json; run the
 *             description-echo lint and report whether prompts discriminate.
 *             A lint failure is REPORTED as signal (the mutant's description is
 *             deliberately vague), not treated as an orchestration error.
 *   check     After the human has run the native eval + native audit, diff the
 *             native SKILL-EVAL.md and the latest NATIVE-AUDIT-REPORT.md against
 *             fixtures/mutant-brief-writer/expected-findings.json and write
 *             evals/fixtures/CALIBRATION-REPORT.md with a per-defect caught/missed
 *             table and an overall 4/4 verdict. Exits 0 on 4/4, 1 otherwise.
 *
 * Report locations (decision, documented):
 *   - The native eval report is expected at fixtures/mutant-brief-writer/SKILL-EVAL.md
 *     (next to the definition — same convention run-native-audit.js --def-path uses,
 *     mirroring skills/<name>/SKILL-EVAL.md). Override with --eval-report <path>.
 *     That path is gitignored — a generated report never gets committed into fixtures/.
 *   - The audit report defaults to the NEWEST run-id directory under
 *     evals/codex-runs/native-audits/skills/mutant-brief-writer/ that contains a
 *     NATIVE-AUDIT-REPORT.md. Override with --audit-report <path>.
 *
 * Detection / matching rules for "check" (keyword + anchor-quote matching):
 *   1. Both report texts are normalized: lowercased, backticks/asterisks/double
 *      quotes stripped, all whitespace collapsed to single spaces.
 *   2. Anchor-quote match: each defect's anchor_quote (plus its
 *      anchor_quote_contradicting / anchor_quote_conflicting variants, when present)
 *      is normalized the same way and slid over the report in 5-word windows; if ANY
 *      window appears verbatim in the report, the defect counts as quoted. Windowing
 *      tolerates partial/elided quoting by the evaluator.
 *   3. Keyword match: each defect_class has a fallback regex over the normalized text
 *      (e.g. self-contradiction: /contradict|inconsisten|conflicting instruction/).
 *   4. A defect is CAUGHT when its PRIMARY document (SKILL-EVAL.md for
 *      "native_metric:*" catchers, NATIVE-AUDIT-REPORT.md for "native_audit:*"
 *      catchers) shows an anchor-quote match OR a keyword match. For native_audit
 *      catchers, a checklist row marking the named check as "fail" also counts
 *      (matches render-native-audit-report.js's "| <check> | fail |" table format).
 *   5. The secondary document is also scanned and reported informationally
 *      ("also mentioned in ..."), but only the primary document decides caught/missed.
 *   6. Verdict: PASS only if all 4 defects are CAUGHT (with the anchor-quote or
 *      keyword evidence excerpted in the report).
 *
 * Usage:
 *   node scripts/run-calibration.js generate
 *   node scripts/run-calibration.js check [--eval-report <path>] [--audit-report <path>]
 *   node scripts/run-calibration.js --help
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const args = process.argv.slice(2);

function flagValue(name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
}

// Fixture locations — parameterized by --fixture (default: the original committed
// calibration fixture). Every mutant fixture follows the same layout under
// fixtures/<name>/, so all fixture-relative paths derive from the one name.
const FIXTURE = flagValue('--fixture') || 'mutant-brief-writer';

function resolvePaths(fixture) {
  return {
    mutantDef: path.join('fixtures', fixture, 'SKILL.md'),
    expectedFindings: path.join('fixtures', fixture, 'expected-findings.json'),
    goldenDef: path.join('fixtures', 'golden-target', 'SKILL.md'),
    contextFile: path.join('evals', 'project-context.json'),
    generator: path.join('skills', 'skill-eval', 'scripts', 'generate-seed-evals.js'),
    evalsOutDir: path.join('evals', 'fixtures', fixture),
    evalReport: path.join('fixtures', fixture, 'SKILL-EVAL.md'),
    auditRunsDir: path.join('evals', 'codex-runs', 'native-audits', 'skills', fixture),
    calibrationReport: path.join('evals', 'fixtures', `CALIBRATION-REPORT-${fixture}.md`),
  };
}

const DEFAULTS = resolvePaths(FIXTURE);

const HELP = `Usage: node scripts/run-calibration.js <generate|check> [OPTIONS]

Reproducible calibration test for the eval pipeline, built on the committed
fixtures/ directory (mutant-brief-writer = 4 known injected defects;
golden-target = benign concrete target). This script makes NO Codex calls and
spends NO API credits — the live steps are separate and human-invoked.

Full human workflow (see fixtures/GATE-RUNBOOK.md for the copy-paste version):

  1. node scripts/run-calibration.js generate
       Writes evals/fixtures/mutant-brief-writer/evals.json (9 scenarios naming
       the golden target) and reports the description-echo lint result.

  2. Run the NATIVE EVAL on the mutant via skill-eval-agent, with explicit
       paths (never copy the mutant into skills/):
       definition:  fixtures/mutant-brief-writer/SKILL.md
       evals.json:  evals/fixtures/mutant-brief-writer/evals.json
       artifacts:   evals/fixtures/mutant-brief-writer/iteration-<N>/ (a new iteration)
       report out:  fixtures/mutant-brief-writer/SKILL-EVAL.md (gitignored)

  3. HUMAN-INVOKED, spends API credits:
       node scripts/codex/run-native-audit.js mutant-brief-writer skill \\
         --def-path fixtures/mutant-brief-writer/SKILL.md \\
         --evals-path evals/fixtures/mutant-brief-writer/evals.json \\
         --live

  4. node scripts/run-calibration.js check
       Diffs both reports against fixtures/mutant-brief-writer/expected-findings.json
       and writes evals/fixtures/CALIBRATION-REPORT.md.

  Pass condition: 4/4 defect classes caught across the native + audit layers,
  each with an evidence quote.

Steps:
  generate                  Generate mutant scenarios + run the echo lint (dry-run-safe)
  check                     Diff native reports against expected-findings.json

Options (check):
  --eval-report <path>      Native SKILL-EVAL.md location
                            (default: ${DEFAULTS.evalReport})
  --audit-report <path>     NATIVE-AUDIT-REPORT.md location
                            (default: newest run under ${DEFAULTS.auditRunsDir}/)
  --expected <path>         Ground-truth expected-findings.json location
                            (default: ${DEFAULTS.expectedFindings})

Options (both):
  --fixture <name>          Calibration fixture under fixtures/ to run against
                            (default: mutant-brief-writer; also committed:
                            mutant-notes-summarizer). All fixture paths and the
                            per-fixture CALIBRATION-REPORT-<name>.md derive from this.
  --help                    Show this help

Exit codes:
  generate: 0 = scenarios written (lint result reported either way, including a
            deliberate-vague-description lint flag, which is signal, not error);
            1 = orchestration error (generator missing, unexpected failure).
  check:    0 = 4/4 defects caught; 1 = any defect missed or inputs missing.
`;

if (args.includes('--help') || args.includes('-h') || args.length === 0) {
  console.log(HELP);
  process.exit(args.length === 0 ? 1 : 0);
}

const step = args[0];

function fail(msg) {
  console.error(`Error: ${msg}`);
  process.exit(1);
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function readFrontmatterName(defPath) {
  const content = fs.readFileSync(defPath, 'utf8');
  const m = content.match(/^name:\s*(.+)$/m);
  return m ? m[1].trim().replace(/^(["'])(.*)\1$/, '$2') : null;
}

function normalize(text) {
  return text
    .toLowerCase()
    .replace(/[`*"]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// ── Step: generate ────────────────────────────────────────────────────────────

function stepGenerate() {
  if (!fs.existsSync(DEFAULTS.mutantDef)) fail(`${DEFAULTS.mutantDef} not found.`);
  if (!fs.existsSync(DEFAULTS.generator)) fail(`${DEFAULTS.generator} not found.`);
  if (!fs.existsSync(DEFAULTS.goldenDef)) fail(`${DEFAULTS.goldenDef} not found.`);

  const goldenName = readFrontmatterName(DEFAULTS.goldenDef);
  if (!goldenName) fail(`could not read frontmatter name from ${DEFAULTS.goldenDef}`);
  console.log(`Golden target (concrete --target for prompts): ${goldenName} (${DEFAULTS.goldenDef})`);

  const genArgs = [DEFAULTS.generator, DEFAULTS.mutantDef, '--target', goldenName];
  if (fs.existsSync(DEFAULTS.contextFile)) {
    genArgs.push('--context', DEFAULTS.contextFile);
  } else {
    console.warn(`Warning: ${DEFAULTS.contextFile} not found — generating 6 scenarios instead of 9.`);
    console.warn('Run extract-project-context.js first for the full 9-scenario set (see CLAUDE.md).');
  }

  console.log(`\nRunning generator: node ${genArgs.join(' ')}\n`);
  const r = spawnSync('node', genArgs, { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 });
  // The generator prints its summary line + lint failures to stderr, JSON to stdout.
  if (r.stderr) process.stderr.write(r.stderr);

  // Generator convention: writes evals/<basename-of-skill-dir>/evals.json.
  const mutantName = path.basename(path.dirname(DEFAULTS.mutantDef));
  const generatorOutDir = path.join('evals', mutantName);
  const generatorOutPath = path.join(generatorOutDir, 'evals.json');
  const finalPath = path.join(DEFAULTS.evalsOutDir, 'evals.json');

  const lintAborted = r.status !== 0 && /Description-echo lint FAILED/i.test(r.stderr || '');

  if (r.status !== 0 && !lintAborted) {
    fail(`generator exited ${r.status} for a reason other than the echo lint — see output above.`);
  }

  if (lintAborted) {
    // Deliberate design: the mutant's description is intentionally vague, so the
    // echo lint flagging its scenarios is itself calibration signal — report it
    // loudly instead of hard-failing the orchestration (per Phase 3 brief).
    console.log('\n=== DISCRIMINATION SIGNAL (not an orchestration error) ===');
    console.log('The description-echo lint FLAGGED the mutant\'s generated prompts.');
    console.log('The mutant\'s trigger description is deliberately vague (defect: vague-trigger),');
    console.log('so lint pressure here is expected fixture behavior worth recording.');
    console.log('However, the generator aborted before writing evals.json — the gate cannot');
    console.log('proceed until prompts pass the lint (adjust generator templates, never the fixture).');
    process.exit(0);
  }

  if (!fs.existsSync(generatorOutPath)) {
    fail(`generator reported success but ${generatorOutPath} was not written.`);
  }

  // Relocate to the gitignored calibration tree (evals/fixtures/…). The generator's
  // default location (evals/<name>/) is NOT covered by evals/.gitignore for fixture
  // names, so nothing may be left behind there.
  fs.mkdirSync(DEFAULTS.evalsOutDir, { recursive: true });
  fs.copyFileSync(generatorOutPath, finalPath);
  fs.rmSync(generatorOutDir, { recursive: true });
  console.log(`Relocated evals.json: ${generatorOutPath} -> ${finalPath}`);

  // Echo lint, reported per-scenario (tolerated — a flag here is signal, not error).
  console.log('\nRunning description-echo lint (--lint-only):\n');
  const lint = spawnSync('node', [DEFAULTS.generator, '--lint-only', finalPath], { encoding: 'utf8' });
  process.stdout.write(lint.stdout || '');
  if (lint.stderr) process.stderr.write(lint.stderr);

  const data = JSON.parse(fs.readFileSync(finalPath, 'utf8'));
  const total = (data.evals || []).length;
  console.log('\n=== generate summary ===');
  console.log(`Scenarios written: ${total} -> ${finalPath}`);
  console.log(`Concrete target named in prompts: ${goldenName}`);
  if (lint.status === 0) {
    console.log('Echo lint: PASS — prompts are discriminating (no description echo).');
  } else {
    console.log('Echo lint: FLAGGED — see per-scenario ratios above. For this fixture that is');
    console.log('SIGNAL (deliberately vague description), recorded here rather than hard-failing.');
  }
  console.log('\nNext step (human): run the native eval on the mutant — see fixtures/GATE-RUNBOOK.md step 2.');
  process.exit(0);
}

// ── Step: check ───────────────────────────────────────────────────────────────

// Fallback keyword regexes per defect_class, applied to NORMALIZED text.
const CLASS_KEYWORDS = {
  vague_trigger_description: /vague|too broad|over-?broad|too generic|generic (trigger|description)|non-?discriminat|any (document|content|writing) task|best-case,? not (a )?floor/,
  internal_self_contradiction: /contradict|self-?contradiction|inconsisten|conflicting (instruction|guidance|step|rule)|(never ask|do not ask).{0,120}(interview|follow-?up)/,
  silently_dropped_step: /silently (skipp|dropp|omitt)|dropped step|skipped step|missing step|never (implement|execut|perform)|omitted (from|in) the detailed|interview.{0,120}(missing|absent|never|omitted|dropped|skipped)/,
  broken_output_filename_integration: /filename mismatch|file ?name.{0,60}(mismatch|inconsisten|does not match|doesn'?t match)|brief\.md.{0,200}project-brief\.md|project-brief\.md.{0,200}brief\.md|integration.{0,80}(break|broken|fail)/,
  over_narrow_trigger: /too narrow|over-?narrow|under-?trigger|(did not|didn'?t|failed to|never) trigger|only.{0,60}exact (phrase|wording)|trigger accuracy.{0,80}(below|fail|low)/,
  phantom_script_reference: /does not exist|doesn'?t exist|nonexistent|non-existent|no such (file|script)|missing script|phantom script|script.{0,80}(not found|cannot be found|is absent)/,
  multi_turn_redundancy: /re-?ask|re-?confirm|redundan|already (established|given|provided|confirmed|known)|asks? again for/,
  dead_step: /dead.?step|unreachable|never (applies|reached|executes|true|fire)|impossible (condition|guard)|can never (be true|execute|apply|run)|guarantees at least one/,
};

function anchorWindows(quote, size = 5) {
  const words = normalize(quote).split(' ').filter(Boolean);
  if (words.length <= size) return words.length ? [words.join(' ')] : [];
  const windows = [];
  for (let i = 0; i + size <= words.length; i++) windows.push(words.slice(i, i + size).join(' '));
  return windows;
}

function findAnchorHit(defect, normalizedReport) {
  const quotes = [defect.anchor_quote, defect.anchor_quote_contradicting, defect.anchor_quote_conflicting]
    .filter(Boolean);
  for (const q of quotes) {
    for (const w of anchorWindows(q)) {
      if (normalizedReport.includes(w)) return { quote: q, window: w };
    }
  }
  return null;
}

function findKeywordHit(defect, normalizedReport) {
  const re = CLASS_KEYWORDS[defect.defect_class];
  if (!re) return null;
  const m = normalizedReport.match(re);
  return m ? { match: m[0], index: m.index } : null;
}

function findChecklistFail(checkName, reportText) {
  // Matches render-native-audit-report.js checklist rows: "| <check> | fail | ... |"
  const re = new RegExp(`\\|\\s*${checkName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\|\\s*fail\\s*\\|`, 'i');
  return re.test(reportText);
}

function excerptAround(rawText, needle, radius = 160) {
  const idx = normalize(rawText).indexOf(needle);
  if (idx === -1) return needle;
  const norm = normalize(rawText);
  return norm.slice(Math.max(0, idx - radius), idx + needle.length + radius).trim();
}

function findLatestAuditReport(baseDir) {
  if (!fs.existsSync(baseDir)) return null;
  const runs = fs.readdirSync(baseDir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => e.name)
    .sort() // run-ids are ISO timestamps — lexicographic sort is chronological
    .reverse();
  for (const run of runs) {
    const p = path.join(baseDir, run, 'NATIVE-AUDIT-REPORT.md');
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function stepCheck() {
  const evalReportPath = flagValue('--eval-report') || DEFAULTS.evalReport;
  const auditReportPath = flagValue('--audit-report') || findLatestAuditReport(DEFAULTS.auditRunsDir);
  const expectedPath = flagValue('--expected') || DEFAULTS.expectedFindings;

  if (!fs.existsSync(expectedPath)) fail(`${expectedPath} not found.`);
  if (!fs.existsSync(evalReportPath)) {
    fail(`native eval report not found at ${evalReportPath}.\n` +
      'Run the native eval first (fixtures/GATE-RUNBOOK.md step 2), or pass --eval-report <path>.');
  }
  if (!auditReportPath || !fs.existsSync(auditReportPath)) {
    fail(`no NATIVE-AUDIT-REPORT.md found under ${DEFAULTS.auditRunsDir}/.\n` +
      'Run the native audit first (fixtures/GATE-RUNBOOK.md step 3), or pass --audit-report <path>.');
  }

  const manifest = JSON.parse(fs.readFileSync(expectedPath, 'utf8'));
  const evalReportRaw = fs.readFileSync(evalReportPath, 'utf8');
  const auditReportRaw = fs.readFileSync(auditReportPath, 'utf8');
  const docs = {
    native_metric: { label: `native eval report (${evalReportPath})`, raw: evalReportRaw, norm: normalize(evalReportRaw) },
    native_audit: { label: `native audit report (${auditReportPath})`, raw: auditReportRaw, norm: normalize(auditReportRaw) },
  };

  const rows = [];
  let caughtCount = 0;

  for (const defect of manifest.defects) {
    const [layer, catcherDetail] = defect.expected_catcher.split(':');
    const primary = docs[layer];
    const secondary = layer === 'native_metric' ? docs.native_audit : docs.native_metric;
    if (!primary) fail(`unknown expected_catcher layer "${layer}" for defect ${defect.id}`);

    const anchorHit = findAnchorHit(defect, primary.norm);
    const keywordHit = anchorHit ? null : findKeywordHit(defect, primary.norm);
    const checklistHit = (!anchorHit && !keywordHit && layer === 'native_audit')
      ? findChecklistFail(catcherDetail, primary.raw)
      : false;

    const caught = !!(anchorHit || keywordHit || checklistHit);
    if (caught) caughtCount++;

    let evidence = '—';
    let mechanism = 'none';
    if (anchorHit) {
      mechanism = 'anchor-quote';
      evidence = excerptAround(primary.raw, anchorHit.window);
    } else if (keywordHit) {
      mechanism = 'keyword';
      evidence = excerptAround(primary.raw, keywordHit.match);
    } else if (checklistHit) {
      mechanism = 'checklist-fail';
      evidence = `checklist row "${catcherDetail}" marked fail`;
    }

    const secondaryAnchor = findAnchorHit(defect, secondary.norm);
    const secondaryKeyword = secondaryAnchor ? null : findKeywordHit(defect, secondary.norm);
    const alsoMentioned = !!(secondaryAnchor || secondaryKeyword);

    rows.push({
      defect,
      layer,
      catcherDetail,
      caught,
      mechanism,
      evidence,
      alsoMentioned,
      primaryLabel: primary.label,
      secondaryLabel: secondary.label,
    });
  }

  const total = manifest.defects.length;
  const verdict = caughtCount === total ? 'PASS' : 'FAIL';

  const lines = [
    '# CALIBRATION-REPORT',
    '',
    `**Fixture:** ${manifest.fixture}  `,
    `**Generated:** ${new Date().toISOString()}  `,
    `**Native eval report:** \`${evalReportPath}\`  `,
    `**Native audit report:** \`${auditReportPath}\`  `,
    `**Ground truth:** \`${expectedPath}\`  `,
    '',
    `## Verdict: ${verdict} — ${caughtCount}/${total} defect classes caught`,
    '',
    verdict === 'PASS'
      ? 'All injected defects were caught by their expected layer. The Phase 3 gate pass condition is met.'
      : 'One or more injected defects were MISSED by their expected layer. The gate does not pass — iterate on the catching layer (e.g. run-native-audit.js buildPrompt()), never on the fixture.',
    '',
    '## Per-defect results',
    '',
    '| Defect | Class | Expected catcher | Phase 8 native result | Result | Mechanism | Also in other layer? |',
    '|--------|-------|------------------|----------------------|--------|-----------|----------------------|',
    ...rows.map(r =>
      `| ${r.defect.id} | ${r.defect.defect_class} | ${r.defect.expected_catcher} | ${r.defect.phase8_native_result || '—'} | ${r.caught ? 'CAUGHT' : '**MISSED**'} | ${r.mechanism} | ${r.alsoMentioned ? 'yes' : 'no'} |`
    ),
    '',
    '## Evidence',
    '',
    ...rows.flatMap(r => [
      `### ${r.defect.id} — ${r.caught ? 'CAUGHT' : 'MISSED'}`,
      '',
      `- Expected catcher: \`${r.defect.expected_catcher}\` (primary doc: ${r.primaryLabel})`,
      `- Injected anchor: "${r.defect.anchor_quote}"`,
      r.caught
        ? `- Detection (${r.mechanism}): "${r.evidence}"`
        : `- No anchor-quote window, class keyword, or failing checklist row found in the primary document.`,
      r.alsoMentioned ? `- Also mentioned in the secondary layer (${r.secondaryLabel}).` : '',
      '',
    ]).filter(l => l !== ''),
    '## Matching rules',
    '',
    'Detection = (a) any 5-word window of a normalized anchor quote found verbatim in the',
    'normalized primary report, else (b) defect-class keyword regex, else (c) for',
    'native_audit catchers, the named checklist item marked "fail" in the report table.',
    'Normalization: lowercase, strip backticks/asterisks/double quotes, collapse whitespace.',
    'Full rules: header of scripts/run-calibration.js.',
    '',
  ];

  fs.mkdirSync(path.dirname(DEFAULTS.calibrationReport), { recursive: true });
  fs.writeFileSync(DEFAULTS.calibrationReport, lines.join('\n'));

  console.log(`\nCalibration check: ${verdict} — ${caughtCount}/${total} defect classes caught.`);
  for (const r of rows) {
    console.log(`  [${r.caught ? 'CAUGHT' : 'MISSED'}] ${r.defect.id} (${r.defect.expected_catcher}) via ${r.mechanism}`);
  }
  console.log(`\nReport written: ${DEFAULTS.calibrationReport}`);
  process.exit(verdict === 'PASS' ? 0 : 1);
}

// ── Dispatch ──────────────────────────────────────────────────────────────────

if (step === 'generate') {
  stepGenerate();
} else if (step === 'check') {
  stepCheck();
} else {
  console.error(`Error: unknown step "${step}". Use generate, check, or --help.`);
  process.exit(1);
}
