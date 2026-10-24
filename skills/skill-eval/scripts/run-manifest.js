#!/usr/bin/env node
// run-manifest.js — idempotent resume tracking for skill-eval/agent-eval iterations.
// Fixes F4 (interrupted runs leaving empty baselines + mixed baseline methods with
// no resume story) by recording the baseline method ONCE per iteration and tracking
// per-scenario progress so a resumed run can pick up only the incomplete scenarios
// using the originally recorded baseline method — never re-deciding it mid-iteration.
//
// P0-11 also pins the evaluator (EVALUATOR_FILES below) so a refine loop cannot edit its own judge unnoticed.
//
// Subcommands:
//   init <iteration-dir> --baseline-method none|snapshot [--snapshot-path P] [--methodology-version N]
//        [--subject <definition-file>] [--commit <sha>] [--evaluator-ref <earlier run-manifest.json>]
//   mark <iteration-dir> <scenario-dir-name> <pending|dispatched|complete|graded>
//   status <iteration-dir>
//   evaluator
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const STATUSES = ['pending', 'dispatched', 'complete', 'graded'];
const REQUIRED_FILES = ['output.md', 'timing.json', 'evidence.json'];
const MANIFEST_NAME = 'run-manifest.json';

// P0-11: the evaluator's own files, pinned beside the subject. Labels are relative to the skills root (two
// levels above this script), so the pin works wherever the skills tree is installed: this repo's skills/, a
// target project's skills/, or ~/.claude/skills/. scripts/run-manifest.test.js fails if a label stops existing.
const SKILLS_ROOT = path.resolve(__dirname, '..', '..');
const EVALUATOR_FILES = [
  'skill-eval/scripts/harvest-evidence.js',
  'skill-eval/scripts/run-manifest.js',
  'skill-eval/scripts/generate-seed-evals.js',
  'agent-eval/scripts/generate-agent-evals.js',
  'skill-eval/REFERENCE.md',   // the grading rubric
];
const EXIT_EVALUATOR_REFUSED = 2;   // distinct from 1 (usage error, missing artifact, ungraded scenario)
const NO_RESUME = 'Do not resume this iteration: start a new iteration';

function usageAndExit(code) {
  console.error(`Usage:
  node run-manifest.js init <iteration-dir> --baseline-method none|snapshot [--snapshot-path P] [--methodology-version N]
                            [--subject <definition-file>] [--commit <sha>] [--evaluator-ref <run-manifest.json>]
  node run-manifest.js mark <iteration-dir> <scenario-dir-name> <${STATUSES.join('|')}>
  node run-manifest.js status <iteration-dir>
  node run-manifest.js evaluator

init:   Writes run-manifest.json at the iteration root. Refuses to re-init if one
        already exists (idempotent-safe) — resume by using mark/status instead.
        --subject pins the evaluated definition (SKILL.md / agent .md) by sha256,
        so a report states exactly which revision it measured; --commit adds the
        repo commit (git rev-parse --short HEAD). Both optional.
        --baseline-method snapshot is kept for an earlier-version baseline; no eval
        flow uses it (E12): skill-eval and agent-eval record none. status treats a
        snapshot manifest as stale (see below); a future snapshot flow must revisit that.
        Always records the sha256 of the evaluator files (P0-11, listed by "evaluator")
        in an "evaluator" block, and refuses if any is missing or not a regular file.
        --evaluator-ref refuses unless that earlier manifest's evaluator record matches
        the files now (a refine passes its baseline iteration's manifest).
mark:   Updates (or creates) a scenario's status entry.
status: Prints a table, re-hashes the --subject and warns if it changed since init
        or is gone, and warns on a snapshot manifest. After either warning a failing
        status closes with "${NO_RESUME}";
        the exit code ignores the warnings. Exits non-zero if any complete/graded scenario is
        missing output.md, timing.json, or evidence.json in either side, or if
        any scenario has not reached "graded". This is the resume/integrity gate.
        Re-hashes the evaluator files and REFUSES the iteration when any changed, is
        missing, or the manifest has no evaluator record (made before P0-11), even if
        every scenario is graded: "${NO_RESUME}".
evaluator: Prints "<sha256>  <label>" for each pinned evaluator file (labels relative
        to the skills root); "MISSING  <label>" and exit 1 when one is absent.

Exit codes:
  0  success (status: every scenario graded, no missing artifacts, evaluator unchanged)
  1  usage or input error; status: missing artifacts or ungraded scenarios (resumable unless a WARNING says not)
  ${EXIT_EVALUATOR_REFUSED}  evaluator refusal: init (a listed file missing, or --evaluator-ref differs or has no
     record) or status (evaluator changed or not recorded). Never resumable.`);
  process.exit(code);
}

const args = process.argv.slice(2);
if (args.includes('--help') || args.includes('-h') || args.length === 0) {
  usageAndExit(args.length === 0 ? 1 : 0);
}

const [cmd, ...rest] = args;

function manifestPath(iterationDir) { return path.join(iterationDir, MANIFEST_NAME); }

function readManifest(iterationDir) {
  const p = manifestPath(iterationDir);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch (e) { console.error(`Error: could not parse ${p}: ${e.message}`); process.exit(1); }
}

function writeManifest(iterationDir, manifest) {
  fs.writeFileSync(manifestPath(iterationDir), JSON.stringify(manifest, null, 2));
}

function sha256File(p) { return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'); }

// label -> sha256 of each evaluator file now; null when it is missing or not a regular file.
function hashEvaluator() {
  const now = {};
  for (const label of EVALUATOR_FILES) {
    const p = path.join(SKILLS_ROOT, ...label.split('/'));
    let st = null;
    try { st = fs.statSync(p); } catch {}
    now[label] = st && st.isFile() ? sha256File(p) : null;
  }
  return now;
}

// A recorded evaluator block is a plain label -> sha256 object; anything else counts as not recorded.
function isEvaluatorRecord(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

// One line per evaluator file that differs between a recorded block and now (short hashes); [] when all match.
// A recorded label this script no longer lists also differs: the recording evaluator was another version.
function evaluatorDiffs(recorded, now) {
  const short = h => (typeof h === 'string' ? h.slice(0, 12) : 'none');
  const diffs = [];
  for (const label of EVALUATOR_FILES) {
    if (now[label] === null) diffs.push(`${label} is missing or not a regular file (recorded ${short(recorded[label])})`);
    else if (recorded[label] !== now[label]) diffs.push(`${label} sha256 now ${short(now[label])}, recorded ${short(recorded[label])}`);
  }
  for (const label of Object.keys(recorded)) {
    if (!EVALUATOR_FILES.includes(label)) diffs.push(`${label} is recorded but no longer part of the evaluator`);
  }
  return diffs;
}

// ── init ───────────────────────────────────────────────────────────────────────
if (cmd === 'init') {
  const VALUE_FLAGS = new Set(['--baseline-method', '--snapshot-path', '--methodology-version', '--subject', '--commit', '--evaluator-ref']);
  let iterationDir = null;
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (VALUE_FLAGS.has(a)) { i++; continue; }
    if (!a.startsWith('--')) iterationDir = a;
  }
  const baselineFlag = rest.indexOf('--baseline-method');
  const baselineMethod = baselineFlag !== -1 ? rest[baselineFlag + 1] : null;
  const snapshotFlag = rest.indexOf('--snapshot-path');
  const snapshotPath = snapshotFlag !== -1 ? rest[snapshotFlag + 1] : null;
  const versionFlag = rest.indexOf('--methodology-version');
  const methodologyVersion = versionFlag !== -1 ? parseInt(rest[versionFlag + 1], 10) : 2;
  // A present value flag must carry a value that is not itself a flag.
  function flagValue(flag) {
    const i = rest.indexOf(flag);
    if (i === -1) return null;
    const v = rest[i + 1];
    if (v === undefined || v.startsWith('--')) {
      console.error(`Error: ${flag} needs a value.`);
      process.exit(1);
    }
    return v;
  }
  const subjectPath = flagValue('--subject');
  const commit = flagValue('--commit');
  const evaluatorRef = flagValue('--evaluator-ref');

  if (!iterationDir) { console.error('Error: <iteration-dir> is required.'); usageAndExit(1); }
  if (baselineMethod !== 'none' && baselineMethod !== 'snapshot') {
    console.error('Error: --baseline-method must be "none" or "snapshot".');
    usageAndExit(1);
  }
  if (baselineMethod === 'snapshot' && !snapshotPath) {
    console.error('Error: --baseline-method snapshot requires --snapshot-path.');
    usageAndExit(1);
  }

  if (subjectPath && !fs.existsSync(subjectPath)) {
    console.error(`Error: --subject ${subjectPath} does not exist — refusing to record a revision for a missing definition.`);
    process.exit(1);
  }
  if (subjectPath && !fs.statSync(subjectPath).isFile()) {
    console.error(`Error: --subject ${subjectPath} is not a file — pass the definition file (SKILL.md or the agent .md).`);
    process.exit(1);
  }
  if (commit !== null && !subjectPath) {
    console.error('Error: --commit requires --subject (the commit is recorded as part of the subject revision).');
    process.exit(1);
  }
  if (commit !== null && !/^[0-9a-f]{7,40}$/.test(commit)) {
    console.error('Error: --commit must be a 7-40 character lowercase hex SHA.');
    process.exit(1);
  }

  // P0-11: pin the evaluator. Fail closed: a missing file would leave the judge unpinned.
  const evaluator = hashEvaluator();
  const absent = EVALUATOR_FILES.filter(label => evaluator[label] === null);
  if (absent.length) {
    console.error(`Error: evaluator file(s) missing or not a regular file under ${SKILLS_ROOT}: ${absent.join(', ')} — refusing to init an iteration whose evaluator cannot be pinned.`);
    process.exit(EXIT_EVALUATOR_REFUSED);
  }
  // --evaluator-ref: the evaluator must be the one an earlier iteration recorded (closes an edit between
  // iterations, which the next init would otherwise record as the new normal).
  if (evaluatorRef !== null) {
    let ref;
    try { ref = JSON.parse(fs.readFileSync(evaluatorRef, 'utf8')); }
    catch (e) {
      console.error(`Error: --evaluator-ref ${evaluatorRef} could not be read as a run manifest: ${e.message}`);
      process.exit(1);
    }
    if (!ref || !isEvaluatorRecord(ref.evaluator)) {
      console.error(`Error: --evaluator-ref ${evaluatorRef} has no evaluator record (made before P0-11?) — the evaluator cannot be compared. Refusing to init; stop and report, do not work around this.`);
      process.exit(EXIT_EVALUATOR_REFUSED);
    }
    const diffs = evaluatorDiffs(ref.evaluator, evaluator);
    if (diffs.length) {
      console.error(`Error: the evaluator differs from the one recorded in --evaluator-ref ${evaluatorRef}:`);
      for (const d of diffs) console.error(`  ${d}`);
      console.error('Refusing to init: scores from a different evaluator are not comparable. Stop and report; do not work around this.');
      process.exit(EXIT_EVALUATOR_REFUSED);
    }
  }

  if (fs.existsSync(manifestPath(iterationDir))) {
    console.error(`Error: ${manifestPath(iterationDir)} already exists — refusing to re-init.`);
    console.error('If resuming an interrupted run, use "mark"/"status" against the existing manifest instead — the recorded baseline_method must not be re-decided.');
    process.exit(1);
  }

  fs.mkdirSync(iterationDir, { recursive: true });
  const manifest = {
    methodology_version: methodologyVersion,
    baseline_method: baselineMethod,
    snapshot_path: snapshotPath || null,
    subject: subjectPath ? {
      path: subjectPath,
      sha256: sha256File(subjectPath),
      commit: commit || null,
    } : null,
    evaluator,
    evaluator_ref: evaluatorRef,
    started_at: new Date().toISOString(),
    scenario_status: {},
    timing: {},
  };
  writeManifest(iterationDir, manifest);
  console.log(`Initialized ${manifestPath(iterationDir)} (baseline_method=${baselineMethod}, methodology_version=${methodologyVersion}).`);
  process.exit(0);
}

// ── mark ───────────────────────────────────────────────────────────────────────
if (cmd === 'mark') {
  const [iterationDir, scenarioDirName, status] = rest;
  if (!iterationDir || !scenarioDirName || !status) {
    console.error('Error: mark requires <iteration-dir> <scenario-dir-name> <status>.');
    usageAndExit(1);
  }
  if (!STATUSES.includes(status)) {
    console.error(`Error: status must be one of: ${STATUSES.join(', ')}.`);
    process.exit(1);
  }
  const manifest = readManifest(iterationDir);
  if (!manifest) {
    console.error(`Error: no manifest found at ${manifestPath(iterationDir)} — run "init" first.`);
    process.exit(1);
  }
  manifest.scenario_status[scenarioDirName] = { status, updated_at: new Date().toISOString() };
  writeManifest(iterationDir, manifest);
  console.log(`Marked ${scenarioDirName} = ${status}`);
  process.exit(0);
}

// ── status ───────────────────────────────────────────────────────────────────────
if (cmd === 'status') {
  const [iterationDir] = rest;
  if (!iterationDir) { console.error('Error: status requires <iteration-dir>.'); usageAndExit(1); }
  const manifest = readManifest(iterationDir);
  if (!manifest) {
    console.error(`Error: no manifest found at ${manifestPath(iterationDir)}.`);
    process.exit(1);
  }

  const entries = Object.entries(manifest.scenario_status || {});
  console.log(`Run manifest: ${manifestPath(iterationDir)}`);
  console.log(`baseline_method=${manifest.baseline_method}  methodology_version=${manifest.methodology_version}  started_at=${manifest.started_at}`);
  // stale: this iteration must not be resumed, only replaced by a new one (E10, E12 review R1).
  let stale = false;
  if (manifest.baseline_method === 'snapshot') {
    stale = true;
    console.log('WARNING: this manifest records baseline_method=snapshot, which no eval flow uses since E12 (its snapshot was identical to the subject) — start a new iteration rather than resuming.');
  }
  if (manifest.subject) {
    console.log(`subject=${manifest.subject.path}  sha256=${manifest.subject.sha256.slice(0, 12)}  commit=${manifest.subject.commit || '-'}`);
    // Re-hash the subject (E10): a resume after an edit would measure a different text than init recorded.
    // A relative path resolves against the working directory, as it did at init. Warn only: the exit code
    // stays the artifacts-and-grading gate.
    let now = null;
    try { now = crypto.createHash('sha256').update(fs.readFileSync(manifest.subject.path)).digest('hex'); } catch {}
    if (now === null) {
      stale = true;
      console.log(`WARNING: the subject ${manifest.subject.path} is not found — this iteration's measured text cannot be checked; start a new iteration rather than resuming.`);
    } else if (now !== manifest.subject.sha256) {
      stale = true;
      console.log(`WARNING: the subject changed since init (sha256 now ${now.slice(0, 12)}, recorded ${manifest.subject.sha256.slice(0, 12)}) — resumed scenarios would measure a different text; start a new iteration rather than resuming.`);
    } else {
      console.log('subject unchanged since init');
    }
  } else {
    console.log('subject=not recorded');   // init ran without --subject: the report must say so (E9)
  }
  // P0-11: unlike the subject warnings, an evaluator change refuses the iteration and sets the exit code:
  // scores from another judge must not be merged with these, even when every scenario is graded.
  let evaluatorRefused = false;
  if (!isEvaluatorRecord(manifest.evaluator)) {
    evaluatorRefused = true;
    console.log('REFUSED: evaluator not recorded — this manifest was made before the evaluator pin (P0-11), so its judge cannot be checked.');
  } else {
    const diffs = evaluatorDiffs(manifest.evaluator, hashEvaluator());
    if (diffs.length) {
      evaluatorRefused = true;
      console.log('REFUSED: the evaluator changed since init:');
      for (const d of diffs) console.log(`  ${d}`);
    } else {
      console.log(`evaluator unchanged since init (${EVALUATOR_FILES.length} files)`);
    }
  }
  const refusedLine = `STATUS: REFUSED — the evaluator does not match this iteration's record (see above). ${NO_RESUME}.`;
  console.log('');

  if (entries.length === 0) {
    console.log('No scenarios recorded in manifest yet.');
    if (evaluatorRefused) { console.log(refusedLine); process.exit(EXIT_EVALUATOR_REFUSED); }
    process.exit(1);
  }

  let ok = true;
  console.log('Scenario'.padEnd(28) + 'Status'.padEnd(12) + 'Sides'.padEnd(8) + 'Notes');
  console.log('-'.repeat(90));

  for (const [name, entry] of entries.sort(([a], [b]) => a.localeCompare(b))) {
    const status = typeof entry === 'string' ? entry : entry.status;
    const scenarioPath = path.join(iterationDir, name);
    let sideDirs = [];
    if (fs.existsSync(scenarioPath)) {
      sideDirs = fs.readdirSync(scenarioPath, { withFileTypes: true })
        .filter(e => e.isDirectory() && /^with/.test(e.name))
        .map(e => e.name);
    }

    const missing = [];
    const isGraded = status === 'graded';
    if (['complete', 'graded'].includes(status)) {
      if (sideDirs.length < 2) missing.push(`expected 2 side dirs (with_*/without_*), found ${sideDirs.length}`);
      for (const side of sideDirs) {
        for (const f of REQUIRED_FILES) {
          if (!fs.existsSync(path.join(scenarioPath, side, f))) missing.push(`${side}/${f} missing`);
        }
      }
    }

    if (!isGraded || missing.length > 0) ok = false;

    let note;
    if (missing.length) note = missing.join('; ');
    else if (isGraded) note = 'OK';
    else note = `not graded yet (status=${status})`;

    console.log(name.padEnd(28) + status.padEnd(12) + String(sideDirs.length).padEnd(8) + note);
  }

  console.log('');
  if (evaluatorRefused) {
    console.log(refusedLine);
    process.exit(EXIT_EVALUATOR_REFUSED);
  }
  console.log(ok
    ? 'STATUS: OK — all scenarios graded, no missing artifacts.'
    : stale
      ? `STATUS: FAILED — see missing files / ungraded scenarios above. ${NO_RESUME} (see the WARNING above).`
      : 'STATUS: FAILED — see missing files / ungraded scenarios above. Resume by dispatching only the incomplete scenarios, using the recorded baseline_method.');
  process.exit(ok ? 0 : 1);
}

// ── evaluator ──────────────────────────────────────────────────────────────────
// Lists the pinned evaluator files with their sha256 now (shasum format), so tests and records read the list
// from the script itself rather than a copy that could drift.
if (cmd === 'evaluator') {
  const now = hashEvaluator();
  for (const label of EVALUATOR_FILES) console.log(`${now[label] || 'MISSING'}  ${label}`);
  process.exit(EVALUATOR_FILES.every(label => now[label] !== null) ? 0 : 1);
}

console.error(`Error: unknown subcommand "${cmd}".`);
usageAndExit(1);
