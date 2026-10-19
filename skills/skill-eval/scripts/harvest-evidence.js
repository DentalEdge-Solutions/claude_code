#!/usr/bin/env node
// harvest-evidence.js — derives evidence.json from a completed scenario's transcript(s)
// and workspace artifacts. This is the ONLY source of truth for skill_loaded/
// agent_dispatched and workflow-step scoring — a subagent's self-reported status
// headers (did_trigger, workflow_steps_executed) are formally dead as grading input
// (F2, F5, F8). They may remain in transcripts as narrative color only.
//
// Usage:
//   node harvest-evidence.js <scenario-dir> --type skill|agent
//   node harvest-evidence.js <iteration-dir> --type skill|agent --all
//
// A scenario dir looks like evals/<name>/iteration-N/s<id>-<type>-r<rep>/ (skills)
// or evals/agents/<name>/iteration-N/s<id>-<type>-r<rep>/ (agents). Writes
// evidence.json next to each with_skill|with_agent|without_skill|without_agent
// output.md found under the given scenario dir(s).
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function usageAndExit(code) {
  console.error(`Usage:
  node harvest-evidence.js <scenario-dir> --type skill|agent
  node harvest-evidence.js <iteration-dir> --type skill|agent --all

Writes evidence.json next to each output.md in with_skill/with_agent and
without_skill/without_agent subdirectories. Never trusts self-reported
did_trigger/workflow_steps_executed headers — all fields are derived from the
filesystem and transcript text.

Options:
  --type skill|agent   Required. Selects with_skill/without_skill vs
                        with_agent/without_agent side-directory names.
  --all                Treat the positional argument as an iteration root and
                        process every scenario dir found under it.`);
  process.exit(code);
}

// ── CLI args ─────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
if (args.includes('--help') || args.includes('-h') || args.length === 0) {
  usageAndExit(args.length === 0 ? 1 : 0);
}

const typeFlagIdx = args.indexOf('--type');
const targetType = typeFlagIdx !== -1 ? args[typeFlagIdx + 1] : null;
const allMode = args.includes('--all');

let dirArg = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--type') { i++; continue; }
  if (a === '--all' || a === '--help' || a === '-h') continue;
  if (!a.startsWith('--')) dirArg = a;
}

if (targetType !== 'skill' && targetType !== 'agent') {
  console.error('Error: --type must be "skill" or "agent".');
  usageAndExit(1);
}
if (!dirArg || !fs.existsSync(dirArg)) {
  console.error(`Error: directory "${dirArg}" not found.`);
  usageAndExit(1);
}

const WITH_NAME = targetType === 'skill' ? 'with_skill' : 'with_agent';
const WITHOUT_NAME = targetType === 'skill' ? 'without_skill' : 'without_agent';
const LOADED_KEY = targetType === 'skill' ? 'skill_loaded' : 'agent_dispatched';

function isScenarioDir(dirPath) {
  if (!fs.existsSync(dirPath) || !fs.statSync(dirPath).isDirectory()) return false;
  return fs.existsSync(path.join(dirPath, WITH_NAME)) || fs.existsSync(path.join(dirPath, WITHOUT_NAME));
}

// ── evals.json resolution ─────────────────────────────────────────────────────
// Scenario dir shape: <name-dir>/iteration-N/s<id>-<type>-r<rep>/ — evals.json is
// two levels up from the scenario dir (a sibling of the iteration-N directory).
const evalsCache = new Map();
function loadEvalsJson(scenarioDir) {
  const iterationDir = path.dirname(path.resolve(scenarioDir));
  const nameDir = path.dirname(iterationDir);
  const evalsPath = path.join(nameDir, 'evals.json');
  if (evalsCache.has(evalsPath)) return evalsCache.get(evalsPath);
  let data = null;
  if (fs.existsSync(evalsPath)) {
    try { data = JSON.parse(fs.readFileSync(evalsPath, 'utf8')); }
    catch (e) { console.error(`Warning: could not parse ${evalsPath}: ${e.message}`); }
  } else {
    console.error(`Warning: evals.json not found at ${evalsPath} (expected two levels above the scenario dir).`);
  }
  evalsCache.set(evalsPath, data);
  return data;
}

function parseScenarioId(dirName) {
  const m = dirName.match(/^s?(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function resolveScenarioEval(scenarioDir) {
  const dirName = path.basename(path.resolve(scenarioDir));
  const id = parseScenarioId(dirName);
  const evalsData = loadEvalsJson(scenarioDir);
  if (!evalsData || id === null) return null;
  return (evalsData.evals || []).find(e => e.id === id) || null;
}

// ── run-manifest.json resolution (mtime window) ───────────────────────────────
function loadManifestStartedAt(scenarioDir) {
  const iterationDir = path.dirname(path.resolve(scenarioDir));
  const manifestPath = path.join(iterationDir, 'run-manifest.json');
  if (!fs.existsSync(manifestPath)) return null;
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    if (!manifest.started_at) return null;
    const startedAt = new Date(manifest.started_at);
    // An unparseable started_at means the window is unknown (null), not that every file is outside it (E3).
    if (Number.isNaN(startedAt.getTime())) {
      console.error(`Warning: started_at ${JSON.stringify(manifest.started_at)} in ${manifestPath} is not a date — mtime checks skipped.`);
      return null;
    }
    return startedAt;
  } catch { return null; }
}

// ── Artifact evidence ──────────────────────────────────────────────────────────
// Some filesystems keep file times to 1–2 s, so a file written in the second started_at was set
// can carry an earlier mtime. Times within this margin before started_at count as in the run.
const WINDOW_SLACK_MS = 2000;
const changedInWindow = (stat, windowStart) => stat.mtime.getTime() >= windowStart.getTime() - WINDOW_SLACK_MS;

function sha256File(filePath) {
  const buf = fs.readFileSync(filePath);
  return crypto.createHash('sha256').update(buf).digest('hex');
}

// An artifact counts only when it resolves, links followed, to a file inside this side's own workspace.
// Otherwise a link to an existing file, a linked folder or a path that climbs out (../) would satisfy an
// artifact workflow step without the run writing anything (E1, PR #4 triage P2 findings).
function insideDir(resolved, dir) {
  try {
    const root = fs.realpathSync(dir);
    return fs.realpathSync(resolved).startsWith(root + path.sep);
  } catch { return false; }
}

function harvestArtifacts(artifactSpecs, workspaceDir, windowStart) {
  return artifactSpecs.map(spec => {
    const resolved = path.join(workspaceDir, spec.path);
    let exists = fs.existsSync(resolved) && fs.statSync(resolved).isFile();
    if (exists && !insideDir(resolved, workspaceDir)) {
      console.error(`Warning: artifact "${spec.path}" resolves outside the workspace (${workspaceDir}) — not counted.`);
      exists = false;
    }
    if (!exists) {
      return { path: spec.path, exists: false, size: null, sha256: null, mtime_in_window: windowStart ? false : null };
    }
    const stat = fs.statSync(resolved);
    const mtimeInWindow = windowStart ? changedInWindow(stat, windowStart) : null;
    return {
      path: spec.path,
      exists: true,
      size: stat.size,
      sha256: sha256File(resolved),
      mtime_in_window: mtimeInWindow,
    };
  });
}

// ── Transcript marker evidence ─────────────────────────────────────────────────
function harvestMarkers(markerSpecs, transcript) {
  return markerSpecs.map(spec => {
    let found = false;
    try { found = new RegExp(spec.pattern, 'i').test(transcript); }
    catch (e) { console.error(`Warning: invalid marker pattern "${spec.pattern}": ${e.message}`); }
    return { kind: spec.kind, pattern: spec.pattern, expect: spec.expect, found };
  });
}

// ── Claim extraction + verification ───────────────────────────────────────────
// Looks for "wrote/created/saved/generated ... `path`" phrasing (and gerund/past
// forms) within ~80 chars before a backtick-quoted, path-like token, and within the
// same sentence (E5): the window starts after the last . ! or ? (plus any closing quote
// or bracket) that is followed by whitespace and a capital letter, so "See `b.md`" after
// "produced `a.md`." is no claim. A list number at the start of a line ("1. Report `a.md`")
// is no sentence end, and "e.g. `x.md`", blank lines and headings start no sentence, so a
// list under one verb stays one window. Backticks are
// required for precision — prose mentions of a path without them are too noisy to
// reliably distinguish from ordinary narration.
const SENTENCE_END_RE = /(?<!(?:^|\n)[ \t]*\d{1,3})[.!?]["'`)\]]*\s+(?=\p{Lu})/gu;
const CLAIM_VERB_RE = /\b(wrote|writing|written|create[sd]?|creating|save[sd]?|saving|generate[sd]?|generating|produce[sd]?|producing)\b/i;

function extractClaims(transcript) {
  const claims = new Set();
  const backtickRe = /`([^`\n]+)`/g;
  let m;
  while ((m = backtickRe.exec(transcript))) {
    const token = m[1].trim();
    if (!token || token.includes(' ')) continue; // paths don't contain spaces
    if (!/[\/.]/.test(token)) continue;          // must look path-like
    const contextStart = Math.max(0, m.index - 80);
    let context = transcript.slice(contextStart, m.index);
    let sentenceStart = 0;
    for (const end of context.matchAll(SENTENCE_END_RE)) sentenceStart = end.index + end[0].length;
    context = context.slice(sentenceStart);
    if (CLAIM_VERB_RE.test(context)) claims.add(token);
  }
  return [...claims];
}

// A claim is verified when the path names something this side's run could have written.
// The path is read against the workspace, then the repo root (cwd), and must resolve, links
// followed, inside this side's own folder (its workspace, output.md, timing.json): not
// `../../etc/hosts`, not evals.json, not the other side's workspace (E2). When
// run-manifest.json gives a start time, the file must also have changed since then (E4: an
// untouched file is not "written"). Without a start time, existence is all it checks.
// So false means "not found as written in this side's folder", not necessarily fabricated.
function verifyClaim(claimedPath, workspaceDir, repoRoot, sideDir, windowStart) {
  for (const base of [workspaceDir, repoRoot]) {
    const resolved = path.resolve(base, claimedPath);
    if (!fs.existsSync(resolved) || !insideDir(resolved, sideDir)) continue;
    if (windowStart && !changedInWindow(fs.statSync(resolved), windowStart)) continue;
    return true;
  }
  return false;
}

// ── Workflow-step evidence ─────────────────────────────────────────────────────
function harvestWorkflowSteps(stepSpecs, artifactResults, transcript) {
  const artifactByPath = new Map(artifactResults.map(a => [a.path, a]));
  return stepSpecs.map(spec => {
    let satisfied = false;
    if (spec.check === 'artifact') {
      const a = artifactByPath.get(spec.ref);
      satisfied = !!(a && a.exists);
    } else if (spec.check === 'marker') {
      const escaped = spec.ref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      satisfied = new RegExp(escaped, 'i').test(transcript);
    }
    return { step: spec.step, check: spec.check, ref: spec.ref, satisfied };
  });
}

// ── Per-scenario harvest ───────────────────────────────────────────────────────
function harvestScenario(scenarioDir) {
  const evalEntry = resolveScenarioEval(scenarioDir);
  const evidence = (evalEntry && evalEntry.expected && evalEntry.expected.evidence)
    ? evalEntry.expected.evidence
    : { artifacts: [], transcript_markers: [], workflow_steps: [] };
  const windowStart = loadManifestStartedAt(scenarioDir);
  const repoRoot = process.cwd();

  const sides = [WITH_NAME, WITHOUT_NAME].filter(s => fs.existsSync(path.join(scenarioDir, s)));
  if (sides.length === 0) {
    console.error(`Warning: no ${WITH_NAME}/${WITHOUT_NAME} directories found in ${scenarioDir} — skipping.`);
    return { scenarioDir, processed: [] };
  }

  const processed = [];
  for (const side of sides) {
    const sideDir = path.join(scenarioDir, side);
    const outputPath = path.join(sideDir, 'output.md');
    if (!fs.existsSync(outputPath)) {
      console.error(`Warning: ${outputPath} not found — skipping ${side}.`);
      continue;
    }
    const transcript = fs.readFileSync(outputPath, 'utf8');
    const workspaceDir = path.join(sideDir, 'workspace');

    const artifactResults = harvestArtifacts(evidence.artifacts || [], workspaceDir, windowStart);
    const markerResults = harvestMarkers(evidence.transcript_markers || [], transcript);
    const claimPaths = extractClaims(transcript);
    const claims = claimPaths.map(p => ({
      claimed_path: p,
      claim_verified: verifyClaim(p, workspaceDir, repoRoot, sideDir, windowStart),
    }));

    // skill_loaded/agent_dispatched comes from the tool_call marker's actual regex
    // match against the transcript — never from a self-reported header.
    const toolCallMarker = markerResults.find(m => m.kind === 'tool_call');
    const loaded = toolCallMarker ? toolCallMarker.found : false;

    const workflowSteps = harvestWorkflowSteps(evidence.workflow_steps || [], artifactResults, transcript);
    const workflowExecuted = workflowSteps.length > 0 ? workflowSteps.every(s => s.satisfied) : null;

    const evidenceOut = {
      scenario_id: evalEntry ? evalEntry.id : null,
      scenario_type: evalEntry ? evalEntry.type : null,
      side,
      artifacts: artifactResults,
      transcript_markers: markerResults,
      claims,
      [LOADED_KEY]: loaded,
      workflow_executed: workflowExecuted,
      workflow_steps: workflowSteps,
      self_report_ignored: true,
    };

    const outPath = path.join(sideDir, 'evidence.json');
    fs.writeFileSync(outPath, JSON.stringify(evidenceOut, null, 2));
    processed.push(outPath);
  }
  return { scenarioDir, processed };
}

// ── Main ────────────────────────────────────────────────────────────────────────
const scenarioDirs = [];
if (allMode) {
  const entries = fs.readdirSync(dirArg, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => path.join(dirArg, e.name))
    .filter(isScenarioDir);
  if (entries.length === 0) {
    console.error(`Error: no scenario directories (containing ${WITH_NAME} or ${WITHOUT_NAME}) found under ${dirArg}.`);
    process.exit(1);
  }
  scenarioDirs.push(...entries);
} else {
  if (!isScenarioDir(dirArg)) {
    console.error(`Error: ${dirArg} does not look like a scenario dir (no ${WITH_NAME}/${WITHOUT_NAME} subdir found). Use --all to point at an iteration root instead.`);
    process.exit(1);
  }
  scenarioDirs.push(dirArg);
}

const results = scenarioDirs.map(harvestScenario);

let totalFiles = 0;
for (const r of results) {
  totalFiles += r.processed.length;
  for (const p of r.processed) console.log(`Wrote ${p}`);
}
console.error(`Harvested evidence for ${results.length} scenario dir(s), ${totalFiles} evidence.json file(s) written.`);
process.exit(0);
