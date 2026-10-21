#!/usr/bin/env node
// run-manifest.js — idempotent resume tracking for skill-eval/agent-eval iterations.
// Fixes F4 (interrupted runs leaving empty baselines + mixed baseline methods with
// no resume story) by recording the baseline method ONCE per iteration and tracking
// per-scenario progress so a resumed run can pick up only the incomplete scenarios
// using the originally recorded baseline method — never re-deciding it mid-iteration.
//
// Subcommands:
//   init <iteration-dir> --baseline-method none|snapshot [--snapshot-path P] [--methodology-version N]
//        [--subject <definition-file>] [--commit <sha>]
//   mark <iteration-dir> <scenario-dir-name> <pending|dispatched|complete|graded>
//   status <iteration-dir>
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const STATUSES = ['pending', 'dispatched', 'complete', 'graded'];
const REQUIRED_FILES = ['output.md', 'timing.json', 'evidence.json'];
const MANIFEST_NAME = 'run-manifest.json';

function usageAndExit(code) {
  console.error(`Usage:
  node run-manifest.js init <iteration-dir> --baseline-method none|snapshot [--snapshot-path P] [--methodology-version N]
                            [--subject <definition-file>] [--commit <sha>]
  node run-manifest.js mark <iteration-dir> <scenario-dir-name> <${STATUSES.join('|')}>
  node run-manifest.js status <iteration-dir>

init:   Writes run-manifest.json at the iteration root. Refuses to re-init if one
        already exists (idempotent-safe) — resume by using mark/status instead.
        --subject pins the evaluated definition (SKILL.md / agent .md) by sha256,
        so a report states exactly which revision it measured; --commit adds the
        repo commit (git rev-parse --short HEAD). Both optional.
        --baseline-method snapshot is kept for an earlier-version baseline; no eval
        flow uses it (E12): skill-eval and agent-eval record none.
mark:   Updates (or creates) a scenario's status entry.
status: Prints a table, re-hashes the --subject and warns if it changed since init
        (the exit code ignores that), and exits non-zero if any complete/graded scenario is
        missing output.md, timing.json, or evidence.json in either side, or if
        any scenario has not reached "graded". This is the resume/integrity gate.`);
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

// ── init ───────────────────────────────────────────────────────────────────────
if (cmd === 'init') {
  const VALUE_FLAGS = new Set(['--baseline-method', '--snapshot-path', '--methodology-version', '--subject', '--commit']);
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
      sha256: crypto.createHash('sha256').update(fs.readFileSync(subjectPath)).digest('hex'),
      commit: commit || null,
    } : null,
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
  console.log('');

  if (entries.length === 0) {
    console.log('No scenarios recorded in manifest yet.');
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
  console.log(ok
    ? 'STATUS: OK — all scenarios graded, no missing artifacts.'
    : stale
      ? 'STATUS: FAILED — see missing files / ungraded scenarios above. Do not resume this iteration: start a new iteration (see the WARNING above).'
      : 'STATUS: FAILED — see missing files / ungraded scenarios above. Resume by dispatching only the incomplete scenarios, using the recorded baseline_method.');
  process.exit(ok ? 0 : 1);
}

console.error(`Error: unknown subcommand "${cmd}".`);
usageAndExit(1);
