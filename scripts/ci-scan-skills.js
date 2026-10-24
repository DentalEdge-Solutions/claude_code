#!/usr/bin/env node
// scripts/ci-scan-skills.js
//
// CI-only wrapper around skills/skill-audit/scripts/static-scan.js. Runs the scanner in two
// passes and diffs each pass's findings against the reviewed exemption list at
// .github/skill-scan-baseline.json:
//
//   - general:     every skill in skills/*/. Keeps every BLOCK finding, plus the conformance
//                  checks below at any severity.
//   - conformance: .claude/agents/*.md, packs/*/skills/, packs/*/tools/ and
//                  infra/hermes-agent/skills/. Keeps ONLY the conformance checks, at any severity.
//                  The general scan of these scopes is P1-06, not this pass.
//
// The conformance checks (P0-02) are unpinned-install (npx without an exact version, pip install
// without ==, @latest) and the existing curl-pipe-shell / wget-pipe-shell. They count at any
// severity because the scanner rates a command found only in markdown code a FLAG (owner's
// decision, 2026-10-15) so that a sourced skill's documented example is not refused outright. For
// this repo's own shipped definitions, a code block is the instruction Claude runs, so a FLAG
// there still fails the build.
//
// Every finding is keyed by its pass, its repo-relative path and its check. For each pass:
//   - a finding NOT in that pass's baseline entries  -> FAIL (a genuinely new finding)
//   - an entry of that pass that no longer fires     -> FAIL as a STALE BASELINE (prune it)
// A pass never matches, or makes stale, the other pass's entries.
//
// This script does not change static-scan.js's behavior or verdicts — it only narrows what
// CI treats as a build failure, for the specific human-reviewed entries in the baseline file.
// skill-audit's vetting of externally sourced skills uses static-scan.js directly.
//
// Each scan has a timeout, so a scanner that hangs (a ReDoS) fails the run instead of stalling it.
//
// Usage: node scripts/ci-scan-skills.js [--root <dir>] [--baseline <file>] [--timeout-ms <n>]
//   --root        the tree to scan (default: this repository)
//   --baseline    the baseline file (default: .github/skill-scan-baseline.json in this repository)
//   --timeout-ms  per-scan timeout (default: 120000)
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
const DEFAULT_BASELINE = path.join(REPO, '.github', 'skill-scan-baseline.json');
const STATIC_SCAN = path.join(REPO, 'skills', 'skill-audit', 'scripts', 'static-scan.js');
const DEFAULT_TIMEOUT_MS = 120000;

const PASSES = ['general', 'conformance'];
const CONFORMANCE_CHECKS = new Set(['unpinned-install', 'curl-pipe-shell', 'wget-pipe-shell']);

function parseArgs(argv) {
  const out = { root: REPO, baselinePath: DEFAULT_BASELINE, timeoutMs: DEFAULT_TIMEOUT_MS };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--root') out.root = path.resolve(argv[++i]);
    else if (argv[i] === '--baseline') out.baselinePath = argv[++i];
    else if (argv[i] === '--timeout-ms') out.timeoutMs = Number(argv[++i]);
    else throw new Error(`unknown argument: ${argv[i]}`);
  }
  if (!Number.isFinite(out.timeoutMs) || out.timeoutMs <= 0) throw new Error('--timeout-ms must be a positive number');
  return out;
}

// A baseline path is repo-relative, written with forward slashes, and never climbs out.
function isRepoRelative(p) {
  return typeof p === 'string' && p.length > 0 && !p.startsWith('/') && !p.includes('\\')
    && !/^[A-Za-z]:/.test(p) && !p.split('/').some(s => s === '..' || s === '.' || s === '');
}

// Loads the baseline file. Returns { entries: [...] }. A missing file is an empty baseline, so
// a first run fails loudly through "new" findings rather than crashing. An entry without a known
// pass, a repo-relative path and a check is an error: it could never match, and an old-format
// entry silently ignored would turn its finding into a failure nobody can explain.
function loadBaseline(baselinePath) {
  if (!fs.existsSync(baselinePath)) return { entries: [] };
  const parsed = JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
  const entries = Array.isArray(parsed.entries) ? parsed.entries : [];
  entries.forEach((e, i) => {
    const bad = !e || typeof e !== 'object' ? 'not an object'
      : !PASSES.includes(e.pass) ? `pass must be one of ${PASSES.join(', ')}`
      : !isRepoRelative(e.path) ? 'path must be repo-relative (forward slashes, no leading /, no . or ..)'
      : typeof e.check !== 'string' || !e.check ? 'check is missing'
      : '';
    if (bad) throw new Error(`invalid baseline entry #${i} in ${baselinePath}: ${bad} (${JSON.stringify(e)})`);
  });
  return { entries };
}

function keyOf(entry) {
  return JSON.stringify([entry.pass, entry.path, entry.check]);
}

// Runs the (unmodified) static scanner on a directory or a single file and returns its parsed JSON
// output. A BLOCK/FLAG exit code is expected control flow; a timeout, a crash or non-JSON output throws.
function scanTarget(target, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const r = spawnSync(process.execPath, [STATIC_SCAN, target],
    { encoding: 'utf8', timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 });
  if (r.error && r.error.code === 'ETIMEDOUT') throw new Error(`static-scan.js timed out after ${timeoutMs} ms on ${target}`);
  if (r.error) throw r.error;
  if (r.signal) throw new Error(`static-scan.js was killed by ${r.signal} on ${target}`);
  try {
    return JSON.parse(r.stdout);
  } catch {
    throw new Error(`static-scan.js produced non-JSON output for ${target}:\n${r.stdout}\n${r.stderr}`);
  }
}

const subdirs = dir => (fs.existsSync(dir)
  ? fs.readdirSync(dir, { withFileTypes: true }).filter(e => e.isDirectory()).map(e => e.name).sort()
  : []);
const toPosix = p => p.split(path.sep).join('/');

// The scan targets of a pass, as { target, base }: base is the directory a finding's file is
// relative to (the target itself for a directory, its parent for a single file).
function targetsOf(root, pass) {
  if (pass === 'general') {
    return subdirs(path.join(root, 'skills')).map(n => ({ target: path.join(root, 'skills', n), base: path.join(root, 'skills', n) }));
  }
  const out = [];
  const agents = path.join(root, '.claude', 'agents');
  if (fs.existsSync(agents)) {
    for (const e of fs.readdirSync(agents, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      if (e.name.endsWith('.md') && !e.isDirectory()) out.push({ target: path.join(agents, e.name), base: agents });
    }
  }
  for (const pack of subdirs(path.join(root, 'packs'))) {
    for (const sub of ['skills', 'tools']) {
      const dir = path.join(root, 'packs', pack, sub);
      if (fs.existsSync(dir)) out.push({ target: dir, base: dir });
    }
  }
  const hermes = path.join(root, 'infra', 'hermes-agent', 'skills');
  if (fs.existsSync(hermes)) out.push({ target: hermes, base: hermes });
  return out;
}

const keeps = (pass, f) => CONFORMANCE_CHECKS.has(f.check) || (pass === 'general' && f.severity === 'BLOCK');

// Runs one pass over a tree. Returns its findings as { pass, path, check, severity, detail }, the
// path repo-relative. With withTargets, returns { findings, targets } (targets repo-relative).
function collectFindings(root, pass, { timeoutMs = DEFAULT_TIMEOUT_MS, withTargets = false } = {}) {
  if (!PASSES.includes(pass)) throw new Error(`unknown pass: ${pass}`);
  const findings = [];
  const targets = targetsOf(root, pass);
  for (const { target, base } of targets) {
    const result = scanTarget(target, timeoutMs);
    for (const f of result.findings || []) {
      if (!keeps(pass, f)) continue;
      findings.push({ pass, path: toPosix(path.relative(root, path.join(base, f.file))), check: f.check, severity: f.severity, detail: f.detail });
    }
  }
  return withTargets ? { findings, targets: targets.map(t => toPosix(path.relative(root, t.target))) } : findings;
}

// Pure diff: no filesystem/process access. Exported separately so it's directly
// unit-testable against synthetic data.
function diff(actualFindings, baselineEntries) {
  const baselineKeys = new Set(baselineEntries.map(keyOf));
  const seen = new Set();
  const matched = [];
  const unmatched = [];
  for (const f of actualFindings) {
    const k = keyOf(f);
    if (baselineKeys.has(k)) { matched.push(f); seen.add(k); }
    else unmatched.push(f);
  }
  const stale = baselineEntries.filter(e => !seen.has(keyOf(e)));
  return { matched, unmatched, stale };
}

// One pass: its own findings against its own entries only.
function diffPass(pass, actualFindings, baselineEntries) {
  return diff(actualFindings.filter(f => f.pass === pass), baselineEntries.filter(e => e.pass === pass));
}

function printSummary(pass, { matched, unmatched, stale, targets }, log) {
  log(`\nstatic-scan-skills baseline check — ${pass} pass (${targets.length} target${targets.length === 1 ? '' : 's'})`);
  log(`  matched (known, reviewed):  ${matched.length}`);
  for (const f of matched) log(`    OK      ${f.path} [${f.check}]`);
  log(`  unmatched (new findings):   ${unmatched.length}`);
  for (const f of unmatched) log(`    NEW     ${f.path} [${f.check}, ${f.severity}] — ${f.detail}`);
  log(`  stale (baseline no longer fires): ${stale.length}`);
  for (const e of stale) log(`    STALE   ${e.path} [${e.check}] — prune this ${pass} entry from .github/skill-scan-baseline.json`);
}

// Runs both passes and prints the summary. Returns { exitCode, results } with results[pass] =
// { matched, unmatched, stale, targets }. Throws on a scanner timeout, crash or a bad baseline.
function run(argv, { log = console.log } = {}) {
  const { root, baselinePath, timeoutMs } = parseArgs(argv);
  const { entries } = loadBaseline(baselinePath);
  const results = {};
  for (const pass of PASSES) {
    const { findings, targets } = collectFindings(root, pass, { timeoutMs, withTargets: true });
    results[pass] = { ...diffPass(pass, findings, entries), targets };
    printSummary(pass, results[pass], log);
  }
  const unmatched = PASSES.reduce((n, p) => n + results[p].unmatched.length, 0);
  const stale = PASSES.reduce((n, p) => n + results[p].stale.length, 0);
  if (unmatched > 0) {
    log(`\nFAIL: ${unmatched} finding(s) not covered by the reviewed baseline.`);
    log('If this is a genuine new risk, fix it (pin the install, or fix the underlying script).');
    log('If it is a reviewed false positive, add a human-reviewed entry, with its pass and repo-relative path, to .github/skill-scan-baseline.json.');
  }
  if (stale > 0) {
    log(`\nFAIL: ${stale} stale baseline entr${stale === 1 ? 'y' : 'ies'} — the scanner no longer finds ${stale === 1 ? 'it' : 'them'}.`);
    log('Prune the stale entry from .github/skill-scan-baseline.json so the baseline stays reviewed, not accumulated.');
  }
  if (unmatched === 0 && stale === 0) log('\nPASS: every finding of both passes is accounted for by the reviewed baseline; no stale entries.');
  return { exitCode: unmatched > 0 || stale > 0 ? 1 : 0, results };
}

function main() {
  try {
    process.exitCode = run(process.argv.slice(2)).exitCode;
  } catch (e) {
    console.error(`ci-scan-skills: ${e.message}`);
    process.exitCode = 2;
  }
}

module.exports = {
  loadBaseline, scanTarget, collectFindings, targetsOf, diff, diffPass, keyOf, run,
  PASSES, CONFORMANCE_CHECKS,
};

if (require.main === module) main();
