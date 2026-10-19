#!/usr/bin/env node
// scripts/ci-static-fallback.js
//
// CI's static fallback for the security gate: when AgentShield is unavailable, scan the
// agent files and settings files under .claude/ with skills/skill-audit/scripts/static-scan.js.
//
//   - BLOCK                     -> FAIL
//   - FLAG                      -> printed for review, does not fail
//   - PASS                      -> printed
//   - anything else             -> ERROR, FAIL: the scanner crashed, printed no or non-JSON
//                                  output, gave an unknown verdict, or exited with a code that
//                                  disagrees with its verdict (static-scan.js exits 0/1/2 for
//                                  PASS/FLAG/BLOCK)
//
// Replaces the inline shell loop in .github/workflows/ci.yml, which printed a scanner crash
// as PASS (U7, PR #4 triage).
//
// Usage: node scripts/ci-static-fallback.js
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
const STATIC_SCAN = path.join(REPO, 'skills', 'skill-audit', 'scripts', 'static-scan.js');
const EXIT_FOR = { PASS: 0, FLAG: 1, BLOCK: 2 };
const SETTINGS_FILES = ['.claude/settings.json', '.claude/settings.local.json'];

// Pure: turns one scanner run ({ status, stdout, stderr, error, signal }) into
// { verdict: PASS | FLAG | BLOCK | ERROR, reason }.
function classify(r) {
  // The error line itself, not the "Node.js vN" line an uncaught exception ends with.
  const lines = (r.stderr || '').split('\n').map(l => l.trim()).filter(l => l && !/^Node\.js v/.test(l));
  const detail = lines.find(l => /^\w*Error\b/.test(l)) || lines.pop();
  const why = text => ({ verdict: 'ERROR', reason: detail ? `${text} — ${detail}` : text });
  if (r.error) return why(`could not run the scanner: ${r.error.message}`);
  if (r.status === null) return why(`scanner killed by ${r.signal || 'a signal'}`);
  let out;
  try { out = JSON.parse(r.stdout); } catch { return why(`scanner printed no JSON (exit ${r.status})`); }
  const verdict = out && out.verdict;
  if (typeof verdict !== 'string' || !Object.hasOwn(EXIT_FOR, verdict)) return why(`unknown verdict ${JSON.stringify(verdict)}`);
  if (EXIT_FOR[verdict] !== r.status) return why(`verdict ${verdict} with exit ${r.status}`);
  return { verdict, reason: '' };
}

// Agent files (sorted), then the settings files that exist; paths relative to repoDir.
function listTargets(repoDir) {
  const agentsDir = path.join(repoDir, '.claude', 'agents');
  const agents = fs.existsSync(agentsDir)
    ? fs.readdirSync(agentsDir).filter(f => f.endsWith('.md')).sort().map(f => `.claude/agents/${f}`)
    : [];
  return [...agents, ...SETTINGS_FILES.filter(f => fs.existsSync(path.join(repoDir, f)))];
}

function scanFile(file, scanner = STATIC_SCAN, cwd = REPO) {
  return classify(spawnSync(process.execPath, [scanner, file], { cwd, encoding: 'utf8' }));
}

// Scans every target, logs one line each, and returns true when the gate fails.
function runFallback(targets, { scanner = STATIC_SCAN, cwd = REPO, log = console.log } = {}) {
  let failed = false;
  for (const file of targets) {
    const { verdict, reason } = scanFile(file, scanner, cwd);
    if (verdict === 'PASS') log(`PASS:  ${file}`);
    else if (verdict === 'FLAG') log(`FLAG:  ${file} (review)`);
    else if (verdict === 'BLOCK') { log(`BLOCK: ${file}`); failed = true; }
    else { log(`ERROR: ${file} — ${reason}`); failed = true; }
  }
  log(failed ? 'Static fallback: FAILED' : 'Static fallback: PASSED');
  return failed;
}

// The process exit code CI reads: 1 when the gate fails, else 0.
function main(repoDir = REPO, opts = {}) {
  return runFallback(listTargets(repoDir), { cwd: repoDir, ...opts }) ? 1 : 0;
}

module.exports = { classify, listTargets, scanFile, runFallback, main };

if (require.main === module) process.exit(main());
