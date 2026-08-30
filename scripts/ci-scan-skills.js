#!/usr/bin/env node
// scripts/ci-scan-skills.js
//
// CI-only wrapper around skills/skill-audit/scripts/static-scan.js. Runs the (unmodified)
// scanner against every skill in skills/*/, then diffs the BLOCK-severity findings against
// the reviewed exemption list at .github/skill-scan-baseline.json.
//
//   - a BLOCK finding NOT in the baseline  -> FAIL (a genuinely new finding — the whole
//     point of this gate is that it can still catch a new child_process anywhere)
//   - a baseline entry that no longer fires -> FAIL as a STALE BASELINE (prune it)
//
// This script does not change static-scan.js's behavior or verdicts in any way — it only
// narrows what CI's own "static-scan-skills" job treats as a build failure, for the specific,
// human-reviewed entries in the baseline file. skill-audit's vetting of externally sourced
// skills uses static-scan.js directly and is completely unaffected.
//
// Usage: node scripts/ci-scan-skills.js [--skills-dir <dir>] [--baseline <file>]
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
const DEFAULT_SKILLS_DIR = path.join(REPO, 'skills');
const DEFAULT_BASELINE = path.join(REPO, '.github', 'skill-scan-baseline.json');
const STATIC_SCAN = path.join(REPO, 'skills', 'skill-audit', 'scripts', 'static-scan.js');

function parseArgs(argv) {
  const out = { skillsDir: DEFAULT_SKILLS_DIR, baselinePath: DEFAULT_BASELINE };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--skills-dir') out.skillsDir = argv[++i];
    else if (argv[i] === '--baseline') out.baselinePath = argv[++i];
  }
  return out;
}

// Loads the baseline file. Returns { entries: [...] }. Tolerates a missing file
// (treated as an empty baseline) so a first-run/misconfigured repo fails loudly
// via "new" findings rather than crashing.
function loadBaseline(baselinePath) {
  if (!fs.existsSync(baselinePath)) return { entries: [] };
  const raw = fs.readFileSync(baselinePath, 'utf8');
  const parsed = JSON.parse(raw);
  return { entries: Array.isArray(parsed.entries) ? parsed.entries : [] };
}

function keyOf(entry) {
  return [entry.skill, entry.file, entry.check].join(' ');
}

// Runs the (unmodified) static scanner against a single skill directory and returns
// its parsed JSON output. Never throws on a scanner BLOCK/FLAG exit code — those are
// expected control flow, not a script failure.
function scanSkillDir(skillDir) {
  const r = spawnSync('node', [STATIC_SCAN, skillDir], { encoding: 'utf8' });
  if (r.error) throw r.error;
  try {
    return JSON.parse(r.stdout);
  } catch {
    throw new Error(`static-scan.js produced non-JSON output for ${skillDir}:\n${r.stdout}\n${r.stderr}`);
  }
}

function listSkillDirs(skillsDir) {
  return fs.readdirSync(skillsDir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => e.name)
    .sort();
}

// Runs the scanner across every skill and returns a flat list of BLOCK-severity
// findings, each tagged with its owning skill: { skill, file, check, severity, detail }.
function collectBlockFindings(skillsDir) {
  const findings = [];
  for (const skill of listSkillDirs(skillsDir)) {
    const result = scanSkillDir(path.join(skillsDir, skill));
    for (const f of result.findings || []) {
      if (f.severity === 'BLOCK') findings.push({ skill, ...f });
    }
  }
  return findings;
}

// Pure diff: no filesystem/process access. Exported separately so it's directly
// unit-testable against synthetic data.
function diff(actualBlockFindings, baselineEntries) {
  const baselineByKey = new Map(baselineEntries.map(e => [keyOf(e), e]));
  const seen = new Set();

  const matched = [];
  const unmatched = [];

  for (const f of actualBlockFindings) {
    const k = keyOf(f);
    if (baselineByKey.has(k)) {
      matched.push(f);
      seen.add(k);
    } else {
      unmatched.push(f);
    }
  }

  const stale = baselineEntries.filter(e => !seen.has(keyOf(e)));

  return { matched, unmatched, stale };
}

function printSummary({ matched, unmatched, stale }) {
  console.log(`\nstatic-scan-skills baseline check`);
  console.log(`  matched (known, reviewed):  ${matched.length}`);
  for (const f of matched) console.log(`    OK      ${f.skill}: ${f.file} [${f.check}]`);

  console.log(`  unmatched (new findings):   ${unmatched.length}`);
  for (const f of unmatched) console.log(`    NEW     ${f.skill}: ${f.file} [${f.check}] — ${f.detail}`);

  console.log(`  stale (baseline no longer fires): ${stale.length}`);
  for (const e of stale) console.log(`    STALE   ${e.skill}: ${e.file} [${e.check}] — prune this entry from .github/skill-scan-baseline.json`);

  if (unmatched.length > 0) {
    console.log(`\nFAIL: ${unmatched.length} BLOCK finding(s) not covered by the reviewed baseline.`);
    console.log('If this is a genuine new risk, fix the underlying script.');
    console.log('If it is a reviewed false positive, add a human-reviewed entry to .github/skill-scan-baseline.json.');
  }
  if (stale.length > 0) {
    console.log(`\nFAIL: ${stale.length} stale baseline entr${stale.length === 1 ? 'y' : 'ies'} — the scanner no longer finds ${stale.length === 1 ? 'it' : 'them'}.`);
    console.log('Prune the stale entry from .github/skill-scan-baseline.json so the baseline stays reviewed, not accumulated.');
  }
  if (unmatched.length === 0 && stale.length === 0) {
    console.log('\nPASS: all BLOCK findings are accounted for by the reviewed baseline; no stale entries.');
  }
}

function main() {
  const { skillsDir, baselinePath } = parseArgs(process.argv.slice(2));
  const baseline = loadBaseline(baselinePath);
  const actual = collectBlockFindings(skillsDir);
  const result = diff(actual, baseline.entries);
  printSummary(result);
  process.exit(result.unmatched.length > 0 || result.stale.length > 0 ? 1 : 0);
}

module.exports = { loadBaseline, scanSkillDir, listSkillDirs, collectBlockFindings, diff, keyOf };

if (require.main === module) main();
